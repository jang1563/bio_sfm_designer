"""M6a self-review: the HONEST cross-model picture on the committed real-design fixtures. Locks both
the positive finding (the ESMFold pLDDT signal transfers to the INDEPENDENT Boltz label, so it is not
pure self-prediction) AND the confounds that keep it from being a clean "caveat closed": the
cross-vs-single AUROC difference is not significant, and failures concentrate at the highest sampling
temperature (so the pooled AUROC is partly a low-temp-vs-high-temp batch effect, not per-design signal).
"""

import unittest

from bio_sfm_designer.experiments.cross_model_auroc import run


class CrossModelAurocTests(unittest.TestCase):
    def test_signal_transfers_but_not_significantly_better(self):
        r = run()
        self.assertGreaterEqual(r["n"], 100)
        self.assertGreater(r["auroc_cross_model"], 0.8)          # transfers to the independent oracle
        self.assertLess(r["label_agreement"], 1.0)               # refolders genuinely differ
        self.assertGreater(r["label_agreement"], 0.5)            # but are correlated, not random
        self.assertLess(r["boltz_success"], r["esmfold_success"])  # Boltz fails more (stricter OR weaker)
        # HONEST: cross-model is NOT significantly better than single-model (the difference CI spans 0)
        lo, hi = r["auroc_cross_minus_single_ci"]
        self.assertLessEqual(lo, 0.0)
        self.assertGreaterEqual(hi, 0.0)

    def test_failures_concentrate_at_high_temperature(self):
        # the confound: at the hottest sampling temp Boltz almost never succeeds, so the pooled AUROC
        # is largely separating easy(low-temp) from hard(high-temp) BATCHES, not per-design quality.
        pt = run()["per_temp"]
        self.assertEqual(pt["design_t03"]["boltz_success"], pt["design_t03"]["n"])  # all low-temp succeed
        self.assertLessEqual(pt["design_t10"]["boltz_success"], 2)                  # almost all high-temp fail


if __name__ == "__main__":
    unittest.main()
