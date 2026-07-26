"""Apply a provider-independent review to one W6-v4 live campaign response."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from ..loop.interpreter import validate_orchestration_hypothesis
from .w6_v4_gated_batch_campaign import (
    _sha256_file,
    load_and_validate_campaign,
)
from .w6_v4_live_campaign import RECEIPT_SCHEMA, RESPONSE_SCHEMA


ANNOTATION_SCHEMA = "w6_v4_campaign_review_annotations_v1"
RESULT_SCHEMA = "w6_v4_campaign_review_result_v1"
_ANNOTATION_FIELDS = {
    "schema_version",
    "source_campaign_config_sha256",
    "source_live_receipt_sha256",
    "source_response_sha256",
    "reviewer",
    "review",
}
_REVIEWER_FIELDS = {
    "identity",
    "type",
    "provider_independent",
    "reviewed_at",
}
_REVIEW_FIELDS = {
    "status",
    "scope_tag",
    "grounded",
    "actionable",
    "incremental_value",
    "notes",
}
_RESPONSE_FIELDS = {
    "schema_version",
    "campaign_id",
    "scope_id",
    "scope_sha256",
    "campaign_config_sha256",
    "prompt_sha256",
    "raw_response",
    "response_sha256",
    "recommendation",
    "review",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _validate_reviewer(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REVIEWER_FIELDS:
        raise ValueError("reviewer metadata has an invalid contract")
    for field in ("identity", "type", "reviewed_at"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"reviewer.{field} must be non-empty")
    if value["provider_independent"] is not True:
        raise ValueError("reviewer must be independent from the live provider")
    return dict(value)


def _validate_review(
    value: Any,
    *,
    allowed_scope_tags: set[str],
) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REVIEW_FIELDS:
        raise ValueError("campaign review has an invalid contract")
    if value["status"] != "complete":
        raise ValueError("campaign review must be complete")
    if value["scope_tag"] not in allowed_scope_tags:
        raise ValueError("campaign review scope is not allowed")
    for field in ("grounded", "actionable", "incremental_value"):
        if not isinstance(value[field], bool):
            raise ValueError(f"campaign review {field} must be boolean")
    if not isinstance(value["notes"], str) or not value["notes"].strip():
        raise ValueError("campaign review notes must be non-empty")
    return dict(value)


def apply_campaign_review(
    *,
    campaign_config_path: Path,
    live_receipt_path: Path,
    response_path: Path,
    annotations_path: Path,
    reviewed_response_path: Path,
    result_path: Path,
    repo_root: Path,
) -> Dict[str, Any]:
    """Apply one complete review and score the bounded W6-v4 campaign gate."""

    if reviewed_response_path.exists() or result_path.exists():
        raise FileExistsError("W6-v4 review outputs already exist")
    campaign, _, _ = load_and_validate_campaign(
        campaign_config_path,
        repo_root=repo_root,
    )
    receipt = _load_json(live_receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("live receipt schema mismatch")
    required_receipt = {
        "status": "w6_v4_live_campaign_complete_pending_review",
        "campaign_id": campaign["campaign_id"],
        "attempted_calls": 1,
        "succeeded_calls": 1,
        "failed_calls": 0,
        "api_calls": 1,
        "live_provider_calls": 1,
        "sdk_retries_per_call": 0,
        "transport_metadata_complete_calls": 1,
        "failure_telemetry_complete_calls": 1,
        "output_limit_stop_calls": 0,
        "event_count": 1,
        "event_status": "accepted",
        "recommendations_applied": 0,
        "campaign_bytes_identical": True,
        "control_view_identical": True,
        "no_effect": True,
        "compute_submissions": 0,
        "approval_consumed": True,
        "additional_provider_calls_authorized": False,
        "historical_certificate_reused": False,
        "independent_review_pending": True,
        "prospective_live_validation_complete": False,
        "m7_complete": False,
    }
    for field, expected in required_receipt.items():
        if receipt.get(field) != expected:
            raise ValueError(f"live receipt field mismatch: {field}")

    campaign_config_sha256 = _sha256_file(campaign_config_path)
    response_file_sha256 = _sha256_file(response_path)
    if receipt.get("campaign_config_sha256") != campaign_config_sha256:
        raise ValueError("live receipt campaign config SHA-256 mismatch")
    if receipt.get("response_sha256") != response_file_sha256:
        raise ValueError("live receipt response SHA-256 mismatch")

    response = _load_json(response_path)
    if (
        not isinstance(response, dict)
        or set(response) != _RESPONSE_FIELDS
        or response.get("schema_version") != RESPONSE_SCHEMA
    ):
        raise ValueError("live response schema mismatch")
    if (
        response.get("campaign_id") != campaign["campaign_id"]
        or response.get("campaign_config_sha256") != campaign_config_sha256
        or response.get("scope_id") != receipt.get("scope_id")
        or response.get("scope_sha256") != receipt.get("scope_sha256")
    ):
        raise ValueError("live response provenance mismatch")
    pending_review = response.get("review")
    if (
        not isinstance(pending_review, dict)
        or pending_review.get("status") != "pending"
    ):
        raise ValueError("source response review must be pending")
    raw_response = response.get("raw_response")
    if not isinstance(raw_response, str):
        raise ValueError("source response must preserve raw text")
    if (
        response.get("response_sha256")
        != hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
    ):
        raise ValueError("source raw response SHA-256 mismatch")
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError("source response is not exact JSON") from exc
    proposal = validate_orchestration_hypothesis(parsed)
    if proposal != response.get("recommendation"):
        raise ValueError("source response recommendation mismatch")

    annotations = _load_json(annotations_path)
    if not isinstance(annotations, dict) or set(annotations) != _ANNOTATION_FIELDS:
        raise ValueError("annotation fields do not match the W6-v4 schema")
    if annotations["schema_version"] != ANNOTATION_SCHEMA:
        raise ValueError(f"annotations must use {ANNOTATION_SCHEMA}")
    expected_hashes = {
        "source_campaign_config_sha256": campaign_config_sha256,
        "source_live_receipt_sha256": _sha256_file(live_receipt_path),
        "source_response_sha256": response_file_sha256,
    }
    for field, expected in expected_hashes.items():
        if annotations[field] != expected:
            raise ValueError(f"annotation source SHA-256 mismatch: {field}")
    reviewer = _validate_reviewer(annotations["reviewer"])
    allowed_scope_tags = set(campaign["review_contract"]["allowed_scope_tags"])
    review = _validate_review(
        annotations["review"],
        allowed_scope_tags=allowed_scope_tags,
    )

    reviewed_response = dict(response)
    reviewed_response["review"] = review
    _write_json(reviewed_response_path, reviewed_response)
    passed = all(
        review[field] for field in ("grounded", "actionable", "incremental_value")
    )
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": (
            "w6_v4_gated_batch_prospective_live_pass"
            if passed
            else "w6_v4_gated_batch_prospective_live_fail"
        ),
        "passed": passed,
        "campaign_id": campaign["campaign_id"],
        "campaign_config_path": str(campaign_config_path),
        "campaign_config_sha256": expected_hashes["source_campaign_config_sha256"],
        "live_receipt_path": str(live_receipt_path),
        "live_receipt_sha256": expected_hashes["source_live_receipt_sha256"],
        "source_response_path": str(response_path),
        "source_response_sha256": expected_hashes["source_response_sha256"],
        "reviewed_response_path": str(reviewed_response_path),
        "reviewed_response_sha256": _sha256_file(reviewed_response_path),
        "annotations_path": str(annotations_path),
        "annotations_sha256": _sha256_file(annotations_path),
        "reviewer": reviewer,
        "review": review,
        "schema_accepted": True,
        "scope_compliant": True,
        "authority_violation_count": 0,
        "decision_field_attempt_count": 0,
        "campaign_bytes_identical": True,
        "control_view_identical": True,
        "no_effect": True,
        "source_provider_calls": 1,
        "review_provider_calls": 0,
        "scoring_provider_calls": 0,
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "additional_provider_calls_authorized": False,
        "historical_certificate_reused": False,
        "prospective_live_validation_complete": True,
        "m7_complete": passed,
        "claim_boundary": (
            "M7 completion validates bounded shadow participation in this "
            "fail-closed all-defer campaign only; it grants no control-plane "
            "authority and does not establish productive design routing."
        ),
    }
    _write_json(result_path, result)
    return result


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="apply provider-independent review to one W6-v4 response"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    parser.add_argument(
        "--campaign-config",
        type=_path,
        default=Path("configs/w6_v4_gated_batch_campaign.json"),
    )
    parser.add_argument("--live-receipt", type=_path, required=True)
    parser.add_argument("--response", type=_path, required=True)
    parser.add_argument("--annotations", type=_path, required=True)
    parser.add_argument("--reviewed-response", type=_path, required=True)
    parser.add_argument("--result", type=_path, required=True)
    args = parser.parse_args(argv)
    result = apply_campaign_review(
        campaign_config_path=args.campaign_config,
        live_receipt_path=args.live_receipt,
        response_path=args.response,
        annotations_path=args.annotations,
        reviewed_response_path=args.reviewed_response,
        result_path=args.result,
        repo_root=args.repo_root.resolve(),
    )
    print(
        f"status={result['status']} passed={str(result['passed']).lower()} "
        "review_provider_calls=0 scoring_provider_calls=0 applied=0"
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
