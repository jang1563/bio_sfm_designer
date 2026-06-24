"""Predictor → standardized evidence packet.

Builds the model-visible evidence dict for a Prediction, shaped after the
`bio_sfm_trust.AdapterContract` evidence fields. Crucially, it exposes ONLY the
visible surface — `truth` is never included — so the same packet is safe to log and
(in M2) to put in front of the orchestrating LLM.
"""

from __future__ import annotations

from typing import Any, Dict

from bio_sfm_trust import confidence_to_risk

from ..types import Prediction


def to_evidence(prediction: Prediction) -> Dict[str, Any]:
    raw_risk = confidence_to_risk(prediction.to_record())
    disagreement = (
        None
        if not prediction.has_baseline or prediction.baseline_value is None
        else round(abs(prediction.value - prediction.baseline_value), 6)
    )
    return {
        "candidate_id": prediction.candidate_id,
        "regime": prediction.regime,
        "raw_confidence": round(prediction.raw_conf, 6),  # raw scalar (uncalibrated), never a latent
        "raw_wrong_risk": round(raw_risk, 6),
        "has_cheap_baseline": prediction.has_baseline,
        "baseline_value": prediction.baseline_value,
        "sfm_value": round(prediction.value, 6),
        "baseline_disagreement": disagreement,
        "available_actions": ["trust_sfm", "verify_assay", "default_baseline", "defer"],
        "evidence_basis": "scalar calibrated confidence + cheap-baseline disagreement",
    }
