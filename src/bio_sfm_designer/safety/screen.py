"""The screening gate. Runs on the objective (before propose) and on each design that
advances (before synth).

TIERED BACKEND, best available first (graceful degradation):
  1. learned DeBERTa classifier (constitutional-bioguard) — needs torch + model weights
     (deberta_pdual_v3 / deberta_bioguard_v8b). Strongest, but heavy.
  2. rule lexicon (constitutional-bioguard `bio_lexicon`) — weight-free regex tiers.
  3. built-in policy only (this package, pure stdlib) — the M0 default.
The built-in target-level policy (allowlist + unconditional denylist) ALWAYS runs first as a
hard pre-filter; the resolved classifier is an additional flag on top.

Posture: a triage aid producing candidates for HUMAN decision, NOT an autonomous gate —
"absence of a flag is not a clearance." Keyword/lexicon screening is documented-evadable
(e.g. ChemCrow's IUPAC-name bypass), which is why sequence-vs-claimed-identity coherence is a
separate check (label_integrity, M2c), not part of this text screen.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from ..config import ObjectiveSpec
from ..types import Candidate, ScreenVerdict
from .policy import target_decision

# A text classifier: text -> (flagged: bool, reason: str)
TextClassifier = Callable[[str], Tuple[bool, str]]


def _load_deberta() -> Optional[TextClassifier]:
    """Learned biosafety classifier (constitutional-bioguard DeBERTa, prompt-side intent screen).
    Needs torch + local model weights; absent here -> None -> falls back to the lexicon/builtin."""
    try:
        import torch  # noqa: F401
        from constitutional_bioguard.dual_mode import DualModeGuard  # type: ignore
    except Exception:
        return None
    try:
        guard = DualModeGuard()

        def classify(text: str) -> Tuple[bool, str]:
            verdict = guard.classify(text)  # prompt-only intent screen
            flagged = bool(getattr(verdict, "joint_flag", False) or getattr(verdict, "prompt_flag", False))
            return flagged, str(getattr(verdict, "joint_reason", "deberta classifier flag"))

        return classify
    except Exception:
        return None


def _load_bioguard_lexicon() -> Optional[TextClassifier]:
    """Rule lexicon (weight-free). Wraps bio_lexicon.classify into a text classifier or None."""
    try:
        from constitutional_bioguard.bio_lexicon import classify as lex  # type: ignore
    except Exception:
        return None

    def classify(text: str) -> Tuple[bool, str]:
        res = lex(text)
        if isinstance(res, dict):
            return bool(res.get("flag")), str(res.get("reason", "lexicon flag"))
        return False, ""

    return classify


def _resolve_backend() -> Tuple[Optional[TextClassifier], str]:
    clf = _load_deberta()
    if clf is not None:
        return clf, "constitutional_bioguard.deberta"
    clf = _load_bioguard_lexicon()
    if clf is not None:
        return clf, "constitutional_bioguard.bio_lexicon"
    return None, "builtin_policy"


class SafetyScreen:
    def __init__(self, classifier: Optional[TextClassifier] = None) -> None:
        # An explicit classifier (e.g. a test fake) overrides backend resolution.
        if classifier is not None:
            self._classifier, self.backend = classifier, "injected"
        else:
            self._classifier, self.backend = _resolve_backend()

    def _classify(self, text: str) -> Optional[Tuple[bool, str]]:
        if self._classifier is None:
            return None
        try:
            return self._classifier(text)
        except Exception:
            return None  # a classifier failure must not crash the loop (no flag -> builtin decides)

    def screen_target(self, spec: ObjectiveSpec) -> ScreenVerdict:
        """Screen the campaign objective BEFORE any design is proposed."""
        decision, allowed, reason = target_decision(spec.target, spec.objective, spec.allowlist)
        if not allowed:  # hard pre-filter (unconditional denylist / allowlist) wins
            return ScreenVerdict(False, decision, "builtin_policy", reason)
        flagged = self._classify(f"{spec.target}. Objective: {spec.objective}")
        if flagged and flagged[0]:
            return ScreenVerdict(False, "escalate", self.backend, flagged[1])
        return ScreenVerdict(True, "allow", "builtin_policy", reason)

    def screen_design(self, text: str, *, context: str = "") -> ScreenVerdict:
        """Screen a single design that is about to advance to build/synth."""
        decision, allowed, reason = target_decision(context, text)
        if not allowed:
            return ScreenVerdict(False, decision, "builtin_policy", reason)
        flagged = self._classify(f"{context} {text}".strip())
        if flagged and flagged[0]:
            return ScreenVerdict(False, "escalate", self.backend, flagged[1])
        return ScreenVerdict(True, "allow", self.backend, "no hazard signal")

    def screen_candidate(self, candidate: Candidate) -> ScreenVerdict:
        ctx = str(candidate.meta.get("target", ""))
        return self.screen_design(candidate.representation, context=ctx)
