import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import numpy as np

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load(name):
    path = os.path.join(_HPC, name)
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_under_test"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pdb_ca(serial, chain, resid, x, y, z):
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{resid:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 50.00           C\n"
    )


def _write_cif(path):
    rows = [
        ("A", 1, 0.0, 0.0, 0.0, 91.0),
        ("A", 2, 1.0, 0.0, 0.0, 92.0),
        ("B", 1, 0.0, 3.0, 0.0, 93.0),
        ("B", 2, 1.0, 3.0, 0.0, 94.0),
    ]
    with open(path, "w") as handle:
        handle.write(
            "data_model\n"
            "loop_\n"
            "_atom_site.group_PDB\n"
            "_atom_site.id\n"
            "_atom_site.type_symbol\n"
            "_atom_site.label_atom_id\n"
            "_atom_site.label_alt_id\n"
            "_atom_site.label_comp_id\n"
            "_atom_site.label_seq_id\n"
            "_atom_site.auth_seq_id\n"
            "_atom_site.pdbx_PDB_ins_code\n"
            "_atom_site.label_asym_id\n"
            "_atom_site.Cartn_x\n"
            "_atom_site.Cartn_y\n"
            "_atom_site.Cartn_z\n"
            "_atom_site.occupancy\n"
            "_atom_site.label_entity_id\n"
            "_atom_site.auth_asym_id\n"
            "_atom_site.auth_comp_id\n"
            "_atom_site.B_iso_or_equiv\n"
            "_atom_site.pdbx_PDB_model_num\n"
        )
        atom_id = 1
        for chain, resid, x, y, z, b in rows:
            entity = 1 if chain == "A" else 2
            handle.write(
                f"ATOM {atom_id} C CA . ALA {resid} {resid} ? {chain} "
                f"{x:.3f} {y:.3f} {z:.3f} 1.00 {entity} {chain} ALA {b:.2f} 1\n"
            )
            atom_id += 1
        handle.write("#\n")


