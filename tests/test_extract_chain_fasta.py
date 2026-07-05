"""Tests for deterministic target-chain FASTA extraction before M6c MSA generation."""

import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import unittest

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load():
    path = os.path.join(_HPC, "extract_chain_fasta.py")
    spec = importlib.util.spec_from_file_location("extract_chain_fasta_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ca(serial, resname, chain, resseq, x=0.0, y=0.0, z=0.0, record="ATOM  ", altloc=" "):
    return ("%s%5d  CA %s%3s %s%4d    %8.3f%8.3f%8.3f  1.00 50.00           C\n"
            % (record, serial, altloc, resname, chain, resseq, x, y, z))


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ExtractChainFastaTests(unittest.TestCase):
    def test_extracts_modeled_chain_and_maps_common_modified_residue(self):
        mod = _load()
        pdb_text = (
            _ca(1, "ALA", "A", 1) +
            _ca(2, "MSE", "A", 2, record="HETATM") +
            _ca(3, "GLY", "B", 1) +
            _ca(4, "VAL", "A", 3, altloc="B")
        )
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "complex.pdb")
            out = os.path.join(d, "target.fasta")
            report = os.path.join(d, "target.report.json")
            with open(pdb, "w") as fh:
                fh.write(pdb_text)
            argv = sys.argv
            sys.argv = ["extract_chain_fasta.py", "--pdb", pdb, "--chain", "A",
                        "--id", "target_A", "--out", out, "--report", report]
            try:
                rep = mod.main()
            finally:
                sys.argv = argv

            self.assertEqual(rep["sequence"], "AM")
            with open(out) as fh:
                self.assertEqual(fh.read(), ">target_A\nAM\n")
            with open(report) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["length"], 2)
            self.assertEqual(saved["pdb_sha256"], _sha256_file(pdb))
            self.assertEqual(saved["out_sha256"], _sha256_file(out))

    def test_rejects_unknown_residue_unless_allowed(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "complex.pdb")
            with open(pdb, "w") as fh:
                fh.write(_ca(1, "UNK", "A", 1))
            with self.assertRaisesRegex(ValueError, "unknown residue"):
                mod.extract_chain_sequence(pdb, "A")
            rep = mod.extract_chain_sequence(pdb, "A", allow_unknown=True)
            self.assertEqual(rep["sequence"], "X")

    def test_expect_sequence_guard_catches_wrong_target(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "complex.pdb")
            out = os.path.join(d, "target.fasta")
            with open(pdb, "w") as fh:
                fh.write(_ca(1, "ALA", "A", 1))
            argv = sys.argv
            sys.argv = ["extract_chain_fasta.py", "--pdb", pdb, "--chain", "A",
                        "--out", out, "--expect-seq", "G"]
            try:
                with self.assertRaisesRegex(ValueError, "expect-seq"):
                    mod.main()
            finally:
                sys.argv = argv


if __name__ == "__main__":
    unittest.main()
