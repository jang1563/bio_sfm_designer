"""Predeclare the M6d W3 third-predictor execution contract without spend.

The W3 challenge manifest pins the 18-row Boltz-vs-Chai adjudication panel.
This helper turns that panel into the next execution-contract artifact: what a
future third predictor/protocol must consume and emit, while still refusing to
emit commands, wrappers, API calls, GPU work, or a positive robustness claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_READY_STATUS = "w3_third_predictor_contract_ready_no_submit"
_BLOCKED_STATUS = "w3_third_predictor_contract_blocked"
_NEXT_READY_STATUS = "w3_next_protocol_ready_no_spend"
_CHALLENGE_READY_STATUS = "w3_challenge_manifest_ready_no_submit"
_PRIMARY_ROUTE = "third_independent_predictor_or_protocol"
_SECONDARY_ROUTE = "stronger_chai_msa_template_protocol"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _route_names(next_protocol: Dict[str, Any]) -> List[str]:
    routes = next_protocol.get("recommended_next_routes")
    if not isinstance(routes, list):
        return []
    return [
        route.get("route")
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("route"), str)
    ]


def _int_counts(obj: Any) -> Dict[str, int]:
    if not isinstance(obj, dict):
        return {}
    return {
        str(key): value
        for key, value in obj.items()
        if isinstance(key, str) and isinstance(value, int)
    }


def _target_ids(challenge_manifest: Dict[str, Any]) -> List[str]:
    panel = challenge_manifest.get("challenge_panel")
    if not isinstance(panel, dict):
        return []
    values = panel.get("target_ids")
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _panel_counts(challenge_manifest: Dict[str, Any]) -> Dict[str, int]:
    panel = challenge_manifest.get("challenge_panel")
    if not isinstance(panel, dict):
        return {}
    return _int_counts(panel.get("counts_by_role"))


def _panel_rows(challenge_manifest: Dict[str, Any]) -> Optional[int]:
    panel = challenge_manifest.get("challenge_panel")
    if not isinstance(panel, dict):
        return None
    rows = panel.get("n_rows")
    return rows if isinstance(rows, int) else None


def _source_predictors(challenge_manifest: Dict[str, Any]) -> List[str]:
    predictors = set()
    for row in challenge_manifest.get("rows", []):
        if not isinstance(row, dict):
            continue
        labels = row.get("source_labels")
        if not isinstance(labels, dict):
            continue
        for key in ("predictor_a", "predictor_b"):
            value = labels.get(key)
            if isinstance(value, str) and value:
                predictors.add(value)
    return sorted(predictors)


def _required_schema(next_protocol: Dict[str, Any],
                     challenge_manifest: Dict[str, Any]) -> List[str]:
    challenge_decision = challenge_manifest.get("decision_contract")
    if isinstance(challenge_decision, dict) and isinstance(challenge_decision.get("future_result_schema"), list):
        return [str(field) for field in challenge_decision["future_result_schema"]]
    next_decision = next_protocol.get("decision_contract")
    if isinstance(next_decision, dict) and isinstance(next_decision.get("future_result_schema"), list):
        return [str(field) for field in next_decision["future_result_schema"]]
    return [
        "target_id",
        "predictor_or_protocol_id",
        "label",
        "label_threshold",
        "complex_target_id",
        "target_chain",
        "binder_chain",
        "signal_source",
        "label_source",
        "provenance",
    ]


def _validate_inputs(next_protocol: Dict[str, Any],
                     challenge_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []

    if next_protocol.get("status") != _NEXT_READY_STATUS:
        _add_failure(
            failures,
            "w3_third_contract_next_protocol_status_invalid",
            "third-predictor contract requires the no-spend W3 next protocol to be ready",
            expected=_NEXT_READY_STATUS,
            observed=next_protocol.get("status"),
        )
    if next_protocol.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_third_contract_next_protocol_audit_not_ok",
            "third-predictor contract requires the W3 next-protocol audit to pass",
            expected=True,
            observed=next_protocol.get("audit_ok"),
        )
    if _route_names(next_protocol)[:1] != [_PRIMARY_ROUTE]:
        _add_failure(
            failures,
            "w3_third_contract_primary_route_mismatch",
            "third-predictor contract only applies to the primary third-predictor route",
            expected=_PRIMARY_ROUTE,
            observed=_route_names(next_protocol)[:1],
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if next_protocol.get(field) is not True:
            _add_failure(
                failures,
                f"w3_third_contract_next_protocol_{field}_not_true",
                "third-predictor contract must inherit the no-submit/no-spend boundary",
                expected=True,
                observed=next_protocol.get(field),
            )
    if next_protocol.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_third_contract_next_protocol_claim_leak",
            "third-predictor contract cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=next_protocol.get("can_claim_independent_predictor_robustness_now"),
        )

    if challenge_manifest.get("status") != _CHALLENGE_READY_STATUS:
        _add_failure(
            failures,
            "w3_third_contract_challenge_status_invalid",
            "third-predictor contract requires the W3 challenge manifest to be ready",
            expected=_CHALLENGE_READY_STATUS,
            observed=challenge_manifest.get("status"),
        )
    if challenge_manifest.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_third_contract_challenge_audit_not_ok",
            "third-predictor contract requires the challenge manifest audit to pass",
            expected=True,
            observed=challenge_manifest.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if challenge_manifest.get(field) is not True:
            _add_failure(
                failures,
                f"w3_third_contract_challenge_{field}_not_true",
                "third-predictor contract must inherit the challenge-manifest no-submit/no-spend boundary",
                expected=True,
                observed=challenge_manifest.get(field),
            )
    if challenge_manifest.get("execution_ready") is not False:
        _add_failure(
            failures,
            "w3_third_contract_challenge_execution_ready_drift",
            "third-predictor contract may not start from an execution-ready challenge manifest",
            expected=False,
            observed=challenge_manifest.get("execution_ready"),
        )
    if challenge_manifest.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_third_contract_challenge_claim_leak",
            "third-predictor contract cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=challenge_manifest.get("can_claim_independent_predictor_robustness_now"),
        )
    if challenge_manifest.get("recommended_next_route") != _PRIMARY_ROUTE:
        _add_failure(
            failures,
            "w3_third_contract_challenge_route_mismatch",
            "third-predictor contract must extend the challenge manifest's primary route",
            expected=_PRIMARY_ROUTE,
            observed=challenge_manifest.get("recommended_next_route"),
        )

    set_contract = next_protocol.get("adjudication_set_contract")
    if not isinstance(set_contract, dict):
        _add_failure(
            failures,
            "w3_third_contract_adjudication_contract_missing",
            "W3 next protocol must contain adjudication_set_contract",
        )
        set_contract = {}
    expected_rows = set_contract.get("n_rows")
    observed_rows = _panel_rows(challenge_manifest)
    if expected_rows != observed_rows:
        _add_failure(
            failures,
            "w3_third_contract_row_count_mismatch",
            "challenge panel row count must match the W3 next-protocol adjudication contract",
            expected=expected_rows,
            observed=observed_rows,
        )
    expected_counts = _int_counts(set_contract.get("counts_by_role"))
    observed_counts = _panel_counts(challenge_manifest)
    if expected_counts != observed_counts:
        _add_failure(
            failures,
            "w3_third_contract_role_count_mismatch",
            "challenge panel role counts must match the W3 next-protocol adjudication contract",
            expected=expected_counts,
            observed=observed_counts,
        )
    if not _target_ids(challenge_manifest):
        _add_failure(
            failures,
            "w3_third_contract_target_ids_missing",
            "challenge manifest must provide selected target IDs for the third-predictor contract",
        )
    if not _required_schema(next_protocol, challenge_manifest):
        _add_failure(
            failures,
            "w3_third_contract_result_schema_missing",
            "third-predictor contract requires a future-result schema",
        )
    return failures


def _input_rows(challenge_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in challenge_manifest.get("rows", []):
        if not isinstance(row, dict):
            continue
        rows.append({
            "challenge_rank": row.get("challenge_rank"),
            "target_id": row.get("target_id"),
            "adjudication_role": row.get("adjudication_role"),
            "complex_target_id": row.get("complex_target_id"),
            "strict_target_identity": row.get("strict_target_identity"),
            "strict_label_threshold": row.get("strict_label_threshold"),
            "source_labels": row.get("source_labels"),
            "source_label_metrics": row.get("source_label_metrics"),
        })
    return rows


def build_contract(next_protocol: Dict[str, Any],
                   challenge_manifest: Dict[str, Any],
                   *,
                   planned_result_jsonl: str = "results/m6d_w3_third_predictor_challenge_records.jsonl",
                   report_date: Optional[str] = None) -> Dict[str, Any]:
    failures = _validate_inputs(next_protocol, challenge_manifest)
    audit_ok = not failures
    target_ids = _target_ids(challenge_manifest)
    counts = _panel_counts(challenge_manifest)
    required_schema = _required_schema(next_protocol, challenge_manifest)
    challenge_path = challenge_manifest.get("_path")
    challenge_sha = (
        _sha256_file(challenge_path)
        if isinstance(challenge_path, str) and os.path.exists(challenge_path)
        else None
    )
    decision = challenge_manifest.get("decision_contract")
    if not isinstance(decision, dict):
        decision = {}

    return {
        "artifact": "m6d_w3_third_predictor_contract",
        "date": report_date or date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "claim_boundary": (
            "third-predictor execution contract only; not an executed predictor result "
            "and not a positive independent-predictor robustness claim"
        ),
        "source_next_protocol": next_protocol.get("_path"),
        "source_challenge_manifest": challenge_path,
        "source_challenge_manifest_sha256": challenge_sha,
        "challenge_panel_contract": {
            "n_rows": _panel_rows(challenge_manifest),
            "counts_by_role": counts,
            "target_ids": target_ids,
            "source_adjudication_jsonl": challenge_manifest.get("source_adjudication_jsonl"),
            "source_adjudication_sha256": challenge_manifest.get("source_adjudication_sha256"),
        },
        "predictor_selection_contract": {
            "route": _PRIMARY_ROUTE,
            "source_predictors_to_adjudicate": _source_predictors(challenge_manifest),
            "disallowed_as_independent_closure": [
                "boltz2_complex",
                "chai1_complex",
                "same_no_msa_chai1_protocol",
            ],
            "required_selection_fields": [
                "predictor_or_protocol_id",
                "model_or_protocol_family",
                "version",
                "msa_policy",
                "template_policy",
                "runtime_environment",
                "label_source",
                "signal_source",
                "approval_gate",
            ],
            "secondary_route_requires_new_contract": _SECONDARY_ROUTE,
        },
        "input_contract": {
            "n_rows": len(target_ids),
            "target_ids": target_ids,
            "rows": _input_rows(challenge_manifest),
        },
        "output_contract": {
            "planned_jsonl": planned_result_jsonl,
            "required_n_rows": len(target_ids),
            "required_target_ids": target_ids,
            "required_result_schema": required_schema,
            "strict_qc": [
                "one result row per challenge target_id",
                "target_id set must equal challenge_panel_contract.target_ids",
                "complex_target_id must remain strict and unchanged",
                "label_threshold and label_source must be declared per row",
                "provenance must include predictor/protocol version and input hash",
            ],
        },
        "decision_contract": {
            "stage": decision.get("stage"),
            "discordant_alignment_threshold": decision.get("discordant_alignment_threshold"),
            "control_consistency_threshold": decision.get("control_consistency_threshold"),
            "outcomes": decision.get("outcomes", []),
            "threshold_note": decision.get("threshold_note"),
        },
        "future_artifacts_required": [
            "selected_predictor_protocol_card",
            "execution_input_manifest",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
            "third_predictor_result_qc_report",
            "w3_challenge_panel_adjudication_report",
        ],
        "execution_blockers": [
            "third predictor/protocol implementation has not been selected",
            "execution inputs are not emitted by this contract",
            "approval-gated command wrapper is not emitted by this contract",
            "explicit approval is required before any API/GPU/HPC execution",
        ],
        "recommended_next_action": (
            "Select a third predictor/protocol implementation and generate an approval-gated "
            "execution-input manifest/wrapper against this contract; do not execute until explicitly approved."
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    panel = rep.get("challenge_panel_contract", {})
    output = rep.get("output_contract", {})
    selection = rep.get("predictor_selection_contract", {})
    decision = rep.get("decision_contract", {})
    lines = [
        "# M6d W3 Third-Predictor Contract",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit, no-API, no-GPU execution contract. It emits no command wrapper and does not support a positive W3 robustness claim.",
        "",
        "## Challenge Panel",
        "",
        f"- Rows: `{panel.get('n_rows')}`",
        f"- Counts by role: `{panel.get('counts_by_role')}`",
        f"- Challenge manifest SHA-256: `{rep.get('source_challenge_manifest_sha256')}`",
        "",
        "## Predictor Selection Contract",
        "",
        f"- Route: `{selection.get('route')}`",
        f"- Source predictors to adjudicate: `{selection.get('source_predictors_to_adjudicate')}`",
        f"- Disallowed as independent closure: `{selection.get('disallowed_as_independent_closure')}`",
        f"- Required selection fields: `{selection.get('required_selection_fields')}`",
        "",
        "## Output Contract",
        "",
        f"- Planned JSONL: `{output.get('planned_jsonl')}`",
        f"- Required rows: `{output.get('required_n_rows')}`",
        f"- Required schema: `{output.get('required_result_schema')}`",
        "",
        "Strict QC:",
    ]
    lines.extend(f"- {item}" for item in output.get("strict_qc", []))
    lines.extend([
        "",
        "## Decision Contract",
        "",
        f"- Discordant alignment threshold: `{decision.get('discordant_alignment_threshold')}`",
        f"- Control consistency threshold: `{decision.get('control_consistency_threshold')}`",
        f"- Note: {decision.get('threshold_note')}",
        "",
        "## Execution Blockers",
        "",
    ])
    lines.extend(f"- {blocker}" for blocker in rep.get("execution_blockers", []))
    lines.extend(["", "## Future Artifacts Required", ""])
    lines.extend(f"- {item}" for item in rep.get("future_artifacts_required", []))
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
    lines.extend([
        "",
        f"Recommended next action: {rep.get('recommended_next_action')}",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--w3-next-protocol", default="results/m6d_w3_next_protocol.json")
    ap.add_argument("--w3-challenge-manifest", default="results/m6d_w3_challenge_manifest.json")
    ap.add_argument("--planned-result-jsonl", default="results/m6d_w3_third_predictor_challenge_records.jsonl")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_third_predictor_contract.json")
    ap.add_argument("--out-md", default="results/m6d_w3_third_predictor_contract.md")
    args = ap.parse_args(argv)

    rep = build_contract(
        _load_json(args.w3_next_protocol),
        _load_json(args.w3_challenge_manifest),
        planned_result_jsonl=args.planned_result_jsonl,
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} execution_ready={ready} command_wrapper_emitted={wrapper} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            ready=rep["execution_ready"],
            wrapper=rep["command_wrapper_emitted"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
