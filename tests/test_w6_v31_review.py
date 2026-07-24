import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v31_review import (
    ANNOTATION_SCHEMA,
    apply_review_annotations,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v31_transport_panel.json"
REQUESTS = ROOT / "results/w6_v31_transport_requests.jsonl"
VALID = ROOT / "tests/fixtures/w6_v31_transport_valid_responses.jsonl"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_jsonl(path, records):
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )
    )


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class W6V31ReviewTests(unittest.TestCase):
    def _prepare(self, temporary, *, pending=True):
        root = Path(temporary)
        responses = root / "responses.jsonl"
        annotations = root / "annotations.json"
        reviewed = root / "reviewed.jsonl"
        receipt = root / "receipt.json"
        source = copy.deepcopy(_read_jsonl(VALID))
        records = []
        for row in source:
            records.append(
                {
                    "case_id": row["case_id"],
                    "review": copy.deepcopy(row["review"]),
                }
            )
            if pending:
                row["response_source"] = "live_shadow_anthropic_test"
                row["review"] = {
                    "status": "pending",
                    "scope_tag": "unreviewed",
                    "grounded": False,
                    "actionable": False,
                    "incremental_value": False,
                    "notes": "Review pending.",
                }
        _write_jsonl(responses, source)
        payload = {
            "schema_version": ANNOTATION_SCHEMA,
            "source_panel_sha256": _sha256(PANEL),
            "source_request_sha256": _sha256(REQUESTS),
            "source_responses_sha256": _sha256(responses),
            "reviewer": {
                "identity": "test-reviewer",
                "type": "offline_rubric_review",
                "provider_independent": True,
                "reviewed_at": "2026-07-24T00:00:00Z",
            },
            "records": records,
        }
        _write_json(annotations, payload)
        return responses, annotations, reviewed, receipt, payload

    def _apply(self, paths):
        responses, annotations, reviewed, receipt, _ = paths
        return apply_review_annotations(
            panel_path=PANEL,
            request_path=REQUESTS,
            responses_path=responses,
            annotations_path=annotations,
            reviewed_responses_path=reviewed,
            receipt_path=receipt,
            repo_root=ROOT,
        )

    def test_applies_reviews_without_modifying_raw_responses(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(temporary)
            original = _read_jsonl(paths[0])
            receipt = self._apply(paths)
            reviewed = _read_jsonl(paths[2])
        self.assertEqual(
            [row["raw_response"] for row in reviewed],
            [row["raw_response"] for row in original],
        )
        self.assertTrue(
            all(row["review"]["status"] == "complete" for row in reviewed)
        )
        self.assertEqual(receipt["case_count"], 16)
        self.assertFalse(receipt["raw_responses_modified"])
        self.assertEqual(receipt["provider_calls"], 0)

    def test_hash_mismatch_and_disallowed_scope_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(temporary)
            payload = paths[4]
            payload["source_responses_sha256"] = "0" * 64
            _write_json(paths[1], payload)
            with self.assertRaisesRegex(ValueError, "source SHA-256 mismatch"):
                self._apply(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(temporary)
            payload = paths[4]
            payload["records"][0]["review"]["scope_tag"] = "screen_validation"
            _write_json(paths[1], payload)
            with self.assertRaisesRegex(ValueError, "scope is not allowed"):
                self._apply(paths)

    def test_nonpending_source_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(temporary, pending=False)
            with self.assertRaisesRegex(ValueError, "is not pending"):
                self._apply(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self._prepare(temporary)
            paths[2].write_text("existing\n")
            with self.assertRaisesRegex(FileExistsError, "already exist"):
                self._apply(paths)


if __name__ == "__main__":
    unittest.main()
