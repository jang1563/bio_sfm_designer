"""Deterministic mock generator — runs the loop with no GPU/weights/network."""

from __future__ import annotations

from typing import List, Optional

from ..config import ObjectiveSpec
from ..types import Candidate
from .base import stable_unit

_AA = "ACDEFGHIKLMNPQRSTVWY"


class StubGenerator:
    """Emits reproducible pseudo-designs. Later rounds are seeded from `parents`,
    so the loop visibly iterates, but no real generative model is invoked."""

    def propose(
        self,
        spec: ObjectiveSpec,
        round: int,
        n: int,
        parents: Optional[List[Candidate]] = None,
    ) -> List[Candidate]:
        out: List[Candidate] = []
        for i in range(n):
            parent = parents[i % len(parents)] if parents else None
            cid = f"{spec.objective}-r{round}-c{i}-s{spec.seed}"
            # 24-residue pseudo-sequence, deterministic from the id
            seq = "".join(_AA[int(stable_unit(f"{cid}:{p}") * len(_AA)) % len(_AA)] for p in range(24))
            out.append(
                Candidate(
                    id=cid,
                    representation=seq,
                    round=round,
                    parent_id=parent.id if parent else None,
                    meta={"objective": spec.objective, "target": spec.target},
                )
            )
        return out
