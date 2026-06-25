"""M6c-lite: locks the complex-regime finding on the committed barstar fixture -- interface ipTM
discriminates designed-interface success at fixed difficulty (pooled AUROC significantly above chance,
ipTM higher for successes), in direct CONTRAST to the monomer regime where pLDDT was chance-level. This
is the empirical basis for pursuing the complex/binder regime (where calibration earns its keep).
"""

import unittest

from bio_sfm_designer.experiments.complex_interface_signal import run as complex_run
from bio_sfm_designer.experiments.within_regime_signal import run as monomer_run


class ComplexInterfaceSignalTests(unittest.TestCase):
    def test_iptm_discriminates_interface_success(self):
        r = complex_run()
        self.assertGreaterEqual(r["n"], 60)
        self.assertGreater(r["success"], 8)                      # genuine mix, not degenerate
        self.assertLess(r["success"], r["n"])
        self.assertGreater(r["auroc_pooled"], 0.6)               # real signal (vs monomer chance)
        self.assertGreater(r["auroc_pooled_ci"][0], 0.5)         # CI excludes chance -> significant
        self.assertGreater(r["mean_iptm_success"], r["mean_iptm_fail"])  # informative

    def test_complex_signal_beats_monomer_chance(self):
        # the whole point: confidence discriminates in the COMPLEX regime but not the monomer regime
        self.assertGreater(complex_run()["auroc_pooled"], monomer_run()["auroc_cross"])


if __name__ == "__main__":
    unittest.main()
