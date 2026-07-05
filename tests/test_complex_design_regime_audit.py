"""Design-temperature audit tests for the M6c complex records."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from bio_sfm_designer.experiments.complex_design_regime_audit import (
    infer_design_temperature,
    main,
    run_audit,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexDesignRegimeAuditTests(unittest.TestCase):
    def test_infers_temperature_from_current_and_batch_tags(self):
        self.assertAlmostEqual(infer_design_temperature({"target_id": "binder_t03-mpnnX-1BRS-0"}), 0.3)
        self.assertAlmostEqual(infer_design_temperature({"target_id": "binder2_t07-mpnnX-1BRS-0"}), 0.7)
        self.assertAlmostEqual(infer_design_temperature({"target_id": "design_t10-5L33-0"}), 1.0)
        self.assertAlmostEqual(infer_design_temperature({"target_id": "x_t030-y"}), 0.3)
        self.assertAlmostEqual(infer_design_temperature({"design_temperature": "0.5"}), 0.5)
        self.assertIsNone(infer_design_temperature({"target_id": "no_temp"}))

    def test_audit_locks_temperature_gradient_and_signal(self):
        rep = run_audit([FIXTURE])
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["decision"], "keep_balanced_temperature_scale")
        self.assertEqual(rep["n_records"], 192)
        self.assertEqual(rep["n_strata"], 3)
        self.assertTrue(rep["all_strata_mixed"])
        self.assertTrue(rep["all_pae_informative"])
        self.assertTrue(rep["success_decreases_with_temperature"])
        self.assertTrue(rep["pae_increases_with_temperature"])
        by_temp = {row["temperature"]: row for row in rep["strata"]}
        self.assertEqual(sorted(by_temp), [0.3, 0.5, 0.7])
        self.assertEqual([by_temp[t]["n"] for t in (0.3, 0.5, 0.7)], [64, 64, 64])
        self.assertEqual([by_temp[t]["success"] for t in (0.3, 0.5, 0.7)], [44, 23, 9])
        self.assertGreater(by_temp[0.3]["pae_auroc_within_stratum"], 0.9)
        self.assertGreater(by_temp[0.5]["pae_auroc_within_stratum"], 0.85)
        self.assertGreater(by_temp[0.7]["pae_auroc_within_stratum"], 0.9)

    def test_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "regime_audit.json")
            with redirect_stdout(StringIO()):
                rep = main(["--records", FIXTURE, "--out", out])
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                saved = json.load(fh)
        self.assertEqual(rep["decision"], "keep_balanced_temperature_scale")
        self.assertEqual(saved["strata"][0]["temperature"], 0.3)


if __name__ == "__main__":
    unittest.main()
