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
                "panel_approval_scope_ready": True,
                "panel_approval_scope_n_ready_targets": 7,
                "panel_approval_scope_records_per_target_planned": 100,
                "panel_approval_scope_planned_design_records": 700,
                "panel_approval_scope_expected_slurm_jobs": 14,
                "panel_approval_scope_target_alpha": 0.2,
            },
            "W3_independent_predictor": {
                "status": "negative_robustness_result_adjudicated",
                "complete": True,
                "positive_claim_supported": False,
            },
            "W4_closed_loop_DBTL": {"status": "closed_loop_round_complete", "complete": True},
        },
    }


def _panel_approval_scope():
    target_ids = ["10XZ_EF", "10YB_GH", "12NP_AH", "10VB_IJ", "10ZO_AB", "1A2Y_BA", "1A6W_HL"]
    return {
        "manifest": "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
        "target_ids": target_ids,
        "n_targets": 7,
        "n_ready_targets": 7,
        "min_targets": 4,
        "records_per_target_planned": 100,
        "planned_design_records": 700,
        "expected_job_pairs": 7,
        "expected_slurm_jobs": 14,
        "job_pair_model": "ProteinMPNN -> Boltz",
        "target_alpha": 0.2,
        "panel_out": "results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json",
        "completion_after_sync": "bash results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
        "sync_back_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v11_sync_back.sh",
        "submit_receipt": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "submit_summary": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
        "no_submit": True,
        "can_claim_w2_generalization": False,
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
        "target_alpha": 0.2,
        "approval_scope": _panel_approval_scope(),
        "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_PANEL=approve-v9-panel-submit bash wrapper.sh'",
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
    }


def _panel_decision_protocol(n_manifest_targets=14):
    return {
        "_path": "/tmp/panel_decision.json",
        "status": "post_panel_decision_protocol_ready",
        "audit_ok": True,
        "no_submit": True,
        "can_claim_w2_generalization_now": False,
        "panel_contract": {
            "target_alpha": 0.2,
            "n_manifest_targets": n_manifest_targets,
            "min_targets": 4,
            "min_records_per_target": 20,
        },
        "current_panel_result": {
            "status": "not_available_not_submitted",
            "w2_generalization_supported": False,
            "claim": "no W2 claim; panel records/report are not available",
        },
    }


def _panel_remote_readiness():
    return {
        "_path": "/tmp/panel_remote_readiness.json",
        "status": "remote_submission_readiness_ok",
        "audit_ok": True,
        "no_submit": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "n_exact_checks": 14,
        "n_semantic_checks": 5,
        "n_absence_checks": 2,
        "n_shell_syntax_checks": 4,
        "n_failures": 0,
        "shell_syntax_checks": [
            {"path": "results/submit.sh", "ok": True, "local_returncode": 0, "remote_returncode": 0},
            {"path": "results/monitor.sh", "ok": True, "local_returncode": 0, "remote_returncode": 0},
            {"path": "hpc/generate.sbatch", "ok": True, "local_returncode": 0, "remote_returncode": 0},
            {"path": "hpc/predict.sbatch", "ok": True, "local_returncode": 0, "remote_returncode": 0},
        ],
        "next_action": "remote mirror is ready; still wait for explicit user approval",
    }


def _panel_submission_decision_state():
    return {
        "_path": "/tmp/panel_submission_decision.json",
        "status": "awaiting_explicit_panel_submission_approval",
        "decision": "awaiting_explicit_approval",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "explicit_approval_required": True,
        "can_submit_if_explicitly_approved": True,
        "can_claim_w2_generalization": False,
        "operator_approval_checklist": {
            "pre_submit_state_ok": True,
            "submit_allowed_by_this_artifact": True,
            "submission_performed_by_this_artifact": False,
            "approval_phrase_required": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "continuation_phrases_are_approval": False,
            "machine_gate": "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
            "postsubmit_driver_command": (
                "bash results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh"
            ),
            "postsync_replay_command": (
                "bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh"
            ),
            "driver_replay_command_pair_ready": True,
            "local_receipts_absent": True,
            "remote_receipts_checked": True,
            "remote_receipts_absent": True,
            "planned_design_records": 700,
            "expected_slurm_jobs": 14,
            "target_alpha": 0.2,
            "no_submit": True,
            "submitted": False,
            "can_claim_w2_generalization": False,
        },
        "receipt_absence": {
            "local": [
                {"path": "results/receipt.jsonl", "exists": False},
                {"path": "results/summary.json", "exists": False},
            ],
            "remote_checked": True,
            "remote": [
                {"path": "results/receipt.jsonl", "exists": False},
                {"path": "results/summary.json", "exists": False},
            ],
        },
        "failures": [],
    }


