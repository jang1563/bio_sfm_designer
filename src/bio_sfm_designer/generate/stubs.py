"""Deterministic mock generator — runs the loop with no GPU/weights/network."""

from __future__ import annotations

from typing import List, Optional

from ..config import ObjectiveSpec
from ..types import Candidate
from .base import stable_unit

_AA = "ACDEFGHIKLMNPQRSTVWY"
_SEQ_LEN = 24
_MUT_K = 2   # residues point-mutated per child — the local-search step size


def _denovo(cid: str, length: int = _SEQ_LEN) -> str:
    """A fresh pseudo-sequence, deterministic from the id (round 0 / no parent)."""
    return "".join(_AA[int(stable_unit(f"{cid}:{p}") * len(_AA)) % len(_AA)] for p in range(length))


def _mutate(parent_seq: str, cid: str, k: int = _MUT_K) -> str:
    """Point-mutate the parent at k positions, deterministically from the child id.

    This is the channel that closes the loop: the child INHERITS the parent's sequence
    (and thus most of its landscape quality) and explores a few residues around it, so
    selecting good parents and mutating them climbs the StubPredictor's fitness landscape.
    """
    chars = list(parent_seq)
    length = len(chars)
    for m in range(k):
        pos = int(stable_unit(f"{cid}:mpos:{m}") * length) % length
        chars[pos] = _AA[int(stable_unit(f"{cid}:maa:{m}") * len(_AA)) % len(_AA)]
    return "".join(chars)


class StubGenerator:
    """Emits reproducible pseudo-designs. Round 0 is de novo; later rounds MUTATE the
    selected `parents`, so a child inherits its parent's sequence — the loop genuinely
    iterates (heritable designs), though no real generative model is invoked.

    Elitism: candidate 0 carries the top-ranked parent forward UNCHANGED (parents arrive
    best-first from the planner). Under the default GREEDY acquisition this is the highest-quality
    design, so the running champion never regresses (a (μ+λ) step); under exploratory acquisitions
    parents[0] is the top-ACQUISITION design (not necessarily the highest quality), so the
    no-regression guarantee is greedy-specific. Either way the generator trusts the planner's
    ranking and never peeks at the hidden fitness.
    """

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
            if not parent or not parent.representation:
                seq = _denovo(cid)
            elif i == 0:
                seq = parent.representation          # elitism: carry the best parent forward unchanged
            else:
                seq = _mutate(parent.representation, cid)
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
