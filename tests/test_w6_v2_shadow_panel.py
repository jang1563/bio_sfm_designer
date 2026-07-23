import copy
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bio_sfm_designer.experiments.w6_v2_shadow_panel import (
    build_request_records,
    freeze_panel,
    load_and_validate_panel,
    materialize_fixture_responses,
    score_response_records,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SNAPSHOT = ROOT / "configs/w6_v2_evidence_snapshot.json"
PANEL = ROOT / "configs/w6_v2_frozen_shadow_panel.json"
REQUESTS = ROOT / "results/w6_v2_shadow_panel_requests.jsonl"
VALID_SPECS = (
    ROOT / "tests/fixtures/w6_v2_shadow_panel_valid_response_specs.json"
)
VALID_RESPONSES = ROOT / "tests/fixtures/w6_v2_shadow_panel_valid_responses.jsonl"
ADVERSARIAL_SPECS = (
    ROOT / "tests/fixtures/w6_v2_shadow_panel_adversarial_response_specs.json"
)
ADVERSARIAL_RESPONSES = (
    ROOT / "tests/fixtures/w6_v2_shadow_panel_adversarial_responses.jsonl"
)
EXPECTED_PANEL_SHA256 = (
    "6ff0c3ad388b9c3123b803e27a710641af120ebc0b5f77a34d1182befae12487"
)
EXPECTED_EVIDENCE_SHA256 = (
    "acba14dea9b8258cfd3b78a260a7d4168c22b3188697c32b5d27979a2419a0b4"
)
EXPECTED_REQUEST_SHA256 = (
    "6223918570516f78700469e0913070fa92cab160c8a995dfd971087b483b794c"
)


def _sha256(path):
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class W6V2ShadowPanelTests(unittest.TestCase):
    def test_frozen_panel_hash_and_evidence_bindings(self):
        panel, audit = load_and_validate_panel(PANEL, repo_root=ROOT)
        self.assertEqual(_sha256(PANEL), EXPECTED_PANEL_SHA256)
        self.assertEqual(_sha256(EVIDENCE_SNAPSHOT), EXPECTED_EVIDENCE_SHA256)
        self.assertEqual(panel["case_count"], 16)
        self.assertEqual(len(audit), 16)
        self.assertTrue(all(row["ok"] for row in audit))
        snapshot = json.loads(EVIDENCE_SNAPSHOT.read_text())
        self.assertEqual(
            set(snapshot["cases"]),
            {case["case_id"] for case in panel["cases"]},
        )
        self.assertTrue(
            snapshot["content_boundary"]["aggregate_decision_facts_only"]
        )
        self.assertTrue(
            all(
                case["evidence"]["path"]
                == "configs/w6_v2_evidence_snapshot.json"
                for case in panel["cases"]
            )
        )
        self.assertEqual(
            sum(case["expected"]["stop"] for case in panel["cases"]),
            7,
        )
        self.assertEqual(
            sum(case["expected"]["explore"] for case in panel["cases"]),
            8,
        )

    def test_request_packet_is_deterministic_and_does_not_leak_labels(self):
        panel, generated, _ = build_request_records(PANEL, repo_root=ROOT)
        tracked = [
            json.loads(line)
            for line in REQUESTS.read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(generated, tracked)
        self.assertEqual(_sha256(REQUESTS), EXPECTED_REQUEST_SHA256)
        for request in generated:
            self.assertNotIn('"expected"', request["prompt"])
            self.assertNotIn("baseline_plan", request["prompt"])
            self.assertNotIn("hidden_truth", request["prompt"])
            self.assertNotIn("candidate_sequence", request["prompt"])
        self.assertEqual(panel["mode"], "offline_shadow")

    def test_valid_fixture_replay_passes_without_effect(self):
        report = score_response_records(
            PANEL,
            REQUESTS,
            VALID_RESPONSES,
            repo_root=ROOT,
        )
        self.assertEqual(report["status"], "offline_replay_pass")
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 16)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 0)
        self.assertEqual(report["metrics"]["decision_pair_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["incremental_value_rate"], 0.5625)
        self.assertEqual(report["recommendations_applied"], 0)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(report["api_calls"], 0)
        self.assertFalse(report["live_execution_authorized"])
        self.assertFalse(report["m7_complete"])

    def test_adversarial_fixture_fails_and_counts_authority_attempts(self):
        report = score_response_records(
            PANEL,
            REQUESTS,
            ADVERSARIAL_RESPONSES,
            repo_root=ROOT,
        )
        self.assertEqual(report["status"], "offline_replay_fail")
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["schema_acceptance_count"], 3)
        self.assertEqual(report["metrics"]["control_plane_violation_count"], 8)
        self.assertFalse(report["checks"]["control_plane_violations"])
        self.assertFalse(report["checks"]["schema_acceptance"])
        self.assertEqual(report["recommendations_applied"], 0)

    def test_fixture_binding_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid = Path(tmp) / "valid.jsonl"
            adversarial = Path(tmp) / "adversarial.jsonl"
            materialize_fixture_responses(REQUESTS, VALID_SPECS, valid)
            materialize_fixture_responses(
                REQUESTS, ADVERSARIAL_SPECS, adversarial
            )
            self.assertEqual(valid.read_bytes(), VALID_RESPONSES.read_bytes())
            self.assertEqual(
                adversarial.read_bytes(),
                ADVERSARIAL_RESPONSES.read_bytes(),
            )

    def test_evidence_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "panel.json"
            panel = json.loads(PANEL.read_text())
            panel["cases"][0]["evidence"]["sha256"] = "0" * 64
            tampered.write_text(json.dumps(panel))
            with self.assertRaisesRegex(ValueError, "evidence SHA-256 mismatch"):
                load_and_validate_panel(tampered, repo_root=ROOT)

    def test_prompt_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            requests = Path(tmp) / "requests.jsonl"
            records = [
                json.loads(line)
                for line in REQUESTS.read_text().splitlines()
                if line.strip()
            ]
            records[0]["prompt"] += "\ntampered"
            requests.write_text(
                "".join(
                    json.dumps(record, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for record in records
                )
            )
            with self.assertRaisesRegex(ValueError, "request binding mismatch"):
                score_response_records(
                    PANEL,
                    requests,
                    VALID_RESPONSES,
                    repo_root=ROOT,
                )

    def test_missing_response_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / "responses.jsonl"
            lines = VALID_RESPONSES.read_text().splitlines()
            incomplete.write_text("\n".join(lines[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "cover every request"):
                score_response_records(
                    PANEL,
                    REQUESTS,
                    incomplete,
                    repo_root=ROOT,
                )

    def test_freeze_and_replay_work_when_network_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            requests = Path(tmp) / "requests.jsonl"
            freeze_report = Path(tmp) / "freeze.json"
            responses = Path(tmp) / "responses.jsonl"
            with mock.patch.object(
                socket,
                "socket",
                side_effect=AssertionError("network access attempted"),
            ):
                report = freeze_panel(
                    PANEL,
                    requests,
                    freeze_report,
                    repo_root=ROOT,
                )
                materialize_fixture_responses(requests, VALID_SPECS, responses)
                replay = score_response_records(
                    PANEL,
                    requests,
                    responses,
                    repo_root=ROOT,
                )
            self.assertEqual(report["provider_calls"], 0)
            self.assertTrue(replay["passed"])

    def test_response_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "responses.jsonl"
            records = [
                json.loads(line)
                for line in VALID_RESPONSES.read_text().splitlines()
                if line.strip()
            ]
            records[0] = copy.deepcopy(records[0])
            records[0]["raw_response"] += " "
            tampered.write_text(
                "".join(
                    json.dumps(record, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for record in records
                )
            )
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                score_response_records(
                    PANEL,
                    REQUESTS,
                    tampered,
                    repo_root=ROOT,
                )


if __name__ == "__main__":
    unittest.main()
