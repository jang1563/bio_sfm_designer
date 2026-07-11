"""Tests for the predeclared W2b target-adaptive evaluator."""

import unittest

from bio_sfm_designer.experiments.m6d_w2b_target_adaptive_report import evaluate


def _protocol():
    return {
        "fresh_target_contract": {
            "n_initial_targets": 3,
            "exclude_v11_new_representative_targets": ["old"],
        },
        "generation_stages": {
            "fit": {"records_per_target": 20, "seed_namespace": "fit"},
            "certification": {"records_per_target": 20, "seed_namespace": "cert"},
            "test": {"records_per_target": 20, "seed_namespace": "test"},
        },
        "fit_stage_rule": {
            "target_alpha": 0.3,
            "minimum_fit_accepts": 10,
            "ordered_modes": [
                {"mode": "trust_all", "condition": "fit risk at most alpha"},
                {"mode": "selective_pae", "condition": "AUROC is at least 0.65, fixed direction"},
                {"mode": "refuse", "condition": "otherwise"},
            ],
        },
        "certification_rule": {
            "method": "one_sided_clopper_pearson_exact",
            "target_alpha": 0.3,
            "panel_delta": 0.1,
            "per_target_delta": 0.1 / 3,
            "minimum_certification_accepts": 10,
        },
        "panel_decision_rule": {
            "success_status": "w2b_target_adaptive_viability_supported",
            "minimum_certified_targets": 2,
            "minimum_selective_pae_certified_targets": 1,
        },
    }


def _row(stage, target, index, success, pae):
    return {
        "target_id": f"{stage}-{target}-{index}",
        "complex_target_id": target,
        "w2b_stage": stage,
        "w2b_seed_namespace": {"fit": "fit", "certification": "cert", "test": "test"}[stage],
        "representation": f"{stage}-{target}-sequence-{index}",
        "lrmsd": 1.0 if success else 5.0,
        "lrmsd_threshold": 4.0,
        "pae_interaction": pae,
    }


def _stage(stage, *, include_refused=True):
    rows = []
    for index in range(20):
        rows.append(_row(stage, "easy", index, True, 1.0 + index / 100))
        rows.append(_row(stage, "selective", index, index < 12, 1.0 if index < 12 else 9.0))
        if include_refused:
            rows.append(_row(stage, "refuse", index, False, 1.0 + index / 100))
    return rows


class W2BTargetAdaptiveReportTests(unittest.TestCase):
    def test_predeclared_modes_and_exact_certification_support_w2b_only(self):
        report = evaluate(
            _protocol(),
            _stage("fit"),
            _stage("certification", include_refused=False),
            _stage("test", include_refused=False),
        )

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_target_adaptive_viability_supported")
        self.assertTrue(report["can_claim_w2b_target_adaptive_viability"])
        self.assertFalse(report["can_claim_universal_w2_generalization"])
        self.assertEqual(report["fit_eligible_targets"], ["easy", "selective"])
        self.assertEqual(report["fit_refused_targets"], ["refuse"])
        self.assertEqual(report["certified_targets"], ["easy", "selective"])
        self.assertEqual(report["selective_pae_certified_targets"], ["selective"])

    def test_fit_only_report_stops_before_certification_spend(self):
        report = evaluate(_protocol(), _stage("fit"))

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_fit_complete_awaiting_certification")
        self.assertFalse(report["can_claim_w2b_target_adaptive_viability"])
        self.assertEqual(report["lrmsd_threshold"], 4.0)

    def test_record_label_threshold_mismatch_fails_closed(self):
        fit = _stage("fit")
        fit[0]["lrmsd_threshold"] = 5.0
        fit[1]["lrmsd_threshold"] = "invalid"

        report = evaluate(_protocol(), fit, threshold=4.0)

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_audit_failed")
        self.assertIn(
            "stage_lrmsd_threshold_mismatch",
            {row["kind"] for row in report["failures"]},
        )
        mismatch = next(
            row for row in report["failures"]
            if row["kind"] == "stage_lrmsd_threshold_mismatch"
        )
        self.assertEqual(mismatch["count"], 2)

    def test_candidate_overlap_across_stages_fails_closed(self):
        certification = _stage("certification", include_refused=False)
        certification[0]["target_id"] = _stage("fit")[0]["target_id"]
        report = evaluate(
            _protocol(),
            _stage("fit"),
            certification,
            _stage("test", include_refused=False),
        )

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_audit_failed")
        self.assertIn("candidate_overlap_across_stages", {row["kind"] for row in report["failures"]})

    def test_candidate_sequence_overlap_across_stages_fails_closed(self):
        certification = _stage("certification", include_refused=False)
        certification[0]["representation"] = _stage("fit")[0]["representation"]
        report = evaluate(
            _protocol(),
            _stage("fit"),
            certification,
            _stage("test", include_refused=False),
        )

        self.assertFalse(report["audit_ok"])
        self.assertIn(
            "candidate_sequence_overlap_across_stages",
            {row["kind"] for row in report["failures"]},
        )

    def test_excluded_target_reuse_fails_closed(self):
        fit = _stage("fit")
        for row in fit:
            if row["complex_target_id"] == "easy":
                row["complex_target_id"] = "old"
        report = evaluate(_protocol(), fit)

        self.assertFalse(report["audit_ok"])
        self.assertIn("excluded_target_reuse", {row["kind"] for row in report["failures"]})


if __name__ == "__main__":
    unittest.main()
