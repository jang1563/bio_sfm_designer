import copy
import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v3_prospective_live_panel import (
    capture_prospective_live_panel,
    load_and_validate_scope,
)


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "configs/w6_v3_prospective_live_scope.json"
EXPECTED_SCOPE_SHA256 = (
    "7ef4da7a1273565bb793e65b6e1fda273024178b173ea92ecba5a18317e7c2ea"
)


class FakeLiveProvider:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("secret-bearing provider failure")
        return json.dumps(
            {
                "reason": "The frozen state isolates one unresolved evidence question.",
                "hypothesis": "Audit one independent evidence slice.",
            },
            sort_keys=True,
        )


def _write_scope(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


class W6V3ProspectiveLivePanelTests(unittest.TestCase):
    def _paths(self, temporary):
        root = Path(temporary)
        return (
            root / "capture.jsonl",
            root / "responses.jsonl",
            root / "receipt.json",
        )

    def _capture(self, provider, temporary, approved_sha=EXPECTED_SCOPE_SHA256):
        capture, responses, receipt = self._paths(temporary)
        result = capture_prospective_live_panel(
            provider=provider,
            scope_path=SCOPE,
            capture_path=capture,
            responses_path=responses,
            receipt_path=receipt,
            repo_root=ROOT,
            approved_scope_sha256=approved_sha,
            source_commit="test-source-commit",
        )
        return result, capture, responses, receipt

    def test_scope_locks_exact_provider_model_and_call_budget(self):
        scope, panel, requests, panel_path, request_path = load_and_validate_scope(
            SCOPE,
            repo_root=ROOT,
            expected_scope_sha256=EXPECTED_SCOPE_SHA256,
        )
        self.assertEqual(scope["provider"], "anthropic")
        self.assertEqual(scope["model"], "claude-opus-4-8")
        self.assertEqual(scope["approved_call_count"], 16)
        self.assertEqual(scope["max_output_tokens_per_call"], 256)
        self.assertEqual(scope["sdk_retries_per_call"], 0)
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(len(requests), 16)
        self.assertEqual(
            panel_path,
            ROOT / "configs/w6_v3_prospective_hypothesis_panel.json",
        )
        self.assertEqual(
            request_path,
            ROOT / "results/w6_v3_prospective_hypothesis_requests.jsonl",
        )

    def test_captures_one_call_per_case_with_pending_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeLiveProvider()
            result, capture, responses, receipt = self._capture(
                provider,
                temporary,
            )
            capture_rows = _read_jsonl(capture)
            response_rows = _read_jsonl(responses)
            stored_receipt = json.loads(receipt.read_text())
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(len(capture_rows), 16)
        self.assertEqual(len(response_rows), 16)
        self.assertEqual(
            result["status"],
            "prospective_live_capture_complete_pending_review",
        )
        self.assertEqual(result, stored_receipt)
        self.assertEqual(result["scope_sha256"], EXPECTED_SCOPE_SHA256)
        self.assertEqual(result["succeeded_calls"], 16)
        self.assertEqual(result["failed_calls"], 0)
        self.assertEqual(result["recommendations_applied"], 0)
        self.assertFalse(result["prospective_live_validation_complete"])
        self.assertFalse(result["live_execution_authorized_for_additional_calls"])
        self.assertTrue(all(row["status"] == "succeeded" for row in capture_rows))
        self.assertTrue(all(not row["applied"] for row in capture_rows))
        self.assertTrue(
            all(row["review"]["status"] == "pending" for row in response_rows)
        )
        self.assertTrue(
            all("contract_sha256" in row for row in response_rows)
        )

    def test_provider_failure_is_sanitized_and_never_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeLiveProvider(fail_at=4)
            result, capture, responses, _ = self._capture(provider, temporary)
            capture_text = capture.read_text()
            failed = [
                row
                for row in _read_jsonl(capture)
                if row["status"] == "provider_error"
            ]
            responses_exist = responses.exists()
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(result["attempted_calls"], 16)
        self.assertEqual(result["succeeded_calls"], 15)
        self.assertEqual(result["failed_calls"], 1)
        self.assertEqual(
            result["status"],
            "prospective_live_capture_incomplete_no_retry",
        )
        self.assertEqual(result["sdk_retries_per_call"], 0)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["error_type"], "RuntimeError")
        self.assertNotIn("secret-bearing", capture_text)
        self.assertFalse(responses_exist)

    def test_mismatched_approved_scope_hash_blocks_before_provider_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeLiveProvider()
            with self.assertRaisesRegex(ValueError, "approved live scope"):
                self._capture(provider, temporary, approved_sha="0" * 64)
        self.assertEqual(provider.calls, [])

    def test_modified_scope_call_count_or_safety_flag_is_rejected(self):
        original = json.loads(SCOPE.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            scope_path = Path(temporary) / "scope.json"
            low_count = copy.deepcopy(original)
            low_count["approved_call_count"] = 15
            _write_scope(scope_path, low_count)
            with self.assertRaisesRegex(ValueError, "approved call count"):
                load_and_validate_scope(scope_path, repo_root=ROOT)

            unsafe = copy.deepcopy(original)
            unsafe["compute_submission_allowed"] = True
            _write_scope(scope_path, unsafe)
            with self.assertRaisesRegex(ValueError, "required false safety flag"):
                load_and_validate_scope(scope_path, repo_root=ROOT)

    def test_scope_path_escape_is_rejected(self):
        original = json.loads(SCOPE.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            scope_path = Path(temporary) / "scope.json"
            original["panel_path"] = "../outside.json"
            _write_scope(scope_path, original)
            with self.assertRaisesRegex(ValueError, "escapes the repository"):
                load_and_validate_scope(scope_path, repo_root=ROOT)

    def test_existing_output_blocks_capture_before_provider_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeLiveProvider()
            capture, _, _ = self._paths(temporary)
            capture.write_text("existing\n")
            with self.assertRaisesRegex(FileExistsError, "already exist"):
                self._capture(provider, temporary)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
