import copy
import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bio_sfm_designer.experiments.w6_v3_prospective_panel import (
    build_request_records,
    freeze_panel,
    load_and_validate_panel,
    materialize_fixture_responses,
    score_response_records,
)


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "configs/w6_v3_prospective_hypothesis_panel.json"
V2_PANEL = ROOT / "configs/w6_v2_frozen_shadow_panel.json"
REQUESTS = ROOT / "results/w6_v3_prospective_hypothesis_requests.jsonl"
FREEZE = ROOT / "results/w6_v3_prospective_hypothesis_freeze.json"
VALID_RESPONSES = (
    ROOT / "tests/fixtures/w6_v3_prospective_hypothesis_valid_responses.jsonl"
)
ADVERSARIAL_RESPONSES = (
    ROOT
    / "tests/fixtures/w6_v3_prospective_hypothesis_adversarial_responses.jsonl"
)
VALID_SCORE = ROOT / "results/w6_v3_prospective_hypothesis_valid_replay.json"
ADVERSARIAL_SCORE = (
    ROOT / "results/w6_v3_prospective_hypothesis_adversarial_replay.json"
)
EXPECTED_PANEL_SHA256 = (
    "1387ada9cefc4095a4a3bb16adf518f4ffed89da54e81e0ce36cc73d8dbaac2a"
)
EXPECTED_REQUEST_SHA256 = (
    "f2680504c12f77281c82562c66d3b47ad943e29d895805f0166a2403044bb387"
)
EXPECTED_FREEZE_SHA256 = (
    "f9d1fa5254c970c0bab4add6ea2ca0594bdaaa8d622bb4071dd5759507f94e4d"
)
EXPECTED_VALID_RESPONSE_SHA256 = (
    "3cb6fcf938a10c5162439a8eab5a3402029fc5c91f5fe5be3494c8f3fbc4a4d4"
)
EXPECTED_ADVERSARIAL_RESPONSE_SHA256 = (
    "62523ebd452b09f7b2832631d8599d160ab71a0581ed46bb8122b6f474eea00a"
)
EXPECTED_VALID_SCORE_SHA256 = (
    "32a7b4cae3673cbfe22cb0df95031222765a8892d708012682dc4a14ad56aa9c"
)
EXPECTED_ADVERSARIAL_SCORE_SHA256 = (
    "e4cc666da6af4411d3949166c16e5692fe8146c34dd6f68f4e3ff88039306e7b"
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path, records):
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )
    )


