"""Stop/continue decision for the M6c alpha-tightening loop.

After each external HPC scale-up batch, this helper turns the synchronized QC/sweep/plan
outputs into one explicit decision:

- stop_certified: the target alpha is certified now
- continue_scale: not certified, but the current empirical rate suggests more records may certify
- no_feasible_threshold: no current threshold has empirical error below the target alpha
- qc_failed: records are not safe to analyze

When more scale is justified, the output also includes a `next_batch` block that
rounds the additional-record estimate into per-temperature ProteinMPNN `NUM_SEQ`
settings for the next external HPC run.
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_plan import run_plan
from .complex_gate_sweep import load_merged_records, run_sweep
from .complex_label_threshold import label_threshold_audit
from .complex_records_qc import run_qc
from .conformal_complex_gate import _DEFAULT_FIXTURE


def _parse_alphas(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _row_for_alpha(rows: List[Dict[str, Any]], alpha: float) -> Optional[Dict[str, Any]]:
    for row in rows:
        if abs(float(row["alpha"]) - float(alpha)) < 1e-12:
            return row
    return None


def _ceil_to_multiple(value: int, multiple: int) -> int:
    if multiple <= 0:
        raise ValueError("batch_round_to must be positive")
    return int(math.ceil(value / multiple) * multiple)


def _build_next_batch(decision: str, additional: Optional[int], *,
                      target_alpha: float, temperatures: Iterable[float],
                      batch_round_to: int, batch_safety_factor: float) -> Dict[str, Any]:
    temps = [float(t) for t in temperatures]
    if not temps:
        raise ValueError("at least one temperature is required for next-batch planning")
    if batch_safety_factor < 1.0:
        raise ValueError("batch_safety_factor must be >= 1.0")
    if decision == "qc_failed":
        return {
            "action": "fix_qc",
            "target_alpha": target_alpha,
            "recommended_total_candidates": 0,
            "message": "Fix QC failures before launching more model work.",
        }
    if decision == "label_threshold_mismatch":
        return {
            "action": "fix_label_threshold",
            "target_alpha": target_alpha,
            "recommended_total_candidates": 0,
            "message": "Regenerate or re-run records under one L-RMSD success threshold before alpha claims.",
        }
    if decision == "stop_certified":
        return {
            "action": "none",
            "target_alpha": target_alpha,
            "recommended_total_candidates": 0,
            "message": "Target alpha is certified; broaden scope rather than scaling this same target.",
        }
    if additional is None:
        return {
            "action": "change_axis_or_revise_metric",
            "target_alpha": target_alpha,
            "recommended_total_candidates": None,
            "message": "No current threshold is empirically below alpha; add targets/predictors or revisit the metric.",
        }

    target_records = int(math.ceil(float(additional) * batch_safety_factor))
    per_temp = _ceil_to_multiple(int(math.ceil(target_records / len(temps))), batch_round_to)
    total = per_temp * len(temps)
    return {
        "action": "run_scale_batch",
        "target_alpha": target_alpha,
        "estimated_additional_records": additional,
        "batch_safety_factor": batch_safety_factor,
        "batch_round_to": batch_round_to,
        "temperatures": temps,
        "num_seq_per_temperature": per_temp,
        "recommended_total_candidates": total,
        "message": (
            f"Run NUM_SEQ={per_temp} for each listed temperature "
            f"({total} total candidates) before rerunning the posthoc bundle."
        ),
    }


def run_decision(records: Iterable[str], *, target_alpha: float = 0.2,
                 alphas: Iterable[float] = (0.3, 0.2, 0.1),
                 n_cal: Optional[int] = None, delta: float = 0.1,
                 threshold: float = 4.0, seed: int = 0,
                 temperatures: Iterable[float] = (0.3, 0.5, 0.7),
                 batch_round_to: int = 20,
                 batch_safety_factor: float = 1.0,
                 require_complex_target_id: bool = False,
                 require_provenance: bool = False,
                 require_chain_ids: bool = False) -> Dict[str, Any]:
    records = list(records)
    alpha_list = list(dict.fromkeys([float(a) for a in list(alphas) + [target_alpha]]))
    qc = run_qc(records, require_complex_target_id=require_complex_target_id,
                require_provenance=require_provenance,
                require_chain_ids=require_chain_ids)
    if not qc["ok"]:
        return {
            "ok": False,
            "decision": "qc_failed",
            "records": records,
            "target_alpha": target_alpha,
            "qc": qc,
            "next_batch": _build_next_batch(
                "qc_failed", None,
                target_alpha=target_alpha,
                temperatures=temperatures,
                batch_round_to=batch_round_to,
                batch_safety_factor=batch_safety_factor,
            ),
            "message": "QC failed; do not run alpha claims until records are fixed.",
        }

    threshold_audit = label_threshold_audit(load_merged_records(records), threshold=threshold)
    if not threshold_audit["ok"]:
        return {
            "ok": False,
            "decision": "label_threshold_mismatch",
            "records": records,
            "target_alpha": target_alpha,
            "qc": qc,
            "label_threshold_audit": threshold_audit,
            "next_batch": _build_next_batch(
                "label_threshold_mismatch", None,
                target_alpha=target_alpha,
                temperatures=temperatures,
                batch_round_to=batch_round_to,
                batch_safety_factor=batch_safety_factor,
            ),
            "message": "Record lrmsd_threshold metadata must match the alpha-analysis threshold.",
        }

    sweep = run_sweep(records, alphas=alpha_list, n_cal=n_cal, delta=delta,
                      threshold=threshold, seed=seed)
    plan = run_plan(records, alphas=alpha_list, n_cal=n_cal, delta=delta,
                    threshold=threshold, seed=seed)
    sweep_row = _row_for_alpha(sweep["alphas"], target_alpha)
    plan_row = _row_for_alpha(plan["plans"], target_alpha)
    certified = bool(sweep_row and sweep_row["certified"])
    certified_alphas = [row["alpha"] for row in sweep["alphas"] if row["certified"]]
    if certified:
        decision = "stop_certified"
        message = f"target alpha={target_alpha} is certified; stop scaling this target unless broadening scope."
        additional = 0
    elif (
        plan_row
        and plan_row.get("estimated_additional_records") is not None
        and plan_row["estimated_additional_records"] > 0
    ):
        decision = "continue_scale"
        additional = plan_row["estimated_additional_records"]
        message = f"target alpha={target_alpha} is not certified; estimate about {additional} more records."
    else:
        decision = "no_feasible_threshold"
        additional = None
        message = f"target alpha={target_alpha} is not certified and no current threshold is empirically below alpha."
    next_batch = _build_next_batch(
        decision, additional,
        target_alpha=target_alpha,
        temperatures=temperatures,
        batch_round_to=batch_round_to,
        batch_safety_factor=batch_safety_factor,
    )
    return {
        "ok": True,
        "decision": decision,
        "records": records,
        "qc": qc,
        "target_alpha": target_alpha,
        "n_records": sweep["n_records"],
        "n_cal": sweep["n_cal"],
        "n_test": sweep["n_test"],
        "delta": delta,
        "threshold": threshold,
        "label_threshold_audit": threshold_audit,
        "seed": seed,
        "certified_alphas": certified_alphas,
        "target_sweep": sweep_row,
        "target_plan": plan_row,
        "estimated_additional_records": additional,
        "next_batch": next_batch,
        "message": message,
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="decide whether the M6c alpha target is certified after a batch")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--alphas", default="0.3,0.2,0.1")
    ap.add_argument("--ncal", type=int, default=None,
                    help="calibration split size; default=floor(2/3*n)")
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperatures", default="0.3,0.5,0.7",
                    help="comma-separated ProteinMPNN temperatures for next-batch NUM_SEQ planning")
    ap.add_argument("--batch-round-to", type=int, default=20,
                    help="round per-temperature NUM_SEQ up to this multiple")
    ap.add_argument("--batch-safety-factor", type=float, default=1.0,
                    help="multiply estimated additional records before rounding; must be >=1")
    ap.add_argument("--require-complex-target-id", action="store_true",
                    help="strict QC: require complex_target_id before alpha claims")
    ap.add_argument("--require-provenance", action="store_true",
                    help="strict QC: require predictor_id, signal_source, and label_source")
    ap.add_argument("--require-chain-ids", action="store_true",
                    help="strict QC: require target_chain and binder_chain")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_decision(args.records, target_alpha=args.target_alpha,
                       alphas=_parse_alphas(args.alphas), n_cal=args.ncal,
                       delta=args.delta, threshold=args.threshold, seed=args.seed,
                       temperatures=_parse_alphas(args.temperatures),
                       batch_round_to=args.batch_round_to,
                       batch_safety_factor=args.batch_safety_factor,
                       require_complex_target_id=args.require_complex_target_id,
                       require_provenance=args.require_provenance,
                       require_chain_ids=args.require_chain_ids)
    print(f"# complex alpha decision  decision={rep['decision']} target_alpha={rep['target_alpha']}")
    print(f"  {rep['message']}")
    if rep.get("ok"):
        print(f"  n={rep['n_records']} n_cal={rep['n_cal']} certified_alphas={rep['certified_alphas']}")
    else:
        print(f"  qc_failures={rep['qc']['n_failures']}")
    nb = rep.get("next_batch", {})
    if nb:
        print(f"  next_batch: action={nb.get('action')} total={nb.get('recommended_total_candidates')}")
        if nb.get("action") == "run_scale_batch":
            temps = ",".join(str(t) for t in nb["temperatures"])
            print(f"    temperatures={temps} NUM_SEQ={nb['num_seq_per_temperature']} each")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
