"""Contract tests for hpc/prep_hetdimer.py.

These lock the cheap target-selection guard for M6c multi-target scale-up: prepare a two-chain
backbone only when the requested chains exist, are gap-free by residue numbering, and form a
CA-contacting interface.
"""

import importlib.util
import os
import tempfile
import unittest

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load():
    path = os.path.join(_HPC, "prep_hetdimer.py")
    spec = importlib.util.spec_from_file_location("prep_hetdimer_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ca(serial, chain, resseq, x, y, z):
    return ("ATOM  %5d  CA  ALA %s%4d    %8.3f%8.3f%8.3f  1.00 50.00           C\n"
            % (serial, chain, resseq, x, y, z))


class PrepHetdimerTests(unittest.TestCase):
    def test_prepares_contacting_two_chain_complex(self):
        mod = _load()
        pdb_text = (
            _ca(1, "A", 1, 0.0, 0.0, 0.0) +
            _ca(2, "A", 2, 3.8, 0.0, 0.0) +
            _ca(3, "B", 1, 0.0, 5.0, 0.0) +
            _ca(4, "B", 2, 3.8, 5.0, 0.0) +
            _ca(5, "C", 1, 50.0, 50.0, 50.0)
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "source.pdb")
            out = os.path.join(d, "prepared.pdb")
            with open(src, "w") as fh:
                fh.write(pdb_text)

            rep = mod.prepare_hetdimer(src, "A", "B", out, min_residues=2)

            self.assertEqual(rep["target_ca_residues"], 2)
            self.assertEqual(rep["binder_ca_residues"], 2)
            self.assertGreaterEqual(rep["ca_interface_contacts"], 1)
            with open(out) as fh:
                prepared = fh.read()
            self.assertIn(" A   1", prepared)
            self.assertIn(" B   1", prepared)
            self.assertNotIn(" C   1", prepared)

    def test_rejects_non_contacting_chains(self):
        mod = _load()
        pdb_text = (
            _ca(1, "A", 1, 0.0, 0.0, 0.0) +
            _ca(2, "A", 2, 3.8, 0.0, 0.0) +
            _ca(3, "B", 1, 0.0, 50.0, 0.0) +
            _ca(4, "B", 2, 3.8, 50.0, 0.0)
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "source.pdb")
            out = os.path.join(d, "prepared.pdb")
            with open(src, "w") as fh:
                fh.write(pdb_text)

            with self.assertRaisesRegex(ValueError, "interface contacts below threshold"):
                mod.prepare_hetdimer(src, "A", "B", out, min_residues=2)

    def test_rejects_numbering_gaps_by_default(self):
        mod = _load()
        pdb_text = (
            _ca(1, "A", 1, 0.0, 0.0, 0.0) +
            _ca(2, "A", 3, 3.8, 0.0, 0.0) +
            _ca(3, "B", 1, 0.0, 5.0, 0.0) +
            _ca(4, "B", 2, 3.8, 5.0, 0.0)
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "source.pdb")
            out = os.path.join(d, "prepared.pdb")
            with open(src, "w") as fh:
                fh.write(pdb_text)

            with self.assertRaisesRegex(ValueError, "residue-numbering gaps"):
                mod.prepare_hetdimer(src, "A", "B", out, min_residues=2)

    def test_rejects_overwriting_source_pdb(self):
        mod = _load()
        pdb_text = (
            _ca(1, "A", 1, 0.0, 0.0, 0.0) +
            _ca(2, "A", 2, 3.8, 0.0, 0.0) +
            _ca(3, "B", 1, 0.0, 5.0, 0.0) +
            _ca(4, "B", 2, 3.8, 5.0, 0.0)
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "source.pdb")
            with open(src, "w") as fh:
                fh.write(pdb_text)

            with self.assertRaisesRegex(ValueError, "out_pdb must be different"):
                mod.prepare_hetdimer(src, "A", "B", src, min_residues=2)


if __name__ == "__main__":
    unittest.main()
