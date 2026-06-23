"""Calibrated-permissioning policy: per-target decision classes + allowlist.

Safety here is a CALIBRATION problem, not blanket suppression (see docs/BACKGROUND.md):
route each target among allow / clarify / escalate / refuse / route_expert, aiming to
minimize BOTH false negatives (harmful) and false positives (blocked legitimate work).

This is a thin, conservative built-in policy for M0. The real classifier
(constitutional-bioguard) plugs in via safety.screen; this module supplies the
target-level allowlist and the small unconditional denylist.
"""

from __future__ import annotations

from typing import List, Tuple

DECISION_CLASSES = ("allow", "clarify", "escalate", "refuse", "route_expert")

# Unconditional: these describe operational intent on their own → refuse.
_UNCONDITIONAL = (
    "bioweapon", "biological weapon", "weaponize", "weaponized",
    "gain-of-function", "gain of function", "enhance transmissibility",
    "enhance lethality", "evade vaccine", "increase virulence",
)

# Contextual select-agent / toxin names: escalate to expert review (not auto-refuse;
# these are legitimate research subjects, and over-refusal is a documented failure).
_SELECT_AGENT_HINTS = (
    "anthrax", "bacillus anthracis", "botulinum", "ricin", "abrin",
    "ebola", "marburg", "smallpox", "variola", "yersinia pestis",
)


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def target_decision(target: str, objective: str = "", allowlist: List[str] = ()) -> Tuple[str, bool, str]:
    """Return (decision_class, allowed, reason) for a campaign target.

    - any unconditional term → refuse
    - select-agent hint → route_expert (allowed only with human sign-off)
    - allowlist set but unmatched → clarify
    - otherwise → allow
    """
    blob = _norm(f"{target} {objective}")
    raw_blob = f"{target} {objective}".lower()  # keep hyphens for "gain-of-function"

    for term in _UNCONDITIONAL:
        if term in blob or term in raw_blob:
            return "refuse", False, f"unconditional hazard term: {term!r}"

    for term in _SELECT_AGENT_HINTS:
        if term in blob:
            return "route_expert", False, f"select-agent hint {term!r} → human expert review required"

    if allowlist:
        tags = [_norm(t) for t in allowlist]
        if not any(tag in blob for tag in tags):
            return "clarify", False, f"target does not match allowlist {list(allowlist)!r}"

    return "allow", True, "no hazard signal; within scope"
