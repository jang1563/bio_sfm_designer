"""Tests for the public-safe W2 v11 approval bundle."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v11_public_approval_bundle import (
    build_bundle,
    main,
    render_markdown,
)


STRICT_COMMAND = (
    "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
    "--manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json "
    "--receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl "
    "--summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json "
    "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
    "--require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _runbook():
    return {
        "_source_path": "results/runbook.json",
        "status": "approval_runbook_ready_not_submitted",
        "submit_state": {
            "submitted": False,
            "submit_receipt": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
            "submit_summary": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
        },
        "approval": {
            "required_env_var": "BIO_SFM_APPROVE_V11_PANEL",
            "required_env_value": "approve-v11-panel-submit",
            "submit_command_if_explicitly_approved": (
                "ssh cayuga-login-private 'cd /home/fs01/private_user_123/bio_sfm_smoke && "
                "BIO_SFM_PYTHON=/home/fs01/private_user_123/.conda/envs/boltz/bin/python "
                "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit bash wrapper.sh'"
            ),
        },
        "post_submit": {
            "receipt_monitor_script": "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh",
            "postsubmit_driver_script": "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh",
            "job_state_query_plan_after_probe": "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
            "sync_back_script": "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
            "completion_script": "results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
            "postsync_replay_script": "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
            "min_targets": 4,
            "min_records_per_target": 20,
        },
    }


def _packet(command=STRICT_COMMAND):
    return {
        "_source_path": "results/packet.json",
        "status": "panel_approval_packet_ready",
        "audit_ok": True,
        "approval_packet_ready": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "panel_approval_env_var": "BIO_SFM_APPROVE_V11_PANEL",
        "panel_approval_env_value": "approve-v11-panel-submit",
        "manifest": "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
        "submit_receipt": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "submit_summary": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
        "job_state_probe_before_sync": "results/m6d_w2_target_family_redesign_v11_job_state_probe.json",
        "postsubmit_status_before_sync": "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json",
        "postsubmit_status_command_before_sync": command,
        "target_alpha": 0.2,
    }


def _preflight():
    return {
        "_source_path": "results/preflight.json",
        "status": "panel_preflight_dry_run_passed_not_submitted",
        "audit_ok": True,
    }


def _decision():
    return {
        "_source_path": "results/decision.json",
        "status": "awaiting_explicit_panel_submission_approval",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "can_claim_w2_generalization": False,
    }


def _remote():
    return {
        "_source_path": "results/remote.json",
        "status": "remote_submission_readiness_ok",
        "audit_ok": True,
        "no_submit": True,
        "can_claim_w2_generalization": False,
    }


class M6DW2V11PublicApprovalBundleTests(unittest.TestCase):
    def test_bundle_is_public_safe_and_keeps_no_submit_boundary(self):
        rep = build_bundle(
            runbook=_runbook(),
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )
        text = json.dumps(rep, sort_keys=True)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_ready_not_submitted")
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["submitted"])
        self.assertFalse(rep["can_claim_w2_generalization"])
        self.assertNotIn("/home/fs01", text)
        self.assertNotIn("private_user_123", text)
        self.assertNotIn("cayuga-login-private", text)
        self.assertIn("<hpc-login-host>", text)
        self.assertIn(
            "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh",
            rep["portable_commands"]["postsubmit_driver_after_submit"],
        )
        self.assertIn("--require-sync-ready", rep["portable_commands"]["strict_postsubmit_status_before_sync"])
        self.assertIn("Approval Boundary", render_markdown(rep))

    def test_non_strict_postsubmit_command_blocks_bundle(self):
        rep = build_bundle(
            runbook=_runbook(),
            packet=_packet("python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --require-sync-ready"),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertIn("strict_postsubmit_command_not_portable_or_complete", {f["kind"] for f in rep["failures"]})

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "runbook": os.path.join(d, "runbook.json"),
                "packet": os.path.join(d, "packet.json"),
                "preflight": os.path.join(d, "preflight.json"),
                "decision": os.path.join(d, "decision.json"),
                "remote": os.path.join(d, "remote.json"),
                "out_json": os.path.join(d, "bundle.json"),
                "out_md": os.path.join(d, "bundle.md"),
            }
            _write_json(paths["runbook"], _runbook())
            _write_json(paths["packet"], _packet())
            _write_json(paths["preflight"], _preflight())
            _write_json(paths["decision"], _decision())
            _write_json(paths["remote"], _remote())

            rc = main([
                "--runbook", paths["runbook"],
                "--approval-packet", paths["packet"],
                "--preflight", paths["preflight"],
                "--submission-decision", paths["decision"],
                "--remote-readiness", paths["remote"],
                "--out-json", paths["out_json"],
                "--out-md", paths["out_md"],
            ])

            with open(paths["out_json"]) as fh:
                saved = json.load(fh)
            with open(paths["out_md"]) as fh:
                md = fh.read()

        self.assertEqual(rc, 0)
        self.assertTrue(saved["audit_ok"])
        self.assertIn("Portable Commands", md)


if __name__ == "__main__":
    unittest.main()
