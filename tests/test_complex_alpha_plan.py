"""Scale-planning tests for tightening the M6c conformal alpha frontier."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_gate_sweep import load_merged_records
from bio_sfm_designer.experiments.complex_alpha_plan import run_plan

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexAlphaPlanTests(unittest.TestCase):
    def test_plan_explains_current_alpha_frontier(self):
        rep = run_plan([FIXTURE], alphas=[0.3, 0.2, 0.1], seed=0)
        self.assertEqual(rep["n_records"], 192)
        self.assertEqual(rep["n_cal"], 128)
        self.assertTrue(rep["label_threshold_audit"]["ok"])
        by_alpha = {row["alpha"]: row for row in rep["plans"]}
        self.assertTrue(by_alpha[0.3]["certified"])
        self.assertFalse(by_alpha[0.2]["certified"])
        self.assertFalse(by_alpha[0.1]["certified"])
        self.assertEqual(by_alpha[0.2]["required_accepted_for_same_rate"], 68)
        self.assertGreater(by_alpha[0.2]["estimated_required_total_records"], rep["n_records"])
        self.assertGreater(by_alpha[0.1]["estimated_required_total_records"],
                           by_alpha[0.2]["estimated_required_total_records"])

    def test_plan_dedupes_record_inputs(self):
        rep = run_plan([FIXTURE, FIXTURE], alphas=[0.2], seed=0)
        self.assertEqual(rep["n_records"], 192)
        self.assertEqual(rep["plans"][0]["alpha"], 0.2)

    def test_plan_blocks_row_threshold_mismatch(self):
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
                run_plan([path], alphas=[0.2], seed=0)


if __name__ == "__main__":
    unittest.main()
