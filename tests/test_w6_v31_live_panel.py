import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bio_sfm_designer.experiments.w6_v31_live_panel import (
    capture_live_panel,
    load_and_validate_scope,
)
from bio_sfm_designer.loop.providers import OrchestrationProviderResult


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "configs/w6_v31_live_scope.json"
EXPECTED_SCOPE_SHA256 = (
    "3ce9af157ba0e3a9a5047c1f01b52c1d94713e356bfaa29fb5f01187be4cfe8e"
)


class FakeMetadataProvider:
    def __init__(self, *, fail_at=None, limit_at=None):
        self.fail_at = fail_at
        self.limit_at = limit_at
        self.calls = []

    def call_with_metadata(self, prompt):
        self.calls.append(prompt)
        index = len(self.calls)
        if index == self.fail_at:
            raise RuntimeError("secret-bearing provider failure")
        return OrchestrationProviderResult(
            text=json.dumps(
                {
                    "reason": "The frozen state identifies one bounded gap.",
                    "hypothesis": "Audit one independent evidence slice.",
                },
                sort_keys=True,
            ),
            input_tokens=100 + index,
            output_tokens=512 if index == self.limit_at else 40 + index,
            stop_reason="max_tokens" if index == self.limit_at else "end_turn",
        )


class FakeLegacyProvider:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return '{"reason":"bounded","hypothesis":"collect evidence"}'


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_scope(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class W6V31LivePanelTests(unittest.TestCase):
    def _paths(self, temporary):
        root = Path(temporary)
        return (
            root / "capture.jsonl",
            root / "responses.jsonl",
            root / "receipt.json",
        )

    def _authorized_scope(self, temporary):
        path = Path(temporary) / "authorized_scope.json"
        scope = json.loads(SCOPE.read_text())
        scope["scope_id"] = "w6-v3-1-test-authorized"
        scope["live_execution_authorized"] = True
        scope["approval_basis"] = "Unit-test-only fake provider approval."
        _write_scope(path, scope)
        return path, _sha256(path)

    def _capture(self, provider, temporary, *, dirty=""):
        scope_path, scope_sha256 = self._authorized_scope(temporary)
        capture, responses, receipt = self._paths(temporary)
        with mock.patch(
            "bio_sfm_designer.experiments.w6_v31_live_panel._git_porcelain",
            return_value=dirty,
        ):
            result = capture_live_panel(
                provider=provider,
                scope_path=scope_path,
                capture_path=capture,
                responses_path=responses,
                receipt_path=receipt,
                repo_root=ROOT,
                approved_scope_sha256=scope_sha256,
                source_commit="test-source-commit",
            )
        return result, capture, responses, receipt

    def test_no_call_scope_is_frozen_but_unauthorized(self):
        scope, panel, requests, _, _, components = load_and_validate_scope(
            SCOPE,
            repo_root=ROOT,
            expected_scope_sha256=EXPECTED_SCOPE_SHA256,
        )
        self.assertFalse(scope["live_execution_authorized"])
        self.assertIsNone(scope["approval_basis"])
        self.assertEqual(scope["max_output_tokens_per_call"], 512)
        self.assertEqual(scope["approved_call_count"], 16)
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(len(requests), 16)
        self.assertEqual(len(components), 5)

    def test_unauthorized_scope_blocks_before_provider_call(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            capture, responses, receipt = self._paths(temporary)
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                capture_live_panel(
                    provider=provider,
                    scope_path=SCOPE,
                    capture_path=capture,
                    responses_path=responses,
                    receipt_path=receipt,
                    repo_root=ROOT,
                    approved_scope_sha256=EXPECTED_SCOPE_SHA256,
                )
        self.assertEqual(provider.calls, [])

    def test_complete_metadata_capture_records_usage_and_stop_reason(self):
        provider = FakeMetadataProvider(limit_at=4)
        with tempfile.TemporaryDirectory() as temporary:
            result, capture, responses, receipt = self._capture(
                provider,
                temporary,
            )
            rows = _read_jsonl(capture)
            response_rows = _read_jsonl(responses)
            stored = json.loads(receipt.read_text())
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(
            result["status"],
            "w6_v31_live_capture_complete_pending_review",
        )
        self.assertEqual(result, stored)
        self.assertEqual(result["transport_metadata_complete_calls"], 16)
        self.assertEqual(result["output_limit_stop_calls"], 1)
        self.assertEqual(result["total_input_tokens"], sum(range(101, 117)))
        self.assertEqual(
            result["total_output_tokens"],
            512 + sum(40 + index for index in range(1, 17) if index != 4),
        )
        self.assertTrue(result["source_worktree_clean"])
        self.assertEqual(len(rows), 16)
        self.assertEqual(len(response_rows), 16)
        self.assertEqual(rows[3]["stop_reason"], "max_tokens")
        self.assertTrue(rows[3]["output_limit_stop"])

    def test_missing_transport_metadata_fails_closed(self):
        provider = FakeLegacyProvider()
        with tempfile.TemporaryDirectory() as temporary:
            result, _, responses, _ = self._capture(provider, temporary)
            responses_exist = responses.exists()
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(
            result["status"],
            "w6_v31_live_capture_incomplete_transport_metadata",
        )
        self.assertEqual(result["transport_metadata_complete_calls"], 0)
        self.assertFalse(responses_exist)

    def test_dirty_worktree_blocks_before_provider_call(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "clean worktree"):
                self._capture(provider, temporary, dirty=" M tracked.py\n")
        self.assertEqual(provider.calls, [])

    def test_provider_failure_is_sanitized_and_never_retried(self):
        provider = FakeMetadataProvider(fail_at=4)
        with tempfile.TemporaryDirectory() as temporary:
            result, capture, responses, _ = self._capture(provider, temporary)
            capture_text = capture.read_text()
            failed = [
                row
                for row in _read_jsonl(capture)
                if row["status"] == "provider_error"
            ]
            responses_exist = responses.exists()
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(result["failed_calls"], 1)
        self.assertEqual(
            result["status"],
            "w6_v31_live_capture_incomplete_no_retry",
        )
        self.assertEqual(result["sdk_retries_per_call"], 0)
        self.assertEqual(failed[0]["error_type"], "RuntimeError")
        self.assertNotIn("secret-bearing", capture_text)
        self.assertFalse(responses_exist)

    def test_component_hash_and_scope_mutation_are_rejected(self):
        original = json.loads(SCOPE.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scope.json"
            tampered = copy.deepcopy(original)
            tampered["execution_components"][0]["sha256"] = "0" * 64
            _write_scope(path, tampered)
            with self.assertRaisesRegex(ValueError, "component SHA-256 mismatch"):
                load_and_validate_scope(path, repo_root=ROOT)

            tampered = copy.deepcopy(original)
            tampered["max_output_tokens_per_call"] = 768
            _write_scope(path, tampered)
            with self.assertRaisesRegex(ValueError, "exactly 512"):
                load_and_validate_scope(path, repo_root=ROOT)

    def test_existing_output_blocks_before_provider_call(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            capture, _, _ = self._paths(temporary)
            capture.write_text("existing\n")
            with self.assertRaisesRegex(FileExistsError, "already exist"):
                self._capture(provider, temporary)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
