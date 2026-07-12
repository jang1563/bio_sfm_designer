"""Tests for validating synced target input-prep artifacts."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_input_prep_completion import main, render_pending_paths, run_completion


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_text(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _report(d, artifacts, **overrides):
    obj = {
        "manifest": os.path.join(d, "targets.json"),
        "min_targets": 1,
        "min_contacts": 2,
        "require_records": False,
        "target_ids": ["t0"],
        "input_prep_artifacts": artifacts,
    }
    obj.update(overrides)
    return obj


class ComplexInputPrepCompletionTests(unittest.TestCase):
    def test_ready_artifacts_emit_manifest_command(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "source_pdb": os.path.join(d, "source.pdb"),
                "prepared_pdb": os.path.join(d, "prepared.pdb"),
                "target_fasta": os.path.join(d, "target.fasta"),
                "target_msa": os.path.join(d, "target.a3m"),
                "target_msa_report": os.path.join(d, "target.a3m.report.json"),
            }
            for path in paths.values():
                _write_text(path)
            artifacts = [{"target_id": "t0", "field": field, "path": path}
                         for field, path in paths.items()]
            report_path = os.path.join(d, "manifest report.json")
            _write_json(report_path, _report(d, artifacts))

            rep = run_completion(report_path, out_path=os.path.join(d, "completion.json"))

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["status"], "ready_for_require_files")
        self.assertEqual(rep["n_artifacts"], 5)
        self.assertEqual(rep["n_nonempty"], 5)
        self.assertEqual(rep["n_missing"], 0)
        self.assertEqual(rep["n_empty"], 0)
        self.assertEqual(rep["ready_targets"], ["t0"])
        self.assertEqual(rep["blocked_targets"], [])
        self.assertEqual(rep["artifacts_by_target"]["t0"]["pending_fields"], [])
        self.assertEqual(rep["pending_artifacts"], [])
        self.assertIn("complex_target_manifest", rep["manifest_command"])
        self.assertIn("--require-files", rep["manifest_command"])
        self.assertIn("--min-contacts 2", rep["manifest_command"])
        self.assertIn("manifest report.json'", rep["manifest_command"])
        self.assertIn("Input-prep files are present", rep["shell_plan"])

    def test_missing_and_empty_artifacts_block_before_manifest_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.pdb")
            empty = os.path.join(d, "empty.a3m")
            missing = os.path.join(d, "missing.a3m.report.json")
            _write_text(good)
            _write_text(empty, "")
            report_path = os.path.join(d, "report.json")
            _write_json(report_path, _report(d, [
                {"target_id": "t0", "field": "prepared_pdb", "path": good},
                {"target_id": "t0", "field": "target_msa", "path": empty},
                {"target_id": "t0", "field": "target_msa_report", "path": missing},
            ]))

            rep = run_completion(report_path, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertEqual(rep["n_present"], 2)
        self.assertEqual(rep["n_nonempty"], 1)
        self.assertEqual(rep["n_missing"], 1)
        self.assertEqual(rep["n_empty"], 1)
        self.assertEqual(rep["ready_targets"], [])
        self.assertEqual(rep["blocked_targets"], ["t0"])
        self.assertEqual(rep["artifacts_by_target"]["t0"]["pending_fields"],
                         ["target_msa", "target_msa_report"])
        self.assertEqual(
            [(a["field"], a["error"]) for a in rep["pending_artifacts"]],
            [("target_msa", "empty_file"), ("target_msa_report", "missing_file")],
        )
        self.assertEqual(
            [(a["field"], a["declared_path"]) for a in rep["pending_artifacts"]],
            [("target_msa", empty), ("target_msa_report", missing)],
        )
        self.assertEqual(render_pending_paths(rep), empty + "\n" + missing + "\n")
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("missing_file", kinds)
        self.assertIn("empty_file", kinds)
        self.assertIn("sync/fix", rep["next_action"])
        self.assertIn("Missing or empty input-prep artifacts", rep["shell_plan"])
        self.assertIn("# pending_input_prep_files", rep["shell_plan"])

    def test_target_subset_filters_report_and_preserves_replay_flag(self):
        with tempfile.TemporaryDirectory() as d:
            t0 = os.path.join(d, "t0.a3m")
            t1 = os.path.join(d, "t1.a3m")
            _write_text(t0)
            report_path = os.path.join(d, "report.json")
            _write_json(report_path, _report(d, [
                {"target_id": "t0", "field": "target_msa", "path": t0},
                {"target_id": "t1", "field": "target_msa", "path": t1},
            ], target_ids=None))

            rep = run_completion(report_path, out_path=os.path.join(d, "completion.json"),
                                 target_ids=["t0"])

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["target_ids"], ["t0"])
        self.assertEqual(rep["n_artifacts"], 1)
        self.assertIn("--target-id t0", rep["shell_plan"])
        self.assertIn("--target-id t0", rep["manifest_command"])
        self.assertNotIn("t1", rep["manifest_command"])

    def test_missing_input_prep_list_is_schema_error(self):
        with tempfile.TemporaryDirectory() as d:
            report_path = os.path.join(d, "old_report.json")
            _write_json(report_path, {"manifest": os.path.join(d, "targets.json")})

            with self.assertRaises(ValueError):
                run_completion(report_path)

    def test_cli_writes_blocked_report_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "missing.a3m")
            report_path = os.path.join(d, "report.json")
            out = os.path.join(d, "completion.json")
            plan = os.path.join(d, "completion.sh")
            pending_paths = os.path.join(d, "pending_paths.txt")
            _write_json(report_path, _report(d, [
                {"target_id": "t0", "field": "target_msa", "path": missing},
            ]))

            with self.assertRaises(SystemExit) as cm:
                main([
                    "--report", report_path,
                    "--out", out,
                    "--emit-plan", plan,
                    "--emit-pending-paths", pending_paths,
                ])

            with open(out) as fh:
                saved = json.load(fh)
            with open(plan) as fh:
                shell_plan = fh.read()
            with open(pending_paths) as fh:
                pending_text = fh.read()

        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["failures"][0]["kind"], "missing_file")
        self.assertEqual(pending_text, missing + "\n")
        self.assertIn("complex_input_prep_completion", shell_plan)
        self.assertIn("--emit-pending-paths", shell_plan)
        self.assertIn("pending_paths.txt", shell_plan)


if __name__ == "__main__":
    unittest.main()
