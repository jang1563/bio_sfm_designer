#!/usr/bin/env python3
"""Aggregate per-candidate Chai-1 batch records into one JSONL artifact."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


def _record_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    complex_target_id = rec.get("complex_target_id")
    target_id = rec.get("target_id")
    predictor_id = rec.get("predictor_id") or rec.get("refolder")
    return (str(complex_target_id or ""), str(target_id or ""), str(predictor_id or ""))


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open() as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            yield line_no, payload


def _manifest_for_record(record_path: Path) -> dict[str, Any] | None:
    manifest = record_path.with_name("input_manifest.json")
    if not manifest.exists():
        return None
    with manifest.open() as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def aggregate_batch_records(
    batch_dir: Path,
    *,
    pattern: str = "*/record.jsonl",
    expected_predictor_id: str | None = "chai1_complex",
    min_records: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    record_files = sorted(batch_dir.glob(pattern)) if batch_dir.exists() else []
    failures: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_rows: list[dict[str, Any]] = []
    records_by_predictor: dict[str, int] = {}
    records_by_complex_target: dict[str, int] = {}

    if not batch_dir.exists():
        failures.append({"kind": "missing_batch_dir", "path": str(batch_dir)})

    for path in record_files:
        rows_in_file = 0
        try:
            rows = list(_read_jsonl(path))
        except (json.JSONDecodeError, ValueError) as exc:
            failures.append({"kind": "bad_record_file", "path": str(path), "message": str(exc)})
            continue
        manifest = _manifest_for_record(path)
        for line_no, rec in rows:
            rows_in_file += 1
            key = _record_key(rec)
            complex_target_id, target_id, predictor_id = key
            if not complex_target_id or not target_id or not predictor_id:
                failures.append({
                    "kind": "missing_record_identity",
                    "path": str(path),
                    "line": line_no,
                    "complex_target_id": complex_target_id or None,
                    "target_id": target_id or None,
                    "predictor_id": predictor_id or None,
                })
                continue
            if expected_predictor_id and predictor_id != expected_predictor_id:
                failures.append({
                    "kind": "unexpected_predictor_id",
                    "path": str(path),
                    "line": line_no,
                    "predictor_id": predictor_id,
                    "expected_predictor_id": expected_predictor_id,
                })
                continue
            if _finite_float(rec.get("pae_interaction")) is None:
                failures.append({"kind": "missing_pae_interaction", "path": str(path), "line": line_no})
                continue
            if key in by_key:
                failures.append({
                    "kind": "duplicate_record_key",
                    "path": str(path),
                    "line": line_no,
                    "first_path": by_key[key].get("_aggregate_source_path"),
                    "complex_target_id": complex_target_id,
                    "target_id": target_id,
                    "predictor_id": predictor_id,
                })
                continue
            saved = dict(rec)
            saved["_aggregate_source_path"] = str(path)
            by_key[key] = saved
            records_by_predictor[predictor_id] = records_by_predictor.get(predictor_id, 0) + 1
            records_by_complex_target[complex_target_id] = records_by_complex_target.get(complex_target_id, 0) + 1
            source_rows.append({
                "record_path": str(path),
                "line": line_no,
                "complex_target_id": complex_target_id,
                "target_id": target_id,
                "predictor_id": predictor_id,
                "selected_index": None if manifest is None else manifest.get("selected_index"),
                "pae_interaction": rec.get("pae_interaction"),
                "lrmsd": rec.get("lrmsd"),
                "truth_correct": rec.get("truth", {}).get("correct") if isinstance(rec.get("truth"), dict) else None,
            })
        if rows_in_file == 0:
            failures.append({"kind": "empty_record_file", "path": str(path)})

    records = []
    for key in sorted(by_key):
        rec = dict(by_key[key])
        rec.pop("_aggregate_source_path", None)
        records.append(rec)

    n_records = len(records)
    ok = not failures and n_records >= min_records
    if failures:
        status = "record_failures"
    elif n_records < min_records:
        status = "insufficient_records"
    else:
        status = "ready"
    report = {
        "ok": ok,
        "status": status,
        "batch_dir": str(batch_dir),
        "pattern": pattern,
        "expected_predictor_id": expected_predictor_id,
        "min_records": min_records,
        "n_record_files": len(record_files),
        "n_records": n_records,
        "records_by_predictor": dict(sorted(records_by_predictor.items())),
        "records_by_complex_target": dict(sorted(records_by_complex_target.items())),
        "failures": failures,
        "source_rows": source_rows,
    }
    return records, report


def write_jsonl(records: Iterable[dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for rec in records:
            handle.write(json.dumps(rec, sort_keys=True) + "\n")


def write_report(report: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="aggregate Chai-1 batch record.jsonl files")
    parser.add_argument("--batch-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--pattern", default="*/record.jsonl")
    parser.add_argument("--expected-predictor-id", default="chai1_complex")
    parser.add_argument("--min-records", type=int, default=1)
    parser.add_argument("--strict", action="store_true", help="return non-zero when report.ok is false")
    args = parser.parse_args(argv)

    records, report = aggregate_batch_records(
        args.batch_dir,
        pattern=args.pattern,
        expected_predictor_id=args.expected_predictor_id,
        min_records=args.min_records,
    )
    write_jsonl(records, args.out)
    write_report(report, args.report)
    print(json.dumps({"out": str(args.out), "report": str(args.report), **report}, sort_keys=True))
    return 0 if report["ok"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
