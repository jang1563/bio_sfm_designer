"""Cross-predictor comparison for complex/binder records.

This is the bridge for closing the current single-model caveat. It does not run a
second predictor; it defines the CPU-side contract for consuming second-predictor
records once they exist and checks whether two predictors agree on the same
designed complexes.

Readiness requires enough labeled overlap on the same `complex_target_id` +
`target_id` pairs, adequate label agreement, and explicit distinct
`signal_source`/`label_source` provenance. A second file that merely copies Boltz
labels under a new predictor id must not close the caveat.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .conformal_complex_gate import _DEFAULT_FIXTURE

_DEFAULT_COPY_TOLERANCE = 1e-6
_DEFAULT_COPY_FRACTION_THRESHOLD = 0.95
_DEFAULT_LABEL_THRESHOLD_TOLERANCE = 1e-9


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError(f"{field} must be a positive integer")
        out = int(text)
    else:
        try:
            out = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a positive integer") from None
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{field} must be a positive integer")
    if out < 1:
        raise ValueError(f"{field} must be a positive integer")
    return out


def _predictor_id(rec: dict) -> str:
    return str(rec.get("predictor_id") or rec.get("refolder") or "unknown")


def _complex_target_id(rec: dict) -> Optional[str]:
    value = rec.get("complex_target_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_records(paths: Iterable[str]) -> Tuple[
    Dict[Tuple[str, str, str], dict],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    by_key: Dict[Tuple[str, str, str], dict] = {}
    failures: List[Dict[str, Any]] = []
    path_reports: List[Dict[str, Any]] = []
    for path in paths:
        n_records = 0
        n_blank = 0
        by_predictor: Dict[str, int] = {}
        with open(path) as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    n_blank += 1
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    failures.append({"path": path, "line": line_no, "kind": "invalid_json", "message": str(exc)})
                    continue
                tid = rec.get("target_id")
                if not tid:
                    failures.append({"path": path, "line": line_no, "kind": "missing_target_id"})
                    continue
                pred = _predictor_id(rec)
                n_records += 1
                by_predictor[pred] = by_predictor.get(pred, 0) + 1
                key = (_complex_target_id(rec) or "", str(tid), pred)
                if key in by_key:
                    failures.append({"path": path, "line": line_no, "kind": "duplicate_predictor_target",
                                     "complex_target_id": key[0] or None,
                                     "target_id": tid, "predictor_id": pred})
                    continue
                by_key[key] = rec
        path_reports.append({
            "path": path,
            "n_records": n_records,
            "n_blank": n_blank,
            "predictors": sorted(by_predictor),
            "records_by_predictor": dict(sorted(by_predictor.items())),
        })
    return by_key, failures, path_reports


def _as_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _label(rec: dict) -> Optional[bool]:
    truth = rec.get("truth")
    return _as_bool(truth.get("correct")) if isinstance(truth, dict) else None


def _as_float(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def _all_exact_numeric_match(pairs: List[Tuple[dict, dict]], field: str) -> bool:
    if not pairs:
        return False
    for ra, rb in pairs:
        a = _as_float(ra.get(field))
        b = _as_float(rb.get(field))
        if a is None or b is None or a != b:
            return False
    return True


def _all_near_numeric_match(pairs: List[Tuple[dict, dict]], field: str, tolerance: float) -> bool:
    if not pairs:
        return False
    for ra, rb in pairs:
        a = _as_float(ra.get(field))
        b = _as_float(rb.get(field))
        if a is None or b is None or abs(a - b) > tolerance:
            return False
    return True


def _near_numeric_pair_count(pairs: List[Tuple[dict, dict]], fields: Iterable[str],
                             tolerance: float) -> int:
    count = 0
    for ra, rb in pairs:
        near = True
        for field in fields:
            a = _as_float(ra.get(field))
            b = _as_float(rb.get(field))
            if a is None or b is None or abs(a - b) > tolerance:
                near = False
                break
        if near:
            count += 1
    return count


def _label_threshold_report(pairs: List[Tuple[dict, dict]], tolerance: float) -> Dict[str, Any]:
    values = set()
    complete = 0
    mismatches = []
    for ra, rb in pairs:
        threshold_a = _as_float(ra.get("lrmsd_threshold"))
        threshold_b = _as_float(rb.get("lrmsd_threshold"))
        if threshold_a is not None:
            values.add(threshold_a)
        if threshold_b is not None:
            values.add(threshold_b)
        if threshold_a is None or threshold_b is None:
            mismatches.append({
                "target_id": ra.get("target_id"),
                "complex_target_id_a": _complex_target_id(ra),
                "complex_target_id_b": _complex_target_id(rb),
                "lrmsd_threshold_a": ra.get("lrmsd_threshold"),
                "lrmsd_threshold_b": rb.get("lrmsd_threshold"),
                "reason": "missing_threshold",
            })
            continue
        complete += 1
        if abs(threshold_a - threshold_b) > tolerance:
            mismatches.append({
                "target_id": ra.get("target_id"),
                "complex_target_id_a": _complex_target_id(ra),
                "complex_target_id_b": _complex_target_id(rb),
                "lrmsd_threshold_a": threshold_a,
                "lrmsd_threshold_b": threshold_b,
                "reason": "threshold_mismatch",
            })
    return {
        "n_label_threshold_overlap": complete,
        "label_threshold_complete": complete == len(pairs),
        "label_threshold_agree": complete == len(pairs) and not mismatches,
        "label_threshold_tolerance": tolerance,
        "label_threshold_values": sorted(values),
        "label_threshold_mismatches": mismatches[:5],
    }


def _matched_pairs(by_key: Dict[Tuple[str, str, str], dict], a: str, b: str) -> List[Tuple[dict, dict]]:
    ids_a = {(complex_id, tid) for complex_id, tid, pred in by_key if pred == a}
    ids_b = {(complex_id, tid) for complex_id, tid, pred in by_key if pred == b}
    return [(by_key[(complex_id, tid, a)], by_key[(complex_id, tid, b)])
            for complex_id, tid in sorted(ids_a & ids_b)]


def _source(rec: dict, field: str) -> Optional[str]:
    value = rec.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _pair_report(by_key: Dict[Tuple[str, str, str], dict], a: str, b: str,
                 min_overlap: int, min_label_agreement: float,
                 copy_tolerance: float,
                 copy_fraction_threshold: float,
                 label_threshold_tolerance: float) -> Dict[str, Any]:
    pairs = _matched_pairs(by_key, a, b)
    both_labeled = [(ra, rb) for ra, rb in pairs if _label(ra) is not None and _label(rb) is not None]
    agree = sum(1 for ra, rb in both_labeled if _label(ra) == _label(rb))
    primary_only_success = sum(1 for ra, rb in both_labeled if _label(ra) and not _label(rb))
    secondary_only_success = sum(1 for ra, rb in both_labeled if (not _label(ra)) and _label(rb))
    pae_pairs = [(ra, rb) for ra, rb in pairs
                 if _as_float(ra.get("pae_interaction")) is not None
                 and _as_float(rb.get("pae_interaction")) is not None]
    lrmsd_pairs = [(ra, rb) for ra, rb in pairs
                   if _as_float(ra.get("lrmsd")) is not None
                   and _as_float(rb.get("lrmsd")) is not None]
    provenance_pairs = [(ra, rb) for ra, rb in pairs
                        if _source(ra, "signal_source") and _source(rb, "signal_source")
                        and _source(ra, "label_source") and _source(rb, "label_source")]
    complex_id_pairs = [(ra, rb) for ra, rb in pairs
                        if _complex_target_id(ra) and _complex_target_id(rb)]
    complex_id_mismatches = [(ra.get("target_id"), _complex_target_id(ra), _complex_target_id(rb))
                             for ra, rb in complex_id_pairs
                             if _complex_target_id(ra) != _complex_target_id(rb)]
    distinct_signal = all(_source(ra, "signal_source") != _source(rb, "signal_source")
                          for ra, rb in provenance_pairs)
    distinct_label = all(_source(ra, "label_source") != _source(rb, "label_source")
                         for ra, rb in provenance_pairs)
    label_agreement = None if not both_labeled else agree / len(both_labeled)
    pae_exact = _all_exact_numeric_match(pairs, "pae_interaction")
    lrmsd_exact = _all_exact_numeric_match(pairs, "lrmsd")
    pae_near = _all_near_numeric_match(pairs, "pae_interaction", copy_tolerance)
    lrmsd_near = _all_near_numeric_match(pairs, "lrmsd", copy_tolerance)
    numeric_copy_count = _near_numeric_pair_count(
        pairs,
        ("pae_interaction", "lrmsd"),
        copy_tolerance,
    )
    numeric_copy_fraction = numeric_copy_count / len(pairs) if pairs else None
    threshold_report = _label_threshold_report(pairs, label_threshold_tolerance)
    return {
        "predictor_a": a,
        "predictor_b": b,
        "n_overlap": len(pairs),
        "n_labeled_overlap": len(both_labeled),
        "meets_min_overlap": len(pairs) >= min_overlap,
        "meets_min_labeled_overlap": len(both_labeled) >= min_overlap,
        "label_agreement": label_agreement,
        "min_label_agreement": min_label_agreement,
        "meets_min_label_agreement": label_agreement is not None and label_agreement >= min_label_agreement,
        "n_provenance_overlap": len(provenance_pairs),
        "provenance_complete": len(provenance_pairs) == len(pairs),
        "n_complex_target_id_overlap": len(complex_id_pairs),
        "complex_target_id_complete": len(complex_id_pairs) == len(pairs),
        "complex_target_id_agree": len(complex_id_pairs) == len(pairs) and not complex_id_mismatches,
        "complex_target_id_mismatches": complex_id_mismatches,
        **threshold_report,
        "distinct_signal_sources": distinct_signal if provenance_pairs else False,
        "distinct_label_sources": distinct_label if provenance_pairs else False,
        "pae_interaction_exact_match": pae_exact,
        "lrmsd_exact_match": lrmsd_exact,
        "numeric_copy_abs_tolerance": copy_tolerance,
        "numeric_copy_fraction_threshold": copy_fraction_threshold,
        "n_numeric_copy_pairs": numeric_copy_count,
        "numeric_copy_fraction": numeric_copy_fraction,
        "pae_interaction_near_match": pae_near,
        "lrmsd_near_match": lrmsd_near,
        "copied_numeric_values": (
            len(pairs) >= min_overlap
            and numeric_copy_fraction is not None
            and numeric_copy_fraction >= copy_fraction_threshold
        ),
        "both_success": sum(1 for ra, rb in both_labeled if _label(ra) and _label(rb)),
        "both_failure": sum(1 for ra, rb in both_labeled if (not _label(ra)) and (not _label(rb))),
        "predictor_a_only_success": primary_only_success,
        "predictor_b_only_success": secondary_only_success,
        "pae_interaction_pearson": _pearson(
            [float(ra["pae_interaction"]) for ra, _ in pae_pairs],
            [float(rb["pae_interaction"]) for _, rb in pae_pairs],
        ),
        "lrmsd_pearson": _pearson(
            [float(ra["lrmsd"]) for ra, _ in lrmsd_pairs],
            [float(rb["lrmsd"]) for _, rb in lrmsd_pairs],
        ),
    }


def _thresholds_agree(ra: dict, rb: dict, tolerance: float) -> Optional[bool]:
    threshold_a = _as_float(ra.get("lrmsd_threshold"))
    threshold_b = _as_float(rb.get("lrmsd_threshold"))
    if threshold_a is None or threshold_b is None:
        return None
    return abs(threshold_a - threshold_b) <= tolerance


def _match_row(ra: dict, rb: dict, a: str, b: str,
               label_threshold_tolerance: float) -> Dict[str, Any]:
    label_a = _label(ra)
    label_b = _label(rb)
    complex_a = _complex_target_id(ra)
    complex_b = _complex_target_id(rb)
    return {
        "target_id": str(ra.get("target_id")),
        "complex_target_id_a": complex_a,
        "complex_target_id_b": complex_b,
        "complex_target_id_agrees": (complex_a == complex_b) if complex_a and complex_b else None,
        "predictor_a": a,
        "predictor_b": b,
        "label_a": label_a,
        "label_b": label_b,
        "label_agrees": (label_a == label_b) if label_a is not None and label_b is not None else None,
        "pae_interaction_a": _as_float(ra.get("pae_interaction")),
        "pae_interaction_b": _as_float(rb.get("pae_interaction")),
        "lrmsd_a": _as_float(ra.get("lrmsd")),
        "lrmsd_b": _as_float(rb.get("lrmsd")),
        "lrmsd_threshold_a": _as_float(ra.get("lrmsd_threshold")),
        "lrmsd_threshold_b": _as_float(rb.get("lrmsd_threshold")),
        "label_threshold_agrees": _thresholds_agree(ra, rb, label_threshold_tolerance),
        "signal_source_a": _source(ra, "signal_source"),
        "signal_source_b": _source(rb, "signal_source"),
        "label_source_a": _source(ra, "label_source"),
        "label_source_b": _source(rb, "label_source"),
    }


def build_match_rows(by_key: Dict[Tuple[str, str, str], dict],
                     predictors: Iterable[str],
                     label_threshold_tolerance: float = _DEFAULT_LABEL_THRESHOLD_TOLERANCE) -> List[Dict[str, Any]]:
    predictors = list(predictors)
    rows: List[Dict[str, Any]] = []
    for i in range(len(predictors)):
        for j in range(i + 1, len(predictors)):
            a = predictors[i]
            b = predictors[j]
            rows.extend(
                _match_row(ra, rb, a, b, label_threshold_tolerance)
                for ra, rb in _matched_pairs(by_key, a, b)
            )
    return rows


def write_match_rows(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            json.dump(row, fh, sort_keys=True)
            fh.write("\n")


def run_cross_predictor(paths: Iterable[str], *, min_predictors: int = 2,
                        min_overlap: int = 20,
                        min_label_agreement: float = 0.8,
                        match_preview: int = 0,
                        copy_tolerance: float = _DEFAULT_COPY_TOLERANCE,
                        copy_fraction_threshold: float = _DEFAULT_COPY_FRACTION_THRESHOLD,
                        label_threshold_tolerance: float = _DEFAULT_LABEL_THRESHOLD_TOLERANCE,
                        require_disjoint_record_files: bool = False) -> Dict[str, Any]:
    min_predictors = _require_positive_int(min_predictors, "min_predictors")
    min_overlap = _require_positive_int(min_overlap, "min_overlap")
    if not 0.0 <= min_label_agreement <= 1.0:
        raise ValueError("min_label_agreement must be in [0, 1]")
    if copy_tolerance < 0 or not math.isfinite(copy_tolerance):
        raise ValueError("copy_tolerance must be a finite non-negative value")
    if not 0.0 <= copy_fraction_threshold <= 1.0:
        raise ValueError("copy_fraction_threshold must be in [0, 1]")
    if label_threshold_tolerance < 0 or not math.isfinite(label_threshold_tolerance):
        raise ValueError("label_threshold_tolerance must be a finite non-negative value")
    paths = list(paths)
    by_key, failures, record_files = _read_records(paths)
    predictors = sorted({pred for _, _, pred in by_key})
    by_predictor = {p: sum(1 for _, _, pred in by_key if pred == p) for p in predictors}
    pair_reports = [
        _pair_report(by_key, predictors[i], predictors[j], min_overlap, min_label_agreement,
                     copy_tolerance, copy_fraction_threshold, label_threshold_tolerance)
        for i in range(len(predictors))
        for j in range(i + 1, len(predictors))
    ]
    match_rows = build_match_rows(by_key, predictors, label_threshold_tolerance)
    blocking = list(failures)
    if require_disjoint_record_files:
        mixed_files = [r for r in record_files if len(r["predictors"]) > 1]
        if mixed_files:
            blocking.append({"kind": "mixed_predictor_record_file",
                             "files": [(r["path"], r["predictors"]) for r in mixed_files],
                             "required": "each input JSONL must contain records from only one predictor"})
    if len(predictors) < min_predictors:
        blocking.append({"kind": "too_few_predictors", "count": len(predictors),
                         "required": min_predictors})
    weak_pairs = [p for p in pair_reports if not p["meets_min_overlap"]]
    if len(predictors) >= min_predictors and not pair_reports:
        blocking.append({"kind": "no_predictor_pairs"})
    elif weak_pairs:
        blocking.append({"kind": "insufficient_overlap",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["n_overlap"]) for p in weak_pairs],
                         "required": min_overlap})
    weak_labeled = [p for p in pair_reports if not p["meets_min_labeled_overlap"]]
    if weak_labeled:
        blocking.append({"kind": "insufficient_labeled_overlap",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["n_labeled_overlap"])
                                   for p in weak_labeled],
                         "required": min_overlap})
    weak_agreement = [p for p in pair_reports if not p["meets_min_label_agreement"]]
    if weak_agreement:
        blocking.append({"kind": "label_agreement_below_min",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["label_agreement"])
                                   for p in weak_agreement],
                         "required": min_label_agreement})
    weak_provenance = [p for p in pair_reports
                       if not (p["provenance_complete"]
                               and p["distinct_signal_sources"]
                               and p["distinct_label_sources"])]
    if weak_provenance:
        blocking.append({"kind": "weak_predictor_provenance",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["n_provenance_overlap"],
                                    p["distinct_signal_sources"], p["distinct_label_sources"])
                                   for p in weak_provenance],
                         "required": "complete distinct signal_source and label_source"})
    weak_target_identity = [p for p in pair_reports
                            if not (p["complex_target_id_complete"] and p["complex_target_id_agree"])]
    if weak_target_identity:
        blocking.append({"kind": "weak_target_identity",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["n_complex_target_id_overlap"],
                                    p["complex_target_id_complete"], p["complex_target_id_agree"])
                                   for p in weak_target_identity],
                         "required": "complete matching complex_target_id for every matched target_id"})
    weak_label_thresholds = [p for p in pair_reports
                             if not (p["label_threshold_complete"] and p["label_threshold_agree"])]
    if weak_label_thresholds:
        blocking.append({"kind": "label_threshold_mismatch",
                         "pairs": [(p["predictor_a"], p["predictor_b"],
                                    p["n_label_threshold_overlap"],
                                    p["label_threshold_complete"],
                                    p["label_threshold_agree"],
                                    p["label_threshold_values"])
                                   for p in weak_label_thresholds],
                         "label_threshold_tolerance": label_threshold_tolerance,
                         "required": "matched predictor records must use the same lrmsd_threshold label definition"})
    copied_values = [p for p in pair_reports if p["copied_numeric_values"]]
    if copied_values:
        blocking.append({"kind": "copied_predictor_values",
                         "pairs": [(p["predictor_a"], p["predictor_b"], p["n_overlap"])
                                   for p in copied_values],
                         "copy_tolerance": copy_tolerance,
                         "copy_fraction_threshold": copy_fraction_threshold,
                         "required": "second predictor must not copy or near-copy most primary pAE and L-RMSD values"})
    status = "cross_predictor_ready" if not blocking else "single_model_caveat_open"
    return {
        "ok": not blocking,
        "status": status,
        "records": paths,
        "predictors": predictors,
        "records_by_predictor": by_predictor,
        "min_predictors": min_predictors,
        "min_overlap": min_overlap,
        "min_label_agreement": min_label_agreement,
        "copy_tolerance": copy_tolerance,
        "copy_fraction_threshold": copy_fraction_threshold,
        "label_threshold_tolerance": label_threshold_tolerance,
        "require_disjoint_record_files": require_disjoint_record_files,
        "record_files": record_files,
        "pairs": pair_reports,
        "n_match_rows": len(match_rows),
        "match_preview": match_rows[:max(0, int(match_preview))],
        "failures": blocking,
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="compare complex records across independent predictors")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE])
    ap.add_argument("--min-predictors", type=int, default=2)
    ap.add_argument("--min-overlap", type=int, default=20)
    ap.add_argument("--min-label-agreement", type=float, default=0.8)
    ap.add_argument("--copy-tolerance", type=float, default=_DEFAULT_COPY_TOLERANCE,
                    help="absolute tolerance for detecting copied pAE/L-RMSD values")
    ap.add_argument("--copy-fraction-threshold", type=float, default=_DEFAULT_COPY_FRACTION_THRESHOLD,
                    help="fraction of near-copied pAE/L-RMSD pairs that blocks independence")
    ap.add_argument("--label-threshold-tolerance", type=float, default=_DEFAULT_LABEL_THRESHOLD_TOLERANCE,
                    help="absolute tolerance for requiring matched lrmsd_threshold values to agree")
    ap.add_argument("--require-disjoint-record-files", action="store_true",
                    help="require each input JSONL to contain records from exactly one predictor")
    ap.add_argument("--match-preview", type=int, default=0,
                    help="include the first N matched rows in the JSON report")
    ap.add_argument("--emit-matches", default=None,
                    help="optional JSONL path for all matched predictor-overlap rows")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rep = run_cross_predictor(args.records, min_predictors=args.min_predictors,
                              min_overlap=args.min_overlap,
                              min_label_agreement=args.min_label_agreement,
                              match_preview=args.match_preview,
                              copy_tolerance=args.copy_tolerance,
                              copy_fraction_threshold=args.copy_fraction_threshold,
                              label_threshold_tolerance=args.label_threshold_tolerance,
                              require_disjoint_record_files=args.require_disjoint_record_files)
    print(f"# complex cross-predictor report  status={rep['status']} ok={rep['ok']}")
    print(f"  predictors={rep['predictors']} records_by_predictor={rep['records_by_predictor']}")
    if rep["pairs"]:
        for pair in rep["pairs"]:
            print(f"  {pair['predictor_a']} vs {pair['predictor_b']}: overlap={pair['n_overlap']} "
                  f"label_agreement={pair['label_agreement']}")
    if rep["failures"]:
        print("  failures:", json.dumps(rep["failures"], sort_keys=True))
    if args.emit_matches:
        by_key, _failures, _record_files = _read_records(args.records)
        rows = build_match_rows(by_key, rep["predictors"], rep["label_threshold_tolerance"])
        write_match_rows(args.emit_matches, rows)
        print(f"wrote {args.emit_matches} ({len(rows)} matched rows)")
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
