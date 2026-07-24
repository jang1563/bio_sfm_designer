"""Freeze and score the independent W6-v3.1 transport-successor panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .w6_v2_shadow_panel import (
    _FORBIDDEN_STATE_KEYS,
    _canonical_json,
    _load_json,
    _load_jsonl,
    _sha256_file,
    _sha256_text,
    _validate_review,
    _walk_keys,
    _write_json,
    _write_jsonl,
)
from .w6_v3_hypothesis_only import (
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    _score_bound_records,
    _validate_request_records,
    build_case_prompt,
)
from .w6_v3_prospective_panel import (
    _adversarial_payload,
    _contract_view,
    _validate_digest,
    _validate_pass_criteria,
    _validate_string_list,
)


PANEL_SCHEMA = "w6_v31_transport_panel_v1"
FREEZE_SCHEMA = "w6_v31_transport_panel_freeze_v1"
_ROOT_FIELDS = {
    "schema_version",
    "panel_id",
    "frozen_at",
    "mode",
    "contract_variant",
    "prospective_live_panel",
    "api_calls_allowed",
    "provider_calls_allowed",
    "compute_submission_allowed",
    "case_count",
    "purpose",
    "transport_hypothesis",
    "independence_contract",
    "scope_taxonomy",
    "review_rubric",
    "pass_criteria",
    "cases",
}
_TRANSPORT_FIELDS = {
    "baseline_scope_path",
    "baseline_scope_sha256",
    "baseline_score_path",
    "baseline_score_sha256",
    "baseline_max_output_tokens",
    "successor_max_output_tokens",
    "primary_change",
    "unchanged_factors",
    "failure_mechanism",
}
_INDEPENDENCE_FIELDS = {
    "source_kind",
    "prior_provider_outputs_used_for_case_construction",
    "prior_provider_reviews_used_for_case_construction",
    "prior_artifacts_used_for_exclusion_audit_only",
    "generic_dbtl_concepts_may_overlap",
    "exact_state_or_answer_reuse_forbidden",
    "excluded_panels",
    "forbidden_source_paths",
    "forbidden_case_ids",
}
_EXCLUDED_PANEL_FIELDS = {"path", "panel_id", "sha256"}
_CASE_FIELDS = {
    "case_id",
    "workstream",
    "scenario_family",
    "aggregate_state",
    "expected",
    "fixture_proposal",
}
_EXPECTED_FIELDS = {
    "stop",
    "explore",
    "allowed_scope_tags",
    "consistency_group",
    "baseline_plan",
    "rationale",
}
_FIXTURE_FIELDS = {"reason", "hypothesis", "review"}
_MIN_CASES = 12
_MAX_CASES = 20


def _validate_transport_hypothesis(
    transport: Any,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    if not isinstance(transport, dict) or set(transport) != _TRANSPORT_FIELDS:
        raise ValueError("transport_hypothesis has an invalid contract")
    if transport["primary_change"] != "max_output_tokens_per_call":
        raise ValueError("W6-v3.1 must isolate the output-token cap")
    if transport["baseline_max_output_tokens"] != 256:
        raise ValueError("W6-v3.1 baseline output cap must be 256")
    if transport["successor_max_output_tokens"] != 512:
        raise ValueError("W6-v3.1 successor output cap must be 512")
    required_unchanged = {
        "provider",
        "model",
        "prompt_template",
        "response_schema",
        "authority_boundary",
        "review_rubric",
        "pass_criteria",
        "retry_policy",
        "shadow_no_effect",
    }
    unchanged = set(
        _validate_string_list(
            transport["unchanged_factors"],
            label="transport_hypothesis.unchanged_factors",
        )
    )
    if unchanged != required_unchanged:
        raise ValueError("transport_hypothesis does not freeze all required factors")
    if transport["failure_mechanism"] != "five_responses_truncated_mid_json":
        raise ValueError("transport_hypothesis must name the observed failure")

    observed = {}
    for path_key, sha_key in (
        ("baseline_scope_path", "baseline_scope_sha256"),
        ("baseline_score_path", "baseline_score_sha256"),
    ):
        raw_path = transport[path_key]
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"transport_hypothesis.{path_key} must be non-empty")
        path = repo_root / raw_path
        if not path.is_file():
            raise ValueError(f"transport baseline artifact is missing: {raw_path}")
        expected_sha256 = _validate_digest(
            transport[sha_key],
            label=f"transport_hypothesis.{sha_key}",
        )
        observed_sha256 = _sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise ValueError(f"transport baseline SHA-256 mismatch: {raw_path}")
        observed[path_key] = {
            "path": raw_path,
            "expected_sha256": expected_sha256,
            "observed_sha256": observed_sha256,
        }
    baseline_score = _load_json(repo_root / transport["baseline_score_path"])
    if baseline_score.get("status") != "prospective_live_validation_fail":
        raise ValueError("baseline score must be the failed prospective result")
    metrics = baseline_score.get("metrics", {})
    if (
        metrics.get("schema_acceptance_count") != 11
        or metrics.get("case_count") != 16
        or metrics.get("control_plane_violation_count") != 0
    ):
        raise ValueError("baseline score does not match the frozen failure")
    return {
        "primary_change": "max_output_tokens_per_call",
        "baseline_max_output_tokens": 256,
        "successor_max_output_tokens": 512,
        "baseline_schema_acceptance_count": 11,
        "baseline_case_count": 16,
        "baseline_authority_violation_count": 0,
        "artifacts": observed,
        "ok": True,
    }


def _load_excluded_panels(
    independence: Mapping[str, Any],
    *,
    repo_root: Path,
) -> Tuple[List[Dict[str, Any]], set[str], set[str]]:
    specs = independence["excluded_panels"]
    if not isinstance(specs, list) or len(specs) != 2:
        raise ValueError("independence_contract must exclude exactly two panels")
    panels = []
    case_ids: set[str] = set()
    state_hashes: set[str] = set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != _EXCLUDED_PANEL_FIELDS:
            raise ValueError("excluded panel entry has an invalid contract")
        raw_path = spec["path"]
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("excluded panel path must be non-empty")
        path = repo_root / raw_path
        expected_sha256 = _validate_digest(
            spec["sha256"],
            label=f"excluded panel SHA-256 ({raw_path})",
        )
        observed_sha256 = _sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise ValueError(f"excluded panel SHA-256 mismatch: {raw_path}")
        panel = _load_json(path)
        if panel.get("panel_id") != spec["panel_id"]:
            raise ValueError(f"excluded panel id mismatch: {raw_path}")
        panel_case_ids = {case.get("case_id") for case in panel.get("cases", [])}
        if None in panel_case_ids or case_ids & panel_case_ids:
            raise ValueError("excluded panel case ids are invalid or duplicated")
        case_ids.update(panel_case_ids)
        state_hashes.update(
            _sha256_text(_canonical_json(case["aggregate_state"]))
            for case in panel["cases"]
        )
        panels.append(
            {
                "path": raw_path,
                "panel_id": panel["panel_id"],
                "expected_sha256": expected_sha256,
                "observed_sha256": observed_sha256,
                "case_count": len(panel["cases"]),
            }
        )
    return panels, case_ids, state_hashes


def _prior_answer_hashes(repo_root: Path) -> set[str]:
    hashes: set[str] = set()
    prior_panel = _load_json(
        repo_root / "configs/w6_v3_prospective_hypothesis_panel.json"
    )
    for case in prior_panel["cases"]:
        fixture = case["fixture_proposal"]
        hashes.add(
            _sha256_text(
                _canonical_json(
                    {
                        "reason": fixture["reason"],
                        "hypothesis": fixture["hypothesis"],
                    }
                )
            )
        )
    prior_live = _load_jsonl(
        repo_root
        / "results/w6_v3_prospective_live_anthropic_claude_opus_4_8_20260724_responses_reviewed.jsonl"
    )
    for record in prior_live:
        raw = record["raw_response"]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            hashes.add(_sha256_text(_canonical_json(parsed)))
    return hashes


def _validate_independence(
    panel: Mapping[str, Any],
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    independence = panel["independence_contract"]
    if not isinstance(independence, dict) or set(independence) != _INDEPENDENCE_FIELDS:
        raise ValueError("independence_contract has an invalid contract")
    if independence["source_kind"] != "new_synthetic_counterfactual_states":
        raise ValueError("W6-v3.1 cases must be new synthetic counterfactual states")
    required_false = (
        "prior_provider_outputs_used_for_case_construction",
        "prior_provider_reviews_used_for_case_construction",
    )
    if any(independence[key] is not False for key in required_false):
        raise ValueError("prior provider evidence cannot construct successor cases")
    if independence["prior_artifacts_used_for_exclusion_audit_only"] is not True:
        raise ValueError("prior artifacts may be used only for exclusion auditing")
    if independence["generic_dbtl_concepts_may_overlap"] is not True:
        raise ValueError("generic DBTL concept overlap must be declared")
    if independence["exact_state_or_answer_reuse_forbidden"] is not True:
        raise ValueError("exact state and answer reuse must be forbidden")

    excluded, excluded_case_ids, excluded_state_hashes = _load_excluded_panels(
        independence,
        repo_root=repo_root,
    )
    forbidden_case_ids = set(
        _validate_string_list(
            independence["forbidden_case_ids"],
            label="independence_contract.forbidden_case_ids",
        )
    )
    if forbidden_case_ids != excluded_case_ids:
        raise ValueError("forbidden case ids must exactly cover both prior panels")
    forbidden_paths = _validate_string_list(
        independence["forbidden_source_paths"],
        label="independence_contract.forbidden_source_paths",
    )
    required_paths = {
        "configs/w6_v2_frozen_shadow_panel.json",
        "configs/w6_v3_prospective_hypothesis_panel.json",
        "results/w6_v3_prospective_live_anthropic_claude_opus_4_8_20260724_responses_reviewed.jsonl",
        "results/w6_v3_prospective_live_anthropic_claude_opus_4_8_20260724_annotations.json",
    }
    if not required_paths.issubset(forbidden_paths):
        raise ValueError("independence contract omits a required prior source")

    case_text = _canonical_json(panel["cases"])
    if any(case_id in case_text for case_id in forbidden_case_ids):
        raise ValueError("W6-v3.1 cases reuse a forbidden prior case identifier")
    if any(path in case_text for path in forbidden_paths):
        raise ValueError("W6-v3.1 cases reuse a forbidden prior source path")
    successor_state_hashes = {
        _sha256_text(_canonical_json(case["aggregate_state"]))
        for case in panel["cases"]
    }
    if successor_state_hashes & excluded_state_hashes:
        raise ValueError("W6-v3.1 reuses an excluded aggregate state")
    successor_answer_hashes = {
        _sha256_text(
            _canonical_json(
                {
                    "reason": case["fixture_proposal"]["reason"],
                    "hypothesis": case["fixture_proposal"]["hypothesis"],
                }
            )
        )
        for case in panel["cases"]
    }
    if successor_answer_hashes & _prior_answer_hashes(repo_root):
        raise ValueError("W6-v3.1 reuses an exact prior answer")
    return {
        "excluded_panels": excluded,
        "excluded_case_count": len(excluded_case_ids),
        "excluded_aggregate_state_count": len(excluded_state_hashes),
        "prior_answer_hash_count": len(_prior_answer_hashes(repo_root)),
        "forbidden_source_count": len(forbidden_paths),
        "exact_case_reuse_detected": False,
        "exact_source_reuse_detected": False,
        "exact_aggregate_state_reuse_detected": False,
        "exact_answer_reuse_detected": False,
        "prior_provider_outputs_used_for_case_construction": False,
        "prior_provider_reviews_used_for_case_construction": False,
        "ok": True,
    }


def _validate_cases(
    panel: Mapping[str, Any],
    *,
    scope_set: set[str],
) -> None:
    cases = panel["cases"]
    if not isinstance(cases, list) or not _MIN_CASES <= len(cases) <= _MAX_CASES:
        raise ValueError(f"panel must contain {_MIN_CASES}-{_MAX_CASES} cases")
    if panel["case_count"] != len(cases):
        raise ValueError("panel case_count does not match cases")
    case_ids = []
    state_hashes = set()
    stop_values = []
    explore_values = []
    group_pairs: Dict[str, Tuple[bool, bool]] = {}
    incremental_count = 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != _CASE_FIELDS:
            raise ValueError("W6-v3.1 case fields do not match the schema")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id.startswith("q_"):
            raise ValueError("W6-v3.1 case ids must start with q_")
        case_ids.append(case_id)
        for key in ("workstream", "scenario_family"):
            if not isinstance(case[key], str) or not case[key].strip():
                raise ValueError(f"{case_id}: {key} must be non-empty")
        state = case["aggregate_state"]
        if not isinstance(state, dict) or not state:
            raise ValueError(f"{case_id}: aggregate_state must be non-empty")
        forbidden = sorted(set(_walk_keys(state)) & _FORBIDDEN_STATE_KEYS)
        if forbidden:
            raise ValueError(f"{case_id}: forbidden aggregate-state keys: {forbidden}")
        state_hash = _sha256_text(_canonical_json(state))
        if state_hash in state_hashes:
            raise ValueError("W6-v3.1 aggregate states must be unique")
        state_hashes.add(state_hash)

        expected = case["expected"]
        if not isinstance(expected, dict) or set(expected) != _EXPECTED_FIELDS:
            raise ValueError(f"{case_id}: expected contract is invalid")
        if not isinstance(expected["stop"], bool) or not isinstance(
            expected["explore"], bool
        ):
            raise ValueError(f"{case_id}: stop and explore must be booleans")
        stop_values.append(expected["stop"])
        explore_values.append(expected["explore"])
        scopes = expected["allowed_scope_tags"]
        if (
            not isinstance(scopes, list)
            or not scopes
            or any(scope not in scope_set for scope in scopes)
            or len(scopes) != len(set(scopes))
        ):
            raise ValueError(f"{case_id}: allowed scopes are invalid")
        for key in ("consistency_group", "baseline_plan", "rationale"):
            if not isinstance(expected[key], str) or not expected[key].strip():
                raise ValueError(f"{case_id}: expected.{key} must be non-empty")
        pair = (expected["stop"], expected["explore"])
        group = expected["consistency_group"]
        if group in group_pairs and group_pairs[group] != pair:
            raise ValueError(f"{case_id}: consistency group decision conflict")
        group_pairs[group] = pair

        fixture = case["fixture_proposal"]
        if not isinstance(fixture, dict) or set(fixture) != _FIXTURE_FIELDS:
            raise ValueError(f"{case_id}: fixture proposal contract is invalid")
        if (
            not isinstance(fixture["reason"], str)
            or not fixture["reason"].strip()
            or not isinstance(fixture["hypothesis"], str)
            or not fixture["hypothesis"].strip()
        ):
            raise ValueError(f"{case_id}: fixture proposal text must be non-empty")
        review = _validate_review(fixture["review"])
        if review["status"] != "complete":
            raise ValueError(f"{case_id}: fixture review must be complete")
        if review["scope_tag"] not in scopes:
            raise ValueError(f"{case_id}: fixture scope is not allowed")
        if not review["grounded"] or not review["actionable"]:
            raise ValueError(f"{case_id}: valid fixture must be useful")
        incremental_count += int(review["incremental_value"])

    if len(case_ids) != len(set(case_ids)):
        raise ValueError("W6-v3.1 case ids must be unique")
    if min(stop_values.count(True), stop_values.count(False)) < 4:
        raise ValueError("W6-v3.1 stop states are insufficiently diverse")
    if min(explore_values.count(True), explore_values.count(False)) < 4:
        raise ValueError("W6-v3.1 explore states are insufficiently diverse")
    threshold = panel["pass_criteria"]["min_incremental_value_rate"]
    if incremental_count / len(cases) < threshold:
        raise ValueError("valid fixture cannot meet incremental-value threshold")


def _validate_panel_structure(
    panel: Any,
    *,
    repo_root: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(panel, dict) or set(panel) != _ROOT_FIELDS:
        raise ValueError("W6-v3.1 panel fields do not match the frozen schema")
    if panel["schema_version"] != PANEL_SCHEMA:
        raise ValueError(f"panel schema_version must be {PANEL_SCHEMA}")
    for key in ("panel_id", "frozen_at", "purpose", "contract_variant"):
        if not isinstance(panel[key], str) or not panel[key].strip():
            raise ValueError(f"panel.{key} must be non-empty")
    if panel["mode"] != "offline_shadow":
        raise ValueError("panel mode must be offline_shadow")
    if panel["contract_variant"] != "w6_v3_1_hypothesis_only_512":
        raise ValueError("panel contract_variant is invalid")
    if panel["prospective_live_panel"] is not True:
        raise ValueError("panel must declare prospective_live_panel=true")
    for key in (
        "api_calls_allowed",
        "provider_calls_allowed",
        "compute_submission_allowed",
    ):
        if panel[key] is not False:
            raise ValueError(f"panel must set {key}=false")
    scope_taxonomy = _validate_string_list(
        panel["scope_taxonomy"],
        label="scope_taxonomy",
    )
    rubric = panel["review_rubric"]
    if not isinstance(rubric, dict) or set(rubric) != {
        "grounded",
        "actionable",
        "incremental_value",
        "scope_compliant",
    }:
        raise ValueError("review_rubric has an invalid contract")
    if any(not isinstance(value, str) or not value.strip() for value in rubric.values()):
        raise ValueError("review_rubric values must be non-empty")
    _validate_pass_criteria(panel["pass_criteria"])
    _validate_cases(panel, scope_set=set(scope_taxonomy))
    transport_audit = _validate_transport_hypothesis(
        panel["transport_hypothesis"],
        repo_root=repo_root,
    )
    independence_audit = _validate_independence(panel, repo_root=repo_root)
    return transport_audit, independence_audit


def load_and_validate_panel(
    panel_path: Path,
    *,
    repo_root: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    panel = _load_json(panel_path)
    transport_audit, independence_audit = _validate_panel_structure(
        panel,
        repo_root=repo_root,
    )
    return panel, transport_audit, independence_audit


def build_request_records(
    panel_path: Path,
    *,
    repo_root: Path,
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Build the provider-free W6-v3.1 request packet."""

    panel, transport_audit, independence_audit = load_and_validate_panel(
        panel_path,
        repo_root=repo_root,
    )
    contract = _contract_view(panel, panel_path)
    panel_sha256 = _sha256_file(panel_path)
    records = []
    for case in panel["cases"]:
        prompt = build_case_prompt(contract, panel, case)
        records.append(
            {
                "schema_version": REQUEST_SCHEMA,
                "contract_id": panel["panel_id"],
                "contract_sha256": panel_sha256,
                "panel_id": panel["panel_id"],
                "panel_sha256": panel_sha256,
                "case_id": case["case_id"],
                "workstream": case["workstream"],
                "mode": "offline_shadow",
                "deterministic_decision": {
                    "stop": case["expected"]["stop"],
                    "explore": case["expected"]["explore"],
                },
                "prompt": prompt,
                "prompt_sha256": _sha256_text(prompt),
            }
        )
    return panel, records, transport_audit, independence_audit


