"""Tests for terminal-W2b / prospective-W2c goal-state refresh."""

import copy
import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_state_refresh import (
    main,
    refresh_bundle,
    render_completion_markdown,
)


def _w2b():
    return {
        "status": "w2b_certification_terminal_not_supported",
        "audit_ok": True,
        "panel_certification_gate": {
            "passed": False,
            "observed_certified_targets": 4,
            "observed_selective_pae_certified_targets": 0,
        },
        "terminal_after_certification": True,
        "test_can_change_certificate": False,
        "test_required_for_final_reporting": False,
        "can_claim_w2b_target_adaptive_viability": False,
        "records": {"test": []},
        "certified_targets": ["easy-a", "easy-b", "easy-c", "easy-d"],
        "selective_pae_certified_targets": [],
    }


def _w2c():
    return {
        "status": "w2c_design_power_qualified_no_submit",
        "audit_ok": True,
        "design_power_qualified": True,
        "execution_ready": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_w2c": False,
        "locked_scientific_digest": "d" * 64,
        "certification_design": {
            "conditional_certification_power": 0.81786,
            "minimum_conditional_power": 0.8,
            "minimum_accepted": 90,
            "design_true_risk": 0.08,
        },
        "remaining_unlock_conditions": ["implement evaluator", "select targets"],
    }


def _target_msa_packet():
    return {
        "status": "ready_for_explicit_target_msa_approval_not_submitted",
        "audit_ok": True,
        "scope": {
            "n_targets": 8,
            "target_ids": [f"fresh-{index}" for index in range(8)],
            "expected_slurm_jobs": 8,
        },
        "checks": {
            "local_guard_dry_run_passed": True,
            "cayuga_guard_dry_run_passed": True,
            "local_cayuga_input_sha_matches": 40,
            "local_cayuga_input_sha_mismatches": 0,
            "cayuga_slurm_jobs_before": 0,
            "cayuga_slurm_jobs_after": 0,
            "cayuga_receipt_absent": True,
        },
        "approval": {
            "submission_performed": False,
            "explicit_user_approval_required": True,
            "required_user_phrase": "approve W2c target-MSA precompute",
        },
    }


def _target_msa_completion():
    return {
        "status": "target_msa_precompute_complete_8_of_8",
        "audit_ok": True,
        "n_targets": 8,
        "n_target_msas": 8,
        "n_target_msa_reports": 8,
        "strict_manifest_ready_targets": 8,
        "submitted_jobs_total": 19,
        "gpu_allocation_hours_total": 0.144722,
        "approved_gpu_hour_ceiling": 8.0,
        "within_approved_gpu_hour_ceiling": True,
        "claim_boundary": (
            "Target-MSA input preparation only. This is not W2c predictive evidence, a gate "
            "certificate, or authorization for ProteinMPNN/Boltz record generation."
        ),
        "targets": [
            {
                "target_id": f"fresh-{index}",
                "target_msa_sha256": "a" * 64,
                "target_msa_report_sha256": "b" * 64,
                "report_ok": True,
            }
            for index in range(8)
        ],
    }


def _fit_learn_packet():
    return {
        "status": "ready_for_explicit_w2c_fit_learn_approval_not_submitted",
        "audit_ok": True,
        "input_lock_digest_sha256": "c" * 64,
        "packet_preparation_approval": {
            "record_generation_approved": False,
        },
        "approval": {
            "submission_performed": False,
            "explicit_user_approval_required": True,
            "required_user_phrase": (
                "approve W2c threshold-learning 480-record generation on H100"
            ),
            "environment_value": "approve-w2c-fit-learn-480-h100",
        },
        "scope": {
            "stage": "threshold_learning",
            "seed_namespace": "w2c-fit-learn-v1",
            "n_targets": 8,
            "target_ids": [f"fresh-{index}" for index in range(8)],
            "records_per_target": 60,
            "total_records": 480,
            "proteinmpnn_jobs": 8,
            "total_slurm_jobs": 16,
            "scheduler_resource": "preempt_gpu/low/gpu:h100:1",
            "authorizes_record_generation": False,
            "authorizes_independent_screen": False,
            "authorizes_certification": False,
        },
        "checks": {
            "local_input_lock_verified": True,
            "cayuga_input_lock_verified": True,
            "local_guard_dry_run_passed": True,
            "cayuga_guard_dry_run_passed": True,
            "local_guard_no_approval_refused": True,
            "cayuga_guard_no_approval_refused": True,
            "cayuga_bound_artifact_hash_matches": 19,
            "cayuga_bound_artifact_hash_mismatches": 0,
            "local_initial_outputs_absent": 16,
            "cayuga_initial_outputs_absent": 16,
            "cayuga_slurm_jobs_before": 0,
            "cayuga_slurm_jobs_after": 0,
            "local_receipt_absent": True,
            "cayuga_receipt_absent": True,
            "local_summary_absent": True,
            "cayuga_summary_absent": True,
        },
    }


def _fit_learn_submission():
    return {
        "artifact": "m6d_w2c_fit_learn_submit_receipt_summary",
        "status": "submitted_on_cayuga",
        "workstream": "m6d_w2c_fit_learn",
        "manifest": "configs/m6d_w2c_fit_learn_targets.json",
        "n_targets": 8,
        "n_records": 8,
        "n_receipt_events": 16,
        "claim_boundary": "job submission is not W2 evidence",
        "targets": [
            {
                "target_id": f"fresh-{index}",
                "proteinmpnn_job_id": str(1000 + 2 * index),
                "boltz_job_id": str(1001 + 2 * index),
                "records": (
                    f"hpc_outputs/m6d_w2c_fit_learn_records/fresh-{index}/"
                    "records_boltz_complex.jsonl"
                ),
            }
            for index in range(8)
        ],
    }


