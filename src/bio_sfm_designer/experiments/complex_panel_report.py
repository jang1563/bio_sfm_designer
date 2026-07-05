"""Panel-level checks for multi-target M6c complex/binder validation.

The pooled complex gate is useful for scale planning, but a multi-target claim
needs target provenance and per-target evidence. This report refuses records that
do not carry `complex_target_id`, summarizes each target separately, and treats
the pooled certificate as diagnostic only. Panel certificates are predictor-
specific: mixed predictors/signal sources/label sources belong in
`complex_cross_predictor.py`, not in a pooled panel certificate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .complex_gate_sweep import _default_n_cal, load_merged_records, run_sweep
from .complex_label_threshold import label_threshold_audit as audit_label_threshold
from .complex_records_qc import run_qc
from .conformal_complex_gate import _DEFAULT_FIXTURE, run_rows


def _group_records(rows: Iterable[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for rec in rows:
        cid = rec.get("complex_target_id")
        if cid:
            grouped[str(cid)].append(rec)
    return dict(grouped)


def _source_set(rows: Iterable[dict], field: str, *, fallback: Optional[str] = None) -> List[str]:
    values = set()
    for rec in rows:
        value = rec.get(field)
        if (value is None or value == "") and fallback:
            value = rec.get(fallback)
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
        else:
            values.add("unknown")
    return sorted(values)


def _target_report(target_id: str, rows: List[dict], *, target_alpha: float,
                   min_records_per_target: int, n_cal: Optional[int],
                   delta: float, threshold: float, seed: int) -> Dict[str, Any]:
    n = len(rows)
    success = sum(1 for r in rows if r["lrmsd"] < threshold)
    base = {
        "complex_target_id": target_id,
        "n_records": n,
        "success": success,
        "failure": n - success,
        "threshold": threshold,
        "min_records_per_target": min_records_per_target,
    }
    if n < min_records_per_target:
        return {**base, "status": "too_few_records", "certified": False,
                "message": f"{n} records < required {min_records_per_target}"}
    try:
        n_cal_eff = _default_n_cal(n) if n_cal is None else n_cal
        rep = run_rows(rows, alpha=target_alpha, delta=delta, threshold=threshold,
                       n_cal=n_cal_eff, seed=seed)
    except ValueError as exc:
        return {**base, "status": "split_failed", "certified": False, "message": str(exc)}
    return {
        **base,
        "status": "certified" if rep["tau"] is not None else "not_certified",
        "certified": rep["tau"] is not None,
        "n_cal": rep["n_cal"],
        "n_test": rep["n_test"],
        "tau": rep["tau"],
        "trusted": rep["conformal"]["trusted"],
        "false_accept_rate": rep["conformal"]["false_accept_rate"],
        "trust_all_false_accept_rate": rep["trust_all"]["false_accept_rate"],
    }


def run_panel(records: Iterable[str], *, target_alpha: float = 0.2,
              min_targets: int = 3, min_records_per_target: int = 20,
              n_cal: Optional[int] = None, delta: float = 0.1,
              threshold: float = 4.0, seed: int = 0) -> Dict[str, Any]:
    records = list(records)
    qc = run_qc(records)
    if not qc["ok"]:
        return {
            "ok": False,
            "panel_status": "qc_failed",
            "records": records,
            "qc": qc,
            "message": "QC failed; panel evidence is not analyzable.",
        }
    rows = load_merged_records(records)
    missing = [r["target_id"] for r in rows if not r.get("complex_target_id")]
    predictors = _source_set(rows, "predictor_id", fallback="refolder")
    signal_sources = _source_set(rows, "signal_source")
    label_sources = _source_set(rows, "label_source")
    label_threshold_audit = audit_label_threshold(rows, threshold=threshold)
    groups = _group_records(rows)
    target_reports = [
        _target_report(tid, groups[tid], target_alpha=target_alpha,
                       min_records_per_target=min_records_per_target,
                       n_cal=n_cal, delta=delta, threshold=threshold, seed=seed)
        for tid in sorted(groups)
    ]
    if label_threshold_audit["ok"]:
        pooled = run_sweep(records, alphas=[target_alpha], n_cal=n_cal,
                           delta=delta, threshold=threshold, seed=seed)
    else:
        pooled = {
            "ok": False,
            "status": "skipped_label_threshold_mismatch",
            "target_alpha": target_alpha,
            "threshold": threshold,
            "label_threshold_audit": label_threshold_audit,
            "message": "Pooled diagnostic skipped because row-level lrmsd_threshold metadata is mixed or missing.",
        }
    failures = []
    if missing:
        failures.append({"kind": "missing_complex_target_id", "count": len(missing),
                         "examples": missing[:5]})
    if len(predictors) != 1 or predictors == ["unknown"]:
        failures.append({"kind": "mixed_or_missing_predictor_id", "values": predictors})
    if len(signal_sources) != 1 or signal_sources == ["unknown"]:
        failures.append({"kind": "mixed_or_missing_signal_source", "values": signal_sources})
    if len(label_sources) != 1 or label_sources == ["unknown"]:
        failures.append({"kind": "mixed_or_missing_label_source", "values": label_sources})
    if not label_threshold_audit["ok"]:
        failures.append({
            "kind": "label_threshold_mismatch",
            "expected_threshold": threshold,
            "record_thresholds": label_threshold_audit["record_thresholds"],
            "count": label_threshold_audit["n_mismatches"],
            "examples": label_threshold_audit["examples"],
        })
    if len(groups) < min_targets:
        failures.append({"kind": "too_few_targets", "count": len(groups),
                         "required": min_targets})
    too_few = [r["complex_target_id"] for r in target_reports if r["status"] == "too_few_records"]
    if too_few:
        failures.append({"kind": "too_few_records_per_target", "targets": too_few,
                         "required": min_records_per_target})
    uncertified = [r["complex_target_id"] for r in target_reports
                   if r["status"] not in ("certified", "too_few_records")]
    if uncertified:
        failures.append({"kind": "target_not_certified", "targets": uncertified})

    if not failures:
        panel_status = "multi_target_certified"
    elif all(f["kind"] == "target_not_certified" for f in failures):
        panel_status = "multi_target_evaluable_not_certified"
    else:
        panel_status = "not_multi_target_proof"
    return {
        "ok": not failures,
        "panel_status": panel_status,
        "records": records,
        "target_alpha": target_alpha,
        "threshold": threshold,
        "min_targets": min_targets,
        "min_records_per_target": min_records_per_target,
        "n_records": len(rows),
        "n_targets": len(groups),
        "missing_complex_target_id": len(missing),
        "predictors": predictors,
        "signal_sources": signal_sources,
        "label_sources": label_sources,
        "label_threshold_audit": label_threshold_audit,
        "targets": target_reports,
        "pooled_diagnostic": pooled,
        "failures": failures,
        "message": (
            "All targets have enough records and per-target certificates."
            if not failures else
            "Do not make a multi-target claim from this panel yet; inspect failures."
        ),
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="check multi-target M6c panel evidence")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--min-targets", type=int, default=3)
    ap.add_argument("--min-records-per-target", type=int, default=20)
    ap.add_argument("--ncal", type=int, default=None)
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_panel(args.records, target_alpha=args.target_alpha,
                    min_targets=args.min_targets,
                    min_records_per_target=args.min_records_per_target,
                    n_cal=args.ncal, delta=args.delta,
                    threshold=args.threshold, seed=args.seed)
    print(f"# complex panel report  status={rep['panel_status']} ok={rep['ok']}")
    print(f"  targets={rep.get('n_targets', 0)} records={rep.get('n_records', 0)} "
          f"missing_complex_target_id={rep.get('missing_complex_target_id', 'n/a')}")
    if rep.get("failures"):
        print("  failures:", json.dumps(rep["failures"], sort_keys=True))
    else:
        print("  ok")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
