"""Generative front-end: SFM wrappers behind a stable Generator protocol."""

from __future__ import annotations

from .base import Generator
from .stubs import StubGenerator

__all__ = ["Generator", "StubGenerator"]
