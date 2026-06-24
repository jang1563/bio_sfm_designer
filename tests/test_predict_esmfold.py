"""Lock the torch-free logic of hpc/predict_esmfold.py (the ESMFold refold runner): CA parsing
with alternate-conformation dedup (the bug that produced uniform ~6 A scRMSD on 5L33), the Kabsch
RMSD, and that its record schema feeds the real PrecomputedStructurePredictor. ESMFold inference
itself needs a GPU and is verified on Cayuga, not here.
"""

import importlib.util
import json
import os
import tempfile
import unittest

from bio_sfm_designer.predict.structure import PrecomputedStructurePredictor
from bio_sfm_designer.types import Candidate

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")

try:
    import numpy as _np  # noqa: F401
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def _load():
    path = os.path.join(_HPC, "predict_esmfold.py")
    spec = importlib.util.spec_from_file_location("predict_esmfold_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 3 residues; residue 2 has altloc A+B (two CA lines). A correct parser yields 3 CAs, not 4.
_PDB = (
    "ATOM      1  CA  MET A   1      0.000   0.000   0.000  1.00 50.00           C\n"
    "ATOM      2  CA AALA A   2      3.800   0.000   0.000  0.50 50.00           C\n"
    "ATOM      3  CA BALA A   2      3.800   0.100   0.000  0.50 50.00           C\n"
    "ATOM      4  CA  GLY A   3      7.600   0.000   0.000  1.00 50.00           C\n"
    "HETATM    5  O   HOH A 101     1.000   1.000   1.000  1.00 50.00           O\n"
)


class PredictEsmfoldLogicTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_ca_parser_dedupes_altloc(self):
        # pure-Python (no numpy): the altloc dedup is the 5L33 bug fix, locked locally
        with tempfile.NamedTemporaryFile("w", suffix=".pdb", delete=False) as fh:
            fh.write(_PDB)
            p = fh.name
        try:
            ca = self.mod._ca_coords_from_pdb(p)
        finally:
            os.unlink(p)
        self.assertEqual(len(ca), 3)                            # altloc B dropped, HETATM ignored
        self.assertEqual(len(ca[0]), 3)
        self.assertAlmostEqual(ca[1][0], 3.8)                   # kept altloc A of residue 2

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed in this env (Kabsch verified on Cayuga)")
    def test_kabsch_rmsd_invariant_to_rigid_motion(self):
        import numpy as np
        P = [[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertAlmostEqual(self.mod._kabsch_rmsd(P, list(P)), 0.0, places=6)
        # rotate 90 deg about z + translate -> RMSD still ~0 after superposition
        Pa = np.asarray(P)
        R = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
        Q = Pa @ R.T + np.array([10.0, -5, 3])
        self.assertAlmostEqual(self.mod._kabsch_rmsd(Pa, Q), 0.0, places=6)

    def test_record_schema_feeds_structure_predictor(self):
        # a record shaped exactly like predict_esmfold.py emits must drive PrecomputedStructurePredictor
        rec = {"target_id": "d-0", "mean_plddt": 78.5, "regime": "monomer", "iptm": 0.66,
               "truth": {"correct": True, "quality": 0.84}, "scrmsd": 0.81,
               "scrmsd_threshold": 2.0, "ca_aligned": True, "proteinmpnn_score": 0.91}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
            pred = PrecomputedStructurePredictor(path)
            p = pred.predict(Candidate(id="d-0", representation="X"))
        self.assertAlmostEqual(p.raw_conf, 0.785, places=3)     # mean_plddt/100
        self.assertEqual(p.regime, "monomer")
        self.assertAlmostEqual(p.iptm, 0.66)
        self.assertTrue((p.truth or {})["sfm_correct"])         # success carried as hidden truth
        self.assertFalse(p.has_baseline)


if __name__ == "__main__":
    unittest.main()
