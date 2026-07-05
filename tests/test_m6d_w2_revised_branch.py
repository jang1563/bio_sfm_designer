"""Tests for the M6d W2 revised branch artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_revised_branch import (
    DEFAULT_EXTRA_DIAGNOSTICS,
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


class M6DW2RevisedBranchTests(unittest.TestCase):
    def test_build_report_keeps_branch_non_runnable_without_admitted_targets(self):
        goal = {"objective": "continue"}
        decision = {
            "w2": {
                "targets": [
                    {
                        "target": "3PC8_AB",
                        "role": "freeze_target_specific_certificate",
                        "classification": "underpowered_low_pae_acceptance",
                        "success_rate": 0.53,
                        "alpha_0_3_seed_rate": 1.0,
                        "median_extra_records_for_alpha_0_2": 22,
                    },
                    {
                        "target": "weak",
                        "role": "drop_or_replace",
                        "classification": "target_protocol_mismatch_low_success",
                        "success_rate": 0.1,
                    },
                ]
            }
        }
        redesign = {"targets": []}
        followup = {"targets": []}

        rep = build_report(goal, decision, redesign, followup)

        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertFalse(rep["can_mark_goal_complete"])
        by_target = {row["target"]: row for row in rep["target_decisions"]}
        self.assertEqual(
            by_target["3PC8_AB"]["branch_decision"],
            "freeze_as_target_specific_positive_control",
        )
        self.assertEqual(
            by_target["weak"]["branch_decision"],
            "reject_for_current_w2_branch",
        )
        self.assertIn("weak", rep["target_sets"]["rejected_or_held_targets"])

    def test_render_markdown_marks_not_submit_plan(self):
        rep = {
            "date": "2026-06-30",
            "status": "candidate_discovery_required_before_next_w2_submission",
            "ready_for_cayuga_submission": False,
            "selected_branch": {
                "rationale": "Need candidates.",
                "not_a_submit_plan_reason": "No current set satisfies rules.",
            },
            "target_decisions": [],
            "future_candidate_admission_rules": ["require pilot evidence"],
            "next_artifacts_to_create": ["new candidate screen"],
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Revised Branch", md)
        self.assertIn("Ready for Cayuga submission: `false`", md)
        self.assertIn("Not a submit plan", md)

    def test_build_report_folds_in_extra_fresh_diagnostic(self):
        goal = {"objective": "continue"}
        decision = {"w2": {"targets": []}}
        redesign = {"targets": []}
        followup = {"targets": []}
        fresh = {
            "targets": [{
                "complex_target_id": "1AK4_BC",
                "classification": "target_protocol_mismatch_low_success",
                "recommended_action": "replace_target_or_redesign_generation_protocol_before_more_gpu",
                "success_rate": 0.02,
                "protocol_cutoff_accepts": 0,
            }]
        }

        rep = build_report(goal, decision, redesign, followup, [fresh])

        by_target = {row["target"]: row for row in rep["target_decisions"]}
        self.assertEqual(
            by_target["1AK4_BC"]["branch_decision"],
            "reject_for_current_w2_branch",
        )
        self.assertIn("1AK4_BC", rep["target_sets"]["rejected_or_held_targets"])

    def test_default_extra_diagnostics_include_initial_and_fresh_negatives(self):
        self.assertIn("results/m6c_w2_redesign_diagnostic.json", DEFAULT_EXTRA_DIAGNOSTICS)
        self.assertIn(
            "results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json",
            DEFAULT_EXTRA_DIAGNOSTICS,
        )

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            goal = os.path.join(d, "goal.json")
            decision = os.path.join(d, "decision.json")
            redesign = os.path.join(d, "redesign.json")
            followup = os.path.join(d, "followup.json")
            out_json = os.path.join(d, "branch.json")
            out_md = os.path.join(d, "branch.md")
            _write_json(goal, {"objective": "x"})
            _write_json(decision, {"w2": {"targets": []}})
            _write_json(redesign, {"targets": []})
            _write_json(followup, {"targets": []})

            rc = main([
                "--goal-anchor", goal,
                "--decision-protocol", decision,
                "--redesign-diagnostic", redesign,
                "--followup-diagnostic", followup,
                "--extra-diagnostic", redesign,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
