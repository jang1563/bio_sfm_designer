import copy
import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bio_sfm_designer.experiments.w6_v3_hypothesis_only import (
    build_request_records,
    freeze_contract,
    load_and_validate_contract,
    materialize_reduced_v2_fixture_responses,
    replay_v2_live_as_post_hoc,
    score_response_records,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/w6_v3_hypothesis_only_contract.json"
REQUESTS = ROOT / "results/w6_v3_hypothesis_only_requests.jsonl"
FREEZE = ROOT / "results/w6_v3_hypothesis_only_freeze.json"
VALID_V2_SPECS = (
    ROOT / "tests/fixtures/w6_v2_shadow_panel_valid_response_specs.json"
)
ADVERSARIAL_V2_SPECS = (
    ROOT / "tests/fixtures/w6_v2_shadow_panel_adversarial_response_specs.json"
)
VALID_RESPONSES = (
    ROOT / "tests/fixtures/w6_v3_hypothesis_only_valid_responses.jsonl"
)
ADVERSARIAL_RESPONSES = (
    ROOT / "tests/fixtures/w6_v3_hypothesis_only_adversarial_responses.jsonl"
)
VALID_SCORE = ROOT / "results/w6_v3_hypothesis_only_valid_replay.json"
ADVERSARIAL_SCORE = (
    ROOT / "results/w6_v3_hypothesis_only_adversarial_replay.json"
)
POST_HOC_SCORE = ROOT / "results/w6_v3_post_hoc_development_replay.json"
LIVE_REVIEWED = (
    ROOT
    / "results/w6_v2_live_shadow_anthropic_claude_opus_4_8_20260723_responses_reviewed.jsonl"
)
EXPECTED_CONTRACT_SHA256 = (
    "0435ff8e82842c6feba9e4ecb54f2dce8d39d380ea7b1f81b0364ac84105f7ad"
)
EXPECTED_REQUEST_SHA256 = (
    "ce7de81e2685a1ea02468b1125d8d0f0f09f33b2d99a9ac70212b4863831c8f8"
)
EXPECTED_VALID_RESPONSE_SHA256 = (
    "74800f5fc38b3d384fd2247f2cb56a6f119e34eb73b405e5b137adffba073330"
)
EXPECTED_ADVERSARIAL_RESPONSE_SHA256 = (
    "0ef0b4795fe6d850fcbdbccd70456c78feffc122a382a040df28c2063c26baa6"
)
EXPECTED_FREEZE_SHA256 = (
    "e325570874add5de4670c9cba1e420e855c96c40c6843eba9a0e64eabda7a2c2"
)
EXPECTED_VALID_SCORE_SHA256 = (
    "e25c317a66ef8433cce77395381769a5fe9588f83d84ccec7dc8d0ee6d9a697d"
)
EXPECTED_ADVERSARIAL_SCORE_SHA256 = (
    "945f0ec41ddbdd1b731f27cb2580ef68e95b9b7a17164b0f8575939bebf52d58"
)
EXPECTED_POST_HOC_SCORE_SHA256 = (
    "2e97e51a01d36bfe325367c80bb7802de5623618a2e80028a8cdaa7a8f1a2e06"
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_jsonl(path, records):
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )
    )


