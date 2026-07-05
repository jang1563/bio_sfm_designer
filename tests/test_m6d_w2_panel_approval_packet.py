"""Tests for the W2 v9 panel approval packet."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_approval_packet import (
    build_packet,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _execution_attempt():
    return {
        "_path": "/tmp/execution.json",
        "status": "target_msa_outputs_synced_strict_require_files_passed",
        "sync_back": {
            "completed": True,
            "strict_require_files_ok": True,
            "ready_targets": 14,
            "post_sync_pending_path_count": 0,
        },
    }


def _panel_preflight():
    return {
        "_path": "/tmp/preflight.json",
        "status": "panel_preflight_dry_run_passed_not_submitted",
        "submit_ready": {
            "ok": True,
            "n_ready_targets": 14,
        },
        "dry_run": {
            "exit_code": 0,
            "sbatch_called": False,
            "receipt_exists_after": False,
            "summary_exists_after": False,
        },
    }


def _wrapper_guard():
    return {
        "_path": "/tmp/guard.json",
        "audit_ok": True,
        "status": "panel_wrapper_guard_ok",
        "panel_approval_env_var": "BIO_SFM_APPROVE_V9_PANEL",
        "panel_approval_env_value": "approve-v9-panel-submit",
        "static_audit": {
            "ok": True,
            "approval_guard_before_shared_submit_wrapper": True,
        },
        "no_env_run": {
            "ok": True,
            "receipt_exists_after": False,
        },
    }


class M6DW2PanelApprovalPacketTests(unittest.TestCase):
    def test_packet_ready_preserves_no_generalization_claim(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "submit_receipt.jsonl")
            summary = os.path.join(d, "submit_summary.json")

            rep = build_packet(
                _execution_attempt(),
                _panel_preflight(),
                _wrapper_guard(),
                submit_receipt=receipt,
                submit_summary=summary,
                remote_host="${CAYUGA_BIO_SFM_HOST}",
                remote_root="/remote/repo",
                local_python="/tmp/python",
                cayuga_python="$HOME/.conda/envs/boltz/bin/python",
            )

        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["approval_packet_ready"])
        self.assertTrue(rep["can_submit_panel_if_user_explicitly_approves"])
        self.assertFalse(rep["can_claim_w2_generalization"])
        self.assertIn("BIO_SFM_APPROVE_V9_PANEL=approve-v9-panel-submit", rep["submit_command_if_approved"])
        self.assertIn("${CAYUGA_BIO_SFM_HOST}", rep["submit_command_if_approved"])
        self.assertIn("Can claim W2 generalization: `False`", render_markdown(rep))

    def test_packet_blocks_if_submit_receipt_already_exists(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "submit_receipt.jsonl")
            summary = os.path.join(d, "submit_summary.json")
            with open(receipt, "w") as fh:
                fh.write("{}\n")

            rep = build_packet(
                _execution_attempt(),
                _panel_preflight(),
                _wrapper_guard(),
                submit_receipt=receipt,
                submit_summary=summary,
                remote_host="${CAYUGA_BIO_SFM_HOST}",
                remote_root="/remote/repo",
                local_python="/tmp/python",
                cayuga_python="$HOME/.conda/envs/boltz/bin/python",
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("panel_submit_receipt_already_exists", {failure["kind"] for failure in rep["failures"]})

    def test_cli_writes_packet(self):
        with tempfile.TemporaryDirectory() as d:
            execution = os.path.join(d, "execution.json")
            preflight = os.path.join(d, "preflight.json")
            guard = os.path.join(d, "guard.json")
            out_json = os.path.join(d, "packet.json")
            out_md = os.path.join(d, "packet.md")
            _write_json(execution, _execution_attempt())
            _write_json(preflight, _panel_preflight())
            _write_json(guard, _wrapper_guard())

            rc = main([
                "--execution-attempt", execution,
                "--panel-preflight", preflight,
                "--wrapper-guard", guard,
                "--submit-receipt", os.path.join(d, "submit_receipt.jsonl"),
                "--submit-summary", os.path.join(d, "submit_summary.json"),
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["approval_packet_ready"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
