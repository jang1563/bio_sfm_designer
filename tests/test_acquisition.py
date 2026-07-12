"""M3b — pluggable acquisition for parent selection (greedy | ucb | thompson) + diversity.

Locks the mechanism: greedy exploits predicted quality (the legacy behavior); UCB/Thompson use
the gate's calibrated risk as an uncertainty signal to explore; diversity spreads the chosen
batch over sequence space. The routing/trust decision is unaffected — this is only *which
candidates to breed next*.
"""

import unittest

from bio_sfm_designer.loop.acquisition import ACQUISITIONS, hamming
from bio_sfm_designer.loop.planner import Planner
from bio_sfm_designer.types import Candidate, Prediction, Routing


def _routing(cid, action="trust_sfm", calibrated_risk=0.1):
    return Routing(candidate_id=cid, action=action, raw_risk=calibrated_risk,
                   calibrated_risk=calibrated_risk, baseline_disagreement=False)


def _pred(cid, value):
    return Prediction(candidate_id=cid, value=value, raw_conf=value)


def _cand(cid, seq):
    return Candidate(id=cid, representation=seq)


def _min_pairwise_hamming(cands):
    seqs = [c.representation for c in cands]
    return min(hamming(seqs[i], seqs[j]) for i in range(len(seqs)) for j in range(i + 1, len(seqs)))


class AcquisitionTests(unittest.TestCase):
    def test_unknown_acquisition_raises(self):
        with self.assertRaises(ValueError):
            Planner(acquisition="bogus")

    def test_greedy_ranks_by_value(self):
        cands = {c.id: c for c in (_cand("a", "AAAA"), _cand("b", "CCCC"), _cand("c", "DDDD"))}
        preds = {"a": _pred("a", 0.3), "b": _pred("b", 0.9), "c": _pred("c", 0.6)}
        routings = [_routing("a"), _routing("b"), _routing("c")]
        parents = Planner("greedy").select_parents(routings, preds, cands, k=2)
        self.assertEqual([p.id for p in parents], ["b", "c"])  # by descending value

    def test_ucb_prefers_the_uncertain_candidate(self):
        # A: higher value, zero risk; B: slightly lower value, high risk.
        cands = {c.id: c for c in (_cand("A", "AAAA"), _cand("B", "CCCC"))}
        preds = {"A": _pred("A", 0.80), "B": _pred("B", 0.70)}
        routings = [_routing("A", "trust_sfm", calibrated_risk=0.0),
                    _routing("B", "verify_assay", calibrated_risk=0.9)]
        self.assertEqual([p.id for p in Planner("greedy").select_parents(routings, preds, cands, k=1)], ["A"])
        # UCB (beta=1) boosts B by its risk (0.70 + 0.9 = 1.6 > 0.80) -> explores it
        self.assertEqual([p.id for p in Planner("ucb", beta=1.0).select_parents(routings, preds, cands, k=1)], ["B"])

    def test_thompson_is_seeded_deterministic(self):
        cands = {c.id: c for c in (_cand("a", "AAAA"), _cand("b", "CCCC"), _cand("c", "DDDD"))}
        preds = {"a": _pred("a", 0.5), "b": _pred("b", 0.55), "c": _pred("c", 0.52)}
        routings = [_routing("a", calibrated_risk=0.3), _routing("b", calibrated_risk=0.3),
                    _routing("c", calibrated_risk=0.3)]
        first = [p.id for p in Planner("thompson", seed=7).select_parents(routings, preds, cands, k=2)]
        again = [p.id for p in Planner("thompson", seed=7).select_parents(routings, preds, cands, k=2)]
        self.assertEqual(first, again)                 # reproducible
        self.assertEqual(len(first), 2)
        self.assertTrue(set(first) <= {"a", "b", "c"})

    def test_thompson_actually_uses_risk(self):
        # behavioral lock: a risk-AWARE Thompson must sometimes explore the lower-value/high-risk
        # candidate. If it ignored sigma (collapsed to greedy), it would ALWAYS pick the higher-value
        # one. A (val 0.80, risk 0) vs B (val 0.70, risk 0.9).
        cands = {c.id: c for c in (_cand("A", "AAAA"), _cand("B", "CCCC"))}
        preds = {"A": _pred("A", 0.80), "B": _pred("B", 0.70)}
        risky = [_routing("A", calibrated_risk=0.0), _routing("B", calibrated_risk=0.9)]
        flat = [_routing("A", calibrated_risk=0.0), _routing("B", calibrated_risk=0.0)]
        picks_B_risky = sum(Planner("thompson", beta=1.0, seed=s).select_parents(risky, preds, cands, k=1)[0].id == "B"
                            for s in range(40))
        picks_B_flat = sum(Planner("thompson", beta=1.0, seed=s).select_parents(flat, preds, cands, k=1)[0].id == "B"
                           for s in range(40))
        self.assertGreater(picks_B_risky, 0, "risk-aware Thompson must sometimes explore the high-risk candidate")
        self.assertGreater(picks_B_risky, picks_B_flat, "B's risk must drive its selection (vanishes when risk=0)")

    def test_diversity_spreads_the_batch(self):
        # greedy top-2 are near-duplicates (Hamming 1); diversity swaps in the far candidate.
        cands = {c.id: c for c in (_cand("hi1", "AAAAAAAA"), _cand("hi2", "AAAAAAAC"),
                                   _cand("far", "YYYYYYYY"))}
        preds = {"hi1": _pred("hi1", 0.90), "hi2": _pred("hi2", 0.89), "far": _pred("far", 0.80)}
        routings = [_routing("hi1"), _routing("hi2"), _routing("far")]
        greedy = Planner("greedy", diversity=False).select_parents(routings, preds, cands, k=2)
        diverse = Planner("greedy", diversity=True).select_parents(routings, preds, cands, k=2)
        self.assertEqual({p.id for p in greedy}, {"hi1", "hi2"})
        self.assertIn("far", {p.id for p in diverse})
        self.assertGreater(_min_pairwise_hamming(diverse), _min_pairwise_hamming(greedy))

    def test_registry_complete(self):
        self.assertEqual(set(ACQUISITIONS), {"greedy", "ucb", "thompson"})


if __name__ == "__main__":
    unittest.main()
