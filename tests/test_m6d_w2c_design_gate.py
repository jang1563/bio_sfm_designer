"""Tests for the W2c no-submit design and power gate."""

import copy
import unittest

from bio_sfm_designer.experiments.m6d_w2c_design_gate import (
    certification_power,
    evaluate,
)


def _protocol():
    return {
        "locked_scientific_protocol": {
            "predecessor_evidence_use": {
                "role": "design_diagnostic_only",
                "reuse_rows_as_fit_or_certification": False,
            },
            "fresh_target_contract": {
                "n_initial_targets": 8,
                "exclude_all_historical_registry_targets": True,
                "exclude_predecessor_target_ids": True,
                "require_unique_source_pdb": True,
                "require_one_representative_per_sequence_cluster": True,
                "require_manifest_and_msa_sha_validation": True,
            },
            "fit_design": {
                "eligible_mode": "selective_pae_only",
                "trust_all_counts_toward_panel_success": False,
                "substage_candidate_overlap_allowed": False,
                "threshold_learning": {
                    "records_per_target": 60,
                    "seed_namespace": "w2c-fit-learn-v1",
                },
                "independent_screen": {
                    "records_per_target": 120,
                    "seed_namespace": "w2c-fit-screen-v1",
                    "minimum_accepted": 75,
                    "maximum_empirical_false_accept_rate": 0.08,
                    "maximum_risk_ucb": 0.15,
                    "risk_delta": 0.1,
                    "acceptance_rate_delta": 0.0125,
                    "minimum_acceptance_rate_lcb": 0.5,
                },
            },
            "certification_design": {
                "method": "one_sided_clopper_pearson_exact",
                "records_per_target": 180,
                "seed_namespace": "w2c-cert-v1",
                "target_alpha": 0.2,
                "panel_delta": 0.1,
                "per_target_delta": 0.0125,
                "minimum_accepted": 90,
                "design_true_risk": 0.08,
                "minimum_conditional_power": 0.8,
            },
            "panel_decision_rule": {
                "minimum_certified_targets": 3,
                "minimum_selective_pae_certified_targets": 3,
                "trust_all_certificates_count": False,
            },
            "compute_budget": {"maximum_total_records": 2880},
        },
        "execution_state": {
            "target_manifest": None,
            "evaluator_implemented": False,
            "command_wrapper_emitted": False,
            "operator_approval_recorded": False,
            "hpc_submission_allowed": False,
        },
        "remaining_unlock_conditions": ["implement evaluator", "select fresh targets"],
    }


def _predecessor_report():
    return {
        "status": "w2b_certification_terminal_not_supported",
        "audit_ok": True,
        "panel_certification_gate": {"passed": False},
        "terminal_after_certification": True,
        "test_can_change_certificate": False,
        "can_claim_w2b_target_adaptive_viability": False,
        "can_claim_universal_w2_generalization": False,
        "records": {"test": []},
        "initial_target_ids": [f"old-{index}" for index in range(8)],
    }


def _predecessor_protocol():
    return {
        "generation_stages": {
            "fit": {"seed_namespace": "w2b-fit-v1"},
            "certification": {"seed_namespace": "w2b-cert-v1"},
            "test": {"seed_namespace": "w2b-test-v1"},
        }
    }


class M6DW2CDesignGateTests(unittest.TestCase):
    def test_locked_design_qualifies_but_remains_no_submit(self):
        report = evaluate(_protocol(), _predecessor_report(), _predecessor_protocol())

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_design_power_qualified_no_submit")
        self.assertTrue(report["design_power_qualified"])
        self.assertFalse(report["execution_ready"])
        self.assertTrue(report["no_submit"])
        self.assertFalse(report["hpc_submission_allowed"])
        self.assertFalse(report["can_claim_w2c"])
        self.assertEqual(
            report["certification_design"]["maximum_certifiable_false_accepts"],
            9,
        )
        self.assertGreaterEqual(
            report["certification_design"]["conditional_certification_power"],
            0.8,
        )
        self.assertEqual(report["panel_decision_rule"]["minimum_selective_pae_certified_targets"], 3)
        self.assertFalse(report["panel_decision_rule"]["trust_all_certificates_count"])

    def test_ninety_accepts_have_required_power_but_sixty_do_not(self):
        qualified = certification_power(90, 0.08, 0.2, 0.0125)
        underpowered = certification_power(60, 0.08, 0.2, 0.0125)

        self.assertEqual(qualified["maximum_certifiable_false_accepts"], 9)
        self.assertGreaterEqual(qualified["conditional_certification_power"], 0.8)
        self.assertLess(underpowered["conditional_certification_power"], 0.8)

    def test_underpowered_protocol_fails_closed(self):
        protocol = _protocol()
        protocol["locked_scientific_protocol"]["certification_design"]["minimum_accepted"] = 60
        report = evaluate(protocol, _predecessor_report(), _predecessor_protocol())

        self.assertFalse(report["audit_ok"])
        self.assertIn("certification_power_below_floor", {row["kind"] for row in report["failures"]})

    def test_nonterminal_predecessor_fails_closed(self):
        predecessor = _predecessor_report()
        predecessor["status"] = "w2b_certification_complete_awaiting_test"
        report = evaluate(_protocol(), predecessor, _predecessor_protocol())

        self.assertFalse(report["audit_ok"])
        self.assertIn("predecessor_not_terminal", {row["kind"] for row in report["failures"]})

    def test_namespace_reuse_fails_closed(self):
        protocol = _protocol()
        protocol["locked_scientific_protocol"]["fit_design"]["threshold_learning"][
            "seed_namespace"
        ] = "w2b-fit-v1"
        report = evaluate(protocol, _predecessor_report(), _predecessor_protocol())

        self.assertFalse(report["audit_ok"])
        self.assertIn("predecessor_namespace_reuse", {row["kind"] for row in report["failures"]})

    def test_trust_all_or_row_reuse_fails_closed(self):
        protocol = copy.deepcopy(_protocol())
        locked = protocol["locked_scientific_protocol"]
        locked["fit_design"]["eligible_mode"] = "trust_all_or_selective_pae"
        locked["predecessor_evidence_use"]["reuse_rows_as_fit_or_certification"] = True
        report = evaluate(protocol, _predecessor_report(), _predecessor_protocol())

        kinds = {row["kind"] for row in report["failures"]}
        self.assertIn("nonselective_fit_mode_allowed", kinds)
        self.assertIn("predecessor_row_reuse_allowed", kinds)


if __name__ == "__main__":
    unittest.main()
