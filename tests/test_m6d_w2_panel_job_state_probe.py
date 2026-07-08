"""Tests for W2 panel Slurm job-state probe."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe import (
    build_probe,
    main,
    render_markdown,
    render_query_plan,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _rows():
    return [
        {
            "status": "submitted",
            "workstream": "m6d_w2_target_family_redesign_v11",
            "target_id": "t0",
            "proteinmpnn_job_id": "100",
            "boltz_job_id": "101",
        },
        {
            "status": "submitted",
            "workstream": "m6d_w2_target_family_redesign_v11",
            "target_id": "t1",
            "proteinmpnn_job_id": "102",
            "boltz_job_id": "103",
        },
    ]


class M6DW2PanelJobStateProbeTests(unittest.TestCase):
    def test_absent_receipt_is_not_submitted(self):
        rep = build_probe(receipt_path="/tmp/missing_w2_v11_receipt.jsonl")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "receipt_absent_not_submitted")
        self.assertFalse(rep["submitted"])
        self.assertEqual(rep["n_states"], 0)
        self.assertEqual(rep["states"], {})
        self.assertIn("No submit", render_markdown(rep))

    def test_valid_receipt_emits_query_command_without_states(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            _write_jsonl(receipt, _rows())

            rep = build_probe(receipt_path=receipt, query_plan_path="query.sh")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "receipt_ready_for_state_query")
        self.assertEqual(rep["n_jobs"], 4)
        self.assertEqual(rep["job_ids"], ["100", "101", "102", "103"])
        self.assertIn("sacct -P -j 100,101,102,103", rep["sacct_query_command"])
        plan = render_query_plan(rep["job_ids"], out_tsv="states.tsv", receipt_path=receipt)
        self.assertIn("Last rendered job-id preview: 100,101,102,103", plan)
        self.assertIn("m6d_w2_panel_job_state_probe", plan)
        self.assertIn('sacct -P -j "$job_ids"', plan)

    def test_sacct_output_builds_postsubmit_compatible_states(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            _write_jsonl(receipt, _rows())
            sacct_output = "\n".join([
                "JobIDRaw|State|ExitCode|Elapsed|NodeList",
                "100|COMPLETED|0:0|00:01:00|node1",
                "101.batch|COMPLETED|0:0|00:02:00|node1",
                "102|RUNNING|0:0|00:03:00|node2",
                "103|PENDING|0:0|00:00:00|",
                "",
            ])

            rep = build_probe(receipt_path=receipt, sacct_output=sacct_output)

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "job_states_collected")
        self.assertEqual(
            rep["states"],
            {"100": "COMPLETED", "101": "COMPLETED", "102": "RUNNING", "103": "PENDING"},
        )
        self.assertIn("--job-states", rep["postsubmit_status_command"])

    def test_rendered_query_plan_runs_receipt_to_probe_with_fake_sacct(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            out_tsv = os.path.join(d, "states.tsv")
            out_json = os.path.join(d, "probe.json")
            out_md = os.path.join(d, "probe.md")
            query = os.path.join(d, "query.sh")
            fakebin = os.path.join(d, "bin")
            _write_jsonl(receipt, _rows())
            _write(query, render_query_plan(
                [],
                receipt_path=receipt,
                out_tsv=out_tsv,
                out_json=out_json,
                out_md=out_md,
            ))
            os.chmod(query, 0o755)
            _write(os.path.join(fakebin, "sacct"), "\n".join([
                "#!/usr/bin/env bash",
                "printf '%s\\n' 'JobIDRaw|State|ExitCode|Elapsed|NodeList'",
                "printf '%s\\n' '100|COMPLETED|0:0|00:01:00|node1'",
                "printf '%s\\n' '101.batch|COMPLETED|0:0|00:02:00|node1'",
                "printf '%s\\n' '102|RUNNING|0:0|00:03:00|node2'",
                "printf '%s\\n' '103|PENDING|0:0|00:00:00|'",
                "",
            ]))
            os.chmod(os.path.join(fakebin, "sacct"), 0o755)
            env = dict(os.environ)
            env["PATH"] = fakebin + os.pathsep + env.get("PATH", "")
            env["BIO_SFM_PYTHON"] = sys.executable
            env["PYTHONPATH"] = os.getcwd() + "/src"

            proc = subprocess.run(
                ["bash", query],
                check=False,
                cwd=os.getcwd(),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["status"], "job_states_collected")
            self.assertEqual(saved["states"]["100"], "COMPLETED")
            self.assertEqual(saved["states"]["101"], "COMPLETED")
            self.assertEqual(saved["states"]["102"], "RUNNING")
            self.assertEqual(saved["states"]["103"], "PENDING")
            self.assertTrue(os.path.exists(out_tsv))
            self.assertTrue(os.path.exists(out_md))

    def test_bad_receipt_blocks_probe(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            rows = _rows()
            rows[0]["boltz_job_id"] = "bad id"
            rows[1]["workstream"] = "wrong"
            _write_jsonl(receipt, rows)

            rep = build_probe(receipt_path=receipt)

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "job_state_probe_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("receipt_bad_job_id", kinds)
        self.assertIn("receipt_row_workstream_mismatch", kinds)

    def test_cli_writes_absent_receipt_probe_and_query_plan(self):
        with tempfile.TemporaryDirectory() as d:
            out_json = os.path.join(d, "probe.json")
            out_md = os.path.join(d, "probe.md")
            query = os.path.join(d, "query.sh")

            rc = main([
                "--receipt", os.path.join(d, "missing.jsonl"),
                "--emit-query-plan", query,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["status"], "receipt_absent_not_submitted")
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.access(query, os.X_OK))
            with open(query) as fh:
                script = fh.read()
            self.assertIn("submit receipt is missing", script)
            self.assertIn("m6d_w2_panel_job_state_probe", script)


if __name__ == "__main__":
    unittest.main()
