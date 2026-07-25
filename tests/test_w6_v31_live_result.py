import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "w6_v31_live_anthropic_claude_opus_4_8_20260725"
SCOPE = ROOT / "configs/w6_v31_live_scope_approved_20260725.json"
CAPTURE = ROOT / f"results/{PREFIX}_capture.jsonl"
RECEIPT = ROOT / f"results/{PREFIX}_receipt.json"
ANNOTATIONS = ROOT / f"results/{PREFIX}_annotations_partial.json"
DIAGNOSTIC = ROOT / f"results/{PREFIX}_incomplete_diagnostic.json"
EXPECTED_HASHES = {
    SCOPE: "b8b667a136a6dbdb2d723bce2586211a6f70c403d6186699e5a80349ba2753ab",
    CAPTURE: "0a350d77af7c854b1593a977574b6ceef53b0a81ac67f1b4a95981e754f1790e",
    RECEIPT: "5ee84cbaf69575cecca04ec35c7d83e2e6aae979e0a346cace253200f4a317c4",
    ANNOTATIONS: ("7e59062fc09729b7ce446874b0e8f596344d0be1f29df04281fc849189cb433e"),
    DIAGNOSTIC: ("49831055538c8476053ce73b7052ba601d182afea17f5453dd9bb22fe4dbe626"),
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class W6V31LiveResultTests(unittest.TestCase):
    def test_public_live_artifact_hashes_are_frozen(self):
        for path, expected in EXPECTED_HASHES.items():
            self.assertEqual(_sha256(path), expected, path.name)

    def test_capture_and_diagnostic_form_one_hash_chain(self):
        receipt = json.loads(RECEIPT.read_text())
        diagnostic = json.loads(DIAGNOSTIC.read_text())
        sources = diagnostic["source_artifacts"]
        self.assertEqual(receipt["scope_sha256"], _sha256(SCOPE))
        self.assertEqual(receipt["capture_sha256"], _sha256(CAPTURE))
        self.assertEqual(sources["scope"]["sha256"], _sha256(SCOPE))
        self.assertEqual(sources["capture"]["sha256"], _sha256(CAPTURE))
        self.assertEqual(sources["receipt"]["sha256"], _sha256(RECEIPT))
        self.assertEqual(
            sources["annotations"]["sha256"],
            _sha256(ANNOTATIONS),
        )
        self.assertTrue(receipt["source_worktree_clean"])
        self.assertTrue(receipt["approval_consumed"])
        self.assertFalse(receipt["live_execution_authorized_for_additional_calls"])

    def test_result_is_incomplete_and_never_promoted_to_a_panel_pass(self):
        receipt = json.loads(RECEIPT.read_text())
        diagnostic = json.loads(DIAGNOSTIC.read_text())
        self.assertEqual(
            receipt["status"],
            "w6_v31_live_capture_incomplete_no_retry",
        )
        self.assertEqual(receipt["attempted_calls"], 16)
        self.assertEqual(receipt["succeeded_calls"], 15)
        self.assertEqual(receipt["failed_calls"], 1)
        self.assertEqual(receipt["sdk_retries_per_call"], 0)
        self.assertEqual(receipt["recommendations_applied"], 0)
        self.assertFalse(diagnostic["passed"])
        self.assertEqual(
            diagnostic["formal_interpretation"],
            "not_passing_incomplete_capture",
        )
        self.assertFalse(diagnostic["prospective_live_validation_complete"])
        self.assertFalse(diagnostic["m7_complete"])
        self.assertEqual(
            diagnostic["transport_interpretation"]["result"],
            "supported_on_successful_calls_but_not_validated_panelwide",
        )

    def test_observed_successes_are_schema_safe_but_cover_only_fifteen_cases(self):
        capture_rows = _read_jsonl(CAPTURE)
        diagnostic = json.loads(DIAGNOSTIC.read_text())
        successes = [row for row in capture_rows if row["status"] == "succeeded"]
        failures = [row for row in capture_rows if row["status"] != "succeeded"]
        self.assertEqual(len(successes), 15)
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            failures[0]["case_id"],
            "q_certificate_sequence_distance_extrapolation",
        )
        self.assertEqual(failures[0]["error_type"], "RuntimeError")
        self.assertTrue(all(not row["applied"] for row in capture_rows))
        self.assertTrue(all(row["stop_reason"] == "end_turn" for row in successes))
        metrics = diagnostic["metrics"]
        self.assertEqual(metrics["schema_acceptance_rate_observed"], 1.0)
        self.assertEqual(metrics["schema_evaluable_coverage_rate"], 0.9375)
        self.assertEqual(
            metrics["control_plane_violation_count_observed"],
            0,
        )
        self.assertEqual(metrics["output_limit_stop_count"], 0)
        self.assertEqual(metrics["observed_output_tokens_max"], 302)


if __name__ == "__main__":
    unittest.main()
