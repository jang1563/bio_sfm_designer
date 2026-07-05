"""Tests for the W2 target-family redesign branch artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_family_redesign import (
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


def _diagnostic():
    return {
        "panel_status": "multi_target_evaluable_not_certified",
        "target_alpha": 0.2,
        "n_targets": 4,
        "n_records": 400,
        "summary": {
            "low_success_targets": ["low_A"],
            "cutoff_failure_targets": [],
            "recommendation": "redesign_or_replace_low_success_targets",
        },
        "targets": [
            {
                "complex_target_id": "low_A",
                "classification": "target_protocol_mismatch_low_success",
                "recommended_action": "replace_target_or_redesign_generation_protocol_before_more_gpu",
                "n_records": 100,
                "success": 3,
                "success_rate": 0.03,
                "median_pae_interaction": 9.0,
                "protocol_cutoff_accepts": 0,
            },
            {
                "complex_target_id": "retain_B",
                "classification": "underpowered_or_split_sensitive",
                "recommended_action": "keep_as_anchor_or_scale_only_after_split_sensitivity_check",
                "n_records": 100,
                "success": 100,
                "success_rate": 1.0,
                "median_pae_interaction": 2.8,
                "protocol_cutoff_accepts": 80,
            },
            {
                "complex_target_id": "hold_C",
                "classification": "underpowered_low_pae_acceptance",
                "recommended_action": "do_not_scale_until_low_pae_acceptance_strategy_exists",
                "n_records": 100,
                "success": 100,
                "success_rate": 1.0,
                "median_pae_interaction": 5.0,
                "protocol_cutoff_accepts": 0,
            },
            {
                "complex_target_id": "cert_D",
                "classification": "already_certified",
                "recommended_action": "retain_as_positive_control",
                "n_records": 100,
                "success": 98,
                "success_rate": 0.98,
                "median_pae_interaction": 3.2,
                "protocol_cutoff_accepts": 20,
            },
        ],
    }


def _previous_rules():
    return {
        "excluded_targets_under_current_protocol": ["old_excluded"],
        "anchors_not_for_immediate_scale": ["old_anchor"],
        "positive_controls_not_generalization_targets": ["positive_control"],
        "candidate_requirements": {
            "min_ca_interface_contacts": 20,
            "min_non_anchor_candidates_for_revised_manifest": 3,
            "require_source_pdb_deduplication": True,
        },
        "pilot_evidence_requirements": {
            "disallow_pooled_only_claim": True,
            "required_panel_report_status_before_claim": "multi_target_certified",
        },
        "panel_contract": {
            "complex_target_id": "required",
            "target_alpha": 0.2,
        },
    }


class M6DW2TargetFamilyRedesignTests(unittest.TestCase):
    def test_build_report_freezes_target_family_rules(self):
        rep = build_report(_diagnostic(), _previous_rules())

        self.assertEqual(rep["branch_id"], "w2_target_family_redesign_v1")
        self.assertTrue(rep["ready_for_candidate_pool_screen"])
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertIn("low_A", rep["target_sets"]["drop_or_redesign_targets"])
        self.assertIn("hold_C", rep["target_sets"]["signal_strategy_hold_targets"])
        self.assertIn("cert_D", rep["target_sets"]["target_specific_certified_targets"])
        self.assertIn("cert_D", rep["target_sets"]["positive_controls_not_generalization_targets"])
        self.assertIn("retain_B", rep["target_sets"]["anchors_not_for_immediate_scale"])
        self.assertIn("old_excluded", rep["target_sets"]["excluded_targets_under_current_protocol"])
        self.assertIn("retain", rep["target_sets"]["excluded_source_ids_under_current_protocol"])
        self.assertIn("cert", rep["target_sets"]["excluded_source_ids_under_current_protocol"])
        self.assertIn("1/4 current targets certified target-wise", rep["claim_boundary"]["target_wise_gate"])

    def test_candidate_rules_exclude_low_success_and_signal_hold(self):
        rep = build_report(_diagnostic(), _previous_rules())
        rules = build_candidate_rules(rep, _previous_rules())

        excluded = set(rules["excluded_targets_under_current_protocol"])
        anchors = set(rules["anchors_not_for_immediate_scale"])

        self.assertIn("low_A", excluded)
        self.assertIn("hold_C", excluded)
        self.assertIn("old_excluded", excluded)
        self.assertIn("retain_B", anchors)
        self.assertIn("cert_D", rules["positive_controls_not_generalization_targets"])
        self.assertIn("cert_D", rules["certified_targets_not_generalization_targets"])
        self.assertIn("retain", rules["excluded_source_ids_under_current_protocol"])
        self.assertIn("cert", rules["excluded_source_ids_under_current_protocol"])
        self.assertFalse(rules["ready_for_cayuga_submission"])
        self.assertFalse(rules["spend_gate"]["cayuga_submission_allowed"])
        self.assertEqual(
            rules["pilot_evidence_requirements"]["required_panel_report_status_before_claim"],
            "multi_target_certified",
        )

    def test_candidate_rules_can_require_gate_strategy_report(self):
        rep = build_report(_diagnostic(), _previous_rules())
        rules = build_candidate_rules(
            rep,
            _previous_rules(),
            gate_strategy_report="results/gate_strategy.json",
        )

        self.assertEqual(rules["gate_strategy_report"], "results/gate_strategy.json")
        self.assertIn(
            "predeclare label-degeneracy handling for all-success targets before using them as gate evidence",
            rules["gate_strategy_preconditions"],
        )
        self.assertEqual(
            rules["spend_gate"]["unlock_conditions"][0],
            "resolve gate-strategy blockers before any W2 Cayuga panel",
        )

    def test_markdown_renders_branch_and_boundary(self):
        md = render_markdown(build_report(_diagnostic(), _previous_rules()))

        self.assertIn("w2_target_family_redesign_v1", md)
        self.assertIn("Pooled-only diagnostics are not sufficient", md)
        self.assertIn("low_A", md)
        self.assertIn("retain_B", md)
        self.assertIn("cert_D", md)
        self.assertIn("target-specific certified, not W2 generalization", md)

    def test_cli_writes_design_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            diagnostic = os.path.join(d, "diag.json")
            previous = os.path.join(d, "previous.json")
            out_json = os.path.join(d, "design.json")
            out_md = os.path.join(d, "design.md")
            rules = os.path.join(d, "rules.json")
            _write_json(diagnostic, _diagnostic())
            _write_json(previous, _previous_rules())

            rc = main([
                "--redesign-diagnostic", diagnostic,
                "--previous-rules", previous,
                "--branch-id", "w2_target_family_redesign_v2",
                "--out-json", out_json,
                "--out-md", out_md,
                "--emit-candidate-rules", rules,
                "--gate-strategy-report", "results/gate_strategy.json",
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(rules))
            with open(out_json) as fh:
                design = json.load(fh)
            with open(rules) as fh:
                emitted_rules = json.load(fh)
            self.assertEqual(design["branch_id"], "w2_target_family_redesign_v2")
            self.assertIn(
                "configs/w2_target_family_redesign_v2_candidate_rules.json",
                design["next_artifacts_to_create"],
            )
            self.assertEqual(emitted_rules["branch_id"], "w2_target_family_redesign_v2")
            self.assertEqual(emitted_rules["protocol_id"], "w2_target_family_redesign_v2")
            self.assertEqual(emitted_rules["gate_strategy_report"], "results/gate_strategy.json")


if __name__ == "__main__":
    unittest.main()
