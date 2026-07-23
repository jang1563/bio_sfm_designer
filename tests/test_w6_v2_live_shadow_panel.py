import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v2_live_shadow_panel import (
    capture_live_shadow_panel,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v2_frozen_shadow_panel.json"
REQUESTS = ROOT / "results/w6_v2_shadow_panel_requests.jsonl"


def _response():
    return json.dumps(
        {
            "stop": False,
            "reason": "continue under the frozen evidence plan",
            "hypothesis": "collect the next independent evidence stage",
            "explore": False,
        }
    )


class FakeLiveProvider:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, prompt):
        self.calls.append(prompt)
        if self.fail_at == len(self.calls):
            raise RuntimeError("secret-bearing provider failure")
        return _response()


class W6V2LiveShadowPanelTests(unittest.TestCase):
    def _paths(self, tmp):
        root = Path(tmp)
        return (
            root / "capture.jsonl",
            root / "responses.jsonl",
            root / "receipt.json",
        )

    def _capture(self, provider, tmp, approved_call_count=16):
        capture, responses, receipt = self._paths(tmp)
        result = capture_live_shadow_panel(
            provider=provider,
            provider_name="anthropic",
            model="test-model",
            panel_path=PANEL,
            request_path=REQUESTS,
            capture_path=capture,
            responses_path=responses,
            receipt_path=receipt,
            repo_root=ROOT,
            approved_call_count=approved_call_count,
            max_output_tokens=256,
            credential_hygiene_attested=True,
            approval_basis="unit-test explicit approval",
            source_commit="test-commit",
        )
        return result, capture, responses, receipt

    def test_captures_exactly_one_call_per_case_with_pending_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeLiveProvider()
            result, capture, responses, receipt = self._capture(provider, tmp)
            self.assertEqual(len(provider.calls), 16)
            self.assertEqual(result["status"], "live_capture_complete_pending_review")
            self.assertEqual(result["attempted_calls"], 16)
            self.assertEqual(result["succeeded_calls"], 16)
            self.assertEqual(result["failed_calls"], 0)
            self.assertEqual(result["sdk_retries_per_call"], 0)
            self.assertEqual(result["recommendations_applied"], 0)
            self.assertFalse(result["live_execution_authorized_for_additional_calls"])
            capture_rows = [
                json.loads(line) for line in capture.read_text().splitlines()
            ]
            response_rows = [
                json.loads(line) for line in responses.read_text().splitlines()
            ]
            self.assertEqual(len(capture_rows), 16)
            self.assertTrue(all(row["status"] == "succeeded" for row in capture_rows))
            self.assertTrue(all(not row["applied"] for row in capture_rows))
            self.assertTrue(
                all(row["review"]["status"] == "pending" for row in response_rows)
            )
            self.assertEqual(json.loads(receipt.read_text()), result)

    def test_provider_failure_is_sanitized_and_never_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeLiveProvider(fail_at=4)
            result, capture, responses, _ = self._capture(provider, tmp)
            self.assertEqual(len(provider.calls), 16)
            self.assertEqual(result["attempted_calls"], 16)
            self.assertEqual(result["succeeded_calls"], 15)
            self.assertEqual(result["failed_calls"], 1)
            self.assertEqual(result["status"], "live_capture_incomplete_no_retry")
            self.assertFalse(responses.exists())
            self.assertNotIn("secret-bearing", capture.read_text())
            failed = [
                json.loads(line)
                for line in capture.read_text().splitlines()
                if json.loads(line)["status"] == "provider_error"
            ]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["error_type"], "RuntimeError")

    def test_wrong_approval_count_blocks_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeLiveProvider()
            with self.assertRaisesRegex(ValueError, "frozen request count"):
                self._capture(provider, tmp, approved_call_count=15)
            self.assertEqual(provider.calls, [])

    def test_existing_output_blocks_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeLiveProvider()
            capture, _, _ = self._paths(tmp)
            capture.write_text("existing\n")
            with self.assertRaisesRegex(FileExistsError, "overwrite or resume"):
                self._capture(provider, tmp)
            self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
