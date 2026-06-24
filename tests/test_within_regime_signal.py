"""M6b: the clean within-regime (fixed-temperature) cross-model test. Locks the honest negative finding
that, once the temperature confound is removed, ESMFold pLDDT does NOT predict independent Boltz success
per design -- the AUROC is consistent with chance and far below the confounded pooled 0.967 (M6a). Guards
against silently re-introducing the batch-effect inflation.
"""

import unittest

from bio_sfm_designer.experiments.within_regime_signal import run


class WithinRegimeSignalTests(unittest.TestCase):
    def test_signal_collapses_to_chance_at_fixed_difficulty(self):
        r = run()
        self.assertGreaterEqual(r["n"], 150)
        # the Boltz label is a genuine mix at this temp (not saturated either way) -> AUROC is meaningful
        rate = r["boltz_success"] / r["n"]
        self.assertGreater(rate, 0.3)
        self.assertLess(rate, 0.9)
        # within a fixed regime the cross-model AUROC is ~chance: its CI contains 0.5 ...
        lo, hi = r["auroc_cross_ci"]
        self.assertLessEqual(lo, 0.5)
        self.assertGreaterEqual(hi, 0.5)
        # ... and it is far below the confounded pooled number (0.967) -> the pooled signal was a batch effect
        self.assertLess(r["auroc_cross"], 0.75)
        # pLDDT barely differs between Boltz-success and Boltz-fail designs (no per-design separation)
        self.assertLess(abs(r["mean_plddt_boltz_success"] - r["mean_plddt_boltz_fail"]), 3.0)


if __name__ == "__main__":
    unittest.main()
