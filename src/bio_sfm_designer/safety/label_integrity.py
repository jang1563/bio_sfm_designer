"""Sequence-vs-claimed-identity coherence check (M2c).

Provenance: the verdict-parsing rule is copied from FRT_Pilot_Execution's
`label_integrity_spec.parse_verdict` (cite FRT). Discipline from docs/LABEL_INTEGRITY_CARD.md:
- read the CONTENT verdict (MATCH / MISMATCH / UNCERTAIN), NEVER `stop_reason`;
- a toxin-LABELED record pre-empts to human review ("absence of MATCH is not MATCH");
- this is a triage aid for a HUMAN decision, not a standalone hazard detector or autonomous gate.

The check is an LLM call routed through the same provider seam as the orchestrator (mock in
tests; real Claude in M2). It does NOT make the trust-routing decision.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..types import ScreenVerdict

_VERDICTS = ("MISMATCH", "MATCH", "UNCERTAIN")


def parse_verdict(text: str) -> str:
    """Parse the leading verdict token from response TEXT (stop_reason-agnostic).

    Provenance: FRT_Pilot_Execution label_integrity_spec.parse_verdict.
    """
    t = re.sub(r"[*_#>`]+", "", text or "").strip().upper()
    m = re.match(r"^\W*(MISMATCH|MATCH|UNCERTAIN)\b", t)
    if m:
        return m.group(1)
    for v in _VERDICTS:
        if re.search(r"\b" + v + r"\b", t[:80]):
            return v
    return "UNPARSEABLE"


def _prompt(sequence: str, claimed_identity: str) -> str:
    return (
        "You are a sequence/label coherence checker. Given a biological sequence and a CLAIMED "
        "identity, judge whether the sequence is consistent with that claimed identity.\n"
        f"Claimed identity: {claimed_identity}\n"
        f"Sequence: {sequence}\n\n"
        "Reply with ONLY one word as the FIRST token: MATCH, MISMATCH, or UNCERTAIN."
    )


def check_label_integrity(
    sequence: str,
    claimed_identity: str,
    provider: Optional[Callable[[str], str]],
    *,
    toxin_labeled: bool = False,
) -> ScreenVerdict:
    """MATCH on a non-toxin-labeled design -> allow; everything else (MISMATCH / UNCERTAIN /
    UNPARSEABLE / any toxin-labeled record / no provider) -> route to human review."""
    if toxin_labeled:
        return ScreenVerdict(False, "route_expert", "label_integrity",
                             "toxin-labeled record -> human review (absence of MATCH is not MATCH)")
    if provider is None:
        return ScreenVerdict(False, "route_expert", "label_integrity",
                             "no provider to verify sequence/identity coherence -> human review")
    try:
        verdict = parse_verdict(provider(_prompt(sequence, claimed_identity)))
    except Exception:
        verdict = "UNPARSEABLE"
    if verdict == "MATCH":
        return ScreenVerdict(True, "allow", "label_integrity", "sequence consistent with claimed identity")
    return ScreenVerdict(False, "route_expert", "label_integrity",
                         f"sequence/identity coherence = {verdict} -> human review")
