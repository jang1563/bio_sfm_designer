"""Tests for the M6d W2 target-MSA approval packet."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_msa_approval_packet import (
    build_packet,
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


def _project_status():
    return {
        "goal_progress": "local_artifact_work_required",
        "remaining": 1,
        "workstreams": {
            "W1_M6c_scale_up": {"status": "certified", "complete": True},
            "W2_multi_target_panel": {
                "status": "target_msa_gate_ready_awaiting_explicit_approval",
                "complete": False,
                "submit_command_if_approved": (
                    "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_TARGET_MSA="
                    "approve-v9-target-msa-precompute bash submit.sh'"
                ),
                "postsubmit_sync_back_command": "bash sync.sh",
            },
            "W3_independent_predictor": {
                "status": "negative_robustness_result_adjudicated",
                "complete": True,
                "positive_claim_supported": False,
            },
            "W4_closed_loop_DBTL": {"status": "closed_loop_round_complete", "complete": True},
        },
    }


def _gate_audit():
    return {
        "audit_ok": True,
        "explicit_submit_approval_required": True,
        "ready_for_target_msa_submission_if_explicitly_approved": True,
        "ready_for_panel_submission": False,
        "target_count": 2,
        "pending_path_count": 4,
        "submit_command_if_approved": (
            "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_TARGET_MSA="
            "approve-v9-target-msa-precompute bash submit.sh'"
        ),
        "postsubmit_sync_back_command": "bash sync.sh",
    }


def _target_manifest():
    return {
        "targets": [
            {
                "id": "t0",
                "target_msa": "out/t0.a3m",
                "target_msa_report": "out/t0.a3m.report.json",
            },
            {
                "id": "t1",
                "target_msa": "out/t1.a3m",
                "target_msa_report": "out/t1.a3m.report.json",
            },
        ],
    }


def _wrapper_guard_audit():
    return {
        "_path": "/tmp/wrapper_guard_audit.json",
        "artifact": "m6d_w2_target_msa_wrapper_guard_audit",
        "status": "wrapper_guard_ok",
        "audit_ok": True,
        "static_audit": {
            "ok": True,
            "wrapper_sha256": "wrapper-sha",
            "receipt_truncate_after_approval_guard": True,
            "dry_run_before_approval_guard": True,
        },
        "no_env_run": {
            "ran": True,
            "ok": True,
            "returncode": 2,
            "receipt_exists_after": False,
        },
        "failures": [],
    }


def _submit_script():
    return """#!/usr/bin/env bash
TARGET_MSA_PRECOMPUTE_DRY_RUN=0
TARGET_MSA_PRECOMPUTE_RECEIPT=receipt.jsonl
BIO_SFM_APPROVE_V9_TARGET_MSA=approve-v9-target-msa-precompute
APPROVAL_TOKEN=approve-v9-target-msa-precompute
echo "refusing v9 target-MSA submission without explicit approval env"
bash "$PLAN"
echo "target-MSA input-prep provenance only"
"""


def _sync_script():
    return """#!/usr/bin/env bash
