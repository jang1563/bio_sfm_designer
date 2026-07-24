import copy
import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bio_sfm_designer.experiments.w6_v31_transport_panel import (
    build_request_records,
    freeze_panel,
    load_and_validate_panel,
    materialize_fixture_responses,
    score_response_records,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v31_transport_panel.json"
V2_PANEL = ROOT / "configs/w6_v2_frozen_shadow_panel.json"
V3_PANEL = ROOT / "configs/w6_v3_prospective_hypothesis_panel.json"
REQUESTS = ROOT / "results/w6_v31_transport_requests.jsonl"
FREEZE = ROOT / "results/w6_v31_transport_freeze.json"
VALID = ROOT / "tests/fixtures/w6_v31_transport_valid_responses.jsonl"
ADVERSARIAL = (
    ROOT / "tests/fixtures/w6_v31_transport_adversarial_responses.jsonl"
)
VALID_SCORE = ROOT / "results/w6_v31_transport_valid_replay.json"
ADVERSARIAL_SCORE = ROOT / "results/w6_v31_transport_adversarial_replay.json"
EXPECTED_HASHES = {
    PANEL: "bf9575157bddfc223f6511af7215618380b6cd438e28e4bb7f99930f9bd928d9",
    REQUESTS: (
        "ac4ea1a8be736eba127a46cf517d18ba427d265a43f74f7728bb79a2a5e4e1b1"
    ),
    FREEZE: "c0f4883b557e0effd04662964e3beb70ff5185a1898fb6a88ba039cf5a45b73b",
    VALID: "a0925cd823ac6f978fe50e3501f17f0efa9b5fc878dde9434496718d7ed0946a",
    ADVERSARIAL: (
        "b197c81cb64cf00c8b590cca3cf563c7092131b2f9554ce6e695684510612860"
    ),
    VALID_SCORE: (
        "340d4e12892fe2bc8e16ea52a9a902cbc39d7f9f23bf180aa6f583b0b8e4d7d7"
    ),
    ADVERSARIAL_SCORE: (
        "228ca447382b0efe610caeb81fc667df559097cf0638a0944cc184d8cbbf0a2e"
    ),
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class W6V31TransportPanelTests(unittest.TestCase):
    def test_frozen_hashes_and_single_transport_change(self):
        panel, transport, independence = load_and_validate_panel(
            PANEL,
            repo_root=ROOT,
        )
        for path, expected in EXPECTED_HASHES.items():
            self.assertEqual(_sha256(path), expected, path.name)
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(transport["baseline_max_output_tokens"], 256)
        self.assertEqual(transport["successor_max_output_tokens"], 512)
        self.assertEqual(transport["baseline_schema_acceptance_count"], 11)
        self.assertEqual(independence["excluded_case_count"], 32)
        self.assertEqual(independence["excluded_aggregate_state_count"], 32)
        self.assertFalse(independence["exact_answer_reuse_detected"])
        self.assertFalse(panel["api_calls_allowed"])

    def test_requests_are_reproducible_and_exclude_prior_identifiers(self):
        panel, generated, _, _ = build_request_records(PANEL, repo_root=ROOT)
        self.assertEqual(generated, _read_jsonl(REQUESTS))
        forbidden = (
            panel["independence_contract"]["forbidden_case_ids"]
            + panel["independence_contract"]["forbidden_source_paths"]
        )
        for case, request in zip(panel["cases"], generated):
            self.assertEqual(
                request["deterministic_decision"],
                {
                    "stop": case["expected"]["stop"],
                    "explore": case["expected"]["explore"],
                },
            )
            self.assertTrue(
                all(value not in request["prompt"] for value in forbidden)
            )
            self.assertNotIn('"expected"', request["prompt"])
            self.assertNotIn("baseline_plan", request["prompt"])

    def test_valid_and_adversarial_replays_separate(self):
        valid = score_response_records(PANEL, REQUESTS, VALID, repo_root=ROOT)
        adversarial = score_response_records(
            PANEL,
            REQUESTS,
            ADVERSARIAL,
            repo_root=ROOT,
        )
        self.assertTrue(valid["passed"])
        self.assertEqual(valid["metrics"]["schema_acceptance_count"], 16)
        self.assertEqual(valid["metrics"]["control_plane_violation_count"], 0)
        self.assertEqual(valid["metrics"]["incremental_value_rate"], 0.6875)
        self.assertFalse(adversarial["passed"])
        self.assertEqual(adversarial["metrics"]["schema_acceptance_count"], 3)
        self.assertEqual(
            adversarial["metrics"]["control_plane_violation_count"],
            8,
        )
        self.assertEqual(
            adversarial["metrics"]["decision_field_attempt_count"],
            2,
        )

    def test_fixture_materialization_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            valid = Path(temporary) / "valid.jsonl"
            adversarial = Path(temporary) / "adversarial.jsonl"
            materialize_fixture_responses(
                PANEL,
                REQUESTS,
                valid,
                repo_root=ROOT,
                fixture_kind="valid",
            )
            materialize_fixture_responses(
                PANEL,
                REQUESTS,
                adversarial,
                repo_root=ROOT,
                fixture_kind="adversarial",
            )
            self.assertEqual(valid.read_bytes(), VALID.read_bytes())
            self.assertEqual(adversarial.read_bytes(), ADVERSARIAL.read_bytes())

    def test_exact_prior_state_reuse_is_rejected_for_each_panel(self):
        for prior_path in (V2_PANEL, V3_PANEL):
            with self.subTest(prior=prior_path.name):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "panel.json"
                    panel = json.loads(PANEL.read_text())
                    prior = json.loads(prior_path.read_text())
                    panel["cases"][0]["aggregate_state"] = copy.deepcopy(
                        prior["cases"][0]["aggregate_state"]
                    )
                    _write_json(path, panel)
                    with self.assertRaisesRegex(
                        ValueError,
                        "reuses an excluded aggregate state",
                    ):
                        load_and_validate_panel(path, repo_root=ROOT)

    def test_exact_prior_answer_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "panel.json"
            panel = json.loads(PANEL.read_text())
            prior = json.loads(V3_PANEL.read_text())
            panel["cases"][0]["fixture_proposal"]["reason"] = prior["cases"][0][
                "fixture_proposal"
            ]["reason"]
            panel["cases"][0]["fixture_proposal"]["hypothesis"] = prior[
                "cases"
            ][0]["fixture_proposal"]["hypothesis"]
            _write_json(path, panel)
            with self.assertRaisesRegex(ValueError, "reuses an exact prior answer"):
                load_and_validate_panel(path, repo_root=ROOT)

    def test_baseline_failure_hash_or_primary_change_tamper_is_rejected(self):
        original = json.loads(PANEL.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "panel.json"
            tampered = copy.deepcopy(original)
            tampered["transport_hypothesis"]["baseline_score_sha256"] = "0" * 64
            _write_json(path, tampered)
            with self.assertRaisesRegex(ValueError, "baseline SHA-256 mismatch"):
                load_and_validate_panel(path, repo_root=ROOT)

            tampered = copy.deepcopy(original)
            tampered["transport_hypothesis"]["successor_max_output_tokens"] = 768
            _write_json(path, tampered)
            with self.assertRaisesRegex(ValueError, "must be 512"):
                load_and_validate_panel(path, repo_root=ROOT)

    def test_freeze_fixture_and_scoring_make_no_network_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            requests = Path(temporary) / "requests.jsonl"
            freeze = Path(temporary) / "freeze.json"
            responses = Path(temporary) / "responses.jsonl"
            with mock.patch.object(
                socket,
                "socket",
                side_effect=AssertionError("network access attempted"),
            ):
                report = freeze_panel(
                    PANEL,
                    requests,
                    freeze,
                    repo_root=ROOT,
                )
                materialize_fixture_responses(
                    PANEL,
                    requests,
                    responses,
                    repo_root=ROOT,
                    fixture_kind="valid",
                )
                score = score_response_records(
                    PANEL,
                    requests,
                    responses,
                    repo_root=ROOT,
                )
        self.assertEqual(report["provider_calls"], 0)
        self.assertTrue(score["passed"])

    def test_tracked_reports_match_recomputed_scores(self):
        self.assertEqual(
            json.loads(VALID_SCORE.read_text()),
            score_response_records(PANEL, REQUESTS, VALID, repo_root=ROOT),
        )
        self.assertEqual(
            json.loads(ADVERSARIAL_SCORE.read_text()),
            score_response_records(
                PANEL,
                REQUESTS,
                ADVERSARIAL,
                repo_root=ROOT,
            ),
        )


if __name__ == "__main__":
    unittest.main()
