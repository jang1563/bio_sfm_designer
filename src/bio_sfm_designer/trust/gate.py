"""The external, engineered calibrated trust gate.

This is the piece the whole project exists to get right. It decides, per candidate,
which of `trust_sfm | verify_assay | default_baseline | defer` to take — using ONLY
the model-visible surface of a Prediction, never its hidden truth.

Three hard constraints (measured upstream; see docs/BACKGROUND.md) are encoded here:

1. The decision is engineered and external — we never ask the LLM whether it feels
   confident (its self-allocation is ≈ chance, and stronger models over-verify).
2. The competence signal is DISAGREEMENT WITH A CHEAP STRUCTURAL BASELINE, not the
   SFM's own confidence. Where no such baseline exists, the gate defaults to
   verify/defer — it never blindly trusts.
3. Confidence is consumed as a scalar risk (calibrated), never as a raw latent.

Calibration is legitimate-data-only: it is fit from candidates whose truth was
revealed by a verify_assay (`update_calibration`). Until enough such points exist,
the gate routes on the raw (uncalibrated) risk, which is conservative.
"""

from __future__ import annotations

from typing import List, Optional

from bio_sfm_trust import confidence_to_risk, isotonic_calibrator

from ..types import Prediction, Routing

_MIN_CALIBRATION_POINTS = 8


class TrustGate:
    def __init__(
        self,
        lam: float = 0.5,
        *,
        defer_threshold: float = 0.35,
        disagreement_tol: float = 0.15,
    ) -> None:
        self.lam = lam
        self.defer_threshold = defer_threshold
        self.disagreement_tol = disagreement_tol
        self._calibrator = None  # Callable[[float], float] once fit
        self._buffer: List[tuple] = []  # (raw_risk, wrong) from verified candidates

    # --- calibration (fed only by verified, i.e. truth-revealed, candidates) ---

    def observe_verified(self, raw_risk: float, sfm_was_wrong: bool) -> None:
        self._buffer.append((float(raw_risk), 1 if sfm_was_wrong else 0))

    def refit(self) -> bool:
        """Refit the isotonic calibrator from the verified buffer. Returns True if fit."""
        if len(self._buffer) < _MIN_CALIBRATION_POINTS:
            return False
        xs = [r for r, _ in self._buffer]
        ys = [float(w) for _, w in self._buffer]
        self._calibrator = isotonic_calibrator(xs, ys)
        return True

    def _calibrate(self, raw_risk: float) -> float:
        if self._calibrator is None:
            return raw_risk
        return max(0.0, min(1.0, float(self._calibrator(raw_risk))))

    # --- routing ---

    def route(self, prediction: Prediction, lam: Optional[float] = None) -> Routing:
        lam = self.lam if lam is None else lam
        raw_risk = confidence_to_risk(prediction.to_record())
        cal_risk = self._calibrate(raw_risk)

        disagree = (
            prediction.has_baseline
            and prediction.baseline_value is not None
            and abs(prediction.value - prediction.baseline_value) > self.disagreement_tol
        )

        if cal_risk > lam:
            action, why = "verify_assay", f"calibrated risk {cal_risk:.2f} > λ={lam:.2f}"
        elif disagree:
            action, why = "default_baseline", "SFM disagrees with the cheap structural baseline"
        elif not prediction.has_baseline and cal_risk >= self.defer_threshold:
            action, why = "defer", "no structural baseline and risk non-trivial → abstain"
        else:
            action, why = "trust_sfm", f"calibrated risk {cal_risk:.2f} ≤ λ and agrees with baseline"

        return Routing(
            candidate_id=prediction.candidate_id,
            action=action,
            raw_risk=round(raw_risk, 6),
            calibrated_risk=round(cal_risk, 6),
            baseline_disagreement=bool(disagree),
            rationale=why,
        )
