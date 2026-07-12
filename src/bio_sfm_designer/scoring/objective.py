"""Per-round objective scoring, delegating the reward idiom to bio_sfm_trust.

net = benefit − λ·assays, where benefit = a design ending up correct via the chosen
action. Truth is read here (scorer-side only); the gate never sees it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from bio_sfm_trust import action_outcome, summarize_actions

from ..types import Prediction, Routing


def score_round(
    routings: List[Routing],
    predictions: Dict[str, Prediction],
    lam: float = 0.5,
) -> Dict[str, Any]:
    """Score one round's routed candidates against hidden truth."""
    rows: List[Dict[str, Any]] = []
    per_candidate: List[Dict[str, Any]] = []
    for r in routings:
        pred = predictions[r.candidate_id]
        truth = pred.truth or {}
        sfm_correct = bool(truth.get("sfm_correct", False))
        baseline_correct = bool(truth.get("baseline_correct", False))
        rows.append({
            "action": r.action,
            "sfm_correct": sfm_correct,
            "baseline_correct": baseline_correct,
        })
        correct, assays = action_outcome(
            r.action, sfm_correct=sfm_correct, baseline_correct=baseline_correct
        )
        per_candidate.append({
            "candidate_id": r.candidate_id,
            "action": r.action,
            "calibrated_risk": r.calibrated_risk,
            "correct": correct,
            "assays": assays,
            "realized_quality": truth.get("quality"),
        })

    summary = summarize_actions(rows, lam=lam)
    accepted = [c for c in per_candidate if c["correct"] == 1 and c["action"] != "verify_assay"]
    summary["best_realized_quality"] = max(
        (c["realized_quality"] for c in per_candidate if c["realized_quality"] is not None),
        default=None,
    )
    summary["accepted_trusted_count"] = len(accepted)
    return {"summary": summary, "per_candidate": per_candidate}
