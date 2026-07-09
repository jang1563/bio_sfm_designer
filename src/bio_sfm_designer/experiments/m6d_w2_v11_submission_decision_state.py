"""Record the W2 v11 explicit panel-submission decision boundary.

This is a no-submit latch. It consolidates the approval packet, post-panel
decision protocol, remote readiness audit, project status, goal audits, and
submit-receipt absence checks into one machine-readable state. A passing state
means the panel is ready to submit only if the user explicitly approves it; it
does not submit jobs and does not create W2 evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


_DEFAULT_REMOTE_HOST = ""
_DEFAULT_REMOTE_ROOT = ""
_READY_STATUS = "awaiting_explicit_panel_submission_approval"
_BLOCKED_STATUS = "submission_decision_blocked"
_PROJECT_W2_READY_STATUS = "panel_approval_packet_ready_awaiting_explicit_approval"
_APPROVAL_READY_STATUS = "panel_approval_packet_ready"
_DECISION_READY_STATUS = "post_panel_decision_protocol_ready"
_REMOTE_READY_STATUS = "remote_submission_readiness_ok"
_NON_APPROVAL_CONTINUATIONS = [
    "resume goal",
    "resume goal mode",
    "goal mode resume",
    "go ahead",
    "continue",
    "continue working toward the active thread goal",
    "keep going",
    "이어서",
    "계속",
]
_DRIFT_READY_EXECUTIONS = {
    "panel_remote_readiness_ready_not_submitted",
    "panel_submission_decision_ready_not_submitted",
    "panel_postsync_interpretation_predeclared_not_synced",
}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
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


def _add_failure(
    failures: List[Dict[str, Any]],
    kind: str,
    message: str,
    *,
    expected: Any = None,
    observed: Any = None,
    path: Optional[str] = None,
) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    if path is not None:
        row["path"] = path
    failures.append(row)


def _field(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _workstream(project_status: Dict[str, Any], key: str) -> Dict[str, Any]:
    streams = project_status.get("workstreams")
    if isinstance(streams, dict) and isinstance(streams.get(key), dict):
        return streams[key]
    return {}


def _local_absence(paths: Iterable[str]) -> List[Dict[str, Any]]:
    rows = []
    for path in paths:
        rows.append({"path": path, "exists": os.path.exists(path), "scope": "local"})
    return rows


def _run_ssh(remote_host: str, command: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", remote_host, command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _remote_exists(remote_root: str, rel_path: str, *, remote_host: Optional[str], ssh_timeout: int) -> bool:
    if not remote_host:
        return os.path.exists(os.path.join(remote_root, rel_path))
    path = os.path.join(remote_root, rel_path)
    proc = _run_ssh(remote_host, "test -e " + shlex.quote(path), ssh_timeout)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())


def _remote_absence(
    paths: Iterable[str],
    *,
    remote_host: Optional[str],
    remote_root: str,
    ssh_timeout: int,
) -> List[Dict[str, Any]]:
    rows = []
    for rel_path in paths:
        row: Dict[str, Any] = {
            "path": rel_path,
            "scope": "remote",
            "remote_host": remote_host or "",
            "remote_root": remote_root,
        }
        try:
            row["exists"] = _remote_exists(remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout)
        except Exception as exc:
            row["exists"] = None
            row["error"] = str(exc)
        rows.append(row)
    return rows


def _strict_postsubmit_command_ok(command: Any, approval_packet: Dict[str, Any]) -> bool:
    text = str(command or "")
    required_flags = (
        "--manifest",
        "--receipt",
        "--summary",
        "--job-states",
        "--require-sync-ready",
        "--out-json",
    )
    required_paths = (
        approval_packet.get("manifest"),
        approval_packet.get("submit_receipt"),
        approval_packet.get("submit_summary"),
        approval_packet.get("postsubmit_status_before_sync"),
        approval_packet.get("job_state_probe_before_sync"),
    )
    return (
        "m6d_w2_panel_postsubmit_status" in text
        and all(flag in text for flag in required_flags)
        and all(str(path) in text for path in required_paths if path)
    )


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _approval_scope_ok(scope: Dict[str, Any], approval_packet: Dict[str, Any]) -> bool:
    checks = approval_packet.get("checks") if isinstance(approval_packet.get("checks"), dict) else {}
    n_ready = _int_or_none(scope.get("n_ready_targets"))
    n_targets = _int_or_none(scope.get("n_targets"))
    min_targets = _int_or_none(scope.get("min_targets"))
    records_per_target = _int_or_none(scope.get("records_per_target_planned"))
    planned_records = _int_or_none(scope.get("planned_design_records"))
    expected_job_pairs = _int_or_none(scope.get("expected_job_pairs"))
    expected_slurm_jobs = _int_or_none(scope.get("expected_slurm_jobs"))
    target_ids = scope.get("target_ids")
    return (
        bool(scope.get("manifest"))
        and isinstance(target_ids, list)
        and n_ready is not None
        and n_targets is not None
        and min_targets is not None
        and len(target_ids) == n_ready
        and n_ready == checks.get("panel_submit_ready_targets")
        and n_targets >= n_ready
        and n_ready >= min_targets
        and records_per_target is not None
        and records_per_target > 0
        and planned_records == n_ready * records_per_target
        and expected_job_pairs == n_ready
        and expected_slurm_jobs == n_ready * 2
        and scope.get("job_pair_model") == "ProteinMPNN -> Boltz"
        and scope.get("target_alpha") == approval_packet.get("target_alpha")
        and bool(scope.get("panel_out"))
        and bool(scope.get("completion_after_sync"))
        and bool(scope.get("sync_back_after_jobs_finish"))
        and scope.get("no_submit") is True
        and scope.get("can_claim_w2_generalization") is False
    )


def _approval_state(approval_packet: Dict[str, Any]) -> Dict[str, Any]:
    checks = approval_packet.get("checks") if isinstance(approval_packet.get("checks"), dict) else {}
    approval_scope = approval_packet.get("approval_scope") if isinstance(approval_packet.get("approval_scope"), dict) else {}
    required_checks = [
        "target_msa_strict_ready",
        "panel_preflight_ready",
        "panel_dry_run_no_sbatch",
        "panel_guard_no_env_refuses",
        "submit_receipt_absent",
        "submit_summary_absent",
        "approval_scope_ready",
    ]
    checks_ok = all(checks.get(key) is True for key in required_checks)
    approval_scope_ok = _approval_scope_ok(approval_scope, approval_packet)
    postsubmit_sync_ready_gate_ok = (
        bool(approval_packet.get("postsubmit_status_before_sync"))
        and bool(approval_packet.get("job_state_probe_before_sync"))
        and _strict_postsubmit_command_ok(approval_packet.get("postsubmit_sync_ready_gate"), approval_packet)
    )
    job_state_sync = str(approval_packet.get("job_state_probe_sync_after_query") or "")
    job_state_query_bridge_ok = (
        bool(approval_packet.get("job_state_query_after_receipt"))
        and bool(job_state_sync)
        and "rsync" in job_state_sync
        and str(approval_packet.get("job_state_probe_before_sync") or "") in job_state_sync
    )
    postsubmit_bridge_ok = (
        bool(approval_packet.get("receipt_monitor_after_submit"))
        and job_state_query_bridge_ok
        and bool(approval_packet.get("postsubmit_status_command_before_sync"))
        and _strict_postsubmit_command_ok(
            approval_packet.get("postsubmit_status_command_before_sync"),
            approval_packet,
        )
        and bool(approval_packet.get("postsync_replay_after_sync"))
    )
    ok = (
        approval_packet.get("status") == _APPROVAL_READY_STATUS
        and approval_packet.get("audit_ok") is True
        and approval_packet.get("approval_packet_ready") is True
        and approval_packet.get("can_submit_panel_if_user_explicitly_approves") is True
        and approval_packet.get("can_claim_w2_generalization") is False
        and checks_ok
        and approval_scope_ok
        and postsubmit_sync_ready_gate_ok
        and postsubmit_bridge_ok
    )
    return {
        "path": approval_packet.get("_path"),
        "status": approval_packet.get("status"),
        "ok": ok,
        "audit_ok": approval_packet.get("audit_ok"),
        "approval_packet_ready": approval_packet.get("approval_packet_ready"),
        "can_submit_panel_if_user_explicitly_approves": approval_packet.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization": approval_packet.get("can_claim_w2_generalization"),
        "panel_approval_env_var": approval_packet.get("panel_approval_env_var"),
        "panel_approval_env_value": approval_packet.get("panel_approval_env_value"),
        "submit_command_if_approved": approval_packet.get("submit_command_if_approved"),
        "sync_back_command_after_jobs_finish": approval_packet.get("sync_back_command_after_jobs_finish"),
        "postsubmit_status_before_sync": approval_packet.get("postsubmit_status_before_sync"),
        "job_state_probe_before_sync": approval_packet.get("job_state_probe_before_sync"),
        "receipt_monitor_after_submit": approval_packet.get("receipt_monitor_after_submit"),
        "job_state_query_after_receipt": approval_packet.get("job_state_query_after_receipt"),
        "job_state_probe_sync_after_query": approval_packet.get("job_state_probe_sync_after_query"),
        "job_state_query_bridge_ok": job_state_query_bridge_ok,
        "approval_scope": approval_scope,
        "approval_scope_ok": approval_scope_ok,
        "postsubmit_sync_ready_gate": approval_packet.get("postsubmit_sync_ready_gate"),
        "postsubmit_status_command_before_sync": approval_packet.get("postsubmit_status_command_before_sync"),
        "postsync_replay_after_sync": approval_packet.get("postsync_replay_after_sync"),
        "postsubmit_sync_ready_gate_ok": postsubmit_sync_ready_gate_ok,
        "postsubmit_bridge_ok": postsubmit_bridge_ok,
        "required_checks": {key: checks.get(key) for key in required_checks},
    }


def _panel_decision_state(panel_decision_protocol: Dict[str, Any]) -> Dict[str, Any]:
    current = (
        panel_decision_protocol.get("current_panel_result")
        if isinstance(panel_decision_protocol.get("current_panel_result"), dict)
        else {}
    )
    ok = (
        panel_decision_protocol.get("status") == _DECISION_READY_STATUS
        and panel_decision_protocol.get("audit_ok") is True
        and panel_decision_protocol.get("no_submit") is True
        and panel_decision_protocol.get("can_submit_panel_if_user_explicitly_approves") is True
        and panel_decision_protocol.get("can_claim_w2_generalization_now") is False
        and current.get("status") == "not_available_not_submitted"
        and current.get("w2_generalization_supported") is False
    )
    return {
        "path": panel_decision_protocol.get("_path"),
        "status": panel_decision_protocol.get("status"),
        "ok": ok,
        "audit_ok": panel_decision_protocol.get("audit_ok"),
        "no_submit": panel_decision_protocol.get("no_submit"),
        "can_submit_panel_if_user_explicitly_approves": panel_decision_protocol.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization_now": panel_decision_protocol.get("can_claim_w2_generalization_now"),
        "current_panel_result_status": current.get("status"),
        "current_panel_result_w2_supported": current.get("w2_generalization_supported"),
        "next_action": panel_decision_protocol.get("next_action"),
    }


def _remote_readiness_state(remote_readiness: Dict[str, Any]) -> Dict[str, Any]:
    absence_checks = remote_readiness.get("absence_checks")
    absence_rows = absence_checks if isinstance(absence_checks, list) else []
    absence_ok = bool(absence_rows) and all(isinstance(row, dict) and row.get("ok") is True for row in absence_rows)
    shell_syntax_checks = remote_readiness.get("shell_syntax_checks")
    shell_syntax_rows = shell_syntax_checks if isinstance(shell_syntax_checks, list) else []
    shell_syntax_ok = (
        bool(shell_syntax_rows)
        and all(
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("local_returncode") == 0
            and row.get("remote_returncode") == 0
            for row in shell_syntax_rows
        )
    )
    ok = (
        remote_readiness.get("status") == _REMOTE_READY_STATUS
        and remote_readiness.get("audit_ok") is True
        and remote_readiness.get("no_submit") is True
        and remote_readiness.get("can_submit_panel_if_user_explicitly_approves") is True
        and remote_readiness.get("can_claim_w2_generalization") is False
        and remote_readiness.get("n_failures") == 0
        and absence_ok
        and shell_syntax_ok
    )
    return {
        "path": remote_readiness.get("_path"),
        "status": remote_readiness.get("status"),
        "ok": ok,
        "audit_ok": remote_readiness.get("audit_ok"),
        "no_submit": remote_readiness.get("no_submit"),
        "can_submit_panel_if_user_explicitly_approves": remote_readiness.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization": remote_readiness.get("can_claim_w2_generalization"),
        "n_exact_checks": remote_readiness.get("n_exact_checks"),
        "n_semantic_checks": remote_readiness.get("n_semantic_checks"),
        "n_absence_checks": remote_readiness.get("n_absence_checks"),
        "n_shell_syntax_checks": remote_readiness.get("n_shell_syntax_checks"),
        "n_failures": remote_readiness.get("n_failures"),
        "absence_checks_ok": absence_ok,
        "shell_syntax_checks_ok": shell_syntax_ok,
        "remote_host": remote_readiness.get("remote_host"),
        "remote_root": remote_readiness.get("remote_root"),
    }


def _project_status_state(project_status: Dict[str, Any]) -> Dict[str, Any]:
    w2 = _workstream(project_status, "W2_multi_target_panel")
    ok = (
        project_status.get("status") == "m6_complex_in_progress"
        and project_status.get("complete") is False
        and project_status.get("can_mark_goal_complete") is False
        and w2.get("status") == _PROJECT_W2_READY_STATUS
        and w2.get("complete") is False
        and w2.get("panel_approval_packet_ready") is True
        and w2.get("panel_decision_protocol_ready") is True
        and w2.get("panel_remote_submission_readiness_ok") is True
        and isinstance(w2.get("panel_remote_shell_syntax_checks"), int)
        and w2.get("panel_remote_shell_syntax_checks") > 0
    )
    return {
        "path": project_status.get("_path"),
        "status": project_status.get("status"),
        "ok": ok,
        "complete": project_status.get("complete"),
        "can_mark_goal_complete": project_status.get("can_mark_goal_complete"),
        "w2_status": w2.get("status"),
        "w2_complete": w2.get("complete"),
        "w2_panel_approval_packet_ready": w2.get("panel_approval_packet_ready"),
        "w2_panel_decision_protocol_ready": w2.get("panel_decision_protocol_ready"),
        "w2_panel_remote_submission_readiness_ok": w2.get("panel_remote_submission_readiness_ok"),
        "w2_panel_remote_shell_syntax_checks": w2.get("panel_remote_shell_syntax_checks"),
        "w2_panel_submit_command_if_approved": w2.get("panel_submit_command_if_approved"),
    }


def _completion_audit_state(goal_completion_audit: Dict[str, Any]) -> Dict[str, Any]:
    workflow_step_count = _field(
        goal_completion_audit,
        "w2_gate.panel_public_approval_bundle_workflow_step_count",
    )
    workflow_all_commands_present = _field(
        goal_completion_audit,
        "w2_gate.panel_public_approval_bundle_workflow_all_commands_present",
    )
    workflow_sync_ready_before_record_sync = _field(
        goal_completion_audit,
        "w2_gate.panel_public_approval_bundle_workflow_sync_ready_before_record_sync",
    )
    workflow_includes_postsync = _field(
        goal_completion_audit,
        "w2_gate.panel_public_approval_bundle_workflow_includes_postsync_interpretation",
    )
    workflow_driver_sync_ready_only = _field(
        goal_completion_audit,
        "w2_gate.panel_public_approval_bundle_workflow_driver_sync_ready_only",
    )
    ok = (
        goal_completion_audit.get("status") == "goal_active_w2_remaining"
        and goal_completion_audit.get("audit_ok") is True
        and goal_completion_audit.get("complete") is False
        and goal_completion_audit.get("can_mark_goal_complete") is False
        and _field(goal_completion_audit, "w2_gate.panel_remote_no_submit") is True
        and _field(goal_completion_audit, "w2_gate.panel_remote_failures") == 0
        and _field(goal_completion_audit, "w2_gate.panel_public_approval_bundle_ready") is True
        and workflow_step_count == 9
        and workflow_all_commands_present is True
        and workflow_sync_ready_before_record_sync is True
        and workflow_includes_postsync is True
        and workflow_driver_sync_ready_only is True
    )
    return {
        "path": goal_completion_audit.get("_path"),
        "status": goal_completion_audit.get("status"),
        "ok": ok,
        "audit_ok": goal_completion_audit.get("audit_ok"),
        "complete": goal_completion_audit.get("complete"),
        "can_mark_goal_complete": goal_completion_audit.get("can_mark_goal_complete"),
        "w2_panel_remote_no_submit": _field(goal_completion_audit, "w2_gate.panel_remote_no_submit"),
        "w2_panel_remote_failures": _field(goal_completion_audit, "w2_gate.panel_remote_failures"),
        "w2_panel_public_approval_bundle_ready": _field(
            goal_completion_audit,
            "w2_gate.panel_public_approval_bundle_ready",
        ),
        "w2_panel_public_approval_bundle_workflow_step_count": workflow_step_count,
        "w2_panel_public_approval_bundle_workflow_all_commands_present": workflow_all_commands_present,
        "w2_panel_public_approval_bundle_workflow_sync_ready_before_record_sync": (
            workflow_sync_ready_before_record_sync
        ),
        "w2_panel_public_approval_bundle_workflow_includes_postsync_interpretation": workflow_includes_postsync,
        "w2_panel_public_approval_bundle_workflow_driver_sync_ready_only": workflow_driver_sync_ready_only,
    }


def _drift_audit_state(goal_drift_audit: Dict[str, Any]) -> Dict[str, Any]:
    ok = (
        goal_drift_audit.get("status") == "no_major_direction_drift_w2_blocked"
        and goal_drift_audit.get("audit_ok") is True
        and goal_drift_audit.get("major_direction_drift") is False
        and goal_drift_audit.get("can_mark_goal_complete") is False
        and _field(goal_drift_audit, "drift_assessment.execution") in _DRIFT_READY_EXECUTIONS
    )
    return {
        "path": goal_drift_audit.get("_path"),
        "status": goal_drift_audit.get("status"),
        "ok": ok,
        "audit_ok": goal_drift_audit.get("audit_ok"),
        "major_direction_drift": goal_drift_audit.get("major_direction_drift"),
        "can_mark_goal_complete": goal_drift_audit.get("can_mark_goal_complete"),
        "execution": _field(goal_drift_audit, "drift_assessment.execution"),
    }


def _collect_state_failures(failures: List[Dict[str, Any]], states: Dict[str, Dict[str, Any]]) -> None:
    for key, state in states.items():
        if state.get("ok") is not True:
            _add_failure(
                failures,
                key + "_not_ready",
                f"{key} does not satisfy the W2 v11 submission-decision boundary",
                observed=state,
                path=state.get("path"),
            )


def build_decision_state(
    *,
    approval_packet: Dict[str, Any],
    panel_decision_protocol: Dict[str, Any],
    remote_readiness: Dict[str, Any],
    project_status: Dict[str, Any],
    goal_completion_audit: Dict[str, Any],
    goal_drift_audit: Dict[str, Any],
    local_absent_paths: Iterable[str],
    remote_absent_paths: Iterable[str] = (),
    remote_host: Optional[str] = None,
    remote_root: str = _DEFAULT_REMOTE_ROOT,
    check_remote_receipts: bool = False,
    ssh_timeout: int = 30,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    states = {
        "approval_packet": _approval_state(approval_packet),
        "panel_decision_protocol": _panel_decision_state(panel_decision_protocol),
        "remote_submission_readiness": _remote_readiness_state(remote_readiness),
        "project_status": _project_status_state(project_status),
        "goal_completion_audit": _completion_audit_state(goal_completion_audit),
        "goal_drift_audit": _drift_audit_state(goal_drift_audit),
    }
    _collect_state_failures(failures, states)

    local_receipts = _local_absence(local_absent_paths)
    for row in local_receipts:
        if row.get("exists") is not False:
            _add_failure(
                failures,
                "submit_receipt_or_summary_present",
                "local submit receipt or summary exists; this is no longer a pre-submit decision state",
                observed=row,
                path=row.get("path"),
            )

    remote_receipts: List[Dict[str, Any]] = []
    if check_remote_receipts:
        remote_receipts = _remote_absence(
            remote_absent_paths,
            remote_host=remote_host,
            remote_root=remote_root,
            ssh_timeout=ssh_timeout,
        )
        for row in remote_receipts:
            if row.get("exists") is not False:
                _add_failure(
                    failures,
                    "remote_submit_receipt_or_summary_present_or_unknown",
                    "remote submit receipt or summary exists, or the remote absence check failed",
                    observed=row,
                    path=row.get("path"),
                )

    audit_ok = not failures
    approval = states["approval_packet"]
    return {
        "artifact": "m6d_w2_v11_submission_decision_state",
        "date": date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "decision": "awaiting_explicit_approval" if audit_ok else "blocked",
        "audit_ok": audit_ok,
        "no_submit": True,
        "submitted": False,
        "explicit_approval_required": True,
        "can_submit_if_explicitly_approved": audit_ok,
        "can_claim_w2_generalization": False,
        "approval": {
            "required_env_var": approval.get("panel_approval_env_var"),
            "required_env_value": approval.get("panel_approval_env_value"),
            "submit_command_if_approved": approval.get("submit_command_if_approved"),
            "sync_back_command_after_jobs_finish": approval.get("sync_back_command_after_jobs_finish"),
        },
        "approval_scope": approval.get("approval_scope"),
        "approval_disambiguation": {
            "continuation_phrases_are_approval": False,
            "non_approval_continuation_phrases": list(_NON_APPROVAL_CONTINUATIONS),
            "approval_must_explicitly_name": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "approval_must_acknowledge": [
                "run the guarded Cayuga panel submit command",
                "create submit receipt and Slurm jobs",
                "spend GPU/compute before sync-back and target-wise certification",
            ],
            "machine_gate": (
                str(approval.get("panel_approval_env_var") or "")
                + "="
                + str(approval.get("panel_approval_env_value") or "")
            ),
        },
        "prerequisites": states,
        "receipt_absence": {
            "local": local_receipts,
            "remote_checked": check_remote_receipts,
            "remote": remote_receipts,
            "remote_host": remote_host or "",
            "remote_root": remote_root,
        },
        "claim_boundary": {
            "decision_state": "records readiness for an explicit approval decision only",
            "panel_submission": "not approved by this artifact; still requires an explicit user submit decision",
            "job_launch": "not evidence; receipt and job IDs only prove execution started",
            "w2_generalization": "not supported until synced records pass completion and target-wise panel certification",
        },
        "next_action": (
            "await explicit user approval before running submit_command_if_approved"
            if audit_ok else
            "repair submission-decision blockers before any W2 v11 panel submission"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 v11 Submission Decision State",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Decision: `{rep.get('decision')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        f"Explicit approval required: `{rep.get('explicit_approval_required')}`.",
        f"Can submit if explicitly approved: `{rep.get('can_submit_if_explicitly_approved')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        "## Prerequisites",
        "",
        "| prerequisite | ok | status |",
        "|---|---:|---|",
    ]
    prerequisites = rep.get("prerequisites") if isinstance(rep.get("prerequisites"), dict) else {}
    for key, state in prerequisites.items():
        status = state.get("status") or state.get("execution") or ""
        lines.append(f"| {key} | {state.get('ok')} | {status} |")

    receipt_absence = rep.get("receipt_absence") if isinstance(rep.get("receipt_absence"), dict) else {}
    lines.extend(["", "## Receipt Absence", ""])
    for row in receipt_absence.get("local") or []:
        lines.append(f"- local `{row.get('path')}` exists: `{row.get('exists')}`")
    if receipt_absence.get("remote_checked"):
        remote_host = receipt_absence.get("remote_host") or ""
        remote_root = receipt_absence.get("remote_root") or ""
        lines.append(f"- remote checked: `{remote_host}:{remote_root}`")
        for row in receipt_absence.get("remote") or []:
            lines.append(f"- remote `{row.get('path')}` exists: `{row.get('exists')}`")
    else:
        lines.append("- direct remote receipt check: `False`")

    approval = rep.get("approval") if isinstance(rep.get("approval"), dict) else {}
    scope = rep.get("approval_scope") if isinstance(rep.get("approval_scope"), dict) else {}
    lines.extend([
        "",
        "## Approval Scope",
        "",
        f"- manifest: `{scope.get('manifest')}`",
        f"- targets: `{scope.get('n_ready_targets')}` ready of `{scope.get('n_targets')}` total",
        f"- target ids: `{', '.join(scope.get('target_ids') or [])}`",
        f"- planned designs: `{scope.get('planned_design_records')}` "
        f"({scope.get('records_per_target_planned')} per target)",
        f"- expected Slurm jobs: `{scope.get('expected_slurm_jobs')}` "
        f"(`{scope.get('job_pair_model')}` pairs)",
        f"- target alpha: `{scope.get('target_alpha')}`",
        "",
        "## Approval Boundary",
        "",
        f"- required env: `{approval.get('required_env_var')}={approval.get('required_env_value')}`",
        "- submit command if explicitly approved:",
        "",
        "```bash",
        str(approval.get("submit_command_if_approved") or ""),
        "```",
        "",
        "Postsubmit sync-ready gate before record sync-back:",
        "",
        "```bash",
        str((prerequisites.get("approval_packet") or {}).get("postsubmit_sync_ready_gate") or ""),
        "```",
        "",
        "This artifact does not submit jobs and does not create W2 evidence.",
        "",
    ])
    disambiguation = (
        rep.get("approval_disambiguation")
        if isinstance(rep.get("approval_disambiguation"), dict)
        else {}
    )
    non_approval = disambiguation.get("non_approval_continuation_phrases") or []
    lines.extend([
        "## Approval Disambiguation",
        "",
        f"- continuation phrases are approval: `{disambiguation.get('continuation_phrases_are_approval')}`",
        f"- approval must explicitly name: `{disambiguation.get('approval_must_explicitly_name')}`",
        f"- machine gate: `{disambiguation.get('machine_gate')}`",
        "- non-approval continuation phrases: " + ", ".join(f"`{phrase}`" for phrase in non_approval),
        "",
    ])
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
        lines.append("")
    lines.extend(["## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--approval-packet", default="results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json")
    ap.add_argument("--panel-decision-protocol", default="results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json")
    ap.add_argument("--remote-readiness", default="results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json")
    ap.add_argument("--project-status", default="results/m6c_project_status_w2_followup.json")
    ap.add_argument("--goal-completion-audit", default="results/m6d_goal_completion_audit.json")
    ap.add_argument("--goal-drift-audit", default="results/m6d_goal_drift_audit.json")
    ap.add_argument("--local-absent-path", action="append", default=None)
    ap.add_argument("--remote-absent-path", action="append", default=None)
    ap.add_argument("--remote-host", default=os.environ.get("CAYUGA_BIO_SFM_HOST", _DEFAULT_REMOTE_HOST))
    ap.add_argument("--remote-root", default=os.environ.get("CAYUGA_BIO_SFM_ROOT", _DEFAULT_REMOTE_ROOT))
    ap.add_argument("--check-remote-receipts", action="store_true")
    ap.add_argument("--ssh-timeout", type=int, default=30)
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v11_submission_decision_state.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v11_submission_decision_state.md")
    args = ap.parse_args(argv)
    if args.check_remote_receipts and not args.remote_root:
        ap.error("--remote-root or CAYUGA_BIO_SFM_ROOT is required with --check-remote-receipts")

    local_absent_paths = args.local_absent_path or [
        "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
    ]
    remote_absent_paths = args.remote_absent_path or [
        "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
    ]
    rep = build_decision_state(
        approval_packet=_load_json(args.approval_packet),
        panel_decision_protocol=_load_json(args.panel_decision_protocol),
        remote_readiness=_load_json(args.remote_readiness),
        project_status=_load_json(args.project_status),
        goal_completion_audit=_load_json(args.goal_completion_audit),
        goal_drift_audit=_load_json(args.goal_drift_audit),
        local_absent_paths=local_absent_paths,
        remote_absent_paths=remote_absent_paths,
        remote_host=args.remote_host or None,
        remote_root=args.remote_root,
        check_remote_receipts=args.check_remote_receipts,
        ssh_timeout=args.ssh_timeout,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} decision={decision} no_submit={no_submit} submitted={submitted}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            decision=rep["decision"],
            no_submit=rep["no_submit"],
            submitted=rep["submitted"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
