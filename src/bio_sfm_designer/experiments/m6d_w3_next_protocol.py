"""Predeclare the next M6d W3 adjudication protocol without spending compute.

The completed no-MSA Chai comparison is a negative robustness result. This
helper turns the audited 18-row adjudication set into the next allowed W3
science contract. It does not submit jobs, call APIs, or close the independent
predictor caveat.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date
from typing import Any, Dict, List, Optional


_READY_STATUS = "w3_next_protocol_ready_no_spend"
_BLOCKED_STATUS = "w3_next_protocol_blocked"
_EXPECTED_W3_STATUS = "negative_robustness_result_adjudicated"
_EXPECTED_VERDICT = "negative_robustness_result_for_no_msa_chai"
_EXPECTED_BOUNDARY = "independent_predictor_robustness_not_supported"
_EXPECTED_PROTOCOL = "adjudicated_disagreement_protocol_v1"
_EXPECTED_COUNTS = {
    "discordant_boltz_chai_label": 12,
    "concordant_success_control": 6,
}


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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _counts(obj: Any) -> Dict[str, int]:
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, int] = {}
    for key, value in obj.items():
        if isinstance(key, str) and isinstance(value, int):
            out[key] = value
    return out


def _ceil_fraction(n: int, fraction: float) -> int:
    return int(math.ceil(n * fraction))


def _validate_inputs(w3_audit: Dict[str, Any],
                     adjudication_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []

    if w3_audit.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_audit_not_ok",
            "W3 next protocol requires the standalone adjudication audit to pass",
            expected=True,
            observed=w3_audit.get("audit_ok"),
        )
    if w3_audit.get("status") != _EXPECTED_W3_STATUS:
        _add_failure(
            failures,
            "w3_audit_status_not_negative",
            "W3 next protocol only applies after the negative robustness adjudication is accepted",
            expected=_EXPECTED_W3_STATUS,
            observed=w3_audit.get("status"),
        )
    if w3_audit.get("positive_claim_supported") is not False:
        _add_failure(
            failures,
            "w3_positive_claim_leak",
            "W3 next protocol must not inherit a positive robustness claim",
            expected=False,
            observed=w3_audit.get("positive_claim_supported"),
        )
    if w3_audit.get("claim_boundary") != _EXPECTED_BOUNDARY:
        _add_failure(
            failures,
            "w3_claim_boundary_mismatch",
            "W3 claim boundary must keep independent-predictor robustness unsupported",
            expected=_EXPECTED_BOUNDARY,
            observed=w3_audit.get("claim_boundary"),
        )
    if w3_audit.get("current_protocol_verdict") != _EXPECTED_VERDICT:
        _add_failure(
            failures,
            "w3_verdict_mismatch",
            "W3 next protocol must start from the negative no-MSA Chai verdict",
            expected=_EXPECTED_VERDICT,
            observed=w3_audit.get("current_protocol_verdict"),
        )
    if w3_audit.get("selected_protocol") != _EXPECTED_PROTOCOL:
        _add_failure(
            failures,
            "w3_selected_protocol_mismatch",
            "W3 next protocol expects the adjudicated-disagreement protocol",
            expected=_EXPECTED_PROTOCOL,
            observed=w3_audit.get("selected_protocol"),
        )

    label_agreement = w3_audit.get("label_agreement")
    min_label_agreement = w3_audit.get("min_label_agreement")
    if not (
        isinstance(label_agreement, (int, float))
        and isinstance(min_label_agreement, (int, float))
        and label_agreement < min_label_agreement
    ):
        _add_failure(
            failures,
            "w3_negative_signal_missing",
            "W3 next protocol requires label agreement to be below the predeclared minimum",
            expected="label_agreement < min_label_agreement",
            observed={"label_agreement": label_agreement, "min_label_agreement": min_label_agreement},
        )

    artifact_audit = w3_audit.get("adjudication_set_artifact_audit")
    if not isinstance(artifact_audit, dict) or artifact_audit.get("ok") is not True:
        _add_failure(
            failures,
            "w3_adjudication_artifact_audit_not_ok",
            "W3 adjudication-set artifact audit must pass before selecting the next protocol",
            expected=True,
            observed=artifact_audit.get("ok") if isinstance(artifact_audit, dict) else None,
        )
        artifact_audit = {}

    audit_counts = _counts(artifact_audit.get("counts_by_role"))
    summary_counts = _counts(adjudication_summary.get("counts_by_role"))
    if audit_counts != _EXPECTED_COUNTS:
        _add_failure(
            failures,
            "w3_artifact_audit_count_mismatch",
            "W3 artifact audit must preserve the 12 discordant plus 6 control contract",
            expected=_EXPECTED_COUNTS,
            observed=audit_counts,
        )
    if summary_counts != _EXPECTED_COUNTS:
        _add_failure(
            failures,
            "w3_adjudication_summary_count_mismatch",
            "W3 adjudication summary must preserve the 12 discordant plus 6 control contract",
            expected=_EXPECTED_COUNTS,
            observed=summary_counts,
        )
    if artifact_audit.get("n_rows") != sum(_EXPECTED_COUNTS.values()):
        _add_failure(
            failures,
            "w3_artifact_audit_row_count_mismatch",
            "W3 artifact audit must report the expected adjudication-set row count",
            expected=sum(_EXPECTED_COUNTS.values()),
            observed=artifact_audit.get("n_rows"),
        )
    if adjudication_summary.get("n_rows") != sum(_EXPECTED_COUNTS.values()):
        _add_failure(
            failures,
            "w3_adjudication_summary_row_count_mismatch",
            "W3 adjudication summary must report the expected adjudication-set row count",
            expected=sum(_EXPECTED_COUNTS.values()),
            observed=adjudication_summary.get("n_rows"),
        )

    audit_sha = artifact_audit.get("actual_sha256")
    summary_sha = adjudication_summary.get("out_jsonl_sha256")
    if audit_sha and summary_sha and audit_sha != summary_sha:
        _add_failure(
            failures,
            "w3_adjudication_sha_mismatch",
            "W3 adjudication audit and summary disagree on the JSONL SHA-256",
            expected=audit_sha,
            observed=summary_sha,
        )
    if adjudication_summary.get("selected_protocol") != _EXPECTED_PROTOCOL:
        _add_failure(
            failures,
            "w3_adjudication_summary_protocol_mismatch",
            "W3 adjudication summary must point to the selected adjudication protocol",
            expected=_EXPECTED_PROTOCOL,
            observed=adjudication_summary.get("selected_protocol"),
        )
    if adjudication_summary.get("claim_boundary") != (
        "not a positive robustness claim; input set for future W3 adjudication only"
    ):
        _add_failure(
            failures,
            "w3_adjudication_summary_claim_boundary_mismatch",
            "W3 adjudication summary must remain an input-set artifact, not a positive claim",
            expected="not a positive robustness claim",
            observed=adjudication_summary.get("claim_boundary"),
        )

    return failures


def _recommended_routes(jsonl_path: Any) -> List[Dict[str, Any]]:
    return [
        {
            "rank": 1,
            "route": "third_independent_predictor_or_protocol",
            "why": (
                "adjudicates the Boltz-vs-Chai disagreement without spending another "
                "cycle on the same no-MSA Chai protocol"
            ),
            "input_set": jsonl_path,
            "claim_after_stage": (
                "challenge-panel adjudication only; a full matched cross-predictor panel "
                "is still required before claiming broad independent-predictor robustness"
            ),
            "spend_gate": "requires explicit approval before API/GPU/HPC execution",
        },
        {
            "rank": 2,
            "route": "stronger_chai_msa_template_protocol",
            "why": (
                "separates no-MSA protocol failure from a stronger Chai-family protocol, "
                "but does not by itself close the independent-model caveat"
            ),
            "input_set": jsonl_path,
            "claim_after_stage": "protocol-variant adjudication only, not independent-predictor robustness",
            "spend_gate": "requires explicit approval before API/GPU/HPC execution",
        },
    ]


def _decision_contract() -> Dict[str, Any]:
    discordant = _EXPECTED_COUNTS["discordant_boltz_chai_label"]
    controls = _EXPECTED_COUNTS["concordant_success_control"]
    return {
        "stage": "challenge_panel_adjudication_before_full_w3_claim",
        "discordant_rows": discordant,
        "concordant_success_controls": controls,
        "discordant_alignment_threshold": _ceil_fraction(discordant, 0.80),
        "control_consistency_threshold": _ceil_fraction(controls, 0.80),
        "threshold_note": (
            "These thresholds classify the challenge panel only. They do not convert the "
            "18-row enriched set into a population-level robustness estimate."
        ),
        "future_result_schema": [
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
        ],
        "outcomes": [
            {
                "outcome": "boltz_supported_on_challenge_panel",
                "if": (
                    "at least 10/12 discordant rows align with Boltz and at least 5/6 "
                    "concordant-success controls remain successful under strict contract QC"
                ),
                "claim": "may justify a full W3 matched-panel run; not a positive robustness claim",
            },
            {
                "outcome": "chai_supported_on_challenge_panel",
                "if": (
                    "at least 10/12 discordant rows align with Chai and at least 5/6 "
                    "concordant-success controls remain successful under strict contract QC"
                ),
                "claim": "supports protocol/model-disagreement interpretation; not a broad robustness claim",
            },
            {
                "outcome": "mixed_or_contract_blocked",
                "if": "thresholds are not met, controls fail, or target/provenance/threshold contracts fail",
                "claim": "W3 remains unresolved or negative; no independent-predictor robustness claim",
            },
        ],
    }


def build_protocol(w3_audit: Dict[str, Any],
                   adjudication_summary: Dict[str, Any],
                   *,
                   report_date: Optional[str] = None) -> Dict[str, Any]:
    failures = _validate_inputs(w3_audit, adjudication_summary)
    audit_ok = not failures
    artifact_audit = (
        w3_audit.get("adjudication_set_artifact_audit")
        if isinstance(w3_audit.get("adjudication_set_artifact_audit"), dict)
        else {}
    )
    jsonl_path = artifact_audit.get("path") or adjudication_summary.get("out_jsonl")
    sha256 = artifact_audit.get("actual_sha256") or adjudication_summary.get("out_jsonl_sha256")

    return {
        "artifact": "m6d_w3_next_protocol",
        "date": report_date or date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "can_claim_independent_predictor_robustness_now": False,
        "positive_claim_supported": False,
        "source_evidence": {
            "w3_adjudication_audit": w3_audit.get("_path"),
            "w3_adjudication_summary": adjudication_summary.get("_path"),
        },
        "current_w3_result": {
            "status": w3_audit.get("status"),
            "verdict": w3_audit.get("current_protocol_verdict"),
            "claim_boundary": w3_audit.get("claim_boundary"),
            "label_agreement": w3_audit.get("label_agreement"),
            "min_label_agreement": w3_audit.get("min_label_agreement"),
            "matched_overlap": w3_audit.get("matched_overlap"),
            "interpretation": (
                "negative robustness result for the completed no-MSA Chai protocol; "
                "single-predictor caveat remains open"
            ),
        },
        "adjudication_set_contract": {
            "jsonl": jsonl_path,
            "jsonl_sha256": sha256,
            "summary": adjudication_summary.get("_path"),
            "selected_protocol": adjudication_summary.get("selected_protocol"),
            "n_rows": adjudication_summary.get("n_rows"),
            "counts_by_role": adjudication_summary.get("counts_by_role"),
            "required_counts_by_role": dict(_EXPECTED_COUNTS),
        },
        "recommended_next_routes": _recommended_routes(jsonl_path),
        "decision_contract": _decision_contract(),
        "hard_guards": [
            "do not rerun the same no-MSA Chai protocol as the next W3 spend",
            "do not close the single-predictor caveat from Chai-family records alone",
            "do not treat the 18-row enriched adjudication set as a population-level robustness estimate",
            "do not use W3 adjudication to support a W2 multi-target generalization claim",
            "do not run API/GPU/HPC spend without explicit approval and a predeclared command wrapper",
        ],
        "recommended_next_action": (
            "Prepare a third independent predictor/protocol run on the pinned 18-row adjudication set; "
            "use stronger Chai MSA/template only as a secondary protocol-variant branch."
        ),
        "failures": failures,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(rep: Dict[str, Any]) -> str:
    current = rep.get("current_w3_result", {})
    contract = rep.get("adjudication_set_contract", {})
    decision = rep.get("decision_contract", {})
    lines = [
        "# M6d W3 Next Protocol",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit, no-API, no-GPU protocol artifact. It does not close the independent-predictor caveat.",
        "",
        "## Current W3 Result",
        "",
        f"- Verdict: `{current.get('verdict')}`",
        f"- Claim boundary: `{current.get('claim_boundary')}`",
        f"- Label agreement: `{_fmt(current.get('label_agreement'))}` / minimum `{_fmt(current.get('min_label_agreement'))}`",
        f"- Matched overlap: `{_fmt(current.get('matched_overlap'))}`",
        "",
        "## Pinned Adjudication Set",
        "",
        f"- JSONL: `{contract.get('jsonl')}`",
        f"- SHA-256: `{contract.get('jsonl_sha256')}`",
        f"- Rows: `{contract.get('n_rows')}`",
        f"- Counts by role: `{contract.get('counts_by_role')}`",
        "",
        "## Recommended Next Routes",
        "",
    ]
    for route in rep.get("recommended_next_routes", []):
        lines.extend([
            f"{route.get('rank')}. `{route.get('route')}`",
            f"   - Why: {route.get('why')}",
            f"   - Claim after stage: {route.get('claim_after_stage')}",
            f"   - Spend gate: {route.get('spend_gate')}",
        ])
    lines.extend([
        "",
        "## Challenge-Panel Decision Contract",
        "",
        f"- Discordant rows: `{decision.get('discordant_rows')}`",
        f"- Concordant-success controls: `{decision.get('concordant_success_controls')}`",
        f"- Discordant alignment threshold: `{decision.get('discordant_alignment_threshold')}`",
        f"- Control consistency threshold: `{decision.get('control_consistency_threshold')}`",
        f"- Note: {decision.get('threshold_note')}",
        "",
        "Outcomes:",
    ])
    for outcome in decision.get("outcomes", []):
        lines.append(f"- `{outcome.get('outcome')}`: {outcome.get('if')} -> {outcome.get('claim')}")
    lines.extend([
        "",
        "## Hard Guards",
        "",
    ])
    lines.extend(f"- {guard}" for guard in rep.get("hard_guards", []))
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
    ap.add_argument("--w3-adjudication-audit", default="results/m6d_w3_adjudication_audit.json")
    ap.add_argument("--w3-adjudication-summary", default="results/m6d_w3_adjudication_set.json")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_next_protocol.json")
    ap.add_argument("--out-md", default="results/m6d_w3_next_protocol.md")
    args = ap.parse_args(argv)

    rep = build_protocol(
        _load_json(args.w3_adjudication_audit),
        _load_json(args.w3_adjudication_summary),
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} no_submit={no_submit} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            no_submit=rep["no_submit"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
