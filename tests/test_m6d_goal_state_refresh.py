"""Tests for terminal-W2b / prospective-W2c goal-state refresh."""

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
