"""Sample-size planner for tightening the M6c conformal alpha frontier.

RCPS certifies a threshold tau using the calibration split's accepted set:

    empirical_false_accept + sqrt(log(1/delta) / (2 * n_accepted)) <= alpha

This helper converts the current complex fixture into an explicit scale-up plan.
It is not a guarantee about future samples; it says how many accepted calibration
examples would be needed if the same threshold kept roughly the same empirical
false-accept rate and coverage.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from typing import Any, Dict, Iterable, List, Optional

from bio_sfm_trust import confidence_to_risk, loo_calibrated_risks

from .complex_gate_sweep import _default_n_cal, load_merged_records
from .complex_label_threshold import require_label_threshold
from .conformal_complex_gate import _DEFAULT_FIXTURE

_DEFAULT_ALPHAS = (0.3, 0.2, 0.1)
_REGIME = "complex"


def _parse_alphas(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _raw_risk(rec: dict) -> float:
    return confidence_to_risk({"regime": _REGIME, "mean_plddt": rec["mean_plddt"],
                               "iptm": rec.get("iptm"), "pae_interaction": rec.get("pae_interaction")})


def _wrong(rec: dict, threshold: float) -> int:
    return 0 if rec["lrmsd"] < threshold else 1


def _candidate_rows(risks: List[float], wrong: List[int], delta: float) -> List[Dict[str, Any]]:
    slack = math.log(1.0 / delta)
    rows = []
    for tau in sorted(set(risks)):
        accepted = [w for r, w in zip(risks, wrong) if r <= tau]
        n = len(accepted)
        false_accepts = sum(accepted)
        empirical = false_accepts / n
        ucb = empirical + math.sqrt(slack / (2 * n))
        rows.append({
            "tau": tau,
            "accepted": n,
            "false_accepts": false_accepts,
            "empirical_false_accept_rate": empirical,
            "hoeffding_ucb": ucb,
        })
    return rows


def _required_accepts(empirical: float, alpha: float, delta: float) -> Optional[int]:
    if empirical >= alpha:
        return None
    return int(math.ceil(math.log(1.0 / delta) / (2 * (alpha - empirical) ** 2)))


def _plan_for_alpha(candidates: List[Dict[str, Any]], alpha: float, delta: float,
                    n_records: int, n_cal: int) -> Dict[str, Any]:
    certified = [c for c in candidates if c["hoeffding_ucb"] <= alpha]
    if certified:
        chosen = max(certified, key=lambda c: c["tau"])
    else:
        feasible = []
        for c in candidates:
            req_accept = _required_accepts(c["empirical_false_accept_rate"], alpha, delta)
            if req_accept is None:
                continue
            coverage = c["accepted"] / n_cal
            req_cal = int(math.ceil(req_accept / coverage))
            req_total = int(math.ceil(req_cal / (n_cal / n_records)))
            feasible.append((req_total, req_cal, req_accept, c))
        if not feasible:
            return {
                "alpha": alpha,
                "certified": False,
                "reason": "no current threshold has empirical false-accept below alpha",
                "tau": None,
                "current_accepted": 0,
                "current_false_accepts": None,
                "current_empirical_false_accept_rate": None,
                "current_hoeffding_ucb": None,
                "required_accepted_for_same_rate": None,
                "estimated_required_calibration_records": None,
                "estimated_required_total_records": None,
                "estimated_additional_records": None,
            }
        req_total, req_cal, req_accept, chosen = min(feasible, key=lambda x: x[0])

    req_accept = _required_accepts(chosen["empirical_false_accept_rate"], alpha, delta)
    coverage = chosen["accepted"] / n_cal
    if req_accept is None:
        req_cal = req_total = addl = None
    else:
        req_cal = int(math.ceil(req_accept / coverage))
        req_total = int(math.ceil(req_cal / (n_cal / n_records)))
        addl = max(0, req_total - n_records)
    return {
        "alpha": alpha,
        "certified": bool(certified),
        "tau": chosen["tau"],
        "current_accepted": chosen["accepted"],
        "current_false_accepts": chosen["false_accepts"],
        "current_empirical_false_accept_rate": chosen["empirical_false_accept_rate"],
        "current_hoeffding_ucb": chosen["hoeffding_ucb"],
        "required_accepted_for_same_rate": req_accept,
        "estimated_required_calibration_records": req_cal,
        "estimated_required_total_records": req_total,
        "estimated_additional_records": addl,
    }


def run_plan(paths: Iterable[str], alphas: Iterable[float] = _DEFAULT_ALPHAS,
             *, n_cal: Optional[int] = None, delta: float = 0.1,
             threshold: float = 4.0, seed: int = 0) -> Dict[str, Any]:
    rows = load_merged_records(paths)
    threshold_audit = require_label_threshold(rows, threshold=threshold)
    n_cal_eff = _default_n_cal(len(rows)) if n_cal is None else n_cal
    if n_cal_eff >= len(rows):
        raise ValueError(f"n_cal={n_cal_eff} leaves no held-out records (n={len(rows)})")
    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)
    cal = [rows[i] for i in idx[:n_cal_eff]]
    raw = [_raw_risk(r) for r in cal]
    wrong = [_wrong(r, threshold) for r in cal]
    risks = loo_calibrated_risks(raw, wrong)
    candidates = _candidate_rows(risks, wrong, delta)
    return {
        "n_records": len(rows),
        "n_cal": n_cal_eff,
        "n_test": len(rows) - n_cal_eff,
        "calibration_wrong": sum(wrong),
        "delta": delta,
        "threshold": threshold,
        "label_threshold_audit": threshold_audit,
        "seed": seed,
        "plans": [_plan_for_alpha(candidates, float(a), delta, len(rows), n_cal_eff) for a in alphas],
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="estimate scale needed to tighten the complex RCPS alpha frontier")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE],
                    help="one or more complex records JSONL files")
    ap.add_argument("--alphas", default="0.3,0.2,0.1")
    ap.add_argument("--ncal", type=int, default=None,
                    help="calibration split size; default=floor(2/3*n), preserving 128 for n=192")
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    rep = run_plan(args.records, _parse_alphas(args.alphas), n_cal=args.ncal,
                   delta=args.delta, threshold=args.threshold, seed=args.seed)
    print(f"# complex alpha scale plan  (n={rep['n_records']}, n_cal={rep['n_cal']}, "
          f"delta={rep['delta']})")
    print(f"  {'alpha':>6}  {'cert':>5}  {'tau':>7}  {'acc':>7}  {'rhat':>7}  "
          f"{'ucb':>7}  {'req_acc':>7}  {'est_total':>9}  {'addl':>7}")
    for row in rep["plans"]:
        print(f"  {row['alpha']:6.2f}  {str(row['certified']):>5}  {_fmt(row['tau']):>7}  "
              f"{row['current_accepted']:>7}  {_fmt(row['current_empirical_false_accept_rate']):>7}  "
              f"{_fmt(row['current_hoeffding_ucb']):>7}  "
              f"{_fmt(row['required_accepted_for_same_rate']):>7}  "
              f"{_fmt(row['estimated_required_total_records']):>9}  "
              f"{_fmt(row['estimated_additional_records']):>7}")
    print("  note: estimates assume the same tau keeps similar calibration coverage and empirical error.")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
