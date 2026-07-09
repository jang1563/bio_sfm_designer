"""Audit M6d goal completion boundaries without submitting work.

This helper is intentionally conservative: a passing audit can still report
``can_mark_goal_complete=false``. Its purpose is to prove that the current
goal-mode state is honest: W1, W3, and W4 are preserved as completed evidence,
while W2 remains the only open requirement until the approved target-MSA,
sync-back, and strict replay path actually finishes.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


_W1_STATUS = "certified"
_W2_STATUS = "target_msa_gate_ready_awaiting_explicit_approval"
_W2_PANEL_APPROVAL_PROJECT_STATUS = "panel_approval_packet_ready_awaiting_explicit_approval"
_W2_OPEN_STATUSES = {_W2_STATUS, _W2_PANEL_APPROVAL_PROJECT_STATUS}
_W3_STATUS = "negative_robustness_result_adjudicated"
_W4_STATUS = "closed_loop_round_complete"
_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_TARGET_MSA"
_APPROVAL_TOKEN = "approve-v9-target-msa-precompute"
_EXECUTION_BLOCKED_STATUS = "blocked_before_submission_ssh_banner_exchange_timeout"
_EXECUTION_SUBMITTED_STATUS = "target_msa_jobs_submitted_waiting_on_completion"
_EXECUTION_SYNCED_STATUS = "target_msa_outputs_synced_strict_require_files_passed"
_PANEL_APPROVAL_READY_STATUS = "panel_approval_packet_ready"
_PANEL_DECISION_READY_STATUS = "post_panel_decision_protocol_ready"
_PANEL_REMOTE_READY_STATUS = "remote_submission_readiness_ok"
_PANEL_SUBMISSION_DECISION_READY_STATUS = "awaiting_explicit_panel_submission_approval"
_PANEL_POSTSYNC_NOT_SYNCED_STATUS = "not_synced_not_interpretable"
_PANEL_POSTSYNC_SUPPORTED_STATUS = "w2_generalization_supported_by_target_wise_panel"
_PANEL_PUBLIC_APPROVAL_BUNDLE_STATUS = "public_approval_bundle_ready_not_submitted"
_PANEL_OPERATOR_APPROVAL_PHRASE = "W2 v11 Cayuga ProteinMPNN/Boltz panel submission"
_PANEL_OPERATOR_MACHINE_GATE = "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit"
_PANEL_OPERATOR_POSTSUBMIT_DRIVER_COMMAND = (
    "bash results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh"
)
_PANEL_OPERATOR_POSTSYNC_REPLAY_COMMAND = (
    "bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh"
)
_PANEL_OPERATOR_PLANNED_DESIGN_RECORDS = 700
_PANEL_OPERATOR_EXPECTED_SLURM_JOBS = 14
_PANEL_OPERATOR_TARGET_ALPHA = 0.2
_POSTSUBMIT_DRIVER_POLLING_CONTRACT = {
    "max_polls_env_var": "M6D_W2_POSTSUBMIT_MAX_POLLS",
    "default_max_polls": 120,
    "poll_seconds_env_var": "M6D_W2_POSTSUBMIT_POLL_SECONDS",
    "default_poll_seconds": 300,
    "proceeds_only_when_sync_ready": True,
    "sync_ready_gate": "m6d_w2_panel_postsubmit_status.sync_ready",
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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _workstream(project_status: Dict[str, Any], key: str) -> Dict[str, Any]:
    streams = project_status.get("workstreams")
    if isinstance(streams, dict) and isinstance(streams.get(key), dict):
        return streams[key]
    return {}


def _receipt_state(path: Optional[str]) -> Dict[str, Any]:
    if not isinstance(path, str) or not path.strip():
        return {"path": path, "exists": None}
    return {"path": path, "exists": os.path.exists(path)}


def _execution_state(execution_attempt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(execution_attempt, dict):
        return {
            "path": None,
            "status": "not_provided",
            "approved_but_blocked_before_submission": False,
            "target_msa_jobs_submitted_waiting_on_completion": False,
            "target_msa_outputs_synced_strict_require_files_passed": False,
        }
    jobs_submitted = execution_attempt.get("jobs_submitted")
    sync_back = execution_attempt.get("sync_back") if isinstance(execution_attempt.get("sync_back"), dict) else {}
    state = {
        "path": execution_attempt.get("_path"),
        "status": execution_attempt.get("status"),
        "approval_scope": execution_attempt.get("approval_scope"),
        "last_checked_at": execution_attempt.get("last_checked_at"),
        "submitted_at": execution_attempt.get("submitted_at"),
        "submission_started": execution_attempt.get("submission_started"),
        "jobs_submitted": jobs_submitted,
        "job_ids": execution_attempt.get("job_ids"),
        "receipt_created_or_updated": execution_attempt.get("receipt_created_or_updated"),
        "receipt_summary": execution_attempt.get("receipt_summary"),
        "queue_status": execution_attempt.get("queue_status"),
        "sync_back": sync_back,
        "next_action": execution_attempt.get("next_action"),
        "approved_but_blocked_before_submission": (
            execution_attempt.get("status") == _EXECUTION_BLOCKED_STATUS
            and execution_attempt.get("submission_started") is False
            and execution_attempt.get("jobs_submitted") == 0
            and execution_attempt.get("receipt_created_or_updated") is False
        ),
        "target_msa_jobs_submitted_waiting_on_completion": (
            execution_attempt.get("status") == _EXECUTION_SUBMITTED_STATUS
            and execution_attempt.get("submission_started") is True
            and jobs_submitted == 14
            and execution_attempt.get("receipt_created_or_updated") is True
        ),
        "target_msa_outputs_synced_strict_require_files_passed": (
            execution_attempt.get("status") == _EXECUTION_SYNCED_STATUS
            and execution_attempt.get("submission_started") is True
            and execution_attempt.get("receipt_created_or_updated") is True
            and sync_back.get("completed") is True
            and sync_back.get("strict_require_files_ok") is True
            and sync_back.get("ready_targets") == 14
            and sync_back.get("post_sync_pending_path_count") == 0
        ),
    }
    return state


def _panel_approval_state(panel_approval_packet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_approval_packet, dict):
        return {
            "path": None,
            "status": "not_provided",
            "approval_packet_ready": False,
            "can_submit_panel_if_user_explicitly_approves": False,
            "can_claim_w2_generalization": None,
        }
    checks = panel_approval_packet.get("checks") if isinstance(panel_approval_packet.get("checks"), dict) else {}
    approval_scope = (
        panel_approval_packet.get("approval_scope")
        if isinstance(panel_approval_packet.get("approval_scope"), dict)
        else {}
    )
    return {
        "path": panel_approval_packet.get("_path"),
        "status": panel_approval_packet.get("status"),
        "approval_packet_ready": panel_approval_packet.get("approval_packet_ready"),
        "can_submit_panel_if_user_explicitly_approves": panel_approval_packet.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization": panel_approval_packet.get("can_claim_w2_generalization"),
        "panel_approval_env_var": panel_approval_packet.get("panel_approval_env_var"),
        "panel_approval_env_value": panel_approval_packet.get("panel_approval_env_value"),
        "submit_command_if_approved": panel_approval_packet.get("submit_command_if_approved"),
        "manifest": panel_approval_packet.get("manifest"),
        "submit_receipt": panel_approval_packet.get("submit_receipt"),
        "submit_summary": panel_approval_packet.get("submit_summary"),
        "sync_back_command_after_jobs_finish": panel_approval_packet.get("sync_back_command_after_jobs_finish"),
        "postsubmit_status_before_sync": panel_approval_packet.get("postsubmit_status_before_sync"),
        "job_state_probe_before_sync": panel_approval_packet.get("job_state_probe_before_sync"),
        "receipt_monitor_after_submit": panel_approval_packet.get("receipt_monitor_after_submit"),
        "job_state_query_after_receipt": panel_approval_packet.get("job_state_query_after_receipt"),
        "job_state_probe_sync_after_query": panel_approval_packet.get("job_state_probe_sync_after_query"),
        "postsubmit_sync_ready_gate": panel_approval_packet.get("postsubmit_sync_ready_gate"),
        "postsubmit_status_command_before_sync": panel_approval_packet.get("postsubmit_status_command_before_sync"),
        "postsync_replay_after_sync": panel_approval_packet.get("postsync_replay_after_sync"),
        "approval_scope": approval_scope,
        "approval_scope_ok": _approval_scope_ok(approval_scope, target_alpha=panel_approval_packet.get("target_alpha")),
        "checks": checks,
        "target_msa_strict_ready": checks.get("target_msa_strict_ready"),
        "panel_dry_run_no_sbatch": checks.get("panel_dry_run_no_sbatch"),
        "panel_guard_no_env_refuses": checks.get("panel_guard_no_env_refuses"),
        "submit_receipt_absent": checks.get("submit_receipt_absent"),
        "submit_summary_absent": checks.get("submit_summary_absent"),
    }


def _strict_postsubmit_command_ok(command: Any, panel_approval: Dict[str, Any]) -> bool:
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
        panel_approval.get("manifest"),
        panel_approval.get("submit_receipt"),
        panel_approval.get("submit_summary"),
        panel_approval.get("postsubmit_status_before_sync"),
        panel_approval.get("job_state_probe_before_sync"),
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


def _approval_scope_ok(scope: Dict[str, Any], *, target_alpha: Any = None) -> bool:
    n_ready = _int_or_none(scope.get("n_ready_targets"))
    n_targets = _int_or_none(scope.get("n_targets"))
    min_targets = _int_or_none(scope.get("min_targets"))
    records_per_target = _int_or_none(scope.get("records_per_target_planned"))
    planned_records = _int_or_none(scope.get("planned_design_records"))
    expected_job_pairs = _int_or_none(scope.get("expected_job_pairs"))
    expected_slurm_jobs = _int_or_none(scope.get("expected_slurm_jobs"))
    target_ids = scope.get("target_ids")
    alpha_ok = True if target_alpha is None else scope.get("target_alpha") == target_alpha
    return (
        bool(scope.get("manifest"))
        and isinstance(target_ids, list)
        and n_ready is not None
        and n_targets is not None
        and min_targets is not None
        and len(target_ids) == n_ready
        and n_targets >= n_ready
        and n_ready >= min_targets
        and records_per_target is not None
        and records_per_target > 0
        and planned_records == n_ready * records_per_target
        and expected_job_pairs == n_ready
        and expected_slurm_jobs == n_ready * 2
        and scope.get("job_pair_model") == "ProteinMPNN -> Boltz"
        and alpha_ok
        and bool(scope.get("panel_out"))
        and bool(scope.get("completion_after_sync"))
        and bool(scope.get("sync_back_after_jobs_finish"))
        and scope.get("no_submit") is True
        and scope.get("can_claim_w2_generalization") is False
    )


def _project_status_approval_scope(project_status_w2: Dict[str, Any]) -> Dict[str, Any]:
    n_ready = _int_or_none(project_status_w2.get("panel_approval_scope_n_ready_targets"))
    records_per_target = _int_or_none(project_status_w2.get("panel_approval_scope_records_per_target_planned"))
    planned_records = _int_or_none(project_status_w2.get("panel_approval_scope_planned_design_records"))
    expected_jobs = _int_or_none(project_status_w2.get("panel_approval_scope_expected_slurm_jobs"))
    ok = (
        project_status_w2.get("panel_approval_scope_ready") is True
        and n_ready is not None
        and n_ready > 0
        and records_per_target is not None
        and records_per_target > 0
        and planned_records == n_ready * records_per_target
        and expected_jobs == n_ready * 2
        and project_status_w2.get("panel_approval_scope_target_alpha") == 0.2
    )
    return {
        "ready": project_status_w2.get("panel_approval_scope_ready"),
        "ok": ok,
        "n_ready_targets": project_status_w2.get("panel_approval_scope_n_ready_targets"),
        "records_per_target_planned": project_status_w2.get(
            "panel_approval_scope_records_per_target_planned"
        ),
        "planned_design_records": project_status_w2.get("panel_approval_scope_planned_design_records"),
        "expected_slurm_jobs": project_status_w2.get("panel_approval_scope_expected_slurm_jobs"),
        "target_alpha": project_status_w2.get("panel_approval_scope_target_alpha"),
    }


def _postsubmit_driver_polling_ok(polling: Dict[str, Any]) -> bool:
    return all(polling.get(key) == expected for key, expected in _POSTSUBMIT_DRIVER_POLLING_CONTRACT.items())


def _panel_decision_state(panel_decision_protocol: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_decision_protocol, dict):
        return {
            "path": None,
            "status": "not_provided",
            "audit_ok": False,
            "no_submit": None,
            "can_claim_w2_generalization_now": None,
            "current_result_status": None,
            "current_result_w2_supported": None,
        }
    current = (
        panel_decision_protocol.get("current_panel_result")
        if isinstance(panel_decision_protocol.get("current_panel_result"), dict)
        else {}
    )
    contract = (
        panel_decision_protocol.get("panel_contract")
        if isinstance(panel_decision_protocol.get("panel_contract"), dict)
        else {}
    )
    return {
        "path": panel_decision_protocol.get("_path"),
        "status": panel_decision_protocol.get("status"),
        "audit_ok": panel_decision_protocol.get("audit_ok"),
        "no_submit": panel_decision_protocol.get("no_submit"),
        "can_claim_w2_generalization_now": panel_decision_protocol.get("can_claim_w2_generalization_now"),
        "current_result_status": current.get("status"),
        "current_result_w2_supported": current.get("w2_generalization_supported"),
        "target_alpha": contract.get("target_alpha"),
        "n_manifest_targets": contract.get("n_manifest_targets"),
        "min_targets": contract.get("min_targets"),
        "min_records_per_target": contract.get("min_records_per_target"),
        "next_action": panel_decision_protocol.get("next_action"),
    }


def _panel_remote_readiness_state(panel_remote_readiness: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_remote_readiness, dict):
        return {
            "path": None,
            "status": "not_provided",
            "audit_ok": False,
            "no_submit": None,
            "can_submit_panel_if_user_explicitly_approves": None,
            "can_claim_w2_generalization": None,
        }
    shell_syntax_checks = panel_remote_readiness.get("shell_syntax_checks")
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
    return {
        "path": panel_remote_readiness.get("_path"),
        "status": panel_remote_readiness.get("status"),
        "audit_ok": panel_remote_readiness.get("audit_ok"),
        "no_submit": panel_remote_readiness.get("no_submit"),
        "can_submit_panel_if_user_explicitly_approves": panel_remote_readiness.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization": panel_remote_readiness.get("can_claim_w2_generalization"),
        "n_exact_checks": panel_remote_readiness.get("n_exact_checks"),
        "n_semantic_checks": panel_remote_readiness.get("n_semantic_checks"),
        "n_absence_checks": panel_remote_readiness.get("n_absence_checks"),
        "n_shell_syntax_checks": panel_remote_readiness.get("n_shell_syntax_checks"),
        "shell_syntax_checks_ok": shell_syntax_ok,
        "n_failures": panel_remote_readiness.get("n_failures"),
        "next_action": panel_remote_readiness.get("next_action"),
    }


def _receipt_absence_rows_ok(rows: Any) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    return all(isinstance(row, dict) and row.get("exists") is False for row in rows)


def _operator_approval_checklist_state(checklist: Any) -> Dict[str, Any]:
    if not isinstance(checklist, dict):
        return {
            "present": False,
            "ok": False,
            "checks": {"present": False},
        }
    checks = {
        "present": True,
        "pre_submit_state_ok": checklist.get("pre_submit_state_ok") is True,
        "submit_allowed_by_this_artifact": checklist.get("submit_allowed_by_this_artifact") is True,
        "submission_performed_by_this_artifact": (
            checklist.get("submission_performed_by_this_artifact") is False
        ),
        "approval_phrase_required": (
            checklist.get("approval_phrase_required") == _PANEL_OPERATOR_APPROVAL_PHRASE
        ),
        "continuation_phrases_are_approval": (
            checklist.get("continuation_phrases_are_approval") is False
        ),
        "machine_gate": checklist.get("machine_gate") == _PANEL_OPERATOR_MACHINE_GATE,
        "postsubmit_driver_command": (
            checklist.get("postsubmit_driver_command") == _PANEL_OPERATOR_POSTSUBMIT_DRIVER_COMMAND
        ),
        "postsync_replay_command": (
            checklist.get("postsync_replay_command") == _PANEL_OPERATOR_POSTSYNC_REPLAY_COMMAND
        ),
        "driver_replay_command_pair_ready": checklist.get("driver_replay_command_pair_ready") is True,
        "local_receipts_absent": checklist.get("local_receipts_absent") is True,
        "remote_receipts_checked": checklist.get("remote_receipts_checked") is True,
        "remote_receipts_absent": checklist.get("remote_receipts_absent") is True,
        "planned_design_records": (
            checklist.get("planned_design_records") == _PANEL_OPERATOR_PLANNED_DESIGN_RECORDS
        ),
        "expected_slurm_jobs": (
            checklist.get("expected_slurm_jobs") == _PANEL_OPERATOR_EXPECTED_SLURM_JOBS
        ),
        "target_alpha": checklist.get("target_alpha") == _PANEL_OPERATOR_TARGET_ALPHA,
        "no_submit": checklist.get("no_submit") is True,
        "submitted": checklist.get("submitted") is False,
        "can_claim_w2_generalization": checklist.get("can_claim_w2_generalization") is False,
    }
    return {
        "present": True,
        "ok": all(checks.values()),
        "checks": checks,
        "pre_submit_state_ok": checklist.get("pre_submit_state_ok"),
        "submit_allowed_by_this_artifact": checklist.get("submit_allowed_by_this_artifact"),
        "submission_performed_by_this_artifact": checklist.get("submission_performed_by_this_artifact"),
        "approval_phrase_required": checklist.get("approval_phrase_required"),
        "continuation_phrases_are_approval": checklist.get("continuation_phrases_are_approval"),
        "machine_gate": checklist.get("machine_gate"),
        "postsubmit_driver_command": checklist.get("postsubmit_driver_command"),
        "postsync_replay_command": checklist.get("postsync_replay_command"),
        "driver_replay_command_pair_ready": checklist.get("driver_replay_command_pair_ready"),
        "local_receipts_absent": checklist.get("local_receipts_absent"),
        "remote_receipts_checked": checklist.get("remote_receipts_checked"),
        "remote_receipts_absent": checklist.get("remote_receipts_absent"),
        "planned_design_records": checklist.get("planned_design_records"),
        "expected_slurm_jobs": checklist.get("expected_slurm_jobs"),
        "target_alpha": checklist.get("target_alpha"),
        "no_submit": checklist.get("no_submit"),
        "submitted": checklist.get("submitted"),
        "can_claim_w2_generalization": checklist.get("can_claim_w2_generalization"),
    }


def _panel_submission_decision_state(panel_submission_decision_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_submission_decision_state, dict):
        return {
            "path": None,
            "status": "not_provided",
            "audit_ok": False,
            "no_submit": None,
            "submitted": None,
            "can_claim_w2_generalization": None,
        }
    receipt_absence = (
        panel_submission_decision_state.get("receipt_absence")
        if isinstance(panel_submission_decision_state.get("receipt_absence"), dict)
        else {}
    )
    remote_checked = receipt_absence.get("remote_checked") is True
    operator = _operator_approval_checklist_state(
        panel_submission_decision_state.get("operator_approval_checklist")
    )
    return {
        "path": panel_submission_decision_state.get("_path"),
        "status": panel_submission_decision_state.get("status"),
        "decision": panel_submission_decision_state.get("decision"),
        "audit_ok": panel_submission_decision_state.get("audit_ok"),
        "no_submit": panel_submission_decision_state.get("no_submit"),
        "submitted": panel_submission_decision_state.get("submitted"),
        "explicit_approval_required": panel_submission_decision_state.get("explicit_approval_required"),
        "can_submit_if_explicitly_approved": panel_submission_decision_state.get(
            "can_submit_if_explicitly_approved"
        ),
        "can_claim_w2_generalization": panel_submission_decision_state.get("can_claim_w2_generalization"),
        "remote_checked": remote_checked,
        "local_receipt_absence_ok": _receipt_absence_rows_ok(receipt_absence.get("local")),
        "remote_receipt_absence_ok": remote_checked and _receipt_absence_rows_ok(receipt_absence.get("remote")),
        "operator_checklist_present": operator.get("present"),
        "operator_checklist_ok": operator.get("ok"),
        "operator_checklist_checks": operator.get("checks"),
        "operator_pre_submit_state_ok": operator.get("pre_submit_state_ok"),
        "operator_submit_allowed_by_this_artifact": operator.get("submit_allowed_by_this_artifact"),
        "operator_submission_performed_by_this_artifact": operator.get("submission_performed_by_this_artifact"),
        "operator_approval_phrase_required": operator.get("approval_phrase_required"),
        "operator_continuation_phrases_are_approval": operator.get("continuation_phrases_are_approval"),
        "operator_machine_gate": operator.get("machine_gate"),
        "operator_postsubmit_driver_command": operator.get("postsubmit_driver_command"),
        "operator_postsync_replay_command": operator.get("postsync_replay_command"),
        "operator_driver_replay_command_pair_ready": operator.get("driver_replay_command_pair_ready"),
        "operator_local_receipts_absent": operator.get("local_receipts_absent"),
        "operator_remote_receipts_checked": operator.get("remote_receipts_checked"),
        "operator_remote_receipts_absent": operator.get("remote_receipts_absent"),
        "operator_planned_design_records": operator.get("planned_design_records"),
        "operator_expected_slurm_jobs": operator.get("expected_slurm_jobs"),
        "operator_target_alpha": operator.get("target_alpha"),
        "operator_no_submit": operator.get("no_submit"),
        "operator_submitted": operator.get("submitted"),
        "operator_can_claim_w2_generalization": operator.get("can_claim_w2_generalization"),
        "n_failures": len(panel_submission_decision_state.get("failures") or []),
        "next_action": panel_submission_decision_state.get("next_action"),
    }


def _panel_postsync_interpretation_state(panel_postsync_interpretation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_postsync_interpretation, dict):
        return {
            "path": None,
            "status": "not_provided",
            "audit_ok": False,
            "no_submit": None,
            "submitted": None,
            "sync_ready": None,
            "can_claim_w2_generalization": None,
        }
    current = (
        panel_postsync_interpretation.get("current_panel_result")
        if isinstance(panel_postsync_interpretation.get("current_panel_result"), dict)
        else {}
    )
    return {
        "path": panel_postsync_interpretation.get("_path"),
        "status": panel_postsync_interpretation.get("status"),
        "audit_ok": panel_postsync_interpretation.get("audit_ok"),
        "no_submit": panel_postsync_interpretation.get("no_submit"),
        "submitted": panel_postsync_interpretation.get("submitted"),
        "sync_ready": panel_postsync_interpretation.get("sync_ready"),
        "can_claim_w2_generalization": panel_postsync_interpretation.get("can_claim_w2_generalization"),
        "current_result_status": current.get("status"),
        "target_alpha": panel_postsync_interpretation.get("target_alpha"),
        "min_targets": panel_postsync_interpretation.get("min_targets"),
        "min_records_per_target": panel_postsync_interpretation.get("min_records_per_target"),
        "n_failures": len(panel_postsync_interpretation.get("failures") or []),
        "next_action": panel_postsync_interpretation.get("next_action"),
    }


def _panel_public_approval_bundle_state(panel_public_approval_bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(panel_public_approval_bundle, dict):
        return {
            "path": None,
            "status": "not_provided",
            "audit_ok": False,
            "no_submit": None,
            "submitted": None,
            "can_claim_w2_generalization": None,
            "explicit_approval_required": None,
        }
    approval = (
        panel_public_approval_bundle.get("approval_boundary")
        if isinstance(panel_public_approval_bundle.get("approval_boundary"), dict)
        else {}
    )
    target = (
        panel_public_approval_bundle.get("target_contract")
        if isinstance(panel_public_approval_bundle.get("target_contract"), dict)
        else {}
    )
    approval_scope = (
        panel_public_approval_bundle.get("approval_scope")
        if isinstance(panel_public_approval_bundle.get("approval_scope"), dict)
        else {}
    )
    commands = (
        panel_public_approval_bundle.get("portable_commands")
        if isinstance(panel_public_approval_bundle.get("portable_commands"), dict)
        else {}
    )
    prereqs = (
        panel_public_approval_bundle.get("prerequisites")
        if isinstance(panel_public_approval_bundle.get("prerequisites"), dict)
        else {}
    )
    workflow = (
        panel_public_approval_bundle.get("post_approval_workflow")
        if isinstance(panel_public_approval_bundle.get("post_approval_workflow"), dict)
        else {}
    )
    polling = (
        panel_public_approval_bundle.get("postsubmit_driver_polling")
        if isinstance(panel_public_approval_bundle.get("postsubmit_driver_polling"), dict)
        else {}
    )
    remote = (
        prereqs.get("remote_readiness")
        if isinstance(prereqs.get("remote_readiness"), dict)
        else {}
    )
    return {
        "path": panel_public_approval_bundle.get("_path"),
        "status": panel_public_approval_bundle.get("status"),
        "audit_ok": panel_public_approval_bundle.get("audit_ok"),
        "no_submit": panel_public_approval_bundle.get("no_submit"),
        "submitted": panel_public_approval_bundle.get("submitted"),
        "can_claim_w2_generalization": panel_public_approval_bundle.get("can_claim_w2_generalization"),
        "explicit_approval_required": approval.get("explicit_approval_required"),
        "continuation_phrases_are_approval": approval.get("continuation_phrases_are_approval"),
        "approval_must_explicitly_name": approval.get("approval_must_explicitly_name"),
        "machine_gate": approval.get("machine_gate"),
        "manifest": target.get("manifest"),
        "target_alpha": target.get("target_alpha"),
        "approval_scope": approval_scope,
        "approval_scope_ok": _approval_scope_ok(approval_scope, target_alpha=target.get("target_alpha")),
        "strict_postsubmit_status_before_sync": commands.get("strict_postsubmit_status_before_sync"),
        "submit_if_explicitly_approved": commands.get("submit_if_explicitly_approved"),
        "remote_readiness_status": remote.get("status"),
        "remote_readiness_exact_checks": remote.get("n_exact_checks"),
        "remote_readiness_shell_syntax_checks": remote.get("n_shell_syntax_checks"),
        "remote_readiness_shell_syntax_checks_ok": remote.get("shell_syntax_checks_ok"),
        "remote_readiness_failures": remote.get("n_failures"),
        "workflow_manual_step_count": workflow.get("manual_step_count"),
        "workflow_all_manual_commands_present": workflow.get("all_manual_commands_present"),
        "workflow_requires_sync_ready_before_record_sync": workflow.get(
            "requires_sync_ready_before_record_sync"
        ),
        "workflow_includes_receipt_monitor": workflow.get("includes_receipt_monitor"),
        "workflow_includes_job_state_query": workflow.get("includes_job_state_query"),
        "workflow_includes_sync_back": workflow.get("includes_sync_back"),
        "workflow_includes_completion": workflow.get("includes_completion"),
        "workflow_includes_postsync_interpretation": workflow.get("includes_postsync_interpretation"),
        "workflow_driver_command_present": workflow.get("driver_command_present"),
        "workflow_driver_command_expected": workflow.get("driver_command_expected"),
        "workflow_postsync_replay_command_expected": workflow.get("postsync_replay_command_expected"),
        "workflow_driver_replay_command_pair_ready": workflow.get("driver_replay_command_pair_ready"),
        "workflow_driver_polling_contract_ok": (
            workflow.get("driver_polling_contract_ok") is True
            and _postsubmit_driver_polling_ok(polling)
        ),
        "workflow_postsubmit_driver_static_chain_ok": workflow.get(
            "postsubmit_driver_static_chain_ok"
        ),
        "workflow_postsync_replay_static_chain_ok": workflow.get(
            "postsync_replay_static_chain_ok"
        ),
        "workflow_sync_back_static_chain_ok": workflow.get("sync_back_static_chain_ok"),
        "workflow_completion_static_chain_ok": workflow.get("completion_static_chain_ok"),
        "workflow_script_chain_static_ok": workflow.get("script_chain_static_ok"),
        "workflow_driver_polling_max_polls_env_var": polling.get("max_polls_env_var"),
        "workflow_driver_polling_default_max_polls": polling.get("default_max_polls"),
        "workflow_driver_polling_poll_seconds_env_var": polling.get("poll_seconds_env_var"),
        "workflow_driver_polling_default_poll_seconds": polling.get("default_poll_seconds"),
        "workflow_driver_polling_sync_ready_gate": polling.get("sync_ready_gate"),
        "workflow_driver_proceeds_only_when_sync_ready": workflow.get(
            "driver_proceeds_only_when_sync_ready"
        ),
        "n_failures": len(panel_public_approval_bundle.get("failures") or []),
    }


def build_audit(project_status: Dict[str, Any],
                approval_packet: Dict[str, Any],
                approval_parity: Dict[str, Any],
                wrapper_guard: Dict[str, Any],
                w3_adjudication_audit: Dict[str, Any],
                execution_attempt: Optional[Dict[str, Any]] = None,
                panel_approval_packet: Optional[Dict[str, Any]] = None,
                panel_decision_protocol: Optional[Dict[str, Any]] = None,
                panel_remote_readiness: Optional[Dict[str, Any]] = None,
                panel_submission_decision_state: Optional[Dict[str, Any]] = None,
                panel_postsync_interpretation: Optional[Dict[str, Any]] = None,
                panel_public_approval_bundle: Optional[Dict[str, Any]] = None,
                *,
                v9_receipt: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    w1 = _workstream(project_status, "W1_M6c_scale_up")
    w2 = _workstream(project_status, "W2_multi_target_panel")
    w3 = _workstream(project_status, "W3_independent_predictor")
    w4 = _workstream(project_status, "W4_closed_loop_DBTL")

    if w1.get("status") != _W1_STATUS or w1.get("complete") is not True:
        _add_failure(
            failures,
            "w1_not_preserved_certified",
            "W1 must remain preserved as target-specific certified evidence",
            expected={"status": _W1_STATUS, "complete": True},
            observed={"status": w1.get("status"), "complete": w1.get("complete")},
        )
    if w2.get("status") not in _W2_OPEN_STATUSES or w2.get("complete") is not False:
        _add_failure(
            failures,
            "w2_not_open_at_target_msa_gate",
            "W2 must remain open at an explicit target-MSA or panel approval boundary",
            expected={"status": sorted(_W2_OPEN_STATUSES), "complete": False},
            observed={"status": w2.get("status"), "complete": w2.get("complete")},
        )
    if w3.get("status") != _W3_STATUS or w3.get("complete") is not True:
        _add_failure(
            failures,
            "w3_not_preserved_negative_robustness",
            "W3 must remain preserved as an adjudicated negative robustness result",
            expected={"status": _W3_STATUS, "complete": True},
            observed={"status": w3.get("status"), "complete": w3.get("complete")},
        )
    if w3.get("positive_claim_supported") is not False:
        _add_failure(
            failures,
            "w3_positive_claim_leak",
            "W3 negative robustness status must not support a positive independent-predictor claim",
            expected=False,
            observed=w3.get("positive_claim_supported"),
        )
    if w4.get("status") != _W4_STATUS or w4.get("complete") is not True:
        _add_failure(
            failures,
            "w4_not_preserved_closed_loop",
            "W4 must remain preserved as completed closed-loop plumbing evidence",
            expected={"status": _W4_STATUS, "complete": True},
            observed={"status": w4.get("status"), "complete": w4.get("complete")},
        )

    if project_status.get("complete") is True or project_status.get("can_mark_goal_complete") is True:
        _add_failure(
            failures,
            "premature_goal_completion_claim",
            "The full goal cannot be marked complete while W2 remains open",
            expected={"complete": False, "can_mark_goal_complete": False},
            observed={
                "complete": project_status.get("complete"),
                "can_mark_goal_complete": project_status.get("can_mark_goal_complete"),
            },
        )
    if project_status.get("remaining") != 1:
        _add_failure(
            failures,
            "remaining_requirement_count_mismatch",
            "Current audited state should have exactly one remaining requirement: W2",
            expected=1,
            observed=project_status.get("remaining"),
        )

    if approval_packet.get("approval_packet_ready") is not True:
        _add_failure(failures, "w2_approval_packet_not_ready",
                     "W2 approval packet must be ready before target-MSA approval is requested")
    if approval_packet.get("can_submit_target_msa_if_user_explicitly_approves") is not True:
        _add_failure(failures, "w2_target_msa_not_approval_ready",
                     "W2 target-MSA path must be ready only under explicit approval")
    if approval_packet.get("can_submit_proteinmpnn_boltz_panel") is not False:
        _add_failure(failures, "w2_panel_submission_not_blocked",
                     "W2 panel submission must remain blocked before target-MSA sync-back and strict replay")
    if approval_packet.get("target_msa_approval_env_var") != _APPROVAL_ENV_VAR:
        _add_failure(failures, "w2_approval_env_var_mismatch",
                     "approval packet uses the wrong approval env var",
                     expected=_APPROVAL_ENV_VAR, observed=approval_packet.get("target_msa_approval_env_var"))
    if approval_packet.get("target_msa_approval_env_value") != _APPROVAL_TOKEN:
        _add_failure(failures, "w2_approval_token_mismatch",
                     "approval packet uses the wrong approval token",
                     expected=_APPROVAL_TOKEN, observed=approval_packet.get("target_msa_approval_env_value"))

    if approval_parity.get("parity_ok") is not True:
        _add_failure(failures, "w2_approval_parity_not_ok",
                     "local/Cayuga approval packet parity must pass")
    if approval_parity.get("panel_submission_blocked") is not True:
        _add_failure(failures, "w2_parity_panel_not_blocked",
                     "local/Cayuga parity must agree that panel submission is blocked")

    if wrapper_guard.get("audit_ok") is not True:
        _add_failure(failures, "w2_wrapper_guard_not_ok",
                     "W2 wrapper guard audit must pass")
    static_audit = wrapper_guard.get("static_audit") if isinstance(wrapper_guard.get("static_audit"), dict) else {}
    if static_audit.get("ok") is not True:
        _add_failure(failures, "w2_wrapper_static_guard_not_ok",
                     "W2 wrapper static guard must pass")
    no_env = wrapper_guard.get("no_env_run") if isinstance(wrapper_guard.get("no_env_run"), dict) else {}
    if no_env.get("ok") is not True or no_env.get("receipt_exists_after") is not False:
        _add_failure(
            failures,
            "w2_wrapper_no_env_guard_not_ok",
            "W2 wrapper must refuse without approval and leave the receipt absent",
            observed=no_env,
        )
    receipt = _receipt_state(v9_receipt)
    execution = _execution_state(execution_attempt)
    panel_approval = _panel_approval_state(panel_approval_packet)
    panel_decision = _panel_decision_state(panel_decision_protocol)
    panel_remote = _panel_remote_readiness_state(panel_remote_readiness)
    panel_submission_decision = _panel_submission_decision_state(panel_submission_decision_state)
    panel_postsync = _panel_postsync_interpretation_state(panel_postsync_interpretation)
    panel_public_bundle = _panel_public_approval_bundle_state(panel_public_approval_bundle)
    project_panel_scope = _project_status_approval_scope(w2)
    receipt_allowed = execution.get("target_msa_jobs_submitted_waiting_on_completion") is True
    receipt_allowed = receipt_allowed or execution.get("target_msa_outputs_synced_strict_require_files_passed") is True
    if receipt.get("exists") is not False and not receipt_allowed:
        _add_failure(
            failures,
            "w2_v9_receipt_unexpected_before_successful_execution",
            "The v9 target-MSA receipt must remain absent until target-MSA execution reaches receipt update",
            expected=False,
            observed=receipt.get("exists"),
        )
    if execution_attempt is not None:
        known_execution_state = (
            execution.get("approved_but_blocked_before_submission") is True
            or execution.get("target_msa_jobs_submitted_waiting_on_completion") is True
            or execution.get("target_msa_outputs_synced_strict_require_files_passed") is True
        )
        if not known_execution_state:
            _add_failure(
                failures,
                "w2_execution_attempt_state_unrecognized",
                "W2 execution attempt must be recorded as either pre-submission SSH-blocked or submitted-waiting",
                expected=[
                    {
                        "status": _EXECUTION_BLOCKED_STATUS,
                        "submission_started": False,
                        "jobs_submitted": 0,
                        "receipt_created_or_updated": False,
                    },
                    {
                        "status": _EXECUTION_SUBMITTED_STATUS,
                        "submission_started": True,
                        "jobs_submitted": 14,
                        "receipt_created_or_updated": True,
                    },
                    {
                        "status": _EXECUTION_SYNCED_STATUS,
                        "submission_started": True,
                        "receipt_created_or_updated": True,
                        "sync_back.completed": True,
                        "sync_back.strict_require_files_ok": True,
                        "sync_back.ready_targets": 14,
                        "sync_back.post_sync_pending_path_count": 0,
                    },
                ],
                observed={
                    "status": execution.get("status"),
                    "submission_started": execution.get("submission_started"),
                    "jobs_submitted": execution.get("jobs_submitted"),
                    "receipt_created_or_updated": execution.get("receipt_created_or_updated"),
                },
            )
        boundary = execution_attempt.get("claim_boundary") if isinstance(execution_attempt.get("claim_boundary"), dict) else {}
        if "blocked" not in str(boundary.get("proteinmpnn_boltz_panel_submission") or ""):
            _add_failure(
                failures,
                "w2_execution_attempt_panel_boundary_drift",
                "execution attempt must keep ProteinMPNN/Boltz panel submission blocked",
                expected="blocked",
                observed=boundary.get("proteinmpnn_boltz_panel_submission"),
            )
        if boundary.get("w2_multi_target_generalization") != "not_supported":
            _add_failure(
                failures,
                "w2_execution_attempt_generalization_claim_drift",
                "execution attempt must not support W2 multi-target generalization",
                expected="not_supported",
                observed=boundary.get("w2_multi_target_generalization"),
            )

    if panel_approval_packet is not None:
        v11_panel_sync = "v11" in str(panel_approval.get("sync_back_command_after_jobs_finish") or "")
        if panel_approval.get("status") != _PANEL_APPROVAL_READY_STATUS or panel_approval.get("approval_packet_ready") is not True:
            _add_failure(
                failures,
                "w2_panel_approval_packet_not_ready",
                "W2 panel approval packet must be ready before panel submission can be considered",
                expected={"status": _PANEL_APPROVAL_READY_STATUS, "approval_packet_ready": True},
                observed={
                    "status": panel_approval.get("status"),
                    "approval_packet_ready": panel_approval.get("approval_packet_ready"),
                },
            )
        if panel_approval.get("can_submit_panel_if_user_explicitly_approves") is not True:
            _add_failure(
                failures,
                "w2_panel_not_explicit_approval_ready",
                "W2 panel may only be ready under explicit approval",
                expected=True,
                observed=panel_approval.get("can_submit_panel_if_user_explicitly_approves"),
            )
        if panel_approval.get("can_claim_w2_generalization") is not False:
            _add_failure(
                failures,
                "w2_panel_approval_claim_leak",
                "W2 panel approval packet must not support a generalization claim",
                expected=False,
                observed=panel_approval.get("can_claim_w2_generalization"),
            )
        for key in (
            "target_msa_strict_ready",
            "panel_dry_run_no_sbatch",
            "panel_guard_no_env_refuses",
            "submit_receipt_absent",
            "submit_summary_absent",
        ):
            if panel_approval.get(key) is not True:
                _add_failure(
                    failures,
                    "w2_panel_approval_check_failed",
                    "W2 panel approval packet must preserve all no-submit guard checks",
                    expected={key: True},
                    observed={key: panel_approval.get(key)},
                )
        if v11_panel_sync and not panel_approval.get("postsubmit_status_before_sync"):
            _add_failure(
                failures,
                "w2_panel_approval_missing_postsubmit_status_gate",
                "W2 panel sync-back must require a postsubmit status artifact before record sync-back",
                expected="postsubmit_status_before_sync",
                observed=panel_approval.get("postsubmit_status_before_sync"),
            )
        if v11_panel_sync and not panel_approval.get("job_state_probe_before_sync"):
            _add_failure(
                failures,
                "w2_panel_approval_missing_job_state_probe_gate",
                "W2 panel sync-back must require job-state probe evidence before record sync-back",
                expected="job_state_probe_before_sync",
                observed=panel_approval.get("job_state_probe_before_sync"),
            )
        if v11_panel_sync and not panel_approval.get("receipt_monitor_after_submit"):
            _add_failure(
                failures,
                "w2_panel_approval_missing_receipt_monitor_bridge",
                "W2 panel approval packet must name the receipt-only monitor before record sync-back",
                expected="receipt_monitor_after_submit",
                observed=panel_approval.get("receipt_monitor_after_submit"),
            )
        if v11_panel_sync and not panel_approval.get("job_state_query_after_receipt"):
            _add_failure(
                failures,
                "w2_panel_approval_missing_job_state_query_bridge",
                "W2 panel approval packet must name the read-only job-state query step",
                expected="job_state_query_after_receipt",
                observed=panel_approval.get("job_state_query_after_receipt"),
            )
        job_state_sync = str(panel_approval.get("job_state_probe_sync_after_query") or "")
        if (
            v11_panel_sync
            and (
                not job_state_sync
                or "rsync" not in job_state_sync
                or str(panel_approval.get("job_state_probe_before_sync") or "") not in job_state_sync
            )
        ):
            _add_failure(
                failures,
                "w2_panel_approval_missing_job_state_probe_sync_bridge",
                "W2 panel approval packet must sync the remote job-state probe locally after the read-only query",
                expected="job_state_probe_sync_after_query",
                observed=panel_approval.get("job_state_probe_sync_after_query"),
            )
        if v11_panel_sync and not _strict_postsubmit_command_ok(
            panel_approval.get("postsubmit_sync_ready_gate"),
            panel_approval,
        ):
            _add_failure(
                failures,
                "w2_panel_approval_missing_sync_ready_gate",
                "W2 panel sync-back must fail closed unless postsubmit status is sync-ready for the explicit manifest/receipt/job-state paths",
                expected="strict postsubmit command with --manifest/--receipt/--summary/--job-states/--require-sync-ready/--out-json",
                observed=panel_approval.get("postsubmit_sync_ready_gate"),
            )
        if (
            v11_panel_sync
            and not _strict_postsubmit_command_ok(
                panel_approval.get("postsubmit_status_command_before_sync"),
                panel_approval,
            )
        ):
            _add_failure(
                failures,
                "w2_panel_approval_missing_postsubmit_command_bridge",
                "W2 panel approval packet must name the strict postsubmit status command before record sync-back",
                expected="strict postsubmit command with --manifest/--receipt/--summary/--job-states/--require-sync-ready/--out-json",
                observed=panel_approval.get("postsubmit_status_command_before_sync"),
            )
        if v11_panel_sync and not panel_approval.get("postsync_replay_after_sync"):
            _add_failure(
                failures,
                "w2_panel_approval_missing_postsync_replay_bridge",
                "W2 panel approval packet must name the post-sync replay path for report and interpretation",
                expected="postsync_replay_after_sync",
                observed=panel_approval.get("postsync_replay_after_sync"),
            )
        if v11_panel_sync and panel_approval.get("approval_scope_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_approval_scope_not_ready",
                "W2 v11 panel approval packet must bind explicit approval to a concrete target/design/job scope",
                expected=True,
                observed=panel_approval.get("approval_scope"),
            )
        if v11_panel_sync and project_panel_scope.get("ok") is not True:
            _add_failure(
                failures,
                "w2_project_status_panel_scope_not_ready",
                "Project status must expose the W2 v11 approval scope before the goal audit can stay ready",
                expected=True,
                observed=project_panel_scope,
            )

    if panel_decision_protocol is not None:
        if panel_decision.get("status") != _PANEL_DECISION_READY_STATUS or panel_decision.get("audit_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_decision_protocol_not_ready",
                "W2 post-panel decision protocol must be ready before panel interpretation",
                expected={"status": _PANEL_DECISION_READY_STATUS, "audit_ok": True},
                observed={"status": panel_decision.get("status"), "audit_ok": panel_decision.get("audit_ok")},
            )
        if panel_decision.get("no_submit") is not True:
            _add_failure(
                failures,
                "w2_panel_decision_protocol_submit_drift",
                "W2 post-panel decision protocol must remain no-submit",
                expected=True,
                observed=panel_decision.get("no_submit"),
            )
        if panel_decision.get("can_claim_w2_generalization_now") is not False:
            _add_failure(
                failures,
                "w2_panel_decision_protocol_claim_leak",
                "W2 post-panel decision protocol must not support a current W2 claim",
                expected=False,
                observed=panel_decision.get("can_claim_w2_generalization_now"),
            )
        if panel_decision.get("current_result_w2_supported") is not False:
            _add_failure(
                failures,
                "w2_panel_decision_current_result_claim_leak",
                "current panel result state must not support W2 generalization before panel records/report exist",
                expected=False,
                observed=panel_decision.get("current_result_w2_supported"),
            )
        min_targets = panel_decision.get("min_targets") or 4
        n_manifest_targets = panel_decision.get("n_manifest_targets")
        if (
            panel_decision.get("target_alpha") != 0.2
            or not isinstance(n_manifest_targets, int)
            or n_manifest_targets < min_targets
        ):
            _add_failure(
                failures,
                "w2_panel_decision_contract_drift",
                "W2 post-panel decision protocol must stay scoped to alpha=0.2 and enough manifest targets",
                expected={"target_alpha": 0.2, "n_manifest_targets": f">={min_targets}"},
                observed={
                    "target_alpha": panel_decision.get("target_alpha"),
                    "n_manifest_targets": n_manifest_targets,
                },
            )

    if panel_remote_readiness is not None:
        if panel_remote.get("status") != _PANEL_REMOTE_READY_STATUS or panel_remote.get("audit_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_remote_readiness_not_ok",
                "W2 remote mirror readiness must pass before guarded panel submission can be considered",
                expected={"status": _PANEL_REMOTE_READY_STATUS, "audit_ok": True},
                observed={"status": panel_remote.get("status"), "audit_ok": panel_remote.get("audit_ok")},
            )
        if panel_remote.get("no_submit") is not True:
            _add_failure(
                failures,
                "w2_panel_remote_readiness_submit_drift",
                "W2 remote readiness audit must remain no-submit",
                expected=True,
                observed=panel_remote.get("no_submit"),
            )
        if panel_remote.get("can_submit_panel_if_user_explicitly_approves") is not True:
            _add_failure(
                failures,
                "w2_panel_remote_not_explicit_approval_ready",
                "W2 remote readiness can only permit panel submission under explicit approval",
                expected=True,
                observed=panel_remote.get("can_submit_panel_if_user_explicitly_approves"),
            )
        if panel_remote.get("can_claim_w2_generalization") is not False:
            _add_failure(
                failures,
                "w2_panel_remote_readiness_claim_leak",
                "W2 remote readiness audit must not support a generalization claim",
                expected=False,
                observed=panel_remote.get("can_claim_w2_generalization"),
            )
        if panel_remote.get("n_failures") != 0:
            _add_failure(
                failures,
                "w2_panel_remote_readiness_failures_present",
                "W2 remote readiness audit must have zero failures",
                expected=0,
                observed=panel_remote.get("n_failures"),
            )
        if panel_remote.get("shell_syntax_checks_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_remote_shell_syntax_not_ok",
                "W2 remote readiness must prove local and Cayuga shell/sbatch syntax checks passed",
                expected=True,
                observed={
                    "shell_syntax_checks_ok": panel_remote.get("shell_syntax_checks_ok"),
                    "n_shell_syntax_checks": panel_remote.get("n_shell_syntax_checks"),
                },
            )

    if panel_submission_decision_state is not None:
        if (
            panel_submission_decision.get("status") != _PANEL_SUBMISSION_DECISION_READY_STATUS
            or panel_submission_decision.get("audit_ok") is not True
        ):
            _add_failure(
                failures,
                "w2_panel_submission_decision_not_ready",
                "W2 panel submission-decision state must pass before guarded panel submission can be considered",
                expected={"status": _PANEL_SUBMISSION_DECISION_READY_STATUS, "audit_ok": True},
                observed={
                    "status": panel_submission_decision.get("status"),
                    "audit_ok": panel_submission_decision.get("audit_ok"),
                },
            )
        if panel_submission_decision.get("decision") != "awaiting_explicit_approval":
            _add_failure(
                failures,
                "w2_panel_submission_decision_not_awaiting_explicit_approval",
                "W2 panel submission-decision state must remain at explicit-approval wait",
                expected="awaiting_explicit_approval",
                observed=panel_submission_decision.get("decision"),
            )
        if panel_submission_decision.get("no_submit") is not True:
            _add_failure(
                failures,
                "w2_panel_submission_decision_submit_drift",
                "W2 panel submission-decision state must remain no-submit",
                expected=True,
                observed=panel_submission_decision.get("no_submit"),
            )
        if panel_submission_decision.get("submitted") is not False:
            _add_failure(
                failures,
                "w2_panel_submission_decision_already_submitted",
                "W2 panel submission-decision state must still be pre-submit for this active goal state",
                expected=False,
                observed=panel_submission_decision.get("submitted"),
            )
        if panel_submission_decision.get("can_claim_w2_generalization") is not False:
            _add_failure(
                failures,
                "w2_panel_submission_decision_claim_leak",
                "W2 panel submission-decision state must not support a generalization claim",
                expected=False,
                observed=panel_submission_decision.get("can_claim_w2_generalization"),
            )
        if panel_submission_decision.get("local_receipt_absence_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_submission_decision_local_receipt_absence_not_verified",
                "W2 panel submission-decision state must verify local receipt absence",
                expected=True,
                observed=panel_submission_decision.get("local_receipt_absence_ok"),
            )
        if panel_submission_decision.get("remote_receipt_absence_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_submission_decision_remote_receipt_absence_not_verified",
                "W2 panel submission-decision state must verify remote receipt absence",
                expected=True,
                observed=panel_submission_decision.get("remote_receipt_absence_ok"),
            )
        if panel_submission_decision.get("operator_checklist_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_submission_decision_operator_checklist_not_ready",
                "W2 panel submission-decision state must expose a complete operator approval checklist",
                expected={
                    "approval_phrase_required": _PANEL_OPERATOR_APPROVAL_PHRASE,
                    "machine_gate": _PANEL_OPERATOR_MACHINE_GATE,
                    "postsubmit_driver_command": _PANEL_OPERATOR_POSTSUBMIT_DRIVER_COMMAND,
                    "postsync_replay_command": _PANEL_OPERATOR_POSTSYNC_REPLAY_COMMAND,
                    "planned_design_records": _PANEL_OPERATOR_PLANNED_DESIGN_RECORDS,
                    "expected_slurm_jobs": _PANEL_OPERATOR_EXPECTED_SLURM_JOBS,
                    "target_alpha": _PANEL_OPERATOR_TARGET_ALPHA,
                    "no_submit": True,
                    "submitted": False,
                    "can_claim_w2_generalization": False,
                },
                observed=panel_submission_decision.get("operator_checklist_checks"),
            )
        if panel_submission_decision.get("n_failures") != 0:
            _add_failure(
                failures,
                "w2_panel_submission_decision_failures_present",
                "W2 panel submission-decision state must have zero failures",
                expected=0,
                observed=panel_submission_decision.get("n_failures"),
            )

    if panel_postsync_interpretation is not None:
        allowed_statuses = {
            _PANEL_POSTSYNC_NOT_SYNCED_STATUS,
            "ready_for_target_wise_panel_report",
            _PANEL_POSTSYNC_SUPPORTED_STATUS,
            "w2_generalization_not_supported_target_wise",
            "panel_report_not_multi_target_proof",
        }
        if panel_postsync.get("status") not in allowed_statuses or panel_postsync.get("audit_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_postsync_interpretation_not_ready",
                "W2 post-sync interpretation must pass before it can govern W2 evidence",
                expected={"status": sorted(allowed_statuses), "audit_ok": True},
                observed={"status": panel_postsync.get("status"), "audit_ok": panel_postsync.get("audit_ok")},
            )
        if panel_postsync.get("no_submit") is not True:
            _add_failure(
                failures,
                "w2_panel_postsync_interpretation_submit_drift",
                "W2 post-sync interpretation must remain no-submit",
                expected=True,
                observed=panel_postsync.get("no_submit"),
            )
        if (
            panel_postsync.get("can_claim_w2_generalization") is True
            and panel_postsync.get("status") != _PANEL_POSTSYNC_SUPPORTED_STATUS
        ):
            _add_failure(
                failures,
                "w2_panel_postsync_interpretation_claim_leak",
                "W2 post-sync interpretation may only claim W2 generalization after target-wise support",
                expected=_PANEL_POSTSYNC_SUPPORTED_STATUS,
                observed={
                    "status": panel_postsync.get("status"),
                    "can_claim_w2_generalization": panel_postsync.get("can_claim_w2_generalization"),
                },
            )
        if panel_postsync.get("target_alpha") != 0.2:
            _add_failure(
                failures,
                "w2_panel_postsync_interpretation_alpha_drift",
                "W2 post-sync interpretation must stay scoped to alpha=0.2",
                expected=0.2,
                observed=panel_postsync.get("target_alpha"),
            )
        if panel_postsync.get("n_failures") != 0:
            _add_failure(
                failures,
                "w2_panel_postsync_interpretation_failures_present",
                "W2 post-sync interpretation must have zero failures",
                expected=0,
                observed=panel_postsync.get("n_failures"),
            )

    if panel_public_approval_bundle is not None:
        if (
            panel_public_bundle.get("status") != _PANEL_PUBLIC_APPROVAL_BUNDLE_STATUS
            or panel_public_bundle.get("audit_ok") is not True
        ):
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_not_ready",
                "W2 public approval bundle must pass before it can be used as the public handoff surface",
                expected={"status": _PANEL_PUBLIC_APPROVAL_BUNDLE_STATUS, "audit_ok": True},
                observed={
                    "status": panel_public_bundle.get("status"),
                    "audit_ok": panel_public_bundle.get("audit_ok"),
                },
            )
        for key, expected in (
            ("no_submit", True),
            ("submitted", False),
            ("can_claim_w2_generalization", False),
            ("explicit_approval_required", True),
            ("continuation_phrases_are_approval", False),
        ):
            if panel_public_bundle.get(key) is not expected:
                _add_failure(
                    failures,
                    "w2_panel_public_approval_bundle_boundary_drift",
                    "W2 public approval bundle must preserve the no-submit explicit-approval boundary",
                    expected={key: expected},
                    observed={key: panel_public_bundle.get(key)},
                )
        if panel_public_bundle.get("approval_must_explicitly_name") != "W2 v11 Cayuga ProteinMPNN/Boltz panel submission":
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_approval_name_drift",
                "W2 public approval bundle must retain the explicit approval phrase",
                expected="W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
                observed=panel_public_bundle.get("approval_must_explicitly_name"),
            )
        if panel_public_bundle.get("machine_gate") != "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit":
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_machine_gate_drift",
                "W2 public approval bundle must retain the guarded submit machine gate",
                expected="BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
                observed=panel_public_bundle.get("machine_gate"),
            )
        if panel_public_bundle.get("manifest") != panel_approval.get("manifest"):
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_manifest_drift",
                "W2 public approval bundle manifest must match the approval packet",
                expected=panel_approval.get("manifest"),
                observed=panel_public_bundle.get("manifest"),
            )
        if panel_public_bundle.get("target_alpha") != 0.2:
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_alpha_drift",
                "W2 public approval bundle must stay scoped to alpha=0.2",
                expected=0.2,
                observed=panel_public_bundle.get("target_alpha"),
            )
        if not _strict_postsubmit_command_ok(
            panel_public_bundle.get("strict_postsubmit_status_before_sync"),
            panel_approval,
        ):
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_missing_strict_postsubmit_command",
                "W2 public approval bundle must preserve the strict postsubmit status command",
                expected="strict postsubmit command with manifest/receipt/summary/job-state paths",
                observed=panel_public_bundle.get("strict_postsubmit_status_before_sync"),
            )
        if panel_public_bundle.get("n_failures") != 0:
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_failures_present",
                "W2 public approval bundle must have zero failures",
                expected=0,
                observed=panel_public_bundle.get("n_failures"),
            )
        if (
            panel_public_bundle.get("remote_readiness_status") != _PANEL_REMOTE_READY_STATUS
            or panel_public_bundle.get("remote_readiness_shell_syntax_checks_ok") is not True
            or panel_public_bundle.get("remote_readiness_failures") != 0
        ):
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_remote_readiness_drift",
                "W2 public approval bundle must include the current passing remote readiness syntax gate",
                expected={
                    "remote_readiness_status": _PANEL_REMOTE_READY_STATUS,
                    "remote_readiness_shell_syntax_checks_ok": True,
                    "remote_readiness_failures": 0,
                },
                observed={
                    "remote_readiness_status": panel_public_bundle.get("remote_readiness_status"),
                    "remote_readiness_shell_syntax_checks": panel_public_bundle.get(
                        "remote_readiness_shell_syntax_checks"
                    ),
                    "remote_readiness_shell_syntax_checks_ok": panel_public_bundle.get(
                        "remote_readiness_shell_syntax_checks_ok"
                    ),
                    "remote_readiness_failures": panel_public_bundle.get("remote_readiness_failures"),
                },
            )
        if (
            panel_public_bundle.get("workflow_manual_step_count") != 9
            or panel_public_bundle.get("workflow_all_manual_commands_present") is not True
            or panel_public_bundle.get("workflow_requires_sync_ready_before_record_sync") is not True
            or panel_public_bundle.get("workflow_includes_receipt_monitor") is not True
            or panel_public_bundle.get("workflow_includes_job_state_query") is not True
            or panel_public_bundle.get("workflow_includes_sync_back") is not True
            or panel_public_bundle.get("workflow_includes_completion") is not True
            or panel_public_bundle.get("workflow_includes_postsync_interpretation") is not True
            or panel_public_bundle.get("workflow_driver_command_present") is not True
            or panel_public_bundle.get("workflow_driver_command_expected") is not True
            or panel_public_bundle.get("workflow_postsync_replay_command_expected") is not True
            or panel_public_bundle.get("workflow_driver_replay_command_pair_ready") is not True
            or panel_public_bundle.get("workflow_driver_polling_contract_ok") is not True
            or panel_public_bundle.get("workflow_driver_proceeds_only_when_sync_ready") is not True
            or panel_public_bundle.get("workflow_postsubmit_driver_static_chain_ok") is not True
            or panel_public_bundle.get("workflow_postsync_replay_static_chain_ok") is not True
            or panel_public_bundle.get("workflow_sync_back_static_chain_ok") is not True
            or panel_public_bundle.get("workflow_completion_static_chain_ok") is not True
            or panel_public_bundle.get("workflow_script_chain_static_ok") is not True
        ):
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_workflow_incomplete",
                "W2 public approval bundle must preserve the full post-approval workflow through interpretation",
                expected={
                    "workflow_manual_step_count": 9,
                    "workflow_all_manual_commands_present": True,
                    "workflow_requires_sync_ready_before_record_sync": True,
                    "workflow_includes_receipt_monitor": True,
                    "workflow_includes_job_state_query": True,
                    "workflow_includes_sync_back": True,
                    "workflow_includes_completion": True,
                    "workflow_includes_postsync_interpretation": True,
                    "workflow_driver_command_present": True,
                    "workflow_driver_command_expected": True,
                    "workflow_postsync_replay_command_expected": True,
                    "workflow_driver_replay_command_pair_ready": True,
                    "workflow_driver_polling_contract_ok": True,
                    "workflow_driver_proceeds_only_when_sync_ready": True,
                    "workflow_postsubmit_driver_static_chain_ok": True,
                    "workflow_postsync_replay_static_chain_ok": True,
                    "workflow_sync_back_static_chain_ok": True,
                    "workflow_completion_static_chain_ok": True,
                    "workflow_script_chain_static_ok": True,
                },
                observed={
                    "workflow_manual_step_count": panel_public_bundle.get("workflow_manual_step_count"),
                    "workflow_all_manual_commands_present": panel_public_bundle.get(
                        "workflow_all_manual_commands_present"
                    ),
                    "workflow_requires_sync_ready_before_record_sync": panel_public_bundle.get(
                        "workflow_requires_sync_ready_before_record_sync"
                    ),
                    "workflow_includes_receipt_monitor": panel_public_bundle.get(
                        "workflow_includes_receipt_monitor"
                    ),
                    "workflow_includes_job_state_query": panel_public_bundle.get(
                        "workflow_includes_job_state_query"
                    ),
                    "workflow_includes_sync_back": panel_public_bundle.get("workflow_includes_sync_back"),
                    "workflow_includes_completion": panel_public_bundle.get("workflow_includes_completion"),
                    "workflow_includes_postsync_interpretation": panel_public_bundle.get(
                        "workflow_includes_postsync_interpretation"
                    ),
                    "workflow_driver_command_present": panel_public_bundle.get(
                        "workflow_driver_command_present"
                    ),
                    "workflow_driver_command_expected": panel_public_bundle.get(
                        "workflow_driver_command_expected"
                    ),
                    "workflow_postsync_replay_command_expected": panel_public_bundle.get(
                        "workflow_postsync_replay_command_expected"
                    ),
                    "workflow_driver_replay_command_pair_ready": panel_public_bundle.get(
                        "workflow_driver_replay_command_pair_ready"
                    ),
                    "workflow_driver_polling_contract_ok": panel_public_bundle.get(
                        "workflow_driver_polling_contract_ok"
                    ),
                    "workflow_driver_polling_sync_ready_gate": panel_public_bundle.get(
                        "workflow_driver_polling_sync_ready_gate"
                    ),
                    "workflow_driver_proceeds_only_when_sync_ready": panel_public_bundle.get(
                        "workflow_driver_proceeds_only_when_sync_ready"
                    ),
                    "workflow_postsubmit_driver_static_chain_ok": panel_public_bundle.get(
                        "workflow_postsubmit_driver_static_chain_ok"
                    ),
                    "workflow_postsync_replay_static_chain_ok": panel_public_bundle.get(
                        "workflow_postsync_replay_static_chain_ok"
                    ),
                    "workflow_sync_back_static_chain_ok": panel_public_bundle.get(
                        "workflow_sync_back_static_chain_ok"
                    ),
                    "workflow_completion_static_chain_ok": panel_public_bundle.get(
                        "workflow_completion_static_chain_ok"
                    ),
                    "workflow_script_chain_static_ok": panel_public_bundle.get(
                        "workflow_script_chain_static_ok"
                    ),
                },
            )
        if panel_public_bundle.get("approval_scope_ok") is not True:
            _add_failure(
                failures,
                "w2_panel_public_approval_bundle_scope_not_ready",
                "W2 public approval bundle must carry the concrete target/design/job approval scope",
                expected=True,
                observed=panel_public_bundle.get("approval_scope"),
            )

    if w3_adjudication_audit.get("audit_ok") is not True:
        _add_failure(failures, "w3_standalone_adjudication_audit_not_ok",
                     "standalone W3 adjudication audit must pass")
    if w3_adjudication_audit.get("positive_claim_supported") is not False:
        _add_failure(failures, "w3_standalone_positive_claim_leak",
                     "standalone W3 audit must not support a positive claim")
    artifact_audit = (
        w3_adjudication_audit.get("adjudication_set_artifact_audit")
        if isinstance(w3_adjudication_audit.get("adjudication_set_artifact_audit"), dict)
        else {}
    )
    if artifact_audit.get("ok") is not True or artifact_audit.get("n_rows") != 18:
        _add_failure(
            failures,
            "w3_standalone_adjudication_set_audit_not_ok",
            "standalone W3 audit must verify the 18-row adjudication set",
            observed=artifact_audit,
        )

    audit_ok = not failures
    w2_boundary = "not complete; target-MSA approval/sync/replay still required"
    next_action = "await explicit target-MSA approval; after approval run target-MSA prep, sync back, and replay strict gates"
    if execution.get("approved_but_blocked_before_submission"):
        w2_boundary = (
            "not complete; approved target-MSA prep is blocked before submission by SSH/login access; "
            "sync-back and strict replay still required"
        )
        next_action = (
            "restore working SSH/VPN/login-node access, rerun the approved W2 v9 full-14 target-MSA wrapper only, "
            "sync back outputs, and replay strict require-files; do not submit ProteinMPNN/Boltz panel jobs"
        )
    if execution.get("target_msa_jobs_submitted_waiting_on_completion"):
        w2_boundary = (
            "not complete; approved target-MSA prep jobs are submitted and waiting on completion; "
            "sync-back and strict replay still required"
        )
        next_action = (
            "wait for the submitted W2 v9 target-MSA jobs to finish, then sync back outputs and replay strict "
            "require-files; do not submit ProteinMPNN/Boltz panel jobs"
        )
    if execution.get("target_msa_outputs_synced_strict_require_files_passed"):
        w2_boundary = (
            "not complete; target-MSA outputs are synced and strict require-files passed for 14 targets; "
            "W2 still needs panel execution and target-wise certification"
        )
        next_action = (
            "prepare or run the next W2 v9 ProteinMPNN/Boltz panel step under the existing panel boundary; "
            "do not claim W2 generalization until target-wise panel certification passes"
        )
        if panel_approval.get("approval_packet_ready") is True:
            w2_boundary = (
                "not complete; target-MSA outputs are synced, strict require-files passed for 14 targets, "
                "and the W2 v9 panel approval packet is ready; W2 still needs explicit panel submission, "
                "sync-back, completion, and target-wise certification"
            )
            next_action = (
                "wait for explicit user approval before running the guarded W2 v9 panel submit command; "
                "do not claim W2 generalization until records sync back and target-wise panel certification passes"
            )
            if panel_decision.get("status") == _PANEL_DECISION_READY_STATUS:
                w2_boundary = (
                    "not complete; target-MSA outputs are synced, strict require-files passed for 14 targets, "
                    "the W2 v9 panel approval packet is ready, and the post-panel decision protocol is "
                    "predeclared; W2 still needs explicit panel submission, sync-back, completion, and "
                    "target-wise certification"
                )
                next_action = (
                    "wait for explicit user approval before running the guarded W2 v9 panel submit command; "
                    "then apply the predeclared post-panel decision protocol after sync-back and completion"
                )
                if panel_remote.get("status") == _PANEL_REMOTE_READY_STATUS:
                    w2_boundary = (
                        "not complete; panel approval, post-panel decision protocol, and remote submission "
                        "readiness are prepared; W2 still needs explicit panel submission, sync-back, "
                        "completion, and target-wise certification"
                    )
                    next_action = (
                        "wait for explicit user approval before running the guarded W2 panel submit command; "
                        "then apply the predeclared post-panel decision protocol after sync-back and completion"
                    )
                    if panel_submission_decision.get("status") == _PANEL_SUBMISSION_DECISION_READY_STATUS:
                        w2_boundary = (
                            "not complete; explicit panel-submission decision state is recorded as awaiting "
                            "approval with local/remote receipts absent; W2 still needs explicit panel "
                            "submission, sync-back, completion, and target-wise certification"
                        )
                        next_action = (
                            "wait for explicit user approval before running the recorded guarded W2 panel "
                            "submit command; then sync back, run completion, and apply target-wise certification"
                        )
                        if panel_postsync.get("status") == _PANEL_POSTSYNC_NOT_SYNCED_STATUS:
                            w2_boundary = (
                                "not complete; explicit panel-submission decision state is awaiting approval "
                                "and post-sync interpretation is predeclared as not yet interpretable; W2 still "
                                "needs explicit panel submission, sync-back, completion, target-wise reporting, "
                                "and alpha-gate interpretation"
                            )
                            next_action = (
                                "wait for explicit user approval before running the guarded W2 panel submit "
                                "command; after jobs finish, use the post-sync replay to sync back, run completion, "
                                "generate the target-wise panel report, and refresh interpretation"
                            )
    return {
        "artifact": "m6d_goal_completion_audit",
        "audit_ok": audit_ok,
        "status": "goal_active_w2_remaining" if audit_ok else "goal_completion_audit_blocked",
        "can_mark_goal_complete": False,
        "complete": False,
        "claim_boundary": {
            "w1": "target-specific certified evidence preserved",
            "w2": w2_boundary,
            "w3": "negative no-MSA Chai robustness result preserved; no positive independent-predictor claim",
            "w4": "closed-loop plumbing evidence preserved",
        },
        "remaining_requirements": ["W2_multi_target_panel"],
        "next_action": (
            next_action
            if audit_ok else
            "repair audit failures before continuing goal-mode execution"
        ),
        "project_status": project_status.get("_path"),
        "approval_packet": approval_packet.get("_path"),
        "approval_parity": approval_parity.get("_path"),
        "wrapper_guard": wrapper_guard.get("_path"),
        "w3_adjudication_audit": w3_adjudication_audit.get("_path"),
        "panel_approval_packet": panel_approval.get("path"),
        "v9_receipt": receipt,
        "w2_execution_attempt": execution,
        "w2_panel_approval": panel_approval,
        "w2_panel_decision_protocol": panel_decision,
        "w2_panel_remote_readiness": panel_remote,
        "w2_panel_submission_decision": panel_submission_decision,
        "w2_panel_postsync_interpretation": panel_postsync,
        "w2_panel_public_approval_bundle": panel_public_bundle,
        "workstream_status": {
            "W1_M6c_scale_up": {"status": w1.get("status"), "complete": w1.get("complete")},
            "W2_multi_target_panel": {"status": w2.get("status"), "complete": w2.get("complete")},
            "W3_independent_predictor": {
                "status": w3.get("status"),
                "complete": w3.get("complete"),
                "positive_claim_supported": w3.get("positive_claim_supported"),
            },
            "W4_closed_loop_DBTL": {"status": w4.get("status"), "complete": w4.get("complete")},
        },
        "w2_gate": {
            "approval_packet_ready": approval_packet.get("approval_packet_ready"),
            "approval_parity_ok": approval_parity.get("parity_ok"),
            "wrapper_guard_ok": wrapper_guard.get("audit_ok"),
            "panel_submission_blocked": approval_packet.get("can_submit_proteinmpnn_boltz_panel") is False,
            "target_msa_ready_if_explicitly_approved": approval_packet.get(
                "can_submit_target_msa_if_user_explicitly_approves"
            ),
            "target_msa_execution_status": execution.get("status"),
            "target_msa_jobs_submitted_waiting_on_completion": execution.get(
                "target_msa_jobs_submitted_waiting_on_completion"
            ),
            "target_msa_outputs_synced_strict_require_files_passed": execution.get(
                "target_msa_outputs_synced_strict_require_files_passed"
            ),
            "target_msa_approved_but_blocked_before_submission": execution.get(
                "approved_but_blocked_before_submission"
            ),
            "panel_approval_packet_ready": panel_approval.get("approval_packet_ready"),
            "panel_can_submit_if_explicitly_approved": panel_approval.get(
                "can_submit_panel_if_user_explicitly_approves"
            ),
            "panel_can_claim_w2_generalization": panel_approval.get("can_claim_w2_generalization"),
            "panel_guard_no_env_refuses": panel_approval.get("panel_guard_no_env_refuses"),
            "panel_postsubmit_status_before_sync": panel_approval.get("postsubmit_status_before_sync"),
            "panel_job_state_probe_before_sync": panel_approval.get("job_state_probe_before_sync"),
            "panel_receipt_monitor_after_submit": panel_approval.get("receipt_monitor_after_submit"),
            "panel_job_state_query_after_receipt": panel_approval.get("job_state_query_after_receipt"),
            "panel_postsubmit_sync_ready_gate": panel_approval.get("postsubmit_sync_ready_gate"),
            "panel_postsubmit_status_command_before_sync": panel_approval.get(
                "postsubmit_status_command_before_sync"
            ),
            "panel_postsync_replay_after_sync": panel_approval.get("postsync_replay_after_sync"),
            "panel_approval_scope_ready": panel_approval.get("approval_scope_ok"),
            "panel_approval_scope_planned_design_records": (
                panel_approval.get("approval_scope") or {}
            ).get("planned_design_records"),
            "panel_approval_scope_expected_slurm_jobs": (
                panel_approval.get("approval_scope") or {}
            ).get("expected_slurm_jobs"),
            "project_status_panel_approval_scope_ready": project_panel_scope.get("ok"),
            "project_status_panel_approval_scope_planned_design_records": project_panel_scope.get(
                "planned_design_records"
            ),
            "project_status_panel_approval_scope_expected_slurm_jobs": project_panel_scope.get(
                "expected_slurm_jobs"
            ),
            "panel_decision_protocol_ready": panel_decision.get("status") == _PANEL_DECISION_READY_STATUS,
            "panel_decision_no_submit": panel_decision.get("no_submit"),
            "panel_decision_can_claim_w2_now": panel_decision.get("can_claim_w2_generalization_now"),
            "panel_decision_current_result_status": panel_decision.get("current_result_status"),
            "panel_remote_readiness_ok": (
                panel_remote.get("status") == _PANEL_REMOTE_READY_STATUS
                and panel_remote.get("shell_syntax_checks_ok") is True
                and panel_remote.get("n_failures") == 0
            ),
            "panel_remote_no_submit": panel_remote.get("no_submit"),
            "panel_remote_can_submit_if_explicitly_approved": panel_remote.get(
                "can_submit_panel_if_user_explicitly_approves"
            ),
            "panel_remote_can_claim_w2_generalization": panel_remote.get("can_claim_w2_generalization"),
            "panel_remote_exact_checks": panel_remote.get("n_exact_checks"),
            "panel_remote_semantic_checks": panel_remote.get("n_semantic_checks"),
            "panel_remote_absence_checks": panel_remote.get("n_absence_checks"),
            "panel_remote_shell_syntax_checks": panel_remote.get("n_shell_syntax_checks"),
            "panel_remote_shell_syntax_checks_ok": panel_remote.get("shell_syntax_checks_ok"),
            "panel_remote_failures": panel_remote.get("n_failures"),
            "panel_submission_decision_ready": (
                panel_submission_decision.get("status") == _PANEL_SUBMISSION_DECISION_READY_STATUS
            ),
            "panel_submission_decision_no_submit": panel_submission_decision.get("no_submit"),
            "panel_submission_decision_submitted": panel_submission_decision.get("submitted"),
            "panel_submission_decision_can_claim_w2_generalization": panel_submission_decision.get(
                "can_claim_w2_generalization"
            ),
            "panel_submission_decision_remote_receipt_absence_ok": panel_submission_decision.get(
                "remote_receipt_absence_ok"
            ),
            "panel_submission_decision_operator_checklist_ok": panel_submission_decision.get(
                "operator_checklist_ok"
            ),
            "panel_submission_decision_operator_submit_allowed": panel_submission_decision.get(
                "operator_submit_allowed_by_this_artifact"
            ),
            "panel_submission_decision_operator_submission_performed": panel_submission_decision.get(
                "operator_submission_performed_by_this_artifact"
            ),
            "panel_submission_decision_operator_approval_phrase_required": panel_submission_decision.get(
                "operator_approval_phrase_required"
            ),
            "panel_submission_decision_operator_machine_gate": panel_submission_decision.get(
                "operator_machine_gate"
            ),
            "panel_submission_decision_operator_postsubmit_driver_command": panel_submission_decision.get(
                "operator_postsubmit_driver_command"
            ),
            "panel_submission_decision_operator_postsync_replay_command": panel_submission_decision.get(
                "operator_postsync_replay_command"
            ),
            "panel_submission_decision_operator_driver_replay_pair_ready": panel_submission_decision.get(
                "operator_driver_replay_command_pair_ready"
            ),
            "panel_submission_decision_operator_local_receipts_absent": panel_submission_decision.get(
                "operator_local_receipts_absent"
            ),
            "panel_submission_decision_operator_remote_receipts_checked": panel_submission_decision.get(
                "operator_remote_receipts_checked"
            ),
            "panel_submission_decision_operator_remote_receipts_absent": panel_submission_decision.get(
                "operator_remote_receipts_absent"
            ),
            "panel_submission_decision_operator_planned_design_records": panel_submission_decision.get(
                "operator_planned_design_records"
            ),
            "panel_submission_decision_operator_expected_slurm_jobs": panel_submission_decision.get(
                "operator_expected_slurm_jobs"
            ),
            "panel_submission_decision_operator_target_alpha": panel_submission_decision.get(
                "operator_target_alpha"
            ),
            "panel_postsync_interpretation_ready": (
                panel_postsync.get("status") in {
                    _PANEL_POSTSYNC_NOT_SYNCED_STATUS,
                    "ready_for_target_wise_panel_report",
                    _PANEL_POSTSYNC_SUPPORTED_STATUS,
                    "w2_generalization_not_supported_target_wise",
                    "panel_report_not_multi_target_proof",
                }
                and panel_postsync.get("audit_ok") is True
            ),
            "panel_postsync_no_submit": panel_postsync.get("no_submit"),
            "panel_postsync_submitted": panel_postsync.get("submitted"),
            "panel_postsync_sync_ready": panel_postsync.get("sync_ready"),
            "panel_postsync_can_claim_w2_generalization": panel_postsync.get("can_claim_w2_generalization"),
            "panel_postsync_status": panel_postsync.get("status"),
            "panel_public_approval_bundle_ready": (
                panel_public_bundle.get("status") == _PANEL_PUBLIC_APPROVAL_BUNDLE_STATUS
                and panel_public_bundle.get("audit_ok") is True
            ),
            "panel_public_approval_bundle_no_submit": panel_public_bundle.get("no_submit"),
            "panel_public_approval_bundle_submitted": panel_public_bundle.get("submitted"),
            "panel_public_approval_bundle_can_claim_w2_generalization": panel_public_bundle.get(
                "can_claim_w2_generalization"
            ),
            "panel_public_approval_bundle_remote_shell_syntax_checks": panel_public_bundle.get(
                "remote_readiness_shell_syntax_checks"
            ),
            "panel_public_approval_bundle_remote_shell_syntax_checks_ok": panel_public_bundle.get(
                "remote_readiness_shell_syntax_checks_ok"
            ),
            "panel_public_approval_bundle_workflow_step_count": panel_public_bundle.get(
                "workflow_manual_step_count"
            ),
            "panel_public_approval_bundle_workflow_all_commands_present": panel_public_bundle.get(
                "workflow_all_manual_commands_present"
            ),
            "panel_public_approval_bundle_workflow_sync_ready_before_record_sync": panel_public_bundle.get(
                "workflow_requires_sync_ready_before_record_sync"
            ),
            "panel_public_approval_bundle_workflow_includes_postsync_interpretation": panel_public_bundle.get(
                "workflow_includes_postsync_interpretation"
            ),
            "panel_public_approval_bundle_workflow_driver_command_present": panel_public_bundle.get(
                "workflow_driver_command_present"
            ),
            "panel_public_approval_bundle_workflow_driver_command_expected": panel_public_bundle.get(
                "workflow_driver_command_expected"
            ),
            "panel_public_approval_bundle_workflow_postsync_replay_command_expected": panel_public_bundle.get(
                "workflow_postsync_replay_command_expected"
            ),
            "panel_public_approval_bundle_workflow_driver_replay_command_pair_ready": panel_public_bundle.get(
                "workflow_driver_replay_command_pair_ready"
            ),
            "panel_public_approval_bundle_workflow_driver_polling_contract_ok": panel_public_bundle.get(
                "workflow_driver_polling_contract_ok"
            ),
            "panel_public_approval_bundle_workflow_postsubmit_driver_static_chain_ok": panel_public_bundle.get(
                "workflow_postsubmit_driver_static_chain_ok"
            ),
            "panel_public_approval_bundle_workflow_postsync_replay_static_chain_ok": panel_public_bundle.get(
                "workflow_postsync_replay_static_chain_ok"
            ),
            "panel_public_approval_bundle_workflow_sync_back_static_chain_ok": panel_public_bundle.get(
                "workflow_sync_back_static_chain_ok"
            ),
            "panel_public_approval_bundle_workflow_completion_static_chain_ok": panel_public_bundle.get(
                "workflow_completion_static_chain_ok"
            ),
            "panel_public_approval_bundle_workflow_script_chain_static_ok": panel_public_bundle.get(
                "workflow_script_chain_static_ok"
            ),
            "panel_public_approval_bundle_workflow_driver_polling_default_max_polls": panel_public_bundle.get(
                "workflow_driver_polling_default_max_polls"
            ),
            "panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds": (
                panel_public_bundle.get("workflow_driver_polling_default_poll_seconds")
            ),
            "panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate": panel_public_bundle.get(
                "workflow_driver_polling_sync_ready_gate"
            ),
            "panel_public_approval_bundle_workflow_driver_sync_ready_only": panel_public_bundle.get(
                "workflow_driver_proceeds_only_when_sync_ready"
            ),
            "panel_public_approval_bundle_explicit_approval_required": panel_public_bundle.get(
                "explicit_approval_required"
            ),
            "panel_public_approval_bundle_scope_ready": panel_public_bundle.get("approval_scope_ok"),
            "panel_public_approval_bundle_scope_planned_design_records": (
                panel_public_bundle.get("approval_scope") or {}
            ).get("planned_design_records"),
            "panel_public_approval_bundle_scope_expected_slurm_jobs": (
                panel_public_bundle.get("approval_scope") or {}
            ).get("expected_slurm_jobs"),
        },
        "w3_gate": {
            "audit_ok": w3_adjudication_audit.get("audit_ok"),
            "status": w3_adjudication_audit.get("status"),
            "positive_claim_supported": w3_adjudication_audit.get("positive_claim_supported"),
            "adjudication_rows": artifact_audit.get("n_rows"),
            "adjudication_sha256": artifact_audit.get("actual_sha256"),
        },
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d Goal Completion Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Can mark goal complete: `{rep.get('can_mark_goal_complete')}`.",
        "",
        "This is a no-submit completion-boundary audit. A passing audit preserves the current active goal state; it does not mark the goal complete.",
        "",
        "## Workstreams",
        "",
        "| workstream | status | complete |",
        "|---|---|---:|",
    ]
    for key, row in (rep.get("workstream_status") or {}).items():
        lines.append(f"| {key} | {row.get('status')} | {row.get('complete')} |")
    lines.extend([
        "",
        "## Remaining Requirement",
        "",
    ])
    lines.extend(f"- {item}" for item in rep.get("remaining_requirements", []))
    lines.extend([
        "",
        "## Gate Evidence",
        "",
        f"- W2 approval packet ready: `{rep.get('w2_gate', {}).get('approval_packet_ready')}`",
        f"- W2 approval parity ok: `{rep.get('w2_gate', {}).get('approval_parity_ok')}`",
        f"- W2 wrapper guard ok: `{rep.get('w2_gate', {}).get('wrapper_guard_ok')}`",
        f"- W2 panel submission blocked: `{rep.get('w2_gate', {}).get('panel_submission_blocked')}`",
        f"- W2 target-MSA execution status: `{rep.get('w2_gate', {}).get('target_msa_execution_status')}`",
        f"- W2 target-MSA jobs submitted waiting on completion: `{rep.get('w2_gate', {}).get('target_msa_jobs_submitted_waiting_on_completion')}`",
        f"- W2 target-MSA outputs synced and strict require-files passed: `{rep.get('w2_gate', {}).get('target_msa_outputs_synced_strict_require_files_passed')}`",
        f"- W2 target-MSA approved but blocked before submission: `{rep.get('w2_gate', {}).get('target_msa_approved_but_blocked_before_submission')}`",
        f"- W2 panel approval packet ready: `{rep.get('w2_gate', {}).get('panel_approval_packet_ready')}`",
        f"- W2 panel can submit if explicitly approved: `{rep.get('w2_gate', {}).get('panel_can_submit_if_explicitly_approved')}`",
        f"- W2 panel can claim generalization: `{rep.get('w2_gate', {}).get('panel_can_claim_w2_generalization')}`",
        f"- W2 panel no-env guard refuses: `{rep.get('w2_gate', {}).get('panel_guard_no_env_refuses')}`",
        f"- W2 panel approval scope ready: `{rep.get('w2_gate', {}).get('panel_approval_scope_ready')}`",
        f"- W2 panel approval scope planned designs: `{rep.get('w2_gate', {}).get('panel_approval_scope_planned_design_records')}`",
        f"- W2 panel approval scope expected Slurm jobs: `{rep.get('w2_gate', {}).get('panel_approval_scope_expected_slurm_jobs')}`",
        f"- W2 project-status approval scope ready: `{rep.get('w2_gate', {}).get('project_status_panel_approval_scope_ready')}`",
        f"- W2 project-status approval scope planned designs: `{rep.get('w2_gate', {}).get('project_status_panel_approval_scope_planned_design_records')}`",
        f"- W2 project-status approval scope expected Slurm jobs: `{rep.get('w2_gate', {}).get('project_status_panel_approval_scope_expected_slurm_jobs')}`",
        f"- W2 panel decision protocol ready: `{rep.get('w2_gate', {}).get('panel_decision_protocol_ready')}`",
        f"- W2 panel decision protocol no-submit: `{rep.get('w2_gate', {}).get('panel_decision_no_submit')}`",
        f"- W2 panel decision can claim now: `{rep.get('w2_gate', {}).get('panel_decision_can_claim_w2_now')}`",
        f"- W2 panel decision current result: `{rep.get('w2_gate', {}).get('panel_decision_current_result_status')}`",
        f"- W2 panel remote readiness ok: `{rep.get('w2_gate', {}).get('panel_remote_readiness_ok')}`",
        f"- W2 panel remote readiness no-submit: `{rep.get('w2_gate', {}).get('panel_remote_no_submit')}`",
        f"- W2 panel remote can claim generalization: `{rep.get('w2_gate', {}).get('panel_remote_can_claim_w2_generalization')}`",
        f"- W2 panel remote shell syntax checks: `{rep.get('w2_gate', {}).get('panel_remote_shell_syntax_checks')}`",
        f"- W2 panel remote shell syntax checks ok: `{rep.get('w2_gate', {}).get('panel_remote_shell_syntax_checks_ok')}`",
        f"- W2 panel submission decision ready: `{rep.get('w2_gate', {}).get('panel_submission_decision_ready')}`",
        f"- W2 panel submission decision no-submit: `{rep.get('w2_gate', {}).get('panel_submission_decision_no_submit')}`",
        f"- W2 panel submission decision submitted: `{rep.get('w2_gate', {}).get('panel_submission_decision_submitted')}`",
        f"- W2 panel submission decision can claim generalization: `{rep.get('w2_gate', {}).get('panel_submission_decision_can_claim_w2_generalization')}`",
        f"- W2 panel submission decision operator checklist ok: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_checklist_ok')}`",
        f"- W2 panel submission decision operator submit allowed: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_submit_allowed')}`",
        f"- W2 panel submission decision operator submission performed: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_submission_performed')}`",
        f"- W2 panel submission decision operator driver/replay pair ready: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_driver_replay_pair_ready')}`",
        f"- W2 panel submission decision operator remote receipts absent: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_remote_receipts_absent')}`",
        f"- W2 panel submission decision operator planned designs: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_planned_design_records')}`",
        f"- W2 panel submission decision operator expected Slurm jobs: `{rep.get('w2_gate', {}).get('panel_submission_decision_operator_expected_slurm_jobs')}`",
        f"- W2 panel post-sync interpretation ready: `{rep.get('w2_gate', {}).get('panel_postsync_interpretation_ready')}`",
        f"- W2 panel post-sync status: `{rep.get('w2_gate', {}).get('panel_postsync_status')}`",
        f"- W2 panel post-sync can claim generalization: `{rep.get('w2_gate', {}).get('panel_postsync_can_claim_w2_generalization')}`",
        f"- W2 panel public approval bundle ready: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_ready')}`",
        f"- W2 panel public approval bundle remote shell syntax checks: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_remote_shell_syntax_checks')}`",
        f"- W2 panel public approval bundle remote shell syntax checks ok: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_remote_shell_syntax_checks_ok')}`",
        f"- W2 panel public approval bundle workflow steps: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_step_count')}`",
        f"- W2 panel public approval bundle workflow sync-ready before record sync: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_sync_ready_before_record_sync')}`",
        f"- W2 panel public approval bundle workflow includes post-sync interpretation: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_includes_postsync_interpretation')}`",
        f"- W2 panel public approval bundle workflow driver command present: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_driver_command_present')}`",
        f"- W2 panel public approval bundle workflow driver command expected: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_driver_command_expected')}`",
        f"- W2 panel public approval bundle workflow post-sync replay command expected: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_postsync_replay_command_expected')}`",
        f"- W2 panel public approval bundle workflow driver/replay command pair ready: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_driver_replay_command_pair_ready')}`",
        f"- W2 panel public approval bundle workflow driver polling contract ok: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_driver_polling_contract_ok')}`",
        f"- W2 panel public approval bundle workflow script chain static ok: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_workflow_script_chain_static_ok')}`",
        f"- W2 panel public approval bundle scope ready: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_scope_ready')}`",
        f"- W2 panel public approval bundle scope planned designs: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_scope_planned_design_records')}`",
        f"- W2 panel public approval bundle scope expected Slurm jobs: `{rep.get('w2_gate', {}).get('panel_public_approval_bundle_scope_expected_slurm_jobs')}`",
        f"- W3 standalone audit ok: `{rep.get('w3_gate', {}).get('audit_ok')}`",
        f"- W3 positive claim supported: `{rep.get('w3_gate', {}).get('positive_claim_supported')}`",
        "",
    ])
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
        lines.append("")
    lines.extend([
        f"Next action: {rep.get('next_action')}",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-status", default="results/m6c_project_status_w2_followup.json")
    ap.add_argument("--approval-packet", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--approval-parity", default="results/m6d_w2_target_family_redesign_v9_approval_parity.json")
    ap.add_argument("--wrapper-guard", default="results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.json")
    ap.add_argument("--w3-adjudication-audit", default="results/m6d_w3_adjudication_audit.json")
    ap.add_argument("--execution-attempt", default="results/m6d_w2_target_family_redesign_v9_full14_target_msa_execution_attempt.json")
    ap.add_argument("--panel-approval-packet", default="results/m6d_w2_target_family_redesign_v9_panel_approval_packet.json")
    ap.add_argument("--panel-decision-protocol", default="results/m6d_w2_target_family_redesign_v9_panel_decision_protocol.json")
    ap.add_argument("--panel-remote-readiness", default=None)
    ap.add_argument("--panel-submission-decision-state", default=None)
    ap.add_argument("--panel-postsync-interpretation", default=None)
    ap.add_argument("--panel-public-approval-bundle", default=None)
    ap.add_argument("--v9-receipt", default="results/m6d_w2_target_family_redesign_v9_target_msa_precompute_receipt.jsonl")
    ap.add_argument("--out-json", default="results/m6d_goal_completion_audit.json")
    ap.add_argument("--out-md", default="results/m6d_goal_completion_audit.md")
    args = ap.parse_args(argv)
    execution_attempt = _load_json(args.execution_attempt) if args.execution_attempt and os.path.exists(args.execution_attempt) else None
    panel_approval_packet = (
        _load_json(args.panel_approval_packet)
        if args.panel_approval_packet and os.path.exists(args.panel_approval_packet)
        else None
    )
    panel_decision_protocol = (
        _load_json(args.panel_decision_protocol)
        if args.panel_decision_protocol and os.path.exists(args.panel_decision_protocol)
        else None
    )
    panel_remote_readiness = (
        _load_json(args.panel_remote_readiness)
        if args.panel_remote_readiness and os.path.exists(args.panel_remote_readiness)
        else None
    )
    panel_submission_decision_state = (
        _load_json(args.panel_submission_decision_state)
        if args.panel_submission_decision_state and os.path.exists(args.panel_submission_decision_state)
        else None
    )
    panel_postsync_interpretation = (
        _load_json(args.panel_postsync_interpretation)
        if args.panel_postsync_interpretation and os.path.exists(args.panel_postsync_interpretation)
        else None
    )
    panel_public_approval_bundle = (
        _load_json(args.panel_public_approval_bundle)
        if args.panel_public_approval_bundle and os.path.exists(args.panel_public_approval_bundle)
        else None
    )

    rep = build_audit(
        _load_json(args.project_status),
        _load_json(args.approval_packet),
        _load_json(args.approval_parity),
        _load_json(args.wrapper_guard),
        _load_json(args.w3_adjudication_audit),
        execution_attempt,
        panel_approval_packet,
        panel_decision_protocol,
        panel_remote_readiness,
        panel_submission_decision_state,
        panel_postsync_interpretation,
        panel_public_approval_bundle,
        v9_receipt=args.v9_receipt,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} can_mark_goal_complete={complete} remaining={remaining}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            complete=rep["can_mark_goal_complete"],
            remaining=",".join(rep["remaining_requirements"]),
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
