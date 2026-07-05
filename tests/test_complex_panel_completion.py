"""Tests for validating completed multi-target panel outputs."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_panel_completion import run_completion


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


def _target(d, tid, *, records=None, out_prefix=None):
    target = {
        "id": tid,
        "prepared_pdb": os.path.join(d, f"{tid}.pdb"),
        "target_chain": "A",
        "binder_chain": "B",
        "target_fasta": os.path.join(d, f"{tid}.fasta"),
        "target_msa": os.path.join(d, f"{tid}.a3m"),
    }
    if records is not None:
        target["records"] = records
    if out_prefix is not None:
        target["out_prefix"] = out_prefix
    return target


class ComplexPanelCompletionTests(unittest.TestCase):
    def test_three_completed_targets_emit_panel_report_command(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for tid in ("t0", "t1", "t2"):
                records = os.path.join(d, tid, "records.jsonl")
                _write_jsonl(records, [{"complex_target_id": tid, "target_id": f"{tid}-0"}])
                targets.append(_target(d, tid, records=records))
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": targets})

            rep = run_completion(
                manifest,
                min_targets=3,
                min_records_per_target=1,
                panel_out=os.path.join(d, "panel.json"),
            )

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["status"], "ready_for_panel_report")
        self.assertEqual(rep["n_completed_targets"], 3)
        self.assertIn("complex_panel_report", rep["panel_report_command"])
        self.assertIn("--min-records-per-target 1", rep["panel_report_command"])
        self.assertIn("Panel records are present", rep["shell_plan"])

    def test_missing_target_record_blocks_panel_report(self):
        with tempfile.TemporaryDirectory() as d:
            records0 = os.path.join(d, "t0", "records.jsonl")
            records1 = os.path.join(d, "t1", "records.jsonl")
            missing = os.path.join(d, "t2", "records.jsonl")
            _write_jsonl(records0, [{"complex_target_id": "t0"}])
            _write_jsonl(records1, [{"complex_target_id": "t1"}])
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": [
                _target(d, "t0", records=records0),
                _target(d, "t1", records=records1),
                _target(d, "t2", records=missing),
            ]})

            rep = run_completion(manifest, min_targets=3)

        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("missing_file", kinds)
        self.assertIn("too_few_completed_targets", kinds)
        self.assertIn("sync/fix", rep["next_action"])

    def test_wrong_complex_target_id_blocks_wrong_sync(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for tid in ("t0", "t1", "t2"):
                records = os.path.join(d, tid, "records.jsonl")
                row_tid = "other" if tid == "t1" else tid
                _write_jsonl(records, [{"complex_target_id": row_tid}])
                targets.append(_target(d, tid, records=records))
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": targets})

            rep = run_completion(manifest, min_targets=3)

        self.assertFalse(rep["ok"])
        mismatch = [f for f in rep["failures"] if f["kind"] == "complex_target_id_mismatch"]
        self.assertEqual(mismatch[0]["target_id"], "t1")
        self.assertEqual(rep["records"][1]["other_complex_target_ids"], ["other"])

    def test_default_records_path_uses_out_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for tid in ("t0", "t1", "t2"):
                out_prefix = os.path.join(d, "panel out", tid)
                records = os.path.join(out_prefix, "records_boltz_complex.jsonl")
                _write_jsonl(records, [{"complex_target_id": tid}])
                targets.append(_target(d, tid, out_prefix=out_prefix))
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": targets})

            rep = run_completion(manifest, min_targets=3)

        self.assertTrue(rep["ok"])
        self.assertIn("panel out", rep["panel_report_command"])
        self.assertIn("'", rep["panel_report_command"])
        self.assertEqual(len(rep["expected_records"]), 3)

    def test_selected_target_subset_ignores_unrun_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            good_records = os.path.join(d, "t0", "records.jsonl")
            missing_records = os.path.join(d, "placeholder", "records.jsonl")
            _write_jsonl(good_records, [{"complex_target_id": "t0"}])
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": [
                _target(d, "t0", records=good_records),
                _target(d, "placeholder", records=missing_records),
            ]})

            rep = run_completion(
                manifest,
                target_ids=["t0"],
                min_targets=1,
                min_records_per_target=1,
            )

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["target_ids"], ["t0"])
        self.assertEqual(rep["n_manifest_targets"], 1)
        self.assertEqual(rep["n_completed_targets"], 1)
        self.assertNotIn("placeholder", rep["panel_report_command"])

    def test_missing_selected_target_blocks_completion(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": [_target(d, "t0", records=os.path.join(d, "t0.jsonl"))]})

            rep = run_completion(manifest, target_ids=["absent"], min_targets=1)

        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("missing_target", kinds)
        self.assertIn("too_few_completed_targets", kinds)

    def test_shell_plan_preserves_completion_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for tid in ("t0", "t1"):
                records = os.path.join(d, tid, "records.jsonl")
                _write_jsonl(records, [{"complex_target_id": "wrong"}])
                targets.append(_target(d, tid, records=records))
            manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "completion report.json")
            panel_out = os.path.join(d, "panel report.json")
            _write_json(manifest, {"targets": targets})

            rep = run_completion(
                manifest,
                target_ids=["t0", "t1"],
                min_targets=2,
                min_records_per_target=7,
                target_alpha=0.1,
                panel_out=panel_out,
                check_target_ids=False,
                out_path=out,
            )

        self.assertTrue(rep["ok"])
        self.assertIn("--min-targets 2", rep["shell_plan"])
        self.assertIn("--min-records-per-target 7", rep["shell_plan"])
        self.assertIn("--target-alpha 0.1", rep["shell_plan"])
        self.assertIn("--panel-out", rep["shell_plan"])
        self.assertIn("panel report.json'", rep["shell_plan"])
        self.assertIn("--out", rep["shell_plan"])
        self.assertIn("completion report.json'", rep["shell_plan"])
        self.assertIn("--target-id t0 --target-id t1", rep["shell_plan"])
        self.assertIn("--no-check-target-ids", rep["shell_plan"])
        self.assertIn("target-id check was disabled", rep["shell_plan"])


if __name__ == "__main__":
    unittest.main()
