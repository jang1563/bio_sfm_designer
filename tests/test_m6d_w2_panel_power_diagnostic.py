"""Tests for the W2 panel split-LTT power diagnostic."""

import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_power_diagnostic import diagnose


def _report(n_certification=33, n_records=100):
    targets = []
    for index in range(11):
        targets.append({
            "complex_target_id": f"t{index}",
            "n_records": n_records,
            "n_certification": n_certification,
            "success": 50,
            "failure": n_records - 50,
            "auroc_pae": 0.7,
            "status": "not_certified",
            "not_certified_reason": "no_rcps_tau",
        })
    return {
        "panel_status": "multi_target_evaluable_not_certified",
        "target_alpha": 0.2,
        "panel_delta": 0.1,
        "n_targets": 11,
        "targets": targets,
    }


class M6DW2PanelPowerDiagnosticTests(unittest.TestCase):
    def test_current_100_record_design_is_structurally_underpowered(self):
        report = diagnose(_report())

        self.assertTrue(report["audit_ok"])
        self.assertTrue(report["post_hoc"])
        self.assertFalse(report["can_recertify_current_panel"])
        self.assertEqual(report["minimum_zero_error_accepted"], 59)
        minimum = report["minimum_records_per_target_for_zero_error_hoeffding_possibility"]
        self.assertEqual(minimum["n_records"], 176)
        self.assertEqual(minimum["n_certification"], 59)
        self.assertTrue(report["all_targets_structurally_underpowered"])
        self.assertGreater(report["targets"][0]["hoeffding_zero_error_ucb_floor"], 0.2)

    def test_larger_certification_split_is_attainable_in_best_case(self):
        report = diagnose(_report(n_certification=60, n_records=180))

        self.assertFalse(report["all_targets_structurally_underpowered"])
        self.assertTrue(report["targets"][0]["certification_possible_at_current_split"])

    def test_rejects_target_count_mismatch(self):
        panel = _report()
        panel["n_targets"] = 10
        with self.assertRaisesRegex(ValueError, "n_targets"):
            diagnose(panel)


if __name__ == "__main__":
    unittest.main()
