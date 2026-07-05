"""M6c scale-up helper: merge complex records and sweep alpha without GPU work."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_gate_sweep import load_merged_records, run_sweep

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexGateSweepTests(unittest.TestCase):
    def test_dedupes_identical_record_inputs(self):
        rows = load_merged_records([FIXTURE, FIXTURE])
        self.assertEqual(len(rows), 192)
        self.assertTrue(all(r.get("pae_interaction") is not None for r in rows))

    def test_sweep_locks_current_alpha_frontier(self):
        rep = run_sweep([FIXTURE], alphas=[0.3, 0.2], seed=0)
        self.assertEqual(rep["n_records"], 192)
        self.assertEqual(rep["n_cal"], 128)
        self.assertTrue(rep["label_threshold_audit"]["ok"])
        self.assertEqual(rep["label_threshold_audit"]["record_thresholds"], [4.0])
        by_alpha = {row["alpha"]: row for row in rep["alphas"]}
        self.assertTrue(by_alpha[0.3]["certified"])
        self.assertFalse(by_alpha[0.2]["certified"])
        self.assertEqual(by_alpha[0.3]["trusted"], 25)
        self.assertAlmostEqual(by_alpha[0.3]["false_accept_rate"], 0.12)

    def test_sweep_blocks_row_threshold_mismatch(self):
        rows = load_merged_records([FIXTURE])[:5]
        rows[0] = dict(rows[0])
        rows[0]["lrmsd_threshold"] = 5.0
        rows[0]["truth"] = dict(rows[0]["truth"])
        rows[0]["truth"]["correct"] = float(rows[0]["lrmsd"]) < 5.0
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            with open(path, "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "lrmsd_threshold metadata"):
                run_sweep([path], alphas=[0.3], seed=0)

    def test_missing_pae_fails_fast(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps({
                    "target_id": "bad-0",
                    "regime": "complex",
                    "mean_plddt": 90.0,
                    "lrmsd": 2.0,
                    "lrmsd_threshold": 4.0,
                    "truth": {"correct": True},
                    "interface_aligned": True,
                }) + "\n")
            with self.assertRaisesRegex(ValueError, "missing pae_interaction"):
                load_merged_records([path])


if __name__ == "__main__":
    unittest.main()
