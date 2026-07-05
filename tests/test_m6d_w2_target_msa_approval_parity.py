"""Tests for local/Cayuga W2 target-MSA approval packet parity."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_msa_approval_parity import (
    build_parity,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _packet():
    return {
        "artifact": "m6d_w2_target_msa_approval_packet",
        "status": "awaiting_explicit_target_msa_approval",
        "approval_packet_ready": True,
        "can_submit_target_msa_if_user_explicitly_approves": True,
        "can_submit_proteinmpnn_boltz_panel": False,
        "explicit_submit_approval_required": True,
        "target_msa_approval_env_var": "BIO_SFM_APPROVE_V9_TARGET_MSA",
        "target_msa_approval_env_value": "approve-v9-target-msa-precompute",
        "target_count": 2,
        "target_ids": ["t0", "t1"],
        "pending_path_count": 4,
        "pending_paths": "pending.txt",
        "pending_paths_sha256": "abc",
        "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'",
        "postsubmit_sync_back_command": "bash sync.sh",
        "wrapper_guard_audit_ok": True,
        "wrapper_guard_static_ok": True,
        "wrapper_guard_no_env_run_ok": True,
        "wrapper_guard_script_sha256": "wrapper-sha",
        "current_workstreams": {
            "W1_M6c_scale_up": "certified",
            "W2_multi_target_panel": "target_msa_gate_ready_awaiting_explicit_approval",
            "W3_independent_predictor": "negative_robustness_result_adjudicated",
            "W4_closed_loop_DBTL": "closed_loop_round_complete",
        },
        "scripts": {
            "submit_wrapper": {"exists": True, "nonempty": True, "sha256": "s1", "path": "/local/submit.sh"},
            "sync_back": {"exists": True, "nonempty": True, "sha256": "s2", "path": "/local/sync.sh"},
        },
        "evidence": {"project_status": "/local/project.json"},
        "failures": [],
    }


class M6DW2TargetMsaApprovalParityTests(unittest.TestCase):
    def test_build_parity_accepts_matching_packets_ignoring_absolute_evidence_paths(self):
        local = _packet()
        remote = _packet()
        remote["evidence"] = {"project_status": "/remote/project.json"}

        rep = build_parity(
            local,
            remote,
            remote_host="${CAYUGA_BIO_SFM_HOST}",
            remote_root="/remote/root",
            remote_path="packet.json",
        )

        self.assertTrue(rep["parity_ok"])
        self.assertEqual(rep["status"], "local_cayuga_approval_packet_agree")
        self.assertTrue(rep["approval_packet_ready"])
        self.assertTrue(rep["panel_submission_blocked"])
        self.assertEqual(rep["mismatches"], [])
        self.assertIn("Parity OK: `True`", render_markdown(rep))

    def test_build_parity_rejects_panel_submission_drift(self):
        local = _packet()
        remote = _packet()
        remote["can_submit_proteinmpnn_boltz_panel"] = True

        rep = build_parity(local, remote, remote_host=None, remote_root=None, remote_path="packet.json")

        self.assertFalse(rep["parity_ok"])
        self.assertEqual(rep["status"], "local_cayuga_approval_packet_mismatch")
        fields = {item["field"] for item in rep["mismatches"]}
        self.assertIn("can_submit_proteinmpnn_boltz_panel", fields)

    def test_cli_reads_remote_packet_from_local_remote_root(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local.json")
            remote_root = os.path.join(d, "remote")
            remote = os.path.join(remote_root, "packet.json")
            out_json = os.path.join(d, "parity.json")
            out_md = os.path.join(d, "parity.md")
            _write_json(local, _packet())
            _write_json(remote, _packet())

            rc = main([
                "--local-packet", local,
                "--remote-root", remote_root,
                "--remote-packet", "packet.json",
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["parity_ok"])


if __name__ == "__main__":
    unittest.main()
