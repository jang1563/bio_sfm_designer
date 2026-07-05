"""Seed-sensitivity audit for the complex conformal alpha frontier.

The default M6c gate result uses one deterministic calibration/test split. This
helper asks a science-facing robustness question: does the alpha frontier change
materially when the split seed changes?
"""

from __future__ import annotations

import argparse
import json
import statistics
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_plan import run_plan
from .complex_gate_sweep import run_sweep
from .conformal_complex_gate import _DEFAULT_FIXTURE


def _parse_floats(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _parse_seeds(text: str) -> List[int]:
    if ":" in text:
        parts = [p.strip() for p in text.split(":")]
        if len(parts) not in {2, 3}:
            raise ValueError("--seeds range must be start:stop or start:stop:step")
        start = int(parts[0])
        stop = int(parts[1])
        step = int(parts[2]) if len(parts) == 3 else 1
        if step == 0:
            raise ValueError("--seeds step must be nonzero")
        return list(range(start, stop, step))
    return [int(x) for x in text.split(",") if x.strip()]


def _row_for_alpha(rows: List[Dict[str, Any]], alpha: float) -> Optional[Dict[str, Any]]:
    for row in rows:
        if abs(float(row["alpha"]) - float(alpha)) < 1e-12:
            return row
    return None


def _quantiles(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "median": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
    }


def run_sensitivity(records: Iterable[str], *, target_alpha: float = 0.2,
                    baseline_alpha: float = 0.3,
                    alphas: Iterable[float] = (0.3, 0.2),
                    seeds: Iterable[int] = range(20),
                    n_cal: Optional[int] = None,
                    delta: float = 0.1,
                    threshold: float = 4.0) -> Dict[str, Any]:
    records = list(records)
    seed_list = list(seeds)
    if not seed_list:
        raise ValueError("at least one seed is required")
    alpha_list = list(dict.fromkeys([float(a) for a in list(alphas) + [baseline_alpha, target_alpha]]))

    per_seed = []
    target_additional = []
    target_certified = 0
    baseline_certified = 0
    for seed in seed_list:
        sweep = run_sweep(
            records,
            alphas=alpha_list,
            n_cal=n_cal,
            delta=delta,
            threshold=threshold,
            seed=int(seed),
        )
        plan = run_plan(
            records,
            alphas=[target_alpha],
            n_cal=n_cal,
            delta=delta,
            threshold=threshold,
            seed=int(seed),
        )
        sweep_by_alpha = {float(row["alpha"]): row for row in sweep["alphas"]}
        target_row = _row_for_alpha(sweep["alphas"], target_alpha)
        baseline_row = _row_for_alpha(sweep["alphas"], baseline_alpha)
        target_plan = plan["plans"][0]
        if target_row and target_row.get("certified"):
            target_certified += 1
        if baseline_row and baseline_row.get("certified"):
            baseline_certified += 1
        additional = target_plan.get("estimated_additional_records")
        if isinstance(additional, (int, float)):
            target_additional.append(float(additional))
        per_seed.append({
            "seed": int(seed),
            "n_records": sweep["n_records"],
            "n_cal": sweep["n_cal"],
            "n_test": sweep["n_test"],
            "target_alpha": target_alpha,
            "target_certified": bool(target_row and target_row.get("certified")),
            "target_tau": target_row.get("tau") if target_row else None,
            "baseline_alpha": baseline_alpha,
            "baseline_certified": bool(baseline_row and baseline_row.get("certified")),
            "baseline_tau": baseline_row.get("tau") if baseline_row else None,
            "target_estimated_additional_records": additional,
            "target_current_accepted": target_plan.get("current_accepted"),
            "target_current_false_accepts": target_plan.get("current_false_accepts"),
            "target_current_empirical_false_accept_rate": target_plan.get("current_empirical_false_accept_rate"),
            "target_current_hoeffding_ucb": target_plan.get("current_hoeffding_ucb"),
            "sweep_by_alpha": sweep_by_alpha,
        })

    n = len(seed_list)
    if target_certified == n:
        decision = "target_alpha_robustly_certified"
        message = f"target alpha={target_alpha} certified for all {n} tested split seeds"
    elif target_certified > 0:
        decision = "target_alpha_split_sensitive"
        message = f"target alpha={target_alpha} certified for {target_certified}/{n} tested split seeds"
    else:
        decision = "continue_scale_robust"
        message = f"target alpha={target_alpha} certified for 0/{n} tested split seeds; scale-up remains justified"

    additional_quantiles = _quantiles(target_additional)
    return {
        "ok": True,
        "decision": decision,
        "message": message,
        "records": records,
        "target_alpha": target_alpha,
        "baseline_alpha": baseline_alpha,
        "alphas": alpha_list,
        "delta": delta,
        "threshold": threshold,
        "seeds": seed_list,
        "n_seeds": n,
        "target_certified_count": target_certified,
        "target_certified_fraction": target_certified / n,
        "baseline_certified_count": baseline_certified,
        "baseline_certified_fraction": baseline_certified / n,
        "target_estimated_additional_records": additional_quantiles,
        "per_seed": per_seed,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="audit split-seed sensitivity of the complex alpha frontier")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--baseline-alpha", type=float, default=0.3)
    ap.add_argument("--alphas", default="0.3,0.2")
    ap.add_argument("--seeds", default="0:20",
                    help="comma-separated seeds or a Python-style start:stop[:step] range")
    ap.add_argument("--ncal", type=int, default=None)
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_sensitivity(
        args.records,
        target_alpha=args.target_alpha,
        baseline_alpha=args.baseline_alpha,
        alphas=_parse_floats(args.alphas),
        seeds=_parse_seeds(args.seeds),
        n_cal=args.ncal,
        delta=args.delta,
        threshold=args.threshold,
    )
    print(
        "# complex alpha seed sensitivity  "
        f"decision={rep['decision']} target_alpha={rep['target_alpha']}"
    )
    print(f"  {rep['message']}")
    print(
        f"  baseline alpha={rep['baseline_alpha']} certified "
        f"{rep['baseline_certified_count']}/{rep['n_seeds']} seeds"
    )
    addl = rep["target_estimated_additional_records"]
    print(
        "  estimated additional records for target alpha: "
        f"min={_fmt(addl['min'])} median={_fmt(addl['median'])} max={_fmt(addl['max'])}"
    )
    print("  seed  base_cert  target_cert  target_addl  accepted  false  ucb")
    for row in rep["per_seed"]:
        print(
            f"  {row['seed']:4d}  {str(row['baseline_certified']):>9}  "
            f"{str(row['target_certified']):>11}  "
            f"{_fmt(row['target_estimated_additional_records']):>11}  "
            f"{_fmt(row['target_current_accepted']):>8}  "
            f"{_fmt(row['target_current_false_accepts']):>5}  "
            f"{_fmt(row['target_current_hoeffding_ucb']):>5}"
        )
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
