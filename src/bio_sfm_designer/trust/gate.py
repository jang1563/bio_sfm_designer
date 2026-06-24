"""The external, engineered calibrated trust gate.

This is the piece the whole project exists to get right. It decides, per candidate,
which of `trust_sfm | verify_assay | default_baseline | defer` to take — using ONLY
the model-visible surface of a Prediction, never its hidden truth.

Three hard constraints (measured upstream; see docs/BACKGROUND.md) are encoded here:

1. The decision is engineered and external — we never ask the LLM whether it feels
   confident (its self-allocation is ≈ chance, and stronger models over-verify).
2. Where a cheap structural baseline exists (e.g. perturbation regimes), the competence
   signal is DISAGREEMENT WITH THAT BASELINE rather than the SFM's own confidence. Where
   none exists (e.g. protein structure), the verify/trust threshold uses the calibrated
   confidence-risk.
3. Confidence is consumed as a scalar risk (calibrated), never as a raw latent.

PER-REGIME, CALIBRATION-VALIDATED TRUST (the design the M0/M1 trade-off analysis drove):
`trust_sfm` is permitted in a regime ONLY if that regime's wrong-risk signal is
calibration-validated — either assumed (monomer pLDDT is offline-validated in the
literature: audit Pearson ~0.89, McGuffin ~0.97) or EARNED, by accumulating verified
candidates (or an offline `prevalidate` pass) whose calibrated risk clears an
offline-gate-style check (AUROC ≥ bar AND calibrated-selective beats trust-all). An
unvalidated regime never trusts the raw signal — it verifies to bootstrap its calibrator
(the assay budget may downgrade overflow to defer). This recovers the ~2× cost saving and
higher net that calibrated-selective routing beats blanket verify-all by, while never
trusting an uncalibrated signal. Routing always uses the calibrated risk when a calibrator
exists (raw risk `1 − pLDDT` is compressed and degenerates to trust-all on its own).

Calibration is legitimate-data-only: fit from candidates whose truth a verify_assay
revealed (`observe_verified`), or from held-out data via `prevalidate`. Never from the
hidden truth of candidates the gate is currently routing.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from bio_sfm_trust import (auroc, confidence_to_risk, isotonic_calibrator, loo_calibrated_risks,
                           rcps_threshold)

from ..types import Prediction, Routing

_MIN_CALIBRATION_POINTS = 8
_VALIDITY_AUROC_MIN = 0.70


class _RegimeState:
    __slots__ = ("buffer", "calibrator", "validated", "tau")

    def __init__(self) -> None:
        self.buffer: List[tuple] = []        # (raw_risk, wrong) from verified candidates
        self.calibrator = None               # Callable[[float], float] once fit
        self.validated = False               # cleared the offline-gate-style validity check
        self.tau = None                      # conformal/RCPS trust threshold (None until certified)


class TrustGate:
    def __init__(
        self,
        lam: float = 0.5,
        *,
        defer_threshold: float = 0.35,
        disagreement_tol: float = 0.15,
        assume_validated: frozenset = frozenset({"monomer"}),
        conformal_alpha: Optional[float] = None,
        conformal_delta: float = 0.1,
    ) -> None:
        self.lam = lam
        # If conformal_alpha is set, trust uses a per-regime RCPS threshold tau (so the trusted set's
        # false-accept rate is <= alpha with prob >= 1-delta) instead of the lambda cost threshold,
        # for any regime where a tau can be certified from calibration data; else it falls back to lambda.
        self.conformal_alpha = conformal_alpha
        self.conformal_delta = conformal_delta
        self.defer_threshold = defer_threshold
        self.disagreement_tol = disagreement_tol
        # Regimes trusted without online data. monomer pLDDT is offline-validated; every
        # other regime must EARN trust through a validated calibrator.
        self.assume_validated = set(assume_validated)
        self._regimes: Dict[str, _RegimeState] = {}

    def _state(self, regime: str) -> _RegimeState:
        st = self._regimes.get(regime)
        if st is None:
            st = _RegimeState()
            self._regimes[regime] = st
        return st

    # --- calibration (fed only by verified, truth-revealed candidates) ---

    def observe_verified(self, raw_risk: float, sfm_was_wrong: bool, regime: str = "monomer") -> None:
        self._state(regime).buffer.append((float(raw_risk), 1 if sfm_was_wrong else 0))

    def prevalidate(self, regime: str, raw_risks: List[float], wrong: List[int]) -> bool:
        """Offline 'gate-before-spend': fit + validate a regime from held-out verified data
        (e.g. the M1 fixture) so deployment starts with that regime calibration-validated.
        Returns whether the regime is now trust-validated."""
        st = self._state(regime)
        st.buffer = [(float(x), int(w)) for x, w in zip(raw_risks, wrong)]
        return self._fit_and_validate(st)

    def refit(self) -> Dict[str, bool]:
        """Refit each regime's calibrator from its verified buffer and re-check validity.
        Returns {regime: validated}. Takes effect on subsequent routing."""
        return {regime: self._fit_and_validate(st) for regime, st in self._regimes.items()}

    def _fit_and_validate(self, st: _RegimeState) -> bool:
        xs = [x for x, _ in st.buffer]
        ys = [w for _, w in st.buffer]
        if len(xs) < _MIN_CALIBRATION_POINTS:
            return st.validated
        st.calibrator = isotonic_calibrator(xs, [float(y) for y in ys])
        npos = sum(ys)
        if npos == 0 or npos == len(ys):
            return st.validated  # one class only -> cannot assess; keep prior verdict
        a = auroc(xs, ys)  # ranking metric (monotonic-invariant)
        if a is None or a < _VALIDITY_AUROC_MIN:
            st.validated = False
            return False
        # honest check: leave-one-out calibrated-selective must beat just-trust-everything
        cal = loo_calibrated_risks(xs, ys)
        st.validated = self._policy_net(cal, ys, self.lam) > (len(ys) - npos) / len(ys)
        if self.conformal_alpha is not None:
            # certify a trust threshold from the LOO (honest) calibrated risks + revealed wrongness
            st.tau = rcps_threshold(cal, ys, self.conformal_alpha, self.conformal_delta)
        return st.validated

    @staticmethod
    def _policy_net(risks: List[float], wrong: List[int], lam: float) -> float:
        """Per-item net for 'verify iff risk>lam, else trust'."""
        n = len(wrong)
        if not n:
            return 0.0
        correct = assays = 0
        for r, w in zip(risks, wrong):
            if r > lam:
                correct += 1
                assays += 1
            elif not w:
                correct += 1
        return (correct - lam * assays) / n

    def _calibrate(self, raw_risk: float, regime: str) -> float:
        st = self._regimes.get(regime)
        if st is None or st.calibrator is None:
            return raw_risk
        return max(0.0, min(1.0, float(st.calibrator(raw_risk))))

    def _trust_eligible(self, regime: str) -> bool:
        if regime in self.assume_validated:
            return True
        st = self._regimes.get(regime)
        return bool(st and st.validated)

    def any_calibrated(self) -> bool:
        return any(st.calibrator is not None for st in self._regimes.values())

    # --- routing ---

    def route(self, prediction: Prediction, lam: Optional[float] = None) -> Routing:
        lam = self.lam if lam is None else lam
        raw_risk = confidence_to_risk(prediction.to_record())
        cal_risk = self._calibrate(raw_risk, prediction.regime)

        disagree = (
            prediction.has_baseline
            and prediction.baseline_value is not None
            and abs(prediction.value - prediction.baseline_value) > self.disagreement_tol
        )

        # trust/verify threshold: the per-regime conformal τ (false-accept ≤ α) when conformal mode
        # is on AND this regime has a certified τ; otherwise the λ cost threshold.
        trust_thr, thr_label = lam, f"λ={lam:.2f}"
        if self.conformal_alpha is not None:
            st = self._regimes.get(prediction.regime)
            tau = st.tau if st is not None else None
            if tau is not None:
                trust_thr = tau
                thr_label = f"RCPS τ={tau:.2f} (false-accept≤{self.conformal_alpha:.2f})"

        if cal_risk > trust_thr:
            action, why = "verify_assay", f"calibrated risk {cal_risk:.2f} > {thr_label}"
        elif disagree:
            action, why = "default_baseline", "SFM disagrees with the cheap structural baseline"
        elif not prediction.has_baseline and cal_risk >= self.defer_threshold:
            action, why = "defer", "no structural baseline and risk non-trivial → abstain"
        else:
            action, why = "trust_sfm", f"calibrated risk {cal_risk:.2f} ≤ {thr_label}"

        # Trust only calibration-validated regimes. An unvalidated regime never trusts the
        # raw signal -> verify to bootstrap its calibrator (budget may downgrade to defer).
        if action == "trust_sfm" and not self._trust_eligible(prediction.regime):
            action = "verify_assay"
            why = f"regime '{prediction.regime}' not calibration-validated → verify to bootstrap"

        return Routing(
            candidate_id=prediction.candidate_id,
            action=action,
            raw_risk=round(raw_risk, 6),
            calibrated_risk=round(cal_risk, 6),
            baseline_disagreement=bool(disagree),
            rationale=why,
        )
