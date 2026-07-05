"""One-command M6c posthoc bundle tests."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_posthoc_bundle import run_bundle
from bio_sfm_designer.experiments.complex_gate_sweep import load_merged_records

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class ComplexPosthocBundleTests(unittest.TestCase):
    def test_bundle_writes_all_artifacts_from_same_records(self):
        with tempfile.TemporaryDirectory() as d:
            rep = run_bundle([FIXTURE], out_dir=d, signal_boot=25,
                             seed_sensitivity_seeds=range(3),
                             scale_projection_seeds=range(3))
            self.assertTrue(rep["ok"])
            for key in ("qc", "sweep", "plan", "decision", "seed_sensitivity", "design_regime_audit",
                        "scale_projection", "report_json", "report_md", "manifest",
                        "project_status_json", "project_status_txt"):
                self.assertTrue(os.path.exists(rep["paths"][key]), key)
            with open(rep["paths"]["manifest"]) as fh:
                manifest = json.load(fh)
            self.assertEqual(manifest["summary"]["n_records"], 192)
            self.assertEqual(manifest["summary"]["certified_alphas"], [0.3])
            self.assertEqual(manifest["summary"]["alpha_decision"], "continue_scale")
            self.assertEqual(manifest["summary"]["estimated_additional_records"], 260)
            self.assertEqual(manifest["summary"]["seed_sensitivity_decision"], "continue_scale_robust")
            self.assertEqual(manifest["summary"]["target_alpha_seed_certified_count"], 0)
            self.assertEqual(manifest["summary"]["target_alpha_seed_n"], 3)
            self.assertEqual(manifest["summary"]["design_regime_decision"], "keep_balanced_temperature_scale")
            self.assertAlmostEqual(manifest["summary"]["temperature_success_rates"]["0.3"], 44 / 64)
            self.assertAlmostEqual(manifest["summary"]["temperature_success_rates"]["0.7"], 9 / 64)
            self.assertEqual(manifest["summary"]["scale_projection_decision"],
                             "planned_batch_strongly_supports_target")
            self.assertEqual(manifest["summary"]["scale_projection_evidence_level"],
                             "planning_diagnostic")
            self.assertEqual(manifest["summary"]["scale_projection_claim_scope"],
                             "single_target_bootstrap_projection")
            self.assertFalse(manifest["summary"]["scale_projection_certifies_target_alpha"])
            self.assertEqual(manifest["summary"]["scale_projection_projected_certified_count"], 3)
            self.assertEqual(manifest["summary"]["scale_projection_n_new"], 300)
            self.assertEqual(manifest["summary"]["science_claims_supported"], [
                "complex_pae_interaction_signal",
                "alpha_0_3_rcps_certificate",
            ])
            self.assertEqual(manifest["summary"]["science_claims_not_yet_supported"], [
                "target_alpha_0_2_certificate",
                "multi_target_generalization",
                "independent_predictor_robustness",
            ])
            self.assertEqual(
                manifest["summary"]["science_claims_planning_diagnostics"],
                ["scale_projection_alpha_0_2"],
            )
            self.assertEqual(manifest["summary"]["science_claims_decisive_next"], [
                "scale_barnase_barstar_alpha_0_2",
                "multi_target_panel",
                "second_predictor",
            ])
            self.assertEqual(manifest["summary"]["next_batch"]["action"], "run_scale_batch")
            self.assertEqual(manifest["summary"]["next_batch"]["recommended_total_candidates"], 300)
            with open(rep["paths"]["seed_sensitivity"]) as fh:
                seed_sensitivity = json.load(fh)
            self.assertEqual(seed_sensitivity["target_certified_count"], 0)
            with open(rep["paths"]["design_regime_audit"]) as fh:
                regime_audit = json.load(fh)
            self.assertEqual(regime_audit["decision"], "keep_balanced_temperature_scale")
            with open(rep["paths"]["scale_projection"]) as fh:
                projection = json.load(fh)
            self.assertEqual(projection["n_projected_records"], 492)
            self.assertFalse(projection["certifies_target_alpha"])
            with open(rep["paths"]["project_status_json"]) as fh:
                status = json.load(fh)
            self.assertEqual(status["workstreams"]["W1_M6c_scale_up"]["status"], "continue_scale")
            self.assertEqual(status["workstreams"]["W2_multi_target_panel"]["status"], "missing")
            self.assertFalse(status["complete"])
            with open(rep["paths"]["project_status_txt"]) as fh:
                self.assertIn("W1_M6c_scale_up: continue_scale", fh.read())
            with open(rep["paths"]["report_md"]) as fh:
                self.assertIn("M6c Complex/Binder Trust-Gate Report", fh.read())

    def test_bundle_stops_after_qc_failure(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.jsonl")
            with open(bad, "w") as fh:
                fh.write(json.dumps({"target_id": "bad", "regime": "complex"}) + "\n")
            out_dir = os.path.join(d, "out")
            rep = run_bundle([bad], out_dir=out_dir, signal_boot=25)
            self.assertFalse(rep["ok"])
            self.assertTrue(os.path.exists(rep["paths"]["qc"]))
            self.assertTrue(os.path.exists(rep["paths"]["decision"]))
            self.assertTrue(os.path.exists(rep["paths"]["project_status_json"]))
            self.assertTrue(os.path.exists(rep["paths"]["project_status_txt"]))
            self.assertFalse(os.path.exists(rep["paths"]["sweep"]))
            self.assertEqual(rep["decision"]["decision"], "qc_failed")
            self.assertEqual(rep["project_status"]["workstreams"]["W1_M6c_scale_up"]["status"], "qc_failed")
            self.assertGreater(rep["qc"]["n_failures"], 0)

    def test_bundle_stops_after_label_threshold_mismatch(self):
        rows = load_merged_records([FIXTURE])[:5]
        rows[0] = dict(rows[0])
        rows[0]["lrmsd_threshold"] = 5.0
        rows[0]["truth"] = dict(rows[0]["truth"])
        rows[0]["truth"]["correct"] = float(rows[0]["lrmsd"]) < 5.0
        with tempfile.TemporaryDirectory() as d:
            records = os.path.join(d, "records.jsonl")
            with open(records, "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            out_dir = os.path.join(d, "out")
            rep = run_bundle([records], out_dir=out_dir, signal_boot=25)

            self.assertFalse(rep["ok"])
            self.assertEqual(rep["decision"]["decision"], "label_threshold_mismatch")
            self.assertTrue(os.path.exists(rep["paths"]["qc"]))
            self.assertTrue(os.path.exists(rep["paths"]["decision"]))
            self.assertFalse(os.path.exists(rep["paths"]["sweep"]))
            self.assertEqual(
                rep["project_status"]["workstreams"]["W1_M6c_scale_up"]["status"],
                "label_threshold_mismatch",
            )

    def test_strict_bundle_accepts_schema_current_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            rep = run_bundle([FIXTURE], out_dir=d, signal_boot=25,
                             seed_sensitivity_seeds=range(3),
                             scale_projection_seeds=range(3),
                             require_complex_target_id=True,
                             require_provenance=True,
                             require_chain_ids=True)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["decision"]["decision"], "continue_scale")
            self.assertEqual(rep["qc"]["n_failures"], 0)
            self.assertTrue(rep["qc"]["require_chain_ids"])
            self.assertTrue(os.path.exists(rep["paths"]["project_status_json"]))
            self.assertTrue(os.path.exists(rep["paths"]["sweep"]))


if __name__ == "__main__":
    unittest.main()
