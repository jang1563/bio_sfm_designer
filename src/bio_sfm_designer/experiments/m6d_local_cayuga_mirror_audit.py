"""Audit local/Cayuga mirror consistency for the active M6d goal state.

This is a no-submit check. It reads selected files from the local checkout and
the Cayuga mirror, then compares exact hashes for stable source/handoff inputs
and semantic fields for generated artifacts that embed machine-specific paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple


_EXACT_SHA_PATHS = [
    "README.md",
    "HANDOFF.md",
    "docs/CODEX_GOAL_MODE.md",
    "docs/M6D_GOAL_MODE_ANCHOR.md",
    "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh",
    "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh",
    "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
    "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
    "results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
    "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
    "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_guarded_preflight.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_receipt_monitor.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_job_state_probe.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_postsubmit_status.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_postsync_interpretation.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_public_approval_bundle.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_remote_submission_readiness.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_submission_decision_state.py",
    "src/bio_sfm_designer/experiments/m6d_local_cayuga_mirror_audit.py",
    "src/bio_sfm_designer/experiments/m6d_goal_completion_audit.py",
    "src/bio_sfm_designer/experiments/m6d_goal_drift_audit.py",
    "src/bio_sfm_designer/experiments/public_surface_sanitize.py",
    "results/m6d_goal_mode_current_anchor.json",
    "results/m6c_cross_predictor.json",
    "results/m6c_cross_predictor_matches.jsonl",
    "results/m6d_w2_w3_decision_protocol.json",
    "results/m6d_w3_adjudication_set.jsonl",
    "results/m6d_w3_adjudication_set.json",
    "results/m6d_w2_explicit_approval_runbook.md",
]


_JSON_FIELD_SPECS: Dict[str, List[str]] = {
    "results/m6c_project_status_w2_followup.json": [
        "status",
        "goal_progress",
        "remaining",
        "complete",
        "can_mark_goal_complete",
        "sync_manifest_audit.ok",
        "sync_manifest_audit.n_checks",
        "workstreams.W1_M6c_scale_up.status",
        "workstreams.W1_M6c_scale_up.complete",
        "workstreams.W2_multi_target_panel.status",
        "workstreams.W2_multi_target_panel.complete",
        "workstreams.W2_multi_target_panel.approval_packet_ready",
        "workstreams.W2_multi_target_panel.approval_parity_ok",
        "workstreams.W2_multi_target_panel.wrapper_guard_audit_ok",
        "workstreams.W2_multi_target_panel.can_submit_proteinmpnn_boltz_panel",
        "workstreams.W2_multi_target_panel.panel_approval_packet_ready",
        "workstreams.W2_multi_target_panel.can_submit_panel_if_user_explicitly_approves",
        "workstreams.W2_multi_target_panel.panel_submission_decision_ready",
        "workstreams.W2_multi_target_panel.panel_submission_decision",
        "workstreams.W2_multi_target_panel.panel_submission_decision_submitted",
        "workstreams.W2_multi_target_panel.panel_submission_decision_can_claim_w2_generalization",
        "workstreams.W2_multi_target_panel.panel_postsync_interpretation_ready",
        "workstreams.W2_multi_target_panel.panel_postsync_status",
        "workstreams.W2_multi_target_panel.panel_postsync_no_submit",
        "workstreams.W2_multi_target_panel.panel_postsync_submitted",
        "workstreams.W2_multi_target_panel.panel_postsync_sync_ready",
        "workstreams.W2_multi_target_panel.panel_postsync_can_claim_w2_generalization",
        "workstreams.W2_multi_target_panel.panel_postsubmit_sync_ready_gate_ok",
        "workstreams.W2_multi_target_panel.panel_postsubmit_bridge_ok",
        "workstreams.W2_multi_target_panel.panel_job_state_query_bridge_ok",
        "workstreams.W2_multi_target_panel.panel_remote_shell_syntax_checks",
        "workstreams.W2_multi_target_panel.panel_approval_scope_ready",
        "workstreams.W2_multi_target_panel.panel_approval_scope_n_ready_targets",
        "workstreams.W2_multi_target_panel.panel_approval_scope_records_per_target_planned",
        "workstreams.W2_multi_target_panel.panel_approval_scope_planned_design_records",
        "workstreams.W2_multi_target_panel.panel_approval_scope_expected_slurm_jobs",
        "workstreams.W2_multi_target_panel.panel_approval_scope_target_alpha",
        "resume_execution_ladder.next_role",
        "resume_execution_ladder.approval_scope.planned_design_records",
        "resume_execution_ladder.approval_scope.expected_slurm_jobs",
        "resume_execution_ladder.approval_disambiguation.continuation_phrases_are_approval",
        "resume_execution_ladder.approval_disambiguation.non_approval_continuation_phrases",
        "resume_execution_ladder.approval_disambiguation.machine_gate",
        "workstreams.W3_independent_predictor.status",
        "workstreams.W3_independent_predictor.complete",
        "workstreams.W3_independent_predictor.positive_claim_supported",
        "workstreams.W4_closed_loop_DBTL.status",
        "workstreams.W4_closed_loop_DBTL.complete",
    ],
    "results/m6d_goal_completion_audit.json": [
        "status",
        "audit_ok",
        "complete",
        "can_mark_goal_complete",
        "remaining_requirements",
        "v9_receipt.exists",
        "workstream_status.W1_M6c_scale_up.status",
        "workstream_status.W1_M6c_scale_up.complete",
        "workstream_status.W2_multi_target_panel.status",
        "workstream_status.W2_multi_target_panel.complete",
        "workstream_status.W3_independent_predictor.status",
        "workstream_status.W3_independent_predictor.complete",
        "workstream_status.W3_independent_predictor.positive_claim_supported",
        "workstream_status.W4_closed_loop_DBTL.status",
        "workstream_status.W4_closed_loop_DBTL.complete",
        "w2_gate.approval_packet_ready",
        "w2_gate.approval_parity_ok",
        "w2_gate.wrapper_guard_ok",
        "w2_gate.panel_submission_blocked",
        "w2_gate.target_msa_ready_if_explicitly_approved",
        "w2_gate.panel_approval_scope_ready",
        "w2_gate.panel_approval_scope_planned_design_records",
        "w2_gate.panel_approval_scope_expected_slurm_jobs",
        "w2_gate.project_status_panel_approval_scope_ready",
        "w2_gate.project_status_panel_approval_scope_planned_design_records",
        "w2_gate.project_status_panel_approval_scope_expected_slurm_jobs",
        "w2_gate.panel_postsync_interpretation_ready",
        "w2_gate.panel_postsync_status",
        "w2_gate.panel_postsync_no_submit",
        "w2_gate.panel_postsync_submitted",
        "w2_gate.panel_postsync_sync_ready",
        "w2_gate.panel_postsync_can_claim_w2_generalization",
        "w2_gate.panel_remote_exact_checks",
        "w2_gate.panel_remote_shell_syntax_checks",
        "w2_gate.panel_remote_shell_syntax_checks_ok",
        "w2_gate.panel_public_approval_bundle_remote_shell_syntax_checks",
        "w2_gate.panel_public_approval_bundle_remote_shell_syntax_checks_ok",
        "w2_gate.panel_public_approval_bundle_workflow_step_count",
        "w2_gate.panel_public_approval_bundle_workflow_sync_ready_before_record_sync",
        "w2_gate.panel_public_approval_bundle_workflow_includes_postsync_interpretation",
        "w2_gate.panel_public_approval_bundle_workflow_driver_command_present",
        "w2_gate.panel_public_approval_bundle_workflow_driver_command_expected",
        "w2_gate.panel_public_approval_bundle_workflow_postsync_replay_command_expected",
        "w2_gate.panel_public_approval_bundle_workflow_driver_replay_command_pair_ready",
        "w2_gate.panel_public_approval_bundle_workflow_driver_polling_contract_ok",
        "w2_gate.panel_public_approval_bundle_workflow_driver_polling_default_max_polls",
        "w2_gate.panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds",
        "w2_gate.panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate",
        "w2_gate.panel_public_approval_bundle_workflow_postsubmit_driver_static_chain_ok",
        "w2_gate.panel_public_approval_bundle_workflow_postsync_replay_static_chain_ok",
        "w2_gate.panel_public_approval_bundle_workflow_sync_back_static_chain_ok",
        "w2_gate.panel_public_approval_bundle_workflow_completion_static_chain_ok",
        "w2_gate.panel_public_approval_bundle_workflow_script_chain_static_ok",
        "w2_gate.panel_public_approval_bundle_scope_ready",
        "w2_gate.panel_public_approval_bundle_scope_planned_design_records",
        "w2_gate.panel_public_approval_bundle_scope_expected_slurm_jobs",
        "w2_gate.panel_submission_decision_operator_checklist_ok",
        "w2_gate.panel_submission_decision_operator_submit_allowed",
        "w2_gate.panel_submission_decision_operator_submission_performed",
        "w2_gate.panel_submission_decision_operator_approval_phrase_required",
        "w2_gate.panel_submission_decision_operator_machine_gate",
        "w2_gate.panel_submission_decision_operator_postsubmit_driver_command",
        "w2_gate.panel_submission_decision_operator_postsync_replay_command",
        "w2_gate.panel_submission_decision_operator_driver_replay_pair_ready",
        "w2_gate.panel_submission_decision_operator_local_receipts_absent",
        "w2_gate.panel_submission_decision_operator_remote_receipts_checked",
        "w2_gate.panel_submission_decision_operator_remote_receipts_absent",
        "w2_gate.panel_submission_decision_operator_planned_design_records",
        "w2_gate.panel_submission_decision_operator_expected_slurm_jobs",
        "w2_gate.panel_submission_decision_operator_target_alpha",
        "w3_gate.audit_ok",
        "w3_gate.positive_claim_supported",
        "w3_gate.adjudication_rows",
        "w3_gate.adjudication_sha256",
    ],
    "results/m6d_w2_target_family_redesign_v9_approval_packet.json": [
        "status",
        "approval_packet_ready",
        "can_submit_target_msa_if_user_explicitly_approves",
        "can_submit_proteinmpnn_boltz_panel",
        "target_count",
        "pending_path_count",
        "target_msa_approval_env_var",
        "target_msa_approval_env_value",
        "wrapper_guard_audit_ok",
        "wrapper_guard_static_ok",
        "wrapper_guard_no_env_run_ok",
        "wrapper_guard_script_sha256",
    ],
    "results/m6d_w2_target_family_redesign_v9_approval_parity.json": [
        "status",
        "parity_ok",
        "approval_packet_ready",
        "panel_submission_blocked",
        "target_count",
        "pending_path_count",
    ],
    "results/m6d_w2_explicit_approval_runbook.json": [
        "status",
        "audit_ok",
        "can_mark_goal_complete",
        "target_count",
        "pending_path_count",
        "target_msa_approval_env_var",
        "target_msa_approval_env_value",
        "submit_command_if_approved",
        "postsubmit_sync_back_command",
        "claim_boundary.target_msa_input_prep",
        "claim_boundary.proteinmpnn_boltz_panel_submission",
        "claim_boundary.w2_multi_target_generalization",
        "runbook_steps",
    ],
    "results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.json": [
        "status",
        "audit_ok",
        "target_msa_approval_env_var",
        "target_msa_approval_env_value",
        "static_audit.ok",
        "static_audit.wrapper_sha256",
        "no_env_run.ok",
        "no_env_run.returncode",
        "no_env_run.receipt_exists_before",
        "no_env_run.receipt_exists_after",
        "no_env_run.refusal_message_seen",
    ],
    "results/m6d_w3_adjudication_audit.json": [
        "status",
        "audit_ok",
        "positive_claim_supported",
        "claim_boundary",
        "current_protocol_verdict",
        "selected_protocol",
        "label_agreement",
        "min_label_agreement",
        "matched_overlap",
        "adjudication_set_artifact_audit.ok",
        "adjudication_set_artifact_audit.n_rows",
        "adjudication_set_artifact_audit.actual_sha256",
    ],
    "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json": [
        "status",
        "audit_ok",
        "approval_packet_ready",
        "can_submit_panel_if_user_explicitly_approves",
        "can_claim_w2_generalization",
        "checks.target_msa_strict_ready",
        "checks.panel_preflight_ready",
        "checks.panel_dry_run_no_sbatch",
        "checks.panel_guard_no_env_refuses",
        "checks.submit_receipt_absent",
        "checks.submit_summary_absent",
        "panel_approval_env_var",
        "panel_approval_env_value",
        "receipt_monitor_after_submit",
        "job_state_query_after_receipt",
        "job_state_probe_sync_after_query",
        "postsubmit_status_before_sync",
        "job_state_probe_before_sync",
        "sacct_states_before_sync",
        "postsubmit_sync_ready_gate",
        "postsubmit_status_command_before_sync",
        "postsync_replay_after_sync",
        "target_alpha",
        "approval_scope.n_ready_targets",
        "approval_scope.records_per_target_planned",
        "approval_scope.planned_design_records",
        "approval_scope.expected_job_pairs",
        "approval_scope.expected_slurm_jobs",
        "approval_scope.target_alpha",
    ],
    "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json": [
        "status",
        "audit_ok",
        "no_submit",
        "can_submit_panel_if_user_explicitly_approves",
        "can_claim_w2_generalization",
        "n_exact_checks",
        "n_semantic_checks",
        "n_absence_checks",
        "n_shell_syntax_checks",
        "n_failures",
    ],
    "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "can_claim_w2_generalization",
        "approval_boundary.explicit_approval_required",
        "approval_boundary.continuation_phrases_are_approval",
        "approval_boundary.machine_gate",
        "target_contract.target_alpha",
        "target_contract.min_targets",
        "target_contract.min_records_per_target",
        "approval_scope.n_ready_targets",
        "approval_scope.records_per_target_planned",
        "approval_scope.planned_design_records",
        "approval_scope.expected_job_pairs",
        "approval_scope.expected_slurm_jobs",
        "approval_scope.target_alpha",
        "prerequisites.remote_readiness.status",
        "prerequisites.remote_readiness.n_exact_checks",
        "prerequisites.remote_readiness.n_shell_syntax_checks",
        "prerequisites.remote_readiness.shell_syntax_checks_ok",
        "prerequisites.remote_readiness.n_failures",
        "post_approval_workflow.manual_step_count",
        "post_approval_workflow.all_manual_commands_present",
        "post_approval_workflow.requires_sync_ready_before_record_sync",
        "post_approval_workflow.includes_sync_back",
        "post_approval_workflow.includes_completion",
        "post_approval_workflow.includes_postsync_interpretation",
        "post_approval_workflow.driver_command_present",
        "post_approval_workflow.driver_command_expected",
        "post_approval_workflow.postsync_replay_command_expected",
        "post_approval_workflow.driver_replay_command_pair_ready",
        "post_approval_workflow.driver_polling_contract_ok",
        "postsubmit_driver_polling.max_polls_env_var",
        "postsubmit_driver_polling.default_max_polls",
        "postsubmit_driver_polling.poll_seconds_env_var",
        "postsubmit_driver_polling.default_poll_seconds",
        "postsubmit_driver_polling.proceeds_only_when_sync_ready",
        "postsubmit_driver_polling.sync_ready_gate",
        "post_approval_workflow.driver_proceeds_only_when_sync_ready",
    ],
    "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json": [
        "status",
        "audit_ok",
        "decision",
        "no_submit",
        "submitted",
        "explicit_approval_required",
        "approval_disambiguation.continuation_phrases_are_approval",
        "approval_disambiguation.approval_must_explicitly_name",
        "approval_disambiguation.machine_gate",
        "operator_approval_checklist.pre_submit_state_ok",
        "operator_approval_checklist.submit_allowed_by_this_artifact",
        "operator_approval_checklist.submission_performed_by_this_artifact",
        "operator_approval_checklist.approval_phrase_required",
        "operator_approval_checklist.continuation_phrases_are_approval",
        "operator_approval_checklist.machine_gate",
        "operator_approval_checklist.postsubmit_driver_command",
        "operator_approval_checklist.postsync_replay_command",
        "operator_approval_checklist.driver_replay_command_pair_ready",
        "operator_approval_checklist.local_receipts_absent",
        "operator_approval_checklist.remote_receipts_checked",
        "operator_approval_checklist.remote_receipts_absent",
        "operator_approval_checklist.planned_design_records",
        "operator_approval_checklist.expected_slurm_jobs",
        "operator_approval_checklist.target_alpha",
        "operator_approval_checklist.no_submit",
        "operator_approval_checklist.submitted",
        "operator_approval_checklist.can_claim_w2_generalization",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_ready",
        "can_submit_if_explicitly_approved",
        "can_claim_w2_generalization",
        "approval_scope.n_ready_targets",
        "approval_scope.records_per_target_planned",
        "approval_scope.planned_design_records",
        "approval_scope.expected_job_pairs",
        "approval_scope.expected_slurm_jobs",
        "approval_scope.target_alpha",
        "prerequisites.approval_packet.approval_scope_ok",
        "receipt_absence.remote_checked",
        "prerequisites.remote_submission_readiness.n_shell_syntax_checks",
        "prerequisites.remote_submission_readiness.shell_syntax_checks_ok",
        "prerequisites.project_status.w2_panel_remote_shell_syntax_checks",
        "prerequisites.project_status.w2_panel_approval_scope_ok",
        "prerequisites.project_status.w2_panel_approval_scope_planned_design_records",
        "prerequisites.project_status.w2_panel_approval_scope_expected_slurm_jobs",
        "prerequisites.goal_completion_audit.w2_panel_approval_scope_ready",
        "prerequisites.goal_completion_audit.w2_panel_approval_scope_planned_design_records",
        "prerequisites.goal_completion_audit.w2_panel_approval_scope_expected_slurm_jobs",
        "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_ready",
        "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_planned_design_records",
        "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_expected_slurm_jobs",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_ready",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_planned_design_records",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_expected_slurm_jobs",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_step_count",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_all_commands_present",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_sync_ready_before_record_sync",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_includes_postsync_interpretation",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_command_present",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_command_expected",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_postsync_replay_command_expected",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_replay_command_pair_ready",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_contract_ok",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_default_max_polls",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_sync_ready_only",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_postsubmit_driver_static_chain_ok",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_postsync_replay_static_chain_ok",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_sync_back_static_chain_ok",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_completion_static_chain_ok",
        "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_script_chain_static_ok",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_checklist_ok",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_submit_allowed",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_submission_performed",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_approval_phrase_required",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_machine_gate",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_postsubmit_driver_command",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_postsync_replay_command",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_driver_replay_pair_ready",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_remote_receipts_absent",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_planned_design_records",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_expected_slurm_jobs",
        "prerequisites.goal_completion_audit.w2_panel_submission_decision_operator_target_alpha",
    ],
    "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "sync_ready",
        "can_claim_w2_generalization",
        "manifest_targets",
        "receipt_exists",
        "summary_exists",
    ],
    "results/m6d_w2_target_family_redesign_v11_job_state_probe.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "receipt_exists",
        "n_jobs",
        "n_states",
        "n_missing_states",
    ],
    "results/m6d_w2_target_family_redesign_v11_receipt_monitor.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "remote_checked",
        "local_receipt_ready",
        "remote_receipt_ready",
        "can_sync_receipt",
        "can_run_job_state_probe",
    ],
    "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "sync_ready",
        "can_claim_w2_generalization",
        "target_alpha",
        "min_targets",
        "min_records_per_target",
    ],
    "results/m6d_goal_drift_audit.json": [
        "status",
        "audit_ok",
        "major_direction_drift",
        "can_mark_goal_complete",
        "current_state.W2_panel_submission_decision.status",
        "current_state.W2_panel_submission_decision.decision",
        "current_state.W2_panel_submission_decision.submitted",
        "current_state.W2_panel_submission_decision.operator_checklist_ok",
        "current_state.W2_panel_submission_decision.operator_submit_allowed_by_this_artifact",
        "current_state.W2_panel_submission_decision.operator_submission_performed_by_this_artifact",
        "current_state.W2_panel_submission_decision.operator_driver_replay_command_pair_ready",
        "current_state.W2_panel_submission_decision.operator_remote_receipts_absent",
        "current_state.W2_panel_submission_decision.operator_planned_design_records",
        "current_state.W2_panel_submission_decision.operator_expected_slurm_jobs",
        "current_state.completion_audit.status",
        "current_state.completion_audit.can_mark_goal_complete",
        "current_state.completion_audit.panel_public_approval_bundle_ready",
        "current_state.W2_panel_remote_readiness.n_exact_checks",
        "current_state.W2_panel_remote_readiness.n_shell_syntax_checks",
        "current_state.W2_panel_remote_readiness.shell_syntax_checks_ok",
        "drift_assessment.execution",
    ],
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _field(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _semantic_value(semantic_checks: List[Dict[str, Any]], rel_path: str, dotted: str) -> Any:
    for row in semantic_checks:
        if row.get("path") != rel_path:
            continue
        for field in row.get("fields") or []:
            if field.get("field") == dotted:
                return field.get("local")
    return None


def _semantic_values(semantic_checks: List[Dict[str, Any]]) -> List[Any]:
    values: List[Any] = []
    for row in semantic_checks:
        for field in row.get("fields") or []:
            if isinstance(field, dict) and "local" in field:
                values.append(field.get("local"))
    return values


def _next_action(*, audit_ok: bool, semantic_checks: List[Dict[str, Any]]) -> str:
    if not audit_ok:
        return "sync or regenerate mismatched local/Cayuga artifacts before continuing goal-mode execution"
    w2_status = _semantic_value(
        semantic_checks,
        "results/m6c_project_status_w2_followup.json",
        "workstreams.W2_multi_target_panel.status",
    )
    panel_decision_status = _semantic_value(
        semantic_checks,
        "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json",
        "status",
    )
    semantic_values = _semantic_values(semantic_checks)
    if (
        w2_status == "panel_approval_packet_ready_awaiting_explicit_approval"
        or panel_decision_status == "awaiting_explicit_panel_submission_approval"
        or "panel_approval_packet_ready_awaiting_explicit_approval" in semantic_values
        or "awaiting_explicit_panel_submission_approval" in semantic_values
    ):
        return (
            "mirror is aligned; W2 remains blocked only on explicit panel submission approval, "
            "then sync-back, completion, target-wise reporting, and post-sync interpretation"
        )
    return "mirror is aligned; W2 remains blocked only on explicit target-MSA approval and replay"


def _read_local(root: str, rel_path: str) -> bytes:
    with open(os.path.join(root, rel_path), "rb") as fh:
        return fh.read()


def _read_remote(remote_root: str, rel_path: str, *, remote_host: Optional[str]) -> bytes:
    path = os.path.join(remote_root, rel_path)
    if not remote_host:
        return _read_local(remote_root, rel_path)
    cmd = ["ssh", remote_host, f"cat {shlex.quote(path)}"]
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def _read_pair(local_root: str,
               remote_root: str,
               rel_path: str,
               *,
               remote_host: Optional[str]) -> Tuple[Optional[bytes], Optional[bytes], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    local: Optional[bytes] = None
    remote: Optional[bytes] = None
    try:
        local = _read_local(local_root, rel_path)
    except Exception as exc:
        failures.append({"kind": "local_file_read_failed", "path": rel_path, "error": str(exc)})
    try:
        remote = _read_remote(remote_root, rel_path, remote_host=remote_host)
    except Exception as exc:
        failures.append({"kind": "remote_file_read_failed", "path": rel_path, "error": str(exc)})
    return local, remote, failures


def build_audit(*,
                local_root: str,
                remote_root: str,
                remote_host: Optional[str],
                exact_sha_paths: Iterable[str] = _EXACT_SHA_PATHS,
                json_field_specs: Dict[str, List[str]] = _JSON_FIELD_SPECS) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    exact_checks: List[Dict[str, Any]] = []
    semantic_checks: List[Dict[str, Any]] = []

    for rel_path in exact_sha_paths:
        local, remote, read_failures = _read_pair(local_root, remote_root, rel_path, remote_host=remote_host)
        failures.extend(read_failures)
        row: Dict[str, Any] = {"path": rel_path, "ok": False}
        if local is not None:
            row["local_sha256"] = _sha256(local)
            row["local_bytes"] = len(local)
        if remote is not None:
            row["remote_sha256"] = _sha256(remote)
            row["remote_bytes"] = len(remote)
        if local is not None and remote is not None:
            row["ok"] = row["local_sha256"] == row["remote_sha256"]
            if not row["ok"]:
                failures.append({
                    "kind": "exact_sha_mismatch",
                    "path": rel_path,
                    "local_sha256": row["local_sha256"],
                    "remote_sha256": row["remote_sha256"],
                })
        exact_checks.append(row)

    for rel_path, fields in json_field_specs.items():
        local, remote, read_failures = _read_pair(local_root, remote_root, rel_path, remote_host=remote_host)
        failures.extend(read_failures)
        row: Dict[str, Any] = {"path": rel_path, "ok": False, "fields": []}
        if local is None or remote is None:
            semantic_checks.append(row)
            continue
        try:
            local_obj = json.loads(local.decode("utf-8"))
            remote_obj = json.loads(remote.decode("utf-8"))
        except Exception as exc:
            failures.append({"kind": "json_parse_failed", "path": rel_path, "error": str(exc)})
            semantic_checks.append(row)
            continue
        field_failures = []
        for dotted in fields:
            local_value = _field(local_obj, dotted)
            remote_value = _field(remote_obj, dotted)
            field_ok = local_value == remote_value
            row["fields"].append({
                "field": dotted,
                "ok": field_ok,
                "local": local_value,
                "remote": remote_value,
            })
            if not field_ok:
                field_failures.append({
                    "kind": "semantic_field_mismatch",
                    "path": rel_path,
                    "field": dotted,
                    "local": local_value,
                    "remote": remote_value,
                })
        row["ok"] = not field_failures
        failures.extend(field_failures)
        semantic_checks.append(row)

    audit_ok = not failures
    return {
        "artifact": "m6d_local_cayuga_mirror_audit",
        "status": "local_cayuga_mirror_agree" if audit_ok else "local_cayuga_mirror_drift",
        "audit_ok": audit_ok,
        "can_mark_goal_complete": False,
        "claim_boundary": "no-submit mirror consistency audit; does not run target-MSA, GPU, API, or panel jobs",
        "local_root": os.path.abspath(local_root),
        "remote_host": remote_host or "",
        "remote_root": remote_root,
        "exact_checks": exact_checks,
        "semantic_checks": semantic_checks,
        "n_exact_checks": len(exact_checks),
        "n_semantic_checks": len(semantic_checks),
        "n_failures": len(failures),
        "failures": failures,
        "next_action": _next_action(audit_ok=audit_ok, semantic_checks=semantic_checks),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d Local/Cayuga Mirror Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit mirror audit. It does not run target-MSA, GPU, API, or panel jobs.",
        "",
        "| check type | count |",
        "|---|---:|",
        f"| exact SHA checks | {rep.get('n_exact_checks')} |",
        f"| semantic JSON checks | {rep.get('n_semantic_checks')} |",
        f"| failures | {rep.get('n_failures')} |",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')} `{failure.get('path')}`: {failure.get('field', failure.get('error', ''))}")
        lines.append("")
    lines.extend([f"Next action: {rep.get('next_action')}", ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-root", default=".")
    ap.add_argument("--remote-host", default=os.environ.get("CAYUGA_BIO_SFM_HOST", ""))
    ap.add_argument("--remote-root", default=os.environ.get("CAYUGA_BIO_SFM_ROOT", ""))
    ap.add_argument("--out-json", default="results/m6d_local_cayuga_mirror_audit.json")
    ap.add_argument("--out-md", default="results/m6d_local_cayuga_mirror_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(
        local_root=args.local_root,
        remote_root=args.remote_root,
        remote_host=args.remote_host,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} exact={exact} semantic={semantic} failures={failures}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            exact=rep["n_exact_checks"],
            semantic=rep["n_semantic_checks"],
            failures=rep["n_failures"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
