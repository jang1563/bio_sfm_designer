"""Tests for the no-submit W3 third-predictor execution contract."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_third_predictor_contract import (
    build_contract,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _next_protocol(*, claim=False):
    return {
        "_path": "/tmp/w3_next.json",
        "status": "w3_next_protocol_ready_no_spend",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "can_claim_independent_predictor_robustness_now": claim,
        "adjudication_set_contract": {
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
        },
        "recommended_next_routes": [
            {"rank": 1, "route": "third_independent_predictor_or_protocol"},
            {"rank": 2, "route": "stronger_chai_msa_template_protocol"},
        ],
        "decision_contract": {
            "future_result_schema": [
                "target_id",
                "predictor_or_protocol_id",
                "label",
                "label_threshold",
                "complex_target_id",
                "target_chain",
                "binder_chain",
                "signal_source",
                "label_source",
                "provenance",
            ],
        },
    }


def _challenge_manifest(*, execution_ready=False, claim=False):
    return {
        "_path": "/tmp/w3_challenge.json",
        "status": "w3_challenge_manifest_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": execution_ready,
        "can_claim_independent_predictor_robustness_now": claim,
        "recommended_next_route": "third_independent_predictor_or_protocol",
        "source_adjudication_jsonl": "/tmp/adjudication.jsonl",
        "source_adjudication_sha256": "a" * 64,
        "challenge_panel": {
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "target_ids": ["d1", "c1"],
        },
        "decision_contract": {
            "stage": "challenge_panel_adjudication_before_full_w3_claim",
            "discordant_alignment_threshold": 1,
            "control_consistency_threshold": 1,
            "future_result_schema": [
                "target_id",
                "predictor_or_protocol_id",
                "label",
                "label_threshold",
                "complex_target_id",
                "target_chain",
                "binder_chain",
                "signal_source",
                "label_source",
                "provenance",
            ],
            "outcomes": [],
            "threshold_note": "challenge only",
        },
        "rows": [
            {
                "challenge_rank": 1,
                "target_id": "d1",
                "adjudication_role": "discordant_boltz_chai_label",
                "complex_target_id": "3PC8_AB",
                "strict_target_identity": True,
                "strict_label_threshold": True,
                "source_labels": {
                    "predictor_a": "boltz2_complex",
                    "label_a": False,
                    "predictor_b": "chai1_complex",
                    "label_b": True,
                },
                "source_label_metrics": {"lrmsd_threshold_a": 4.0, "lrmsd_threshold_b": 4.0},
            },
            {
                "challenge_rank": 2,
                "target_id": "c1",
                "adjudication_role": "concordant_success_control",
                "complex_target_id": "3PC8_AB",
                "strict_target_identity": True,
                "strict_label_threshold": True,
                "source_labels": {
                    "predictor_a": "boltz2_complex",
                    "label_a": True,
                    "predictor_b": "chai1_complex",
                    "label_b": True,
                },
                "source_label_metrics": {"lrmsd_threshold_a": 4.0, "lrmsd_threshold_b": 4.0},
            },
        ],
    }


class M6DW3ThirdPredictorContractTests(unittest.TestCase):
    def test_build_contract_pins_inputs_and_stays_no_submit(self):
        rep = build_contract(
            _next_protocol(),
            _challenge_manifest(),
            planned_result_jsonl="results/future.jsonl",
            report_date="2026-07-05",
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_third_predictor_contract_ready_no_submit")
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(rep["challenge_panel_contract"]["n_rows"], 2)
        self.assertEqual(rep["input_contract"]["target_ids"], ["d1", "c1"])
        self.assertEqual(rep["output_contract"]["planned_jsonl"], "results/future.jsonl")
        self.assertIn("approval_gated_command_wrapper", rep["future_artifacts_required"])
        self.assertIn("boltz2_complex", rep["predictor_selection_contract"]["source_predictors_to_adjudicate"])

    def test_blocks_execution_ready_or_claim_leak(self):
        rep = build_contract(
            _next_protocol(claim=True),
            _challenge_manifest(execution_ready=True, claim=True),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_third_predictor_contract_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_third_contract_next_protocol_claim_leak", kinds)
        self.assertIn("w3_third_contract_challenge_execution_ready_drift", kinds)
        self.assertIn("w3_third_contract_challenge_claim_leak", kinds)

    def test_blocks_count_drift(self):
        challenge = _challenge_manifest()
        challenge["challenge_panel"]["counts_by_role"]["discordant_boltz_chai_label"] = 2

        rep = build_contract(_next_protocol(), challenge)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_third_contract_role_count_mismatch", kinds)

    def test_render_markdown_names_no_command_wrapper(self):
        md = render_markdown(build_contract(_next_protocol(), _challenge_manifest()))

        self.assertIn("M6d W3 Third-Predictor Contract", md)
        self.assertIn("no-submit, no-API, no-GPU", md)
        self.assertIn("emits no command wrapper", md)
        self.assertIn("approval-gated command wrapper is not emitted", md)

    def test_cli_writes_contract_files(self):
        with tempfile.TemporaryDirectory() as d:
            next_protocol = os.path.join(d, "next.json")
            challenge = os.path.join(d, "challenge.json")
            out_json = os.path.join(d, "contract.json")
            out_md = os.path.join(d, "contract.md")
            _write_json(next_protocol, _next_protocol())
            _write_json(challenge, _challenge_manifest())

            rc = main([
                "--w3-next-protocol", next_protocol,
                "--w3-challenge-manifest", challenge,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_third_predictor_contract_ready_no_submit")
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
