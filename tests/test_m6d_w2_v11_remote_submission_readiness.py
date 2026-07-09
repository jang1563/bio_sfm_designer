"""Tests for the W2 v11 no-submit remote submission readiness audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v11_remote_submission_readiness import (
    _EXACT_SHA_PATHS,
    _SEMANTIC_JSON_FIELDS,
    build_readiness,
    main,
    render_markdown,
)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(data)


def _write_json(path, obj):
    _write(path, json.dumps(obj, sort_keys=True) + "\n")


def _make_roots(d):
    local = os.path.join(d, "local")
    remote = os.path.join(d, "remote")
    os.makedirs(local)
    os.makedirs(remote)
    return local, remote


class M6DW2V11RemoteSubmissionReadinessTests(unittest.TestCase):
    def test_default_exact_paths_cover_postsubmit_bridge(self):
        expected = {
            "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh",
            "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
            "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
            "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh",
            "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_receipt_monitor.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_job_state_probe.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_postsubmit_status.py",
            "src/bio_sfm_designer/experiments/m6d_w2_panel_postsync_interpretation.py",
            "src/bio_sfm_designer/experiments/m6d_w2_v11_submission_decision_state.py",
            "src/bio_sfm_designer/experiments/m6d_w2_v11_remote_submission_readiness.py",
            "src/bio_sfm_designer/experiments/m6d_local_cayuga_mirror_audit.py",
        }

        self.assertTrue(expected.issubset(set(_EXACT_SHA_PATHS)))

    def test_default_semantic_fields_cover_postsubmit_sync_ready_gate(self):
        fields = _SEMANTIC_JSON_FIELDS[
            "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"
        ]
        wrapper_fields = _SEMANTIC_JSON_FIELDS[
            "results/m6d_w2_target_family_redesign_v11_panel_wrapper_guard_audit.json"
        ]
        decision_fields = _SEMANTIC_JSON_FIELDS[
            "results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json"
        ]

        self.assertIn("no_env_run.ok", wrapper_fields)
        self.assertIn("no_env_run.ran", wrapper_fields)
        self.assertIn("no_env_run.returncode", wrapper_fields)
        self.assertIn("no_env_run.receipt_exists_before", wrapper_fields)
        self.assertIn("no_env_run.receipt_exists_after", wrapper_fields)
        self.assertIn("no_env_run.refusal_message_seen", wrapper_fields)
        self.assertIn("postsubmit_status_before_sync", fields)
        self.assertIn("job_state_probe_before_sync", fields)
        self.assertIn("receipt_monitor_after_submit", fields)
        self.assertIn("postsubmit_driver_after_submit", fields)
        self.assertIn("postsubmit_driver_polling.max_polls_env_var", fields)
        self.assertIn("postsubmit_driver_polling.proceeds_only_when_sync_ready", fields)
        self.assertIn("job_state_query_after_receipt", fields)
        self.assertIn("job_state_probe_sync_after_query", fields)
        self.assertIn("sacct_states_before_sync", fields)
        self.assertIn("postsubmit_sync_ready_gate", fields)
        self.assertIn("postsubmit_status_command_before_sync", fields)
        self.assertIn("postsync_replay_after_sync", fields)
        self.assertIn("checks.approval_scope_ready", fields)
        self.assertIn("approval_scope.planned_design_records", fields)
        self.assertIn("approval_scope.expected_slurm_jobs", fields)
        self.assertIn("approval_scope.target_alpha", fields)
        self.assertIn("panel_contract.panel_label", decision_fields)

    def test_build_readiness_accepts_hash_match_and_semantic_path_drift(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            for root in [local, remote]:
                _write(os.path.join(root, "results/submit.sh"), "#!/usr/bin/env bash\n")
            _write_json(os.path.join(local, "results/packet.json"), {
                "status": "panel_approval_packet_ready",
                "approval_packet_ready": True,
                "inputs": {"manifest_report": "/local/config.json"},
            })
            _write_json(os.path.join(remote, "results/packet.json"), {
                "status": "panel_approval_packet_ready",
                "approval_packet_ready": True,
                "inputs": {"manifest_report": "/remote/config.json"},
            })

            rep = build_readiness(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=["results/submit.sh"],
                semantic_json_fields={"results/packet.json": ["status", "approval_packet_ready"]},
                absent_paths=["results/receipt.jsonl"],
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "remote_submission_readiness_ok")
        self.assertTrue(rep["no_submit"])
        self.assertTrue(rep["can_submit_panel_if_user_explicitly_approves"])
        self.assertFalse(rep["can_claim_w2_generalization"])
        self.assertEqual(rep["n_shell_syntax_checks"], 1)
        self.assertTrue(rep["shell_syntax_checks"][0]["ok"])
        self.assertIn("does not submit jobs", render_markdown(rep))

    def test_build_readiness_rejects_exact_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            _write(os.path.join(local, "results/submit.sh"), "local\n")
            _write(os.path.join(remote, "results/submit.sh"), "remote\n")

            rep = build_readiness(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=["results/submit.sh"],
                semantic_json_fields={},
                absent_paths=[],
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("exact_sha_mismatch", {failure["kind"] for failure in rep["failures"]})

    def test_build_readiness_rejects_semantic_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            _write_json(os.path.join(local, "results/packet.json"), {"status": "ready"})
            _write_json(os.path.join(remote, "results/packet.json"), {"status": "blocked"})

            rep = build_readiness(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=[],
                semantic_json_fields={"results/packet.json": ["status"]},
                absent_paths=[],
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("semantic_field_mismatch", {failure["kind"] for failure in rep["failures"]})

    def test_build_readiness_rejects_shell_syntax_failure(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            for root in [local, remote]:
                _write(os.path.join(root, "results/submit.sh"), "if then\n")

            rep = build_readiness(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=["results/submit.sh"],
                semantic_json_fields={},
                absent_paths=[],
            )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["n_shell_syntax_checks"], 1)
        self.assertIn("local_shell_syntax_failed", {failure["kind"] for failure in rep["failures"]})
        self.assertIn("remote_shell_syntax_failed", {failure["kind"] for failure in rep["failures"]})

    def test_build_readiness_rejects_local_or_remote_receipt_presence(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            _write(os.path.join(remote, "results/receipt.jsonl"), "{}\n")

            rep = build_readiness(
                local_root=local,
                remote_root=remote,
                remote_host=None,
                exact_sha_paths=[],
                semantic_json_fields={},
                absent_paths=["results/receipt.jsonl"],
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("submit_receipt_or_summary_present", {failure["kind"] for failure in rep["failures"]})

    def test_cli_writes_custom_fixture_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            local, remote = _make_roots(d)
            out_json = os.path.join(d, "readiness.json")
            out_md = os.path.join(d, "readiness.md")
            for root in [local, remote]:
                _write(os.path.join(root, "results/submit.sh"), "same\n")
                _write_json(os.path.join(root, "results/status.json"), {"status": "ready"})

            rc = main([
                "--local-root", local,
                "--remote-host", "",
                "--remote-root", remote,
                "--exact-path", "results/submit.sh",
                "--semantic-field", "results/status.json:status",
                "--absent-path", "results/receipt.jsonl",
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
