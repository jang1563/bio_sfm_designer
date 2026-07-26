"""Validate or capture one authorized W6-v4 gated DBTL shadow campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..loop.providers import (
    call_provider_with_metadata,
    get_orchestration_provider,
)
from .w6_v32_failure_telemetry import (
    TELEMETRY_SCHEMA,
    classify_provider_failure,
    success_telemetry,
    validate_failure_telemetry,
)
from .w6_v4_gated_batch_campaign import (
    _sha256_file,
    load_and_validate_campaign,
    run_frozen_campaign,
)


SCOPE_SCHEMA = "w6_v4_live_campaign_scope_v1"
CAPTURE_SCHEMA = "w6_v4_live_campaign_transport_capture_v1"
RESPONSE_SCHEMA = "w6_v4_live_campaign_response_v1"
RECEIPT_SCHEMA = "w6_v4_live_campaign_receipt_v1"
_SCOPE_FIELDS = {
    "schema_version",
    "scope_id",
    "frozen_at",
    "purpose",
    "campaign_config_path",
    "campaign_config_sha256",
    "campaign_id",
    "provider",
    "model",
    "mode",
    "approved_call_count",
    "max_output_tokens_per_call",
    "sdk_retries_per_call",
    "temperature_override",
    "one_call_per_campaign",
    "one_shot",
    "resume_allowed",
    "overwrite_allowed",
    "credential_hygiene_attested",
    "capture_transport_metadata",
    "capture_failure_telemetry",
    "failure_telemetry_schema",
    "store_exception_messages",
    "store_tracebacks",
    "store_headers",
    "store_request_ids",
    "require_clean_worktree",
    "require_component_hash_match",
    "execution_components",
    "live_execution_authorized",
    "approval_basis",
    "review_required_before_scoring",
    "reviewer_provider_independence_required",
    "recommendations_may_be_applied",
    "stop_or_explore_may_change",
    "routing_may_change",
    "trust_or_safety_may_change",
    "budget_may_change",
    "compute_submission_allowed",
    "historical_certificate_reused",
    "additional_provider_calls_authorized",
}
_COMPONENT_FIELDS = {"path", "sha256"}
_REQUIRED_COMPONENT_PATHS = {
    "src/bio_sfm_designer/loop/providers.py",
    "src/bio_sfm_designer/loop/interpreter.py",
    "src/bio_sfm_designer/loop/controller.py",
    "src/bio_sfm_designer/experiments/run_batch_round.py",
    "src/bio_sfm_designer/experiments/w6_v32_failure_telemetry.py",
    "src/bio_sfm_designer/experiments/w6_v4_gated_batch_campaign.py",
    "src/bio_sfm_designer/experiments/w6_v4_live_campaign.py",
}
_REQUIRED_TRUE = {
    "one_call_per_campaign",
    "one_shot",
    "credential_hygiene_attested",
    "capture_transport_metadata",
    "capture_failure_telemetry",
    "require_clean_worktree",
    "require_component_hash_match",
    "review_required_before_scoring",
    "reviewer_provider_independence_required",
}
_REQUIRED_FALSE = {
    "resume_allowed",
    "overwrite_allowed",
    "store_exception_messages",
    "store_tracebacks",
    "store_headers",
    "store_request_ids",
    "recommendations_may_be_applied",
    "stop_or_explore_may_change",
    "routing_may_change",
    "trust_or_safety_may_change",
    "budget_may_change",
    "compute_submission_allowed",
    "historical_certificate_reused",
    "additional_provider_calls_authorized",
}
_OUTPUT_LIMIT_STOP_REASONS = {
    "length",
    "max_output_tokens",
    "max_tokens",
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _validate_digest(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


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
    Dict[str, Path],
    List[Dict[str, Any]],
]:
    """Validate a W6-v4 scope without constructing or calling a provider."""

    observed_scope_sha256 = _sha256_file(scope_path)
    if expected_scope_sha256 is not None:
        expected = _validate_digest(
            expected_scope_sha256,
            label="expected_scope_sha256",
        )
        if observed_scope_sha256 != expected:
            raise ValueError("approved W6-v4 scope SHA-256 mismatch")
    scope = _load_json(scope_path)
    if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
        raise ValueError("W6-v4 scope fields do not match the frozen schema")
    if scope["schema_version"] != SCOPE_SCHEMA:
        raise ValueError(f"scope schema_version must be {SCOPE_SCHEMA}")
    for field in (
        "scope_id",
        "frozen_at",
        "purpose",
        "campaign_id",
        "provider",
        "model",
    ):
        if not isinstance(scope[field], str) or not scope[field].strip():
            raise ValueError(f"scope.{field} must be non-empty")
    if scope["provider"] != "anthropic" or scope["model"] != "claude-opus-4-8":
        raise ValueError("W6-v4 must preserve the provider and model")
    if scope["mode"] != "shadow":
        raise ValueError("W6-v4 mode must be shadow")
    if scope["approved_call_count"] != 1:
        raise ValueError("W6-v4 permits exactly one campaign-level call")
    if scope["max_output_tokens_per_call"] != 512:
        raise ValueError("W6-v4 output cap must be exactly 512")
    if scope["sdk_retries_per_call"] != 0:
        raise ValueError("W6-v4 SDK retries must be zero")
    if scope["temperature_override"] is not None:
        raise ValueError("temperature override is forbidden")
    if any(scope[key] is not True for key in _REQUIRED_TRUE):
        raise ValueError("W6-v4 scope is missing a required true flag")
    if any(scope[key] is not False for key in _REQUIRED_FALSE):
        raise ValueError("W6-v4 scope is missing a required false flag")
    if scope["failure_telemetry_schema"] != TELEMETRY_SCHEMA:
        raise ValueError("W6-v4 failure telemetry schema mismatch")
    authorized = scope["live_execution_authorized"]
    if not isinstance(authorized, bool):
        raise ValueError("live_execution_authorized must be boolean")
    approval_basis = scope["approval_basis"]
    if authorized:
        if not isinstance(approval_basis, str) or not approval_basis.strip():
            raise ValueError("authorized scope requires a non-empty approval_basis")
    elif approval_basis is not None:
        raise ValueError("unauthorized scope must set approval_basis=null")

    campaign_path = _resolve_repo_path(
        repo_root,
        scope["campaign_config_path"],
        label="campaign_config_path",
    )
    if _sha256_file(campaign_path) != scope["campaign_config_sha256"]:
        raise ValueError("W6-v4 campaign config SHA-256 mismatch")
    campaign, paths, _ = load_and_validate_campaign(
        campaign_path,
        repo_root=repo_root,
    )
    if campaign["campaign_id"] != scope["campaign_id"]:
        raise ValueError("W6-v4 scope campaign id mismatch")
    contract = campaign["orchestration_contract"]
    if (
        contract["future_live_provider"] != scope["provider"]
        or contract["future_live_model"] != scope["model"]
        or contract["future_max_output_tokens"] != scope["max_output_tokens_per_call"]
        or contract["future_sdk_retries_per_call"] != scope["sdk_retries_per_call"]
    ):
        raise ValueError("W6-v4 scope drifts from the campaign contract")
    components = _validate_components(
        scope["execution_components"],
        repo_root=repo_root,
    )
    return scope, campaign, paths, components


class _CapturingProvider:
    def __init__(
        self,
        provider: Any,
        *,
        provider_name: str,
        model: str,
        scope_id: str,
        scope_sha256: str,
        capture_path: Path,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.scope_id = scope_id
        self.scope_sha256 = scope_sha256
        self.capture_path = capture_path
        self.calls = 0
        self.record: Optional[Dict[str, Any]] = None

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        if self.calls != 1:
            raise RuntimeError("W6-v4 provider wrapper forbids additional calls")
        row: Dict[str, Any] = {
            "schema_version": CAPTURE_SCHEMA,
            "scope_id": self.scope_id,
            "scope_sha256": self.scope_sha256,
            "call_index": 1,
            "provider": self.provider_name,
            "model": self.model,
            "mode": "shadow",
            "attempt_number": 1,
            "retry_count": 0,
            "max_output_tokens": 512,
            "prompt_sha256": _sha256_text(prompt),
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
            "failure_telemetry": None,
            "applied": False,
        }
        self.record = row
        _write_json(self.capture_path, row)
        started = time.monotonic()
        try:
            result = call_provider_with_metadata(self.provider, prompt)
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
            row["failure_telemetry"] = success_telemetry()
            row["status"] = "succeeded"
            return result.text
        except Exception as exc:
            row["failure_telemetry"] = classify_provider_failure(exc)
            row["status"] = "provider_error"
            raise
        finally:
            row["latency_seconds"] = round(time.monotonic() - started, 6)
            row["completed_at"] = _utc_now()
            validate_failure_telemetry(row["failure_telemetry"])
            _write_json(self.capture_path, row)


def capture_live_campaign(
    *,
    provider: Any,
    scope_path: Path,
    out_dir: Path,
    repo_root: Path,
    approved_scope_sha256: str,
    source_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one authorized W6-v4 campaign call with immutable control comparison."""

    if out_dir.exists():
        raise FileExistsError("W6-v4 output directory already exists")
    scope, campaign, paths, components = load_and_validate_scope(
        scope_path,
        repo_root=repo_root,
        expected_scope_sha256=approved_scope_sha256,
    )
    if not scope["live_execution_authorized"]:
        raise PermissionError("W6-v4 live execution is not authorized")
    worktree_porcelain = _git_porcelain(repo_root)
    if worktree_porcelain:
        raise RuntimeError("W6-v4 live execution requires a clean worktree")

    source_commit = source_commit or _git_head(repo_root)
    scope_sha256 = _sha256_file(scope_path)
    out_dir.mkdir(parents=True)
    capture_path = out_dir / "transport_capture.json"
    receipt_path = out_dir / "receipt.json"
    response_path = out_dir / "response_pending_review.json"
    baseline = run_frozen_campaign(
        campaign,
        paths,
        provider=None,
        out_dir=out_dir / "baseline",
    )
    capturing = _CapturingProvider(
        provider,
        provider_name=scope["provider"],
        model=scope["model"],
        scope_id=scope["scope_id"],
        scope_sha256=scope_sha256,
        capture_path=capture_path,
    )
    shadow = run_frozen_campaign(
        campaign,
        paths,
        provider=capturing,
        out_dir=out_dir / "shadow",
    )
    if capturing.record is None:
        raise RuntimeError("W6-v4 provider call did not produce a capture record")
    capture = capturing.record
    telemetry = validate_failure_telemetry(capture["failure_telemetry"])
    events = shadow.events
    event = events[0] if len(events) == 1 else {}
    campaign_identical = shadow.campaign_sha256 == baseline.campaign_sha256
    control_identical = shadow.control_sha256 == baseline.control_sha256
    no_effect = (
        campaign_identical and control_identical and event.get("applied") is False
    )
    accepted = event.get("status") == "accepted"
    metadata_complete = capture["transport_metadata_complete"] is True
    output_limit_stop = capture["output_limit_stop"] is True
    response_written = False
    if (
        capture["status"] == "succeeded"
        and accepted
        and metadata_complete
        and not output_limit_stop
        and no_effect
    ):
        response = {
            "schema_version": RESPONSE_SCHEMA,
            "campaign_id": campaign["campaign_id"],
            "scope_id": scope["scope_id"],
            "scope_sha256": scope_sha256,
            "campaign_config_sha256": scope["campaign_config_sha256"],
            "prompt_sha256": capture["prompt_sha256"],
            "raw_response": capture["raw_response"],
            "response_sha256": capture["response_sha256"],
            "recommendation": event.get("recommendation"),
            "review": {
                "status": "pending",
                "scope_tag": "unreviewed",
                "grounded": False,
                "actionable": False,
                "incremental_value": False,
                "notes": "Provider-independent campaign review pending.",
            },
        }
        _write_json(response_path, response)
        response_written = True

    if capturing.calls != 1:
        status = "w6_v4_live_campaign_invalid_call_count"
    elif capture["status"] != "succeeded":
        status = "w6_v4_live_campaign_incomplete_no_retry"
    elif not metadata_complete:
        status = "w6_v4_live_campaign_incomplete_transport_metadata"
    elif output_limit_stop:
        status = "w6_v4_live_campaign_output_limit_fail"
    elif not accepted:
        status = "w6_v4_live_campaign_contract_fail"
    elif not no_effect:
        status = "w6_v4_live_campaign_safety_invariant_fail"
    else:
        status = "w6_v4_live_campaign_complete_pending_review"
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "scope_id": scope["scope_id"],
        "scope_path": str(scope_path),
        "scope_sha256": scope_sha256,
        "campaign_id": campaign["campaign_id"],
        "campaign_config_path": scope["campaign_config_path"],
        "campaign_config_sha256": scope["campaign_config_sha256"],
        "source_commit": source_commit,
        "source_worktree_clean": True,
        "source_worktree_porcelain_sha256": hashlib.sha256(
            worktree_porcelain.encode("utf-8")
        ).hexdigest(),
        "execution_components": components,
        "provider": scope["provider"],
        "model": scope["model"],
        "mode": "shadow",
        "approved_call_count": 1,
        "attempted_calls": capturing.calls,
        "succeeded_calls": int(capture["status"] == "succeeded"),
        "failed_calls": int(capture["status"] != "succeeded"),
        "sdk_retries_per_call": 0,
        "max_output_tokens_per_call": 512,
        "transport_metadata_complete_calls": int(metadata_complete),
        "failure_telemetry_complete_calls": 1,
        "failure_reason": telemetry["safe_reason_code"],
        "output_limit_stop_calls": int(output_limit_stop),
        "input_tokens": capture["input_tokens"],
        "output_tokens": capture["output_tokens"],
        "stop_reason": capture["stop_reason"],
        "event_count": len(events),
        "event_status": event.get("status"),
        "recommendations_applied": int(event.get("applied") is True),
        "baseline_campaign_sha256": baseline.campaign_sha256,
        "shadow_campaign_sha256": shadow.campaign_sha256,
        "campaign_bytes_identical": campaign_identical,
        "baseline_control_sha256": baseline.control_sha256,
        "shadow_control_sha256": shadow.control_sha256,
        "control_view_identical": control_identical,
        "no_effect": no_effect,
        "capture_path": str(capture_path),
        "capture_sha256": _sha256_file(capture_path),
        "response_path": str(response_path) if response_written else None,
        "response_sha256": (_sha256_file(response_path) if response_written else None),
        "api_calls": capturing.calls,
        "live_provider_calls": capturing.calls,
        "compute_submissions": 0,
        "approval_basis": scope["approval_basis"],
        "approval_consumed": True,
        "additional_provider_calls_authorized": False,
        "historical_certificate_reused": False,
        "independent_review_pending": response_written,
        "prospective_live_validation_complete": False,
        "m7_complete": False,
    }
    _write_json(receipt_path, receipt)
    return receipt


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="validate or capture one W6-v4 live gated batch campaign"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v4_live_campaign_scope.json"),
    )

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--scope",
        type=_path,
        default=Path("configs/w6_v4_live_campaign_scope.json"),
    )
    capture_parser.add_argument("--approved-scope-sha256", required=True)
    capture_parser.add_argument("--out-dir", type=_path, required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "validate":
        scope, campaign, _, _ = load_and_validate_scope(
            args.scope,
            repo_root=repo_root,
        )
        print(
            f"status=w6_v4_scope_valid scope_id={scope['scope_id']} "
            f"campaign_id={campaign['campaign_id']} "
            f"calls={scope['approved_call_count']} "
            f"authorized={str(scope['live_execution_authorized']).lower()} "
            f"scope_sha256={_sha256_file(args.scope)} api_calls=0"
        )
        return 0

    scope, _, _, _ = load_and_validate_scope(
        args.scope,
        repo_root=repo_root,
        expected_scope_sha256=args.approved_scope_sha256,
    )
    if not scope["live_execution_authorized"]:
        raise PermissionError("W6-v4 live execution is not authorized")
    provider = get_orchestration_provider(
        scope["provider"],
        model=scope["model"],
        max_output_tokens=scope["max_output_tokens_per_call"],
        credential_hygiene_attested=scope["credential_hygiene_attested"],
    )
    receipt = capture_live_campaign(
        provider=provider,
        scope_path=args.scope,
        out_dir=args.out_dir,
        repo_root=repo_root,
        approved_scope_sha256=args.approved_scope_sha256,
    )
    print(
        f"status={receipt['status']} attempted={receipt['attempted_calls']} "
        f"succeeded={receipt['succeeded_calls']} failed={receipt['failed_calls']} "
        f"metadata_complete={receipt['transport_metadata_complete_calls']} "
        f"no_effect={str(receipt['no_effect']).lower()} retries=0 applied=0"
    )
    return (
        0 if receipt["status"] == "w6_v4_live_campaign_complete_pending_review" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
