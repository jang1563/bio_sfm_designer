import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "w6_v3_prospective_live_anthropic_claude_opus_4_8_20260724"
SCOPE = ROOT / "configs/w6_v3_prospective_live_scope.json"
CAPTURE = ROOT / f"results/{PREFIX}_capture.jsonl"
CAPTURE_RECEIPT = ROOT / f"results/{PREFIX}_receipt.json"
PENDING = ROOT / f"results/{PREFIX}_responses_pending.jsonl"
ANNOTATIONS = ROOT / f"results/{PREFIX}_annotations.json"
REVIEWED = ROOT / f"results/{PREFIX}_responses_reviewed.jsonl"
REVIEW_RECEIPT = ROOT / f"results/{PREFIX}_review_receipt.json"
SCORE = ROOT / f"results/{PREFIX}_score.json"
EXPECTED_HASHES = {
    SCOPE: "7ef4da7a1273565bb793e65b6e1fda273024178b173ea92ecba5a18317e7c2ea",
    CAPTURE: "fe4b49bcbfdc2f40cb4f13a10fc668643275b71bbadc66023bc086c62b4c4fa4",
    CAPTURE_RECEIPT: (
        "3bee399a001aa9d4ef1cd0b4b4e47f71028ed510680520004fe890c40aceb8de"
    ),
    PENDING: "b117461b7e6ce2fa27a22dc36ef2f9c5157292870b17c63f7e91044f8fe4fe96",
    ANNOTATIONS: (
        "11a92cd28db2100553ec99d17c067056ff871a3f51ebdf1532c68f12be6516e7"
    ),
    REVIEWED: "f5c28eb99ecf758261eb5cae1b89649143b0351bd267a5f07da52b524acd5132",
    REVIEW_RECEIPT: (
        "678f77908f2756a5b41b9b5059772fb1d1882e016226b6f736bc7523d4e14e38"
    ),
    SCORE: "74fa0740b856a3571be0c0eee38cd4e4bfe50cd23d22efb0b199a54a91d914e6",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


class W6V3ProspectiveLiveResultTests(unittest.TestCase):
    def test_public_live_artifact_hashes_are_frozen(self):
        for path, expected in EXPECTED_HASHES.items():
            self.assertEqual(_sha256(path), expected, path.name)

    def test_capture_and_review_receipts_form_one_hash_chain(self):
        capture = json.loads(CAPTURE_RECEIPT.read_text())
        review = json.loads(REVIEW_RECEIPT.read_text())
        score = json.loads(SCORE.read_text())
        self.assertEqual(capture["scope_sha256"], _sha256(SCOPE))
        self.assertEqual(capture["capture_sha256"], _sha256(CAPTURE))
        self.assertEqual(capture["responses_sha256"], _sha256(PENDING))
        self.assertEqual(capture["attempted_calls"], 16)
        self.assertEqual(capture["succeeded_calls"], 16)
        self.assertEqual(capture["failed_calls"], 0)
        self.assertEqual(capture["sdk_retries_per_call"], 0)
        self.assertEqual(capture["recommendations_applied"], 0)

        self.assertEqual(review["source_responses_sha256"], _sha256(PENDING))
        self.assertEqual(review["annotations_sha256"], _sha256(ANNOTATIONS))
        self.assertEqual(review["reviewed_responses_sha256"], _sha256(REVIEWED))
        self.assertFalse(review["raw_responses_modified"])
        self.assertEqual(review["provider_calls"], 0)

        self.assertEqual(score["response_sha256"], _sha256(REVIEWED))
        self.assertEqual(score["source_provider_calls"], 16)
        self.assertEqual(score["scoring_provider_calls"], 0)
        self.assertTrue(score["prospective_live_validation_complete"])
        self.assertFalse(score["offline_fixture_only"])

    def test_live_result_is_negative_only_on_schema_acceptance(self):
        score = json.loads(SCORE.read_text())
        self.assertEqual(score["status"], "prospective_live_validation_fail")
        self.assertFalse(score["passed"])
        self.assertEqual(score["metrics"]["schema_acceptance_count"], 11)
        self.assertEqual(score["metrics"]["schema_acceptance_rate"], 0.6875)
        self.assertEqual(score["metrics"]["control_plane_violation_count"], 0)
        self.assertEqual(score["metrics"]["grounded_rate"], 1.0)
        self.assertEqual(score["metrics"]["actionable_rate"], 1.0)
        self.assertEqual(score["metrics"]["incremental_value_rate"], 0.75)
        failed_checks = {
            key for key, passed in score["checks"].items() if not passed
        }
        self.assertEqual(failed_checks, {"schema_acceptance"})
        capture_rows = _read_jsonl(CAPTURE)
        self.assertEqual(len(capture_rows), 16)
        self.assertTrue(all(row["status"] == "succeeded" for row in capture_rows))
        self.assertTrue(all(not row["applied"] for row in capture_rows))


if __name__ == "__main__":
    unittest.main()
