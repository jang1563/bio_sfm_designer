"""Tests for the M6d W2 next-branch design artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_next_branch_design import (
    build_candidate_rules,
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


class M6DW2NextBranchDesignTests(unittest.TestCase):
    def test_zero_admission_fresh_low_success_selects_protocol_redesign(self):
        revised = {
            "status": "candidate_discovery_required_before_next_w2_submission",
            "target_sets": {
                "rejected_or_held_targets": ["fresh_bad", "held"],
                "frozen_target_specific_positive_controls": ["3PC8_AB"],
                "anchors_not_for_immediate_scale": ["1BRS_AD"],
            },
            "target_decisions": [{
                "target": "held",
                "branch_decision": "hold_until_low_pae_acceptance_strategy_changes",
            }],
        }
        screen = {
            "status": "no_current_non_anchor_admissions",
            "n_candidates": 2,
            "n_admitted_for_pilot": 0,
            "ready_for_revised_manifest": False,
            "ready_for_cayuga_submission": False,
            "screened_targets": [
                {"target": "fresh_bad", "verdict": "reject_for_current_w2_branch"},
                {"target": "held", "verdict": "hold_until_low_pae_acceptance_strategy_changes"},
            ],
        }
        fresh = {
            "summary": {"recommendation": "redesign_or_replace_low_success_targets"},
            "targets": [{
                "complex_target_id": "fresh_bad",
                "classification": "target_protocol_mismatch_low_success",
            }],
        }

        rep = build_report(revised, screen, fresh)

        self.assertEqual(rep["status"], "no_spend_protocol_and_target_redesign_required")
        self.assertEqual(rep["selected_design"], "protocol_redesign_plus_success_enriched_discovery_v1")
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertIn("known_candidate_pool_has_zero_admissions", rep["blocked_reasons"])
        self.assertIn("fresh_bad", rep["target_sets"]["fresh_low_success_targets"])

        rules = build_candidate_rules(rep)
        self.assertFalse(rules["spend_gate"]["cayuga_submission_allowed"])
        self.assertIn("fresh_bad", rules["excluded_targets_under_current_protocol"])
        self.assertEqual(
            rules["candidate_requirements"]["min_non_anchor_candidates_for_revised_manifest"],
            3,
        )

    def test_admitted_candidate_selects_manifest_design_but_not_submit_ready(self):
        revised = {"status": "candidate_discovery_required_before_next_w2_submission", "target_sets": {}}
        screen = {
            "status": "pilot_candidates_admitted",
            "n_candidates": 3,
            "n_admitted_for_pilot": 1,
            "ready_for_revised_manifest": True,
            "ready_for_cayuga_submission": False,
            "screened_targets": [{"target": "new", "verdict": "admitted_for_pilot_candidate_pool"}],
        }
        fresh = {"summary": {"recommendation": "add_target_wise_scale_or_adjust_split"}, "targets": []}

        rep = build_report(revised, screen, fresh)

        self.assertEqual(rep["selected_design"], "build_revised_manifest_from_admitted_candidates")
        self.assertTrue(rep["ready_for_revised_manifest"])
        self.assertFalse(rep["ready_for_cayuga_submission"])

    def test_render_markdown_names_selected_design_and_preconditions(self):
        rep = {
            "date": "2026-06-30",
            "status": "no_spend_protocol_and_target_redesign_required",
            "selected_design": "protocol_redesign_plus_success_enriched_discovery_v1",
            "ready_for_revised_manifest": False,
            "ready_for_cayuga_submission": False,
            "known_pool": {"n_candidates": 12, "n_admitted_for_pilot": 0, "status": "none"},
            "blocked_reasons": ["known_candidate_pool_has_zero_admissions"],
            "target_sets": {"fresh_low_success_targets": ["1AK4_BC"]},
            "design_tracks": [{
                "priority": 1,
                "name": "success_enriched_target_discovery",
                "purpose": "find targets",
                "exit_to_cayuga": "after strict preflight",
            }],
            "manifest_preconditions": ["at least three non-anchor candidates"],
            "next_artifacts_to_create": ["candidate rules"],
            "next_action": "create a spec",
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Next Branch Design", md)
        self.assertIn("protocol_redesign_plus_success_enriched_discovery_v1", md)
        self.assertIn("Ready for Cayuga submission: `false`", md)
        self.assertIn("at least three non-anchor candidates", md)

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            revised = os.path.join(d, "revised.json")
            screen = os.path.join(d, "screen.json")
            fresh = os.path.join(d, "fresh.json")
            w3 = os.path.join(d, "w3.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            rules = os.path.join(d, "rules.json")
            _write_json(revised, {"status": "x", "target_sets": {}})
            _write_json(screen, {
                "status": "no_current_non_anchor_admissions",
                "n_candidates": 0,
                "n_admitted_for_pilot": 0,
                "ready_for_revised_manifest": False,
                "ready_for_cayuga_submission": False,
                "screened_targets": [],
            })
            _write_json(fresh, {"summary": {"recommendation": "x"}, "targets": []})
            _write_json(w3, {"w3": {"status": "protocol_selected"}})

            rc = main([
                "--revised-branch", revised,
                "--candidate-screen", screen,
                "--fresh-diagnostic", fresh,
                "--w3-decision", w3,
                "--out-json", out_json,
                "--out-md", out_md,
                "--emit-candidate-rules", rules,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(rules))


if __name__ == "__main__":
    unittest.main()
