"""Tests for the locked W2c one-shot evaluator."""

import copy
import unittest

from bio_sfm_designer.experiments.m6d_w2c_one_shot_report import (
    evaluate,
    evaluate_threshold_learning,
)


TARGETS = ("A_AB", "B_AB", "C_AB")


def _protocol():
    return {
        "locked_scientific_protocol": {
            "fresh_target_contract": {"n_initial_targets": 3},
            "fit_design": {
                "threshold_learning": {
                    "records_per_target": 60,
                    "seed_namespace": "w2c-fit-learn-v1",
                    "minimum_accepted": 30,
                    "minimum_auroc": 0.65,
                    "maximum_empirical_false_accept_rate": 0.08,
                },
                "independent_screen": {
                    "records_per_target": 120,
                    "seed_namespace": "w2c-fit-screen-v1",
                    "minimum_accepted": 75,
                    "maximum_empirical_false_accept_rate": 0.08,
                    "risk_delta": 0.1,
                    "maximum_risk_ucb": 0.15,
                    "acceptance_rate_delta": 0.0125,
                    "minimum_acceptance_rate_lcb": 0.5,
                },
            },
            "certification_design": {
                "method": "one_sided_clopper_pearson_exact",
                "records_per_target": 180,
                "seed_namespace": "w2c-cert-v1",
                "target_alpha": 0.2,
                "per_target_delta": 0.1 / 3,
                "minimum_accepted": 90,
            },
            "panel_decision_rule": {
                "minimum_certified_targets": 3,
                "minimum_selective_pae_certified_targets": 3,
            },
        },
        "execution_state": {},
    }


def _row(target, stage, namespace, index, *, pae, wrong):
    return {
        "complex_target_id": target,
        "target_id": f"{namespace}-{target}-{index:03d}",
        "w2c_stage": stage,
        "w2c_seed_namespace": namespace,
        "pae_interaction": pae,
        "lrmsd": 6.0 if wrong else 2.0,
        "lrmsd_threshold": 4.0,
        "representation": f"SEQ-{stage}-{target}-{index:03d}",
    }


def _learning(*, all_success=False):
    rows = []
    for target in TARGETS:
        for index in range(60):
            low = index < 50
            rows.append(_row(
                target,
                "threshold_learning",
                "w2c-fit-learn-v1",
                index,
                pae=1.0 + index / 100 if low else 10.0 + index,
                wrong=False if all_success else not low,
            ))
    return rows


def _screen(*, false_accepts=4):
    rows = []
    for target in TARGETS:
        for index in range(120):
            accepted = index < 80
            rows.append(_row(
                target,
                "independent_screen",
                "w2c-fit-screen-v1",
                index,
                pae=2.0 if accepted else 30.0,
                wrong=accepted and index < false_accepts,
            ))
    return rows


def _certification(*, false_accepts=5):
    rows = []
    for target in TARGETS:
        for index in range(180):
            accepted = index < 100
            rows.append(_row(
                target,
                "certification",
                "w2c-cert-v1",
                index,
                pae=2.0 if accepted else 30.0,
                wrong=accepted and index < false_accepts,
            ))
    return rows


