"""Tests for the M6d W2 v9 target-MSA gate audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_msa_gate_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_text(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _anchor():
    return {
        "current_status": {
            "goal_progress": (
                "w2_target_family_redesign_v9_target_msa_presubmit_and_postsubmit_replay_ready_"
                "awaiting_explicit_submission_approval"
            )
        },
        "w2_decision_path": {
            "target_family_redesign_v9": {
                "status": "target_msa_submit_and_postsubmit_replay_ready_awaiting_explicit_submission_approval"
            }
        },
    }


def _project_level_anchor():
    return {
        "current_status": {
            "goal_progress": "local_artifact_work_required",
            "project_status_w2": "target_msa_gate_ready_awaiting_explicit_approval",
            "remaining_requirements": 1,
        },
        "w2_decision_path": {
            "target_family_redesign_v9": {
                "status": "target_msa_submit_and_postsubmit_replay_ready_awaiting_explicit_submission_approval"
            }
        },
    }


def _presubmit():
    return {
        "status": "ready_for_explicitly_approved_target_msa_submission_only",
        "explicit_submit_approval_required": True,
        "next_command_if_approved": (
            "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_TARGET_MSA="
            "approve-v9-target-msa-precompute bash target_msa.sh'"
        ),
        "preflight": {
            "dry_run_passed_on_cayuga": True,
            "boltz_runtime_executable_on_cayuga": True,
            "helper_scripts_present_on_cayuga": True,
            "local_remote_anchor_match": True,
            "input_prep_missing_on_cayuga": 0,
            "manifest_targets": 2,
        },
        "target_ids": ["t0", "t1"],
    }


def _completion():
    return {
        "status": "blocked",
        "ok": False,
        "n_artifacts": 14,
        "n_nonempty": 10,
        "n_missing": 4,
        "n_empty": 0,
        "pending_artifacts": [
            {"target_id": "t0", "field": "target_msa", "declared_path": "out/t0.a3m"},
            {"target_id": "t0", "field": "target_msa_report", "declared_path": "out/t0.a3m.report.json"},
            {"target_id": "t1", "field": "target_msa", "declared_path": "out/t1.a3m"},
            {"target_id": "t1", "field": "target_msa_report", "declared_path": "out/t1.a3m.report.json"},
        ],
    }


def _postsubmit(pending_paths, script):
    return {
        "status": "postsubmit_replay_ready_awaiting_target_msa_submission_and_completion",
        "pending_input_prep_paths": pending_paths,
        "pending_input_prep_path_count": 4,
        "pre_submit_command_if_approved": (
            "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_TARGET_MSA="
            "approve-v9-target-msa-precompute bash target_msa.sh'"
        ),
        "sync_back_script": script,
        "sync_back_command_after_jobs_finish": "bash sync.sh",
    }


def _manifest():
    return {
        "ok": False,
        "n_ready_targets": 0,
        "n_targets": 2,
        "failures": [
            {"kind": "missing_file"},
            {"kind": "missing_file"},
            {"kind": "missing_file"},
            {"kind": "missing_file"},
        ],
    }


class M6DW2TargetMsaGateAuditTests(unittest.TestCase):
    def test_build_audit_accepts_expected_blocked_gate(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "sync.sh")
            _write_text(script)
            pending_path = os.path.join(d, "pending.txt")
            pending = ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"]
            _write_text(pending_path, "\n".join(pending) + "\n")

            rep = build_audit(
                _anchor(),
                _presubmit(),
                _completion(),
                _postsubmit(pending_path, script),
                _manifest(),
                pending,
                pending_paths_path=pending_path,
                expected_targets=2,
                expected_pending_paths=4,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "pre_submit_gate_ready_awaiting_explicit_approval")
        self.assertFalse(rep["ready_for_panel_submission"])
        self.assertTrue(rep["ready_for_target_msa_submission_if_explicitly_approved"])
        self.assertEqual(rep["pending_path_count"], 4)
        self.assertEqual(rep["observed_pending_fields"], ["target_msa", "target_msa_report"])
        self.assertEqual(rep["failures"], [])

    def test_build_audit_accepts_project_level_w2_ready_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "sync.sh")
            _write_text(script)
            pending_path = os.path.join(d, "pending.txt")
            pending = ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"]
            _write_text(pending_path, "\n".join(pending) + "\n")

            rep = build_audit(
                _project_level_anchor(),
                _presubmit(),
                _completion(),
                _postsubmit(pending_path, script),
                _manifest(),
                pending,
                pending_paths_path=pending_path,
                expected_targets=2,
                expected_pending_paths=4,
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["anchor_goal_progress_mode"], "project_level_w2_ready")

    def test_build_audit_blocks_when_pending_path_list_drifts(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "sync.sh")
            _write_text(script)
            pending_path = os.path.join(d, "pending.txt")
            pending = ["out/t0.a3m", "out/t1.a3m"]

            rep = build_audit(
                _anchor(),
                _presubmit(),
                _completion(),
                _postsubmit(pending_path, script),
                _manifest(),
                pending,
                pending_paths_path=pending_path,
                expected_targets=2,
                expected_pending_paths=4,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("pending_path_set_mismatch", kinds)
        self.assertIn("pending_path_count_mismatch", kinds)
        self.assertIn("completion_missing_count_mismatch", kinds)

    def test_build_audit_blocks_postsubmit_plan_without_approval_env(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "sync.sh")
            _write_text(script)
            pending_path = os.path.join(d, "pending.txt")
            pending = ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"]
            _write_text(pending_path, "\n".join(pending) + "\n")
            postsubmit = _postsubmit(pending_path, script)
            postsubmit["pre_submit_command_if_approved"] = "ssh ${CAYUGA_BIO_SFM_HOST} 'bash target_msa.sh'"

            rep = build_audit(
                _anchor(),
                _presubmit(),
                _completion(),
                postsubmit,
                _manifest(),
                pending,
                pending_paths_path=pending_path,
                expected_targets=2,
                expected_pending_paths=4,
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("postsubmit_presubmit_command_mismatch", kinds)
        self.assertIn("postsubmit_command_missing_approval_env", kinds)

    def test_render_markdown_contains_commands_and_boundary(self):
        rep = {
            "status": "pre_submit_gate_ready_awaiting_explicit_approval",
            "audit_ok": True,
            "target_count": 2,
            "pending_path_count": 4,
            "completion_counts": {"n_nonempty": 10, "n_missing": 4},
            "manifest_counts": {"n_failures": 4},
            "next_action": "await explicit approval",
            "submit_command_if_approved": (
                "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_TARGET_MSA="
                "approve-v9-target-msa-precompute bash target_msa.sh'"
            ),
            "postsubmit_sync_back_command": "bash sync.sh",
            "failures": [],
        }

        md = render_markdown(rep)

        self.assertIn("gate-consistency audit only", md)
        self.assertIn("ssh ${CAYUGA_BIO_SFM_HOST}", md)
        self.assertIn("bash sync.sh", md)

    def test_cli_writes_audit_files(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "anchor": os.path.join(d, "anchor.json"),
                "presubmit": os.path.join(d, "presubmit.json"),
                "completion": os.path.join(d, "completion.json"),
                "postsubmit": os.path.join(d, "postsubmit.json"),
                "manifest": os.path.join(d, "manifest.json"),
                "pending": os.path.join(d, "pending.txt"),
                "script": os.path.join(d, "sync.sh"),
                "out_json": os.path.join(d, "audit.json"),
                "out_md": os.path.join(d, "audit.md"),
            }
            pending = ["out/t0.a3m", "out/t0.a3m.report.json", "out/t1.a3m", "out/t1.a3m.report.json"]
            _write_json(paths["anchor"], _anchor())
            _write_json(paths["presubmit"], _presubmit())
            _write_json(paths["completion"], _completion())
            _write_json(paths["postsubmit"], _postsubmit(paths["pending"], paths["script"]))
            _write_json(paths["manifest"], _manifest())
            _write_text(paths["pending"], "\n".join(pending) + "\n")
            _write_text(paths["script"])

            rc = main([
                "--anchor", paths["anchor"],
                "--presubmit-preflight", paths["presubmit"],
                "--pre-sync-completion", paths["completion"],
                "--postsubmit-plan", paths["postsubmit"],
                "--manifest-post-msa", paths["manifest"],
                "--pending-paths", paths["pending"],
                "--sync-back-script", paths["script"],
                "--expected-targets", "2",
                "--expected-pending-paths", "4",
                "--out-json", paths["out_json"],
                "--out-md", paths["out_md"],
            ])

            with open(paths["out_json"]) as fh:
                saved = json.load(fh)
            out_md_exists = os.path.exists(paths["out_md"])

        self.assertEqual(rc, 0)
        self.assertTrue(saved["audit_ok"])
        self.assertTrue(out_md_exists)


if __name__ == "__main__":
    unittest.main()
