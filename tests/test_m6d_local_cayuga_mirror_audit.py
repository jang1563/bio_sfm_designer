"""Tests for local/Cayuga mirror consistency audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_local_cayuga_mirror_audit import (
    _EXACT_SHA_PATHS,
    _JSON_FIELD_SPECS,
    build_audit,
    main,
    render_markdown,
)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as fh:
        if isinstance(data, bytes):
            fh.write(data)
        else:
            fh.write(data)


def _write_json(path, obj):
    _write(path, json.dumps(obj, sort_keys=True) + "\n")


class M6DLocalCayugaMirrorAuditTests(unittest.TestCase):
    def test_default_exact_paths_cover_v11_postsubmit_bridge(self):
        expected = {
            "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh",
            "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh",
            "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
            "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
            "results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
            "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_guarded_preflight.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_receipt_monitor.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_job_state_probe.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_postsubmit_status.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_postsync_interpretation.py",
            "src/bio_sfm_designer/experiments/m6d_w2_v11_public_approval_bundle.py",
            "src/bio_sfm_designer/experiments/m6d_w2_v11_remote_submission_readiness.py",
            "src/bio_sfm_designer/experiments/m6d_w2_v11_submission_decision_state.py",
            "src/bio_sfm_designer/experiments/m6d_local_cayuga_mirror_audit.py",
            "src/bio_sfm_designer/experiments/m6d_goal_completion_audit.py",
            "src/bio_sfm_designer/experiments/m6d_goal_drift_audit.py",
            "src/bio_sfm_designer/experiments/public_surface_sanitize.py",
        }

        self.assertTrue(expected.issubset(set(_EXACT_SHA_PATHS)))

    def test_default_mirror_fields_cover_v11_postsubmit_sync_gate(self):
        packet_fields = _JSON_FIELD_SPECS[
            "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"
        ]
        status_fields = _JSON_FIELD_SPECS["results/m6c_project_status_w2_followup.json"]
        decision_fields = _JSON_FIELD_SPECS[
            "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json"
        ]
        public_bundle_fields = _JSON_FIELD_SPECS[
            "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.json"
        ]
        completion_fields = _JSON_FIELD_SPECS["results/m6d_goal_completion_audit.json"]
        drift_fields = _JSON_FIELD_SPECS["results/m6d_goal_drift_audit.json"]
        remote_readiness_fields = _JSON_FIELD_SPECS[
            "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json"
        ]

        self.assertIn("postsubmit_status_before_sync", packet_fields)
        self.assertIn("job_state_probe_before_sync", packet_fields)
        self.assertIn("receipt_monitor_after_submit", packet_fields)
        self.assertIn("job_state_query_after_receipt", packet_fields)
        self.assertIn("job_state_probe_sync_after_query", packet_fields)
        self.assertIn("sacct_states_before_sync", packet_fields)
        self.assertIn("postsubmit_sync_ready_gate", packet_fields)
        self.assertIn("postsubmit_status_command_before_sync", packet_fields)
        self.assertIn("postsync_replay_after_sync", packet_fields)
        self.assertIn("approval_scope.planned_design_records", packet_fields)
        self.assertIn("approval_scope.expected_slurm_jobs", packet_fields)
        self.assertIn("approval_scope.target_alpha", packet_fields)
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_postsubmit_sync_ready_gate_ok",
            status_fields,
        )
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_postsubmit_bridge_ok",
            status_fields,
        )
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_job_state_query_bridge_ok",
            status_fields,
        )
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_remote_shell_syntax_checks",
            status_fields,
        )
        self.assertIn("workstreams.W2_multi_target_panel.panel_approval_scope_ready", status_fields)
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_approval_scope_records_per_target_planned",
            status_fields,
        )
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_approval_scope_planned_design_records",
            status_fields,
        )
        self.assertIn(
            "workstreams.W2_multi_target_panel.panel_approval_scope_expected_slurm_jobs",
            status_fields,
        )
        self.assertIn("resume_execution_ladder.next_role", status_fields)
        self.assertIn("resume_execution_ladder.approval_scope.planned_design_records", status_fields)
        self.assertIn("resume_execution_ladder.approval_scope.expected_slurm_jobs", status_fields)
        self.assertIn(
            "resume_execution_ladder.approval_disambiguation.continuation_phrases_are_approval",
            status_fields,
        )
        self.assertIn(
            "resume_execution_ladder.approval_disambiguation.non_approval_continuation_phrases",
            status_fields,
        )
        self.assertIn("approval_disambiguation.continuation_phrases_are_approval", decision_fields)
        self.assertIn("approval_disambiguation.machine_gate", decision_fields)
        self.assertIn("approval_scope.planned_design_records", decision_fields)
        self.assertIn("approval_scope.expected_slurm_jobs", decision_fields)
        self.assertIn("prerequisites.approval_packet.approval_scope_ok", decision_fields)
        self.assertIn(
            "prerequisites.remote_submission_readiness.n_shell_syntax_checks",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.remote_submission_readiness.shell_syntax_checks_ok",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.project_status.w2_panel_remote_shell_syntax_checks",
            decision_fields,
        )
        self.assertIn("prerequisites.project_status.w2_panel_approval_scope_ok", decision_fields)
        self.assertIn(
            "prerequisites.project_status.w2_panel_approval_scope_planned_design_records",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.project_status.w2_panel_approval_scope_expected_slurm_jobs",
            decision_fields,
        )
        self.assertIn("prerequisites.goal_completion_audit.w2_panel_approval_scope_ready", decision_fields)
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_approval_scope_planned_design_records",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_approval_scope_expected_slurm_jobs",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_ready",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_planned_design_records",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_project_status_panel_approval_scope_expected_slurm_jobs",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_ready",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_planned_design_records",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_scope_expected_slurm_jobs",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_ready",
            decision_fields,
        )
        self.assertIn("operator_approval_checklist.pre_submit_state_ok", decision_fields)
        self.assertIn("operator_approval_checklist.submit_allowed_by_this_artifact", decision_fields)
        self.assertIn("operator_approval_checklist.submission_performed_by_this_artifact", decision_fields)
        self.assertIn("operator_approval_checklist.approval_phrase_required", decision_fields)
        self.assertIn("operator_approval_checklist.machine_gate", decision_fields)
        self.assertIn("operator_approval_checklist.postsubmit_driver_command", decision_fields)
        self.assertIn("operator_approval_checklist.postsync_replay_command", decision_fields)
        self.assertIn("operator_approval_checklist.driver_replay_command_pair_ready", decision_fields)
        self.assertIn("operator_approval_checklist.remote_receipts_checked", decision_fields)
        self.assertIn("operator_approval_checklist.remote_receipts_absent", decision_fields)
        self.assertIn("operator_approval_checklist.planned_design_records", decision_fields)
        self.assertIn("operator_approval_checklist.expected_slurm_jobs", decision_fields)
        self.assertIn("operator_approval_checklist.target_alpha", decision_fields)
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_step_count",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_all_commands_present",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_sync_ready_before_record_sync",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_includes_postsync_interpretation",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_command_present",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_command_expected",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_postsync_replay_command_expected",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_replay_command_pair_ready",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_contract_ok",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_default_max_polls",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate",
            decision_fields,
        )
        self.assertIn(
            "prerequisites.goal_completion_audit.w2_panel_public_approval_bundle_workflow_driver_sync_ready_only",
            decision_fields,
        )
        self.assertIn("w2_gate.panel_remote_exact_checks", completion_fields)
        self.assertIn("w2_gate.panel_approval_scope_ready", completion_fields)
        self.assertIn("w2_gate.panel_approval_scope_planned_design_records", completion_fields)
        self.assertIn("w2_gate.panel_approval_scope_expected_slurm_jobs", completion_fields)
        self.assertIn("w2_gate.project_status_panel_approval_scope_ready", completion_fields)
        self.assertIn(
            "w2_gate.project_status_panel_approval_scope_planned_design_records",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.project_status_panel_approval_scope_expected_slurm_jobs",
            completion_fields,
        )
        self.assertIn("w2_gate.panel_remote_shell_syntax_checks", completion_fields)
        self.assertIn("w2_gate.panel_remote_shell_syntax_checks_ok", completion_fields)
        self.assertIn("w2_gate.panel_public_approval_bundle_remote_shell_syntax_checks", completion_fields)
        self.assertIn("w2_gate.panel_public_approval_bundle_remote_shell_syntax_checks_ok", completion_fields)
        self.assertIn("w2_gate.panel_public_approval_bundle_workflow_step_count", completion_fields)
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_sync_ready_before_record_sync",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_includes_postsync_interpretation",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_command_present",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_command_expected",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_postsync_replay_command_expected",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_replay_command_pair_ready",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_polling_contract_ok",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_polling_default_max_polls",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_polling_default_poll_seconds",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_public_approval_bundle_workflow_driver_polling_sync_ready_gate",
            completion_fields,
        )
        self.assertIn("w2_gate.panel_public_approval_bundle_scope_ready", completion_fields)
        self.assertIn("w2_gate.panel_public_approval_bundle_scope_planned_design_records", completion_fields)
        self.assertIn("w2_gate.panel_public_approval_bundle_scope_expected_slurm_jobs", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_checklist_ok", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_submit_allowed", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_submission_performed", completion_fields)
        self.assertIn(
            "w2_gate.panel_submission_decision_operator_approval_phrase_required",
            completion_fields,
        )
        self.assertIn("w2_gate.panel_submission_decision_operator_machine_gate", completion_fields)
        self.assertIn(
            "w2_gate.panel_submission_decision_operator_postsubmit_driver_command",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_submission_decision_operator_postsync_replay_command",
            completion_fields,
        )
        self.assertIn(
            "w2_gate.panel_submission_decision_operator_driver_replay_pair_ready",
            completion_fields,
        )
        self.assertIn("w2_gate.panel_submission_decision_operator_local_receipts_absent", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_remote_receipts_checked", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_remote_receipts_absent", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_planned_design_records", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_expected_slurm_jobs", completion_fields)
        self.assertIn("w2_gate.panel_submission_decision_operator_target_alpha", completion_fields)
        self.assertIn("prerequisites.remote_readiness.n_exact_checks", public_bundle_fields)
        self.assertIn("approval_scope.planned_design_records", public_bundle_fields)
        self.assertIn("approval_scope.expected_slurm_jobs", public_bundle_fields)
        self.assertIn("approval_scope.target_alpha", public_bundle_fields)
        self.assertIn("prerequisites.remote_readiness.n_shell_syntax_checks", public_bundle_fields)
        self.assertIn("prerequisites.remote_readiness.shell_syntax_checks_ok", public_bundle_fields)
        self.assertIn("post_approval_workflow.manual_step_count", public_bundle_fields)
        self.assertIn("post_approval_workflow.all_manual_commands_present", public_bundle_fields)
        self.assertIn(
            "post_approval_workflow.requires_sync_ready_before_record_sync",
            public_bundle_fields,
        )
        self.assertIn("post_approval_workflow.includes_sync_back", public_bundle_fields)
        self.assertIn("post_approval_workflow.includes_completion", public_bundle_fields)
        self.assertIn("post_approval_workflow.includes_postsync_interpretation", public_bundle_fields)
        self.assertIn("post_approval_workflow.driver_command_present", public_bundle_fields)
        self.assertIn("post_approval_workflow.driver_command_expected", public_bundle_fields)
        self.assertIn("post_approval_workflow.postsync_replay_command_expected", public_bundle_fields)
        self.assertIn("post_approval_workflow.driver_replay_command_pair_ready", public_bundle_fields)
        self.assertIn("post_approval_workflow.driver_polling_contract_ok", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.max_polls_env_var", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.default_max_polls", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.poll_seconds_env_var", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.default_poll_seconds", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.proceeds_only_when_sync_ready", public_bundle_fields)
        self.assertIn("postsubmit_driver_polling.sync_ready_gate", public_bundle_fields)
        self.assertIn(
            "post_approval_workflow.driver_proceeds_only_when_sync_ready",
            public_bundle_fields,
        )
        self.assertIn(
            "current_state.completion_audit.panel_public_approval_bundle_ready",
            drift_fields,
        )
        self.assertIn("current_state.W2_panel_remote_readiness.n_exact_checks", drift_fields)
        self.assertIn("current_state.W2_panel_remote_readiness.n_shell_syntax_checks", drift_fields)
        self.assertIn("current_state.W2_panel_remote_readiness.shell_syntax_checks_ok", drift_fields)
        self.assertIn("drift_assessment.execution", drift_fields)
        self.assertIn("n_shell_syntax_checks", remote_readiness_fields)

    def test_build_audit_accepts_matching_exact_and_semantic_fields(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            _write(os.path.join(local, "README.md"), "same\n")
            _write(os.path.join(remote, "README.md"), "same\n")
            obj_local = {"status": "ok", "path": "/local/path", "nested": {"ready": True}}
            obj_remote = {"status": "ok", "path": "/remote/path", "nested": {"ready": True}}
            _write_json(os.path.join(local, "status.json"), obj_local)
            _write_json(os.path.join(remote, "status.json"), obj_remote)

            rep = build_audit(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=["README.md"],
                json_field_specs={"status.json": ["status", "nested.ready"]},
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "local_cayuga_mirror_agree")
        self.assertIn("no-submit mirror audit", render_markdown(rep))

    def test_build_audit_rejects_exact_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            _write(os.path.join(local, "README.md"), "local\n")
            _write(os.path.join(remote, "README.md"), "remote\n")

            rep = build_audit(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=["README.md"],
                json_field_specs={},
            )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "local_cayuga_mirror_drift")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("exact_sha_mismatch", kinds)

    def test_build_audit_rejects_semantic_field_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            _write_json(os.path.join(local, "status.json"), {"status": "ready"})
            _write_json(os.path.join(remote, "status.json"), {"status": "stale"})

            rep = build_audit(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=[],
                json_field_specs={"status.json": ["status"]},
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("semantic_field_mismatch", kinds)

    def test_build_audit_reports_panel_submission_as_next_action_for_v11_state(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            project_status = {
                "workstreams": {
                    "W2_multi_target_panel": {
                        "status": "panel_approval_packet_ready_awaiting_explicit_approval",
                    }
                }
            }
            decision_state = {
                "status": "awaiting_explicit_panel_submission_approval",
            }
            for root in [local, remote]:
                _write_json(os.path.join(root, "project.json"), project_status)
                _write_json(os.path.join(root, "decision.json"), decision_state)

            rep = build_audit(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=[],
                json_field_specs={
                    "project.json": ["workstreams.W2_multi_target_panel.status"],
                    "decision.json": ["status"],
                },
            )

        self.assertTrue(rep["audit_ok"])
        self.assertIn("explicit panel submission approval", rep["next_action"])

    def test_cli_writes_audit_against_filesystem_remote(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            out_json = os.path.join(d, "audit.json")
            out_md = os.path.join(d, "audit.md")
            for root in [local, remote]:
                for rel_path in _EXACT_SHA_PATHS:
                    _write(os.path.join(root, rel_path), "same\n")
                _write_json(os.path.join(root, "results/m6d_goal_mode_current_anchor.json"), {"x": 1})
                _write_json(os.path.join(root, "results/m6c_cross_predictor.json"), {"x": 1})
                _write(os.path.join(root, "results/m6c_cross_predictor_matches.jsonl"), "{}\n")
                _write_json(os.path.join(root, "results/m6d_w2_w3_decision_protocol.json"), {"x": 1})
                _write(os.path.join(root, "results/m6d_w3_adjudication_set.jsonl"), "{}\n")
                _write_json(os.path.join(root, "results/m6d_w3_adjudication_set.json"), {"x": 1})
                _write_json(os.path.join(root, "results/m6c_project_status_w2_followup.json"), {"status": "s", "workstreams": {}})
                _write_json(os.path.join(root, "results/m6d_goal_completion_audit.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v9_approval_packet.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v9_approval_parity.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_explicit_approval_runbook.json"), {"status": "s"})
                _write(os.path.join(root, "results/m6d_w2_explicit_approval_runbook.md"), "same\n")
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w3_adjudication_audit.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_receipt_monitor.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json"), {"status": "s"})
                _write_json(os.path.join(root, "results/m6d_goal_drift_audit.json"), {"status": "s"})

            rc = main([
                "--local-root", local,
                "--remote-host", "",
                "--remote-root", remote,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["audit_ok"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
