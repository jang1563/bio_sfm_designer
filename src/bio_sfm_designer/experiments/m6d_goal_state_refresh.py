"""Refresh current M6d goal artifacts from terminal W2b and no-submit W2c evidence.

The older goal audits contain useful historical detail but predate W2b.  This
refresh layer preserves that detail, marks obsolete W2 execution branches as
historical, and replaces every current-status and next-action surface with one
consistent terminal-W2b / precompute-W2c state.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional


_W2B_TERMINAL_STATUS = "w2b_certification_terminal_not_supported"
_W2C_DESIGN_STATUS = "w2c_design_power_qualified_no_submit"
_GOAL_STATUS = "goal_active_w2b_terminal_w2c_precompute"
_NEXT_ACTION = (
    "Implement the locked W2c evaluator and construct an eight-target fresh manifest with complete "
    "historical, source, sequence, MSA, and hash-lock checks; do not generate records or submit Cayuga "
    "jobs until those gates pass and explicit operator approval is recorded."
)
_TARGET_NEXT_ACTION = (
    "Select and hash-lock eight label-blind fresh W2c targets with zero historical/W2b target or source "
    "overlap, distinct sequence clusters, and complete prepared/FASTA/MSA provenance; keep Cayuga record "
    "generation blocked until strict preflight and explicit operator approval."
)
_MSA_NEXT_ACTION = (
    "Prepare a guarded target-MSA-only packet for the eight locked W2c targets, validate it locally and "
    "on Cayuga with zero record-generation jobs, and require a separate explicit approval before MSA "
    "submission; W2c ProteinMPNN/Boltz generation remains blocked."
)
_APPROVAL_NEXT_ACTION = (
    "Wait for explicit user approval naming W2c target-MSA precompute. Do not infer approval from generic "
    "continuation or goal-mode resume; ProteinMPNN/Boltz record generation remains separately blocked."
)


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminal_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    gate = report.get("panel_certification_gate", {})
    checks = {
        "status_terminal": report.get("status") == _W2B_TERMINAL_STATUS,
        "audit_ok": report.get("audit_ok") is True,
        "panel_gate_failed": gate.get("passed") is False,
        "terminal_after_certification": report.get("terminal_after_certification") is True,
        "test_cannot_change_certificate": report.get("test_can_change_certificate") is False,
        "test_not_required": report.get("test_required_for_final_reporting") is False,
        "positive_claim_false": report.get("can_claim_w2b_target_adaptive_viability") is False,
        "test_rows_absent": not report.get("records", {}).get("test"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W2b terminal invariants failed: {', '.join(failed)}")
    return {
        "status": report.get("status"),
        "audit_ok": True,
        "certified_targets": report.get("certified_targets", []),
        "selective_pae_certified_targets": report.get("selective_pae_certified_targets", []),
        "panel_certification_gate": gate,
        "terminal_after_certification": True,
        "test_can_change_certificate": False,
        "test_compute_submitted": False,
        "can_claim_w2b_target_adaptive_viability": False,
        "checks": checks,
    }


def _w2c_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    checks = {
        "status_ready": report.get("status") == _W2C_DESIGN_STATUS,
        "audit_ok": report.get("audit_ok") is True,
        "design_power_qualified": report.get("design_power_qualified") is True,
        "execution_not_ready": report.get("execution_ready") is False,
        "no_submit": report.get("no_submit") is True,
        "cayuga_submission_blocked": report.get("cayuga_submission_allowed") is False,
        "positive_claim_false": report.get("can_claim_w2c") is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W2c design-gate invariants failed: {', '.join(failed)}")
    certification = report.get("certification_design", {})
    readiness = report.get("execution_readiness", {})
    return {
        "status": report.get("status"),
        "audit_ok": True,
        "design_power_qualified": True,
        "execution_ready": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_w2c": False,
        "locked_scientific_digest": report.get("locked_scientific_digest"),
        "conditional_certification_power": certification.get("conditional_certification_power"),
        "minimum_conditional_power": certification.get("minimum_conditional_power"),
        "minimum_accepted": certification.get("minimum_accepted"),
        "design_true_risk": certification.get("design_true_risk"),
        "evaluator_implemented": readiness.get("evaluator_implemented") is True,
        "evaluator_module": readiness.get("evaluator_module"),
        "target_manifest_present": readiness.get("target_manifest_present") is True,
        "target_manifest_integrity_ok": readiness.get("target_manifest_integrity_ok") is True,
        "target_manifest_ids": readiness.get("target_manifest_ids", []),
        "target_msa_ready": readiness.get("target_msa_ready") is True,
        "remaining_unlock_conditions": report.get("remaining_unlock_conditions", []),
        "checks": checks,
    }


def _mark_historical(value: Any, superseded_by: str) -> None:
    if isinstance(value, dict):
        value["historical"] = True
        value["superseded_by"] = superseded_by


def _target_msa_packet_summary(packet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(packet, dict):
        return None
    approval = packet.get("approval", {})
    checks = packet.get("checks", {})
    required = {
        "status_ready": packet.get("status") == "ready_for_explicit_target_msa_approval_not_submitted",
        "audit_ok": packet.get("audit_ok") is True,
        "submission_not_performed": approval.get("submission_performed") is False,
        "explicit_approval_required": approval.get("explicit_user_approval_required") is True,
        "local_dry_run_passed": checks.get("local_guard_dry_run_passed") is True,
        "cayuga_dry_run_passed": checks.get("cayuga_guard_dry_run_passed") is True,
        "input_parity_passed": checks.get("local_cayuga_input_sha_mismatches") == 0,
        "no_slurm_delta": checks.get("cayuga_slurm_jobs_before") == checks.get("cayuga_slurm_jobs_after"),
        "receipt_absent": checks.get("cayuga_receipt_absent") is True,
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError(f"W2c target-MSA packet invariants failed: {', '.join(failed)}")
    return {
        "status": packet.get("status"),
        "audit_ok": True,
        "n_targets": packet.get("scope", {}).get("n_targets"),
        "target_ids": packet.get("scope", {}).get("target_ids", []),
        "expected_slurm_jobs": packet.get("scope", {}).get("expected_slurm_jobs"),
        "input_sha_matches": checks.get("local_cayuga_input_sha_matches"),
        "input_sha_mismatches": checks.get("local_cayuga_input_sha_mismatches"),
        "submission_performed": False,
        "explicit_user_approval_required": True,
        "required_user_phrase": approval.get("required_user_phrase"),
        "authorizes_record_generation": False,
        "checks": required,
    }


def refresh_bundle(
    anchor: Dict[str, Any],
    completion: Dict[str, Any],
    drift: Dict[str, Any],
    actions: Dict[str, Any],
    harness: Dict[str, Any],
    w2b_report: Dict[str, Any],
    w2c_gate: Dict[str, Any],
    w2c_target_msa_packet: Optional[Dict[str, Any]] = None,
    *,
    updated_at: str,
    test_command: str,
    test_result: str,
    runtime_goal_active: bool = False,
) -> Dict[str, Dict[str, Any]]:
    w2b = _terminal_summary(w2b_report)
    w2c = _w2c_summary(w2c_gate)
    w2c_target_msa = _target_msa_packet_summary(w2c_target_msa_packet)
    if w2c_target_msa is not None:
        next_action = _APPROVAL_NEXT_ACTION
        remaining_requirement = "W2c_target_MSA_completion_and_fit_packet_gate"
        resume_steps = [
            "read docs/M6D_W2B_CERTIFICATION_COMPLETION.md and preserve W2b as terminal",
            "read docs/M6D_W2C_ONE_SHOT_PROTOCOL.md and results/m6d_w2c_design_gate.json",
            "read docs/M6D_W2C_TARGET_MSA_APPROVAL.md and results/m6d_w2c_target_msa_approval_packet.json",
            "do not infer W2c target-MSA approval from continue, go ahead, or goal-mode resume",
            "if explicitly approved, submit only the eight guarded target-MSA jobs and preserve the receipt",
            "after MSA completion, sync and hash-lock all eight MSA/report pairs before preparing a separate fit packet",
            "do not authorize ProteinMPNN/Boltz record generation from the target-MSA approval",
            "move to W3 if W2c cannot pass its locked prospective gates",
        ]
        ranked_actions = [
            "Wait for explicit approval naming W2c target-MSA precompute; no job is currently submitted.",
            "After approved MSA jobs finish, sync and hash-lock all eight MSA/report pairs.",
            "Prepare a separate no-submit W2c fit-stage input lock and bounded execution packet.",
            "Stop W2c before certification if fewer than three selective targets pass the independent fit screen.",
            "Move to W3 if the prospective W2c protocol cannot qualify without changing its locked rules.",
        ]
    elif w2c["target_manifest_present"] and not w2c["target_msa_ready"]:
        next_action = _MSA_NEXT_ACTION
        remaining_requirement = "W2c_target_MSA_packet_gate"
        resume_steps = [
            "preserve W2b as terminal and do not reuse its rows",
            "read configs/m6d_w2c_fresh_targets.json and results/m6d_w2c_target_selection.json",
            "prepare a guarded target-MSA-only packet with local/Cayuga dry-run and input parity",
            "keep ProteinMPNN/Boltz record generation blocked",
        ]
        ranked_actions = [
            "Prepare and validate the guarded W2c target-MSA-only packet.",
            "Keep all W2c record generation blocked until target MSAs are synced and hash-locked.",
            "Move to W3 if prospective W2c gates require post-hoc changes.",
        ]
    elif w2c["evaluator_implemented"]:
        next_action = _TARGET_NEXT_ACTION
        remaining_requirement = "W2c_fresh_target_manifest_gate"
        resume_steps = [
            "preserve W2b as terminal and do not reuse its rows",
            "select eight label-blind fresh W2c targets under historical/source/sequence exclusion",
            "keep Cayuga submission blocked",
        ]
        ranked_actions = [
            "Select eight entirely fresh source-diverse and sequence-diverse targets without outcome labels.",
            "Hash-lock target inputs before any compute packet.",
            "Move to W3 if prospective W2c gates require post-hoc changes.",
        ]
    else:
        next_action = _NEXT_ACTION
        remaining_requirement = "W2c_evaluator_and_fresh_target_gate"
        resume_steps = [
            "preserve W2b as terminal and do not reuse its rows",
            "implement and test the locked W2c evaluator",
            "keep Cayuga submission blocked",
        ]
        ranked_actions = [
            "Implement the locked W2c evaluator and its fail-closed regression tests.",
            "Select eight entirely fresh targets only after the evaluator is fixed.",
            "Move to W3 if prospective W2c gates require post-hoc changes.",
        ]
    date = updated_at.split("T", 1)[0]

    refreshed_anchor = copy.deepcopy(anchor)
    refreshed_anchor["date"] = date
    refreshed_anchor["goal_mode"] = (
        "active" if runtime_goal_active else "contract_ready_runtime_goal_inactive"
    )
    refreshed_anchor["objective"] = (
        "Advance M6d from terminal W2b v1 to a one-shot W2c selective-pAE successor: preserve W1-W4 "
        "claim boundaries, block compute until the fresh-target/evaluator/approval gates pass, and move "
        "to W3 rather than iterating W2 if W2c cannot qualify prospectively."
    )
    refreshed_anchor.setdefault("claim_boundaries", {}).update({
        "w2_multi_target_generalization": "not_supported",
        "w2b_target_adaptive_viability": "terminal_not_supported",
        "w2c_selective_target_adaptive_viability": "not_tested_design_only",
    })
    refreshed_anchor.setdefault("current_artifacts", {}).update({
        "w2b_certification_completion": "docs/M6D_W2B_CERTIFICATION_COMPLETION.md",
        "w2b_certification_report": "results/m6d_w2b_target_adaptive_certification_report.json",
        "w2c_protocol": "configs/m6d_w2c_one_shot_protocol.json",
        "w2c_design_gate": "results/m6d_w2c_design_gate.json",
        "w2c_design_gate_md": "results/m6d_w2c_design_gate.md",
        "w2c_target_manifest": "configs/m6d_w2c_fresh_targets.json",
        "w2c_target_selection": "results/m6d_w2c_target_selection.json",
        "w2c_target_msa_approval_packet": "results/m6d_w2c_target_msa_approval_packet.json",
        "goal_state_refresh": "results/m6d_goal_state_refresh_report.json",
    })
    refreshed_anchor["current_status"] = {
        "status": "m6_complex_in_progress_w2b_terminal_w2c_design_no_submit",
        "goal_progress": "local_w2c_precompute_work_required",
        "runtime_goal_active": runtime_goal_active,
        "remaining_requirements": [remaining_requirement],
        "w1": "target_specific_certification_supported",
        "w2": "universal_multi_target_generalization_not_supported",
        "w2b": w2b["status"],
        "w2c": w2c["status"],
        "w2c_execution_ready": False,
        "w2c_cayuga_submission_allowed": False,
        "w2c_target_manifest_present": w2c["target_manifest_present"],
        "w2c_target_msa_ready": w2c["target_msa_ready"],
        "w2c_target_msa_packet_status": w2c_target_msa["status"] if w2c_target_msa else None,
        "w3": "negative_robustness_result_adjudicated",
        "w4": "closed_loop_plumbing_supported_fail_closed_only",
        "local_harness_status": "results/m6d_goal_mode_local_harness_status.json",
        "local_harness_verification": f"{test_result} with {test_command}",
        "goal_completion_audit": "results/m6d_goal_completion_audit.json",
        "goal_drift_audit": "results/m6d_goal_drift_audit.json",
        "next_action": next_action,
    }
    refreshed_anchor["w2b_terminal_result"] = w2b
    refreshed_anchor["w2c_successor"] = w2c
    refreshed_anchor["w2c_target_msa_approval"] = w2c_target_msa
    refreshed_anchor["next_resume_steps"] = resume_steps
    refreshed_anchor["latest_goal_mode_refresh"] = {
        "updated_at": updated_at,
        "local_harness": test_result,
        "runtime_goal_active": runtime_goal_active,
        "w2b_status": w2b["status"],
        "w2c_status": w2c["status"],
        "w2c_execution_ready": False,
        "w2c_cayuga_submission_allowed": False,
        "w2c_target_manifest_present": w2c["target_manifest_present"],
        "w2c_target_msa_ready": w2c["target_msa_ready"],
        "w2c_target_msa_packet_status": w2c_target_msa["status"] if w2c_target_msa else None,
        "remaining_requirement": remaining_requirement,
    }

    refreshed_completion = copy.deepcopy(completion)
    refreshed_completion.update({
        "status": _GOAL_STATUS,
        "audit_ok": True,
        "complete": False,
        "can_mark_goal_complete": False,
        "failures": [],
        "remaining_requirements": [remaining_requirement],
        "next_action": next_action,
        "w2b_terminal_result": w2b,
        "w2c_successor": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
    })
    refreshed_completion["claim_boundary"] = {
        "w1": "target-specific certified evidence preserved",
        "w2": "universal multi-target generalization not supported",
        "w2b": "terminally not supported; no test compute and no extension",
        "w2c": "power-qualified design only; no targets, compute, certificate, or claim",
        "w3": "negative no-MSA Chai robustness result preserved; no positive independent-predictor claim",
        "w4": "closed-loop plumbing evidence preserved as fail-closed only",
    }
    workstreams = refreshed_completion.setdefault("workstream_status", {})
    workstreams["W2_multi_target_panel"] = {
        "complete": True,
        "scientific_success": False,
        "status": _W2B_TERMINAL_STATUS,
        "successor": _W2C_DESIGN_STATUS,
    }
    refreshed_completion.setdefault("w2_gate", {}).update({
        "status": "historical_pre_w2b_panel_path_superseded",
        "historical": True,
        "superseded_by": _W2B_TERMINAL_STATUS,
        "panel_submission_blocked": True,
        "panel_can_submit_if_explicitly_approved": False,
        "target_msa_ready_if_explicitly_approved": False,
    })
    for key in (
        "w2_execution_attempt",
        "w2_panel_approval",
        "w2_panel_decision_protocol",
        "w2_panel_postsync_interpretation",
        "w2_panel_public_approval_bundle",
        "w2_panel_remote_readiness",
        "w2_panel_submission_decision",
    ):
        _mark_historical(refreshed_completion.get(key), _W2B_TERMINAL_STATUS)

    refreshed_drift = copy.deepcopy(drift)
    refreshed_drift.update({
        "status": "no_major_direction_drift_w2b_terminal_w2c_precompute",
        "audit_ok": True,
        "major_direction_drift": False,
        "can_mark_goal_complete": False,
        "failures": [],
        "next_action": next_action,
    })
    refreshed_drift["claim_boundary"] = {
        "publication": "not_current_goal",
        "w1": "preserved_target_specific_certificate",
        "w2": "generalization_not_supported",
        "w2b": "terminal_not_supported_no_extension",
        "w2c": "design_only_no_submit_no_claim",
        "w3": "negative_robustness_adjudicated_no_positive_claim",
        "w4": "closed_loop_plumbing_only",
    }
    refreshed_drift["active_risks"] = [
        {
            "id": "w2b_result_reinterpretation",
            "status": "managed",
            "control": "W2b is terminal and its rows are planning-only for W2c",
        },
        {
            "id": "trust_all_overclaim",
            "status": "managed",
            "control": "W2c permits selective_pae only and trust_all cannot satisfy panel success",
        },
        {
            "id": "underpowered_or_adaptive_w2c",
            "status": "managed",
            "control": "exact power floor, fixed sample sizes, and no adaptive top-up are locked before compute",
        },
        {
            "id": "verification_instead_of_science",
            "status": "managed",
            "control": "next work is evaluator plus fresh-target qualification; no further W2b validation is allowed",
        },
    ]
    refreshed_drift["drift_assessment"] = {
        "mission": "no_drift_external_calibrated_trust_gate_north_star_preserved",
        "protocol": "no_drift_w2b_lock_preserved_w2c_declared_as_new_experiment",
        "claims": "no_drift_negative_boundaries_preserved",
        "execution": "w2b_closed_without_nondecisive_test_compute_w2c_no_submit",
        "operational_status": "stale_current_surfaces_replaced_historical_detail_retained",
        "major_direction_drift": False,
    }
    current_state = refreshed_drift.setdefault("current_state", {})
    current_state["W2_multi_target_panel"] = {
        "complete": True,
        "scientific_success": False,
        "status": _W2B_TERMINAL_STATUS,
    }
    current_state["W2b_terminal_result"] = w2b
    current_state["W2c_successor"] = w2c
    current_state["W2c_target_msa_approval"] = w2c_target_msa
    current_state.setdefault("completion_audit", {}).update({
        "status": _GOAL_STATUS,
        "can_mark_goal_complete": False,
        "historical_panel_fields_retained": True,
    })
    for key, value in current_state.items():
        if key.startswith("W2_") and key not in {"W2_multi_target_panel"}:
            _mark_historical(value, _W2B_TERMINAL_STATUS)

    refreshed_actions = {
        "artifact": "m6d_followup_next_science_actions",
        "date": date,
        "status": "w2b_terminal_w2c_design_gate_no_submit",
        "target_alpha": 0.2,
        "claim_boundary": {
            "w1_target_specific": "supported",
            "w2_multi_target_generalization": "not_supported",
            "w2b_target_adaptive_viability": "terminal_not_supported",
            "w2c_selective_target_adaptive_viability": "not_tested_design_only",
            "w3_independent_predictor_robustness": "not_supported_predictor_disagreement",
            "w4_closed_loop": "fail_closed_plumbing_only",
        },
        "w2b_terminal_result": w2b,
        "w2c_successor": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
        "next_actions_ranked": ranked_actions,
        "next_action": next_action,
        "no_submit": True,
        "cayuga_submission_allowed": False,
    }

    refreshed_harness = {
        "artifact": "m6d_goal_mode_local_harness_status",
        "updated_at": updated_at,
        "goal_mode_status": (
            "active_w2c_precompute" if runtime_goal_active else "contract_ready_runtime_goal_inactive"
        ),
        "science_focus": "W2b terminal preservation plus W2c selective one-shot precompute qualification",
        "local_verification": {
            "command": test_command,
            "result": test_result,
            "w2b_terminal_regression": "preserved",
            "w2c_design_gate": w2c["status"],
        },
        "hpc_status": {
            "active_branch": "none",
            "jobs_running": 0,
            "w2b_test_compute": "not_submitted_terminal_futility_stop",
            "w2c_submission_allowed": False,
            "w2c_target_msa_packet_status": w2c_target_msa["status"] if w2c_target_msa else None,
            "next_action": next_action,
        },
        "claim_boundary": {
            "w2b": "terminal_not_supported",
            "w2c": "design_only_no_submit_no_claim",
            "w3": "negative_robustness_result_preserved",
        },
        "w3_runtime_provision": harness.get("w3_runtime_provision", {}),
    }

    report = {
        "artifact": "m6d_goal_state_refresh_report",
        "status": "goal_state_refreshed_w2b_terminal_w2c_no_submit",
        "audit_ok": True,
        "updated_at": updated_at,
        "runtime_goal_active": runtime_goal_active,
        "w2b": w2b,
        "w2c": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
        "updated_artifacts": [
            "results/m6d_goal_mode_current_anchor.json",
            "results/m6d_goal_completion_audit.json",
            "results/m6d_goal_completion_audit.md",
            "results/m6d_goal_drift_audit.json",
            "results/m6d_goal_drift_audit.md",
            "results/m6d_followup_next_science_actions.json",
            "results/m6d_followup_next_science_actions.md",
            "results/m6d_goal_mode_local_harness_status.json",
            "results/m6d_goal_mode_local_harness_status.md",
        ],
        "obsolete_current_routes_removed": [
            "v9/v11 panel approval wait",
            "W2b test submission",
            "W2b recertification or row extension",
        ],
        "historical_detail_retained": True,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "next_action": next_action,
    }
    return {
        "anchor": refreshed_anchor,
        "completion": refreshed_completion,
        "drift": refreshed_drift,
        "actions": refreshed_actions,
        "harness": refreshed_harness,
        "report": report,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    target_msa = report.get("w2c_target_msa_approval") or {}
    return "\n".join([
        "# M6d Goal-State Refresh",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Runtime goal active: `{report['runtime_goal_active']}`.",
        f"W2b: `{report['w2b']['status']}`.",
        f"W2c: `{report['w2c']['status']}`.",
        f"W2c target-MSA packet: `{target_msa.get('status', 'not_ready')}`.",
        f"Cayuga submission allowed: `{report['cayuga_submission_allowed']}`.",
        "",
        "## Updated Artifacts",
        "",
        *[f"- `{path}`" for path in report["updated_artifacts"]],
        "",
        "## Next Action",
        "",
        report["next_action"],
        "",
    ])


def render_completion_markdown(report: Dict[str, Any]) -> str:
    target_msa = report.get("w2c_target_msa_approval") or {}
    return "\n".join([
        "# M6d Goal Completion Audit",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Can mark goal complete: `{report['can_mark_goal_complete']}`.",
        "",
        "## Current Boundary",
        "",
        f"- W2b: `{report['w2b_terminal_result']['status']}`",
        f"- W2c: `{report['w2c_successor']['status']}`",
        f"- W2c execution ready: `{report['w2c_successor']['execution_ready']}`",
        f"- W2c Cayuga submission allowed: `{report['w2c_successor']['cayuga_submission_allowed']}`",
        f"- W2c target-MSA packet: `{target_msa.get('status', 'not_ready')}`",
        f"- remaining requirement: `{', '.join(report['remaining_requirements'])}`",
        "",
        "Historical W2 v9/v11 panel fields retained in the JSON are superseded and are not current routes.",
        "",
        "## Next Action",
        "",
        report["next_action"],
        "",
    ])


def render_drift_markdown(report: Dict[str, Any]) -> str:
    assessment = report["drift_assessment"]
    lines = [
        "# M6d Goal Drift Audit",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Major direction drift: `{report['major_direction_drift']}`.",
        "",
        "## Assessment",
        "",
        f"- mission: `{assessment['mission']}`",
        f"- protocol: `{assessment['protocol']}`",
        f"- claims: `{assessment['claims']}`",
        f"- execution: `{assessment['execution']}`",
        f"- operational status: `{assessment['operational_status']}`",
        "",
        "## Active Risks",
        "",
    ]
    lines.extend(
        f"- `{risk['id']}` ({risk['status']}): {risk['control']}"
        for risk in report["active_risks"]
    )
    lines.extend(["", "## Next Action", "", report["next_action"], ""])
    return "\n".join(lines)


def render_actions_markdown(report: Dict[str, Any]) -> str:
    target_msa = report.get("w2c_target_msa_approval") or {}
    lines = [
        "# M6d Next Science Actions",
        "",
        f"Status: `{report['status']}`.",
        f"No submit: `{report['no_submit']}`.",
        f"Cayuga submission allowed: `{report['cayuga_submission_allowed']}`.",
        f"W2c target-MSA packet: `{target_msa.get('status', 'not_ready')}`.",
        "",
        "## Ranked Actions",
        "",
    ]
    lines.extend(
        f"{index}. {action}"
        for index, action in enumerate(report["next_actions_ranked"], 1)
    )
    lines.extend(["", "## Next Action", "", report["next_action"], ""])
    return "\n".join(lines)


def render_harness_markdown(report: Dict[str, Any]) -> str:
    verification = report["local_verification"]
    hpc = report["hpc_status"]
    return "\n".join([
        "# M6d Goal-Mode Local Harness Status",
        "",
        f"Updated: `{report['updated_at']}`.",
        f"Goal-mode status: `{report['goal_mode_status']}`.",
        f"Verification: `{verification['result']}`.",
        f"Command: `{verification['command']}`.",
        "",
        "## HPC Boundary",
        "",
        f"- active branch: `{hpc['active_branch']}`",
        f"- jobs running: `{hpc['jobs_running']}`",
        f"- W2b test compute: `{hpc['w2b_test_compute']}`",
        f"- W2c submission allowed: `{hpc['w2c_submission_allowed']}`",
        f"- W2c target-MSA packet: `{hpc.get('w2c_target_msa_packet_status', 'not_ready')}`",
        "",
        "## Next Action",
        "",
        hpc["next_action"],
        "",
    ])


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_json_or_default(path: str, artifact: str) -> Dict[str, Any]:
    if os.path.exists(path):
        return _load_json(path)
    return {"artifact": artifact}


def _write_json_atomic(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_text_atomic(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        handle.write(value)
    os.replace(temporary, path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", default="results/m6d_goal_mode_current_anchor.json")
    parser.add_argument("--completion", default="results/m6d_goal_completion_audit.json")
    parser.add_argument("--completion-md", default="results/m6d_goal_completion_audit.md")
    parser.add_argument("--drift", default="results/m6d_goal_drift_audit.json")
    parser.add_argument("--drift-md", default="results/m6d_goal_drift_audit.md")
    parser.add_argument("--actions", default="results/m6d_followup_next_science_actions.json")
    parser.add_argument("--actions-md", default="results/m6d_followup_next_science_actions.md")
    parser.add_argument("--harness", default="results/m6d_goal_mode_local_harness_status.json")
    parser.add_argument("--harness-md", default="results/m6d_goal_mode_local_harness_status.md")
    parser.add_argument(
        "--w2b-report",
        default="results/m6d_w2b_target_adaptive_certification_report.json",
    )
    parser.add_argument("--w2c-gate", default="results/m6d_w2c_design_gate.json")
    parser.add_argument(
        "--w2c-target-msa-packet",
        default="results/m6d_w2c_target_msa_approval_packet.json",
    )
    parser.add_argument("--updated-at", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--test-result", required=True)
    parser.add_argument("--runtime-goal-active", action="store_true")
    parser.add_argument("--out-json", default="results/m6d_goal_state_refresh_report.json")
    parser.add_argument("--out-md", default="results/m6d_goal_state_refresh_report.md")
    args = parser.parse_args(argv)

    paths = {
        "anchor": args.anchor,
        "completion": args.completion,
        "drift": args.drift,
        "actions": args.actions,
        "harness": args.harness,
    }
    artifact_defaults = {
        "anchor": "m6d_goal_mode_current_anchor",
        "completion": "m6d_goal_completion_audit",
        "drift": "m6d_goal_drift_audit",
        "actions": "m6d_followup_next_science_actions",
        "harness": "m6d_goal_mode_local_harness_status",
    }
    bundle = refresh_bundle(
        *[
            _load_json_or_default(paths[name], artifact_defaults[name])
            for name in ("anchor", "completion", "drift", "actions", "harness")
        ],
        _load_json(args.w2b_report),
        _load_json(args.w2c_gate),
        _load_json(args.w2c_target_msa_packet) if os.path.exists(args.w2c_target_msa_packet) else None,
        updated_at=args.updated_at,
        test_command=args.test_command,
        test_result=args.test_result,
        runtime_goal_active=args.runtime_goal_active,
    )
    for name, path in paths.items():
        _write_json_atomic(path, bundle[name])
    text_paths = {
        args.completion_md: render_completion_markdown(bundle["completion"]),
        args.drift_md: render_drift_markdown(bundle["drift"]),
        args.actions_md: render_actions_markdown(bundle["actions"]),
        args.harness_md: render_harness_markdown(bundle["harness"]),
    }
    for path, content in text_paths.items():
        _write_text_atomic(path, content)
    bundle["report"]["output_sha256"] = {
        path: _file_sha256(path) for path in [*paths.values(), *text_paths]
    }
    _write_json_atomic(args.out_json, bundle["report"])
    _write_text_atomic(args.out_md, render_markdown(bundle["report"]))
    print(
        f"status={bundle['report']['status']} runtime_goal_active="
        f"{bundle['report']['runtime_goal_active']} no_submit={bundle['report']['no_submit']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
