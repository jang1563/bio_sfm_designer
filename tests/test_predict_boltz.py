"""Producer->consumer contract for hpc/predict_boltz.py WITHOUT Boltz/torch/the cluster: import the
runner, fake the `boltz predict` subprocess so it writes Boltz-shaped output (predictions/<name>/
<name>_model_0.pdb + confidence_<name>_model_0.json), run main(), and feed the resulting records.jsonl
into the real PrecomputedStructurePredictor. Locks the output-glob paths, the confidence-JSON keys
(complex_plddt/ptm), and the record schema. Boltz inference itself is verified on Cayuga.
"""

import glob
import importlib.util
import json
import os
import sys
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

# three CA atoms in the proven column layout (chain A); backbone == refold -> scRMSD 0 -> success.
_CA3 = (
    "ATOM      1  CA  ALA A   1      0.000   0.000   0.000  1.00 50.00           C\n"
    "ATOM      2  CA  ALA A   2      3.800   0.000   0.000  1.00 50.00           C\n"
    "ATOM      3  CA  ALA A   3      7.600   0.000   0.000  1.00 50.00           C\n"
)


def _load():
    path = os.path.join(_HPC, "predict_boltz.py")
    spec = importlib.util.spec_from_file_location("predict_boltz_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PredictBoltzContractTests(unittest.TestCase):
    @unittest.skipUnless(_HAS_NUMPY, "numpy needed for the Kabsch scRMSD (verified on Cayuga)")
    def test_producer_output_feeds_structure_predictor(self):
        mod = _load()

        def fake_run(cmd, **kwargs):  # mimic `boltz predict <yamls> --out_dir <out> ...`
            yamls = cmd[2]
            outdir = cmd[cmd.index("--out_dir") + 1]
            base = os.path.basename(yamls.rstrip("/"))
            for y in glob.glob(os.path.join(yamls, "*.yaml")):
                name = os.path.splitext(os.path.basename(y))[0]
                pdir = os.path.join(outdir, f"boltz_results_{base}", "predictions", name)
                os.makedirs(pdir, exist_ok=True)
                with open(os.path.join(pdir, f"{name}_model_0.pdb"), "w") as fh:
                    fh.write(_CA3)
                with open(os.path.join(pdir, f"confidence_{name}_model_0.json"), "w") as fh:
                    json.dump({"complex_plddt": 0.91, "ptm": 0.88, "iptm": 0.0}, fh)

        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "bb.pdb")
            with open(backbone, "w") as fh:
                fh.write(_CA3)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "des-0", "representation": "AAA", "regime": "monomer"}) + "\n")
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz.py", "--candidates", cands, "--backbone", backbone,
                        "--out", out, "--boltz", "/bin/true"]
            try:
                mod.main()
            finally:
                sys.argv = argv

            pred = PrecomputedStructurePredictor(out)
            p = pred.predict(Candidate(id="des-0", representation="X"))
            self.assertAlmostEqual(p.raw_conf, 0.91, places=3)      # complex_plddt/100
            self.assertEqual(p.regime, "monomer")
            self.assertTrue((p.truth or {})["sfm_correct"])         # scRMSD 0 < 2A
            with open(out) as fh:
                rec = json.loads(fh.readline())
            self.assertEqual(rec["refolder"], "boltz2")
            self.assertTrue(rec["ca_aligned"])


if __name__ == "__main__":
    unittest.main()
