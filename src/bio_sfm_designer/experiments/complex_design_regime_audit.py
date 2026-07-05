"""Design-regime audit for the M6c complex/binder records.

This posthoc helper asks a narrow science question before the next scale batch:
do the existing temperature strata all contribute useful pAE signal, or is the
current gate result mostly a low-temperature/easy-design artifact?
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from typing import Any, Dict, Iterable, List, Optional

from .complex_gate_sweep import load_merged_records
from .conformal_complex_gate import _DEFAULT_FIXTURE
from .cross_model_auroc import _auroc

_TEMP_RE = re.compile(r"(?:^|[_-])t(\d{2,4})(?:[_-]|$)")


def _as_float(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def infer_design_temperature(rec: Dict[str, Any]) -> Optional[float]:
    """Infer ProteinMPNN/design temperature from explicit fields or target_id."""
    for key in ("design_temperature", "mpnn_temperature", "temperature"):
        x = _as_float(rec.get(key))
        if x is not None:
            return x

    target_id = str(rec.get("target_id", ""))
    match = _TEMP_RE.search(target_id)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 2:
        scale = 10.0
    elif len(digits) == 3:
        scale = 100.0
    else:
        scale = 1000.0
    return int(digits) / scale


def _median(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [_as_float(row.get(key)) for row in rows]
    clean = [x for x in values if x is not None]
    return statistics.median(clean) if clean else None


def _mean(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [_as_float(row.get(key)) for row in rows]
    clean = [x for x in values if x is not None]
    return statistics.mean(clean) if clean else None


def _auroc_for(rows: List[Dict[str, Any]], key: str, sign: int, threshold: float) -> Optional[float]:
    scores = []
    labels = []
    for row in rows:
        value = _as_float(row.get(key))
        lrmsd = _as_float(row.get("lrmsd"))
        if value is None or lrmsd is None:
            continue
        scores.append(sign * value)
        labels.append(lrmsd < threshold)
    return _auroc(scores, labels)


def _round(value: Any, ndigits: int = 3) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, ndigits)
    return value


def _temperature_label(temp: Optional[float]) -> str:
    if temp is None:
        return "unknown"
    return f"temp_{temp:g}"


def _summarize_stratum(rows: List[Dict[str, Any]], temp: Optional[float],
                       threshold: float) -> Dict[str, Any]:
    successes = 0
    for row in rows:
        lrmsd = _as_float(row.get("lrmsd"))
        if lrmsd is not None and lrmsd < threshold:
            successes += 1
    n = len(rows)
    failures = n - successes
    return {
        "stratum": _temperature_label(temp),
        "temperature": temp,
        "n": n,
        "success": successes,
        "failure": failures,
        "success_rate": successes / n if n else None,
        "failure_rate": failures / n if n else None,
        "median_pae_interaction": _median(rows, "pae_interaction"),
        "mean_pae_interaction": _mean(rows, "pae_interaction"),
        "median_lrmsd": _median(rows, "lrmsd"),
        "median_mean_plddt": _median(rows, "mean_plddt"),
        "pae_auroc_within_stratum": _auroc_for(rows, "pae_interaction", -1, threshold),
        "iptm_auroc_within_stratum": _auroc_for(rows, "iptm", 1, threshold),
    }


def run_rows(rows: List[Dict[str, Any]], *, threshold: float = 4.0,
             informative_auroc: float = 0.75) -> Dict[str, Any]:
    groups: Dict[Optional[float], List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(infer_design_temperature(row), []).append(row)

    strata = [
        _summarize_stratum(groups[temp], temp, threshold)
        for temp in sorted(groups, key=lambda t: (t is None, t if t is not None else 0.0))
    ]
    numeric = [row for row in strata if row["temperature"] is not None]
    success_rates = [row["success_rate"] for row in numeric]
    pae_medians = [row["median_pae_interaction"] for row in numeric]
    pae_aurocs = [row["pae_auroc_within_stratum"] for row in numeric]

    all_strata_mixed = bool(numeric) and all(row["success"] > 0 and row["failure"] > 0 for row in numeric)
    all_pae_informative = bool(pae_aurocs) and all(
        value is not None and value >= informative_auroc for value in pae_aurocs
    )
    success_decreases_with_temperature = all(
        success_rates[i] >= success_rates[i + 1] for i in range(len(success_rates) - 1)
    )
    pae_increases_with_temperature = all(
        pae_medians[i] <= pae_medians[i + 1] for i in range(len(pae_medians) - 1)
        if pae_medians[i] is not None and pae_medians[i + 1] is not None
    )

    if all_strata_mixed and all_pae_informative and success_decreases_with_temperature:
        decision = "keep_balanced_temperature_scale"
        message = (
            "pAE remains informative within every temperature stratum while success rate drops with "
            "temperature; keep the next scale batch balanced across the existing temperatures."
        )
    elif all_pae_informative:
        decision = "keep_temperature_stratification"
        message = "pAE remains informative across parsed strata; keep stratified reporting in scale-up."
    else:
        decision = "inspect_temperature_strata"
        message = "at least one stratum lacks a clear pAE signal or mixed labels; inspect before reweighting."

    return {
        "ok": True,
        "decision": decision,
        "message": message,
        "threshold": threshold,
        "informative_auroc": informative_auroc,
        "n_records": len(rows),
        "n_strata": len(strata),
        "all_strata_mixed": all_strata_mixed,
        "all_pae_informative": all_pae_informative,
        "success_decreases_with_temperature": success_decreases_with_temperature,
        "pae_increases_with_temperature": pae_increases_with_temperature,
        "strata": strata,
    }


def run_audit(records: Iterable[str], *, threshold: float = 4.0,
              informative_auroc: float = 0.75) -> Dict[str, Any]:
    rows = load_merged_records(records)
    return run_rows(rows, threshold=threshold, informative_auroc=informative_auroc)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, float):
        return _round(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="audit M6c design-temperature strata")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--informative-auroc", type=float, default=0.75)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_audit(args.records, threshold=args.threshold,
                    informative_auroc=args.informative_auroc)
    print(f"# complex design-regime audit  decision={rep['decision']} n={rep['n_records']}")
    print(f"  {rep['message']}")
    print("  stratum     n  succ  success  median_pae  median_lrmsd  pAE_AUROC  ipTM_AUROC")
    for row in rep["strata"]:
        print(
            f"  {row['stratum']:8s}  {row['n']:3d}  {row['success']:4d}  "
            f"{_fmt(row['success_rate']):>7}  {_fmt(row['median_pae_interaction']):>10}  "
            f"{_fmt(row['median_lrmsd']):>12}  {_fmt(row['pae_auroc_within_stratum']):>9}  "
            f"{_fmt(row['iptm_auroc_within_stratum']):>10}"
        )
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True, default=_json_default)
            fh.write("\n")
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
