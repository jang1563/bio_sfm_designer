"""Tests for the W2 v11 no-submit remote submission readiness audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v11_remote_submission_readiness import (
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
    def test_default_semantic_fields_cover_postsubmit_sync_ready_gate(self):
        fields = _SEMANTIC_JSON_FIELDS[
            "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"
        ]

        self.assertIn("postsubmit_status_before_sync", fields)
        self.assertIn("job_state_probe_before_sync", fields)
        self.assertIn("postsubmit_sync_ready_gate", fields)

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
