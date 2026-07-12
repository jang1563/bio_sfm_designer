"""M5 — the trust gate's optional conformal mode: trusting `risk <= tau` carries a controlled
false-accept rate. These lock the WIRING (tau certified from calibration data, stored per regime,
and used as the trust threshold); the false-accept guarantee itself is proven in bio-sfm-trust's
tests/test_conformal.py.
"""

import unittest

from bio_sfm_designer.trust import TrustGate
from bio_sfm_designer.types import Prediction

# a clean two-cluster calibration set: low-risk cluster ~5% wrong, high-risk cluster ~90% wrong.
_RISKS = [0.1] * 200 + [0.9] * 200
_WRONG = [1] * 10 + [0] * 190 + [1] * 180 + [0] * 20


def _complex_pred(cid, raw_conf):
    return Prediction(candidate_id=cid, value=raw_conf, raw_conf=raw_conf, regime="complex",
                      has_baseline=False)


class ConformalGateTests(unittest.TestCase):
    def test_conformal_mode_certifies_a_tau_tighter_than_lambda(self):
        gate = TrustGate(lam=0.5, conformal_alpha=0.2)
        self.assertTrue(gate.prevalidate("complex", _RISKS, _WRONG))   # regime validates
        tau = gate._regimes["complex"].tau
        self.assertIsNotNone(tau, "conformal mode must certify a tau from separable calibration data")
        self.assertTrue(0.0 <= tau < 0.5, f"conformal tau={tau} should be tighter than lambda=0.5")

    def test_without_conformal_mode_no_tau(self):
        gate = TrustGate(lam=0.5)                                       # conformal_alpha unset
        gate.prevalidate("complex", _RISKS, _WRONG)
        self.assertIsNone(gate._regimes["complex"].tau)

    def test_route_uses_the_conformal_threshold(self):
        # under conformal mode the routing rationale references the RCPS tau (not lambda), proving
        # route() consults the conformal threshold; without it, the rationale references lambda.
        conf = TrustGate(lam=0.5, conformal_alpha=0.2)
        conf.prevalidate("complex", _RISKS, _WRONG)
        plain = TrustGate(lam=0.5)
        plain.prevalidate("complex", _RISKS, _WRONG)
        r_conf = conf.route(_complex_pred("x", 0.95))
        r_plain = plain.route(_complex_pred("x", 0.95))
        self.assertIn("RCPS", r_conf.rationale)
        self.assertNotIn("RCPS", r_plain.rationale)
        self.assertIn("λ", r_plain.rationale)


if __name__ == "__main__":
    unittest.main()
