"""M6c-lite (review-complete): the complex-regime interface signal on the barstar fixture. pAE_interaction
(the metric binder-design actually uses) discriminates designed-interface success at fixed difficulty AND
even among WELL-FOLDED binders (foldability controlled), where ipTM is chance -- so it is a genuine
interface-quality signal, in contrast to the monomer regime (chance). Locks the corrected finding.
"""

import unittest

from bio_sfm_designer.experiments.complex_interface_signal import run as complex_run
from bio_sfm_designer.experiments.within_regime_signal import run as monomer_run


class ComplexInterfaceSignalTests(unittest.TestCase):
    def test_pae_interaction_discriminates_at_fixed_difficulty(self):
        r = complex_run()
        self.assertGreaterEqual(r["n"], 150)
        self.assertGreater(r["success"], 20)                         # genuine dock mix
        self.assertLess(r["success"], r["n"])
        pae = r["stratified"]["pae_interaction"]
        self.assertGreater(pae["auroc"], 0.8)                        # the real interface signal
        self.assertGreater(pae["ci"][0], 0.5)                        # confound-free CI excludes chance

    def test_pae_beats_iptm_even_among_well_folded(self):
        # foldability control: pAE_interaction strongly separates docking among well-folded binders; ipTM weak
        r = complex_run()
        self.assertGreater(r["well_folded"]["auroc_pae"], 0.75)
        self.assertGreater(r["well_folded"]["auroc_pae"] - r["well_folded"]["auroc_iptm"], 0.2)  # pAE >> ipTM
        self.assertGreater(r["stratified"]["pae_interaction"]["auroc"], r["stratified"]["iptm"]["auroc"])

    def test_complex_signal_beats_monomer_chance(self):
        # the strategic point: an interface signal exists in the COMPLEX regime but not the monomer regime
        self.assertGreater(complex_run()["stratified"]["pae_interaction"]["auroc"], monomer_run()["auroc_cross"])


if __name__ == "__main__":
    unittest.main()
