"""Tests for the no-spend W2 gate-strategy artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_gate_strategy import (
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_records(path, target, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for i, row in enumerate(rows):
            rec = {
                "target_id": f"{target}-{i}",
                "complex_target_id": target,
                "mean_plddt": row.get("mean_plddt", 80.0),
                "regime": "complex",
                "predictor_id": "boltz2_complex",
                "signal_source": "boltz2_pae_interaction",
                "label_source": "boltz2_lrmsd_to_reference",
                "iptm": row.get("iptm", 0.5),
                "ptm": row.get("ptm", 0.5),
                "pae_interaction": row["pae"],
                "truth": {"correct": row["lrmsd"] < 4.0, "quality": 1.0},
                "lrmsd": row["lrmsd"],
                "lrmsd_threshold": 4.0,
                "interface_aligned": True,
                "target_chain": "A",
                "binder_chain": "B",
                "refolder": "boltz2_complex",
            }
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _panel(paths):
    return {
        "panel_status": "multi_target_evaluable_not_certified",
        "target_alpha": 0.2,
        "records": paths,
        "targets": [
            {"complex_target_id": "all_success", "certified": False},
            {"complex_target_id": "cutoff_fail", "certified": False},
        ],
    }


def _diagnostic():
    return {
        "panel_status": "multi_target_evaluable_not_certified",
        "target_alpha": 0.2,
        "targets": [
            {
                "complex_target_id": "all_success",
                "classification": "underpowered_or_split_sensitive",
                "recommended_action": "keep_as_anchor_or_scale_only_after_split_sensitivity_check",
                "median_pae_interaction": 2.0,
                "protocol_cutoff_accepts": 60,
                "protocol_cutoff_false_accept_rate": 0.0,
            },
            {
                "complex_target_id": "cutoff_fail",
                "classification": "low_pae_cutoff_not_transferable",
                "recommended_action": "target_specific_calibration_required_before_cutoff_transfer",
                "median_pae_interaction": 3.5,
                "protocol_cutoff_accepts": 40,
                "protocol_cutoff_false_accept_rate": 0.5,
            },
        ],
    }


class M6DW2GateStrategyTests(unittest.TestCase):
    def test_build_report_separates_label_degeneracy_and_cutoff_transfer(self):
        with tempfile.TemporaryDirectory() as d:
            all_success = os.path.join(d, "all_success", "records.jsonl")
            cutoff_fail = os.path.join(d, "cutoff_fail", "records.jsonl")
            _write_records(
                all_success,
                "all_success",
                [{"pae": 2.0, "lrmsd": 1.0} for _ in range(60)],
            )
            _write_records(
                cutoff_fail,
                "cutoff_fail",
                [{"pae": 2.0, "lrmsd": 6.0} for _ in range(30)]
                + [{"pae": 6.0, "lrmsd": 1.0} for _ in range(30)],
            )

            rep = build_report(
                _panel([all_success, cutoff_fail]),
                _diagnostic(),
                seeds=range(3),
            )

        groups = rep["gate_strategy_groups"]
        self.assertEqual(rep["status"], "no_spend_gate_strategy_required")
        self.assertFalse(rep["spend_gate"]["cayuga_submission_allowed"])
        self.assertIn(
            "all_success",
            groups["label_degeneracy_policy_required_before_gate_claim"],
        )
        self.assertIn("cutoff_fail", groups["target_specific_calibration_required"])
        by_target = {row["target"]: row for row in rep["targets"]}
        self.assertEqual(by_target["all_success"]["label_class"], "label_degenerate_all_success")
        self.assertTrue(by_target["all_success"]["alpha_plan_gate_drift"])

    def test_markdown_renders_spend_gate(self):
        with tempfile.TemporaryDirectory() as d:
            all_success = os.path.join(d, "all_success", "records.jsonl")
            cutoff_fail = os.path.join(d, "cutoff_fail", "records.jsonl")
            _write_records(all_success, "all_success", [{"pae": 2.0, "lrmsd": 1.0} for _ in range(60)])
            _write_records(cutoff_fail, "cutoff_fail", [{"pae": 2.0, "lrmsd": 6.0} for _ in range(60)])
            md = render_markdown(build_report(_panel([all_success, cutoff_fail]), _diagnostic(), seeds=range(3)))

        self.assertIn("Cayuga submission allowed: `false`", md)
        self.assertIn("label_degeneracy_policy_required_before_gate_claim", md)
        self.assertIn("target_specific_calibration_required", md)

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            all_success = os.path.join(d, "all_success", "records.jsonl")
            cutoff_fail = os.path.join(d, "cutoff_fail", "records.jsonl")
            panel = os.path.join(d, "panel.json")
            diagnostic = os.path.join(d, "diagnostic.json")
            out_json = os.path.join(d, "gate_strategy.json")
            out_md = os.path.join(d, "gate_strategy.md")
            _write_records(all_success, "all_success", [{"pae": 2.0, "lrmsd": 1.0} for _ in range(60)])
            _write_records(cutoff_fail, "cutoff_fail", [{"pae": 2.0, "lrmsd": 6.0} for _ in range(60)])
            _write_json(panel, _panel([all_success, cutoff_fail]))
            _write_json(diagnostic, _diagnostic())

            rc = main([
                "--panel-report", panel,
                "--redesign-diagnostic", diagnostic,
                "--seeds", "0:3",
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["branch_id"], "w2_target_family_redesign_v6_no_spend_gate_strategy")


if __name__ == "__main__":
    unittest.main()
