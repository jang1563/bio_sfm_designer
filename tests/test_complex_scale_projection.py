"""Empirical projection tests for the M6c scale batch."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from bio_sfm_designer.experiments.complex_scale_projection import main, run_projection

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexScaleProjectionTests(unittest.TestCase):
    def test_planned_balanced_batch_makes_alpha_02_plausible(self):
        rep = run_projection([FIXTURE], target_alpha=0.2, n_new=300, seeds=range(20))
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["decision"], "planned_batch_plausible")
        self.assertEqual(rep["n_current_records"], 192)
        self.assertEqual(rep["n_projected_records"], 492)
        self.assertEqual(rep["new_records_by_temperature"], {"0.3": 100, "0.5": 100, "0.7": 100})
        self.assertEqual(rep["evidence_level"], "planning_diagnostic")
        self.assertEqual(rep["claim_scope"], "single_target_bootstrap_projection")
        self.assertFalse(rep["certifies_target_alpha"])
        self.assertEqual(rep["certification_scope"], "none_projection_only")
        self.assertIn("bootstrap", rep["projection_method"])
        self.assertTrue(any("do not certify" in item for item in rep["projection_limitations"]))
        self.assertEqual(rep["current_certified_count"], 0)
        self.assertEqual(rep["projected_certified_count"], 15)
        self.assertGreaterEqual(rep["projected_certified_fraction"], 0.7)
        self.assertGreater(rep["projected_tau"]["median"], 0.0)
        self.assertGreater(rep["projected_trusted"]["median"], 0)
        self.assertLess(rep["projected_false_accept_rate"]["median"], 0.2)

    def test_smaller_batch_is_split_sensitive(self):
        rep = run_projection([FIXTURE], target_alpha=0.2, n_new=180, seeds=range(20))
        self.assertEqual(rep["decision"], "planned_batch_split_sensitive")
        self.assertLess(rep["projected_certified_fraction"], 0.7)
        self.assertGreater(rep["projected_certified_count"], 0)

    def test_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "scale_projection.json")
            with redirect_stdout(StringIO()):
                rep = main(["--records", FIXTURE, "--seeds", "0:5", "--out", out])
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                saved = json.load(fh)
        self.assertEqual(rep["n_projected_records"], 492)
        self.assertEqual(saved["new_records_by_temperature"]["0.3"], 100)


if __name__ == "__main__":
    unittest.main()