def _panel_postsync_interpretation():
    return {
        "_path": "/tmp/panel_postsync.json",
        "status": "not_synced_not_interpretable",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "sync_ready": False,
        "can_claim_w2_generalization": False,
        "target_alpha": 0.2,
        "min_targets": 4,
        "min_records_per_target": 20,
        "current_panel_result": {
            "status": "not_available_not_submitted",
            "w2_generalization_supported": False,
        },
        "failures": [],
    }


def _panel_public_approval_bundle():
    return {
        "_path": "/tmp/panel_public_bundle.json",
        "artifact": "m6d_w2_v11_public_approval_bundle",
        "status": "public_approval_bundle_ready_not_submitted",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "can_claim_w2_generalization": False,
        "approval_boundary": {
            "explicit_approval_required": True,
            "approval_must_explicitly_name": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "continuation_phrases_are_approval": False,
            "machine_gate": "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
        },
        "target_contract": {
            "manifest": "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
            "target_alpha": 0.2,
            "min_targets": 4,
            "min_records_per_target": 20,
        },
        "approval_scope": _panel_approval_scope(),
        "prerequisites": {
            "remote_readiness": {
                "status": "remote_submission_readiness_ok",
                "n_exact_checks": 25,
                "n_shell_syntax_checks": 4,
                "shell_syntax_checks_ok": True,
                "n_failures": 0,
            },
        },
        "portable_commands": {
            "strict_postsubmit_status_before_sync": (
                "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
                "--manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json "
                "--receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl "
                "--summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json "
                "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json "
                "--require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
            )
        },
        "post_approval_workflow": {
            "manual_step_count": 9,
            "all_manual_commands_present": True,
            "requires_sync_ready_before_record_sync": True,
            "includes_receipt_monitor": True,
            "includes_job_state_query": True,
            "includes_sync_back": True,
            "includes_completion": True,
            "includes_postsync_interpretation": True,
            "driver_command_present": True,
            "driver_command_expected": True,
            "postsync_replay_command_expected": True,
            "driver_replay_command_pair_ready": True,
            "driver_polling_contract_ok": True,
            "driver_proceeds_only_when_sync_ready": True,
        },
        "postsubmit_driver_polling": {
            "max_polls_env_var": "M6D_W2_POSTSUBMIT_MAX_POLLS",
            "default_max_polls": 120,
            "poll_seconds_env_var": "M6D_W2_POSTSUBMIT_POLL_SECONDS",
            "default_poll_seconds": 300,
            "proceeds_only_when_sync_ready": True,
            "sync_ready_gate": "m6d_w2_panel_postsubmit_status.sync_ready",
        },
        "failures": [],
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
        self.assertIn("--require-sync-ready", rep["w2_gate"]["panel_postsubmit_sync_ready_gate"])
        self.assertIn("receipt_monitor", rep["w2_gate"]["panel_receipt_monitor_after_submit"])
        self.assertIn("postsync_interpretation", rep["w2_gate"]["panel_postsync_replay_after_sync"])
        self.assertTrue(rep["w2_gate"]["panel_approval_scope_ready"])
        self.assertTrue(rep["w2_gate"]["project_status_panel_approval_scope_ready"])
        self.assertEqual(rep["w2_gate"]["panel_approval_scope_planned_design_records"], 700)
        self.assertEqual(rep["w2_gate"]["panel_approval_scope_expected_slurm_jobs"], 14)
        self.assertIn("explicit panel submission", rep["claim_boundary"]["w2"])

    def test_panel_approval_packet_missing_postsubmit_gate_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            packet = _panel_approval_packet()
            packet.pop("postsubmit_sync_ready_gate")

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                packet,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_approval_missing_sync_ready_gate", kinds)

    def test_panel_approval_packet_missing_postsubmit_bridge_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            packet = _panel_approval_packet()
            packet.pop("postsync_replay_after_sync")

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                packet,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_approval_missing_postsync_replay_bridge", kinds)

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

    def test_v11_remote_readiness_still_does_not_complete_goal(self):
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
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertIn("remote submission readiness", rep["claim_boundary"]["w2"])
        self.assertTrue(rep["w2_gate"]["panel_remote_readiness_ok"])
        self.assertTrue(rep["w2_gate"]["panel_remote_no_submit"])
        self.assertTrue(rep["w2_gate"]["panel_remote_can_submit_if_explicitly_approved"])
        self.assertFalse(rep["w2_gate"]["panel_remote_can_claim_w2_generalization"])
        self.assertEqual(rep["w2_gate"]["panel_remote_shell_syntax_checks"], 4)
        self.assertTrue(rep["w2_gate"]["panel_remote_shell_syntax_checks_ok"])
        self.assertIn("W2 panel remote readiness ok: `True`", render_markdown(rep))
        self.assertIn("W2 panel remote shell syntax checks ok: `True`", render_markdown(rep))

    def test_missing_panel_remote_shell_syntax_gate_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            remote = _panel_remote_readiness()
            remote.pop("n_shell_syntax_checks")
            remote.pop("shell_syntax_checks")

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                remote,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_remote_readiness_ok"])
        self.assertFalse(rep["w2_gate"]["panel_remote_shell_syntax_checks_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_remote_shell_syntax_not_ok", kinds)

    def test_v11_submission_decision_state_still_does_not_complete_goal(self):
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
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertIn("panel-submission decision", rep["claim_boundary"]["w2"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_ready"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_no_submit"])
        self.assertFalse(rep["w2_gate"]["panel_submission_decision_submitted"])
        self.assertFalse(rep["w2_gate"]["panel_submission_decision_can_claim_w2_generalization"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_operator_checklist_ok"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_operator_submit_allowed"])
        self.assertFalse(rep["w2_gate"]["panel_submission_decision_operator_submission_performed"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_operator_driver_replay_pair_ready"])
        self.assertTrue(rep["w2_gate"]["panel_submission_decision_operator_remote_receipts_absent"])
        self.assertEqual(rep["w2_gate"]["panel_submission_decision_operator_planned_design_records"], 700)
        self.assertEqual(rep["w2_gate"]["panel_submission_decision_operator_expected_slurm_jobs"], 14)
        self.assertIn("W2 panel submission decision ready: `True`", render_markdown(rep))
        self.assertIn("W2 panel submission decision operator checklist ok: `True`", render_markdown(rep))

    def test_v11_submission_decision_operator_checklist_blocks_drift(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            decision = _panel_submission_decision_state()
            decision["operator_approval_checklist"]["remote_receipts_absent"] = False

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                decision,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_submission_decision_operator_checklist_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_submission_decision_operator_checklist_not_ready", kinds)

    def test_public_approval_bundle_missing_remote_syntax_gate_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle.pop("prerequisites")

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_remote_shell_syntax_checks_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_remote_readiness_drift", kinds)

    def test_v11_postsync_interpretation_still_does_not_complete_goal(self):
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
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertIn("post-sync interpretation", rep["claim_boundary"]["w2"])
        self.assertTrue(rep["w2_gate"]["panel_postsync_interpretation_ready"])
        self.assertFalse(rep["w2_gate"]["panel_postsync_can_claim_w2_generalization"])
        self.assertIn("W2 panel post-sync interpretation ready: `True`", render_markdown(rep))

    def test_v11_public_approval_bundle_still_does_not_complete_goal(self):
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
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                _panel_public_approval_bundle(),
                v9_receipt=receipt,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_ready"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_no_submit"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_submitted"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_can_claim_w2_generalization"])
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_remote_shell_syntax_checks"], 4)
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_remote_shell_syntax_checks_ok"])
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_workflow_step_count"], 9)
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_all_commands_present"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_sync_ready_before_record_sync"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_includes_postsync_interpretation"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_command_present"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_command_expected"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_postsync_replay_command_expected"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_replay_command_pair_ready"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_polling_contract_ok"])
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_polling_default_max_polls"], 120)
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds"], 300)
        self.assertEqual(
            rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate"],
            "m6d_w2_panel_postsubmit_status.sync_ready",
        )
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_sync_ready_only"])
        self.assertTrue(rep["w2_gate"]["panel_approval_scope_ready"])
        self.assertTrue(rep["w2_gate"]["project_status_panel_approval_scope_ready"])
        self.assertTrue(rep["w2_gate"]["panel_public_approval_bundle_scope_ready"])
        self.assertEqual(rep["w2_gate"]["panel_approval_scope_planned_design_records"], 700)
        self.assertEqual(rep["w2_gate"]["project_status_panel_approval_scope_planned_design_records"], 700)
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_scope_planned_design_records"], 700)
        self.assertEqual(rep["w2_gate"]["panel_approval_scope_expected_slurm_jobs"], 14)
        self.assertEqual(rep["w2_gate"]["project_status_panel_approval_scope_expected_slurm_jobs"], 14)
        self.assertEqual(rep["w2_gate"]["panel_public_approval_bundle_scope_expected_slurm_jobs"], 14)
        md = render_markdown(rep)
        self.assertIn("W2 panel public approval bundle ready: `True`", md)
        self.assertIn("W2 panel public approval bundle remote shell syntax checks ok: `True`", md)
        self.assertIn("W2 panel public approval bundle workflow steps: `9`", md)
        self.assertIn("W2 panel public approval bundle workflow driver command present: `True`", md)
        self.assertIn("W2 panel public approval bundle workflow driver command expected: `True`", md)
        self.assertIn("W2 panel public approval bundle workflow post-sync replay command expected: `True`", md)
        self.assertIn("W2 panel public approval bundle workflow driver/replay command pair ready: `True`", md)
        self.assertIn("W2 panel public approval bundle workflow driver polling contract ok: `True`", md)
        self.assertIn("W2 panel approval scope ready: `True`", md)
        self.assertIn("W2 project-status approval scope ready: `True`", md)
        self.assertIn("W2 panel public approval bundle scope ready: `True`", md)

    def test_missing_project_status_scope_blocks_v11_panel_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            w2 = project_status["workstreams"]["W2_multi_target_panel"]
            w2["status"] = "panel_approval_packet_ready_awaiting_explicit_approval"
            for key in list(w2):
                if key.startswith("panel_approval_scope"):
                    w2.pop(key)

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                _panel_public_approval_bundle(),
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["project_status_panel_approval_scope_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_project_status_panel_scope_not_ready", kinds)

    def test_missing_public_bundle_scope_blocks_v11_panel_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle.pop("approval_scope")

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_scope_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_scope_not_ready", kinds)

    def test_public_bundle_missing_driver_command_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle["post_approval_workflow"]["driver_command_present"] = False

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_command_present"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_workflow_incomplete", kinds)

    def test_public_bundle_wrong_driver_replay_pair_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle["post_approval_workflow"]["driver_command_expected"] = False
            bundle["post_approval_workflow"]["driver_replay_command_pair_ready"] = False

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_command_expected"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_replay_command_pair_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_workflow_incomplete", kinds)

    def test_public_bundle_polling_contract_drift_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle["postsubmit_driver_polling"]["sync_ready_gate"] = "wrong.gate"

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["w2_gate"]["panel_public_approval_bundle_workflow_driver_polling_contract_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_workflow_incomplete", kinds)

    def test_public_approval_bundle_missing_workflow_blocks_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            project_status = _project_status()
            project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
                "panel_approval_packet_ready_awaiting_explicit_approval"
            )
            bundle = _panel_public_approval_bundle()
            bundle.pop("post_approval_workflow")

            rep = build_audit(
                project_status,
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                _panel_decision_protocol(n_manifest_targets=7),
                _panel_remote_readiness(),
                _panel_submission_decision_state(),
                _panel_postsync_interpretation(),
                bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIsNone(rep["w2_gate"]["panel_public_approval_bundle_workflow_step_count"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_workflow_incomplete", kinds)

    def test_v11_public_approval_bundle_blocks_boundary_drift(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            bundle = _panel_public_approval_bundle()
            bundle["submitted"] = True
            bundle["can_claim_w2_generalization"] = True

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                _panel_approval_packet(),
                panel_public_approval_bundle=bundle,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_public_approval_bundle_boundary_drift", kinds)

    def test_v11_postsync_interpretation_blocks_claim_leak(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            postsync = _panel_postsync_interpretation()
            postsync["can_claim_w2_generalization"] = True

            rep = build_audit(
                _project_status(),
                _approval_packet(),
                _approval_parity(),
                _wrapper_guard(),
                _w3_audit(),
                _execution_attempt(),
                panel_postsync_interpretation=postsync,
                v9_receipt=receipt,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_panel_postsync_interpretation_claim_leak", kinds)

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
