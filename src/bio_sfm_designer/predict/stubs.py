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


class StubPredictor:
    def predict(self, candidate: Candidate, spec: ObjectiveSpec) -> Prediction:
        cid = candidate.id
        raw_conf = round(0.40 + 0.59 * stable_unit(cid + ":conf"), 4)   # 0.40..0.99
        regime = "complex" if stable_unit(cid + ":regime") < 0.4 else "monomer"
        has_baseline = stable_unit(cid + ":hb") > 0.20                  # ~80% have a baseline

        if regime == "monomer":
            quality = raw_conf                                         # calibrated
        else:
            quality = round(stable_unit(cid + ":qual"), 4)            # overconfident / decoupled

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
