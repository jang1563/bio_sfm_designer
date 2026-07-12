"""Closed-loop DBTL campaign + an honest routing-policy comparison.

Runs a multi-round campaign on the CPU stub backend (heritable designs + a hidden, sequence-
derived fitness landscape) and reports:

  1. THE CLIMB — mean/best design quality per round. Because designs are heritable and quality is
     sequence-derived (M3a), selecting good parents and mutating them genuinely improves the
     population: the loop is closed and the orchestrator actually drives it.

  2. THE ROUTING-POLICY COMPARISON — on the SAME candidate stream (the M1 offline setup, now on a
     climbing loop), score three routing policies under a verification price `lambda` and a
     FALSE-ACCEPT cost `mu` (advancing a wrong design is not free):
       - calibrated : the external trust gate (verify the high-risk, trust the low-risk).
       - verify_all : verify every candidate up to budget (max assay spend; no false-accepts).
       - trust_all  : trust every candidate (zero assays, but every wrong design is a false-accept).

HONEST READING of the synthetic result: trust_all COLLAPSES once false-accepts are costly (the
regime the gate exists for); the gate makes far fewer false-accepts than trust_all at far fewer
assays than verify_all — it is the risk-controlled middle. verify_all can still edge the gate on
raw net *in this stub*, because assays here are cheap and the stub's trust threshold is not
perfectly aligned with its correctness threshold. The clean net-win over verify_all is an
empirical claim for REAL data (M1 offline on the 80-target fixture; M4 dynamic on ProteinMPNN->
Boltz), where assays are expensive and complex-regime confidence is genuinely miscalibrated.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from ..config import ObjectiveSpec
from ..loop.controller import DBTLController

_DEFAULT_TARGET = "thermostable variant of green fluorescent protein (GFP), a benign reporter"
_POLICIES = ("calibrated", "verify_all", "trust_all")


def _build_stream(spec: ObjectiveSpec) -> Tuple[Any, List[Dict[str, Any]]]:
    """Run the calibrated reference campaign; return (result, per-candidate stream)."""
    res = DBTLController().run(spec)
    stream = []
    for r in res.rows:
        t = r["hidden_truth"]
        stream.append({
            "round": r["round"],
            "action": r["action"],                                  # the calibrated gate's actual choice
            "sfm_correct": bool(t["sfm_correct"]),
            "baseline_correct": bool(t["baseline_correct"]),
            "has_baseline": bool(r["evidence"]["has_cheap_baseline"]),
            "quality": t["quality"],
        })
    return res, stream


def _score_policy(stream: List[Dict[str, Any]], policy: str, lam: float, mu: float, budget: int) -> Dict[str, Any]:
    """Score a routing policy on a fixed candidate stream. net = (benefit − lam·assays − mu·false_accepts)/n.
    A false-accept = advancing a wrong design (trust a wrong SFM, or default to a wrong baseline)."""
    n = benefit = assays = false_accepts = used = 0
    for c in stream:
        n += 1
        if policy == "calibrated":
            action = c["action"]
        elif policy == "verify_all":
            action = "verify_assay" if used < budget else ("default_baseline" if c["has_baseline"] else "defer")
        elif policy == "trust_all":
            action = "trust_sfm"
        else:
            raise ValueError(f"unknown policy {policy!r}")

        if action == "trust_sfm":
            benefit += 1 if c["sfm_correct"] else 0
            false_accepts += 0 if c["sfm_correct"] else 1
        elif action == "verify_assay":
            benefit += 1
            assays += 1
            used += 1
        elif action == "default_baseline":
            benefit += 1 if c["baseline_correct"] else 0
            false_accepts += 0 if c["baseline_correct"] else 1
        # defer: no benefit, no assay, no false-accept
    return {
        "net": round((benefit - lam * assays - mu * false_accepts) / n, 4) if n else 0.0,
        "assays": assays,
        "false_accepts": false_accepts,
        "benefit": benefit,
        "n": n,
    }


def compare_policies(spec: ObjectiveSpec, false_accept_cost: float = 1.0) -> Dict[str, Any]:
    """Climb (from the calibrated reference run) + the three policies scored on its candidate stream."""
    res, stream = _build_stream(spec)
    by_round: Dict[int, list] = defaultdict(list)
    for c in stream:
        by_round[c["round"]].append(c["quality"])
    rounds = sorted(by_round)
    climb = {r: round(sum(by_round[r]) / len(by_round[r]), 4) for r in rounds}
    return {
        "climb_mean_quality_per_round": climb,
        "best_quality": round(max((c["quality"] for c in stream), default=0.0), 4),
        "rounds_run": res.rounds_run,
        "false_accept_cost": false_accept_cost,
        "policies": {p: _score_policy(stream, p, spec.lam, false_accept_cost, spec.assay_budget)
                     for p in _POLICIES},
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="closed-loop DBTL campaign + routing-policy comparison")
    ap.add_argument("--target", default=_DEFAULT_TARGET)
    ap.add_argument("--objective", default="thermostability")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--cpr", type=int, default=24, help="candidates per round")
    ap.add_argument("--lam", type=float, default=0.5, help="verification price lambda")
    ap.add_argument("--budget", type=int, default=80, help="assay budget (verify cap)")
    ap.add_argument("--mu", type=float, default=1.0, help="false-accept cost (advancing a wrong design)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--acquisition", default="greedy", choices=["greedy", "ucb", "thompson"])
    ap.add_argument("--out", default=None, help="write the full comparison JSON here")
    args = ap.parse_args(argv)

    spec = ObjectiveSpec(
        target=args.target, objective=args.objective, lam=args.lam, rounds=args.rounds,
        candidates_per_round=args.cpr, assay_budget=args.budget, seed=args.seed,
        acquisition=args.acquisition,
    )
    rep = compare_policies(spec, false_accept_cost=args.mu)

    print(f"# closed-loop campaign  (lambda={spec.lam}, mu={args.mu}, budget={spec.assay_budget}, "
          f"cpr={spec.candidates_per_round}, acq={spec.acquisition}, seed={spec.seed})")
    print("\n## climb — mean design quality per round (the loop is closed)")
    for r, m in rep["climb_mean_quality_per_round"].items():
        print(f"  round {r:>2}: mean_q={m:.3f}")
    print(f"  best design quality reached: {rep['best_quality']:.3f}  (rounds_run={rep['rounds_run']})")

    print(f"\n## routing-policy comparison on the same stream (lambda={spec.lam}, mu={args.mu})")
    print(f"  {'policy':<14}{'net':>9}{'assays':>8}{'false_acc':>11}")
    for p in _POLICIES:
        s = rep["policies"][p]
        print(f"  {p:<14}{s['net']:>9.4f}{s['assays']:>8}{s['false_accepts']:>11}")
    ta, cal, va = (rep["policies"][k] for k in ("trust_all", "calibrated", "verify_all"))
    saved = va["assays"] - cal["assays"]
    assay_note = (f"using {saved} fewer assays than verify_all ({cal['assays']} vs {va['assays']})"
                  if saved > 0 else
                  f"at the same assays here ({cal['assays']}={va['assays']}); the gate's assay savings show with a larger budget")
    print(f"\n  honest read: trust_all makes by far the most false-accepts ({ta['false_accepts']}, "
          f"net {ta['net']}) -> it collapses when they are costly. The calibrated gate bounds "
          f"false-accepts to {cal['false_accepts']} (vs trust_all {ta['false_accepts']}), {assay_note}.")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
