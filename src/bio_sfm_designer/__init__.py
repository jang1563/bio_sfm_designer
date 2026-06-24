"""bio_sfm_designer — a calibrated, cost-aware, safety-screened DBTL designer.

Claude orchestrates specialist scientific foundation models (SFMs); an EXTERNAL
calibrated trust gate decides, per candidate, whether to trust the model's output,
verify it by assay, fall back to a cheap baseline, or defer — and a biosafety screen
runs before propose and before synth. The trust engine is reused from
`bio_sfm_trust` (the bio-sfm-trust-core package).
"""

from __future__ import annotations

__version__ = "0.1.0"

try:  # the calibrated trust engine (sibling package) — fail loudly with a fix hint
    import bio_sfm_trust as _bio_sfm_trust  # noqa: F401
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "bio_sfm_designer requires 'bio-sfm-trust' (the trust engine). Install it first:\n"
        "    pip install -e ../bio-sfm-trust-core"
    ) from _exc

from .types import Candidate, Prediction, Routing, ScreenVerdict
from .config import ObjectiveSpec
from .loop.controller import DBTLController, CampaignResult

__all__ = [
    "Candidate",
    "Prediction",
    "Routing",
    "ScreenVerdict",
    "ObjectiveSpec",
    "DBTLController",
    "CampaignResult",
]
