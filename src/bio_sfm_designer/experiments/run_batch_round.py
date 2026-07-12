"""Run ONE batch DBTL round from synced HPC artifacts (docs/HPC.md).

Ties the three consume-side adapters into a single command: generate (candidates.jsonl) +
predict (records.jsonl, structure substrate) + screen (verdicts.jsonl) -> the controller routes
via the external calibrated trust gate, screens before synth, scores net = benefit - lambda*
assays, and writes campaign.jsonl + summary.json. This is the LOCAL half of an async HPC round;
the heavy stages produced the JSONL on external HPC (see hpc/). Candidate ids in --candidates
must be covered by --records (predict ran on those candidates) and --verdicts (screened).

Run:
  python -m bio_sfm_designer.experiments.run_batch_round \
    --candidates hpc_outputs/generate/candidates.jsonl \
    --records    hpc_outputs/predict/records.jsonl \
    --verdicts   hpc_outputs/screen/verdicts.jsonl \
    --target "thermostable variant of a benign reporter" --objective thermostability \
    --out results/round_0
"""

import argparse
import hashlib
import json
import math
import os
import shlex
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bio_sfm_trust import confidence_to_risk

from ..config import ObjectiveSpec
from ..generate import PrecomputedGenerator
from ..generate.precomputed import load_candidate_records
from ..loop.controller import DBTLController
from ..predict.structure import PrecomputedStructurePredictor
from ..predict.structure import load_structure_records
from ..safety import PrecomputedScreen, SafetyScreen
from ..trust import TrustGate
from .complex_records_qc import run_qc as run_complex_records_qc


_PREVALIDATION_CONTRACT_FIELDS = ("predictor_id", "signal_source", "label_source")
_PREVALIDATION_LABEL_THRESHOLD_TOLERANCE = 1e-9


