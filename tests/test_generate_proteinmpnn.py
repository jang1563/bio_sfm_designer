"""Simulate the external HPC ProteinMPNN producer locally to prove the producer->consumer JSONL contract
WITHOUT torch / ProteinMPNN / the cluster. We import hpc/generate_proteinmpnn.py, swap its
subprocess call (the actual ProteinMPNN run) for a fake that writes a ProteinMPNN-format FASTA, run
main(), then feed the resulting candidates.jsonl into the real local PrecomputedGenerator. If field
names drift between the producer and generate.PrecomputedGenerator, this fails.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.generate.precomputed import PrecomputedGenerator

_HPC_DIR = os.path.join(os.path.dirname(__file__), "..", "hpc")

# native sequence first (ProteinMPNN convention), then two designs with score/seq_recovery headers
_FAKE_FASTA = (
    ">5L33, score=1.5969, global_score=1.5969, fixed_chains=[], designed_chains=['A'], model_name=v_48_020\n"
    "HMPEEEKAARLFIEALEKGD\n"
    ">T=0.2, sample=1, score=0.9074, global_score=0.9074, seq_recovery=0.4057\n"
    "SVDADTQKALDYIKALEAAD\n"
    ">T=0.2, sample=2, score=0.9406, global_score=0.9406, seq_recovery=0.3585\n"
    "AVDAETAKALAFVKALEQAD\n"
)


def _load_gen_module():
    path = os.path.join(_HPC_DIR, "generate_proteinmpnn.py")
    spec = importlib.util.spec_from_file_location("generate_proteinmpnn_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GenerateContractTests(unittest.TestCase):
    def test_parse_fasta_and_header_meta(self):
        mod = _load_gen_module()
        with tempfile.NamedTemporaryFile("w", suffix=".fa", delete=False) as fh:
            fh.write(_FAKE_FASTA)
            path = fh.name
        try:
            recs = list(mod._parse_fasta(path))
        finally:
            os.unlink(path)
        self.assertEqual(len(recs), 3)                          # native + 2 designs
        self.assertEqual(recs[1][1], "SVDADTQKALDYIKALEAAD")
        meta = mod._meta_from_header(recs[1][0])
        self.assertAlmostEqual(meta["seq_recovery"], 0.4057)
        self.assertAlmostEqual(meta["score"], 0.9074)          # not confused by global_score=

    def test_producer_output_feeds_precomputed_generator(self):
        mod = _load_gen_module()

        def fake_run(cmd, **kwargs):  # mimic ProteinMPNN writing <out_folder>/seqs/<pdb_id>.fa
            out_folder = cmd[cmd.index("--out_folder") + 1]
            pdb = cmd[cmd.index("--pdb_path") + 1]
            pdb_id = os.path.splitext(os.path.basename(pdb))[0]
            seqs = os.path.join(out_folder, "seqs")
            os.makedirs(seqs, exist_ok=True)
            with open(os.path.join(seqs, f"{pdb_id}.fa"), "w") as fh:
                fh.write(_FAKE_FASTA)

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "5L33.pdb")
            with open(pdb, "w") as fh:
                fh.write("FAKE PDB")
            out = os.path.join(d, "candidates.jsonl")
            argv = sys.argv
            sys.argv = ["generate_proteinmpnn.py", "--mpnn-dir", d, "--pdb", pdb, "--chains", "A",
                        "--num-seq", "2", "--objective", "thermostability", "--target",
                        "benign monomer", "--out", out, "--python", sys.executable]
            try:
                mod.main()
            finally:
                sys.argv = argv

            spec = ObjectiveSpec(target="benign monomer", objective="thermostability",
                                 rounds=1, candidates_per_round=8)
            cands = PrecomputedGenerator(out).propose(spec, 0, 8)
            self.assertEqual(len(cands), 2)                     # 2 designs (native excluded)
            self.assertEqual(cands[0].representation, "SVDADTQKALDYIKALEAAD")
            self.assertEqual(cands[0].meta["regime"], "monomer")
            self.assertEqual(cands[0].meta["backbone"], "5L33")
            self.assertEqual(cands[0].meta["generator"], "proteinmpnn")
            self.assertIn("seq_recovery", cands[0].meta)
            self.assertEqual(PrecomputedGenerator(out).propose(spec, 1, 8), [])  # single-pass set


if __name__ == "__main__":
    unittest.main()
