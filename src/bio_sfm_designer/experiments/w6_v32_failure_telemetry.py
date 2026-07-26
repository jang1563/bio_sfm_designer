"""Non-sensitive provider-failure telemetry for W6-v3.2 live capture."""

from __future__ import annotations

from typing import Any, Dict, Mapping


TELEMETRY_SCHEMA = "w6_v32_provider_failure_telemetry_v1"
_FIELDS = {
    "schema_version",
    "outcome",
    "safe_reason_code",
    "error_type",
    "http_status",
    "transience_class",
    "retry_authorized",
    "exception_message_stored",
    "traceback_stored",
    "headers_stored",
    "request_id_stored",
}
_KNOWN_SAFE_MESSAGES = {
    "Anthropic response did not contain a text block": "empty_text_response",
    "OpenAI response did not contain output_text": "empty_text_response",
}
_POTENTIALLY_TRANSIENT = {
    "connection_error",
    "rate_limit",
    "server_error",
    "timeout",
}
_NON_TRANSIENT = {
    "authentication_error",
    "invalid_request",
    "not_found",
    "permission_error",
}


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _reason_from_status(status: int | None) -> str | None:
    if status is None:
        return None
    if status == 400:
        return "invalid_request"
    if status == 401:
        return "authentication_error"
    if status == 403:
        return "permission_error"
    if status == 404:
        return "not_found"
    if status == 408:
        return "timeout"
    if status == 409:
        return "connection_error"
    if status == 429:
        return "rate_limit"
    if 500 <= status <= 599:
        return "server_error"
    return "http_error"


def _reason_from_type(error_type: str) -> str:
    normalized = error_type.lower().replace("_", "")
    if "timeout" in normalized:
        return "timeout"
    if "connection" in normalized:
        return "connection_error"
    if "ratelimit" in normalized:
        return "rate_limit"
    if "authentication" in normalized or normalized.startswith("auth"):
        return "authentication_error"
    if "permission" in normalized:
        return "permission_error"
    if "notfound" in normalized:
        return "not_found"
    if "badrequest" in normalized or "invalidrequest" in normalized:
        return "invalid_request"
    if error_type == "RuntimeError":
        return "runtime_error"
    return "provider_error"


def _transience_class(reason: str) -> str:
    if reason in _POTENTIALLY_TRANSIENT:
        return "potentially_transient"
    if reason in _NON_TRANSIENT:
        return "non_transient"
    return "unknown"


def success_telemetry() -> Dict[str, Any]:
    """Return the frozen no-error telemetry record."""

    return {
        "schema_version": TELEMETRY_SCHEMA,
        "outcome": "success",
        "safe_reason_code": None,
        "error_type": None,
        "http_status": None,
        "transience_class": None,
        "retry_authorized": False,
        "exception_message_stored": False,
        "traceback_stored": False,
        "headers_stored": False,
        "request_id_stored": False,
    }


def classify_provider_failure(exc: BaseException) -> Dict[str, Any]:
    """Classify an exception without retaining its message or attached payloads."""

    error_type = type(exc).__name__
    status = _status_code(exc)
    reason = _KNOWN_SAFE_MESSAGES.get(str(exc))
    if reason is None:
        reason = _reason_from_status(status) or _reason_from_type(error_type)
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "outcome": "failure",
        "safe_reason_code": reason,
        "error_type": error_type,
        "http_status": status,
        "transience_class": _transience_class(reason),
        "retry_authorized": False,
        "exception_message_stored": False,
        "traceback_stored": False,
        "headers_stored": False,
        "request_id_stored": False,
    }


def validate_failure_telemetry(value: Any) -> Dict[str, Any]:
    """Validate a persisted W6-v3.2 telemetry record."""

    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise ValueError("provider failure telemetry has an invalid contract")
    record = dict(value)
    if record["schema_version"] != TELEMETRY_SCHEMA:
        raise ValueError("provider failure telemetry schema mismatch")
    if record["outcome"] not in {"success", "failure"}:
        raise ValueError("provider failure telemetry outcome is invalid")
    if record["outcome"] == "success":
        for key in (
            "safe_reason_code",
            "error_type",
            "http_status",
            "transience_class",
        ):
            if record[key] is not None:
                raise ValueError("success telemetry cannot contain failure data")
    else:
        for key in ("safe_reason_code", "error_type", "transience_class"):
            if not isinstance(record[key], str) or not record[key]:
                raise ValueError(f"failure telemetry {key} must be non-empty")
        status = record["http_status"]
        if status is not None and (
            not isinstance(status, int) or isinstance(status, bool)
        ):
            raise ValueError("failure telemetry http_status must be integer or null")
    if record["retry_authorized"] is not False:
        raise ValueError("failure telemetry cannot authorize retries")
    for key in (
        "exception_message_stored",
        "traceback_stored",
        "headers_stored",
        "request_id_stored",
    ):
        if record[key] is not False:
            raise ValueError(f"failure telemetry must set {key}=false")
    return record
