"""Validate and capture one hash-bound prospective W6-v3 live shadow panel."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..loop.providers import get_orchestration_provider, is_live_provider
from .w6_v2_live_shadow_panel import (
    _git_head,
    _safe_source_name,
    _utc_now,
    _write_json,
    _write_jsonl,
)
from .w6_v2_shadow_panel import (
    _load_json,
    _load_jsonl,
    _sha256_file,
    _sha256_text,
)
from .w6_v3_hypothesis_only import RESPONSE_SCHEMA, _validate_request_records
from .w6_v3_prospective_panel import _contract_view, load_and_validate_panel


SCOPE_SCHEMA = "w6_v3_prospective_live_scope_v1"
CAPTURE_SCHEMA = "w6_v3_prospective_live_capture_v1"
RECEIPT_SCHEMA = "w6_v3_prospective_live_receipt_v1"
_SCOPE_FIELDS = {
    "schema_version",
    "scope_id",
    "frozen_at",
    "purpose",
    "panel_path",
    "panel_id",
    "panel_sha256",
    "request_path",
    "request_sha256",
    "provider",
    "model",
    "provider_selection_rationale",
    "mode",
    "approved_call_count",
    "max_output_tokens_per_call",
    "sdk_retries_per_call",
    "temperature_override",
    "one_call_per_case",
    "one_shot",
    "resume_allowed",
    "overwrite_allowed",
    "credential_hygiene_attested",
    "live_execution_authorized",
    "approval_basis",
    "review_required_before_scoring",
    "reviewer_provider_independence_required",
    "recommendations_may_be_applied",
    "compute_submission_allowed",
    "additional_provider_calls_authorized",
}
_REQUIRED_TRUE = {
    "one_call_per_case",
    "one_shot",
    "credential_hygiene_attested",
    "live_execution_authorized",
    "review_required_before_scoring",
    "reviewer_provider_independence_required",
}
_REQUIRED_FALSE = {
    "resume_allowed",
    "overwrite_allowed",
    "recommendations_may_be_applied",
    "compute_submission_allowed",
    "additional_provider_calls_authorized",
}


def _resolve_repo_path(repo_root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} must be relative to the repository")
    root = repo_root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{label} escapes the repository")
    return resolved


def _validate_digest(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def load_and_validate_scope(
    scope_path: Path,
    *,
    repo_root: Path,
    expected_scope_sha256: Optional[str] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    List[Dict[str, Any]],
    Path,
    Path,
]:
    """Validate the exact live scope without constructing a provider."""

    observed_scope_sha256 = _sha256_file(scope_path)
    if expected_scope_sha256 is not None:
        expected = _validate_digest(
            expected_scope_sha256,
            label="expected_scope_sha256",
        )
        if observed_scope_sha256 != expected:
            raise ValueError("approved live scope SHA-256 mismatch")
    scope = _load_json(scope_path)
    if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
        raise ValueError("live scope fields do not match the frozen schema")
    if scope["schema_version"] != SCOPE_SCHEMA:
        raise ValueError(f"scope schema_version must be {SCOPE_SCHEMA}")
    for key in (
        "scope_id",
        "frozen_at",
        "purpose",
        "panel_id",
        "provider",
        "model",
        "provider_selection_rationale",
        "approval_basis",
    ):
        if not isinstance(scope[key], str) or not scope[key].strip():
            raise ValueError(f"scope.{key} must be a non-empty string")
    if scope["mode"] != "shadow":
        raise ValueError("live scope mode must be shadow")
    if not is_live_provider(scope["provider"]):
        raise ValueError("live scope provider must be network-backed")
    if any(scope[key] is not True for key in _REQUIRED_TRUE):
        raise ValueError("live scope is missing a required true safety flag")
    if any(scope[key] is not False for key in _REQUIRED_FALSE):
        raise ValueError("live scope is missing a required false safety flag")
    if scope["temperature_override"] is not None:
        raise ValueError("temperature override is forbidden")
    if scope["sdk_retries_per_call"] != 0:
        raise ValueError("SDK retries must be zero")
    max_tokens = scope["max_output_tokens_per_call"]
    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or not 1 <= max_tokens <= 1024
    ):
        raise ValueError("max_output_tokens_per_call must be in [1, 1024]")

    panel_path = _resolve_repo_path(
        repo_root,
        scope["panel_path"],
        label="panel_path",
    )
    request_path = _resolve_repo_path(
        repo_root,
        scope["request_path"],
        label="request_path",
    )
    if _sha256_file(panel_path) != scope["panel_sha256"]:
        raise ValueError("live scope panel SHA-256 mismatch")
    if _sha256_file(request_path) != scope["request_sha256"]:
        raise ValueError("live scope request SHA-256 mismatch")

    panel, _ = load_and_validate_panel(panel_path, repo_root=repo_root)
    if panel["panel_id"] != scope["panel_id"]:
        raise ValueError("live scope panel id mismatch")
    requests = _load_jsonl(request_path)
    contract = _contract_view(panel, panel_path)
    _validate_request_records(contract, panel, panel_path, requests)
    approved_calls = scope["approved_call_count"]
    if (
        not isinstance(approved_calls, int)
        or isinstance(approved_calls, bool)
        or approved_calls != panel["case_count"]
        or approved_calls != len(requests)
    ):
        raise ValueError("approved call count must equal the frozen case count")
    return scope, panel, requests, panel_path, request_path


def capture_prospective_live_panel(
    *,
    provider: Any,
    scope_path: Path,
    capture_path: Path,
    responses_path: Path,
    receipt_path: Path,
    repo_root: Path,
    approved_scope_sha256: str,
    source_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """Attempt each scope-bound prompt once and preserve no-effect outputs."""

    if any(path.exists() for path in (capture_path, responses_path, receipt_path)):
        raise FileExistsError(
            "live outputs already exist; overwrite and automatic resume are forbidden"
        )
    scope, panel, requests, panel_path, request_path = load_and_validate_scope(
        scope_path,
        repo_root=repo_root,
        expected_scope_sha256=approved_scope_sha256,
    )
    source_commit = source_commit or _git_head(repo_root)
    scope_sha256 = _sha256_file(scope_path)
    response_source = _safe_source_name(scope["provider"], scope["model"])
    capture_rows: List[Dict[str, Any]] = []

    for index, request in enumerate(requests, 1):
        row: Dict[str, Any] = {
            "schema_version": CAPTURE_SCHEMA,
            "scope_id": scope["scope_id"],
            "scope_sha256": scope_sha256,
            "call_index": index,
            "case_id": request["case_id"],
            "contract_sha256": request["contract_sha256"],
            "panel_sha256": request["panel_sha256"],
            "prompt_sha256": request["prompt_sha256"],
            "provider": scope["provider"],
            "model": scope["model"],
            "mode": "shadow",
            "attempt_number": 1,
            "retry_count": 0,
            "max_output_tokens": scope["max_output_tokens_per_call"],
            "started_at": _utc_now(),
            "completed_at": None,
            "latency_seconds": None,
            "status": "attempt_started",
            "raw_response": None,
            "response_sha256": None,
            "error_type": None,
            "http_status": None,
            "applied": False,
        }
        capture_rows.append(row)
        _write_jsonl(capture_path, capture_rows)
        started = time.monotonic()
        try:
            raw = provider(request["prompt"])
            if not isinstance(raw, str):
                raise TypeError("provider returned a non-string response")
            row["raw_response"] = raw
            row["response_sha256"] = _sha256_text(raw)
            row["status"] = "succeeded"
        except Exception as exc:
            row["status"] = "provider_error"
            row["error_type"] = type(exc).__name__
            status_code = getattr(exc, "status_code", None)
            row["http_status"] = status_code if isinstance(status_code, int) else None
        row["latency_seconds"] = round(time.monotonic() - started, 6)
        row["completed_at"] = _utc_now()
        _write_jsonl(capture_path, capture_rows)

    succeeded = sum(row["status"] == "succeeded" for row in capture_rows)
    failed = len(capture_rows) - succeeded
    responses_written = False
    if failed == 0:
        responses = [
            {
                "schema_version": RESPONSE_SCHEMA,
                "response_source": response_source,
                "case_id": row["case_id"],
                "contract_sha256": row["contract_sha256"],
                "panel_sha256": row["panel_sha256"],
                "prompt_sha256": row["prompt_sha256"],
                "raw_response": row["raw_response"],
                "response_sha256": row["response_sha256"],
                "review": {
                    "status": "pending",
                    "scope_tag": "unreviewed",
                    "grounded": False,
                    "actionable": False,
                    "incremental_value": False,
                    "notes": "Provider-independent offline rubric review pending.",
                },
            }
            for row in capture_rows
        ]
        _write_jsonl(responses_path, responses)
        responses_written = True

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "scope_id": scope["scope_id"],
        "scope_path": str(scope_path),
        "scope_sha256": scope_sha256,
        "panel_id": panel["panel_id"],
        "status": (
            "prospective_live_capture_complete_pending_review"
            if failed == 0
            else "prospective_live_capture_incomplete_no_retry"
        ),
        "source_commit": source_commit,
        "panel_path": scope["panel_path"],
        "panel_sha256": _sha256_file(panel_path),
        "request_path": scope["request_path"],
        "request_sha256": _sha256_file(request_path),
        "capture_path": str(capture_path),
        "capture_sha256": _sha256_file(capture_path),
        "responses_path": str(responses_path) if responses_written else None,
        "responses_sha256": (
            _sha256_file(responses_path) if responses_written else None
        ),
        "provider": scope["provider"],
        "model": scope["model"],
        "mode": "shadow",
        "max_output_tokens_per_call": scope["max_output_tokens_per_call"],
        "approved_call_count": scope["approved_call_count"],
        "attempted_calls": len(capture_rows),
        "succeeded_calls": succeeded,
        "failed_calls": failed,
        "sdk_retries_per_call": 0,
        "api_calls": len(capture_rows),
        "provider_calls": len(capture_rows),
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "approval_basis": scope["approval_basis"],
        "approval_consumed": True,
        "credential_hygiene_attested": True,
        "independent_from_w6_v2": True,
        "independent_review_pending": failed == 0,
        "prospective_live_validation_complete": False,
        "live_execution_authorized_for_additional_calls": False,
        "m7_complete": False,
    }
    _write_json(receipt_path, receipt)
    return receipt


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="validate or capture the prospective W6-v3 live shadow panel"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v3_prospective_live_scope.json"),
    )

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v3_prospective_live_scope.json"),
    )
    capture_parser.add_argument("--approved-scope-sha256", required=True)
    capture_parser.add_argument("--capture", type=_path, required=True)
    capture_parser.add_argument("--responses", type=_path, required=True)
    capture_parser.add_argument("--receipt", type=_path, required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.command == "validate":
        scope, panel, requests, _, _ = load_and_validate_scope(
            args.scope,
            repo_root=repo_root,
        )
        print(
            f"status=live_scope_valid scope_id={scope['scope_id']} "
            f"provider={scope['provider']} model={scope['model']} "
            f"calls={len(requests)} cases={panel['case_count']} "
            f"scope_sha256={_sha256_file(args.scope)} api_calls=0"
        )
        return 0

    scope, _, _, _, _ = load_and_validate_scope(
        args.scope,
        repo_root=repo_root,
    )
    provider = get_orchestration_provider(
        scope["provider"],
        model=scope["model"],
        max_output_tokens=scope["max_output_tokens_per_call"],
        credential_hygiene_attested=scope["credential_hygiene_attested"],
    )
    receipt = capture_prospective_live_panel(
        provider=provider,
        scope_path=args.scope,
        capture_path=args.capture,
        responses_path=args.responses,
        receipt_path=args.receipt,
        repo_root=repo_root,
        approved_scope_sha256=args.approved_scope_sha256,
    )
    print(
        f"status={receipt['status']} attempted={receipt['attempted_calls']} "
        f"succeeded={receipt['succeeded_calls']} failed={receipt['failed_calls']} "
        "retries=0 applied=0"
    )
    return 0 if receipt["failed_calls"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
