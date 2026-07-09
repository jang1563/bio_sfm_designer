"""Tests for the M6d goal drift audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_drift_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _goal_text():
    return """
This is not a publication plan. It develops the project as a research engine.
Continue the bio_sfm_designer M6d science-result program in Cayuga-first goal mode:
redesign W2 multi-target generalization after the current evaluable-not-certified panel,
resolve W3 Boltz-Chai predictor disagreement through a chosen robustness protocol,
preserve W1 as target-specific certified evidence and W4 as closed-loop plumbing evidence,
and keep all status artifacts, tests, and local/Cayuga handoff anchors honest and reproducible.
"""


def _anchor_text():
    return """
Current Evidence Boundary
- W1: certified as target-specific complex evidence.
- W2: not certified as multi-target generalization.
- W3: independent-predictor robustness is not supported under the current Boltz-vs-Chai readout.
- W4: closed-loop plumbing is complete.
Do not pool target evidence into a generalization claim.
"""


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
            },
            "W3_independent_predictor": {
                "status": "negative_robustness_result_adjudicated",
                "complete": True,
                "positive_claim_supported": False,
            },
            "W4_closed_loop_DBTL": {"status": "closed_loop_round_complete", "complete": True},
        },
    }


def _completion_audit():
    return {
        "_path": "/tmp/completion.json",
        "audit_ok": True,
        "status": "goal_active_w2_remaining",
        "can_mark_goal_complete": False,
        "w2_gate": {
            "panel_public_approval_bundle_ready": True,
            "panel_public_approval_bundle_workflow_script_chain_static_ok": True,
        },
    }


def _runbook():
    return {
        "_path": "/tmp/runbook.json",
        "audit_ok": True,
        "status": "explicit_approval_runbook_ready",
        "target_count": 14,
        "pending_path_count": 28,
        "claim_boundary": {
            "target_msa_input_prep": "allowed only after explicit approval",
            "proteinmpnn_boltz_panel_submission": "blocked until target-MSA sync-back and strict replay pass",
            "w2_multi_target_generalization": "not_supported",
        },
    }


def _w3_audit():
    return {
        "_path": "/tmp/w3.json",
        "audit_ok": True,
        "positive_claim_supported": False,
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
        "sync_back_command_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v11_sync_back.sh",
        "manifest": "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
        "submit_receipt": "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
        "submit_summary": "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
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


class M6DGoalDriftAuditTests(unittest.TestCase):
    def test_current_goal_state_has_no_major_direction_drift(self):
        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "no_major_direction_drift_w2_blocked")
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["direction"], "aligned")
        self.assertEqual(rep["drift_assessment"]["execution"], "target_msa_outputs_synced_strict_require_files_passed")
        self.assertIn("w2_branch_explosion", {risk["id"] for risk in rep["active_risks"]})
        self.assertIn("panel_step_boundary", {risk["id"] for risk in rep["active_risks"]})
        self.assertIn("M6d Goal Drift Audit", render_markdown(rep))

    def test_panel_approval_packet_ready_has_no_major_direction_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["execution"], "panel_approval_packet_ready_not_submitted")
        self.assertEqual(rep["current_state"]["W2_panel_approval"]["can_claim_w2_generalization"], False)
        self.assertIn(
            "--require-sync-ready",
            rep["current_state"]["W2_panel_approval"]["postsubmit_sync_ready_gate"],
        )
        self.assertIn("receipt_monitor", rep["current_state"]["W2_panel_approval"]["receipt_monitor_after_submit"])
        self.assertIn("postsync_interpretation", rep["current_state"]["W2_panel_approval"]["postsync_replay_after_sync"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_approval_packet_boundary"], "managed")

    def test_panel_approval_packet_missing_postsubmit_gate_is_drift(self):
        packet = _panel_approval_packet()
        packet.pop("postsubmit_sync_ready_gate")

        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            packet,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_approval_missing_sync_ready_gate", kinds)

    def test_panel_approval_packet_missing_postsubmit_bridge_is_drift(self):
        packet = _panel_approval_packet()
        packet.pop("job_state_query_after_receipt")

        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            packet,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_approval_missing_job_state_query_bridge", kinds)

    def test_panel_decision_protocol_ready_has_no_major_direction_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["execution"], "panel_decision_protocol_ready_not_submitted")
        self.assertFalse(rep["current_state"]["W2_panel_decision_protocol"]["can_claim_w2_generalization_now"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_decision_protocol_boundary"], "managed")
        self.assertIn("W2_panel_decision_protocol", render_markdown(rep))

    def test_v11_remote_readiness_ready_has_no_major_direction_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(n_manifest_targets=7),
            _panel_remote_readiness(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["execution"], "panel_remote_readiness_ready_not_submitted")
        self.assertFalse(rep["current_state"]["W2_panel_remote_readiness"]["can_claim_w2_generalization"])
        self.assertEqual(rep["current_state"]["W2_panel_remote_readiness"]["n_shell_syntax_checks"], 4)
        self.assertTrue(rep["current_state"]["W2_panel_remote_readiness"]["shell_syntax_checks_ok"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_remote_readiness_boundary"], "managed")
        self.assertIn("W2_panel_remote_readiness", render_markdown(rep))
        self.assertIn("syntax_ok=`True`", render_markdown(rep))

    def test_missing_panel_remote_shell_syntax_gate_is_execution_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        remote = _panel_remote_readiness()
        remote.pop("n_shell_syntax_checks")
        remote.pop("shell_syntax_checks")

        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(n_manifest_targets=7),
            remote,
        )

        self.assertFalse(rep["audit_ok"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_remote_readiness_boundary"], "not_ready")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_remote_shell_syntax_not_ok", kinds)

    def test_v11_submission_decision_ready_has_no_major_direction_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(n_manifest_targets=7),
            _panel_remote_readiness(),
            _panel_submission_decision_state(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["execution"], "panel_submission_decision_ready_not_submitted")
        self.assertFalse(rep["current_state"]["W2_panel_submission_decision"]["can_claim_w2_generalization"])
        self.assertTrue(rep["current_state"]["W2_panel_submission_decision"]["operator_checklist_ok"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_submission_decision_boundary"], "managed")
        self.assertIn("W2_panel_submission_decision", render_markdown(rep))
        self.assertIn("operator_checklist_ok=`True`", render_markdown(rep))

    def test_v11_submission_decision_operator_checklist_drift_blocks_audit(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        decision = _panel_submission_decision_state()
        decision["operator_approval_checklist"]["submit_allowed_by_this_artifact"] = False

        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(n_manifest_targets=7),
            _panel_remote_readiness(),
            decision,
        )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["claim_boundary"], "repair_required")
        self.assertFalse(rep["current_state"]["W2_panel_submission_decision"]["operator_checklist_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_submission_decision_operator_checklist_drift", kinds)

    def test_v11_postsync_interpretation_has_no_major_direction_drift(self):
        project_status = _project_status()
        project_status["workstreams"]["W2_multi_target_panel"]["status"] = (
            "panel_approval_packet_ready_awaiting_explicit_approval"
        )
        rep = build_audit(
            project_status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            _panel_approval_packet(),
            _panel_decision_protocol(n_manifest_targets=7),
            _panel_remote_readiness(),
            _panel_submission_decision_state(),
            _panel_postsync_interpretation(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["major_direction_drift"])
        self.assertEqual(rep["drift_assessment"]["execution"], "panel_postsync_interpretation_predeclared_not_synced")
        self.assertFalse(rep["current_state"]["W2_panel_postsync_interpretation"]["can_claim_w2_generalization"])
        risks = {risk["id"]: risk["status"] for risk in rep["active_risks"]}
        self.assertEqual(risks["panel_postsync_interpretation_boundary"], "managed")
        self.assertIn("W2_panel_postsync_interpretation", render_markdown(rep))

    def test_v11_postsync_interpretation_blocks_claim_drift(self):
        postsync = _panel_postsync_interpretation()
        postsync["can_claim_w2_generalization"] = True

        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
            panel_postsync_interpretation=postsync,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_postsync_interpretation_claim_drift", kinds)

    def test_pre_submission_blocked_state_has_no_major_direction_drift(self):
        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _blocked_execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["drift_assessment"]["execution"], "target_msa_approved_but_blocked_before_submission_by_ssh_login")

    def test_blocks_goal_text_drift_toward_publication(self):
        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            "publication packaging plan only",
            "",
        )

        self.assertFalse(rep["audit_ok"])
        self.assertTrue(rep["major_direction_drift"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("research_engine_not_publication", kinds)
        self.assertIn("w2_redesign_objective", kinds)

    def test_blocks_w2_premature_completion(self):
        status = _project_status()
        status["complete"] = True
        status["can_mark_goal_complete"] = True
        status["remaining"] = 0
        status["workstreams"]["W2_multi_target_panel"]["status"] = "multi_target_certified"
        status["workstreams"]["W2_multi_target_panel"]["complete"] = True

        rep = build_audit(
            status,
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w2_gate_boundary_drift", kinds)
        self.assertIn("premature_goal_completion_drift", kinds)

    def test_blocks_missing_public_approval_bundle_readiness(self):
        completion = _completion_audit()
        completion["w2_gate"].pop("panel_public_approval_bundle_ready")

        rep = build_audit(
            _project_status(),
            completion,
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("completion_audit_public_bundle_not_ready", kinds)

    def test_blocks_missing_public_approval_bundle_static_script_chain(self):
        completion = _completion_audit()
        completion["w2_gate"]["panel_public_approval_bundle_workflow_script_chain_static_ok"] = False

        rep = build_audit(
            _project_status(),
            completion,
            _runbook(),
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("completion_audit_public_bundle_script_chain_not_verified", kinds)

    def test_blocks_panel_submission_boundary_drift(self):
        runbook = _runbook()
        runbook["claim_boundary"]["proteinmpnn_boltz_panel_submission"] = "ready"

        rep = build_audit(
            _project_status(),
            _completion_audit(),
            runbook,
            _w3_audit(),
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_submission_boundary_drift", kinds)

    def test_blocks_w3_positive_claim_drift(self):
        status = _project_status()
        status["workstreams"]["W3_independent_predictor"]["positive_claim_supported"] = True
        w3_audit = _w3_audit()
        w3_audit["positive_claim_supported"] = True

        rep = build_audit(
            status,
            _completion_audit(),
            _runbook(),
            w3_audit,
            _execution_attempt(),
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_positive_claim_drift", kinds)
        self.assertIn("w3_standalone_positive_claim_drift", kinds)

    def test_blocks_execution_attempt_claim_drift(self):
        execution = _execution_attempt()
        execution["sync_back"]["ready_targets"] = 13
        execution["claim_boundary"]["w2_multi_target_generalization"] = "supported"

        rep = build_audit(
            _project_status(),
            _completion_audit(),
            _runbook(),
            _w3_audit(),
            execution,
            _goal_text(),
            _anchor_text(),
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("target_msa_execution_state_drift", kinds)
        self.assertIn("target_msa_execution_generalization_boundary_drift", kinds)

    def test_cli_writes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "status": os.path.join(d, "status.json"),
                "completion": os.path.join(d, "completion.json"),
                "runbook": os.path.join(d, "runbook.json"),
                "w3": os.path.join(d, "w3.json"),
                "execution": os.path.join(d, "execution.json"),
                "goal": os.path.join(d, "goal.md"),
                "anchor": os.path.join(d, "anchor.md"),
                "out": os.path.join(d, "drift.json"),
                "md": os.path.join(d, "drift.md"),
            }
            _write_json(paths["status"], _project_status())
            _write_json(paths["completion"], _completion_audit())
            _write_json(paths["runbook"], _runbook())
            _write_json(paths["w3"], _w3_audit())
            _write_json(paths["execution"], _execution_attempt())
            _write_text(paths["goal"], _goal_text())
            _write_text(paths["anchor"], _anchor_text())

            rc = main([
                "--project-status", paths["status"],
                "--completion-audit", paths["completion"],
                "--runbook", paths["runbook"],
                "--w3-adjudication-audit", paths["w3"],
                "--execution-attempt", paths["execution"],
                "--goal-mode-doc", paths["goal"],
                "--anchor-doc", paths["anchor"],
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