def _threshold_learning_result():
    target_ids = [f"fresh-{index}" for index in range(8)]
    return {
        "artifact": "m6d_w2c_threshold_learning_report",
        "status": "w2c_threshold_learning_terminal_not_supported",
        "audit_ok": True,
        "locked_scientific_digest": "d" * 64,
        "lrmsd_threshold": 4.0,
        "n_initial_targets": 8,
        "initial_target_ids": target_ids,
        "n_threshold_candidate_targets": 0,
        "threshold_candidate_targets": [],
        "minimum_selective_targets_required": 3,
        "candidate_floor_reachable": False,
        "terminal_after_threshold_learning": True,
        "threshold_decisions_frozen": True,
        "independent_screen_generation_approved": False,
        "certification_generation_approved": False,
        "can_claim_w2c_selective_target_adaptive_viability": False,
        "can_claim_universal_w2_generalization": False,
        "targets": [
            {
                "target_id": target_id,
                "decision_frozen": True,
                "learning": {
                    "mode": "refuse",
                    "candidate": False,
                    "tau": None,
                    "accepted": 0,
                    "false_accepts": 0,
                    "false_accept_rate": None,
                    "auroc_pae": None,
                },
            }
            for target_id in target_ids
        ],
        "qc": {
            "ok": True,
            "n_rows": 480,
            "n_unique_record_keys": 480,
            "n_failures": 0,
            "require_chain_ids": True,
            "require_complex_target_id": True,
            "require_provenance": True,
            "expect_predictor_id": "boltz2_complex",
            "expect_signal_source": "boltz2_pae_interaction",
            "expect_label_source": "boltz2_lrmsd_to_reference",
        },
        "claim_boundary": "threshold learning only",
        "next_action": "close W2c",
    }


