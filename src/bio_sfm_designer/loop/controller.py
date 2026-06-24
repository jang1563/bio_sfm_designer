"""The DBTL controller: Design → Build → Test → Learn, with both gates wired in.

Per round:
  1. (round 0) screen the objective; abort if not allowed.
  2. Design:  generator proposes candidates (seeded from prior parents).
  3. Test:    predictor scores each candidate (value + raw confidence).
  4. Route:   the EXTERNAL trust gate picks an action per candidate.
  5. Budget:  cap verify_assay at the assay budget (downgrade overflow).
  6. Screen:  re-screen any candidate that would advance to build/synth.
  7. Calibrate: verified candidates (truth revealed) feed the gate's calibrator.
  8. Score:   net = benefit − λ·assays (via bio_sfm_trust).
  9. Learn:   planner seeds the next round; interpreter decides iterate vs stop.

Claude orchestrates (planner/interpreter); the gate decides trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bio_sfm_trust import summarize_actions

from .. import io_utils
from ..config import ObjectiveSpec
from ..generate import StubGenerator
from ..predict import StubPredictor
from ..safety import SafetyScreen
from ..scoring import score_round
from ..trust import TrustGate, to_evidence
from .interpreter import Interpreter
from .planner import Planner

_ADVANCING = ("trust_sfm", "verify_assay", "default_baseline")


@dataclass
class CampaignResult:
    status: str                      # "allow" if it ran, else the blocking decision class
    allowed: bool
    target: str
    rounds_run: int = 0
    assays_used: int = 0
    gate_calibrated: bool = False
    screen_backend: str = ""
    aggregate: Dict[str, Any] = field(default_factory=dict)
    per_round: List[Dict[str, Any]] = field(default_factory=list)
    best: Optional[Dict[str, Any]] = None
    campaign_path: Optional[str] = None
    summary_path: Optional[str] = None
    rows: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""


class DBTLController:
    def __init__(self, generator=None, predictor=None, gate=None, screen=None, planner=None,
                 interpreter=None, provider=None):
        self.generator = generator or StubGenerator()
        self.predictor = predictor or StubPredictor()
        self.gate = gate or TrustGate()
        self.screen = screen or SafetyScreen()
        # planner may be None -> built from the spec in run() (so acquisition/diversity are configurable)
        self.planner = planner
        # provider (an LLM callable) makes the interpreter LLM-orchestrated; None -> deterministic.
        self.interpreter = interpreter or Interpreter(provider=provider)

    def run(self, spec: ObjectiveSpec, out_dir: Optional[str] = None) -> CampaignResult:
        # 1. screen the objective before anything is generated
        verdict = self.screen.screen_target(spec)
        if not verdict.allowed:
            return CampaignResult(
                status=verdict.decision_class,
                allowed=False,
                target=spec.target,
                screen_backend=self.screen.backend,
                note=f"objective blocked at screen: {verdict.reason}",
            )

        self.gate.lam = spec.lam
        planner = self.planner or Planner(
            acquisition=spec.acquisition, beta=spec.acq_beta, diversity=spec.diversity, seed=spec.seed
        )
        rows: List[Dict[str, Any]] = []
        all_decisions: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []
        assays_used = 0
        best: Optional[Dict[str, Any]] = None
        parents = None
        rounds_run = 0

        for rnd in range(spec.rounds):
            candidates = self.generator.propose(spec, rnd, spec.candidates_per_round, parents)
            if not candidates:
                break  # generator exhausted (e.g. a fixed target set) -> stop, no phantom round
            rounds_run = rnd + 1
            cand_by_id = {c.id: c for c in candidates}
            predictions = {c.id: self.predictor.predict(c, spec) for c in candidates}
            calibrated_this_round = self.gate.any_calibrated()  # calibrator state USED by this round

            routings = []
            for c in candidates:
                pred = predictions[c.id]
                routing = self.gate.route(pred, lam=spec.lam)

                # 5. assay-budget enforcement
                if routing.action == "verify_assay" and assays_used >= spec.assay_budget:
                    if pred.has_baseline:
                        routing.action = "default_baseline"
                        routing.rationale += " | assay budget exhausted → baseline"
                    else:
                        routing.action = "defer"
                        routing.rationale += " | assay budget exhausted → defer"

                # 6. pre-synth screen for advancing actions
                screen_v = None
                if routing.action in _ADVANCING:
                    screen_v = self.screen.screen_candidate(c)
                    if not screen_v.allowed:
                        routing.action = "defer"
                        routing.rationale += f" | screen blocked ({screen_v.decision_class}: {screen_v.reason})"

                # 7. verify reveals truth → feeds the calibrator (legitimate data only)
                if routing.action == "verify_assay":
                    assays_used += 1
                    sfm_wrong = not bool((pred.truth or {}).get("sfm_correct", False))
                    self.gate.observe_verified(routing.raw_risk, sfm_wrong, pred.regime)

                routings.append(routing)
                rows.append({
                    "round": rnd,
                    "candidate_id": c.id,
                    "parent_id": c.parent_id,
                    "action": routing.action,
                    "raw_risk": routing.raw_risk,
                    "calibrated_risk": routing.calibrated_risk,
                    "baseline_disagreement": routing.baseline_disagreement,
                    "rationale": routing.rationale,
                    "evidence": to_evidence(pred),
                    "screen": None if screen_v is None else {
                        "allowed": screen_v.allowed,
                        "decision_class": screen_v.decision_class,
                        "source": screen_v.source,
                    },
                    "hidden_truth": pred.truth,   # research artifact; never seen by the gate
                })
                all_decisions.append({
                    "action": routing.action,
                    "sfm_correct": bool((pred.truth or {}).get("sfm_correct", False)),
                    "baseline_correct": bool((pred.truth or {}).get("baseline_correct", False)),
                })

            # refit the calibrator from verified data — takes effect on the NEXT round
            self.gate.refit()

            # 8. score the round
            scored = score_round(routings, predictions, lam=spec.lam)
            scored["round"] = rnd
            scored["calibrator_fitted"] = calibrated_this_round  # did THIS round's routing use a calibrator
            history.append(scored)

            for pc in scored["per_candidate"]:
                if pc["correct"] == 1 and pc["action"] != "verify_assay" and pc["realized_quality"] is not None:
                    if best is None or pc["realized_quality"] > best["realized_quality"]:
                        best = {"candidate_id": pc["candidate_id"], "realized_quality": pc["realized_quality"], "round": rnd}

            # 9. learn: seed next round, decide stop
            parents = planner.select_parents(
                routings, predictions, cand_by_id, k=max(1, spec.candidates_per_round // 2)
            )
            decision = self.interpreter.interpret(rnd, spec, history, assays_used)
            if decision.get("hypothesis"):
                history[-1]["llm_hypothesis"] = decision["hypothesis"]
            if decision["stop"]:
                history[-1]["stop_reason"] = decision["reason"]
                break

        aggregate = summarize_actions(all_decisions, lam=spec.lam)
        per_round = [{"round": h["round"], **h["summary"],
                      "calibrator_fitted": h.get("calibrator_fitted", False),
                      "stop_reason": h.get("stop_reason"),
                      "llm_hypothesis": h.get("llm_hypothesis")} for h in history]

        result = CampaignResult(
            status="allow",
            allowed=True,
            target=spec.target,
            rounds_run=rounds_run,
            assays_used=assays_used,
            gate_calibrated=self.gate.any_calibrated(),
            screen_backend=self.screen.backend,
            aggregate=aggregate,
            per_round=per_round,
            best=best,
            rows=rows,
        )

        if out_dir:
            result.campaign_path = io_utils.write_campaign(rows, f"{out_dir}/campaign.jsonl")
            result.summary_path = io_utils.write_summary(
                {
                    "target": spec.target,
                    "objective": spec.objective,
                    "lambda": spec.lam,
                    "rounds_run": rounds_run,
                    "assays_used": assays_used,
                    "assay_budget": spec.assay_budget,
                    "gate_calibrated": result.gate_calibrated,
                    "screen_backend": result.screen_backend,
                    "aggregate": aggregate,
                    "per_round": per_round,
                    "best": best,
                },
                f"{out_dir}/summary.json",
            )
        return result
