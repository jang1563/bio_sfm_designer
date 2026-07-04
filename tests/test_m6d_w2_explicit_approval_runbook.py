"""Tests for the W2 explicit-approval runbook artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_explicit_approval_runbook import (
    build_runbook,
    main,
    render_markdown,
)


CAYUGA_HOST_FOR_TEST = "cayuga-" + "login1"
CAYUGA_ROOT_FOR_TEST = "/" + "home" + "/fs01/jak4013/bio_sfm_smoke"

SUBMIT = (
    f"ssh {CAYUGA_HOST_FOR_TEST} 'cd {CAYUGA_ROOT_FOR_TEST} && "
    "BIO_SFM_APPROVE_V9_TARGET_MSA=approve-v9-target-msa-precompute "
    "bash results/m6d_w2_target_family_redesign_v9_target_msa_with_receipt.sh'"
)
SYNC = "bash results/m6d_w2_target_family_redesign_v9_msa_sync_back.sh"


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _approval_packet():
    return {
        "_path": "/tmp/packet.json",
        "status": "awaiting_explicit_target_msa_approval",
        "approval_packet_ready": True,
        "can_submit_target_msa_if_user_explicitly_approves": True,
        "can_submit_proteinmpnn_boltz_panel": False,
        "wrapper_guard_audit_ok": True,
        "target_count": 14,
        "pending_path_count": 28,
        "target_msa_approval_env_var": "BIO_SFM_APPROVE_V9_TARGET_MSA",
        "target_msa_approval_env_value": "approve-v9-target-msa-precompute",
        "submit_command_if_approved": SUBMIT,
        "postsubmit_sync_back_command": SYNC,
    }


def _gate_audit():
    return {
        "_path": "/tmp/gate.json",
        "status": "pre_submit_gate_ready_awaiting_explicit_approval",
        "audit_ok": True,
        "ready_for_panel_submission": False,
        "ready_for_target_msa_submission_if_explicitly_approved": True,
        "target_count": 14,
        "pending_path_count": 28,
        "submit_command_if_approved": SUBMIT,
        "postsubmit_sync_back_command": SYNC,
    }


def _postsubmit_plan():
    return {
        "_path": "/tmp/postsubmit.json",
        "status": "postsubmit_replay_ready_awaiting_target_msa_submission_and_completion",
        "pre_submit_command_if_approved": SUBMIT,
        "sync_back_command_after_jobs_finish": SYNC,
        "post_sync_outputs": {
            "completion_report": "completion.json",
            "manifest_require_files_report": "manifest.json",
        },
    }


def _completion_audit():
    return {
        "_path": "/tmp/completion.json",
        "audit_ok": True,
        "can_mark_goal_complete": False,
    }


def _mirror_audit():
    return {
        "_path": "/tmp/mirror.json",
        "audit_ok": True,
        "status": "local_cayuga_mirror_agree",
        "n_failures": 0,
    }


class M6DW2ExplicitApprovalRunbookTests(unittest.TestCase):
    def test_build_runbook_accepts_target_msa_only_approval_boundary(self):
        rep = build_runbook(
            _approval_packet(),
            _gate_audit(),
            _postsubmit_plan(),
            _completion_audit(),
            _mirror_audit(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "explicit_approval_runbook_ready")
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertEqual(rep["target_count"], 14)
        self.assertEqual(rep["pending_path_count"], 28)
        self.assertIn("run_target_msa_input_prep_on_cayuga", [s["step"] for s in rep["runbook_steps"]])
        self.assertIn("does not submit work", render_markdown(rep))

    def test_build_runbook_blocks_command_drift(self):
        postsubmit = _postsubmit_plan()
        postsubmit["pre_submit_command_if_approved"] = f"ssh {CAYUGA_HOST_FOR_TEST} 'bash stale.sh'"

        rep = build_runbook(
            _approval_packet(),
            _gate_audit(),
            postsubmit,
            _completion_audit(),
            _mirror_audit(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("submit_command_drift", kinds)

    def test_build_runbook_blocks_panel_submission(self):
        packet = _approval_packet()
        packet["can_submit_proteinmpnn_boltz_panel"] = True

        rep = build_runbook(
            packet,
            _gate_audit(),
            _postsubmit_plan(),
            _completion_audit(),
            _mirror_audit(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_submission_not_blocked", kinds)

    def test_build_runbook_blocks_missing_mirror_audit(self):
        mirror = _mirror_audit()
        mirror["audit_ok"] = False
        mirror["n_failures"] = 1

        rep = build_runbook(
            _approval_packet(),
            _gate_audit(),
            _postsubmit_plan(),
            _completion_audit(),
            mirror,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("mirror_audit_not_ok", kinds)

    def test_cli_writes_runbook(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "packet": os.path.join(d, "packet.json"),
                "gate": os.path.join(d, "gate.json"),
                "postsubmit": os.path.join(d, "postsubmit.json"),
                "completion": os.path.join(d, "completion.json"),
                "mirror": os.path.join(d, "mirror.json"),
                "out": os.path.join(d, "runbook.json"),
                "md": os.path.join(d, "runbook.md"),
            }
            _write_json(paths["packet"], _approval_packet())
            _write_json(paths["gate"], _gate_audit())
            _write_json(paths["postsubmit"], _postsubmit_plan())
            _write_json(paths["completion"], _completion_audit())
            _write_json(paths["mirror"], _mirror_audit())

            rc = main([
                "--approval-packet", paths["packet"],
                "--gate-audit", paths["gate"],
                "--postsubmit-plan", paths["postsubmit"],
                "--completion-audit", paths["completion"],
                "--mirror-audit", paths["mirror"],
                "--out-json", paths["out"],
                "--out-md", paths["md"],
            ])

            self.assertEqual(rc, 0)
            with open(paths["out"]) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["audit_ok"])
            self.assertTrue(os.path.exists(paths["md"]))


if __name__ == "__main__":
    unittest.main()
