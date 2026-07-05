"""Tests for validating completed scale-batch outputs before posthoc."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_scale_completion import run_completion


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


class ComplexScaleCompletionTests(unittest.TestCase):
    def test_ready_records_emit_posthoc_action(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "old.jsonl")
            new = os.path.join(d, "new.jsonl")
            _write_jsonl(old, [{"design_id": "old-1", "complex_target_id": "1BRS_AD"}])
            _write_jsonl(new, [{"design_id": "new-1", "complex_target_id": "1BRS_AD"}])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "target_alpha": 0.2,
                "records": [old, new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records old new",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["status"], "ready_for_posthoc")
        self.assertEqual(rep["records"][0]["role"], "previous_record")
        self.assertEqual(rep["records"][1]["role"], "new_record")
        self.assertEqual(rep["records"][1]["n_rows"], 1)
        self.assertEqual(rep["records"][1]["n_matching_complex_target_id"], 1)
        self.assertIn("complex_posthoc_bundle", rep["posthoc_command"])
        self.assertIn("Records are present", rep["shell_plan"])

    def test_diagnostic_unchecked_plan_surfaces_warning(self):
        with tempfile.TemporaryDirectory() as d:
            new = os.path.join(d, "new.jsonl")
            _write_jsonl(new, [{"design_id": "new-1", "complex_target_id": "1BRS_AD"}])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "target_alpha": 0.2,
                "diagnostic_only": True,
                "unchecked_files_allowed": True,
                "diagnostic_reason": "saved without --require-files via --allow-unchecked-files",
                "records": [new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records new",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertTrue(rep["ok"])
        self.assertTrue(rep["diagnostic_only"])
        self.assertTrue(rep["unchecked_files_allowed"])
        self.assertIn("without --require-files", rep["diagnostic_reason"])
        self.assertIn("WARNING: diagnostic-only", rep["shell_plan"])

    def test_missing_new_record_blocks_before_posthoc(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "old.jsonl")
            new = os.path.join(d, "missing.jsonl")
            _write_jsonl(old, [{"design_id": "old-1", "complex_target_id": "1BRS_AD"}])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "records": [old, new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records old missing",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertEqual(rep["failures"][0]["role"], "new_record")
        self.assertEqual(rep["failures"][0]["error"], "missing_file")
        self.assertIn("sync or fix", rep["next_action"])
        self.assertIn("Missing, invalid, or target-mismatched records", rep["shell_plan"])

    def test_bad_jsonl_blocks_even_when_file_exists(self):
        with tempfile.TemporaryDirectory() as d:
            new = os.path.join(d, "bad.jsonl")
            os.makedirs(os.path.dirname(new), exist_ok=True)
            with open(new, "w") as fh:
                fh.write("{not-json}\n")
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "records": [new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records bad",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertIn("bad_jsonl", rep["failures"][0]["error"])

    def test_wrong_complex_target_id_blocks_wrong_sync(self):
        with tempfile.TemporaryDirectory() as d:
            new = os.path.join(d, "wrong.jsonl")
            _write_jsonl(new, [{"design_id": "new-1", "complex_target_id": "OTHER_TARGET"}])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "records": [new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records wrong",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertEqual(rep["failures"][0]["error"], "complex_target_id_mismatch")
        self.assertEqual(rep["records"][0]["other_complex_target_ids"], ["OTHER_TARGET"])
        self.assertIn("target-mismatched", rep["shell_plan"])

    def test_duplicate_target_ids_across_new_records_block_before_posthoc(self):
        with tempfile.TemporaryDirectory() as d:
            first = os.path.join(d, "records_t030.jsonl")
            second = os.path.join(d, "records_t050.jsonl")
            _write_jsonl(first, [{
                "target_id": "binder-1BRS_AD-0",
                "complex_target_id": "1BRS_AD",
            }])
            _write_jsonl(second, [{
                "target_id": "binder-1BRS_AD-0",
                "complex_target_id": "1BRS_AD",
            }])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "records": [first, second],
                "new_records": [first, second],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records first second",
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertEqual(rep["failures"][0]["error"], "duplicate_record_identity")
        self.assertEqual(rep["records"][1]["duplicate_record_identities"][0]["identity"],
                         ["1BRS_AD", "binder-1BRS_AD-0"])

    def test_non_scale_plan_needs_no_completion_check(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {"action": "none", "records": [], "new_records": []})

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["status"], "no_scale_batch")
        self.assertIn("no completion check needed", rep["next_action"])

    def test_unavailable_readiness_sentinel_blocks_completion(self):
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "ok": False,
                "action": "unavailable",
                "status": "waiting_on_input_prep",
                "readiness_status": "waiting_on_input_prep",
                "next_action": "run input prep first",
                "records": [],
                "new_records": [],
            })

            rep = run_completion(plan, out_path=os.path.join(d, "completion.json"))

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "scale_plan_unavailable")
        self.assertEqual(rep["next_action"], "run input prep first")
        self.assertEqual(rep["failures"][0]["role"], "scale_plan")
        self.assertEqual(rep["failures"][0]["error"], "waiting_on_input_prep")
        self.assertIn("Missing, invalid, or target-mismatched records", rep["shell_plan"])

    def test_new_records_only_shell_plan_preserves_replay_flag(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "missing_previous.jsonl")
            new = os.path.join(d, "new.jsonl")
            out = os.path.join(d, "completion report.json")
            _write_jsonl(new, [{"design_id": "new-1", "complex_target_id": "1BRS_AD"}])
            plan = os.path.join(d, "plan with spaces.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "target_alpha": 0.2,
                "records": [old, new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records old new",
            })

            rep = run_completion(plan, check_all_records=False, out_path=out)

        self.assertTrue(rep["ok"])
        self.assertEqual(len(rep["records"]), 1)
        self.assertEqual(rep["records"][0]["role"], "new_record")
        self.assertIn("--new-records-only", rep["shell_plan"])
        self.assertIn("plan with spaces.json'", rep["shell_plan"])
        self.assertIn("completion report.json'", rep["shell_plan"])

    def test_no_check_target_ids_shell_plan_marks_escape_hatch(self):
        with tempfile.TemporaryDirectory() as d:
            new = os.path.join(d, "wrong.jsonl")
            _write_jsonl(new, [{"design_id": "new-1", "complex_target_id": "OTHER_TARGET"}])
            plan = os.path.join(d, "plan.json")
            _write_json(plan, {
                "action": "run_scale_batch",
                "target_id": "1BRS_AD",
                "records": [new],
                "new_records": [new],
                "posthoc_command": "python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records wrong",
            })

            rep = run_completion(plan, check_target_ids=False)

        self.assertTrue(rep["ok"])
        self.assertIn("--no-check-target-ids", rep["shell_plan"])
        self.assertIn("target-id check was disabled", rep["shell_plan"])
        self.assertNotIn("target-id aligned", rep["shell_plan"])


if __name__ == "__main__":
    unittest.main()
