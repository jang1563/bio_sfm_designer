"""Tests for W2 target-family follow-up contracts."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_family_followup import (
    build_candidate_rules,
    build_contract,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _panel_report():
    return {
        "ok": False,
        "panel_status": "multi_target_evaluable_not_certified",
        "target_alpha": 0.2,
        "n_targets": 3,
        "n_records": 300,
        "targets": [
            {"complex_target_id": "weak", "status": "not_certified", "certified": False},
            {"complex_target_id": "hold", "status": "not_certified", "certified": False},
            {"complex_target_id": "control", "status": "certified", "certified": True},
        ],
    }


def _diagnostic():
    return {
        "diagnostic": "complex_panel_redesign",
        "summary": {"recommendation": "redesign_or_replace_low_success_targets"},
        "targets": [
            {
                "complex_target_id": "weak",
                "classification": "target_protocol_mismatch_low_success",
            },
            {
                "complex_target_id": "hold",
                "classification": "underpowered_low_pae_acceptance",
            },
            {
                "complex_target_id": "control",
                "classification": "already_certified",
            },
        ],
    }


class M6DW2TargetFamilyFollowupTests(unittest.TestCase):
    def test_build_contract_keeps_negative_panel_no_spend(self):
        manifest = {
            "source_manifest": "source.json",
            "targets": [
                {"id": "weak", "rcsb_id": "1AAA"},
                {"id": "hold", "rcsb_id": "1BBB"},
            ],
        }
        rep = build_contract(_panel_report(), _diagnostic(), manifest, branch_id="v8")

        self.assertEqual(rep["branch_id"], "v8")
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertEqual(rep["claim_boundary"]["w2_multi_target_generalization"], "not_supported")
        self.assertIn("weak", rep["target_sets"]["replace_or_redesign_low_success_targets"])
        self.assertIn(
            "hold",
            rep["target_sets"]["hold_until_low_pae_acceptance_or_target_specific_calibration"],
        )
        self.assertIn("control", rep["target_sets"]["target_wise_certified_controls"])
        self.assertIn("1AAA", rep["source_manifest"]["source_rcsb_ids"])

    def test_candidate_rules_exclude_failed_current_protocol_targets(self):
        rep = build_contract(_panel_report(), _diagnostic(), {"targets": [{"id": "weak", "rcsb_id": "1AAA"}]})
        rules = build_candidate_rules(rep, source_contract="contract.json")

        self.assertFalse(rules["spend_gate"]["cayuga_submission_allowed"])
        self.assertIn("weak", rules["excluded_targets_under_current_protocol"])
        self.assertIn("hold", rules["excluded_targets_under_current_protocol"])
        self.assertEqual(rules["candidate_requirements"]["max_largest_cluster_fraction_for_full_panel"], 0.25)
        self.assertFalse(rules["gate_requirements"]["fixed_low_pae_cutoff_transfer_allowed"])

    def test_render_markdown_names_no_spend_boundary(self):
        rep = build_contract(_panel_report(), _diagnostic(), None, branch_id="v8")
        md = render_markdown(rep)

        self.assertIn("W2 Target-Family Follow-up Contract", md)
        self.assertIn("no-spend redesign contract", md)
        self.assertIn("v8", md)

    def test_cli_writes_contract_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            panel = os.path.join(d, "panel.json")
            diag = os.path.join(d, "diagnostic.json")
            manifest = os.path.join(d, "manifest.json")
            out_json = os.path.join(d, "contract.json")
            out_md = os.path.join(d, "contract.md")
            out_rules = os.path.join(d, "rules.json")
            _write_json(panel, _panel_report())
            _write_json(diag, _diagnostic())
            _write_json(manifest, {"targets": [{"id": "weak", "rcsb_id": "1AAA"}]})

            rc = main([
                "--panel-report", panel,
                "--redesign-diagnostic", diag,
                "--manifest", manifest,
                "--branch-id", "v8",
                "--out-json", out_json,
                "--out-md", out_md,
                "--out-candidate-rules", out_rules,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_rules))


if __name__ == "__main__":
    unittest.main()
