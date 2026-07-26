import hashlib
import json
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v32_failure_telemetry import (
    validate_failure_telemetry,
)


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "w6_v32_live_shadow_anthropic_claude_opus_4_8_20260726"
RESULTS = ROOT / "results"
SUMMARY = RESULTS / f"{PREFIX}_public_summary.json"
CAPTURE = RESULTS / f"{PREFIX}_capture.jsonl"
PENDING = RESULTS / f"{PREFIX}_responses_pending_review.jsonl"
REVIEWED = RESULTS / f"{PREFIX}_responses_reviewed.jsonl"
ANNOTATIONS = RESULTS / f"{PREFIX}_review_annotations.json"
FINAL_SCORE = RESULTS / f"{PREFIX}_live_result.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path):
    return json.loads(path.read_text())


def _load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class W6V32LiveResultTests(unittest.TestCase):
    def test_public_summary_hash_binds_every_audit_artifact(self):
        summary = _load_json(SUMMARY)
        artifacts = summary["tracked_audit_artifacts"]
        self.assertEqual(len(artifacts), 7)
        for artifact in artifacts.values():
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(_sha256(path), artifact["sha256"])
        scope = summary["frozen_inputs"]
        scope_path = ROOT / scope["authorized_scope"]
        self.assertEqual(_sha256(scope_path), scope["authorized_scope_sha256"])

    def test_capture_is_exactly_sixteen_one_shot_successes(self):
        rows = _load_jsonl(CAPTURE)
        self.assertEqual(len(rows), 16)
        self.assertEqual([row["call_index"] for row in rows], list(range(1, 17)))
        self.assertEqual(len({row["case_id"] for row in rows}), 16)
        for row in rows:
            self.assertEqual(row["attempt_number"], 1)
            self.assertEqual(row["retry_count"], 0)
            self.assertEqual(row["status"], "succeeded")
            self.assertTrue(row["transport_metadata_complete"])
            self.assertFalse(row["output_limit_stop"])
            self.assertFalse(row["applied"])
            self.assertEqual(
                hashlib.sha256(row["raw_response"].encode("utf-8")).hexdigest(),
                row["response_sha256"],
            )
            telemetry = validate_failure_telemetry(row["failure_telemetry"])
            self.assertEqual(telemetry["outcome"], "success")

    def test_review_preserves_raw_responses_and_expected_counts(self):
        pending = _load_jsonl(PENDING)
        reviewed = _load_jsonl(REVIEWED)
        annotations = _load_json(ANNOTATIONS)
        self.assertEqual(
            [row["raw_response"] for row in pending],
            [row["raw_response"] for row in reviewed],
        )
        self.assertEqual(len(annotations["records"]), 16)
        reviews = [row["review"] for row in reviewed]
        self.assertTrue(all(review["status"] == "complete" for review in reviews))
        self.assertEqual(sum(review["grounded"] for review in reviews), 15)
        self.assertEqual(sum(review["actionable"] for review in reviews), 16)
        self.assertEqual(
            sum(review["incremental_value"] for review in reviews),
            14,
        )

    def test_final_score_is_bounded_pass_not_m7_completion(self):
        score = _load_json(FINAL_SCORE)
        summary = _load_json(SUMMARY)
        self.assertEqual(
            score["status"],
            "w6_v32_prospective_live_validation_pass",
        )
        self.assertTrue(score["passed"])
        self.assertTrue(score["prospective_live_validation_complete"])
        self.assertEqual(score["source_provider_calls"], 16)
        self.assertEqual(score["scoring_provider_calls"], 0)
        self.assertFalse(score["m7_complete"])
        self.assertEqual(score["metrics"]["schema_acceptance_rate"], 1.0)
        self.assertEqual(score["metrics"]["grounded_rate"], 0.9375)
        self.assertEqual(score["metrics"]["actionable_rate"], 1.0)
        self.assertEqual(score["metrics"]["incremental_value_rate"], 0.875)
        self.assertEqual(summary["verdict"]["overall"], "bounded_pass")
        self.assertFalse(summary["verdict"]["m7_complete"])
        self.assertFalse(
            summary["execution"]["additional_calls_authorized"],
        )


if __name__ == "__main__":
    unittest.main()
