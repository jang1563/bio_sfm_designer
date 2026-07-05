"""Empirical scale projection for the M6c alpha-tightening batch.

The analytic alpha plan estimates how many more records are needed if the same
threshold keeps roughly the same calibration coverage/error. This helper asks a
complementary planning question: if the recommended balanced temperature batch
looked like the current empirical strata, how often would alpha certify across
split/sample seeds?
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import statistics
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_seed_sensitivity import _parse_seeds
from .complex_design_regime_audit import infer_design_temperature
from .complex_gate_sweep import _default_n_cal, load_merged_records
from .conformal_complex_gate import _DEFAULT_FIXTURE, run_rows as run_gate_rows


_CLAIM_SCOPE = "single_target_bootstrap_projection"
_EVIDENCE_LEVEL = "planning_diagnostic"
_CERTIFICATION_SCOPE = "none_projection_only"
_PROJECTION_METHOD = "bootstrap_resample_current_temperature_strata"
_PROJECTION_LIMITATIONS = [
    "Rows are resampled from current empirical temperature strata; no new folds have been run.",
    "Projected split/sample certificates do not certify the target alpha on real synchronized records.",
    "Only complex_alpha_decision.py can stop W1 after it sees actual post-scale records and strict QC.",
]


def _parse_floats(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _allocation(n_new: int, temperatures: Iterable[float]) -> Dict[str, int]:
    temps = [float(t) for t in temperatures]
    if n_new < 0:
        raise ValueError("n_new must be nonnegative")
    if not temps:
        raise ValueError("at least one temperature is required")
    base, rem = divmod(int(n_new), len(temps))
    return {str(t): base + (1 if i < rem else 0) for i, t in enumerate(temps)}


def _group_by_temperature(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        temp = infer_design_temperature(row)
        if temp is None:
            continue
        groups.setdefault(str(float(temp)), []).append(row)
    return groups


def _augment_rows(rows: List[Dict[str, Any]], *, allocation: Dict[str, int],
                  seed: int) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    groups = _group_by_temperature(rows)
    rng = random.Random(seed)
    augmented = list(rows)
    added_summary: Dict[str, Dict[str, int]] = {}
    for temp, count in allocation.items():
        source = groups.get(temp)
        if not source:
            raise ValueError(f"cannot sample temperature {temp}: no current records in that stratum")
        success = 0
        for i in range(count):
            rec = copy.deepcopy(rng.choice(source))
            source_target_id = rec.get("target_id")
            rec["target_id"] = f"bootstrap_t{temp}_seed{seed}_{i}_{rec['target_id']}"
            rec["bootstrap_source_target_id"] = source_target_id
            rec["bootstrap_projection"] = True
            augmented.append(rec)
            if float(rec["lrmsd"]) < float(rec.get("lrmsd_threshold", 4.0)):
                success += 1
        added_summary[temp] = {
            "n": count,
            "success": success,
            "failure": count - success,
        }
    return augmented, added_summary


def _quantiles(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "median": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
    }


def run_projection(records: Iterable[str], *, target_alpha: float = 0.2,
                   n_new: int = 300,
                   temperatures: Iterable[float] = (0.3, 0.5, 0.7),
                   seeds: Iterable[int] = range(20),
                   delta: float = 0.1,
                   threshold: float = 4.0,
                   n_cal: Optional[int] = None,
                   plausible_fraction: float = 0.7) -> Dict[str, Any]:
    record_paths = list(records)
    rows = load_merged_records(record_paths)
    seed_list = list(seeds)
    if not seed_list:
        raise ValueError("at least one seed is required")
    allocation = _allocation(n_new, temperatures)

    current_certified = 0
    projected_certified = 0
    projected_taus: List[float] = []
    projected_trusted: List[float] = []
    projected_false_accept_rates: List[float] = []
    per_seed = []
    for seed in seed_list:
        current_n_cal = _default_n_cal(len(rows)) if n_cal is None else n_cal
        current = run_gate_rows(
            rows,
            alpha=target_alpha,
            delta=delta,
            threshold=threshold,
            n_cal=current_n_cal,
            seed=int(seed),
        )
        current_is_certified = current["tau"] is not None
        if current_is_certified:
            current_certified += 1

        augmented, added_summary = _augment_rows(rows, allocation=allocation, seed=int(seed))
        projected_n_cal = _default_n_cal(len(augmented)) if n_cal is None else n_cal
        projected = run_gate_rows(
            augmented,
            alpha=target_alpha,
            delta=delta,
            threshold=threshold,
            n_cal=projected_n_cal,
            seed=int(seed),
        )
        projected_is_certified = projected["tau"] is not None
        if projected_is_certified:
            projected_certified += 1
        if projected["tau"] is not None:
            projected_taus.append(float(projected["tau"]))
        projected_trusted.append(float(projected["conformal"]["trusted"]))
        far = projected["conformal"]["false_accept_rate"]
        if far is not None:
            projected_false_accept_rates.append(float(far))
        per_seed.append({
            "seed": int(seed),
            "target_alpha": target_alpha,
            "current_n_records": len(rows),
            "current_n_cal": current["n_cal"],
            "current_certified": current_is_certified,
            "current_tau": current["tau"],
            "projected_n_records": len(augmented),
            "projected_n_cal": projected["n_cal"],
            "projected_n_test": projected["n_test"],
            "projected_certified": projected_is_certified,
            "projected_tau": projected["tau"],
            "projected_trusted": projected["conformal"]["trusted"],
            "projected_false_accept_rate": projected["conformal"]["false_accept_rate"],
            "projected_trust_all_false_accept_rate": projected["trust_all"]["false_accept_rate"],
            "added_summary_by_temperature": added_summary,
        })

    n = len(seed_list)
    projected_fraction = projected_certified / n
    if projected_certified == n:
        decision = "planned_batch_strongly_supports_target"
        message = (
            f"planned +{n_new} batch would certify alpha={target_alpha} for all {n} tested seeds "
            "under bootstrap projection"
        )
    elif projected_fraction >= plausible_fraction:
        decision = "planned_batch_plausible"
        message = (
            f"planned +{n_new} batch would certify alpha={target_alpha} for "
            f"{projected_certified}/{n} tested seeds under bootstrap projection"
        )
    elif projected_certified > 0:
        decision = "planned_batch_split_sensitive"
        message = (
            f"planned +{n_new} batch sometimes would certify alpha={target_alpha} "
            f"under bootstrap projection ({projected_certified}/{n} tested seeds)"
        )
    else:
        decision = "planned_batch_insufficient"
        message = (
            f"planned +{n_new} batch would certify alpha={target_alpha} for 0/{n} tested seeds "
            "under bootstrap projection"
        )

    return {
        "ok": True,
        "decision": decision,
        "message": message,
        "claim_scope": _CLAIM_SCOPE,
        "evidence_level": _EVIDENCE_LEVEL,
        "certifies_target_alpha": False,
        "certification_scope": _CERTIFICATION_SCOPE,
        "projection_method": _PROJECTION_METHOD,
        "projection_limitations": list(_PROJECTION_LIMITATIONS),
        "records": record_paths,
        "target_alpha": target_alpha,
        "delta": delta,
        "threshold": threshold,
        "n_current_records": len(rows),
        "n_new": n_new,
        "n_projected_records": len(rows) + n_new,
        "temperatures": [float(t) for t in temperatures],
        "new_records_by_temperature": allocation,
        "seeds": seed_list,
        "n_seeds": n,
        "current_certified_count": current_certified,
        "current_certified_fraction": current_certified / n,
        "projected_certified_count": projected_certified,
        "projected_certified_fraction": projected_fraction,
        "plausible_fraction": plausible_fraction,
        "projected_tau": _quantiles(projected_taus),
        "projected_trusted": _quantiles(projected_trusted),
        "projected_false_accept_rate": _quantiles(projected_false_accept_rates),
        "per_seed": per_seed,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="empirical projection for the next M6c scale batch")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--n-new", type=int, default=300)
    ap.add_argument("--temperatures", default="0.3,0.5,0.7")
    ap.add_argument("--seeds", default="0:20",
                    help="comma-separated seeds or a Python-style start:stop[:step] range")
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--ncal", type=int, default=None)
    ap.add_argument("--plausible-fraction", type=float, default=0.7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_projection(
        args.records,
        target_alpha=args.target_alpha,
        n_new=args.n_new,
        temperatures=_parse_floats(args.temperatures),
        seeds=_parse_seeds(args.seeds),
        delta=args.delta,
        threshold=args.threshold,
        n_cal=args.ncal,
        plausible_fraction=args.plausible_fraction,
    )
    print(
        "# complex scale projection  "
        f"decision={rep['decision']} target_alpha={rep['target_alpha']} n_new={rep['n_new']}"
    )
    print(f"  {rep['message']}")
    print(
        f"  current certified {rep['current_certified_count']}/{rep['n_seeds']} seeds; "
        f"projected certified {rep['projected_certified_count']}/{rep['n_seeds']} seeds"
    )
    tau = rep["projected_tau"]
    trusted = rep["projected_trusted"]
    far = rep["projected_false_accept_rate"]
    print(
        "  projected tau: "
        f"min={_fmt(tau['min'])} median={_fmt(tau['median'])} max={_fmt(tau['max'])}"
    )
    print(
        "  projected trusted: "
        f"min={_fmt(trusted['min'])} median={_fmt(trusted['median'])} max={_fmt(trusted['max'])}"
    )
    print(
        "  projected false-accept: "
        f"min={_fmt(far['min'])} median={_fmt(far['median'])} max={_fmt(far['max'])}"
    )
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