class W6V3HypothesisOnlyTests(unittest.TestCase):
    def test_contract_and_request_hashes_are_frozen(self):
        contract, panel, audit = load_and_validate_contract(
            CONTRACT,
            repo_root=ROOT,
        )
        self.assertEqual(_sha256(CONTRACT), EXPECTED_CONTRACT_SHA256)
        self.assertEqual(_sha256(REQUESTS), EXPECTED_REQUEST_SHA256)
        self.assertEqual(contract["source_panel"]["case_count"], 16)
        self.assertEqual(panel["case_count"], 16)
        self.assertTrue(all(row["ok"] for row in audit))
        self.assertFalse(contract["api_calls_allowed"])
        self.assertFalse(contract["provider_calls_allowed"])

    def test_requests_expose_immutable_decisions_without_hidden_labels(self):
        _, panel, generated, _ = build_request_records(
            CONTRACT,
            repo_root=ROOT,
        )
        self.assertEqual(generated, _load_jsonl(REQUESTS))
        for case, request in zip(panel["cases"], generated):
            self.assertEqual(
                request["deterministic_decision"],
                {
                    "stop": case["expected"]["stop"],
                    "explore": case["expected"]["explore"],
                },
            )
            self.assertIn("deterministic_controller_decision", request["prompt"])
            self.assertIn('"immutable": true', request["prompt"])
            self.assertNotIn('"expected"', request["prompt"])
            self.assertNotIn("baseline_plan", request["prompt"])
            self.assertNotIn("hidden_truth", request["prompt"])
            self.assertNotIn("candidate_sequence", request["prompt"])

    def test_valid_replay_passes_without_decision_metrics_or_effect(self):
        report = score_response_records(
            CONTRACT,
            REQUESTS,
            VALID_RESPONSES,
            repo_root=ROOT,
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "offline_replay_pass")
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 16)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 0)
        self.assertEqual(report["metrics"]["decision_field_attempt_count"], 0)
        self.assertEqual(report["metrics"]["incremental_value_rate"], 0.5625)
        self.assertFalse(report["decision_accuracy_scored"])
        self.assertEqual(report["recommendations_applied"], 0)
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["prospective_live_validation_complete"])

    def test_adversarial_replay_fails_closed(self):
        report = score_response_records(
            CONTRACT,
            REQUESTS,
            ADVERSARIAL_RESPONSES,
            repo_root=ROOT,
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "offline_replay_fail")
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 5)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 9)
        self.assertEqual(report["metrics"]["decision_field_attempt_count"], 1)
        self.assertFalse(report["checks"]["schema_acceptance"])
        self.assertFalse(report["checks"]["control_plane_violations"])

    def test_fixture_reduction_is_reproducible_and_removes_decisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            valid = Path(temporary) / "valid.jsonl"
            adversarial = Path(temporary) / "adversarial.jsonl"
            materialize_reduced_v2_fixture_responses(
                REQUESTS,
                VALID_V2_SPECS,
                valid,
            )
            materialize_reduced_v2_fixture_responses(
                REQUESTS,
                ADVERSARIAL_V2_SPECS,
                adversarial,
            )
            self.assertEqual(valid.read_bytes(), VALID_RESPONSES.read_bytes())
            self.assertEqual(
                adversarial.read_bytes(),
                ADVERSARIAL_RESPONSES.read_bytes(),
            )
        self.assertEqual(_sha256(VALID_RESPONSES), EXPECTED_VALID_RESPONSE_SHA256)
        self.assertEqual(
            _sha256(ADVERSARIAL_RESPONSES),
            EXPECTED_ADVERSARIAL_RESPONSE_SHA256,
        )
        source = json.loads(VALID_V2_SPECS.read_text())["records"][0][
            "recommendation"
        ]
        reduced = json.loads(_load_jsonl(VALID_RESPONSES)[0]["raw_response"])
        self.assertEqual(reduced["reason"], source["reason"])
        self.assertEqual(reduced["hypothesis"], source["hypothesis"])
        self.assertNotIn("stop", reduced)
        self.assertNotIn("explore", reduced)

    def test_extra_decision_field_is_rejected_and_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "responses.jsonl"
            records = copy.deepcopy(_load_jsonl(VALID_RESPONSES))
            payload = json.loads(records[0]["raw_response"])
            payload["stop"] = True
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            records[0]["raw_response"] = raw
            records[0]["response_sha256"] = hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest()
            _write_jsonl(path, records)
            report = score_response_records(
                CONTRACT,
                REQUESTS,
                path,
                repo_root=ROOT,
            )
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["decision_field_attempt_count"], 1)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 1)
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 15)

    def test_freeze_and_scoring_make_no_network_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            requests = Path(temporary) / "requests.jsonl"
            freeze = Path(temporary) / "freeze.json"
            responses = Path(temporary) / "responses.jsonl"
            with mock.patch.object(
                socket,
                "socket",
                side_effect=AssertionError("network access attempted"),
            ):
                freeze_report = freeze_contract(
                    CONTRACT,
                    requests,
                    freeze,
                    repo_root=ROOT,
                )
                materialize_reduced_v2_fixture_responses(
                    requests,
                    VALID_V2_SPECS,
                    responses,
                )
                score = score_response_records(
                    CONTRACT,
                    requests,
                    responses,
                    repo_root=ROOT,
                )
        self.assertEqual(freeze_report["provider_calls"], 0)
        self.assertTrue(score["passed"])

    def test_tracked_reports_match_recomputed_scores(self):
        self.assertEqual(_sha256(FREEZE), EXPECTED_FREEZE_SHA256)
        self.assertEqual(_sha256(VALID_SCORE), EXPECTED_VALID_SCORE_SHA256)
        self.assertEqual(
            _sha256(ADVERSARIAL_SCORE),
            EXPECTED_ADVERSARIAL_SCORE_SHA256,
        )
        self.assertEqual(
            json.loads(VALID_SCORE.read_text()),
            score_response_records(
                CONTRACT,
                REQUESTS,
                VALID_RESPONSES,
                repo_root=ROOT,
            ),
        )
        self.assertEqual(
            json.loads(ADVERSARIAL_SCORE.read_text()),
            score_response_records(
                CONTRACT,
                REQUESTS,
                ADVERSARIAL_RESPONSES,
                repo_root=ROOT,
            ),
        )
        freeze = json.loads(FREEZE.read_text())
        self.assertEqual(freeze["request_sha256"], EXPECTED_REQUEST_SHA256)
        self.assertFalse(freeze["prospective_live_validation_complete"])

    def test_post_hoc_artifact_cannot_claim_validation(self):
        self.assertEqual(_sha256(POST_HOC_SCORE), EXPECTED_POST_HOC_SCORE_SHA256)
        report = json.loads(POST_HOC_SCORE.read_text())
        self.assertTrue(report["contract_checks_passed"])
        self.assertFalse(report["prospective_validation"])
        self.assertFalse(report["independent_evidence"])
        self.assertFalse(report["deployment_authorized"])
        self.assertFalse(report["future_provider_calls_authorized"])
        self.assertFalse(report["source_v2_decision_contract_passed"])
        self.assertEqual(report["historical_provider_calls"], 16)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(len(report["component_hashes"]), 16)

    @unittest.skipUnless(
        LIVE_REVIEWED.exists(),
        "local ignored live responses are unavailable in a public clone",
    )
    def test_local_post_hoc_replay_matches_tracked_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "post_hoc.json"
            replay = replay_v2_live_as_post_hoc(
                CONTRACT,
                REQUESTS,
                out,
                repo_root=ROOT,
            )
        self.assertEqual(replay, json.loads(POST_HOC_SCORE.read_text()))


if __name__ == "__main__":
    unittest.main()
