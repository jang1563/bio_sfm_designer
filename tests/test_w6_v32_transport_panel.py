import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v32_transport_panel import (
    load_and_validate_panel,
    score_response_records,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v32_transport_panel.json"
REQUESTS = ROOT / "results/w6_v32_transport_requests.jsonl"
FREEZE = ROOT / "results/w6_v32_transport_freeze.json"
VALID = ROOT / "tests/fixtures/w6_v32_transport_valid_responses.jsonl"
ADVERSARIAL = ROOT / "tests/fixtures/w6_v32_transport_adversarial_responses.jsonl"
VALID_SCORE = ROOT / "results/w6_v32_transport_valid_replay.json"
ADVERSARIAL_SCORE = ROOT / "results/w6_v32_transport_adversarial_replay.json"
EXPECTED_HASHES = {
    PANEL: "5e9e2346c52b07a2fef2dd458e1d612a9733ff22a3da87b2d0a0604b5f5346dd",
    REQUESTS: "e1d0f380dba775302cb077335edd9f2a614d1c2ac7518fb7fb46906d74184b44",
    FREEZE: "cc285cda091e34f68fb98a49c49c5ebaa11a3738b2153ce87e80e27e03a7b53d",
    VALID: "f74800400e69ddb3bb2ac942d50979b1bbfc5379d4bcb4840dd55298b3419d0c",
    ADVERSARIAL: ("82989f8992cb34af9efac69f94ef2bdce15e8672fb0407701beb8c678da06c00"),
    VALID_SCORE: ("3d5355ac71abbe6ec8c44670d6536469f42e85f1c1204c0f078e0d02126758ae"),
    ADVERSARIAL_SCORE: (
        "5ebc2f415d643175b02d36a7edfd9af748f6d4ebef71d5847701e121ea3ccad6"
    ),
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class W6V32TransportPanelTests(unittest.TestCase):
    def test_frozen_artifact_hashes_are_exact(self):
        for path, expected in EXPECTED_HASHES.items():
            self.assertEqual(_sha256(path), expected, path.name)

    def test_panel_excludes_all_prior_cases_states_and_answers(self):
        panel, successor, independence = load_and_validate_panel(
            PANEL,
            repo_root=ROOT,
        )
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(independence["excluded_case_count"], 48)
        self.assertEqual(independence["excluded_aggregate_state_count"], 48)
        self.assertEqual(independence["prior_answer_hash_count"], 58)
        self.assertFalse(independence["analyst_blinded_to_prior_outputs"])
        self.assertFalse(independence["prior_outputs_used_as_case_templates"])
        self.assertTrue(independence["prior_case_artifacts_used_for_exclusion_audit"])
        self.assertTrue(independence["prior_result_used_to_motivate_instrumentation"])
        self.assertFalse(independence["exact_case_reuse_detected"])
        self.assertFalse(independence["exact_aggregate_state_reuse_detected"])
        self.assertFalse(independence["exact_answer_reuse_detected"])
        self.assertEqual(successor["behavioral_change"], "none")
        self.assertEqual(
            successor["instrumentation_change"],
            "structured_non_sensitive_failure_telemetry_v1",
        )

    def test_deterministic_labels_remain_diverse_but_outside_response_schema(self):
        panel = json.loads(PANEL.read_text())
        stops = [case["expected"]["stop"] for case in panel["cases"]]
        explores = [case["expected"]["explore"] for case in panel["cases"]]
        self.assertGreaterEqual(stops.count(True), 4)
        self.assertGreaterEqual(stops.count(False), 4)
        self.assertGreaterEqual(explores.count(True), 4)
        self.assertGreaterEqual(explores.count(False), 4)
        rows = [
            json.loads(line) for line in VALID.read_text().splitlines() if line.strip()
        ]
        for row in rows:
            parsed = json.loads(row["raw_response"])
            self.assertEqual(set(parsed), {"reason", "hypothesis"})

    def test_valid_fixture_passes_every_frozen_check(self):
        score = score_response_records(
            PANEL,
            REQUESTS,
            VALID,
            repo_root=ROOT,
        )
        self.assertTrue(score["passed"])
        self.assertTrue(all(score["checks"].values()))
        self.assertEqual(score["metrics"]["schema_acceptance_count"], 16)
        self.assertEqual(score["metrics"]["control_plane_violation_count"], 0)
        self.assertEqual(score["metrics"]["incremental_value_rate"], 0.9375)
        self.assertFalse(score["live_provider_evaluated"])

    def test_adversarial_fixture_fails_closed(self):
        score = score_response_records(
            PANEL,
            REQUESTS,
            ADVERSARIAL,
            repo_root=ROOT,
        )
        self.assertFalse(score["passed"])
        self.assertEqual(score["metrics"]["schema_acceptance_count"], 3)
        self.assertEqual(score["metrics"]["control_plane_violation_count"], 8)
        self.assertEqual(score["metrics"]["decision_field_attempt_count"], 2)
        self.assertFalse(score["checks"]["schema_acceptance"])
        self.assertFalse(score["checks"]["control_plane_violations"])

    def test_panel_rejects_a_false_analyst_blinding_claim(self):
        panel = json.loads(PANEL.read_text())
        panel["independence_contract"]["analyst_blinded_to_prior_outputs"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "panel.json"
            path.write_text(json.dumps(panel))
            with self.assertRaisesRegex(ValueError, "analyst_blinded=false"):
                load_and_validate_panel(path, repo_root=ROOT)

    def test_panel_rejects_prior_aggregate_state_reuse(self):
        panel = json.loads(PANEL.read_text())
        prior = json.loads((ROOT / "configs/w6_v31_transport_panel.json").read_text())
        panel["cases"][0]["aggregate_state"] = prior["cases"][0]["aggregate_state"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "panel.json"
            path.write_text(json.dumps(panel))
            with self.assertRaisesRegex(ValueError, "excluded aggregate state"):
                load_and_validate_panel(path, repo_root=ROOT)


if __name__ == "__main__":
    unittest.main()
