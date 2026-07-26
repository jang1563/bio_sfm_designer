"""Freeze and replay the W6-v4 gated DBTL shadow campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..config import ObjectiveSpec
from ..generate import PrecomputedGenerator
from ..loop.controller import DBTLController
from ..loop.interpreter import validate_orchestration_hypothesis
from ..predict.structure import PrecomputedStructurePredictor
from ..safety import PrecomputedScreen
from .run_batch_round import preflight_batch_round


CAMPAIGN_SCHEMA = "w6_v4_gated_batch_campaign_v1"
REPORT_SCHEMA = "w6_v4_gated_batch_offline_report_v1"
_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "frozen_at",
    "mode",
    "purpose",
    "api_calls_allowed",
    "live_provider_calls_allowed",
    "compute_submission_allowed",
    "historical_boundary",
    "inputs",
    "campaign_contract",
    "orchestration_contract",
    "review_contract",
    "valid_fixture",
    "adversarial_fixtures",
    "pass_criteria",
}
_BOUNDARY_FIELDS = {
    "status_path",
    "status_sha256",
    "historical_prevalidation_ok",
    "historical_conformal_alpha",
    "historical_tau",
    "current_prevalidation_expected_ok",
    "current_campaign_uses_prevalidation",
    "correction",
}
_INPUT_NAMES = {
    "candidates",
    "records",
    "verdicts",
    "historical_prevalidation_records",
}
_INPUT_FIELDS = {"path", "sha256", "row_count"}
_CAMPAIGN_FIELDS = {
    "target",
    "objective",
    "lambda",
    "rounds",
    "candidates_per_round",
    "assay_budget",
    "strict_complex_records",
    "use_gate_prevalidation",
    "conformal_alpha",
    "conformal_delta",
    "expected_gate_calibrated",
    "expected_rounds_run",
    "expected_assays_used",
    "expected_action_counts",
    "expected_hard_stop",
    "expected_hard_stop_reason",
}
_ORCHESTRATION_FIELDS = {
    "contract_version",
    "mode",
    "response_fields",
    "one_call_per_campaign",
    "consult_on_hard_stop",
    "future_live_provider",
    "future_live_model",
    "future_max_output_tokens",
    "future_sdk_retries_per_call",
    "recommendations_may_be_applied",
    "stop_or_explore_may_change",
    "routing_may_change",
    "trust_or_safety_may_change",
    "budget_may_change",
    "compute_may_be_submitted",
    "prompt_may_include_candidate_ids",
    "prompt_may_include_sequences",
    "prompt_may_include_hidden_truth",
}
_REVIEW_CONTRACT_FIELDS = {
    "allowed_scope_tags",
    "grounded",
    "actionable",
    "incremental_value",
    "scope_compliant",
}
_VALID_FIXTURE_FIELDS = {"response", "review"}
_REVIEW_FIELDS = {
    "status",
    "scope_tag",
    "grounded",
    "actionable",
    "incremental_value",
    "notes",
}
_ADVERSARIAL_BASE_FIELDS = {
    "fixture_id",
    "kind",
    "expected_event_status",
}
_PASS_FIELDS = {
    "require_current_preflight_ok",
    "require_historical_prevalidation_refused",
    "require_strict_complex_qc",
    "require_baseline_expected_actions",
    "require_valid_fixture_accepted",
    "require_valid_review_complete",
    "require_valid_review_all_positive",
    "require_all_campaign_bytes_identical",
    "require_all_control_views_identical",
    "require_all_adversarial_fixtures_fail_closed",
    "require_prompt_privacy",
    "max_authority_violations",
    "max_applied_recommendations",
    "max_api_calls",
    "max_live_provider_calls",
    "max_compute_submissions",
    "m7_complete",
}
_ACTIONS = {"trust_sfm", "verify_assay", "default_baseline", "defer"}
_PROMPT_MARKER = "DBTL_STATE=\n"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(row)
    return rows


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _repo_path(repo_root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty repository-relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} must be repository-relative")
    root = repo_root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{label} escapes the repository")
    return resolved


def _validate_bound_inputs(
    inputs: Any,
    *,
    repo_root: Path,
) -> Tuple[Dict[str, Path], List[Dict[str, Any]]]:
    if not isinstance(inputs, dict) or set(inputs) != _INPUT_NAMES:
        raise ValueError("W6-v4 inputs do not match the frozen contract")
    paths: Dict[str, Path] = {}
    audit: List[Dict[str, Any]] = []
    for name in sorted(_INPUT_NAMES):
        spec = inputs[name]
        if not isinstance(spec, dict) or set(spec) != _INPUT_FIELDS:
            raise ValueError(f"inputs.{name} has an invalid contract")
        path = _repo_path(repo_root, spec["path"], label=f"inputs.{name}.path")
        if not path.is_file():
            raise ValueError(f"inputs.{name} is missing")
        observed_sha256 = _sha256_file(path)
        if observed_sha256 != spec["sha256"]:
            raise ValueError(f"inputs.{name} SHA-256 mismatch")
        rows = _load_jsonl(path)
        if spec["row_count"] != len(rows):
            raise ValueError(f"inputs.{name} row count mismatch")
        paths[name] = path
        audit.append(
            {
                "name": name,
                "path": spec["path"],
                "sha256": observed_sha256,
                "row_count": len(rows),
            }
        )
    return paths, audit


def _validate_historical_boundary(
    boundary: Any,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    if not isinstance(boundary, dict) or set(boundary) != _BOUNDARY_FIELDS:
        raise ValueError("historical_boundary has an invalid contract")
    status_path = _repo_path(
        repo_root,
        boundary["status_path"],
        label="historical_boundary.status_path",
    )
    if _sha256_file(status_path) != boundary["status_sha256"]:
        raise ValueError("historical W4 status SHA-256 mismatch")
    status = _load_json(status_path)
    gate_context = status.get("gate_context", {})
    preflight = status.get("batch_preflight", {})
    if (
        boundary["historical_prevalidation_ok"] is not True
        or preflight.get("gate_prevalidation_ok") is not True
        or gate_context.get("conformal_alpha") != boundary["historical_conformal_alpha"]
        or gate_context.get("complex_tau") != boundary["historical_tau"]
    ):
        raise ValueError("historical W4 prevalidation claim does not match")
    if (
        boundary["current_prevalidation_expected_ok"] is not False
        or boundary["current_campaign_uses_prevalidation"] is not False
    ):
        raise ValueError("W6-v4 must freeze the corrected prevalidation boundary")
    if (
        not isinstance(boundary["correction"], str)
        or not boundary["correction"].strip()
    ):
        raise ValueError("historical boundary correction must be non-empty")
    return {
        "status_path": boundary["status_path"],
        "status_sha256": boundary["status_sha256"],
        "historical_prevalidation_ok": True,
        "historical_conformal_alpha": boundary["historical_conformal_alpha"],
        "historical_tau": boundary["historical_tau"],
    }


def _validate_campaign_contract(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _CAMPAIGN_FIELDS:
        raise ValueError("campaign_contract has an invalid contract")
    if value["rounds"] != 1 or value["candidates_per_round"] != 50:
        raise ValueError("W6-v4 must preserve one 50-candidate batch")
    if value["strict_complex_records"] is not True:
        raise ValueError("W6-v4 requires strict complex-record QC")
    if (
        value["use_gate_prevalidation"] is not False
        or value["conformal_alpha"] is not None
        or value["expected_gate_calibrated"] is not False
    ):
        raise ValueError("W6-v4 cannot revive the historical gate certificate")
    actions = value["expected_action_counts"]
    if (
        not isinstance(actions, dict)
        or set(actions) != _ACTIONS
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in actions.values()
        )
        or sum(actions.values()) != 50
    ):
        raise ValueError("expected action counts are invalid")
    if (
        value["expected_rounds_run"] != 1
        or value["expected_assays_used"] != 0
        or value["expected_hard_stop"] is not True
        or value["expected_hard_stop_reason"] != "round budget reached"
    ):
        raise ValueError("W6-v4 deterministic stop contract is invalid")


def _validate_orchestration_contract(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ORCHESTRATION_FIELDS:
        raise ValueError("orchestration_contract has an invalid contract")
    if (
        value["contract_version"] != "llm_orchestration_hypothesis_v3"
        or value["mode"] != "shadow"
        or value["response_fields"] != ["reason", "hypothesis"]
        or value["one_call_per_campaign"] is not True
        or value["consult_on_hard_stop"] is not True
        or value["future_live_provider"] != "anthropic"
        or value["future_live_model"] != "claude-opus-4-8"
        or value["future_max_output_tokens"] != 512
        or value["future_sdk_retries_per_call"] != 0
    ):
        raise ValueError("W6-v4 orchestration behavior is not frozen")
    forbidden_true = (
        "recommendations_may_be_applied",
        "stop_or_explore_may_change",
        "routing_may_change",
        "trust_or_safety_may_change",
        "budget_may_change",
        "compute_may_be_submitted",
        "prompt_may_include_candidate_ids",
        "prompt_may_include_sequences",
        "prompt_may_include_hidden_truth",
    )
    if any(value[key] is not False for key in forbidden_true):
        raise ValueError("W6-v4 orchestration authority is overbroad")


def _validate_review(value: Any, *, allowed_scope_tags: set[str]) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REVIEW_FIELDS:
        raise ValueError("valid fixture review has an invalid contract")
    if value["status"] != "complete":
        raise ValueError("valid fixture review must be complete")
    if value["scope_tag"] not in allowed_scope_tags:
        raise ValueError("valid fixture review scope is not allowed")
    for field in ("grounded", "actionable", "incremental_value"):
        if not isinstance(value[field], bool):
            raise ValueError(f"valid fixture review {field} must be boolean")
    if not isinstance(value["notes"], str) or not value["notes"].strip():
        raise ValueError("valid fixture review notes must be non-empty")
    return dict(value)


def _validate_fixtures(config: Mapping[str, Any]) -> None:
    review_contract = config["review_contract"]
    if (
        not isinstance(review_contract, dict)
        or set(review_contract) != _REVIEW_CONTRACT_FIELDS
    ):
        raise ValueError("review_contract has an invalid contract")
    allowed = review_contract["allowed_scope_tags"]
    if (
        not isinstance(allowed, list)
        or len(allowed) != len(set(allowed))
        or any(not isinstance(item, str) or not item for item in allowed)
    ):
        raise ValueError("review scope tags are invalid")
    for field in _REVIEW_CONTRACT_FIELDS - {"allowed_scope_tags"}:
        if (
            not isinstance(review_contract[field], str)
            or not review_contract[field].strip()
        ):
            raise ValueError(f"review_contract.{field} must be non-empty")

    valid = config["valid_fixture"]
    if not isinstance(valid, dict) or set(valid) != _VALID_FIXTURE_FIELDS:
        raise ValueError("valid_fixture has an invalid contract")
    validate_orchestration_hypothesis(valid["response"])
    _validate_review(valid["review"], allowed_scope_tags=set(allowed))

    adversarial = config["adversarial_fixtures"]
    if not isinstance(adversarial, list) or len(adversarial) != 5:
        raise ValueError("W6-v4 requires exactly five adversarial fixtures")
    seen = set()
    for fixture in adversarial:
        if not isinstance(fixture, dict):
            raise ValueError("adversarial fixture must be an object")
        fixture_id = fixture.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in seen:
            raise ValueError("adversarial fixture ids must be unique")
        seen.add(fixture_id)
        kind = fixture.get("kind")
        expected_fields = set(_ADVERSARIAL_BASE_FIELDS)
        if kind == "response":
            expected_fields.add("response")
        elif kind == "raw_text":
            expected_fields.add("raw_text")
        elif kind == "provider_error":
            expected_fields.update({"error_type", "http_status"})
        else:
            raise ValueError(f"unsupported adversarial fixture kind: {kind}")
        if set(fixture) != expected_fields:
            raise ValueError(f"{fixture_id}: adversarial fixture fields are invalid")
        if fixture["expected_event_status"] not in {
            "invalid_response",
            "provider_error",
        }:
            raise ValueError(f"{fixture_id}: expected event status is invalid")


def _validate_pass_criteria(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _PASS_FIELDS:
        raise ValueError("pass_criteria has an invalid contract")
    required_true = _PASS_FIELDS - {
        "max_authority_violations",
        "max_applied_recommendations",
        "max_api_calls",
        "max_live_provider_calls",
        "max_compute_submissions",
        "m7_complete",
    }
    if any(value[key] is not True for key in required_true):
        raise ValueError("W6-v4 pass criteria must require every invariant")
    for key in (
        "max_authority_violations",
        "max_applied_recommendations",
        "max_api_calls",
        "max_live_provider_calls",
        "max_compute_submissions",
    ):
        if value[key] != 0:
            raise ValueError(f"pass_criteria.{key} must be zero")
    if value["m7_complete"] is not False:
        raise ValueError("offline W6-v4 cannot complete M7")


def load_and_validate_campaign(
    config_path: Path,
    *,
    repo_root: Path,
) -> Tuple[Dict[str, Any], Dict[str, Path], Dict[str, Any]]:
    """Validate the frozen W6-v4 campaign without constructing a provider."""

    config = _load_json(config_path)
    if not isinstance(config, dict) or set(config) != _ROOT_FIELDS:
        raise ValueError("W6-v4 campaign fields do not match the frozen schema")
    if config["schema_version"] != CAMPAIGN_SCHEMA:
        raise ValueError(f"campaign schema_version must be {CAMPAIGN_SCHEMA}")
    if config["mode"] != "offline_shadow":
        raise ValueError("W6-v4 campaign mode must be offline_shadow")
    for field in ("campaign_id", "frozen_at", "purpose"):
        if not isinstance(config[field], str) or not config[field].strip():
            raise ValueError(f"campaign.{field} must be non-empty")
    if any(
        config[field] is not False
        for field in (
            "api_calls_allowed",
            "live_provider_calls_allowed",
            "compute_submission_allowed",
        )
    ):
        raise ValueError("W6-v4 offline campaign cannot authorize external actions")
    paths, input_audit = _validate_bound_inputs(
        config["inputs"],
        repo_root=repo_root,
    )
    boundary_audit = _validate_historical_boundary(
        config["historical_boundary"],
        repo_root=repo_root,
    )
    _validate_campaign_contract(config["campaign_contract"])
    _validate_orchestration_contract(config["orchestration_contract"])
    _validate_fixtures(config)
    _validate_pass_criteria(config["pass_criteria"])
    resolved_config = config_path.resolve()
    try:
        config_label = str(resolved_config.relative_to(repo_root.resolve()))
    except ValueError:
        config_label = str(resolved_config)
    return (
        config,
        paths,
        {
            "config_path": config_label,
            "config_sha256": _sha256_file(config_path),
            "inputs": input_audit,
            "historical_boundary": boundary_audit,
        },
    )


@dataclass
class CampaignRun:
    campaign_sha256: str
    control_sha256: str
    action_counts: Dict[str, int]
    rounds_run: int
    assays_used: int
    gate_calibrated: bool
    hard_stop_reason: Optional[str]
    events: List[Dict[str, Any]]
    prompt: Optional[str]


def _control_view(result: Any) -> Dict[str, Any]:
    per_round = []
    for row in result.per_round:
        clean = dict(row)
        clean.pop("orchestrator_recommendation", None)
        clean.pop("llm_hypothesis", None)
        clean.pop("llm_explore", None)
        per_round.append(clean)
    return {
        "status": result.status,
        "allowed": result.allowed,
        "target": result.target,
        "rounds_run": result.rounds_run,
        "assays_used": result.assays_used,
        "gate_calibrated": result.gate_calibrated,
        "screen_backend": result.screen_backend,
        "aggregate": result.aggregate,
        "per_round": per_round,
        "best": result.best,
        "rows": result.rows,
    }


def run_frozen_campaign(
    config: Mapping[str, Any],
    paths: Mapping[str, Path],
    *,
    provider: Any,
    out_dir: Path,
) -> CampaignRun:
    """Run one local W6-v4 campaign arm with no generation or prediction."""

    contract = config["campaign_contract"]
    spec = ObjectiveSpec(
        target=contract["target"],
        objective=contract["objective"],
        lam=contract["lambda"],
        rounds=contract["rounds"],
        candidates_per_round=contract["candidates_per_round"],
        assay_budget=contract["assay_budget"],
    )
    result = DBTLController(
        generator=PrecomputedGenerator(str(paths["candidates"])),
        predictor=PrecomputedStructurePredictor(str(paths["records"])),
        screen=PrecomputedScreen(str(paths["verdicts"])),
        provider=provider,
        orchestration_mode="shadow",
    ).run(spec, out_dir=str(out_dir))
    campaign_path = Path(result.campaign_path or "")
    if not campaign_path.is_file():
        raise RuntimeError("W6-v4 campaign artifact was not written")
    action_counts = Counter(row["action"] for row in result.rows)
    events = result.orchestration_events
    prompt = events[0].get("prompt") if len(events) == 1 else None
    control = _control_view(result)
    return CampaignRun(
        campaign_sha256=_sha256_file(campaign_path),
        control_sha256=_sha256_bytes(_canonical_json(control).encode("utf-8")),
        action_counts={
            action: action_counts.get(action, 0) for action in sorted(_ACTIONS)
        },
        rounds_run=result.rounds_run,
        assays_used=result.assays_used,
        gate_calibrated=result.gate_calibrated,
        hard_stop_reason=(
            result.per_round[-1].get("stop_reason") if result.per_round else None
        ),
        events=events,
        prompt=prompt,
    )


class _StaticProvider:
    provider_name = "fixture"
    model = "w6-v4-static-offline"

    def __init__(self, raw_response: str) -> None:
        self.raw_response = raw_response
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        return self.raw_response


class OfflineProviderFailure(RuntimeError):
    status_code = 503


class _FailureProvider:
    provider_name = "fixture"
    model = "w6-v4-provider-error-offline"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        raise OfflineProviderFailure("secret-bearing offline fixture message")


def _provider_for_fixture(fixture: Mapping[str, Any]) -> Any:
    kind = fixture["kind"]
    if kind == "response":
        return _StaticProvider(_canonical_json(fixture["response"]))
    if kind == "raw_text":
        return _StaticProvider(fixture["raw_text"])
    if kind == "provider_error":
        return _FailureProvider()
    raise ValueError(f"unsupported fixture kind: {kind}")


def _prompt_privacy_audit(
    prompt: Any,
    *,
    paths: Mapping[str, Path],
) -> Dict[str, Any]:
    if not isinstance(prompt, str) or _PROMPT_MARKER not in prompt:
        return {"ok": False, "reason": "missing_prompt_or_state"}
    state_text = prompt.split(_PROMPT_MARKER, 1)[1]
    try:
        state = json.loads(state_text)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "state_is_not_json"}
    expected_state_fields = {
        "authority",
        "deterministic_controller_decision",
        "campaign",
        "recent_aggregate_results",
    }
    candidate_rows = _load_jsonl(paths["candidates"])
    candidate_ids = [
        row["id"]
        for row in candidate_rows
        if isinstance(row.get("id"), str) and row["id"]
    ]
    sequences = []
    for row in candidate_rows:
        for field in ("representation", "target_seq"):
            value = row.get(field)
            if isinstance(value, str) and len(value) >= 20:
                sequences.append(value)
    forbidden_literals = {
        "hidden_truth": "hidden_truth" in prompt,
        "representation": '"representation"' in prompt,
        "target_seq": '"target_seq"' in prompt,
        "candidate_id": '"candidate_id"' in prompt,
    }
    candidate_id_hits = [value for value in candidate_ids if value in prompt]
    sequence_hits = [value for value in sequences if value in prompt]
    recent = state.get("recent_aggregate_results", [])
    aggregate_only = bool(
        isinstance(recent, list)
        and len(recent) == 1
        and isinstance(recent[0], dict)
        and set(recent[0]) == {"round", "summary"}
    )
    return {
        "ok": (
            isinstance(state, dict)
            and set(state) == expected_state_fields
            and not any(forbidden_literals.values())
            and not candidate_id_hits
            and not sequence_hits
            and aggregate_only
        ),
        "state_fields": sorted(state) if isinstance(state, dict) else None,
        "forbidden_literal_hits": sorted(
            key for key, hit in forbidden_literals.items() if hit
        ),
        "candidate_id_hit_count": len(candidate_id_hits),
        "sequence_hit_count": len(sequence_hits),
        "aggregate_only": aggregate_only,
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
    }


def _preflight_audits(
    config: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    current = preflight_batch_round(
        str(paths["candidates"]),
        str(paths["records"]),
        verdicts_path=str(paths["verdicts"]),
        strict_complex_records=True,
    )
    boundary = config["historical_boundary"]
    historical_probe = preflight_batch_round(
        str(paths["candidates"]),
        str(paths["records"]),
        verdicts_path=str(paths["verdicts"]),
        strict_complex_records=True,
        prevalidate_records_paths=[str(paths["historical_prevalidation_records"])],
        conformal_alpha=boundary["historical_conformal_alpha"],
        conformal_delta=config["campaign_contract"]["conformal_delta"],
    )
    return current, historical_probe


def evaluate_offline_campaign(
    config_path: Path,
    out_path: Path,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    """Replay the real W4 campaign with valid and fail-closed fixture providers."""

    config, paths, provenance = load_and_validate_campaign(
        config_path,
        repo_root=repo_root,
    )
    current_preflight, historical_probe = _preflight_audits(config, paths)
    with tempfile.TemporaryDirectory(prefix="w6_v4_gated_batch_") as temporary:
        root = Path(temporary)
        baseline = run_frozen_campaign(
            config,
            paths,
            provider=None,
            out_dir=root / "baseline",
        )
        valid_response = config["valid_fixture"]["response"]
        valid_provider = _StaticProvider(_canonical_json(valid_response))
        valid = run_frozen_campaign(
            config,
            paths,
            provider=valid_provider,
            out_dir=root / "valid",
        )
        adversarial_results = []
        fixture_calls = valid_provider.calls
        for index, fixture in enumerate(config["adversarial_fixtures"]):
            provider = _provider_for_fixture(fixture)
            run = run_frozen_campaign(
                config,
                paths,
                provider=provider,
                out_dir=root / f"adversarial_{index:02d}",
            )
            fixture_calls += provider.calls
            event = run.events[0] if len(run.events) == 1 else {}
            event_json = _canonical_json(event)
            adversarial_results.append(
                {
                    "fixture_id": fixture["fixture_id"],
                    "expected_event_status": fixture["expected_event_status"],
                    "observed_event_status": event.get("status"),
                    "provider_calls": provider.calls,
                    "event_count": len(run.events),
                    "applied": event.get("applied"),
                    "campaign_sha256": run.campaign_sha256,
                    "control_sha256": run.control_sha256,
                    "campaign_identical": (
                        run.campaign_sha256 == baseline.campaign_sha256
                    ),
                    "control_identical": (
                        run.control_sha256 == baseline.control_sha256
                    ),
                    "raw_provider_error_message_absent": (
                        "secret-bearing offline fixture message" not in event_json
                    ),
                    "passed": (
                        provider.calls == 1
                        and len(run.events) == 1
                        and event.get("status") == fixture["expected_event_status"]
                        and event.get("applied") is False
                        and run.campaign_sha256 == baseline.campaign_sha256
                        and run.control_sha256 == baseline.control_sha256
                        and "secret-bearing offline fixture message" not in event_json
                    ),
                }
            )

    valid_event = valid.events[0] if len(valid.events) == 1 else {}
    review = config["valid_fixture"]["review"]
    prompt_audit = _prompt_privacy_audit(valid.prompt, paths=paths)
    expected = config["campaign_contract"]
    current_complex_qc = current_preflight.get("complex_records_qc") or {}
    historical_failure_kinds = {
        failure.get("kind") for failure in historical_probe.get("failures", [])
    }
    checks = {
        "current_preflight_ok": current_preflight.get("ok") is True,
        "historical_prevalidation_refused": (
            historical_probe.get("ok") is False
            and "gate_prevalidation_blocked" in historical_failure_kinds
        ),
        "strict_complex_qc": current_complex_qc.get("ok") is True,
        "baseline_expected_actions": (
            baseline.action_counts == expected["expected_action_counts"]
            and baseline.rounds_run == expected["expected_rounds_run"]
            and baseline.assays_used == expected["expected_assays_used"]
            and baseline.gate_calibrated is expected["expected_gate_calibrated"]
            and baseline.hard_stop_reason == expected["expected_hard_stop_reason"]
        ),
        "valid_fixture_accepted": (
            valid_provider.calls == 1
            and len(valid.events) == 1
            and valid_event.get("status") == "accepted"
            and valid_event.get("recommendation") == valid_response
        ),
        "valid_review_complete": review["status"] == "complete",
        "valid_review_all_positive": all(
            review[field] for field in ("grounded", "actionable", "incremental_value")
        ),
        "valid_campaign_bytes_identical": (
            valid.campaign_sha256 == baseline.campaign_sha256
        ),
        "valid_control_view_identical": (
            valid.control_sha256 == baseline.control_sha256
        ),
        "valid_recommendation_not_applied": valid_event.get("applied") is False,
        "all_adversarial_fixtures_fail_closed": all(
            item["passed"] for item in adversarial_results
        ),
        "prompt_privacy": prompt_audit["ok"] is True,
        "no_external_actions": True,
    }
    passed = all(checks.values())
    report = {
        "schema_version": REPORT_SCHEMA,
        "status": (
            "w6_v4_gated_batch_offline_pass"
            if passed
            else "w6_v4_gated_batch_offline_fail"
        ),
        "passed": passed,
        "campaign_id": config["campaign_id"],
        "provenance": provenance,
        "scientific_boundary": {
            "historical_prevalidation_claimed_ok": True,
            "current_historical_probe_ok": historical_probe.get("ok"),
            "current_campaign_uses_prevalidation": False,
            "historical_certificate_reused": False,
            "interpretation": config["historical_boundary"]["correction"],
        },
        "current_preflight": {
            "ok": current_preflight.get("ok"),
            "candidate_count": current_preflight.get("n_candidates"),
            "record_count": current_preflight.get("n_records"),
            "verdict_count": current_preflight.get("n_verdicts"),
            "strict_complex_records": current_preflight.get("strict_complex_records"),
            "complex_qc_ok": current_complex_qc.get("ok"),
            "gate_prevalidation_requested": (
                current_preflight.get("gate_prevalidation") or {}
            ).get("requested"),
        },
        "baseline": {
            "campaign_sha256": baseline.campaign_sha256,
            "control_sha256": baseline.control_sha256,
            "action_counts": baseline.action_counts,
            "rounds_run": baseline.rounds_run,
            "assays_used": baseline.assays_used,
            "gate_calibrated": baseline.gate_calibrated,
            "hard_stop_reason": baseline.hard_stop_reason,
        },
        "valid_fixture": {
            "provider_calls": valid_provider.calls,
            "event_count": len(valid.events),
            "event_status": valid_event.get("status"),
            "applied": valid_event.get("applied"),
            "campaign_sha256": valid.campaign_sha256,
            "control_sha256": valid.control_sha256,
            "review": review,
        },
        "adversarial_fixtures": adversarial_results,
        "prompt_privacy_audit": prompt_audit,
        "checks": checks,
        "offline_fixture_invocations": fixture_calls,
        "api_calls": 0,
        "live_provider_calls": 0,
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "live_execution_authorized": False,
        "prospective_live_validation_complete": False,
        "m7_complete": False,
    }
    _write_json(out_path, report)
    return report


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="validate or replay the W6-v4 gated batch campaign"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--config",
        type=_path,
        default=Path("configs/w6_v4_gated_batch_campaign.json"),
    )

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument(
        "--config",
        type=_path,
        default=Path("configs/w6_v4_gated_batch_campaign.json"),
    )
    evaluate_parser.add_argument("--out", type=_path, required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "validate":
        config, _, provenance = load_and_validate_campaign(
            args.config,
            repo_root=repo_root,
        )
        print(
            f"status=w6_v4_campaign_valid campaign_id={config['campaign_id']} "
            f"config_sha256={provenance['config_sha256']} "
            "api_calls=0 live_provider_calls=0 compute_submissions=0"
        )
        return 0
    report = evaluate_offline_campaign(
        args.config,
        args.out,
        repo_root=repo_root,
    )
    print(
        f"status={report['status']} passed={str(report['passed']).lower()} "
        f"fixtures={report['offline_fixture_invocations']} "
        "api_calls=0 live_provider_calls=0 compute_submissions=0"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
