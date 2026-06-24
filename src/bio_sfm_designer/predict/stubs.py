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


def _seq_quality(seq: str) -> float:
    """Hidden fitness landscape over a sequence, in [0, 1].

    Each position has a hidden set of "good" residues; quality is the fraction of positions
    holding a good one. A point mutation shifts quality by ~1/len(seq), so quality is
    HERITABLE and the landscape is climbable by mutation+selection (OneMax-style): selecting
    high-quality parents and mutating them (StubGenerator) raises quality across rounds —
    this is what makes the closed loop actually improve. The gate never sees it: hidden
    truth, surfaced only by a verify-assay / the scorer.
    """
    if not seq:
        return 0.0
    good = sum(1 for pos, aa in enumerate(seq) if stable_unit(f"fit:{pos}:{aa}") > 0.5)
    return round(good / len(seq), 4)


class StubPredictor:
    def predict(self, candidate: Candidate, spec: ObjectiveSpec) -> Prediction:
        cid = candidate.id
        quality = _seq_quality(candidate.representation)               # heritable, sequence-derived
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
