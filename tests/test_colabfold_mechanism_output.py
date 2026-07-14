"""Tests for strict conversion of ColabFold mechanism-panel outputs."""

import importlib.util
import json
import pathlib
import tempfile
import unittest

import numpy as np


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "hpc/convert_colabfold_mechanism_panel.py"


def _load():
    spec = importlib.util.spec_from_file_location("convert_colabfold_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdb_ca(serial, chain, resid, x, y, z):
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{resid:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 50.00           C\n"
    )


class ColabFoldMechanismOutputTests(unittest.TestCase):
    def test_build_record_uses_rank_one_pae_and_target_aligned_lrmsd(self):
        module = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            reference = root / "reference.pdb"
            reference.write_text(
                _pdb_ca(1, "X", 1, 0, 0, 0)
                + _pdb_ca(2, "X", 2, 1, 0, 0)
                + _pdb_ca(3, "Y", 1, 0, 3, 0)
                + _pdb_ca(4, "Y", 2, 1, 3, 0)
                + "END\n"
            )
            a3m = root / "w3m-001.a3m"
            a3m.write_text("#2,2\t1,1\n>101\t102\nACDE\n")
            output = root / "output"
            output.mkdir()
            tag = "rank_001_alphafold2_multimer_v3_model_1_seed_000"
            pdb = output / f"w3m-001_unrelaxed_{tag}.pdb"
            pdb.write_text(
                _pdb_ca(1, "A", 1, 0, 0, 0)
                + _pdb_ca(2, "A", 2, 1, 0, 0)
                + _pdb_ca(3, "B", 1, 0, 3, 0)
                + _pdb_ca(4, "B", 2, 1, 3, 0)
                + "END\n"
            )
            pae = np.zeros((4, 4), dtype=float)
            pae[:2, 2:] = 4.0
            pae[2:, :2] = 6.0
            scores = output / f"w3m-001_scores_{tag}.json"
            scores.write_text(json.dumps({
                "pae": pae.tolist(),
                "plddt": [90.0, 91.0, 92.0, 93.0],
                "iptm": 0.8,
                "ptm": 0.7,
            }))
            case = {
                "case_id": "w3m-001",
                "source_target_id": "design-0",
                "complex_target_id": "3PC8_AB",
                "target_chain": "X",
                "binder_chain": "Y",
                "target_sequence": "AC",
                "binder_sequence": "DE",
                "target_sequence_sha256": "target-sha",
                "binder_sequence_sha256": "binder-sha",
                "a3m_path": str(a3m),
                "a3m_sha256": module._sha256_file(a3m),
                "reference_backbone_path": str(reference),
                "reference_backbone_sha256": module._sha256_file(reference),
                "panel_block": "test",
                "panel_role": "test",
            }

            record = module.build_record(case, output)

            pdb.write_text(
                _pdb_ca(1, "A", 1, 0, 0, 0)
                + _pdb_ca(2, "A", 2, 1, 0, 0)
                + _pdb_ca(3, "B", 1, 0, 3, 0)
                + "END\n"
            )
            with self.assertRaisesRegex(ValueError, "CA lengths do not match locks"):
                module.build_record(case, output)

        self.assertEqual(record["target_id"], "design-0")
        self.assertEqual(record["predictor_id"], "af2_multimer_colabfold_v1")
        self.assertAlmostEqual(record["pae_interaction"], 5.0)
        self.assertAlmostEqual(record["lrmsd"], 0.0)
        self.assertTrue(record["interface_aligned"])
        self.assertTrue(record["truth"]["correct"])
        self.assertEqual(record["model_tag"], tag)

    def test_conversion_revalidates_private_manifest_sha_lock(self):
        module = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manifest = root / "inputs.jsonl"
            private_rows = [
                {"case_id": f"w3m-{index:03d}", "panel_block": "test"}
                for index in range(1, 59)
            ]
            manifest.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in private_rows)
            )
            packet = {
                "status": "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit",
                "audit_ok": True,
                "execution_packet": {
                    "private_manifest_sha256": module._sha256_file(manifest),
                },
                "rows": [dict(row) for row in private_rows],
            }

            self.assertEqual(
                module.validate_conversion_inputs(packet, manifest, private_rows), []
            )
            manifest.write_text(manifest.read_text() + "\n")
            failures = module.validate_conversion_inputs(packet, manifest, private_rows)

        self.assertIn("private_manifest_sha_mismatch", {row["kind"] for row in failures})


if __name__ == "__main__":
    unittest.main()