class Chai1OutputToolTests(unittest.TestCase):
    def test_wrapper_saves_candidate_metric_arrays(self):
        mod = _load("run_chai1_api_with_metrics.py")

        class Candidate:
            pae = np.ones((2, 4, 4), dtype=np.float32)
            pde = np.full((2, 4, 4), 2.0, dtype=np.float32)
            plddt = np.full((2, 4), 0.9, dtype=np.float32)

        with tempfile.TemporaryDirectory() as d:
            summary = mod.save_candidate_metric_arrays(Candidate(), pathlib.Path(d))
            self.assertEqual(summary["n_models"], 2)
            self.assertTrue(os.path.exists(os.path.join(d, "pae.model_idx_1.npz")))
            self.assertTrue(os.path.exists(os.path.join(d, "chai_api_metrics_summary.json")))
            saved = np.load(os.path.join(d, "plddt.model_idx_0.npz"))["plddt"]
            self.assertEqual(saved.shape, (4,))

    def test_converter_writes_strict_chai_complex_record_from_real_pae(self):
        mod = _load("convert_chai1_complex_output.py")
        with tempfile.TemporaryDirectory() as d:
            backbone = os.path.join(d, "ref.pdb")
            with open(backbone, "w") as handle:
                handle.write(_pdb_ca(1, "A", 1, 0.0, 0.0, 0.0))
                handle.write(_pdb_ca(2, "A", 2, 1.0, 0.0, 0.0))
                handle.write(_pdb_ca(3, "B", 1, 0.0, 3.0, 0.0))
                handle.write(_pdb_ca(4, "B", 2, 1.0, 3.0, 0.0))
                handle.write("END\n")
            out_dir = os.path.join(d, "chai")
            os.makedirs(out_dir)
            _write_cif(os.path.join(out_dir, "pred.model_idx_0.cif"))
            np.savez(os.path.join(out_dir, "scores.model_idx_0.npz"),
                     aggregate_score=np.array([0.8]), iptm=np.array([0.7]), ptm=np.array([0.9]))
            pae = np.zeros((4, 4), dtype=np.float32)
            pae[:2, 2:] = 4.0
            pae[2:, :2] = 6.0
            np.savez(os.path.join(out_dir, "pae.model_idx_0.npz"), pae=pae)
            np.savez(os.path.join(out_dir, "plddt.model_idx_0.npz"), plddt=np.full(4, 0.88))
            manifest = os.path.join(d, "manifest.json")
            with open(manifest, "w") as handle:
                json.dump({
                    "candidate_id": "cand0",
                    "complex_target_id": "3PC8_AB",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_sequence_length": 2,
                    "binder_sequence_length": 2,
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                }, handle)
            records = os.path.join(d, "records.jsonl")

            rc = mod.main([
                "--manifest", manifest,
                "--chai-out", out_dir,
                "--backbone", backbone,
                "--out", records,
                "--threshold", "4.0",
            ])

            self.assertEqual(rc, 0)
            with open(records) as handle:
                rec = json.loads(handle.readline())
            self.assertEqual(rec["target_id"], "cand0")
            self.assertEqual(rec["predictor_id"], "chai1_complex")
            self.assertEqual(rec["signal_source"], "chai1_pae_interaction")
            self.assertAlmostEqual(rec["pae_interaction"], 5.0)
            self.assertAlmostEqual(rec["lrmsd"], 0.0)
            self.assertTrue(rec["truth"]["correct"])
            self.assertTrue(rec["interface_aligned"])

    def test_sbatch_syntax(self):
        subprocess.run(["bash", "-n", os.path.join(_HPC, "run_chai1_smoke.sbatch")], check=True)
        subprocess.run(["bash", "-n", os.path.join(_HPC, "run_chai1_batch_array.sbatch")], check=True)

    def test_batch_aggregator_writes_unique_records_and_report(self):
        mod = _load("aggregate_chai1_batch_records.py")
        with tempfile.TemporaryDirectory() as d:
            batch = pathlib.Path(d) / "batch"
            out = pathlib.Path(d) / "records.jsonl"
            report = pathlib.Path(d) / "report.json"
            for i in range(2):
                run_dir = batch / f"index_{i}"
                run_dir.mkdir(parents=True)
                with open(run_dir / "input_manifest.json", "w") as handle:
                    json.dump({"selected_index": i}, handle)
                with open(run_dir / "record.jsonl", "w") as handle:
                    handle.write(json.dumps({
                        "target_id": f"design-{i}",
                        "complex_target_id": "3PC8_AB",
                        "predictor_id": "chai1_complex",
                        "refolder": "chai1_complex",
                        "signal_source": "chai1_pae_interaction",
                        "label_source": "chai1_lrmsd_to_reference",
                        "pae_interaction": 4.0 + i,
                        "lrmsd": 1.0 + i,
                        "truth": {"correct": i == 0},
                    }) + "\n")

            rc = mod.main([
                "--batch-dir", str(batch),
                "--out", str(out),
                "--report", str(report),
                "--min-records", "2",
            ])

            self.assertEqual(rc, 0)
            with open(out) as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual([row["target_id"] for row in rows], ["design-0", "design-1"])
            with open(report) as handle:
                saved = json.load(handle)
            self.assertTrue(saved["ok"])
            self.assertEqual(saved["status"], "ready")
            self.assertEqual(saved["n_records"], 2)
            self.assertEqual(saved["records_by_predictor"], {"chai1_complex": 2})
            self.assertEqual(saved["source_rows"][1]["selected_index"], 1)

    def test_batch_aggregator_flags_duplicate_keys(self):
        mod = _load("aggregate_chai1_batch_records.py")
        with tempfile.TemporaryDirectory() as d:
            batch = pathlib.Path(d) / "batch"
            out = pathlib.Path(d) / "records.jsonl"
            report = pathlib.Path(d) / "report.json"
            rec = {
                "target_id": "design-0",
                "complex_target_id": "3PC8_AB",
                "predictor_id": "chai1_complex",
                "refolder": "chai1_complex",
                "signal_source": "chai1_pae_interaction",
                "label_source": "chai1_lrmsd_to_reference",
                "pae_interaction": 4.0,
                "lrmsd": 1.0,
                "truth": {"correct": True},
            }
            for i in range(2):
                run_dir = batch / f"index_{i}"
                run_dir.mkdir(parents=True)
                with open(run_dir / "record.jsonl", "w") as handle:
                    handle.write(json.dumps(rec) + "\n")

            rc = mod.main([
                "--batch-dir", str(batch),
                "--out", str(out),
                "--report", str(report),
                "--min-records", "1",
            ])

            self.assertEqual(rc, 0)
            with open(report) as handle:
                saved = json.load(handle)
            self.assertFalse(saved["ok"])
            self.assertEqual(saved["status"], "record_failures")
            self.assertEqual(saved["failures"][0]["kind"], "duplicate_record_key")


if __name__ == "__main__":
    unittest.main()
