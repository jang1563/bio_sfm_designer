"""M5b — the conformal trust gate, demonstrated on the REAL ProteinMPNN->ESMFold design fixture
(tests/fixtures/esmfold_designs_records.jsonl, 120 designs). Locks that on real designs the gate
certifies a tau and the held-out TRUSTED set's false-accept rate respects the target alpha, while
trusting a meaningful fraction and making strictly fewer false-accepts than trusting everything.
(The RCPS guarantee itself is proven in bio-sfm-trust tests/test_conformal.py.)
"""

import os
import unittest

from bio_sfm_designer.experiments.conformal_design_gate import run

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "esmfold_designs_records.jsonl")


class ConformalDesignTests(unittest.TestCase):
    def test_conformal_controls_held_out_false_accepts_on_real_designs(self):
        rep = run(_FIXTURE, alpha=0.2, delta=0.1, n_cal=80, seed=0)
        self.assertGreater(rep["auroc_plddt"], 0.7, "pLDDT should predict self-consistency success")
        self.assertIsNotNone(rep["tau"], "should certify a tau on the real designs at this (alpha, delta, n)")
        c, ta = rep["conformal"], rep["trust_all"]
        self.assertGreater(c["trusted"], 0, "should trust a meaningful fraction, not nothing")
        self.assertLessEqual(c["false_accept_rate"], rep["alpha"], "trusted-set false-accept must respect alpha")
        self.assertLess(c["false_accepts"], ta["false_accepts"],
                        "conformal must make fewer false-accepts than trusting everything")

    def test_refuses_when_alpha_too_strict_for_n(self):
        # the gate must NOT over-promise: a tiny alpha on ~120 designs is uncertifiable -> no tau.
        rep = run(_FIXTURE, alpha=0.02, delta=0.1, n_cal=80, seed=0)
        self.assertIsNone(rep["tau"])
        self.assertEqual(rep["conformal"]["trusted"], 0)   # no tau -> trust nothing in this regime


if __name__ == "__main__":
    unittest.main()
