"""Producer->consumer contract for hpc/predict_boltz_complex.py WITHOUT Boltz/torch/the cluster: import
the runner, fake `boltz predict` so it writes a 2-chain Boltz-shaped output (chains A=target, B=binder +
confidence json with iptm), run main(), and feed the records into the real PrecomputedStructurePredictor.
Locks the 2-chain YAML path, the output-glob, the confidence keys (complex_plddt/iptm), the interface
L-RMSD (align on target, measure binder), and the record schema. Boltz inference itself is verified on Cayuga.
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


def _ca(serial, chain, resseq, x, y, z):
    # exact column layout the parser reads ([30:38]/[38:46]/[46:54] xyz, [21] chain, [12:16] "CA")
    return ("ATOM  %5d  CA  ALA %s%4d    %8.3f%8.3f%8.3f  1.00 50.00           C\n"
            % (serial, chain, resseq, x, y, z))


# reference complex: chain A (target) along x, chain C (binder) offset in y
_TARGET = [(0.0, 0.0, 0.0), (3.8, 0.0, 0.0), (7.6, 0.0, 0.0)]
_BINDER = [(0.0, 10.0, 0.0), (3.8, 10.0, 0.0), (7.6, 10.0, 0.0)]
_BACKBONE = "".join(_ca(i + 1, "A", i + 1, *p) for i, p in enumerate(_TARGET)) + \
            "".join(_ca(i + 1, "C", i + 1, *p) for i, p in enumerate(_BINDER))
# a faithful refold: chain A == target, chain B == binder -> L-RMSD 0 -> interface success
_FOLD = "".join(_ca(i + 1, "A", i + 1, *p) for i, p in enumerate(_TARGET)) + \
        "".join(_ca(i + 1, "B", i + 1, *p) for i, p in enumerate(_BINDER))


def _load():
    path = os.path.join(_HPC, "predict_boltz_complex.py")
    spec = importlib.util.spec_from_file_location("predict_boltz_complex_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PredictBoltzComplexContractTests(unittest.TestCase):
    @unittest.skipUnless(_HAS_NUMPY, "numpy needed for the Kabsch L-RMSD (verified on Cayuga)")
    def test_two_chain_output_feeds_structure_predictor(self):
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
                    fh.write(_FOLD)
                with open(os.path.join(pdir, f"confidence_{name}_model_0.json"), "w") as fh:
                    json.dump({"complex_plddt": 0.88, "ptm": 0.7, "iptm": 0.42}, fh)

        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "complex.pdb")
            with open(backbone, "w") as fh:
                fh.write(_BACKBONE)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "cx-0", "representation": "AAA", "target_seq": "AAA",
                                     "regime": "complex"}) + "\n")
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz_complex.py", "--candidates", cands, "--backbone", backbone,
                        "--target-chain", "A", "--binder-chain", "C", "--out", out, "--boltz", "/bin/true"]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(out) as fh:
                rec = json.loads(fh.readline())
            self.assertEqual(rec["refolder"], "boltz2_complex")
            self.assertEqual(rec["regime"], "complex")
            self.assertTrue(rec["interface_aligned"])
            self.assertAlmostEqual(rec["lrmsd"], 0.0, places=3)     # faithful refold -> binder in place
            self.assertEqual(rec["iptm"], 0.42)                      # interface signal carried through
            self.assertTrue(rec["truth"]["correct"])                 # L-RMSD 0 < threshold

            pred = PrecomputedStructurePredictor(out)
            p = pred.predict(Candidate(id="cx-0", representation="X"))
            self.assertAlmostEqual(p.raw_conf, 0.88, places=3)       # complex_plddt/100
            self.assertEqual(p.regime, "complex")


if __name__ == "__main__":
    unittest.main()
