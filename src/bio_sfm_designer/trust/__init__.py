"""The external calibrated trust gate + the predictor→evidence adapter."""

from __future__ import annotations

from .gate import TrustGate
from .adapter import to_evidence

__all__ = ["TrustGate", "to_evidence"]
