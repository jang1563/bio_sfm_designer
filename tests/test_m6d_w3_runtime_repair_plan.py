"""Tests for the no-submit W3 Cayuga runtime repair plan."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_runtime_repair_plan import (
    build_runtime_repair_plan,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _runtime_report(*, claim=False, runtime_ready=False, msa_ok=True):
    return {
        "_path": "/tmp/runtime_report.json",
        "artifact": "m6d_w3_runtime_probe_report",
        "status": "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "probe_surface": "cayuga_gpu_no_submit",
        "probe_executed": True,
        "cayuga_probe_executed": True,
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "observed_checks": [
            {"kind": "env_discovery", "ran": True, "ok": False, "selected_cli": None},
            {"kind": "cli_help", "ran": False, "ok": False, "reason": "colabfold_batch_not_found"},
            {"kind": "gpu_stack", "ran": True, "ok": False, "jax_import_ok": False},
            {"kind": "msa_policy", "ran": True, "ok": msa_ok, "public_server_disabled": True},
            {"kind": "dry_run_enumeration", "ran": True, "ok": True, "n_inputs": 18, "submitted_jobs": 0},
        ],
    }


def _discovery(*, colabfold="missing", jax=False):
    return {
        "_path": "/tmp/discovery.json",
        "artifact": "m6d_w3_cayuga_runtime_repair_discovery",
        "surface": "configured_login_read_only_no_submit",
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "prediction_executed": False,
        "command_presence": {
            "colabfold_batch": colabfold,
            "nvidia-smi": "/usr/bin/nvidia-smi",
            "apptainer": "/usr/bin/apptainer",
        },
        "candidate_paths": [
            {
                "path": "/remote/home/localcolabfold/.pixi/envs/default/bin/colabfold_batch",
                "exists": False,
                "executable": False,
            }
        ],
        "python_package_probe": [
            {
                "python": "/remote/home/.conda/envs/boltz/bin/python",
                "version": "3.11.15",
                "packages": {"jax": jax, "jaxlib": jax, "colabfold": False},
            }
        ],
    }


class M6DW3RuntimeRepairPlanTests(unittest.TestCase):
    def test_build_runtime_repair_plan_records_required_repairs_without_execution(self):
        rep = build_runtime_repair_plan(_runtime_report(), _discovery(), report_date="2026-07-05")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_repair_plan_ready_no_submit")
        self.assertFalse(rep["runtime_ready"])
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(
            rep["failed_runtime_checks"],
            ["cli_help", "env_discovery", "gpu_stack"],
        )
        self.assertIn("msa_policy", rep["passed_runtime_checks"])
        ids = {item["id"] for item in rep["repair_items"]}
        self.assertIn("provision_colabfold_cli", ids)
        self.assertIn("provision_jax_cuda_runtime", ids)
        self.assertIn("rerun_gpu_check_on_actual_gpu_surface", ids)

    def test_blocks_claim_or_ready_drift(self):
        rep = build_runtime_repair_plan(
            _runtime_report(claim=True, runtime_ready=True),
            _discovery(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_repair_plan_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_repair_report_runtime_ready_drift", kinds)
        self.assertIn("w3_runtime_repair_report_can_claim_independent_predictor_robustness_now_drift", kinds)

    def test_blocks_if_msa_policy_regresses(self):
        rep = build_runtime_repair_plan(_runtime_report(msa_ok=False), _discovery())

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_repair_msa_policy_not_ok", kinds)

    def test_blocks_if_discovery_no_longer_matches_current_missing_colabfold_state(self):
        rep = build_runtime_repair_plan(_runtime_report(), _discovery(colabfold="/opt/colabfold_batch"))

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_repair_discovery_colabfold_unexpectedly_present", kinds)

    def test_render_markdown_names_no_submit_boundary(self):
        md = render_markdown(build_runtime_repair_plan(_runtime_report(), _discovery()))

        self.assertIn("M6d W3 Runtime Repair Plan", md)
        self.assertIn("no prediction execution", md)
        self.assertIn("provision_colabfold_cli", md)
        self.assertIn("provision_jax_cuda_runtime", md)

    def test_cli_writes_runtime_repair_plan(self):
        with tempfile.TemporaryDirectory() as d:
            report = os.path.join(d, "runtime_report.json")
            discovery = os.path.join(d, "discovery.json")
            out_json = os.path.join(d, "repair_plan.json")
            out_md = os.path.join(d, "repair_plan.md")
            _write_json(report, _runtime_report())
            _write_json(discovery, _discovery())

            rc = main([
                "--runtime-probe-report", report,
                "--cayuga-runtime-repair-discovery", discovery,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_runtime_repair_plan_ready_no_submit")
            self.assertEqual(rep["source_runtime_probe_report"], os.path.abspath(report))
            self.assertIsNotNone(rep["source_runtime_probe_report_sha256"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
