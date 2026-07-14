"""Validate and attach W2c stage metadata to generated candidates or predictor records."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(value)
    return rows


def _write_jsonl_atomic(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _validate_scope(stage: str, namespace: str, complex_target_id: str, expected_count: int) -> str:
    if stage != "threshold_learning":
        raise ValueError("W2c packet currently permits threshold_learning only")
    if namespace != "w2c-fit-learn-v1":
        raise ValueError("W2c threshold-learning namespace must be w2c-fit-learn-v1")
    if not complex_target_id or expected_count != 60:
        raise ValueError("W2c threshold-learning metadata requires one target and exactly 60 rows")
    return f"{namespace}-{complex_target_id}-"


def _validate_ids(rows: List[Dict[str, Any]], prefix: str, expected_count: int) -> List[str]:
    identifiers = [str(row.get("id") or row.get("target_id") or "") for row in rows]
    if len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} rows, observed {len(rows)}")
    if len(set(identifiers)) != expected_count or any(not value.startswith(prefix) for value in identifiers):
        raise ValueError("W2c candidate IDs are missing, duplicated, or outside the locked namespace")
    return identifiers


def annotate_candidates(
    path: str,
    *,
    stage: str,
    namespace: str,
    complex_target_id: str,
    expected_count: int,
) -> Dict[str, Any]:
    prefix = _validate_scope(stage, namespace, complex_target_id, expected_count)
    rows = _load_jsonl(path)
    _validate_ids(rows, prefix, expected_count)
    for row in rows:
        if row.get("w2b_stage") or row.get("w2b_seed_namespace"):
            raise ValueError("historical W2b stage metadata is forbidden in W2c candidates")
        meta = row.get("meta")
        if not isinstance(meta, dict) or meta.get("complex_target_id") != complex_target_id:
            raise ValueError("W2c candidate complex_target_id does not match the locked target")
        row["w2c_stage"] = stage
        row["w2c_seed_namespace"] = namespace
        meta["w2c_stage"] = stage
        meta["w2c_seed_namespace"] = namespace
    _write_jsonl_atomic(path, rows)
    return {"kind": "candidates", "path": path, "rows": len(rows), "status": "w2c_metadata_attached"}


def annotate_records(
    path: str,
    candidates_path: str,
    *,
    stage: str,
    namespace: str,
    complex_target_id: str,
    expected_count: int,
) -> Dict[str, Any]:
    prefix = _validate_scope(stage, namespace, complex_target_id, expected_count)
    candidates = _load_jsonl(candidates_path)
    candidate_ids = _validate_ids(candidates, prefix, expected_count)
    for candidate in candidates:
        if candidate.get("w2c_stage") != stage or candidate.get("w2c_seed_namespace") != namespace:
            raise ValueError("candidate file is missing the locked W2c stage metadata")
    rows = _load_jsonl(path)
    record_ids = _validate_ids(rows, prefix, expected_count)
    if set(record_ids) != set(candidate_ids):
        raise ValueError("W2c predictor records do not match the generated candidate IDs")
    for row in rows:
        if row.get("w2b_stage") or row.get("w2b_seed_namespace"):
            raise ValueError("historical W2b stage metadata is forbidden in W2c records")
        if row.get("complex_target_id") != complex_target_id:
            raise ValueError("W2c record complex_target_id does not match the locked target")
        row["w2c_stage"] = stage
        row["w2c_seed_namespace"] = namespace
    _write_jsonl_atomic(path, rows)
    return {"kind": "records", "path": path, "rows": len(rows), "status": "w2c_metadata_attached"}


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("candidates", "records"), required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--complex-target-id", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    args = parser.parse_args(argv)
    if args.kind == "candidates":
        report = annotate_candidates(
            args.path,
            stage=args.stage,
            namespace=args.namespace,
            complex_target_id=args.complex_target_id,
            expected_count=args.expected_count,
        )
    else:
        if not args.candidates:
            parser.error("--candidates is required for record annotation")
        report = annotate_records(
            args.path,
            args.candidates,
            stage=args.stage,
            namespace=args.namespace,
            complex_target_id=args.complex_target_id,
            expected_count=args.expected_count,
        )
    print(f"status={report['status']} kind={report['kind']} rows={report['rows']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
