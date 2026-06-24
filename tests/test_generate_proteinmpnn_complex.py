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
                open(out, "w").write("{}\n")
            elif script == "protein_mpnn_run.py":
                work = cmd[cmd.index("--out_folder") + 1]
                stem = os.path.splitext(os.path.basename(glob.glob(os.path.join(work, "pdbs", "*.pdb"))[0]))[0]
                seqs = os.path.join(work, "seqs")
                os.makedirs(seqs, exist_ok=True)
                with open(os.path.join(seqs, stem + ".fa"), "w") as fh:
                    fh.write(">cplx_AC, score=1.0, fixed_chains=['A'], designed_chains=['C']\nCCCC\n")
                    fh.write(">T=0.2, sample=1, score=0.8, seq_recovery=0.5\nDEDE\n")
                    fh.write(">T=0.2, sample=2, score=0.7, seq_recovery=0.5\nFGFG\n")

        mod.subprocess.run = fake_run

        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "cplx.pdb")
            with open(pdb, "w") as fh:  # _strip_chains needs ATOM lines for A and C
                fh.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 0.00           C\n")
                fh.write("ATOM      2  CA  ALA C   1       0.000  10.000   0.000  1.00 0.00           C\n")
            out = os.path.join(d, "cands.jsonl")
            argv = sys.argv
            sys.argv = ["generate_proteinmpnn_complex.py", "--mpnn-dir", d, "--pdb", pdb,
                        "--target-chain", "A", "--design-chain", "C", "--num-seq", "2",
                        "--objective", "binder", "--out", out, "--python", sys.executable]
            try:
                mod.main()
            finally:
                sys.argv = argv

            rows = [json.loads(line) for line in open(out) if line.strip()]
            self.assertEqual(len(rows), 2)                       # 2 designs (native row dropped)
            for r in rows:
                self.assertEqual(r["regime"], "complex")
                self.assertEqual(r["target_seq"], "AAAA")        # fixed target from parsed.jsonl
                self.assertEqual(r["meta"]["design_chain"], "C")
            self.assertEqual(rows[0]["representation"], "DEDE")  # redesigned binder from the FASTA
            self.assertEqual(rows[1]["representation"], "FGFG")


if __name__ == "__main__":
    unittest.main()
