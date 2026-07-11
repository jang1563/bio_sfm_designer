"""Tests for the predeclared W2b target-adaptive evaluator."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2b_target_adaptive_report import evaluate, run


_ROOT = os.path.dirname(os.path.dirname(__file__))


def _protocol():
    return {
        "fresh_target_contract": {
            "n_initial_targets": 3,
            "exclude_v11_new_representative_targets": ["old"],
        },
        "current_execution_state": {
            "fit_target_ids": ["easy", "selective", "refuse"],
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
    namespace = {"fit": "fit", "certification": "cert", "test": "test"}[stage]
    return {
        "target_id": f"{namespace}-{target}-{index}",
        "complex_target_id": target,
        "w2b_stage": stage,
        "w2b_seed_namespace": namespace,
        "representation": f"{stage}-{target}-sequence-{index}",
        "lrmsd": 1.0 if success else 5.0,
        "lrmsd_threshold": 4.0,
        "pae_interaction": pae,
        "regime": "complex",
        "mean_plddt": 90.0,
        "truth": {"correct": success, "quality": 1.0 if success else 0.5},
        "interface_aligned": True,
        "predictor_id": "boltz2_complex",
        "signal_source": "boltz2_pae_interaction",
        "label_source": "boltz2_lrmsd_to_reference",
        "target_chain": "A",
        "binder_chain": "B",
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
    def test_committed_fit_fixture_replays_frozen_rules(self):
        report = run(
            os.path.join(_ROOT, "configs", "m6d_w2b_target_adaptive_exact_ltt_protocol.json"),
            [os.path.join(_ROOT, "tests", "fixtures", "m6d_w2b_target_adaptive_fit_records.jsonl")],
        )

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_fit_complete_awaiting_certification")
        self.assertEqual(
            report["fit_eligible_targets"],
            ["1F51_AE", "1F93_DC", "1FDH_GA", "1FLT_WV", "1FVC_DC"],
        )
        self.assertEqual(report["fit_refused_targets"], ["1F66_AB", "1FJG_FR", "1FXK_CA"])
        fit = {row["target_id"]: row["fit"] for row in report["targets"]}
        self.assertEqual(fit["1F51_AE"]["mode"], "selective_pae")
        self.assertEqual(fit["1F51_AE"]["tau"], 5.7365)
        self.assertEqual(fit["1F51_AE"]["fit_auroc_pae"], 0.8421052631578947)
        self.assertEqual(fit["1F93_DC"]["mode"], "trust_all")
        self.assertEqual(fit["1F66_AB"]["mode"], "refuse")

    def test_committed_certification_fixture_replays_terminal_result(self):
        report = run(
            os.path.join(_ROOT, "configs", "m6d_w2b_target_adaptive_exact_ltt_protocol.json"),
            [os.path.join(_ROOT, "tests", "fixtures", "m6d_w2b_target_adaptive_fit_records.jsonl")],
            [
                os.path.join(
                    _ROOT,
                    "tests",
                    "fixtures",
                    "m6d_w2b_target_adaptive_certification_records.jsonl",
                )
            ],
        )

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_certification_terminal_not_supported")
        self.assertEqual(
            report["certified_targets"],
            ["1F93_DC", "1FDH_GA", "1FLT_WV", "1FVC_DC"],
        )
        self.assertEqual(report["selective_pae_certified_targets"], [])
        self.assertTrue(report["terminal_after_certification"])
        self.assertFalse(report["test_required_for_final_reporting"])
        target = {row["target_id"]: row for row in report["targets"]}["1F51_AE"]
        self.assertEqual(target["certification"]["accepted"], 31)
        self.assertEqual(target["certification"]["false_accepts"], 6)
        self.assertEqual(target["certification"]["false_accept_rate"], 6 / 31)
        self.assertEqual(target["certification"]["ucb"], 0.4002058003899586)
        self.assertEqual(
            target["certification"]["diagnostic_auroc_pae"],
            0.7839366515837104,
        )
        self.assertFalse(target["certification"]["diagnostic_affects_certificate"])

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

    def test_passing_certification_gate_awaits_reporting_test(self):
        report = evaluate(
            _protocol(),
            _stage("fit"),
            _stage("certification", include_refused=False),
        )

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_certification_complete_awaiting_test")
        self.assertTrue(report["panel_certification_gate"]["passed"])
        self.assertFalse(report["terminal_after_certification"])
        self.assertTrue(report["test_required_for_final_reporting"])

    def test_failed_certification_gate_stops_before_non_decisive_test(self):
        certification = _stage("certification", include_refused=False)
        for row in certification:
            if row["complex_target_id"] == "selective" and not row["truth"]["correct"]:
                row["pae_interaction"] = 1.0
        report = evaluate(_protocol(), _stage("fit"), certification)

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_certification_terminal_not_supported")
        self.assertFalse(report["panel_certification_gate"]["passed"])
        self.assertTrue(report["terminal_after_certification"])
        self.assertFalse(report["test_can_change_certificate"])
        self.assertFalse(report["test_required_for_final_reporting"])
        self.assertFalse(report["can_claim_w2b_target_adaptive_viability"])

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

    def test_run_enforces_strict_boltz_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol_path = os.path.join(tmp, "protocol.json")
            records_path = os.path.join(tmp, "fit.jsonl")
            with open(protocol_path, "w") as handle:
                json.dump(_protocol(), handle)
            rows = _stage("fit")
            del rows[0]["predictor_id"]
            with open(records_path, "w") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

            report = run(protocol_path, [records_path])

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2b_audit_failed")
        self.assertTrue(report["qc"]["require_complex_target_id"])
        self.assertTrue(report["qc"]["require_provenance"])
        self.assertTrue(report["qc"]["require_chain_ids"])
        self.assertEqual(report["qc"]["expect_predictor_id"], "boltz2_complex")
        self.assertEqual(
            report["qc"]["failures_by_kind"],
            {"missing_provenance": 1, "unexpected_predictor_id": 1},
        )

    def test_locked_initial_target_identity_mismatch_fails_closed(self):
        fit = _stage("fit")
        for row in fit:
            if row["complex_target_id"] == "easy":
                row["complex_target_id"] = "replacement"
                row["target_id"] = row["target_id"].replace("-easy-", "-replacement-")

        report = evaluate(_protocol(), fit)

        self.assertFalse(report["audit_ok"])
        mismatch = next(
            row for row in report["failures"]
            if row["kind"] == "locked_initial_target_identity_mismatch"
        )
        self.assertEqual(mismatch["missing"], ["easy"])
        self.assertEqual(mismatch["unexpected"], ["replacement"])

    def test_candidate_id_namespace_mismatch_fails_closed(self):
        fit = _stage("fit")
        fit[0]["target_id"] = "wrong-namespace-easy-0"

        report = evaluate(_protocol(), fit)

        self.assertFalse(report["audit_ok"])
        self.assertIn(
            "stage_candidate_id_namespace_mismatch",
            {row["kind"] for row in report["failures"]},
        )

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
