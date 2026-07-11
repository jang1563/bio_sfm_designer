"""Split-seed robustness tests for the M6c complex alpha frontier."""

import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_alpha_seed_sensitivity import main, run_sensitivity

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexAlphaSeedSensitivityTests(unittest.TestCase):
    def test_target_alpha_failure_is_robust_for_initial_splits(self):
        rep = run_sensitivity([FIXTURE], target_alpha=0.2, baseline_alpha=0.3, seeds=range(5))
        self.assertEqual(rep["n_seeds"], 5)
        self.assertEqual(rep["target_certified_count"], 0)
        self.assertEqual(rep["baseline_certified_count"], 0)
        self.assertEqual(rep["decision"], "continue_scale_robust")
        self.assertGreater(rep["target_estimated_additional_records"]["median"], 0)
        self.assertEqual(len(rep["per_seed"]), 5)
        self.assertTrue(all(not row["target_certified"] for row in rep["per_seed"]))

    def test_cli_writes_json_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "seed_sensitivity.json")
            rep = main([
                "--records", FIXTURE,
                "--target-alpha", "0.2",
                "--baseline-alpha", "0.3",
                "--seeds", "0:3",
                "--out", out,
            ])
            self.assertTrue(os.path.exists(out))
        self.assertEqual(rep["n_seeds"], 3)
        self.assertEqual(rep["target_certified_count"], 0)
        self.assertEqual(rep["baseline_certified_count"], 0)


if __name__ == "__main__":
    unittest.main()
