"""QC for Boltz complex records before M6c sweep/plan/report analyses.

The analysis helpers intentionally merge/dedupe records, but scale-up needs a
stricter ingestion gate: missing pAE, missing L-RMSD, duplicate conflicts, or
truth/threshold mismatches should be seen before they distort alpha estimates.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Iterable, List, Optional

from .conformal_complex_gate import _DEFAULT_FIXTURE

_REQUIRED = ("target_id", "regime", "mean_plddt", "pae_interaction", "lrmsd",
             "lrmsd_threshold", "truth", "interface_aligned")
_PROVENANCE_REQUIRED = ("predictor_id", "signal_source", "label_source")


def _stable_record_key(rec: dict) -> str:
    return json.dumps(rec, sort_keys=True, separators=(",", ":"))


def _complex_target_id(rec: dict) -> str:
    value = rec.get("complex_target_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _record_identity(rec: dict) -> Optional[tuple]:
    target_id = rec.get("target_id")
    if target_id is None:
        return None
    return (_complex_target_id(rec), str(target_id))


def _failure(path: str, line_no: int, target_id: Optional[str], kind: str, message: str) -> Dict[str, Any]:
    return {"path": path, "line": line_no, "target_id": target_id, "kind": kind, "message": message}


def _as_float(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_record(rec: dict, path: str, line_no: int, *,
                     require_complex_target_id: bool = False,
                     require_provenance: bool = False,
                     require_chain_ids: bool = False,
                     expect_predictor_id: Optional[str] = None,
                     expect_signal_source: Optional[str] = None,
                     expect_label_source: Optional[str] = None,
                     forbid_predictor_ids: Iterable[str] = ()) -> List[Dict[str, Any]]:
    target_id = str(rec.get("target_id")) if rec.get("target_id") is not None else None
    failures: List[Dict[str, Any]] = []
    for key in _REQUIRED:
        if key not in rec:
            failures.append(_failure(path, line_no, target_id, "missing_field", f"missing {key}"))
    if require_complex_target_id and not _nonempty_str(rec.get("complex_target_id")):
        failures.append(_failure(path, line_no, target_id, "missing_complex_target_id",
                                 "complex_target_id is required in strict QC mode"))
    if require_provenance:
        for key in _PROVENANCE_REQUIRED:
            if not _nonempty_str(rec.get(key)):
                failures.append(_failure(path, line_no, target_id, "missing_provenance", f"missing {key}"))
    if require_chain_ids:
        for key in ("target_chain", "binder_chain"):
            if not _nonempty_str(rec.get(key)):
                failures.append(_failure(path, line_no, target_id, "missing_chain_id", f"missing {key}"))
        if _nonempty_str(rec.get("target_chain")) and rec.get("target_chain") == rec.get("binder_chain"):
            failures.append(_failure(path, line_no, target_id, "bad_chain_ids",
                                     "target_chain and binder_chain must differ"))
    predictor_id = rec.get("predictor_id")
    if expect_predictor_id is not None and predictor_id != expect_predictor_id:
        failures.append(_failure(path, line_no, target_id, "unexpected_predictor_id",
                                 f"predictor_id={predictor_id!r}, expected {expect_predictor_id!r}"))
    forbidden = set(forbid_predictor_ids)
    if predictor_id in forbidden:
        failures.append(_failure(path, line_no, target_id, "forbidden_predictor_id",
                                 f"predictor_id={predictor_id!r} is forbidden"))
    if expect_signal_source is not None and rec.get("signal_source") != expect_signal_source:
        failures.append(_failure(path, line_no, target_id, "unexpected_signal_source",
                                 f"signal_source={rec.get('signal_source')!r}, expected {expect_signal_source!r}"))
    if expect_label_source is not None and rec.get("label_source") != expect_label_source:
        failures.append(_failure(path, line_no, target_id, "unexpected_label_source",
                                 f"label_source={rec.get('label_source')!r}, expected {expect_label_source!r}"))
    if failures:
        return failures

    if rec.get("regime") != "complex":
        failures.append(_failure(path, line_no, target_id, "bad_regime", f"regime={rec.get('regime')!r}"))
    if rec.get("interface_aligned") is not True:
        failures.append(_failure(path, line_no, target_id, "unaligned_interface", "interface_aligned is not true"))

    mean_plddt = _as_float(rec.get("mean_plddt"))
    if mean_plddt is None or not (0.0 <= mean_plddt <= 100.0):
        failures.append(_failure(path, line_no, target_id, "bad_mean_plddt", "mean_plddt must be finite in [0, 100]"))
    pae = _as_float(rec.get("pae_interaction"))
    if pae is None or pae < 0.0:
        failures.append(_failure(path, line_no, target_id, "bad_pae_interaction", "pae_interaction must be finite and >= 0"))
    lrmsd = _as_float(rec.get("lrmsd"))
    if lrmsd is None or lrmsd < 0.0:
        failures.append(_failure(path, line_no, target_id, "bad_lrmsd", "lrmsd must be finite and >= 0"))
    threshold = _as_float(rec.get("lrmsd_threshold"))
    if threshold is None or threshold <= 0.0:
        failures.append(_failure(path, line_no, target_id, "bad_lrmsd_threshold", "lrmsd_threshold must be finite and > 0"))

    truth = rec.get("truth")
    if not isinstance(truth, dict) or not isinstance(truth.get("correct"), bool):
        failures.append(_failure(path, line_no, target_id, "bad_truth", "truth.correct must be boolean"))
    elif lrmsd is not None and threshold is not None:
        expected = lrmsd < threshold
        if truth["correct"] != expected:
            failures.append(_failure(path, line_no, target_id, "truth_mismatch",
                                     f"truth.correct={truth['correct']} but lrmsd<threshold is {expected}"))
    return failures


def run_qc(paths: Iterable[str], *, require_complex_target_id: bool = False,
           require_provenance: bool = False,
           require_chain_ids: bool = False,
           expect_predictor_id: Optional[str] = None,
           expect_signal_source: Optional[str] = None,
           expect_label_source: Optional[str] = None,
           forbid_predictor_ids: Iterable[str] = ()) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    fingerprints: Dict[tuple, str] = {}
    seen_where: Dict[tuple, str] = {}
    target_ids = set()
    n_rows = n_blank = n_exact_duplicates = 0
    forbidden = tuple(str(x) for x in forbid_predictor_ids)
    for path in paths:
        with open(path) as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    n_blank += 1
                    continue
                n_rows += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    failures.append(_failure(path, line_no, None, "invalid_json", str(exc)))
                    continue
                if not isinstance(rec, dict):
                    failures.append(_failure(path, line_no, None, "invalid_record", "record is not a JSON object"))
                    continue
                tid = str(rec.get("target_id")) if rec.get("target_id") is not None else None
                if tid is None:
                    failures.append(_failure(path, line_no, None, "missing_field", "missing target_id"))
                else:
                    target_ids.add(tid)
                    fp = _stable_record_key(rec)
                    identity = _record_identity(rec)
                    if identity in fingerprints:
                        if fingerprints[identity] == fp:
                            n_exact_duplicates += 1
                            continue
                        failures.append(_failure(path, line_no, tid, "duplicate_conflict",
                                                 f"conflicts with previous record at {seen_where[identity]}"))
                    else:
                        fingerprints[identity] = fp
                        seen_where[identity] = f"{path}:{line_no}"
                failures.extend(_validate_record(
                    rec, path, line_no,
                    require_complex_target_id=require_complex_target_id,
                    require_provenance=require_provenance,
                    require_chain_ids=require_chain_ids,
                    expect_predictor_id=expect_predictor_id,
                    expect_signal_source=expect_signal_source,
                    expect_label_source=expect_label_source,
                    forbid_predictor_ids=forbidden,
                ))
    by_kind: Dict[str, int] = {}
    for f in failures:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {
        "ok": not failures,
        "n_rows": n_rows,
        "n_blank": n_blank,
        "n_unique_target_ids": len(target_ids),
        "n_unique_record_keys": len(fingerprints),
        "n_exact_duplicates": n_exact_duplicates,
        "n_failures": len(failures),
        "require_complex_target_id": require_complex_target_id,
        "require_provenance": require_provenance,
        "require_chain_ids": require_chain_ids,
        "expect_predictor_id": expect_predictor_id,
        "expect_signal_source": expect_signal_source,
        "expect_label_source": expect_label_source,
        "forbid_predictor_ids": list(forbidden),
        "failures_by_kind": by_kind,
        "failures": failures,
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="QC complex Boltz records before M6c analyses")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE],
                    help="one or more complex records JSONL files")
    ap.add_argument("--require-complex-target-id", action="store_true",
                    help="strict mode: require complex_target_id on every record")
    ap.add_argument("--require-provenance", action="store_true",
                    help="strict mode: require predictor_id, signal_source, and label_source")
    ap.add_argument("--require-chain-ids", action="store_true",
                    help="strict mode: require target_chain and binder_chain")
    ap.add_argument("--expect-predictor-id", default=None,
                    help="require every record to have this predictor_id")
    ap.add_argument("--expect-signal-source", default=None,
                    help="require every record to have this signal_source")
    ap.add_argument("--expect-label-source", default=None,
                    help="require every record to have this label_source")
    ap.add_argument("--forbid-predictor-id", action="append", default=[],
                    help="forbid this predictor_id; repeatable")
    ap.add_argument("--out", default=None, help="optional JSON QC report")
    ap.add_argument("--max-failures", type=int, default=20)
    args = ap.parse_args(argv)

    rep = run_qc(args.records, require_complex_target_id=args.require_complex_target_id,
                 require_provenance=args.require_provenance,
                 require_chain_ids=args.require_chain_ids,
                 expect_predictor_id=args.expect_predictor_id,
                 expect_signal_source=args.expect_signal_source,
                 expect_label_source=args.expect_label_source,
                 forbid_predictor_ids=args.forbid_predictor_id)
    print(f"# complex records QC  rows={rep['n_rows']} unique={rep['n_unique_target_ids']} "
          f"exact_dupes={rep['n_exact_duplicates']} failures={rep['n_failures']}")
    if rep["failures_by_kind"]:
        print("  failures_by_kind:", json.dumps(rep["failures_by_kind"], sort_keys=True))
        for f in rep["failures"][:args.max_failures]:
            print(f"  {f['path']}:{f['line']} {f['kind']} target={f['target_id']} -- {f['message']}")
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
