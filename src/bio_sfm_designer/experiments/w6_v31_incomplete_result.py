"""Freeze an honest offline diagnostic for an incomplete W6-v3.1 live run."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..loop.interpreter import (
    _extract_exact_json,
    attempts_control_plane_mutation,
    validate_orchestration_hypothesis,
)
from .w6_v2_shadow_panel import (
    _load_json,
    _load_jsonl,
    _rate,
    _sha256_file,
    _sha256_text,
    _validate_review,
    _write_json,
)
from .w6_v3_hypothesis_only import _attempts_decision_mutation
from .w6_v31_live_panel import (
    CAPTURE_SCHEMA,
    RECEIPT_SCHEMA,
    load_and_validate_scope,
)


ANNOTATION_SCHEMA = "w6_v31_incomplete_review_annotations_v1"
DIAGNOSTIC_SCHEMA = "w6_v31_incomplete_live_diagnostic_v1"
_ANNOTATION_FIELDS = {
    "schema_version",
    "source_scope_sha256",
    "source_panel_sha256",
    "source_request_sha256",
    "source_capture_sha256",
    "source_receipt_sha256",
    "reviewer",
    "records",
}
_REVIEWER_FIELDS = {
    "identity",
    "type",
    "provider_independent",
    "reviewed_at",
}
_CAPTURE_FIELDS = {
    "schema_version",
    "scope_id",
    "scope_sha256",
    "call_index",
    "case_id",
    "contract_sha256",
    "panel_sha256",
    "prompt_sha256",
    "provider",
    "model",
    "mode",
    "attempt_number",
    "retry_count",
    "max_output_tokens",
    "started_at",
    "completed_at",
    "latency_seconds",
    "status",
    "raw_response",
    "response_sha256",
    "input_tokens",
    "output_tokens",
    "stop_reason",
    "transport_metadata_complete",
    "output_limit_stop",
    "error_type",
    "http_status",
    "applied",
}


def _validate_non_empty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _resolve_recorded_path(
    value: Any,
    *,
    repo_root: Path,
    label: str,
) -> Path:
    raw = _validate_non_empty_string(value, label=label)
    path = Path(raw)
    root = repo_root.resolve()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{label} escapes the repository")
    return resolved


def _validate_capture_rows(
    *,
    capture_rows: Sequence[Mapping[str, Any]],
    requests: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
    scope_sha256: str,
) -> None:
    if len(capture_rows) != len(requests):
        raise ValueError("capture must contain one row for every approved request")
    for index, (row, request) in enumerate(zip(capture_rows, requests), 1):
        case_id = request["case_id"]
        if not isinstance(row, Mapping) or set(row) != _CAPTURE_FIELDS:
            raise ValueError(f"{case_id}: capture wrapper contract mismatch")
        expected_values = {
            "schema_version": CAPTURE_SCHEMA,
            "scope_id": scope["scope_id"],
            "scope_sha256": scope_sha256,
            "call_index": index,
            "case_id": case_id,
            "contract_sha256": request["contract_sha256"],
            "panel_sha256": request["panel_sha256"],
            "prompt_sha256": request["prompt_sha256"],
            "provider": scope["provider"],
            "model": scope["model"],
            "mode": "shadow",
            "attempt_number": 1,
            "retry_count": 0,
            "max_output_tokens": scope["max_output_tokens_per_call"],
            "applied": False,
        }
        for key, expected in expected_values.items():
            if row[key] != expected:
                raise ValueError(f"{case_id}: capture {key} mismatch")
        _validate_non_empty_string(row["started_at"], label=f"{case_id}.started_at")
        _validate_non_empty_string(
            row["completed_at"],
            label=f"{case_id}.completed_at",
        )
        latency = row["latency_seconds"]
        if not isinstance(latency, (int, float)) or isinstance(latency, bool):
            raise ValueError(f"{case_id}: latency_seconds must be numeric")
        if latency < 0:
            raise ValueError(f"{case_id}: latency_seconds cannot be negative")

        status = row["status"]
        if status == "succeeded":
            raw = _validate_non_empty_string(
                row["raw_response"],
                label=f"{case_id}.raw_response",
            )
            if row["response_sha256"] != _sha256_text(raw):
                raise ValueError(f"{case_id}: response SHA-256 mismatch")
            for key in ("input_tokens", "output_tokens"):
                value = row[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"{case_id}: {key} must be non-negative")
            _validate_non_empty_string(
                row["stop_reason"],
                label=f"{case_id}.stop_reason",
            )
            if row["transport_metadata_complete"] is not True:
                raise ValueError(f"{case_id}: successful metadata is incomplete")
            if row["error_type"] is not None or row["http_status"] is not None:
                raise ValueError(f"{case_id}: successful row contains an error")
        elif status == "provider_error":
            null_fields = (
                "raw_response",
                "response_sha256",
                "input_tokens",
                "output_tokens",
                "stop_reason",
            )
            if any(row[key] is not None for key in null_fields):
                raise ValueError(f"{case_id}: failed row contains response data")
            if row["transport_metadata_complete"] is not False:
                raise ValueError(f"{case_id}: failed row claims complete metadata")
            _validate_non_empty_string(
                row["error_type"],
                label=f"{case_id}.error_type",
            )
            status_code = row["http_status"]
            if status_code is not None and (
                not isinstance(status_code, int) or isinstance(status_code, bool)
            ):
                raise ValueError(f"{case_id}: http_status must be integer or null")
        else:
            raise ValueError(f"{case_id}: unsupported capture status {status!r}")
        if not isinstance(row["output_limit_stop"], bool):
            raise ValueError(f"{case_id}: output_limit_stop must be boolean")


def _validate_receipt(
    *,
    receipt: Mapping[str, Any],
    scope: Mapping[str, Any],
    scope_path: Path,
    scope_sha256: str,
    panel_path: Path,
    request_path: Path,
    capture_path: Path,
    capture_rows: Sequence[Mapping[str, Any]],
    component_audit: Sequence[Mapping[str, Any]],
    repo_root: Path,
) -> None:
    succeeded = sum(row["status"] == "succeeded" for row in capture_rows)
    failed = len(capture_rows) - succeeded
    metadata_complete = sum(
        row["transport_metadata_complete"] is True for row in capture_rows
    )
    output_limit_stops = sum(row["output_limit_stop"] is True for row in capture_rows)
    expected = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "w6_v31_live_capture_incomplete_no_retry",
        "scope_id": scope["scope_id"],
        "scope_sha256": scope_sha256,
        "panel_id": scope["panel_id"],
        "panel_path": scope["panel_path"],
        "panel_sha256": _sha256_file(panel_path),
        "request_path": scope["request_path"],
        "request_sha256": _sha256_file(request_path),
        "capture_sha256": _sha256_file(capture_path),
        "provider": scope["provider"],
        "model": scope["model"],
        "mode": "shadow",
        "max_output_tokens_per_call": scope["max_output_tokens_per_call"],
        "approved_call_count": scope["approved_call_count"],
        "attempted_calls": len(capture_rows),
        "succeeded_calls": succeeded,
        "failed_calls": failed,
        "transport_metadata_complete_calls": metadata_complete,
        "output_limit_stop_calls": output_limit_stops,
        "sdk_retries_per_call": 0,
        "api_calls": len(capture_rows),
        "provider_calls": len(capture_rows),
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "approval_consumed": True,
        "credential_hygiene_attested": True,
        "independent_from_w6_v2_and_w6_v3": True,
        "source_worktree_clean": True,
        "source_worktree_porcelain_sha256": (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ),
        "responses_path": None,
        "responses_sha256": None,
        "independent_review_pending": False,
        "prospective_live_validation_complete": False,
        "live_execution_authorized_for_additional_calls": False,
        "m7_complete": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"receipt {key} mismatch")
    recorded_paths = {
        "scope_path": scope_path,
        "capture_path": capture_path,
    }
    for key, expected_path in recorded_paths.items():
        observed_path = _resolve_recorded_path(
            receipt.get(key),
            repo_root=repo_root,
            label=f"receipt.{key}",
        )
        if observed_path != expected_path.resolve():
            raise ValueError(f"receipt {key} mismatch")
    if succeeded != 15 or failed != 1:
        raise ValueError("this diagnostic requires the observed 15/16 run")
    if receipt.get("source_commit") is None:
        raise ValueError("receipt source_commit is missing")
    observed_components = receipt.get("execution_components")
    if observed_components != list(component_audit):
        raise ValueError("receipt execution-component audit mismatch")
    if receipt.get("approval_basis") != scope["approval_basis"]:
        raise ValueError("receipt approval basis mismatch")


def _load_annotations(
    *,
    annotations_path: Path,
    source_hashes: Mapping[str, str],
    successful_case_ids: set[str],
    cases_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    annotations = _load_json(annotations_path)
    if not isinstance(annotations, dict) or set(annotations) != _ANNOTATION_FIELDS:
        raise ValueError("annotation fields do not match the incomplete-run schema")
    if annotations["schema_version"] != ANNOTATION_SCHEMA:
        raise ValueError(f"annotations must use {ANNOTATION_SCHEMA}")
    for key, expected in source_hashes.items():
        if annotations[key] != expected:
            raise ValueError(f"annotation {key} mismatch")
    reviewer = annotations["reviewer"]
    if not isinstance(reviewer, dict) or set(reviewer) != _REVIEWER_FIELDS:
        raise ValueError("reviewer metadata has an invalid contract")
    for key in ("identity", "type", "reviewed_at"):
        _validate_non_empty_string(reviewer[key], label=f"reviewer.{key}")
    if reviewer["provider_independent"] is not True:
        raise ValueError("reviewer must be independent from the provider")

    rows = annotations["records"]
    if not isinstance(rows, list):
        raise ValueError("annotation records must be a list")
    reviews: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "review"}:
            raise ValueError("annotation rows require case_id and review")
        case_id = _validate_non_empty_string(
            row["case_id"],
            label="annotation.case_id",
        )
        if case_id in reviews:
            raise ValueError("annotation case ids must be unique")
        if case_id not in successful_case_ids:
            raise ValueError(f"{case_id}: no successful response is reviewable")
        review = _validate_review(row["review"])
        if review["status"] != "complete":
            raise ValueError(f"{case_id}: review must be complete")
        allowed = cases_by_id[case_id]["expected"]["allowed_scope_tags"]
        if review["scope_tag"] not in allowed:
            raise ValueError(f"{case_id}: review scope tag is not allowed")
        reviews[case_id] = review
    if set(reviews) != successful_case_ids:
        raise ValueError("annotations must cover every successful response")
    return reviewer, reviews


def build_incomplete_diagnostic(
    *,
    scope_path: Path,
    capture_path: Path,
    receipt_path: Path,
    annotations_path: Path,
    out_path: Path,
    repo_root: Path,
) -> Dict[str, Any]:
    """Validate and freeze the no-retry 15/16 live result without API calls."""

    if out_path.exists():
        raise FileExistsError("diagnostic output already exists")
    scope_sha256 = _sha256_file(scope_path)
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
        expected_scope_sha256=scope_sha256,
    )
    capture_rows = _load_jsonl(capture_path)
    _validate_capture_rows(
        capture_rows=capture_rows,
        requests=requests,
        scope=scope,
        scope_sha256=scope_sha256,
    )
    receipt = _load_json(receipt_path)
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    _validate_receipt(
        receipt=receipt,
        scope=scope,
        scope_path=scope_path,
        scope_sha256=scope_sha256,
        panel_path=panel_path,
        request_path=request_path,
        capture_path=capture_path,
        capture_rows=capture_rows,
        component_audit=component_audit,
        repo_root=repo_root,
    )

    source_hashes = {
        "source_scope_sha256": scope_sha256,
        "source_panel_sha256": _sha256_file(panel_path),
        "source_request_sha256": _sha256_file(request_path),
        "source_capture_sha256": _sha256_file(capture_path),
        "source_receipt_sha256": _sha256_file(receipt_path),
    }
    cases_by_id = {case["case_id"]: case for case in panel["cases"]}
    successful_case_ids = {
        row["case_id"] for row in capture_rows if row["status"] == "succeeded"
    }
    reviewer, reviews = _load_annotations(
        annotations_path=annotations_path,
        source_hashes=source_hashes,
        successful_case_ids=successful_case_ids,
        cases_by_id=cases_by_id,
    )

    details: List[Dict[str, Any]] = []
    schema_accepted = 0
    authority_violations = 0
    decision_field_attempts = 0
    scope_compliant = 0
    grounded = 0
    actionable = 0
    incremental = 0
    for row in capture_rows:
        case_id = row["case_id"]
        if row["status"] != "succeeded":
            details.append(
                {
                    "case_id": case_id,
                    "status": row["status"],
                    "observed_response": False,
                    "error_type": row["error_type"],
                    "http_status": row["http_status"],
                    "schema_accepted": None,
                    "authority_violation": None,
                    "review_complete": False,
                }
            )
            continue
        raw = row["raw_response"]
        parsed = _extract_exact_json(raw)
        contract_error = None
        try:
            validate_orchestration_hypothesis(parsed)
            accepted = True
        except ValueError as exc:
            accepted = False
            contract_error = str(exc)
        decision_attempt = _attempts_decision_mutation(parsed, raw)
        control_attempt = attempts_control_plane_mutation(
            parsed if parsed is not None else raw
        )
        authority_violation = decision_attempt or control_attempt
        review = reviews[case_id]
        scope_ok = (
            review["scope_tag"]
            in cases_by_id[case_id]["expected"]["allowed_scope_tags"]
        )
        schema_accepted += int(accepted)
        decision_field_attempts += int(decision_attempt)
        authority_violations += int(authority_violation)
        scope_compliant += int(scope_ok)
        grounded += int(review["grounded"])
        actionable += int(review["actionable"])
        incremental += int(review["incremental_value"])
        details.append(
            {
                "case_id": case_id,
                "status": row["status"],
                "observed_response": True,
                "schema_accepted": accepted,
                "contract_error": contract_error,
                "decision_field_attempt": decision_attempt,
                "control_plane_mutation_attempt": control_attempt,
                "authority_violation": authority_violation,
                "review_complete": True,
                "scope_compliant": scope_ok,
                "grounded": review["grounded"],
                "actionable": review["actionable"],
                "incremental_value": review["incremental_value"],
                "scope_tag": review["scope_tag"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "stop_reason": row["stop_reason"],
                "output_limit_stop": row["output_limit_stop"],
            }
        )

    n_cases = len(capture_rows)
    n_observed = len(successful_case_ids)
    metadata_complete = sum(
        row["transport_metadata_complete"] is True for row in capture_rows
    )
    output_limit_stops = sum(row["output_limit_stop"] is True for row in capture_rows)
    observed_input_tokens = [
        row["input_tokens"]
        for row in capture_rows
        if isinstance(row["input_tokens"], int)
    ]
    observed_output_tokens = [
        row["output_tokens"]
        for row in capture_rows
        if isinstance(row["output_tokens"], int)
    ]
    metrics = {
        "panel_case_count": n_cases,
        "attempted_call_count": n_cases,
        "successful_call_count": n_observed,
        "failed_call_count": n_cases - n_observed,
        "capture_completion_rate": _rate(n_observed, n_cases),
        "transport_metadata_complete_count": metadata_complete,
        "transport_metadata_coverage_rate": _rate(metadata_complete, n_cases),
        "output_limit_stop_count": output_limit_stops,
        "schema_acceptance_count_observed": schema_accepted,
        "schema_acceptance_rate_observed": _rate(schema_accepted, n_observed),
        "schema_evaluable_coverage_rate": _rate(n_observed, n_cases),
        "schema_acceptance_full_panel_lower_bound": _rate(
            schema_accepted,
            n_cases,
        ),
        "control_plane_violation_count_observed": authority_violations,
        "decision_field_attempt_count_observed": decision_field_attempts,
        "authority_safe_rate_observed": _rate(
            n_observed - authority_violations,
            n_observed,
        ),
        "authority_assessed_coverage_rate": _rate(n_observed, n_cases),
        "review_completion_rate_observed": 1.0,
        "review_assessed_coverage_rate": _rate(n_observed, n_cases),
        "scope_compliance_rate_observed": _rate(scope_compliant, n_observed),
        "grounded_rate_observed": _rate(grounded, n_observed),
        "actionable_rate_observed": _rate(actionable, n_observed),
        "incremental_value_rate_observed": _rate(incremental, n_observed),
        "no_effect_rate": 1.0,
        "observed_input_tokens_total": sum(observed_input_tokens),
        "observed_output_tokens_total": sum(observed_output_tokens),
        "observed_output_tokens_min": min(observed_output_tokens),
        "observed_output_tokens_max": max(observed_output_tokens),
    }
    criteria = panel["pass_criteria"]
    checks = {
        "capture_complete": n_observed == n_cases,
        "transport_metadata_complete": metadata_complete == n_cases,
        "schema_acceptance_full_panel": (
            metrics["schema_acceptance_full_panel_lower_bound"]
            >= criteria["min_schema_acceptance_rate"]
        ),
        "control_plane_violations_observed": (
            authority_violations <= criteria["max_control_plane_violations"]
        ),
        "review_completion_observed": (
            metrics["review_completion_rate_observed"]
            >= criteria["min_review_completion_rate"]
        ),
        "scope_compliance_observed": (
            metrics["scope_compliance_rate_observed"]
            >= criteria["min_scope_compliance_rate"]
        ),
        "grounded_observed": (
            metrics["grounded_rate_observed"] >= criteria["min_grounded_rate"]
        ),
        "actionable_observed": (
            metrics["actionable_rate_observed"] >= criteria["min_actionable_rate"]
        ),
        "incremental_value_observed": (
            metrics["incremental_value_rate_observed"]
            >= criteria["min_incremental_value_rate"]
        ),
        "no_effect": metrics["no_effect_rate"] == 1.0,
    }
    passed = all(checks.values())
    if passed:
        raise AssertionError("an incomplete capture cannot pass")
    failed_rows = [
        {
            "case_id": row["case_id"],
            "error_type": row["error_type"],
            "http_status": row["http_status"],
        }
        for row in capture_rows
        if row["status"] != "succeeded"
    ]
    result = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "status": "w6_v31_prospective_live_validation_incomplete",
        "evaluation_class": "w6_v31_incomplete_live_shadow_diagnostic",
        "passed": False,
        "formal_interpretation": "not_passing_incomplete_capture",
        "panel_id": panel["panel_id"],
        "source_commit": receipt["source_commit"],
        "provider": scope["provider"],
        "model": scope["model"],
        "mode": "shadow",
        "source_artifacts": {
            "scope": {"path": str(scope_path), "sha256": scope_sha256},
            "panel": {"path": scope["panel_path"], "sha256": _sha256_file(panel_path)},
            "requests": {
                "path": scope["request_path"],
                "sha256": _sha256_file(request_path),
            },
            "capture": {
                "path": str(capture_path),
                "sha256": _sha256_file(capture_path),
            },
            "receipt": {
                "path": str(receipt_path),
                "sha256": _sha256_file(receipt_path),
            },
            "annotations": {
                "path": str(annotations_path),
                "sha256": _sha256_file(annotations_path),
            },
        },
        "reviewer": reviewer,
        "call_contract": {
            "approved_calls": scope["approved_call_count"],
            "attempted_calls": receipt["attempted_calls"],
            "max_output_tokens_per_call": scope["max_output_tokens_per_call"],
            "sdk_retries_per_call": scope["sdk_retries_per_call"],
            "additional_provider_calls_authorized": False,
            "approval_consumed": True,
        },
        "metrics": metrics,
        "pass_criteria": {
            **criteria,
            "require_complete_capture": True,
            "require_complete_transport_metadata": True,
        },
        "checks": checks,
        "failed_cases": failed_rows,
        "details": details,
        "transport_interpretation": {
            "baseline_max_output_tokens": panel["transport_hypothesis"][
                "baseline_max_output_tokens"
            ],
            "successor_max_output_tokens": panel["transport_hypothesis"][
                "successor_max_output_tokens"
            ],
            "observed_successes_exact_schema": (schema_accepted == n_observed),
            "observed_successes_output_limit_stops": output_limit_stops,
            "result": ("supported_on_successful_calls_but_not_validated_panelwide"),
        },
        "limitations": [
            (
                "One approved request produced no response or transport metadata; "
                "the exact cause is unavailable beyond error_type=RuntimeError."
            ),
            (
                "Observed 15/15 schema and authority results cannot be promoted "
                "to a 16/16 prospective panel claim."
            ),
            (
                "The missing case was not synthesized, imputed, retried, or "
                "qualitatively reviewed."
            ),
        ],
        "source_provider_calls": receipt["provider_calls"],
        "analysis_provider_calls": 0,
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "prospective_live_validation_complete": False,
        "live_execution_authorized_for_additional_calls": False,
        "m7_complete": False,
    }
    _write_json(out_path, result)
    return result


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="freeze an offline diagnostic for an incomplete W6-v3.1 run"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    parser.add_argument("--scope", type=_path, required=True)
    parser.add_argument("--capture", type=_path, required=True)
    parser.add_argument("--receipt", type=_path, required=True)
    parser.add_argument("--annotations", type=_path, required=True)
    parser.add_argument("--out", type=_path, required=True)
    args = parser.parse_args(argv)
    result = build_incomplete_diagnostic(
        scope_path=args.scope,
        capture_path=args.capture,
        receipt_path=args.receipt,
        annotations_path=args.annotations,
        out_path=args.out,
        repo_root=args.repo_root.resolve(),
    )
    print(
        f"status={result['status']} attempted="
        f"{result['metrics']['attempted_call_count']} succeeded="
        f"{result['metrics']['successful_call_count']} failed="
        f"{result['metrics']['failed_call_count']} analysis_provider_calls=0 "
        "applied=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
