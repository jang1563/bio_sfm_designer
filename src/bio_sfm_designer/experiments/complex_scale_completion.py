"""Validate completed M6c scale-batch outputs before posthoc analysis.

`complex_next_batch_plan.py --out` records the JSONL files that should appear
after Cayuga jobs finish. This helper checks that those files were synced back,
are structurally readable, and carry the planned `complex_target_id` before the
synchronized posthoc bundle is run.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Any, Dict, Iterable, List


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _check_jsonl(path: str, *, expected_target_id: str, check_target_ids: bool) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "path": os.path.abspath(path),
        "exists": os.path.exists(path),
        "nonempty": False,
        "jsonl_ok": False,
        "target_ids_ok": False,
        "n_rows": 0,
        "n_matching_complex_target_id": 0,
        "n_missing_complex_target_id": 0,
        "other_complex_target_ids": [],
        "_record_identities": [],
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
                target_id = row.get("target_id")
                if target_id is not None and str(target_id).strip():
                    complex_id = row.get("complex_target_id")
                    info["_record_identities"].append({
                        "identity": [str(complex_id or ""), str(target_id)],
                        "line": lineno,
                    })
                cid = row.get("complex_target_id")
                if cid == expected_target_id:
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


def _records_from_plan(plan: Dict[str, Any]) -> Dict[str, List[str]]:
    all_records = plan.get("records")
    new_records = plan.get("new_records")
    if not isinstance(all_records, list):
        raise ValueError("plan JSON is missing records list")
    if not isinstance(new_records, list):
        raise ValueError("plan JSON is missing new_records list")
    return {
        "all_records": [str(path) for path in all_records],
        "new_records": [str(path) for path in new_records],
    }


def _completion_command(rep: Dict[str, Any], *, plan_path: str, out_path: str) -> str:
    parts = [
        "python -m bio_sfm_designer.experiments.complex_scale_completion",
        "--plan",
        shlex.quote(plan_path),
        "--out",
        shlex.quote(out_path),
    ]
    if not rep.get("check_all_records", True):
        parts.append("--new-records-only")
    if not rep.get("check_target_ids", True):
        parts.append("--no-check-target-ids")
    return " ".join(parts)


def render_shell_plan(rep: Dict[str, Any], *, plan_path: str, out_path: str) -> str:
    lines = [
        "# M6c scale completion plan",
        "# Run locally after Cayuga records are synced back to the paths in the next-batch JSON plan.",
        "set -euo pipefail",
        "",
        _completion_command(rep, plan_path=plan_path, out_path=out_path),
    ]
    if rep.get("diagnostic_only"):
        lines.extend([
            "",
            "# WARNING: diagnostic-only unchecked-files scale plan; rerun with --require-files before production Cayuga submission or claims.",
        ])
    if rep["ok"] and rep.get("posthoc_command"):
        if rep.get("check_target_ids", True):
            ok_note = "# Records are present, structurally readable, and target-id aligned in the current filesystem snapshot."
        else:
            ok_note = "# Records are present and structurally readable; row-level target-id check was disabled."
        lines.extend([
            "",
            ok_note,
            rep["posthoc_command"],
            "",
        ])
    elif rep["ok"]:
        lines.extend([
            "",
            "# No scale-batch posthoc command is needed for this plan action.",
            "",
        ])
    else:
        lines.extend([
            "",
            "# Missing, invalid, or target-mismatched records in the current filesystem snapshot; sync/fix these before posthoc:",
        ])
        for failure in rep["failures"]:
            lines.append(f"# - {failure['role']} {failure['path']}: {failure['error']}")
        lines.append("")
    return "\n".join(lines)


def run_completion(plan_path: str, *, check_all_records: bool = True,
                   check_target_ids: bool = True,
                   out_path: str = "results/m6c_scale_completion.json") -> Dict[str, Any]:
    plan = _load_json(plan_path)
    action = str(plan.get("action"))
    posthoc_command = plan.get("posthoc_command")
    if plan.get("ok") is False or action == "unavailable":
        rep = {
            "ok": False,
            "status": "scale_plan_unavailable",
            "next_action": str(plan.get("next_action") or "rerun readiness after fixing the scale-plan blocker"),
            "plan": os.path.abspath(plan_path),
            "action": action,
            "check_all_records": check_all_records,
            "check_target_ids": check_target_ids,
            "posthoc_command": posthoc_command,
            "records": [],
            "failures": [{
                "path": os.path.abspath(plan_path),
                "role": "scale_plan",
                "error": str(plan.get("status") or "unavailable"),
            }],
            "source_status": plan.get("status"),
            "readiness_status": plan.get("readiness_status"),
            "message": plan.get("message"),
        }
        rep["shell_plan"] = render_shell_plan(rep, plan_path=plan_path, out_path=out_path)
        return rep
    if action != "run_scale_batch":
        rep = {
            "ok": True,
            "status": "no_scale_batch",
            "next_action": f"no completion check needed for action={action}",
            "plan": os.path.abspath(plan_path),
            "action": action,
            "check_all_records": check_all_records,
            "check_target_ids": check_target_ids,
            "posthoc_command": posthoc_command,
            "records": [],
            "failures": [],
        }
        rep["shell_plan"] = render_shell_plan(rep, plan_path=plan_path, out_path=out_path)
        return rep
    if not isinstance(posthoc_command, str) or not posthoc_command.strip():
        raise ValueError("run_scale_batch plan is missing posthoc_command")
    target_id = plan.get("target_id")
    if check_target_ids and (not isinstance(target_id, str) or not target_id.strip()):
        raise ValueError("run_scale_batch plan is missing target_id; rerun complex_next_batch_plan.py")
    expected_target_id = str(target_id or "")

    record_paths = _records_from_plan(plan)
    wanted = record_paths["all_records"] if check_all_records else record_paths["new_records"]
    new_set = set(record_paths["new_records"])
    records = []
    failures = []
    seen_identities: Dict[tuple, str] = {}
    for path in wanted:
        info = _check_jsonl(path, expected_target_id=expected_target_id, check_target_ids=check_target_ids)
        info["role"] = "new_record" if path in new_set else "previous_record"
        if not info["jsonl_ok"] or not info["target_ids_ok"]:
            failures.append({
                "path": info["path"],
                "role": info["role"],
                "error": info.get("error", "invalid_record"),
            })
        duplicate_identities = []
        for item in info.get("_record_identities", []):
            identity = tuple(item["identity"])
            here = f"{info['path']}:{item['line']}"
            first = seen_identities.get(identity)
            if first is not None:
                duplicate_identities.append({
                    "identity": item["identity"],
                    "first": first,
                    "duplicate": here,
                })
            else:
                seen_identities[identity] = here
        if duplicate_identities:
            info["duplicate_record_identities"] = duplicate_identities
            failures.append({
                "path": info["path"],
                "role": info["role"],
                "error": "duplicate_record_identity",
            })
        info["n_record_identities"] = len(info.get("_record_identities", []))
        info.pop("_record_identities", None)
        records.append(info)
    ok = not failures
    rep = {
        "ok": ok,
        "status": "ready_for_posthoc" if ok else "blocked",
        "next_action": (
            "run posthoc_command" if ok
            else "sync or fix missing, invalid, or target-mismatched record JSONL files before posthoc"
        ),
        "plan": os.path.abspath(plan_path),
        "action": action,
        "target_id": target_id,
        "target_alpha": plan.get("target_alpha"),
        "diagnostic_only": bool(plan.get("diagnostic_only")),
        "unchecked_files_allowed": bool(plan.get("unchecked_files_allowed")),
        "diagnostic_reason": plan.get("diagnostic_reason"),
        "check_all_records": check_all_records,
        "check_target_ids": check_target_ids,
        "expected_new_records": [os.path.abspath(path) for path in record_paths["new_records"]],
        "expected_records": [os.path.abspath(path) for path in record_paths["all_records"]],
        "posthoc_command": posthoc_command,
        "records": records,
        "failures": failures,
    }
    rep["shell_plan"] = render_shell_plan(rep, plan_path=plan_path, out_path=out_path)
    return rep


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="validate completed M6c scale-batch records before posthoc")
    ap.add_argument("--plan", required=True,
                    help="JSON written by complex_next_batch_plan.py --out or complex_readiness.py --emit-scale-plan")
    ap.add_argument("--new-records-only", action="store_true",
                    help="check only newly expected HPC outputs, not previous records in the posthoc set")
    ap.add_argument("--no-check-target-ids", action="store_true",
                    help="legacy/debug escape hatch: do not require rows to match planned complex_target_id")
    ap.add_argument("--out", default="results/m6c_scale_completion.json",
                    help="optional JSON completion report path")
    ap.add_argument("--emit-plan", default=None, help="optional shell completion plan path")
    args = ap.parse_args(argv)

    try:
        rep = run_completion(
            args.plan,
            check_all_records=not args.new_records_only,
            check_target_ids=not args.no_check_target_ids,
            out_path=args.out,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex scale completion failed: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"# complex scale completion  status={rep['status']} ok={rep['ok']}")
    print(f"  next_action: {rep['next_action']}")
    if rep.get("posthoc_command"):
        print(f"  posthoc_command: {rep['posthoc_command']}")
    for failure in rep["failures"]:
        print(f"  {failure['role']} {failure['path']}: {failure['error']}")
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
