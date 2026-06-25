"""M6c: the trust gate on the COMPLEX regime, routing on the validated pAE_interaction signal. Locks that
the signal enables selective trust -- trusting the most-confident (lowest-pAE) designs is far safer than
trust-all -- on the barstar fixture. (The distribution-free conformal certificate needs more designs than
n=72; that scale-up is proper-M6c, and the experiment honestly refuses to certify rather than over-promise.)
"""

import unittest

from bio_sfm_designer.experiments.conformal_complex_gate import run


class ConformalComplexGateTests(unittest.TestCase):
    def test_pae_signal_enables_selective_trust(self):
        r = run()
        self.assertGreaterEqual(r["n_cal"] + r["n_test"], 150)
        self.assertGreater(r["auroc_pae"], 0.85)                         # validated interface signal
        # trusting the most-confident (lowest-pAE) quartile is far safer than trust-all
        lowest = r["selective"][0]
        self.assertLess(lowest["false_accept_rate"], r["base_rate_fail"] - 0.3)
        # selective risk rises as you trust a larger (less confident) fraction
        fas = [s["false_accept_rate"] for s in r["selective"]]
        self.assertLessEqual(fas[0], fas[-1])

    def test_conformal_certifies_and_bounds_false_accept(self):
        # at n=192 (default n_cal=128, alpha=0.3) RCPS certifies a tau and the held-out trusted set's
        # false-accept rate is within the bound AND beats trust-all -- the distribution-free guarantee.
        r = run()
        self.assertIsNotNone(r["tau"])
        far = r["conformal"]["false_accept_rate"]
        self.assertIsNotNone(far)
        self.assertLessEqual(far, r["alpha"])
        self.assertLess(far, r["trust_all"]["false_accept_rate"])


if __name__ == "__main__":
    unittest.main()