class M6DW2COneShotReportTests(unittest.TestCase):
    def test_learning_only_freezes_rules_without_authorizing_later_stages(self):
        report = evaluate_threshold_learning(_protocol(), _learning())

        self.assertTrue(report["audit_ok"])
        self.assertEqual(
            report["status"],
            "w2c_threshold_learning_complete_awaiting_screen_packet",
        )
        self.assertEqual(report["threshold_candidate_targets"], list(TARGETS))
        self.assertTrue(report["threshold_decisions_frozen"])
        self.assertFalse(report["terminal_after_threshold_learning"])
        self.assertFalse(report["independent_screen_generation_approved"])
        self.assertFalse(report["certification_generation_approved"])
        self.assertFalse(report["can_claim_w2c_selective_target_adaptive_viability"])
        self.assertTrue(all(row["decision_frozen"] for row in report["targets"]))

    def test_learning_only_futility_stop_when_candidate_floor_is_unreachable(self):
        report = evaluate_threshold_learning(_protocol(), _learning(all_success=True))

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_threshold_learning_terminal_not_supported")
        self.assertEqual(report["threshold_candidate_targets"], [])
        self.assertTrue(report["terminal_after_threshold_learning"])
        self.assertFalse(report["candidate_floor_reachable"])

    def test_learning_only_metadata_drift_fails_closed(self):
        rows = _learning()
        rows[0]["w2c_seed_namespace"] = "wrong-stage"
        report = evaluate_threshold_learning(_protocol(), rows)

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_threshold_learning_audit_failed")
        self.assertFalse(report["threshold_decisions_frozen"])
        self.assertIn("stage_namespace_mismatch", {row["kind"] for row in report["failures"]})

    def test_three_selective_targets_certify(self):
        report = evaluate(_protocol(), _learning(), _screen(), _certification())

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_selective_target_adaptive_viability_supported")
        self.assertTrue(report["can_claim_w2c_selective_target_adaptive_viability"])
        self.assertFalse(report["can_claim_universal_w2_generalization"])
        self.assertEqual(report["fit_screen_eligible_targets"], list(TARGETS))
        self.assertEqual(report["certified_targets"], list(TARGETS))
        self.assertTrue(report["panel_gate"]["passed"])
        self.assertTrue(all(row["learning"]["mode"] == "selective_pae" for row in report["targets"]))

    def test_fit_screen_completes_before_certification_without_claim(self):
        report = evaluate(_protocol(), _learning(), _screen())

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_fit_screen_complete_awaiting_certification")
        self.assertFalse(report["can_claim_w2c_selective_target_adaptive_viability"])
        self.assertEqual(len(report["fit_screen_eligible_targets"]), 3)

    def test_trust_all_one_class_target_is_refused(self):
        report = evaluate(_protocol(), _learning(all_success=True), _screen())

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_fit_screen_terminal_not_supported")
        self.assertTrue(report["terminal_after_fit_screen"])
        self.assertEqual(report["fit_screen_eligible_targets"], [])
        self.assertTrue(all(row["learning"]["mode"] == "refuse" for row in report["targets"]))

    def test_screen_risk_failure_stops_before_certification(self):
        report = evaluate(_protocol(), _learning(), _screen(false_accepts=20))

        self.assertEqual(report["status"], "w2c_fit_screen_terminal_not_supported")
        self.assertEqual(report["fit_screen_eligible_targets"], [])
        self.assertTrue(all(
            row["independent_screen"]["reason"] == "screen_empirical_risk_above_cap"
            for row in report["targets"]
        ))

    def test_certification_failure_is_terminal_without_adaptive_top_up(self):
        report = evaluate(
            _protocol(),
            _learning(),
            _screen(),
            _certification(false_accepts=30),
        )

        self.assertEqual(report["status"], "w2c_certification_terminal_not_supported")
        self.assertFalse(report["panel_gate"]["passed"])
        self.assertFalse(report["adaptive_top_up_allowed"])

    def test_screen_labels_cannot_retune_learning_threshold(self):
        first = evaluate(_protocol(), _learning(), _screen(false_accepts=4))
        second = evaluate(_protocol(), _learning(), _screen(false_accepts=20))

        self.assertEqual(
            [row["learning"]["tau"] for row in first["targets"]],
            [row["learning"]["tau"] for row in second["targets"]],
        )

    def test_candidate_or_sequence_overlap_fails_closed(self):
        screen = copy.deepcopy(_screen())
        screen[0]["target_id"] = _learning()[0]["target_id"]
        screen[1]["representation"] = _learning()[1]["representation"]
        report = evaluate(_protocol(), _learning(), screen)

        kinds = {failure["kind"] for failure in report["failures"]}
        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_audit_failed")
        self.assertIn("candidate_overlap_across_stages", kinds)
        self.assertIn("candidate_sequence_overlap_across_stages", kinds)

    def test_missing_screen_rows_fail_audit_without_crashing(self):
        report = evaluate(_protocol(), _learning(), [])

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_audit_failed")
        self.assertIn("stage_record_count_mismatch", {row["kind"] for row in report["failures"]})
        self.assertTrue(all(
            row["independent_screen"]["reason"] == "missing_screen_rows"
            for row in report["targets"]
        ))


if __name__ == "__main__":
    unittest.main()