def _record_id(row: Any, field: str, artifact: str, index: int,
               failures: List[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(row, dict):
        failures.append({"kind": "invalid_record", "artifact": artifact, "line": index,
                         "message": "JSONL row is not an object"})
        return None
    value = row.get(field)
    if value is None or str(value).strip() == "":
        failures.append({"kind": "missing_id", "artifact": artifact, "line": index,
                         "field": field, "message": f"missing {field}"})
        return None
    return str(value)


def _complex_target_id(row: Any, artifact: str, index: int,
                       failures: List[Dict[str, Any]], *,
                       required: bool = False) -> Optional[str]:
    value = None
    if isinstance(row, dict):
        value = row.get("complex_target_id")
        meta = row.get("meta")
        if (value is None or str(value).strip() == "") and isinstance(meta, dict):
            value = meta.get("complex_target_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if required:
        failures.append({"kind": "missing_complex_target_id", "artifact": artifact, "line": index,
                         "message": "missing complex_target_id for strict complex DBTL preflight"})
    return None


def _ids(rows: Iterable[Any], field: str, artifact: str,
         failures: List[Dict[str, Any]], *,
         use_complex_target_id: bool = False) -> Tuple[List[str], List[str]]:
    ids: List[str] = []
    duplicates: List[str] = []
    seen = set()
    for index, row in enumerate(rows, 1):
        item_id = _record_id(row, field, artifact, index, failures)
        if item_id is None:
            continue
        if use_complex_target_id:
            complex_id = _complex_target_id(row, artifact, index, failures, required=True)
            if complex_id is None:
                continue
            item_id = f"{complex_id}\t{item_id}"
        if item_id in seen:
            duplicates.append(item_id)
        seen.add(item_id)
        ids.append(item_id)
    return ids, duplicates


def _complex_ids_by_item_id(rows: Iterable[Any], field: str, artifact: str,
                            failures: List[Dict[str, Any]]) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        value = row.get(field)
        if value is None or str(value).strip() == "":
            continue
        complex_id = _complex_target_id(row, artifact, index, failures, required=True)
        if complex_id is None:
            continue
        out.setdefault(str(value), set()).add(complex_id)
    return out


def _identity_keys(rows: Iterable[Any], field: str, artifact: str,
                   failures: List[Dict[str, Any]], *,
                   require_complex_target_id: bool = False) -> set:
    keys = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        value = row.get(field)
        if value is None or str(value).strip() == "":
            continue
        complex_id = _complex_target_id(
            row,
            artifact,
            index,
            failures,
            required=require_complex_target_id,
        )
        keys.add((complex_id or "", str(value)))
    return keys


def _format_identity_key(key: Tuple[str, str]) -> str:
    complex_id, item_id = key
    return f"{complex_id}/{item_id}" if complex_id else item_id


def _load_verdict_records(path: str) -> List[dict]:
    out: List[dict] = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{line_no} verdict row is not a JSON object")
            out.append(rec)
    return out


def _coverage_failure(kind: str, ids: Iterable[str], message: str) -> Dict[str, Any]:
    values = sorted(set(ids))
    return {
        "kind": kind,
        "count": len(values),
        "ids": values[:20],
        "message": message,
    }


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _pending_jsonl_artifact(path: str, role: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        status = "missing"
        kind = "missing_batch_artifact"
    elif os.path.isfile(path) and os.path.getsize(path) == 0:
        status = "empty"
        kind = "empty_batch_artifact"
    else:
        return None
    return {
        "kind": kind,
        "artifact": role,
        "path": path,
        "absolute_path": os.path.abspath(path),
        "status": status,
        "message": f"{role} JSONL is {status}: {path}",
    }


def _preflight_artifact_presence(candidates_path: str, records_path: str, *,
                                 verdicts_path: Optional[str],
                                 prevalidate_records_paths: Iterable[str]) -> List[Dict[str, Any]]:
    pending: List[Dict[str, Any]] = []
    for role, path in (("candidates", candidates_path), ("records", records_path)):
        artifact = _pending_jsonl_artifact(path, role)
        if artifact is not None:
            pending.append(artifact)
    if verdicts_path:
        artifact = _pending_jsonl_artifact(verdicts_path, "verdicts")
        if artifact is not None:
            pending.append(artifact)
    for path in prevalidate_records_paths:
        artifact = _pending_jsonl_artifact(str(path), "prevalidate_records")
        if artifact is not None:
            pending.append(artifact)
    return pending


def _blocked_preflight_report(candidates_path: str, records_path: str, *,
                              verdicts_path: Optional[str],
                              require_verdict_coverage: bool,
                              strict_complex_records: bool,
                              prevalidate_records_paths: Iterable[str],
                              lam: float,
                              conformal_alpha: Optional[float],
                              conformal_delta: float,
                              pending_artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    prevalidation_paths = [str(path) for path in prevalidate_records_paths]
    prevalidation_requested = bool(prevalidation_paths) or conformal_alpha is not None
    return {
        "ok": False,
        "candidates": candidates_path,
        "records": records_path,
        "verdicts": verdicts_path,
        "n_candidates": 0,
        "n_records": 0,
        "n_verdicts": 0 if verdicts_path else None,
        "require_verdict_coverage": require_verdict_coverage,
        "strict_complex_records": strict_complex_records,
        "complex_target_identity_checked": strict_complex_records,
        "complex_records_qc": None,
        "gate_prevalidation": {
            "requested": prevalidation_requested,
            "ok": not any(a["artifact"] == "prevalidate_records" for a in pending_artifacts),
            "paths": prevalidation_paths,
            "n_records": 0,
            "regimes": {},
            "conformal_alpha": conformal_alpha,
            "conformal_delta": conformal_delta,
            "batch_contract": {
                "checked": False,
                "ok": None,
                "tolerance": _PREVALIDATION_LABEL_THRESHOLD_TOLERANCE,
            },
            "failures": [a for a in pending_artifacts if a["artifact"] == "prevalidate_records"],
        },
        "pending_artifacts": pending_artifacts,
        "failures": pending_artifacts,
    }


def _safe_relative_pending_artifacts(preflight: Dict[str, Any]) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[str]]:
    paths: List[Tuple[str, Dict[str, Any]]] = []
    skipped: List[str] = []
    for artifact in preflight.get("pending_artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        norm = os.path.normpath(path)
        if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
            skipped.append(path)
            continue
        paths.append((norm, artifact))
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


def _nonempty_contract_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _finite_contract_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _regime_of(row: Any) -> Optional[str]:
    if not isinstance(row, dict):
        return None
    value = row.get("regime")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _records_by_regime(rows: Iterable[Any]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for row in rows:
        regime = _regime_of(row)
        if regime is not None and isinstance(row, dict):
            out.setdefault(regime, []).append(row)
    return out


def _string_field_summary(rows: List[dict], field: str) -> Dict[str, Any]:
    values = []
    missing = 0
    for row in rows:
        value = _nonempty_contract_string(row.get(field))
        if value is None:
            missing += 1
        else:
            values.append(value)
    return {
        "values": sorted(set(values)),
        "missing": missing,
        "complete": missing == 0,
    }


def _unique_floats(values: Iterable[float], tolerance: float) -> List[float]:
    unique: List[float] = []
    for value in sorted(values):
        if not any(abs(value - seen) <= tolerance for seen in unique):
            unique.append(value)
    return unique


def _float_sets_agree(left: List[float], right: List[float], tolerance: float) -> bool:
    unmatched = list(right)
    for value in left:
        match_index = next(
            (index for index, other in enumerate(unmatched) if abs(value - other) <= tolerance),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return not unmatched


def _threshold_field_summary(rows: List[dict], tolerance: float) -> Dict[str, Any]:
    values = []
    missing = 0
    for row in rows:
        value = _finite_contract_float(row.get("lrmsd_threshold"))
        if value is None:
            missing += 1
        else:
            values.append(value)
    return {
        "values": _unique_floats(values, tolerance),
        "missing": missing,
        "complete": missing == 0,
    }


def _single_value_field_agrees(prevalidation: Dict[str, Any], batch: Dict[str, Any]) -> bool:
    return (
        prevalidation["complete"]
        and batch["complete"]
        and len(prevalidation["values"]) == 1
        and prevalidation["values"] == batch["values"]
    )


def _single_threshold_agrees(prevalidation: Dict[str, Any], batch: Dict[str, Any],
                             tolerance: float) -> bool:
    return (
        prevalidation["complete"]
        and batch["complete"]
        and len(prevalidation["values"]) == 1
        and len(batch["values"]) == 1
        and _float_sets_agree(prevalidation["values"], batch["values"], tolerance)
    )


def _prevalidation_batch_contract_audit(prevalidation_records: Iterable[Any],
                                        batch_records: Iterable[Any], *,
                                        label_threshold_tolerance: float = _PREVALIDATION_LABEL_THRESHOLD_TOLERANCE) -> Dict[str, Any]:
    pre_by_regime = _records_by_regime(prevalidation_records)
    batch_by_regime = _records_by_regime(batch_records)
    failures: List[Dict[str, Any]] = []
    regimes: Dict[str, Any] = {}
    for regime in sorted(batch_by_regime):
        pre_rows = pre_by_regime.get(regime, [])
        batch_rows = batch_by_regime[regime]
        regime_report: Dict[str, Any] = {
            "ok": True,
            "n_prevalidation": len(pre_rows),
            "n_batch": len(batch_rows),
            "fields": {},
        }
        if not pre_rows:
            failure = {
                "kind": "prevalidation_missing_batch_regime",
                "regime": regime,
                "n_batch": len(batch_rows),
                "message": "prevalidation records must cover every batch regime before calibrated routing",
            }
            failures.append(failure)
            regime_report["ok"] = False
            regime_report["failures"] = [failure]
            regimes[regime] = regime_report
            continue

        regime_failures: List[Dict[str, Any]] = []
        for field in _PREVALIDATION_CONTRACT_FIELDS:
            pre_summary = _string_field_summary(pre_rows, field)
            batch_summary = _string_field_summary(batch_rows, field)
            agrees = _single_value_field_agrees(pre_summary, batch_summary)
            field_report = {
                "prevalidation": pre_summary,
                "batch": batch_summary,
                "single_value_agree": agrees,
            }
            regime_report["fields"][field] = field_report
            if not agrees:
                regime_failures.append({
                    "kind": "prevalidation_batch_contract_field_mismatch",
                    "regime": regime,
                    "field": field,
                    "prevalidation_values": pre_summary["values"],
                    "batch_values": batch_summary["values"],
                    "prevalidation_missing": pre_summary["missing"],
                    "batch_missing": batch_summary["missing"],
                    "message": (
                        f"prevalidation and current batch must share one {field} value "
                        "before calibrated routing"
                    ),
                })

        pre_threshold = _threshold_field_summary(pre_rows, label_threshold_tolerance)
        batch_threshold = _threshold_field_summary(batch_rows, label_threshold_tolerance)
        threshold_agrees = _single_threshold_agrees(
            pre_threshold,
            batch_threshold,
            label_threshold_tolerance,
        )
        regime_report["fields"]["lrmsd_threshold"] = {
            "prevalidation": pre_threshold,
            "batch": batch_threshold,
            "single_value_agree": threshold_agrees,
            "tolerance": label_threshold_tolerance,
        }
        if not threshold_agrees:
            regime_failures.append({
                "kind": "prevalidation_batch_contract_field_mismatch",
                "regime": regime,
                "field": "lrmsd_threshold",
                "prevalidation_values": pre_threshold["values"],
                "batch_values": batch_threshold["values"],
                "prevalidation_missing": pre_threshold["missing"],
                "batch_missing": batch_threshold["missing"],
                "tolerance": label_threshold_tolerance,
                "message": (
                    "prevalidation and current batch must share one lrmsd_threshold "
                    "label definition before calibrated routing"
                ),
            })

        if regime_failures:
            failures.extend(regime_failures)
            regime_report["ok"] = False
            regime_report["failures"] = regime_failures
        regimes[regime] = regime_report

    return {
        "checked": True,
        "ok": not failures,
        "tolerance": label_threshold_tolerance,
        "fields": list(_PREVALIDATION_CONTRACT_FIELDS) + ["lrmsd_threshold"],
        "regimes": regimes,
        "failures": failures,
    }


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


def _batch_round_command_from_args(args, *, include_sync_back_plan: bool = True) -> str:
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.run_batch_round",
        "--candidates",
        str(args.candidates),
        "--records",
        str(args.records),
    ]
    if getattr(args, "verdicts", None):
        parts.extend(["--verdicts", str(args.verdicts)])
    parts.extend([
        "--target",
        str(args.target),
        "--objective",
        str(args.objective),
        "--lam",
        str(args.lam),
        "--assay-budget",
        str(args.assay_budget),
        "--out",
        str(args.out),
    ])
    if getattr(args, "preflight_out", None):
        parts.extend(["--preflight-out", str(args.preflight_out)])
    if getattr(args, "strict_complex_records", False):
        parts.append("--strict-complex-records")
    if getattr(args, "allow_missing_verdicts", False):
        parts.append("--allow-missing-verdicts")
    prevalidate_records = list(getattr(args, "prevalidate_records", []) or [])
    if prevalidate_records:
        parts.append("--prevalidate-records")
        parts.extend(str(path) for path in prevalidate_records)
    if getattr(args, "conformal_alpha", None) is not None:
        parts.extend(["--conformal-alpha", str(args.conformal_alpha)])
    parts.extend(["--conformal-delta", str(getattr(args, "conformal_delta", 0.1))])
    if getattr(args, "provider", None):
        parts.extend(["--provider", str(args.provider)])
    if include_sync_back_plan:
        if getattr(args, "emit_sync_back_plan", None):
            parts.extend(["--emit-sync-back-plan", str(args.emit_sync_back_plan)])
        sync_remote_root = getattr(args, "sync_remote_root", None)
        if sync_remote_root:
            parts.extend(["--sync-remote-root", str(sync_remote_root)])
        sync_local_root = getattr(args, "sync_local_root", ".")
        if sync_local_root != ".":
            parts.extend(["--sync-local-root", str(sync_local_root)])
    return shlex.join(parts)


def render_sync_back_plan(preflight: Dict[str, Any], *, args) -> str:
    paths, skipped = _safe_relative_pending_artifacts(preflight)
    path_values = [rel_path for rel_path, _ in paths]
    sync_script = getattr(args, "emit_sync_back_plan", None)
    manifest_path = _manifest_path_for(sync_script) if sync_script else None
    manifest = _sync_manifest(
        kind="w4_batch_sync_back",
        paths=path_values,
        sync_script=sync_script,
        manifest_file=manifest_path,
    )
    lines = [
        "# W4 batch DBTL sync-back plan",
        "# Pull missing/empty candidates, records, verdicts, or prevalidation JSONLs from external HPC.",
        "set -euo pipefail",
        "",
        _shell_assignment(
            "REMOTE_ROOT",
            getattr(args, "sync_remote_root", None),
            "${REMOTE_BIO_SFM_ROOT:?set REMOTE_BIO_SFM_ROOT, e.g. USER@<hpc-login-host>:/scratch/<user>/bio_sfm_designer}",
        ),
        _shell_assignment("LOCAL_ROOT", getattr(args, "sync_local_root", "."), "${LOCAL_BIO_SFM_ROOT:-.}"),
        "",
    ]
    lines.extend(_sync_manifest_guard(manifest, label="W4 batch"))
    if not paths:
        lines.extend([
            "# No safe relative pending batch artifacts were present in the preflight report.",
            "",
        ])
    for rel_path, artifact in paths:
        parent = os.path.dirname(rel_path) or "."
        role = artifact.get("artifact", "artifact")
        status = artifact.get("status", "pending")
        lines.append(f"# {role} status={status}")
        lines.append(f"mkdir -p {_shell_path_with_root('LOCAL_ROOT', parent)}")
        lines.append(
            "rsync -avP "
            f"{_shell_path_with_root('REMOTE_ROOT', rel_path)} "
            f"{_shell_path_with_root('LOCAL_ROOT', parent)}/"
        )
        lines.append(f"if ! test -s {_shell_path_with_root('LOCAL_ROOT', rel_path)}; then")
        lines.append(
            "  echo missing or empty W4 batch artifact after rsync: "
            f"{shlex.quote(rel_path)} >&2"
        )
        lines.append("  exit 1")
        lines.append("fi")
        lines.append("")
    if skipped:
        lines.append("# Skipped unsafe or absolute pending paths; handle manually:")
        for path in skipped:
            lines.append(f"# - {path}")
        lines.append("")
    lines.extend([
        "# Rerun the W4 DBTL batch after sync-back.",
        _batch_round_command_from_args(args, include_sync_back_plan=False),
        "",
    ])
    return "\n".join(lines)


def _prevalidation_report_and_data(paths: Iterable[str],
                                   candidates: Iterable[Any], *,
                                   strict_complex_records: bool,
                                   lam: float,
                                   conformal_alpha: Optional[float],
                                   conformal_delta: float,
                                   batch_records: Optional[Iterable[Any]] = None,
                                   label_threshold_tolerance: float = _PREVALIDATION_LABEL_THRESHOLD_TOLERANCE) -> Tuple[Dict[str, Any], Dict[str, Tuple[List[float], List[int]]]]:
    paths = [str(path) for path in paths if str(path)]
    data: Dict[str, Tuple[List[float], List[int]]] = {}
    report: Dict[str, Any] = {
        "requested": bool(paths) or conformal_alpha is not None,
        "ok": True,
        "paths": paths,
        "n_records": 0,
        "regimes": {},
        "conformal_alpha": conformal_alpha,
        "conformal_delta": conformal_delta,
        "batch_contract": {
            "checked": False,
            "ok": None,
            "tolerance": label_threshold_tolerance,
        },
        "failures": [],
    }
    if not paths:
        if conformal_alpha is not None:
            report["ok"] = False
            report["failures"].append({
                "kind": "missing_prevalidation_records",
                "message": "conformal_alpha requires prior verified prevalidation records",
            })
        return report, data

    failures: List[Dict[str, Any]] = []
    records: List[dict] = []
    for path in paths:
        records.extend(load_structure_records(path))
    report["n_records"] = len(records)

    current_keys = _identity_keys(
        candidates,
        "id",
        "candidates",
        failures,
        require_complex_target_id=strict_complex_records,
    )
    prevalidation_keys = _identity_keys(
        records,
        "target_id",
        "prevalidate_records",
        failures,
        require_complex_target_id=strict_complex_records,
    )
    overlap = sorted(current_keys & prevalidation_keys)
    if overlap:
        failures.append({
            "kind": "prevalidation_overlaps_current_batch",
            "count": len(overlap),
            "ids": [_format_identity_key(key) for key in overlap[:20]],
            "message": "prevalidation records must be prior evidence, not current-batch hidden truth",
        })

    if strict_complex_records:
        complex_qc = run_complex_records_qc(
            paths,
            require_complex_target_id=True,
            require_provenance=True,
            require_chain_ids=True,
        )
        report["complex_records_qc"] = complex_qc
        if not complex_qc["ok"]:
            failures.append({
                "kind": "prevalidation_records_qc_failed",
                "count": complex_qc["n_failures"],
                "failures_by_kind": complex_qc["failures_by_kind"],
                "message": "strict QC failed for gate prevalidation records",
            })
        if batch_records is not None:
            batch_contract = _prevalidation_batch_contract_audit(
                records,
                batch_records,
                label_threshold_tolerance=label_threshold_tolerance,
            )
            report["batch_contract"] = batch_contract
            if not batch_contract["ok"]:
                failures.append({
                    "kind": "prevalidation_batch_contract_mismatch",
                    "failures": batch_contract["failures"],
                    "message": (
                        "prevalidation records and current batch records must use the same "
                        "predictor/source/label contract before W4 routing"
                    ),
                })

    for index, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            failures.append({
                "kind": "invalid_prevalidation_record",
                "line": index,
                "message": "prevalidation record is not a JSON object",
            })
            continue
        regime = rec.get("regime")
        if not isinstance(regime, str) or not regime.strip():
            failures.append({
                "kind": "missing_prevalidation_regime",
                "target_id": rec.get("target_id"),
                "message": "prevalidation record is missing regime",
            })
            continue
        truth = rec.get("truth")
        if not isinstance(truth, dict) or not isinstance(truth.get("correct"), bool):
            failures.append({
                "kind": "missing_prevalidation_truth",
                "target_id": rec.get("target_id"),
                "message": "prevalidation records must contain truth.correct from prior verified evidence",
            })
            continue
        try:
            raw_risk = confidence_to_risk(rec)
        except (TypeError, ValueError, KeyError) as exc:
            failures.append({
                "kind": "bad_prevalidation_risk",
                "target_id": rec.get("target_id"),
                "message": str(exc),
            })
            continue
        risks, wrong = data.setdefault(regime.strip(), ([], []))
        risks.append(raw_risk)
        wrong.append(0 if truth["correct"] else 1)

    gate = TrustGate(
        lam=lam,
        conformal_alpha=conformal_alpha,
        conformal_delta=conformal_delta,
    )
    for regime, (risks, wrong) in sorted(data.items()):
        validated = gate.prevalidate(regime, risks, wrong)
        state = getattr(gate, "_regimes", {}).get(regime)
        tau = getattr(state, "tau", None)
        report["regimes"][regime] = {
            "n": len(risks),
            "n_wrong": sum(wrong),
            "validated": bool(validated),
            "tau": tau,
            "certificate": getattr(state, "certificate", None),
        }
        if not validated:
            failures.append({
                "kind": "gate_prevalidation_failed",
                "regime": regime,
                "n": len(risks),
                "n_wrong": sum(wrong),
                "message": "prior records did not validate this regime for trust routing",
            })

    report["ok"] = not failures
    report["failures"] = failures
    return report, data


def _gate_from_prevalidation(data: Dict[str, Tuple[List[float], List[int]]], *,
                             lam: float,
                             conformal_alpha: Optional[float],
                             conformal_delta: float) -> TrustGate:
    gate = TrustGate(
        lam=lam,
        conformal_alpha=conformal_alpha,
        conformal_delta=conformal_delta,
    )
    for regime, (risks, wrong) in sorted(data.items()):
        if not gate.prevalidate(regime, risks, wrong):
            raise ValueError(f"gate prevalidation failed for regime {regime!r}")
    return gate


def preflight_batch_round(candidates_path: str, records_path: str, *,
                          verdicts_path: Optional[str] = None,
                          require_verdict_coverage: bool = True,
                          strict_complex_records: bool = False,
                          prevalidate_records_paths: Iterable[str] = (),
                          lam: float = 0.5,
                          conformal_alpha: Optional[float] = None,
                          conformal_delta: float = 0.1) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    prevalidate_records_paths = [str(path) for path in prevalidate_records_paths]
    pending_artifacts = _preflight_artifact_presence(
        candidates_path,
        records_path,
        verdicts_path=verdicts_path,
        prevalidate_records_paths=prevalidate_records_paths,
    )
    if pending_artifacts:
        return _blocked_preflight_report(
            candidates_path,
            records_path,
            verdicts_path=verdicts_path,
            require_verdict_coverage=require_verdict_coverage,
            strict_complex_records=strict_complex_records,
            prevalidate_records_paths=prevalidate_records_paths,
            lam=lam,
            conformal_alpha=conformal_alpha,
            conformal_delta=conformal_delta,
            pending_artifacts=pending_artifacts,
        )
    candidates = load_candidate_records(candidates_path)
    records = load_structure_records(records_path)
    candidate_ids, duplicate_candidates = _ids(candidates, "id", "candidates", failures)
    record_ids, duplicate_records = _ids(records, "target_id", "records", failures)
    candidate_complex_ids: Dict[str, set] = {}
    record_complex_ids: Dict[str, set] = {}
    if strict_complex_records:
        candidate_complex_ids = _complex_ids_by_item_id(candidates, "id", "candidates", failures)
        record_complex_ids = _complex_ids_by_item_id(records, "target_id", "records", failures)
    if duplicate_candidates:
        failures.append(_coverage_failure("duplicate_candidate_id", duplicate_candidates,
                                          "candidate ids must be unique before DBTL routing"))
    if duplicate_records:
        failures.append(_coverage_failure("duplicate_record_target_id", duplicate_records,
                                          "record target_ids must be unique before DBTL routing"))
    missing_records = set(candidate_ids) - set(record_ids)
    if missing_records:
        failures.append(_coverage_failure("missing_prediction_record", missing_records,
                                          "every candidate id must have a prediction record"))
    if strict_complex_records:
        for candidate_id in sorted(set(candidate_ids) & set(record_ids)):
            candidate_complex_set = candidate_complex_ids.get(candidate_id, set())
            record_complex_set = record_complex_ids.get(candidate_id, set())
            if not candidate_complex_set or not record_complex_set:
                continue
            if candidate_complex_set.isdisjoint(record_complex_set):
                failures.append({
                    "kind": "complex_target_mismatch",
                    "id": candidate_id,
                    "candidate_complex_target_ids": sorted(candidate_complex_set),
                    "record_complex_target_ids": sorted(record_complex_set),
                    "message": "candidate complex_target_id must match the prediction record for the same id",
                })

    verdict_ids: List[str] = []
    duplicate_verdicts: List[str] = []
    if verdicts_path:
        verdicts = _load_verdict_records(verdicts_path)
        verdict_ids, duplicate_verdicts = _ids(verdicts, "id", "verdicts", failures)
        if duplicate_verdicts:
            failures.append(_coverage_failure("duplicate_verdict_id", duplicate_verdicts,
                                              "verdict ids must be unique before DBTL routing"))
        if require_verdict_coverage:
            missing_verdicts = set(candidate_ids) - set(verdict_ids)
            if missing_verdicts:
                failures.append(_coverage_failure("missing_screen_verdict", missing_verdicts,
                                                  "every candidate id must have a precomputed screen verdict"))

    complex_qc = None
    if strict_complex_records:
        complex_qc = run_complex_records_qc(
            [records_path],
            require_complex_target_id=True,
            require_provenance=True,
            require_chain_ids=True,
        )
        if not complex_qc["ok"]:
            failures.append({
                "kind": "complex_records_qc_failed",
                "count": complex_qc["n_failures"],
                "failures_by_kind": complex_qc["failures_by_kind"],
                "message": "strict complex-record QC failed before DBTL routing",
            })

    prevalidation, _ = _prevalidation_report_and_data(
        prevalidate_records_paths,
        candidates,
        strict_complex_records=strict_complex_records,
        lam=lam,
        conformal_alpha=conformal_alpha,
        conformal_delta=conformal_delta,
        batch_records=records,
    )
    if prevalidation["requested"] and not prevalidation["ok"]:
        failures.append({
            "kind": "gate_prevalidation_blocked",
            "failures": prevalidation["failures"],
            "message": "fix prior gate prevalidation records before W4 routing",
        })

    return {
        "ok": not failures,
        "candidates": candidates_path,
        "records": records_path,
        "verdicts": verdicts_path,
        "n_candidates": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "n_records": len(record_ids),
        "n_verdicts": len(verdict_ids) if verdicts_path else None,
        "require_verdict_coverage": require_verdict_coverage,
        "strict_complex_records": strict_complex_records,
        "complex_target_identity_checked": strict_complex_records,
        "complex_records_qc": complex_qc,
        "gate_prevalidation": prevalidation,
        "pending_artifacts": [],
        "failures": failures,
    }


def run(args) -> "object":
    strict_complex_records = bool(getattr(args, "strict_complex_records", False))
    allow_missing_verdicts = bool(getattr(args, "allow_missing_verdicts", False))
    preflight = preflight_batch_round(
        args.candidates,
        args.records,
        verdicts_path=args.verdicts,
        require_verdict_coverage=not allow_missing_verdicts,
        strict_complex_records=strict_complex_records,
        prevalidate_records_paths=getattr(args, "prevalidate_records", []),
        lam=args.lam,
        conformal_alpha=getattr(args, "conformal_alpha", None),
        conformal_delta=getattr(args, "conformal_delta", 0.1),
    )
    preflight["self_command"] = _batch_round_command_from_args(args)
    preflight_out = getattr(args, "preflight_out", None) or os.path.join(args.out, "preflight.json")
    _write_json(preflight_out, preflight)
    sync_back_plan = getattr(args, "emit_sync_back_plan", None)
    if sync_back_plan:
        os.makedirs(os.path.dirname(os.path.abspath(sync_back_plan)) or ".", exist_ok=True)
        paths, _ = _safe_relative_pending_artifacts(preflight)
        sync_manifest_path = _manifest_path_for(sync_back_plan)
        manifest = _sync_manifest(
            kind="w4_batch_sync_back",
            paths=[rel_path for rel_path, _ in paths],
            sync_script=sync_back_plan,
            manifest_file=sync_manifest_path,
        )
        with open(sync_back_plan, "w") as fh:
            fh.write(render_sync_back_plan(preflight, args=args))
        with open(sync_manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {sync_back_plan}")
    print(f"# batch round preflight ok={preflight['ok']} candidates={preflight['n_candidates']} "
          f"records={preflight['n_records']} verdicts={preflight['n_verdicts']}")
    if not preflight["ok"]:
        raise ValueError("batch round preflight failed: " +
                         json.dumps(preflight["failures"], sort_keys=True))

    n = preflight["n_candidates"]
    spec = ObjectiveSpec(
        target=args.target, objective=args.objective, lam=args.lam,
        rounds=1, candidates_per_round=max(1, n), assay_budget=args.assay_budget,
    )
    screen = PrecomputedScreen(args.verdicts) if args.verdicts else SafetyScreen()
    gate = None
    prevalidate_records = list(getattr(args, "prevalidate_records", []) or [])
    if prevalidate_records or getattr(args, "conformal_alpha", None) is not None:
        candidates = load_candidate_records(args.candidates)
        _, prevalidation_data = _prevalidation_report_and_data(
            prevalidate_records,
            candidates,
            strict_complex_records=strict_complex_records,
            lam=args.lam,
            conformal_alpha=getattr(args, "conformal_alpha", None),
            conformal_delta=getattr(args, "conformal_delta", 0.1),
        )
        gate = _gate_from_prevalidation(
            prevalidation_data,
            lam=args.lam,
            conformal_alpha=getattr(args, "conformal_alpha", None),
            conformal_delta=getattr(args, "conformal_delta", 0.1),
        )
    provider = None
    if args.provider:
        from bio_sfm_trust import get_provider
        provider = get_provider(args.provider)

    result = DBTLController(
        generator=PrecomputedGenerator(args.candidates),
        predictor=PrecomputedStructurePredictor(args.records),
        gate=gate,
        screen=screen,
        provider=provider,
    ).run(spec, out_dir=args.out)

    agg = result.aggregate
    print(f"status={result.status} allowed={result.allowed} rounds={result.rounds_run} "
          f"candidates={agg.get('n')} assays_used={result.assays_used}")
    print(f"action mix: trust={agg.get('trust_rate')} verify={agg.get('verify_rate')} "
          f"baseline={agg.get('default_rate')} defer={agg.get('defer_rate')}")
    print(f"net/item={agg.get('net_reward_per_item')}  screen_backend={result.screen_backend}  "
          f"best={result.best}")
    if result.summary_path:
        with open(result.summary_path) as fh:
            summary = json.load(fh)
        summary["status"] = "closed_loop_round_complete" if result.allowed else result.status
        summary["controller_status"] = result.status
        summary["allowed"] = result.allowed
        summary["preflight_path"] = os.path.abspath(preflight_out)
        summary["strict_complex_records"] = preflight.get("strict_complex_records")
        summary["gate_prevalidation"] = preflight.get("gate_prevalidation")
        _write_json(result.summary_path, summary)
    if result.campaign_path:
        print(f"wrote {result.campaign_path} and {result.summary_path}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="run one batch DBTL round from synced HPC artifacts")
    ap.add_argument("--candidates", required=True, help="generate output JSONL (PrecomputedGenerator)")
    ap.add_argument("--records", required=True, help="predict output JSONL (PrecomputedStructurePredictor)")
    ap.add_argument("--verdicts", default=None, help="screen output JSONL (PrecomputedScreen); omit -> built-in screen")
    ap.add_argument("--target", required=True)
    ap.add_argument("--objective", default="stability")
    ap.add_argument("--lam", type=float, default=0.5)
    ap.add_argument("--assay-budget", type=int, default=1000)
    ap.add_argument("--out", default="results/batch_round")
    ap.add_argument("--preflight-out", default=None,
                    help="optional JSON preflight report path; default: <out>/preflight.json")
    ap.add_argument("--strict-complex-records", action="store_true",
                    help="require strict complex-record QC before running the DBTL round")
    ap.add_argument("--allow-missing-verdicts", action="store_true",
                    help="diagnostic escape hatch: let PrecomputedScreen fail-closed per missing verdict")
    ap.add_argument("--prevalidate-records", nargs="*", default=[],
                    help="prior verified records JSONL used to prevalidate the gate before routing")
    ap.add_argument("--conformal-alpha", type=float, default=None,
                    help="optional RCPS false-accept target for prevalidated regimes")
    ap.add_argument("--conformal-delta", type=float, default=0.1)
    ap.add_argument("--provider", default=None, help="optional LLM orchestrator: 'anthropic' or 'mock_defer'")
    ap.add_argument("--emit-sync-back-plan", default=None,
                    help="optional shell plan to rsync missing batch JSONLs back from external HPC")
    ap.add_argument("--sync-remote-root", default=None,
                    help="remote repo root for --emit-sync-back-plan; defaults to REMOTE_BIO_SFM_ROOT in the script")
    ap.add_argument("--sync-local-root", default=".",
                    help="local repo root for --emit-sync-back-plan")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
