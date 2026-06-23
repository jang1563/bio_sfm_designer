"""Generator protocol: propose candidate designs.

Real generators (ProteinMPNN / RFdiffusion / ESM) slot in behind this same
interface in a later milestone; M0 ships only the deterministic stub.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Protocol, runtime_checkable

from ..config import ObjectiveSpec
from ..types import Candidate


@runtime_checkable
class Generator(Protocol):
    def propose(
        self,
        spec: ObjectiveSpec,
        round: int,
        n: int,
        parents: Optional[List[Candidate]] = None,
    ) -> List[Candidate]:
        """Return up to `n` candidate designs for the given round."""
        ...


def stable_unit(key: str) -> float:
    """Deterministic float in [0, 1) from a string (platform-independent; no salted hash)."""
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF
