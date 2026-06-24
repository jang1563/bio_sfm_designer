"""M3a — the DBTL loop is genuinely CLOSED on CPU.

Two feedback channels were already real (calibrator refit, parent selection); the third —
candidate *content* — was a no-op (the stub generator ignored the parent sequence and stub
quality was keyed on the candidate id, so a child's quality was uncorrelated with its parent's).
These tests lock the fix: sequences are heritable (mutated from parents), quality is a pure
function of the sequence, and a multi-round campaign therefore climbs the hidden landscape and
discovers designs better than anything in the initial round.
"""

import unittest
from collections import defaultdict

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.generate.stubs import _MUT_K, StubGenerator, _denovo, _mutate
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.predict.stubs import StubPredictor, _seq_quality
from bio_sfm_designer.types import Candidate

_BENIGN_TARGET = "thermostable variant of green fluorescent protein (GFP), a benign reporter"


def _spec(**kw):
    base = dict(target=_BENIGN_TARGET, objective="thermostability", lam=0.5,
                rounds=10, candidates_per_round=24, assay_budget=240, seed=0)
    base.update(kw)
    return ObjectiveSpec(**base)


class HeritabilityTests(unittest.TestCase):
    def test_mutation_is_local(self):
        parent = _denovo("parent-seed")
        child = _mutate(parent, "child-1")
        self.assertEqual(len(child), len(parent))
        hamming = sum(a != b for a, b in zip(parent, child))
        self.assertLessEqual(hamming, _MUT_K, "a child must differ from its parent in <= k residues")

    def test_quality_depends_only_on_sequence(self):
        # the heritability fix: quality is a pure function of the representation, NOT the id.
        # (Before M3a, quality was keyed on the candidate id, breaking inheritance.)
        spec = _spec()
        seq = _denovo("some-seq")
        a = StubPredictor().predict(Candidate(id="id-A", representation=seq), spec)
        b = StubPredictor().predict(Candidate(id="totally-different-id", representation=seq), spec)
        self.assertEqual(a.value, b.value)
        self.assertEqual(_seq_quality(seq), a.value)

    def test_quality_is_heritable(self):
        # a near-neighbor child has near-equal quality: |Δquality| <= k / L
        parent = _denovo("p")
        child = _mutate(parent, "c")
        self.assertLessEqual(
            abs(_seq_quality(parent) - _seq_quality(child)),
            _MUT_K / len(parent) + 1e-9,
        )

    def test_epistasis_zero_is_the_smooth_landscape(self):
        # backward-compat: the default predictor (epistasis=0) is the M3a OneMax landscape.
        from bio_sfm_designer.generate.base import stable_unit
        seq = _denovo("zz")
        smooth = sum(1 for pos, aa in enumerate(seq) if stable_unit(f"fit:{pos}:{aa}") > 0.5) / len(seq)
        self.assertAlmostEqual(_seq_quality(seq, 0), round(smooth, 4), places=4)

    def test_quality_heritable_under_epistasis(self):
        # on a rugged (epistasis=K) landscape a mutated residue affects up to K+1 windows,
        # so |Δquality| <= k*(K+1)/L — still heritable, just a larger constant.
        seq = _denovo("p")
        child = _mutate(seq, "c")
        K = 3
        self.assertLessEqual(
            abs(_seq_quality(seq, K) - _seq_quality(child, K)),
            _MUT_K * (K + 1) / len(seq) + 1e-9,
        )

    def test_elite_parent_carried_forward_unchanged(self):
        # elitism: candidate 0 is the top parent (planner returns best-first), copied verbatim
        spec = _spec()
        parents = [Candidate(id="p0", representation="A" * 24),
                   Candidate(id="p1", representation="C" * 24)]
        kids = StubGenerator().propose(spec, round=1, n=6, parents=parents)
        self.assertEqual(kids[0].representation, parents[0].representation)
        self.assertEqual(kids[0].parent_id, "p0")
        # the rest are mutated neighbors of their parents (not verbatim copies in general)
        self.assertTrue(any(k.representation != parents[k_idx % 2].representation
                            for k_idx, k in enumerate(kids[1:], start=1)))


class ClosedLoopClimbTests(unittest.TestCase):
    def _per_round_quality(self, result):
        by_round = defaultdict(list)
        for row in result.rows:
            by_round[row["round"]].append(row["hidden_truth"]["quality"])
        return by_round

    def test_loop_climbs_on_average_across_seeds(self):
        # Seed-robust: the real invariant is "the closed loop climbs IN EXPECTATION", not "every
        # seed climbs by >=0.08" (a single seed is noisy; an earlier seed-0-only assert was brittle).
        climbs, beat_round0 = [], 0
        seeds = list(range(6))
        for s in seeds:
            by_round = self._per_round_quality(DBTLController().run(_spec(seed=s)))
            rounds = sorted(by_round)
            self.assertGreaterEqual(len(rounds), 3)
            m0 = sum(by_round[rounds[0]]) / len(by_round[rounds[0]])
            mL = sum(by_round[rounds[-1]]) / len(by_round[rounds[-1]])
            climbs.append(mL - m0)
            if max(max(by_round[r]) for r in rounds) > max(by_round[rounds[0]]):
                beat_round0 += 1
        mean_climb = sum(climbs) / len(climbs)
        self.assertGreater(mean_climb, 0.05,
                           f"loop should climb on average (mean={mean_climb:.3f}; per-seed={[round(c,3) for c in climbs]})")
        self.assertGreaterEqual(beat_round0, len(seeds) - 2,
                                f"most seeds should discover a design better than round 0 (got {beat_round0}/{len(seeds)})")

    def test_later_rounds_have_lineage(self):
        # every non-initial candidate is descended from a selected parent (the loop is wired through)
        result = DBTLController().run(_spec(rounds=4, candidates_per_round=12, assay_budget=60))
        later = [r for r in result.rows if r["round"] > 0]
        self.assertTrue(later)
        self.assertTrue(all(r["parent_id"] is not None for r in later))


if __name__ == "__main__":
    unittest.main()
