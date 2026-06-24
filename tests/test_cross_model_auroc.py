"""M6a — the honest cross-model AUROC on the committed real-design fixtures. Locks that the ESMFold
pLDDT signal transfers to an INDEPENDENT Boltz-2 success label (so the M4b result is not a
self-prediction artifact), that the two refolders genuinely disagree (a non-trivial cross check),
and that Boltz is the stricter oracle.
"""

import unittest

from bio_sfm_designer.experiments.cross_model_auroc import run


class CrossModelAurocTests(unittest.TestCase):
    def test_signal_transfers_to_independent_refolder(self):
        r = run()
        self.assertGreaterEqual(r["n"], 100)
        # the ESMFold pLDDT signal predicts the INDEPENDENT Boltz success well -> not self-prediction
        self.assertGreater(r["auroc_cross_model"], 0.8)
        # the refolders genuinely differ (real independent check), but are correlated (not random)
        self.assertLess(r["label_agreement"], 1.0)
        self.assertGreater(r["label_agreement"], 0.5)
        # Boltz is the stricter oracle on these designs
        self.assertLess(r["boltz_success"], r["esmfold_success"])


if __name__ == "__main__":
    unittest.main()
