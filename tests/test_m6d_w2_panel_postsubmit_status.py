"""Tests for W2 panel postsubmit receipt status."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status import (
    build_status,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _manifest():
    return {
        "targets": [
            {
                "id": "t0",
                "prepared_pdb": "targets/t0.pdb",
                "target_msa": "targets/t0.a3m",
                "records": "records/t0.jsonl",
            },
            {
                "id": "t1",
                "prepared_pdb": "targets/t1.pdb",
                "target_msa": "targets/t1.a3m",
                "records": "records/t1.jsonl",
            },
        ],
    }


def _rows():
    return [
        {
            "artifact": "m6d_w2_target_family_redesign_v11_submit_record",
            "status": "submitted",
            "workstream": "m6d_w2_target_family_redesign_v11",
            "target_id": "t0",
            "proteinmpnn_job_id": "100",
            "boltz_job_id": "101",
            "prepared_pdb": "targets/t0.pdb",
            "target_msa": "targets/t0.a3m",
            "records": "records/t0.jsonl",
        },
        {
            "artifact": "m6d_w2_target_family_redesign_v11_submit_record",
            "status": "submitted",
            "workstream": "m6d_w2_target_family_redesign_v11",
            "target_id": "t1",
            "proteinmpnn_job_id": "102",
            "boltz_job_id": "103",
            "prepared_pdb": "targets/t1.pdb",
            "target_msa": "targets/t1.a3m",
            "records": "records/t1.jsonl",
        },
    ]


def _summary(receipt):
    return {
        "artifact": "m6d_w2_target_family_redesign_v11_submit_receipt_summary",
        "status": "submitted_on_cayuga",
        "manifest": "manifest.json",
        "receipt": receipt,
        "workstream": "m6d_w2_target_family_redesign_v11",
        "n_targets": 2,
        "n_records": 2,
        "targets": [
            {"target_id": "t0", "proteinmpnn_job_id": "100", "boltz_job_id": "101", "records": "records/t0.jsonl"},
            {"target_id": "t1", "proteinmpnn_job_id": "102", "boltz_job_id": "103", "records": "records/t1.jsonl"},
        ],
    }


class M6DW2PanelPostsubmitStatusTests(unittest.TestCase):
    def test_absent_receipt_is_not_submitted_and_not_sync_ready(self):
        rep = build_status(_manifest(), receipt_path="/tmp/missing_receipt.jsonl", summary_path="/tmp/missing_summary.json")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "not_submitted")
        self.assertFalse(rep["submitted"])
        self.assertFalse(rep["sync_ready"])
        self.assertIn("No submit", render_markdown(rep))

    def test_valid_receipt_without_states_is_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            _write_jsonl(receipt, _rows())
            _write_json(summary, _summary(receipt))

            rep = build_status(_manifest(), receipt_path=receipt, summary_path=summary)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "submitted_jobs_unverified")
        self.assertTrue(rep["submitted"])
        self.assertFalse(rep["sync_ready"])

    def test_append_only_stage_journal_is_accepted_after_pair_completion(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            rows = []
            for pair in _rows():
                protein = dict(pair)
                protein["stage"] = "proteinmpnn_submitted"
                protein["status"] = "proteinmpnn_submitted"
                protein["boltz_job_id"] = None
                rows.append(protein)
                complete = dict(pair)
                complete["stage"] = "pair_submitted"
                complete["status"] = "pair_submitted"
                rows.append(complete)
            _write_jsonl(receipt, rows)
            journal_summary = _summary(receipt)
            journal_summary["n_receipt_events"] = 4
            journal_summary["receipt_format"] = "append_only_stage_journal_v1"
            _write_json(summary, journal_summary)

            rep = build_status(_manifest(), receipt_path=receipt, summary_path=summary)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "submitted_jobs_unverified")

    def test_partial_journal_target_blocks_submitted_status(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            rows = _rows()
            rows[0]["stage"] = "proteinmpnn_submitted"
            rows[0]["status"] = "proteinmpnn_submitted"
            rows[0]["boltz_job_id"] = None
            _write_jsonl(receipt, rows)
            _write_json(summary, _summary(receipt))

            rep = build_status(_manifest(), receipt_path=receipt, summary_path=summary)

        self.assertFalse(rep["audit_ok"])
        self.assertIn("receipt_missing_targets", {failure["kind"] for failure in rep["failures"]})

    def test_completed_states_are_sync_ready(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            _write_jsonl(receipt, _rows())
            _write_json(summary, _summary(receipt))

            rep = build_status(
                _manifest(),
                receipt_path=receipt,
                summary_path=summary,
                job_states={"states": {"100": "COMPLETED", "101": "COMPLETED", "102": "CD", "103": "CD"}},
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "submitted_jobs_complete_ready_for_sync")
        self.assertTrue(rep["sync_ready"])
        self.assertEqual(rep["job_state_report"]["counts"]["complete"], 4)

    def test_failed_state_blocks_sync(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            _write_jsonl(receipt, _rows())
            _write_json(summary, _summary(receipt))

            rep = build_status(
                _manifest(),
                receipt_path=receipt,
                summary_path=summary,
                job_states={"states": {"100": "COMPLETED", "101": "FAILED", "102": "CD", "103": "CD"}},
            )

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "postsubmit_status_blocked")
        self.assertFalse(rep["sync_ready"])
        self.assertIn("submitted_job_failed", {failure["kind"] for failure in rep["failures"]})

    def test_receipt_manifest_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            rows = _rows()
            rows[0]["records"] = "wrong.jsonl"
            _write_jsonl(receipt, rows)
            _write_json(summary, _summary(receipt))

            rep = build_status(_manifest(), receipt_path=receipt, summary_path=summary)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "postsubmit_status_blocked")
        self.assertIn("receipt_manifest_field_mismatch", {failure["kind"] for failure in rep["failures"]})

    def test_cli_writes_not_submitted_status(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            out_json = os.path.join(d, "status.json")
            out_md = os.path.join(d, "status.md")
            _write_json(manifest, _manifest())

            rc = main([
                "--manifest", manifest,
                "--receipt", os.path.join(d, "missing_receipt.jsonl"),
                "--summary", os.path.join(d, "missing_summary.json"),
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["status"], "not_submitted")
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
