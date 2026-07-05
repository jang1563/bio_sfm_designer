"""Tests for the no-submit W3 predictor/protocol selection card."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_predictor_selection_card import (
    build_selection_card,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _third_contract(*, execution_ready=False, wrapper=False, claim=False):
    return {
        "_path": "/tmp/w3_third.json",
        "status": "w3_third_predictor_contract_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": execution_ready,
        "command_wrapper_emitted": wrapper,
        "can_claim_independent_predictor_robustness_now": claim,
        "predictor_selection_contract": {
            "route": "third_independent_predictor_or_protocol",
            "source_predictors_to_adjudicate": ["boltz2_complex", "chai1_complex"],
            "disallowed_as_independent_closure": [
                "boltz2_complex",
                "chai1_complex",
                "same_no_msa_chai1_protocol",
            ],
            "required_selection_fields": [
                "predictor_or_protocol_id",
                "model_or_protocol_family",
                "version",
                "msa_policy",
                "template_policy",
                "runtime_environment",
                "label_source",
                "signal_source",
                "approval_gate",
            ],
        },
        "challenge_panel_contract": {
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "target_ids": ["d1", "c1"],
        },
        "output_contract": {
            "planned_jsonl": "results/future.jsonl",
            "required_n_rows": 2,
            "required_result_schema": ["target_id", "predictor_or_protocol_id", "label", "provenance"],
        },
        "future_artifacts_required": [
            "selected_predictor_protocol_card",
            "execution_input_manifest",
            "approval_gated_command_wrapper",
        ],
    }


class M6DW3PredictorSelectionCardTests(unittest.TestCase):
    def test_build_selection_card_selects_af2_multimer_without_execution(self):
        rep = build_selection_card(_third_contract(), report_date="2026-07-05")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_predictor_selection_card_ready_no_submit")
        self.assertEqual(
            rep["selected_predictor_protocol"]["predictor_or_protocol_id"],
            "af2_multimer_colabfold_v1",
        )
        self.assertFalse(rep["runtime_ready"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertIn("approval_gate", rep["selected_predictor_protocol"]["required_fields_satisfied"])
        self.assertIn("execution_input_manifest", rep["future_artifacts_required"])
        self.assertEqual(rep["challenge_panel_contract"]["target_ids"], ["d1", "c1"])

    def test_blocks_execution_or_claim_leak_from_third_contract(self):
        rep = build_selection_card(_third_contract(execution_ready=True, wrapper=True, claim=True))

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_predictor_selection_card_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_selection_third_contract_execution_ready_drift", kinds)
        self.assertIn("w3_selection_third_contract_wrapper_emitted_drift", kinds)
        self.assertIn("w3_selection_third_contract_claim_leak", kinds)

    def test_render_markdown_names_runtime_probe_and_rejected_esmfold(self):
        md = render_markdown(build_selection_card(_third_contract()))

        self.assertIn("M6d W3 Predictor Selection Card", md)
        self.assertIn("af2_multimer_colabfold_v1", md)
        self.assertIn("Runtime Probe Required", md)
        self.assertIn("esmfold_single_chain", md)
        self.assertIn("emits no execution inputs or command wrapper", md)

    def test_cli_writes_selection_card_files(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "third.json")
            out_json = os.path.join(d, "selection.json")
            out_md = os.path.join(d, "selection.md")
            _write_json(contract, _third_contract())

            rc = main([
                "--w3-third-predictor-contract", contract,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_predictor_selection_card_ready_no_submit")
            self.assertEqual(rep["selected_predictor_protocol"]["predictor_or_protocol_id"], "af2_multimer_colabfold_v1")
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
