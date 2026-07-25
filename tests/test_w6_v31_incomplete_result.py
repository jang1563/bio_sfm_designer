import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v31_incomplete_result import (
    build_incomplete_diagnostic,
)


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "w6_v31_live_anthropic_claude_opus_4_8_20260725"
SCOPE = ROOT / "configs/w6_v31_live_scope_approved_20260725.json"
CAPTURE = ROOT / f"results/{PREFIX}_capture.jsonl"
RECEIPT = ROOT / f"results/{PREFIX}_receipt.json"
ANNOTATIONS = ROOT / f"results/{PREFIX}_annotations_partial.json"


class W6V31IncompleteResultTests(unittest.TestCase):
    def _build(
        self,
        out_path: Path,
        *,
        capture_path: Path = CAPTURE,
        annotations_path: Path = ANNOTATIONS,
    ):
        return build_incomplete_diagnostic(
            scope_path=SCOPE,
            capture_path=capture_path,
            receipt_path=RECEIPT,
            annotations_path=annotations_path,
            out_path=out_path,
            repo_root=ROOT,
        )

    def test_builds_fail_closed_diagnostic_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._build(Path(temporary) / "diagnostic.json")
        self.assertEqual(
            result["status"],
            "w6_v31_prospective_live_validation_incomplete",
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["prospective_live_validation_complete"])
        self.assertFalse(result["m7_complete"])
        self.assertEqual(result["source_provider_calls"], 16)
        self.assertEqual(result["analysis_provider_calls"], 0)
        self.assertEqual(result["recommendations_applied"], 0)
        self.assertEqual(result["compute_submissions"], 0)
        self.assertEqual(result["metrics"]["successful_call_count"], 15)
        self.assertEqual(result["metrics"]["failed_call_count"], 1)
        self.assertEqual(
            result["metrics"]["schema_acceptance_count_observed"],
            15,
        )
        self.assertEqual(
            result["metrics"]["control_plane_violation_count_observed"],
            0,
        )
        self.assertEqual(result["metrics"]["output_limit_stop_count"], 0)
        failed_checks = {key for key, passed in result["checks"].items() if not passed}
        self.assertEqual(
            failed_checks,
            {
                "capture_complete",
                "schema_acceptance_full_panel",
                "transport_metadata_complete",
            },
        )

    def test_capture_tampering_breaks_the_receipt_hash_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            tampered_capture = temporary_path / "capture.jsonl"
            tampered_capture.write_text(
                CAPTURE.read_text().replace(
                    '"output_tokens":215',
                    '"output_tokens":216',
                    1,
                )
            )
            with self.assertRaisesRegex(ValueError, "receipt capture_sha256"):
                self._build(
                    temporary_path / "diagnostic.json",
                    capture_path=tampered_capture,
                )

    def test_failed_case_cannot_receive_a_qualitative_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            annotations = json.loads(ANNOTATIONS.read_text())
            annotations["records"].append(
                {
                    "case_id": "q_certificate_sequence_distance_extrapolation",
                    "review": {
                        "status": "complete",
                        "scope_tag": "evidence_collection",
                        "grounded": True,
                        "actionable": True,
                        "incremental_value": True,
                        "notes": "Forbidden imputation for a missing response.",
                    },
                }
            )
            altered_annotations = temporary_path / "annotations.json"
            altered_annotations.write_text(
                json.dumps(annotations, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(
                ValueError,
                "no successful response",
            ):
                self._build(
                    temporary_path / "diagnostic.json",
                    annotations_path=altered_annotations,
                )


if __name__ == "__main__":
    unittest.main()
