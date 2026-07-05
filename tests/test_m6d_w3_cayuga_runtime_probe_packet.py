"""Tests for the no-submit W3 Cayuga runtime-probe packet."""

import json
import os
import subprocess
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_cayuga_runtime_probe_packet import (
    build_packet,
    main,
    render_markdown,
    render_probe_script,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _plan():
    return {
        "_path": "/tmp/runtime_probe_plan.json",
        "artifact": "m6d_w3_runtime_probe_plan",
        "status": "w3_runtime_probe_plan_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
        "probe_contract": {
            "candidate_runtime_locations": [
                "$HOME/localcolabfold/.pixi/envs/default/bin/colabfold_batch",
                "$HOME/.conda/envs/colabfold/bin/colabfold_batch",
                "colabfold_batch on PATH",
            ],
            "target_count": 2,
            "target_ids": ["d1", "c1"],
        },
    }


def _local_report(*, runtime_ready=False, claim=False):
    return {
        "_path": "/tmp/runtime_probe_report.json",
        "artifact": "m6d_w3_runtime_probe_report",
        "status": "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "probe_surface": "local_static_no_submit",
        "probe_executed": True,
        "cayuga_probe_executed": False,
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": claim,
        "selected_predictor_or_protocol_id": "af2_multimer_colabfold_v1",
    }


class M6DW3CayugaRuntimeProbePacketTests(unittest.TestCase):
    def test_build_packet_writes_no_submit_script_contract(self):
        script = render_probe_script(
            plan_path="results/m6d_w3_runtime_probe_plan.json",
            observed_checks_path="results/observed.json",
            report_json_path="results/report.json",
            report_md_path="results/report.md",
        )

        rep = build_packet(
            _plan(),
            _local_report(),
            script_path="results/probe.sh",
            observed_checks_path="results/observed.json",
            report_json_path="results/report.json",
            report_md_path="results/report.md",
            script_text=script,
            report_date="2026-07-05",
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_cayuga_runtime_probe_packet_ready_no_submit")
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["prediction_executed"])
        self.assertFalse(rep["execution_inputs_emitted"])
        self.assertFalse(rep["command_wrapper_emitted"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertTrue(rep["static_script_audit"]["ok"])
        self.assertIn("--observed-checks-json", script)
        self.assertIn("--probe-surface cayuga_gpu_no_submit", script)
        self.assertIn("nvidia-smi", script)
        self.assertIn("BIO_SFM_TRUST_CORE_SRC", script)
        self.assertIn("bio-sfm-trust-core/src", script)
        self.assertIn('${PYTHONPATH:+:${PYTHONPATH}}', script)
        self.assertIn("universal_newlines=True", script)
        self.assertNotIn("capture_output=True", script)
        self.assertNotIn("text=True", script)
        self.assertNotIn("\nsbatch ", script)
        self.assertNotIn("\nsrun ", script)
        self.assertIn("Cayuga Runtime Probe Packet", render_markdown(rep))

    def test_rendered_script_is_bash_syntax_valid(self):
        with tempfile.TemporaryDirectory() as d:
            script_path = os.path.join(d, "probe.sh")
            script = render_probe_script(
                plan_path="results/m6d_w3_runtime_probe_plan.json",
                observed_checks_path="results/observed.json",
                report_json_path="results/report.json",
                report_md_path="results/report.md",
            )
            with open(script_path, "w") as fh:
                fh.write(script)

            proc = subprocess.run(["bash", "-n", script_path], text=True, capture_output=True)

        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_blocks_local_report_runtime_or_claim_leak(self):
        script = render_probe_script(
            plan_path="results/m6d_w3_runtime_probe_plan.json",
            observed_checks_path="results/observed.json",
            report_json_path="results/report.json",
            report_md_path="results/report.md",
        )

        rep = build_packet(
            _plan(),
            _local_report(runtime_ready=True, claim=True),
            script_path="results/probe.sh",
            observed_checks_path="results/observed.json",
            report_json_path="results/report.json",
            report_md_path="results/report.md",
            script_text=script,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_cayuga_probe_local_report_ready_drift", kinds)
        self.assertIn("w3_cayuga_probe_local_report_claim_leak", kinds)

    def test_cli_writes_packet_script_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "plan.json")
            local_report = os.path.join(d, "local_report.json")
            script = os.path.join(d, "probe.sh")
            observed = os.path.join(d, "observed.json")
            future_json = os.path.join(d, "future_report.json")
            future_md = os.path.join(d, "future_report.md")
            out_json = os.path.join(d, "packet.json")
            out_md = os.path.join(d, "packet.md")
            plan_obj = _plan()
            local_obj = _local_report()
            _write_json(plan, plan_obj)
            _write_json(local_report, local_obj)

            rc = main([
                "--w3-runtime-probe-plan", plan,
                "--local-runtime-probe-report", local_report,
                "--script", script,
                "--observed-checks-json", observed,
                "--future-report-json", future_json,
                "--future-report-md", future_md,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(script))
            self.assertTrue(os.path.exists(out_md))
            subprocess.run(["bash", "-n", script], check=True)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_cayuga_runtime_probe_packet_ready_no_submit")


if __name__ == "__main__":
    unittest.main()
