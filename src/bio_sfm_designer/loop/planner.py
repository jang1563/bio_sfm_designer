"""Planner — proposes the next round's seeds from the current round's results.

This is the orchestration role Claude plays (hypothesis → next design). The trust/routing
decision is NOT made here — that belongs to the external gate. The planner's job is parent
SELECTION: which of the round's candidates to breed from next.

Acquisition is pluggable (greedy | ucb | thompson). Greedy (the default, = M0/M1 behavior)
ranks advancing candidates by predicted quality. UCB/Thompson add exploration using the gate's
calibrated risk as the per-candidate uncertainty; optional `diversity` then spreads the chosen
batch over sequence space (farthest-point on Hamming distance) so the next round isn't a cluster
of near-duplicates.
"""

from __future__ import annotations

import random
from typing import Dict, List

from ..types import Candidate, Prediction, Routing
from .acquisition import ACQUISITIONS, hamming

_ADVANCING = {"trust_sfm", "verify_assay"}


class Planner:
    def __init__(self, acquisition: str = "greedy", beta: float = 1.0,
                 diversity: bool = False, seed: int = 0) -> None:
        if acquisition not in ACQUISITIONS:
            raise ValueError(f"unknown acquisition {acquisition!r}; choose from {sorted(ACQUISITIONS)}")
        self.acquisition = acquisition
        self.beta = beta
        self.diversity = diversity
        self._rng = random.Random(seed)

    def _score(self, mu: float, sigma: float) -> float:
        return ACQUISITIONS[self.acquisition](mu, sigma, self.beta, self._rng)

    def select_parents(
        self,
        routings: List[Routing],
        predictions: Dict[str, Prediction],
        candidates: Dict[str, Candidate],
        k: int,
    ) -> List[Candidate]:
        advancing = [r for r in routings if r.action in _ADVANCING]
        if advancing:
            ranked = sorted(
                advancing,
                key=lambda r: self._score(predictions[r.candidate_id].value, r.calibrated_risk),
                reverse=True,
            )
            ordered = [candidates[r.candidate_id] for r in ranked]
            return _diverse_topk(ordered, k) if self.diversity else ordered[:k]
        # nothing advanced; fall back to the highest-confidence designs
        best = sorted(candidates.values(), key=lambda c: predictions[c.id].raw_conf, reverse=True)
        return best[:k]


def _diverse_topk(ordered: List[Candidate], k: int) -> List[Candidate]:
    """Farthest-point batch selection: take the top-scored candidate, then iteratively add the
    one (in acquisition order) maximally Hamming-distant from those already chosen. Keeps the
    batch from collapsing onto near-identical sequences."""
    if k >= len(ordered):
        return ordered[:k]
    chosen = [ordered[0]]
    chosen_ids = {ordered[0].id}
    while len(chosen) < k:
        best_c, best_d = None, -1
        for c in ordered:
            if c.id in chosen_ids:
                continue
            d = min(hamming(c.representation, s.representation) for s in chosen)
            if d > best_d:
                best_d, best_c = d, c
        chosen.append(best_c)              # type: ignore[arg-type]
        chosen_ids.add(best_c.id)          # type: ignore[union-attr]
    return chosen
