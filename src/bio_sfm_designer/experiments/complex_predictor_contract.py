"""Contract validator for adding an independent complex predictor.

This is the CPU-side preflight before using `complex_cross_predictor.py`.
It checks that a second-predictor records JSONL is not accidentally another
Boltz file, has stable chain/target/source provenance, and can be compared
against the primary complex records with one reproducible command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import sys
from typing import Any, Dict, Iterable, List, Optional

from .complex_cross_predictor import (
    _DEFAULT_COPY_FRACTION_THRESHOLD,
    _DEFAULT_COPY_TOLERANCE,
    _DEFAULT_LABEL_THRESHOLD_TOLERANCE,
)
from .complex_records_qc import run_qc


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _failure(kind: str, message: str, *, field: Optional[str] = None) -> Dict[str, Any]:
    out = {"kind": kind, "message": message}
    if field:
        out["field"] = field
    return out


def _string_list(obj: Dict[str, Any], field: str, failures: List[Dict[str, Any]]) -> List[str]:
    value = obj.get(field)
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value):
        return list(value)
    failures.append(_failure("bad_field", f"{field} must be a non-empty string or list of strings", field=field))
    return []


def _nonempty_string(obj: Dict[str, Any], field: str, failures: List[Dict[str, Any]]) -> Optional[str]:
    value = obj.get(field)
    if isinstance(value, str) and value.strip():
        return value
    failures.append(_failure("bad_field", f"{field} must be a non-empty string", field=field))
    return None


def _float_field(obj: Dict[str, Any], field: str, default: float,
                 failures: List[Dict[str, Any]]) -> float:
    value = obj.get(field, default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        failures.append(_failure("bad_field", f"{field} must be a finite non-negative number", field=field))
        return default
    if not math.isfinite(out) or out < 0:
        failures.append(_failure("bad_field", f"{field} must be a finite non-negative number", field=field))
        return default
    return out


def _fraction_field(obj: Dict[str, Any], field: str, default: float,
                    failures: List[Dict[str, Any]]) -> float:
    out = _float_field(obj, field, default, failures)
    if not 0.0 <= out <= 1.0:
        failures.append(_failure("bad_field", f"{field} must be in [0, 1]", field=field))
        return default
    return out


def _positive_int_field(obj: Dict[str, Any], field: str, default: int,
                        failures: List[Dict[str, Any]]) -> int:
    value = obj.get(field, default)
    bad = False
    if isinstance(value, bool):
        bad = True
        out = default
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            bad = True
            out = default
        else:
            out = int(text)
    else:
        try:
            out = int(value)
        except (TypeError, ValueError):
            bad = True
            out = default
        else:
            if isinstance(value, float) and not value.is_integer():
                bad = True
    if bad or out < 1:
        failures.append(_failure("bad_field", f"{field} must be a positive integer", field=field))
        return default
    return out


def _bool_field(obj: Dict[str, Any], field: str, default: bool,
                failures: List[Dict[str, Any]]) -> bool:
    value = obj.get(field, default)
    if isinstance(value, bool):
        return value
    failures.append(_failure("bad_field", f"{field} must be a boolean", field=field))
    return default


def _quote_paths(paths: Iterable[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def _qc_command(records: List[str], predictor: Dict[str, Any], qc: Dict[str, Any]) -> str:
    parts = [
        "python -m bio_sfm_designer.experiments.complex_records_qc",
        "--records",
        _quote_paths(records),
    ]
    if qc.get("require_complex_target_id", True):
        parts.append("--require-complex-target-id")
    if qc.get("require_provenance", True):
        parts.append("--require-provenance")
    if qc.get("require_chain_ids", True):
        parts.append("--require-chain-ids")
    parts.extend(["--expect-predictor-id", shlex.quote(str(predictor["predictor_id"]))])
    parts.extend(["--expect-signal-source", shlex.quote(str(predictor["signal_source"]))])
    parts.extend(["--expect-label-source", shlex.quote(str(predictor["label_source"]))])
    for pred in predictor.get("forbid_predictor_ids", []):
        parts.extend(["--forbid-predictor-id", shlex.quote(str(pred))])
    return " ".join(parts)


def _cross_command(primary: List[str], secondary: List[str], cross: Dict[str, Any]) -> str:
    all_records = list(primary) + list(secondary)
    parts = [
        "python -m bio_sfm_designer.experiments.complex_cross_predictor",
        "--records",
        _quote_paths(all_records),
        "--min-overlap",
        shlex.quote(str(cross.get("min_overlap", 20))),
        "--min-label-agreement",
        shlex.quote(str(cross.get("min_label_agreement", 0.8))),
        "--copy-tolerance",
        shlex.quote(str(cross.get("copy_tolerance", _DEFAULT_COPY_TOLERANCE))),
        "--copy-fraction-threshold",
        shlex.quote(str(cross.get("copy_fraction_threshold", _DEFAULT_COPY_FRACTION_THRESHOLD))),
        "--label-threshold-tolerance",
        shlex.quote(str(cross.get("label_threshold_tolerance", _DEFAULT_LABEL_THRESHOLD_TOLERANCE))),
    ]
    if cross.get("require_disjoint_record_files", False):
        parts.append("--require-disjoint-record-files")
    out = cross.get("out")
    if isinstance(out, str) and out.strip():
        parts.extend(["--out", shlex.quote(out)])
    matches = cross.get("emit_matches")
    if isinstance(matches, str) and matches.strip():
        parts.extend(["--emit-matches", shlex.quote(matches)])
    return " ".join(parts)


def _validation_command(report: Dict[str, Any]) -> str:
    parts = [
        "python -m bio_sfm_designer.experiments.complex_predictor_contract",
        "--contract",
        shlex.quote(str(report.get("contract_input", report["contract"]))),
    ]
    if report.get("require_files"):
        parts.append("--require-files")
    if report.get("run_record_qc"):
        parts.append("--run-record-qc")
    return " ".join(parts)


def _failure_text(failure: Dict[str, Any]) -> str:
    kind = str(failure.get("kind", "failure"))
    field = failure.get("field")
    message = str(failure.get("message", "")).strip()
    labels = [kind]
    if field:
        labels.append(f"field={field}")
    if message:
        return f"{' '.join(labels)} -- {message}"
    return " ".join(labels)


def render_plan_text(report: Dict[str, Any]) -> str:
    lines = [
        "# M6c second-predictor contract plan",
        "# Run from the repo root after the second predictor JSONL is synced locally.",
        "set -euo pipefail",
        "",
        _validation_command(report),
    ]
    if report["ok"]:
        lines.extend([
            "",
            report["commands"]["secondary_qc"],
            report["commands"]["cross_predictor"],
            "",
        ])
    else:
        lines.extend([
            "",
            "# blockers",
        ])
        for failure in report["failures"]:
            lines.append(f"# - {_failure_text(failure)}")
        lines.extend([
            "",
            "# Downstream commands are commented until the contract validates.",
            f"# {report['commands']['secondary_qc']}",
            f"# {report['commands']['cross_predictor']}",
            "",
        ])
    return "\n".join(lines)


def _pending_record_artifacts(paths: List[str]) -> List[Dict[str, Any]]:
    pending = []
    for path in paths:
        if not os.path.exists(path):
            status = "missing"
        elif os.path.isfile(path) and os.path.getsize(path) == 0:
            status = "empty"
        else:
            continue
        pending.append({
            "path": path,
            "status": status,
            "absolute_path": os.path.abspath(path),
        })
    return pending


def _record_path_overlaps(primary_records: List[str],
                          secondary_records: List[str]) -> List[Dict[str, str]]:
    primary_by_abs = {
        os.path.abspath(os.path.normpath(path)): path
        for path in primary_records
    }
    overlaps = []
    seen = set()
    for path in secondary_records:
        norm = os.path.abspath(os.path.normpath(path))
        if norm in primary_by_abs and norm not in seen:
            overlaps.append({
                "primary_record": primary_by_abs[norm],
                "secondary_record": path,
                "absolute_path": norm,
            })
            seen.add(norm)
    return overlaps


def _safe_relative_paths(entries: Iterable[Dict[str, Any]]) -> tuple:
    paths = []
    skipped = []
    for entry in entries:
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        norm = os.path.normpath(path)
        if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
            skipped.append(path)
            continue
        paths.append((norm, entry))
    return paths, skipped


def _shell_path_with_root(var_name: str, rel_path: str) -> str:
    if rel_path in ("", "."):
        return f'"${{{var_name}%/}}"/'
    return f'"${{{var_name}%/}}"/{shlex.quote(rel_path)}'


def _shell_assignment(name: str, value: Optional[str], default_expr: str) -> str:
    if value is None:
        return f"{name}={default_expr}"
    return f"{name}={shlex.quote(str(value))}"


def _manifest_path_for(path: str) -> str:
    root, ext = os.path.splitext(path)
    if ext:
        return f"{root}.manifest.json"
    return f"{path}.manifest.json"


def _pending_paths_text(paths: List[str]) -> str:
    return "\n".join(paths) + ("\n" if paths else "")


def _sync_manifest(*, kind: str, paths: List[str],
                   sync_script: Optional[str] = None,
                   manifest_file: Optional[str] = None) -> Dict[str, Any]:
    text = _pending_paths_text(paths)
    return {
        "kind": kind,
        "sync_script": sync_script,
        "manifest_file": manifest_file,
        "n_paths": len(paths),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "paths": paths,
    }


def _sync_manifest_guard(manifest: Dict[str, Any], *, label: str) -> List[str]:
    manifest_file = manifest.get("manifest_file")
    if not manifest_file:
        return []
    return [
        "PYTHON_BIN=\"${BIO_SFM_PYTHON:-${ENV_PY:-python3}}\"",
        f"SYNC_PLAN_MANIFEST={shlex.quote(str(manifest_file))}",
        f"EXPECTED_SYNC_PLAN_COUNT={int(manifest.get('n_paths') or 0)}",
        f"EXPECTED_SYNC_PLAN_SHA256={shlex.quote(str(manifest.get('sha256') or ''))}",
        "\"$PYTHON_BIN\" - \"$SYNC_PLAN_MANIFEST\" \"$EXPECTED_SYNC_PLAN_COUNT\" "
        "\"$EXPECTED_SYNC_PLAN_SHA256\" <<'PY'",
        "import hashlib",
        "import json",
        "import pathlib",
        "import sys",
        "",
        "path = pathlib.Path(sys.argv[1])",
        "expected_count = int(sys.argv[2])",
        "expected_sha256 = sys.argv[3]",
        "payload = json.loads(path.read_text())",
        "paths = payload.get('paths')",
        "if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):",
        f"    raise SystemExit(f\"stale {label} sync manifest: {{path}} paths field is invalid\")",
        "text = '\\n'.join(paths) + ('\\n' if paths else '')",
        "actual_count = len(paths)",
        "actual_sha256 = hashlib.sha256(text.encode()).hexdigest()",
        "declared_sha256 = payload.get('sha256')",
        "if actual_count != expected_count or actual_sha256 != expected_sha256 or declared_sha256 != expected_sha256:",
        "    raise SystemExit(",
        f"        f\"stale {label} sync manifest: {{path}} \"",
        "        f\"count={actual_count} sha256={actual_sha256}\"",
        "    )",
        "PY",
        "",
    ]


def _contract_refresh_command(report: Dict[str, Any], *,
                              out: Optional[str] = None,
                              emit_plan: Optional[str] = None,
                              emit_sync_back_plan: Optional[str] = None,
                              sync_remote_root: Optional[str] = None,
                              sync_local_root: str = ".") -> str:
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.complex_predictor_contract",
        "--contract",
        str(report.get("contract_input", report["contract"])),
    ]
    if report.get("require_files"):
        parts.append("--require-files")
    if report.get("run_record_qc"):
        parts.append("--run-record-qc")
    if out:
        parts.extend(["--out", str(out)])
    if emit_plan:
        parts.extend(["--emit-plan", str(emit_plan)])
    if emit_sync_back_plan:
        parts.extend(["--emit-sync-back-plan", str(emit_sync_back_plan)])
        if sync_remote_root:
            parts.extend(["--sync-remote-root", str(sync_remote_root)])
        if sync_local_root != ".":
            parts.extend(["--sync-local-root", str(sync_local_root)])
    return shlex.join(parts)


def render_sync_back_plan(report: Dict[str, Any], *,
                          remote_root: Optional[str] = None,
                          local_root: str = ".",
                          out: Optional[str] = None,
                          emit_plan: Optional[str] = None,
                          sync_script: Optional[str] = None,
                          sync_manifest_path: Optional[str] = None) -> str:
    paths, skipped = _safe_relative_paths(report.get("pending_secondary_records") or [])
    path_values = [rel_path for rel_path, _ in paths]
    manifest = _sync_manifest(
        kind="second_predictor_sync_back",
        paths=path_values,
        sync_script=sync_script,
        manifest_file=sync_manifest_path,
    )
    lines = [
        "# M6c second-predictor records sync-back plan",
        "# Pull missing/empty secondary-predictor JSONL artifacts from Cayuga.",
        "set -euo pipefail",
        "",
        _shell_assignment(
            "REMOTE_ROOT",
            remote_root,
            "${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}",
        ),
        _shell_assignment("LOCAL_ROOT", local_root, "${LOCAL_BIO_SFM_ROOT:-.}"),
        "",
    ]
    lines.extend(_sync_manifest_guard(manifest, label="second-predictor"))
    if not paths:
        lines.extend([
            "# No safe relative pending secondary-predictor records were present in the contract report.",
            "",
        ])
    for rel_path, entry in paths:
        parent = os.path.dirname(rel_path) or "."
        status = entry.get("status", "pending")
        lines.append(f"# secondary_record status={status}")
        lines.append(f"mkdir -p {_shell_path_with_root('LOCAL_ROOT', parent)}")
        lines.append(
            "rsync -avP "
            f"{_shell_path_with_root('REMOTE_ROOT', rel_path)} "
            f"{_shell_path_with_root('LOCAL_ROOT', parent)}/"
        )
        lines.append(f"if ! test -s {_shell_path_with_root('LOCAL_ROOT', rel_path)}; then")
        lines.append(
            "  echo missing or empty secondary-predictor record after rsync: "
            f"{shlex.quote(rel_path)} >&2"
        )
        lines.append("  exit 1")
        lines.append("fi")
        lines.append("")
    if skipped:
        lines.append("# Skipped unsafe or absolute secondary-predictor paths; handle manually:")
        for path in skipped:
            lines.append(f"# - {path}")
        lines.append("")
    lines.extend([
        "# Refresh the contract report and command plan after sync-back.",
        _contract_refresh_command(report, out=out, emit_plan=emit_plan),
        "",
    ])
    if emit_plan:
        lines.extend([
            "# Run strict secondary QC and cross-predictor comparison if the refreshed plan validates.",
            f"bash {shlex.quote(emit_plan)}",
            "",
        ])
    return "\n".join(lines)


def validate_contract(path: str, *, require_files: bool = False,
                      run_record_qc: bool = False) -> Dict[str, Any]:
    contract = _load_json(path)
    failures: List[Dict[str, Any]] = []
    primary_records = _string_list(contract, "primary_records", failures)
    secondary_records = _string_list(contract, "secondary_records", failures)
    predictor = contract.get("secondary_predictor")
    if not isinstance(predictor, dict):
        failures.append(_failure("bad_field", "secondary_predictor must be an object",
                                 field="secondary_predictor"))
        predictor = {}
    predictor_id = _nonempty_string(predictor, "predictor_id", failures)
    signal_source = _nonempty_string(predictor, "signal_source", failures)
    label_source = _nonempty_string(predictor, "label_source", failures)
    forbidden = predictor.get("forbid_predictor_ids", ["boltz2_complex"])
    if not isinstance(forbidden, list) or not all(isinstance(x, str) and x.strip() for x in forbidden):
        failures.append(_failure("bad_field", "forbid_predictor_ids must be a list of strings",
                                 field="forbid_predictor_ids"))
        forbidden = []
    if predictor_id is not None and predictor_id in set(forbidden):
        failures.append(_failure(
            "forbidden_secondary_predictor_id",
            f"secondary predictor_id={predictor_id!r} is listed in forbid_predictor_ids",
            field="secondary_predictor.predictor_id",
        ))
    record_overlaps = _record_path_overlaps(primary_records, secondary_records)
    for overlap in record_overlaps:
        failures.append(_failure(
            "overlapping_primary_secondary_records",
            "primary_records and secondary_records must not point to the same JSONL: "
            f"{overlap['secondary_record']}",
            field="secondary_records",
        ))
    predictor_norm = {
        "predictor_id": predictor_id or "",
        "signal_source": signal_source or "",
        "label_source": label_source or "",
        "forbid_predictor_ids": list(forbidden),
    }
    qc = contract.get("qc")
    if not isinstance(qc, dict):
        qc = {}
    qc_norm = {
        "require_complex_target_id": bool(qc.get("require_complex_target_id", True)),
        "require_provenance": bool(qc.get("require_provenance", True)),
        "require_chain_ids": bool(qc.get("require_chain_ids", True)),
    }
    cross = contract.get("cross_predictor")
    if not isinstance(cross, dict):
        cross = {}
    copy_tolerance = _float_field(
        cross,
        "copy_tolerance",
        _DEFAULT_COPY_TOLERANCE,
        failures,
    )
    copy_fraction_threshold = _fraction_field(
        cross,
        "copy_fraction_threshold",
        _DEFAULT_COPY_FRACTION_THRESHOLD,
        failures,
    )
    label_threshold_tolerance = _float_field(
        cross,
        "label_threshold_tolerance",
        _DEFAULT_LABEL_THRESHOLD_TOLERANCE,
        failures,
    )
    min_overlap = _positive_int_field(cross, "min_overlap", 20, failures)
    min_label_agreement = _fraction_field(cross, "min_label_agreement", 0.8, failures)
    require_disjoint_record_files = _bool_field(
        cross,
        "require_disjoint_record_files",
        True,
        failures,
    )
    cross_norm = {
        "min_overlap": min_overlap,
        "min_label_agreement": min_label_agreement,
        "copy_tolerance": copy_tolerance,
        "copy_fraction_threshold": copy_fraction_threshold,
        "label_threshold_tolerance": label_threshold_tolerance,
        "require_disjoint_record_files": require_disjoint_record_files,
        "out": cross.get("out"),
        "emit_matches": cross.get("emit_matches"),
    }

    if require_files:
        for field, records in (("primary_records", primary_records), ("secondary_records", secondary_records)):
            for record_path in records:
                if not os.path.exists(record_path):
                    failures.append(_failure("missing_file", f"{field} path does not exist: {record_path}",
                                             field=field))
                elif os.path.isfile(record_path) and os.path.getsize(record_path) == 0:
                    failures.append(_failure("empty_file", f"{field} path is empty: {record_path}",
                                             field=field))

    secondary_qc = None
    if run_record_qc and not failures:
        secondary_qc = run_qc(
            secondary_records,
            require_complex_target_id=qc_norm["require_complex_target_id"],
            require_provenance=qc_norm["require_provenance"],
            require_chain_ids=qc_norm["require_chain_ids"],
            expect_predictor_id=predictor_norm["predictor_id"],
            expect_signal_source=predictor_norm["signal_source"],
            expect_label_source=predictor_norm["label_source"],
            forbid_predictor_ids=predictor_norm["forbid_predictor_ids"],
        )
        if not secondary_qc["ok"]:
            failures.append(_failure("secondary_records_qc_failed",
                                     f"secondary records QC failed with {secondary_qc['n_failures']} failure(s)"))

    commands = {
        "secondary_qc": _qc_command(secondary_records, predictor_norm, qc_norm),
        "cross_predictor": _cross_command(primary_records, secondary_records, cross_norm),
    }
    report = {
        "ok": not failures,
        "contract": os.path.abspath(path),
        "contract_input": path,
        "require_files": require_files,
        "run_record_qc": run_record_qc,
        "primary_records": primary_records,
        "secondary_records": secondary_records,
        "record_path_overlaps": record_overlaps,
        "pending_secondary_records": _pending_record_artifacts(secondary_records),
        "secondary_predictor": predictor_norm,
        "qc": qc_norm,
        "cross_predictor": cross_norm,
        "commands": commands,
        "secondary_records_qc": secondary_qc,
        "failures": failures,
    }
    report["plan_text"] = render_plan_text(report)
    return report


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="validate a second complex-predictor contract")
    ap.add_argument("--contract", required=True, help="second predictor contract JSON")
    ap.add_argument("--require-files", action="store_true",
                    help="require primary and secondary records files to exist")
    ap.add_argument("--run-record-qc", action="store_true",
                    help="run secondary-records QC with the expected predictor/source contract")
    ap.add_argument("--out", default=None, help="optional JSON report path")
    ap.add_argument("--emit-plan", default=None, help="optional shell plan path")
    ap.add_argument("--emit-sync-back-plan", default=None,
                    help="optional shell plan to rsync missing secondary-predictor records back from Cayuga")
    ap.add_argument("--sync-remote-root", default=None,
                    help="remote repo root for --emit-sync-back-plan; defaults to CAYUGA_BIO_SFM_ROOT in the script")
    ap.add_argument("--sync-local-root", default=".",
                    help="local repo root for --emit-sync-back-plan")
    args = ap.parse_args(argv)

    try:
        rep = validate_contract(args.contract, require_files=args.require_files,
                                run_record_qc=args.run_record_qc)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex predictor contract failed: {exc}", file=sys.stderr)
        sys.exit(2)
    rep["self_command"] = _contract_refresh_command(
        rep,
        out=args.out,
        emit_plan=args.emit_plan,
        emit_sync_back_plan=args.emit_sync_back_plan,
        sync_remote_root=args.sync_remote_root,
        sync_local_root=args.sync_local_root,
    )
    print(f"# complex predictor contract  ok={rep['ok']} predictor={rep['secondary_predictor']['predictor_id']}")
    if rep["failures"]:
        print("  failures:", json.dumps(rep["failures"], sort_keys=True))
    print("  secondary_qc:", rep["commands"]["secondary_qc"])
    print("  cross_predictor:", rep["commands"]["cross_predictor"])
    if args.out:
        with open(args.out, "w") as fh:
            obj = {k: v for k, v in rep.items() if k != "plan_text"}
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.emit_plan:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_plan)) or ".", exist_ok=True)
        with open(args.emit_plan, "w") as fh:
            fh.write(rep["plan_text"])
        print(f"wrote {args.emit_plan}")
    if args.emit_sync_back_plan:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_sync_back_plan)) or ".", exist_ok=True)
        sync_manifest_path = _manifest_path_for(args.emit_sync_back_plan)
        paths, _ = _safe_relative_paths(rep.get("pending_secondary_records") or [])
        manifest = _sync_manifest(
            kind="second_predictor_sync_back",
            paths=[rel_path for rel_path, _ in paths],
            sync_script=args.emit_sync_back_plan,
            manifest_file=sync_manifest_path,
        )
        with open(args.emit_sync_back_plan, "w") as fh:
            fh.write(render_sync_back_plan(
                rep,
                remote_root=args.sync_remote_root,
                local_root=args.sync_local_root,
                out=args.out,
                emit_plan=args.emit_plan,
                sync_script=args.emit_sync_back_plan,
                sync_manifest_path=sync_manifest_path,
            ))
        with open(sync_manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.emit_sync_back_plan}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
