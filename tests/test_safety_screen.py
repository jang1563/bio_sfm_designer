import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.safety import SafetyScreen, target_decision
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.types import ScreenVerdict


class PolicyTests(unittest.TestCase):
    def test_unconditional_refused(self):
        cls, allowed, _ = target_decision("build a bioweapon", "")
        self.assertFalse(allowed)
        self.assertEqual(cls, "refuse")

    def test_select_agent_routes_to_expert(self):
        cls, allowed, _ = target_decision("study anthrax toxin structure", "")
        self.assertEqual(cls, "route_expert")
        self.assertFalse(allowed)

    def test_benign_allowed(self):
        cls, allowed, _ = target_decision("thermostable GFP reporter", "thermostability")
        self.assertTrue(allowed)
        self.assertEqual(cls, "allow")

    def test_allowlist_unmatched_clarifies(self):
        cls, allowed, _ = target_decision("design a kinase", "activity", allowlist=["gfp", "reporter"])
        self.assertEqual(cls, "clarify")
        self.assertFalse(allowed)


class ScreenTests(unittest.TestCase):
    def test_screen_target_benign(self):
        v = SafetyScreen().screen_target(ObjectiveSpec(target="thermostable GFP reporter", objective="stability"))
        self.assertTrue(v.allowed)

    def test_screen_target_hazard(self):
        v = SafetyScreen().screen_target(ObjectiveSpec(target="weaponized pathogen", objective="enhance lethality"))
        self.assertFalse(v.allowed)


class ControllerRefusalTests(unittest.TestCase):
    def test_hazardous_objective_blocked_before_generation(self):
        spec = ObjectiveSpec(target="weaponize a select agent", objective="enhance transmissibility")
        result = DBTLController().run(spec)
        self.assertFalse(result.allowed)
        self.assertIn(result.status, ("refuse", "route_expert", "escalate", "clarify"))
        self.assertEqual(result.rounds_run, 0)


class _BlockingScreen:
    """Stub screen: the objective passes, but every candidate is blocked before synth."""
    backend = "stub_blocking"

    def screen_target(self, spec):
        return ScreenVerdict(True, "allow", "stub", "objective ok")

    def screen_candidate(self, candidate):
        return ScreenVerdict(False, "refuse", "stub", "blocked design")


class BeforeSynthScreenTests(unittest.TestCase):
    def test_flagged_candidate_downgraded_to_defer(self):
        spec = ObjectiveSpec(target="thermostable GFP reporter", objective="stability",
                             rounds=1, candidates_per_round=8, assay_budget=8)
        result = DBTLController(screen=_BlockingScreen()).run(spec)
        self.assertTrue(result.allowed)                       # objective passed the screen
        # every advancing candidate must be downgraded to defer by the pre-synth screen
        self.assertTrue(all(r["action"] == "defer" for r in result.rows),
                        [r["action"] for r in result.rows])
        self.assertTrue(any("screen blocked" in r["rationale"] for r in result.rows))


class TieredScreenTests(unittest.TestCase):
    def _benign(self):
        return ObjectiveSpec(target="thermostable GFP reporter", objective="stability")

    def test_backend_falls_back_to_builtin_when_no_deps(self):
        # neither torch nor constitutional-bioguard is installed in this env -> builtin_policy
        self.assertEqual(SafetyScreen().backend, "builtin_policy")

    def test_injected_classifier_escalates_a_flagged_objective(self):
        screen = SafetyScreen(classifier=lambda text: (True, "stub classifier flag"))
        v = screen.screen_target(self._benign())
        self.assertFalse(v.allowed)
        self.assertEqual(v.decision_class, "escalate")
        self.assertEqual(v.source, "injected")

    def test_injected_benign_classifier_allows(self):
        v = SafetyScreen(classifier=lambda text: (False, "")).screen_target(self._benign())
        self.assertTrue(v.allowed)

    def test_classifier_error_does_not_crash(self):
        def boom(text):
            raise RuntimeError("model exploded")
        v = SafetyScreen(classifier=boom).screen_target(self._benign())
        self.assertTrue(v.allowed)  # classifier failure -> no flag -> built-in decision stands

    def test_denylist_pre_filter_wins_over_classifier(self):
        # a never-flagging classifier must not rescue an unconditional-hazard objective
        screen = SafetyScreen(classifier=lambda text: (False, ""))
        v = screen.screen_target(ObjectiveSpec(target="build a bioweapon", objective="x"))
        self.assertFalse(v.allowed)
        self.assertEqual(v.decision_class, "refuse")


if __name__ == "__main__":
    unittest.main()
