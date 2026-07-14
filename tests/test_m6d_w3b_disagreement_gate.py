"""Tests for the prospective W3b matched-predictor disagreement gate."""

import copy
import json
import pathlib
import unittest

from bio_sfm_designer.experiments.m6d_w2c_design_gate import certification_power
from bio_sfm_designer.experiments.m6d_w3_mechanism_adjudication import adjudicate
from bio_sfm_designer.experiments.m6d_w3b_disagreement_design_gate import evaluate as audit_design
from bio_sfm_designer.experiments.m6d_w3b_disagreement_gate import evaluate


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads((ROOT / path).read_text())


def _load_jsonl(path):
    return [json.loads(line) for line in (ROOT / path).read_text().splitlines() if line.strip()]


def _record(target, role, index, boltz_pae, af2_pae, boltz_success, af2_success):
    sequence_hash = f"{index + 1:064x}"
    msa_hash = f"{sum(ord(char) for char in target):064x}"

    def predictor(pae, success):
        return {
            "candidate_sequence_sha256": sequence_hash,
            "label": success,
            "label_threshold": 4.0,
            "lrmsd": 2.0 if success else 8.0,
            "pae_interaction": pae,
            "seed": 0,
            "target_msa_sha256": msa_hash,
            "templates_used": False,
        }

    namespaces = {
        "fit": "w3b-fit-v1",
        "certification": "w3b-cert-v1",
        "held_out_test": "w3b-test-v1",
    }
    return {
        "candidate_id": f"{role}-{target}-{index:03d}",
        "experimental_role": role,
        "predictors": {
            "af2_multimer_colabfold_v1": predictor(af2_pae, af2_success),
            "boltz2_complex": predictor(boltz_pae, boltz_success),
        },
        "seed_namespace": namespaces[role],
        "target_id": target,
    }


def _synthetic_records(manifest):
    rows = []
    for target_row in manifest["targets"]:
        target = target_row["id"]
        role = target_row["experimental_role"]
        if role == "fit":
            for index in range(60):
                good = index < 48
                rows.append(_record(target, role, index, 2.0 if good else 8.0, 2.2 if good else 8.0, good, good))
        elif role == "certification":
            for index in range(150):
                good = index < 110
                rows.append(_record(target, role, index, 2.0 if good else 8.0, 2.2 if good else 8.0, good, good))
        else:
            for index in range(120):
                if index < 70:
                    values = (2.0, 2.2, True, True)
                elif index < 100:
                    values = (2.0, 10.0, True, False)
                else:
                    values = (8.0, 8.0, False, False)
                rows.append(_record(target, role, index, *values))
    return rows


