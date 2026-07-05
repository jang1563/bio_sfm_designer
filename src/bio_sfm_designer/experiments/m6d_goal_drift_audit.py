"""Audit whether M6d goal-mode execution has drifted from its objective.

This is a no-submit guardrail. It checks that the project is still being run as
a research-engine development goal, not as publication packaging; that W1/W3/W4
claim boundaries remain preserved; and that W2 is still blocked at explicit
target-MSA execution rather than silently becoming panel submission or a
generalization claim. After explicit approval, this audit can also represent
the honest pre-submission SSH/login blocker state.
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
_EXECUTION_BLOCKED_STATUS = "blocked_before_submission_ssh_banner_exchange_timeout"
_EXECUTION_SUBMITTED_STATUS = "target_msa_jobs_submitted_waiting_on_completion"
_EXECUTION_SYNCED_STATUS = "target_msa_outputs_synced_strict_require_files_passed"
_PANEL_APPROVAL_READY_STATUS = "panel_approval_packet_ready"
_PANEL_DECISION_READY_STATUS = "post_panel_decision_protocol_ready"


_GOAL_TEXT_REQUIREMENTS = (
    (
        "research_engine_not_publication",
        ("not a publication plan", "research engine"),
        "goal-mode docs must keep the project framed as research-engine development, not publication work",
    ),
    (
        "w2_redesign_objective",
        ("redesign w2 multi-target generalization",),
        "goal objective must still include W2 multi-target redesign",
    ),
    (
        "w3_disagreement_objective",
        ("resolve w3 boltz-chai predictor disagreement",),
        "goal objective must still include W3 Boltz-Chai disagreement resolution",
    ),
    (
        "w1_preservation_objective",
        ("preserve w1 as target-specific certified evidence",),
        "goal objective must still preserve W1 as target-specific evidence",
    ),
    (
        "w4_preservation_objective",
        ("w4 as closed-loop plumbing evidence",),
        "goal objective must still preserve W4 as plumbing evidence",
    ),
    (
        "honest_reproducible_artifacts",
        ("honest", "reproducible"),
        "goal objective must still emphasize honest reproducible artifacts",
    ),
)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _read_text(path: str) -> str:
    with open(path) as fh:
        return fh.read()


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
    category: str,
    expected: Any = None,
    observed: Any = None,
) -> None:
    row: Dict[str, Any] = {"kind": kind, "category": category, "message": message}
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


def _contains_all(text: str, needles: Any) -> bool:
    lower = text.lower()
    return all(str(needle).lower() in lower for needle in needles)


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
    return {
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
        "sync_back_command_after_jobs_finish": panel_approval_packet.get("sync_back_command_after_jobs_finish"),
        "checks": checks,
        "target_msa_strict_ready": checks.get("target_msa_strict_ready"),
        "panel_dry_run_no_sbatch": checks.get("panel_dry_run_no_sbatch"),
        "panel_guard_no_env_refuses": checks.get("panel_guard_no_env_refuses"),
        "submit_receipt_absent": checks.get("submit_receipt_absent"),
        "submit_summary_absent": checks.get("submit_summary_absent"),
    }


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
        "min_records_per_target": contract.get("min_records_per_target"),
        "next_action": panel_decision_protocol.get("next_action"),
    }


def build_audit(
    project_status: Dict[str, Any],
    completion_audit: Dict[str, Any],
    runbook: Dict[str, Any],
    w3_adjudication_audit: Dict[str, Any],
    execution_attempt: Optional[Dict[str, Any]],
    goal_mode_text: str,
    anchor_text: str,
    panel_approval_packet: Optional[Dict[str, Any]] = None,
    panel_decision_protocol: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    combined_goal_text = "\n".join([goal_mode_text or "", anchor_text or ""])
    execution = _execution_state(execution_attempt)
    panel_approval = _panel_approval_state(panel_approval_packet)
    panel_decision = _panel_decision_state(panel_decision_protocol)

    for kind, needles, message in _GOAL_TEXT_REQUIREMENTS:
        if not _contains_all(combined_goal_text, needles):
            _add_failure(
                failures,
                kind,
                message,
                category="direction",
                expected=list(needles),
            )

    w1 = _workstream(project_status, "W1_M6c_scale_up")
    w2 = _workstream(project_status, "W2_multi_target_panel")
    w3 = _workstream(project_status, "W3_independent_predictor")
    w4 = _workstream(project_status, "W4_closed_loop_DBTL")

    if w1.get("status") != _W1_STATUS or w1.get("complete") is not True:
        _add_failure(
            failures,
            "w1_boundary_drift",
            "W1 must remain target-specific certified evidence",
            category="claim_boundary",
            expected={"status": _W1_STATUS, "complete": True},
            observed={"status": w1.get("status"), "complete": w1.get("complete")},
        )
    if w2.get("status") not in _W2_OPEN_STATUSES or w2.get("complete") is not False:
        _add_failure(
            failures,
            "w2_gate_boundary_drift",
            "W2 must remain open at an explicit target-MSA or panel approval boundary until target-wise certification passes",
            category="claim_boundary",
            expected={"status": sorted(_W2_OPEN_STATUSES), "complete": False},
            observed={"status": w2.get("status"), "complete": w2.get("complete")},
        )
    if w3.get("status") != _W3_STATUS or w3.get("complete") is not True:
        _add_failure(
            failures,
            "w3_boundary_drift",
            "W3 must remain an adjudicated negative robustness result unless a new protocol overturns it",
            category="claim_boundary",
            expected={"status": _W3_STATUS, "complete": True},
            observed={"status": w3.get("status"), "complete": w3.get("complete")},
        )
    if w3.get("positive_claim_supported") is not False:
        _add_failure(
            failures,
            "w3_positive_claim_drift",
            "W3 must not be converted into a positive independent-predictor robustness claim",
            category="claim_boundary",
            expected=False,
            observed=w3.get("positive_claim_supported"),
        )
    if w4.get("status") != _W4_STATUS or w4.get("complete") is not True:
        _add_failure(
            failures,
            "w4_boundary_drift",
            "W4 must remain completed closed-loop plumbing evidence, not a productive routing claim",
            category="claim_boundary",
            expected={"status": _W4_STATUS, "complete": True},
            observed={"status": w4.get("status"), "complete": w4.get("complete")},
        )

    if project_status.get("complete") is not False or project_status.get("can_mark_goal_complete") is not False:
        _add_failure(
            failures,
            "premature_goal_completion_drift",
            "The project status must not mark the full goal complete while W2 remains open",
            category="execution",
            expected={"complete": False, "can_mark_goal_complete": False},
            observed={
                "complete": project_status.get("complete"),
                "can_mark_goal_complete": project_status.get("can_mark_goal_complete"),
            },
        )
    if project_status.get("remaining") != 1:
        _add_failure(
            failures,
            "remaining_requirement_drift",
            "Exactly one requirement should remain in the current state: W2",
            category="execution",
            expected=1,
            observed=project_status.get("remaining"),
        )

    if completion_audit.get("audit_ok") is not True or completion_audit.get("status") != "goal_active_w2_remaining":
        _add_failure(
            failures,
            "completion_audit_drift",
            "goal completion audit must pass while preserving W2 as the remaining requirement",
            category="execution",
            expected={"audit_ok": True, "status": "goal_active_w2_remaining"},
            observed={"audit_ok": completion_audit.get("audit_ok"), "status": completion_audit.get("status")},
        )
    if completion_audit.get("can_mark_goal_complete") is not False:
        _add_failure(
            failures,
            "completion_audit_allows_completion",
            "completion audit must not allow goal completion before W2 finishes",
            category="execution",
            expected=False,
            observed=completion_audit.get("can_mark_goal_complete"),
        )

    if runbook.get("audit_ok") is not True or runbook.get("status") != "explicit_approval_runbook_ready":
        _add_failure(
            failures,
            "runbook_not_ready",
            "explicit-approval runbook must be ready and audited before W2 target-MSA prep is requested",
            category="execution",
            expected={"audit_ok": True, "status": "explicit_approval_runbook_ready"},
            observed={"audit_ok": runbook.get("audit_ok"), "status": runbook.get("status")},
        )
    if runbook.get("target_count") != 14 or runbook.get("pending_path_count") != 28:
        _add_failure(
            failures,
            "runbook_count_drift",
            "current W2 v9 runbook should still be scoped to 14 targets and 28 pending MSA/report paths",
            category="execution",
            expected={"target_count": 14, "pending_path_count": 28},
            observed={"target_count": runbook.get("target_count"), "pending_path_count": runbook.get("pending_path_count")},
        )
    boundary = runbook.get("claim_boundary") if isinstance(runbook.get("claim_boundary"), dict) else {}
    if boundary.get("target_msa_input_prep") != "allowed only after explicit approval":
        _add_failure(
            failures,
            "target_msa_approval_boundary_drift",
            "target-MSA input prep must remain gated on explicit approval",
            category="approval_boundary",
            expected="allowed only after explicit approval",
            observed=boundary.get("target_msa_input_prep"),
        )
    panel_boundary = str(boundary.get("proteinmpnn_boltz_panel_submission") or "")
    if "blocked" not in panel_boundary:
        _add_failure(
            failures,
            "panel_submission_boundary_drift",
            "ProteinMPNN/Boltz panel submission must remain blocked",
            category="approval_boundary",
            expected="blocked",
            observed=boundary.get("proteinmpnn_boltz_panel_submission"),
        )
    if boundary.get("w2_multi_target_generalization") != "not_supported":
        _add_failure(
            failures,
            "w2_generalization_boundary_drift",
            "W2 multi-target generalization must remain unsupported",
            category="claim_boundary",
            expected="not_supported",
            observed=boundary.get("w2_multi_target_generalization"),
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
                "target_msa_execution_state_drift",
                "W2 target-MSA execution must remain recorded as pre-submission blocked or submitted-waiting",
                category="execution",
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
        execution_boundary = (
            execution_attempt.get("claim_boundary")
            if isinstance(execution_attempt.get("claim_boundary"), dict)
            else {}
        )
        if "blocked" not in str(execution_boundary.get("proteinmpnn_boltz_panel_submission") or ""):
            _add_failure(
                failures,
                "target_msa_execution_panel_boundary_drift",
                "execution attempt must keep ProteinMPNN/Boltz panel submission blocked",
                category="approval_boundary",
                expected="blocked",
                observed=execution_boundary.get("proteinmpnn_boltz_panel_submission"),
            )
        if execution_boundary.get("w2_multi_target_generalization") != "not_supported":
            _add_failure(
                failures,
                "target_msa_execution_generalization_boundary_drift",
                "execution attempt must not convert W2 into a multi-target generalization claim",
                category="claim_boundary",
                expected="not_supported",
                observed=execution_boundary.get("w2_multi_target_generalization"),
            )

    if panel_approval_packet is not None:
        if panel_approval.get("status") != _PANEL_APPROVAL_READY_STATUS or panel_approval.get("approval_packet_ready") is not True:
            _add_failure(
                failures,
                "panel_approval_packet_not_ready",
                "panel approval packet must pass before it can become the current W2 panel boundary",
                category="execution",
                expected={"status": _PANEL_APPROVAL_READY_STATUS, "approval_packet_ready": True},
                observed={
                    "status": panel_approval.get("status"),
                    "approval_packet_ready": panel_approval.get("approval_packet_ready"),
                },
            )
        if panel_approval.get("can_submit_panel_if_user_explicitly_approves") is not True:
            _add_failure(
                failures,
                "panel_not_explicit_approval_ready",
                "panel packet must only allow submission under explicit approval",
                category="approval_boundary",
                expected=True,
                observed=panel_approval.get("can_submit_panel_if_user_explicitly_approves"),
            )
        if panel_approval.get("can_claim_w2_generalization") is not False:
            _add_failure(
                failures,
                "panel_approval_claim_drift",
                "panel approval packet must not become a W2 generalization claim",
                category="claim_boundary",
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
                    "panel_approval_guard_check_drift",
                    "panel approval packet guard checks must remain true",
                    category="execution",
                    expected={key: True},
                    observed={key: panel_approval.get(key)},
                )

    if panel_decision_protocol is not None:
        if panel_decision.get("status") != _PANEL_DECISION_READY_STATUS or panel_decision.get("audit_ok") is not True:
            _add_failure(
                failures,
                "panel_decision_protocol_not_ready",
                "post-panel decision protocol must pass before it can govern W2 interpretation",
                category="execution",
                expected={"status": _PANEL_DECISION_READY_STATUS, "audit_ok": True},
                observed={"status": panel_decision.get("status"), "audit_ok": panel_decision.get("audit_ok")},
            )
        if panel_decision.get("no_submit") is not True:
            _add_failure(
                failures,
                "panel_decision_protocol_submit_drift",
                "post-panel decision protocol must remain no-submit",
                category="approval_boundary",
                expected=True,
                observed=panel_decision.get("no_submit"),
            )
        if panel_decision.get("can_claim_w2_generalization_now") is not False:
            _add_failure(
                failures,
                "panel_decision_protocol_claim_drift",
                "post-panel decision protocol must not support a current W2 generalization claim",
                category="claim_boundary",
                expected=False,
                observed=panel_decision.get("can_claim_w2_generalization_now"),
            )
        if panel_decision.get("current_result_w2_supported") is not False:
            _add_failure(
                failures,
                "panel_decision_current_result_claim_drift",
                "current panel result state must not support W2 generalization before panel records/report exist",
                category="claim_boundary",
                expected=False,
                observed=panel_decision.get("current_result_w2_supported"),
            )
        if panel_decision.get("target_alpha") != 0.2 or panel_decision.get("n_manifest_targets") != 14:
            _add_failure(
                failures,
                "panel_decision_contract_drift",
                "post-panel decision protocol must stay scoped to alpha=0.2 and 14 manifest targets",
                category="claim_boundary",
                expected={"target_alpha": 0.2, "n_manifest_targets": 14},
                observed={
                    "target_alpha": panel_decision.get("target_alpha"),
                    "n_manifest_targets": panel_decision.get("n_manifest_targets"),
                },
            )

    if w3_adjudication_audit.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_standalone_audit_drift",
            "standalone W3 adjudication audit must pass",
            category="execution",
            expected=True,
            observed=w3_adjudication_audit.get("audit_ok"),
        )
    if w3_adjudication_audit.get("positive_claim_supported") is not False:
        _add_failure(
            failures,
            "w3_standalone_positive_claim_drift",
            "standalone W3 audit must not support a positive robustness claim",
            category="claim_boundary",
            expected=False,
            observed=w3_adjudication_audit.get("positive_claim_supported"),
        )

    audit_ok = not failures
    major_direction_drift = any(failure.get("category") == "direction" for failure in failures)
    execution_assessment = "w2_branch_complexity_managed_by_explicit_approval_runbook"
    w2_boundary = "open_at_explicit_target_msa_gate; no multi-target generalization claim"
    next_action = "await explicit W2 v9 target-MSA input-prep approval only; do not submit panel work"
    if execution.get("approved_but_blocked_before_submission"):
        execution_assessment = "target_msa_approved_but_blocked_before_submission_by_ssh_login"
        w2_boundary = "open_after_approved_target_msa_attempt_blocked_before_submission; no multi-target generalization claim"
        next_action = (
            "restore SSH/VPN/login access, rerun only the approved W2 v9 target-MSA wrapper, "
            "then sync back and replay strict require-files before any panel plan"
        )
    if execution.get("target_msa_jobs_submitted_waiting_on_completion"):
        execution_assessment = "target_msa_jobs_submitted_waiting_on_completion"
        w2_boundary = "open_after_target_msa_jobs_submitted; waiting on completion and strict replay; no multi-target generalization claim"
        next_action = (
            "wait for submitted W2 v9 target-MSA jobs to finish, then sync back and replay strict require-files "
            "before any panel plan"
        )
    if execution.get("target_msa_outputs_synced_strict_require_files_passed"):
        execution_assessment = "target_msa_outputs_synced_strict_require_files_passed"
        w2_boundary = "open_after_target_msa_sync_and_strict_replay; next panel step still cannot imply generalization"
        next_action = (
            "prepare or run the next W2 v9 panel step, then require target-wise panel certification before any "
            "multi-target generalization claim"
        )
        if panel_approval.get("approval_packet_ready") is True:
            execution_assessment = "panel_approval_packet_ready_not_submitted"
            w2_boundary = (
                "open_after_panel_approval_packet_ready; explicit guarded panel submission still required; "
                "no multi-target generalization claim"
            )
            next_action = (
                "wait for explicit user approval before running the guarded W2 v9 panel submit command; "
                "then require sync-back, completion, and target-wise certification before any generalization claim"
            )
            if panel_decision.get("status") == _PANEL_DECISION_READY_STATUS:
                execution_assessment = "panel_decision_protocol_ready_not_submitted"
                w2_boundary = (
                    "open_after_panel_decision_protocol_ready; explicit guarded panel submission still required; "
                    "predeclared post-panel rules still require target-wise certification before any claim"
                )
                next_action = (
                    "wait for explicit user approval before running the guarded W2 v9 panel submit command; "
                    "then apply the predeclared post-panel decision protocol after sync-back and completion"
                )
    ssh_pre_submission_resolved = (
        execution.get("target_msa_jobs_submitted_waiting_on_completion") is True
        or execution.get("target_msa_outputs_synced_strict_require_files_passed") is True
    )
    return {
        "artifact": "m6d_goal_drift_audit",
        "audit_ok": audit_ok,
        "status": "no_major_direction_drift_w2_blocked" if audit_ok else "goal_drift_audit_blocked",
        "major_direction_drift": major_direction_drift,
        "can_mark_goal_complete": False,
        "claim_boundary": {
            "publication": "not_current_goal",
            "w1": "preserved_target_specific_certificate",
            "w2": w2_boundary,
            "w3": "negative_robustness_adjudicated; no positive independent-predictor claim",
            "w4": "closed_loop_plumbing_only",
        },
        "current_state": {
            "project_status": project_status.get("status"),
            "remaining": project_status.get("remaining"),
            "W1_M6c_scale_up": {"status": w1.get("status"), "complete": w1.get("complete")},
            "W2_multi_target_panel": {"status": w2.get("status"), "complete": w2.get("complete")},
            "W3_independent_predictor": {
                "status": w3.get("status"),
                "complete": w3.get("complete"),
                "positive_claim_supported": w3.get("positive_claim_supported"),
            },
            "W4_closed_loop_DBTL": {"status": w4.get("status"), "complete": w4.get("complete")},
            "W2_target_msa_execution": execution,
            "W2_panel_approval": panel_approval,
            "W2_panel_decision_protocol": panel_decision,
        },
        "drift_assessment": {
            "direction": "aligned" if not major_direction_drift else "drift_detected",
            "execution": execution_assessment if audit_ok else "repair_required",
            "claim_boundary": "preserved" if audit_ok else "repair_required",
        },
        "active_risks": [
            {
                "id": "w2_branch_explosion",
                "status": "managed",
                "control": "keep W2 staged through target-MSA sync, no-submit panel approval, explicit panel approval, then target-wise certification",
            },
            {
                "id": "approval_inference_from_continue_prompt",
                "status": "managed",
                "control": "target-MSA and panel approvals are separately guarded; continuation still does not authorize panel work",
            },
            {
                "id": "ssh_pre_submission_blocker",
                "status": "resolved" if ssh_pre_submission_resolved else "active",
                "control": (
                    "fallback login2 reached and the audited target-MSA wrapper submitted jobs; future reruns must still use audited target-MSA-only wrappers"
                    if ssh_pre_submission_resolved
                    else
                    "restore Cayuga SSH/VPN/login access before rerunning only the approved target-MSA wrapper"
                ),
            },
            {
                "id": "target_msa_job_completion_pending",
                "status": (
                    "resolved"
                    if execution.get("target_msa_outputs_synced_strict_require_files_passed")
                    else "active"
                    if execution.get("target_msa_jobs_submitted_waiting_on_completion")
                    else "not_started"
                ),
                "control": "wait for target-MSA jobs to leave the queue before running sync-back and strict require-files",
            },
            {
                "id": "panel_step_boundary",
                "status": "active" if execution.get("target_msa_outputs_synced_strict_require_files_passed") else "not_ready",
                "control": "post-MSA strict gate and panel approval packet readiness still must not be converted into a W2 claim until target-wise certification passes",
            },
            {
                "id": "panel_approval_packet_boundary",
                "status": "managed" if panel_approval.get("approval_packet_ready") is True else "not_ready",
                "control": "panel approval packet is no-submit readiness only; explicit approval and target-wise certification remain required",
            },
            {
                "id": "panel_decision_protocol_boundary",
                "status": "managed" if panel_decision.get("status") == _PANEL_DECISION_READY_STATUS else "not_ready",
                "control": "post-panel decision protocol is no-submit interpretation only; it cannot authorize execution or claims",
            },
            {
                "id": "pooled_only_w2_claim",
                "status": "managed",
                "control": "require target-wise certificates for W2 generalization",
            },
        ],
        "inputs": {
            "project_status": project_status.get("_path"),
            "completion_audit": completion_audit.get("_path"),
            "runbook": runbook.get("_path"),
            "w3_adjudication_audit": w3_adjudication_audit.get("_path"),
            "execution_attempt": execution.get("path"),
            "panel_approval_packet": panel_approval.get("path"),
            "panel_decision_protocol": panel_decision.get("path"),
        },
        "failures": failures,
        "next_action": (
            next_action
            if audit_ok else
            "repair drift failures before resuming goal-mode execution"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d Goal Drift Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Major direction drift: `{rep.get('major_direction_drift')}`.",
        f"Can mark goal complete: `{rep.get('can_mark_goal_complete')}`.",
        "",
        "## Assessment",
        "",
    ]
    assessment = rep.get("drift_assessment") if isinstance(rep.get("drift_assessment"), dict) else {}
    for key in ("direction", "execution", "claim_boundary"):
        lines.append(f"- {key}: `{assessment.get(key)}`")
    lines.extend(["", "## Current State", ""])
    current = rep.get("current_state") if isinstance(rep.get("current_state"), dict) else {}
    for key in ("W1_M6c_scale_up", "W2_multi_target_panel", "W3_independent_predictor", "W4_closed_loop_DBTL"):
        row = current.get(key) if isinstance(current.get(key), dict) else {}
        lines.append(f"- {key}: status=`{row.get('status')}` complete=`{row.get('complete')}`")
    execution = current.get("W2_target_msa_execution") if isinstance(current.get("W2_target_msa_execution"), dict) else {}
    lines.append(
        "- W2_target_msa_execution: "
        f"status=`{execution.get('status')}` "
        f"jobs_submitted=`{execution.get('jobs_submitted')}` "
        f"receipt_created_or_updated=`{execution.get('receipt_created_or_updated')}`"
    )
    panel_approval = current.get("W2_panel_approval") if isinstance(current.get("W2_panel_approval"), dict) else {}
    lines.append(
        "- W2_panel_approval: "
        f"status=`{panel_approval.get('status')}` "
        f"ready=`{panel_approval.get('approval_packet_ready')}` "
        f"can_claim_w2_generalization=`{panel_approval.get('can_claim_w2_generalization')}`"
    )
    panel_decision = (
        current.get("W2_panel_decision_protocol")
        if isinstance(current.get("W2_panel_decision_protocol"), dict)
        else {}
    )
    lines.append(
        "- W2_panel_decision_protocol: "
        f"status=`{panel_decision.get('status')}` "
        f"no_submit=`{panel_decision.get('no_submit')}` "
        f"can_claim_now=`{panel_decision.get('can_claim_w2_generalization_now')}` "
        f"current_result=`{panel_decision.get('current_result_status')}`"
    )
    lines.extend(["", "## Active Risks", ""])
    for risk in rep.get("active_risks") or []:
        lines.append(f"- {risk.get('id')}: status=`{risk.get('status')}`; {risk.get('control')}")
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')} ({failure.get('category')}): {failure.get('message')}")
    lines.extend(["", f"Next action: {rep.get('next_action')}", ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-status", default="results/m6c_project_status_w2_followup.json")
    ap.add_argument("--completion-audit", default="results/m6d_goal_completion_audit.json")
    ap.add_argument("--runbook", default="results/m6d_w2_explicit_approval_runbook.json")
    ap.add_argument("--w3-adjudication-audit", default="results/m6d_w3_adjudication_audit.json")
    ap.add_argument("--execution-attempt", default="results/m6d_w2_target_family_redesign_v9_full14_target_msa_execution_attempt.json")
    ap.add_argument("--panel-approval-packet", default="results/m6d_w2_target_family_redesign_v9_panel_approval_packet.json")
    ap.add_argument("--panel-decision-protocol", default="results/m6d_w2_target_family_redesign_v9_panel_decision_protocol.json")
    ap.add_argument("--goal-mode-doc", default="docs/CODEX_GOAL_MODE.md")
    ap.add_argument("--anchor-doc", default="docs/M6D_GOAL_MODE_ANCHOR.md")
    ap.add_argument("--out-json", default="results/m6d_goal_drift_audit.json")
    ap.add_argument("--out-md", default="results/m6d_goal_drift_audit.md")
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

    rep = build_audit(
        _load_json(args.project_status),
        _load_json(args.completion_audit),
        _load_json(args.runbook),
        _load_json(args.w3_adjudication_audit),
        execution_attempt,
        _read_text(args.goal_mode_doc),
        _read_text(args.anchor_doc),
        panel_approval_packet,
        panel_decision_protocol,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(render_markdown(rep))
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0 if rep.get("audit_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
