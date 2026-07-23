import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.llm_orchestration_smoke import run_smoke


class LlmOrchestrationSmokeTests(unittest.TestCase):
    def test_fixture_smoke_passes_with_one_unapplied_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "smoke.json")
            report = run_smoke(out=out)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["provider_contract_ok"])
            self.assertTrue(report["gate_actions_identical"])
            self.assertTrue(report["safety_invariants_ok"])
            self.assertEqual(report["provider_event_count"], 1)
            self.assertFalse(report["orchestration_events"][0]["applied"])
            with open(out) as fh:
                self.assertEqual(json.load(fh)["status"], "passed")

    def test_live_smoke_blocks_without_p0_attestation(self):
        report = run_smoke(
            provider_name="openai",
            model="test-model",
            credential_hygiene_attested=False,
        )
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["provider_contract_ok"])
        self.assertIn("credential hygiene", report["blocker"]["message"])


if __name__ == "__main__":
    unittest.main()
