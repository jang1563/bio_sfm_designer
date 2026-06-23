"""Core data records shared across the DBTL loop.

Leakage discipline (inherited from bio-sfm-trust-audit): a `Prediction` carries a
model-visible surface (value, raw_conf, regime, baseline_value) AND a hidden
`truth` block. The trust gate may read ONLY the visible surface; `truth` is used
exclusively by the scorer to grade a finished campaign (and, in reality, is what a
verify-assay would reveal). The stub predictor fills `truth` so a dry-run can be
scored; real predictors leave it None until an assay is run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Candidate:
    """A proposed design."""
    id: str
    representation: str            # e.g. an amino-acid sequence (opaque to the loop)
    round: int = 0
    parent_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Prediction:
    """A predictive-SFM result for one candidate.

    Visible to the gate: value, raw_conf, regime, baseline_value, has_baseline.
    Hidden from the gate: truth.
    """
    candidate_id: str
    value: float                   # the predicted property (e.g. predicted stability / lDDT)
    raw_conf: float                # model-emitted confidence in [0,1] (e.g. pLDDT/100)
    regime: str = "monomer"        # routing regime; "monomer" has a cheap structural baseline
    baseline_value: Optional[float] = None   # cheap structural baseline's prediction
    has_baseline: bool = True      # whether a cheap structural baseline exists for this regime
    truth: Optional[Dict[str, Any]] = None    # HIDDEN: {sfm_correct, baseline_correct, quality}

    def to_record(self) -> Dict[str, Any]:
        """confidence_to_risk-compatible record (mean_plddt on a 0..100 scale)."""
        rec: Dict[str, Any] = {
            "regime": self.regime,
            "mean_plddt": 100.0 * self.raw_conf,
        }
        if self.regime == "complex":
            rec["iptm"] = self.raw_conf  # stub: reuse raw_conf as interface confidence
        return rec


@dataclass
class Routing:
    """The trust gate's per-candidate decision (no truth leakage)."""
    candidate_id: str
    action: str                    # trust_sfm | verify_assay | default_baseline | defer
    raw_risk: float
    calibrated_risk: float
    baseline_disagreement: bool
    rationale: str = ""


@dataclass
class ScreenVerdict:
    """Output of the biosafety screen."""
    allowed: bool
    decision_class: str            # allow | clarify | escalate | refuse | route_expert
    source: str                    # which check fired (allowlist | lexicon | bioguard | label_integrity)
    reason: str = ""
