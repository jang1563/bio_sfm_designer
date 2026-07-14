"""Refresh current M6d goal artifacts from terminal W2b and prospective W2c evidence.

The older goal audits contain useful historical detail but predate W2b.  This
refresh layer preserves that detail, marks obsolete W2 execution branches as
historical, and replaces every current-status and next-action surface with one
consistent terminal-W2b / prospective-W2c state.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional


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
_FIT_PACKET_NEXT_ACTION = (
    "Prepare a hash-bound, no-submit W2c threshold-learning packet for exactly 60 fresh records per "
    "target under seed namespace w2c-fit-learn-v1. Require a separate explicit approval before any "
    "ProteinMPNN/Boltz record generation; target-MSA approval does not transfer to this stage."
)
_FIT_APPROVAL_NEXT_ACTION = (
    "Wait for explicit user approval naming W2c threshold-learning 480-record generation on H100. "
    "Packet-preparation approval, generic continuation, and target-MSA approval do not transfer; no "
    "independent-screen or certification compute is authorized."
)
_FIT_SUBMITTED_NEXT_ACTION = (
    "Wait for the 8 ProteinMPNN and 8 dependent H100 Boltz jobs in the validated W2c threshold-learning "
    "receipt, then sync exactly 480 candidates and records, run strict provenance QC, and execute only "
    "the learning-only evaluator. No retry, screen, or certification submission is authorized."
)
_FIT_TERMINAL_NEXT_ACTION = (
    "Close W2c without independent-screen or certification compute: all 480 threshold-learning records "
    "passed strict QC, but the frozen learning decisions retained fewer than three selective-pAE target "
    "candidates. Preserve this negative result and select the next W3 scientific experiment."
)
_W3_MECHANISM_NEXT_ACTION = (
    "Validate or provision the exact ColabFold 1.6.1 runtime and local AF2-Multimer v3 weights without "
    "prediction, write the hash-bound runtime receipt, and stop for a separate exact approval before "
    "executing the frozen 58-case W3 mechanism panel."
)
_FIT_SCREEN_PACKET_NEXT_ACTION = (
    "Prepare a separate hash-bound, no-submit independent-screen packet for only the frozen W2c target "
    "candidates. Require a new explicit approval before compute and do not retune any learned threshold."
)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
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


def _target_msa_completion_summary(completion: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(completion, dict):
        return None
    targets = completion.get("targets") if isinstance(completion.get("targets"), list) else []
    target_ids = [str(row.get("target_id") or "") for row in targets if isinstance(row, dict)]
    gpu_hours = completion.get("gpu_allocation_hours_total")
    gpu_hour_ceiling = completion.get("approved_gpu_hour_ceiling")
    budget_values_valid = (
        isinstance(gpu_hours, (int, float))
        and not isinstance(gpu_hours, bool)
        and isinstance(gpu_hour_ceiling, (int, float))
        and not isinstance(gpu_hour_ceiling, bool)
        and 0 <= gpu_hours <= gpu_hour_ceiling
    )
    required = {
        "status_complete": completion.get("status") == "target_msa_precompute_complete_8_of_8",
        "audit_ok": completion.get("audit_ok") is True,
        "target_count": completion.get("n_targets") == 8,
        "msa_count": completion.get("n_target_msas") == 8,
        "report_count": completion.get("n_target_msa_reports") == 8,
        "strict_manifest_ready": completion.get("strict_manifest_ready_targets") == 8,
        "target_rows_complete": len(target_ids) == 8 and len(set(target_ids)) == 8 and all(target_ids),
        "reports_ok": len(targets) == 8 and all(
            isinstance(row, dict) and row.get("report_ok") is True for row in targets
        ),
        "hash_locks_present": len(targets) == 8 and all(
            isinstance(row, dict)
            and _is_sha256(row.get("target_msa_sha256"))
            and _is_sha256(row.get("target_msa_report_sha256"))
            for row in targets
        ),
        "target_msa_only_boundary": completion.get("claim_boundary") == (
            "Target-MSA input preparation only. This is not W2c predictive evidence, a gate "
            "certificate, or authorization for ProteinMPNN/Boltz record generation."
        ),
        "within_approved_budget": (
            completion.get("within_approved_gpu_hour_ceiling") is True and budget_values_valid
        ),
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError(f"W2c target-MSA completion invariants failed: {', '.join(failed)}")
    return {
        "status": completion.get("status"),
        "audit_ok": True,
        "n_targets": 8,
        "n_target_msas": 8,
        "n_target_msa_reports": 8,
        "strict_manifest_ready_targets": 8,
        "target_ids": sorted(target_ids),
        "target_hash_locks": [
            {
                "target_id": row["target_id"],
                "target_msa_sha256": row["target_msa_sha256"],
                "target_msa_report_sha256": row["target_msa_report_sha256"],
            }
            for row in sorted(targets, key=lambda value: str(value.get("target_id") or ""))
        ],
        "submitted_jobs_total": completion.get("submitted_jobs_total"),
        "gpu_allocation_hours_total": gpu_hours,
        "approved_gpu_hour_ceiling": gpu_hour_ceiling,
        "within_approved_gpu_hour_ceiling": True,
        "records_generated": 0,
        "authorizes_record_generation": False,
        "checks": required,
    }


def _fit_learn_packet_summary(packet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(packet, dict):
        return None
    approval = packet.get("approval", {})
    preparation = packet.get("packet_preparation_approval", {})
    scope = packet.get("scope", {})
    checks = packet.get("checks", {})
    target_ids = scope.get("target_ids") if isinstance(scope.get("target_ids"), list) else []
    required = {
        "status_ready": (
            packet.get("status") == "ready_for_explicit_w2c_fit_learn_approval_not_submitted"
        ),
        "audit_ok": packet.get("audit_ok") is True,
        "packet_preparation_only": preparation.get("record_generation_approved") is False,
        "submission_not_performed": approval.get("submission_performed") is False,
        "explicit_approval_required": approval.get("explicit_user_approval_required") is True,
        "approval_phrase_exact": approval.get("required_user_phrase") == (
            "approve W2c threshold-learning 480-record generation on H100"
        ),
        "approval_token_exact": approval.get("environment_value") == (
            "approve-w2c-fit-learn-480-h100"
        ),
        "target_count": scope.get("n_targets") == 8,
        "target_rows_unique": len(target_ids) == 8 and len(set(target_ids)) == 8 and all(target_ids),
        "stage_exact": scope.get("stage") == "threshold_learning",
        "namespace_exact": scope.get("seed_namespace") == "w2c-fit-learn-v1",
        "records_per_target": scope.get("records_per_target") == 60,
        "total_records": scope.get("total_records") == 480,
        "job_count": (
            scope.get("proteinmpnn_jobs") == 8
            and scope.get("total_slurm_jobs") == 16
        ),
        "resource_exact": scope.get("scheduler_resource") == "preempt_gpu/low/gpu:h100:1",
        "record_generation_not_authorized": scope.get("authorizes_record_generation") is False,
        "independent_screen_not_authorized": scope.get("authorizes_independent_screen") is False,
        "certification_not_authorized": scope.get("authorizes_certification") is False,
        "local_input_lock_verified": checks.get("local_input_lock_verified") is True,
        "cayuga_input_lock_verified": checks.get("cayuga_input_lock_verified") is True,
        "local_dry_run_passed": checks.get("local_guard_dry_run_passed") is True,
        "cayuga_dry_run_passed": checks.get("cayuga_guard_dry_run_passed") is True,
        "local_no_approval_refused": checks.get("local_guard_no_approval_refused") is True,
        "cayuga_no_approval_refused": checks.get("cayuga_guard_no_approval_refused") is True,
        "bound_hashes_match": (
            checks.get("cayuga_bound_artifact_hash_matches") == 19
            and checks.get("cayuga_bound_artifact_hash_mismatches") == 0
        ),
        "initial_outputs_absent": (
            checks.get("local_initial_outputs_absent") == 16
            and checks.get("cayuga_initial_outputs_absent") == 16
        ),
        "slurm_zero": (
            checks.get("cayuga_slurm_jobs_before") == 0
            and checks.get("cayuga_slurm_jobs_after") == 0
        ),
        "receipts_absent": (
            checks.get("local_receipt_absent") is True
            and checks.get("cayuga_receipt_absent") is True
            and checks.get("local_summary_absent") is True
            and checks.get("cayuga_summary_absent") is True
        ),
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError(f"W2c fit-learn packet invariants failed: {', '.join(failed)}")
    return {
        "status": packet.get("status"),
        "audit_ok": True,
        "stage": "threshold_learning",
        "seed_namespace": "w2c-fit-learn-v1",
        "n_targets": 8,
        "target_ids": sorted(str(target_id) for target_id in target_ids),
        "records_per_target": 60,
        "total_records": 480,
        "total_slurm_jobs": 16,
        "scheduler_resource": scope.get("scheduler_resource"),
        "input_lock_digest_sha256": packet.get("input_lock_digest_sha256"),
        "submission_performed": False,
        "record_generation_approved": False,
        "explicit_user_approval_required": True,
        "required_user_phrase": approval.get("required_user_phrase"),
        "authorizes_independent_screen": False,
        "authorizes_certification": False,
        "checks": required,
    }


def _fit_learn_submission_summary(summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return None
    targets = summary.get("targets") if isinstance(summary.get("targets"), list) else []
    target_ids = [str(row.get("target_id") or "") for row in targets if isinstance(row, dict)]
    proteinmpnn_ids = [
        str(row.get("proteinmpnn_job_id") or "") for row in targets if isinstance(row, dict)
    ]
    boltz_ids = [str(row.get("boltz_job_id") or "") for row in targets if isinstance(row, dict)]
    all_job_ids = proteinmpnn_ids + boltz_ids
    required = {
        "artifact_exact": summary.get("artifact") == "m6d_w2c_fit_learn_submit_receipt_summary",
        "status_submitted": summary.get("status") == "submitted_on_cayuga",
        "workstream_exact": summary.get("workstream") == "m6d_w2c_fit_learn",
        "manifest_exact": summary.get("manifest") == "configs/m6d_w2c_fit_learn_targets.json",
        "target_count": summary.get("n_targets") == 8 and len(targets) == 8,
        "pair_count": summary.get("n_records") == 8,
        "event_count": summary.get("n_receipt_events") == 16,
        "target_ids_unique": len(target_ids) == 8 and len(set(target_ids)) == 8 and all(target_ids),
        "job_ids_complete": len(all_job_ids) == 16 and len(set(all_job_ids)) == 16 and all(all_job_ids),
        "job_ids_valid": all(not any(character.isspace() for character in value) for value in all_job_ids),
        "record_paths_isolated": all(
            isinstance(row, dict)
            and str(row.get("records") or "").startswith("hpc_outputs/m6d_w2c_fit_learn_records/")
            for row in targets
        ),
        "claim_boundary_preserved": summary.get("claim_boundary") == "job submission is not W2 evidence",
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError(f"W2c fit-learn submission invariants failed: {', '.join(failed)}")
    return {
        "status": summary.get("status"),
        "workstream": summary.get("workstream"),
        "n_targets": 8,
        "n_submission_pairs": 8,
        "n_receipt_events": 16,
        "target_ids": sorted(target_ids),
        "jobs": [
            {
                "target_id": row["target_id"],
                "proteinmpnn_job_id": str(row["proteinmpnn_job_id"]),
                "boltz_job_id": str(row["boltz_job_id"]),
                "records": row["records"],
            }
            for row in sorted(targets, key=lambda value: str(value.get("target_id") or ""))
        ],
        "approval_consumed": True,
        "additional_submission_allowed": False,
        "authorizes_independent_screen": False,
        "authorizes_certification": False,
        "checks": required,
    }


def _fit_learn_result_summary(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(report, dict):
        return None
    targets = report.get("targets") if isinstance(report.get("targets"), list) else []
    initial_ids = (
        report.get("initial_target_ids")
        if isinstance(report.get("initial_target_ids"), list)
        else []
    )
    candidate_ids = (
        report.get("threshold_candidate_targets")
        if isinstance(report.get("threshold_candidate_targets"), list)
        else []
    )
    target_ids = [str(row.get("target_id") or "") for row in targets if isinstance(row, dict)]
    qc = report.get("qc") if isinstance(report.get("qc"), dict) else {}
    status = report.get("status")
    terminal = status == "w2c_threshold_learning_terminal_not_supported"
    screen_packet = status == "w2c_threshold_learning_complete_awaiting_screen_packet"
    minimum_selective = report.get("minimum_selective_targets_required")
    candidate_count = report.get("n_threshold_candidate_targets")
    required = {
        "artifact_exact": report.get("artifact") == "m6d_w2c_threshold_learning_report",
        "status_supported": terminal or screen_packet,
        "audit_ok": report.get("audit_ok") is True,
        "locked_digest_valid": _is_sha256(report.get("locked_scientific_digest")),
        "threshold_exact": report.get("lrmsd_threshold") == 4.0,
        "initial_target_count": report.get("n_initial_targets") == 8,
        "initial_target_ids_unique": (
            len(initial_ids) == 8 and len(set(initial_ids)) == 8 and all(initial_ids)
        ),
        "target_rows_complete": (
            len(target_ids) == 8
            and len(set(target_ids)) == 8
            and all(target_ids)
            and sorted(target_ids) == sorted(str(value) for value in initial_ids)
        ),
        "target_decisions_frozen": (
            report.get("threshold_decisions_frozen") is True
            and len(targets) == 8
            and all(
                isinstance(row, dict)
                and row.get("decision_frozen") is True
                and isinstance(row.get("learning"), dict)
                and row["learning"].get("mode") in {"selective_pae", "refuse"}
                and row["learning"].get("candidate")
                == (row["learning"].get("mode") == "selective_pae")
                for row in targets
            )
        ),
        "candidate_count_consistent": (
            isinstance(candidate_count, int)
            and not isinstance(candidate_count, bool)
            and candidate_count == len(candidate_ids)
            and sorted(str(value) for value in candidate_ids) == sorted(
                row["target_id"]
                for row in targets
                if row.get("learning", {}).get("candidate") is True
            )
        ),
        "minimum_selective_exact": minimum_selective == 3,
        "terminal_logic_consistent": (
            terminal
            and report.get("terminal_after_threshold_learning") is True
            and report.get("candidate_floor_reachable") is False
            and isinstance(candidate_count, int)
            and candidate_count < 3
        ) or (
            screen_packet
            and report.get("terminal_after_threshold_learning") is False
            and report.get("candidate_floor_reachable") is True
            and isinstance(candidate_count, int)
            and candidate_count >= 3
        ),
        "qc_complete": (
            qc.get("ok") is True
            and qc.get("n_rows") == 480
            and qc.get("n_unique_record_keys") == 480
            and qc.get("n_failures") == 0
            and qc.get("require_chain_ids") is True
            and qc.get("require_complex_target_id") is True
            and qc.get("require_provenance") is True
        ),
        "predictor_provenance_exact": (
            qc.get("expect_predictor_id") == "boltz2_complex"
            and qc.get("expect_signal_source") == "boltz2_pae_interaction"
            and qc.get("expect_label_source") == "boltz2_lrmsd_to_reference"
        ),
        "positive_claims_blocked": (
            report.get("can_claim_w2c_selective_target_adaptive_viability") is False
            and report.get("can_claim_universal_w2_generalization") is False
        ),
        "later_compute_blocked": (
            report.get("independent_screen_generation_approved") is False
            and report.get("certification_generation_approved") is False
        ),
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError(f"W2c threshold-learning result invariants failed: {', '.join(failed)}")
    return {
        "status": status,
        "audit_ok": True,
        "locked_scientific_digest": report.get("locked_scientific_digest"),
        "n_initial_targets": 8,
        "initial_target_ids": sorted(str(value) for value in initial_ids),
        "n_records": 480,
        "n_threshold_candidate_targets": candidate_count,
        "threshold_candidate_targets": sorted(str(value) for value in candidate_ids),
        "minimum_selective_targets_required": 3,
        "candidate_floor_reachable": report.get("candidate_floor_reachable"),
        "terminal_after_threshold_learning": report.get("terminal_after_threshold_learning"),
        "threshold_decisions_frozen": True,
        "independent_screen_generation_approved": False,
        "certification_generation_approved": False,
        "can_claim_w2c_selective_target_adaptive_viability": False,
        "can_claim_universal_w2_generalization": False,
        "targets": targets,
        "qc": qc,
        "claim_boundary": report.get("claim_boundary"),
        "next_action": report.get("next_action"),
        "checks": required,
    }


def _w3_mechanism_summary(packet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(packet, dict):
        return None
    rows = packet.get("rows") if isinstance(packet.get("rows"), list) else []
    execution = (
        packet.get("execution_packet")
        if isinstance(packet.get("execution_packet"), dict)
        else {}
    )
    selection = (
        packet.get("selection_lock")
        if isinstance(packet.get("selection_lock"), dict)
        else {}
    )
    blocks: Dict[str, int] = {}
    raw_sequence_fields = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        block = str(row.get("panel_block") or "")
        blocks[block] = blocks.get(block, 0) + 1
        raw_sequence_fields += int("target_sequence" in row or "binder_sequence" in row)
    checks = {
        "artifact_exact": packet.get("artifact") == "m6d_w3_decisive_mechanism_panel_protocol",
        "status_exact": packet.get("status")
        == "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit",
        "audit_ok": packet.get("audit_ok") is True and packet.get("failures") == [],
        "case_count_exact": len(rows) == 58 and selection.get("n_total_cases") == 58,
        "block_counts_exact": blocks
        == {"boltz_chai_3pc8_challenge": 18, "w2c_pae_order_statistics": 40},
        "selection_outcome_blind": selection.get("selection_uses_outcome_labels") is False,
        "input_hash_lock": (
            execution.get("n_inputs") == 58
            and execution.get("inputs_emitted") is True
            and _is_sha256(execution.get("private_manifest_sha256"))
        ),
        "no_submit_boundary": (
            execution.get("no_submit") is True
            and execution.get("no_gpu_compute") is True
            and execution.get("no_api_spend") is True
            and execution.get("no_network_fetch") is True
        ),
        "approval_unrecorded": (
            execution.get("approval_recorded") is False
            and execution.get("approval_consumed") is False
        ),
        "runtime_and_execution_blocked": (
            execution.get("runtime_ready") is False
            and execution.get("execution_ready") is False
        ),
        "public_rows_redacted": raw_sequence_fields == 0,
        "claims_blocked": (
            packet.get("can_claim_independent_predictor_robustness_now") is False
            and packet.get("can_claim_w2c_rescue_now") is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3 mechanism-panel invariants failed: {', '.join(failed)}")
    return {
        "status": packet.get("status"),
        "audit_ok": True,
        "n_cases": 58,
        "blocks": blocks,
        "predictor_or_protocol_id": (
            packet.get("predictor_protocol", {}).get("predictor_or_protocol_id")
        ),
        "runtime_ready": False,
        "execution_ready": False,
        "approval_recorded": False,
        "approval_consumed": False,
        "no_submit": True,
        "can_claim_independent_predictor_robustness_now": False,
        "claim_boundary": packet.get("claim_boundary"),
        "checks": checks,
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
    w2c_target_msa_completion: Optional[Dict[str, Any]] = None,
    w2c_fit_learn_packet: Optional[Dict[str, Any]] = None,
    w2c_fit_learn_submission: Optional[Dict[str, Any]] = None,
    w2c_threshold_learning_report: Optional[Dict[str, Any]] = None,
    w3_mechanism_packet: Optional[Dict[str, Any]] = None,
    *,
    updated_at: str,
    test_command: str,
    test_result: str,
    runtime_goal_active: bool = False,
) -> Dict[str, Dict[str, Any]]:
    w2b = _terminal_summary(w2b_report)
    w2c = _w2c_summary(w2c_gate)
    w2c_target_msa = _target_msa_packet_summary(w2c_target_msa_packet)
    w2c_target_msa_complete = _target_msa_completion_summary(w2c_target_msa_completion)
    w2c_fit_learn = _fit_learn_packet_summary(w2c_fit_learn_packet)
    w2c_fit_submitted = _fit_learn_submission_summary(w2c_fit_learn_submission)
    w2c_fit_result = _fit_learn_result_summary(w2c_threshold_learning_report)
    w3_mechanism = _w3_mechanism_summary(w3_mechanism_packet)
    if w2c_fit_learn is not None and w2c_target_msa_complete is None:
        raise ValueError("W2c fit-learn packet requires completed target-MSA evidence")
    if w2c_fit_submitted is not None and w2c_fit_learn is None:
        raise ValueError("W2c fit-learn submission requires the validated no-submit packet")
    if w2c_fit_result is not None and w2c_fit_submitted is None:
        raise ValueError("W2c threshold-learning result requires the validated submission receipt")
    if w3_mechanism is not None and not (
        w2c_fit_result and w2c_fit_result["terminal_after_threshold_learning"]
    ):
        raise ValueError("W3 mechanism packet requires the terminal W2c threshold-learning result")
    if w2c_target_msa_complete is not None:
        expected_ids = sorted(w2c.get("target_manifest_ids", []))
        if w2c_target_msa_complete["target_ids"] != expected_ids:
            raise ValueError("W2c target-MSA completion targets do not match the locked W2c manifest")
        if w2c_fit_learn is not None and w2c_fit_learn["target_ids"] != expected_ids:
            raise ValueError("W2c fit-learn packet targets do not match the locked W2c manifest")
        if w2c_fit_submitted is not None and w2c_fit_submitted["target_ids"] != expected_ids:
            raise ValueError("W2c fit-learn submission targets do not match the locked W2c manifest")
        if w2c_fit_result is not None and w2c_fit_result["initial_target_ids"] != expected_ids:
            raise ValueError("W2c threshold-learning targets do not match the locked W2c manifest")
        if (
            w2c_fit_result is not None
            and w2c_fit_result["locked_scientific_digest"] != w2c["locked_scientific_digest"]
        ):
            raise ValueError("W2c threshold-learning digest does not match the locked W2c protocol")
        w2c["target_msa_ready"] = True
        w2c["target_msa_completion_status"] = w2c_target_msa_complete["status"]
        if w2c_target_msa is not None:
            w2c_target_msa["historical_after_completion"] = True
            w2c_target_msa["superseded_by"] = w2c_target_msa_complete["status"]
        if w2c_fit_learn is not None:
            if w2c_fit_result is not None:
                if w2c_fit_result["terminal_after_threshold_learning"]:
                    next_action = _FIT_TERMINAL_NEXT_ACTION
                    remaining_requirement = "W3_next_experiment_selection"
                    resume_steps = [
                        "read docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md and preserve the frozen decisions",
                        "preserve the 480/480 strict-QC result and all eight target refusals",
                        "do not generate W2c independent-screen or certification records",
                        "do not relax the minimum AUROC, minimum acceptance, or false-acceptance cap post hoc",
                        "select the next W3 experiment around independent-predictor robustness or failure analysis",
                    ]
                    ranked_actions = [
                        "Close W2c as terminal under its pre-locked threshold-learning rule.",
                        "Preserve the all-target refusal and target-level diagnostics as negative evidence.",
                        "Select and pre-register the next W3 scientific experiment before new compute.",
                        "Keep W2c independent-screen and certification generation permanently unsubmitted.",
                    ]
                else:
                    next_action = _FIT_SCREEN_PACKET_NEXT_ACTION
                    remaining_requirement = "W2c_independent_screen_packet_and_explicit_approval"
                    resume_steps = [
                        "read the frozen threshold-learning report without changing target decisions",
                        "prepare a separate no-submit screen manifest for only the retained target candidates",
                        "bind a new namespace and exact hashes before requesting approval",
                        "do not generate certification records from screen-stage approval",
                        "move to W3 if fewer than three targets pass the independent screen",
                    ]
                    ranked_actions = [
                        "Prepare a hash-bound, no-submit independent-screen packet.",
                        "Obtain separate explicit approval before any screen-stage generation.",
                        "Evaluate the frozen thresholds without retuning.",
                        "Move to W3 if the independent screen cannot retain three selective targets.",
                    ]
            elif w2c_fit_submitted is not None:
                next_action = _FIT_SUBMITTED_NEXT_ACTION
                remaining_requirement = "W2c_threshold_learning_completion_and_QC"
                resume_steps = [
                    "read the local W2c fit-learn receipt and validated submission summary",
                    "query only the 16 receipt-bound Slurm job IDs and do not resubmit the initial bridge",
                    "after 16/16 completion, sync exactly 60 candidates and records per target",
                    "run strict provenance QC and the W2c learning-only evaluator",
                    "freeze or refuse each target threshold without using future-stage labels",
                    "require a new packet and explicit approval before any independent-screen compute",
                    "move to W3 if the frozen learning decisions make the selective target floor unreachable",
                ]
                ranked_actions = [
                    "Monitor the 16 receipt-bound threshold-learning jobs without resubmission.",
                    "Sync and validate exactly 480 candidates plus 480 Boltz records after completion.",
                    "Run strict QC and freeze or refuse target thresholds with the learning-only evaluator.",
                    "Prepare an independent-screen packet only if the frozen candidate floor remains reachable.",
                    "Move to W3 if W2c becomes terminal under its locked prospective rules.",
                ]
            else:
                next_action = _FIT_APPROVAL_NEXT_ACTION
                remaining_requirement = "W2c_threshold_learning_explicit_approval"
                resume_steps = [
                    "read docs/M6D_W2B_CERTIFICATION_COMPLETION.md and preserve W2b as terminal",
                    "read docs/M6D_W2C_FIT_LEARN_APPROVAL.md and the hash-bound approval packet",
                    "preserve the 8/8 target-MSA lock and w2c-fit-learn-v1 8x60 scope",
                    "do not infer generation approval from packet preparation, continue, or goal-mode resume",
                    "if explicitly approved, submit only the 8 ProteinMPNN plus 8 dependent Boltz H100 jobs",
                    "do not generate independent-screen or certification rows from learning-stage approval",
                    "move to W3 if W2c cannot pass its locked prospective gates",
                ]
                ranked_actions = [
                    "Wait for explicit approval naming W2c threshold-learning 480-record generation on H100.",
                    "After approval, preserve the guarded receipt and generate exactly 60 learning rows per target.",
                    "Freeze target-wise selective-pAE thresholds from learning rows only.",
                    "Generate independent-screen rows only after the learning artifact is locked and reviewed.",
                    "Move to W3 if the prospective W2c protocol cannot qualify without changing locked rules.",
                ]
        else:
            next_action = _FIT_PACKET_NEXT_ACTION
            remaining_requirement = "W2c_threshold_learning_packet_gate"
            resume_steps = [
                "read docs/M6D_W2B_CERTIFICATION_COMPLETION.md and preserve W2b as terminal",
                "read results/m6d_w2c_target_msa_completion.json and preserve the 8/8 MSA hash lock",
                "prepare a no-submit threshold-learning packet for exactly 60 fresh rows per target",
                "bind the w2c-fit-learn-v1 namespace, manifest, MSA, evaluator, and wrapper hashes",
                "require a separate explicit approval; target-MSA approval does not authorize record generation",
                "do not generate independent-screen or certification rows from the learning-stage approval",
                "move to W3 if W2c cannot pass its locked prospective gates",
            ]
            ranked_actions = [
                "Prepare and dry-run the hash-bound W2c threshold-learning packet with zero submissions.",
                "Obtain separate explicit approval for exactly 480 learning-stage records before compute.",
                "Freeze target-wise selective-pAE thresholds from learning rows only.",
                "Generate independent-screen rows only after the learning artifact is locked and reviewed.",
                "Move to W3 if the prospective W2c protocol cannot qualify without changing locked rules.",
            ]
    elif w2c_target_msa is not None:
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
    if w3_mechanism is not None:
        next_action = _W3_MECHANISM_NEXT_ACTION
        remaining_requirement = "W3_colabfold_runtime_receipt_then_separate_compute_approval"
        resume_steps = [
            "read docs/M6D_W3_MECHANISM_PANEL.md and configs/m6d_w3_mechanism_panel_protocol.json",
            "preserve the frozen 18-case 3PC8 block and 40-case W2c fixed-rank block",
            "run only the no-prediction ColabFold 1.6.1 runtime and local-weight validation",
            "keep the guarded W3 wrapper in dry-run mode until a separate exact approval is given",
            "after approved compute, convert all 58 outputs and run the preregistered adjudicator without retuning",
        ]
        ranked_actions = [
            "Validate or provision ColabFold 1.6.1 and local AF2-Multimer v3 weights without prediction.",
            "Write and verify the hash-bound W3 runtime receipt.",
            "Stop for separate explicit approval before any H100/GPU/HPC execution.",
            "After approval, execute exactly the frozen 58-case panel and no adaptive additions.",
            "Convert and adjudicate all outputs under the preregistered thresholds.",
        ]
    date = updated_at.split("T", 1)[0]
    post_msa = w2c_target_msa_complete is not None
    fit_packet_ready = w2c_fit_learn is not None
    fit_submission_active = w2c_fit_submitted is not None
    fit_result_ready = w2c_fit_result is not None
    fit_terminal = bool(
        w2c_fit_result and w2c_fit_result["terminal_after_threshold_learning"]
    )
    if w3_mechanism is not None:
        goal_status = "goal_active_w3_mechanism_runtime_gate"
        current_status = "m6_complex_in_progress_w3_mechanism_preregistered_runtime_blocked_no_submit"
        goal_progress = "w3_mechanism_inputs_ready_awaiting_runtime_receipt_then_separate_approval"
    elif fit_result_ready:
        if fit_terminal:
            goal_status = "goal_active_w2b_terminal_w2c_threshold_learning_terminal"
            current_status = (
                "m6_complex_in_progress_w2b_terminal_w2c_threshold_learning_terminal_not_supported"
            )
            goal_progress = "w2c_threshold_learning_complete_terminal_move_to_w3"
        else:
            goal_status = "goal_active_w2b_terminal_w2c_screen_packet_gate"
            current_status = (
                "m6_complex_in_progress_w2b_terminal_w2c_thresholds_frozen_screen_not_approved"
            )
            goal_progress = "w2c_thresholds_frozen_awaiting_screen_packet"
    elif fit_submission_active:
        goal_status = "goal_active_w2b_terminal_w2c_fit_learn_jobs_in_flight"
        current_status = (
            "m6_complex_in_progress_w2b_terminal_w2c_fit_learn_submitted_awaiting_completion"
        )
        goal_progress = "w2c_fit_learn_receipt_validated_jobs_in_flight"
    elif fit_packet_ready:
        goal_status = "goal_active_w2b_terminal_w2c_fit_learn_approval_wait"
        current_status = (
            "m6_complex_in_progress_w2b_terminal_w2c_fit_learn_packet_ready_generation_not_approved"
        )
        goal_progress = "w2c_fit_learn_packet_ready_awaiting_explicit_generation_approval"
    elif post_msa:
        goal_status = "goal_active_w2b_terminal_w2c_threshold_learning_packet"
        current_status = "m6_complex_in_progress_w2b_terminal_w2c_msa_complete_record_generation_blocked"
        goal_progress = "local_w2c_threshold_learning_packet_work_required"
    else:
        goal_status = _GOAL_STATUS
        current_status = "m6_complex_in_progress_w2b_terminal_w2c_design_no_submit"
        goal_progress = "local_w2c_precompute_work_required"
    w2c_claim_boundary = (
        "threshold learning terminally retained zero eligible targets; no W2c viability claim or later-stage compute"
        if fit_terminal else (
            "thresholds frozen from learning records only; no independent-screen result, certificate, or claim"
            if fit_result_ready else (
                "threshold-learning jobs submitted under consumed approval; no evaluated records, certificate, or claim"
                if fit_submission_active else (
            "power-qualified design with hash-bound fit packet ready; no model records, certificate, or claim"
            if fit_packet_ready else (
            "power-qualified design with target inputs ready; no model records, certificate, or claim"
            if post_msa else "power-qualified design only; no targets, compute, certificate, or claim"
            )
                )
            )
        )
    )

    refreshed_anchor = copy.deepcopy(anchor)
    refreshed_anchor["date"] = date
    refreshed_anchor["goal_mode"] = (
        "active" if runtime_goal_active else "contract_ready_runtime_goal_inactive"
    )
    refreshed_anchor["objective"] = (
        "Execute the preregistered 58-case W3 AF2-Multimer mechanism panel only after an exact runtime "
        "receipt and separate compute approval; preserve terminal W2b/W2c and all W1-W4 claim boundaries."
        if w3_mechanism is not None else
        "Advance M6d from terminal W2b and W2c results into decisive W3 science: preserve W1-W4 claim "
        "boundaries, select and preregister one independent-predictor robustness or failure-mechanism "
        "experiment, and block new compute until a separate explicit approval."
        if fit_terminal else (
            "Advance M6d from terminal W2b v1 to a one-shot W2c selective-pAE successor: preserve W1-W4 "
            "claim boundaries, block compute until the fresh-target/evaluator/approval gates pass, and move "
            "to W3 rather than iterating W2 if W2c cannot qualify prospectively."
        )
    )
    refreshed_anchor.setdefault("claim_boundaries", {}).update({
        "w2_multi_target_generalization": "not_supported",
        "w2b_target_adaptive_viability": "terminal_not_supported",
        "w2c_selective_target_adaptive_viability": (
            "terminal_not_supported" if fit_terminal else (
                "not_tested_thresholds_frozen_screen_not_run" if fit_result_ready else (
                    "not_tested_fit_jobs_in_flight" if fit_submission_active else (
                "not_tested_fit_packet_ready" if fit_packet_ready else (
                "not_tested_inputs_ready" if post_msa else "not_tested_design_only"
                )
                    )
                )
            )
        ),
        "w3_independent_predictor_robustness": (
            "not_tested_mechanism_panel_preregistered_runtime_blocked"
            if w3_mechanism is not None
            else "not_supported_predictor_disagreement"
        ),
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
        "w2c_target_msa_completion": "results/m6d_w2c_target_msa_completion.json",
        "w2c_fit_learn_stage_manifest": "configs/m6d_w2c_fit_learn_targets.json",
        "w2c_fit_learn_input_lock": "configs/m6d_w2c_fit_learn_input_lock.json",
        "w2c_fit_learn_approval_packet": "results/m6d_w2c_fit_learn_approval_packet.json",
        "w2c_fit_learn_approval_doc": "docs/M6D_W2C_FIT_LEARN_APPROVAL.md",
        "w2c_fit_learn_submit_receipt": "results/m6d_w2c_fit_learn_submit_receipt.jsonl",
        "w2c_fit_learn_submit_summary": "results/m6d_w2c_fit_learn_submit_receipt_summary.json",
        "w2c_threshold_learning_report": "results/m6d_w2c_threshold_learning_report.json",
        "w2c_threshold_learning_completion": "docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md",
        "w3_mechanism_protocol": "configs/m6d_w3_mechanism_panel_protocol.json",
        "w3_mechanism_doc": "docs/M6D_W3_MECHANISM_PANEL.md",
        "w3_mechanism_guard": "hpc/run_w3_mechanism_panel_guarded.sh",
        "w3_runtime_validator": "hpc/validate_w3_mechanism_runtime.sh",
        "goal_state_refresh": "results/m6d_goal_state_refresh_report.json",
    })
    refreshed_anchor["current_status"] = {
        "status": current_status,
        "goal_progress": goal_progress,
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
        "w2c_target_msa_completion_status": (
            w2c_target_msa_complete["status"] if w2c_target_msa_complete else None
        ),
        "w2c_fit_learn_packet_status": w2c_fit_learn["status"] if w2c_fit_learn else None,
        "w2c_fit_learn_submission_status": (
            w2c_fit_submitted["status"] if w2c_fit_submitted else None
        ),
        "w2c_fit_learn_submission_performed": fit_submission_active,
        "w2c_fit_learn_approval_consumed": fit_submission_active,
        "w2c_additional_submission_allowed": False,
        "w2c_record_generation_approved": False,
        "w2c_threshold_learning_status": w2c_fit_result["status"] if w2c_fit_result else None,
        "w2c_threshold_candidate_targets": (
            w2c_fit_result["n_threshold_candidate_targets"] if w2c_fit_result else None
        ),
        "w2c_independent_screen_generation_approved": False,
        "w2c_certification_generation_approved": False,
        "w3": (
            "mechanism_panel_preregistered_runtime_blocked_no_submit"
            if w3_mechanism is not None
            else "negative_robustness_result_adjudicated"
        ),
        "w3_mechanism_case_count": w3_mechanism["n_cases"] if w3_mechanism else None,
        "w3_runtime_ready": w3_mechanism["runtime_ready"] if w3_mechanism else False,
        "w3_execution_ready": w3_mechanism["execution_ready"] if w3_mechanism else False,
        "w3_compute_approval_recorded": (
            w3_mechanism["approval_recorded"] if w3_mechanism else False
        ),
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
    refreshed_anchor["w2c_target_msa_completion"] = w2c_target_msa_complete
    refreshed_anchor["w2c_fit_learn_approval"] = w2c_fit_learn
    refreshed_anchor["w2c_fit_learn_submission"] = w2c_fit_submitted
    refreshed_anchor["w2c_threshold_learning_result"] = w2c_fit_result
    refreshed_anchor["w3_mechanism_panel"] = w3_mechanism
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
        "w2c_target_msa_completion_status": (
            w2c_target_msa_complete["status"] if w2c_target_msa_complete else None
        ),
        "w2c_fit_learn_packet_status": w2c_fit_learn["status"] if w2c_fit_learn else None,
        "w2c_fit_learn_submission_status": (
            w2c_fit_submitted["status"] if w2c_fit_submitted else None
        ),
        "w2c_fit_learn_submission_performed": fit_submission_active,
        "w2c_fit_learn_approval_consumed": fit_submission_active,
        "w2c_additional_submission_allowed": False,
        "w2c_record_generation_approved": False,
        "w2c_threshold_learning_status": w2c_fit_result["status"] if w2c_fit_result else None,
        "w2c_threshold_candidate_targets": (
            w2c_fit_result["n_threshold_candidate_targets"] if w2c_fit_result else None
        ),
        "w2c_independent_screen_generation_approved": False,
        "w2c_certification_generation_approved": False,
        "w3_mechanism_panel_status": w3_mechanism["status"] if w3_mechanism else None,
        "w3_mechanism_case_count": w3_mechanism["n_cases"] if w3_mechanism else None,
        "w3_runtime_ready": w3_mechanism["runtime_ready"] if w3_mechanism else False,
        "w3_execution_ready": w3_mechanism["execution_ready"] if w3_mechanism else False,
        "w3_compute_approval_recorded": (
            w3_mechanism["approval_recorded"] if w3_mechanism else False
        ),
        "remaining_requirement": remaining_requirement,
    }

    refreshed_completion = copy.deepcopy(completion)
    refreshed_completion.update({
        "status": goal_status,
        "audit_ok": True,
        "complete": False,
        "can_mark_goal_complete": False,
        "failures": [],
        "remaining_requirements": [remaining_requirement],
        "next_action": next_action,
        "w2b_terminal_result": w2b,
        "w2c_successor": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
        "w2c_target_msa_completion": w2c_target_msa_complete,
        "w2c_fit_learn_approval": w2c_fit_learn,
        "w2c_fit_learn_submission": w2c_fit_submitted,
        "w2c_threshold_learning_result": w2c_fit_result,
        "w3_mechanism_panel": w3_mechanism,
    })
    refreshed_completion["claim_boundary"] = {
        "w1": "target-specific certified evidence preserved",
        "w2": "universal multi-target generalization not supported",
        "w2b": "terminally not supported; no test compute and no extension",
        "w2c": w2c_claim_boundary,
        "w3": (
            "58-case mechanism panel preregistered; runtime and compute approval absent; no positive claim"
            if w3_mechanism is not None
            else "negative no-MSA Chai robustness result preserved; no positive independent-predictor claim"
        ),
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
        "status": (
            "no_major_direction_drift_w3_mechanism_preregistered_runtime_gate"
            if w3_mechanism is not None else
            "no_major_direction_drift_w2b_terminal_w2c_threshold_learning_terminal"
            if fit_terminal else (
                "no_major_direction_drift_w2b_terminal_w2c_thresholds_frozen_screen_gate"
                if fit_result_ready else (
                    "no_major_direction_drift_w2b_terminal_w2c_fit_jobs_in_flight"
                    if fit_submission_active else (
                "no_major_direction_drift_w2b_terminal_w2c_fit_packet_ready_approval_wait"
                if fit_packet_ready else (
                "no_major_direction_drift_w2b_terminal_w2c_msa_complete_fit_packet"
                if post_msa else "no_major_direction_drift_w2b_terminal_w2c_precompute"
                )
                    )
                )
            )
        ),
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
        "w2c": (
            "threshold_learning_terminal_no_viability_claim" if fit_terminal else (
                "thresholds_frozen_screen_not_run_no_claim" if fit_result_ready else (
                    "fit_jobs_in_flight_no_evaluated_records_no_claim" if fit_submission_active else (
                "fit_packet_ready_no_records_no_claim" if fit_packet_ready else (
                "inputs_ready_no_records_no_claim" if post_msa else "design_only_no_submit_no_claim"
                )
                    )
                )
            )
        ),
        "w3": (
            "mechanism_panel_preregistered_no_compute_no_positive_claim"
            if w3_mechanism is not None
            else "negative_robustness_adjudicated_no_positive_claim"
        ),
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
            "control": (
                "W3 is frozen to one 58-case panel; next work is runtime validation then a separate approval"
                if w3_mechanism is not None else
                "W2c is closed under its frozen learning rule; next work must be a distinct W3 experiment"
                if fit_terminal else (
                    "next boundary is a new no-submit screen packet; learned thresholds cannot be retuned"
                    if fit_result_ready else (
                        "next work is receipt-bound completion, QC, and learning-only evaluation; no resubmission is allowed"
                        if fit_submission_active else (
                    "next boundary is explicit approval for the fixed fit packet; no further W2b validation is allowed"
                    if fit_packet_ready else (
                    "next work is a bounded threshold-learning packet; no further W2b validation is allowed"
                    if post_msa else
                    "next work is evaluator plus fresh-target qualification; no further W2b validation is allowed"
                    )
                        )
                    )
                )
            ),
        },
    ]
    refreshed_drift["drift_assessment"] = {
        "mission": "no_drift_external_calibrated_trust_gate_north_star_preserved",
        "protocol": (
            "no_drift_terminal_w2_locks_preserved_w3_mechanism_panel_preregistered"
            if w3_mechanism is not None
            else "no_drift_w2b_lock_preserved_w2c_declared_as_new_experiment"
        ),
        "claims": "no_drift_negative_boundaries_preserved",
        "execution": (
            "w3_inputs_ready_runtime_blocked_compute_not_approved_no_submit"
            if w3_mechanism is not None else
            "w2b_closed_w2c_threshold_learning_terminal_no_later_stage_submit"
            if fit_terminal else (
                "w2b_closed_w2c_thresholds_frozen_screen_generation_not_approved"
                if fit_result_ready else (
                    "w2b_closed_w2c_fit_generation_submitted_receipt_bound_no_additional_submit"
                    if fit_submission_active else (
                "w2b_closed_w2c_fit_packet_ready_record_generation_not_approved"
                if fit_packet_ready else (
                "w2b_closed_w2c_target_msa_complete_record_generation_no_submit"
                if post_msa else "w2b_closed_without_nondecisive_test_compute_w2c_no_submit"
                )
                    )
                )
            )
        ),
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
    current_state["W2c_target_msa_completion"] = w2c_target_msa_complete
    current_state["W2c_fit_learn_approval"] = w2c_fit_learn
    current_state["W2c_fit_learn_submission"] = w2c_fit_submitted
    current_state["W2c_threshold_learning_result"] = w2c_fit_result
    current_state["W3_mechanism_panel"] = w3_mechanism
    current_state.setdefault("completion_audit", {}).update({
        "status": goal_status,
        "can_mark_goal_complete": False,
        "historical_panel_fields_retained": True,
    })
    for key, value in current_state.items():
        if key.startswith("W2_") and key not in {"W2_multi_target_panel"}:
            _mark_historical(value, _W2B_TERMINAL_STATUS)

    refreshed_actions = {
        "artifact": "m6d_followup_next_science_actions",
        "date": date,
        "status": (
            "w3_mechanism_panel_preregistered_runtime_gate_no_submit"
            if w3_mechanism is not None else
            "w2b_terminal_w2c_threshold_learning_terminal_move_to_w3"
            if fit_terminal else (
                "w2b_terminal_w2c_thresholds_frozen_screen_packet_no_submit"
                if fit_result_ready else (
                    "w2b_terminal_w2c_fit_jobs_in_flight_awaiting_completion"
                    if fit_submission_active else (
                "w2b_terminal_w2c_fit_packet_ready_awaiting_explicit_approval"
                if fit_packet_ready else (
                "w2b_terminal_w2c_msa_complete_threshold_learning_packet_no_submit"
                if post_msa else "w2b_terminal_w2c_design_gate_no_submit"
                )
                    )
                )
            )
        ),
        "target_alpha": 0.2,
        "claim_boundary": {
            "w1_target_specific": "supported",
            "w2_multi_target_generalization": "not_supported",
            "w2b_target_adaptive_viability": "terminal_not_supported",
            "w2c_selective_target_adaptive_viability": (
                "terminal_not_supported" if fit_terminal else (
                    "not_tested_thresholds_frozen_screen_not_run" if fit_result_ready else (
                        "not_tested_fit_jobs_in_flight" if fit_submission_active else (
                    "not_tested_fit_packet_ready" if fit_packet_ready else (
                    "not_tested_inputs_ready" if post_msa else "not_tested_design_only"
                    )
                        )
                    )
                )
            ),
            "w3_independent_predictor_robustness": (
                "not_tested_mechanism_panel_preregistered_runtime_blocked"
                if w3_mechanism is not None
                else "not_supported_predictor_disagreement"
            ),
            "w4_closed_loop": "fail_closed_plumbing_only",
        },
        "w2b_terminal_result": w2b,
        "w2c_successor": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
        "w2c_target_msa_completion": w2c_target_msa_complete,
        "w2c_fit_learn_approval": w2c_fit_learn,
        "w2c_fit_learn_submission": w2c_fit_submitted,
        "w2c_threshold_learning_result": w2c_fit_result,
        "w3_mechanism_panel": w3_mechanism,
        "next_actions_ranked": ranked_actions,
        "next_action": next_action,
        "submission_performed": False if w3_mechanism is not None else fit_submission_active,
        "historical_w2c_submission_performed": fit_submission_active,
        "no_submit": True if w3_mechanism is not None else not fit_submission_active,
        "cayuga_submission_allowed": False,
    }

    refreshed_harness = {
        "artifact": "m6d_goal_mode_local_harness_status",
        "updated_at": updated_at,
        "goal_mode_status": (
            (
                "active_w3_mechanism_runtime_gate"
                if w3_mechanism is not None else
                "active_w2c_threshold_learning_terminal_move_to_w3"
                if fit_terminal else (
                    "active_w2c_thresholds_frozen_screen_packet_gate"
                    if fit_result_ready else (
                        "active_w2c_fit_learn_jobs_in_flight"
                        if fit_submission_active else (
                    "active_w2c_fit_learn_approval_wait"
                    if fit_packet_ready else (
                    "active_w2c_threshold_learning_packet"
                    if post_msa else "active_w2c_precompute"
                    )
                        )
                    )
                )
            ) if runtime_goal_active else "contract_ready_runtime_goal_inactive"
        ),
        "science_focus": (
            "W3 58-case mechanism-panel runtime qualification and separate compute approval gate"
            if w3_mechanism is not None else
            "W2c threshold-learning terminal result preservation plus W3 experiment selection"
            if fit_terminal else (
                "W2c frozen-threshold preservation plus guarded independent-screen packet"
                if fit_result_ready else (
                    "W2b terminal preservation plus receipt-bound W2c threshold-learning completion"
                    if fit_submission_active else (
                "W2b terminal preservation plus guarded W2c fit-learn approval boundary"
                if fit_packet_ready else (
                "W2b terminal preservation plus W2c threshold-learning packet qualification"
                if post_msa else
                "W2b terminal preservation plus W2c selective one-shot precompute qualification"
                )
                    )
                )
            )
        ),
        "local_verification": {
            "command": test_command,
            "result": test_result,
            "w2b_terminal_regression": "preserved",
            "w2c_design_gate": w2c["status"],
            "w3_mechanism_panel": w3_mechanism["status"] if w3_mechanism else None,
        },
        "hpc_status": {
            "active_branch": (
                "none" if fit_result_ready else "w2c_fit_learn" if fit_submission_active else "none"
            ),
            "jobs_submitted": 16 if fit_submission_active else 0,
            "jobs_completed": 16 if fit_result_ready else None,
            "jobs_running": 0 if fit_result_ready else None if fit_submission_active else 0,
            "job_state": (
                "receipt_bound_outputs_complete_and_evaluated"
                if fit_result_ready else (
                    "submitted_receipt_requires_live_query" if fit_submission_active else "none"
                )
            ),
            "w2b_test_compute": "not_submitted_terminal_futility_stop",
            "w2c_submission_allowed": False,
            "w2c_target_msa_packet_status": w2c_target_msa["status"] if w2c_target_msa else None,
            "w2c_target_msa_packet_historical": bool(
                w2c_target_msa and w2c_target_msa.get("historical_after_completion")
            ),
            "w2c_target_msa_completion_status": (
                w2c_target_msa_complete["status"] if w2c_target_msa_complete else None
            ),
            "w2c_fit_learn_packet_status": w2c_fit_learn["status"] if w2c_fit_learn else None,
            "w2c_fit_learn_submission_status": (
                w2c_fit_submitted["status"] if w2c_fit_submitted else None
            ),
            "w2c_fit_learn_submission_performed": fit_submission_active,
            "w2c_fit_learn_approval_consumed": fit_submission_active,
            "w2c_additional_submission_allowed": False,
            "w2c_record_generation_approved": False,
            "w2c_threshold_learning_status": (
                w2c_fit_result["status"] if w2c_fit_result else None
            ),
            "w2c_threshold_candidate_targets": (
                w2c_fit_result["n_threshold_candidate_targets"] if w2c_fit_result else None
            ),
            "w2c_independent_screen_generation_approved": False,
            "w2c_certification_generation_approved": False,
            "w3_mechanism_case_count": w3_mechanism["n_cases"] if w3_mechanism else None,
            "w3_runtime_ready": w3_mechanism["runtime_ready"] if w3_mechanism else False,
            "w3_execution_ready": w3_mechanism["execution_ready"] if w3_mechanism else False,
            "w3_compute_approval_recorded": (
                w3_mechanism["approval_recorded"] if w3_mechanism else False
            ),
            "w3_jobs_submitted": 0,
            "next_action": next_action,
        },
        "claim_boundary": {
            "w2b": "terminal_not_supported",
            "w2c": (
                "threshold_learning_terminal_no_viability_claim" if fit_terminal else (
                    "thresholds_frozen_screen_not_run_no_claim" if fit_result_ready else (
                        "fit_jobs_in_flight_no_evaluated_records_no_claim" if fit_submission_active else (
                    "fit_packet_ready_no_records_no_claim" if fit_packet_ready else (
                    "inputs_ready_no_records_no_claim" if post_msa else "design_only_no_submit_no_claim"
                    )
                        )
                    )
                )
            ),
            "w3": (
                "mechanism_panel_preregistered_runtime_blocked_no_compute_no_claim"
                if w3_mechanism is not None
                else "negative_robustness_result_preserved"
            ),
        },
        "w3_runtime_provision": harness.get("w3_runtime_provision", {}),
    }

    report = {
        "artifact": "m6d_goal_state_refresh_report",
        "status": (
            "goal_state_refreshed_w3_mechanism_preregistered_runtime_gate_no_submit"
            if w3_mechanism is not None else
            "goal_state_refreshed_w2b_terminal_w2c_threshold_learning_terminal"
            if fit_terminal else (
                "goal_state_refreshed_w2b_terminal_w2c_thresholds_frozen_screen_gate"
                if fit_result_ready else (
                    "goal_state_refreshed_w2b_terminal_w2c_fit_jobs_in_flight"
                    if fit_submission_active else (
                "goal_state_refreshed_w2b_terminal_w2c_fit_packet_ready_approval_wait"
                if fit_packet_ready else (
                "goal_state_refreshed_w2b_terminal_w2c_msa_complete_fit_packet_no_submit"
                if post_msa else "goal_state_refreshed_w2b_terminal_w2c_no_submit"
                )
                    )
                )
            )
        ),
        "audit_ok": True,
        "updated_at": updated_at,
        "runtime_goal_active": runtime_goal_active,
        "w2b": w2b,
        "w2c": w2c,
        "w2c_target_msa_approval": w2c_target_msa,
        "w2c_target_msa_completion": w2c_target_msa_complete,
        "w2c_fit_learn_approval": w2c_fit_learn,
        "w2c_fit_learn_submission": w2c_fit_submitted,
        "w2c_threshold_learning_result": w2c_fit_result,
        "w3_mechanism_panel": w3_mechanism,
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
        "submission_performed": False if w3_mechanism is not None else fit_submission_active,
        "historical_w2c_submission_performed": fit_submission_active,
        "no_submit": True if w3_mechanism is not None else not fit_submission_active,
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


def _target_msa_packet_status_label(status: Any, historical: bool) -> str:
    label = str(status or "not_ready")
    if historical:
        return f"{label} (historical; superseded by completion)"
    return label


def render_markdown(report: Dict[str, Any]) -> str:
    target_msa = report.get("w2c_target_msa_approval") or {}
    target_msa_completion = report.get("w2c_target_msa_completion") or {}
    fit_learn = report.get("w2c_fit_learn_approval") or {}
    fit_submission = report.get("w2c_fit_learn_submission") or {}
    fit_result = report.get("w2c_threshold_learning_result") or {}
    w3_mechanism = report.get("w3_mechanism_panel") or {}
    target_msa_status = _target_msa_packet_status_label(
        target_msa.get("status"),
        bool(target_msa.get("historical_after_completion")),
    )
    return "\n".join([
        "# M6d Goal-State Refresh",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Runtime goal active: `{report['runtime_goal_active']}`.",
        f"W2b: `{report['w2b']['status']}`.",
        f"W2c: `{report['w2c']['status']}`.",
        f"W2c target-MSA packet: `{target_msa_status}`.",
        f"W2c target-MSA completion: `{target_msa_completion.get('status', 'not_complete')}`.",
        f"W2c fit-learn packet: `{fit_learn.get('status', 'not_ready')}`.",
        f"W2c fit-learn submission: `{fit_submission.get('status', 'not_submitted')}`.",
        f"W2c threshold-learning result: `{fit_result.get('status', 'not_evaluated')}`.",
        f"W3 mechanism panel: `{w3_mechanism.get('status', 'not_preregistered')}`.",
        f"W3 cases: `{w3_mechanism.get('n_cases', 0)}`.",
        f"W3 runtime ready: `{w3_mechanism.get('runtime_ready', False)}`.",
        f"W3 execution ready: `{w3_mechanism.get('execution_ready', False)}`.",
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
    target_msa_completion = report.get("w2c_target_msa_completion") or {}
    fit_learn = report.get("w2c_fit_learn_approval") or {}
    fit_submission = report.get("w2c_fit_learn_submission") or {}
    fit_result = report.get("w2c_threshold_learning_result") or {}
    w3_mechanism = report.get("w3_mechanism_panel") or {}
    target_msa_status = _target_msa_packet_status_label(
        target_msa.get("status"),
        bool(target_msa.get("historical_after_completion")),
    )
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
        f"- W2c target-MSA packet: `{target_msa_status}`",
        f"- W2c target-MSA completion: `{target_msa_completion.get('status', 'not_complete')}`",
        f"- W2c fit-learn packet: `{fit_learn.get('status', 'not_ready')}`",
        f"- W2c fit-learn submission: `{fit_submission.get('status', 'not_submitted')}`",
        f"- W2c threshold-learning result: `{fit_result.get('status', 'not_evaluated')}`",
        f"- W3 mechanism panel: `{w3_mechanism.get('status', 'not_preregistered')}`",
        f"- W3 runtime ready: `{w3_mechanism.get('runtime_ready', False)}`",
        f"- W3 execution ready: `{w3_mechanism.get('execution_ready', False)}`",
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
    target_msa_completion = report.get("w2c_target_msa_completion") or {}
    fit_learn = report.get("w2c_fit_learn_approval") or {}
    fit_submission = report.get("w2c_fit_learn_submission") or {}
    fit_result = report.get("w2c_threshold_learning_result") or {}
    target_msa_status = _target_msa_packet_status_label(
        target_msa.get("status"),
        bool(target_msa.get("historical_after_completion")),
    )
    lines = [
        "# M6d Next Science Actions",
        "",
        f"Status: `{report['status']}`.",
        f"No submit: `{report['no_submit']}`.",
        f"Cayuga submission allowed: `{report['cayuga_submission_allowed']}`.",
        f"W2c target-MSA packet: `{target_msa_status}`.",
        f"W2c target-MSA completion: `{target_msa_completion.get('status', 'not_complete')}`.",
        f"W2c fit-learn packet: `{fit_learn.get('status', 'not_ready')}`.",
        f"W2c fit-learn submission: `{fit_submission.get('status', 'not_submitted')}`.",
        f"W2c threshold-learning result: `{fit_result.get('status', 'not_evaluated')}`.",
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
    target_msa_status = _target_msa_packet_status_label(
        hpc.get("w2c_target_msa_packet_status"),
        bool(hpc.get("w2c_target_msa_packet_historical")),
    )
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
        f"- W2c target-MSA packet: `{target_msa_status}`",
        f"- W2c target-MSA completion: `{hpc.get('w2c_target_msa_completion_status', 'not_complete')}`",
        f"- W2c fit-learn packet: `{hpc.get('w2c_fit_learn_packet_status', 'not_ready')}`",
        f"- W2c fit-learn submission: `{hpc.get('w2c_fit_learn_submission_status', 'not_submitted')}`",
        f"- W2c threshold-learning result: `{hpc.get('w2c_threshold_learning_status', 'not_evaluated')}`",
        f"- W2c threshold candidates: `{hpc.get('w2c_threshold_candidate_targets', 'not_evaluated')}`",
        f"- W2c fit-learn submission performed: `{hpc.get('w2c_fit_learn_submission_performed', False)}`",
        f"- W2c fit-learn approval consumed: `{hpc.get('w2c_fit_learn_approval_consumed', False)}`",
        f"- W2c additional submission allowed: `{hpc.get('w2c_additional_submission_allowed', False)}`",
        f"- W2c record generation approved: `{hpc.get('w2c_record_generation_approved', False)}`",
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
    parser.add_argument(
        "--w2c-target-msa-completion",
        default="results/m6d_w2c_target_msa_completion.json",
    )
    parser.add_argument(
        "--w2c-fit-learn-packet",
        default="results/m6d_w2c_fit_learn_approval_packet.json",
    )
    parser.add_argument(
        "--w2c-fit-learn-submission-summary",
        default="results/m6d_w2c_fit_learn_submit_receipt_summary.json",
    )
    parser.add_argument(
        "--w2c-threshold-learning-report",
        default="results/m6d_w2c_threshold_learning_report.json",
    )
    parser.add_argument(
        "--w3-mechanism-packet",
        default="configs/m6d_w3_mechanism_panel_protocol.json",
    )
    parser.add_argument("--updated-at", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--test-result", required=True)
    parser.add_argument("--runtime-goal-active", action="store_true")
    parser.add_argument("--out-json", default="results/m6d_goal_state_refresh_report.json")
    parser.add_argument("--out-md", default="results/m6d_goal_state_refresh_report.md")
    args = parser.parse_args(argv)

    if not os.path.exists(args.w2c_threshold_learning_report) and os.path.exists(args.out_json):
        existing_report = _load_json(args.out_json)
        existing_result = existing_report.get("w2c_threshold_learning_result")
        if (
            isinstance(existing_result, dict)
            and existing_result.get("threshold_decisions_frozen") is True
        ):
            parser.error(
                "refusing to overwrite frozen W2c goal-state without the threshold-learning report"
            )

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
        (
            _load_json(args.w2c_target_msa_completion)
            if os.path.exists(args.w2c_target_msa_completion)
            else None
        ),
        (
            _load_json(args.w2c_fit_learn_packet)
            if os.path.exists(args.w2c_fit_learn_packet)
            else None
        ),
        (
            _load_json(args.w2c_fit_learn_submission_summary)
            if os.path.exists(args.w2c_fit_learn_submission_summary)
            else None
        ),
        (
            _load_json(args.w2c_threshold_learning_report)
            if os.path.exists(args.w2c_threshold_learning_report)
            else None
        ),
        (
            _load_json(args.w3_mechanism_packet)
            if (
                os.path.exists(args.w3_mechanism_packet)
                and os.path.exists(args.w2c_threshold_learning_report)
            )
            else None
        ),
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
