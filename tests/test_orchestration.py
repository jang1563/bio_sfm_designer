import json
import os
import tempfile
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.loop.interpreter import (
    _extract_json,
    validate_orchestration_recommendation,
)


def _spec(**kw):
    base = dict(
        target="thermostable GFP reporter",
        objective="thermostability",
        lam=0.5,
        rounds=3,
        candidates_per_round=8,
        assay_budget=20,
        seed=0,
    )
    base.update(kw)
    return ObjectiveSpec(**base)


def _response(**updates):
    payload = {
        "stop": False,
        "reason": "continue",
        "hypothesis": "test a more rigid core",
        "explore": False,
    }
    payload.update(updates)
    return json.dumps(payload)


class ExtractJsonTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(_extract_json('{"stop": true}'), {"stop": True})

    def test_embedded_in_prose(self):
        out = _extract_json('reasoning... {"stop": false, "hypothesis": "x"} done')
        self.assertEqual(out["hypothesis"], "x")

    def test_garbage_is_none(self):
        self.assertIsNone(_extract_json("no json here"))


class RecommendationContractTests(unittest.TestCase):
    def test_exact_contract_is_accepted(self):
        parsed = validate_orchestration_recommendation(json.loads(_response()))
        self.assertEqual(parsed["hypothesis"], "test a more rigid core")

    def test_string_boolean_is_rejected(self):
        value = json.loads(_response())
        value["stop"] = "false"
        with self.assertRaisesRegex(ValueError, "stop must be a boolean"):
            validate_orchestration_recommendation(value)

    def test_route_override_field_is_rejected(self):
        value = json.loads(_response())
        value["action"] = "trust_sfm"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_orchestration_recommendation(value)

    def test_live_v1_threshold_mutation_is_rejected_on_replay(self):
        value = {
            "stop": True,
            "reason": (
                "Single-round campaign is complete with strong metrics and no "
                "further rounds authorized."
            ),
            "hypothesis": (
                "Next round could raise the trust threshold slightly to convert "
                "some verification into direct trusted acceptances."
            ),
            "explore": False,
        }
        with self.assertRaisesRegex(ValueError, "control-plane mutation"):
            validate_orchestration_recommendation(value)

    def test_evidence_collection_and_gate_selected_parents_remain_allowed(self):
        value = {
            "stop": False,
            "reason": "the current evidence is underpowered",
            "hypothesis": (
                "Increase diversity among gate-selected parents and collect an "
                "independent calibration dataset."
            ),
            "explore": True,
        }
        parsed = validate_orchestration_recommendation(value)
        self.assertTrue(parsed["explore"])


