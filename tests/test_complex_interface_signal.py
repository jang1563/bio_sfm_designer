"""M6c-lite (corrected): locks the honest complex-regime finding on the barstar fixture. CONFIDENCE
discriminates designed-complex success at fixed difficulty (confound-free stratified AUROC), in contrast
to the monomer regime (chance) -- BUT it is FOLD confidence (complex pLDDT), not INTERFACE confidence
(ipTM, which is weak), and the label conflates fold with dock (failures are mostly binder mis-folds).
"""

import unittest

from bio_sfm_designer.experiments.complex_interface_signal import run as complex_run
from bio_sfm_designer.experiments.within_regime_signal import run as monomer_run


class ComplexInterfaceSignalTests(unittest.TestCase):
    def test_fold_confidence_discriminates_at_fixed_difficulty(self):
        r = complex_run()
        self.assertGreaterEqual(r["n"], 60)
        self.assertGreater(r["success"], 8)                       # genuine mix, not degenerate
        self.assertLess(r["success"], r["n"])
        plddt = r["stratified"]["mean_plddt"]
        self.assertGreater(plddt["auroc"], 0.75)                  # complex fold confidence discriminates
        self.assertGreater(plddt["ci"][0], 0.5)                   # confound-free CI excludes chance
        # most failures are binder mis-folds -> the label conflates fold quality with interface quality
        self.assertGreater(r["mean_plddt_success"], r["mean_plddt_fail"] + 3)

    def test_iptm_is_weaker_than_fold_confidence(self):
        # the corrected finding: it is FOLD confidence (pLDDT), NOT interface confidence (ipTM)
        s = complex_run()["stratified"]
        self.assertGreater(s["mean_plddt"]["auroc"], s["iptm"]["auroc"])

    def test_complex_signal_beats_monomer_chance(self):
        # the strategic point: confidence discriminates in the COMPLEX regime but not the monomer regime
        self.assertGreater(complex_run()["stratified"]["mean_plddt"]["auroc"], monomer_run()["auroc_cross"])


if __name__ == "__main__":
    unittest.main()
