"""Tests for project-level M6 complex roadmap status audit."""

import argparse
import hashlib
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_project_status import (
    attach_generated_script_syntax_audit,
    attach_goal_progress_audit,
    attach_pending_artifact_local_audit,
    attach_resume_bridge_preflight,
    attach_target_msa_precompute_receipt,
    attach_target_msa_precompute_script_validation_audit,
    _remote_missing_action,
    main,
    render_pending_external_paths,
    render_pending_input_prep_paths,
    render_text,
    run_status,
    _w3_runtime_probe_report_failures,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _alpha_decision_ready_report(target_alpha=0.2, n_records=500, n_cal=320):
    n_test = n_records - n_cal
    certified_alphas = [0.3] if abs(target_alpha - 0.3) > 1e-9 else []
    certified_alphas.append(target_alpha)
    return {
        "ok": True,
        "decision": "stop_certified",
        "target_alpha": target_alpha,
        "records": ["records_boltz_complex.jsonl"],
        "qc": {"ok": True, "n_failures": 0},
        "n_records": n_records,
        "n_cal": n_cal,
        "n_test": n_test,
        "delta": 0.1,
        "threshold": 4.0,
        "label_threshold_audit": {
            "ok": True,
            "expected_threshold": 4.0,
            "tolerance": 1e-9,
            "record_thresholds": [4.0],
            "n_records": n_records,
            "n_mismatches": 0,
            "examples": [],
        },
        "certified_alphas": certified_alphas,
        "target_sweep": {
            "alpha": target_alpha,
            "certified": True,
            "tau": 0.07142857142857142,
            "trusted": max(1, n_test // 3),
            "n_test": n_test,
            "false_accept_rate": min(0.05, target_alpha / 2),
            "trust_all_false_accept_rate": 0.5,
            "actions": {"trust_sfm": max(1, n_test // 3), "verify_assay": n_test - max(1, n_test // 3)},
        },
        "target_plan": {
            "alpha": target_alpha,
            "certified": True,
            "tau": 0.07142857142857142,
            "current_accepted": max(1, n_cal // 3),
            "current_false_accepts": 0,
            "current_empirical_false_accept_rate": 0.0,
            "current_hoeffding_ucb": min(0.05, target_alpha / 2),
            "required_accepted_for_same_rate": max(1, n_cal // 4),
            "estimated_required_calibration_records": n_cal,
            "estimated_required_total_records": n_records,
            "estimated_additional_records": 0,
        },
        "estimated_additional_records": 0,
        "next_batch": {
            "action": "none",
            "target_alpha": target_alpha,
            "recommended_total_candidates": 0,
            "message": "Target alpha is certified; broaden scope rather than scaling this same target.",
        },
        "failures": [],
        "message": "certified",
    }


def _panel_ready_report(n_targets=3, n_records_per_target=20, target_alpha=0.2):
    target_ids = [f"target_{i}" for i in range(n_targets)]
    return {
        "ok": True,
        "panel_status": "multi_target_certified",
        "target_alpha": target_alpha,
        "threshold": 4.0,
        "min_targets": 3,
        "min_records_per_target": n_records_per_target,
        "n_targets": n_targets,
        "n_records": n_targets * n_records_per_target,
        "predictors": ["boltz2_complex"],
        "signal_sources": ["boltz2_pae_interaction"],
        "label_sources": ["boltz2_lrmsd_to_reference"],
        "label_threshold_audit": {"ok": True, "expected_threshold": 4.0, "record_thresholds": [4.0]},
        "targets": [
            {
                "complex_target_id": target_id,
                "status": "certified",
                "certified": True,
                "n_records": n_records_per_target,
                "min_records_per_target": n_records_per_target,
                "tau": 0.08,
            }
            for target_id in target_ids
        ],
        "failures": [],
        "message": "panel ready",
    }


def _complete_goal_workstreams(evidence_dir, statuses=None):
    default_statuses = {
        "W1_M6c_scale_up": "certified",
        "W2_multi_target_panel": "multi_target_certified",
        "W3_independent_predictor": "cross_predictor_ready",
        "W4_closed_loop_DBTL": "closed_loop_round_complete",
    }
    statuses = dict(default_statuses if statuses is None else statuses)
    workstreams = {}
    for key, status in statuses.items():
        evidence = os.path.join(evidence_dir, f"{key}.json")
        payload = {"ok": True, "status": status}
        if key == "W1_M6c_scale_up" and status == "certified":
            payload.update(_alpha_decision_ready_report())
        if key == "W2_multi_target_panel" and status == "multi_target_certified":
            payload.update(_panel_ready_report(n_records_per_target=1))
        if key == "W3_independent_predictor" and status == "cross_predictor_ready":
            payload.update(_cross_predictor_ready_report(n=1))
        if key == "W4_closed_loop_DBTL" and status == "closed_loop_round_complete":
            payload.update({"gate_calibrated": True, "aggregate": {"n": 1}})
        _write_json(evidence, payload)
        workstreams[key] = {
            "complete": True,
            "status": status,
            "evidence": evidence,
            "next_action": "done",
        }
        if key == "W4_closed_loop_DBTL" and status == "closed_loop_round_complete":
            preflight = os.path.join(evidence_dir, "W4_closed_loop_DBTL.preflight.json")
            campaign = os.path.join(evidence_dir, "W4_closed_loop_DBTL.campaign.jsonl")
            _write_json(preflight, {"ok": True, "strict_complex_records": True})
            _write_jsonl(campaign, [{"candidate_id": "c0", "action": "verify_assay"}])
            workstreams[key].update({
                "preflight": preflight,
                "summary": evidence,
                "campaign": campaign,
            })
    return workstreams


def _posthoc_science_claims_ok():
    return {
        "posthoc_science_claims": {
            "source": "posthoc_manifest",
            "report_json": "m6c_report.json",
            "supported": ["complex_pae_interaction_signal", "alpha_0_3_rcps_certificate"],
            "not_yet_supported": [
                "target_alpha_0_2_certificate",
                "multi_target_generalization",
                "independent_predictor_robustness",
            ],
            "planning_diagnostics": ["scale_projection_alpha_0_2"],
            "decisive_next": ["scale_barnase_barstar_alpha_0_2", "multi_target_panel", "second_predictor"],
        },
        "posthoc_science_claims_audit": {"ok": True, "status": "ok"},
    }


def _sync_manifest(kind, sync_script, paths):
    text = "\n".join(paths) + ("\n" if paths else "")
    manifest_file = os.path.splitext(sync_script)[0] + ".manifest.json"
    return {
        "kind": kind,
        "manifest_file": manifest_file,
        "n_paths": len(paths),
        "paths": paths,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "sync_script": sync_script,
    }


def _remote_path_manifest(path_file, paths_text):
    paths = [line for line in paths_text.splitlines() if line.strip()]
    return {
        "kind": "pending_external_paths",
        "path_file": path_file,
        "manifest_file": os.path.splitext(path_file)[0] + ".manifest.json",
        "expected_n_paths": len(paths),
        "expected_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
    }


def _gate_prevalidation():
    return {
        "requested": True,
        "ok": True,
        "paths": ["prior_records.jsonl"],
        "n_records": 128,
        "conformal_alpha": 0.3,
        "conformal_delta": 0.1,
        "regimes": {
            "complex": {
                "n": 128,
                "n_wrong": 52,
                "validated": True,
                "tau": 0.071,
            },
        },
        "batch_contract": {
            "checked": True,
            "ok": True,
            "tolerance": 1e-9,
            "fields": ["predictor_id", "signal_source", "label_source", "lrmsd_threshold"],
            "regimes": {
                "complex": {
                    "ok": True,
                    "n_prevalidation": 128,
                    "n_batch": 4,
                    "fields": {
                        "predictor_id": {
                            "single_value_agree": True,
                            "prevalidation": {"values": ["boltz2_complex"], "missing": 0, "complete": True},
                            "batch": {"values": ["boltz2_complex"], "missing": 0, "complete": True},
                        },
                        "signal_source": {
                            "single_value_agree": True,
                            "prevalidation": {"values": ["boltz2_pae_interaction"], "missing": 0, "complete": True},
                            "batch": {"values": ["boltz2_pae_interaction"], "missing": 0, "complete": True},
                        },
                        "label_source": {
                            "single_value_agree": True,
                            "prevalidation": {"values": ["boltz2_lrmsd_to_reference"], "missing": 0, "complete": True},
                            "batch": {"values": ["boltz2_lrmsd_to_reference"], "missing": 0, "complete": True},
                        },
                        "lrmsd_threshold": {
                            "single_value_agree": True,
                            "tolerance": 1e-9,
                            "prevalidation": {"values": [4.0], "missing": 0, "complete": True},
                            "batch": {"values": [4.0], "missing": 0, "complete": True},
                        },
                    },
                },
            },
            "failures": [],
        },
        "failures": [],
    }


def _cross_predictor_ready_report(n=100, min_overlap=None, min_label_agreement=0.8):
    min_overlap = n if min_overlap is None else min_overlap
    return {
        "ok": True,
        "status": "cross_predictor_ready",
        "predictors": ["boltz2_complex", "chai1_complex"],
        "records_by_predictor": {"boltz2_complex": n, "chai1_complex": n},
        "min_overlap": min_overlap,
        "min_label_agreement": min_label_agreement,
        "require_disjoint_record_files": True,
        "record_files": [
            {
                "path": "boltz.jsonl",
                "n_records": n,
                "n_blank": 0,
                "predictors": ["boltz2_complex"],
                "records_by_predictor": {"boltz2_complex": n},
            },
            {
                "path": "chai.jsonl",
                "n_records": n,
                "n_blank": 0,
                "predictors": ["chai1_complex"],
                "records_by_predictor": {"chai1_complex": n},
            },
        ],
        "pairs": [
            {
                "predictor_a": "boltz2_complex",
                "predictor_b": "chai1_complex",
                "n_overlap": n,
                "n_labeled_overlap": n,
                "meets_min_overlap": n >= min_overlap,
                "meets_min_labeled_overlap": n >= min_overlap,
                "label_agreement": 1.0,
                "min_label_agreement": min_label_agreement,
                "meets_min_label_agreement": True,
                "n_provenance_overlap": n,
                "provenance_complete": True,
                "n_complex_target_id_overlap": n,
                "complex_target_id_complete": True,
                "complex_target_id_agree": True,
                "n_label_threshold_overlap": n,
                "label_threshold_complete": True,
                "label_threshold_agree": True,
                "distinct_signal_sources": True,
                "distinct_label_sources": True,
                "copied_numeric_values": False,
            },
        ],
        "failures": [],
    }


def _w3_negative_decision_protocol(adjudication_jsonl=None, adjudication_sha256=None):
    artifact = {
        "n_rows": 2,
        "out_jsonl": adjudication_jsonl or "results/m6d_w3_adjudication_set.jsonl",
        "out_jsonl_sha256": adjudication_sha256 or "abc123",
        "out_summary": "results/m6d_w3_adjudication_set.json",
        "counts_by_role": {
            "discordant_boltz_chai_label": 1,
            "concordant_success_control": 1,
        },
        "target_ids_by_role": {
            "discordant_boltz_chai_label": ["d1"],
            "concordant_success_control": ["c1"],
        },
    }
    return {
        "artifact": "m6d_w2_w3_decision_protocol",
        "overall_status": "w2_w3_decision_protocol_selected_goal_still_active",
        "can_mark_goal_complete": False,
        "w3": {
            "status": "protocol_selected",
            "claim_boundary": "independent_predictor_robustness_not_supported",
            "current_protocol_verdict": "negative_robustness_result_for_no_msa_chai",
            "selected_protocol": "adjudicated_disagreement_protocol_v1",
            "strict_adjudication_integrity": True,
            "strict_adjudication_integrity_blockers": [],
            "cross_predictor_failure_kinds": ["label_agreement_below_min"],
            "label_agreement": 0.6,
            "min_label_agreement": 0.8,
            "matched_overlap": 30,
            "adjudication_set": {
                "discordant_target_ids": ["d1"],
                "concordant_success_control_ids": ["c1"],
            },
            "adjudication_set_artifact": artifact,
            "protocol_rules": [
                "treat the completed no-MSA Chai comparison as a negative robustness result under that protocol",
                "do not close the single-predictor caveat from Chai records alone",
            ],
            "next_spend_gate": "do not rerun no-MSA Chai; use the adjudication set before any future W3 spend",
        },
    }


def _w3_next_protocol(adjudication_jsonl, adjudication_sha256, *, claim=False):
    return {
        "artifact": "m6d_w3_next_protocol",
        "status": "w3_next_protocol_ready_no_spend",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "can_claim_independent_predictor_robustness_now": claim,
        "positive_claim_supported": False,
        "current_w3_result": {
            "status": "negative_robustness_result_adjudicated",
            "verdict": "negative_robustness_result_for_no_msa_chai",
            "claim_boundary": "independent_predictor_robustness_not_supported",
            "label_agreement": 0.6,
            "min_label_agreement": 0.8,
            "matched_overlap": 30,
        },
        "adjudication_set_contract": {
            "jsonl": adjudication_jsonl,
            "jsonl_sha256": adjudication_sha256,
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "required_counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
        },
        "recommended_next_routes": [
            {"rank": 1, "route": "third_independent_predictor_or_protocol"},
            {"rank": 2, "route": "stronger_chai_msa_template_protocol"},
        ],
        "decision_contract": {
            "discordant_rows": 1,
            "concordant_success_controls": 1,
            "discordant_alignment_threshold": 1,
            "control_consistency_threshold": 1,
        },
        "recommended_next_action": "Prepare a third independent predictor/protocol run on the pinned set.",
    }


def _w3_challenge_manifest(adjudication_jsonl, adjudication_sha256, *, execution_ready=False):
    return {
        "artifact": "m6d_w3_challenge_manifest",
        "status": "w3_challenge_manifest_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": execution_ready,
        "can_claim_independent_predictor_robustness_now": False,
        "source_adjudication_jsonl": adjudication_jsonl,
        "source_adjudication_sha256": adjudication_sha256,
        "challenge_panel": {
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "target_ids": ["d1", "c1"],
        },
        "source_record_audit": [
            {
                "path": "boltz.jsonl",
                "exists": True,
                "n_records": 2,
                "selected_seen": 2,
                "missing_selected_target_ids": [],
                "predictor_ids": ["boltz2_complex"],
            },
            {
                "path": "chai.jsonl",
                "exists": True,
                "n_records": 2,
                "selected_seen": 2,
                "missing_selected_target_ids": [],
                "predictor_ids": ["chai1_complex"],
            },
        ],
        "recommended_next_route": "third_independent_predictor_or_protocol",
        "execution_blockers": [
            "third predictor/protocol implementation is not selected in this manifest",
            "explicit approval is required before any API/GPU/HPC execution",
        ],
    }


def _w3_third_predictor_contract(challenge_path, challenge_sha256, *, execution_ready=False,
                                 command_wrapper_emitted=False, claim=False):
    return {
        "artifact": "m6d_w3_third_predictor_contract",
        "status": "w3_third_predictor_contract_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": execution_ready,
        "command_wrapper_emitted": command_wrapper_emitted,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "source_challenge_manifest": challenge_path,
        "source_challenge_manifest_sha256": challenge_sha256,
        "challenge_panel_contract": {
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "target_ids": ["d1", "c1"],
        },
        "predictor_selection_contract": {
            "route": "third_independent_predictor_or_protocol",
            "required_selection_fields": [
                "predictor_or_protocol_id",
                "version",
                "approval_gate",
            ],
        },
        "output_contract": {
            "planned_jsonl": "results/m6d_w3_third_predictor_challenge_records.jsonl",
            "required_n_rows": 2,
            "required_target_ids": ["d1", "c1"],
            "required_result_schema": ["target_id", "predictor_or_protocol_id", "label", "provenance"],
        },
        "future_artifacts_required": [
            "selected_predictor_protocol_card",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
        ],
        "execution_blockers": [
            "third predictor/protocol implementation has not been selected",
            "approval-gated command wrapper is not emitted by this contract",
        ],
    }


def _w3_predictor_selection_card(third_contract_path, third_contract_sha256, *,
                                 runtime_ready=False, execution_ready=False, claim=False):
    return {
        "artifact": "m6d_w3_predictor_selection_card",
        "status": "w3_predictor_selection_card_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "runtime_ready": runtime_ready,
        "execution_ready": execution_ready,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "source_third_predictor_contract": third_contract_path,
        "source_third_predictor_contract_sha256": third_contract_sha256,
        "selected_predictor_protocol": {
            "predictor_or_protocol_id": "af2_multimer_colabfold_v1",
            "model_or_protocol_family": "AlphaFold2-Multimer via ColabFold/localcolabfold",
            "version": "runtime_version_pending_cayuga_probe",
            "msa_policy": "paired/unpaired MMseqs2 MSA required",
            "template_policy": "templates disabled unless predeclared",
            "runtime_environment": "Cayuga colabfold/localcolabfold environment pending install/probe",
            "label_source": "af2_multimer_lrmsd_to_reference",
            "signal_source": "af2_multimer_pae_interaction_or_iptm",
            "approval_gate": "BIO_SFM_APPROVE_W3_THIRD_PREDICTOR=approve-w3-third-predictor-submit",
            "route": "third_independent_predictor_or_protocol",
            "selection_status": "selected_pending_runtime_probe",
            "required_fields_satisfied": [
                "predictor_or_protocol_id",
                "model_or_protocol_family",
                "version",
                "msa_policy",
                "template_policy",
                "runtime_environment",
                "label_source",
                "signal_source",
                "approval_gate",
            ],
        },
        "runtime_probe_required": {"required": True, "checks": ["colabfold_batch --help"]},
        "future_artifacts_required": [
            "execution_input_manifest",
            "approval_gated_command_wrapper",
        ],
        "execution_blockers": [
            "runtime has not been probed",
            "approval-gated command wrapper is not emitted here",
        ],
    }


def _w3_runtime_probe_plan(selection_path, selection_sha256, *,
                           probe_executed=False, runtime_ready=False,
                           execution_ready=False, claim=False):
    return {
        "artifact": "m6d_w3_runtime_probe_plan",
        "status": "w3_runtime_probe_plan_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "runtime_probe_ready": False,
        "runtime_ready": runtime_ready,
        "probe_executed": probe_executed,
        "execution_ready": execution_ready,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "source_predictor_selection_card": selection_path,
        "source_predictor_selection_card_sha256": selection_sha256,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "selected_model_or_protocol_family": "AlphaFold2-Multimer via ColabFold/localcolabfold",
        "probe_contract": {
            "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
            "runtime_surface": "Cayuga AF2-Multimer/ColabFold runtime probe",
            "target_partition_candidates": ["scu-gpu", "gpu partition pending probe"],
            "candidate_runtime_locations": [
                "$HOME/localcolabfold/.pixi/envs/default/bin/colabfold_batch",
                "$HOME/.conda/envs/colabfold/bin/colabfold_batch",
                "colabfold_batch on PATH",
            ],
            "target_count": 2,
            "target_ids": ["d1", "c1"],
            "checks": [
                {"kind": "env_discovery", "status": "planned_not_executed"},
                {"kind": "cli_help", "status": "planned_not_executed"},
                {"kind": "gpu_stack", "status": "planned_not_executed"},
                {"kind": "msa_policy", "status": "planned_not_executed"},
                {"kind": "dry_run_enumeration", "status": "planned_not_executed"},
            ],
        },
        "future_artifacts_required": [
            "runtime_probe_report",
            "execution_input_manifest",
            "approval_gated_command_wrapper",
        ],
        "execution_blockers": [
            "runtime probe has not been executed",
            "execution input FASTA/MSA manifest is not emitted here",
            "approval-gated command wrapper is not emitted here",
        ],
        "recommended_next_action": (
            "Run and record a no-submit runtime probe report only after choosing the probe surface; "
            "do not submit jobs or query external services."
        ),
    }


def _w3_runtime_probe_report(plan_path, plan_sha256, *,
                             probe_surface="local_static_no_submit",
                             runtime_ready=False, execution_ready=False,
                             claim=False):
    status = (
        "w3_runtime_probe_report_runtime_ready_no_submit"
        if runtime_ready else
        "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit"
    )
    return {
        "artifact": "m6d_w3_runtime_probe_report",
        "status": status,
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "probe_surface": probe_surface,
        "probe_executed": True,
        "cayuga_probe_executed": probe_surface.startswith("cayuga_"),
        "runtime_ready": runtime_ready,
        "execution_ready": execution_ready,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "source_runtime_probe_plan": plan_path,
        "source_runtime_probe_plan_sha256": plan_sha256,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "target_count": 2,
        "observed_checks": [
            {"kind": "env_discovery", "ran": True, "ok": runtime_ready},
            {"kind": "cli_help", "ran": runtime_ready, "ok": runtime_ready},
            {"kind": "gpu_stack", "ran": runtime_ready, "ok": runtime_ready},
            {"kind": "msa_policy", "ran": True, "ok": True},
            {"kind": "dry_run_enumeration", "ran": True, "ok": True, "n_inputs": 2},
        ],
        "readiness_blockers": [] if runtime_ready else [
            "probe surface is not the target Cayuga GPU no-submit surface",
            "cli_help check is not ok",
            "gpu_stack check is not ok",
        ],
        "future_artifacts_required": [
            "execution_input_manifest",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
        ],
        "recommended_next_action": (
            "generate the no-submit execution-input manifest for the 18-row W3 challenge panel"
            if runtime_ready else
            "run the no-submit runtime probe on the target Cayuga GPU surface before generating execution inputs"
        ),
    }


def _w3_runtime_repair_plan(report_path, report_sha256, *,
                            runtime_ready=False, claim=False):
    return {
        "artifact": "m6d_w3_runtime_repair_plan",
        "status": "w3_runtime_repair_plan_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "prediction_executed": False,
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "source_runtime_probe_report": report_path,
        "source_runtime_probe_report_sha256": report_sha256,
        "source_cayuga_runtime_repair_discovery": "/tmp/discovery.json",
        "source_cayuga_runtime_repair_discovery_sha256": "dummy",
        "failed_runtime_checks": ["cli_help", "env_discovery", "gpu_stack"],
        "passed_runtime_checks": ["dry_run_enumeration", "msa_policy"],
        "repair_items": [
            {"id": "provision_colabfold_cli", "status": "required"},
            {"id": "provision_jax_cuda_runtime", "status": "required"},
            {"id": "rerun_gpu_check_on_actual_gpu_surface", "status": "required_after_runtime_install"},
        ],
        "next_action": (
            "provision a W3-specific ColabFold/JAX CUDA runtime, then rerun the existing no-submit "
            "Cayuga runtime probe before generating execution inputs"
        ),
    }


def _w3_runtime_provision_packet(repair_path, repair_sha256, *,
                                 runtime_ready=False, install=False, claim=False):
    return {
        "artifact": "m6d_w3_runtime_provision_packet",
        "status": "w3_runtime_provision_packet_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "network_fetch_emitted": False,
        "install_executed": install,
        "provision_validation_executed": False,
        "prediction_executed": False,
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "approval_env_var": "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION",
        "approval_env_value": "approve-w3-runtime-provision",
        "source_runtime_repair_plan": repair_path,
        "source_runtime_repair_plan_sha256": repair_sha256,
        "script": "results/m6d_w3_runtime_provision_colabfold_guarded.sh",
        "receipt": "results/m6d_w3_runtime_provision_receipt.json",
        "static_script_audit": {"ok": True, "failures": []},
        "next_action": (
            "stage or provide an existing ColabFold runtime through W3_COLABFOLD_BIN or W3_COLABFOLD_SIF, "
            "then run this guarded validation script only with explicit approval"
        ),
    }


class ComplexProjectStatusTests(unittest.TestCase):
    def test_missing_artifacts_report_next_actions(self):
        rep = run_status()
        self.assertFalse(rep["complete"])
        self.assertEqual(rep["status"], "m6_complex_in_progress")
        self.assertEqual(rep["workstreams"]["W1_M6c_scale_up"]["status"], "missing")
        self.assertEqual(rep["workstreams"]["W2_multi_target_panel"]["status"], "missing")
        self.assertEqual(rep["workstreams"]["W3_independent_predictor"]["status"], "missing")
        self.assertEqual(rep["workstreams"]["W4_closed_loop_DBTL"]["status"], "missing")
        self.assertIn("complex_posthoc_bundle", rep["next_action"])

    def test_reads_decision_from_posthoc_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
                "estimated_additional_records": 260,
                "next_batch": {"action": "run_scale_batch", "recommended_total_candidates": 300},
                "message": "needs more records",
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "records_paths": [os.path.join(d, "records.jsonl")],
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [
                        {"id": "complex_pae_interaction_signal"},
                        {"id": "alpha_0_3_rcps_certificate"},
                    ],
                    "not_yet_supported": [
                        {"id": "target_alpha_0_2_certificate"},
                        {"id": "multi_target_generalization"},
                    ],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "records": [os.path.join(d, "records.jsonl")],
                "paths": {
                    "decision": decision,
                    "report_json": report,
                },
                "summary": {
                    "n_records": 192,
                    "science_claims_supported": [
                        "complex_pae_interaction_signal",
                        "alpha_0_3_rcps_certificate",
                    ],
                    "science_claims_not_yet_supported": [
                        "target_alpha_0_2_certificate",
                        "multi_target_generalization",
                    ],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_status(posthoc_manifest_path=manifest)
        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "continue_scale")
        self.assertEqual(w1["estimated_additional_records"], 260)
        self.assertEqual(w1["next_batch"]["action"], "run_scale_batch")
        self.assertIn("next scale batch", w1["next_action"])
        self.assertEqual(rep["posthoc_science_claims"]["supported"], [
            "complex_pae_interaction_signal",
            "alpha_0_3_rcps_certificate",
        ])
        self.assertEqual(rep["posthoc_science_claims"]["not_yet_supported"], [
            "target_alpha_0_2_certificate",
            "multi_target_generalization",
        ])
        self.assertEqual(rep["posthoc_science_claims"]["planning_diagnostics"], [
            "scale_projection_alpha_0_2",
        ])
        self.assertEqual(rep["posthoc_science_claims"]["decisive_next"], [
            "scale_barnase_barstar_alpha_0_2",
        ])
        self.assertTrue(rep["posthoc_science_claims_audit"]["ok"])
        self.assertEqual(rep["posthoc_science_claims_audit"]["status"], "ok")
        text = render_text(rep)
        self.assertIn("posthoc_science_claims=", text)
        self.assertIn("target_alpha_0_2_certificate", text)

    def test_posthoc_report_path_can_fall_back_to_repo_relative_results_path(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                os.makedirs(os.path.join(d, "results", "posthoc"), exist_ok=True)
                os.makedirs(os.path.join(d, "hpc_outputs"), exist_ok=True)
                manifest = os.path.join(d, "results", "posthoc", "manifest.json")
                report = os.path.join(d, "results", "posthoc", "m6c_report.json")
                records = os.path.join(d, "hpc_outputs", "posthoc_records.jsonl")
                stale_abs_report = "/old/machine/bio_sfm_designer/results/posthoc/m6c_report.json"
                stale_abs_records = "/old/machine/bio_sfm_designer/hpc_outputs/posthoc_records.jsonl"
                _write_jsonl(records, [{"record_id": "r1"}])
                _write_json(report, {
                    "dataset": {"n": 10},
                    "records_paths": [stale_abs_records],
                    "target_alpha": 0.2,
                    "science_claims": {
                        "supported": [{"id": "complex_pae_interaction_signal"}],
                        "not_yet_supported": [{"id": "multi_target_generalization"}],
                        "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                        "decisive_next_experiments": [{"id": "multi_target_panel"}],
                    },
                })
                _write_json(manifest, {
                    "records": [records],
                    "paths": {"report_json": stale_abs_report},
                    "summary": {
                        "n_records": 10,
                        "science_claims_supported": ["complex_pae_interaction_signal"],
                        "science_claims_not_yet_supported": ["multi_target_generalization"],
                        "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                        "science_claims_decisive_next": ["multi_target_panel"],
                    },
                })

                rep = run_status(posthoc_manifest_path=manifest, target_alpha=0.2)
            finally:
                os.chdir(cwd)

        audit = rep["posthoc_science_claims_audit"]
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(os.path.realpath(audit["report_json"]), os.path.realpath(report))

    def test_posthoc_science_claim_mismatch_blocks_goal_progress(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
                "estimated_additional_records": 260,
                "next_batch": {"action": "run_scale_batch", "recommended_total_candidates": 300},
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "science_claims_supported": [
                        "complex_pae_interaction_signal",
                        "alpha_0_3_rcps_certificate",
                    ],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_status(posthoc_manifest_path=manifest)
            attach_goal_progress_audit(rep)

        self.assertFalse(rep["posthoc_science_claims_audit"]["ok"])
        self.assertEqual(rep["posthoc_science_claims_audit"]["status"], "claim_summary_mismatch")
        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertEqual(audit["local_blockers"][0]["kind"], "posthoc_science_claims_audit")
        self.assertEqual(audit["local_blockers"][0]["status"], "claim_summary_mismatch")

    def test_posthoc_science_report_alpha_mismatch_blocks_goal_progress(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
                "estimated_additional_records": 260,
                "next_batch": {"action": "run_scale_batch", "recommended_total_candidates": 300},
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "target_alpha": 0.3,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "science_claims_supported": ["complex_pae_interaction_signal"],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_status(posthoc_manifest_path=manifest, target_alpha=0.2)
            attach_goal_progress_audit(rep)

        audit = rep["posthoc_science_claims_audit"]
        self.assertFalse(audit["ok"])
        self.assertEqual(audit["status"], "report_target_alpha_mismatch")
        self.assertEqual(audit["target_alpha"], 0.2)
        self.assertEqual(audit["report_target_alpha"], 0.3)
        goal_audit = rep["goal_progress_audit"]
        self.assertEqual(goal_audit["status"], "local_replay_or_regeneration_required")
        self.assertEqual(goal_audit["local_blockers"][0]["kind"], "posthoc_science_claims_audit")
        self.assertEqual(goal_audit["local_blockers"][0]["status"], "report_target_alpha_mismatch")

    def test_posthoc_science_report_record_count_mismatch_blocks_goal_progress(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
                "estimated_additional_records": 260,
                "next_batch": {"action": "run_scale_batch", "recommended_total_candidates": 300},
            })
            _write_json(report, {
                "dataset": {"n": 96},
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "n_records": 192,
                    "science_claims_supported": ["complex_pae_interaction_signal"],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_status(posthoc_manifest_path=manifest, target_alpha=0.2)
            attach_goal_progress_audit(rep)

        audit = rep["posthoc_science_claims_audit"]
        self.assertFalse(audit["ok"])
        self.assertEqual(audit["status"], "report_n_records_mismatch")
        self.assertEqual(audit["manifest_n_records"], 192)
        self.assertEqual(audit["report_n_records"], 96)
        goal_audit = rep["goal_progress_audit"]
        self.assertEqual(goal_audit["status"], "local_replay_or_regeneration_required")
        self.assertEqual(goal_audit["local_blockers"][0]["kind"], "posthoc_science_claims_audit")
        self.assertEqual(goal_audit["local_blockers"][0]["status"], "report_n_records_mismatch")

    def test_posthoc_science_report_record_path_mismatch_blocks_goal_progress(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            manifest_records = os.path.join(d, "records.jsonl")
            report_records = os.path.join(d, "other_records.jsonl")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
                "estimated_additional_records": 260,
                "next_batch": {"action": "run_scale_batch", "recommended_total_candidates": 300},
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "records_paths": [report_records],
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "records": [manifest_records],
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "n_records": 192,
                    "science_claims_supported": ["complex_pae_interaction_signal"],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_status(posthoc_manifest_path=manifest, target_alpha=0.2)
            attach_goal_progress_audit(rep)

        audit = rep["posthoc_science_claims_audit"]
        self.assertFalse(audit["ok"])
        self.assertEqual(audit["status"], "report_records_paths_mismatch")
        self.assertEqual(audit["manifest_records"], [manifest_records])
        self.assertEqual(audit["report_records_paths"], [report_records])
        goal_audit = rep["goal_progress_audit"]
        self.assertEqual(goal_audit["status"], "local_replay_or_regeneration_required")
        self.assertEqual(goal_audit["local_blockers"][0]["kind"], "posthoc_science_claims_audit")
        self.assertEqual(goal_audit["local_blockers"][0]["status"], "report_records_paths_mismatch")

    def test_w1_label_threshold_mismatch_is_blocked_status(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            _write_json(decision, {
                "ok": False,
                "decision": "label_threshold_mismatch",
                "target_alpha": 0.2,
                "label_threshold_audit": {
                    "ok": False,
                    "expected_threshold": 4.0,
                    "record_thresholds": [4.0, 5.0],
                    "n_mismatches": 1,
                },
                "next_batch": {"action": "fix_label_threshold"},
                "message": "Record lrmsd_threshold metadata must match the alpha-analysis threshold.",
            })

            rep = run_status(decision_path=decision)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "label_threshold_mismatch")
        self.assertFalse(w1["complete"])
        self.assertEqual(w1["next_batch"]["action"], "fix_label_threshold")
        self.assertFalse(w1["label_threshold_audit"]["ok"])

    def test_w1_certified_status_requires_strict_alpha_decision_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            _write_json(decision, {
                "ok": True,
                "decision": "stop_certified",
                "target_alpha": 0.2,
                "n_records": 500,
                "certified_alphas": [0.2],
            })

            rep = run_status(decision_path=decision)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "alpha_decision_audit_failed")
        self.assertFalse(w1["complete"])
        self.assertIn("complex_alpha_decision.py", w1["next_action"])
        kinds = {failure["kind"] for failure in w1["audit_failures"]}
        self.assertIn("alpha_decision_n_cal_invalid", kinds)
        self.assertIn("alpha_decision_qc_invalid", kinds)
        self.assertIn("alpha_decision_target_sweep_missing", kinds)

    def test_target_manifest_ready_without_panel_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            _write_json(target_manifest, {
                "ok": True,
                "n_targets": 3,
                "n_ready_targets": 3,
                "failures": [],
            })
            rep = run_status(target_manifest_path=target_manifest)
        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "targets_ready_no_panel")
        self.assertFalse(w2["complete"])
        self.assertEqual(w2["n_ready_targets"], 3)
        self.assertIn("complex_panel_completion", w2["next_action"])

    def test_target_manifest_waiting_on_msa_artifacts_is_input_prep_status(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "target_fasta_report_missing_field", "field": "target_fasta_report", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t2"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t2"},
                ],
                "input_prep_artifacts": [
                    {"target_id": "t1", "field": "target_msa_report", "path": "t1.a3m.report.json"},
                ],
            })

            rep = run_status(target_manifest_path=target_manifest)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_waiting_on_input_prep")
        self.assertEqual(w2["n_targets"], 3)
        self.assertEqual(w2["input_prep_artifacts"][0]["path"], "t1.a3m.report.json")
        self.assertIn("target_msa_precompute", w2["next_action"])

    def test_input_prep_completion_blocked_refines_w2_manifest_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            input_prep = os.path.join(d, "input_prep_completion.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1"},
                ],
            })
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 7,
                "n_present": 5,
                "n_nonempty": 5,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": "t1.a3m"},
                ],
                "artifacts_by_target": {
                    "t1": {
                        "n_artifacts": 7,
                        "n_present": 5,
                        "n_nonempty": 5,
                        "n_missing": 2,
                        "n_empty": 0,
                        "pending_fields": ["target_msa"],
                        "ready": False,
                    },
                },
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": "t1.a3m"},
                ],
                "next_action": "sync/fix missing or empty input-prep artifacts before rerunning --require-files",
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })

            rep = run_status(
                target_manifest_path=target_manifest,
                input_prep_completion_path=input_prep,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_input_prep_completion_blocked")
        self.assertEqual(w2["n_missing"], 2)
        self.assertEqual(w2["blocked_targets"], ["t1"])
        self.assertEqual(w2["pending_artifacts"][0]["field"], "target_msa")
        self.assertFalse(w2["artifacts_by_target"]["t1"]["ready"])
        self.assertEqual(w2["failures"][0]["field"], "target_msa")
        self.assertIn("sync/fix", w2["next_action"])
        self.assertIn("complex_target_manifest", w2["manifest_command"])
        self.assertEqual(w2["superseded_target_manifest_status"], "panel_waiting_on_input_prep")

    def test_input_prep_completion_ready_points_w2_to_manifest_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            input_prep = os.path.join(d, "input_prep_completion.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1"},
                ],
            })
            _write_json(input_prep, {
                "ok": True,
                "status": "ready_for_require_files",
                "n_artifacts": 7,
                "n_present": 7,
                "n_nonempty": 7,
                "n_missing": 0,
                "n_empty": 0,
                "ready_targets": ["t1"],
                "blocked_targets": [],
                "pending_artifacts": [],
                "artifacts_by_target": {
                    "t1": {
                        "n_artifacts": 7,
                        "n_present": 7,
                        "n_nonempty": 7,
                        "n_missing": 0,
                        "n_empty": 0,
                        "pending_fields": [],
                        "ready": True,
                    },
                },
                "failures": [],
                "next_action": "run manifest_command",
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })

            rep = run_status(
                target_manifest_path=target_manifest,
                input_prep_completion_path=input_prep,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_input_prep_ready_for_manifest")
        self.assertEqual(w2["n_nonempty"], 7)
        self.assertEqual(w2["ready_targets"], ["t1"])
        self.assertEqual(w2["pending_artifacts"], [])
        self.assertIn("manifest_command", w2["next_action"])
        self.assertIn("--require-files", w2["manifest_command"])

    def test_target_manifest_non_msa_failure_stays_failed(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "prepared_pdb", "target_id": "t1"},
                ],
            })

            rep = run_status(target_manifest_path=target_manifest)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_manifest_failed")
        self.assertIn("fix target manifest", w2["next_action"])

    def test_scale_completion_ready_overrides_continue_scale_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            completion = os.path.join(d, "scale_completion.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "next_batch": {"action": "run_scale_batch"},
            })
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_posthoc",
                "target_alpha": 0.2,
                "expected_new_records": ["/tmp/new.jsonl"],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records old new",
            })

            rep = run_status(decision_path=decision, scale_completion_path=completion)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "scale_records_ready_for_posthoc")
        self.assertIn("posthoc", w1["next_action"])
        self.assertIn("complex_posthoc_bundle", w1["posthoc_command"])

    def test_consumed_scale_completion_keeps_latest_continue_scale_decision(self):
        with tempfile.TemporaryDirectory() as d:
            old_records = os.path.abspath(os.path.join(d, "old_records.jsonl"))
            new_records = os.path.abspath(os.path.join(d, "new_records.jsonl"))
            decision = os.path.join(d, "decision.json")
            completion = os.path.join(d, "scale_completion.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 2,
                "records": [old_records, new_records],
                "next_batch": {"action": "run_scale_batch"},
            })
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_posthoc",
                "target_alpha": 0.2,
                "expected_records": [old_records, new_records],
                "expected_new_records": [new_records],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records old new",
            })

            rep = run_status(decision_path=decision, scale_completion_path=completion)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "continue_scale")
        self.assertIn("next scale", w1["next_action"])
        self.assertEqual(w1["n_records"], 2)

    def test_scale_plan_unavailable_surfaces_input_prep_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "scale_completion.json")
            _write_json(completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "action": "unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "waiting_on_input_prep",
                "next_action": "run input prep first",
                "failures": [{
                    "role": "scale_plan",
                    "path": "results/m6c_next_batch_1BRS_AD.json",
                    "error": "waiting_on_input_prep",
                }],
            })

            rep = run_status(scale_completion_path=completion, target_alpha=0.2)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "scale_waiting_on_input_prep")
        self.assertEqual(w1["next_action"], "run input prep first")
        self.assertEqual(w1["source_status"], "waiting_on_input_prep")
        self.assertEqual(w1["failures"][0]["error"], "waiting_on_input_prep")

    def test_input_prep_completion_refines_w1_scale_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "scale_completion.json")
            input_prep = os.path.join(d, "input_prep_completion.json")
            _write_json(completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "action": "unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "waiting_on_input_prep",
                "next_action": "run input prep first",
                "failures": [{
                    "role": "scale_plan",
                    "path": "results/m6c_next_batch_1BRS_AD.json",
                    "error": "waiting_on_input_prep",
                }],
            })
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 7,
                "n_present": 5,
                "n_nonempty": 5,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["1BRS_AD"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD", "path": "1BRS_A.a3m"},
                ],
                "artifacts_by_target": {
                    "1BRS_AD": {
                        "n_artifacts": 7,
                        "n_present": 5,
                        "n_nonempty": 5,
                        "n_missing": 2,
                        "n_empty": 0,
                        "pending_fields": ["target_msa"],
                        "ready": False,
                    },
                },
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD"}],
                "next_action": "sync/fix missing or empty input-prep artifacts before rerunning --require-files",
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })

            rep = run_status(
                scale_completion_path=completion,
                input_prep_completion_path=input_prep,
                target_alpha=0.2,
            )

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "scale_input_prep_completion_blocked")
        self.assertEqual(w1["source_status"], "waiting_on_input_prep")
        self.assertEqual(w1["n_missing"], 2)
        self.assertEqual(w1["blocked_targets"], ["1BRS_AD"])
        self.assertEqual(w1["pending_artifacts"][0]["field"], "target_msa")
        self.assertEqual(w1["superseded_scale_completion_status"], "scale_plan_unavailable")
        self.assertIn("sync/fix", w1["next_action"])

    def test_separate_input_prep_completion_paths_refine_w1_and_w2(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            scale_completion = os.path.join(d, "scale_completion.json")
            scale_input_prep = os.path.join(d, "scale_input_prep.json")
            target_manifest = os.path.join(d, "targets_report.json")
            panel_input_prep = os.path.join(d, "panel_input_prep.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "next_batch": {"action": "run_scale_batch"},
            })
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "action": "unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "waiting_on_input_prep",
                "next_action": "run input prep first",
            })
            _write_json(scale_input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 7,
                "n_present": 5,
                "n_nonempty": 5,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["1BRS_AD"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD", "path": "1BRS_A.a3m"},
                ],
                "artifacts_by_target": {"1BRS_AD": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD"}],
                "next_action": "sync/fix W1",
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --target-id 1BRS_AD",
            })
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "2SIC_EI"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "2SIC_EI"},
                ],
            })
            _write_json(panel_input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 21,
                "n_present": 19,
                "n_nonempty": 19,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": ["1BRS_AD", "1CGI_EI"],
                "blocked_targets": ["1BRS_AD", "2SIC_EI"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD", "path": "1BRS_A.a3m"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "2SIC_EI", "path": "2SIC_E.a3m"},
                ],
                "artifacts_by_target": {"2SIC_EI": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "2SIC_EI"}],
                "next_action": "sync/fix W2",
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --min-targets 3",
            })

            rep = run_status(
                decision_path=decision,
                scale_completion_path=scale_completion,
                scale_input_prep_completion_path=scale_input_prep,
                target_manifest_path=target_manifest,
                panel_input_prep_completion_path=panel_input_prep,
                target_alpha=0.2,
            )

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w1["status"], "scale_input_prep_completion_blocked")
        self.assertEqual(w1["blocked_targets"], ["1BRS_AD"])
        self.assertEqual(w1["next_action"], "sync/fix W1")
        self.assertEqual(w2["status"], "panel_input_prep_completion_blocked")
        self.assertEqual(w2["blocked_targets"], ["1BRS_AD", "2SIC_EI"])
        self.assertEqual(w2["next_action"], "sync/fix W2")
        self.assertEqual(rep["n_pending_input_prep_paths"], 2)
        pending_by_path = {p["path"]: p for p in rep["pending_input_prep_paths"]}
        self.assertEqual(
            pending_by_path["1BRS_A.a3m"]["workstreams"],
            ["W1_M6c_scale_up", "W2_multi_target_panel"],
        )
        self.assertEqual(pending_by_path["2SIC_E.a3m"]["target_ids"], ["2SIC_EI"])
        self.assertEqual(render_pending_input_prep_paths(rep), "1BRS_A.a3m\n2SIC_E.a3m\n")
        self.assertEqual(rep["n_pending_external_artifacts"], 2)
        self.assertEqual(
            rep["pending_external_summary"]["by_workstream"],
            {"W1_M6c_scale_up": 1, "W2_multi_target_panel": 2},
        )
        self.assertEqual(
            rep["pending_external_summary"]["by_target_id"],
            {"1BRS_AD": 1, "2SIC_EI": 1},
        )
        self.assertEqual(rep["pending_external_summary"]["by_field"], {"target_msa": 2})
        summary_by_workstream = {
            item["workstream"]: item
            for item in rep["pending_external_summary"]["workstreams"]
        }
        self.assertEqual(summary_by_workstream["W1_M6c_scale_up"]["n_paths"], 1)
        self.assertEqual(summary_by_workstream["W2_multi_target_panel"]["n_paths"], 2)
        external_by_path = {p["path"]: p for p in rep["pending_external_artifacts"]}
        self.assertEqual(external_by_path["1BRS_A.a3m"]["categories"], ["input_prep"])
        self.assertEqual(
            external_by_path["1BRS_A.a3m"]["workstreams"],
            ["W1_M6c_scale_up", "W2_multi_target_panel"],
        )
        self.assertEqual(render_pending_external_paths(rep), "1BRS_A.a3m\n2SIC_E.a3m\n")

    def test_cli_emits_pending_input_prep_paths(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_paths = os.path.join(d, "pending_paths.txt")
            pending_external = os.path.join(d, "pending_external.txt")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-input-prep-paths", pending_paths,
                "--emit-pending-external-paths", pending_external,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(pending_paths) as fh:
                pending_text = fh.read()
            with open(pending_external) as fh:
                pending_external_text = fh.read()

        self.assertEqual(saved["n_pending_input_prep_paths"], 1)
        self.assertEqual(saved["n_pending_external_artifacts"], 1)
        self.assertEqual(pending_text, "targets/t1.a3m\n")
        self.assertEqual(pending_external_text, "targets/t1.a3m\n")

    def test_cli_emits_sync_back_plan(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_paths = os.path.join(d, "pending_paths.txt")
            sync_back = os.path.join(d, "sync_back.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa_report",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m.report.json",
                        "path": os.path.join(d, "targets/t1.a3m.report.json"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-input-prep-paths", pending_paths,
                "--emit-sync-back-plan", sync_back,
                "--emit-post-sync-plan", post_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(sync_back) as fh:
                plan = fh.read()
            pending_manifest = os.path.splitext(pending_paths)[0] + ".manifest.json"
            with open(pending_manifest) as fh:
                manifest = json.load(fh)

        self.assertEqual(saved["pending_input_prep_manifest"]["path_file"], pending_paths)
        self.assertEqual(saved["pending_input_prep_manifest"]["manifest_file"], pending_manifest)
        self.assertEqual(saved["pending_input_prep_manifest"]["n_paths"], 2)
        self.assertEqual(saved["pending_input_prep_manifest"]["sha256"], manifest["sha256"])
        self.assertEqual(manifest["paths"], ["targets/t1.a3m", "targets/t1.a3m.report.json"])
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        sync_manifest = scripts_by_role["input_prep_sync_back"]["manifest"]
        self.assertEqual(sync_manifest["source"], "project_status")
        self.assertEqual(sync_manifest["manifest_file"], pending_manifest)
        self.assertEqual(sync_manifest["n_paths"], 2)
        self.assertEqual(sync_manifest["sha256"], manifest["sha256"])
        self.assertIn("script_manifests=2/2", render_text(saved))
        self.assertIn("CAYUGA_BIO_SFM_ROOT", plan)
        self.assertIn("REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-", plan)
        self.assertIn("cd \"$REPO_ROOT\"", plan)
        self.assertIn("BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"", plan)
        self.assertIn("export -f python", plan)
        self.assertIn('LOCAL_ROOT=${LOCAL_BIO_SFM_ROOT:-$REPO_ROOT}', plan)
        self.assertIn("PENDING_INPUT_PREP_PATHS=", plan)
        self.assertIn("EXPECTED_PENDING_INPUT_PREP_COUNT=2", plan)
        self.assertIn("EXPECTED_PENDING_INPUT_PREP_SHA256=", plan)
        self.assertIn("stale pending input-prep path list", plan)
        self.assertIn("INPUT_PREP_SYNC_FAILURES=0", plan)
        self.assertIn("run_input_prep_sync_step()", plan)
        self.assertIn("input-prep sync step failed", plan)
        self.assertIn("input-prep sync completed with", plan)
        self.assertIn("run_input_prep_sync_step targets/t1.a3m <<'SH'", plan)
        self.assertIn("run_input_prep_sync_step targets/t1.a3m.report.json <<'SH'", plan)
        self.assertIn("run_input_prep_sync_step 'post-sync replay' <<'SH'", plan)
        self.assertIn("export REMOTE_ROOT LOCAL_ROOT", plan)
        self.assertIn("rsync -avP", plan)
        self.assertIn('test -s "${LOCAL_ROOT%/}"/targets/t1.a3m', plan)
        self.assertIn('test -s "${LOCAL_ROOT%/}"/targets/t1.a3m.report.json', plan)
        self.assertIn('"${REMOTE_ROOT%/}"/targets/t1.a3m', plan)
        self.assertIn('"${REMOTE_ROOT%/}"/targets/t1.a3m.report.json', plan)
        self.assertIn('"${LOCAL_ROOT%/}"/targets/', plan)
        self.assertIn("targets=t1 fields=target_msa", plan)
        self.assertIn(f"bash {post_sync}", plan)

    def test_input_prep_sync_plan_failure_collects_rsync_and_runs_post_sync(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_paths = os.path.join(d, "pending_paths.txt")
            sync_back = os.path.join(d, "sync_back.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            fake_bin = os.path.join(d, "bin")
            fake_rsync = os.path.join(fake_bin, "rsync")
            log_path = os.path.join(d, "rsync.log")
            marker = os.path.join(d, "post_sync_marker.txt")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_rsync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$RSYNC_LOG\"\n")
                fh.write("case \"$*\" in *fail.a3m*) exit 12 ;; esac\n")
                fh.write("prev=\n")
                fh.write("last=\n")
                fh.write("for arg in \"$@\"; do prev=\"$last\"; last=\"$arg\"; done\n")
                fh.write("mkdir -p \"$last\"\n")
                fh.write("printf synced > \"${last%/}/${prev##*/}\"\n")
                fh.write("exit 0\n")
            os.chmod(fake_rsync, 0o755)
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1", "t2"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/fail.a3m",
                        "path": os.path.join(d, "targets/fail.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t2",
                        "declared_path": "targets/pass.a3m",
                        "path": os.path.join(d, "targets/pass.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}, "t2": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-input-prep-paths", pending_paths,
                "--emit-sync-back-plan", sync_back,
                "--emit-post-sync-plan", post_sync,
                "--sync-local-root", d,
            ])
            with open(post_sync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("set -euo pipefail\n")
                fh.write(f"printf ran > {shlex.quote(marker)}\n")
            os.chmod(post_sync, 0o755)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["LOCAL_BIO_SFM_ROOT"] = d
            env["RSYNC_LOG"] = log_path
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", sync_back], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)
            with open(log_path) as fh:
                rsync_log = fh.read()

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("input-prep sync step failed (12): targets/fail.a3m", proc.stderr)
            self.assertIn("input-prep sync completed with 1 failed step", proc.stderr)
            self.assertIn("targets/fail.a3m", rsync_log)
            self.assertIn("targets/pass.a3m", rsync_log)
            self.assertTrue(os.path.exists(marker))

    def test_cli_emits_external_sync_back_plan(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            contract = os.path.join(d, "predictor_contract.json")
            preflight = os.path.join(d, "preflight.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            w3_sync = os.path.join(d, "w3_sync.sh")
            w4_sync = os.path.join(d, "w4_sync.sh")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [{
                    "kind": "missing_file",
                    "field": "target_msa",
                    "target_id": "t1",
                    "declared_path": "targets/t1.a3m",
                    "path": os.path.join(d, "targets/t1.a3m"),
                }],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(contract, {
                "ok": False,
                "secondary_predictor": {"predictor_id": "chai1_complex"},
                "pending_secondary_records": [{"path": "hpc_outputs/chai.jsonl", "status": "missing"}],
                "failures": [{"kind": "missing_file", "field": "secondary_records"}],
            })
            _write_json(preflight, {
                "ok": False,
                "n_candidates": 0,
                "strict_complex_records": True,
                "pending_artifacts": [{"artifact": "records", "path": "hpc_outputs/w4/records.jsonl", "status": "missing"}],
                "failures": [{"kind": "missing_batch_artifact", "artifact": "records"}],
            })
            _write_json(
                os.path.splitext(w3_sync)[0] + ".manifest.json",
                _sync_manifest("second_predictor_sync_back", w3_sync, ["hpc_outputs/chai.jsonl"]),
            )
            _write_json(
                os.path.splitext(w4_sync)[0] + ".manifest.json",
                _sync_manifest("w4_batch_sync_back", w4_sync, ["hpc_outputs/w4/records.jsonl"]),
            )

            main([
                "--panel-input-prep-completion", input_prep,
                "--predictor-contract-report", contract,
                "--predictor-sync-back-plan", w3_sync,
                "--batch-preflight", preflight,
                "--batch-sync-back-plan", w4_sync,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(pending_external) as fh:
                pending_text = fh.read()
            with open(external_sync) as fh:
                plan = fh.read()
            pending_manifest = os.path.splitext(pending_external)[0] + ".manifest.json"
            with open(pending_manifest) as fh:
                manifest = json.load(fh)

        self.assertEqual(saved["n_pending_external_artifacts"], 3)
        self.assertEqual(saved["pending_external_manifest"]["path_file"], pending_external)
        self.assertEqual(saved["pending_external_manifest"]["manifest_file"], pending_manifest)
        self.assertEqual(saved["pending_external_manifest"]["n_paths"], 3)
        self.assertEqual(saved["pending_external_manifest"]["sha256"], manifest["sha256"])
        self.assertEqual(manifest["paths"], [
            "targets/t1.a3m",
            "hpc_outputs/chai.jsonl",
            "hpc_outputs/w4/records.jsonl",
        ])
        self.assertEqual(saved["recommended_next_script"]["path"], external_sync)
        self.assertEqual(saved["recommended_next_script"]["command"], f"bash {external_sync}")
        self.assertTrue(saved["recommended_next_script"]["recommended"])
        self.assertIn("recommended_next_script", render_text(saved))
        self.assertIn("script_manifests=4/4", render_text(saved))
        self.assertIn("sync_manifest_audit=ok checks=4", render_text(saved))
        self.assertTrue(saved["sync_manifest_audit"]["ok"])
        self.assertEqual(saved["sync_manifest_audit"]["n_checks"], 4)
        self.assertEqual(
            [script["role"] for script in saved["generated_scripts"]],
            [
                "external_sync_back",
                "second_predictor_sync_back",
                "closed_loop_batch_sync_back",
                "post_sync_replay",
            ],
        )
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        external_manifest = scripts_by_role["external_sync_back"]["manifest"]
        self.assertEqual(external_manifest["source"], "project_status")
        self.assertEqual(external_manifest["manifest_file"], pending_manifest)
        self.assertEqual(external_manifest["n_paths"], 3)
        self.assertEqual(external_manifest["sha256"], manifest["sha256"])
        self.assertTrue(scripts_by_role["second_predictor_sync_back"]["manifest"]["matches_expected"])
        self.assertTrue(scripts_by_role["closed_loop_batch_sync_back"]["manifest"]["matches_expected"])
        post_manifest = scripts_by_role["post_sync_replay"]["manifest"]
        self.assertEqual(post_manifest["source"], "project_status")
        self.assertEqual(post_manifest["kind"], "post_sync_replay_dependencies")
        self.assertEqual(post_manifest["n_paths"], 3)
        self.assertTrue(post_manifest["matches_expected"])
        self.assertEqual(
            pending_text,
            "targets/t1.a3m\nhpc_outputs/chai.jsonl\nhpc_outputs/w4/records.jsonl\n",
        )
        self.assertIn('"${REMOTE_ROOT%/}"/targets/t1.a3m', plan)
        self.assertIn("REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-", plan)
        self.assertIn("cd \"$REPO_ROOT\"", plan)
        self.assertIn("BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"", plan)
        self.assertIn("export -f python", plan)
        self.assertIn('LOCAL_ROOT=${LOCAL_BIO_SFM_ROOT:-$REPO_ROOT}', plan)
        self.assertIn('"${REMOTE_ROOT%/}"/hpc_outputs/chai.jsonl', plan)
        self.assertIn('"${REMOTE_ROOT%/}"/hpc_outputs/w4/records.jsonl', plan)
        self.assertIn('test -s "${LOCAL_ROOT%/}"/targets/t1.a3m', plan)
        self.assertIn('test -s "${LOCAL_ROOT%/}"/hpc_outputs/chai.jsonl', plan)
        self.assertIn('test -s "${LOCAL_ROOT%/}"/hpc_outputs/w4/records.jsonl', plan)
        self.assertIn("EXTERNAL_SYNC_FAILURES=0", plan)
        self.assertIn("run_external_sync_step()", plan)
        self.assertIn("external sync step failed", plan)
        self.assertIn("external sync completed with", plan)
        self.assertIn("run_external_sync_step targets/t1.a3m <<'SH'", plan)
        self.assertIn("run_external_sync_step hpc_outputs/chai.jsonl <<'SH'", plan)
        self.assertIn("run_external_sync_step 'post-sync replay' <<'SH'", plan)
        self.assertIn(f"# - bash {w3_sync}", plan)
        self.assertIn(f"# - bash {w4_sync}", plan)
        self.assertNotIn(f"\nbash {w3_sync}", plan)
        self.assertNotIn(f"\nbash {w4_sync}", plan)
        self.assertIn(f"bash {post_sync}", plan)
        self.assertIn("categories=second_predictor", plan)
        self.assertIn("categories=closed_loop_batch", plan)
        self.assertIn("EXPECTED_PENDING_EXTERNAL_COUNT=3", plan)
        self.assertIn("EXPECTED_PENDING_EXTERNAL_SHA256=", plan)
        self.assertIn("stale pending external path list", plan)

    def test_cli_emits_external_remote_check_plan(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1", "t2"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/missing.a3m",
                        "path": os.path.join(d, "targets/missing.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t2",
                        "declared_path": "targets/present.a3m",
                        "path": os.path.join(d, "targets/present.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}, "t2": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            old_env = os.environ.pop("CAYUGA_BIO_SFM_ROOT", None)
            try:
                main([
                    "--panel-input-prep-completion", input_prep,
                    "--out", out,
                    "--emit-pending-external-paths", pending_external,
                    "--emit-external-remote-check-plan", remote_check,
                    "--emit-external-sync-back-plan", external_sync,
                    "--emit-post-sync-plan", post_sync,
                ])
            finally:
                if old_env is not None:
                    os.environ["CAYUGA_BIO_SFM_ROOT"] = old_env
            with open(out) as fh:
                saved = json.load(fh)
            with open(remote_check) as fh:
                plan = fh.read()

            fake_bin = os.path.join(d, "bin")
            fake_ssh = os.path.join(fake_bin, "ssh")
            ssh_log = os.path.join(d, "ssh.log")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_ssh, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$SSH_LOG\"\n")
                fh.write("case \"$*\" in *missing.a3m*) exit 44 ;; esac\n")
                fh.write("exit 0\n")
            os.chmod(fake_ssh, 0o755)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["SSH_LOG"] = ssh_log
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", remote_check], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)
            with open(ssh_log) as fh:
                ssh_log_text = fh.read()
            report_path = os.path.splitext(remote_check)[0] + ".json"
            with open(report_path) as fh:
                report = json.load(fh)

        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertEqual(saved["recommended_next_script"]["path"], remote_check)
        self.assertEqual(saved["recommended_next_script"]["resume_preflight_status"], "waiting_on_env")
        self.assertEqual(saved["resume_bridge_preflight"]["missing_env"], ["CAYUGA_BIO_SFM_ROOT"])
        self.assertEqual(saved["external_remote_check_report"]["status"], "missing_report")
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(scripts_by_role["external_remote_check"]["manifest"]["n_paths"], 2)
        self.assertEqual(scripts_by_role["external_remote_check"]["report"], os.path.splitext(remote_check)[0] + ".json")
        self.assertTrue(saved["sync_manifest_audit"]["ok"])
        self.assertIn("REMOTE_CHECK_FAILURES=0", plan)
        self.assertIn("BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"", plan)
        self.assertIn("REMOTE_CHECK_REPORT=\"${REMOTE_CHECK_REPORT:-${SCRIPT_DIR}/$(basename \"${BASH_SOURCE[0]}\" .sh).json}\"", plan)
        self.assertIn("REMOTE_CHECK_METADATA=\"$(mktemp", plan)
        self.assertIn("REMOTE_CHECK_MANIFEST_PROVENANCE=\"$(mktemp", plan)
        self.assertIn("\"targets/missing.a3m\"", plan)
        self.assertIn("\"target_ids\"", plan)
        self.assertIn("\"path_file\"", plan)
        self.assertIn("\"manifest_file\"", plan)
        self.assertIn("REMOTE_HOST=\"${REMOTE_ROOT%%:*}\"", plan)
        self.assertIn("REMOTE_DIR=\"${REMOTE_ROOT#*:}\"", plan)
        self.assertIn("ssh \"$REMOTE_HOST\"", plan)
        self.assertIn("test -s $(printf '%q' \"$remote_path\")", plan)
        self.assertIn("EXPECTED_PENDING_EXTERNAL_COUNT=2", plan)
        self.assertIn("stale pending external path list", plan)
        self.assertIn(
            "next: rerun project status with --external-remote-check-report $REMOTE_CHECK_REPORT",
            plan,
        )
        self.assertNotIn(f"next: bash {external_sync}", plan)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("remote check step failed (44): targets/missing.a3m", proc.stderr)
        self.assertIn("remote preflight completed with 1 failed step", proc.stderr)
        self.assertIn("remote check report:", proc.stdout)
        self.assertIn("remote test -s /scratch/bio_sfm_designer/targets/missing.a3m", ssh_log_text)
        self.assertIn("remote test -s /scratch/bio_sfm_designer/targets/present.a3m", ssh_log_text)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "missing_remote_artifacts")
        self.assertEqual(report["n_paths"], 2)
        self.assertEqual(report["n_present"], 1)
        self.assertEqual(report["n_missing"], 1)
        self.assertEqual(report["n_metadata_paths"], 2)
        self.assertEqual(report["path_manifest"], _remote_path_manifest(pending_external, "targets/missing.a3m\ntargets/present.a3m\n"))
        self.assertEqual(report["target_msa_precompute_receipt_sync"], {"requested": False})
        self.assertEqual(report["missing_by_workstream"], {"W2_multi_target_panel": 1})
        self.assertEqual(report["missing_by_category"], {"input_prep": 1})
        self.assertEqual(report["missing_by_target_id"], {"t1": 1})
        self.assertEqual(
            report["path_file_sha256"],
            hashlib.sha256(b"targets/missing.a3m\ntargets/present.a3m\n").hexdigest(),
        )
        by_path = {item["path"]: item for item in report["paths"]}
        self.assertEqual(by_path["targets/missing.a3m"]["status"], "missing_or_empty")
        self.assertEqual(by_path["targets/missing.a3m"]["workstreams"], ["W2_multi_target_panel"])
        self.assertEqual(by_path["targets/missing.a3m"]["categories"], ["input_prep"])
        self.assertEqual(by_path["targets/missing.a3m"]["target_ids"], ["t1"])
        self.assertEqual(by_path["targets/missing.a3m"]["fields"], ["target_msa"])
        self.assertEqual(by_path["targets/present.a3m"]["status"], "present_nonempty")

    def test_fresh_remote_check_report_advances_to_external_sync(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            paths_text = "targets/a.a3m\ntargets/b.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a", "b"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "a",
                        "declared_path": "targets/a.a3m",
                        "path": os.path.join(d, "targets/a.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "b",
                        "declared_path": "targets/b.a3m",
                        "path": os.path.join(d, "targets/b.a3m"),
                    },
                ],
                "artifacts_by_target": {"a": {"ready": False}, "b": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 2,
                "n_present": 2,
                "n_missing": 0,
                "n_not_checked": 0,
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/a.a3m", "status": "present_nonempty", "present_nonempty": True},
                    {"path": "targets/b.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(remote_check) as fh:
                remote_check_text = fh.read()

        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertEqual(saved["external_remote_check_report"]["status"], "ready_for_external_sync")
        self.assertTrue(saved["external_remote_check_report"]["fresh"])
        self.assertTrue(saved["external_remote_check_report"]["ready_for_external_sync"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_sync_back")
        self.assertFalse(scripts_by_role["external_remote_check"]["recommended"])
        self.assertTrue(scripts_by_role["external_sync_back"]["recommended"])
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            ["external_remote_check", "project_status_refresh", "external_sync_back"],
        )
        self.assertEqual(ladder[0]["status"], "satisfied")
        self.assertEqual(ladder[1]["status"], "satisfied")
        self.assertTrue(ladder[1]["pseudo_step"])
        self.assertIn("complex_project_status", ladder[1]["command"])
        self.assertEqual(ladder[2]["status"], "waiting_on_env")
        self.assertNotIn("blocked_by", ladder[2])
        self.assertIn("external_remote_check_report=ready_for_external_sync", render_text(saved))
        self.assertIn(
            "resume_execution_ladder=external_remote_check:satisfied>project_status_refresh:satisfied>external_sync_back:waiting_on_env",
            render_text(saved),
        )
        self.assertIn("next: python -m bio_sfm_designer.experiments.complex_project_status", remote_check_text)
        self.assertIn(f"--external-remote-check-report {remote_report}", remote_check_text)
        self.assertIn(f"then if status recommends it: bash {external_sync}", remote_check_text)
        self.assertNotIn(f"next: bash {external_sync}", remote_check_text)

    def test_fresh_remote_check_report_must_match_manifest_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            paths_text = "targets/a.a3m\n"
            stale_path_file = os.path.join(d, "stale_pending_external.txt")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "a",
                        "declared_path": "targets/a.a3m",
                        "path": os.path.join(d, "targets/a.a3m"),
                    },
                ],
                "artifacts_by_target": {"a": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(stale_path_file, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/a.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "inconsistent_report")
        self.assertTrue(report["fresh"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["remote_artifacts_ready"])
        self.assertFalse(report["ready_for_external_sync"])
        fields = {failure["field"] for failure in report["consistency_failures"]}
        self.assertIn("path_manifest.path_file", fields)
        self.assertIn("path_manifest.manifest_file", fields)
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")

    def test_fresh_ok_remote_check_report_must_be_counter_consistent(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            paths_text = "targets/a.a3m\ntargets/b.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a", "b"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "a",
                        "declared_path": "targets/a.a3m",
                        "path": os.path.join(d, "targets/a.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "b",
                        "declared_path": "targets/b.a3m",
                        "path": os.path.join(d, "targets/b.a3m"),
                    },
                ],
                "artifacts_by_target": {"a": {"ready": False}, "b": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 2,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/a.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "inconsistent_report")
        self.assertTrue(report["fresh"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["remote_artifacts_ready"])
        self.assertFalse(report["ready_for_external_sync"])
        fields = {failure["field"] for failure in report["consistency_failures"]}
        self.assertEqual(fields, {"n_present", "paths"})
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            ["external_remote_check", "project_status_refresh", "external_sync_back"],
        )
        self.assertEqual(ladder[0]["status"], "waiting_on_env")
        self.assertEqual(ladder[1]["status"], "blocked_until_remote_check_passes")
        self.assertEqual(ladder[1]["blocked_by"], "external_remote_check")
        self.assertIn(f"--external-remote-check-report {remote_report}", ladder[1]["next_action"])
        self.assertEqual(ladder[2]["status"], "blocked_until_project_status_refresh_completes")
        self.assertEqual(ladder[2]["blocked_by"], "project_status_refresh")
        self.assertIn("external_remote_check_report=inconsistent_report", render_text(saved))

    def test_fresh_ok_remote_check_report_must_have_success_status(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            paths_text = "targets/a.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "a",
                        "declared_path": "targets/a.a3m",
                        "path": os.path.join(d, "targets/a.a3m"),
                    },
                ],
                "artifacts_by_target": {"a": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "missing_remote_artifacts",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/a.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "inconsistent_report")
        self.assertFalse(report["remote_artifacts_ready"])
        self.assertFalse(report["ready_for_external_sync"])
        self.assertEqual(report["consistency_failures"], [{
            "field": "status",
            "expected": "all_present_nonempty",
            "actual": "missing_remote_artifacts",
        }])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")

    def test_fresh_remote_check_receipt_sync_failure_does_not_bypass_missing_target_msa_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            target_manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            paths_text = "targets/t1.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(target_manifest, {
                "targets": [{
                    "id": "t1",
                    "prepared_pdb": "targets/t1.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "targets/t1.fasta",
                    "target_fasta_report": "targets/t1.fasta.report.json",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                }],
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "target_msa_precompute_receipt_sync": {
                    "requested": True,
                    "status": "missing_remote_receipt",
                    "synced": False,
                    "returncode": 1,
                },
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/t1.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-target-manifest", target_manifest,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-target-msa-precompute-plan", precompute_plan,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "target_msa_receipt_sync_failed")
        self.assertTrue(report["fresh"])
        self.assertTrue(report["ok"])
        self.assertTrue(report["remote_artifacts_ready"])
        self.assertTrue(report["target_msa_receipt_required"])
        self.assertFalse(report["target_msa_receipt_ok"])
        self.assertTrue(report["target_msa_receipt_sync_requested"])
        self.assertEqual(report["target_msa_receipt_sync_status"], "missing_remote_receipt")
        self.assertFalse(report["target_msa_receipt_sync_synced"])
        self.assertFalse(report["target_msa_receipt_sync_has_digest"])
        self.assertIsNone(report["target_msa_receipt_sync_sha256"])
        self.assertIsNone(report["target_msa_receipt_sync_size_bytes"])
        self.assertTrue(report["target_msa_receipt_sync_failed"])
        self.assertFalse(report["ready_for_external_sync"])
        self.assertEqual(saved["target_msa_precompute_receipt"]["status"], "missing_receipt")
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(scripts_by_role["target_msa_precompute"]["recommended"])
        self.assertFalse(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["operator_next_role"], "target_msa_precompute")
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            ["target_msa_precompute", "external_remote_check", "project_status_refresh", "external_sync_back"],
        )
        self.assertEqual(ladder[0]["status"], "waiting_on_cayuga_session")
        self.assertEqual(ladder[1]["status"], "blocked_until_target_msa_precompute_completes")
        self.assertEqual(ladder[1]["blocked_by"], "target_msa_precompute")
        self.assertEqual(ladder[2]["status"], "blocked_until_remote_check_passes")
        self.assertEqual(ladder[2]["blocked_by"], "external_remote_check")
        self.assertEqual(saved["goal_progress_audit"]["status"], "external_receipt_sync_repair_required")
        self.assertIn("external_remote_check_report=target_msa_receipt_sync_failed", render_text(saved))
        self.assertIn("target_msa_precompute_receipt_sync=missing_remote_receipt synced=False", render_text(saved))
        self.assertIn(
            "resume_execution_ladder=target_msa_precompute:waiting_on_cayuga_session>external_remote_check:blocked_until_target_msa_precompute_completes",
            render_text(saved),
        )

    def test_fresh_remote_check_synced_receipt_requires_digest_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            target_manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            paths_text = "targets/t1.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(target_manifest, {
                "targets": [{
                    "id": "t1",
                    "prepared_pdb": "targets/t1.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "targets/t1.fasta",
                    "target_fasta_report": "targets/t1.fasta.report.json",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                }],
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "target_msa_precompute_receipt_sync": {
                    "requested": True,
                    "status": "synced",
                    "synced": True,
                    "returncode": 0,
                    "local_path": os.path.join(d, "missing_receipt.jsonl"),
                },
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/t1.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-target-manifest", target_manifest,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-target-msa-precompute-plan", precompute_plan,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "target_msa_receipt_sync_failed")
        self.assertTrue(report["target_msa_receipt_sync_requested"])
        self.assertEqual(report["target_msa_receipt_sync_status"], "synced")
        self.assertFalse(report["target_msa_receipt_sync_synced"])
        self.assertFalse(report["target_msa_receipt_sync_has_digest"])
        self.assertIsNone(report["target_msa_receipt_sync_sha256"])
        self.assertIsNone(report["target_msa_receipt_sync_size_bytes"])
        self.assertTrue(report["target_msa_receipt_sync_failed"])
        self.assertFalse(report["ready_for_external_sync"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertIn(
            "target_msa_precompute_receipt_sync=synced_missing_digest synced=False",
            render_text(saved),
        )

    def test_fresh_remote_check_synced_receipt_digest_must_match_local_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            target_manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            paths_text = "targets/t1.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(target_manifest, {
                "targets": [{
                    "id": "t1",
                    "prepared_pdb": "targets/t1.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "targets/t1.fasta",
                    "target_fasta_report": "targets/t1.fasta.report.json",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                }],
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "t1",
                    "status": "validated_existing",
                    "target_fasta": "targets/t1.fasta",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                    "manifest": target_manifest,
                    "manifest_sha256": _sha256_file(target_manifest),
                    "workstream": "W2_multi_target_panel",
                }) + "\n")
            local_receipt_sha = _sha256_file(receipt)
            remote_receipt_sha = "0" * 64
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "target_msa_precompute_receipt_sync": {
                    "requested": True,
                    "status": "synced",
                    "synced": True,
                    "returncode": 0,
                    "sha256": remote_receipt_sha,
                    "size_bytes": os.path.getsize(receipt),
                    "local_path": receipt,
                },
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/t1.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-target-manifest", target_manifest,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-target-msa-precompute-plan", precompute_plan,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "target_msa_receipt_sync_mismatch")
        self.assertTrue(report["target_msa_receipt_required"])
        self.assertTrue(report["target_msa_receipt_ok"])
        self.assertTrue(report["target_msa_receipt_sync_requested"])
        self.assertTrue(report["target_msa_receipt_sync_synced"])
        self.assertTrue(report["target_msa_receipt_sync_has_digest"])
        self.assertFalse(report["target_msa_receipt_sync_matches_local"])
        self.assertTrue(report["target_msa_receipt_sync_mismatch"])
        self.assertEqual(report["target_msa_receipt_local_sha256"], local_receipt_sha)
        self.assertEqual(report["target_msa_receipt_sync_sha256"], remote_receipt_sha)
        self.assertFalse(report["ready_for_external_sync"])
        self.assertEqual(saved["target_msa_precompute_receipt"]["status"], "satisfied")
        self.assertEqual(saved["goal_progress_audit"]["status"], "external_receipt_sync_repair_required")
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertIn("external_remote_check_report=target_msa_receipt_sync_mismatch", render_text(saved))

    def test_fresh_remote_check_without_receipt_sync_is_rerun_before_submit(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            target_manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            paths_text = "targets/t1.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(target_manifest, {
                "targets": [{
                    "id": "t1",
                    "prepared_pdb": "targets/t1.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "targets/t1.fasta",
                    "target_fasta_report": "targets/t1.fasta.report.json",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                }],
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "remote_root": "remote:/scratch/bio_sfm_designer",
                "paths": [
                    {"path": "targets/t1.a3m", "status": "present_nonempty", "present_nonempty": True},
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-target-manifest", target_manifest,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-target-msa-precompute-plan", precompute_plan,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        report = saved["external_remote_check_report"]
        self.assertEqual(report["status"], "target_msa_receipt_sync_missing")
        self.assertTrue(report["fresh"])
        self.assertTrue(report["ok"])
        self.assertTrue(report["remote_artifacts_ready"])
        self.assertTrue(report["target_msa_receipt_required"])
        self.assertFalse(report["target_msa_receipt_ok"])
        self.assertFalse(report["target_msa_receipt_sync_requested"])
        self.assertFalse(report["ready_for_external_sync"])
        self.assertEqual(saved["target_msa_precompute_receipt"]["status"], "missing_receipt")
        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertFalse(scripts_by_role["target_msa_precompute"]["recommended"])
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertEqual(saved["operator_next_role"], "external_remote_check")
        self.assertEqual(saved["resume_bridge_preflight"]["status"], "waiting_on_env")
        self.assertEqual(saved["goal_progress_audit"]["status"], "external_remote_check_required")
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            ["external_remote_check", "project_status_refresh", "external_sync_back"],
        )
        self.assertEqual(ladder[0]["status"], "waiting_on_env")
        self.assertEqual(ladder[1]["status"], "blocked_until_remote_check_passes")
        self.assertEqual(ladder[1]["blocked_by"], "external_remote_check")
        self.assertEqual(ladder[2]["status"], "blocked_until_project_status_refresh_completes")
        self.assertEqual(ladder[2]["blocked_by"], "project_status_refresh")
        self.assertIn("external_remote_check_report=target_msa_receipt_sync_missing", render_text(saved))
        self.assertIn(
            "resume_execution_ladder=external_remote_check:waiting_on_env>project_status_refresh:blocked_until_remote_check_passes>external_sync_back:blocked_until_project_status_refresh_completes",
            render_text(saved),
        )

    def test_fresh_missing_remote_check_report_surfaces_remote_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            readiness = os.path.join(d, "readiness.json")
            paths_text = "targets/a.a3m\n"
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a"],
                "pending_artifacts": [{
                    "kind": "missing_file",
                    "field": "target_msa",
                    "target_id": "a",
                    "declared_path": "targets/a.a3m",
                    "path": os.path.join(d, "targets/a.a3m"),
                }],
                "artifacts_by_target": {"a": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(readiness, {
                "ok": False,
                "status": "blocked",
                "next_action": "sync/fix pending_artifacts, then rerun complex_input_prep_completion.py",
                "self_command": "python -m bio_sfm_designer.experiments.complex_readiness --out readiness.json",
                "ordered_steps": [
                    {
                        "id": "target_msa_precompute",
                        "status": "available",
                        "plan_section": "target_msa_precompute",
                        "description": "Run first when target .a3m/report files are missing.",
                    },
                    {
                        "id": "multi_target_panel",
                        "status": "waiting_on_input_prep",
                        "description": "run target_msa_precompute first",
                    },
                ],
            })
            _write_json(remote_report, {
                "ok": False,
                "status": "missing_remote_artifacts",
                "path_file": pending_external,
                "path_file_sha256": hashlib.sha256(paths_text.encode()).hexdigest(),
                "path_manifest": _remote_path_manifest(pending_external, paths_text),
                "n_paths": 1,
                "n_present": 0,
                "n_missing": 1,
                "n_not_checked": 0,
                "n_metadata_paths": 1,
                "missing_by_workstream": {"W2_multi_target_panel": 1},
                "missing_by_category": {"input_prep": 1},
                "missing_by_target_id": {"a": 1},
                "missing_by_artifact": {"unknown": 1},
                "paths": [{
                    "path": "targets/a.a3m",
                    "status": "missing_or_empty",
                    "present_nonempty": False,
                    "workstreams": ["W2_multi_target_panel"],
                    "categories": ["input_prep"],
                    "target_ids": ["a"],
                    "fields": ["target_msa"],
                }],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-readiness-report", readiness,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        remote_summary = saved["external_remote_check_report"]
        self.assertEqual(remote_summary["status"], "missing_remote_artifacts")
        self.assertTrue(remote_summary["fresh"])
        self.assertFalse(remote_summary["ready_for_external_sync"])
        self.assertEqual(remote_summary["missing_by_workstream"], {"W2_multi_target_panel": 1})
        self.assertEqual(remote_summary["missing_by_category"], {"input_prep": 1})
        self.assertEqual(remote_summary["missing_by_target_id"], {"a": 1})
        followups = remote_summary["remote_missing_followups"]
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0]["workstream"], "W2_multi_target_panel")
        self.assertEqual(followups[0]["n_missing"], 1)
        self.assertEqual(followups[0]["target_ids"], ["a"])
        self.assertIn("target_msa_precompute", followups[0]["next_action"])
        self.assertEqual(followups[0]["readiness"]["path"], readiness)
        self.assertEqual(followups[0]["readiness"]["available_steps"][0]["id"], "target_msa_precompute")
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])
        self.assertEqual(saved["goal_progress_audit"]["status"], "remote_jobs_incomplete")
        self.assertIn("missing_workstreams=W2_multi_target_panel:1", render_text(saved))
        self.assertIn("followups=W2_multi_target_panel:1", render_text(saved))

    def test_stale_remote_check_report_keeps_remote_check_recommended(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            remote_report = os.path.join(d, "remote_check.json")
            external_sync = os.path.join(d, "external_sync.sh")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["a"],
                "pending_artifacts": [{
                    "kind": "missing_file",
                    "field": "target_msa",
                    "target_id": "a",
                    "declared_path": "targets/a.a3m",
                    "path": os.path.join(d, "targets/a.a3m"),
                }],
                "artifacts_by_target": {"a": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "a"}],
                "next_action": "sync/fix",
            })
            _write_json(remote_report, {
                "ok": True,
                "status": "all_present_nonempty",
                "path_file": pending_external,
                "path_file_sha256": "stale",
                "n_paths": 1,
                "n_present": 1,
                "n_missing": 0,
                "n_not_checked": 0,
                "paths": [{"path": "targets/a.a3m", "status": "present_nonempty"}],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--external-remote-check-report", remote_report,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        scripts_by_role = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertEqual(saved["external_remote_check_report"]["status"], "stale_report")
        self.assertFalse(saved["external_remote_check_report"]["fresh"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertTrue(scripts_by_role["external_remote_check"]["recommended"])
        self.assertFalse(scripts_by_role["external_sync_back"]["recommended"])

    def test_external_sync_plan_requires_matching_remote_check_report_when_emitted(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            fake_bin = os.path.join(d, "bin")
            fake_rsync = os.path.join(fake_bin, "rsync")
            log_path = os.path.join(d, "rsync.log")
            marker = os.path.join(d, "post_sync_marker.txt")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_rsync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$RSYNC_LOG\"\n")
                fh.write("exit 99\n")
            os.chmod(fake_rsync, 0o755)
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--sync-local-root", d,
            ])
            with open(post_sync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("set -euo pipefail\n")
                fh.write(f"printf ran > {shlex.quote(marker)}\n")
            os.chmod(post_sync, 0o755)
            with open(external_sync) as fh:
                plan = fh.read()
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["LOCAL_BIO_SFM_ROOT"] = d
            env["RSYNC_LOG"] = log_path
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", external_sync], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)

        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("REMOTE_CHECK_REPORT=${REMOTE_CHECK_REPORT:-", plan)
        self.assertIn("external sync blocked: missing remote-check report", proc.stderr)
        self.assertFalse(os.path.exists(log_path))
        self.assertFalse(os.path.exists(marker))

    def test_external_sync_plan_failure_collects_rsync_and_runs_post_sync(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            fake_bin = os.path.join(d, "bin")
            fake_rsync = os.path.join(fake_bin, "rsync")
            log_path = os.path.join(d, "rsync.log")
            marker = os.path.join(d, "post_sync_marker.txt")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_rsync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$RSYNC_LOG\"\n")
                fh.write("case \"$*\" in *fail.a3m*) exit 12 ;; esac\n")
                fh.write("prev=\n")
                fh.write("last=\n")
                fh.write("for arg in \"$@\"; do prev=\"$last\"; last=\"$arg\"; done\n")
                fh.write("mkdir -p \"$last\"\n")
                fh.write("printf synced > \"${last%/}/${prev##*/}\"\n")
                fh.write("exit 0\n")
            os.chmod(fake_rsync, 0o755)
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1", "t2"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/fail.a3m",
                        "path": os.path.join(d, "targets/fail.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t2",
                        "declared_path": "targets/pass.a3m",
                        "path": os.path.join(d, "targets/pass.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}, "t2": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--sync-local-root", d,
            ])
            with open(post_sync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("set -euo pipefail\n")
                fh.write(f"printf ran > {shlex.quote(marker)}\n")
            os.chmod(post_sync, 0o755)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["LOCAL_BIO_SFM_ROOT"] = d
            env["RSYNC_LOG"] = log_path
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", external_sync], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)
            with open(log_path) as fh:
                rsync_log = fh.read()

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("external sync step failed (12): targets/fail.a3m", proc.stderr)
            self.assertIn("external sync completed with 1 failed step", proc.stderr)
            self.assertIn("targets/fail.a3m", rsync_log)
            self.assertIn("targets/pass.a3m", rsync_log)
            self.assertTrue(os.path.exists(marker))

    def test_external_sync_plan_fails_when_rsync_leaves_missing_local_file(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            fake_bin = os.path.join(d, "bin")
            fake_rsync = os.path.join(fake_bin, "rsync")
            log_path = os.path.join(d, "rsync.log")
            marker = os.path.join(d, "post_sync_marker.txt")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_rsync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$RSYNC_LOG\"\n")
                fh.write("case \"$*\" in *missing_after_rsync.a3m*) exit 0 ;; esac\n")
                fh.write("prev=\n")
                fh.write("last=\n")
                fh.write("for arg in \"$@\"; do prev=\"$last\"; last=\"$arg\"; done\n")
                fh.write("mkdir -p \"$last\"\n")
                fh.write("printf synced > \"${last%/}/${prev##*/}\"\n")
                fh.write("exit 0\n")
            os.chmod(fake_rsync, 0o755)
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1", "t2"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/missing_after_rsync.a3m",
                        "path": os.path.join(d, "targets/missing_after_rsync.a3m"),
                    },
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t2",
                        "declared_path": "targets/pass.a3m",
                        "path": os.path.join(d, "targets/pass.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}, "t2": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--sync-local-root", d,
            ])
            with open(post_sync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("set -euo pipefail\n")
                fh.write(f"printf ran > {shlex.quote(marker)}\n")
            os.chmod(post_sync, 0o755)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["LOCAL_BIO_SFM_ROOT"] = d
            env["RSYNC_LOG"] = log_path
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", external_sync], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)
            with open(log_path) as fh:
                rsync_log = fh.read()

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn(
                "external sync step failed (1): targets/missing_after_rsync.a3m",
                proc.stderr,
            )
            self.assertIn("external sync completed with 1 failed step", proc.stderr)
            self.assertIn("targets/missing_after_rsync.a3m", rsync_log)
            self.assertIn("targets/pass.a3m", rsync_log)
            self.assertTrue(os.path.exists(os.path.join(d, "targets", "pass.a3m")))
            self.assertTrue(os.path.exists(marker))

    def test_cli_resume_bridge_preflight_waits_on_cayuga_env(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            external_sync = os.path.join(d, "external_sync.sh")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [{
                    "kind": "missing_file",
                    "field": "target_msa",
                    "target_id": "t1",
                    "declared_path": "targets/t1.a3m",
                    "path": os.path.join(d, "targets/t1.a3m"),
                }],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            old_env = os.environ.pop("CAYUGA_BIO_SFM_ROOT", None)
            try:
                main([
                    "--panel-input-prep-completion", input_prep,
                    "--out", out,
                    "--emit-pending-external-paths", pending_external,
                    "--emit-external-sync-back-plan", external_sync,
                ])
            finally:
                if old_env is not None:
                    os.environ["CAYUGA_BIO_SFM_ROOT"] = old_env
            with open(out) as fh:
                saved = json.load(fh)

        preflight = saved["resume_bridge_preflight"]
        self.assertEqual(preflight["status"], "waiting_on_env")
        self.assertTrue(preflight["structural_ok"])
        self.assertFalse(preflight["ready_to_execute_now"])
        self.assertEqual(preflight["missing_env"], ["CAYUGA_BIO_SFM_ROOT"])
        self.assertTrue(preflight["script_exists"])
        self.assertTrue(preflight["script_readable"])
        self.assertTrue(preflight["script_runs_via_bash"])
        self.assertTrue(preflight["script_bash_syntax_checked"])
        self.assertTrue(preflight["script_bash_syntax_ok"])
        self.assertEqual(preflight["script_bash_syntax_returncode"], 0)
        self.assertIsNone(preflight["script_bash_syntax_error"])
        self.assertTrue(preflight["path_file_exists"])
        self.assertTrue(preflight["manifest_file_exists"])
        self.assertTrue(preflight["sync_manifest_audit_ok"])
        self.assertIn("export CAYUGA_BIO_SFM_ROOT", preflight["next_action"])
        self.assertEqual(saved["recommended_next_script"]["resume_preflight_status"], "waiting_on_env")
        self.assertTrue(saved["recommended_next_script"]["script_bash_syntax_ok"])
        self.assertIn("resume_bridge_preflight=waiting_on_env", render_text(saved))

    def test_resume_bridge_preflight_blocks_bash_syntax_errors(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "bad_bridge.sh")
            with open(script, "w") as fh:
                fh.write("if true; then\n  echo broken bridge\n")
            rep = run_status()
            rep["recommended_next_script"] = {
                "role": "external_sync_back",
                "path": script,
                "command": f"bash {script}",
                "recommended": True,
            }

            attach_resume_bridge_preflight(
                rep,
                env={"CAYUGA_BIO_SFM_ROOT": "NETID@cayuga:/scratch/NETID/bio_sfm_designer"},
            )

        preflight = rep["resume_bridge_preflight"]
        self.assertEqual(preflight["status"], "blocked")
        self.assertFalse(preflight["structural_ok"])
        self.assertFalse(preflight["ready_to_execute_now"])
        self.assertTrue(preflight["script_bash_syntax_checked"])
        self.assertFalse(preflight["script_bash_syntax_ok"])
        self.assertNotEqual(preflight["script_bash_syntax_returncode"], 0)
        self.assertIn("bash_syntax_error", preflight["blockers"])
        self.assertIn("syntax", preflight["script_bash_syntax_error"])
        self.assertFalse(rep["recommended_next_script"]["script_bash_syntax_ok"])
        self.assertIn("bash_syntax_error", rep["recommended_next_script"]["resume_preflight_blockers"])
        self.assertIn("resume_bridge_preflight=blocked blockers=bash_syntax_error", render_text(rep))

    def test_generated_script_syntax_audit_covers_nonrecommended_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            good_script = os.path.join(d, "good_bridge.sh")
            bad_script = os.path.join(d, "bad_later_bridge.sh")
            with open(good_script, "w") as fh:
                fh.write("echo good bridge\n")
            with open(bad_script, "w") as fh:
                fh.write("for value in one two; do\n  echo \"$value\"\n")
            rep = run_status()
            rep["generated_scripts"] = [
                {
                    "role": "external_remote_check",
                    "path": good_script,
                    "command": f"bash {good_script}",
                    "recommended": True,
                },
                {
                    "role": "external_sync_back",
                    "path": bad_script,
                    "command": f"bash {bad_script}",
                    "recommended": False,
                },
            ]

            attach_generated_script_syntax_audit(rep)

        audit = rep["generated_script_syntax_audit"]
        self.assertFalse(audit["ok"])
        self.assertTrue(audit["all_checked"])
        self.assertEqual(audit["n_scripts"], 2)
        self.assertEqual(audit["n_checked"], 2)
        self.assertEqual(audit["n_ok"], 1)
        self.assertEqual(audit["n_failures"], 1)
        self.assertEqual(audit["failures"][0]["role"], "external_sync_back")
        self.assertEqual(audit["failures"][0]["blocker"], "bash_syntax_error")
        self.assertTrue(rep["generated_scripts"][0]["script_bash_syntax_ok"])
        self.assertFalse(rep["generated_scripts"][1]["script_bash_syntax_ok"])
        self.assertTrue(rep["generated_scripts"][1]["syntax_blocked"])
        self.assertIn("generated_script_syntax_audit=fail checked=2/2", render_text(rep))

    def test_target_msa_precompute_script_validation_audit_blocks_missing_guard(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "target_msa_precompute.sh")
            with open(script, "w") as fh:
                fh.write("echo missing receipt validation\n")
            rep = run_status()
            rep["target_msa_precompute_plan"] = {
                "n_targets": 1,
                "target_ids": ["t1"],
                "expected_receipt_targets": {
                    "t1": {
                        "target_fasta": "hpc_outputs/targets/t1.fasta",
                        "target_msa": "hpc_outputs/targets/t1.a3m",
                        "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
                        "manifest": "configs/targets.json",
                        "manifest_sha256": "abc123",
                        "workstream": "W1_M6c_scale_up",
                    },
                },
                "sections": [
                    {
                        "workstream": "W1_M6c_scale_up",
                        "manifest": "configs/targets.json",
                        "selected_target_ids": ["t1"],
                    },
                ],
            }
            rep["generated_scripts"] = [
                {
                    "role": "target_msa_precompute",
                    "path": script,
                    "command": f"bash {script}",
                    "recommended": True,
                },
            ]
            rep["recommended_next_script"] = rep["generated_scripts"][0]

            attach_generated_script_syntax_audit(rep)
            attach_target_msa_precompute_script_validation_audit(rep)
            attach_resume_bridge_preflight(rep)
            attach_goal_progress_audit(rep)

        audit = rep["target_msa_precompute_script_validation_audit"]
        self.assertTrue(audit["checked"])
        self.assertFalse(audit["ok"])
        self.assertIn("receipt_safe_dry_run_mode", audit["missing_markers"])
        self.assertIn("receipt_validator_function", audit["missing_markers"])
        self.assertTrue(rep["generated_scripts"][0]["receipt_validation_blocked"])
        self.assertIn(
            "target_msa_receipt_validation_audit_failed",
            rep["generated_scripts"][0]["blockers"],
        )
        self.assertEqual(rep["resume_bridge_preflight"]["status"], "blocked")
        self.assertIn(
            "target_msa_receipt_validation_audit_failed",
            rep["resume_bridge_preflight"]["blockers"],
        )
        self.assertEqual(
            rep["goal_progress_audit"]["local_blockers"][0]["kind"],
            "target_msa_receipt_validation_audit_failed",
        )
        self.assertIn(
            "target_msa_precompute_script_validation_audit=fail targets=1",
            render_text(rep),
        )

    def test_goal_progress_blocks_generated_script_syntax_failures(self):
        with tempfile.TemporaryDirectory() as d:
            good_script = os.path.join(d, "good_bridge.sh")
            bad_script = os.path.join(d, "bad_later_bridge.sh")
            with open(good_script, "w") as fh:
                fh.write("echo good bridge\n")
            with open(bad_script, "w") as fh:
                fh.write("while true; do\n  echo broken\n")
            rep = run_status()
            rep["generated_scripts"] = [
                {
                    "role": "external_remote_check",
                    "path": good_script,
                    "command": f"bash {good_script}",
                    "recommended": True,
                },
                {
                    "role": "external_sync_back",
                    "path": bad_script,
                    "command": f"bash {bad_script}",
                    "recommended": False,
                },
            ]
            rep["recommended_next_script"] = rep["generated_scripts"][0]

            attach_generated_script_syntax_audit(rep)
            attach_resume_bridge_preflight(
                rep,
                env={"CAYUGA_BIO_SFM_ROOT": "NETID@cayuga:/scratch/NETID/bio_sfm_designer"},
            )
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertEqual(audit["local_blockers"][0]["kind"], "generated_script_syntax_audit")
        self.assertEqual(audit["local_blockers"][0]["n_failures"], 1)
        self.assertEqual(audit["local_blockers"][0]["failures"][0]["role"], "external_sync_back")
        self.assertIn("syntax failures", audit["next_action"])
        self.assertIn("generated_script_syntax_audit=fail checked=2/2", render_text(rep))

    def test_cli_goal_progress_audit_keeps_incomplete_goal_external_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            readiness = os.path.join(d, "readiness.json")
            missing = os.path.join(d, "targets", "missing.a3m")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": missing},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(readiness, {
                "status": "blocked",
                "next_action": "sync/fix pending_artifacts, then rerun complex_input_prep_completion.py",
                "self_command": "python -m bio_sfm_designer.experiments.complex_readiness --out status.json",
                "ordered_steps": [
                    {
                        "id": "target_msa_precompute",
                        "status": "available",
                        "plan_section": "target_msa_precompute",
                        "description": "Run first when target .a3m/report files are missing.",
                    },
                    {
                        "id": "multi_target_panel",
                        "status": "waiting_on_input_prep",
                        "description": "run target_msa_precompute first",
                    },
                ],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-readiness-report", readiness,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        audit = saved["goal_progress_audit"]
        self.assertEqual(audit["status"], "external_bridge_waiting_on_env")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 4)
        self.assertEqual(saved["goal_progress"], audit["status"])
        self.assertFalse(saved["can_mark_goal_complete"])
        self.assertEqual(saved["remaining_requirements"], 4)
        self.assertEqual(saved["remaining"], 4)
        self.assertEqual(saved["goal_completion_note"], audit["completion_note"])
        self.assertEqual(saved["operator_next_action"], audit["next_action"])
        self.assertEqual(saved["operator_next_command"], f"bash {remote_check}")
        self.assertEqual(saved["operator_next_role"], "external_remote_check")
        self.assertFalse(saved["operator_ready_to_execute_now"])
        self.assertIn("export CAYUGA_BIO_SFM_ROOT", saved["operator_next_action"])
        self.assertIn("--external-remote-check-report", saved["operator_next_action"])
        self.assertIn("refreshed status recommends it", saved["operator_next_action"])
        self.assertIn("--external-remote-check-report", saved["resume_bridge_preflight"]["next_action"])
        self.assertEqual(saved["next_action"], "run complex_posthoc_bundle.py on synchronized records")
        self.assertEqual(audit["first_action"]["role"], "external_remote_check")
        self.assertEqual(audit["first_action"]["resume_preflight_status"], "waiting_on_env")
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            ["external_remote_check", "project_status_refresh", "external_sync_back"],
        )
        self.assertEqual(ladder[0]["status"], "waiting_on_env")
        self.assertEqual(ladder[0]["missing_env"], ["CAYUGA_BIO_SFM_ROOT"])
        self.assertIn("--external-remote-check-report", ladder[0]["next_action"])
        self.assertIn("--external-remote-check-report", ladder[0]["preflight_next_action"])
        self.assertEqual(ladder[1]["status"], "blocked_until_remote_check_passes")
        self.assertEqual(ladder[1]["blocked_by"], "external_remote_check")
        self.assertEqual(ladder[2]["status"], "blocked_until_project_status_refresh_completes")
        self.assertEqual(ladder[2]["blocked_by"], "project_status_refresh")
        self.assertEqual(audit["execution_ladder"]["next_role"], "external_remote_check")
        blocker_kinds = {item["kind"] for item in audit["external_blockers"]}
        self.assertIn("missing_env", blocker_kinds)
        self.assertIn("external_remote_check_report", blocker_kinds)
        self.assertIn("pending_external_artifacts", blocker_kinds)
        pending_blocker = next(
            item for item in audit["external_blockers"]
            if item["kind"] == "pending_external_artifacts"
        )
        self.assertEqual(
            pending_blocker["summary"]["by_workstream"],
            {"W2_multi_target_panel": 1},
        )
        followups = saved["pending_external_followups"]
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0]["workstream"], "W2_multi_target_panel")
        self.assertEqual(followups[0]["n_missing"], 1)
        self.assertEqual(followups[0]["target_ids"], ["t1"])
        self.assertIn("target_msa_precompute", followups[0]["next_action"])
        self.assertEqual(followups[0]["readiness"]["path"], readiness)
        self.assertEqual(followups[0]["readiness"]["available_steps"][0]["id"], "target_msa_precompute")
        self.assertEqual(
            pending_blocker["pending_external_followups"][0]["workstream"],
            "W2_multi_target_panel",
        )
        self.assertIn("do not mark the Codex goal complete", audit["completion_note"])
        self.assertIn("goal_progress=external_bridge_waiting_on_env", render_text(saved))
        self.assertIn("pending_external_workstreams=W2_multi_target_panel:1", render_text(saved))
        self.assertIn("pending_external_followups=W2_multi_target_panel:1", render_text(saved))
        self.assertIn("operator_next_action: export CAYUGA_BIO_SFM_ROOT", render_text(saved))
        self.assertIn("workstream_next_action: run complex_posthoc_bundle.py on synchronized records", render_text(saved))
        self.assertIn(
            "resume_execution_ladder=external_remote_check:waiting_on_env>project_status_refresh:blocked_until_remote_check_passes>external_sync_back:blocked_until_project_status_refresh_completes",
            render_text(saved),
        )

    def test_cli_emits_deduplicated_target_msa_precompute_plan(self):
        with tempfile.TemporaryDirectory() as d:
            scale_input = os.path.join(d, "scale_input.json")
            scale_completion = os.path.join(d, "scale_completion.json")
            panel_input = os.path.join(d, "panel_input.json")
            scale_manifest = os.path.join(d, "scale_targets.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = f"results/test_{os.path.basename(d)}_target_msa_precompute_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            out = os.path.join(d, "status.json")

            def target(target_id):
                return {
                    "id": target_id,
                    "prepared_pdb": f"hpc_outputs/targets/{target_id}.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": f"hpc_outputs/targets/{target_id}.fasta",
                    "target_fasta_report": f"hpc_outputs/targets/{target_id}.fasta.report.json",
                    "target_msa": f"hpc_outputs/targets/{target_id}.a3m",
                    "target_msa_report": f"hpc_outputs/targets/{target_id}.a3m.report.json",
                }

            _write_json(scale_manifest, {"targets": [target("shared")]})
            _write_json(panel_manifest, {"targets": [target("shared"), target("unique")]})
            scale_manifest_sha = _sha256_file(scale_manifest)
            panel_manifest_sha = _sha256_file(panel_manifest)
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "blocked",
                "target_alpha": 0.2,
                "next_action": "run target_msa_precompute first",
            })
            _write_json(scale_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 4,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 4,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared", "unique"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}, "unique": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })

            main([
                "--scale-completion", scale_completion,
                "--scale-input-prep-completion", scale_input,
                "--panel-input-prep-completion", panel_input,
                "--scale-target-manifest", scale_manifest,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(precompute_plan) as fh:
                plan_text = fh.read()
            with open(remote_check) as fh:
                remote_check_text = fh.read()
            dry_run_receipt = os.path.join(d, "dry_run_receipt.jsonl")
            dry_run_env = dict(os.environ)
            dry_run_env.update({
                "BIO_SFM_REPO_ROOT": os.getcwd(),
                "TARGET_MSA_PRECOMPUTE_DRY_RUN": "1",
                "TARGET_MSA_PRECOMPUTE_RECEIPT": dry_run_receipt,
            })
            dry_run = subprocess.run(
                ["bash", precompute_plan],
                check=True,
                capture_output=True,
                text=True,
                env=dry_run_env,
            )
            dry_run_stdout = dry_run.stdout
            dry_run_receipt_exists_after = os.path.exists(dry_run_receipt)
            dry_run_payload = json.loads(dry_run_stdout[dry_run_stdout.index("{"):])
            source_guard_receipt = os.path.join(d, "source_guard_receipt.jsonl")
            source_guard_env = dict(os.environ)
            source_guard_env.update({
                "BIO_SFM_REPO_ROOT": os.getcwd(),
                "TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH": "1",
                "TARGET_MSA_PRECOMPUTE_RECEIPT": source_guard_receipt,
            })
            source_guard = subprocess.run(
                ["bash", precompute_plan],
                check=False,
                capture_output=True,
                text=True,
                env=source_guard_env,
            )
            helper_guard_receipt = os.path.join(d, "helper_guard_receipt.jsonl")
            helper_guard_env = dict(os.environ)
            helper_guard_env.update({
                "BIO_SFM_REPO_ROOT": d,
                "TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH": "1",
                "TARGET_MSA_PRECOMPUTE_RECEIPT": helper_guard_receipt,
            })
            helper_guard = subprocess.run(
                ["bash", precompute_plan],
                check=False,
                capture_output=True,
                text=True,
                env=helper_guard_env,
            )
            runtime_root = os.path.join(d, "runtime_root")
            for helper in (
                "hpc/prep_hetdimer.py",
                "hpc/extract_chain_fasta.py",
                "hpc/precompute_boltz_target_msa.py",
                "hpc/run_precompute_boltz_target_msa.sbatch",
            ):
                dst = os.path.join(runtime_root, helper)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(os.getcwd(), helper), dst)
            for target_id in ("shared", "unique"):
                target_fasta = os.path.join(runtime_root, "hpc_outputs", "targets", f"{target_id}.fasta")
                os.makedirs(os.path.dirname(target_fasta), exist_ok=True)
                with open(target_fasta, "w") as fh:
                    fh.write(f">{target_id}\nAAAA\n")
            runtime_guard_receipt = os.path.join(d, "runtime_guard_receipt.jsonl")
            runtime_guard_env = dict(os.environ)
            runtime_guard_env.update({
                "BIO_SFM_REPO_ROOT": runtime_root,
                "TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH": "1",
                "TARGET_MSA_PRECOMPUTE_RECEIPT": runtime_guard_receipt,
                "ENV_PY": os.path.join(d, "missing_python"),
                "BOLTZ": os.path.join(d, "missing_boltz"),
            })
            runtime_guard = subprocess.run(
                ["bash", precompute_plan],
                check=False,
                capture_output=True,
                text=True,
                env=runtime_guard_env,
            )
            existing_receipt = os.path.join(d, "existing_receipt.jsonl")
            existing_receipt_rows = [
                {
                    "target_id": "shared",
                    "status": "submitted",
                    "job_id": "12345",
                    "target_fasta": "hpc_outputs/targets/shared.fasta",
                    "target_msa": "hpc_outputs/targets/shared.a3m",
                    "target_msa_report": "hpc_outputs/targets/shared.a3m.report.json",
                    "manifest": scale_manifest,
                    "manifest_sha256": scale_manifest_sha,
                    "workstream": "W1_M6c_scale_up",
                }
            ]
            _write_jsonl(existing_receipt, existing_receipt_rows)
            with open(existing_receipt) as fh:
                existing_receipt_before = fh.read()
            existing_env = dict(dry_run_env)
            existing_env["TARGET_MSA_PRECOMPUTE_RECEIPT"] = existing_receipt
            existing_dry_run = subprocess.run(
                ["bash", precompute_plan],
                check=True,
                capture_output=True,
                text=True,
                env=existing_env,
            )
            existing_dry_run_payload = json.loads(
                existing_dry_run.stdout[existing_dry_run.stdout.index("{"):]
            )
            with open(existing_receipt) as fh:
                existing_receipt_after = fh.read()
            mismatched_receipt = os.path.join(d, "mismatched_receipt.jsonl")
            _write_jsonl(mismatched_receipt, [
                {
                    "target_id": "shared",
                    "status": "submitted",
                    "job_id": "bad id",
                    "target_fasta": "hpc_outputs/targets/shared.fasta",
                    "target_msa": "hpc_outputs/targets/wrong.a3m",
                    "target_msa_report": "hpc_outputs/targets/shared.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": panel_manifest_sha,
                    "workstream": "W2_multi_target_panel",
                }
            ])
            mismatched_env = dict(dry_run_env)
            mismatched_env["TARGET_MSA_PRECOMPUTE_RECEIPT"] = mismatched_receipt
            mismatched_dry_run = subprocess.run(
                ["bash", precompute_plan],
                check=True,
                capture_output=True,
                text=True,
                env=mismatched_env,
            )
            mismatched_dry_run_payload = json.loads(
                mismatched_dry_run.stdout[mismatched_dry_run.stdout.index("{"):]
            )

        plan = saved["target_msa_precompute_plan"]
        self.assertEqual(plan["n_targets"], 2)
        self.assertEqual(plan["target_ids"], ["shared", "unique"])
        self.assertEqual(plan["receipt_path"], receipt)
        self.assertEqual(
            plan["expected_receipt_targets"]["shared"]["target_msa"],
            "hpc_outputs/targets/shared.a3m",
        )
        self.assertEqual(plan["expected_receipt_targets"]["shared"]["manifest"], scale_manifest)
        self.assertEqual(plan["expected_receipt_targets"]["shared"]["manifest_sha256"], scale_manifest_sha)
        self.assertEqual(plan["expected_receipt_targets"]["shared"]["workstream"], "W1_M6c_scale_up")
        self.assertEqual(plan["sections"][0]["manifest_sha256"], scale_manifest_sha)
        self.assertEqual(
            plan["expected_receipt_targets"]["unique"]["target_msa_report"],
            "hpc_outputs/targets/unique.a3m.report.json",
        )
        self.assertEqual(plan["expected_receipt_targets"]["unique"]["manifest"], panel_manifest)
        self.assertEqual(plan["expected_receipt_targets"]["unique"]["manifest_sha256"], panel_manifest_sha)
        self.assertEqual(plan["expected_receipt_targets"]["unique"]["workstream"], "W2_multi_target_panel")
        self.assertEqual(plan["sections"][1]["manifest_sha256"], panel_manifest_sha)
        self.assertEqual(saved["target_msa_precompute_receipt"]["status"], "missing_receipt")
        self.assertEqual(saved["target_msa_precompute_receipt"]["missing_target_ids"], ["shared", "unique"])
        self.assertEqual(plan["skipped_duplicate_target_ids"][0]["target_id"], "shared")
        self.assertEqual(plan_text.count("submitted target MSA job for shared"), 1)
        self.assertEqual(plan_text.count("submitted target MSA job for unique"), 1)
        self.assertIn("BIO_SFM_PYTHONPATH", plan_text)
        self.assertIn("TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT", plan_text)
        self.assertIn("BIO_SFM_PYTHON_BIN=\"$TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT\"", plan_text)
        self.assertIn("TARGET_MSA_PRECOMPUTE_RECEIPT", plan_text)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST={scale_manifest}", plan_text)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST={panel_manifest}", plan_text)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED={scale_manifest_sha}", plan_text)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED={panel_manifest_sha}", plan_text)
        self.assertIn("verify_target_msa_manifest_fresh() {", plan_text)
        self.assertIn("target-MSA precompute manifest is stale", plan_text)
        self.assertIn("target-MSA precompute requires SLURM sbatch", plan_text)
        self.assertIn("TARGET_MSA_PRECOMPUTE_DRY_RUN=1", plan_text)
        self.assertIn("receipt-safe local plan preview", plan_text)
        self.assertIn("target-MSA precompute dry-run", plan_text)
        self.assertIn("receipt untouched", plan_text)
        self.assertIn("will_block_real_submit", plan_text)
        self.assertIn("recorded_target_ids", plan_text)
        self.assertIn("helper_files", plan_text)
        self.assertIn("verify_target_msa_helper_files", plan_text)
        self.assertIn("helper_file_sha256_mismatch", plan_text)
        self.assertIn("boltz_runtime", plan_text)
        self.assertIn("verify_target_msa_boltz_runtime", plan_text)
        self.assertIn("Boltz runtime preflight failed", plan_text)
        self.assertIn("source_fasta_inputs", plan_text)
        self.assertIn("all_present_or_regenerable", plan_text)
        self.assertIn("regenerable_from_rcsb", plan_text)
        self.assertIn("verify_target_msa_source_fastas", plan_text)
        self.assertIn("target_fasta_missing_and_no_regeneration_source", plan_text)
        self.assertIn("target-MSA precompute dry-run", dry_run_stdout)
        self.assertIn("receipt untouched", dry_run_stdout)
        self.assertEqual(dry_run_payload["receipt"]["path"], dry_run_receipt)
        self.assertFalse(dry_run_payload["receipt"]["exists"])
        self.assertFalse(dry_run_payload["receipt"]["nonempty"])
        self.assertFalse(dry_run_payload["receipt"]["will_block_real_submit"])
        self.assertIsNone(dry_run_payload["receipt"]["preview"])
        self.assertEqual(dry_run_payload["helper_files"]["n_inputs"], 4)
        self.assertTrue(dry_run_payload["helper_files"]["all_present_nonempty_matching"])
        self.assertTrue(dry_run_payload["boltz_runtime"]["would_require_boltz_runtime"])
        self.assertEqual(dry_run_payload["boltz_runtime"]["n_target_msa_outputs"], 2)
        self.assertEqual(dry_run_payload["boltz_runtime"]["n_missing_target_msa_outputs"], 2)
        self.assertEqual(dry_run_payload["source_fasta_inputs"]["n_inputs"], 2)
        self.assertEqual(dry_run_payload["source_fasta_inputs"]["n_missing"], 2)
        self.assertEqual(dry_run_payload["source_fasta_inputs"]["n_blocked"], 2)
        self.assertFalse(dry_run_payload["source_fasta_inputs"]["all_present_nonempty"])
        self.assertFalse(dry_run_payload["source_fasta_inputs"]["all_present_or_regenerable"])
        self.assertFalse(dry_run_receipt_exists_after)
        self.assertEqual(source_guard.returncode, 2)
        self.assertIn("source FASTA preflight failed", source_guard.stderr)
        self.assertIn("target_fasta_missing_and_no_regeneration_source", source_guard.stderr)
        self.assertFalse(os.path.exists(source_guard_receipt))
        self.assertEqual(helper_guard.returncode, 2)
        self.assertIn("helper file preflight failed", helper_guard.stderr)
        self.assertIn("missing_helper_file", helper_guard.stderr)
        self.assertFalse(os.path.exists(helper_guard_receipt))
        self.assertEqual(runtime_guard.returncode, 2)
        self.assertIn("Boltz runtime preflight failed", runtime_guard.stderr)
        self.assertIn("missing_runtime_path", runtime_guard.stderr)
        self.assertFalse(os.path.exists(runtime_guard_receipt))
        self.assertEqual(existing_receipt_after, existing_receipt_before)
        self.assertTrue(existing_dry_run_payload["receipt"]["exists"])
        self.assertTrue(existing_dry_run_payload["receipt"]["nonempty"])
        self.assertTrue(existing_dry_run_payload["receipt"]["will_block_real_submit"])
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["recorded_target_ids"],
            ["shared"],
        )
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["valid_recorded_target_ids"],
            ["shared"],
        )
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["missing_target_ids"],
            ["unique"],
        )
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["missing_valid_target_ids"],
            ["unique"],
        )
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["status_counts"],
            {"submitted": 1},
        )
        self.assertEqual(
            existing_dry_run_payload["receipt"]["preview"]["validation_error_count"],
            0,
        )
        self.assertFalse(
            existing_dry_run_payload["receipt"]["preview"]["looks_complete_for_planned_targets"]
        )
        self.assertFalse(
            existing_dry_run_payload["receipt"]["preview"]["strictly_valid_for_planned_targets"]
        )
        self.assertEqual(
            mismatched_dry_run_payload["receipt"]["preview"]["recorded_target_ids"],
            ["shared"],
        )
        self.assertEqual(
            mismatched_dry_run_payload["receipt"]["preview"]["valid_recorded_target_ids"],
            [],
        )
        self.assertEqual(
            mismatched_dry_run_payload["receipt"]["preview"]["missing_valid_target_ids"],
            ["shared", "unique"],
        )
        self.assertGreater(
            mismatched_dry_run_payload["receipt"]["preview"]["validation_error_count"],
            0,
        )
        self.assertFalse(
            mismatched_dry_run_payload["receipt"]["preview"]["strictly_valid_for_planned_targets"]
        )
        self.assertIn(
            "receipt_field_mismatch",
            json.dumps(mismatched_dry_run_payload["receipt"]["preview"]["validation_errors"]),
        )
        self.assertIn(
            "invalid_job_id",
            json.dumps(mismatched_dry_run_payload["receipt"]["preview"]["validation_errors"]),
        )
        self.assertIn("TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH=1", plan_text)
        self.assertLess(
            plan_text.index("TARGET_MSA_PRECOMPUTE_DRY_RUN"),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )
        self.assertLess(
            plan_text.index("target-MSA precompute requires SLURM sbatch"),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )
        self.assertLess(
            plan_text.index("verify_target_msa_source_fastas"),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )
        self.assertLess(
            plan_text.index(
                "verify_target_msa_manifest_fresh "
                f"{shlex.quote(scale_manifest)} {scale_manifest_sha} W1_M6c_scale_up"
            ),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )
        self.assertIn("TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1", plan_text)
        self.assertLess(
            plan_text.index("receipt already exists and is non-empty"),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )
        self.assertIn("require_target_msa_job_id shared \"${MSA_00_SHARED}\"", plan_text)
        self.assertLess(
            plan_text.index("require_target_msa_job_id shared \"${MSA_00_SHARED}\""),
            plan_text.index("record_target_msa_precompute shared submitted"),
        )
        self.assertIn("record_target_msa_precompute shared submitted", plan_text)
        self.assertIn("validate_target_msa_precompute_receipt --expect-json", plan_text)
        self.assertIn("\"shared\":{\"manifest\"", plan_text)
        self.assertIn("\"unique\":{\"manifest\"", plan_text)
        self.assertIn("\"workstream\":\"W1_M6c_scale_up\"", plan_text)
        self.assertIn("\"workstream\":\"W2_multi_target_panel\"", plan_text)
        self.assertIn("\"target_msa\":\"hpc_outputs/targets/shared.a3m\"", plan_text)
        self.assertIn("\"target_msa\":\"hpc_outputs/targets/unique.a3m\"", plan_text)
        self.assertIn("# validate_project_target_msa_precompute_receipt", plan_text)
        self.assertIn(
            "TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET=1 "
            "validate_target_msa_precompute_receipt --expect-json",
            plan_text,
        )
        self.assertIn("' shared unique", plan_text)
        self.assertLess(
            plan_text.index("record_target_msa_precompute unique submitted"),
            plan_text.index("# validate_project_target_msa_precompute_receipt"),
        )
        self.assertIn("REMOTE_RECEIPT_SYNC_STATUS", remote_check_text)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_RECEIPT={receipt}", remote_check_text)
        self.assertIn("sync_target_msa_precompute_receipt", remote_check_text)
        self.assertIn("import hashlib, json, pathlib, sys", remote_check_text)
        self.assertIn("sha256 = hashlib.sha256(data).hexdigest()", remote_check_text)
        self.assertIn("'size_bytes': size_bytes", remote_check_text)
        self.assertIn("'sha256': sha256", remote_check_text)
        self.assertIn("target_msa_precompute_receipt_sync", remote_check_text)
        self.assertIn(
            "next: rerun project status with --external-remote-check-report $REMOTE_CHECK_REPORT",
            remote_check_text,
        )
        self.assertNotIn(f"next: bash {external_sync}", remote_check_text)
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        dry_run_command = f"TARGET_MSA_PRECOMPUTE_DRY_RUN=1 bash {precompute_plan}"
        self.assertEqual(plan["dry_run_command"], dry_run_command)
        self.assertEqual(roles["target_msa_precompute"]["command"], f"bash {precompute_plan}")
        self.assertEqual(roles["target_msa_precompute"]["dry_run_command"], dry_run_command)
        self.assertEqual(roles["target_msa_precompute"]["receipt"], receipt)
        self.assertTrue(roles["target_msa_precompute"]["recommended"])
        guard_audit = roles["target_msa_precompute"]["target_msa_receipt_validation_audit"]
        self.assertTrue(guard_audit["checked"])
        self.assertTrue(guard_audit["ok"])
        self.assertEqual(guard_audit["n_expected_targets"], 2)
        self.assertEqual(guard_audit["expected_min_validation_calls"], 3)
        self.assertGreaterEqual(guard_audit["validation_call_count"], 3)
        self.assertTrue(guard_audit["exact_expected_receipt_json_present"])
        self.assertTrue(guard_audit["strict_aggregate_validation_present"])
        self.assertTrue(guard_audit["dry_run_guard_present"])
        self.assertTrue(guard_audit["dry_run_before_receipt_truncate"])
        self.assertEqual(guard_audit["missing_markers"], [])
        self.assertEqual(saved["target_msa_precompute_script_validation_audit"]["status"], "ok")
        self.assertFalse(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["recommended_next_script"]["resume_preflight_status"], "waiting_on_cayuga_session")
        self.assertFalse(saved["recommended_next_script"]["ready_to_execute_now"])
        self.assertEqual(saved["operator_next_role"], "target_msa_precompute")
        self.assertEqual(saved["operator_preflight_command"], dry_run_command)
        self.assertEqual(saved["operator_next_command"], f"bash {precompute_plan}")
        self.assertIn(dry_run_command, saved["operator_next_action"])
        self.assertIn("helper/source FASTA guards", saved["operator_next_action"])
        self.assertIn("Boltz runtime readiness", saved["operator_next_action"])
        self.assertIn("without touching the receipt", saved["operator_next_action"])
        self.assertIn("Cayuga repo checkout", saved["operator_next_action"])
        self.assertIn("--external-remote-check-report", saved["operator_next_action"])
        self.assertIn("refreshed status recommends it", saved["operator_next_action"])
        self.assertEqual(
            saved["goal_progress_audit"]["first_action"]["preflight_command"],
            dry_run_command,
        )
        rendered = render_text(saved)
        self.assertIn(f"recommended_next_preflight: {dry_run_command}", rendered)
        self.assertIn(f"operator_preflight_command: {dry_run_command}", rendered)
        self.assertIn("--external-remote-check-report", saved["resume_bridge_preflight"]["next_action"])
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(
            [step["role"] for step in ladder],
            [
                "target_msa_precompute",
                "external_remote_check",
                "project_status_refresh",
                "external_sync_back",
                "post_sync_replay",
            ],
        )
        self.assertEqual(ladder[0]["status"], "waiting_on_cayuga_session")
        self.assertIn("--external-remote-check-report", ladder[0]["next_action"])
        self.assertIn("--external-remote-check-report", ladder[0]["preflight_next_action"])
        self.assertEqual(ladder[1]["status"], "blocked_until_target_msa_precompute_completes")
        self.assertEqual(ladder[1]["blocked_by"], "target_msa_precompute")
        self.assertEqual(ladder[2]["status"], "blocked_until_remote_check_passes")
        self.assertEqual(ladder[2]["blocked_by"], "external_remote_check")
        self.assertIn(
            f"--external-remote-check-report {os.path.splitext(remote_check)[0]}.json",
            ladder[2]["next_action"],
        )
        self.assertIn("target_msa_precompute_plan=targets:2", render_text(saved))
        self.assertIn("target_msa_precompute_script_validation_audit=ok targets=2", render_text(saved))
        self.assertIn(
            "resume_execution_ladder=target_msa_precompute:waiting_on_cayuga_session>external_remote_check:blocked_until_target_msa_precompute_completes",
            render_text(saved),
        )
        self.assertIn("target_msa_precompute_receipt=missing_receipt recorded=0/2", render_text(saved))
        self.assertIn("--emit-target-msa-precompute-plan", saved["self_command"])
        self.assertIn("--target-msa-precompute-receipt", saved["self_command"])

    def test_remote_check_stale_pending_external_manifest_fails_before_receipt_sync(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            target_manifest = os.path.join(d, "targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = f"results/test_{os.path.basename(d)}_target_msa_precompute_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            out = os.path.join(d, "status.json")

            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {
                        "kind": "missing_file",
                        "field": "target_msa",
                        "target_id": "t1",
                        "declared_path": "targets/t1.a3m",
                        "path": os.path.join(d, "targets/t1.a3m"),
                    },
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(target_manifest, {
                "targets": [{
                    "id": "t1",
                    "prepared_pdb": "targets/t1.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "targets/t1.fasta",
                    "target_fasta_report": "targets/t1.fasta.report.json",
                    "target_msa": "targets/t1.a3m",
                    "target_msa_report": "targets/t1.a3m.report.json",
                }],
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--panel-target-manifest", target_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--out", out,
            ])
            with open(remote_check) as fh:
                remote_check_text = fh.read()
            with open(pending_external, "a") as fh:
                fh.write("targets/stale-extra.a3m\n")

            fake_bin = os.path.join(d, "bin")
            fake_ssh = os.path.join(fake_bin, "ssh")
            ssh_log = os.path.join(d, "ssh.log")
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_ssh, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$SSH_LOG\"\n")
                fh.write("exit 1\n")
            os.chmod(fake_ssh, 0o755)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["SSH_LOG"] = ssh_log
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", remote_check], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("stale pending external path list", proc.stderr + proc.stdout)
        self.assertFalse(os.path.exists(ssh_log))
        self.assertFalse(os.path.exists(os.path.splitext(remote_check)[0] + ".json"))
        self.assertLess(
            remote_check_text.index("EXPECTED_PENDING_EXTERNAL_COUNT=1"),
            remote_check_text.index("sync_target_msa_precompute_receipt"),
        )

    def test_conflicting_duplicate_target_msa_precompute_plan_blocks_resume(self):
        with tempfile.TemporaryDirectory() as d:
            scale_input = os.path.join(d, "scale_input.json")
            scale_completion = os.path.join(d, "scale_completion.json")
            panel_input = os.path.join(d, "panel_input.json")
            scale_manifest = os.path.join(d, "scale_targets.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = f"results/test_{os.path.basename(d)}_target_msa_precompute_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            out = os.path.join(d, "status.json")

            scale_target = {
                "id": "shared",
                "prepared_pdb": "hpc_outputs/targets/shared.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "hpc_outputs/targets/shared.fasta",
                "target_fasta_report": "hpc_outputs/targets/shared.fasta.report.json",
                "target_msa": "hpc_outputs/targets/shared.a3m",
                "target_msa_report": "hpc_outputs/targets/shared.a3m.report.json",
            }
            panel_target = dict(scale_target)
            panel_target.update({
                "target_msa": "hpc_outputs/targets/shared_panel.a3m",
                "target_msa_report": "hpc_outputs/targets/shared_panel.a3m.report.json",
            })

            _write_json(scale_manifest, {"targets": [scale_target]})
            _write_json(panel_manifest, {"targets": [panel_target]})
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "blocked",
                "target_alpha": 0.2,
                "next_action": "run target_msa_precompute first",
            })
            _write_json(scale_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared_panel.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared_panel.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })

            main([
                "--scale-completion", scale_completion,
                "--scale-input-prep-completion", scale_input,
                "--panel-input-prep-completion", panel_input,
                "--scale-target-manifest", scale_manifest,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(precompute_plan) as fh:
                plan_text = fh.read()

        plan = saved["target_msa_precompute_plan"]
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["n_targets"], 1)
        self.assertEqual(plan["target_ids"], ["shared"])
        conflicts = plan["conflicting_duplicate_target_ids"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["target_id"], "shared")
        self.assertEqual(conflicts[0]["first_workstream"], "W1_M6c_scale_up")
        self.assertEqual(conflicts[0]["duplicate_workstream"], "W2_multi_target_panel")
        self.assertEqual(
            conflicts[0]["first_material"]["target_msa"],
            "hpc_outputs/targets/shared.a3m",
        )
        self.assertEqual(
            conflicts[0]["duplicate_material"]["target_msa"],
            "hpc_outputs/targets/shared_panel.a3m",
        )
        self.assertEqual(saved["target_msa_precompute_receipt"]["status"], "plan_conflict")
        self.assertEqual(
            saved["target_msa_precompute_receipt"]["conflicting_duplicate_target_ids"],
            conflicts,
        )
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertEqual(roles["target_msa_precompute"]["blockers"], ["target_msa_plan_conflicts"])
        self.assertTrue(roles["target_msa_precompute"]["blocked"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["recommended_next_script"]["blockers"], ["target_msa_plan_conflicts"])
        self.assertEqual(saved["resume_bridge_preflight"]["status"], "blocked")
        self.assertIn("target_msa_plan_conflicts", saved["resume_bridge_preflight"]["blockers"])
        self.assertEqual(saved["goal_progress_audit"]["status"], "local_replay_or_regeneration_required")
        self.assertEqual(
            saved["goal_progress_audit"]["local_blockers"][0]["kind"],
            "target_msa_plan_conflict",
        )
        self.assertIn("target_msa_precompute_plan_conflicts=1", render_text(saved))
        self.assertIn("target-MSA precompute plan has conflicting duplicate target ids", plan_text)
        self.assertIn("hpc_outputs/targets/shared_panel.a3m", plan_text)
        self.assertLess(
            plan_text.index("conflicting duplicate target ids"),
            plan_text.index(": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""),
        )

    def test_complete_target_msa_precompute_receipt_unblocks_remote_check(self):
        with tempfile.TemporaryDirectory() as d:
            scale_input = os.path.join(d, "scale_input.json")
            scale_completion = os.path.join(d, "scale_completion.json")
            panel_input = os.path.join(d, "panel_input.json")
            scale_manifest = os.path.join(d, "scale_targets.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            out = os.path.join(d, "status.json")
            fake_bin = os.path.join(d, "bin")
            fake_rsync = os.path.join(fake_bin, "rsync")
            rsync_log = os.path.join(d, "rsync.log")

            def target(target_id):
                return {
                    "id": target_id,
                    "prepared_pdb": f"hpc_outputs/targets/{target_id}.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": f"hpc_outputs/targets/{target_id}.fasta",
                    "target_fasta_report": f"hpc_outputs/targets/{target_id}.fasta.report.json",
                    "target_msa": f"hpc_outputs/targets/{target_id}.a3m",
                    "target_msa_report": f"hpc_outputs/targets/{target_id}.a3m.report.json",
                }

            _write_json(scale_manifest, {"targets": [target("shared")]})
            _write_json(panel_manifest, {"targets": [target("shared"), target("unique")]})
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "blocked",
                "target_alpha": 0.2,
                "next_action": "run target_msa_precompute first",
            })
            _write_json(scale_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 4,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 4,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared", "unique"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}, "unique": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "shared",
                    "status": "submitted",
                    "job_id": "101",
                    "target_fasta": "hpc_outputs/targets/shared.fasta",
                    "target_msa": "hpc_outputs/targets/shared.a3m",
                    "target_msa_report": "hpc_outputs/targets/shared.a3m.report.json",
                    "manifest": scale_manifest,
                    "manifest_sha256": _sha256_file(scale_manifest),
                    "workstream": "W1_M6c_scale_up",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "unique",
                    "status": "validated_existing",
                    "target_fasta": "hpc_outputs/targets/unique.fasta",
                    "target_msa": "hpc_outputs/targets/unique.a3m",
                    "target_msa_report": "hpc_outputs/targets/unique.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": _sha256_file(panel_manifest),
                    "workstream": "W2_multi_target_panel",
                }) + "\n")
            main([
                "--scale-completion", scale_completion,
                "--scale-input-prep-completion", scale_input,
                "--panel-input-prep-completion", panel_input,
                "--scale-target-manifest", scale_manifest,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)
            receipt_sha = _sha256_file(receipt)
            with open(external_sync) as fh:
                external_sync_text = fh.read()
            os.makedirs(fake_bin, exist_ok=True)
            with open(fake_rsync, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("echo \"$*\" >> \"$RSYNC_LOG\"\n")
                fh.write("exit 99\n")
            os.chmod(fake_rsync, 0o755)
            os.remove(receipt)
            env = os.environ.copy()
            env["CAYUGA_BIO_SFM_ROOT"] = "remote:/scratch/bio_sfm_designer"
            env["RSYNC_LOG"] = rsync_log
            env["PATH"] = os.pathsep.join([fake_bin, env.get("PATH", "")])
            proc = subprocess.run(["bash", external_sync], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)

        receipt_status = saved["target_msa_precompute_receipt"]
        self.assertTrue(receipt_status["ok"])
        self.assertEqual(receipt_status["status"], "satisfied")
        self.assertEqual(receipt_status["sha256"], receipt_sha)
        self.assertEqual(receipt_status["recorded_target_ids"], ["shared", "unique"])
        self.assertIn(f"TARGET_MSA_RECEIPT_PATH={receipt}", external_sync_text)
        self.assertIn(f"TARGET_MSA_RECEIPT_SHA256={receipt_sha}", external_sync_text)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("target-MSA precompute receipt is missing or empty", proc.stderr)
        self.assertFalse(os.path.exists(rsync_log))
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertFalse(roles["target_msa_precompute"]["recommended"])
        self.assertTrue(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertEqual(saved["operator_next_role"], "external_remote_check")
        ladder = saved["resume_execution_ladder"]["steps"]
        self.assertEqual(ladder[0]["role"], "target_msa_precompute")
        self.assertEqual(ladder[0]["status"], "satisfied")
        self.assertEqual(ladder[1]["role"], "external_remote_check")
        self.assertEqual(ladder[1]["status"], "waiting_on_env")
        self.assertIn(
            "resume_execution_ladder=target_msa_precompute:satisfied>external_remote_check:waiting_on_env",
            render_text(saved),
        )

    def test_existing_target_msa_outputs_prevent_stale_receipt_from_stealing_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            panel_input = os.path.join(d, "panel_input.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            predictor_contract = os.path.join(d, "predictor_contract.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            out = os.path.join(d, "status.json")
            target_msa = os.path.join(d, "targets/t1.a3m")
            target_msa_report = os.path.join(d, "targets/t1.a3m.report.json")
            os.makedirs(os.path.dirname(target_msa), exist_ok=True)
            with open(target_msa, "w") as fh:
                fh.write(">t1\nAAAA\n")
            _write_json(target_msa_report, {"ok": True})
            _write_json(panel_manifest, {"targets": [{
                "id": "t1",
                "prepared_pdb": os.path.join(d, "targets/t1.pdb"),
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": os.path.join(d, "targets/t1.fasta"),
                "target_fasta_report": os.path.join(d, "targets/t1.fasta.report.json"),
                "target_msa": target_msa,
                "target_msa_report": target_msa_report,
            }]})
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": target_msa},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1", "path": target_msa_report},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })
            _write_json(predictor_contract, {
                "ok": False,
                "secondary_predictor": {"id": "chai1"},
                "secondary_records": os.path.join(d, "remote/chai_records.jsonl"),
                "pending_secondary_records": [
                    {
                        "path": os.path.join(d, "remote/chai_records.jsonl"),
                        "absolute_path": os.path.join(d, "remote/chai_records.jsonl"),
                        "field": "secondary_records",
                        "status": "missing",
                    }
                ],
                "failures": [{"kind": "missing_file", "field": "secondary_records"}],
                "commands": {},
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "t1",
                    "status": "submitted",
                    "job_id": "101",
                    "target_fasta": os.path.join(d, "targets/t1.fasta"),
                    "target_msa": target_msa,
                    "target_msa_report": target_msa_report,
                    "manifest": panel_manifest,
                    "manifest_sha256": _sha256_file(panel_manifest),
                    "workstream": "W2_multi_target_panel",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "old_extra",
                    "status": "submitted",
                    "job_id": "102",
                }) + "\n")

            old_env = os.environ.pop("CAYUGA_BIO_SFM_ROOT", None)
            try:
                main([
                    "--panel-input-prep-completion", panel_input,
                    "--panel-target-manifest", panel_manifest,
                    "--predictor-contract-report", predictor_contract,
                    "--emit-target-msa-precompute-plan", precompute_plan,
                    "--target-msa-precompute-receipt", receipt,
                    "--emit-pending-external-paths", pending_external,
                    "--emit-external-remote-check-plan", remote_check,
                    "--emit-external-sync-back-plan", external_sync,
                    "--out", out,
                ])
            finally:
                if old_env is not None:
                    os.environ["CAYUGA_BIO_SFM_ROOT"] = old_env
            with open(out) as fh:
                saved = json.load(fh)
            with open(external_sync) as fh:
                external_sync_text = fh.read()

        self.assertFalse(saved["target_msa_precompute_receipt"]["ok"])
        self.assertEqual(saved["target_msa_precompute_receipt"]["unexpected_target_ids"], ["old_extra"])
        self.assertTrue(saved["target_msa_precompute_outputs_satisfied"])
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertFalse(roles["target_msa_precompute"]["recommended"])
        self.assertNotIn("blockers", roles["target_msa_precompute"])
        self.assertTrue(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "external_remote_check")
        self.assertNotEqual(saved["operator_next_role"], "target_msa_precompute")
        self.assertIn("TARGET_MSA_RECEIPT_REQUIRED=0", external_sync_text)

    def test_target_msa_precompute_receipt_submitted_requires_job_id(self):
        with tempfile.TemporaryDirectory() as d:
            panel_input = os.path.join(d, "panel_input.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            out = os.path.join(d, "status.json")

            def target(target_id):
                return {
                    "id": target_id,
                    "prepared_pdb": f"hpc_outputs/targets/{target_id}.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": f"hpc_outputs/targets/{target_id}.fasta",
                    "target_fasta_report": f"hpc_outputs/targets/{target_id}.fasta.report.json",
                    "target_msa": f"hpc_outputs/targets/{target_id}.a3m",
                    "target_msa_report": f"hpc_outputs/targets/{target_id}.a3m.report.json",
                }

            _write_json(panel_manifest, {"targets": [target("t1"), target("t2")]})
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 4,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 4,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1", "t2"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m.report.json"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t2", "path": "hpc_outputs/targets/t2.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t2", "path": "hpc_outputs/targets/t2.a3m.report.json"},
                ],
                "artifacts_by_target": {"t1": {"ready": False}, "t2": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "t1",
                    "status": "submitted",
                    "target_fasta": "hpc_outputs/targets/t1.fasta",
                    "target_msa": "hpc_outputs/targets/t1.a3m",
                    "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": _sha256_file(panel_manifest),
                    "workstream": "W2_multi_target_panel",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "t2",
                    "status": "submitted",
                    "job_id": "Submitted batch job 102",
                    "target_fasta": "hpc_outputs/targets/t2.fasta",
                    "target_msa": "hpc_outputs/targets/t2.a3m",
                    "target_msa_report": "hpc_outputs/targets/t2.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": _sha256_file(panel_manifest),
                    "workstream": "W2_multi_target_panel",
                }) + "\n")

            main([
                "--panel-input-prep-completion", panel_input,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        receipt_status = saved["target_msa_precompute_receipt"]
        self.assertFalse(receipt_status["ok"])
        self.assertEqual(receipt_status["status"], "incomplete_receipt")
        missing_job = next(record for record in receipt_status["bad_records"]
                           if record.get("error") == "missing_job_id")
        self.assertEqual(missing_job["target_id"], "t1")
        invalid_job = next(record for record in receipt_status["bad_records"]
                           if record.get("error") == "invalid_job_id")
        self.assertEqual(invalid_job["target_id"], "t2")
        self.assertEqual(invalid_job["job_id"], "Submitted batch job 102")
        self.assertEqual(receipt_status["resume_blocker"], "target_msa_receipt_requires_review")
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(roles["target_msa_precompute"]["recommended"])
        self.assertEqual(roles["target_msa_precompute"]["blockers"], ["target_msa_receipt_requires_review"])
        self.assertFalse(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["resume_bridge_preflight"]["status"], "blocked")
        self.assertIn("target_msa_receipt_requires_review", saved["resume_bridge_preflight"]["blockers"])
        self.assertIn("inspect or archive the existing target-MSA precompute receipt", saved["operator_next_action"])
        self.assertNotIn("--external-remote-check-report", saved["operator_next_action"])
        self.assertNotIn("--external-remote-check-report", saved["resume_bridge_preflight"]["next_action"])
        self.assertIn("target_msa_precompute_receipt_blocker=target_msa_receipt_requires_review", render_text(saved))

    def test_nonrequired_target_msa_precompute_ignores_old_receipt_rows(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "target_msa_precompute_receipt.jsonl")
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "old_target",
                    "status": "submitted",
                    "job_id": "12345",
                }) + "\n")
            rep = {
                "target_msa_precompute_plan": {
                    "target_ids": [],
                    "expected_receipt_targets": {},
                }
            }

            attach_target_msa_precompute_receipt(
                rep,
                args=argparse.Namespace(target_msa_precompute_receipt=receipt),
            )

        receipt_status = rep["target_msa_precompute_receipt"]
        self.assertEqual(receipt_status["status"], "not_required")
        self.assertTrue(receipt_status["ok"])
        self.assertTrue(receipt_status["fresh"])
        self.assertEqual(receipt_status["n_expected"], 0)
        self.assertEqual(receipt_status["unexpected_target_ids"], [])
        self.assertNotIn("resume_blocker", receipt_status)

    def test_target_msa_precompute_receipt_provenance_mismatch_blocks_remote_check(self):
        with tempfile.TemporaryDirectory() as d:
            panel_input = os.path.join(d, "panel_input.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            out = os.path.join(d, "status.json")

            _write_json(panel_manifest, {"targets": [{
                "id": "t1",
                "prepared_pdb": "hpc_outputs/targets/t1.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "hpc_outputs/targets/t1.fasta",
                "target_fasta_report": "hpc_outputs/targets/t1.fasta.report.json",
                "target_msa": "hpc_outputs/targets/t1.a3m",
                "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
            }]})
            panel_manifest_sha = _sha256_file(panel_manifest)
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m.report.json"},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "t1",
                    "status": "submitted",
                    "job_id": "101",
                    "target_fasta": "hpc_outputs/targets/t1.fasta",
                    "target_msa": "hpc_outputs/targets/t1.a3m",
                    "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": _sha256_file(panel_manifest),
                    "workstream": "W1_M6c_scale_up",
                }) + "\n")

            main([
                "--panel-input-prep-completion", panel_input,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        receipt_status = saved["target_msa_precompute_receipt"]
        self.assertFalse(receipt_status["ok"])
        self.assertEqual(receipt_status["status"], "incomplete_receipt")
        mismatch = next(record for record in receipt_status["bad_records"]
                        if record.get("field") == "workstream")
        self.assertEqual(mismatch["expected"], "W2_multi_target_panel")
        self.assertEqual(mismatch["actual"], "W1_M6c_scale_up")
        self.assertEqual(receipt_status["resume_blocker"], "target_msa_receipt_requires_review")
        self.assertGreater(receipt_status["size_bytes"], 0)
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(roles["target_msa_precompute"]["recommended"])
        self.assertEqual(roles["target_msa_precompute"]["blockers"], ["target_msa_receipt_requires_review"])
        self.assertFalse(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["recommended_next_script"]["blockers"], ["target_msa_receipt_requires_review"])
        self.assertEqual(saved["resume_bridge_preflight"]["status"], "blocked")
        self.assertIn("target_msa_receipt_requires_review", saved["resume_bridge_preflight"]["blockers"])
        self.assertEqual(saved["goal_progress_audit"]["status"], "local_replay_or_regeneration_required")
        self.assertEqual(
            saved["goal_progress_audit"]["local_blockers"][0]["kind"],
            "target_msa_receipt_requires_review",
        )
        self.assertIn("target_msa_precompute_receipt_blocker=target_msa_receipt_requires_review", render_text(saved))

    def test_target_msa_precompute_receipt_manifest_hash_mismatch_blocks_remote_check(self):
        with tempfile.TemporaryDirectory() as d:
            panel_input = os.path.join(d, "panel_input.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            out = os.path.join(d, "status.json")

            _write_json(panel_manifest, {"targets": [{
                "id": "t1",
                "prepared_pdb": "hpc_outputs/targets/t1.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "hpc_outputs/targets/t1.fasta",
                "target_fasta_report": "hpc_outputs/targets/t1.fasta.report.json",
                "target_msa": "hpc_outputs/targets/t1.a3m",
                "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
            }]})
            panel_manifest_sha = _sha256_file(panel_manifest)
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1", "path": "hpc_outputs/targets/t1.a3m.report.json"},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "t1",
                    "status": "validated_existing",
                    "target_fasta": "hpc_outputs/targets/t1.fasta",
                    "target_msa": "hpc_outputs/targets/t1.a3m",
                    "target_msa_report": "hpc_outputs/targets/t1.a3m.report.json",
                    "manifest": panel_manifest,
                    "manifest_sha256": "stale-manifest-hash",
                    "workstream": "W2_multi_target_panel",
                }) + "\n")

            main([
                "--panel-input-prep-completion", panel_input,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--target-msa-precompute-receipt", receipt,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        receipt_status = saved["target_msa_precompute_receipt"]
        self.assertFalse(receipt_status["ok"])
        self.assertEqual(receipt_status["status"], "incomplete_receipt")
        mismatch = next(record for record in receipt_status["bad_records"]
                        if record.get("field") == "manifest_sha256")
        self.assertEqual(mismatch["expected"], panel_manifest_sha)
        self.assertEqual(mismatch["actual"], "stale-manifest-hash")
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(roles["target_msa_precompute"]["recommended"])
        self.assertFalse(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")

    def test_stale_target_msa_precompute_receipt_path_mismatch_blocks_remote_check(self):
        with tempfile.TemporaryDirectory() as d:
            scale_input = os.path.join(d, "scale_input.json")
            scale_completion = os.path.join(d, "scale_completion.json")
            panel_input = os.path.join(d, "panel_input.json")
            scale_manifest = os.path.join(d, "scale_targets.json")
            panel_manifest = os.path.join(d, "panel_targets.json")
            precompute_plan = os.path.join(d, "target_msa_precompute.sh")
            receipt = os.path.splitext(precompute_plan)[0] + "_receipt.jsonl"
            pending_external = os.path.join(d, "pending_external.txt")
            remote_check = os.path.join(d, "remote_check.sh")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            out = os.path.join(d, "status.json")

            def target(target_id):
                return {
                    "id": target_id,
                    "prepared_pdb": f"hpc_outputs/targets/{target_id}.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": f"hpc_outputs/targets/{target_id}.fasta",
                    "target_fasta_report": f"hpc_outputs/targets/{target_id}.fasta.report.json",
                    "target_msa": f"hpc_outputs/targets/{target_id}.a3m",
                    "target_msa_report": f"hpc_outputs/targets/{target_id}.a3m.report.json",
                }

            _write_json(scale_manifest, {"targets": [target("shared")]})
            _write_json(panel_manifest, {"targets": [target("shared"), target("unique")]})
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "blocked",
                "target_alpha": 0.2,
                "next_action": "run target_msa_precompute first",
            })
            _write_json(scale_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 2,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            _write_json(panel_input, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 4,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 4,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["shared", "unique"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "shared", "path": "hpc_outputs/targets/shared.a3m.report.json"},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "unique", "path": "hpc_outputs/targets/unique.a3m.report.json"},
                ],
                "artifacts_by_target": {"shared": {"ready": False}, "unique": {"ready": False}},
                "failures": [],
                "next_action": "sync/fix",
            })
            with open(receipt, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "shared",
                    "status": "submitted",
                    "job_id": "101",
                    "target_fasta": "hpc_outputs/targets/shared.fasta",
                    "target_msa": "hpc_outputs/targets/old_shared.a3m",
                    "target_msa_report": "hpc_outputs/targets/shared.a3m.report.json",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "unique",
                    "status": "validated_existing",
                    "target_fasta": "hpc_outputs/targets/unique.fasta",
                    "target_msa": "hpc_outputs/targets/unique.a3m",
                    "target_msa_report": "hpc_outputs/targets/unique.a3m.report.json",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "unique",
                    "status": "validated_existing",
                    "target_fasta": "hpc_outputs/targets/unique.fasta",
                    "target_msa": "hpc_outputs/targets/unique.a3m",
                    "target_msa_report": "hpc_outputs/targets/unique.a3m.report.json",
                }) + "\n")
                fh.write(json.dumps({
                    "target_id": "extra",
                    "status": "validated_existing",
                    "target_fasta": "hpc_outputs/targets/extra.fasta",
                    "target_msa": "hpc_outputs/targets/extra.a3m",
                    "target_msa_report": "hpc_outputs/targets/extra.a3m.report.json",
                }) + "\n")

            main([
                "--scale-completion", scale_completion,
                "--scale-input-prep-completion", scale_input,
                "--panel-input-prep-completion", panel_input,
                "--scale-target-manifest", scale_manifest,
                "--panel-target-manifest", panel_manifest,
                "--emit-target-msa-precompute-plan", precompute_plan,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-remote-check-plan", remote_check,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        receipt_status = saved["target_msa_precompute_receipt"]
        self.assertFalse(receipt_status["ok"])
        self.assertEqual(receipt_status["status"], "incomplete_receipt")
        errors = {record["error"] for record in receipt_status["bad_records"]}
        self.assertEqual(errors, {"receipt_field_mismatch", "duplicate_target_id", "unexpected_target_id"})
        self.assertEqual(receipt_status["unexpected_target_ids"], ["extra"])
        mismatch = next(record for record in receipt_status["bad_records"]
                        if record["error"] == "receipt_field_mismatch")
        self.assertEqual(mismatch["field"], "target_msa")
        self.assertEqual(mismatch["expected"], "hpc_outputs/targets/shared.a3m")
        roles = {script["role"]: script for script in saved["generated_scripts"]}
        self.assertTrue(roles["target_msa_precompute"]["recommended"])
        self.assertFalse(roles["external_remote_check"]["recommended"])
        self.assertEqual(saved["recommended_next_script"]["role"], "target_msa_precompute")
        self.assertEqual(saved["operator_next_role"], "target_msa_precompute")

    def test_goal_progress_audit_allows_complete_only_when_w1_to_w4_complete(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": _complete_goal_workstreams(d),
                **_posthoc_science_claims_ok(),
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "goal_complete")
        self.assertTrue(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 0)
        self.assertTrue(all(item["evidence_ok"] for item in audit["requirements"]))
        self.assertEqual(audit["completion_note"], "all W1-W4 requirements complete")
        self.assertEqual(rep["goal_progress"], "goal_complete")
        self.assertTrue(rep["can_mark_goal_complete"])
        self.assertEqual(rep["remaining_requirements"], 0)
        self.assertEqual(rep["remaining"], 0)
        self.assertEqual(rep["goal_completion_note"], "all W1-W4 requirements complete")

    def test_goal_progress_audit_rejects_w1_terminal_without_claim_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": _complete_goal_workstreams(d),
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 0)
        self.assertEqual(audit["local_blockers"][0]["kind"], "posthoc_science_claims_missing")
        self.assertEqual(audit["local_blockers"][0]["status"], "certified")
        self.assertEqual(audit["local_blockers"][0]["missing_sections"], [
            "supported",
            "not_yet_supported",
            "planning_diagnostics",
            "decisive_next",
        ])
        self.assertIn("claim IDs", audit["local_blockers"][0]["next_action"])

    def test_goal_progress_audit_rejects_w1_terminal_with_partial_claim_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": _complete_goal_workstreams(d),
                "posthoc_science_claims": {
                    "source": "posthoc_manifest",
                    "supported": ["complex_pae_interaction_signal"],
                },
                "posthoc_science_claims_audit": {"ok": True, "status": "ok"},
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 0)
        self.assertEqual(audit["local_blockers"][0]["kind"], "posthoc_science_claims_missing")
        self.assertEqual(audit["local_blockers"][0]["missing_sections"], [
            "not_yet_supported",
            "planning_diagnostics",
            "decisive_next",
        ])
        self.assertIn("claim IDs", audit["local_blockers"][0]["next_action"])

    def test_goal_progress_audit_rejects_noncanonical_terminal_statuses(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": _complete_goal_workstreams(d, {
                    "W1_M6c_scale_up": "certified",
                    "W2_multi_target_panel": "panel_report_complete",
                    "W3_independent_predictor": "cross_predictor_complete",
                    "W4_closed_loop_DBTL": "closed_loop_round_complete",
                }),
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 2)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_status_mismatch")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W2_multi_target_panel"]["raw_complete"])
        self.assertFalse(by_id["W2_multi_target_panel"]["status_complete"])
        self.assertEqual(by_id["W2_multi_target_panel"]["accepted_statuses"], ["multi_target_certified"])
        self.assertTrue(by_id["W3_independent_predictor"]["raw_complete"])
        self.assertFalse(by_id["W3_independent_predictor"]["status_complete"])
        self.assertEqual(
            by_id["W3_independent_predictor"]["accepted_statuses"],
            ["cross_predictor_ready", "negative_robustness_result_adjudicated"],
        )
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertEqual(rep["remaining_requirements"], 2)

    def test_goal_progress_audit_rejects_complete_without_evidence_artifacts(self):
        rep = {
            "complete": True,
            "next_action": "move to de-novo binder generation",
            "workstreams": {
                "W1_M6c_scale_up": {
                    "complete": True,
                    "status": "certified",
                    "evidence": "missing/w1.json",
                    "next_action": "done",
                },
                "W2_multi_target_panel": {
                    "complete": True,
                    "status": "multi_target_certified",
                    "evidence": "missing/w2.json",
                    "next_action": "done",
                },
                "W3_independent_predictor": {
                    "complete": True,
                    "status": "cross_predictor_ready",
                    "evidence": "missing/w3.json",
                    "next_action": "done",
                },
                "W4_closed_loop_DBTL": {
                    "complete": True,
                    "status": "closed_loop_round_complete",
                    "evidence": "missing/w4.json",
                    "next_action": "done",
                },
            },
        }
        attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 4)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_evidence_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W1_M6c_scale_up"]["status_complete"])
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_ok"])
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_file_ok"])
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_supports_status"])
        self.assertEqual(by_id["W1_M6c_scale_up"]["evidence_missing_paths"], ["missing/w1.json"])
        self.assertFalse(rep["can_mark_goal_complete"])

    def test_goal_progress_audit_rejects_terminal_status_with_bad_evidence_content(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w1_evidence = workstreams["W1_M6c_scale_up"]["evidence"]
            _write_json(w1_evidence, {"ok": True, "decision": "continue_scale"})
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_evidence_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W1_M6c_scale_up"]["evidence_file_ok"])
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_supports_status"])
        blocker_req = audit["local_blockers"][0]["requirements"][0]
        self.assertEqual(blocker_req["id"], "W1_M6c_scale_up")
        self.assertFalse(blocker_req["supports_status"])
        self.assertEqual(blocker_req["status"], "certified")

    def test_goal_progress_audit_rejects_w1_without_strict_alpha_decision_audit(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w1_evidence = workstreams["W1_M6c_scale_up"]["evidence"]
            _write_json(w1_evidence, {
                "ok": True,
                "decision": "stop_certified",
                "target_alpha": 0.2,
                "n_records": 500,
                "certified_alphas": [0.2],
                "estimated_additional_records": 0,
                "next_batch": {"action": "none", "target_alpha": 0.2, "recommended_total_candidates": 0},
            })
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W1_M6c_scale_up"]["evidence_file_ok"])
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w1_pending_next_batch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w1_evidence = workstreams["W1_M6c_scale_up"]["evidence"]
            report = _alpha_decision_ready_report()
            report["next_batch"] = {
                "action": "run_scale_batch",
                "target_alpha": 0.2,
                "recommended_total_candidates": 300,
            }
            _write_json(w1_evidence, report)
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w1_uncertified_target_sweep(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w1_evidence = workstreams["W1_M6c_scale_up"]["evidence"]
            report = _alpha_decision_ready_report()
            report["target_sweep"]["certified"] = False
            _write_json(w1_evidence, report)
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertFalse(by_id["W1_M6c_scale_up"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w2_without_target_certificates(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w2_evidence = workstreams["W2_multi_target_panel"]["evidence"]
            _write_json(w2_evidence, {
                "ok": True,
                "panel_status": "multi_target_certified",
                "n_targets": 3,
                "n_records": 900,
                "failures": [],
            })
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_evidence_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W2_multi_target_panel"]["evidence_file_ok"])
        self.assertFalse(by_id["W2_multi_target_panel"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w3_without_strict_cross_predictor_audit(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w3_evidence = workstreams["W3_independent_predictor"]["evidence"]
            _write_json(w3_evidence, {
                "ok": True,
                "status": "cross_predictor_ready",
                "predictors": ["boltz2_complex", "chai1_complex"],
                "records_by_predictor": {"boltz2_complex": 10, "chai1_complex": 10},
                "failures": [],
            })
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_evidence_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W3_independent_predictor"]["evidence_file_ok"])
        self.assertFalse(by_id["W3_independent_predictor"]["evidence_supports_status"])
        blocker_req = audit["local_blockers"][0]["requirements"][0]
        self.assertEqual(blocker_req["id"], "W3_independent_predictor")
        self.assertFalse(blocker_req["supports_status"])

    def test_goal_progress_audit_rejects_w3_inconsistent_record_file_predictors(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w3_evidence = workstreams["W3_independent_predictor"]["evidence"]
            report = _cross_predictor_ready_report(n=10)
            report["record_files"][1]["predictors"] = ["boltz2_complex"]
            report["record_files"][1]["records_by_predictor"] = {"boltz2_complex": 10}
            _write_json(w3_evidence, report)
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W3_independent_predictor"]["evidence_file_ok"])
        self.assertFalse(by_id["W3_independent_predictor"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w3_without_pair_audit(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w3_evidence = workstreams["W3_independent_predictor"]["evidence"]
            report = _cross_predictor_ready_report(n=10)
            report.pop("pairs")
            _write_json(w3_evidence, report)
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W3_independent_predictor"]["evidence_file_ok"])
        self.assertFalse(by_id["W3_independent_predictor"]["evidence_supports_status"])

    def test_goal_progress_audit_rejects_w4_shallow_terminal_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            shallow_evidence = os.path.join(d, "W4_closed_loop_DBTL.shallow.json")
            _write_json(shallow_evidence, {
                "ok": True,
                "status": "closed_loop_round_complete",
            })
            w4["evidence"] = shallow_evidence
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_evidence_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W4_closed_loop_DBTL"]["evidence_file_ok"])
        self.assertFalse(by_id["W4_closed_loop_DBTL"]["evidence_supports_status"])
        self.assertFalse(by_id["W4_closed_loop_DBTL"]["evidence_ok"])
        self.assertTrue(by_id["W4_closed_loop_DBTL"]["supporting_artifact_ok"])
        blocker_req = audit["local_blockers"][0]["requirements"][0]
        self.assertEqual(blocker_req["id"], "W4_closed_loop_DBTL")
        self.assertFalse(blocker_req["supports_status"])

    def test_goal_progress_audit_rejects_w4_without_supporting_campaign(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            os.remove(workstreams["W4_closed_loop_DBTL"]["campaign"])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_supporting_artifact_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W4_closed_loop_DBTL"]["evidence_ok"])
        self.assertFalse(by_id["W4_closed_loop_DBTL"]["supporting_artifact_ok"])
        missing = by_id["W4_closed_loop_DBTL"]["supporting_artifact_missing"]
        self.assertEqual(missing[0]["role"], "campaign")
        self.assertEqual(missing[0]["reason"], "missing_file")

    def test_goal_progress_audit_rejects_w4_campaign_count_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
            })
            _write_jsonl(w4["campaign"], [{"candidate_id": "c0", "action": "verify_assay"}])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 1)
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_supporting_artifact_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        self.assertTrue(by_id["W4_closed_loop_DBTL"]["evidence_ok"])
        self.assertFalse(by_id["W4_closed_loop_DBTL"]["supporting_artifact_ok"])
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        mismatch = next(error for error in content_errors if error["field"] == "campaign_record_count")
        self.assertEqual(mismatch["expected"], 2)
        self.assertEqual(mismatch["actual"], 1)

    def test_goal_progress_audit_rejects_w4_duplicate_campaign_candidate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
            })
            _write_jsonl(w4["campaign"], [
                {"candidate_id": "c0", "action": "verify_assay"},
                {"candidate_id": "c0", "action": "trust_sfm"},
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_supporting_artifact_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        duplicate = next(error for error in content_errors
                         if error["field"] == "campaign_candidate_id_unique")
        self.assertEqual(duplicate["candidate_ids"], ["c0"])

    def test_goal_progress_audit_rejects_w4_unknown_campaign_action(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_jsonl(w4["campaign"], [{"candidate_id": "c0", "action": "manual_override"}])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["local_blockers"][0]["kind"], "goal_requirement_supporting_artifact_invalid")
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        invalid = next(error for error in content_errors
                       if error["field"] == "campaign_action_allowed")
        self.assertEqual(invalid["records"], [{"line": 1, "action": "manual_override"}])

    def test_goal_progress_audit_rejects_w4_campaign_action_rate_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {
                    "n": 2,
                    "trust_rate": 0.5,
                    "verify_rate": 0.5,
                    "default_rate": 0.0,
                    "defer_rate": 0.0,
                },
            })
            _write_jsonl(w4["campaign"], [
                {"candidate_id": "c0", "action": "verify_assay"},
                {"candidate_id": "c1", "action": "verify_assay"},
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        action_rates = next(error for error in content_errors
                            if error["field"] == "campaign_action_rates")
        by_field = {item["rate_field"]: item for item in action_rates["mismatches"]}
        self.assertEqual(by_field["trust_rate"]["actual_rate"], 0.0)
        self.assertEqual(by_field["verify_rate"]["actual_rate"], 1.0)

    def test_goal_progress_audit_rejects_w4_campaign_assay_count_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "assays_used": 1,
                "gate_calibrated": True,
                "aggregate": {"n": 2},
            })
            _write_jsonl(w4["campaign"], [
                {"candidate_id": "c0", "action": "verify_assay"},
                {"candidate_id": "c1", "action": "verify_assay"},
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        assays_used = next(error for error in content_errors
                           if error["field"] == "campaign_assays_used")
        self.assertEqual(assays_used["mismatches"][0]["field"], "assays_used")
        self.assertEqual(assays_used["mismatches"][0]["expected"], 1)
        self.assertEqual(assays_used["mismatches"][0]["actual"], 2)

    def test_goal_progress_audit_rejects_w4_campaign_best_quality_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
                "best": {"candidate_id": "c0", "realized_quality": 0.9, "round": 0},
            })
            _write_jsonl(w4["campaign"], [
                {
                    "round": 0,
                    "candidate_id": "c0",
                    "action": "trust_sfm",
                    "hidden_truth": {"quality": 0.7},
                },
                {
                    "round": 0,
                    "candidate_id": "c1",
                    "action": "defer",
                    "hidden_truth": {"quality": 0.1},
                },
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        best = next(error for error in content_errors
                    if error["field"] == "campaign_best")
        self.assertEqual(best["mismatches"][0]["field"], "best.realized_quality")
        self.assertEqual(best["mismatches"][0]["candidate_id"], "c0")
        self.assertEqual(best["mismatches"][0]["expected"], 0.7)
        self.assertEqual(best["mismatches"][0]["actual"], 0.9)

    def test_goal_progress_audit_rejects_w4_campaign_best_verified_action(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
                "best": {"candidate_id": "c0", "realized_quality": 0.7, "round": 0},
            })
            _write_jsonl(w4["campaign"], [
                {
                    "round": 0,
                    "candidate_id": "c0",
                    "action": "verify_assay",
                    "hidden_truth": {"quality": 0.7},
                },
                {
                    "round": 0,
                    "candidate_id": "c1",
                    "action": "defer",
                    "hidden_truth": {"quality": 0.1},
                },
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        best = next(error for error in content_errors
                    if error["field"] == "campaign_best")
        self.assertEqual(best["mismatches"][0]["field"], "best.action")
        self.assertEqual(best["mismatches"][0]["candidate_id"], "c0")
        self.assertEqual(best["mismatches"][0]["actual"], "verify_assay")
        self.assertEqual(best["mismatches"][0]["allowed"], ["default_baseline", "trust_sfm"])

    def test_goal_progress_audit_rejects_w4_campaign_best_not_max_quality(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
                "best": {"candidate_id": "c0", "realized_quality": 0.7, "round": 0},
            })
            _write_jsonl(w4["campaign"], [
                {
                    "round": 0,
                    "candidate_id": "c0",
                    "action": "trust_sfm",
                    "hidden_truth": {"quality": 0.7},
                },
                {
                    "round": 0,
                    "candidate_id": "c1",
                    "action": "trust_sfm",
                    "hidden_truth": {"quality": 0.9},
                },
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        best = next(error for error in content_errors
                    if error["field"] == "campaign_best")
        self.assertEqual(best["mismatches"][0]["field"], "best.max_realized_quality")
        self.assertEqual(best["mismatches"][0]["candidate_id"], "c0")
        self.assertEqual(best["mismatches"][0]["actual_quality"], 0.7)
        self.assertEqual(best["mismatches"][0]["better_candidate_id"], "c1")
        self.assertEqual(best["mismatches"][0]["better_quality"], 0.9)

    def test_goal_progress_audit_rejects_w4_summary_per_round_count_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            workstreams = _complete_goal_workstreams(d)
            w4 = workstreams["W4_closed_loop_DBTL"]
            _write_json(w4["summary"], {
                "ok": True,
                "status": "closed_loop_round_complete",
                "gate_calibrated": True,
                "aggregate": {"n": 2},
                "per_round": [{"round": 0, "n": 1}],
            })
            _write_jsonl(w4["campaign"], [
                {"candidate_id": "c0", "action": "verify_assay"},
                {"candidate_id": "c1", "action": "verify_assay"},
            ])
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": workstreams,
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        by_id = {item["id"]: item for item in audit["requirements"]}
        content_errors = by_id["W4_closed_loop_DBTL"]["supporting_artifact_content_errors"]
        per_round = next(error for error in content_errors
                         if error["field"] == "summary_per_round")
        self.assertEqual(per_round["mismatches"][0]["field"], "per_round.n_sum")
        self.assertEqual(per_round["mismatches"][0]["expected"], 2)
        self.assertEqual(per_round["mismatches"][0]["actual"], 1)

    def test_goal_progress_audit_rejects_complete_with_local_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "workstreams": _complete_goal_workstreams(d),
                "sync_manifest_audit": {"ok": False, "n_failures": 1},
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertEqual(audit["status"], "local_replay_or_regeneration_required")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 0)
        self.assertEqual(audit["local_blockers"][0]["kind"], "stale_or_invalid_sync_manifest")
        self.assertEqual(
            audit["completion_note"],
            "do not mark the Codex goal complete; W1-W4 requirements are complete but local or external blockers remain",
        )
        self.assertFalse(rep["can_mark_goal_complete"])

    def test_goal_progress_audit_rejects_complete_with_external_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {
                "complete": True,
                "next_action": "move to de-novo binder generation",
                "n_pending_external_artifacts": 1,
                "workstreams": _complete_goal_workstreams(d),
            }
            attach_goal_progress_audit(rep)

        audit = rep["goal_progress_audit"]
        self.assertNotEqual(audit["status"], "goal_complete")
        self.assertFalse(audit["can_mark_goal_complete"])
        self.assertEqual(audit["remaining_requirements"], 0)
        self.assertEqual(audit["external_blockers"][0]["kind"], "pending_external_artifacts")
        self.assertEqual(
            audit["completion_note"],
            "do not mark the Codex goal complete; W1-W4 requirements are complete but local or external blockers remain",
        )
        self.assertFalse(rep["can_mark_goal_complete"])

    def test_pending_artifact_local_audit_counts_present_empty_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            present = os.path.join(d, "targets", "present.a3m")
            empty = os.path.join(d, "targets", "empty.a3m")
            missing = os.path.join(d, "targets", "missing.a3m")
            os.makedirs(os.path.dirname(present), exist_ok=True)
            with open(present, "w") as fh:
                fh.write(">target\nAAAA\n")
            open(empty, "w").close()
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 3,
                "n_present": 2,
                "n_nonempty": 1,
                "n_missing": 1,
                "n_empty": 1,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": present},
                    {"kind": "empty_file", "field": "target_msa", "target_id": "t2", "path": empty},
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t3", "path": missing},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t3"}],
                "next_action": "sync/fix",
            })

            rep = run_status(panel_input_prep_completion_path=input_prep)
            attach_pending_artifact_local_audit(rep)

        audit = rep["pending_artifact_local_audit"]["external"]
        self.assertEqual(audit["status"], "partially_present")
        self.assertEqual(audit["n_paths"], 3)
        self.assertEqual(audit["n_present"], 2)
        self.assertEqual(audit["n_nonempty"], 1)
        self.assertEqual(audit["n_empty"], 1)
        self.assertEqual(audit["n_missing"], 1)
        self.assertFalse(audit["all_present_nonempty"])
        by_path = {item["local_path"]: item for item in audit["paths"]}
        self.assertTrue(by_path[present]["nonempty"])
        self.assertTrue(by_path[empty]["empty"])
        self.assertFalse(by_path[missing]["exists"])

    def test_cli_marks_pending_external_local_audit_all_missing(self):
        with tempfile.TemporaryDirectory() as d:
            input_prep = os.path.join(d, "input_prep.json")
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            missing = os.path.join(d, "targets", "missing.a3m")
            _write_json(input_prep, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t1"],
                "pending_artifacts": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1", "path": missing},
                ],
                "artifacts_by_target": {"t1": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "t1"}],
                "next_action": "sync/fix",
            })

            main([
                "--panel-input-prep-completion", input_prep,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        audit = saved["pending_artifact_local_audit"]["external"]
        self.assertEqual(audit["status"], "all_missing")
        self.assertEqual(audit["n_missing"], 1)
        self.assertIn("pending_external_local=all_missing", render_text(saved))

    def test_cli_records_self_command_for_status_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "status.json")
            pending_external = os.path.join(d, "pending_external.txt")
            external_sync = os.path.join(d, "external_sync.sh")
            post_sync = os.path.join(d, "post_sync.sh")
            remote_readiness = os.path.join(d, "remote_readiness.json")
            submission_decision = os.path.join(d, "submission_decision.json")

            main([
                "--target-alpha", "0.1",
                "--w2-panel-remote-readiness", remote_readiness,
                "--w2-panel-submission-decision-state", submission_decision,
                "--out", out,
                "--emit-pending-external-paths", pending_external,
                "--emit-external-sync-back-plan", external_sync,
                "--emit-post-sync-plan", post_sync,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        command = saved["self_command"]
        self.assertIn("complex_project_status", command)
        self.assertIn("--target-alpha 0.1", command)
        self.assertIn(f"--w2-panel-remote-readiness {remote_readiness}", command)
        self.assertIn(f"--w2-panel-submission-decision-state {submission_decision}", command)
        self.assertIn(f"--out {out}", command)
        self.assertIn(f"--emit-pending-external-paths {pending_external}", command)
        self.assertIn(f"--emit-external-sync-back-plan {external_sync}", command)
        self.assertIn(f"--emit-post-sync-plan {post_sync}", command)

    def test_cli_replaces_generated_scripts_without_truncating_open_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "status.json")
            post_sync = os.path.join(d, "post_sync.sh")
            old_text = "#!/usr/bin/env bash\nprintf old-start\nprintf old-tail\n"
            with open(post_sync, "w") as fh:
                fh.write(old_text)

            with open(post_sync) as old_fh:
                self.assertEqual(old_fh.readline(), "#!/usr/bin/env bash\n")
                main([
                    "--out", out,
                    "--emit-post-sync-plan", post_sync,
                ])
                old_tail = old_fh.read()

            with open(post_sync) as new_fh:
                new_text = new_fh.read()

        self.assertIn("printf old-tail", old_tail)
        self.assertIn("# M6 complex post-sync replay plan", new_text)
        self.assertNotIn("printf old-tail", new_text)

    def test_cli_audits_stale_w3_sync_sidecar_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "predictor_contract.json")
            sync_back = os.path.join(d, "second_predictor_sync_back.sh")
            out = os.path.join(d, "status.json")
            _write_json(contract, {
                "ok": False,
                "secondary_predictor": {"predictor_id": "chai1_complex"},
                "pending_secondary_records": [{"path": "hpc_outputs/chai.jsonl", "status": "missing"}],
                "failures": [{"kind": "missing_file", "field": "secondary_records"}],
            })
            _write_json(
                os.path.splitext(sync_back)[0] + ".manifest.json",
                _sync_manifest("second_predictor_sync_back", sync_back, ["hpc_outputs/stale.jsonl"]),
            )

            main([
                "--predictor-contract-report", contract,
                "--predictor-sync-back-plan", sync_back,
                "--out", out,
            ])
            with open(out) as fh:
                saved = json.load(fh)

        self.assertFalse(saved["sync_manifest_audit"]["ok"])
        self.assertEqual(saved["sync_manifest_audit"]["failures"][0]["role"], "second_predictor_sync_back")
        self.assertEqual(saved["sync_manifest_audit"]["failures"][0]["reason"], "manifest_digest_mismatch")
        self.assertFalse(saved["generated_scripts"][0]["manifest"]["matches_expected"])
        self.assertTrue(saved["generated_scripts"][0]["blocked_by_sync_manifest_audit"])
        self.assertTrue(saved["recommended_next_script"]["blocked_by_sync_manifest_audit"])
        self.assertFalse(saved["recommended_next_script"]["recommended"])
        self.assertEqual(saved["sync_manifest_audit"]["blocks_recommended_next_script"], True)
        self.assertIn("regenerate stale sync script manifests", saved["next_action"])
        self.assertIn("recommended_next_script_blocked", render_text(saved))

    def test_cli_emits_post_sync_plan(self):
        with tempfile.TemporaryDirectory() as d:
            scale_completion = os.path.join(d, "scale_completion.json")
            scale_input_prep = os.path.join(d, "scale_input_prep.json")
            panel_input_prep = os.path.join(d, "panel_input_prep.json")
            scale_readiness = os.path.join(d, "scale_readiness.json")
            panel_readiness = os.path.join(d, "panel_readiness.json")
            predictor_contract = os.path.join(d, "predictor_contract.json")
            out = os.path.join(d, "status.json")
            pending_paths = os.path.join(d, "pending_paths.txt")
            post_sync = os.path.join(d, "post_sync.sh")
            batch_preflight = os.path.join(d, "preflight.json")
            batch_summary = os.path.join(d, "summary.json")
            batch_campaign = os.path.join(d, "campaign.jsonl")
            _write_json(scale_completion, {
                "ok": False,
                "status": "scale_plan_unavailable",
                "action": "unavailable",
                "source_status": "waiting_on_input_prep",
                "readiness_status": "waiting_on_input_prep",
                "next_action": "run input prep first",
            })
            _write_json(scale_input_prep, {
                "ok": False,
                "status": "blocked",
                "report": os.path.join(d, "scale_manifest.json"),
                "target_ids": ["1BRS_AD"],
                "n_artifacts": 7,
                "n_present": 5,
                "n_nonempty": 5,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["1BRS_AD"],
                "pending_artifacts": [
                    {"field": "target_msa", "target_id": "1BRS_AD", "declared_path": "1BRS_A.a3m", "path": "1BRS_A.a3m"},
                ],
                "artifacts_by_target": {"1BRS_AD": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "1BRS_AD"}],
                "next_action": "sync/fix",
            })
            _write_json(panel_input_prep, {
                "ok": False,
                "status": "blocked",
                "report": os.path.join(d, "panel_manifest.json"),
                "n_artifacts": 21,
                "n_present": 19,
                "n_nonempty": 19,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["2SIC_EI"],
                "pending_artifacts": [
                    {"field": "target_msa", "target_id": "2SIC_EI", "declared_path": "2SIC_E.a3m", "path": "2SIC_E.a3m"},
                ],
                "artifacts_by_target": {"2SIC_EI": {"ready": False}},
                "failures": [{"kind": "missing_file", "field": "target_msa", "target_id": "2SIC_EI"}],
                "next_action": "sync/fix",
            })
            _write_json(scale_readiness, {
                "ok": False,
                "status": "blocked",
                "self_command": "python -m bio_sfm_designer.experiments.complex_readiness --out scale.json",
            })
            _write_json(panel_readiness, {
                "ok": False,
                "status": "blocked",
                "self_command": "python -m bio_sfm_designer.experiments.complex_readiness --out panel.json",
            })
            _write_json(batch_preflight, {
                "ok": False,
                "self_command": "python -m bio_sfm_designer.experiments.run_batch_round --out w4",
                "pending_artifacts": [],
                "failures": [],
            })
            _write_json(predictor_contract, {
                "ok": False,
                "self_command": "python -m bio_sfm_designer.experiments.complex_predictor_contract --out w3.json",
                "pending_secondary_records": [],
                "failures": [],
            })

            main([
                "--scale-completion", scale_completion,
                "--scale-input-prep-completion", scale_input_prep,
                "--panel-input-prep-completion", panel_input_prep,
                "--scale-readiness-report", scale_readiness,
                "--panel-readiness-report", panel_readiness,
                "--predictor-contract-report", predictor_contract,
                "--batch-preflight", batch_preflight,
                "--batch-summary", batch_summary,
                "--batch-campaign", batch_campaign,
                "--out", out,
                "--emit-pending-input-prep-paths", pending_paths,
                "--emit-post-sync-plan", post_sync,
            ])
            with open(post_sync) as fh:
                plan = fh.read()
            post_sync_manifest = os.path.splitext(post_sync)[0] + ".manifest.json"
            with open(post_sync_manifest) as fh:
                manifest = json.load(fh)

        self.assertIn("set -euo pipefail", plan)
        self.assertIn("BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"", plan)
        self.assertIn("export PYTHONNOUSERSITE=\"${PYTHONNOUSERSITE:-1}\"", plan)
        self.assertIn("export PYTHONPATH=\"${BIO_SFM_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}\"", plan)
        self.assertIn("python() {", plan)
        self.assertIn("export -f python", plan)
        self.assertIn("verify_post_sync_replay_manifest", plan)
        self.assertIn(f"POST_SYNC_REPLAY_MANIFEST={shlex.quote(post_sync_manifest)}", plan)
        self.assertIn("cd \"$REPO_ROOT\"", plan)
        self.assertIn("POST_SYNC_FAILURES=0", plan)
        self.assertIn("run_post_sync_step()", plan)
        self.assertIn("post-sync step failed", plan)
        self.assertIn("post-sync replay completed with", plan)
        self.assertIn("complex_input_prep_completion", plan)
        self.assertIn("--report", plan)
        self.assertIn("--target-id 1BRS_AD", plan)
        self.assertIn("--out scale.json", plan)
        self.assertIn("--out panel.json", plan)
        self.assertIn("bio_sfm_designer.experiments.complex_predictor_contract --out w3.json", plan)
        self.assertIn("bio_sfm_designer.experiments.run_batch_round --out w4", plan)
        self.assertIn("bash -euo pipefail -c \"$command\"", plan)
        self.assertIn("run_post_sync_step 'rerun W3 predictor contract' <<'SH'", plan)
        self.assertIn("run_post_sync_step 'refresh project status and pending-path checklist' <<'SH'", plan)
        self.assertIn(f"--batch-summary {batch_summary}", plan)
        self.assertIn(f"--batch-campaign {batch_campaign}", plan)
        self.assertIn("--emit-post-sync-plan", plan)
        self.assertIn("1BRS_A.a3m", plan)
        self.assertIn("2SIC_E.a3m", plan)
        self.assertEqual(manifest["kind"], "post_sync_replay_dependencies")
        self.assertEqual(manifest["paths"], ["1BRS_A.a3m", "2SIC_E.a3m"])

    def test_post_sync_plan_uses_bio_sfm_python_for_nested_steps(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "status.json")
            post_sync = os.path.join(d, "post_sync.sh")
            fake_python = os.path.join(d, "fake_python.sh")
            log_path = os.path.join(d, "python.log")
            with open(fake_python, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write("printf 'args=%s\\n' \"$*\" >> \"$PYTHON_LOG\"\n")
                fh.write("printf 'PYTHONNOUSERSITE=%s\\n' \"$PYTHONNOUSERSITE\" >> \"$PYTHON_LOG\"\n")
                fh.write("printf 'PYTHONPATH=%s\\n' \"$PYTHONPATH\" >> \"$PYTHON_LOG\"\n")
                fh.write("exit 0\n")
            os.chmod(fake_python, 0o755)

            main([
                "--out", out,
                "--emit-post-sync-plan", post_sync,
            ])
            env = os.environ.copy()
            env["BIO_SFM_PYTHON"] = fake_python
            env["BIO_SFM_REPO_ROOT"] = os.getcwd()
            env["PYTHON_LOG"] = log_path
            proc = subprocess.run(["bash", post_sync], cwd=d, env=env,
                                  text=True, capture_output=True)
            with open(log_path) as fh:
                python_log = fh.read()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("args=-m bio_sfm_designer.experiments.complex_project_status", python_log)
        self.assertIn("PYTHONNOUSERSITE=1", python_log)
        self.assertIn(os.path.join(os.getcwd(), "src"), python_log)

    def test_post_sync_plan_failure_collects_and_runs_later_steps(self):
        with tempfile.TemporaryDirectory() as d:
            scale_readiness = os.path.join(d, "scale_readiness.json")
            panel_readiness = os.path.join(d, "panel_readiness.json")
            marker = os.path.join(d, "later_step.txt")
            out = os.path.join(d, "status.json")
            post_sync = os.path.join(d, "post_sync.sh")
            _write_json(scale_readiness, {
                "ok": False,
                "status": "blocked",
                "self_command": shlex.join([sys.executable, "-c", "import sys; sys.exit(7)"]),
            })
            _write_json(panel_readiness, {
                "ok": False,
                "status": "blocked",
                "self_command": shlex.join([
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({marker!r}).write_text('ran')",
                ]),
            })

            main([
                "--scale-readiness-report", scale_readiness,
                "--panel-readiness-report", panel_readiness,
                "--out", out,
                "--emit-post-sync-plan", post_sync,
            ])
            env = os.environ.copy()
            env["PATH"] = os.pathsep.join([os.path.dirname(sys.executable), env.get("PATH", "")])
            env["BIO_SFM_REPO_ROOT"] = os.getcwd()
            proc = subprocess.run(["bash", post_sync], cwd=os.getcwd(), env=env,
                                  text=True, capture_output=True)

            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("post-sync step failed (7): rerun W1 readiness", proc.stderr)
            self.assertIn("post-sync replay completed with 1 failed step", proc.stderr)
            self.assertTrue(os.path.exists(marker))
            self.assertTrue(os.path.exists(out))

    def test_alpha_decision_target_alpha_mismatch_blocks_w1_completion(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            _write_json(decision, {
                "decision": "stop_certified",
                "target_alpha": 0.3,
                "n_records": 192,
                "certified_alphas": [0.3],
            })

            rep = run_status(decision_path=decision, target_alpha=0.2)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "alpha_decision_alpha_mismatch")
        self.assertFalse(w1["complete"])
        self.assertEqual(w1["target_alpha"], 0.3)
        self.assertEqual(w1["requested_target_alpha"], 0.2)

    def test_scale_completion_target_alpha_mismatch_blocks_posthoc_status(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "scale_completion.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_posthoc",
                "target_alpha": 0.3,
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records x",
            })

            rep = run_status(scale_completion_path=completion, target_alpha=0.2)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "scale_completion_alpha_mismatch")
        self.assertFalse(w1["complete"])
        self.assertIn("matching --target-alpha", w1["next_action"])

    def test_alpha_decision_mismatch_takes_precedence_over_scale_completion(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            completion = os.path.join(d, "scale_completion.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.3,
                "next_batch": {"action": "run_scale_batch"},
            })
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_posthoc",
                "target_alpha": 0.2,
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records x",
            })

            rep = run_status(decision_path=decision, scale_completion_path=completion, target_alpha=0.2)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "alpha_decision_alpha_mismatch")
        self.assertFalse(w1["complete"])
        self.assertEqual(w1["target_alpha"], 0.3)

    def test_panel_completion_ready_without_panel_report_is_next_status(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            completion = os.path.join(d, "panel_completion.json")
            _write_json(target_manifest, {
                "ok": True,
                "n_targets": 3,
                "n_ready_targets": 3,
            })
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_panel_report",
                "n_manifest_targets": 3,
                "n_completed_targets": 3,
                "panel_report_command": "python -m bio_sfm_designer.experiments.complex_panel_report --records a b c",
            })

            rep = run_status(target_manifest_path=target_manifest, panel_completion_path=completion)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_records_ready_for_report")
        self.assertEqual(w2["n_completed_targets"], 3)
        self.assertIn("panel_report", w2["next_action"])
        self.assertIn("complex_panel_report", w2["panel_report_command"])

    def test_panel_completion_target_alpha_mismatch_blocks_report_status(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "panel_completion.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_panel_report",
                "target_alpha": 0.3,
                "n_manifest_targets": 3,
                "n_completed_targets": 3,
                "panel_report_command": "python -m bio_sfm_designer.experiments.complex_panel_report --records a b c",
            })

            rep = run_status(panel_completion_path=completion, target_alpha=0.2)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_completion_alpha_mismatch")
        self.assertFalse(w2["complete"])
        self.assertEqual(w2["requested_target_alpha"], 0.2)

    def test_panel_completion_blocked_surfaces_sync_failures(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "panel_completion.json")
            _write_json(completion, {
                "ok": False,
                "status": "blocked",
                "n_manifest_targets": 3,
                "n_completed_targets": 2,
                "failures": [{"kind": "missing_file", "target_id": "t2"}],
                "next_action": "sync/fix target records before panel report",
            })

            rep = run_status(panel_completion_path=completion)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_completion_blocked")
        self.assertEqual(w2["failures"][0]["kind"], "missing_file")
        self.assertIn("sync/fix", w2["next_action"])

    def test_target_msa_gate_audit_supersedes_stale_panel_report(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            panel = os.path.join(d, "panel.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "completion_counts": {"n_artifacts": 98, "n_nonempty": 70, "n_missing": 28, "n_empty": 0},
                "manifest_counts": {"n_targets": 14, "n_ready_targets": 0, "n_failures": 28},
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
                "next_action": "await explicit approval",
            })
            _write_json(panel, {
                "ok": False,
                "panel_status": "multi_target_evaluable_not_certified",
                "target_alpha": 0.2,
                "n_targets": 5,
                "n_records": 500,
                "failures": [{"kind": "target_not_certified"}],
                "targets": [],
            })

            rep = run_status(target_msa_gate_audit_path=gate, panel_report_path=panel)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_gate_ready_awaiting_explicit_approval")
        self.assertFalse(w2["complete"])
        self.assertTrue(w2["audit_ok"])
        self.assertEqual(w2["target_count"], 14)
        self.assertEqual(w2["pending_path_count"], 28)
        self.assertFalse(w2["ready_for_panel_submission"])
        self.assertTrue(w2["ready_for_target_msa_submission_if_explicitly_approved"])
        self.assertTrue(w2["superseded_panel_report"].endswith("panel.json"))
        self.assertEqual(w2["superseded_panel_report_status"], "multi_target_evaluable_not_certified")
        self.assertEqual(w2["next_action"], "await explicit approval")

    def test_w2_approval_packet_attaches_to_ready_target_msa_gate(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            packet = os.path.join(d, "approval_packet.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "completion_counts": {"n_artifacts": 98, "n_nonempty": 70, "n_missing": 28, "n_empty": 0},
                "manifest_counts": {"n_targets": 14, "n_ready_targets": 0, "n_failures": 28},
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
                "next_action": "await explicit approval",
            })
            _write_json(packet, {
                "artifact": "m6d_w2_target_msa_approval_packet",
                "approval_packet_ready": True,
                "status": "awaiting_explicit_target_msa_approval",
                "can_submit_target_msa_if_user_explicitly_approves": True,
                "can_submit_proteinmpnn_boltz_panel": False,
                "target_msa_approval_env_var": "BIO_SFM_APPROVE_V9_TARGET_MSA",
                "target_msa_approval_env_value": "approve-v9-target-msa-precompute",
                "wrapper_guard_audit": "/tmp/wrapper_guard.json",
                "wrapper_guard_audit_ok": True,
                "wrapper_guard_static_ok": True,
                "wrapper_guard_no_env_run_ok": True,
                "wrapper_guard_script_sha256": "wrapper-sha",
                "target_count": 14,
                "pending_path_count": 28,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "failures": [],
            })

            rep = run_status(target_msa_gate_audit_path=gate, w2_approval_packet_path=packet)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_gate_ready_awaiting_explicit_approval")
        self.assertTrue(w2["approval_packet_ready"])
        self.assertFalse(w2["can_submit_proteinmpnn_boltz_panel"])
        self.assertEqual(w2["target_msa_approval_env_var"], "BIO_SFM_APPROVE_V9_TARGET_MSA")
        self.assertEqual(w2["target_msa_approval_env_value"], "approve-v9-target-msa-precompute")
        self.assertTrue(w2["wrapper_guard_audit_ok"])
        self.assertTrue(w2["wrapper_guard_static_ok"])
        self.assertTrue(w2["wrapper_guard_no_env_run_ok"])
        self.assertEqual(w2["wrapper_guard_script_sha256"], "wrapper-sha")
        self.assertTrue(w2["approval_packet"].endswith("approval_packet.json"))
        self.assertEqual(w2["approval_packet_failures"], [])
        self.assertIn("approval_packet_ready=True", render_text(rep))

    def test_w2_approval_packet_blocks_when_panel_submission_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            packet = os.path.join(d, "approval_packet.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
            })
            _write_json(packet, {
                "artifact": "m6d_w2_target_msa_approval_packet",
                "approval_packet_ready": True,
                "status": "awaiting_explicit_target_msa_approval",
                "can_submit_target_msa_if_user_explicitly_approves": True,
                "can_submit_proteinmpnn_boltz_panel": True,
                "target_count": 14,
                "pending_path_count": 28,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "failures": [],
                "next_action": "fix approval packet",
            })

            rep = run_status(target_msa_gate_audit_path=gate, w2_approval_packet_path=packet)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_approval_packet_blocked")
        self.assertFalse(w2["approval_packet_ready"])
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("approval_packet_panel_submission_not_blocked", kinds)

    def test_w2_panel_approval_packet_advances_state_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            packet = os.path.join(d, "panel_approval_packet.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
            })
            _write_json(packet, {
                "artifact": "m6d_w2_panel_approval_packet",
                "status": "panel_approval_packet_ready",
                "audit_ok": True,
                "approval_packet_ready": True,
                "can_submit_panel_if_user_explicitly_approves": True,
                "can_claim_w2_generalization": False,
                "panel_approval_env_var": "BIO_SFM_APPROVE_V9_PANEL",
                "panel_approval_env_value": "approve-v9-panel-submit",
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash submit_panel.sh'",
                "sync_back_command_after_jobs_finish": "bash sync_panel.sh",
                "checks": {
                    "target_msa_strict_ready": True,
                    "panel_preflight_ready": True,
                    "panel_dry_run_no_sbatch": True,
                    "panel_guard_no_env_refuses": True,
                    "submit_receipt_absent": True,
                    "submit_summary_absent": True,
                },
                "failures": [],
            })

            rep = run_status(target_msa_gate_audit_path=gate, w2_panel_approval_packet_path=packet)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_approval_packet_ready_awaiting_explicit_approval")
        self.assertFalse(w2["complete"])
        self.assertTrue(w2["panel_approval_packet_ready"])
        self.assertTrue(w2["can_submit_panel_if_user_explicitly_approves"])
        self.assertFalse(w2["can_claim_w2_generalization"])
        self.assertTrue(w2["ready_for_panel_submission_if_explicitly_approved"])
        self.assertEqual(w2["panel_approval_env_var"], "BIO_SFM_APPROVE_V9_PANEL")
        self.assertEqual(w2["panel_approval_env_value"], "approve-v9-panel-submit")
        self.assertEqual(w2["panel_approval_packet_failures"], [])
        self.assertIn("explicit user approval", w2["next_action"])
        text = render_text(rep)
        self.assertIn("panel_approval_packet_ready=True", text)
        self.assertIn("can_claim_w2_generalization=False", text)

    def test_w2_panel_decision_protocol_attaches_without_completing_w2(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            packet = os.path.join(d, "panel_approval_packet.json")
            protocol = os.path.join(d, "panel_decision_protocol.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
            })
            _write_json(packet, {
                "artifact": "m6d_w2_panel_approval_packet",
                "status": "panel_approval_packet_ready",
                "audit_ok": True,
                "approval_packet_ready": True,
                "can_submit_panel_if_user_explicitly_approves": True,
                "can_claim_w2_generalization": False,
                "panel_approval_env_var": "BIO_SFM_APPROVE_V9_PANEL",
                "panel_approval_env_value": "approve-v9-panel-submit",
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash submit_panel.sh'",
                "sync_back_command_after_jobs_finish": "bash sync_panel.sh",
                "checks": {
                    "target_msa_strict_ready": True,
                    "panel_preflight_ready": True,
                    "panel_dry_run_no_sbatch": True,
                    "panel_guard_no_env_refuses": True,
                    "submit_receipt_absent": True,
                    "submit_summary_absent": True,
                },
                "failures": [],
            })
            _write_json(protocol, {
                "artifact": "m6d_w2_panel_decision_protocol",
                "status": "post_panel_decision_protocol_ready",
                "audit_ok": True,
                "no_submit": True,
                "can_claim_w2_generalization_now": False,
                "current_panel_result": {
                    "status": "not_available_not_submitted",
                    "w2_generalization_supported": False,
                    "claim": "no W2 claim; panel records/report are not available",
                },
                "failures": [],
            })

            rep = run_status(
                target_msa_gate_audit_path=gate,
                w2_panel_approval_packet_path=packet,
                w2_panel_decision_protocol_path=protocol,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_approval_packet_ready_awaiting_explicit_approval")
        self.assertFalse(w2["complete"])
        self.assertTrue(w2["panel_decision_protocol_ready"])
        self.assertTrue(w2["panel_decision_no_submit"])
        self.assertFalse(w2["panel_decision_can_claim_w2_now"])
        self.assertEqual(w2["panel_decision_current_result_status"], "not_available_not_submitted")
        self.assertEqual(w2["panel_decision_protocol_failures"], [])
        self.assertIn("panel_decision_protocol_ready=True", render_text(rep))

    def test_w2_panel_packets_attach_to_ready_manifest_status(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets_report.json")
            packet = os.path.join(d, "panel_approval_packet.json")
            protocol = os.path.join(d, "panel_decision_protocol.json")
            remote = os.path.join(d, "remote_readiness.json")
            submission_decision = os.path.join(d, "submission_decision.json")
            postsync = os.path.join(d, "postsync.json")
            _write_json(manifest, {
                "ok": True,
                "n_targets": 7,
                "n_ready_targets": 7,
                "failures": [],
            })
            _write_json(packet, {
                "artifact": "m6d_w2_panel_approval_packet",
                "status": "panel_approval_packet_ready",
                "audit_ok": True,
                "approval_packet_ready": True,
                "can_submit_panel_if_user_explicitly_approves": True,
                "can_claim_w2_generalization": False,
                "panel_approval_env_var": "BIO_SFM_APPROVE_V11_PANEL",
                "panel_approval_env_value": "approve-v11-panel-submit",
                "submit_command_if_approved": "ssh cayuga 'bash submit_panel.sh'",
                "sync_back_command_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v11_sync_back.sh",
                "completion_command_after_sync": "bash results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
                "receipt_monitor_after_submit": (
                    "CAYUGA_BIO_SFM_ROOT=cayuga-login1:/home/fs01/<user>/bio_sfm_smoke "
                    "bash results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh"
                ),
                "job_state_query_after_receipt": (
                    "ssh cayuga-login1 'cd /home/fs01/<user>/bio_sfm_smoke && "
                    "bash results/m6d_w2_target_family_redesign_v11_job_state_query.sh'"
                ),
                "job_state_probe_sync_after_query": (
                    "rsync -avP cayuga-login1:/home/fs01/<user>/bio_sfm_smoke/"
                    "results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
                    "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
                ),
                "postsubmit_status_before_sync": "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json",
                "job_state_probe_before_sync": "results/m6d_w2_target_family_redesign_v11_job_state_probe.json",
                "postsubmit_sync_ready_gate": (
                    "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --require-sync-ready"
                ),
                "postsubmit_status_command_before_sync": (
                    "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
                    "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json --require-sync-ready"
                ),
                "postsync_replay_after_sync": "bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
                "checks": {
                    "target_msa_strict_ready": True,
                    "panel_preflight_ready": True,
                    "panel_dry_run_no_sbatch": True,
                    "panel_guard_no_env_refuses": True,
                    "submit_receipt_absent": True,
                    "submit_summary_absent": True,
                },
                "failures": [],
            })
            _write_json(protocol, {
                "artifact": "m6d_w2_panel_decision_protocol",
                "status": "post_panel_decision_protocol_ready",
                "audit_ok": True,
                "no_submit": True,
                "can_claim_w2_generalization_now": False,
                "current_panel_result": {
                    "status": "not_available_not_submitted",
                    "w2_generalization_supported": False,
                    "claim": "no W2 claim; panel records/report are not available",
                },
                "failures": [],
            })
            _write_json(remote, {
                "artifact": "m6d_w2_v11_remote_submission_readiness",
                "status": "remote_submission_readiness_ok",
                "audit_ok": True,
                "no_submit": True,
                "can_submit_panel_if_user_explicitly_approves": True,
                "can_claim_w2_generalization": False,
                "n_exact_checks": 14,
                "n_semantic_checks": 5,
                "n_absence_checks": 2,
                "n_failures": 0,
                "failures": [],
            })
            _write_json(submission_decision, {
                "artifact": "m6d_w2_v11_submission_decision_state",
                "status": "awaiting_explicit_panel_submission_approval",
                "decision": "awaiting_explicit_approval",
                "audit_ok": True,
                "no_submit": True,
                "submitted": False,
                "explicit_approval_required": True,
                "can_submit_if_explicitly_approved": True,
                "can_claim_w2_generalization": False,
                "approval_disambiguation": {
                    "continuation_phrases_are_approval": False,
                    "approval_must_explicitly_name": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
                    "machine_gate": "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
                },
                "receipt_absence": {
                    "local": [
                        {"path": "results/receipt.jsonl", "exists": False},
                        {"path": "results/summary.json", "exists": False},
                    ],
                    "remote_checked": True,
                    "remote": [
                        {"path": "results/receipt.jsonl", "exists": False},
                        {"path": "results/summary.json", "exists": False},
                    ],
                },
                "failures": [],
            })
            _write_json(postsync, {
                "artifact": "m6d_w2_panel_postsync_interpretation",
                "status": "not_synced_not_interpretable",
                "audit_ok": True,
                "no_submit": True,
                "submitted": False,
                "sync_ready": False,
                "can_claim_w2_generalization": False,
                "target_alpha": 0.2,
                "min_targets": 4,
                "min_records_per_target": 20,
                "current_panel_result": {
                    "status": "not_available_not_submitted",
                    "w2_generalization_supported": False,
                },
                "failures": [],
            })

            rep = run_status(
                target_manifest_path=manifest,
                w2_panel_approval_packet_path=packet,
                w2_panel_decision_protocol_path=protocol,
                w2_panel_remote_readiness_path=remote,
                w2_panel_submission_decision_state_path=submission_decision,
                w2_panel_postsync_interpretation_path=postsync,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_approval_packet_ready_awaiting_explicit_approval")
        self.assertFalse(w2["complete"])
        self.assertEqual(w2["n_ready_targets"], 7)
        self.assertTrue(w2["panel_approval_packet_ready"])
        self.assertTrue(w2["panel_postsubmit_sync_ready_gate_ok"])
        self.assertTrue(w2["panel_postsubmit_bridge_ok"])
        self.assertIn("receipt_monitor", w2["panel_receipt_monitor_after_submit"])
        self.assertIn("job_state_query", w2["panel_job_state_query_after_receipt"])
        self.assertIn("postsync_interpretation", w2["panel_postsync_replay_after_sync"])
        self.assertIn("--require-sync-ready", w2["panel_postsubmit_sync_ready_gate"])
        self.assertTrue(w2["panel_decision_protocol_ready"])
        self.assertTrue(w2["panel_decision_no_submit"])
        self.assertFalse(w2["panel_decision_can_claim_w2_now"])
        self.assertTrue(w2["panel_remote_submission_readiness_ok"])
        self.assertTrue(w2["panel_remote_no_submit"])
        self.assertEqual(w2["panel_remote_exact_checks"], 14)
        self.assertEqual(w2["panel_remote_semantic_checks"], 5)
        self.assertEqual(w2["panel_remote_absence_checks"], 2)
        self.assertTrue(w2["panel_submission_decision_ready"])
        self.assertEqual(w2["panel_submission_decision"], "awaiting_explicit_approval")
        self.assertTrue(w2["panel_submission_decision_no_submit"])
        self.assertFalse(w2["panel_submission_decision_submitted"])
        self.assertFalse(w2["panel_submission_decision_can_claim_w2_generalization"])
        self.assertTrue(w2["panel_postsync_interpretation_ready"])
        self.assertEqual(w2["panel_postsync_status"], "not_synced_not_interpretable")
        self.assertFalse(w2["panel_postsync_can_claim_w2_generalization"])
        self.assertIn("submission decision is recorded", w2["next_action"])
        self.assertIn("panel_remote_submission_readiness_ok=True", render_text(rep))
        self.assertIn("panel_postsubmit_sync_ready_gate_ok=True", render_text(rep))
        self.assertIn("panel_postsubmit_bridge_ok=True", render_text(rep))
        self.assertIn("panel_submission_decision_ready=True", render_text(rep))
        self.assertIn("panel_postsync_interpretation_ready=True", render_text(rep))
        self.assertIn("W2 panel submission", w2["next_action"])
        ladder = rep["resume_execution_ladder"]
        self.assertEqual(ladder["next_role"], "w2_panel_submit")
        self.assertFalse(ladder["approval_disambiguation"]["continuation_phrases_are_approval"])
        self.assertEqual(
            [step["role"] for step in ladder["steps"]],
            [
                "w2_panel_submit",
                "w2_panel_receipt_monitor",
                "w2_panel_job_state_query",
                "w2_panel_postsubmit_status",
                "w2_panel_sync_back",
                "w2_panel_completion",
                "w2_panel_postsync_replay",
            ],
        )
        self.assertEqual(ladder["steps"][0]["status"], "waiting_for_explicit_approval")
        self.assertEqual(ladder["steps"][1]["blocked_by"], "w2_panel_submit")
        self.assertIn("receipt_monitor", ladder["steps"][1]["command"])
        self.assertIn("job_state_query", ladder["steps"][2]["command"])
        self.assertIn("--require-sync-ready", ladder["steps"][3]["command"])
        self.assertIn("sync_back", ladder["steps"][4]["command"])
        self.assertIn("panel_completion", ladder["steps"][5]["command"])
        self.assertIn("postsync_interpretation", ladder["steps"][6]["command"])

    def test_w2_panel_submission_decision_state_blocks_if_already_submitted(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets_report.json")
            submission_decision = os.path.join(d, "submission_decision.json")
            _write_json(manifest, {
                "ok": True,
                "n_targets": 7,
                "n_ready_targets": 7,
                "failures": [],
            })
            _write_json(submission_decision, {
                "artifact": "m6d_w2_v11_submission_decision_state",
                "status": "awaiting_explicit_panel_submission_approval",
                "decision": "awaiting_explicit_approval",
                "audit_ok": True,
                "no_submit": True,
                "submitted": True,
                "explicit_approval_required": True,
                "can_submit_if_explicitly_approved": True,
                "can_claim_w2_generalization": False,
                "receipt_absence": {
                    "local": [{"path": "results/receipt.jsonl", "exists": False}],
                    "remote_checked": True,
                    "remote": [{"path": "results/receipt.jsonl", "exists": False}],
                },
                "failures": [],
            })

            rep = run_status(
                target_manifest_path=manifest,
                w2_panel_submission_decision_state_path=submission_decision,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_submission_decision_state_blocked")
        self.assertFalse(w2["panel_submission_decision_ready"])
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("panel_submission_decision_already_submitted", kinds)

    def test_w2_panel_postsync_interpretation_blocks_claim_leak(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets_report.json")
            postsync = os.path.join(d, "postsync.json")
            _write_json(manifest, {
                "ok": True,
                "n_targets": 7,
                "n_ready_targets": 7,
                "failures": [],
            })
            _write_json(postsync, {
                "artifact": "m6d_w2_panel_postsync_interpretation",
                "status": "not_synced_not_interpretable",
                "audit_ok": True,
                "no_submit": True,
                "submitted": False,
                "sync_ready": False,
                "can_claim_w2_generalization": True,
                "target_alpha": 0.2,
                "current_panel_result": {
                    "status": "not_available_not_submitted",
                    "w2_generalization_supported": False,
                },
                "failures": [],
            })

            rep = run_status(
                target_manifest_path=manifest,
                w2_panel_postsync_interpretation_path=postsync,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_postsync_interpretation_blocked")
        self.assertFalse(w2["panel_postsync_interpretation_ready"])
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("panel_postsync_interpretation_claim_without_supported_panel", kinds)

    def test_w2_panel_remote_readiness_blocks_if_receipt_present(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets_report.json")
            remote = os.path.join(d, "remote_readiness.json")
            _write_json(manifest, {
                "ok": True,
                "n_targets": 7,
                "n_ready_targets": 7,
                "failures": [],
            })
            _write_json(remote, {
                "artifact": "m6d_w2_v11_remote_submission_readiness",
                "status": "remote_submission_readiness_blocked",
                "audit_ok": False,
                "no_submit": True,
                "can_submit_panel_if_user_explicitly_approves": False,
                "can_claim_w2_generalization": False,
                "n_exact_checks": 14,
                "n_semantic_checks": 5,
                "n_absence_checks": 2,
                "n_failures": 1,
                "failures": [{"kind": "submit_receipt_or_summary_present", "path": "results/receipt.jsonl"}],
            })

            rep = run_status(
                target_manifest_path=manifest,
                w2_panel_remote_readiness_path=remote,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_remote_submission_readiness_blocked")
        self.assertFalse(w2["complete"])
        self.assertFalse(w2["panel_remote_submission_readiness_ok"])
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("submit_receipt_or_summary_present", kinds)
        self.assertIn("panel_remote_submission_readiness_status_not_ok", kinds)

    def test_w2_panel_remote_readiness_blocks_if_local_exact_check_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets_report.json")
            remote = os.path.join(d, "remote_readiness.json")
            checked = os.path.join(d, "checked.py")
            with open(checked, "w") as fh:
                fh.write("current\n")
            _write_json(manifest, {
                "ok": True,
                "n_targets": 7,
                "n_ready_targets": 7,
                "failures": [],
            })
            _write_json(remote, {
                "artifact": "m6d_w2_v11_remote_submission_readiness",
                "status": "remote_submission_readiness_ok",
                "audit_ok": True,
                "no_submit": True,
                "can_submit_panel_if_user_explicitly_approves": True,
                "can_claim_w2_generalization": False,
                "local_root": d,
                "n_exact_checks": 1,
                "n_semantic_checks": 0,
                "n_absence_checks": 2,
                "n_failures": 0,
                "exact_checks": [{
                    "path": "checked.py",
                    "ok": True,
                    "local_bytes": 4,
                    "local_sha256": hashlib.sha256(b"old\n").hexdigest(),
                    "remote_bytes": 4,
                    "remote_sha256": hashlib.sha256(b"old\n").hexdigest(),
                }],
                "failures": [],
            })

            rep = run_status(
                target_manifest_path=manifest,
                w2_panel_remote_readiness_path=remote,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_remote_submission_readiness_blocked")
        self.assertFalse(w2["panel_remote_submission_readiness_ok"])
        self.assertFalse(w2["panel_remote_local_exact_fresh"])
        self.assertEqual(w2["panel_remote_local_exact_stale_count"], 1)
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("panel_remote_submission_readiness_local_exact_stale", kinds)

    def test_w2_approval_parity_attaches_to_ready_target_msa_gate(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            parity = os.path.join(d, "approval_parity.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
            })
            _write_json(parity, {
                "artifact": "m6d_w2_target_msa_approval_parity",
                "parity_ok": True,
                "status": "local_cayuga_approval_packet_agree",
                "approval_packet_ready": True,
                "panel_submission_blocked": True,
                "target_count": 14,
                "pending_path_count": 28,
                "mismatches": [],
            })

            rep = run_status(target_msa_gate_audit_path=gate, w2_approval_parity_path=parity)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_gate_ready_awaiting_explicit_approval")
        self.assertTrue(w2["approval_parity_ok"])
        self.assertTrue(w2["local_cayuga_approval_packet_agree"])
        self.assertEqual(w2["approval_parity_failures"], [])
        self.assertIn("approval_parity_ok=True", render_text(rep))

    def test_w2_approval_parity_blocks_when_panel_not_blocked_on_both_sides(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            parity = os.path.join(d, "approval_parity.json")
            _write_json(gate, {
                "artifact": "m6d_w2_target_msa_gate_audit",
                "audit_ok": True,
                "status": "pre_submit_gate_ready_awaiting_explicit_approval",
                "target_count": 14,
                "pending_path_count": 28,
                "ready_for_panel_submission": False,
                "ready_for_target_msa_submission_if_explicitly_approved": True,
                "explicit_submit_approval_required": True,
                "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
                "postsubmit_sync_back_command": "bash sync_back.sh",
                "pending_paths": "pending.txt",
                "failures": [],
            })
            _write_json(parity, {
                "artifact": "m6d_w2_target_msa_approval_parity",
                "parity_ok": False,
                "status": "local_cayuga_approval_packet_mismatch",
                "approval_packet_ready": True,
                "panel_submission_blocked": False,
                "target_count": 14,
                "pending_path_count": 28,
                "mismatches": [{"field": "can_submit_proteinmpnn_boltz_panel"}],
                "next_action": "fix local/Cayuga approval packet parity",
            })

            rep = run_status(target_msa_gate_audit_path=gate, w2_approval_parity_path=parity)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_approval_parity_blocked")
        self.assertFalse(w2["approval_parity_ok"])
        kinds = {failure["kind"] for failure in w2["failures"]}
        self.assertIn("approval_parity_not_ok", kinds)
        self.assertIn("approval_parity_panel_not_blocked_on_both_sides", kinds)

    def test_missing_target_msa_gate_audit_is_explicit_status(self):
        with tempfile.TemporaryDirectory() as d:
            missing_gate = os.path.join(d, "missing_gate.json")

            rep = run_status(target_msa_gate_audit_path=missing_gate)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "target_msa_gate_audit_missing")
        self.assertFalse(w2["complete"])
        self.assertIn("m6d_w2_target_msa_gate_audit", w2["next_action"])

    def test_completion_blockers_feed_pending_external_records(self):
        with tempfile.TemporaryDirectory() as d:
            scale_completion = os.path.join(d, "scale_completion.json")
            panel_completion = os.path.join(d, "panel_completion.json")
            _write_json(scale_completion, {
                "ok": False,
                "status": "blocked",
                "target_id": "1BRS_AD",
                "target_alpha": 0.2,
                "failures": [{"role": "new_record", "path": "hpc_outputs/m6c_targets/1BRS_AD/records_t030.jsonl", "error": "missing_file"}],
                "records": [
                    {
                        "role": "new_record",
                        "path": "hpc_outputs/m6c_targets/1BRS_AD/records_t030.jsonl",
                        "exists": False,
                        "nonempty": False,
                        "jsonl_ok": False,
                        "error": "missing_file",
                    }
                ],
                "next_action": "sync scale records",
            })
            _write_json(panel_completion, {
                "ok": False,
                "status": "blocked",
                "n_manifest_targets": 3,
                "n_completed_targets": 0,
                "records": [
                    {
                        "target_id": "2SIC_EI",
                        "path": "hpc_outputs/m6d_targets/2SIC_EI/records_boltz_complex.jsonl",
                        "exists": False,
                        "nonempty": False,
                        "jsonl_ok": False,
                        "error": "missing_file",
                    }
                ],
                "failures": [{"kind": "missing_file", "target_id": "2SIC_EI"}],
                "next_action": "sync panel records",
            })

            rep = run_status(
                scale_completion_path=scale_completion,
                panel_completion_path=panel_completion,
                target_alpha=0.2,
            )

        external_by_path = {item["path"]: item for item in rep["pending_external_artifacts"]}
        self.assertEqual(rep["n_pending_external_artifacts"], 2)
        scale = external_by_path["hpc_outputs/m6c_targets/1BRS_AD/records_t030.jsonl"]
        self.assertEqual(scale["categories"], ["scale_records"])
        self.assertEqual(scale["artifacts"], ["records"])
        self.assertEqual(scale["target_ids"], ["1BRS_AD"])
        panel = external_by_path["hpc_outputs/m6d_targets/2SIC_EI/records_boltz_complex.jsonl"]
        self.assertEqual(panel["categories"], ["panel_records"])
        self.assertEqual(panel["artifacts"], ["records"])
        self.assertEqual(panel["target_ids"], ["2SIC_EI"])
        self.assertEqual(
            rep["pending_external_summary"]["by_workstream"],
            {"W1_M6c_scale_up": 1, "W2_multi_target_panel": 1},
        )
        readiness = {"available_steps": [{"id": "target_msa_precompute", "status": "available"}]}
        action = _remote_missing_action(
            "W1_M6c_scale_up",
            readiness,
            {"categories": {"scale_records"}, "artifacts": {"records"}, "fields": set()},
        )
        self.assertIn("Cayuga ProteinMPNN/Boltz record jobs", action)
        self.assertNotIn("target_msa_precompute", action)

    def test_target_manifest_input_prep_supersedes_stale_panel_completion(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            completion = os.path.join(d, "panel_completion.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1"},
                ],
            })
            _write_json(completion, {
                "ok": False,
                "status": "blocked",
                "n_manifest_targets": 1,
                "n_completed_targets": 0,
                "records": [
                    {
                        "target_id": "t1",
                        "path": "hpc_outputs/m6d_targets/t1/records_boltz_complex.jsonl",
                        "exists": False,
                        "nonempty": False,
                        "jsonl_ok": False,
                        "error": "missing_file",
                    }
                ],
                "failures": [{"kind": "missing_file", "target_id": "t1", "field": "records"}],
                "next_action": "sync/fix target records before panel report",
            })

            rep = run_status(target_manifest_path=target_manifest, panel_completion_path=completion)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_waiting_on_input_prep")
        self.assertIn("target_msa_precompute", w2["next_action"])
        self.assertEqual(w2["superseded_panel_completion_status"], "blocked")
        self.assertTrue(w2["superseded_panel_completion"].endswith("panel_completion.json"))
        external_by_path = {item["path"]: item for item in rep["pending_external_artifacts"]}
        panel = external_by_path["hpc_outputs/m6d_targets/t1/records_boltz_complex.jsonl"]
        self.assertEqual(panel["categories"], ["panel_records"])
        self.assertEqual(panel["artifacts"], ["records"])
        self.assertEqual(panel["target_ids"], ["t1"])

    def test_missing_panel_completion_path_is_status_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            target_manifest = os.path.join(d, "targets_report.json")
            missing_completion = os.path.join(d, "panel_completion.json")
            _write_json(target_manifest, {
                "ok": False,
                "n_targets": 3,
                "n_ready_targets": 0,
                "failures": [
                    {"kind": "missing_file", "field": "target_msa", "target_id": "t1"},
                    {"kind": "missing_file", "field": "target_msa_report", "target_id": "t1"},
                ],
            })

            rep = run_status(
                target_manifest_path=target_manifest,
                panel_completion_path=missing_completion,
            )

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_waiting_on_input_prep")
        self.assertEqual(w2["superseded_panel_completion_status"], "missing_artifact")
        self.assertTrue(w2["superseded_panel_completion"].endswith("panel_completion.json"))
        self.assertIn("target_msa_precompute", render_text(rep))

    def test_missing_scale_completion_path_is_status_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            missing_completion = os.path.join(d, "scale_completion.json")
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "next_batch": {"action": "run_scale_batch"},
            })

            rep = run_status(decision_path=decision, scale_completion_path=missing_completion)

        w1 = rep["workstreams"]["W1_M6c_scale_up"]
        self.assertEqual(w1["status"], "scale_completion_missing")
        self.assertIn("complex_scale_completion.py", w1["next_action"])

    def test_panel_report_target_alpha_mismatch_blocks_w2_completion(self):
        with tempfile.TemporaryDirectory() as d:
            panel = os.path.join(d, "panel.json")
            _write_json(panel, _panel_ready_report(n_records_per_target=300, target_alpha=0.3))

            rep = run_status(panel_report_path=panel, target_alpha=0.2)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_report_alpha_mismatch")
        self.assertFalse(w2["complete"])
        self.assertIn("regenerate panel report", w2["next_action"])

    def test_panel_report_without_target_certificates_blocks_w2_completion(self):
        with tempfile.TemporaryDirectory() as d:
            panel = os.path.join(d, "panel.json")
            _write_json(panel, {
                "ok": True,
                "panel_status": "multi_target_certified",
                "target_alpha": 0.2,
                "threshold": 4.0,
                "min_targets": 3,
                "min_records_per_target": 20,
                "n_targets": 3,
                "n_records": 900,
                "predictors": ["boltz2_complex"],
                "signal_sources": ["boltz2_pae_interaction"],
                "label_sources": ["boltz2_lrmsd_to_reference"],
                "label_threshold_audit": {"ok": True},
                "failures": [],
            })

            rep = run_status(panel_report_path=panel, target_alpha=0.2)

        w2 = rep["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "not_multi_target_proof")
        self.assertFalse(w2["complete"])
        self.assertIn("panel_report_targets_missing", {f["kind"] for f in w2["failures"]})

    def test_predictor_contract_ready_is_w3_intermediate_status(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "predictor_contract.json")
            _write_json(contract, {
                "ok": True,
                "secondary_predictor": {"predictor_id": "chai1_complex"},
                "primary_records": ["boltz.jsonl"],
                "secondary_records": ["chai.jsonl"],
                "commands": {
                    "cross_predictor": "python -m bio_sfm_designer.experiments.complex_cross_predictor --records boltz.jsonl chai.jsonl",
                },
                "failures": [],
            })

            rep = run_status(predictor_contract_path=contract)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "second_predictor_contract_ready")
        self.assertEqual(w3["secondary_predictor"]["predictor_id"], "chai1_complex")
        self.assertIn("cross-predictor", w3["next_action"])
        self.assertIn("complex_cross_predictor", w3["commands"]["cross_predictor"])

    def test_predictor_contract_blocked_surfaces_failures(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "predictor_contract.json")
            sync_back = os.path.join(d, "second_predictor_sync_back.sh")
            _write_json(contract, {
                "ok": False,
                "secondary_predictor": {"predictor_id": "chai1_complex"},
                "commands": {
                    "secondary_qc": "python -m bio_sfm_designer.experiments.complex_records_qc --records missing",
                    "cross_predictor": "python -m bio_sfm_designer.experiments.complex_cross_predictor --records missing",
                },
                "pending_secondary_records": [{"path": "missing", "status": "missing"}],
                "failures": [{"kind": "missing_file", "field": "secondary_records"}],
            })

            rep = run_status(
                predictor_contract_path=contract,
                predictor_sync_back_plan=sync_back,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "second_predictor_contract_blocked")
        self.assertEqual(w3["failures"][0]["kind"], "missing_file")
        self.assertFalse(w3["commands_available"])
        self.assertEqual(w3["commands"], {})
        self.assertEqual(w3["blocked_command_keys"], ["cross_predictor", "secondary_qc"])
        self.assertEqual(w3["pending_secondary_records"], [{"path": "missing", "status": "missing"}])
        self.assertEqual(w3["sync_back_plan"], sync_back)
        self.assertIn("fix", w3["next_action"])
        self.assertIn(f"sync_back: bash {sync_back}", render_text(rep))
        self.assertEqual(rep["n_pending_external_artifacts"], 1)
        external = rep["pending_external_artifacts"][0]
        self.assertEqual(external["path"], "missing")
        self.assertEqual(external["categories"], ["second_predictor"])
        self.assertEqual(external["sync_back_plan"], sync_back)

    def test_cross_predictor_report_takes_precedence_over_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "predictor_contract.json")
            cross = os.path.join(d, "cross.json")
            _write_json(contract, {
                "ok": True,
                "secondary_predictor": {"predictor_id": "chai1_complex"},
                "commands": {"cross_predictor": "placeholder"},
            })
            _write_json(cross, _cross_predictor_ready_report(n=10))

            rep = run_status(predictor_contract_path=contract, cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "cross_predictor_ready")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["require_disjoint_record_files"])
        self.assertEqual(w3["record_files"][0]["predictors"], ["boltz2_complex"])

    def test_w3_decision_protocol_supersedes_cross_predictor_caveat(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            protocol = os.path.join(d, "w3_decision_protocol.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            cross_report = _cross_predictor_ready_report(n=30)
            cross_report["status"] = "single_model_caveat_open"
            cross_report["failures"] = [{
                "kind": "label_agreement_below_min",
                "pairs": [["boltz2_complex", "chai1_complex", 0.6]],
                "required": 0.8,
            }]
            _write_json(cross, cross_report)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=_sha256_file(adjudication),
                ),
            )

            rep = run_status(cross_predictor_path=cross, w3_decision_protocol_path=protocol)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["positive_claim_supported"])
        self.assertEqual(w3["claim_boundary"], "independent_predictor_robustness_not_supported")
        self.assertEqual(w3["current_protocol_verdict"], "negative_robustness_result_for_no_msa_chai")
        self.assertEqual(w3["cross_predictor_failure_kinds"], ["label_agreement_below_min"])
        self.assertEqual(w3["evidence"], os.path.abspath(protocol))
        self.assertEqual(w3["cross_predictor_evidence"], os.path.abspath(cross))
        self.assertEqual(
            w3["adjudication_set_artifact"]["out_jsonl"],
            adjudication,
        )
        self.assertTrue(w3["adjudication_set_artifact_audit"]["ok"])
        self.assertEqual(w3["adjudication_set_artifact_audit"]["n_rows"], 2)
        self.assertIn("adjudication set", w3["next_action"])

    def test_w3_next_protocol_attaches_no_spend_contract(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_next_protocol_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertTrue(w3["future_w3_spend_requires_explicit_approval"])
        self.assertEqual(
            w3["recommended_next_routes"],
            ["third_independent_predictor_or_protocol", "stronger_chai_msa_template_protocol"],
        )
        self.assertIn("third independent predictor", w3["next_action"])
        self.assertIn("w3_next_protocol_ready=True", render_text(rep))

    def test_w3_next_protocol_claim_leak_blocks_future_spend_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha, claim=True))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_next_protocol_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("repair W3 next-protocol", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_next_protocol_failures"]}
        self.assertIn("w3_next_protocol_claim_leak", kinds)

    def test_w3_challenge_manifest_attaches_no_submit_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_challenge_manifest_ready"])
        self.assertFalse(w3["w3_challenge_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertTrue(w3["future_w3_execution_requires_new_contract"])
        self.assertEqual(w3["w3_challenge_manifest"]["n_rows"], 2)
        self.assertIn("w3_challenge_manifest_ready=True", render_text(rep))

    def test_w3_challenge_manifest_execution_drift_blocks_future_wrapper_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(
                challenge,
                _w3_challenge_manifest(adjudication, adjudication_sha, execution_ready=True),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_challenge_manifest_ready"])
        self.assertFalse(w3["w3_challenge_execution_ready"])
        self.assertIn("repair W3 challenge manifest", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_challenge_manifest_failures"]}
        self.assertIn("w3_challenge_manifest_execution_ready_drift", kinds)

    def test_w3_third_predictor_contract_attaches_no_submit_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_third_predictor_contract_ready"])
        self.assertFalse(w3["w3_third_predictor_execution_ready"])
        self.assertTrue(w3["future_w3_execution_requires_approval_gated_wrapper"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(w3["w3_third_predictor_contract"]["n_rows"], 2)
        self.assertEqual(
            w3["w3_third_predictor_contract"]["planned_result_jsonl"],
            "results/m6d_w3_third_predictor_challenge_records.jsonl",
        )
        self.assertIn("w3_third_predictor_contract_ready=True", render_text(rep))

    def test_w3_third_predictor_contract_execution_drift_blocks_future_wrapper_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(
                third_contract,
                _w3_third_predictor_contract(
                    challenge,
                    challenge_sha,
                    execution_ready=True,
                    command_wrapper_emitted=True,
                    claim=True,
                ),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_third_predictor_contract_ready"])
        self.assertFalse(w3["w3_third_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("repair W3 third-predictor execution contract", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_third_predictor_contract_failures"]}
        self.assertIn("w3_third_predictor_contract_execution_ready_drift", kinds)
        self.assertIn("w3_third_predictor_contract_wrapper_emitted_drift", kinds)
        self.assertIn("w3_third_predictor_contract_claim_leak", kinds)

    def test_w3_predictor_selection_card_attaches_selected_no_submit_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_predictor_selection_card_ready"])
        self.assertEqual(w3["w3_selected_predictor_or_protocol_id"], "af2_multimer_colabfold_v1")
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertTrue(w3["future_w3_execution_requires_runtime_probe"])
        self.assertIn("runtime", w3["next_action"])
        self.assertIn("w3_predictor_selection_card_ready=True", render_text(rep))

    def test_w3_predictor_selection_card_runtime_drift_blocks_future_inputs_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(
                selection,
                _w3_predictor_selection_card(
                    third_contract,
                    third_sha,
                    runtime_ready=True,
                    execution_ready=True,
                    claim=True,
                ),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_predictor_selection_card_ready"])
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("repair W3 predictor selection card", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_predictor_selection_card_failures"]}
        self.assertIn("w3_predictor_selection_card_runtime_ready_drift", kinds)
        self.assertIn("w3_predictor_selection_card_execution_ready_drift", kinds)
        self.assertIn("w3_predictor_selection_card_claim_leak", kinds)

    def test_w3_runtime_probe_plan_attaches_no_submit_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(runtime_probe_plan, _w3_runtime_probe_plan(selection, selection_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_predictor_selection_card_ready"])
        self.assertTrue(w3["w3_runtime_probe_plan_ready"])
        self.assertFalse(w3["w3_runtime_probe_executed"])
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertTrue(w3["future_w3_execution_requires_input_manifest"])
        self.assertIn("no-submit runtime probe report", w3["next_action"])
        self.assertIn("w3_runtime_probe_plan_ready=True", render_text(rep))

    def test_w3_runtime_probe_plan_execution_drift_blocks_future_inputs_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(
                runtime_probe_plan,
                _w3_runtime_probe_plan(
                    selection,
                    selection_sha,
                    probe_executed=True,
                    runtime_ready=True,
                    execution_ready=True,
                    claim=True,
                ),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_runtime_probe_plan_ready"])
        self.assertFalse(w3["w3_runtime_probe_executed"])
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("repair W3 runtime-probe plan", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_runtime_probe_plan_failures"]}
        self.assertIn("w3_runtime_probe_plan_probe_executed_drift", kinds)
        self.assertIn("w3_runtime_probe_plan_runtime_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_plan_execution_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_plan_claim_leak", kinds)

    def test_w3_runtime_probe_report_attaches_local_no_submit_not_runtime_ready(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            runtime_probe_report = os.path.join(d, "w3_runtime_probe_report.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(runtime_probe_plan, _w3_runtime_probe_plan(selection, selection_sha))
            plan_sha = _sha256_file(runtime_probe_plan)
            _write_json(runtime_probe_report, _w3_runtime_probe_report(runtime_probe_plan, plan_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
                w3_runtime_probe_report_path=runtime_probe_report,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertTrue(w3["w3_runtime_probe_plan_ready"])
        self.assertTrue(w3["w3_runtime_probe_report_ready"])
        self.assertTrue(w3["w3_runtime_probe_executed"])
        self.assertFalse(w3["w3_runtime_probe_cayuga_executed"])
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("target Cayuga GPU surface", w3["next_action"])
        self.assertIn("w3_runtime_probe_report_ready=True", render_text(rep))

    def test_w3_runtime_probe_report_execution_drift_blocks_future_inputs_only(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            runtime_probe_report = os.path.join(d, "w3_runtime_probe_report.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(runtime_probe_plan, _w3_runtime_probe_plan(selection, selection_sha))
            plan_sha = _sha256_file(runtime_probe_plan)
            _write_json(
                runtime_probe_report,
                _w3_runtime_probe_report(
                    runtime_probe_plan,
                    plan_sha,
                    runtime_ready=True,
                    execution_ready=True,
                    claim=True,
                ),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
                w3_runtime_probe_report_path=runtime_probe_report,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "negative_robustness_result_adjudicated")
        self.assertTrue(w3["complete"])
        self.assertFalse(w3["w3_runtime_probe_report_ready"])
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("repair W3 runtime-probe report", w3["next_action"])
        kinds = {failure["kind"] for failure in w3["w3_runtime_probe_report_failures"]}
        self.assertIn("w3_runtime_probe_report_execution_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_report_claim_leak", kinds)

    def test_w3_runtime_repair_plan_attaches_next_repair_without_claim(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            runtime_probe_report = os.path.join(d, "w3_runtime_probe_report.json")
            runtime_repair_plan = os.path.join(d, "w3_runtime_repair_plan.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(runtime_probe_plan, _w3_runtime_probe_plan(selection, selection_sha))
            plan_sha = _sha256_file(runtime_probe_plan)
            _write_json(
                runtime_probe_report,
                _w3_runtime_probe_report(
                    runtime_probe_plan,
                    plan_sha,
                    probe_surface="cayuga_gpu_no_submit",
                ),
            )
            report_sha = _sha256_file(runtime_probe_report)
            _write_json(runtime_repair_plan, _w3_runtime_repair_plan(runtime_probe_report, report_sha))

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
                w3_runtime_probe_report_path=runtime_probe_report,
                w3_runtime_repair_plan_path=runtime_repair_plan,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertTrue(w3["w3_runtime_probe_report_ready"])
        self.assertTrue(w3["w3_runtime_repair_plan_ready"])
        self.assertEqual(
            w3["w3_runtime_repair_plan"]["failed_runtime_checks"],
            ["cli_help", "env_discovery", "gpu_stack"],
        )
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("ColabFold/JAX CUDA runtime", w3["next_action"])
        self.assertIn("w3_runtime_repair_plan_ready=True", render_text(rep))

    def test_w3_runtime_provision_packet_attaches_guarded_script_without_claim(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            next_protocol = os.path.join(d, "w3_next_protocol.json")
            challenge = os.path.join(d, "w3_challenge.json")
            third_contract = os.path.join(d, "w3_third_contract.json")
            selection = os.path.join(d, "w3_selection.json")
            runtime_probe_plan = os.path.join(d, "w3_runtime_probe_plan.json")
            runtime_probe_report = os.path.join(d, "w3_runtime_probe_report.json")
            runtime_repair_plan = os.path.join(d, "w3_runtime_repair_plan.json")
            runtime_provision_packet = os.path.join(d, "w3_runtime_provision_packet.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            adjudication_sha = _sha256_file(adjudication)
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256=adjudication_sha,
                ),
            )
            _write_json(next_protocol, _w3_next_protocol(adjudication, adjudication_sha))
            _write_json(challenge, _w3_challenge_manifest(adjudication, adjudication_sha))
            challenge_sha = _sha256_file(challenge)
            _write_json(third_contract, _w3_third_predictor_contract(challenge, challenge_sha))
            third_sha = _sha256_file(third_contract)
            _write_json(selection, _w3_predictor_selection_card(third_contract, third_sha))
            selection_sha = _sha256_file(selection)
            _write_json(runtime_probe_plan, _w3_runtime_probe_plan(selection, selection_sha))
            plan_sha = _sha256_file(runtime_probe_plan)
            _write_json(
                runtime_probe_report,
                _w3_runtime_probe_report(
                    runtime_probe_plan,
                    plan_sha,
                    probe_surface="cayuga_gpu_no_submit",
                ),
            )
            report_sha = _sha256_file(runtime_probe_report)
            _write_json(runtime_repair_plan, _w3_runtime_repair_plan(runtime_probe_report, report_sha))
            repair_sha = _sha256_file(runtime_repair_plan)
            _write_json(
                runtime_provision_packet,
                _w3_runtime_provision_packet(runtime_repair_plan, repair_sha),
            )

            rep = run_status(
                w3_decision_protocol_path=protocol,
                w3_next_protocol_path=next_protocol,
                w3_challenge_manifest_path=challenge,
                w3_third_predictor_contract_path=third_contract,
                w3_predictor_selection_card_path=selection,
                w3_runtime_probe_plan_path=runtime_probe_plan,
                w3_runtime_probe_report_path=runtime_probe_report,
                w3_runtime_repair_plan_path=runtime_repair_plan,
                w3_runtime_provision_packet_path=runtime_provision_packet,
            )

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertTrue(w3["w3_runtime_repair_plan_ready"])
        self.assertTrue(w3["w3_runtime_provision_packet_ready"])
        self.assertEqual(
            w3["w3_runtime_provision_packet"]["approval_env_var"],
            "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION",
        )
        self.assertFalse(w3["w3_selected_predictor_runtime_ready"])
        self.assertFalse(w3["w3_selected_predictor_execution_ready"])
        self.assertFalse(w3["can_claim_independent_predictor_robustness_now"])
        self.assertIn("W3_COLABFOLD_BIN", w3["next_action"])
        self.assertIn("w3_runtime_provision_packet_ready=True", render_text(rep))

    def test_w3_runtime_probe_report_allows_remote_plan_path_when_sha_matches(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "runtime_probe_plan.json")
            _write_json(plan, _w3_runtime_probe_plan("/remote/selection.json", "selection-sha"))
            plan_sha = _sha256_file(plan)
            status = {
                "w3_runtime_probe_plan_ready": True,
                "w3_runtime_probe_plan": {"path": plan},
                "w3_selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
            }
            report = _w3_runtime_probe_report(
                "/remote/home/bio_sfm_smoke/results/m6d_w3_runtime_probe_plan.json",
                plan_sha,
            )

            failures = _w3_runtime_probe_report_failures(report, status)

        kinds = {failure["kind"] for failure in failures}
        self.assertNotIn("w3_runtime_probe_report_plan_path_mismatch", kinds)
        self.assertNotIn("w3_runtime_probe_report_plan_sha_mismatch", kinds)

    def test_w3_decision_protocol_with_blockers_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            report = _w3_negative_decision_protocol()
            report["w3"]["strict_adjudication_integrity"] = False
            report["w3"]["strict_adjudication_integrity_blockers"] = ["copied_numeric_values"]
            _write_json(protocol, report)

            rep = run_status(w3_decision_protocol_path=protocol)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "w3_decision_protocol_blocked")
        self.assertFalse(w3["complete"])
        kinds = {failure["kind"] for failure in w3["failures"]}
        self.assertIn("w3_decision_protocol_integrity_not_strict", kinds)
        self.assertIn("w3_decision_protocol_integrity_blockers_present", kinds)

    def test_w3_decision_protocol_without_adjudication_set_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            report = _w3_negative_decision_protocol()
            report["w3"]["adjudication_set"] = {
                "discordant_target_ids": [],
                "concordant_success_control_ids": [],
            }
            _write_json(protocol, report)

            rep = run_status(w3_decision_protocol_path=protocol)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "w3_decision_protocol_blocked")
        self.assertFalse(w3["complete"])
        kinds = {failure["kind"] for failure in w3["failures"]}
        self.assertIn("w3_decision_protocol_adjudication_discordants_missing", kinds)
        self.assertIn("w3_decision_protocol_adjudication_controls_missing", kinds)

    def test_w3_decision_protocol_with_stale_adjudication_artifact_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            protocol = os.path.join(d, "w3_decision_protocol.json")
            adjudication = os.path.join(d, "w3_adjudication.jsonl")
            _write_jsonl(adjudication, [
                {"target_id": "d1", "adjudication_role": "discordant_boltz_chai_label"},
                {"target_id": "c1", "adjudication_role": "concordant_success_control"},
            ])
            _write_json(
                protocol,
                _w3_negative_decision_protocol(
                    adjudication_jsonl=adjudication,
                    adjudication_sha256="0" * 64,
                ),
            )

            rep = run_status(w3_decision_protocol_path=protocol)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "w3_decision_protocol_blocked")
        self.assertFalse(w3["complete"])
        kinds = {failure["kind"] for failure in w3["failures"]}
        self.assertIn("w3_adjudication_set_jsonl_sha256_mismatch", kinds)

    def test_cross_predictor_report_without_disjoint_record_file_audit_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            _write_json(cross, {
                "ok": True,
                "status": "cross_predictor_ready",
                "predictors": ["boltz2_complex", "chai1_complex"],
                "records_by_predictor": {"boltz2_complex": 10, "chai1_complex": 10},
                "failures": [],
            })

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        kinds = {f["kind"] for f in w3["failures"]}
        self.assertIn("cross_predictor_disjoint_record_files_not_required", kinds)
        self.assertIn("cross_predictor_record_file_audit_missing", kinds)

    def test_cross_predictor_mixed_record_file_audit_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            report["record_files"] = [
                {
                    "path": "mixed.jsonl",
                    "n_records": 20,
                    "n_blank": 0,
                    "predictors": ["boltz2_complex", "chai1_complex"],
                    "records_by_predictor": {"boltz2_complex": 10, "chai1_complex": 10},
                }
            ]
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        self.assertIn("mixed_predictor_record_file", {f["kind"] for f in w3["failures"]})

    def test_cross_predictor_report_with_reported_failures_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            report["failures"] = [{"kind": "copied_predictor_values"}]
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        kinds = {f["kind"] for f in w3["failures"]}
        self.assertIn("copied_predictor_values", kinds)
        self.assertIn("cross_predictor_report_has_failures", kinds)

    def test_cross_predictor_record_file_predictors_must_match_top_level(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            report["record_files"][1]["predictors"] = ["boltz2_complex"]
            report["record_files"][1]["records_by_predictor"] = {"boltz2_complex": 10}
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        kinds = {f["kind"] for f in w3["failures"]}
        self.assertIn("cross_predictor_record_file_too_few_predictors", kinds)
        self.assertIn("cross_predictor_record_file_predictor_mismatch", kinds)
        self.assertIn("cross_predictor_record_file_count_mismatch", kinds)

    def test_cross_predictor_record_file_counts_must_match_top_level(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            report["record_files"][0]["n_records"] = 9
            report["record_files"][0]["records_by_predictor"] = {"boltz2_complex": 9}
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        mismatches = [
            failure for failure in w3["failures"]
            if failure["kind"] == "cross_predictor_record_file_count_mismatch"
            and failure.get("expected") == {"boltz2_complex": 10, "chai1_complex": 10}
        ]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["actual"], {"boltz2_complex": 9, "chai1_complex": 10})

    def test_cross_predictor_report_without_pair_audit_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            report.pop("pairs")
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        self.assertIn("cross_predictor_pair_audit_missing", {f["kind"] for f in w3["failures"]})

    def test_cross_predictor_pair_overlap_and_agreement_must_meet_thresholds(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10, min_overlap=10, min_label_agreement=0.8)
            pair = report["pairs"][0]
            pair["n_overlap"] = 9
            pair["n_labeled_overlap"] = 8
            pair["meets_min_overlap"] = False
            pair["meets_min_labeled_overlap"] = False
            pair["label_agreement"] = 0.7
            pair["meets_min_label_agreement"] = False
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        kinds = {f["kind"] for f in w3["failures"]}
        self.assertIn("cross_predictor_pair_overlap_below_min", kinds)
        self.assertIn("cross_predictor_pair_labeled_overlap_below_min", kinds)
        self.assertIn("cross_predictor_pair_label_agreement_below_min", kinds)

    def test_cross_predictor_pair_provenance_identity_threshold_and_copy_checks_must_pass(self):
        with tempfile.TemporaryDirectory() as d:
            cross = os.path.join(d, "cross.json")
            report = _cross_predictor_ready_report(n=10)
            pair = report["pairs"][0]
            pair["provenance_complete"] = False
            pair["distinct_signal_sources"] = False
            pair["complex_target_id_agree"] = False
            pair["label_threshold_agree"] = False
            pair["copied_numeric_values"] = True
            _write_json(cross, report)

            rep = run_status(cross_predictor_path=cross)

        w3 = rep["workstreams"]["W3_independent_predictor"]
        self.assertEqual(w3["status"], "single_model_caveat_open")
        self.assertFalse(w3["complete"])
        kinds = {f["kind"] for f in w3["failures"]}
        self.assertIn("cross_predictor_pair_provenance_weak", kinds)
        self.assertIn("cross_predictor_pair_target_identity_weak", kinds)
        self.assertIn("cross_predictor_pair_label_threshold_mismatch", kinds)
        self.assertIn("cross_predictor_pair_copied_numeric_values", kinds)

    def test_complete_artifacts_mark_m6_complex_evidence_ready(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            panel = os.path.join(d, "panel.json")
            cross = os.path.join(d, "cross.json")
            _write_json(decision, _alpha_decision_ready_report(target_alpha=0.2, n_records=500, n_cal=320))
            _write_json(panel, _panel_ready_report(n_records_per_target=300))
            _write_json(cross, _cross_predictor_ready_report())

            rep = run_status(decision_path=decision, panel_report_path=panel,
                             cross_predictor_path=cross)
        self.assertFalse(rep["complete"])
        self.assertEqual(rep["status"], "m6_complex_evidence_ready")
        self.assertIn("run_batch_round", rep["next_action"])
        text = render_text(rep)
        self.assertIn("W1_M6c_scale_up: certified", text)
        self.assertIn("W2_multi_target_panel: multi_target_certified", text)
        self.assertIn("W3_independent_predictor: cross_predictor_ready", text)
        self.assertIn("W4_closed_loop_DBTL: missing", text)

    def test_w4_preflight_blocked_surfaces_failures(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            sync_back = os.path.join(d, "w4_sync_back.sh")
            _write_json(preflight, {
                "ok": False,
                "n_candidates": 2,
                "strict_complex_records": True,
                "pending_artifacts": [{"artifact": "records", "path": "missing.jsonl"}],
                "failures": [{"kind": "missing_screen_verdict", "ids": ["design-1"]}],
            })

            rep = run_status(batch_preflight_path=preflight, batch_sync_back_plan=sync_back)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_preflight_blocked")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["failures"][0]["kind"], "missing_screen_verdict")
        self.assertEqual(w4["pending_artifacts"], [{"artifact": "records", "path": "missing.jsonl"}])
        self.assertEqual(w4["sync_back_plan"], sync_back)
        self.assertEqual(rep["pending_input_prep_paths"], [])
        self.assertEqual(rep["n_pending_external_artifacts"], 1)
        external = rep["pending_external_artifacts"][0]
        self.assertEqual(external["path"], "missing.jsonl")
        self.assertEqual(external["categories"], ["closed_loop_batch"])
        self.assertEqual(external["artifacts"], ["records"])
        self.assertEqual(external["sync_back_plan"], sync_back)
        text = render_text(rep)
        self.assertIn(f"sync_back: bash {sync_back}", text)

    def test_w4_preflight_ready_requires_summary(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": _gate_prevalidation(),
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_preflight_ready")
        self.assertFalse(w4["complete"])
        self.assertIn("summary", w4["next_action"])
        self.assertTrue(w4["gate_prevalidation"]["ok"])

    def test_w4_preflight_not_strict_is_not_closed_loop_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": False,
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_preflight_not_strict")
        self.assertFalse(w4["complete"])
        self.assertIn("--strict-complex-records", w4["next_action"])

    def test_w4_preflight_requires_conformal_gate_prevalidation(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_gate_prevalidation_missing")
        self.assertFalse(w4["complete"])
        self.assertIn("--prevalidate-records", w4["next_action"])

    def test_w4_preflight_surfaces_missing_prevalidation_records(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": False,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": {
                    "requested": True,
                    "ok": False,
                    "paths": [],
                    "n_records": 0,
                    "regimes": {},
                    "conformal_alpha": 0.3,
                    "conformal_delta": 0.1,
                    "failures": [
                        {
                            "kind": "missing_prevalidation_records",
                            "message": "conformal_alpha requires prior verified prevalidation records",
                        },
                    ],
                },
                "failures": [
                    {
                        "kind": "gate_prevalidation_blocked",
                        "message": "fix prior gate prevalidation records before W4 routing",
                    },
                ],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_gate_prevalidation_blocked")
        self.assertFalse(w4["complete"])
        self.assertIn(
            "missing_prevalidation_records",
            {f["kind"] for f in w4["failures"]},
        )
        self.assertIn("gate_prevalidation_blocked", {f["kind"] for f in w4["preflight_failures"]})

    def test_w4_preflight_requires_recorded_complex_tau(self):
        gate = _gate_prevalidation()
        gate["regimes"]["complex"]["tau"] = None
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_complex_gate_tau_missing")
        self.assertFalse(w4["complete"])

    def test_w4_preflight_requires_batch_contract_audit(self):
        gate = _gate_prevalidation()
        gate.pop("batch_contract")
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_gate_contract_missing")
        self.assertFalse(w4["complete"])
        self.assertIn("batch", w4["message"])

    def test_w4_preflight_blocks_batch_contract_mismatch(self):
        gate = _gate_prevalidation()
        gate["batch_contract"]["ok"] = False
        gate["batch_contract"]["regimes"]["complex"]["ok"] = False
        gate["batch_contract"]["failures"] = [
            {
                "kind": "prevalidation_batch_contract_field_mismatch",
                "field": "lrmsd_threshold",
            },
        ]
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })

            rep = run_status(batch_preflight_path=preflight)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_gate_contract_blocked")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["failures"][0]["field"], "lrmsd_threshold")

    def test_w4_closed_loop_round_complete_requires_campaign_and_matching_summary(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "candidate_ids": [f"design-{i}" for i in range(4)],
                "n_records": 192,
                "n_verdicts": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "target": "benign interface campaign",
                "objective": "interface_quality",
                "lambda": 0.5,
                "assays_used": 4,
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "screen_backend": "precomputed_deberta",
                "aggregate": {
                    "n": 4,
                    "trust_rate": 0.0,
                    "verify_rate": 1.0,
                    "default_rate": 0.0,
                    "defer_rate": 0.0,
                    "net_reward_per_item": 0.5,
                },
                "per_round": [{"round": 0, "n": 4}],
            })
            _write_jsonl(campaign, [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "closed_loop_round_complete")
        self.assertTrue(w4["complete"])
        self.assertEqual(w4["n_routed"], 4)
        self.assertEqual(w4["campaign_records"], 4)
        self.assertEqual(w4["campaign"], campaign)
        self.assertTrue(w4["gate_calibrated"])
        self.assertEqual(w4["gate_prevalidation"]["conformal_alpha"], 0.3)

    def test_w4_campaign_row_count_must_match_summary_count(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(campaign, [{"candidate_id": "design-0", "action": "verify_assay"}])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["campaign_records"], 1)
        self.assertEqual(w4["n_routed"], 4)
        self.assertIn("same DBTL batch run", w4["next_action"])

    def test_w4_summary_per_round_count_must_match_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
                "per_round": [{"round": 0, "n": 3}],
            })
            _write_jsonl(
                campaign,
                [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_summary_per_round_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["n_routed"], 4)
        self.assertEqual(w4["per_round_mismatches"][0]["field"], "per_round.n_sum")
        self.assertEqual(w4["per_round_mismatches"][0]["expected"], 4)
        self.assertEqual(w4["per_round_mismatches"][0]["actual"], 3)

    def test_w4_campaign_candidate_ids_must_be_unique(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(campaign, [
                {"candidate_id": "design-0", "action": "verify_assay"},
                {"candidate_id": "design-0", "action": "trust_sfm"},
                {"candidate_id": "design-1", "action": "verify_assay"},
                {"candidate_id": "design-2", "action": "verify_assay"},
            ])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_invalid")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["duplicate_candidate_ids"], ["design-0"])

    def test_w4_campaign_candidate_ids_must_match_preflight_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "candidate_ids": [f"design-{i}" for i in range(4)],
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(campaign, [
                {"candidate_id": "design-0", "action": "verify_assay"},
                {"candidate_id": "design-1", "action": "verify_assay"},
                {"candidate_id": "design-2", "action": "verify_assay"},
                {"candidate_id": "design-x", "action": "verify_assay"},
            ])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_preflight_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["expected_candidate_ids"], [f"design-{i}" for i in range(4)])
        self.assertEqual(w4["campaign_candidate_ids"], ["design-0", "design-1", "design-2", "design-x"])

    def test_w4_campaign_action_must_be_known_dtbl_action(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(campaign, [
                {"candidate_id": "design-0", "action": "verify_assay"},
                {"candidate_id": "design-1", "action": "trust_sfm"},
                {"candidate_id": "design-2", "action": "default_baseline"},
                {"candidate_id": "design-3", "action": "manual_override"},
            ])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_invalid")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["invalid_action_records"], [{"line": 4, "action": "manual_override"}])
        self.assertIn("verify_assay", w4["allowed_actions"])

    def test_w4_campaign_action_mix_must_match_summary_rates(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {
                    "n": 4,
                    "trust_rate": 0.5,
                    "verify_rate": 0.5,
                    "default_rate": 0.0,
                    "defer_rate": 0.0,
                },
            })
            _write_jsonl(campaign, [
                {"candidate_id": f"design-{i}", "action": "verify_assay"}
                for i in range(4)
            ])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_action_mismatch")
        self.assertFalse(w4["complete"])
        by_field = {item["rate_field"]: item for item in w4["action_rate_mismatches"]}
        self.assertEqual(by_field["trust_rate"]["actual_rate"], 0.0)
        self.assertEqual(by_field["verify_rate"]["actual_rate"], 1.0)

    def test_w4_campaign_assay_count_must_match_summary_assays_used(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "assays_used": 3,
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(
                campaign,
                [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_assay_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["assay_count_mismatches"][0]["field"], "assays_used")
        self.assertEqual(w4["assay_count_mismatches"][0]["expected"], 3)
        self.assertEqual(w4["assay_count_mismatches"][0]["actual"], 4)

    def test_w4_summary_best_candidate_must_exist_in_campaign(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 2,
                "candidate_ids": ["design-0", "design-1"],
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 2},
                "best": {"candidate_id": "design-x", "realized_quality": 0.9, "round": 0},
            })
            _write_jsonl(
                campaign,
                [
                    {"round": 0, "candidate_id": "design-0", "action": "trust_sfm",
                     "hidden_truth": {"quality": 0.7}},
                    {"round": 0, "candidate_id": "design-1", "action": "defer",
                     "hidden_truth": {"quality": 0.1}},
                ],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_best_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["best_mismatches"][0]["field"], "best.candidate_id")
        self.assertEqual(w4["best_mismatches"][0]["reason"], "not_in_campaign")
        self.assertEqual(w4["best_mismatches"][0]["candidate_id"], "design-x")

    def test_w4_summary_best_candidate_must_have_advancing_action(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 2,
                "candidate_ids": ["design-0", "design-1"],
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 2},
                "best": {"candidate_id": "design-0", "realized_quality": 0.7, "round": 0},
            })
            _write_jsonl(
                campaign,
                [
                    {"round": 0, "candidate_id": "design-0", "action": "defer",
                     "hidden_truth": {"quality": 0.7}},
                    {"round": 0, "candidate_id": "design-1", "action": "trust_sfm",
                     "hidden_truth": {"quality": 0.1}},
                ],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_best_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["best_mismatches"][0]["field"], "best.action")
        self.assertEqual(w4["best_mismatches"][0]["candidate_id"], "design-0")
        self.assertEqual(w4["best_mismatches"][0]["actual"], "defer")
        self.assertEqual(w4["best_mismatches"][0]["allowed"], ["default_baseline", "trust_sfm"])

    def test_w4_summary_best_candidate_must_be_highest_quality_advancing_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 3,
                "candidate_ids": ["design-0", "design-1", "design-2"],
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "aggregate": {"n": 3},
                "best": {"candidate_id": "design-0", "realized_quality": 0.7, "round": 0},
            })
            _write_jsonl(
                campaign,
                [
                    {"round": 0, "candidate_id": "design-0", "action": "trust_sfm",
                     "hidden_truth": {"quality": 0.7}},
                    {"round": 0, "candidate_id": "design-1", "action": "default_baseline",
                     "hidden_truth": {"quality": 0.8}},
                    {"round": 0, "candidate_id": "design-2", "action": "verify_assay",
                     "hidden_truth": {"quality": 0.95}},
                ],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "campaign_summary_best_mismatch")
        self.assertFalse(w4["complete"])
        self.assertEqual(w4["best_mismatches"][0]["field"], "best.max_realized_quality")
        self.assertEqual(w4["best_mismatches"][0]["candidate_id"], "design-0")
        self.assertEqual(w4["best_mismatches"][0]["actual_quality"], 0.7)
        self.assertEqual(w4["best_mismatches"][0]["better_candidate_id"], "design-1")
        self.assertEqual(w4["best_mismatches"][0]["better_action"], "default_baseline")
        self.assertEqual(w4["best_mismatches"][0]["better_quality"], 0.8)

    def test_w4_summary_contract_must_match_preflight_contract(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            summary_gate = _gate_prevalidation()
            summary_gate["batch_contract"]["regimes"]["complex"]["fields"]["lrmsd_threshold"]["batch"]["values"] = [5.0]
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": True,
                "gate_prevalidation": summary_gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(campaign, [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)])

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_summary_gate_contract_mismatch")
        self.assertFalse(w4["complete"])

    def test_w4_summary_must_prove_gate_calibrated(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "gate_calibrated": False,
                "gate_prevalidation": gate,
                "aggregate": {"n": 4},
            })
            _write_jsonl(
                campaign,
                [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)],
            )

            rep = run_status(batch_preflight_path=preflight, batch_summary_path=summary)

        w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
        self.assertEqual(w4["status"], "batch_summary_not_gate_calibrated")
        self.assertFalse(w4["complete"])

    def test_all_w1_to_w4_artifacts_mark_closed_loop_ready(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            panel = os.path.join(d, "panel.json")
            cross = os.path.join(d, "cross.json")
            preflight = os.path.join(d, "preflight.json")
            summary = os.path.join(d, "summary.json")
            campaign = os.path.join(d, "campaign.jsonl")
            gate = _gate_prevalidation()
            _write_json(decision, _alpha_decision_ready_report(target_alpha=0.2, n_records=500, n_cal=320))
            _write_json(panel, _panel_ready_report(n_records_per_target=300))
            _write_json(cross, _cross_predictor_ready_report())
            _write_json(preflight, {
                "ok": True,
                "n_candidates": 4,
                "strict_complex_records": True,
                "gate_prevalidation": gate,
                "failures": [],
            })
            _write_json(summary, {
                "assays_used": 4,
                "gate_calibrated": True,
                "gate_prevalidation": gate,
                "screen_backend": "precomputed_deberta",
                "aggregate": {"n": 4, "verify_rate": 1.0, "net_reward_per_item": 0.5},
            })
            _write_jsonl(
                campaign,
                [{"candidate_id": f"design-{i}", "action": "verify_assay"} for i in range(4)],
            )

            rep = run_status(decision_path=decision, panel_report_path=panel,
                             cross_predictor_path=cross,
                             batch_preflight_path=preflight,
                             batch_summary_path=summary)

        self.assertTrue(rep["complete"])
        self.assertEqual(rep["status"], "m6_complex_closed_loop_ready")
        self.assertIn("de-novo", rep["next_action"])


if __name__ == "__main__":
    unittest.main()
