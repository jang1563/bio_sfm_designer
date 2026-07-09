"""Tests for the W2 v11 explicit submission-decision state."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v11_submission_decision_state import (
    build_decision_state,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _approval_packet():
    return {
        "_path": "/tmp/approval.json",
        "artifact": "m6d_w2_panel_approval_packet",
        "status": "panel_approval_packet_ready",
        "audit_ok": True,
        "approval_packet_ready": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "panel_approval_env_var": "BIO_SFM_APPROVE_V11_PANEL",
        "panel_approval_env_value": "approve-v11-panel-submit",
        "submit_command_if_approved": "ssh hpc-login1 'BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit bash wrapper.sh'",
        "manifest": "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
        "submit_receipt": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "submit_summary": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
        "sync_back_command_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v11_sync_back.sh",
        "receipt_monitor_after_submit": (
            "CAYUGA_BIO_SFM_ROOT=cayuga-login1:/home/fs01/<user>/bio_sfm_smoke "
            "bash results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh"
        ),
        "job_state_query_after_receipt": (
            "ssh cayuga-login1 'cd /home/fs01/<user>/bio_sfm_smoke && "
            "bash results/m6d_w2_target_family_redesign_v11_job_state_query.sh'"
        ),
        "job_state_probe_sync_after_query": (
            "rsync -avP cayuga-login1:/home/fs01/<user>/bio_sfm_smoke/"
            "results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
            "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
        ),
        "postsubmit_status_before_sync": "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json",
        "job_state_probe_before_sync": "results/m6d_w2_target_family_redesign_v11_job_state_probe.json",
        "postsubmit_sync_ready_gate": (
            "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
            "--manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json "
            "--receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl "
            "--summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json "
            "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
            "--require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
        ),
        "postsubmit_status_command_before_sync": (
            "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
            "--manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json "
            "--receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl "
            "--summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json "
            "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
            "--require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
        ),
        "postsync_replay_after_sync": "bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
        "checks": {
            "target_msa_strict_ready": True,
            "panel_preflight_ready": True,
            "panel_dry_run_no_sbatch": True,
            "panel_guard_no_env_refuses": True,
            "submit_receipt_absent": True,
            "submit_summary_absent": True,
        },
    }


def _panel_decision_protocol():
    return {
        "_path": "/tmp/decision.json",
        "artifact": "m6d_w2_panel_decision_protocol",
        "status": "post_panel_decision_protocol_ready",
        "audit_ok": True,
        "no_submit": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization_now": False,
        "current_panel_result": {
            "status": "not_available_not_submitted",
            "w2_generalization_supported": False,
        },
    }


def _remote_readiness():
    return {
        "_path": "/tmp/remote_readiness.json",
        "artifact": "m6d_w2_v11_remote_submission_readiness",
        "status": "remote_submission_readiness_ok",
        "audit_ok": True,
        "no_submit": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "n_exact_checks": 14,
        "n_semantic_checks": 5,
        "n_absence_checks": 2,
        "n_failures": 0,
        "remote_host": "hpc-login1",
        "remote_root": "/home/fs01/<user>/bio_sfm_smoke",
        "absence_checks": [
            {
                "path": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
                "ok": True,
                "local_exists": False,
                "remote_exists": False,
            },
            {
                "path": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
                "ok": True,
                "local_exists": False,
                "remote_exists": False,
            },
        ],
    }


def _project_status():
    return {
        "_path": "/tmp/project_status.json",
        "status": "m6_complex_in_progress",
        "complete": False,
        "can_mark_goal_complete": False,
        "workstreams": {
            "W2_multi_target_panel": {
                "status": "panel_approval_packet_ready_awaiting_explicit_approval",
                "complete": False,
                "panel_approval_packet_ready": True,
                "panel_decision_protocol_ready": True,
                "panel_remote_submission_readiness_ok": True,
                "panel_submit_command_if_approved": "ssh hpc-login1 'BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit bash wrapper.sh'",
            }
        },
    }


def _goal_completion_audit():
    return {
        "_path": "/tmp/completion.json",
        "artifact": "m6d_goal_completion_audit",
        "status": "goal_active_w2_remaining",
        "audit_ok": True,
        "complete": False,
        "can_mark_goal_complete": False,
        "w2_gate": {
            "panel_remote_no_submit": True,
            "panel_remote_failures": 0,
            "panel_public_approval_bundle_ready": True,
        },
    }


def _goal_drift_audit():
    return {
        "_path": "/tmp/drift.json",
        "artifact": "m6d_goal_drift_audit",
        "status": "no_major_direction_drift_w2_blocked",
        "audit_ok": True,
        "major_direction_drift": False,
        "can_mark_goal_complete": False,
        "drift_assessment": {
            "execution": "panel_remote_readiness_ready_not_submitted",
        },
    }


def _build(**kwargs):
    args = {
        "approval_packet": _approval_packet(),
        "panel_decision_protocol": _panel_decision_protocol(),
        "remote_readiness": _remote_readiness(),
        "project_status": _project_status(),
        "goal_completion_audit": _goal_completion_audit(),
        "goal_drift_audit": _goal_drift_audit(),
        "local_absent_paths": [],
    }
    args.update(kwargs)
    return build_decision_state(**args)


class M6DW2V11SubmissionDecisionStateTests(unittest.TestCase):
    def test_ready_state_is_awaiting_explicit_approval_and_no_submit(self):
        rep = _build()

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "awaiting_explicit_panel_submission_approval")
        self.assertEqual(rep["decision"], "awaiting_explicit_approval")
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["submitted"])
        self.assertTrue(rep["explicit_approval_required"])
        self.assertTrue(rep["can_submit_if_explicitly_approved"])
        self.assertFalse(rep["can_claim_w2_generalization"])
        self.assertIn("BIO_SFM_APPROVE_V11_PANEL", rep["approval"]["required_env_var"])
        self.assertFalse(rep["approval_disambiguation"]["continuation_phrases_are_approval"])
        self.assertIn("go ahead", rep["approval_disambiguation"]["non_approval_continuation_phrases"])
        self.assertIn(
            "continue working toward the active thread goal",
            rep["approval_disambiguation"]["non_approval_continuation_phrases"],
        )
        self.assertIn("W2 v11", rep["approval_disambiguation"]["approval_must_explicitly_name"])
        self.assertTrue(rep["prerequisites"]["approval_packet"]["postsubmit_sync_ready_gate_ok"])
        self.assertTrue(rep["prerequisites"]["approval_packet"]["postsubmit_bridge_ok"])
        self.assertIn("does not submit jobs", render_markdown(rep))
        self.assertIn("Approval Disambiguation", render_markdown(rep))
        self.assertIn("continuation phrases are approval: `False`", render_markdown(rep))

    def test_existing_local_receipt_blocks_pre_submit_decision_state(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            with open(receipt, "w") as fh:
                fh.write("{}\n")

            rep = _build(local_absent_paths=[receipt])

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "submission_decision_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("submit_receipt_or_summary_present", kinds)
        self.assertFalse(rep["can_submit_if_explicitly_approved"])

    def test_remote_readiness_drift_blocks_decision_state(self):
        remote = _remote_readiness()
        remote["status"] = "remote_submission_readiness_blocked"
        remote["audit_ok"] = False
        remote["n_failures"] = 1

        rep = _build(remote_readiness=remote)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("remote_submission_readiness_not_ready", kinds)

    def test_missing_public_approval_bundle_readiness_blocks_decision_state(self):
        completion = _goal_completion_audit()
        completion["w2_gate"].pop("panel_public_approval_bundle_ready")

        rep = _build(goal_completion_audit=completion)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "submission_decision_blocked")
        self.assertFalse(rep["prerequisites"]["goal_completion_audit"]["ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("goal_completion_audit_not_ready", kinds)

    def test_missing_postsubmit_sync_ready_gate_blocks_decision_state(self):
        approval = _approval_packet()
        approval.pop("postsubmit_sync_ready_gate")

        rep = _build(approval_packet=approval)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "submission_decision_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_packet_not_ready", kinds)

    def test_missing_postsubmit_bridge_blocks_decision_state(self):
        approval = _approval_packet()
        approval.pop("receipt_monitor_after_submit")

        rep = _build(approval_packet=approval)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "submission_decision_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_packet_not_ready", kinds)

    def test_accepts_drift_audit_after_postsync_boundary_is_attached(self):
        drift = _goal_drift_audit()
        drift["drift_assessment"]["execution"] = "panel_postsync_interpretation_predeclared_not_synced"

        rep = _build(goal_drift_audit=drift)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["prerequisites"]["goal_drift_audit"]["execution"],
                         "panel_postsync_interpretation_predeclared_not_synced")

    def test_direct_remote_receipt_check_can_use_local_fixture_root(self):
        with tempfile.TemporaryDirectory() as d:
            rep = _build(
                remote_host=None,
                remote_root=d,
                check_remote_receipts=True,
                remote_absent_paths=["receipt.jsonl", "summary.json"],
            )

        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["receipt_absence"]["remote_checked"])
        self.assertEqual([row["exists"] for row in rep["receipt_absence"]["remote"]], [False, False])

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            approval = os.path.join(d, "approval.json")
            decision = os.path.join(d, "decision.json")
            remote = os.path.join(d, "remote.json")
            status = os.path.join(d, "status.json")
            completion = os.path.join(d, "completion.json")
            drift = os.path.join(d, "drift.json")
            out_json = os.path.join(d, "submission_state.json")
            out_md = os.path.join(d, "submission_state.md")
            _write_json(approval, _approval_packet())
            _write_json(decision, _panel_decision_protocol())
            _write_json(remote, _remote_readiness())
            _write_json(status, _project_status())
            _write_json(completion, _goal_completion_audit())
            _write_json(drift, _goal_drift_audit())

            rc = main([
                "--approval-packet", approval,
                "--panel-decision-protocol", decision,
                "--remote-readiness", remote,
                "--project-status", status,
                "--goal-completion-audit", completion,
                "--goal-drift-audit", drift,
                "--local-absent-path", os.path.join(d, "absent_receipt.jsonl"),
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            with open(out_json) as fh:
                saved = json.load(fh)
            with open(out_md) as fh:
                md = fh.read()

        self.assertEqual(rc, 0)
        self.assertEqual(saved["decision"], "awaiting_explicit_approval")
        self.assertIn("M6d W2 v11 Submission Decision State", md)


if __name__ == "__main__":
    unittest.main()
