"""Tests for the public-safe W2 v11 approval bundle."""

import json
import os
import tempfile
import unittest
from unittest import mock

from bio_sfm_designer.experiments import m6d_w2_v11_public_approval_bundle as bundle_mod
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
            "postsubmit_driver_polling": {
                "max_polls_env_var": "M6D_W2_POSTSUBMIT_MAX_POLLS",
                "default_max_polls": 120,
                "poll_seconds_env_var": "M6D_W2_POSTSUBMIT_POLL_SECONDS",
                "default_poll_seconds": 300,
                "sync_ready_gate": "m6d_w2_panel_postsubmit_status.sync_ready",
                "proceeds_only_when_sync_ready": True,
            },
            "job_state_query_plan_after_probe": "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
            "sync_back_script": "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
            "completion_script": "results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
            "postsync_replay_script": "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
            "min_targets": 4,
            "min_records_per_target": 20,
        },
    }


def _packet(command=STRICT_COMMAND):
    target_ids = ["10XZ_EF", "10YB_GH", "12NP_AH", "10VB_IJ", "10ZO_AB", "1A2Y_BA", "1A6W_HL"]
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
        "approval_scope": {
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
        },
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
        "n_exact_checks": 25,
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
        self.assertEqual(
            rep["postsubmit_driver_polling"]["max_polls_env_var"],
            "M6D_W2_POSTSUBMIT_MAX_POLLS",
        )
        self.assertEqual(rep["postsubmit_driver_polling"]["default_max_polls"], 120)
        self.assertEqual(
            rep["postsubmit_driver_polling"]["poll_seconds_env_var"],
            "M6D_W2_POSTSUBMIT_POLL_SECONDS",
        )
        self.assertEqual(rep["postsubmit_driver_polling"]["default_poll_seconds"], 300)
        self.assertEqual(
            rep["postsubmit_driver_polling"]["sync_ready_gate"],
            "m6d_w2_panel_postsubmit_status.sync_ready",
        )
        self.assertTrue(rep["post_approval_workflow"]["driver_polling_contract_ok"])
        self.assertTrue(rep["postsubmit_driver_polling"]["proceeds_only_when_sync_ready"])
        self.assertEqual(rep["post_approval_workflow"]["manual_step_count"], 9)
        self.assertEqual(rep["approval_scope"]["n_ready_targets"], 7)
        self.assertEqual(rep["approval_scope"]["planned_design_records"], 700)
        self.assertEqual(rep["approval_scope"]["expected_slurm_jobs"], 14)
        self.assertTrue(rep["post_approval_workflow"]["all_manual_commands_present"])
        self.assertTrue(rep["post_approval_workflow"]["requires_sync_ready_before_record_sync"])
        self.assertTrue(rep["post_approval_workflow"]["includes_receipt_monitor"])
        self.assertTrue(rep["post_approval_workflow"]["includes_job_state_query"])
        self.assertTrue(rep["post_approval_workflow"]["includes_sync_back"])
        self.assertTrue(rep["post_approval_workflow"]["includes_completion"])
        self.assertTrue(rep["post_approval_workflow"]["includes_postsync_interpretation"])
        self.assertTrue(rep["post_approval_workflow"]["driver_proceeds_only_when_sync_ready"])
        self.assertTrue(rep["post_approval_workflow"]["driver_command_expected"])
        self.assertTrue(rep["post_approval_workflow"]["postsync_replay_command_expected"])
        self.assertTrue(rep["post_approval_workflow"]["driver_replay_command_pair_ready"])
        self.assertTrue(rep["post_approval_workflow"]["postsubmit_driver_static_chain_ok"])
        self.assertTrue(rep["post_approval_workflow"]["postsync_replay_static_chain_ok"])
        self.assertTrue(rep["post_approval_workflow"]["sync_back_static_chain_ok"])
        self.assertTrue(rep["post_approval_workflow"]["completion_static_chain_ok"])
        self.assertTrue(rep["post_approval_workflow"]["script_chain_static_ok"])
        self.assertEqual(rep["prerequisites"]["remote_readiness"]["n_exact_checks"], 25)
        self.assertEqual(rep["prerequisites"]["remote_readiness"]["n_shell_syntax_checks"], 4)
        self.assertTrue(rep["prerequisites"]["remote_readiness"]["shell_syntax_checks_ok"])
        self.assertIn("--require-sync-ready", rep["portable_commands"]["strict_postsubmit_status_before_sync"])
        self.assertIn("Approval Boundary", render_markdown(rep))
        self.assertIn("Approval Scope", render_markdown(rep))
        self.assertIn("Post-Approval Workflow", render_markdown(rep))
        self.assertIn("driver command expected: `True`", render_markdown(rep))
        self.assertIn("post-sync replay command expected: `True`", render_markdown(rep))
        self.assertIn("driver/replay command pair ready: `True`", render_markdown(rep))
        self.assertIn("driver polling contract ok: `True`", render_markdown(rep))
        self.assertIn("script chain static ok: `True`", render_markdown(rep))
        self.assertIn("remote shell syntax checks ok: `True`", render_markdown(rep))

    def test_missing_approval_scope_blocks_bundle(self):
        packet = _packet()
        packet.pop("approval_scope")

        rep = build_bundle(
            runbook=_runbook(),
            packet=packet,
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertIn("approval_scope_not_ready", {f["kind"] for f in rep["failures"]})

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

    def test_missing_postsync_workflow_step_blocks_bundle(self):
        runbook = _runbook()
        runbook["post_submit"].pop("postsync_replay_script")

        rep = build_bundle(
            runbook=runbook,
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertFalse(rep["post_approval_workflow"]["all_manual_commands_present"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_polling_contract_drift_blocks_bundle(self):
        runbook = _runbook()
        runbook["post_submit"]["postsubmit_driver_polling"]["default_poll_seconds"] = 30

        rep = build_bundle(
            runbook=runbook,
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertFalse(rep["post_approval_workflow"]["driver_polling_contract_ok"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_wrong_postsubmit_driver_command_blocks_bundle(self):
        runbook = _runbook()
        runbook["post_submit"]["postsubmit_driver_script"] = "results/custom_postsubmit_driver.sh"

        rep = build_bundle(
            runbook=runbook,
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertTrue(rep["post_approval_workflow"]["driver_command_present"])
        self.assertFalse(rep["post_approval_workflow"]["driver_command_expected"])
        self.assertTrue(rep["post_approval_workflow"]["postsync_replay_command_expected"])
        self.assertFalse(rep["post_approval_workflow"]["driver_replay_command_pair_ready"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_wrong_postsync_replay_command_blocks_bundle(self):
        runbook = _runbook()
        runbook["post_submit"]["postsync_replay_script"] = "results/custom_postsync_replay.sh"

        rep = build_bundle(
            runbook=runbook,
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=_remote(),
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertTrue(rep["post_approval_workflow"]["driver_command_expected"])
        self.assertFalse(rep["post_approval_workflow"]["postsync_replay_command_expected"])
        self.assertFalse(rep["post_approval_workflow"]["driver_replay_command_pair_ready"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_broken_postsubmit_driver_static_chain_blocks_bundle(self):
        real_reader = bundle_mod._read_script_text

        def fake_reader(path):
            if path.endswith("m6d_w2_target_family_redesign_v11_postsubmit_driver.sh"):
                return "#!/usr/bin/env bash\nm6d_w2_panel_postsubmit_status\nsync_ready=true\n"
            return real_reader(path)

        with mock.patch.object(bundle_mod, "_read_script_text", side_effect=fake_reader):
            rep = build_bundle(
                runbook=_runbook(),
                packet=_packet(),
                preflight=_preflight(),
                decision_state=_decision(),
                remote_readiness=_remote(),
            )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertFalse(rep["post_approval_workflow"]["postsubmit_driver_static_chain_ok"])
        self.assertFalse(rep["post_approval_workflow"]["script_chain_static_ok"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_broken_postsync_replay_static_chain_blocks_bundle(self):
        real_reader = bundle_mod._read_script_text

        def fake_reader(path):
            if path.endswith("m6d_w2_target_family_redesign_v11_postsync_interpretation.sh"):
                return (
                    "#!/usr/bin/env bash\n"
                    "m6d_w2_panel_postsubmit_status --require-sync-ready\n"
                    "bash results/m6d_w2_target_family_redesign_v11_sync_back.sh\n"
                    "bash \"$COMPLETION_SCRIPT\"\n"
                    "complex_panel_report --target-alpha 0.2 --min-targets 4 "
                    "--min-records-per-target 20 --out "
                    "results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json\n"
                    "m6d_w2_panel_postsync_interpretation\n"
                )
            return real_reader(path)

        with mock.patch.object(bundle_mod, "_read_script_text", side_effect=fake_reader):
            rep = build_bundle(
                runbook=_runbook(),
                packet=_packet(),
                preflight=_preflight(),
                decision_state=_decision(),
                remote_readiness=_remote(),
            )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertFalse(rep["post_approval_workflow"]["postsync_replay_static_chain_ok"])
        self.assertFalse(rep["post_approval_workflow"]["script_chain_static_ok"])
        self.assertIn("post_approval_workflow_not_complete", {f["kind"] for f in rep["failures"]})

    def test_missing_remote_shell_syntax_gate_blocks_bundle(self):
        remote = _remote()
        remote.pop("n_shell_syntax_checks")
        remote.pop("shell_syntax_checks")

        rep = build_bundle(
            runbook=_runbook(),
            packet=_packet(),
            preflight=_preflight(),
            decision_state=_decision(),
            remote_readiness=remote,
        )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "public_approval_bundle_blocked")
        self.assertFalse(rep["prerequisites"]["remote_readiness"]["shell_syntax_checks_ok"])
        self.assertIn("remote_readiness_shell_syntax_not_ok", {f["kind"] for f in rep["failures"]})

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
        self.assertIn("Post-Approval Workflow", md)
        self.assertIn("Postsubmit Driver Polling", md)


if __name__ == "__main__":
    unittest.main()
