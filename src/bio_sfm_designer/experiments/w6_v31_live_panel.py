"""Validate and capture one provenance-hardened W6-v3.1 live shadow panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..loop.providers import (
    call_provider_with_metadata,
    get_orchestration_provider,
)
from .w6_v2_shadow_panel import (
    _load_json,
    _load_jsonl,
    _sha256_file,
    _sha256_text,
)
from .w6_v3_hypothesis_only import RESPONSE_SCHEMA, _validate_request_records
from .w6_v3_prospective_panel import _contract_view, _validate_digest
from .w6_v31_transport_panel import load_and_validate_panel


SCOPE_SCHEMA = "w6_v31_live_scope_v1"
CAPTURE_SCHEMA = "w6_v31_live_capture_v1"
RECEIPT_SCHEMA = "w6_v31_live_receipt_v1"
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
    "capture_transport_metadata",
    "require_clean_worktree",
    "require_component_hash_match",
    "execution_components",
    "live_execution_authorized",
    "approval_basis",
    "review_required_before_scoring",
    "reviewer_provider_independence_required",
    "recommendations_may_be_applied",
    "compute_submission_allowed",
    "additional_provider_calls_authorized",
}
_COMPONENT_FIELDS = {"path", "sha256"}
_REQUIRED_COMPONENT_PATHS = {
    "src/bio_sfm_designer/loop/providers.py",
    "src/bio_sfm_designer/experiments/w6_v2_shadow_panel.py",
    "src/bio_sfm_designer/experiments/w6_v3_hypothesis_only.py",
    "src/bio_sfm_designer/experiments/w6_v31_transport_panel.py",
    "src/bio_sfm_designer/experiments/w6_v31_live_panel.py",
}
_REQUIRED_TRUE = {
    "one_call_per_case",
    "one_shot",
    "credential_hygiene_attested",
    "capture_transport_metadata",
    "require_clean_worktree",
    "require_component_hash_match",
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
_OUTPUT_LIMIT_STOP_REASONS = {
    "length",
    "max_output_tokens",
    "max_tokens",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content)
    os.replace(str(temporary), str(path))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    _atomic_write(path, "".join(_canonical_json(row) + "\n" for row in records))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        text=True,
    ).strip()


def _git_porcelain(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(repo_root),
        text=True,
    )


def _safe_source_name(provider: str, model: str) -> str:
    raw = f"live_shadow_{provider}_{model}_{datetime.now(timezone.utc):%Y%m%d}"
    return "".join(
        character
        if character.isalnum() or character in "-_"
        else "_"
        for character in raw
    )


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


def _validate_components(
    components: Any,
    *,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    if not isinstance(components, list) or not components:
        raise ValueError("execution_components must be a non-empty list")
    observed = []
    paths = set()
    for component in components:
        if not isinstance(component, dict) or set(component) != _COMPONENT_FIELDS:
            raise ValueError("execution component has an invalid contract")
        raw_path = component["path"]
        if raw_path in paths:
            raise ValueError("execution component paths must be unique")
        paths.add(raw_path)
        path = _resolve_repo_path(
            repo_root,
            raw_path,
            label="execution component path",
        )
        expected_sha256 = _validate_digest(
            component["sha256"],
            label=f"execution component SHA-256 ({raw_path})",
        )
        observed_sha256 = _sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise ValueError(f"execution component SHA-256 mismatch: {raw_path}")
        observed.append(
            {
                "path": raw_path,
                "expected_sha256": expected_sha256,
                "observed_sha256": observed_sha256,
            }
        )
    if paths != _REQUIRED_COMPONENT_PATHS:
        raise ValueError("execution component set is incomplete or overbroad")
    return observed


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
    List[Dict[str, Any]],
]:
    """Validate the frozen W6-v3.1 scope without constructing a provider."""

    observed_scope_sha256 = _sha256_file(scope_path)
    if expected_scope_sha256 is not None:
        expected = _validate_digest(
            expected_scope_sha256,
            label="expected_scope_sha256",
        )
        if observed_scope_sha256 != expected:
            raise ValueError("approved W6-v3.1 scope SHA-256 mismatch")
    scope = _load_json(scope_path)
    if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
        raise ValueError("W6-v3.1 scope fields do not match the frozen schema")
    if scope["schema_version"] != SCOPE_SCHEMA:
        raise ValueError(f"scope schema_version must be {SCOPE_SCHEMA}")
    for key in (
        "scope_id",
        "frozen_at",
        "purpose",
        "panel_id",
        "provider",
        "model",
    ):
        if not isinstance(scope[key], str) or not scope[key].strip():
            raise ValueError(f"scope.{key} must be non-empty")
    if scope["provider"] != "anthropic" or scope["model"] != "claude-opus-4-8":
        raise ValueError("W6-v3.1 must preserve the baseline provider and model")
    if scope["mode"] != "shadow":
        raise ValueError("W6-v3.1 mode must be shadow")
    if scope["max_output_tokens_per_call"] != 512:
        raise ValueError("W6-v3.1 output cap must be exactly 512")
    if scope["sdk_retries_per_call"] != 0:
        raise ValueError("W6-v3.1 SDK retries must be zero")
    if scope["temperature_override"] is not None:
        raise ValueError("temperature override is forbidden")
    if any(scope[key] is not True for key in _REQUIRED_TRUE):
        raise ValueError("W6-v3.1 scope is missing a required true flag")
    if any(scope[key] is not False for key in _REQUIRED_FALSE):
        raise ValueError("W6-v3.1 scope is missing a required false flag")
    authorized = scope["live_execution_authorized"]
    if not isinstance(authorized, bool):
        raise ValueError("live_execution_authorized must be boolean")
    approval_basis = scope["approval_basis"]
    if authorized:
        if not isinstance(approval_basis, str) or not approval_basis.strip():
            raise ValueError("authorized scope requires a non-empty approval_basis")
    elif approval_basis is not None:
        raise ValueError("unauthorized scope must set approval_basis=null")

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
        raise ValueError("W6-v3.1 scope panel SHA-256 mismatch")
    if _sha256_file(request_path) != scope["request_sha256"]:
        raise ValueError("W6-v3.1 scope request SHA-256 mismatch")
    panel, _, _ = load_and_validate_panel(panel_path, repo_root=repo_root)
    if panel["panel_id"] != scope["panel_id"]:
        raise ValueError("W6-v3.1 scope panel id mismatch")
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
    component_audit = _validate_components(
        scope["execution_components"],
        repo_root=repo_root,
    )
    return (
        scope,
        panel,
        requests,
        panel_path,
        request_path,
        component_audit,
    )


def capture_live_panel(
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
    """Capture one approved W6-v3.1 panel with complete transport metadata."""

    if any(path.exists() for path in (capture_path, responses_path, receipt_path)):
        raise FileExistsError(
            "live outputs already exist; overwrite and resume are forbidden"
        )
    (
        scope,
        panel,
        requests,
        panel_path,
        request_path,
        component_audit,
    ) = load_and_validate_scope(
        scope_path,
        repo_root=repo_root,
        expected_scope_sha256=approved_scope_sha256,
    )
    if not scope["live_execution_authorized"]:
        raise PermissionError("W6-v3.1 live execution is not authorized")
    worktree_porcelain = _git_porcelain(repo_root)
    if worktree_porcelain:
        raise RuntimeError("W6-v3.1 live execution requires a clean worktree")

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
            "max_output_tokens": 512,
            "started_at": _utc_now(),
            "completed_at": None,
            "latency_seconds": None,
            "status": "attempt_started",
            "raw_response": None,
            "response_sha256": None,
            "input_tokens": None,
            "output_tokens": None,
            "stop_reason": None,
            "transport_metadata_complete": False,
            "output_limit_stop": False,
            "error_type": None,
            "http_status": None,
            "applied": False,
        }
        capture_rows.append(row)
        _write_jsonl(capture_path, capture_rows)
        started = time.monotonic()
        try:
            result = call_provider_with_metadata(provider, request["prompt"])
            row["raw_response"] = result.text
            row["response_sha256"] = _sha256_text(result.text)
            row["input_tokens"] = result.input_tokens
            row["output_tokens"] = result.output_tokens
            row["stop_reason"] = result.stop_reason
            row["transport_metadata_complete"] = (
                isinstance(result.input_tokens, int)
                and isinstance(result.output_tokens, int)
                and isinstance(result.stop_reason, str)
                and bool(result.stop_reason.strip())
            )
            row["output_limit_stop"] = (
                isinstance(result.stop_reason, str)
                and result.stop_reason.lower() in _OUTPUT_LIMIT_STOP_REASONS
            )
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
    metadata_complete = sum(
        row["transport_metadata_complete"] for row in capture_rows
    )
    output_limit_stops = sum(row["output_limit_stop"] for row in capture_rows)
    responses_written = False
    if failed == 0 and metadata_complete == len(capture_rows):
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

    if failed:
        status = "w6_v31_live_capture_incomplete_no_retry"
    elif metadata_complete != len(capture_rows):
        status = "w6_v31_live_capture_incomplete_transport_metadata"
    else:
        status = "w6_v31_live_capture_complete_pending_review"
    input_counts = [
        row["input_tokens"]
        for row in capture_rows
        if isinstance(row["input_tokens"], int)
    ]
    output_counts = [
        row["output_tokens"]
        for row in capture_rows
        if isinstance(row["output_tokens"], int)
    ]
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "scope_id": scope["scope_id"],
        "scope_path": str(scope_path),
        "scope_sha256": scope_sha256,
        "panel_id": panel["panel_id"],
        "status": status,
        "source_commit": source_commit,
        "source_worktree_clean": True,
        "source_worktree_porcelain_sha256": hashlib.sha256(
            worktree_porcelain.encode("utf-8")
        ).hexdigest(),
        "execution_components": component_audit,
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
        "max_output_tokens_per_call": 512,
        "approved_call_count": scope["approved_call_count"],
        "attempted_calls": len(capture_rows),
        "succeeded_calls": succeeded,
        "failed_calls": failed,
        "transport_metadata_complete_calls": metadata_complete,
        "output_limit_stop_calls": output_limit_stops,
        "total_input_tokens": (
            sum(input_counts) if len(input_counts) == len(capture_rows) else None
        ),
        "total_output_tokens": (
            sum(output_counts) if len(output_counts) == len(capture_rows) else None
        ),
        "sdk_retries_per_call": 0,
        "api_calls": len(capture_rows),
        "provider_calls": len(capture_rows),
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "approval_basis": scope["approval_basis"],
        "approval_consumed": True,
        "credential_hygiene_attested": True,
        "independent_from_w6_v2_and_w6_v3": True,
        "independent_review_pending": responses_written,
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
        description="validate or capture the W6-v3.1 live shadow panel"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v31_live_scope.json"),
    )

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v31_live_scope.json"),
    )
    capture_parser.add_argument("--approved-scope-sha256", required=True)
    capture_parser.add_argument("--capture", type=_path, required=True)
    capture_parser.add_argument("--responses", type=_path, required=True)
    capture_parser.add_argument("--receipt", type=_path, required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "validate":
        scope, panel, requests, _, _, _ = load_and_validate_scope(
            args.scope,
            repo_root=repo_root,
        )
        print(
            f"status=w6_v31_scope_valid scope_id={scope['scope_id']} "
            f"provider={scope['provider']} model={scope['model']} "
            f"calls={len(requests)} cases={panel['case_count']} "
            f"authorized={str(scope['live_execution_authorized']).lower()} "
            f"scope_sha256={_sha256_file(args.scope)} api_calls=0"
        )
        return 0

    scope, _, _, _, _, _ = load_and_validate_scope(
        args.scope,
        repo_root=repo_root,
        expected_scope_sha256=args.approved_scope_sha256,
    )
    if not scope["live_execution_authorized"]:
        raise PermissionError("W6-v3.1 live execution is not authorized")
    provider = get_orchestration_provider(
        scope["provider"],
        model=scope["model"],
        max_output_tokens=scope["max_output_tokens_per_call"],
        credential_hygiene_attested=scope["credential_hygiene_attested"],
    )
    receipt = capture_live_panel(
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
        f"metadata_complete={receipt['transport_metadata_complete_calls']} "
        f"output_limit_stops={receipt['output_limit_stop_calls']} "
        "retries=0 applied=0"
    )
    return 0 if receipt["status"].endswith("pending_review") else 1


if __name__ == "__main__":
    raise SystemExit(main())
