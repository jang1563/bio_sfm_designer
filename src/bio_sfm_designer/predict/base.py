"""Predictor protocol: score a candidate, emitting a value + raw confidence.

The protocol deliberately returns a `Prediction` whose `truth` block is HIDDEN from
the trust gate. A real structure predictor (predict/structure.py, M1) populates
value/raw_conf from Boltz-2 pLDDT/ipTM and leaves `truth` None until a verify-assay
(here, experimental lDDT) is run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import ObjectiveSpec
from ..types import Candidate, Prediction


@runtime_checkable
class Predictor(Protocol):
    def predict(self, candidate: Candidate, spec: ObjectiveSpec) -> Prediction:
        """Return a Prediction for one candidate."""
        ...
