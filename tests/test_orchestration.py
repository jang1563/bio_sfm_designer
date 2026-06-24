import json
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.loop.interpreter import _extract_json


def _spec(**kw):
    base = dict(target="thermostable GFP reporter", objective="thermostability",
                lam=0.5, rounds=3, candidates_per_round=8, assay_budget=20, seed=0)
    base.update(kw)
    return ObjectiveSpec(**base)


class ExtractJsonTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(_extract_json('{"stop": true}'), {"stop": True})

    def test_embedded_in_prose(self):
        out = _extract_json('reasoning... {"stop": false, "hypothesis": "x"} done')
        self.assertEqual(out["hypothesis"], "x")

    def test_garbage_is_none(self):
        self.assertIsNone(_extract_json("no json here"))


class OrchestrationTests(unittest.TestCase):
    def test_llm_hypothesis_recorded_and_early_stop(self):
        calls = []

        def fake_provider(prompt):
            calls.append(prompt)
            return json.dumps({"stop": True, "reason": "looks converged", "hypothesis": "try a more rigid core"})

        result = DBTLController(provider=fake_provider).run(_spec(rounds=3, assay_budget=20))
        self.assertGreaterEqual(len(calls), 1)                       # orchestrator was consulted
        self.assertEqual(result.rounds_run, 1)                       # and chose to stop after round 0
        self.assertEqual(result.per_round[0]["llm_hypothesis"], "try a more rigid core")
        self.assertIn("llm:", result.per_round[0]["stop_reason"])

    def test_llm_cannot_override_budget(self):
        # provider always says "continue", but the tiny assay budget is a hard cap enforced in code
        def keep_going(prompt):
            return json.dumps({"stop": False, "hypothesis": "keep exploring"})

        result = DBTLController(provider=keep_going).run(_spec(rounds=5, candidates_per_round=20, assay_budget=3))
        self.assertLessEqual(result.assays_used, 3)
        reasons = [r["stop_reason"] for r in result.per_round if r.get("stop_reason")]
        self.assertTrue(any(r and "llm:" not in r for r in reasons), reasons)  # stopped by a deterministic cap

    def test_provider_does_not_affect_routing(self):
        # routing (gate actions) must be byte-identical with and without the LLM orchestrator
        spec = _spec(rounds=2, candidates_per_round=12, assay_budget=20)
        no_llm = DBTLController().run(spec)
        with_llm = DBTLController(provider=lambda p: json.dumps({"stop": False, "hypothesis": "h"})).run(spec)
        self.assertEqual([r["action"] for r in no_llm.rows], [r["action"] for r in with_llm.rows])

    def test_garbage_provider_falls_back_to_deterministic(self):
        result = DBTLController(provider=lambda p: "I will not emit JSON").run(_spec(rounds=2))
        self.assertTrue(result.allowed)                              # no crash; deterministic decision used
        self.assertLessEqual(result.rounds_run, 2)

    def test_explore_directive_causally_changes_the_next_batch(self):
        # the orchestrator's `explore` steer toggles parent diversity -> different designs bred next
        def provider(explore):
            return lambda p: json.dumps({"stop": False, "hypothesis": "h", "explore": explore})
        spec = _spec(rounds=3, candidates_per_round=12, assay_budget=200)
        exp = DBTLController(provider=provider(True)).run(spec)
        nox = DBTLController(provider=provider(False)).run(spec)
        self.assertTrue(any(r.get("llm_explore") is True for r in exp.per_round))
        self.assertTrue(any(r.get("llm_explore") is False for r in nox.per_round))

        def later_quality(res):  # quality of designs in rounds >= 1 (the bred ones)
            return {row["candidate_id"]: row["hidden_truth"]["quality"]
                    for row in res.rows if row["round"] >= 1}
        self.assertNotEqual(later_quality(exp), later_quality(nox),
                            "explore steer must change which designs get bred")

    def test_explore_steer_does_not_rewrite_round0_routing(self):
        # the steer is forward-only: it changes round >=1's batch, never round 0's gate actions
        def provider(explore):
            return lambda p: json.dumps({"stop": False, "explore": explore})
        spec = _spec(rounds=2, candidates_per_round=12, assay_budget=200)
        a = DBTLController(provider=provider(True)).run(spec)
        b = DBTLController(provider=provider(False)).run(spec)
        a0 = [r["action"] for r in a.rows if r["round"] == 0]
        b0 = [r["action"] for r in b.rows if r["round"] == 0]
        self.assertEqual(a0, b0)

    def test_controller_prevalidate_hook(self):
        # offline gate-before-spend: a separable regime starts calibration-validated before round 0
        raw_risks = [0.1] * 12 + [0.9] * 12
        wrong = [0] * 12 + [1] * 12
        ctrl = DBTLController()
        ctrl.run(_spec(rounds=1, candidates_per_round=6, assay_budget=10),
                 prevalidate={"complex": (raw_risks, wrong)})
        self.assertTrue(ctrl.gate.any_calibrated())


if __name__ == "__main__":
    unittest.main()
