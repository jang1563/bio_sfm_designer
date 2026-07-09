"""Tests for W2 v11 post-sync panel interpretation."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation import (
    build_interpretation,
    main,
    render_replay_script,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, sort_keys=True)
        fh.write("\n")


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _manifest(root, n=2):
    targets = []
    for i in range(n):
        target_id = f"t{i}"
        records = os.path.join(root, "records", target_id, "records_boltz_complex.jsonl")
        targets.append({"id": target_id, "records": records, "out_prefix": os.path.dirname(records)})
    return {"targets": targets}


def _postsubmit(sync_ready):
    return {
        "status": "sync_ready" if sync_ready else "not_submitted",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "sync_ready": sync_ready,
        "can_claim_w2_generalization": False,
    }


def _panel_report():
    targets = [
        {"complex_target_id": "t0", "certified": True},
        {"complex_target_id": "t1", "certified": True},
    ]
    return {
        "ok": True,
        "panel_status": "multi_target_certified",
        "target_alpha": 0.2,
        "n_targets": 2,
        "targets": targets,
        "failures": [],
    }


def _completion_report():
    return {
        "ok": True,
        "status": "ready_for_panel_report",
        "n_completed_targets": 2,
        "n_manifest_targets": 2,
        "failures": [],
    }


class M6DW2PanelPostsyncInterpretationTests(unittest.TestCase):
    def test_not_sync_ready_is_not_interpretable_but_audits_clean(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            postsubmit = os.path.join(d, "postsubmit.json")
            _write_json(manifest, _manifest(d))
            _write_json(postsubmit, _postsubmit(False))

            rep = build_interpretation(
                manifest_path=manifest,
                postsubmit_path=postsubmit,
                completion_path=os.path.join(d, "missing_completion.json"),
                panel_report_path=os.path.join(d, "missing_panel.json"),
                min_targets=2,
            )

        self.assertEqual(rep["status"], "not_synced_not_interpretable")
        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["can_claim_w2_generalization"])

    def test_sync_ready_records_present_waits_for_target_wise_panel_report(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            postsubmit = os.path.join(d, "postsubmit.json")
            obj = _manifest(d)
            _write_json(manifest, obj)
            _write_json(postsubmit, _postsubmit(True))
            for target in obj["targets"]:
                _write_jsonl(target["records"], [{"complex_target_id": target["id"]}])

            rep = build_interpretation(
                manifest_path=manifest,
                postsubmit_path=postsubmit,
                completion_path=os.path.join(d, "missing_completion.json"),
                panel_report_path=os.path.join(d, "missing_panel.json"),
                min_targets=2,
            )

        self.assertEqual(rep["status"], "ready_for_target_wise_panel_report")
        self.assertTrue(rep["audit_ok"])
        self.assertFalse(rep["can_claim_w2_generalization"])
        self.assertEqual(rep["completion_probe"]["n_completed_targets"], 2)

    def test_panel_report_classification_supports_w2_only_with_completion(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            postsubmit = os.path.join(d, "postsubmit.json")
            completion = os.path.join(d, "completion.json")
            panel = os.path.join(d, "panel.json")
            obj = _manifest(d)
            _write_json(manifest, obj)
            _write_json(postsubmit, _postsubmit(True))
            _write_json(completion, _completion_report())
            _write_json(panel, _panel_report())
            for target in obj["targets"]:
                _write_jsonl(target["records"], [{"complex_target_id": target["id"]}])

            rep = build_interpretation(
                manifest_path=manifest,
                postsubmit_path=postsubmit,
                completion_path=completion,
                panel_report_path=panel,
                min_targets=2,
                panel_label="W2 v11 Boltz-2 representative panel/protocol",
            )

        self.assertEqual(rep["status"], "w2_generalization_supported_by_target_wise_panel")
        self.assertTrue(rep["can_claim_w2_generalization"])
        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["panel_label"], "W2 v11 Boltz-2 representative panel/protocol")
        self.assertIn("W2 v11 Boltz-2 representative panel/protocol", rep["current_panel_result"]["claim"])

    def test_replay_script_requires_sync_ready_and_refreshes_decision_protocol(self):
        script = render_replay_script(
            manifest="custom/manifest.json",
            receipt="custom/receipt.jsonl",
            summary="custom/summary.json",
            postsubmit="custom/postsubmit.json",
            job_states="custom/job_states.json",
            records=["a/records.jsonl", "b/records.jsonl"],
            min_targets=2,
            panel_label="W2 v11 Boltz-2 representative panel/protocol",
        )

        self.assertIn("--require-sync-ready", script)
        self.assertIn("MANIFEST=custom/manifest.json", script)
        self.assertIn("RECEIPT=custom/receipt.jsonl", script)
        self.assertIn("SUMMARY=custom/summary.json", script)
        self.assertIn("POSTSUBMIT=custom/postsubmit.json", script)
        self.assertIn("JOB_STATES=custom/job_states.json", script)
        self.assertIn("COMPLETION_SCRIPT=results/m6d_w2_target_family_redesign_v11_panel_completion.sh", script)
        self.assertIn("COMPLETION_REPORT=results/m6d_w2_target_family_redesign_v11_panel_completion.json", script)
        self.assertIn("--manifest \"$MANIFEST\"", script)
        self.assertIn("--receipt \"$RECEIPT\"", script)
        self.assertIn("--summary \"$SUMMARY\"", script)
        self.assertIn("--job-states \"$JOB_STATES\"", script)
        self.assertIn("--out-json \"$POSTSUBMIT\"", script)
        self.assertLess(
            script.index("bash \"$COMPLETION_SCRIPT\""),
            script.index("complex_panel_report"),
        )
        self.assertLess(
            script.index("test -s \"$COMPLETION_REPORT\""),
            script.index("complex_panel_report"),
        )
        self.assertIn("complex_panel_report", script)
        self.assertIn("m6d_w2_panel_decision_protocol", script)
        self.assertIn("m6d_w2_panel_postsync_interpretation", script)
        self.assertIn("--panel-label 'W2 v11 Boltz-2 representative panel/protocol'", script)

    def test_cli_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            postsubmit = os.path.join(d, "postsubmit.json")
            out_json = os.path.join(d, "interpretation.json")
            out_md = os.path.join(d, "interpretation.md")
            replay = os.path.join(d, "interpretation.sh")
            _write_json(manifest, _manifest(d))
            _write_json(postsubmit, _postsubmit(False))

            rc = main([
                "--manifest", manifest,
                "--postsubmit-status", postsubmit,
                "--job-states", os.path.join(d, "job_states.json"),
                "--receipt", os.path.join(d, "receipt.jsonl"),
                "--summary", os.path.join(d, "summary.json"),
                "--completion", os.path.join(d, "missing_completion.json"),
                "--panel-report", os.path.join(d, "missing_panel.json"),
                "--min-targets", "2",
                "--panel-label", "W2 v11 Boltz-2 representative panel/protocol",
                "--emit-replay-script", replay,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            with open(out_json) as fh:
                saved = json.load(fh)
            with open(out_md) as fh:
                md = fh.read()
            with open(replay) as fh:
                replay_text = fh.read()
            replay_exists = os.path.exists(replay)

        self.assertEqual(rc, 0)
        self.assertEqual(saved["status"], "not_synced_not_interpretable")
        self.assertEqual(saved["panel_label"], "W2 v11 Boltz-2 representative panel/protocol")
        self.assertIn("Post-Sync Interpretation", md)
        self.assertIn("W2 v11 Boltz-2 representative panel/protocol", md)
        self.assertTrue(replay_exists)
        self.assertIn("--receipt \"$RECEIPT\"", replay_text)
        self.assertIn("--summary \"$SUMMARY\"", replay_text)
        self.assertIn("--panel-label 'W2 v11 Boltz-2 representative panel/protocol'", replay_text)


if __name__ == "__main__":
    unittest.main()
