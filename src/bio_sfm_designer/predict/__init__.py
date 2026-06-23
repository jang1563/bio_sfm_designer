"""Predictive scorers: each emits a value + a (to-be-calibrated) confidence."""

from __future__ import annotations

from .base import Predictor
from .stubs import StubPredictor

__all__ = ["Predictor", "StubPredictor"]
