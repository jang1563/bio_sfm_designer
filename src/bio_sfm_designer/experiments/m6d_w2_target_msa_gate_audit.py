"""Audit the M6d W2 v9 target-MSA gate without submitting jobs.

This helper validates the *expected blocked* state before the target-MSA
precompute is explicitly approved. Missing target MSA files are not a failure
when they are exactly the files listed in the pre-sync completion report and
postsubmit replay plan. The audit only checks reproducibility and gate
discipline; it does not certify W2 and never submits Cayuga work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Set


_READY_STATUS = "ready_for_explicitly_approved_target_msa_submission_only"
_AWAITING_STATUS = "postsubmit_replay_ready_awaiting_target_msa_submission_and_completion"
_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_TARGET_MSA"
_APPROVAL_TOKEN = "approve-v9-target-msa-precompute"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _read_paths(path: str) -> List[str]:
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip()]


def _is_true(value: Any) -> bool:
    return value is True


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _pending_declared_paths(completion: Dict[str, Any]) -> List[str]:
    out = []
    for artifact in completion.get("pending_artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("declared_path") or artifact.get("path")
        if isinstance(path, str) and path.strip():
            out.append(path.strip())
    return sorted(out)


def _pending_fields(completion: Dict[str, Any]) -> List[str]:
    fields = []
    for artifact in completion.get("pending_artifacts") or []:
        if isinstance(artifact, dict) and isinstance(artifact.get("field"), str):
            fields.append(artifact["field"])
    return sorted(set(fields))


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _path_exists(path: Optional[str]) -> bool:
    return isinstance(path, str) and bool(path.strip()) and os.path.exists(path)


def build_audit(anchor: Dict[str, Any],
                presubmit: Dict[str, Any],
                completion: Dict[str, Any],
                postsubmit: Dict[str, Any],
                manifest: Dict[str, Any],
                pending_paths: Iterable[str],
                *,
                pending_paths_path: str,
                sync_back_script: Optional[str] = None,
                expected_targets: Optional[int] = None,
                expected_pending_paths: Optional[int] = None) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    pending = sorted(str(p) for p in pending_paths)
    pending_from_completion = _pending_declared_paths(completion)
    pending_set: Set[str] = set(pending)
    completion_set: Set[str] = set(pending_from_completion)

    current_status = anchor.get("current_status") if isinstance(anchor.get("current_status"), dict) else {}
    goal_progress = current_status.get("goal_progress")
    w2_v9 = (
        anchor.get("w2_decision_path", {})
        .get("target_family_redesign_v9", {})
        if isinstance(anchor.get("w2_decision_path"), dict)
        else {}
    )

    if presubmit.get("status") != _READY_STATUS:
        _add_failure(failures, "presubmit_status_not_ready_for_approval",
                     "presubmit preflight is not in the explicit-approval ready state",
                     expected=_READY_STATUS, observed=presubmit.get("status"))
    if not _is_true(presubmit.get("explicit_submit_approval_required")):
        _add_failure(failures, "approval_not_required",
                     "presubmit artifact must require explicit approval before job submission")
    if not _nonempty_str(presubmit.get("next_command_if_approved")):
        _add_failure(failures, "missing_submit_command",
                     "presubmit artifact is missing next_command_if_approved")
    elif (
        _APPROVAL_ENV_VAR not in str(presubmit.get("next_command_if_approved"))
        or _APPROVAL_TOKEN not in str(presubmit.get("next_command_if_approved"))
    ):
        _add_failure(
            failures,
            "submit_command_missing_approval_env",
            "target-MSA submit command must carry the explicit approval environment variable",
            expected=f"{_APPROVAL_ENV_VAR}={_APPROVAL_TOKEN}",
            observed=presubmit.get("next_command_if_approved"),
        )

    preflight = presubmit.get("preflight") if isinstance(presubmit.get("preflight"), dict) else {}
    for field in (
        "dry_run_passed_on_cayuga",
        "boltz_runtime_executable_on_cayuga",
        "helper_scripts_present_on_cayuga",
        "local_remote_anchor_match",
    ):
        if not _is_true(preflight.get(field)):
            _add_failure(failures, f"preflight_{field}_not_true",
                         f"preflight.{field} must be true", observed=preflight.get(field))
    if preflight.get("input_prep_missing_on_cayuga") != 0:
        _add_failure(failures, "input_prep_missing_on_cayuga",
                     "all non-MSA input-prep files should already exist on Cayuga",
                     expected=0, observed=preflight.get("input_prep_missing_on_cayuga"))

    manifest_targets = _as_int(preflight.get("manifest_targets"))
    target_ids = presubmit.get("target_ids") if isinstance(presubmit.get("target_ids"), list) else []
    if expected_targets is not None and manifest_targets != expected_targets:
        _add_failure(failures, "manifest_target_count_mismatch",
                     "preflight manifest target count differs from expected",
                     expected=expected_targets, observed=manifest_targets)
    if manifest_targets is not None and len(target_ids) != manifest_targets:
        _add_failure(failures, "target_id_count_mismatch",
                     "presubmit target_ids length does not match manifest_targets",
                     expected=manifest_targets, observed=len(target_ids))

    if completion.get("status") != "blocked" or completion.get("ok") is not False:
        _add_failure(failures, "pre_sync_completion_not_expected_blocked",
                     "pre-sync completion should be blocked before target-MSA outputs exist",
                     observed={"status": completion.get("status"), "ok": completion.get("ok")})
    if completion.get("n_empty") not in (0, None):
        _add_failure(failures, "empty_input_prep_artifacts",
                     "pre-sync completion has empty artifacts, not just missing MSA outputs",
                     expected=0, observed=completion.get("n_empty"))
    if _pending_fields(completion) != ["target_msa", "target_msa_report"]:
        _add_failure(failures, "unexpected_pending_fields",
                     "pending input-prep fields should be only target_msa and target_msa_report",
                     expected=["target_msa", "target_msa_report"],
                     observed=_pending_fields(completion))
    if pending_set != completion_set:
        _add_failure(failures, "pending_path_set_mismatch",
                     "pending paths file differs from completion pending_artifacts",
                     expected=len(completion_set), observed=len(pending_set))
    if expected_pending_paths is not None and len(pending) != expected_pending_paths:
        _add_failure(failures, "pending_path_count_mismatch",
                     "pending path count differs from expected",
                     expected=expected_pending_paths, observed=len(pending))
    if completion.get("n_missing") != len(pending):
        _add_failure(failures, "completion_missing_count_mismatch",
                     "completion n_missing differs from pending path count",
                     expected=len(pending), observed=completion.get("n_missing"))

    if manifest.get("ok") is not False or manifest.get("n_ready_targets") not in (0, None):
        _add_failure(failures, "manifest_not_expected_pre_submit_blocked",
                     "strict post-MSA manifest should fail closed before MSA outputs exist",
                     observed={"ok": manifest.get("ok"), "n_ready_targets": manifest.get("n_ready_targets")})
    manifest_failures = manifest.get("failures") if isinstance(manifest.get("failures"), list) else []
    if len(manifest_failures) != len(pending):
        _add_failure(failures, "manifest_failure_count_mismatch",
                     "manifest missing-file failures differ from pending path count",
                     expected=len(pending), observed=len(manifest_failures))
    if any(isinstance(f, dict) and f.get("kind") != "missing_file" for f in manifest_failures):
        _add_failure(failures, "manifest_has_non_missing_failures",
                     "pre-submit manifest failures should only be missing_file failures")

    if postsubmit.get("status") != _AWAITING_STATUS:
        _add_failure(failures, "postsubmit_plan_status_mismatch",
                     "postsubmit replay plan is not waiting for target-MSA completion",
                     expected=_AWAITING_STATUS, observed=postsubmit.get("status"))
    if postsubmit.get("pending_input_prep_path_count") != len(pending):
        _add_failure(failures, "postsubmit_pending_count_mismatch",
                     "postsubmit pending path count differs from pending paths file",
                     expected=len(pending), observed=postsubmit.get("pending_input_prep_path_count"))
    if postsubmit.get("pending_input_prep_paths") != pending_paths_path:
        _add_failure(failures, "postsubmit_pending_paths_pointer_mismatch",
                     "postsubmit plan points to a different pending path list",
                     expected=pending_paths_path, observed=postsubmit.get("pending_input_prep_paths"))
    postsubmit_submit_command = postsubmit.get("pre_submit_command_if_approved")
    if postsubmit_submit_command != presubmit.get("next_command_if_approved"):
        _add_failure(failures, "postsubmit_presubmit_command_mismatch",
                     "postsubmit replay plan and presubmit preflight must record the same approved submit command",
                     expected=presubmit.get("next_command_if_approved"),
                     observed=postsubmit_submit_command)
    if (
        _APPROVAL_ENV_VAR not in str(postsubmit_submit_command or "")
        or _APPROVAL_TOKEN not in str(postsubmit_submit_command or "")
    ):
        _add_failure(
            failures,
            "postsubmit_command_missing_approval_env",
            "postsubmit replay plan must carry the explicit target-MSA approval environment variable",
            expected=f"{_APPROVAL_ENV_VAR}={_APPROVAL_TOKEN}",
            observed=postsubmit_submit_command,
        )
    script = sync_back_script or postsubmit.get("sync_back_script")
    if not _path_exists(script):
        _add_failure(failures, "missing_sync_back_script",
                     "sync-back script referenced by the postsubmit plan does not exist",
                     observed=script)

    expected_goal = "w2_target_family_redesign_v9_target_msa_presubmit_and_postsubmit_replay_ready_awaiting_explicit_submission_approval"
    project_level_goal_ready = (
        goal_progress == "local_artifact_work_required"
        and current_status.get("project_status_w2") == "target_msa_gate_ready_awaiting_explicit_approval"
        and current_status.get("remaining_requirements") == 1
    )
    branch_goal_ready = goal_progress == expected_goal
    if not (branch_goal_ready or project_level_goal_ready):
        _add_failure(failures, "anchor_goal_progress_mismatch",
                     "goal anchor is not in the expected W2 v9 target-MSA gate state",
                     expected=[expected_goal, "local_artifact_work_required with W2 ready and one remaining requirement"],
                     observed={
                         "goal_progress": goal_progress,
                         "project_status_w2": current_status.get("project_status_w2"),
                         "remaining_requirements": current_status.get("remaining_requirements"),
                     })
    if w2_v9.get("status") != "target_msa_submit_and_postsubmit_replay_ready_awaiting_explicit_submission_approval":
        _add_failure(failures, "anchor_w2_v9_status_mismatch",
                     "W2 v9 anchor branch status does not match the target-MSA gate",
                     observed=w2_v9.get("status"))

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_target_msa_gate_audit",
        "audit_ok": audit_ok,
        "status": (
            "pre_submit_gate_ready_awaiting_explicit_approval"
            if audit_ok else "pre_submit_gate_inconsistent"
        ),
        "can_mark_goal_complete": False,
        "claim_boundary": {
            "audit": "target-MSA pre/post submission gate consistency only",
            "w2_multi_target_generalization": "not_supported",
            "proteinmpnn_boltz_panel_submission": "blocked_until_target_msa_outputs_sync_back_and_strict_require_files_passes",
        },
        "ready_for_target_msa_submission_if_explicitly_approved": audit_ok,
        "ready_for_panel_submission": False,
        "explicit_submit_approval_required": presubmit.get("explicit_submit_approval_required"),
        "target_msa_approval_env_var": _APPROVAL_ENV_VAR,
        "target_msa_approval_env_value": _APPROVAL_TOKEN,
        "anchor_goal_progress_mode": (
            "branch_v9_ready" if branch_goal_ready else
            "project_level_w2_ready" if project_level_goal_ready else
            "inconsistent"
        ),
        "submit_command_if_approved": presubmit.get("next_command_if_approved"),
        "postsubmit_sync_back_command": postsubmit.get("sync_back_command_after_jobs_finish"),
        "pending_paths": pending_paths_path,
        "pending_path_count": len(pending),
        "target_count": len(target_ids),
        "completion_counts": {
            "n_artifacts": completion.get("n_artifacts"),
            "n_nonempty": completion.get("n_nonempty"),
            "n_missing": completion.get("n_missing"),
            "n_empty": completion.get("n_empty"),
        },
        "manifest_counts": {
            "n_targets": manifest.get("n_targets"),
            "n_ready_targets": manifest.get("n_ready_targets"),
            "n_failures": len(manifest_failures),
        },
        "expected_pending_fields": ["target_msa", "target_msa_report"],
        "observed_pending_fields": _pending_fields(completion),
        "failures": failures,
        "next_action": (
            "await explicit approval; if approved, run the recorded target-MSA command on Cayuga, then run the recorded sync-back command"
            if audit_ok
            else "repair the gate artifacts before submitting target-MSA jobs"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Target-MSA Gate Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a gate-consistency audit only. It does not certify W2 and does not submit jobs.",
        "",
        "| item | value |",
        "|---|---:|",
        f"| targets | {rep.get('target_count')} |",
        f"| pending paths | {rep.get('pending_path_count')} |",
        f"| nonempty input-prep artifacts | {rep.get('completion_counts', {}).get('n_nonempty')} |",
        f"| missing input-prep artifacts | {rep.get('completion_counts', {}).get('n_missing')} |",
        f"| strict-manifest failures | {rep.get('manifest_counts', {}).get('n_failures')} |",
        "",
        f"Next action: {rep.get('next_action')}",
        "",
        "Submit command if explicitly approved:",
        "",
        "```bash",
        str(rep.get("submit_command_if_approved") or ""),
        "```",
        "",
        "Sync-back command after jobs finish:",
        "",
        "```bash",
        str(rep.get("postsubmit_sync_back_command") or ""),
        "```",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anchor", default="results/m6d_goal_mode_current_anchor.json")
    ap.add_argument("--presubmit-preflight", default="results/m6d_w2_target_family_redesign_v9_target_msa_presubmit_preflight.json")
    ap.add_argument("--pre-sync-completion", default="results/m6d_w2_target_family_redesign_v9_input_prep_completion_pre_sync.json")
    ap.add_argument("--postsubmit-plan", default="results/m6d_w2_target_family_redesign_v9_postsubmit_replay_plan.json")
    ap.add_argument("--manifest-post-msa", default="results/m6d_w2_target_family_redesign_v9_manifest_post_msa_require_files.json")
    ap.add_argument("--pending-paths", default="results/m6d_w2_target_family_redesign_v9_pending_input_prep_paths.txt")
    ap.add_argument("--sync-back-script", default="results/m6d_w2_target_family_redesign_v9_msa_sync_back.sh")
    ap.add_argument("--expected-targets", type=int, default=14)
    ap.add_argument("--expected-pending-paths", type=int, default=28)
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(
        _load_json(args.anchor),
        _load_json(args.presubmit_preflight),
        _load_json(args.pre_sync_completion),
        _load_json(args.postsubmit_plan),
        _load_json(args.manifest_post_msa),
        _read_paths(args.pending_paths),
        pending_paths_path=args.pending_paths,
        sync_back_script=args.sync_back_script,
        expected_targets=args.expected_targets,
        expected_pending_paths=args.expected_pending_paths,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} targets={targets} pending={pending}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            targets=rep["target_count"],
            pending=rep["pending_path_count"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
