"""M6c: the trust gate on the COMPLEX regime, routing on the validated pAE_interaction signal. Locks that
the signal enables selective trust -- trusting the most-confident (lowest-pAE) designs is far safer than
trust-all -- on the barstar fixture. At n=192, RCPS certifies alpha=0.3; stricter alpha remains a scale-up
question, and the experiment honestly refuses to certify rather than over-promise when data are insufficient.
"""

import unittest

from bio_sfm_designer.experiments.conformal_complex_gate import run, run_rows


class ConformalComplexGateTests(unittest.TestCase):
    def test_pae_signal_enables_selective_trust(self):
        r = run()
        self.assertGreaterEqual(r["n_cal"] + r["n_test"], 150)
        self.assertTrue(r["label_threshold_audit"]["ok"])
        self.assertGreater(r["auroc_pae"], 0.85)                         # validated interface signal
        # trusting the most-confident (lowest-pAE) quartile is far safer than trust-all
        lowest = r["selective"][0]
        self.assertLess(lowest["false_accept_rate"], r["base_rate_fail"] - 0.3)
        # selective risk rises as you trust a larger (less confident) fraction
        fas = [s["false_accept_rate"] for s in r["selective"]]
        self.assertLessEqual(fas[0], fas[-1])

    def test_conformal_certifies_and_bounds_false_accept(self):
        # Any certificate must come from an independent certification split.
        r = run()
        self.assertEqual(r["n_fit"] + r["n_certification"], r["n_cal"])
        self.assertEqual(r["certificate"]["method"], "split_learn_then_test_hoeffding")
        if r["tau"] is not None:
            self.assertTrue(r["certificate"]["certified"])
            far = r["conformal"]["false_accept_rate"]
            self.assertIsNotNone(far)
            self.assertLess(far, r["trust_all"]["false_accept_rate"])
        else:
            self.assertFalse(r["certificate"]["certified"])

    def test_exact_bound_is_explicit_and_does_not_change_default(self):
        exact = run(certification_bound="clopper_pearson")
        self.assertEqual(exact["certification_schema"], "split_ltt_exact_v1")
        self.assertEqual(exact["certification_bound"], "clopper_pearson")
        self.assertEqual(
            exact["certificate"]["method"],
            "split_learn_then_test_clopper_pearson",
        )

    def test_missing_pae_fails_fast(self):
        rows = [{
            "target_id": "bad-0",
            "regime": "complex",
            "mean_plddt": 90.0,
            "lrmsd": 2.0,
            "lrmsd_threshold": 4.0,
            "truth": {"correct": True},
            "interface_aligned": True,
        }]
        with self.assertRaisesRegex(ValueError, "missing pae_interaction"):
            run_rows(rows, n_cal=0)

    def test_row_threshold_mismatch_fails_fast(self):
        rows = [
            {
                "target_id": f"toy-{i}",
                "regime": "complex",
                "mean_plddt": 90.0,
                "pae_interaction": float(i + 1),
                "lrmsd": 2.0,
                "lrmsd_threshold": 4.0,
                "truth": {"correct": True},
                "interface_aligned": True,
            }
            for i in range(4)
        ]
        rows[0]["lrmsd_threshold"] = 5.0
        with self.assertRaisesRegex(ValueError, "lrmsd_threshold metadata"):
            run_rows(rows, n_cal=2)


if __name__ == "__main__":
    unittest.main()
