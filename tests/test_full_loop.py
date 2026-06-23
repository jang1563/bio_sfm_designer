import json
import os
import tempfile
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.scoring import score_round
from bio_sfm_designer.trust import TrustGate
from bio_sfm_designer.generate import StubGenerator
from bio_sfm_designer.predict import StubPredictor

ACTIONS = {"trust_sfm", "verify_assay", "default_baseline", "defer"}


def _benign_spec(**kw):
    base = dict(
        target="thermostable variant of green fluorescent protein (GFP), a benign reporter",
        objective="thermostability",
        lam=0.5,
        rounds=3,
        candidates_per_round=8,
        assay_budget=10,
        seed=0,
    )
    base.update(kw)
    return ObjectiveSpec(**base)


class FullLoopTests(unittest.TestCase):
    def test_campaign_runs_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            result = DBTLController().run(_benign_spec(), out_dir=d)
            self.assertTrue(result.allowed)
            self.assertEqual(result.status, "allow")
            self.assertGreaterEqual(result.rounds_run, 1)
            # campaign + summary written
            self.assertTrue(os.path.exists(os.path.join(d, "campaign.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(d, "summary.json")))
            with open(os.path.join(d, "summary.json")) as fh:
                summ = json.load(fh)
            self.assertEqual(summ["target"], result.target)

    def test_all_four_actions_appear(self):
        # a wider candidate pool with a tight assay budget exercises the full action set:
        # low-risk -> trust, high-risk -> verify (until budget), overflow with a baseline ->
        # default_baseline, overflow without a baseline -> defer.
        result = DBTLController().run(_benign_spec(rounds=3, candidates_per_round=20, assay_budget=5))
        seen = {row["action"] for row in result.rows}
        self.assertEqual(seen, ACTIONS, f"expected all four actions, saw {seen}")

    def test_aggregate_has_reward_and_rates(self):
        result = DBTLController().run(_benign_spec())
        agg = result.aggregate
        for key in ("net_reward_per_item", "trust_rate", "verify_rate", "default_rate", "defer_rate", "n"):
            self.assertIn(key, agg)
        rate_sum = agg["trust_rate"] + agg["verify_rate"] + agg["default_rate"] + agg["defer_rate"]
        self.assertAlmostEqual(rate_sum, 1.0, places=6)

    def test_assay_budget_respected(self):
        result = DBTLController().run(_benign_spec(assay_budget=3, rounds=3, candidates_per_round=10))
        self.assertLessEqual(result.assays_used, 3)

    def test_scoring_matches_trust_core(self):
        # build one round of routings/predictions directly and confirm score_round agrees
        spec = _benign_spec()
        gen, pred_fn, gate = StubGenerator(), StubPredictor(), TrustGate(lam=spec.lam)
        cands = gen.propose(spec, 0, spec.candidates_per_round)
        preds = {c.id: pred_fn.predict(c, spec) for c in cands}
        routings = [gate.route(preds[c.id], lam=spec.lam) for c in cands]
        scored = score_round(routings, preds, lam=spec.lam)
        n = scored["summary"]["n"]
        self.assertEqual(n, len(cands))
        self.assertIsInstance(scored["summary"]["net_reward_per_item"], float)

    def test_gate_never_receives_truth_in_evidence(self):
        result = DBTLController().run(_benign_spec())
        for row in result.rows:
            self.assertNotIn("truth", row["evidence"])
            self.assertNotIn("sfm_correct", row["evidence"])


if __name__ == "__main__":
    unittest.main()