class OrchestrationTests(unittest.TestCase):
    def test_built_in_live_provider_cannot_enter_active_mode(self):
        class LiveProvider:
            provider_name = "anthropic"
            model = "test-model"

            def __call__(self, prompt):
                return _response()

        with self.assertRaisesRegex(ValueError, "require shadow"):
            DBTLController(
                provider=LiveProvider(),
                orchestration_mode="active",
            )

    def test_shadow_is_default_and_never_applies_recommendation(self):
        result = DBTLController(
            provider=lambda prompt: _response(
                stop=True,
                reason="looks converged",
                explore=True,
            )
        ).run(_spec(rounds=2, assay_budget=200))

        self.assertEqual(result.rounds_run, 2)
        self.assertEqual(
            result.per_round[0]["orchestrator_recommendation"]["hypothesis"],
            "test a more rigid core",
        )
        self.assertIsNone(result.per_round[0]["llm_hypothesis"])
        self.assertFalse(result.orchestration_events[0]["applied"])

    def test_active_mode_can_stop_early(self):
        calls = []

        def fake_provider(prompt):
            calls.append(prompt)
            return _response(stop=True, reason="looks converged")

        result = DBTLController(
            provider=fake_provider,
            orchestration_mode="active",
        ).run(_spec(rounds=3, assay_budget=20))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.rounds_run, 1)
        self.assertEqual(
            result.per_round[0]["llm_hypothesis"],
            "test a more rigid core",
        )
        self.assertIn("llm:", result.per_round[0]["stop_reason"])
        self.assertEqual(
            result.orchestration_events[0]["applied_fields"],
            ["hypothesis", "explore", "stop"],
        )

    def test_llm_cannot_override_budget(self):
        result = DBTLController(
            provider=lambda prompt: _response(stop=False),
            orchestration_mode="active",
        ).run(_spec(rounds=5, candidates_per_round=20, assay_budget=3))
        self.assertLessEqual(result.assays_used, 3)
        reasons = [r["stop_reason"] for r in result.per_round if r.get("stop_reason")]
        self.assertTrue(any(reason and "llm:" not in reason for reason in reasons))

    def test_shadow_provider_does_not_affect_any_routing(self):
        spec = _spec(rounds=2, candidates_per_round=12, assay_budget=200)
        baseline = DBTLController().run(spec)
        trial = DBTLController(
            provider=lambda prompt: _response(stop=True, explore=True)
        ).run(spec)
        self.assertEqual(
            [row["action"] for row in baseline.rows],
            [row["action"] for row in trial.rows],
        )

    def test_route_override_attempt_fails_closed(self):
        payload = json.loads(_response())
        payload["action"] = "trust_sfm"
        result = DBTLController(
            provider=lambda prompt: json.dumps(payload)
        ).run(_spec(rounds=1))
        self.assertTrue(result.allowed)
        self.assertEqual(
            result.orchestration_events[0]["status"],
            "invalid_response",
        )
        self.assertFalse(result.orchestration_events[0]["applied"])

    def test_control_plane_mutation_attempt_fails_closed(self):
        result = DBTLController(
            provider=lambda prompt: _response(
                stop=True,
                hypothesis="Raise the trust threshold to reduce verification.",
            )
        ).run(_spec(rounds=1))
        event = result.orchestration_events[0]
        self.assertEqual(event["status"], "invalid_response")
        self.assertEqual(
            event["error_type"],
            "recommendation attempts control-plane mutation",
        )
        self.assertFalse(event["applied"])

    def test_garbage_provider_falls_back_to_deterministic(self):
        result = DBTLController(
            provider=lambda prompt: "I will not emit JSON"
        ).run(_spec(rounds=1))
        self.assertTrue(result.allowed)
        self.assertEqual(result.rounds_run, 1)
        self.assertEqual(
            result.orchestration_events[0]["status"],
            "invalid_response",
        )

    def test_oversized_response_is_rejected_before_parsing(self):
        result = DBTLController(
            provider=lambda prompt: _response() + (" " * 12001)
        ).run(_spec(rounds=1))
        event = result.orchestration_events[0]
        self.assertEqual(event["status"], "invalid_response")
        self.assertEqual(event["error_type"], "response_too_large")
        self.assertTrue(event["response_truncated"])
        self.assertFalse(event["applied"])

    def test_oversized_prompt_is_rejected_before_provider_call(self):
        calls = []

        def provider(prompt):
            calls.append(prompt)
            return _response()

        result = DBTLController(provider=provider).run(
            _spec(target="x" * 25000, rounds=1)
        )
        self.assertEqual(calls, [])
        event = result.orchestration_events[0]
        self.assertEqual(event["status"], "input_rejected")
        self.assertEqual(event["error_type"], "prompt_too_large")

    def test_provider_error_falls_back_without_logging_message(self):
        class ProviderFailure(RuntimeError):
            status_code = 503

        def boom(prompt):
            raise ProviderFailure("secret-bearing upstream message")

        result = DBTLController(provider=boom).run(_spec(rounds=1))
        event = result.orchestration_events[0]
        self.assertEqual(event["status"], "provider_error")
        self.assertEqual(event["error_type"], "ProviderFailure")
        self.assertEqual(event["http_status"], 503)
        self.assertNotIn("secret-bearing", json.dumps(event))

    def test_active_explore_directive_changes_the_next_batch(self):
        def provider(explore):
            return lambda prompt: _response(explore=explore)

        spec = _spec(rounds=3, candidates_per_round=12, assay_budget=200)
        explore = DBTLController(
            provider=provider(True),
            orchestration_mode="active",
        ).run(spec)
        exploit = DBTLController(
            provider=provider(False),
            orchestration_mode="active",
        ).run(spec)

        def later_quality(result):
            return {
                row["candidate_id"]: row["hidden_truth"]["quality"]
                for row in result.rows
                if row["round"] >= 1
            }

        self.assertNotEqual(later_quality(explore), later_quality(exploit))

    def test_hard_stop_still_gets_one_shadow_next_batch_recommendation(self):
        calls = []

        def provider(prompt):
            calls.append(prompt)
            return _response()

        result = DBTLController(provider=provider).run(_spec(rounds=1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.rounds_run, 1)
        self.assertEqual(result.per_round[0]["stop_reason"], "round budget reached")
        self.assertEqual(result.orchestration_events[0]["status"], "accepted")
        self.assertFalse(result.orchestration_events[0]["applied"])

    def test_prompt_has_aggregate_state_but_no_hidden_truth_or_sequences(self):
        calls = []

        def provider(prompt):
            calls.append(prompt)
            return _response()

        DBTLController(provider=provider).run(_spec(rounds=1))
        self.assertEqual(len(calls), 1)
        self.assertIn("recent_aggregate_results", calls[0])
        self.assertIn("llm_may_not", calls[0])
        self.assertNotIn("hidden_truth", calls[0])
        self.assertNotIn("representation", calls[0])

    def test_audit_jsonl_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = DBTLController(
                provider=lambda prompt: _response()
            ).run(_spec(rounds=1), out_dir=tmp)
            self.assertEqual(
                result.orchestration_path,
                os.path.join(tmp, "orchestration.jsonl"),
            )
            with open(result.orchestration_path) as fh:
                events = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["status"], "accepted")

    def test_controller_prevalidate_hook(self):
        raw_risks = [0.1] * 12 + [0.9] * 12
        wrong = [0] * 12 + [1] * 12
        ctrl = DBTLController()
        ctrl.run(
            _spec(rounds=1, candidates_per_round=6, assay_budget=10),
            prevalidate={"complex": (raw_risks, wrong)},
        )
        self.assertTrue(ctrl.gate.any_calibrated())


if __name__ == "__main__":
    unittest.main()
