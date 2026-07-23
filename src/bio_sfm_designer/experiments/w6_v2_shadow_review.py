"""Apply hash-bound offline rubric annotations to captured W6-v2 responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .w6_v2_shadow_panel import (
    _load_jsonl,
    _validate_review,
)


ANNOTATION_SCHEMA = "w6_v2_shadow_review_annotations_v1"
REVIEW_RECEIPT_SCHEMA = "w6_v2_shadow_review_receipt_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content)
    os.replace(str(temporary), str(path))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    _atomic_write(path, "".join(_canonical_json(record) + "\n" for record in records))


def apply_review_annotations(
    *,
    responses_path: Path,
    annotations_path: Path,
    reviewed_responses_path: Path,
    receipt_path: Path,
) -> Dict[str, Any]:
    """Replace pending review fields only after exact response-hash validation."""

    if reviewed_responses_path.exists() or receipt_path.exists():
        raise FileExistsError("review outputs already exist; overwrite is forbidden")
    responses = _load_jsonl(responses_path)
    annotations = json.loads(annotations_path.read_text())
    if (
        not isinstance(annotations, dict)
        or annotations.get("schema_version") != ANNOTATION_SCHEMA
    ):
        raise ValueError(f"annotations must use {ANNOTATION_SCHEMA}")
    observed_response_sha256 = _sha256_file(responses_path)
    if annotations.get("source_responses_sha256") != observed_response_sha256:
        raise ValueError("annotation source response SHA-256 mismatch")
    reviewer = annotations.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {
        "identity",
        "type",
        "provider_independent",
        "reviewed_at",
    }:
        raise ValueError("reviewer metadata has an invalid contract")
    if reviewer["provider_independent"] is not True:
        raise ValueError("reviewer must be independent from the captured provider")

    annotation_rows = annotations.get("records")
    if not isinstance(annotation_rows, list):
        raise ValueError("annotation records must be a list")
    annotation_by_id: Dict[str, Dict[str, Any]] = {}
    for row in annotation_rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "review"}:
            raise ValueError("each annotation must contain case_id and review")
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("annotation case_id must be a non-empty string")
        if case_id in annotation_by_id:
            raise ValueError("annotation case ids must be unique")
        review = _validate_review(row["review"])
        if review["status"] != "complete":
            raise ValueError("all applied reviews must be complete")
        annotation_by_id[case_id] = review

    response_ids = [row.get("case_id") for row in responses]
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("captured response case ids must be unique")
    if set(response_ids) != set(annotation_by_id):
        raise ValueError("annotations must cover every captured response exactly once")

    reviewed: List[Dict[str, Any]] = []
    for response in responses:
        pending = response.get("review")
        if not isinstance(pending, dict) or pending.get("status") != "pending":
            raise ValueError(
                f"{response.get('case_id')}: source response review is not pending"
            )
        updated = dict(response)
        updated["review"] = annotation_by_id[response["case_id"]]
        reviewed.append(updated)
    _write_jsonl(reviewed_responses_path, reviewed)

    receipt = {
        "schema_version": REVIEW_RECEIPT_SCHEMA,
        "status": "offline_independent_review_complete",
        "source_responses_path": str(responses_path),
        "source_responses_sha256": observed_response_sha256,
        "annotations_path": str(annotations_path),
        "annotations_sha256": _sha256_file(annotations_path),
        "reviewed_responses_path": str(reviewed_responses_path),
        "reviewed_responses_sha256": _sha256_file(reviewed_responses_path),
        "case_count": len(reviewed),
        "reviewer": reviewer,
        "raw_responses_modified": False,
        "api_calls": 0,
        "provider_calls": 0,
        "recommendations_applied": 0,
    }
    _write_json(receipt_path, receipt)
    return receipt


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="apply hash-bound offline W6-v2 rubric annotations"
    )
    parser.add_argument("--responses", type=_path, required=True)
    parser.add_argument("--annotations", type=_path, required=True)
    parser.add_argument("--reviewed-responses", type=_path, required=True)
    parser.add_argument("--receipt", type=_path, required=True)
    args = parser.parse_args(argv)
    receipt = apply_review_annotations(
        responses_path=args.responses,
        annotations_path=args.annotations,
        reviewed_responses_path=args.reviewed_responses,
        receipt_path=args.receipt,
    )
    print(
        f"status={receipt['status']} cases={receipt['case_count']} "
        "provider_calls=0 applied=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
