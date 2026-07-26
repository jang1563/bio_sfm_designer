import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bio_sfm_designer.experiments.w6_v4_campaign_review import (
    apply_campaign_review,
)
from bio_sfm_designer.experiments.w6_v4_live_campaign import (
    capture_live_campaign,
)
from bio_sfm_designer.loop.providers import OrchestrationProviderResult


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "configs/w6_v4_live_campaign_scope.json"
CAMPAIGN = ROOT / "configs/w6_v4_gated_batch_campaign.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _MetadataProvider:
    def __init__(self, text):
        self.text = text

    def call_with_metadata(self, prompt):
        return OrchestrationProviderResult(
            text=self.text,
            input_tokens=211,
            output_tokens=57,
            stop_reason="end_turn",
        )


class W6V4CampaignReviewTests(unittest.TestCase):
    def _live_inputs(self, root):
        campaign = json.loads(CAMPAIGN.read_text())
        scope = json.loads(SCOPE.read_text())
        scope["scope_id"] = "w6-v4-review-test-authorized"
        scope["live_execution_authorized"] = True
        scope["approval_basis"] = "Unit-test-only fake provider authorization."
        scope_path = Path(root) / "authorized_scope.json"
        scope_path.write_text(json.dumps(scope, indent=2, sort_keys=True) + "\n")
        provider = _MetadataProvider(
            json.dumps(
                campaign["valid_fixture"]["response"],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        out_dir = Path(root) / "live"
        with patch(
            "bio_sfm_designer.experiments.w6_v4_live_campaign._git_porcelain",
            return_value="",
        ):
            capture_live_campaign(
                provider=provider,
                scope_path=scope_path,
                out_dir=out_dir,
                repo_root=ROOT,
                approved_scope_sha256=_sha256(scope_path),
                source_commit="unit-test-source",
            )
        return campaign, out_dir

    def _annotations(self, root, campaign, out_dir, **review_updates):
        review = dict(campaign["valid_fixture"]["review"])
        review.update(review_updates)
        annotations = {
            "schema_version": "w6_v4_campaign_review_annotations_v1",
            "source_campaign_config_sha256": _sha256(CAMPAIGN),
            "source_live_receipt_sha256": _sha256(out_dir / "receipt.json"),
            "source_response_sha256": _sha256(out_dir / "response_pending_review.json"),
            "reviewer": {
                "identity": "independent-test-reviewer",
                "type": "offline_provider_independent_rubric_review",
                "provider_independent": True,
                "reviewed_at": "2026-07-26T00:00:00Z",
            },
            "review": review,
        }
        path = Path(root) / "annotations.json"
        path.write_text(json.dumps(annotations, indent=2, sort_keys=True) + "\n")
        return path

    def _apply(self, root, campaign, out_dir, annotations):
        return apply_campaign_review(
            campaign_config_path=CAMPAIGN,
            live_receipt_path=out_dir / "receipt.json",
            response_path=out_dir / "response_pending_review.json",
            annotations_path=annotations,
            reviewed_response_path=Path(root) / "reviewed_response.json",
            result_path=Path(root) / "result.json",
            repo_root=ROOT,
        )

    def test_positive_independent_review_completes_bounded_m7(self):
        with tempfile.TemporaryDirectory() as temporary:
            campaign, out_dir = self._live_inputs(temporary)
            annotations = self._annotations(
                temporary,
                campaign,
                out_dir,
            )
            source_response = json.loads(
                (out_dir / "response_pending_review.json").read_text()
            )
            result = self._apply(
                temporary,
                campaign,
                out_dir,
                annotations,
            )
            reviewed = json.loads(
                (Path(temporary) / "reviewed_response.json").read_text()
            )
        self.assertEqual(
            result["status"],
            "w6_v4_gated_batch_prospective_live_pass",
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["m7_complete"])
        self.assertEqual(result["source_provider_calls"], 1)
        self.assertEqual(result["review_provider_calls"], 0)
        self.assertEqual(result["scoring_provider_calls"], 0)
        self.assertEqual(
            source_response["raw_response"],
            reviewed["raw_response"],
        )

    def test_negative_qualitative_review_is_a_completed_non_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            campaign, out_dir = self._live_inputs(temporary)
            annotations = self._annotations(
                temporary,
                campaign,
                out_dir,
                incremental_value=False,
                notes="Actionable but adds no discriminator beyond the baseline.",
            )
            result = self._apply(
                temporary,
                campaign,
                out_dir,
                annotations,
            )
        self.assertEqual(
            result["status"],
            "w6_v4_gated_batch_prospective_live_fail",
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["m7_complete"])

    def test_provider_dependent_reviewer_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            campaign, out_dir = self._live_inputs(temporary)
            annotations_path = self._annotations(
                temporary,
                campaign,
                out_dir,
            )
            annotations = json.loads(annotations_path.read_text())
            annotations["reviewer"]["provider_independent"] = False
            annotations_path.write_text(json.dumps(annotations))
            with self.assertRaisesRegex(ValueError, "independent"):
                self._apply(
                    temporary,
                    campaign,
                    out_dir,
                    annotations_path,
                )

    def test_annotation_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            campaign, out_dir = self._live_inputs(temporary)
            annotations_path = self._annotations(
                temporary,
                campaign,
                out_dir,
            )
            annotations = json.loads(annotations_path.read_text())
            annotations["source_response_sha256"] = "0" * 64
            annotations_path.write_text(json.dumps(annotations))
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self._apply(
                    temporary,
                    campaign,
                    out_dir,
                    annotations_path,
                )

    def test_response_and_annotations_cannot_drift_from_live_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            campaign, out_dir = self._live_inputs(temporary)
            response_path = out_dir / "response_pending_review.json"
            response = json.loads(response_path.read_text())
            replacement = {
                "reason": "A replacement response must remain bound to the live receipt.",
                "hypothesis": "Blind a second known-safe control before interpreting the screen.",
            }
            raw_response = json.dumps(
                replacement,
                sort_keys=True,
                separators=(",", ":"),
            )
            response["raw_response"] = raw_response
            response["response_sha256"] = hashlib.sha256(
                raw_response.encode()
            ).hexdigest()
            response["recommendation"] = replacement
            response_path.write_text(
                json.dumps(response, indent=2, sort_keys=True) + "\n"
            )
            annotations_path = self._annotations(
                temporary,
                campaign,
                out_dir,
            )
            with self.assertRaisesRegex(
                ValueError,
                "live receipt response SHA-256 mismatch",
            ):
                self._apply(
                    temporary,
                    campaign,
                    out_dir,
                    annotations_path,
                )


if __name__ == "__main__":
    unittest.main()
