"""Validate completed multi-target panel outputs before panel analysis.

The target manifest names the per-target records JSONL files that should appear
after the dependency-chained ProteinMPNN/Boltz panel jobs finish. This helper
checks those files before `complex_panel_report.py`, including that rows carry
the manifest target id as `complex_target_id`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _records_path(target: Dict[str, Any]) -> str:
    target_id = str(target.get("id", "target"))
    out_prefix = target.get("out_prefix", f"hpc_outputs/{target_id}")
    records = target.get("records", os.path.join(str(out_prefix), "records_boltz_complex.jsonl"))
    if not _is_nonempty_str(records):
        raise ValueError(f"target {target_id} has an empty records path")
    return str(records)


def _inspect_records(path: str, target_id: str, *, check_target_ids: bool) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "target_id": target_id,
        "path": os.path.abspath(path),
        "exists": os.path.exists(path),
        "nonempty": False,
        "jsonl_ok": False,
        "target_ids_ok": False,
        "n_rows": 0,
        "n_matching_complex_target_id": 0,
        "n_missing_complex_target_id": 0,
        "other_complex_target_ids": [],
    }
    if not info["exists"]:
        info["error"] = "missing_file"
        return info
    if os.path.getsize(path) == 0:
        info["error"] = "empty_file"
        return info
    info["nonempty"] = True
    other_ids = set()
    try:
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                if not isinstance(row, dict):
                    info["error"] = f"line_{lineno}_not_object"
                    return info
                info["n_rows"] += 1
                cid = row.get("complex_target_id")
                if cid == target_id:
                    info["n_matching_complex_target_id"] += 1
                elif cid is None or cid == "":
                    info["n_missing_complex_target_id"] += 1
                else:
                    other_ids.add(str(cid))
    except (OSError, json.JSONDecodeError) as exc:
        info["error"] = f"bad_jsonl: {exc}"
        return info
    if info["n_rows"] == 0:
        info["error"] = "no_jsonl_rows"
        return info
    info["jsonl_ok"] = True
    info["other_complex_target_ids"] = sorted(other_ids)
    if not check_target_ids:
        info["target_ids_ok"] = True
        return info
    if info["n_matching_complex_target_id"] != info["n_rows"]:
        info["error"] = "complex_target_id_mismatch"
        return info
    info["target_ids_ok"] = True
    return info


def _target_records(manifest: Dict[str, Any],
                    target_ids: Optional[Iterable[str]] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise ValueError("manifest must contain a targets list")
    selected_ids = set(str(t) for t in target_ids) if target_ids is not None else None
    planned = []
    failures = []
    seen = set()
    for index, target in enumerate(targets):
        if selected_ids is not None:
            if not isinstance(target, dict) or str(target.get("id")) not in selected_ids:
                continue
        if not isinstance(target, dict):
            failures.append({"target_id": None, "kind": "bad_target", "message": f"targets[{index}] must be an object"})
            continue
        target_id = target.get("id")
        if not _is_nonempty_str(target_id):
            failures.append({"target_id": None, "kind": "missing_target_id", "message": f"targets[{index}] missing id"})
            continue
        target_id = str(target_id)
        if target_id in seen:
            failures.append({"target_id": target_id, "kind": "duplicate_target", "message": "duplicate target id"})
            continue
        seen.add(target_id)
        try:
            planned.append({"target_id": target_id, "records": _records_path(target)})
        except ValueError as exc:
            failures.append({"target_id": target_id, "kind": "bad_records_path", "message": str(exc)})
    if selected_ids is not None:
        for missing in sorted(selected_ids - seen):
            failures.append({
                "target_id": missing,
                "kind": "missing_target",
                "message": "requested target id is not present in manifest",
            })
    return planned, failures


def _records_arg(paths: List[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def _panel_command(records: List[str], *, target_alpha: float, min_targets: int,
                   min_records_per_target: int, panel_out: str) -> str:
    return (
        "python -m bio_sfm_designer.experiments.complex_panel_report "
        f"--records {_records_arg(records)} "
        f"--target-alpha {target_alpha} "
        f"--min-targets {min_targets} "
        f"--min-records-per-target {min_records_per_target} "
        f"--out {shlex.quote(panel_out)}"
    )


def _completion_command(rep: Dict[str, Any], *, manifest_path: str, out_path: str) -> str:
    parts = [
        "python -m bio_sfm_designer.experiments.complex_panel_completion",
        "--manifest",
        shlex.quote(manifest_path),
        "--min-targets",
        shlex.quote(str(rep["min_targets"])),
        "--min-records-per-target",
        shlex.quote(str(rep["min_records_per_target"])),
        "--target-alpha",
        shlex.quote(str(rep["target_alpha"])),
        "--panel-out",
        shlex.quote(str(rep["panel_out"])),
        "--out",
        shlex.quote(out_path),
    ]
    for target_id in rep.get("target_ids") or []:
        parts.extend(["--target-id", shlex.quote(str(target_id))])
    if not rep.get("check_target_ids", True):
        parts.append("--no-check-target-ids")
    return " ".join(parts)


def render_shell_plan(rep: Dict[str, Any], *, manifest_path: str, out_path: str) -> str:
    lines = [
        "# M6c panel completion plan",
        "# Run locally after all target panel records are synced back to the manifest paths.",
        "set -euo pipefail",
        "",
        _completion_command(rep, manifest_path=manifest_path, out_path=out_path),
    ]
    if rep["ok"]:
        if rep.get("check_target_ids", True):
            ok_note = "# Panel records are present, structurally readable, and target-id aligned."
        else:
            ok_note = "# Panel records are present and structurally readable; row-level target-id check was disabled."
        lines.extend([
            "",
            ok_note,
            rep["panel_report_command"],
            "",
        ])
    else:
        lines.extend([
            "",
            "# Missing, malformed, or target-mismatched records; fix these before panel_report:",
        ])
        for failure in rep["failures"]:
            lines.append(f"# - {failure['kind']} target={failure.get('target_id')}: {failure['message']}")
        lines.append("")
    return "\n".join(lines)


def run_completion(manifest_path: str, *, min_targets: int = 3,
                   min_records_per_target: int = 20,
                   target_alpha: float = 0.2,
                   panel_out: str = "results/m6c_panel_report.json",
                   check_target_ids: bool = True,
                   out_path: str = "results/m6c_panel_completion.json",
                   target_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    manifest = _load_json(manifest_path)
    selected_target_ids = sorted(set(str(t) for t in target_ids)) if target_ids is not None else None
    planned, failures = _target_records(manifest, target_ids=selected_target_ids)
    records = []
    ready_records = []
    for target in planned:
        info = _inspect_records(target["records"], target["target_id"], check_target_ids=check_target_ids)
        records.append(info)
        if info["jsonl_ok"] and info["target_ids_ok"]:
            ready_records.append(target["records"])
        else:
            failures.append({
                "target_id": target["target_id"],
                "kind": info.get("error", "invalid_records"),
                "message": f"{target['records']}: {info.get('error', 'invalid_records')}",
                "path": info["path"],
            })
    if len(planned) < min_targets:
        failures.append({
            "target_id": None,
            "kind": "too_few_manifest_targets",
            "message": f"{len(planned)} targets < required {min_targets}",
        })
    if len(ready_records) < min_targets:
        failures.append({
            "target_id": None,
            "kind": "too_few_completed_targets",
            "message": f"{len(ready_records)} completed target records < required {min_targets}",
        })

    panel_report_command = _panel_command(
        ready_records,
        target_alpha=target_alpha,
        min_targets=min_targets,
        min_records_per_target=min_records_per_target,
        panel_out=panel_out,
    )
    ok = not failures
    rep = {
        "ok": ok,
        "status": "ready_for_panel_report" if ok else "blocked",
        "next_action": "run panel_report_command" if ok else "sync/fix target records before panel report",
        "manifest": os.path.abspath(manifest_path),
        "target_alpha": target_alpha,
        "panel_out": panel_out,
        "min_targets": min_targets,
        "min_records_per_target": min_records_per_target,
        "check_target_ids": check_target_ids,
        "target_ids": selected_target_ids,
        "n_manifest_targets": len(planned),
        "n_completed_targets": len(ready_records),
        "expected_records": [{"target_id": t["target_id"], "records": os.path.abspath(t["records"])}
                             for t in planned],
        "records": records,
        "failures": failures,
        "panel_report_command": panel_report_command,
    }
    rep["shell_plan"] = render_shell_plan(rep, manifest_path=manifest_path, out_path=out_path)
    return rep


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="validate completed M6c panel records before panel report")
    ap.add_argument("--manifest", required=True, help="target manifest used to submit the panel jobs")
    ap.add_argument("--target-id", action="append", dest="target_ids", default=None,
                    help="optional target id to validate; repeat for a selected staged-panel subset")
    ap.add_argument("--min-targets", type=int, default=3)
    ap.add_argument("--min-records-per-target", type=int, default=20)
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--panel-out", default="results/m6c_panel_report.json")
    ap.add_argument("--no-check-target-ids", action="store_true",
                    help="legacy/debug escape hatch: do not require rows to match manifest complex_target_id")
    ap.add_argument("--out", default="results/m6c_panel_completion.json")
    ap.add_argument("--emit-plan", default=None, help="optional shell completion plan path")
    args = ap.parse_args(argv)

    try:
        rep = run_completion(
            args.manifest,
            min_targets=args.min_targets,
            min_records_per_target=args.min_records_per_target,
            target_alpha=args.target_alpha,
            panel_out=args.panel_out,
            check_target_ids=not args.no_check_target_ids,
            out_path=args.out,
            target_ids=args.target_ids,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex panel completion failed: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"# complex panel completion  status={rep['status']} ok={rep['ok']}")
    print(f"  completed_targets={rep['n_completed_targets']}/{rep['n_manifest_targets']}")
    print(f"  next_action: {rep['next_action']}")
    if rep["ok"]:
        print(f"  panel_report_command: {rep['panel_report_command']}")
    for failure in rep["failures"]:
        print(f"  {failure['kind']} target={failure.get('target_id')}: {failure['message']}")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            obj = {k: v for k, v in rep.items() if k != "shell_plan"}
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.emit_plan:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_plan)) or ".", exist_ok=True)
        with open(args.emit_plan, "w") as fh:
            fh.write(rep["shell_plan"])
        print(f"wrote {args.emit_plan}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
