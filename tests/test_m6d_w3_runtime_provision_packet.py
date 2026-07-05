"""Tests for the guarded W3 runtime provisioning packet."""

import json
import os
import subprocess
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_runtime_provision_packet import (
    build_provision_packet,
    main,
    render_markdown,
    render_provision_script,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _repair_plan(*, runtime_ready=False, claim=False):
    return {
        "_path": "/tmp/repair_plan.json",
        "artifact": "m6d_w3_runtime_repair_plan",
        "status": "w3_runtime_repair_plan_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "prediction_executed": False,
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "repair_items": [
            {"id": "provision_colabfold_cli", "status": "required"},
            {"id": "provision_jax_cuda_runtime", "status": "required"},
            {"id": "rerun_gpu_check_on_actual_gpu_surface", "status": "required_after_runtime_install"},
        ],
    }


class M6DW3RuntimeProvisionPacketTests(unittest.TestCase):
    def test_build_packet_emits_guarded_validation_script_only(self):
        script = render_provision_script(receipt_path="results/receipt.json")
        rep = build_provision_packet(
            _repair_plan(),
            script_path="results/provision.sh",
            receipt_path="results/receipt.json",
            script_text=script,
            report_date="2026-07-05",
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_provision_packet_ready_no_submit")
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["install_executed"])
        self.assertFalse(rep["network_fetch_emitted"])
        self.assertFalse(rep["prediction_executed"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["runtime_ready"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(rep["approval_env_var"], "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION")
        self.assertIn("W3_COLABFOLD_BIN", script)
        self.assertIn("W3_COLABFOLD_SIF", script)
        self.assertIn("colabfold_batch --help", script)
        for forbidden in ["\nsbatch ", "\nsrun ", "curl ", "wget ", "pip install", "conda install"]:
            self.assertNotIn(forbidden, script)
        self.assertIn("Runtime Provision Packet", render_markdown(rep))

    def test_rendered_script_is_bash_syntax_valid_and_no_env_refuses_without_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            script_path = os.path.join(d, "provision.sh")
            receipt = os.path.join(d, "receipt.json")
            script = render_provision_script(receipt_path=receipt)
            with open(script_path, "w") as fh:
                fh.write(script)
            os.chmod(script_path, 0o755)

            subprocess.run(["bash", "-n", script_path], check=True)
            proc = subprocess.run([script_path], text=True, capture_output=True)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("refusing W3 runtime provisioning validation", proc.stderr)
        self.assertFalse(os.path.exists(receipt))

    def test_blocks_repair_plan_ready_or_claim_drift(self):
        script = render_provision_script(receipt_path="results/receipt.json")
        rep = build_provision_packet(
            _repair_plan(runtime_ready=True, claim=True),
            script_path="results/provision.sh",
            receipt_path="results/receipt.json",
            script_text=script,
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_runtime_provision_packet_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_provision_repair_plan_runtime_ready_drift", kinds)
        self.assertIn("w3_runtime_provision_repair_plan_can_claim_independent_predictor_robustness_now_drift", kinds)

    def test_static_audit_blocks_download_or_scheduler_markers(self):
        script = render_provision_script(receipt_path="results/receipt.json") + "\nwget https://example.invalid\n"
        rep = build_provision_packet(
            _repair_plan(),
            script_path="results/provision.sh",
            receipt_path="results/receipt.json",
            script_text=script,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_runtime_provision_script_forbidden_marker", kinds)

    def test_cli_writes_packet_and_guarded_script(self):
        with tempfile.TemporaryDirectory() as d:
            repair = os.path.join(d, "repair.json")
            script = os.path.join(d, "provision.sh")
            receipt = os.path.join(d, "receipt.json")
            out_json = os.path.join(d, "packet.json")
            out_md = os.path.join(d, "packet.md")
            _write_json(repair, _repair_plan())

            rc = main([
                "--runtime-repair-plan", repair,
                "--script", script,
                "--receipt", receipt,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(script))
            subprocess.run(["bash", "-n", script], check=True)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_runtime_provision_packet_ready_no_submit")
            self.assertEqual(rep["source_runtime_repair_plan"], os.path.abspath(repair))
            self.assertIsNotNone(rep["source_runtime_repair_plan_sha256"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
