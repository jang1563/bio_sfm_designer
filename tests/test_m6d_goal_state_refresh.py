"""Tests for the terminal-W2b / precompute-W2c goal-state refresh."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_state_refresh import main, refresh_bundle


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
        "locked_scientific_digest": "abc",
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
                "--updated-at", "2026-07-12T12:00:00+09:00",
                "--test-command", "pytest",
                "--test-result", "passed",
                "--out-json", paths["report"],
                "--out-md", paths["report_md"],
            ]

            self.assertEqual(main(argv), 0)
            for key, path in paths.items():
                if key == "target_msa_packet":
                    continue
                self.assertTrue(os.path.exists(path), path)
            with open(paths["anchor"]) as handle:
                anchor = json.load(handle)
            self.assertEqual(anchor["current_status"]["w2c"], "w2c_design_power_qualified_no_submit")


if __name__ == "__main__":
    unittest.main()
