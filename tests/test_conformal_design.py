"""M5b split-LTT trust gate on the real ProteinMPNN->ESMFold design fixture."""

import os
import unittest

from bio_sfm_designer.experiments.conformal_design_gate import run

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "esmfold_designs_records.jsonl")


class ConformalDesignTests(unittest.TestCase):
    def test_split_ltt_refuses_when_independent_certificate_is_underpowered(self):
        rep = run(_FIXTURE, alpha=0.2, delta=0.1, n_cal=80, seed=0)
        self.assertGreater(rep["auroc_plddt"], 0.7, "pLDDT should predict self-consistency success")
        self.assertIsNone(rep["tau"])
        self.assertEqual(rep["certification_schema"], "split_ltt_v1")
        self.assertFalse(rep["certificate"]["certified"])
        self.assertEqual(rep["conformal"]["trusted"], 0)

    def test_refuses_when_alpha_too_strict_for_n(self):
        # the gate must NOT over-promise: a tiny alpha on ~120 designs is uncertifiable -> no tau.
        rep = run(_FIXTURE, alpha=0.02, delta=0.1, n_cal=80, seed=0)
        self.assertIsNone(rep["tau"])
        self.assertEqual(rep["conformal"]["trusted"], 0)   # no tau -> trust nothing in this regime


if __name__ == "__main__":
    unittest.main()
