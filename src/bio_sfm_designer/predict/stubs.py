"""Deterministic mock predictor.

Produces a spread of (confidence, regime, baseline-disagreement) so the trust gate
exercises all four actions, and attaches a HIDDEN truth block so a dry-run campaign
can be scored. Monomers are calibrated (confidence tracks quality); complexes are
overconfident (confidence decoupled from quality) — mirroring the audit's designed
monomer→complex calibration gap.
"""

from __future__ import annotations

from ..config import ObjectiveSpec
from ..generate.base import stable_unit
from ..types import Candidate, Prediction

_CORRECT_QUALITY = 0.7   # quality >= this counts as a "correct" design


def _seq_quality(seq: str, epistasis: int = 0) -> float:
    """Hidden fitness landscape over a sequence, in [0, 1].

    Quality is the fraction of positions whose local context is "good". With epistasis=0 each
    position is independent (smooth, OneMax-like) — a single global optimum that greedy hill-
    climbing solves optimally. With epistasis>0 a position's good/bad status depends on a window
    of epistasis+1 residues (NK-style), creating LOCAL OPTIMA where pure exploitation can get
    trapped and exploration (UCB / Thompson / diversity) pays off — as on real, rugged protein
    fitness landscapes. Either way a point mutation shifts quality by ~(epistasis+1)/len, so
    quality is HERITABLE and the landscape is climbable by mutation+selection. The gate never
    sees it: hidden truth, surfaced only by a verify-assay / the scorer.
    """
    if not seq:
        return 0.0
    n = len(seq)
    good = 0
    for pos in range(n):
        ctx = "".join(seq[(pos + j) % n] for j in range(epistasis + 1))  # window of epistasis+1 residues
        if stable_unit(f"fit:{pos}:{ctx}") > 0.5:
            good += 1
    return round(good / n, 4)


class StubPredictor:
    def __init__(self, epistasis: int = 0) -> None:
        # 0 -> smooth landscape (greedy-optimal); >0 -> rugged (exploration pays). See _seq_quality.
        self.epistasis = epistasis

    def predict(self, candidate: Candidate, spec: ObjectiveSpec) -> Prediction:
        cid = candidate.id
        quality = _seq_quality(candidate.representation, self.epistasis)  # heritable, sequence-derived
        regime = "complex" if stable_unit(cid + ":regime") < 0.4 else "monomer"
        has_baseline = stable_unit(cid + ":hb") > 0.20                  # ~80% have a baseline

        if regime == "monomer":
            raw_conf = quality                                         # calibrated: confidence tracks quality
        else:
            raw_conf = round(0.40 + 0.59 * stable_unit(cid + ":conf"), 4)  # overconfident / decoupled

        sfm_correct = quality >= _CORRECT_QUALITY
        baseline_value = (
            round(quality + (stable_unit(cid + ":bdir") - 0.5) * 0.6, 4) if has_baseline else None
        )
        baseline_correct = bool(has_baseline and stable_unit(cid + ":bc") > 0.45)

        return Prediction(
            candidate_id=cid,
            value=quality,                 # predicted property (informational)
            raw_conf=raw_conf,
            regime=regime,
            baseline_value=baseline_value,
            has_baseline=has_baseline,
            truth={
                "sfm_correct": sfm_correct,
                "baseline_correct": baseline_correct,
                "quality": quality,
            },
        )
