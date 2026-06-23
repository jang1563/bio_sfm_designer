"""Interpreter — reads round results and decides iterate vs stop.

In M2 this is a Claude call ("given these results, continue or stop?"). In M0 it is a
deterministic budget/convergence rule.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..config import ObjectiveSpec


class Interpreter:
    def should_stop(
        self,
        round: int,
        spec: ObjectiveSpec,
        history: List[Dict[str, Any]],
        assays_used: int,
    ) -> Tuple[bool, str]:
        if round + 1 >= spec.rounds:
            return True, "round budget reached"
        if assays_used >= spec.assay_budget:
            return True, "assay budget exhausted"
        # convergence: no improvement in net reward for the last two rounds
        if len(history) >= 3:
            nets = [h["summary"].get("net_reward_per_item", 0.0) for h in history[-3:]]
            if nets[2] <= nets[1] <= nets[0]:
                return True, "net reward stopped improving"
        return False, "continue"
