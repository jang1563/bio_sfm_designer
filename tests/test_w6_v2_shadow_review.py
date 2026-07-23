import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v2_shadow_review import (
    apply_review_annotations,
)


def _sha256(path):
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class W6V2ShadowReviewTests(unittest.TestCase):
    def _inputs(self, root):
        responses = root / "responses.jsonl"
        response_rows = [
            {
                "schema_version": "w6_v2_shadow_response_v1",
                "response_source": "live_shadow_test",
                "case_id": case_id,
                "panel_sha256": "a" * 64,
                "prompt_sha256": character * 64,
                "raw_response": "{}",
                "response_sha256": "b" * 64,
                "review": {
                    "status": "pending",
                    "scope_tag": "unreviewed",
                    "grounded": False,
                    "actionable": False,
                    "incremental_value": False,
                    "notes": "pending",
                },
            }
            for case_id, character in (("case-a", "c"), ("case-b", "d"))
        ]
        responses.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in response_rows
            )
        )
        annotations = root / "annotations.json"
        annotation = {
            "schema_version": "w6_v2_shadow_review_annotations_v1",
            "source_responses_sha256": _sha256(responses),
            "reviewer": {
                "identity": "test-reviewer",
                "type": "offline_test",
                "provider_independent": True,
                "reviewed_at": "2026-07-23",
            },
            "records": [
                {
                    "case_id": case_id,
                    "review": {
                        "status": "complete",
                        "scope_tag": "evidence_collection",
                        "grounded": True,
                        "actionable": True,
                        "incremental_value": case_id == "case-a",
                        "notes": "reviewed",
                    },
                }
                for case_id in ("case-a", "case-b")
            ],
        }
        annotations.write_text(json.dumps(annotation))
        return responses, annotations

    def test_applies_complete_reviews_without_changing_raw_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            responses, annotations = self._inputs(root)
            reviewed = root / "reviewed.jsonl"
            receipt = root / "receipt.json"
            result = apply_review_annotations(
                responses_path=responses,
                annotations_path=annotations,
                reviewed_responses_path=reviewed,
                receipt_path=receipt,
            )
            rows = [json.loads(line) for line in reviewed.read_text().splitlines()]
            self.assertEqual(result["case_count"], 2)
            self.assertFalse(result["raw_responses_modified"])
            self.assertEqual(result["provider_calls"], 0)
            self.assertTrue(all(row["raw_response"] == "{}" for row in rows))
            self.assertTrue(all(row["review"]["status"] == "complete" for row in rows))

    def test_wrong_source_hash_fails_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            responses, annotations = self._inputs(root)
            payload = json.loads(annotations.read_text())
            payload["source_responses_sha256"] = "0" * 64
            annotations.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                apply_review_annotations(
                    responses_path=responses,
                    annotations_path=annotations,
                    reviewed_responses_path=root / "reviewed.jsonl",
                    receipt_path=root / "receipt.json",
                )


if __name__ == "__main__":
    unittest.main()