class W6V3ProspectivePanelTests(unittest.TestCase):
    def test_panel_and_request_packet_are_frozen_and_independent(self):
        panel, audit = load_and_validate_panel(PANEL, repo_root=ROOT)
        self.assertEqual(_sha256(PANEL), EXPECTED_PANEL_SHA256)
        self.assertEqual(_sha256(REQUESTS), EXPECTED_REQUEST_SHA256)
        self.assertEqual(panel["case_count"], 16)
        self.assertTrue(panel["prospective_live_panel"])
        self.assertFalse(panel["api_calls_allowed"])
        self.assertFalse(panel["provider_calls_allowed"])
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["excluded_case_count"], 16)
        self.assertEqual(audit["excluded_aggregate_state_count"], 16)
        self.assertFalse(audit["prior_provider_outputs_used"])
        self.assertFalse(audit["prior_provider_reviews_used"])
        self.assertFalse(audit["exact_case_or_source_reuse_detected"])
        self.assertFalse(audit["exact_aggregate_state_reuse_detected"])

    def test_requests_are_reproducible_without_hidden_answers_or_v2_sources(self):
        panel, generated, _ = build_request_records(PANEL, repo_root=ROOT)
        self.assertEqual(generated, _load_jsonl(REQUESTS))
        independence = panel["independence_contract"]
        forbidden = (
            independence["forbidden_case_ids"]
            + independence["forbidden_source_paths"]
        )
        for case, request in zip(panel["cases"], generated):
            self.assertEqual(
                request["deterministic_decision"],
                {
                    "stop": case["expected"]["stop"],
                    "explore": case["expected"]["explore"],
                },
            )
            self.assertIn("deterministic_controller_decision", request["prompt"])
            self.assertNotIn('"expected"', request["prompt"])
            self.assertNotIn("baseline_plan", request["prompt"])
            self.assertNotIn('"rationale":', request["prompt"])
            self.assertTrue(
                all(value not in request["prompt"] for value in forbidden)
            )

    def test_valid_offline_replay_passes_without_authority_or_effect(self):
        report = score_response_records(
            PANEL,
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
        self.assertTrue(report["independent_from_w6_v2"])
        self.assertTrue(report["prospective_live_panel"])
        self.assertTrue(report["offline_fixture_only"])
        self.assertFalse(report["live_provider_evaluated"])
        self.assertFalse(report["prospective_live_validation_complete"])
        self.assertEqual(report["recommendations_applied"], 0)
        self.assertEqual(report["provider_calls"], 0)

    def test_adversarial_offline_replay_fails_closed(self):
        report = score_response_records(
            PANEL,
            REQUESTS,
            ADVERSARIAL_RESPONSES,
            repo_root=ROOT,
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "offline_replay_fail")
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 3)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 8)
        self.assertEqual(report["metrics"]["decision_field_attempt_count"], 2)
        self.assertEqual(report["metrics"]["scope_compliance_rate"], 0.9375)
        self.assertFalse(report["checks"]["schema_acceptance"])
        self.assertFalse(report["checks"]["control_plane_violations"])
        self.assertFalse(report["checks"]["scope_compliance"])

    def test_reviewed_live_source_is_labeled_separately_from_fixtures(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "live.jsonl"
            records = copy.deepcopy(_load_jsonl(VALID_RESPONSES))
            for record in records:
                record["response_source"] = "live_shadow_anthropic_test_model"
            _write_jsonl(path, records)
            report = score_response_records(
                PANEL,
                REQUESTS,
                path,
                repo_root=ROOT,
            )
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "prospective_live_validation_pass")
        self.assertEqual(
            report["evaluation_class"],
            "prospective_live_shadow_panel_reviewed",
        )
        self.assertFalse(report["offline_fixture_only"])
        self.assertTrue(report["live_provider_evaluated"])
        self.assertTrue(report["provider_outputs_observed"])
        self.assertEqual(report["source_provider_calls"], 16)
        self.assertEqual(report["scoring_provider_calls"], 0)
        self.assertTrue(report["prospective_live_validation_complete"])

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
                PANEL,
                REQUESTS,
                path,
                repo_root=ROOT,
            )
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["decision_field_attempt_count"], 1)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 1)
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 15)

    def test_exact_v2_aggregate_state_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            panel_path = Path(temporary) / "panel.json"
            panel = json.loads(PANEL.read_text())
            v2_panel = json.loads(V2_PANEL.read_text())
            panel["cases"][0]["aggregate_state"] = copy.deepcopy(
                v2_panel["cases"][0]["aggregate_state"]
            )
            _write_json(panel_path, panel)
            with self.assertRaisesRegex(ValueError, "reuses.*aggregate state"):
                load_and_validate_panel(panel_path, repo_root=ROOT)

    def test_v2_identifier_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            panel_path = Path(temporary) / "panel.json"
            panel = json.loads(PANEL.read_text())
            forbidden_id = panel["independence_contract"]["forbidden_case_ids"][0]
            panel["cases"][0]["aggregate_state"]["source_case"] = forbidden_id
            _write_json(panel_path, panel)
            with self.assertRaisesRegex(ValueError, "forbidden W6-v2"):
                load_and_validate_panel(panel_path, repo_root=ROOT)

    def test_request_or_response_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "requests.jsonl"
            response_path = Path(temporary) / "responses.jsonl"
            requests = copy.deepcopy(_load_jsonl(REQUESTS))
            requests[0]["prompt"] += " tampered"
            _write_jsonl(request_path, requests)
            with self.assertRaisesRegex(ValueError, "request binding mismatch"):
                score_response_records(
                    PANEL,
                    request_path,
                    VALID_RESPONSES,
                    repo_root=ROOT,
                )

            responses = copy.deepcopy(_load_jsonl(VALID_RESPONSES))
            responses[0]["raw_response"] += " "
            _write_jsonl(response_path, responses)
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                score_response_records(
                    PANEL,
                    REQUESTS,
                    response_path,
                    repo_root=ROOT,
                )

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
                freeze_report = freeze_panel(
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
        self.assertEqual(freeze_report["provider_calls"], 0)
        self.assertTrue(score["passed"])

    def test_tracked_reports_match_recomputed_artifacts(self):
        self.assertEqual(_sha256(FREEZE), EXPECTED_FREEZE_SHA256)
        self.assertEqual(_sha256(VALID_SCORE), EXPECTED_VALID_SCORE_SHA256)
        self.assertEqual(
            _sha256(ADVERSARIAL_SCORE),
            EXPECTED_ADVERSARIAL_SCORE_SHA256,
        )
        self.assertEqual(
            json.loads(VALID_SCORE.read_text()),
            score_response_records(
                PANEL,
                REQUESTS,
                VALID_RESPONSES,
                repo_root=ROOT,
            ),
        )
        self.assertEqual(
            json.loads(ADVERSARIAL_SCORE.read_text()),
            score_response_records(
                PANEL,
                REQUESTS,
                ADVERSARIAL_RESPONSES,
                repo_root=ROOT,
            ),
        )
        freeze = json.loads(FREEZE.read_text())
        self.assertEqual(freeze["request_sha256"], EXPECTED_REQUEST_SHA256)
        self.assertTrue(freeze["independent_from_w6_v2"])
        self.assertFalse(freeze["live_provider_evaluated"])
        self.assertFalse(freeze["live_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
