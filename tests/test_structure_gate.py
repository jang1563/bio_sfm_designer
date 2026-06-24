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

    def test_raw_gate_degenerates_and_calibration_is_monomer_scoped(self):
        raw = phase2_calibration_gate(self.records, lam=0.5)
        # binary truth.correct gate degenerates (Boltz-2 right ~95% -> trust-all ~= oracle)
        self.assertEqual(raw["decision"], "do_not_run_signal_not_calibrated")
        mono = [r for r in self.records if r["regime"] == "monomer"]
        cplx = [r for r in self.records if r["regime"] == "complex"]
        cal_mono = calibrated_gate(mono, lam=0.5, correct_lddt=0.9)
        cal_cplx = calibrated_gate(cplx, lam=0.5, correct_lddt=0.9)
        # honest per-regime story: calibrated wrong-risk signal is strong for monomers, weak for complexes
        self.assertGreater(
            cal_mono["signal_validity"]["wrong_risk_auroc"],
            cal_cplx["signal_validity"]["wrong_risk_auroc"],
        )


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

    def test_complexes_never_trusted_monomers_can_be(self):
        gate = TrustGate(lam=0.5)
        pred = PrecomputedStructurePredictor(FIXTURE)
        by_regime = {"monomer": set(), "complex": set()}
        for rec in load_structure_records(FIXTURE):
            p = pred.predict(Candidate(id=str(rec["target_id"]), representation=str(rec["target_id"])))
            by_regime[rec["regime"]].add(gate.route(p, lam=0.5).action)
        # complex is not a calibration-validated regime -> never trusted outright (regime guard)
        self.assertNotIn("trust_sfm", by_regime["complex"], by_regime["complex"])
        self.assertTrue(by_regime["complex"] <= {"verify_assay", "defer"}, by_regime["complex"])
        # monomers (validated) can still be trusted
        self.assertIn("trust_sfm", by_regime["monomer"])


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
        # the regime guard: complexes are never trusted outright -> verify/defer only
        complex_actions = {r["action"] for r in result.rows if r["evidence"]["regime"] == "complex"}
        self.assertNotIn("trust_sfm", complex_actions, complex_actions)
        self.assertTrue(complex_actions <= {"verify_assay", "defer"}, complex_actions)


if __name__ == "__main__":
    unittest.main()
