"""Capture one explicitly approved W6-v2 live shadow panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..loop.providers import get_orchestration_provider, is_live_provider
from .w6_v2_shadow_panel import (
    RESPONSE_SCHEMA,
    _load_jsonl,
    _validate_request_records,
    load_and_validate_panel,
)


CAPTURE_SCHEMA = "w6_v2_live_shadow_capture_v1"
RECEIPT_SCHEMA = "w6_v2_live_shadow_receipt_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        text=True,
    ).strip()


def _safe_source_name(provider_name: str, model: str) -> str:
    raw = f"live_shadow_{provider_name}_{model}_{datetime.now(timezone.utc):%Y%m%d}"
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in raw)


def capture_live_shadow_panel(
    *,
    provider: Any,
    provider_name: str,
    model: str,
    panel_path: Path,
    request_path: Path,
    capture_path: Path,
    responses_path: Path,
    receipt_path: Path,
    repo_root: Path,
    approved_call_count: int,
    max_output_tokens: int,
    credential_hygiene_attested: bool,
    approval_basis: str,
    source_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """Attempt each frozen prompt once and write a no-effect capture receipt."""

    if not is_live_provider(provider_name):
        raise ValueError("live shadow capture requires a live provider")
    if not model or not model.strip():
        raise ValueError("live shadow capture requires an explicit model")
    if not credential_hygiene_attested:
        raise ValueError("credential hygiene attestation is required")
    if not isinstance(approval_basis, str) or not approval_basis.strip():
        raise ValueError("approval_basis must be a non-empty string")
    if any(path.exists() for path in (capture_path, responses_path, receipt_path)):
        raise FileExistsError(
            "live capture outputs already exist; automatic overwrite or resume is forbidden"
        )

    panel, _ = load_and_validate_panel(panel_path, repo_root=repo_root)
    requests = _load_jsonl(request_path)
    _validate_request_records(panel, panel_path, requests)
    if approved_call_count != len(requests):
        raise ValueError(
            f"approved_call_count must equal frozen request count {len(requests)}"
        )
    if approved_call_count != panel["case_count"]:
        raise ValueError("approved call count does not match the frozen panel")
    if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
        raise ValueError("max_output_tokens must be an integer")
    if not 1 <= max_output_tokens <= 1024:
        raise ValueError("max_output_tokens must be in [1, 1024]")

    source_commit = source_commit or _git_head(repo_root)
    panel_sha256 = _sha256_file(panel_path)
    request_sha256 = _sha256_file(request_path)
    response_source = _safe_source_name(provider_name, model)
    capture_rows: List[Dict[str, Any]] = []

    for index, request in enumerate(requests, 1):
        row: Dict[str, Any] = {
            "schema_version": CAPTURE_SCHEMA,
            "call_index": index,
            "case_id": request["case_id"],
            "panel_sha256": request["panel_sha256"],
            "prompt_sha256": request["prompt_sha256"],
            "provider": provider_name,
            "model": model,
            "mode": "shadow",
            "attempt_number": 1,
            "retry_count": 0,
            "max_output_tokens": max_output_tokens,
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
                    "notes": "Independent offline rubric review pending.",
                },
            }
            for row in capture_rows
        ]
        _write_jsonl(responses_path, responses)
        responses_written = True

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "panel_id": panel["panel_id"],
        "status": (
            "live_capture_complete_pending_review"
            if failed == 0
            else "live_capture_incomplete_no_retry"
        ),
        "source_commit": source_commit,
        "panel_path": str(panel_path),
        "panel_sha256": panel_sha256,
        "request_path": str(request_path),
        "request_sha256": request_sha256,
        "capture_path": str(capture_path),
        "capture_sha256": _sha256_file(capture_path),
        "responses_path": str(responses_path) if responses_written else None,
        "responses_sha256": _sha256_file(responses_path) if responses_written else None,
        "provider": provider_name,
        "model": model,
        "mode": "shadow",
        "max_output_tokens_per_call": max_output_tokens,
        "approved_call_count": approved_call_count,
        "attempted_calls": len(capture_rows),
        "succeeded_calls": succeeded,
        "failed_calls": failed,
        "sdk_retries_per_call": 0,
        "api_calls": len(capture_rows),
        "provider_calls": len(capture_rows),
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "approval_basis": approval_basis.strip(),
        "approval_consumed": True,
        "credential_hygiene_attested": True,
        "independent_review_pending": failed == 0,
        "live_execution_authorized_for_additional_calls": False,
        "m7_complete": False,
    }
    _write_json(receipt_path, receipt)
    return receipt


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="capture one explicitly approved W6-v2 live shadow panel"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    parser.add_argument(
        "--panel",
        type=_path,
        default=Path("configs/w6_v2_frozen_shadow_panel.json"),
    )
    parser.add_argument(
        "--requests",
        type=_path,
        default=Path("results/w6_v2_shadow_panel_requests.jsonl"),
    )
    parser.add_argument("--provider", choices=["anthropic", "openai"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--approved-call-count", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--credential-hygiene-attested", action="store_true")
    parser.add_argument("--approval-basis", required=True)
    parser.add_argument("--capture", type=_path, required=True)
    parser.add_argument("--responses", type=_path, required=True)
    parser.add_argument("--receipt", type=_path, required=True)
    args = parser.parse_args(argv)

    provider = get_orchestration_provider(
        args.provider,
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        credential_hygiene_attested=args.credential_hygiene_attested,
    )
    receipt = capture_live_shadow_panel(
        provider=provider,
        provider_name=args.provider,
        model=args.model,
        panel_path=args.panel,
        request_path=args.requests,
        capture_path=args.capture,
        responses_path=args.responses,
        receipt_path=args.receipt,
        repo_root=args.repo_root.resolve(),
        approved_call_count=args.approved_call_count,
        max_output_tokens=args.max_output_tokens,
        credential_hygiene_attested=args.credential_hygiene_attested,
        approval_basis=args.approval_basis,
    )
    print(
        f"status={receipt['status']} attempted={receipt['attempted_calls']} "
        f"succeeded={receipt['succeeded_calls']} failed={receipt['failed_calls']} "
        "retries=0 applied=0"
    )
    return 0 if receipt["failed_calls"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
