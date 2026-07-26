import json
import tempfile
import unittest
from pathlib import Path

from bio_sfm_designer.experiments.w6_v4_gated_batch_campaign import (
    evaluate_offline_campaign,
    load_and_validate_campaign,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/w6_v4_gated_batch_campaign.json"
STORED_REPORT = ROOT / "results/w6_v4_gated_batch_offline_report.json"


class W6V4GatedBatchCampaignTests(unittest.TestCase):
    def test_frozen_campaign_validates_real_bound_inputs(self):
        config, paths, audit = load_and_validate_campaign(
            CONFIG,
            repo_root=ROOT,
        )
        self.assertEqual(config["campaign_contract"]["candidates_per_round"], 50)
        self.assertEqual(set(paths), set(config["inputs"]))
        self.assertEqual(
            {row["row_count"] for row in audit["inputs"]},
            {50, 192},
        )
        self.assertFalse(
            config["historical_boundary"]["current_campaign_uses_prevalidation"]
        )

    def test_offline_replay_passes_every_frozen_invariant(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "report.json",
                repo_root=ROOT,
            )
        self.assertEqual(
            report["status"],
            "w6_v4_gated_batch_offline_pass",
        )
        self.assertTrue(report["passed"])
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["baseline"]["action_counts"]["defer"], 50)
        self.assertFalse(report["baseline"]["gate_calibrated"])
        self.assertEqual(report["offline_fixture_invocations"], 6)
        self.assertEqual(report["api_calls"], 0)
        self.assertEqual(report["live_provider_calls"], 0)
        self.assertFalse(report["m7_complete"])

    def test_replay_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "first.json",
                repo_root=ROOT,
            )
            second = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "second.json",
                repo_root=ROOT,
            )
        self.assertEqual(first, second)

    def test_stored_report_matches_fresh_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            fresh = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "fresh.json",
                repo_root=ROOT,
            )
        self.assertEqual(json.loads(STORED_REPORT.read_text()), fresh)

    def test_every_adversarial_arm_fails_closed_without_routing_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "report.json",
                repo_root=ROOT,
            )
        adversarial = report["adversarial_fixtures"]
        self.assertEqual(len(adversarial), 5)
        self.assertTrue(all(row["passed"] for row in adversarial))
        self.assertTrue(all(row["applied"] is False for row in adversarial))
        self.assertTrue(all(row["campaign_identical"] for row in adversarial))
        self.assertTrue(all(row["control_identical"] for row in adversarial))
        self.assertTrue(
            all(row["raw_provider_error_message_absent"] for row in adversarial)
        )

    def test_prompt_contains_only_aggregate_campaign_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = evaluate_offline_campaign(
                CONFIG,
                Path(temporary) / "report.json",
                repo_root=ROOT,
            )
        audit = report["prompt_privacy_audit"]
        self.assertTrue(audit["ok"])
        self.assertTrue(audit["aggregate_only"])
        self.assertEqual(audit["candidate_id_hit_count"], 0)
        self.assertEqual(audit["sequence_hit_count"], 0)
        self.assertEqual(audit["forbidden_literal_hits"], [])

    def test_tampered_input_hash_is_rejected(self):
        config = json.loads(CONFIG.read_text())
        config["inputs"]["records"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tampered.json"
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "records SHA-256 mismatch"):
                load_and_validate_campaign(path, repo_root=ROOT)

    def test_historical_certificate_cannot_be_reenabled(self):
        config = json.loads(CONFIG.read_text())
        config["campaign_contract"]["use_gate_prevalidation"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tampered.json"
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "historical gate certificate"):
                load_and_validate_campaign(path, repo_root=ROOT)


if __name__ == "__main__":
    unittest.main()
