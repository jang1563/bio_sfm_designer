"""Interpreter — reads round results and decides iterate vs stop.

M0/M1: deterministic budget/convergence rule. M2: an optional LLM provider acts as the
ORCHESTRATOR — it may stop early and propose a hypothesis for the next round. It does NOT
make the trust-routing decision (that's the external gate), and it CANNOT override the
budget caps: hard limits (rounds, assay budget) are enforced in code regardless of what the
LLM says. The LLM can only stop earlier or annotate direction. Tests inject a fake provider;
no network.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import ObjectiveSpec


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort parse of a JSON object from an LLM response (robust to prose around it)."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None


class Interpreter:
    def __init__(self, provider: Optional[Callable[[str], str]] = None) -> None:
        # provider: an LLM callable (prompt -> text) for orchestration; None -> deterministic only
        self.provider = provider

    # --- deterministic hard limits (never delegated to the LLM) ---

    def should_stop(self, round: int, spec: ObjectiveSpec, history: List[Dict[str, Any]], assays_used: int) -> Tuple[bool, str]:
        if round + 1 >= spec.rounds:
            return True, "round budget reached"
        if assays_used >= spec.assay_budget:
            return True, "assay budget exhausted"
        if len(history) >= 3:
            nets = [h["summary"].get("net_reward_per_item", 0.0) for h in history[-3:]]
            if nets[2] <= nets[1] <= nets[0]:
                return True, "net reward stopped improving"
        return False, "continue"

    # --- orchestration: deterministic caps OR'd with the LLM's (early-stop + hypothesis) ---

    def interpret(self, round: int, spec: ObjectiveSpec, history: List[Dict[str, Any]], assays_used: int) -> Dict[str, Any]:
        stop, reason = self.should_stop(round, spec, history, assays_used)
        hypothesis = None
        explore = None  # the orchestrator's optional steer: diversify (True) vs exploit (False)
        if self.provider is not None and not stop:
            decision = self._ask_llm(round, spec, history)
            if decision:
                hypothesis = decision.get("hypothesis")
                if "explore" in decision:
                    explore = bool(decision["explore"])
                if decision.get("stop") is True:
                    stop, reason = True, f"llm: {decision.get('reason', 'orchestrator chose to stop')}"
        return {"stop": stop, "reason": reason, "hypothesis": hypothesis, "explore": explore}

    def _ask_llm(self, round: int, spec: ObjectiveSpec, history: List[Dict[str, Any]]) -> Optional[dict]:
        summary = history[-1]["summary"] if history else {}
        prompt = (
            "You are the ORCHESTRATOR of a Design-Build-Test-Learn protein-design loop. "
            "You do NOT decide whether to trust any model output — an external calibrated gate "
            "does that. Your job: given this round's aggregate results, decide whether to stop "
            "early and propose one hypothesis for the next round.\n\n"
            f"Objective: {spec.objective} for target: {spec.target}\n"
            f"Round {round} (of max {spec.rounds}) results: {json.dumps(summary, sort_keys=True)}\n\n"
            'Reply with ONLY a JSON object: {"stop": <bool>, "reason": "<short>", '
            '"hypothesis": "<one concrete next-round design direction>", '
            '"explore": <bool: true to DIVERSIFY the next batch (escape a plateau), '
            'false to EXPLOIT the current best>}'
        )
        try:
            return _extract_json(self.provider(prompt))  # type: ignore[misc]
        except Exception:
            return None  # any provider/parse failure -> fall back to the deterministic decision
