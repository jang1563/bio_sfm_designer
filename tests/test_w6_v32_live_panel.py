import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bio_sfm_designer.experiments.w6_v32_live_panel import (
    capture_live_panel,
    load_and_validate_scope,
)
from bio_sfm_designer.loop.providers import OrchestrationProviderResult


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v32_transport_panel.json"
REQUESTS = ROOT / "results/w6_v32_transport_requests.jsonl"
FROZEN_SCOPE = ROOT / "configs/w6_v32_live_scope.json"
EXPECTED_FROZEN_SCOPE_SHA256 = (
    "e71cca5a7fba25eb30cf2ed5dbea4541d862cca7f5d8f404f2177ab7711c7708"
)
COMPONENT_PATHS = (
    "src/bio_sfm_designer/loop/providers.py",
    "src/bio_sfm_designer/experiments/w6_v2_shadow_panel.py",
    "src/bio_sfm_designer/experiments/w6_v3_hypothesis_only.py",
    "src/bio_sfm_designer/experiments/w6_v32_failure_telemetry.py",
    "src/bio_sfm_designer/experiments/w6_v32_transport_panel.py",
    "src/bio_sfm_designer/experiments/w6_v32_live_panel.py",
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeMetadataProvider:
    def __init__(self, *, fail_at=None, incomplete_metadata=False):
        self.calls = []
        self.fail_at = fail_at
        self.incomplete_metadata = incomplete_metadata

    def call_with_metadata(self, prompt):
        self.calls.append(prompt)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("Anthropic response did not contain a text block")
        return OrchestrationProviderResult(
            text=json.dumps(
                {
                    "reason": "The frozen state supports one bounded audit.",
                    "hypothesis": "Collect one matched evidence slice.",
                }
            ),
            input_tokens=None if self.incomplete_metadata else 700,
            output_tokens=None if self.incomplete_metadata else 80,
            stop_reason=None if self.incomplete_metadata else "end_turn",
        )


class W6V32LivePanelTests(unittest.TestCase):
    def _scope(self, *, authorized=True):
        return {
            "schema_version": "w6_v32_live_scope_v1",
            "scope_id": "w6-v3-2-test-scope",
            "frozen_at": "2026-07-26T00:00:00Z",
            "purpose": "Unit-test scope with no real provider construction.",
            "panel_path": "configs/w6_v32_transport_panel.json",
            "panel_id": "w6-v3-2-transport-panel-2026-07-26",
            "panel_sha256": _sha256(PANEL),
            "request_path": "results/w6_v32_transport_requests.jsonl",
            "request_sha256": _sha256(REQUESTS),
            "provider": "anthropic",
            "model": "claude-opus-4-8",
            "mode": "shadow",
            "approved_call_count": 16,
            "max_output_tokens_per_call": 512,
            "sdk_retries_per_call": 0,
            "temperature_override": None,
            "one_call_per_case": True,
            "one_shot": True,
            "resume_allowed": False,
            "overwrite_allowed": False,
            "credential_hygiene_attested": True,
            "capture_transport_metadata": True,
            "capture_failure_telemetry": True,
            "failure_telemetry_schema": ("w6_v32_provider_failure_telemetry_v1"),
            "store_exception_messages": False,
            "store_tracebacks": False,
            "store_headers": False,
            "store_request_ids": False,
            "require_clean_worktree": True,
            "require_component_hash_match": True,
            "execution_components": [
                {
                    "path": path,
                    "sha256": _sha256(ROOT / path),
                }
                for path in COMPONENT_PATHS
            ],
            "live_execution_authorized": authorized,
            "approval_basis": "Unit-test authorization." if authorized else None,
            "review_required_before_scoring": True,
            "reviewer_provider_independence_required": True,
            "recommendations_may_be_applied": False,
            "compute_submission_allowed": False,
            "additional_provider_calls_authorized": False,
            "behavioral_change": "none",
            "instrumentation_change": ("structured_non_sensitive_failure_telemetry_v1"),
            "analyst_blinded_to_prior_outputs": False,
        }

    def _write_scope(self, directory, *, authorized=True):
        scope_path = Path(directory) / "scope.json"
        scope_path.write_text(
            json.dumps(self._scope(authorized=authorized), indent=2) + "\n"
        )
        return scope_path

    def _capture(self, temporary, provider, *, authorized=True):
        root = Path(temporary)
        scope = self._write_scope(root, authorized=authorized)
        capture = root / "capture.jsonl"
        responses = root / "responses.jsonl"
        receipt = root / "receipt.json"
        with patch(
            "bio_sfm_designer.experiments.w6_v32_live_panel._git_porcelain",
            return_value="",
        ):
            result = capture_live_panel(
                provider=provider,
                scope_path=scope,
                capture_path=capture,
                responses_path=responses,
                receipt_path=receipt,
                repo_root=ROOT,
                approved_scope_sha256=_sha256(scope),
                source_commit="a" * 40,
            )
        return result, capture, responses, receipt

    def test_scope_validation_constructs_no_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            scope_path = self._write_scope(temporary, authorized=False)
            scope, panel, requests, _, _, components = load_and_validate_scope(
                scope_path,
                repo_root=ROOT,
                expected_scope_sha256=_sha256(scope_path),
            )
        self.assertFalse(scope["live_execution_authorized"])
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(len(requests), 16)
        self.assertEqual(len(components), len(COMPONENT_PATHS))

    def test_frozen_scope_is_exactly_no_call(self):
        scope, panel, requests, _, _, components = load_and_validate_scope(
            FROZEN_SCOPE,
            repo_root=ROOT,
            expected_scope_sha256=EXPECTED_FROZEN_SCOPE_SHA256,
        )
        self.assertFalse(scope["live_execution_authorized"])
        self.assertIsNone(scope["approval_basis"])
        self.assertEqual(scope["provider"], "anthropic")
        self.assertEqual(scope["model"], "claude-opus-4-8")
        self.assertEqual(scope["approved_call_count"], 16)
        self.assertEqual(scope["max_output_tokens_per_call"], 512)
        self.assertEqual(scope["sdk_retries_per_call"], 0)
        self.assertFalse(scope["store_exception_messages"])
        self.assertFalse(scope["store_tracebacks"])
        self.assertFalse(scope["store_headers"])
        self.assertFalse(scope["store_request_ids"])
        self.assertFalse(scope["analyst_blinded_to_prior_outputs"])
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(len(requests), 16)
        self.assertEqual(len(components), len(COMPONENT_PATHS))

    def test_complete_capture_writes_pending_responses_and_safe_telemetry(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            result, capture, responses, _ = self._capture(
                temporary,
                provider,
            )
            rows = [
                json.loads(line)
                for line in capture.read_text().splitlines()
                if line.strip()
            ]
            response_rows = [
                json.loads(line)
                for line in responses.read_text().splitlines()
                if line.strip()
            ]
        self.assertEqual(
            result["status"],
            "w6_v32_live_capture_complete_pending_review",
        )
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(len(rows), 16)
        self.assertEqual(len(response_rows), 16)
        self.assertEqual(result["failure_telemetry_complete_calls"], 16)
        self.assertEqual(result["failure_reason_counts"], {})
        self.assertTrue(
            all(row["failure_telemetry"]["outcome"] == "success" for row in rows)
        )

    def test_failure_is_classified_without_message_or_retry(self):
        provider = FakeMetadataProvider(fail_at=5)
        with tempfile.TemporaryDirectory() as temporary:
            result, capture, responses, _ = self._capture(
                temporary,
                provider,
            )
            capture_text = capture.read_text()
            rows = [
                json.loads(line) for line in capture_text.splitlines() if line.strip()
            ]
            response_exists = responses.exists()
        failed = [row for row in rows if row["status"] == "provider_error"]
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(len(failed), 1)
        self.assertEqual(
            failed[0]["failure_telemetry"]["safe_reason_code"],
            "empty_text_response",
        )
        self.assertFalse(failed[0]["failure_telemetry"]["retry_authorized"])
        self.assertNotIn("did not contain a text block", capture_text)
        self.assertFalse(response_exists)
        self.assertEqual(
            result["status"],
            "w6_v32_live_capture_incomplete_no_retry",
        )
        self.assertEqual(result["failure_telemetry_complete_calls"], 16)
        self.assertEqual(
            result["failure_reason_counts"],
            {"empty_text_response": 1},
        )

    def test_missing_transport_metadata_fails_closed(self):
        provider = FakeMetadataProvider(incomplete_metadata=True)
        with tempfile.TemporaryDirectory() as temporary:
            result, _, responses, _ = self._capture(temporary, provider)
            response_exists = responses.exists()
        self.assertEqual(len(provider.calls), 16)
        self.assertEqual(
            result["status"],
            "w6_v32_live_capture_incomplete_transport_metadata",
        )
        self.assertEqual(result["transport_metadata_complete_calls"], 0)
        self.assertEqual(result["failure_telemetry_complete_calls"], 16)
        self.assertFalse(response_exists)

    def test_unauthorized_scope_blocks_before_any_call(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                self._capture(temporary, provider, authorized=False)
        self.assertEqual(provider.calls, [])

    def test_existing_output_blocks_before_any_call(self):
        provider = FakeMetadataProvider()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scope = self._write_scope(root)
            capture = root / "capture.jsonl"
            capture.write_text("existing\n")
            with self.assertRaisesRegex(FileExistsError, "already exist"):
                capture_live_panel(
                    provider=provider,
                    scope_path=scope,
                    capture_path=capture,
                    responses_path=root / "responses.jsonl",
                    receipt_path=root / "receipt.json",
                    repo_root=ROOT,
                    approved_scope_sha256=_sha256(scope),
                )
        self.assertEqual(provider.calls, [])

    def test_scope_rejects_sensitive_storage_flags(self):
        scope = self._scope(authorized=False)
        scope["store_exception_messages"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scope.json"
            path.write_text(json.dumps(scope))
            with self.assertRaisesRegex(ValueError, "required false"):
                load_and_validate_scope(path, repo_root=ROOT)


if __name__ == "__main__":
    unittest.main()
