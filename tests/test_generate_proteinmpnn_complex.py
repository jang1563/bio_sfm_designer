"""Contract test for hpc/generate_proteinmpnn_complex.py WITHOUT ProteinMPNN/torch: fake the three
helper subprocess calls (parse_multiple_chains -> parsed.jsonl, assign_fixed_chains -> chainid, and
protein_mpnn_run -> seqs/<name>.fa), run main(), and assert the candidates carry BOTH the fixed target
sequence (from parsed.jsonl) and the redesigned binder sequence (from the FASTA), with regime=complex.
Locks the multichain FASTA-parsing + candidate schema. ProteinMPNN itself is verified on Cayuga.
"""

import glob
import importlib.util
import json
import os
import sys
import tempfile
import unittest

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load():
    path = os.path.join(_HPC, "generate_proteinmpnn_complex.py")
    spec = importlib.util.spec_from_file_location("generate_proteinmpnn_complex_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GenerateComplexContractTests(unittest.TestCase):
    def test_strip_chains_normalizes_modified_amino_acid(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "source.pdb")
            out = os.path.join(d, "stripped.pdb")
            with open(src, "w") as fh:
                fh.write("HETATM    1  CA  MSE A   1       0.000   0.000   0.000  1.00 0.00          SE\n")
                fh.write("ATOM      2  CA  ALA C   1       0.000  10.000   0.000  1.00 0.00           C\n")

            mod._strip_chains(src, ["A", "C"], out)

            with open(out) as fh:
                stripped = fh.read()
            self.assertIn("ATOM      1  CA  MET A   1", stripped)
            self.assertNotIn("HETATM", stripped)
            self.assertEqual(mod._target_ca_sequence(out, "A"), "M")

    def test_complex_sbatch_wrapper_targets_the_complex_runner(self):
        wrapper = os.path.join(_HPC, "run_generate_proteinmpnn_complex.sbatch")
        with open(wrapper) as fh:
            text = fh.read()
        self.assertIn("generate_proteinmpnn_complex.py", text)
        self.assertIn("TARGET_CHAIN", text)
        self.assertIn("DESIGN_CHAIN", text)
        self.assertIn("NUM_SEQ", text)
        self.assertIn("COMPLEX_ID", text)
        self.assertIn("ID_PREFIX", text)
        self.assertIn("W2B_STAGE", text)
        self.assertIn("W2B_SEED_NAMESPACE", text)
        self.assertIn("--complex-id", text)
        self.assertIn("--id-prefix", text)
        self.assertIn("unset PYTHONNOUSERSITE", text)

    def test_multichain_designs_become_candidates(self):
        mod = _load()

        def fake_run(cmd, **kwargs):
            script = os.path.basename(cmd[1])
            if script == "parse_multiple_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write(json.dumps({"name": "cplx_AC", "seq_chain_A": "AAAA",
                                         "seq_chain_C": "CCCC", "seq": "AAAACCCC"}) + "\n")
            elif script == "assign_fixed_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write("{}\n")
            elif script == "protein_mpnn_run.py":
                work = cmd[cmd.index("--out_folder") + 1]
                stem = os.path.splitext(os.path.basename(glob.glob(os.path.join(work, "pdbs", "*.pdb"))[0]))[0]
                seqs = os.path.join(work, "seqs")
                os.makedirs(seqs, exist_ok=True)
                with open(os.path.join(seqs, stem + ".fa"), "w") as fh:
                    fh.write(">cplx_AC, score=1.0, fixed_chains=['A'], designed_chains=['C']\nCCCC\n")
                    fh.write(">T=0.2, sample=1, score=0.8, seq_recovery=0.5\nDEDE\n")
                    fh.write(">T=0.2, sample=2, score=0.7, seq_recovery=0.5\nFGFG\n")

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "cplx.pdb")
            with open(pdb, "w") as fh:  # _strip_chains needs ATOM lines for A and C
                for i in range(1, 5):
                    fh.write(f"ATOM  {i:5d}  CA  ALA A{i:4d}       0.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      5  CA  CYS C   1       0.000  10.000   0.000  1.00 0.00           C\n")
            out = os.path.join(d, "cands.jsonl")
            argv = sys.argv
            sys.argv = ["generate_proteinmpnn_complex.py", "--mpnn-dir", d, "--pdb", pdb,
                        "--target-chain", "A", "--design-chain", "C", "--num-seq", "2",
                        "--objective", "binder", "--complex-id", "toy_complex",
                        "--out", out, "--python", sys.executable]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(out) as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(rows), 2)                       # 2 designs (native row dropped)
            for r in rows:
                self.assertEqual(r["regime"], "complex")
                self.assertEqual(r["target_seq"], "AAAA")        # fixed target from parsed.jsonl
                self.assertEqual(r["meta"]["design_chain"], "C")
                self.assertEqual(r["meta"]["complex_target_id"], "toy_complex")
                self.assertIn("toy_complex", r["id"])
            self.assertEqual(rows[0]["representation"], "DEDE")  # redesigned binder from the FASTA
            self.assertEqual(rows[1]["representation"], "FGFG")

    def test_target_seq_uses_ca_modeled_sequence_not_terminal_atom_only_residue(self):
        mod = _load()

        def fake_run(cmd, **kwargs):
            script = os.path.basename(cmd[1])
            if script == "parse_multiple_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write(json.dumps({"name": "cplx_AC", "seq_chain_A": "ACD",
                                         "seq_chain_C": "CCCC", "seq": "ACDCCCC"}) + "\n")
            elif script == "assign_fixed_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write("{}\n")
            elif script == "protein_mpnn_run.py":
                work = cmd[cmd.index("--out_folder") + 1]
                stem = os.path.splitext(os.path.basename(glob.glob(os.path.join(work, "pdbs", "*.pdb"))[0]))[0]
                seqs = os.path.join(work, "seqs")
                os.makedirs(seqs, exist_ok=True)
                with open(os.path.join(seqs, stem + ".fa"), "w") as fh:
                    fh.write(">native\nCCCC\n")
                    fh.write(">T=0.2, sample=1, score=0.8\nDEDE\n")

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "cplx.pdb")
            with open(pdb, "w") as fh:
                fh.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      2  CA  CYS A   2       1.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      3  N   ASP A   3       2.000   0.000   0.000  1.00 0.00           N\n")
                fh.write("ATOM      4  CA  CYS C   1       0.000  10.000   0.000  1.00 0.00           C\n")
            out = os.path.join(d, "cands.jsonl")
            argv = sys.argv
            sys.argv = ["generate_proteinmpnn_complex.py", "--mpnn-dir", d, "--pdb", pdb,
                        "--target-chain", "A", "--design-chain", "C",
                        "--out", out, "--python", sys.executable]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(out) as fh:
                rows = [json.loads(line) for line in fh if line.strip()]

        self.assertEqual(rows[0]["target_seq"], "AC")

    def test_output_stem_namespaces_proteinmpnn_workdir(self):
        mod = _load()
        workdirs = []

        def fake_run(cmd, **kwargs):
            script = os.path.basename(cmd[1])
            if script == "parse_multiple_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write(json.dumps({"name": "cplx_AC", "seq_chain_A": "AAAA",
                                         "seq_chain_C": "CCCC", "seq": "AAAACCCC"}) + "\n")
            elif script == "assign_fixed_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write("{}\n")
            elif script == "protein_mpnn_run.py":
                work = cmd[cmd.index("--out_folder") + 1]
                workdirs.append(work)
                stem = os.path.splitext(os.path.basename(glob.glob(os.path.join(work, "pdbs", "*.pdb"))[0]))[0]
                seqs = os.path.join(work, "seqs")
                os.makedirs(seqs)
                with open(os.path.join(seqs, stem + ".fa"), "w") as fh:
                    fh.write(">native\nCCCC\n")
                    fh.write(">T=0.2, sample=1, score=0.8\nDEDE\n")

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "cplx.pdb")
            with open(pdb, "w") as fh:
                fh.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      2  CA  ALA C   1       0.000  10.000   0.000  1.00 0.00           C\n")
            argv = sys.argv
            try:
                for out_name in ("cands_t030.jsonl", "cands_t050.jsonl"):
                    sys.argv = ["generate_proteinmpnn_complex.py", "--mpnn-dir", d, "--pdb", pdb,
                                "--target-chain", "A", "--design-chain", "C",
                                "--out", os.path.join(d, out_name), "--python", sys.executable]
                    mod.main()
            finally:
                sys.argv = argv

        self.assertEqual(len(workdirs), 2)
        self.assertNotEqual(workdirs[0], workdirs[1])
        self.assertTrue(workdirs[0].endswith("_mpnnX_cplx_cands_t030"))
        self.assertTrue(workdirs[1].endswith("_mpnnX_cplx_cands_t050"))

    def test_id_prefix_namespaces_candidate_ids(self):
        mod = _load()

        def fake_run(cmd, **kwargs):
            script = os.path.basename(cmd[1])
            if script == "parse_multiple_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write(json.dumps({"name": "cplx_AC", "seq_chain_A": "AAAA",
                                         "seq_chain_C": "CCCC", "seq": "AAAACCCC"}) + "\n")
            elif script == "assign_fixed_chains.py":
                out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output_path="))
                with open(out, "w") as fh:
                    fh.write("{}\n")
            elif script == "protein_mpnn_run.py":
                work = cmd[cmd.index("--out_folder") + 1]
                stem = os.path.splitext(os.path.basename(glob.glob(os.path.join(work, "pdbs", "*.pdb"))[0]))[0]
                seqs = os.path.join(work, "seqs")
                os.makedirs(seqs)
                with open(os.path.join(seqs, stem + ".fa"), "w") as fh:
                    fh.write(">native\nCCCC\n")
                    fh.write(">T=0.3, sample=1, score=0.8\nDEDE\n")

        original_run = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", original_run)
        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "cplx.pdb")
            with open(pdb, "w") as fh:
                fh.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      2  CA  ALA C   1       0.000  10.000   0.000  1.00 0.00           C\n")
            out = os.path.join(d, "cands_t030.jsonl")
            argv = sys.argv
            sys.argv = ["generate_proteinmpnn_complex.py", "--mpnn-dir", d, "--pdb", pdb,
                        "--target-chain", "A", "--design-chain", "C",
                        "--complex-id", "toy_complex", "--id-prefix", "binder-toy-t030",
                        "--w2b-stage", "fit", "--w2b-seed-namespace", "w2b-fit-v1",
                        "--out", out, "--python", sys.executable]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(out) as fh:
                rows = [json.loads(line) for line in fh if line.strip()]

        self.assertEqual(rows[0]["id"], "binder-toy-t030-0")
        self.assertEqual(rows[0]["meta"]["id_prefix"], "binder-toy-t030")
        self.assertEqual(rows[0]["w2b_stage"], "fit")
        self.assertEqual(rows[0]["w2b_seed_namespace"], "w2b-fit-v1")
        self.assertEqual(rows[0]["meta"]["w2b_stage"], "fit")


if __name__ == "__main__":
    unittest.main()
