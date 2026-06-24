import unittest
from dataclasses import asdict

from bio_sfm_designer.trust import TrustGate
from bio_sfm_designer.types import Prediction


def _pred(cid, value, raw_conf, regime="monomer", baseline_value=None, has_baseline=True, sfm_correct=True):
    return Prediction(
        candidate_id=cid,
        value=value,
        raw_conf=raw_conf,
        regime=regime,
        baseline_value=baseline_value,
        has_baseline=has_baseline,
        truth={"sfm_correct": sfm_correct, "baseline_correct": True, "quality": value},
    )


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.gate = TrustGate(lam=0.5, defer_threshold=0.35, disagreement_tol=0.15)

    def test_high_risk_verifies(self):
        # raw_conf 0.3 -> risk 0.7 > lam 0.5
        r = self.gate.route(_pred("a", value=0.5, raw_conf=0.3))
        self.assertEqual(r.action, "verify_assay")

    def test_low_risk_agree_trusts(self):
        # raw_conf 0.95 -> risk 0.05; baseline agrees (|0.9-0.92|<tol)
        r = self.gate.route(_pred("b", value=0.9, raw_conf=0.95, baseline_value=0.92))
        self.assertEqual(r.action, "trust_sfm")

    def test_disagreement_falls_back_to_baseline(self):
        # low risk but SFM value far from cheap baseline
        r = self.gate.route(_pred("c", value=0.9, raw_conf=0.95, baseline_value=0.2))
        self.assertEqual(r.action, "default_baseline")

    def test_no_baseline_nontrivial_risk_defers(self):
        # raw_conf 0.6 -> risk 0.4 (<=lam) but no baseline and risk >= defer_threshold
        r = self.gate.route(_pred("d", value=0.5, raw_conf=0.6, has_baseline=False, baseline_value=None))
        self.assertEqual(r.action, "defer")

    def test_gate_never_sees_truth(self):
        # the FULL routing (risk scalars too, not just .action) must be invariant to hidden truth
        good = self.gate.route(_pred("e", 0.9, 0.95, baseline_value=0.92, sfm_correct=True))
        bad = self.gate.route(_pred("e", 0.9, 0.95, baseline_value=0.92, sfm_correct=False))
        self.assertEqual(asdict(good), asdict(bad))

    def test_gate_never_reads_truth_attribute(self):
        # a proxy that raises if .truth is read proves route() never touches hidden truth
        class _TruthPoison:
            def __init__(self, p):
                self._p = p

            def __getattr__(self, name):
                if name == "truth":
                    raise AssertionError("TrustGate.route read hidden truth")
                return getattr(self._p, name)

        poisoned = _TruthPoison(_pred("p", 0.9, 0.95, baseline_value=0.92))
        self.gate.route(poisoned)  # must not raise

    def test_prevalidate_validates_a_separable_regime(self):
        # offline gate-before-spend: held-out verified data where risk cleanly separates
        # wrong from right -> the regime is trust-validated without spending any live assay.
        raw_risks = [0.1] * 12 + [0.9] * 12
        wrong = [0] * 12 + [1] * 12
        gate = TrustGate(lam=0.5)
        self.assertFalse(gate.any_calibrated())
        self.assertTrue(gate.prevalidate("complex", raw_risks, wrong))
        self.assertTrue(gate.any_calibrated())

    def test_calibration_refit_changes_risk(self):
        # feed verified observations that say low-raw-risk items are actually often wrong
        for i in range(12):
            self.gate.observe_verified(raw_risk=0.1, sfm_was_wrong=True)
            self.gate.observe_verified(raw_risk=0.9, sfm_was_wrong=False)
        self.assertTrue(self.gate.refit())
        r = self.gate.route(_pred("f", value=0.9, raw_conf=0.95, baseline_value=0.92))
        # calibrated risk for low raw risk should now be elevated toward ~1.0
        self.assertGreater(r.calibrated_risk, r.raw_risk)


if __name__ == "__main__":
    unittest.main()
