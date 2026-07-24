"""Apply hash-bound offline reviews to W6-v3.1 live responses."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .w6_v2_live_shadow_panel import _write_json, _write_jsonl
from .w6_v2_shadow_panel import (
    _load_json,
    _load_jsonl,
    _sha256_file,
    _validate_review,
)
from .w6_v31_transport_panel import (
    load_and_validate_panel,
    score_response_records,
)


ANNOTATION_SCHEMA = "w6_v31_review_annotations_v1"
RECEIPT_SCHEMA = "w6_v31_review_receipt_v1"
_ANNOTATION_FIELDS = {
    "schema_version",
    "source_panel_sha256",
    "source_request_sha256",
    "source_responses_sha256",
    "reviewer",
    "records",
}
_REVIEWER_FIELDS = {
    "identity",
    "type",
    "provider_independent",
    "reviewed_at",
}


def apply_review_annotations(
    *,
    panel_path: Path,
    request_path: Path,
    responses_path: Path,
    annotations_path: Path,
    reviewed_responses_path: Path,
    receipt_path: Path,
    repo_root: Path,
) -> Dict[str, Any]:
    """Apply complete reviews after exact W6-v3.1 source validation."""

    if reviewed_responses_path.exists() or receipt_path.exists():
        raise FileExistsError("review outputs already exist; overwrite is forbidden")
    panel, _, _ = load_and_validate_panel(panel_path, repo_root=repo_root)
    pending_score = score_response_records(
        panel_path,
        request_path,
        responses_path,
        repo_root=repo_root,
    )
    responses = _load_jsonl(responses_path)
    annotations = _load_json(annotations_path)
    if not isinstance(annotations, dict) or set(annotations) != _ANNOTATION_FIELDS:
        raise ValueError("annotation fields do not match the W6-v3.1 schema")
    if annotations["schema_version"] != ANNOTATION_SCHEMA:
        raise ValueError(f"annotations must use {ANNOTATION_SCHEMA}")
    source_hashes = {
        "source_panel_sha256": _sha256_file(panel_path),
        "source_request_sha256": _sha256_file(request_path),
        "source_responses_sha256": _sha256_file(responses_path),
    }
    if any(annotations[key] != value for key, value in source_hashes.items()):
        raise ValueError("annotation source SHA-256 mismatch")

    reviewer = annotations["reviewer"]
    if not isinstance(reviewer, dict) or set(reviewer) != _REVIEWER_FIELDS:
        raise ValueError("reviewer metadata has an invalid contract")
    for key in ("identity", "type", "reviewed_at"):
        if not isinstance(reviewer[key], str) or not reviewer[key].strip():
            raise ValueError(f"reviewer.{key} must be non-empty")
    if reviewer["provider_independent"] is not True:
        raise ValueError("reviewer must be independent from the captured provider")

    cases_by_id = {case["case_id"]: case for case in panel["cases"]}
    annotation_rows = annotations["records"]
    if not isinstance(annotation_rows, list):
        raise ValueError("annotation records must be a list")
    annotation_by_id: Dict[str, Dict[str, Any]] = {}
    for row in annotation_rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "review"}:
            raise ValueError("each annotation must contain case_id and review")
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("annotation case_id must be non-empty")
        if case_id in annotation_by_id:
            raise ValueError("annotation case ids must be unique")
        if case_id not in cases_by_id:
            raise ValueError(f"unknown annotation case id: {case_id}")
        review = _validate_review(row["review"])
        if review["status"] != "complete":
            raise ValueError("all applied reviews must be complete")
        if review["scope_tag"] not in cases_by_id[case_id]["expected"][
            "allowed_scope_tags"
        ]:
            raise ValueError(f"{case_id}: review scope is not allowed")
        annotation_by_id[case_id] = review

    response_ids = [row.get("case_id") for row in responses]
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("captured response case ids must be unique")
    if set(response_ids) != set(annotation_by_id):
        raise ValueError("annotations must cover every response exactly once")
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
        "schema_version": RECEIPT_SCHEMA,
        "status": "w6_v31_offline_independent_review_complete",
        "panel_id": panel["panel_id"],
        "panel_path": str(panel_path),
        "panel_sha256": source_hashes["source_panel_sha256"],
        "request_path": str(request_path),
        "request_sha256": source_hashes["source_request_sha256"],
        "source_responses_path": str(responses_path),
        "source_responses_sha256": source_hashes["source_responses_sha256"],
        "annotations_path": str(annotations_path),
        "annotations_sha256": _sha256_file(annotations_path),
        "reviewed_responses_path": str(reviewed_responses_path),
        "reviewed_responses_sha256": _sha256_file(reviewed_responses_path),
        "case_count": len(reviewed),
        "reviewer": reviewer,
        "raw_responses_modified": False,
        "pre_review_schema_acceptance_count": pending_score["metrics"][
            "schema_acceptance_count"
        ],
        "pre_review_authority_violation_count": pending_score["metrics"][
            "control_plane_violation_count"
        ],
        "api_calls": 0,
        "provider_calls": 0,
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "prospective_live_validation_complete": False,
    }
    _write_json(receipt_path, receipt)
    return receipt


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="apply hash-bound W6-v3.1 rubric annotations"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    parser.add_argument(
        "--panel",
        type=_path,
        default=Path("configs/w6_v31_transport_panel.json"),
    )
    parser.add_argument(
        "--requests",
        type=_path,
        default=Path("results/w6_v31_transport_requests.jsonl"),
    )
    parser.add_argument("--responses", type=_path, required=True)
    parser.add_argument("--annotations", type=_path, required=True)
    parser.add_argument("--reviewed-responses", type=_path, required=True)
    parser.add_argument("--receipt", type=_path, required=True)
    args = parser.parse_args(argv)
    receipt = apply_review_annotations(
        panel_path=args.panel,
        request_path=args.requests,
        responses_path=args.responses,
        annotations_path=args.annotations,
        reviewed_responses_path=args.reviewed_responses,
        receipt_path=args.receipt,
        repo_root=args.repo_root.resolve(),
    )
    print(
        f"status={receipt['status']} cases={receipt['case_count']} "
        "provider_calls=0 applied=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
