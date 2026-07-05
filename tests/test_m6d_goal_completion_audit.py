"""Tests for the M6d goal completion-boundary audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_completion_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _project_status():
    return {
        "_path": "/tmp/status.json",
        "status": "m6_complex_in_progress",
        "complete": False,
        "can_mark_goal_complete": False,
        "remaining": 1,
        "workstreams": {
            "W1_M6c_scale_up": {"status": "certified", "complete": True},
            "W2_multi_target_panel": {
                "status": "target_msa_gate_ready_awaiting_explicit_approval",
                "complete": False,
                "positive_claim_supported": False,
            },
            "W3_independent_predictor": {
                "status": "negative_robustness_result_adjudicated",
                "complete": True,
                "positive_claim_supported": False,
            },
            "W4_closed_loop_DBTL": {"status": "closed_loop_round_complete", "complete": True},
        },
    }


def _approval_packet():
    return {
        "_path": "/tmp/packet.json",
        "approval_packet_ready": True,
        "can_submit_target_msa_if_user_explicitly_approves": True,
        "can_submit_proteinmpnn_boltz_panel": False,
        "target_msa_approval_env_var": "BIO_SFM_APPROVE_V9_TARGET_MSA",
        "target_msa_approval_env_value": "approve-v9-target-msa-precompute",
    }


def _approval_parity():
    return {
        "_path": "/tmp/parity.json",
        "parity_ok": True,
        "panel_submission_blocked": True,
    }


def _wrapper_guard():
    return {
        "_path": "/tmp/wrapper_guard.json",
        "audit_ok": True,
        "static_audit": {"ok": True},
        "no_env_run": {"ok": True, "receipt_exists_after": False},
    }


def _w3_audit():
    return {
        "_path": "/tmp/w3_audit.json",
        "audit_ok": True,
        "status": "negative_robustness_result_adjudicated",
        "positive_claim_supported": False,
        "adjudication_set_artifact_audit": {
            "ok": True,
            "n_rows": 18,
            "actual_sha256": "a" * 64,
        },
    }


def _execution_attempt():
    return {
        "_path": "/tmp/execution.json",
        "status": "target_msa_outputs_synced_strict_require_files_passed",
        "approval_scope": "W2 v9 full 14-target target-MSA input prep only",
        "last_checked_at": "2026-07-05T09:08:12+09:00",
        "submitted_at": "2026-07-05T08:57:40+09:00",
        "submission_started": True,
        "jobs_submitted": 17,
        "job_ids": [str(job_id) for job_id in range(3059563, 3059580)],
        "receipt_created_or_updated": True,
        "receipt_summary": {
            "n_records": 14,
            "n_targets": 14,
            "status_counts": {"submitted": 3, "validated_existing": 11},
        },
        "queue_status": {
            "completed": 14,
            "failed_initial": 3,
            "retried": 3,
        },
        "sync_back": {
            "completed": True,
            "input_prep_artifacts": "98/98",
            "ready_targets": 14,
            "post_sync_pending_path_count": 0,
            "strict_require_files_ok": True,
        },
        "claim_boundary": {
            "target_msa_input_prep": "target-MSA outputs synced and strict require-files passed for the full 14-target W2 v9 batch",
            "proteinmpnn_boltz_panel_submission": "blocked",
            "w2_multi_target_generalization": "not_supported",
        },
        "next_action": "prepare the next W2 v9 panel step without making a W2 claim",
    }


def _panel_approval_packet():
    return {
        "_path": "/tmp/panel_approval.json",
        "status": "panel_approval_packet_ready",
        "approval_packet_ready": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "checks": {
            "target_msa_strict_ready": True,
            "panel_dry_run_no_sbatch": True,
            "panel_guard_no_env_refuses": True,
            "submit_receipt_absent": True,
            "submit_summary_absent": True,
        },
        "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_PANEL=approve-v9-panel-submit bash wrapper.sh'",
        "sync_back_command_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v9_sync_back.sh",
    }


def _panel_decision_protocol():
    return {
        "_path": "/tmp/panel_decision.json",
        "status": "post_panel_decision_protocol_ready",
        "audit_ok": True,
        "no_submit": True,
        "can_claim_w2_generalization_now": False,
        "panel_contract": {
            "target_alpha": 0.2,
            "n_manifest_targets": 14,
            "min_records_per_target": 20,
        },
        "current_panel_result": {
            "status": "not_available_not_submitted",
            "w2_generalization_supported": False,
            "claim": "no W2 claim; panel records/report are not available",
        },
    }


def _blocked_execution_attempt():
    execution = _execution_attempt()
    execution.update({
        "status": "blocked_before_submission_ssh_banner_exchange_timeout",
        "last_checked_at": "2026-07-05T08:55:01+09:00",
        "submitted_at": None,
        "submission_started": False,
        "jobs_submitted": 0,
        "job_ids": [],
        "receipt_created_or_updated": False,
        "receipt_summary": None,
        "queue_status": None,
        "sync_back": None,
        "next_action": "restore SSH access and rerun the approved target-MSA wrapper only",
    })
    execution["claim_boundary"] = {
        "target_msa_input_prep": "approved for full 14-target W2 v9 batch but not yet submitted because SSH login failed before command execution",
        "proteinmpnn_boltz_panel_submission": "blocked",
        "w2_multi_target_generalization": "not_supported",
    }
    return execution


class M6DGoalCompletionAuditTests(unittest.TestCase):
    def test_honest_active_goal_passes_without_marking_complete(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "goal_active_w2_remaining")
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertFalse(rep["complete"])
        self.assertEqual(rep["remaining_requirements"], ["W2_multi_target_panel"])
        self.assertTrue(rep["w2_execution_attempt"]["target_msa_outputs_synced_strict_require_files_passed"])
        self.assertIn("no-submit completion-boundary audit", render_markdown(rep))

    def test_panel_approval_packet_ready_still_does_not_complete_goal(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertTrue(rep["w2_gate"]["panel_approval_packet_ready"])
        self.assertTrue(rep["w2_gate"]["panel_can_submit_if_explicitly_approved"])
        self.assertFalse(rep["w2_gate"]["panel_can_claim_w2_generalization"])
        self.assertIn("explicit panel submission", rep["claim_boundary"]["w2"])

    def test_panel_decision_protocol_ready_still_does_not_complete_goal(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertTrue(rep["w2_gate"]["panel_decision_protocol_ready"])
        self.assertTrue(rep["w2_gate"]["panel_decision_no_submit"])
        self.assertFalse(rep["w2_gate"]["panel_decision_can_claim_w2_now"])
        self.assertEqual(rep["w2_gate"]["panel_decision_current_result_status"], "not_available_not_submitted")
        self.assertIn("post-panel decision protocol", rep["claim_boundary"]["w2"])
        self.assertIn("W2 panel decision protocol ready: `True`", render_markdown(rep))

    def test_pre_submission_blocked_state_also_passes_without_marking_complete(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _blocked_execution_attempt(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["w2_execution_attempt"]["approved_but_blocked_before_submission"])
        self.assertFalse(rep["can_mark_goal_complete"])

    def test_blocks_premature_goal_completion_claim(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            status = _project_status()
            status["complete"] = True
            status["can_mark_goal_complete"] = True
            status["remaining"] = 0

            rep = build_audit(
                status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("premature_goal_completion_claim", kinds)
        self.assertIn("remaining_requirement_count_mismatch", kinds)

    def test_blocks_w3_positive_claim_leak(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            w3_audit = _w3_audit()
            w3_audit["positive_claim_supported"] = True

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                w3_audit,
                _execution_attempt(),
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_standalone_positive_claim_leak", kinds)

    def test_blocks_unexpected_receipt_before_execution_starts(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            with open(receipt, "w") as fh:
                fh.write("{}\n")

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _blocked_execution_attempt(),
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_v9_receipt_unexpected_before_successful_execution", kinds)

    def test_blocks_execution_attempt_claim_drift(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            execution = _execution_attempt()
            execution["sync_back"]["ready_targets"] = 13
            execution["claim_boundary"]["proteinmpnn_boltz_panel_submission"] = "ready"

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                execution,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_execution_attempt_state_unrecognized", kinds)
        self.assertIn("w2_execution_attempt_panel_boundary_drift", kinds)

    def test_cli_writes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "status": os.path.join(d, "status.json"),
                "packet": os.path.join(d, "packet.json"),
                "parity": os.path.join(d, "parity.json"),
                "wrapper": os.path.join(d, "wrapper.json"),
                "w3": os.path.join(d, "w3.json"),
                "execution": os.path.join(d, "execution.json"),
                "receipt": os.path.join(d, "receipt.jsonl"),
                "out": os.path.join(d, "audit.json"),
                "md": os.path.join(d, "audit.md"),
            }
            _write_json(paths["status"], _project_status())
            _write_json(paths["packet"], _approval_packet())
            _write_json(paths["parity"], _approval_parity())
            _write_json(paths["wrapper"], _wrapper_guard())
            _write_json(paths["w3"], _w3_audit())
            _write_json(paths["execution"], _execution_attempt())

            rc = main([
                "--project-status", paths["status"],
                "--approval-packet", paths["packet"],
                "--approval-parity", paths["parity"],
                "--wrapper-guard", paths["wrapper"],
                "--w3-adjudication-audit", paths["w3"],
                "--execution-attempt", paths["execution"],
                "--v9-receipt", paths["receipt"],
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
