"""Validate synced target input-prep artifacts before rerunning manifest preflight.

`complex_target_manifest.py --out` records the source/prepared PDB, target FASTA,
target MSA, and companion report paths that the emitted MSA/prep plan may create
on external HPC. This helper checks that those files are back in the local filesystem
snapshot before the stricter `--require-files` manifest gate is rerun.
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


def _selected_ids(target_ids: Optional[Iterable[str]]) -> Optional[List[str]]:
    if target_ids is None:
        return None
    return sorted(set(str(t) for t in target_ids))


def _artifact_failure(target_id: Optional[str], field: Optional[str], kind: str,
                      message: str, *, path: Optional[str] = None) -> Dict[str, Any]:
    failure: Dict[str, Any] = {
        "target_id": target_id,
        "field": field,
        "kind": kind,
        "message": message,
    }
    if path is not None:
        failure["path"] = os.path.abspath(path)
    return failure


def _planned_artifacts(report: Dict[str, Any],
                       target_ids: Optional[Iterable[str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    artifacts = report.get("input_prep_artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("report is missing input_prep_artifacts list; rerun complex_target_manifest.py")
    selected = set(_selected_ids(target_ids) or [])
    planned: List[Dict[str, str]] = []
    failures: List[Dict[str, Any]] = []
    seen_targets = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(_artifact_failure(
                None, None, "bad_artifact", f"input_prep_artifacts[{index}] must be an object"
            ))
            continue
        target_id = str(artifact.get("target_id")) if artifact.get("target_id") is not None else None
        if selected and target_id not in selected:
            continue
        field = str(artifact.get("field")) if artifact.get("field") is not None else None
        path = artifact.get("path")
        if target_id is not None:
            seen_targets.add(target_id)
        if not _is_nonempty_str(field):
            failures.append(_artifact_failure(target_id, None, "bad_artifact",
                                              f"input_prep_artifacts[{index}] missing field"))
            continue
        if not _is_nonempty_str(path):
            failures.append(_artifact_failure(target_id, field, "bad_artifact",
                                              f"input_prep_artifacts[{index}] missing path"))
            continue
        planned.append({"target_id": str(target_id), "field": str(field), "path": str(path)})
    for missing in sorted(selected - seen_targets):
        failures.append(_artifact_failure(
            missing, None, "missing_target_artifacts",
            "requested target id has no input-prep artifacts in this report",
        ))
    return planned, failures


def _inspect_artifact(artifact: Dict[str, str]) -> Dict[str, Any]:
    path = artifact["path"]
    info: Dict[str, Any] = {
        "target_id": artifact["target_id"],
        "field": artifact["field"],
        "declared_path": path,
        "path": os.path.abspath(path),
        "exists": os.path.exists(path),
        "nonempty": False,
        "size_bytes": None,
    }
    if not info["exists"]:
        info["error"] = "missing_file"
        return info
    size = os.path.getsize(path)
    info["size_bytes"] = size
    if size == 0:
        info["error"] = "empty_file"
        return info
    info["nonempty"] = True
    return info


def _artifact_summary(artifacts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_target: Dict[str, Dict[str, Any]] = {}
    for artifact in artifacts:
        target_id = str(artifact.get("target_id"))
        summary = by_target.setdefault(target_id, {
            "n_artifacts": 0,
            "n_present": 0,
            "n_nonempty": 0,
            "n_missing": 0,
            "n_empty": 0,
            "pending_fields": [],
            "ready": False,
        })
        summary["n_artifacts"] += 1
        if artifact.get("exists"):
            summary["n_present"] += 1
        if artifact.get("nonempty"):
            summary["n_nonempty"] += 1
        error = artifact.get("error")
        if error == "missing_file":
            summary["n_missing"] += 1
            summary["pending_fields"].append(artifact.get("field"))
        elif error == "empty_file":
            summary["n_empty"] += 1
            summary["pending_fields"].append(artifact.get("field"))
    for summary in by_target.values():
        summary["pending_fields"] = sorted(str(f) for f in summary["pending_fields"] if f is not None)
        summary["ready"] = (
            summary["n_artifacts"] > 0
            and summary["n_missing"] == 0
            and summary["n_empty"] == 0
            and summary["n_nonempty"] == summary["n_artifacts"]
        )
    return by_target


def _pending_artifacts(artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pending = []
    for artifact in artifacts:
        error = artifact.get("error")
        if error not in {"missing_file", "empty_file"}:
            continue
        pending.append({
            "target_id": artifact.get("target_id"),
            "field": artifact.get("field"),
            "declared_path": artifact.get("declared_path"),
            "path": artifact.get("path"),
            "error": error,
        })
    return pending


def _manifest_command(report: Dict[str, Any], *, report_path: str,
                      target_ids: Optional[Iterable[str]]) -> Optional[str]:
    manifest = report.get("manifest")
    if not _is_nonempty_str(manifest):
        return None
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.complex_target_manifest",
        "--manifest",
        str(manifest),
        "--require-files",
        "--min-targets",
        str(report.get("min_targets", 1)),
        "--min-contacts",
        str(report.get("min_contacts", 1)),
    ]
    selected = _selected_ids(target_ids)
    if selected is None:
        selected = report.get("target_ids")
        if not isinstance(selected, list):
            selected = None
    for target_id in selected or []:
        parts.extend(["--target-id", str(target_id)])
    if report.get("require_records"):
        parts.append("--require-records")
    parts.extend(["--out", report_path])
    return shlex.join(parts)


def _completion_command(rep: Dict[str, Any], *, report_path: str, out_path: str,
                        pending_paths_path: Optional[str] = None,
                        absolute_pending_paths: bool = False) -> str:
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.complex_input_prep_completion",
        "--report",
        report_path,
        "--out",
        out_path,
    ]
    for target_id in rep.get("target_ids") or []:
        parts.extend(["--target-id", str(target_id)])
    if pending_paths_path:
        parts.extend(["--emit-pending-paths", pending_paths_path])
        if absolute_pending_paths:
            parts.append("--absolute-pending-paths")
    return shlex.join(parts)


def render_shell_plan(rep: Dict[str, Any], *, report_path: str, out_path: str,
                      pending_paths_path: Optional[str] = None,
                      absolute_pending_paths: bool = False) -> str:
    lines = [
        "# M6c input-prep completion plan",
        "# Run locally after target input-prep files are synced back from external HPC.",
        "set -euo pipefail",
        "",
        _completion_command(
            rep,
            report_path=report_path,
            out_path=out_path,
            pending_paths_path=pending_paths_path,
            absolute_pending_paths=absolute_pending_paths,
        ),
    ]
    if rep["ok"]:
        lines.extend([
            "",
            "# Input-prep files are present and non-empty in the current filesystem snapshot.",
        ])
        if rep.get("manifest_command"):
            lines.append(rep["manifest_command"])
            lines.append("")
        else:
            lines.extend([
                "# No manifest path was recorded in the input-prep report; rerun complex_target_manifest.py manually.",
                "",
            ])
    else:
        lines.extend([
            "",
            "# Missing or empty input-prep artifacts; sync/fix these before rerunning --require-files:",
        ])
        for failure in rep["failures"]:
            path = failure.get("path", "")
            field = failure.get("field")
            lines.append(
                f"# - {failure['kind']} target={failure.get('target_id')} field={field} {path}: "
                f"{failure['message']}"
            )
        pending = rep.get("pending_artifacts") or []
        if pending:
            lines.extend([
                "",
                "# pending_input_prep_files",
            ])
            for artifact in pending:
                lines.append(
                    f"# {artifact.get('target_id')} {artifact.get('field')}: "
                    f"{artifact.get('path')} ({artifact.get('error')})"
                )
        lines.append("")
    return "\n".join(lines)


def render_pending_paths(rep: Dict[str, Any], *, absolute: bool = False) -> str:
    lines = []
    for artifact in rep.get("pending_artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path") if absolute else artifact.get("declared_path")
        if not path:
            path = artifact.get("path")
        if path:
            lines.append(str(path))
    return "\n".join(lines) + ("\n" if lines else "")


def run_completion(report_path: str, *, out_path: str = "results/m6c_input_prep_completion.json",
                   target_ids: Optional[Iterable[str]] = None,
                   pending_paths_path: Optional[str] = None,
                   absolute_pending_paths: bool = False) -> Dict[str, Any]:
    report = _load_json(report_path)
    selected_target_ids = _selected_ids(target_ids)
    planned, failures = _planned_artifacts(report, selected_target_ids)
    artifacts = []
    for artifact in planned:
        info = _inspect_artifact(artifact)
        artifacts.append(info)
        if not info["exists"] or not info["nonempty"]:
            failures.append(_artifact_failure(
                info["target_id"],
                info["field"],
                info.get("error", "invalid_artifact"),
                f"{artifact['path']}: {info.get('error', 'invalid_artifact')}",
                path=artifact["path"],
            ))
    if not planned:
        failures.append(_artifact_failure(
            None,
            None,
            "no_input_prep_artifacts",
            "no input-prep artifacts matched this report/target selection",
        ))

    ok = not failures
    n_present = sum(1 for a in artifacts if a["exists"])
    n_nonempty = sum(1 for a in artifacts if a["nonempty"])
    n_missing = sum(1 for a in artifacts if a.get("error") == "missing_file")
    n_empty = sum(1 for a in artifacts if a.get("error") == "empty_file")
    artifacts_by_target = _artifact_summary(artifacts)
    pending_artifacts = _pending_artifacts(artifacts)
    manifest_command = _manifest_command(report, report_path=report_path, target_ids=selected_target_ids)
    rep = {
        "ok": ok,
        "status": "ready_for_require_files" if ok else "blocked",
        "next_action": (
            "run manifest_command" if ok and manifest_command
            else "sync/fix missing or empty input-prep artifacts before rerunning --require-files"
        ),
        "report": os.path.abspath(report_path),
        "manifest": report.get("manifest"),
        "target_ids": selected_target_ids,
        "min_targets": report.get("min_targets", 1),
        "min_contacts": report.get("min_contacts", 1),
        "require_records": bool(report.get("require_records")),
        "n_artifacts": len(artifacts),
        "n_present": n_present,
        "n_nonempty": n_nonempty,
        "n_missing": n_missing,
        "n_empty": n_empty,
        "ready_targets": sorted(t for t, s in artifacts_by_target.items() if s["ready"]),
        "blocked_targets": sorted(t for t, s in artifacts_by_target.items() if not s["ready"]),
        "artifacts_by_target": artifacts_by_target,
        "pending_artifacts": pending_artifacts,
        "artifacts": artifacts,
        "failures": failures,
        "manifest_command": manifest_command,
    }
    rep["shell_plan"] = render_shell_plan(
        rep,
        report_path=report_path,
        out_path=out_path,
        pending_paths_path=pending_paths_path,
        absolute_pending_paths=absolute_pending_paths,
    )
    return rep


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="validate synced target input-prep files before manifest preflight")
    ap.add_argument("--report", required=True,
                    help="JSON written by complex_target_manifest.py --out")
    ap.add_argument("--target-id", action="append", dest="target_ids", default=None,
                    help="optional target id to validate; repeat for a selected subset")
    ap.add_argument("--out", default="results/m6c_input_prep_completion.json",
                    help="optional JSON completion report path")
    ap.add_argument("--emit-plan", default=None, help="optional shell completion plan path")
    ap.add_argument("--emit-pending-paths", default=None,
                    help="optional text file listing missing/empty input-prep paths, one path per line")
    ap.add_argument("--absolute-pending-paths", action="store_true",
                    help="write absolute paths in --emit-pending-paths instead of manifest-declared paths")
    args = ap.parse_args(argv)

    try:
        rep = run_completion(
            args.report,
            out_path=args.out,
            target_ids=args.target_ids,
            pending_paths_path=args.emit_pending_paths,
            absolute_pending_paths=args.absolute_pending_paths,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex input-prep completion failed: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"# complex input-prep completion  status={rep['status']} ok={rep['ok']}")
    print(f"  artifacts={rep['n_nonempty']}/{rep['n_artifacts']} nonempty")
    print(f"  next_action: {rep['next_action']}")
    if rep.get("manifest_command"):
        print(f"  manifest_command: {rep['manifest_command']}")
    for failure in rep["failures"]:
        field = f" field={failure['field']}" if failure.get("field") is not None else ""
        path = f" {failure['path']}" if failure.get("path") else ""
        print(f"  {failure['kind']} target={failure.get('target_id')}{field}{path} -- {failure['message']}")
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
    if args.emit_pending_paths:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_pending_paths)) or ".", exist_ok=True)
        with open(args.emit_pending_paths, "w") as fh:
            fh.write(render_pending_paths(rep, absolute=args.absolute_pending_paths))
        print(f"wrote {args.emit_pending_paths}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