def _w3_mechanism_packet():
    rows = [
        {"case_id": f"w3m-{index + 1:03d}", "panel_block": "boltz_chai_3pc8_challenge"}
        for index in range(18)
    ]
    rows.extend(
        {
            "case_id": f"w3m-{index + 19:03d}",
            "panel_block": "w2c_pae_order_statistics",
        }
        for index in range(40)
    )
    return {
        "artifact": "m6d_w3_decisive_mechanism_panel_protocol",
        "status": "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit",
        "audit_ok": True,
        "failures": [],
        "selection_lock": {
            "n_total_cases": 58,
            "selection_uses_outcome_labels": False,
        },
        "execution_packet": {
            "n_inputs": 58,
            "inputs_emitted": True,
            "private_manifest_sha256": "e" * 64,
            "no_submit": True,
            "no_gpu_compute": True,
            "no_api_spend": True,
            "no_network_fetch": True,
            "approval_recorded": False,
            "approval_consumed": False,
            "runtime_ready": False,
            "execution_ready": False,
        },
        "predictor_protocol": {
            "predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        },
        "can_claim_independent_predictor_robustness_now": False,
        "can_claim_w2c_rescue_now": False,
        "claim_boundary": "preregistered no-submit mechanism panel only",
        "rows": rows,
    }


def _w3_completion():
    return {
        "artifact": "m6d_w3_mechanism_panel_adjudication",
        "status": "adjudicated",
        "audit_ok": True,
        "failures": [],
        "joint_outcome": "context_dependent_or_unresolved",
        "can_claim_population_level_independent_predictor_robustness": False,
        "can_reopen_or_rescue_w2c": False,
        "three_pc8": {
            "n_discordant": 12,
            "aligns_with_chai": 12,
            "aligns_with_boltz": 0,
            "n_controls": 6,
            "control_successes": 6,
            "outcome": "chai_supported_on_challenge_panel",
        },
        "w2c": {
            "n_rows": 40,
            "n_targets": 8,
            "label_agreement_with_boltz": 30,
            "targets_with_at_least_4_of_5_agreement": 5,
            "label_agreement_fraction": 0.75,
            "outcome": "mixed_or_contract_blocked",
        },
        "claim_boundary": "bounded completed W3 mechanism panel only",
    }


def _w3b_fit_ready_artifacts():
    target_ids = [f"w3b-{index}" for index in range(8)]
    roles = ["fit"] * 3 + ["certification"] * 3 + ["held_out_test"] * 2
    records = [60] * 3 + [150] * 3 + [120] * 2
    msa_hashes = {target_id: f"{index + 1:064x}" for index, target_id in enumerate(target_ids)}
    role_counts = {"fit": 3, "certification": 3, "held_out_test": 2}
    scientific_digest = "a" * 64
    lifecycle_sha = "b" * 64
    runtime_sha = "c" * 64
    runtime_digest = "d" * 64
    packet_digest = "e" * 64
    design_gate = {
        "artifact": "m6d_w3b_disagreement_design_gate",
        "status": "w3b_design_power_qualified_inputs_ready_no_submit",
        "audit_ok": True,
        "failures": [],
        "design_power_qualified": True,
        "inputs_ready": True,
        "execution_ready": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_w3b": False,
        "locked_scientific_digest": scientific_digest,
        "fresh_target_contract": {
            "n_targets": 8,
            "target_ids": target_ids,
            "role_counts": role_counts,
            "target_msa_ready": True,
            "missing_target_msa_targets": [],
        },
        "certification_power": {
            "accepted_rows": 100,
            "conditional_certification_power": 0.824333,
            "maximum_certifiable_false_accepts": 10,
        },
        "compute_budget": {
            "maximum_candidate_designs": 870,
            "maximum_predictor_evaluations": 1740,
            "maximum_h100_gpu_hours": 24.0,
        },
    }
    lifecycle = {
        "artifact": "m6d_w3b_target_msa_lifecycle",
        "status": "target_msa_precompute_complete_8_of_8",
        "audit_ok": True,
        "completion_ok": True,
        "failures": [],
        "n_failures": 0,
        "n_targets": 8,
        "target_ids": target_ids,
        "jobs_terminal_success": True,
        "receipt_present": True,
        "summary_present": True,
        "within_gpu_budget": True,
        "gpu_allocation_hours": 0.25,
        "maximum_a40_gpu_hours": 8.0,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "can_claim_w3b": False,
        "strict_manifest": {
            "ok": True,
            "n_targets": 8,
            "n_ready_targets": 8,
            "failures": [],
        },
        "target_artifacts": [
            {
                "target_id": target_id,
                "target_msa_sha256": msa_hashes[target_id],
                "target_msa_report_sha256": "f" * 64,
                "target_msa_report_ok": True,
                "target_sequence_sha256": "1" * 64,
                "expected_target_sequence_sha256": "1" * 64,
            }
            for target_id in target_ids
        ],
        "telemetry_reconciliation_applied": True,
        "allocation_telemetry_reconciliation": {
            "status": "allocation_telemetry_reconciled",
            "audit_ok": True,
            "failures": [],
            "normalized_job_ids": [str(1000 + index) for index in range(8)],
        },
    }
    manifest_targets = [
        {
            "id": target_id,
            "experimental_role": role,
            "num_seq": n_records,
            "target_msa_sha256": msa_hashes[target_id],
        }
        for target_id, role, n_records in zip(target_ids, roles, records)
    ]
    execution_manifest = {
        "artifact": "m6d_w3b_execution_target_manifest",
        "status": "w3b_execution_inputs_locked_no_submit",
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_generate_candidates_or_run_predictors": False,
        "role_counts": role_counts,
        "target_ids": target_ids,
        "targets": manifest_targets,
        "total_candidate_designs": 870,
        "total_matched_predictor_evaluations": 1740,
        "locked_scientific_digest": scientific_digest,
        "target_msa_lifecycle_sha256": lifecycle_sha,
    }
    input_targets = [
        {
            "target_id": target_id,
            "experimental_role": role,
            "records_planned": n_records,
            "target_msa_sha256": msa_hashes[target_id],
        }
        for target_id, role, n_records in zip(target_ids, roles, records)
    ]
    execution_input_lock = {
        "artifact": "m6d_w3b_execution_input_lock",
        "status": "w3b_execution_input_locked_no_submit",
        "audit_ok": True,
        "failures": [],
        "no_submit": True,
        "n_targets": 8,
        "n_artifacts": 56,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "lock_digest_sha256": "2" * 64,
        "binding": {
            "targets": input_targets,
            "locked_scientific_digest": scientific_digest,
            "target_msa_lifecycle_sha256": lifecycle_sha,
        },
    }
    runtime_readiness = {
        "artifact": "m6d_w3b_runtime_lock_readiness",
        "status": "w3b_runtime_lock_ready_for_separate_fit_approval_packet",
        "audit_ok": True,
        "failures": [],
        "n_failures": 0,
        "execution_lock_ready": True,
        "runtime_identity_ready": True,
        "fit_packet_prerequisites_ready": True,
        "can_submit_fit_stage": False,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "no_submit": True,
        "runtime_lock_sha256": runtime_sha,
        "runtime_lock_digest_sha256": runtime_digest,
    }
    matched_record_contract = {
        "artifact": "m6d_w3b_matched_record_contract",
        "status": "w3b_matched_record_contract_ready_for_stage_inputs",
        "audit_ok": True,
        "failures": [],
        "n_failures": 0,
        "execution_lock_ready": True,
        "runtime_identity_ready": True,
        "assembly_ready": True,
        "can_run_candidate_generation_or_prediction": False,
        "can_claim_w3b": False,
        "no_submit": True,
        "required_predictors": ["boltz2_complex", "af2_multimer_colabfold_v1"],
        "stage_records_per_target": {"fit": 60, "certification": 150, "held_out_test": 120},
        "runtime_lock_sha256": runtime_sha,
        "runtime_lock_digest_sha256": runtime_digest,
    }
    fit_targets = [
        {
            "target_id": target_id,
            "records_planned": 60,
            "target_msa_sha256": msa_hashes[target_id],
        }
        for target_id in target_ids[:3]
    ]
    approval_contract = {
        "stage": "fit",
        "target_count": 3,
        "records_per_target": 60,
        "candidate_designs": 180,
        "matched_predictor_evaluations": 360,
        "proteinmpnn_cpu_jobs": 3,
        "boltz_h100_jobs": 3,
        "af2_h100_jobs": 3,
        "user_phrase": "approve W3b fit-stage 180-design matched Boltz-AF2 generation on H100",
        "authorizes_certification": False,
        "authorizes_held_out_test": False,
        "authorizes_claim": False,
    }
    bound_artifacts = [
        {"path": path, "sha256": "3" * 64}
        for path in (
            "configs/m6d_w3b_execution_targets.json",
            "configs/m6d_w3b_execution_input_lock.json",
            "configs/m6d_w3b_runtime_lock.json",
            "results/m6d_w3b_runtime_lock_readiness.json",
            "results/m6d_w3b_matched_record_contract.json",
        )
    ]
    fit_packet_readiness = {
        "artifact": "m6d_w3b_fit_packet_readiness",
        "status": "w3b_fit_packet_ready_awaiting_explicit_approval",
        "audit_ok": True,
        "failures": [],
        "n_failures": 0,
        "fit_packet_ready": True,
        "execution_lock_ready": True,
        "runtime_identity_ready": True,
        "matched_record_contract_ready": True,
        "explicit_fit_approval_recorded": False,
        "can_submit_fit_stage": False,
        "can_run_candidate_generation_or_prediction": False,
        "submitted_jobs": 0,
        "can_claim_w3b": False,
        "no_submit": True,
        "packet_digest_sha256": packet_digest,
        "fit_targets": fit_targets,
        "approval_contract": approval_contract,
        "bound_artifacts": bound_artifacts,
        "claim_boundary": "fit packet readiness only",
    }
    fit_approval_packet = {
        "artifact": "m6d_w3b_fit_approval_packet",
        "status": "w3b_fit_approval_packet_ready_no_submit",
        "audit_ok": True,
        "approval_recorded": False,
        "submitted_jobs": 0,
        "can_claim_w3b": False,
        "no_submit": True,
        "readiness_packet_digest_sha256": packet_digest,
        "fit_targets": copy.deepcopy(fit_targets),
        "approval_contract": copy.deepcopy(approval_contract),
        "bound_artifacts": copy.deepcopy(bound_artifacts),
    }
    return (
        design_gate,
        lifecycle,
        execution_manifest,
        execution_input_lock,
        runtime_readiness,
        matched_record_contract,
        fit_packet_readiness,
        fit_approval_packet,
    )


def _w3b_recovery_artifacts():
    targets = ["w3b-0", "w3b-1", "w3b-2"]
    jobs = {
        "w3b-0": ("101", "102", "103"),
        "w3b-1": ("104", "105", "106"),
        "w3b-2": ("107", "108", "109"),
    }
    submission_targets = [
        {
            "target_id": target_id,
            "proteinmpnn_job_id": jobs[target_id][0],
            "boltz_job_id": jobs[target_id][1],
            "af2_job_id": jobs[target_id][2],
        }
        for target_id in targets
    ]
    submission = {
        "artifact": "m6d_w3b_fit_submit_receipt_summary",
        "status": "w3b_fit_jobs_submitted_awaiting_completion",
        "n_targets": 3,
        "n_candidate_designs": 180,
        "n_predictor_evaluations_planned": 360,
        "n_jobs": 9,
        "n_proteinmpnn_jobs": 3,
        "n_boltz_h100_jobs": 3,
        "n_af2_h100_jobs": 3,
        "targets": submission_targets,
        "can_claim_w3b": False,
    }
    observation_targets = [
        {
            "target_id": target_id,
            "proteinmpnn": {"job_id": jobs[target_id][0], "state": "COMPLETED", "exit_code": "0:0"},
            "boltz": {"job_id": jobs[target_id][1], "state": "COMPLETED", "exit_code": "0:0"},
            "failed_af2": {"job_id": jobs[target_id][2], "state": "FAILED", "exit_code": "1:0"},
            "failure_kind": "container_relative_input_path_not_found_before_prediction",
            "partial_state": {"terminal_af2_outputs_absent": True},
        }
        for target_id in targets
    ]
    observation = {
        "artifact": "m6d_w3b_fit_initial_execution_observation",
        "status": "w3b_fit_af2_path_failure_recovery_eligible_no_submit",
        "audit_ok": True,
        "n_targets": 3,
        "n_initial_jobs": 9,
        "n_proteinmpnn_completed": 3,
        "n_af2_failed_before_prediction": 3,
        "initial_failed_af2_gpu_seconds": 38,
        "target_reports": observation_targets,
        "recovery_submission_performed": False,
        "no_submit": True,
        "can_claim_w3b": False,
    }
    failed_ids = sorted((jobs[target_id][2] for target_id in targets), key=int)
    recovery_packet = {
        "artifact": "m6d_w3b_fit_af2_recovery_approval_packet",
        "status": "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval",
        "audit_ok": True,
        "approval_recorded": False,
        "submitted_jobs": 0,
        "no_submit": True,
        "can_claim_w3b": False,
        "packet_digest_sha256": "7" * 64,
        "targets": [
            {
                "target_id": target_id,
                "failed_af2_job_id": jobs[target_id][2],
            }
            for target_id in targets
        ],
        "approval_contract": {
            "stage": "fit_af2_path_recovery",
            "failed_af2_job_ids": failed_ids,
            "target_count": 3,
            "af2_h100_recovery_jobs": 3,
            "proteinmpnn_jobs_authorized": 0,
            "boltz_jobs_authorized": 0,
            "recovery_time_limit": "03:59:30",
            "requeue": False,
            "initial_failed_af2_gpu_seconds": 38,
            "maximum_protocol_gpu_seconds_after_recovery": 86348,
            "maximum_protocol_h100_gpu_hours": 24.0,
            "authorizes_certification": False,
            "authorizes_held_out_test": False,
            "authorizes_adaptive_top_up": False,
            "authorizes_claim": False,
            "user_phrase": (
                "approve W3b AF2 fit recovery for failed jobs "
                + ",".join(failed_ids)
                + " on H100"
            ),
            "environment_variable": "BIO_SFM_APPROVE_W3B_AF2_RECOVERY",
            "environment_value": (
                "approve-w3b-af2-fit-recovery-" + "-".join(failed_ids) + "-h100"
            ),
        },
    }
    return submission, observation, recovery_packet


def _legacy_bundle():
    anchor = {
        "artifact": "m6d_goal_mode_current_anchor",
        "goal_mode": "active",
        "objective": "old objective",
        "claim_boundaries": {},
        "current_artifacts": {},
        "current_status": {
            "project_status_w2": "panel_approval_packet_ready_awaiting_explicit_approval"
        },
        "next_resume_steps": ["submit v9"],
        "latest_goal_mode_refresh": {"local_harness": "676 passed"},
    }
    completion = {
        "artifact": "m6d_goal_completion_audit",
        "status": "goal_active_w2_remaining",
        "audit_ok": True,
        "workstream_status": {"W2_multi_target_panel": {"complete": False}},
        "w2_gate": {"panel_can_submit_if_explicitly_approved": True},
        "w2_execution_attempt": {"status": "old"},
    }
    drift = {
        "artifact": "m6d_goal_drift_audit",
        "status": "no_major_direction_drift_w2_blocked",
        "current_state": {
            "W2_multi_target_panel": {"status": "approval_pending"},
            "W2_panel_submission_decision": {
                "status": "approval_pending",
                "operator_submit_allowed_by_this_artifact": True,
            },
            "completion_audit": {"status": "goal_active_w2_remaining"},
        },
    }
    actions = {"artifact": "m6d_followup_next_science_actions", "status": "old"}
    harness = {
        "artifact": "m6d_goal_mode_local_harness_status",
        "w3_runtime_provision": {"status": "preserved"},
    }
    return anchor, completion, drift, actions, harness


def _refresh_current_w3b(*, completion=None, artifacts=None, recovery=None):
    gate = _w2c()
    gate["execution_readiness"] = {
        "target_manifest_present": True,
        "target_manifest_integrity_ok": True,
        "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
        "target_msa_ready": False,
        "evaluator_implemented": True,
    }
    optional = [*(artifacts or _w3b_fit_ready_artifacts())]
    if recovery is not None:
        optional.extend(recovery)
    return refresh_bundle(
        *_legacy_bundle(),
        _w2b(),
        gate,
        _target_msa_packet(),
        _target_msa_completion(),
        _fit_learn_packet(),
        _fit_learn_submission(),
        _threshold_learning_result(),
        _w3_mechanism_packet(),
        completion or _w3_completion(),
        *optional,
        updated_at="2026-07-15T18:00:00+09:00",
        test_command="pytest -q",
        test_result="passed",
        runtime_goal_active=True,
    )


class M6DGoalStateRefreshTests(unittest.TestCase):
    def test_refresh_replaces_current_routes_and_preserves_history(self):
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            _w2c(),
            updated_at="2026-07-12T12:00:00+09:00",
            test_command="python3 -m pytest -q",
            test_result="879 passed",
        )

        anchor = bundle["anchor"]
        self.assertEqual(anchor["goal_mode"], "contract_ready_runtime_goal_inactive")
        self.assertEqual(anchor["current_status"]["w2b"], "w2b_certification_terminal_not_supported")
        self.assertEqual(anchor["current_status"]["w2c"], "w2c_design_power_qualified_no_submit")
        self.assertFalse(anchor["current_status"]["w2c_cayuga_submission_allowed"])
        self.assertNotIn("submit v9", anchor["next_resume_steps"])
        self.assertIn("879 passed", anchor["current_status"]["local_harness_verification"])

        completion = bundle["completion"]
        self.assertEqual(completion["status"], "goal_active_w2b_terminal_w2c_precompute")
        self.assertEqual(completion["remaining_requirements"], ["W2c_evaluator_and_fresh_target_gate"])
        self.assertTrue(completion["w2_execution_attempt"]["historical"])
        self.assertFalse(completion["w2_gate"]["panel_can_submit_if_explicitly_approved"])

        drift = bundle["drift"]
        self.assertFalse(drift["major_direction_drift"])
        self.assertEqual(
            drift["current_state"]["W2_multi_target_panel"]["status"],
            "w2b_certification_terminal_not_supported",
        )
        self.assertTrue(drift["current_state"]["W2_panel_submission_decision"]["historical"])

        self.assertTrue(bundle["actions"]["no_submit"])
        self.assertFalse(bundle["harness"]["hpc_status"]["w2c_submission_allowed"])
        self.assertTrue(bundle["report"]["historical_detail_retained"])

    def test_nonterminal_w2b_is_rejected(self):
        report = _w2b()
        report["status"] = "w2b_certification_complete_awaiting_test"
        with self.assertRaisesRegex(ValueError, "W2b terminal invariants"):
            refresh_bundle(
                *_legacy_bundle(),
                report,
                _w2c(),
                updated_at="2026-07-12T12:00:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_ready_target_msa_packet_becomes_the_only_current_action(self):
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            _w2c(),
            _target_msa_packet(),
            updated_at="2026-07-12T12:00:00+09:00",
            test_command="pytest",
            test_result="passed",
        )

        self.assertEqual(
            bundle["anchor"]["current_status"]["w2c_target_msa_packet_status"],
            "ready_for_explicit_target_msa_approval_not_submitted",
        )
        self.assertIn("Wait for explicit user approval", bundle["anchor"]["current_status"]["next_action"])
        self.assertFalse(bundle["completion"]["w2c_target_msa_approval"]["submission_performed"])
        self.assertFalse(bundle["harness"]["hpc_status"]["w2c_submission_allowed"])

    def test_target_msa_completion_supersedes_pre_submit_packet(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            gate,
            _target_msa_packet(),
            _target_msa_completion(),
            updated_at="2026-07-14T11:30:00+09:00",
            test_command="pytest",
            test_result="passed",
        )

        self.assertTrue(bundle["anchor"]["current_status"]["w2c_target_msa_ready"])
        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W2c_threshold_learning_packet_gate"],
        )
        self.assertIn("threshold-learning packet", bundle["completion"]["next_action"])
        self.assertTrue(
            bundle["completion"]["w2c_target_msa_approval"]["historical_after_completion"]
        )
        self.assertEqual(
            bundle["report"]["w2c_target_msa_completion"]["status"],
            "target_msa_precompute_complete_8_of_8",
        )
        self.assertNotIn("job_ids", bundle["report"]["w2c_target_msa_completion"])
        self.assertFalse(bundle["actions"]["cayuga_submission_allowed"])
        self.assertIn(
            "historical; superseded by completion",
            render_completion_markdown(bundle["completion"]),
        )

    def test_malformed_target_msa_completion_is_rejected(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        malformed = _target_msa_completion()
        malformed["targets"][0]["target_msa_sha256"] = "not-a-sha256"

        with self.assertRaisesRegex(ValueError, "hash_locks_present"):
            refresh_bundle(
                *_legacy_bundle(),
                _w2b(),
                gate,
                _target_msa_packet(),
                malformed,
                updated_at="2026-07-14T11:30:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_fit_learn_packet_advances_to_separate_approval_wait(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            gate,
            _target_msa_packet(),
            _target_msa_completion(),
            _fit_learn_packet(),
            updated_at="2026-07-14T13:30:00+09:00",
            test_command="pytest",
            test_result="passed",
        )

        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W2c_threshold_learning_explicit_approval"],
        )
        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w2b_terminal_w2c_fit_packet_ready_approval_wait",
        )
        self.assertEqual(
            bundle["anchor"]["current_status"]["w2c_fit_learn_packet_status"],
            "ready_for_explicit_w2c_fit_learn_approval_not_submitted",
        )
        self.assertFalse(bundle["anchor"]["current_status"]["w2c_record_generation_approved"])
        self.assertFalse(bundle["harness"]["hpc_status"]["w2c_submission_allowed"])
        self.assertFalse(bundle["harness"]["hpc_status"]["w2c_record_generation_approved"])
        self.assertIn("480-record generation on H100", bundle["completion"]["next_action"])
        self.assertIn("W2c fit-learn packet", render_completion_markdown(bundle["completion"]))

    def test_fit_learn_packet_with_submission_or_scope_drift_is_rejected(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        for field, value, failure in (
            (("approval", "submission_performed"), True, "submission_not_performed"),
            (("scope", "total_records"), 479, "total_records"),
            (("checks", "cayuga_slurm_jobs_after"), 1, "slurm_zero"),
        ):
            with self.subTest(field=field):
                packet = _fit_learn_packet()
                packet[field[0]][field[1]] = value
                with self.assertRaisesRegex(ValueError, failure):
                    refresh_bundle(
                        *_legacy_bundle(),
                        _w2b(),
                        gate,
                        _target_msa_packet(),
                        _target_msa_completion(),
                        packet,
                        updated_at="2026-07-14T13:30:00+09:00",
                        test_command="pytest",
                        test_result="passed",
                    )

    def test_fit_learn_submission_consumes_approval_and_blocks_resubmission(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            gate,
            _target_msa_packet(),
            _target_msa_completion(),
            _fit_learn_packet(),
            _fit_learn_submission(),
            updated_at="2026-07-14T14:00:00+09:00",
            test_command="pytest",
            test_result="passed",
        )

        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w2b_terminal_w2c_fit_jobs_in_flight",
        )
        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W2c_threshold_learning_completion_and_QC"],
        )
        self.assertTrue(bundle["anchor"]["current_status"]["w2c_fit_learn_approval_consumed"])
        self.assertFalse(bundle["anchor"]["current_status"]["w2c_additional_submission_allowed"])
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_submitted"], 16)
        self.assertTrue(bundle["report"]["submission_performed"])
        self.assertFalse(bundle["report"]["no_submit"])
        self.assertIn("learning-only evaluator", bundle["completion"]["next_action"])
        self.assertFalse(bundle["actions"]["cayuga_submission_allowed"])

    def test_fit_learn_submission_with_duplicate_job_id_is_rejected(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        submission = _fit_learn_submission()
        submission["targets"][1]["proteinmpnn_job_id"] = submission["targets"][0]["proteinmpnn_job_id"]
        with self.assertRaisesRegex(ValueError, "job_ids_complete"):
            refresh_bundle(
                *_legacy_bundle(),
                _w2b(),
                gate,
                _target_msa_packet(),
                _target_msa_completion(),
                _fit_learn_packet(),
                submission,
                updated_at="2026-07-14T14:00:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_terminal_threshold_learning_closes_w2c_without_later_compute(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            gate,
            _target_msa_packet(),
            _target_msa_completion(),
            _fit_learn_packet(),
            _fit_learn_submission(),
            _threshold_learning_result(),
            updated_at="2026-07-14T14:30:00+09:00",
            test_command="pytest",
            test_result="passed",
            runtime_goal_active=True,
        )

        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w2b_terminal_w2c_threshold_learning_terminal",
        )
        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W3_next_experiment_selection"],
        )
        self.assertEqual(
            bundle["anchor"]["claim_boundaries"]["w2c_selective_target_adaptive_viability"],
            "terminal_not_supported",
        )
        self.assertIn("decisive W3 science", bundle["anchor"]["objective"])
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_completed"], 16)
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_running"], 0)
        self.assertEqual(bundle["harness"]["hpc_status"]["active_branch"], "none")
        self.assertFalse(
            bundle["anchor"]["current_status"][
                "w2c_independent_screen_generation_approved"
            ]
        )
        self.assertFalse(
            bundle["anchor"]["current_status"]["w2c_certification_generation_approved"]
        )
        self.assertIn("Close W2c", bundle["completion"]["next_action"])
        self.assertIn("distinct W3 experiment", bundle["drift"]["active_risks"][-1]["control"])

    def test_w3_mechanism_packet_advances_to_runtime_gate_without_compute(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        bundle = refresh_bundle(
            *_legacy_bundle(),
            _w2b(),
            gate,
            _target_msa_packet(),
            _target_msa_completion(),
            _fit_learn_packet(),
            _fit_learn_submission(),
            _threshold_learning_result(),
            _w3_mechanism_packet(),
            updated_at="2026-07-14T15:00:00+09:00",
            test_command="pytest",
            test_result="passed",
            runtime_goal_active=True,
        )

        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w3_mechanism_preregistered_runtime_gate_no_submit",
        )
        self.assertEqual(bundle["report"]["w3_mechanism_panel"]["n_cases"], 58)
        self.assertTrue(bundle["report"]["no_submit"])
        self.assertFalse(bundle["report"]["submission_performed"])
        self.assertTrue(bundle["report"]["historical_w2c_submission_performed"])
        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W3_colabfold_runtime_receipt_then_separate_compute_approval"],
        )
        self.assertFalse(bundle["anchor"]["current_status"]["w3_runtime_ready"])
        self.assertFalse(bundle["anchor"]["current_status"]["w3_execution_ready"])
        self.assertFalse(
            bundle["anchor"]["current_status"]["w3_compute_approval_recorded"]
        )
        self.assertEqual(bundle["harness"]["hpc_status"]["w3_jobs_submitted"], 0)
        self.assertIn("ColabFold 1.6.1", bundle["completion"]["next_action"])

    def test_completed_w3_and_w3b_fit_packet_become_current_boundary(self):
        bundle = _refresh_current_w3b()

        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w3_complete_w3b_fit_packet_ready_approval_wait",
        )
        self.assertEqual(
            bundle["report"]["w3_mechanism_completion"]["joint_outcome"],
            "context_dependent_or_unresolved",
        )
        self.assertEqual(
            bundle["completion"]["remaining_requirements"],
            ["W3b_fit_stage_explicit_approval"],
        )
        self.assertEqual(
            bundle["anchor"]["current_status"]["w3b"],
            "w3b_fit_packet_ready_awaiting_explicit_approval",
        )
        self.assertTrue(bundle["anchor"]["current_status"]["w3_execution_complete"])
        self.assertFalse(bundle["anchor"]["current_status"]["w3b_fit_approval_recorded"])
        self.assertEqual(bundle["harness"]["hpc_status"]["w3b_fit_jobs_submitted"], 0)
        self.assertFalse(bundle["actions"]["cayuga_submission_allowed"])
        self.assertTrue(bundle["report"]["no_submit"])
        self.assertEqual(len(bundle["report"]["next_actions_ranked"]), 5)
        self.assertIn(
            "W3b initial fit approval recorded: `False`",
            render_completion_markdown(bundle["completion"]),
        )

    def test_w3_completion_rejects_positive_population_claim_drift(self):
        completion = _w3_completion()
        completion["can_claim_population_level_independent_predictor_robustness"] = True
        with self.assertRaisesRegex(ValueError, "population_claim_false"):
            _refresh_current_w3b(completion=completion)

    def test_w3b_fit_ready_rejects_msa_hash_lock_drift(self):
        artifacts = list(_w3b_fit_ready_artifacts())
        artifacts[2]["targets"][0]["target_msa_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "target_and_msa_locks_match"):
            _refresh_current_w3b(artifacts=tuple(artifacts))

    def test_w3b_fit_ready_rejects_nonzero_submission(self):
        artifacts = list(_w3b_fit_ready_artifacts())
        artifacts[6]["submitted_jobs"] = 1
        with self.assertRaisesRegex(ValueError, "fit_packet_ready_no_submit"):
            _refresh_current_w3b(artifacts=tuple(artifacts))

    def test_w3b_initial_fit_failure_advances_to_separate_af2_recovery_gate(self):
        bundle = _refresh_current_w3b(recovery=_w3b_recovery_artifacts())

        self.assertEqual(
            bundle["report"]["status"],
            "goal_state_refreshed_w3_complete_w3b_af2_recovery_approval_wait",
        )
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_submitted"], 9)
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_completed"], 6)
        self.assertEqual(bundle["harness"]["hpc_status"]["jobs_failed"], 3)
        self.assertEqual(
            bundle["anchor"]["current_status"]["w3b_af2_recovery_jobs_submitted"],
            0,
        )
        self.assertFalse(
            bundle["anchor"]["current_status"]["w3b_af2_recovery_approval_recorded"]
        )
        self.assertIn("approve W3b AF2 fit recovery", bundle["report"]["next_action"])
        self.assertFalse(bundle["report"]["cayuga_submission_allowed"])
        self.assertFalse(bundle["report"]["w3b_successor"]["can_claim_w3b"])
        self.assertIn(
            "initial fit is incomplete",
            bundle["report"]["w3b_successor"]["claim_boundary"].lower(),
        )

    def test_w3b_af2_recovery_rejects_any_recorded_recovery_submission(self):
        recovery = list(_w3b_recovery_artifacts())
        recovery[2]["submitted_jobs"] = 1
        with self.assertRaisesRegex(ValueError, "recovery_packet_exact"):
            _refresh_current_w3b(recovery=tuple(recovery))

    def test_w3_mechanism_packet_fails_closed_on_case_count_drift(self):
        packet = _w3_mechanism_packet()
        packet["rows"].pop()
        with self.assertRaisesRegex(ValueError, "case_count_exact"):
            refresh_bundle(
                *_legacy_bundle(),
                _w2b(),
                _w2c(),
                w3_mechanism_packet=packet,
                updated_at="2026-07-14T15:00:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_threshold_learning_result_fails_closed_on_incomplete_qc(self):
        gate = _w2c()
        gate["execution_readiness"] = {
            "target_manifest_present": True,
            "target_manifest_integrity_ok": True,
            "target_manifest_ids": [f"fresh-{index}" for index in range(8)],
            "target_msa_ready": False,
            "evaluator_implemented": True,
        }
        result = _threshold_learning_result()
        result["qc"]["n_rows"] = 479
        with self.assertRaisesRegex(ValueError, "qc_complete"):
            refresh_bundle(
                *_legacy_bundle(),
                _w2b(),
                gate,
                _target_msa_packet(),
                _target_msa_completion(),
                _fit_learn_packet(),
                _fit_learn_submission(),
                result,
                updated_at="2026-07-14T14:30:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_executable_w2c_is_rejected(self):
        gate = _w2c()
        gate["cayuga_submission_allowed"] = True
        with self.assertRaisesRegex(ValueError, "W2c design-gate invariants"):
            refresh_bundle(
                *_legacy_bundle(),
                _w2b(),
                gate,
                updated_at="2026-07-12T12:00:00+09:00",
                test_command="pytest",
                test_result="passed",
            )

    def test_cli_bootstraps_optional_local_artifacts_in_public_checkout(self):
        with tempfile.TemporaryDirectory() as root:
            w2b_path = os.path.join(root, "w2b.json")
            w2c_path = os.path.join(root, "w2c.json")
            with open(w2b_path, "w") as handle:
                json.dump(_w2b(), handle)
            with open(w2c_path, "w") as handle:
                json.dump(_w2c(), handle)

            paths = {
                "anchor": os.path.join(root, "anchor.json"),
                "completion": os.path.join(root, "completion.json"),
                "completion_md": os.path.join(root, "completion.md"),
                "drift": os.path.join(root, "drift.json"),
                "drift_md": os.path.join(root, "drift.md"),
                "actions": os.path.join(root, "actions.json"),
                "actions_md": os.path.join(root, "actions.md"),
                "harness": os.path.join(root, "harness.json"),
                "harness_md": os.path.join(root, "harness.md"),
                "report": os.path.join(root, "refresh.json"),
                "report_md": os.path.join(root, "refresh.md"),
                "target_msa_packet": os.path.join(root, "missing-target-msa-packet.json"),
                "target_msa_completion": os.path.join(root, "missing-target-msa-completion.json"),
                "fit_learn_packet": os.path.join(root, "missing-fit-learn-packet.json"),
                "fit_learn_submission": os.path.join(root, "missing-fit-learn-submission.json"),
                "threshold_learning_result": os.path.join(
                    root, "missing-threshold-learning-result.json"
                ),
                "w3_completion": os.path.join(root, "missing-w3-completion.json"),
                "w3b_design_gate": os.path.join(root, "missing-w3b-design-gate.json"),
                "w3b_target_msa": os.path.join(root, "missing-w3b-target-msa.json"),
                "w3b_execution_manifest": os.path.join(
                    root, "missing-w3b-execution-manifest.json"
                ),
                "w3b_execution_input_lock": os.path.join(
                    root, "missing-w3b-execution-input-lock.json"
                ),
                "w3b_runtime": os.path.join(root, "missing-w3b-runtime.json"),
                "w3b_matched": os.path.join(root, "missing-w3b-matched.json"),
                "w3b_fit_readiness": os.path.join(root, "missing-w3b-fit-readiness.json"),
                "w3b_fit_approval": os.path.join(root, "missing-w3b-fit-approval.json"),
                "w3b_fit_submission": os.path.join(
                    root, "missing-w3b-fit-submission.json"
                ),
                "w3b_fit_observation": os.path.join(
                    root, "missing-w3b-fit-observation.json"
                ),
                "w3b_af2_recovery": os.path.join(
                    root, "missing-w3b-af2-recovery.json"
                ),
            }
            argv = [
                "--anchor", paths["anchor"],
                "--completion", paths["completion"],
                "--completion-md", paths["completion_md"],
                "--drift", paths["drift"],
                "--drift-md", paths["drift_md"],
                "--actions", paths["actions"],
                "--actions-md", paths["actions_md"],
                "--harness", paths["harness"],
                "--harness-md", paths["harness_md"],
                "--w2b-report", w2b_path,
                "--w2c-gate", w2c_path,
                "--w2c-target-msa-packet", paths["target_msa_packet"],
                "--w2c-target-msa-completion", paths["target_msa_completion"],
                "--w2c-fit-learn-packet", paths["fit_learn_packet"],
                "--w2c-fit-learn-submission-summary", paths["fit_learn_submission"],
                "--w2c-threshold-learning-report", paths["threshold_learning_result"],
                "--w3-mechanism-completion", paths["w3_completion"],
                "--w3b-design-gate", paths["w3b_design_gate"],
                "--w3b-target-msa-lifecycle", paths["w3b_target_msa"],
                "--w3b-execution-manifest", paths["w3b_execution_manifest"],
                "--w3b-execution-input-lock", paths["w3b_execution_input_lock"],
                "--w3b-runtime-readiness", paths["w3b_runtime"],
                "--w3b-matched-record-contract", paths["w3b_matched"],
                "--w3b-fit-packet-readiness", paths["w3b_fit_readiness"],
                "--w3b-fit-approval-packet", paths["w3b_fit_approval"],
                "--w3b-fit-submission-summary", paths["w3b_fit_submission"],
                "--w3b-fit-initial-execution-observation",
                paths["w3b_fit_observation"],
                "--w3b-fit-af2-recovery-packet", paths["w3b_af2_recovery"],
                "--updated-at", "2026-07-12T12:00:00+09:00",
                "--test-command", "pytest",
                "--test-result", "passed",
                "--out-json", paths["report"],
                "--out-md", paths["report_md"],
            ]

            self.assertEqual(main(argv), 0)
            for key, path in paths.items():
                if key in {
                    "target_msa_packet",
                    "target_msa_completion",
                    "fit_learn_packet",
                    "fit_learn_submission",
                    "threshold_learning_result",
                    "w3_completion",
                    "w3b_design_gate",
                    "w3b_target_msa",
                    "w3b_execution_manifest",
                    "w3b_execution_input_lock",
                    "w3b_runtime",
                    "w3b_matched",
                    "w3b_fit_readiness",
                    "w3b_fit_approval",
                    "w3b_fit_submission",
                    "w3b_fit_observation",
                    "w3b_af2_recovery",
                }:
                    continue
                self.assertTrue(os.path.exists(path), path)
            with open(paths["anchor"]) as handle:
                anchor = json.load(handle)
            self.assertEqual(anchor["current_status"]["w2c"], "w2c_design_power_qualified_no_submit")

            with open(paths["report"], "w") as handle:
                json.dump(
                    {
                        "artifact": "m6d_goal_state_refresh_report",
                        "w2c_threshold_learning_result": {
                            "status": "w2c_threshold_learning_terminal_not_supported",
                            "threshold_decisions_frozen": True,
                        },
                    },
                    handle,
                )
            with self.assertRaisesRegex(SystemExit, "2"):
                main(argv)


if __name__ == "__main__":
    unittest.main()
