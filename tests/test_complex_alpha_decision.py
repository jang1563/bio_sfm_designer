"""Decision tests for the M6c alpha-tightening loop."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_alpha_decision import run_decision
from bio_sfm_designer.experiments.complex_gate_sweep import load_merged_records

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexAlphaDecisionTests(unittest.TestCase):
    def test_current_fixture_continues_for_alpha_02(self):
        rep = run_decision([FIXTURE], target_alpha=0.2, seed=0)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["decision"], "continue_scale")
        self.assertEqual(rep["n_records"], 192)
        self.assertEqual(rep["n_cal"], 128)
        self.assertTrue(rep["label_threshold_audit"]["ok"])
        self.assertEqual(rep["target_plan"]["estimated_additional_records"], 260)
        self.assertEqual(rep["next_batch"]["action"], "run_scale_batch")
        self.assertEqual(rep["next_batch"]["num_seq_per_temperature"], 100)
        self.assertEqual(rep["next_batch"]["recommended_total_candidates"], 300)
        self.assertEqual(rep["next_batch"]["temperatures"], [0.3, 0.5, 0.7])

    def test_next_batch_can_be_planned_for_one_temperature(self):
        rep = run_decision([FIXTURE], target_alpha=0.2, seed=0,
                           temperatures=[0.3], batch_round_to=20)
        self.assertEqual(rep["decision"], "continue_scale")
        self.assertEqual(rep["next_batch"]["num_seq_per_temperature"], 260)
        self.assertEqual(rep["next_batch"]["recommended_total_candidates"], 260)

    def test_current_fixture_stops_for_alpha_03(self):
        rep = run_decision([FIXTURE], target_alpha=0.3, seed=0)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["decision"], "stop_certified")
        self.assertIn(0.3, rep["certified_alphas"])
        self.assertEqual(rep["estimated_additional_records"], 0)
        self.assertEqual(rep["next_batch"]["action"], "none")
        self.assertEqual(rep["next_batch"]["recommended_total_candidates"], 0)

    def test_qc_failure_blocks_decision(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.jsonl")
            with open(bad, "w") as fh:
                fh.write(json.dumps({"target_id": "bad", "regime": "complex"}) + "\n")
            rep = run_decision([bad], target_alpha=0.2)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["decision"], "qc_failed")
        self.assertEqual(rep["next_batch"]["action"], "fix_qc")
        self.assertGreater(rep["qc"]["n_failures"], 0)

    def test_label_threshold_mismatch_blocks_alpha_decision(self):
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
            rep = run_decision([path], target_alpha=0.2)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["decision"], "label_threshold_mismatch")
        self.assertEqual(rep["next_batch"]["action"], "fix_label_threshold")
        self.assertFalse(rep["label_threshold_audit"]["ok"])
        self.assertEqual(rep["label_threshold_audit"]["record_thresholds"], [4.0, 5.0])

    def test_strict_qc_allows_schema_current_fixture(self):
        rep = run_decision([FIXTURE], target_alpha=0.2,
                           require_complex_target_id=True,
                           require_provenance=True,
                           require_chain_ids=True)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["decision"], "continue_scale")
        self.assertEqual(rep["qc"]["n_failures"], 0)
        self.assertTrue(rep["qc"]["require_chain_ids"])
        self.assertEqual(rep["next_batch"]["action"], "run_scale_batch")


if __name__ == "__main__":
    unittest.main()
