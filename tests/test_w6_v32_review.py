import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v32_review import (
    apply_review_annotations,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v32_transport_panel.json"
REQUESTS = ROOT / "results/w6_v32_transport_requests.jsonl"
VALID = ROOT / "tests/fixtures/w6_v32_transport_valid_responses.jsonl"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path, rows):
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        )
    )


class W6V32ReviewTests(unittest.TestCase):
    def _inputs(self, temporary, *, provider_independent=True):
        root = Path(temporary)
        panel = json.loads(PANEL.read_text())
        pending_rows = _read_jsonl(VALID)
        for row in pending_rows:
            row["response_source"] = "live_shadow_anthropic_test"
            row["review"] = {
                "status": "pending",
                "scope_tag": "unreviewed",
                "grounded": False,
                "actionable": False,
                "incremental_value": False,
                "notes": "Review pending.",
            }
        responses = root / "responses_pending.jsonl"
        _write_jsonl(responses, pending_rows)
        annotations = {
            "schema_version": "w6_v32_review_annotations_v1",
            "source_panel_sha256": _sha256(PANEL),
            "source_request_sha256": _sha256(REQUESTS),
            "source_responses_sha256": _sha256(responses),
            "reviewer": {
                "identity": "independent-test-reviewer",
                "type": "offline_rubric_review",
                "provider_independent": provider_independent,
                "reviewed_at": "2026-07-26T00:00:00Z",
            },
            "records": [
                {
                    "case_id": case["case_id"],
                    "review": case["fixture_proposal"]["review"],
                }
                for case in panel["cases"]
            ],
        }
        annotations_path = root / "annotations.json"
        annotations_path.write_text(json.dumps(annotations))
        return responses, annotations_path

    def _apply(self, temporary, *, provider_independent=True):
        root = Path(temporary)
        responses, annotations = self._inputs(
            temporary,
            provider_independent=provider_independent,
        )
        reviewed = root / "responses_reviewed.jsonl"
        receipt = root / "review_receipt.json"
        result = apply_review_annotations(
            panel_path=PANEL,
            request_path=REQUESTS,
            responses_path=responses,
            annotations_path=annotations,
            reviewed_responses_path=reviewed,
            receipt_path=receipt,
            repo_root=ROOT,
        )
        return result, responses, reviewed

    def test_complete_review_preserves_raw_responses(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, pending, reviewed = self._apply(temporary)
            pending_rows = _read_jsonl(pending)
            reviewed_rows = _read_jsonl(reviewed)
        self.assertEqual(
            result["status"],
            "w6_v32_offline_independent_review_complete",
        )
        self.assertEqual(result["case_count"], 16)
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["raw_responses_modified"])
        self.assertEqual(
            [row["raw_response"] for row in pending_rows],
            [row["raw_response"] for row in reviewed_rows],
        )
        self.assertTrue(
            all(row["review"]["status"] == "complete" for row in reviewed_rows)
        )

    def test_review_requires_provider_independence(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "independent"):
                self._apply(temporary, provider_independent=False)

    def test_review_rejects_an_undeclared_scope_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses, annotations_path = self._inputs(temporary)
            annotations = json.loads(annotations_path.read_text())
            annotations["records"][0]["review"]["scope_tag"] = "candidate_strategy"
            annotations_path.write_text(json.dumps(annotations))
            with self.assertRaisesRegex(ValueError, "scope is not allowed"):
                apply_review_annotations(
                    panel_path=PANEL,
                    request_path=REQUESTS,
                    responses_path=responses,
                    annotations_path=annotations_path,
                    reviewed_responses_path=root / "reviewed.jsonl",
                    receipt_path=root / "receipt.json",
                    repo_root=ROOT,
                )


if __name__ == "__main__":
    unittest.main()