class M6DW3BDisagreementGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = _load("configs/m6d_w3b_disagreement_gate_protocol.json")
        cls.source_manifest = _load("configs/m6d_w3b_fresh_targets.json")
        cls.manifest = copy.deepcopy(cls.source_manifest)
        cls.manifest.update({
            "artifact": "m6d_w3b_execution_target_manifest",
            "status": "w3b_execution_inputs_locked_no_submit",
            "no_submit": True,
            "cayuga_submission_allowed": False,
        })
        for target in cls.manifest["targets"]:
            target["target_msa_sha256"] = f"{sum(ord(char) for char in target['id']):064x}"

    def test_public_design_is_powered_but_remains_no_submit(self):
        predecessor = adjudicate(
            _load("configs/m6d_w3_mechanism_panel_protocol.json"),
            _load_jsonl("tests/fixtures/m6d_w3_mechanism_panel_af2_records.jsonl"),
        )
        report = audit_design(
            self.protocol,
            predecessor,
            self.source_manifest,
            target_manifest_path=str(ROOT / "configs/m6d_w3b_fresh_targets.json"),
        )

        self.assertTrue(report["audit_ok"])
        self.assertTrue(report["design_power_qualified"])
        self.assertFalse(report["inputs_ready"])
        self.assertFalse(report["execution_ready"])
        self.assertTrue(report["no_submit"])
        self.assertFalse(report["cayuga_submission_allowed"])
        self.assertEqual(report["fresh_target_contract"]["role_counts"], {"fit": 3, "certification": 3, "held_out_test": 2})
        self.assertEqual(len(report["fresh_target_contract"]["missing_target_msa_targets"]), 8)
        self.assertEqual(report["certification_power"]["maximum_certifiable_false_accepts"], 10)
        self.assertGreaterEqual(report["certification_power"]["conditional_certification_power"], 0.8)

    def test_100_accepts_are_powered_but_90_are_not(self):
        delta = 0.05 / 6
        self.assertGreaterEqual(certification_power(100, 0.08, 0.2, delta)["conditional_certification_power"], 0.8)
        self.assertLess(certification_power(90, 0.08, 0.2, delta)["conditional_certification_power"], 0.8)

    def test_wrong_multiplicity_fails_the_design_audit(self):
        predecessor = adjudicate(
            _load("configs/m6d_w3_mechanism_panel_protocol.json"),
            _load_jsonl("tests/fixtures/m6d_w3_mechanism_panel_af2_records.jsonl"),
        )
        protocol = copy.deepcopy(self.protocol)
        protocol["locked_scientific_protocol"]["certification_design"]["per_endpoint_delta"] = 0.05 / 3
        report = audit_design(protocol, predecessor, self.manifest)

        self.assertFalse(report["audit_ok"])
        self.assertIn("per_endpoint_delta_mismatch", {row["kind"] for row in report["failures"]})

    def test_full_synthetic_panel_certifies_and_supports_disagreement_gate(self):
        report = evaluate(self.protocol, self.manifest, _synthetic_records(self.manifest))

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w3b_disagreement_gate_certified_and_test_supported")
        self.assertTrue(report["fit"]["rules_frozen"])
        self.assertEqual(report["certification"]["n_certified_targets"], 3)
        self.assertTrue(report["certification"]["panel_certified"])
        self.assertTrue(report["test"]["supported"])
        self.assertAlmostEqual(report["test"]["pooled_coverage_retention"], 0.7)
        self.assertGreaterEqual(report["test"]["pooled_worst_predictor_risk_improvement"], 0.05)
        self.assertTrue(report["can_claim_bounded_disagreement_gate_viability"])
        self.assertFalse(report["can_claim_biological_binder_success"])
        self.assertFalse(report["can_claim_population_level_independent_predictor_robustness"])
        self.assertFalse(report["can_reopen_or_rescue_w2c"])
        self.assertFalse(report["test_can_change_certificate"])

    def test_msa_mismatch_fails_closed(self):
        records = _synthetic_records(self.manifest)
        records[0]["predictors"]["af2_multimer_colabfold_v1"]["target_msa_sha256"] = "f" * 64
        report = evaluate(self.protocol, self.manifest, records)

        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["status"], "w3b_gate_audit_blocked")
        self.assertIn("target_msa_hash_mismatch", {row["kind"] for row in report["failures"]})

    def test_pairwise_matching_but_wrong_manifest_msa_fails_closed(self):
        records = _synthetic_records(self.manifest)
        for predictor in records[0]["predictors"].values():
            predictor["target_msa_sha256"] = "f" * 64
        report = evaluate(self.protocol, self.manifest, records)

        self.assertFalse(report["audit_ok"])
        self.assertIn("target_msa_not_manifest_bound", {row["kind"] for row in report["failures"]})

    def test_missing_execution_manifest_msa_hash_fails_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["targets"][0].pop("target_msa_sha256")
        report = evaluate(self.protocol, manifest, _synthetic_records(self.manifest))

        self.assertFalse(report["audit_ok"])
        self.assertIn("target_manifest_msa_hash_missing", {row["kind"] for row in report["failures"]})

    def test_original_source_manifest_cannot_be_used_for_evaluation(self):
        report = evaluate(self.protocol, self.source_manifest, _synthetic_records(self.manifest))

        self.assertFalse(report["audit_ok"])
        self.assertIn("execution_manifest_contract_invalid", {row["kind"] for row in report["failures"]})

    def test_failed_certification_stops_before_test(self):
        records = _synthetic_records(self.manifest)
        records = [row for row in records if row["experimental_role"] != "held_out_test"]
        for row in records:
            if row["experimental_role"] == "certification" and row["predictors"]["boltz2_complex"]["pae_interaction"] <= 2.0:
                row["predictors"]["boltz2_complex"]["label"] = False
                row["predictors"]["boltz2_complex"]["lrmsd"] = 8.0
        report = evaluate(self.protocol, self.manifest, records)

        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w3b_certification_not_supported_stop_before_test")
        self.assertFalse(report["certification"]["panel_certified"])
        self.assertIsNone(report["test"])
        self.assertFalse(report["can_claim_bounded_disagreement_gate_viability"])


if __name__ == "__main__":
    unittest.main()
