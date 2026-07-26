import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bio_sfm_designer.experiments.w6_v4_live_campaign import (
    capture_live_campaign,
    load_and_validate_scope,
)
from bio_sfm_designer.loop.providers import OrchestrationProviderResult


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "configs/w6_v4_live_campaign_scope.json"
CAMPAIGN = ROOT / "configs/w6_v4_gated_batch_campaign.json"
EXPECTED_SCOPE_SHA256 = (
    "090799a27da715a327461b4a686f8fe6ff2ae4b67e4513cb0f2d2f6b71fa8552"
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _MetadataProvider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def call_with_metadata(self, prompt):
        self.calls += 1
        return OrchestrationProviderResult(
            text=self.text,
            input_tokens=211,
            output_tokens=57,
            stop_reason="end_turn",
        )


class _ProviderFailure(RuntimeError):
    status_code = 503


class _FailingProvider:
    def __init__(self):
        self.calls = 0

    def call_with_metadata(self, prompt):
        self.calls += 1
        raise _ProviderFailure("secret-bearing live test message")


class W6V4LiveCampaignTests(unittest.TestCase):
    def _authorized_scope(self, root):
        scope = json.loads(SCOPE.read_text())
        scope["scope_id"] = "w6-v4-test-authorized"
        scope["live_execution_authorized"] = True
        scope["approval_basis"] = "Unit-test-only fake provider authorization."
        path = Path(root) / "authorized_scope.json"
        path.write_text(json.dumps(scope, indent=2, sort_keys=True) + "\n")
        return path, _sha256(path)

    def test_frozen_scope_is_exact_and_unauthorized(self):
        scope, campaign, _, components = load_and_validate_scope(
            SCOPE,
            repo_root=ROOT,
            expected_scope_sha256=EXPECTED_SCOPE_SHA256,
        )
        self.assertFalse(scope["live_execution_authorized"])
        self.assertIsNone(scope["approval_basis"])
        self.assertEqual(scope["approved_call_count"], 1)
        self.assertEqual(campaign["campaign_id"], scope["campaign_id"])
        self.assertEqual(len(components), 7)

    def test_unauthorized_scope_blocks_before_provider_or_output(self):
        campaign = json.loads(CAMPAIGN.read_text())
        provider = _MetadataProvider(json.dumps(campaign["valid_fixture"]["response"]))
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "out"
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                capture_live_campaign(
                    provider=provider,
                    scope_path=SCOPE,
                    out_dir=out_dir,
                    repo_root=ROOT,
                    approved_scope_sha256=EXPECTED_SCOPE_SHA256,
                )
            self.assertFalse(out_dir.exists())
        self.assertEqual(provider.calls, 0)

    def test_fake_live_success_is_one_call_no_effect_pending_review(self):
        campaign = json.loads(CAMPAIGN.read_text())
        provider = _MetadataProvider(
            json.dumps(
                campaign["valid_fixture"]["response"],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            scope_path, scope_sha256 = self._authorized_scope(temporary)
            out_dir = Path(temporary) / "out"
            with patch(
                "bio_sfm_designer.experiments.w6_v4_live_campaign._git_porcelain",
                return_value="",
            ):
                receipt = capture_live_campaign(
                    provider=provider,
                    scope_path=scope_path,
                    out_dir=out_dir,
                    repo_root=ROOT,
                    approved_scope_sha256=scope_sha256,
                    source_commit="unit-test-source",
                )
            response = json.loads(
                (out_dir / "response_pending_review.json").read_text()
            )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            receipt["status"],
            "w6_v4_live_campaign_complete_pending_review",
        )
        self.assertEqual(receipt["attempted_calls"], 1)
        self.assertEqual(receipt["succeeded_calls"], 1)
        self.assertEqual(receipt["sdk_retries_per_call"], 0)
        self.assertTrue(receipt["campaign_bytes_identical"])
        self.assertTrue(receipt["control_view_identical"])
        self.assertTrue(receipt["no_effect"])
        self.assertEqual(receipt["recommendations_applied"], 0)
        self.assertEqual(receipt["compute_submissions"], 0)
        self.assertEqual(response["review"]["status"], "pending")

    def test_fake_provider_failure_is_one_call_safe_and_not_retried(self):
        provider = _FailingProvider()
        with tempfile.TemporaryDirectory() as temporary:
            scope_path, scope_sha256 = self._authorized_scope(temporary)
            out_dir = Path(temporary) / "out"
            with patch(
                "bio_sfm_designer.experiments.w6_v4_live_campaign._git_porcelain",
                return_value="",
            ):
                receipt = capture_live_campaign(
                    provider=provider,
                    scope_path=scope_path,
                    out_dir=out_dir,
                    repo_root=ROOT,
                    approved_scope_sha256=scope_sha256,
                    source_commit="unit-test-source",
                )
            capture_text = (out_dir / "transport_capture.json").read_text()
            receipt_text = (out_dir / "receipt.json").read_text()
            response_exists = (out_dir / "response_pending_review.json").exists()
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            receipt["status"],
            "w6_v4_live_campaign_incomplete_no_retry",
        )
        self.assertEqual(receipt["failed_calls"], 1)
        self.assertEqual(receipt["failure_reason"], "server_error")
        self.assertTrue(receipt["campaign_bytes_identical"])
        self.assertTrue(receipt["control_view_identical"])
        self.assertFalse(response_exists)
        self.assertNotIn("secret-bearing", capture_text)
        self.assertNotIn("secret-bearing", receipt_text)

    def test_invalid_response_fails_contract_without_control_drift(self):
        provider = _MetadataProvider(
            json.dumps(
                {
                    "reason": "change the decision",
                    "hypothesis": "collect evidence",
                    "stop": False,
                }
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            scope_path, scope_sha256 = self._authorized_scope(temporary)
            out_dir = Path(temporary) / "out"
            with patch(
                "bio_sfm_designer.experiments.w6_v4_live_campaign._git_porcelain",
                return_value="",
            ):
                receipt = capture_live_campaign(
                    provider=provider,
                    scope_path=scope_path,
                    out_dir=out_dir,
                    repo_root=ROOT,
                    approved_scope_sha256=scope_sha256,
                    source_commit="unit-test-source",
                )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            receipt["status"],
            "w6_v4_live_campaign_contract_fail",
        )
        self.assertEqual(receipt["event_status"], "invalid_response")
        self.assertTrue(receipt["no_effect"])
        self.assertEqual(receipt["recommendations_applied"], 0)

    def test_scope_digest_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError, "scope SHA-256 mismatch"):
            load_and_validate_scope(
                SCOPE,
                repo_root=ROOT,
                expected_scope_sha256="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
