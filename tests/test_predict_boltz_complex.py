"""Producer->consumer contract for hpc/predict_boltz_complex.py WITHOUT Boltz/torch/the cluster: import
the runner, fake `boltz predict` so it writes a 2-chain Boltz-shaped output (chains A=target, B=binder +
confidence json with iptm + PAE), run main(), and feed the records into the real PrecomputedStructurePredictor.
Locks the 2-chain YAML path, the output-glob, the confidence keys (complex_plddt/iptm/pAE), the interface
L-RMSD (align on target, measure binder), and the pAE_interaction record/schema plumbing. Boltz inference
itself is verified on Cayuga.
"""

import glob
import importlib.util
import json
import os
import sys
import tempfile
import unittest

from bio_sfm_trust import confidence_to_risk

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
    def test_target_msa_query_sequence_must_match_candidates(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "complex.pdb")
            with open(backbone, "w") as fh:
                fh.write(_BACKBONE)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "cx-0", "representation": "AAA", "target_seq": "AAA",
                                     "regime": "complex"}) + "\n")
            target_msa = os.path.join(d, "wrong_target.a3m")
            with open(target_msa, "w") as fh:
                fh.write(">wrong\nAAK\n")
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz_complex.py", "--candidates", cands, "--backbone", backbone,
                        "--target-chain", "A", "--binder-chain", "C", "--target-msa", target_msa,
                        "--out", out, "--boltz", "/bin/true"]
            try:
                with self.assertRaises(SystemExit) as cm:
                    mod.main()
            finally:
                sys.argv = argv
            self.assertEqual(cm.exception.code, 2)

    def test_target_msa_query_parser_ignores_a3m_insertions_and_gaps(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            msa = os.path.join(d, "target.a3m")
            with open(msa, "w") as fh:
                fh.write(">target\nA-cD\n>hit\nAEDD\n")
            self.assertEqual(mod._read_first_fasta_sequence(msa), "AD")

    def test_target_msa_rejects_nul_bytes_before_boltz(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "complex.pdb")
            with open(backbone, "w") as fh:
                fh.write(_BACKBONE)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "cx-0", "representation": "AAA", "target_seq": "AAA",
                                     "regime": "complex"}) + "\n")
            target_msa = os.path.join(d, "target.a3m")
            with open(target_msa, "wb") as fh:
                fh.write(b">target\nAAA\n\x00")
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz_complex.py", "--candidates", cands, "--backbone", backbone,
                        "--target-chain", "A", "--binder-chain", "C", "--target-msa", target_msa,
                        "--out", out, "--boltz", "/bin/true"]
            try:
                with self.assertRaises(SystemExit) as cm:
                    mod.main()
            finally:
                sys.argv = argv
            self.assertEqual(cm.exception.code, 2)

    def test_zero_boltz_outputs_fail_closed(self):
        mod = _load()

        def fake_run(cmd, **kwargs):
            return None

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "complex.pdb")
            with open(backbone, "w") as fh:
                fh.write(_BACKBONE)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "cx-0", "representation": "AAA", "target_seq": "AAA",
                                     "regime": "complex"}) + "\n")
            target_msa = os.path.join(d, "target.a3m")
            with open(target_msa, "w") as fh:
                fh.write(">target\nAAA\n")
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz_complex.py", "--candidates", cands, "--backbone", backbone,
                        "--target-chain", "A", "--binder-chain", "C", "--target-msa", target_msa,
                        "--out", out, "--boltz", "/bin/true"]
            try:
                with self.assertRaises(RuntimeError):
                    mod.main()
            finally:
                sys.argv = argv

    @unittest.skipUnless(_HAS_NUMPY, "numpy needed for the Kabsch L-RMSD (verified on Cayuga)")
    def test_two_chain_output_feeds_structure_predictor(self):
        mod = _load()
        expected_target_msa = []

        def fake_run(cmd, **kwargs):  # mimic `boltz predict <yamls> --out_dir <out> ...`
            import numpy as np
            self.assertNotIn("--use_msa_server", cmd)
            yamls = cmd[2]
            outdir = cmd[cmd.index("--out_dir") + 1]
            base = os.path.basename(yamls.rstrip("/"))
            for y in glob.glob(os.path.join(yamls, "*.yaml")):
                name = os.path.splitext(os.path.basename(y))[0]
                with open(y) as fh:
                    yaml_text = fh.read()
                self.assertIn(f'msa: "{expected_target_msa[0]}"', yaml_text)
                self.assertIn("id: B", yaml_text)
                self.assertIn("msa: empty", yaml_text)
                pdir = os.path.join(outdir, f"boltz_results_{base}", "predictions", name)
                os.makedirs(pdir, exist_ok=True)
                with open(os.path.join(pdir, f"{name}_model_0.pdb"), "w") as fh:
                    fh.write(_FOLD)
                with open(os.path.join(pdir, f"confidence_{name}_model_0.json"), "w") as fh:
                    json.dump({"complex_plddt": 0.88, "ptm": 0.7, "iptm": 0.42}, fh)
                pae = np.full((6, 6), 12.0)
                pae[:3, 3:] = 2.4
                pae[3:, :3] = 2.4
                np.savez(os.path.join(pdir, f"pae_{name}_model_0.npz"), pae)

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "complex.pdb")
            with open(backbone, "w") as fh:
                fh.write(_BACKBONE)
            cands = os.path.join(d, "cands.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "cx-0", "representation": "AAA", "target_seq": "AAA",
                                     "regime": "complex"}) + "\n")
            target_msa = os.path.join(d, "target.a3m")
            with open(target_msa, "w") as fh:
                fh.write(">target\nAAA\n")
            expected_target_msa.append(os.path.abspath(target_msa))
            out = os.path.join(d, "records.jsonl")
            argv = sys.argv
            sys.argv = ["predict_boltz_complex.py", "--candidates", cands, "--backbone", backbone,
                        "--target-chain", "A", "--binder-chain", "C", "--target-msa", target_msa,
                        "--complex-id", "toy_complex", "--out", out, "--boltz", "/bin/true"]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(out) as fh:
                rec = json.loads(fh.readline())
            self.assertEqual(rec["refolder"], "boltz2_complex")
            self.assertEqual(rec["predictor_id"], "boltz2_complex")
            self.assertEqual(rec["signal_source"], "boltz2_pae_interaction")
            self.assertEqual(rec["label_source"], "boltz2_lrmsd_to_reference")
            self.assertEqual(rec["regime"], "complex")
            self.assertEqual(rec["complex_target_id"], "toy_complex")
            self.assertEqual(rec["target_chain"], "A")
            self.assertEqual(rec["binder_chain"], "C")
            self.assertTrue(rec["interface_aligned"])
            self.assertAlmostEqual(rec["lrmsd"], 0.0, places=3)     # faithful refold -> binder in place
            self.assertEqual(rec["iptm"], 0.42)                      # secondary interface signal carried through
            self.assertAlmostEqual(rec["pae_interaction"], 2.4, places=3)  # validated signal carried through
            self.assertTrue(rec["truth"]["correct"])                 # L-RMSD 0 < threshold

            pred = PrecomputedStructurePredictor(out)
            p = pred.predict(Candidate(id="cx-0", representation="X",
                                       meta={"complex_target_id": "toy_complex"}))
            self.assertAlmostEqual(p.raw_conf, 0.88, places=3)       # complex_plddt/100
            self.assertEqual(p.regime, "complex")
            self.assertAlmostEqual(p.pae_interaction, 2.4, places=3)
            self.assertAlmostEqual(confidence_to_risk(p.to_record()), 2.4 / 30.0, places=6)

    def test_structure_predictor_requires_complex_namespace_for_ambiguous_ids(self):
        rec_a = {
            "target_id": "design-0",
            "complex_target_id": "target_a",
            "mean_plddt": 90.0,
            "regime": "complex",
            "pae_interaction": 2.0,
            "truth": {"correct": True, "quality": 0.9},
        }
        rec_b = dict(rec_a)
        rec_b["complex_target_id"] = "target_b"
        rec_b["mean_plddt"] = 50.0
        rec_b["pae_interaction"] = 10.0
        rec_b["truth"] = {"correct": False, "quality": 0.1}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(rec_a) + "\n")
                fh.write(json.dumps(rec_b) + "\n")
            pred = PrecomputedStructurePredictor(path)

            with self.assertRaises(KeyError):
                pred.predict(Candidate(id="design-0", representation="X"))
            p = pred.predict(Candidate(id="design-0", representation="X",
                                       meta={"complex_target_id": "target_b"}))
        self.assertAlmostEqual(p.raw_conf, 0.5)
        self.assertAlmostEqual(p.pae_interaction, 10.0)


if __name__ == "__main__":
    unittest.main()
