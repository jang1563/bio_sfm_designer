"""M3d — the closed-loop driver + routing-policy comparison.

Asserts only what is ROBUSTLY true (no rigged 'gate wins the net race' claim, which the synthetic
stub does not support): the loop climbs; trust_all collapses once false-accepts are costly while
the calibrated gate stays bounded; the gate makes fewer false-accepts than trust_all at no more
assays than verify_all.
"""

import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.experiments.closed_loop_campaign import _score_policy, compare_policies

_TARGET = "thermostable variant of green fluorescent protein (GFP), a benign reporter"


def _spec(**kw):
    base = dict(target=_TARGET, objective="thermostability", lam=0.5, rounds=8,
                candidates_per_round=24, assay_budget=80, seed=0)
    base.update(kw)
    return ObjectiveSpec(**base)


class ClosedLoopCampaignTests(unittest.TestCase):
    def test_climb_is_reported_and_rises(self):
        rep = compare_policies(_spec())
        climb = rep["climb_mean_quality_per_round"]
        rounds = sorted(climb)
        self.assertGreaterEqual(len(rounds), 4)
        self.assertGreater(climb[rounds[-1]], climb[rounds[0]] + 0.05)

    def test_trust_all_collapses_under_false_accept_cost(self):
        pol = compare_policies(_spec(), false_accept_cost=1.5)["policies"]
        # advancing wrong designs is now costly -> trusting everything is catastrophic
        self.assertLess(pol["trust_all"]["net"], pol["calibrated"]["net"] - 0.3)
        self.assertGreater(pol["trust_all"]["false_accepts"], pol["calibrated"]["false_accepts"])

    def test_verify_all_spends_the_most_assays_trust_all_none(self):
        pol = compare_policies(_spec())["policies"]
        self.assertGreaterEqual(pol["verify_all"]["assays"], pol["calibrated"]["assays"])
        self.assertEqual(pol["trust_all"]["assays"], 0)

    def test_gate_makes_fewer_false_accepts_than_trust_all(self):
        pol = compare_policies(_spec())["policies"]
        self.assertLess(pol["calibrated"]["false_accepts"], pol["trust_all"]["false_accepts"])

    def test_defer_incurs_no_cost(self):
        stream = [{"action": "defer", "sfm_correct": False, "baseline_correct": False,
                   "has_baseline": False, "quality": 0.1}]
        s = _score_policy(stream, "calibrated", lam=0.5, mu=2.0, budget=10)
        self.assertEqual((s["net"], s["assays"], s["false_accepts"]), (0.0, 0, 0))


if __name__ == "__main__":
    unittest.main()
