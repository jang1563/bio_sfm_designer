"""Planner — proposes the next round's seeds from the current round's results.

This is the orchestration role Claude plays in M2 (hypothesis → next design). In M0
it is deterministic and rule-based: keep the candidates the gate trusted or verified,
ranked by realized quality, as parents for the next round. No LLM call is required to
make the routing decision — that belongs to the trust gate.
"""

from __future__ import annotations

from typing import Dict, List

from ..types import Candidate, Prediction, Routing

_ADVANCING = {"trust_sfm", "verify_assay"}


class Planner:
    def select_parents(
        self,
        routings: List[Routing],
        predictions: Dict[str, Prediction],
        candidates: Dict[str, Candidate],
        k: int,
    ) -> List[Candidate]:
        ranked = sorted(
            (r for r in routings if r.action in _ADVANCING),
            key=lambda r: predictions[r.candidate_id].value,
            reverse=True,
        )
        parents = [candidates[r.candidate_id] for r in ranked[:k]]
        if not parents:  # nothing advanced; fall back to the highest-confidence designs
            best = sorted(candidates.values(), key=lambda c: predictions[c.id].raw_conf, reverse=True)
            parents = best[:k]
        return parents
