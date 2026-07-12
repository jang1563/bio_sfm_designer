"""M6c scale-up helper: merge complex records and sweep RCPS alpha.

After external HPC produces one or more `records_boltz_complex*.jsonl` files, this utility deduplicates
records by `target_id`, then reruns the exact conformal complex-gate analysis for alpha values such
as 0.3, 0.2, and 0.1. It is intentionally CPU-only and fixture-compatible: no Boltz/GPU required.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Iterable, List, Optional

from .conformal_complex_gate import _DEFAULT_FIXTURE, run_rows
from .complex_label_threshold import require_label_threshold


def _stable_record_key(rec: dict) -> str:
    return json.dumps(rec, sort_keys=True, separators=(",", ":"))


def load_merged_records(paths: Iterable[str]) -> List[dict]:
    """Load JSONL records, deduplicating identical target_id rows and rejecting conflicts."""
    by_id: Dict[str, dict] = {}
    fingerprints: Dict[str, str] = {}
    for path in paths:
        with open(path) as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("pae_interaction") is None:
                    raise ValueError(f"missing pae_interaction in {path}:{line_no}")
                tid = str(rec["target_id"])
                fp = _stable_record_key(rec)
                if tid in by_id:
                    if fingerprints[tid] != fp:
                        raise ValueError(f"conflicting duplicate target_id {tid!r} in {path}:{line_no}")
                    continue
                by_id[tid] = rec
                fingerprints[tid] = fp
    return list(by_id.values())


def _default_n_cal(n: int) -> int:
    if n < 3:
        raise ValueError(f"need at least 3 records for a calibration/test split, got {n}")
    return max(1, min(n - 1, int((2 * n) / 3)))


def run_sweep(paths: Iterable[str], alphas: Iterable[float] = (0.3, 0.2, 0.1),
              *, n_cal: Optional[int] = None, delta: float = 0.1,
              threshold: float = 4.0, seed: int = 0,
              certification_bound: str = "hoeffding") -> Dict[str, Any]:
    rows = load_merged_records(paths)
    threshold_audit = require_label_threshold(rows, threshold=threshold)
    n_cal_eff = _default_n_cal(len(rows)) if n_cal is None else n_cal
    reports = []
    for alpha in alphas:
        rep = run_rows(rows, alpha=float(alpha), delta=delta, threshold=threshold,
                       n_cal=n_cal_eff, seed=seed,
                       certification_bound=certification_bound)
        c = rep["conformal"]
        reports.append({
            "alpha": float(alpha),
            "certified": rep["tau"] is not None,
            "tau": rep["tau"],
            "trusted": c["trusted"],
            "n_test": rep["n_test"],
            "false_accept_rate": c["false_accept_rate"],
            "trust_all_false_accept_rate": rep["trust_all"]["false_accept_rate"],
            "actions": c["actions"],
        })
    return {
        "n_records": len(rows),
        "n_cal": n_cal_eff,
        "n_test": len(rows) - n_cal_eff,
        "delta": delta,
        "certification_bound": certification_bound,
        "threshold": threshold,
        "label_threshold_audit": threshold_audit,
        "seed": seed,
        "alphas": reports,
    }


def _parse_alphas(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="merge complex records and sweep conformal alpha")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE],
                    help="one or more complex records JSONL files")
    ap.add_argument("--alphas", default="0.3,0.2,0.1")
    ap.add_argument("--ncal", type=int, default=None,
                    help="calibration split size; default=floor(2/3*n), preserving 128 for n=192")
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--certification-bound", choices=("hoeffding", "clopper_pearson"),
                    default="hoeffding")
    ap.add_argument("--out", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    rep = run_sweep(args.records, _parse_alphas(args.alphas), n_cal=args.ncal,
                    delta=args.delta, threshold=args.threshold, seed=args.seed,
                    certification_bound=args.certification_bound)
    print(f"# complex conformal alpha sweep  (n={rep['n_records']}, n_cal={rep['n_cal']}, "
          f"n_test={rep['n_test']}, delta={rep['delta']})")
    print(f"  {'alpha':>6}  {'cert':>5}  {'tau':>7}  {'trusted':>9}  {'false_acc':>9}  {'trust_all':>9}")
    for row in rep["alphas"]:
        tau = "none" if row["tau"] is None else f"{row['tau']:.3f}"
        far = "n/a" if row["false_accept_rate"] is None else f"{row['false_accept_rate']:.3f}"
        ta = "n/a" if row["trust_all_false_accept_rate"] is None else f"{row['trust_all_false_accept_rate']:.3f}"
        print(f"  {row['alpha']:6.2f}  {str(row['certified']):>5}  {tau:>7}  "
              f"{row['trusted']:>4}/{row['n_test']:<4}  {far:>9}  {ta:>9}")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
