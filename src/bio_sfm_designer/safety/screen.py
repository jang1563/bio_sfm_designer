"""The screening gate. Runs on the objective (before propose) and on each design
that advances (before synth).

M0 uses a dependency-free built-in path + the target-level policy. When
`constitutional-bioguard` is installed, its rule-based `bio_lexicon` (weight-free)
is preferred for text screening; the full DeBERTa classifier is an M2 upgrade.
Posture: a triage aid producing candidates for human decision, NOT an autonomous
gate — "absence of a flag is not a clearance."
"""

from __future__ import annotations

from typing import Callable, Optional

from ..config import ObjectiveSpec
from ..types import Candidate, ScreenVerdict
from .policy import target_decision


def _load_bioguard_lexicon() -> Optional[Callable]:
    """Return constitutional_bioguard.bio_lexicon.classify if importable (no weights)."""
    try:
        from constitutional_bioguard.bio_lexicon import classify  # type: ignore
        return classify
    except Exception:
        return None


class SafetyScreen:
    def __init__(self) -> None:
        self._bioguard = _load_bioguard_lexicon()
        self.backend = "constitutional_bioguard.bio_lexicon" if self._bioguard else "builtin_policy"

    def screen_target(self, spec: ObjectiveSpec) -> ScreenVerdict:
        """Screen the campaign objective BEFORE any design is proposed."""
        decision, allowed, reason = target_decision(spec.target, spec.objective, spec.allowlist)
        # If a bioguard lexicon is present, let it veto (flag → escalate) on the target text.
        if self._bioguard is not None and allowed:
            res = self._bioguard(f"{spec.target}. Objective: {spec.objective}")
            if isinstance(res, dict) and res.get("flag"):
                return ScreenVerdict(False, "escalate", self.backend, res.get("reason", "lexicon flag"))
        return ScreenVerdict(allowed, decision, "builtin_policy", reason)

    def screen_design(self, text: str, *, context: str = "") -> ScreenVerdict:
        """Screen a single design that is about to advance to build/synth."""
        decision, allowed, reason = target_decision(context, text)
        if not allowed:
            return ScreenVerdict(False, decision, "builtin_policy", reason)
        if self._bioguard is not None:
            res = self._bioguard(f"{context} {text}".strip())
            if isinstance(res, dict) and res.get("flag"):
                return ScreenVerdict(False, "escalate", self.backend, res.get("reason", "lexicon flag"))
        return ScreenVerdict(True, "allow", self.backend, "no hazard signal")

    def screen_candidate(self, candidate: Candidate) -> ScreenVerdict:
        ctx = str(candidate.meta.get("target", ""))
        return self.screen_design(candidate.representation, context=ctx)