def freeze_panel(
    panel_path: Path,
    request_path: Path,
    out_path: Path,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    panel, requests, transport_audit, independence_audit = build_request_records(
        panel_path,
        repo_root=repo_root,
    )
    _write_jsonl(request_path, requests)
    report = {
        "schema_version": FREEZE_SCHEMA,
        "panel_id": panel["panel_id"],
        "status": "w6_v31_transport_panel_frozen_offline",
        "panel_path": str(panel_path),
        "panel_sha256": _sha256_file(panel_path),
        "request_path": str(request_path),
        "request_sha256": _sha256_file(request_path),
        "case_count": len(requests),
        "transport_audit": transport_audit,
        "independence_audit": independence_audit,
        "independent_from_w6_v2_and_w6_v3": True,
        "primary_change": "max_output_tokens_per_call",
        "baseline_max_output_tokens": 256,
        "successor_max_output_tokens": 512,
        "provider_outputs_observed": False,
        "live_provider_evaluated": False,
        "decision_owner": "deterministic_controller",
        "api_calls": 0,
        "provider_calls": 0,
        "compute_submissions": 0,
        "recommendations_applied": 0,
        "live_execution_authorized": False,
        "m7_complete": False,
    }
    _write_json(out_path, report)
    return report


def materialize_fixture_responses(
    panel_path: Path,
    request_path: Path,
    out_path: Path,
    *,
    repo_root: Path,
    fixture_kind: str,
) -> List[Dict[str, Any]]:
    """Bind valid or adversarial fixtures to the frozen W6-v3.1 requests."""

    if fixture_kind not in {"valid", "adversarial"}:
        raise ValueError("fixture_kind must be valid or adversarial")
    panel, _, _ = load_and_validate_panel(panel_path, repo_root=repo_root)
    requests = _load_jsonl(request_path)
    contract = _contract_view(panel, panel_path)
    _validate_request_records(contract, panel, panel_path, requests)
    requests_by_id = {request["case_id"]: request for request in requests}
    if len(requests_by_id) != len(requests):
        raise ValueError("request packet contains duplicate case ids")
    records = []
    for index, case in enumerate(panel["cases"]):
        request = requests_by_id[case["case_id"]]
        if fixture_kind == "valid":
            raw = _canonical_json(
                {
                    "reason": case["fixture_proposal"]["reason"],
                    "hypothesis": case["fixture_proposal"]["hypothesis"],
                }
            )
            review = _validate_review(case["fixture_proposal"]["review"])
        else:
            raw, review = _adversarial_payload(index, case)
            review = _validate_review(review)
        records.append(
            {
                "schema_version": RESPONSE_SCHEMA,
                "response_source": f"synthetic_w6_v31_{fixture_kind}_fixture",
                "case_id": case["case_id"],
                "contract_sha256": request["contract_sha256"],
                "panel_sha256": request["panel_sha256"],
                "prompt_sha256": request["prompt_sha256"],
                "raw_response": raw,
                "response_sha256": _sha256_text(raw),
                "review": review,
            }
        )
    _write_jsonl(out_path, records)
    return records


def score_response_records(
    panel_path: Path,
    request_path: Path,
    response_path: Path,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    panel, transport_audit, independence_audit = load_and_validate_panel(
        panel_path,
        repo_root=repo_root,
    )
    contract = _contract_view(panel, panel_path)
    requests = _load_jsonl(request_path)
    responses = _load_jsonl(response_path)
    report = _score_bound_records(
        contract=contract,
        panel=panel,
        contract_path=panel_path,
        request_path=request_path,
        response_path=response_path,
        requests=requests,
        responses=responses,
    )
    source = report["response_source"]
    fixture_source = source.startswith("synthetic_")
    live_source = source.startswith("live_shadow_")
    review_complete = report["metrics"]["review_completion_rate"] == 1.0
    if fixture_source:
        evaluation_class = "w6_v31_transport_offline_fixture_replay"
        status = report["status"]
    elif live_source and review_complete:
        evaluation_class = "w6_v31_prospective_live_shadow_reviewed"
        status = (
            "w6_v31_prospective_live_validation_pass"
            if report["passed"]
            else "w6_v31_prospective_live_validation_fail"
        )
    elif live_source:
        evaluation_class = "w6_v31_prospective_live_shadow_pending_review"
        status = "w6_v31_prospective_live_review_pending"
    else:
        evaluation_class = "w6_v31_saved_response_replay"
        status = report["status"]
    report.update(
        {
            "status": status,
            "evaluation_class": evaluation_class,
            "transport_audit": transport_audit,
            "independence_audit": independence_audit,
            "independent_from_w6_v2_and_w6_v3": True,
            "primary_change": "max_output_tokens_per_call",
            "baseline_max_output_tokens": 256,
            "successor_max_output_tokens": 512,
            "offline_fixture_only": fixture_source,
            "live_provider_evaluated": live_source,
            "provider_outputs_observed": live_source,
            "source_provider_calls": len(responses) if live_source else 0,
            "scoring_provider_calls": 0,
            "prospective_live_validation_complete": (
                live_source and review_complete
            ),
        }
    )
    return report


def score_responses(
    panel_path: Path,
    request_path: Path,
    response_path: Path,
    out_path: Path,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    report = score_response_records(
        panel_path,
        request_path,
        response_path,
        repo_root=repo_root,
    )
    _write_json(out_path, report)
    return report


def _path(value: str) -> Path:
    return Path(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="freeze and score the W6-v3.1 transport-successor panel"
    )
    parser.add_argument("--repo-root", type=_path, default=Path("."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument(
        "--panel",
        type=_path,
        default=Path("configs/w6_v31_transport_panel.json"),
    )
    freeze_parser.add_argument(
        "--requests",
        type=_path,
        default=Path("results/w6_v31_transport_requests.jsonl"),
    )
    freeze_parser.add_argument(
        "--out",
        type=_path,
        default=Path("results/w6_v31_transport_freeze.json"),
    )

    bind_parser = subparsers.add_parser("bind-fixture")
    bind_parser.add_argument(
        "--panel",
        type=_path,
        default=Path("configs/w6_v31_transport_panel.json"),
    )
    bind_parser.add_argument(
        "--requests",
        type=_path,
        default=Path("results/w6_v31_transport_requests.jsonl"),
    )
    bind_parser.add_argument(
        "--fixture-kind",
        choices=["valid", "adversarial"],
        required=True,
    )
    bind_parser.add_argument("--out", type=_path, required=True)

    score_parser = subparsers.add_parser("score")
    score_parser.add_argument(
        "--panel",
        type=_path,
        default=Path("configs/w6_v31_transport_panel.json"),
    )
    score_parser.add_argument(
        "--requests",
        type=_path,
        default=Path("results/w6_v31_transport_requests.jsonl"),
    )
    score_parser.add_argument("--responses", type=_path, required=True)
    score_parser.add_argument("--out", type=_path, required=True)
    score_parser.add_argument("--expect-fail", action="store_true")

    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "freeze":
        report = freeze_panel(
            args.panel,
            args.requests,
            args.out,
            repo_root=repo_root,
        )
        print(
            f"status={report['status']} cases={report['case_count']} "
            "provider_calls=0 independent=true"
        )
        return 0
    if args.command == "bind-fixture":
        records = materialize_fixture_responses(
            args.panel,
            args.requests,
            args.out,
            repo_root=repo_root,
            fixture_kind=args.fixture_kind,
        )
        print(
            f"status=fixture_bound kind={args.fixture_kind} "
            f"responses={len(records)} provider_calls=0"
        )
        return 0
    report = score_responses(
        args.panel,
        args.requests,
        args.responses,
        args.out,
        repo_root=repo_root,
    )
    print(
        f"status={report['status']} cases={report['metrics']['case_count']} "
        f"authority_violations="
        f"{report['metrics']['control_plane_violation_count']} provider_calls=0"
    )
    if args.expect_fail:
        return 0 if not report["passed"] else 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
