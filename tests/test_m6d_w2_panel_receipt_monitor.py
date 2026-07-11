"""Tests for W2 panel receipt monitor."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_receipt_monitor import (
    build_monitor,
    main,
    render_markdown,
    render_sync_plan,
)


RECEIPT = "results/receipt.jsonl"
SUMMARY = "results/summary.json"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class M6DW2PanelReceiptMonitorTests(unittest.TestCase):
    def test_absent_local_and_remote_receipts_are_not_submitted(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            os.makedirs(local)
            os.makedirs(remote)

            rep = build_monitor(local_root=local, remote_root=remote, receipt_path=RECEIPT, summary_path=SUMMARY)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "receipt_absent_not_submitted")
        self.assertFalse(rep["submitted"])
        self.assertFalse(rep["can_sync_receipt"])
        self.assertIn("No submit", render_markdown(rep))

    def test_remote_receipt_pair_is_ready_for_receipt_only_sync(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            os.makedirs(local)
            _write(os.path.join(remote, RECEIPT), "{}\n")
            _write(os.path.join(remote, SUMMARY), json.dumps({"status": "submitted_on_cayuga"}) + "\n")

            rep = build_monitor(
                local_root=local,
                remote_root=remote,
                receipt_path=RECEIPT,
                summary_path=SUMMARY,
                sync_plan_path="sync.sh",
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "remote_receipt_ready_for_monitor_sync")
        self.assertTrue(rep["submitted"])
        self.assertTrue(rep["can_sync_receipt"])
        self.assertFalse(rep["can_run_job_state_probe"])
        plan = render_sync_plan(
            receipt_path=RECEIPT,
            summary_path=SUMMARY,
            expected_workstream="custom_w2_panel",
            job_state_probe="results/custom_job_states.json",
            job_state_probe_md="results/custom_job_states.md",
            job_state_query="results/custom_job_query.sh",
            sacct_states="results/custom_sacct.tsv",
        )
        self.assertIn("rsync -avP", plan)
        self.assertIn("m6d_w2_panel_job_state_probe", plan)
        self.assertIn("EXPECTED_WORKSTREAM=custom_w2_panel", plan)
        self.assertIn('JOB_STATE_PROBE=results/custom_job_states.json', plan)
        self.assertIn('--expected-workstream "$EXPECTED_WORKSTREAM"', plan)
        self.assertIn('--emit-query-plan "$JOB_STATE_QUERY"', plan)

    def test_matching_local_and_remote_receipts_are_ready_for_job_state_probe(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            for root in [local, remote]:
                _write(os.path.join(root, RECEIPT), "{}\n")
                _write(os.path.join(root, SUMMARY), "{\"status\":\"submitted_on_cayuga\"}\n")

            rep = build_monitor(local_root=local, remote_root=remote, receipt_path=RECEIPT, summary_path=SUMMARY)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "local_receipt_ready_for_job_state_probe")
        self.assertTrue(rep["can_run_job_state_probe"])
        self.assertFalse(rep["can_sync_receipt"])

    def test_digest_mismatch_blocks_monitoring(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            _write(os.path.join(local, RECEIPT), "local\n")
            _write(os.path.join(local, SUMMARY), "same\n")
            _write(os.path.join(remote, RECEIPT), "remote\n")
            _write(os.path.join(remote, SUMMARY), "same\n")

            rep = build_monitor(local_root=local, remote_root=remote, receipt_path=RECEIPT, summary_path=SUMMARY)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "receipt_monitor_blocked")
        self.assertIn("receipt_digest_mismatch", {failure["kind"] for failure in rep["failures"]})

    def test_cli_writes_monitor_and_sync_plan(self):
        with tempfile.TemporaryDirectory() as d:
            local = os.path.join(d, "local")
            remote = os.path.join(d, "remote")
            out_json = os.path.join(d, "monitor.json")
            out_md = os.path.join(d, "monitor.md")
            sync_plan = os.path.join(d, "sync.sh")
            os.makedirs(local)
            os.makedirs(remote)

            rc = main([
                "--local-root", local,
                "--remote-host", "",
                "--remote-root", remote,
                "--receipt", RECEIPT,
                "--summary", SUMMARY,
                "--emit-sync-plan", sync_plan,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["status"], "receipt_absent_not_submitted")
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.access(sync_plan, os.X_OK))


if __name__ == "__main__":
    unittest.main()
