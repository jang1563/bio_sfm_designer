"""Tests for W2 negative-panel redesign diagnostics."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_panel_redesign_diagnostic import (
    render_markdown,
    run_diagnostic,
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


def _record(target, i, *, success=True, pae=2.0):
    return {
        "target_id": f"{target}-{i}",
        "complex_target_id": target,
        "predictor_id": "boltz2_complex",
        "signal_source": "boltz2_pae_interaction",
        "label_source": "boltz2_lrmsd_to_reference",
        "regime": "complex",
        "mean_plddt": 90.0,
        "pae_interaction": pae,
        "iptm": 0.8,
        "ptm": 0.8,
        "lrmsd": 2.0 if success else 8.0,
        "lrmsd_threshold": 4.0,
        "truth": {"correct": success},
        "interface_aligned": True,
        "target_chain": "A",
        "binder_chain": "B",
    }


class ComplexPanelRedesignDiagnosticTests(unittest.TestCase):
    def test_low_success_targets_drive_replace_recommendation(self):
        with tempfile.TemporaryDirectory() as d:
            records = os.path.join(d, "panel.jsonl")
            rows = []
            rows.extend(_record("good", i, success=True, pae=2.0) for i in range(10))
            rows.extend(_record("weak", i, success=(i == 0), pae=2.0) for i in range(10))
            _write_jsonl(records, rows)
            panel = os.path.join(d, "panel_report.json")
            _write_json(panel, {
                "panel_status": "multi_target_evaluable_not_certified",
                "target_alpha": 0.2,
                "records": [records],
                "targets": [
                    {"complex_target_id": "good", "certified": False, "status": "not_certified"},
                    {"complex_target_id": "weak", "certified": False, "status": "not_certified"},
                ],
            })
            summary = os.path.join(d, "summary.json")
            _write_json(summary, {"t030_protocol": {"target_tau": 0.10526315789473684}})

            rep = run_diagnostic(panel, summary, min_success_rate=0.25)

        by_target = {row["complex_target_id"]: row for row in rep["targets"]}
        self.assertEqual(
            by_target["weak"]["classification"],
            "target_protocol_mismatch_low_success",
        )
        self.assertEqual(
            by_target["weak"]["recommended_action"],
            "replace_target_or_redesign_generation_protocol_before_more_gpu",
        )
        self.assertIn("weak", rep["summary"]["drop_or_redesign_targets"])
        self.assertEqual(
            rep["summary"]["recommendation"],
            "redesign_or_replace_low_success_targets",
        )

    def test_cutoff_false_accepts_block_cutoff_transfer(self):
        with tempfile.TemporaryDirectory() as d:
            records = os.path.join(d, "panel.jsonl")
            rows = []
            rows.extend(_record("noisy", i, success=(i % 2 == 0), pae=2.0) for i in range(20))
            _write_jsonl(records, rows)
            panel = os.path.join(d, "panel_report.json")
            _write_json(panel, {
                "panel_status": "multi_target_evaluable_not_certified",
                "target_alpha": 0.2,
                "records": [records],
                "targets": [
                    {"complex_target_id": "noisy", "certified": False, "status": "not_certified"},
                ],
            })
            summary = os.path.join(d, "summary.json")
            _write_json(summary, {"t030_protocol": {"target_tau": 0.10526315789473684}})

            rep = run_diagnostic(panel, summary, max_protocol_false_accept_rate=0.2)

        self.assertEqual(
            rep["targets"][0]["classification"],
            "low_pae_cutoff_not_transferable",
        )
        self.assertEqual(
            rep["targets"][0]["recommended_action"],
            "target_specific_calibration_required_before_cutoff_transfer",
        )
        self.assertIn("noisy", rep["summary"]["cutoff_failure_targets"])

    def test_markdown_renders_target_table(self):
        rep = {
            "panel_status": "multi_target_evaluable_not_certified",
            "n_targets": 1,
            "n_records": 5,
            "summary": {"recommendation": "redesign_or_replace_low_success_targets"},
            "protocol_cutoff": {"risk_tau": 0.1, "pae_cutoff": 3.0, "source": "test"},
            "targets": [{
                "complex_target_id": "weak",
                "classification": "target_protocol_mismatch_low_success",
                "recommended_action": "replace_target_or_redesign_generation_protocol_before_more_gpu",
                "n_records": 5,
                "success": 0,
                "success_rate": 0.0,
                "median_pae_interaction": 2.0,
                "protocol_cutoff_accepts": 5,
                "protocol_cutoff_false_accepts": 5,
                "protocol_cutoff_false_accept_rate": 1.0,
            }],
            "next_action": "replace or redesign low-success W2 targets",
        }

        md = render_markdown(rep)

        self.assertIn("W2 Panel Redesign Diagnostic", md)
        self.assertIn("weak", md)
        self.assertIn("target_protocol_mismatch_low_success", md)
        self.assertIn("Redesign Gate", md)
        self.assertIn("replace_target_or_redesign_generation_protocol_before_more_gpu", md)

    def test_markdown_tolerates_missing_median_pae(self):
        rep = {
            "panel_status": "multi_target_evaluable_not_certified",
            "n_targets": 1,
            "n_records": 1,
            "summary": {"recommendation": "add_target_wise_scale_or_adjust_split"},
            "protocol_cutoff": {"risk_tau": None, "pae_cutoff": None, "source": None},
            "targets": [{
                "complex_target_id": "missing_pae",
                "classification": "underpowered_low_pae_acceptance",
                "recommended_action": "do_not_scale_until_low_pae_acceptance_strategy_exists",
                "n_records": 1,
                "success": 1,
                "success_rate": 1.0,
                "median_pae_interaction": None,
                "protocol_cutoff_accepts": 0,
                "protocol_cutoff_false_accepts": 0,
                "protocol_cutoff_false_accept_rate": None,
            }],
            "next_action": "inspect target-specific cutoff transfer",
        }

        md = render_markdown(rep)

        self.assertIn("missing_pae", md)
        self.assertIn("n/a", md)


if __name__ == "__main__":
    unittest.main()