# Run only after v9 target-MSA input-prep jobs have finished.
rsync -avP remote local
python -m bio_sfm_designer.experiments.complex_input_prep_completion
python -m bio_sfm_designer.experiments.complex_target_manifest --require-files
"""


class M6DW2TargetMsaApprovalPacketTests(unittest.TestCase):
    def test_build_packet_accepts_ready_gate_without_authorizing_panel(self):
        with tempfile.TemporaryDirectory() as d:
            submit = os.path.join(d, "submit.sh")
            sync = os.path.join(d, "sync.sh")
            _write_text(submit, _submit_script())
            _write_text(sync, _sync_script())
            pending = ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"]

            rep = build_packet(
                _project_status(),
                _gate_audit(),
                _target_manifest(),
                _wrapper_guard_audit(),
                pending,
                pending_paths_path="pending.txt",
                submit_wrapper_path=submit,
                sync_back_script_path=sync,
            )

        self.assertTrue(rep["approval_packet_ready"])
        self.assertTrue(rep["can_submit_target_msa_if_user_explicitly_approves"])
        self.assertFalse(rep["can_submit_proteinmpnn_boltz_panel"])
        self.assertEqual(rep["target_count"], 2)
        self.assertEqual(rep["pending_path_count"], 4)
        self.assertEqual(rep["failures"], [])
        md = render_markdown(rep)
        self.assertIn("Target-MSA command if explicitly approved", md)
        self.assertIn("Required approval environment", md)
        self.assertIn("panel submission allowed", md)

    def test_build_packet_blocks_panel_job_in_submit_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            submit = os.path.join(d, "submit.sh")
            sync = os.path.join(d, "sync.sh")
            _write_text(submit, _submit_script() + "\npython hpc/predict_boltz_complex.py\n")
            _write_text(sync, _sync_script())

            rep = build_packet(
                _project_status(),
                _gate_audit(),
                _target_manifest(),
                _wrapper_guard_audit(),
                ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"],
                pending_paths_path="pending.txt",
                submit_wrapper_path=submit,
                sync_back_script_path=sync,
            )

        self.assertFalse(rep["approval_packet_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("submit_wrapper_contains_panel_job", kinds)

    def test_build_packet_blocks_submit_wrapper_without_approval_env(self):
        with tempfile.TemporaryDirectory() as d:
            submit = os.path.join(d, "submit.sh")
            sync = os.path.join(d, "sync.sh")
            _write_text(
                submit,
                """#!/usr/bin/env bash
TARGET_MSA_PRECOMPUTE_DRY_RUN=0
TARGET_MSA_PRECOMPUTE_RECEIPT=receipt.jsonl
bash "$PLAN"
echo "target-MSA input-prep provenance only"
""",
            )
            _write_text(sync, _sync_script())

            rep = build_packet(
                _project_status(),
                _gate_audit(),
                _target_manifest(),
                _wrapper_guard_audit(),
                ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"],
                pending_paths_path="pending.txt",
                submit_wrapper_path=submit,
                sync_back_script_path=sync,
            )

        self.assertFalse(rep["approval_packet_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("submit_wrapper_missing_guard", kinds)

    def test_build_packet_blocks_failed_wrapper_guard_audit(self):
        with tempfile.TemporaryDirectory() as d:
            submit = os.path.join(d, "submit.sh")
            sync = os.path.join(d, "sync.sh")
            _write_text(submit, _submit_script())
            _write_text(sync, _sync_script())
            guard = _wrapper_guard_audit()
            guard["audit_ok"] = False
            guard["status"] = "wrapper_guard_failed"

            rep = build_packet(
                _project_status(),
                _gate_audit(),
                _target_manifest(),
                guard,
                ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"],
                pending_paths_path="pending.txt",
                submit_wrapper_path=submit,
                sync_back_script_path=sync,
            )

        self.assertFalse(rep["approval_packet_ready"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("wrapper_guard_audit_not_ok", kinds)

    def test_cli_writes_packet(self):
        with tempfile.TemporaryDirectory() as d:
            project = os.path.join(d, "project.json")
            audit = os.path.join(d, "audit.json")
            manifest = os.path.join(d, "targets.json")
            guard = os.path.join(d, "wrapper_guard.json")
            pending = os.path.join(d, "pending.txt")
            submit = os.path.join(d, "submit.sh")
            sync = os.path.join(d, "sync.sh")
            out_json = os.path.join(d, "packet.json")
            out_md = os.path.join(d, "packet.md")
            _write_json(project, _project_status())
            _write_json(audit, _gate_audit())
            _write_json(manifest, _target_manifest())
            _write_json(guard, _wrapper_guard_audit())
            _write_text(pending, "out/t0.a3m\nout/t0.a3m.report.json\nout/t1.a3m\nout/t1.a3m.report.json\n")
            _write_text(submit, _submit_script())
            _write_text(sync, _sync_script())

            rc = main([
                "--project-status", project,
                "--gate-audit", audit,
                "--target-manifest", manifest,
                "--wrapper-guard-audit", guard,
                "--pending-paths", pending,
                "--submit-wrapper", submit,
                "--sync-back-script", sync,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            with open(out_json) as fh:
                rep = json.load(fh)
        self.assertTrue(rep["approval_packet_ready"])


if __name__ == "__main__":
    unittest.main()
