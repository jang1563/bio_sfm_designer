"""Tests for the no-submit W3 runtime-probe plan."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_runtime_probe_plan import (
    build_runtime_probe_plan,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _selection_card(*, runtime_ready=False, execution_ready=False, claim=False):
    return {
        "_path": "/tmp/w3_selection.json",
        "artifact": "m6d_w3_predictor_selection_card",
        "status": "w3_predictor_selection_card_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "runtime_ready": runtime_ready,
        "execution_ready": execution_ready,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "selected_predictor_protocol": {
            "predictor_or_protocol_id": "af2_multimer_colabfold_v1",
            "model_or_protocol_family": "AlphaFold2-Multimer via ColabFold/localcolabfold",
            "version": "runtime_version_pending_cayuga_probe",
            "msa_policy": "paired/unpaired MMseqs2 MSA required",
            "template_policy": "templates disabled unless predeclared",
            "runtime_environment": "Cayuga colabfold/localcolabfold environment pending install/probe",
            "label_source": "af2_multimer_lrmsd_to_reference",
            "signal_source": "af2_multimer_pae_interaction_or_iptm",
            "approval_gate": "BIO_SFM_APPROVE_W3_THIRD_PREDICTOR=approve-w3-third-predictor-submit",
            "route": "third_independent_predictor_or_protocol",
            "selection_status": "selected_pending_runtime_probe",
            "required_fields_satisfied": [
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
        "runtime_probe_required": {
            "required": True,
            "checks": [
                "colabfold_batch --help is available in the selected env",
                "GPU/CUDA/JAX compatibility is verified on the target partition",
                "MSA policy is resolved to local database, precomputed MSA, or explicitly approved server query",
                "a dry-run wrapper can enumerate 18 inputs without submitting jobs",
            ],
        },
        "future_artifacts_required": [
            "execution_input_manifest",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
        ],
        "execution_blockers": [
            "runtime has not been probed",
            "approval-gated command wrapper is not emitted here",
        ],
    }


class M6DW3RuntimeProbePlanTests(unittest.TestCase):
    def test_build_runtime_probe_plan_pins_checks_without_execution(self):
        rep = build_runtime_probe_plan(_selection_card(), report_date="2026-07-05")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_probe_plan_ready_no_submit")
        self.assertEqual(rep["selected_predictor_or_protocol_id"], "af2_multimer_colabfold_v1")
        self.assertFalse(rep["probe_executed"])
        self.assertFalse(rep["runtime_ready"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["approval_token_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertIn("runtime_probe_report", rep["future_artifacts_required"])
        kinds = {check["kind"] for check in rep["probe_contract"]["checks"]}
        self.assertIn("cli_help", kinds)
        self.assertIn("gpu_stack", kinds)
        self.assertIn("msa_policy", kinds)
        self.assertIn("dry_run_enumeration", kinds)
        self.assertEqual(rep["probe_contract"]["target_ids"], ["d1", "c1"])

    def test_blocks_selection_runtime_or_execution_leak(self):
        rep = build_runtime_probe_plan(
            _selection_card(runtime_ready=True, execution_ready=True, claim=True),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_probe_plan_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_probe_selection_runtime_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_selection_execution_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_selection_claim_leak", kinds)

    def test_render_markdown_names_no_submit_boundary(self):
        md = render_markdown(build_runtime_probe_plan(_selection_card()))

        self.assertIn("M6d W3 Runtime Probe Plan", md)
        self.assertIn("no-submit, no-API, no-GPU", md)
        self.assertIn("No runtime probe was executed", md)
        self.assertIn("cli_help", md)
        self.assertIn("public MMseqs2/API/server queries stay disabled", md)

    def test_cli_writes_plan_files(self):
        with tempfile.TemporaryDirectory() as d:
            selection = os.path.join(d, "selection.json")
            out_json = os.path.join(d, "runtime_probe_plan.json")
            out_md = os.path.join(d, "runtime_probe_plan.md")
            _write_json(selection, _selection_card())

            rc = main([
                "--w3-predictor-selection-card", selection,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_runtime_probe_plan_ready_no_submit")
            self.assertEqual(rep["source_predictor_selection_card"], os.path.abspath(selection))
            self.assertIsNotNone(rep["source_predictor_selection_card_sha256"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
