import os
import unittest
from pathlib import Path

from bio_sfm_trust import calibrated_gate, phase2_calibration_gate

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.predict.structure import (
    PrecomputedStructurePredictor,
    StructureRecordGenerator,
    load_structure_records,
)
from bio_sfm_designer.trust import TrustGate
from bio_sfm_designer.types import Candidate

FIXTURE = str(Path(__file__).parent / "fixtures" / "phase2_targets_records.jsonl")


class StructureFixtureTests(unittest.TestCase):
    def setUp(self):
        self.records = load_structure_records(FIXTURE)

    def test_regime_split(self):
        self.assertEqual(len(self.records), 80)
        self.assertEqual(sum(1 for r in self.records if r["regime"] == "monomer"), 40)
        self.assertEqual(sum(1 for r in self.records if r["regime"] == "complex"), 40)

    def test_reproduces_calibration_gap(self):
        # the audit headline + McGuffin benchmark: pLDDT calibrated for monomers, not complexes
        gate = phase2_calibration_gate(self.records, lam=0.5)
        rc = gate["regime_calibration"]
        mono = rc["monomer"]["pearson_plddt_vs_quality"]
        comp = rc["complex"]["pearson_plddt_vs_quality"]
        self.assertGreater(mono, 0.8)          # ~0.89
        self.assertLess(comp, 0.4)             # ~0.16
        self.assertGreater(rc["monomer_minus_complex"], 0.5)

    def test_raw_gate_degenerates_but_calibrated_gate_fires(self):
        raw = phase2_calibration_gate(self.records, lam=0.5)
        cal = calibrated_gate(self.records, lam=0.5, correct_lddt=0.9)
        # binary truth.correct gate degenerates (Boltz-2 right ~95% -> trust-all ~= oracle)
        self.assertEqual(raw["decision"], "do_not_run_signal_not_calibrated")
        # the LOO-isotonic gate at the stricter lDDT cutoff is eligible
        self.assertEqual(cal["decision"], "eligible_for_phase2_interface_pilot")


class StructurePredictorTests(unittest.TestCase):
    def test_predictor_serves_records_with_hidden_truth(self):
        pred = PrecomputedStructurePredictor(FIXTURE)
        rec = load_structure_records(FIXTURE)[0]
        p = pred.predict(Candidate(id=str(rec["target_id"]), representation=str(rec["target_id"])))
        self.assertEqual(p.candidate_id, str(rec["target_id"]))
        self.assertAlmostEqual(p.raw_conf, rec["mean_plddt"] / 100.0, places=4)
        self.assertIn("quality", p.truth)
        # visible value must not equal the hidden lDDT (no leakage)
        self.assertNotEqual(p.value, p.truth["quality"])

    def test_gate_routes_trust_or_verify_on_structure(self):
        gate = TrustGate(lam=0.5)
        pred = PrecomputedStructurePredictor(FIXTURE)
        actions = set()
        for rec in load_structure_records(FIXTURE):
            p = pred.predict(Candidate(id=str(rec["target_id"]), representation=str(rec["target_id"])))
            actions.add(gate.route(p, lam=0.5).action)
        # no numeric baseline + has_baseline=True -> only trust/verify on this substrate
        self.assertTrue(actions <= {"trust_sfm", "verify_assay"}, actions)
        self.assertIn("trust_sfm", actions)


class StructureCampaignTests(unittest.TestCase):
    def test_campaign_runs_on_real_records(self):
        spec = ObjectiveSpec(
            target="protein-structure trust-routing evaluation on post-cutoff PDB targets",
            objective="structure_quality",
            lam=0.5,
            rounds=1,
            candidates_per_round=80,
            assay_budget=80,
        )
        controller = DBTLController(
            generator=StructureRecordGenerator(FIXTURE),
            predictor=PrecomputedStructurePredictor(FIXTURE),
        )
        result = controller.run(spec)
        self.assertTrue(result.allowed)
        self.assertEqual(result.rounds_run, 1)
        self.assertEqual(len(result.rows), 80)
        seen = {row["action"] for row in result.rows}
        self.assertTrue(seen <= {"trust_sfm", "verify_assay"}, seen)


if __name__ == "__main__":
    unittest.main()
