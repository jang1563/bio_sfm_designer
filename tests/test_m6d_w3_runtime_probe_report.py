"""Tests for the no-submit W3 runtime-probe report."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_runtime_probe_report import (
    build_runtime_probe_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _runtime_probe_plan(*, runtime_ready=False, probe_executed=False, claim=False):
    return {
        "_path": "/tmp/runtime_probe_plan.json",
        "artifact": "m6d_w3_runtime_probe_plan",
        "status": "w3_runtime_probe_plan_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "runtime_probe_ready": False,
        "runtime_ready": runtime_ready,
        "probe_executed": probe_executed,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "selected_model_or_protocol_family": "AlphaFold2-Multimer via ColabFold/localcolabfold",
        "probe_contract": {
            "candidate_runtime_locations": [
                "$HOME/localcolabfold/.pixi/envs/default/bin/colabfold_batch",
                "$HOME/.conda/envs/colabfold/bin/colabfold_batch",
                "colabfold_batch on PATH",
            ],
            "checks": [
                {"kind": "env_discovery", "status": "planned_not_executed"},
                {"kind": "cli_help", "status": "planned_not_executed"},
                {"kind": "gpu_stack", "status": "planned_not_executed"},
                {"kind": "msa_policy", "status": "planned_not_executed"},
                {"kind": "dry_run_enumeration", "status": "planned_not_executed"},
            ],
            "runtime_surface": "Cayuga AF2-Multimer/ColabFold runtime probe",
            "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
            "target_count": 2,
            "target_ids": ["d1", "c1"],
            "target_partition_candidates": ["scu-gpu"],
        },
        "future_artifacts_required": [
            "runtime_probe_report",
            "execution_input_manifest",
            "approval_gated_command_wrapper",
        ],
    }


def _ready_observed_checks():
    return [
        {"kind": "env_discovery", "ran": True, "ok": True, "selected_cli": "/opt/colabfold/bin/colabfold_batch"},
        {"kind": "cli_help", "ran": True, "ok": True, "returncode": 0},
        {"kind": "gpu_stack", "ran": True, "ok": True, "jax_backend": "gpu"},
        {"kind": "msa_policy", "ran": True, "ok": True, "public_server_disabled": True},
        {"kind": "dry_run_enumeration", "ran": True, "ok": True, "n_inputs": 2, "submitted_jobs": 0},
    ]


class M6DW3RuntimeProbeReportTests(unittest.TestCase):
    def test_local_static_report_records_not_runtime_ready_without_execution_inputs(self):
        rep = build_runtime_probe_report(_runtime_probe_plan(), report_date="2026-07-05")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit")
        self.assertTrue(rep["probe_executed"])
        self.assertFalse(rep["cayuga_probe_executed"])
        self.assertFalse(rep["runtime_ready"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["approval_token_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        kinds = {check["kind"] for check in rep["observed_checks"]}
        self.assertEqual(
            kinds,
            {"env_discovery", "cli_help", "gpu_stack", "msa_policy", "dry_run_enumeration"},
        )
        self.assertIn("probe surface is not the target Cayuga GPU no-submit surface", rep["readiness_blockers"])

    def test_target_surface_all_checks_ready_still_no_execution_or_claim(self):
        rep = build_runtime_probe_report(
            _runtime_probe_plan(),
            probe_surface="cayuga_gpu_no_submit",
            observed_checks=_ready_observed_checks(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_probe_report_runtime_ready_no_submit")
        self.assertTrue(rep["runtime_ready"])
        self.assertTrue(rep["cayuga_probe_executed"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertIn("execution_input_manifest", rep["future_artifacts_required"])

    def test_target_surface_failed_checks_recommend_runtime_repair(self):
        checks = _ready_observed_checks()
        checks[0] = {"kind": "env_discovery", "ran": True, "ok": False, "selected_cli": None}
        checks[1] = {"kind": "cli_help", "ran": False, "ok": False}
        checks[2] = {"kind": "gpu_stack", "ran": True, "ok": False}

        rep = build_runtime_probe_report(
            _runtime_probe_plan(),
            probe_surface="cayuga_gpu_no_submit",
            observed_checks=checks,
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["runtime_ready"])
        self.assertIn("repair the Cayuga ColabFold/JAX/GPU runtime blockers", rep["recommended_next_action"])

    def test_blocks_plan_runtime_or_claim_leak(self):
        rep = build_runtime_probe_report(
            _runtime_probe_plan(runtime_ready=True, probe_executed=True, claim=True),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_probe_report_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_probe_report_plan_runtime_ready_drift", kinds)
        self.assertIn("w3_runtime_probe_report_plan_probe_executed_drift", kinds)
        self.assertIn("w3_runtime_probe_report_plan_claim_leak", kinds)

    def test_render_markdown_names_no_submit_boundary(self):
        md = render_markdown(build_runtime_probe_report(_runtime_probe_plan()))

        self.assertIn("M6d W3 Runtime Probe Report", md)
        self.assertIn("no prediction execution", md)
        self.assertIn("Runtime ready: `False`", md)
        self.assertIn("Readiness Blockers", md)

    def test_cli_writes_report_files(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "runtime_probe_plan.json")
            out_json = os.path.join(d, "runtime_probe_report.json")
            out_md = os.path.join(d, "runtime_probe_report.md")
            _write_json(plan, _runtime_probe_plan())

            rc = main([
                "--w3-runtime-probe-plan", plan,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit")
            self.assertEqual(rep["source_runtime_probe_plan"], os.path.abspath(plan))
            self.assertIsNotNone(rep["source_runtime_probe_plan_sha256"])
            self.assertTrue(os.path.exists(out_md))

    def test_cli_consumes_observed_checks_json_for_target_surface(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "runtime_probe_plan.json")
            checks = os.path.join(d, "observed_checks.json")
            out_json = os.path.join(d, "runtime_probe_report.json")
            out_md = os.path.join(d, "runtime_probe_report.md")
            _write_json(plan, _runtime_probe_plan())
            _write_json(checks, {"observed_checks": _ready_observed_checks()})

            rc = main([
                "--w3-runtime-probe-plan", plan,
                "--probe-surface", "cayuga_gpu_no_submit",
                "--observed-checks-json", checks,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_runtime_probe_report_runtime_ready_no_submit")
            self.assertTrue(rep["runtime_ready"])
            self.assertTrue(rep["cayuga_probe_executed"])


if __name__ == "__main__":
    unittest.main()
