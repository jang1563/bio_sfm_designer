"""M6c report contract: headline, caveats, and alpha frontier stay generated from the fixtures."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from bio_sfm_designer.experiments.m6c_report import build_report, main, render_markdown

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


class M6cReportTests(unittest.TestCase):
    def test_report_locks_headline_and_caveats(self):
        rep = build_report(signal_boot=100, seed_sensitivity_seeds=range(5),
                           scale_projection_seeds=range(5))
        self.assertEqual(rep["dataset"]["n"], 192)
        self.assertEqual(rep["target_alpha"], 0.2)
        self.assertEqual(rep["gate"]["trusted"], 25)
        self.assertAlmostEqual(rep["gate"]["false_accept_rate"], 0.12)
        self.assertAlmostEqual(rep["gate"]["trust_all_false_accept_rate"], 33 / 64)
        frontier = {row["alpha"]: row for row in rep["alpha_frontier"]}
        self.assertTrue(frontier[0.3]["certified"])
        self.assertFalse(frontier[0.2]["certified"])
        self.assertFalse(frontier[0.1]["certified"])
        self.assertGreater(rep["signal"]["pae_stratified_auroc"], 0.9)
        self.assertEqual(rep["design_regime_audit"]["decision"], "keep_balanced_temperature_scale")
        regime_by_temp = {
            row["temperature"]: row for row in rep["design_regime_audit"]["strata"]
        }
        self.assertEqual([regime_by_temp[t]["success"] for t in (0.3, 0.5, 0.7)], [44, 23, 9])
        self.assertEqual(rep["alpha_seed_sensitivity"]["target_certified_count"], 0)
        self.assertEqual(rep["alpha_seed_sensitivity"]["baseline_certified_count"], 5)
        self.assertEqual(rep["scale_projection"]["n_projected_records"], 492)
        self.assertEqual(rep["scale_projection"]["n_new"], 300)
        self.assertFalse(rep["scale_projection"]["certifies_target_alpha"])
        self.assertEqual(rep["scale_projection"]["evidence_level"], "planning_diagnostic")
        self.assertGreater(rep["scale_projection"]["projected_certified_count"], 0)
        supported_claims = {item["id"]: item for item in rep["science_claims"]["supported"]}
        self.assertIn("complex_pae_interaction_signal", supported_claims)
        self.assertIn("alpha_0_3_rcps_certificate", supported_claims)
        blocked_claims = {item["id"]: item for item in rep["science_claims"]["not_yet_supported"]}
        self.assertEqual(blocked_claims["target_alpha_0_2_certificate"]["status"], "not_certified")
        self.assertIn("multi_target_generalization", blocked_claims)
        planning = {item["id"]: item for item in rep["science_claims"]["planning_diagnostics"]}
        self.assertFalse(planning["scale_projection_alpha_0_2"]["evidence"]["certifies_target_alpha"])
        caveats = " ".join(rep["positioning"]["not_claiming"])
        self.assertIn("one target", caveats)
        self.assertIn("one Boltz fold", caveats)

    def test_report_accepts_multiple_record_files_with_dedupe(self):
        rep = build_report([FIXTURE, FIXTURE], signal_boot=25, seed_sensitivity_seeds=range(3),
                           scale_projection_seeds=range(3))
        self.assertEqual(rep["dataset"]["n"], 192)
        self.assertEqual(len(rep["records_paths"]), 2)

    def test_report_infers_non_barstar_target_label(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records_3pc8.jsonl")
            with open(FIXTURE) as src, open(path, "w") as dst:
                for line in src:
                    row = json.loads(line)
                    row["complex_target_id"] = "3PC8_AB"
                    row["target_chain"] = "A"
                    row["binder_chain"] = "B"
                    dst.write(json.dumps(row) + "\n")
            rep = build_report(
                path,
                signal_boot=25,
                seed_sensitivity_seeds=range(3),
                scale_projection_seeds=range(3),
            )
        self.assertEqual(rep["dataset"]["target"], "3PC8_AB")
        supported = {item["id"]: item for item in rep["science_claims"]["supported"]}
        self.assertIn("3PC8_AB", supported["complex_pae_interaction_signal"]["scope"])
        decisive = {item["id"]: item for item in rep["science_claims"]["decisive_next_experiments"]}
        self.assertIn("scale_3PC8_AB_alpha_0_2", decisive)
        text = render_markdown(rep)
        self.assertIn("Dataset: 192 3PC8_AB redesigns", text)
        self.assertNotIn("192 barnase-barstar redesigns", text)

    def test_cli_writes_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            md = os.path.join(d, "m6c.md")
            js = os.path.join(d, "m6c.json")
            with redirect_stdout(StringIO()):
                main([
                    "--signal-boot", "25",
                    "--seed-sensitivity-seeds", "0:3",
                    "--scale-projection-seeds", "0:3",
                    "--out-md", md,
                    "--out-json", js,
                ])
            with open(md) as fh:
                text = fh.read()
            self.assertIn("M6c Complex/Binder Trust-Gate Report", text)
            self.assertIn("alpha=0.3", text)
            self.assertIn("Design Regime Audit", text)
            self.assertIn("Claim Ledger", text)
            self.assertIn("target_alpha_0_2_certificate", text)
            self.assertIn("not a multi-target generalization claim", text)
            self.assertIn("keep the next scale batch balanced", text)
            self.assertIn("Alpha Seed Sensitivity", text)
            self.assertIn("Scale Projection", text)
            self.assertIn("planning_diagnostic", text)
            self.assertIn("certifies target alpha: False", text)
            self.assertIn("single-model", text)
            with open(js) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["report"], "m6c_complex_binder_trust_gate")
            self.assertEqual(rep["target_alpha"], 0.2)
            self.assertEqual(rep["alpha_seed_sensitivity"]["n_seeds"], 3)
            self.assertEqual(rep["scale_projection"]["n_seeds"], 3)
            self.assertIn("science_claims", rep)

    def test_claim_ledger_respects_target_alpha(self):
        rep = build_report(
            alphas=(0.3, 0.2),
            target_alpha=0.3,
            signal_boot=25,
            seed_sensitivity_seeds=range(3),
            scale_projection_seeds=range(3),
        )
        self.assertEqual(rep["target_alpha"], 0.3)
        supported = {item["id"]: item for item in rep["science_claims"]["supported"]}
        self.assertEqual(supported["target_alpha_0_3_certificate"]["status"], "certified")
        self.assertIn("alpha=0.3", supported["target_alpha_0_3_certificate"]["claim"])
        blocked = {item["id"]: item for item in rep["science_claims"]["not_yet_supported"]}
        self.assertNotIn("target_alpha_0_2_certificate", blocked)
        planning = {item["id"]: item for item in rep["science_claims"]["planning_diagnostics"]}
        self.assertIn("scale_projection_alpha_0_3", planning)
        text = render_markdown(rep)
        self.assertIn("target_alpha_0_3_certificate", text)

    def test_report_adds_target_alpha_to_frontier_when_omitted(self):
        rep = build_report(
            alphas=(0.3,),
            target_alpha=0.2,
            signal_boot=25,
            seed_sensitivity_seeds=range(3),
            scale_projection_seeds=range(3),
        )
        frontier = {row["alpha"]: row for row in rep["alpha_frontier"]}
        self.assertIn(0.2, frontier)
        self.assertFalse(frontier[0.2]["certified"])
        blocked = {item["id"]: item for item in rep["science_claims"]["not_yet_supported"]}
        self.assertEqual(
            blocked["target_alpha_0_2_certificate"]["evidence"]["certified"],
            frontier[0.2]["certified"],
        )
        decisive = {item["id"]: item for item in rep["science_claims"]["decisive_next_experiments"]}
        self.assertIn("scale_barnase_barstar_alpha_0_2", decisive)

    def test_render_has_alpha_frontier_table(self):
        text = render_markdown(build_report(signal_boot=25, seed_sensitivity_seeds=range(3),
                                            scale_projection_seeds=range(3)))
        self.assertIn("| 0.30 | True |", text)
        self.assertIn("| 0.20 | False | none |", text)
        self.assertIn("alpha_0_3_rcps_certificate", text)


if __name__ == "__main__":
    unittest.main()
