"""Select the M6d W3 third predictor/protocol without executing it.

The third-predictor contract says a predictor/protocol must be selected before
any future execution inputs or wrappers are emitted. This helper creates that
selection card. It chooses an AF2-Multimer/ColabFold-style protocol as the
primary next W3 adjudicator, but keeps runtime probing, input generation, and
execution behind later explicit gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_READY_STATUS = "w3_predictor_selection_card_ready_no_submit"
_BLOCKED_STATUS = "w3_predictor_selection_card_blocked"
_THIRD_CONTRACT_READY_STATUS = "w3_third_predictor_contract_ready_no_submit"
_PRIMARY_ROUTE = "third_independent_predictor_or_protocol"
_SELECTED_PROTOCOL_ID = "af2_multimer_colabfold_v1"


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


def _contract_selection(third_contract: Dict[str, Any]) -> Dict[str, Any]:
    selection = third_contract.get("predictor_selection_contract")
    return selection if isinstance(selection, dict) else {}


def _contract_output(third_contract: Dict[str, Any]) -> Dict[str, Any]:
    output = third_contract.get("output_contract")
    return output if isinstance(output, dict) else {}


def _contract_panel(third_contract: Dict[str, Any]) -> Dict[str, Any]:
    panel = third_contract.get("challenge_panel_contract")
    return panel if isinstance(panel, dict) else {}


def _validate_third_contract(third_contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if third_contract.get("status") != _THIRD_CONTRACT_READY_STATUS:
        _add_failure(
            failures,
            "w3_selection_third_contract_status_invalid",
            "selection card requires the W3 third-predictor contract to be ready",
            expected=_THIRD_CONTRACT_READY_STATUS,
            observed=third_contract.get("status"),
        )
    if third_contract.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_selection_third_contract_audit_not_ok",
            "selection card requires the third-predictor contract audit to pass",
            expected=True,
            observed=third_contract.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if third_contract.get(field) is not True:
            _add_failure(
                failures,
                f"w3_selection_third_contract_{field}_not_true",
                "selection card must inherit the no-submit/no-spend boundary",
                expected=True,
                observed=third_contract.get(field),
            )
    if third_contract.get("execution_ready") is not False:
        _add_failure(
            failures,
            "w3_selection_third_contract_execution_ready_drift",
            "selection card may not start from an execution-ready contract",
            expected=False,
            observed=third_contract.get("execution_ready"),
        )
    if third_contract.get("command_wrapper_emitted") is not False:
        _add_failure(
            failures,
            "w3_selection_third_contract_wrapper_emitted_drift",
            "selection card may not start from a contract that already emitted a wrapper",
            expected=False,
            observed=third_contract.get("command_wrapper_emitted"),
        )
    if third_contract.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_selection_third_contract_claim_leak",
            "selection card cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=third_contract.get("can_claim_independent_predictor_robustness_now"),
        )
    future = third_contract.get("future_artifacts_required")
    if not isinstance(future, list) or "selected_predictor_protocol_card" not in future:
        _add_failure(
            failures,
            "w3_selection_future_artifact_not_requested",
            "third-predictor contract must explicitly request a selected predictor/protocol card",
        )
    selection = _contract_selection(third_contract)
    required_fields = selection.get("required_selection_fields")
    if not isinstance(required_fields, list) or not required_fields:
        _add_failure(
            failures,
            "w3_selection_required_fields_missing",
            "third-predictor contract must define required selection fields",
        )
    if selection.get("route") != _PRIMARY_ROUTE:
        _add_failure(
            failures,
            "w3_selection_route_mismatch",
            "selection card must extend the primary third-predictor route",
            expected=_PRIMARY_ROUTE,
            observed=selection.get("route"),
        )
    return failures


def _selected_protocol(third_contract: Dict[str, Any]) -> Dict[str, Any]:
    selection = _contract_selection(third_contract)
    required_fields = selection.get("required_selection_fields")
    if not isinstance(required_fields, list):
        required_fields = []
    return {
        "predictor_or_protocol_id": _SELECTED_PROTOCOL_ID,
        "model_or_protocol_family": "AlphaFold2-Multimer via ColabFold/localcolabfold",
        "version": "runtime_version_pending_cayuga_probe",
        "msa_policy": (
            "paired/unpaired MMseqs2 MSA required; prefer local database or precomputed MSA, "
            "public MSA server only with explicit approval"
        ),
        "template_policy": "templates disabled unless predeclared in a later execution-input manifest",
        "runtime_environment": "Cayuga colabfold/localcolabfold environment pending install/probe",
        "label_source": "af2_multimer_lrmsd_to_reference",
        "signal_source": "af2_multimer_pae_interaction_or_iptm",
        "approval_gate": "BIO_SFM_APPROVE_W3_THIRD_PREDICTOR=approve-w3-third-predictor-submit",
        "route": _PRIMARY_ROUTE,
        "selection_status": "selected_pending_runtime_probe",
        "required_fields_satisfied": sorted(required_fields),
    }


def _candidate_review() -> List[Dict[str, Any]]:
    return [
        {
            "candidate": _SELECTED_PROTOCOL_ID,
            "decision": "selected_pending_runtime_probe",
            "reason": (
                "complex-specific AF2-Multimer protocol; independent from Boltz-2 and Chai-1; "
                "maps naturally to structure, PAE/ipTM-like confidence, and L-RMSD labels"
            ),
        },
        {
            "candidate": "esmfold_single_chain",
            "decision": "rejected_for_w3_complex_adjudication",
            "reason": "repo ESMFold runner is single-chain/self-consistency oriented and does not adjudicate complex interface geometry",
        },
        {
            "candidate": "stronger_chai_msa_template_protocol",
            "decision": "secondary_protocol_variant_only",
            "reason": "useful to diagnose no-MSA Chai protocol failure but not independent-model closure",
        },
        {
            "candidate": "alphafold3_or_af3_json_protocol",
            "decision": "deferred_requires_separate_access_and_license_check",
            "reason": "potentially strong but access/runtime/licensing and execution wrapper are not verified here",
        },
    ]


def _validate_selection(third_contract: Dict[str, Any],
                        selected: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    selection = _contract_selection(third_contract)
    required_fields = selection.get("required_selection_fields")
    if not isinstance(required_fields, list):
        required_fields = []
    missing = [
        field for field in required_fields
        if not isinstance(selected.get(field), str) or not selected.get(field, "").strip()
    ]
    if missing:
        _add_failure(
            failures,
            "w3_selection_required_field_values_missing",
            "selected predictor/protocol must populate all required selection fields",
            expected=required_fields,
            observed=missing,
        )
    disallowed = selection.get("disallowed_as_independent_closure")
    if isinstance(disallowed, list) and selected.get("predictor_or_protocol_id") in disallowed:
        _add_failure(
            failures,
            "w3_selection_disallowed_predictor_selected",
            "selected predictor/protocol cannot be one of the disallowed source predictors",
            expected="not in disallowed_as_independent_closure",
            observed=selected.get("predictor_or_protocol_id"),
        )
    if selected.get("route") != _PRIMARY_ROUTE:
        _add_failure(
            failures,
            "w3_selection_selected_route_mismatch",
            "selected predictor/protocol must stay on the primary third-predictor route",
            expected=_PRIMARY_ROUTE,
            observed=selected.get("route"),
        )
    return failures


def build_selection_card(third_contract: Dict[str, Any],
                         *,
                         report_date: Optional[str] = None) -> Dict[str, Any]:
    selected = _selected_protocol(third_contract)
    failures = []
    failures.extend(_validate_third_contract(third_contract))
    failures.extend(_validate_selection(third_contract, selected))
    audit_ok = not failures
    contract_path = third_contract.get("_path")
    contract_sha = (
        _sha256_file(contract_path)
        if isinstance(contract_path, str) and os.path.exists(contract_path)
        else None
    )
    panel = _contract_panel(third_contract)
    output = _contract_output(third_contract)
    return {
        "artifact": "m6d_w3_predictor_selection_card",
        "date": report_date or date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": False,
        "runtime_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "claim_boundary": (
            "predictor/protocol selection only; not an executed result and not a positive "
            "independent-predictor robustness claim"
        ),
        "source_third_predictor_contract": contract_path,
        "source_third_predictor_contract_sha256": contract_sha,
        "selected_predictor_protocol": selected,
        "challenge_panel_contract": {
            "n_rows": panel.get("n_rows"),
            "counts_by_role": panel.get("counts_by_role"),
            "target_ids": panel.get("target_ids"),
        },
        "output_contract": {
            "planned_jsonl": output.get("planned_jsonl"),
            "required_n_rows": output.get("required_n_rows"),
            "required_result_schema": output.get("required_result_schema"),
        },
        "candidate_review": _candidate_review(),
        "evidence_sources": [
            {
                "name": "ColabFold GitHub",
                "url": "https://github.com/sokrypton/ColabFold",
                "used_for": "complex prediction support, colabfold_batch, MSA/server/local-database constraints",
            },
            {
                "name": "AlphaFold GitHub",
                "url": "https://github.com/google-deepmind/alphafold",
                "used_for": "AlphaFold-Multimer availability and GPU/database/runtime constraints",
            },
            {
                "name": "LocalColabFold GitHub",
                "url": "https://github.com/YoshitakaMo/localcolabfold",
                "used_for": "local colabfold_batch installation and multimer auto/model-type notes",
            },
        ],
        "runtime_probe_required": {
            "required": True,
            "reason": "prior Cayuga feasibility did not show colabfold_batch/alphafold installed in checked envs",
            "checks": [
                "colabfold_batch --help is available in the selected env",
                "GPU/CUDA/JAX compatibility is verified on the target partition",
                "MSA policy is resolved to local database, precomputed MSA, or explicitly approved server query",
                "a dry-run wrapper can enumerate 18 inputs without submitting jobs",
            ],
        },
        "future_artifacts_required": [
            "execution_input_manifest",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
            "third_predictor_result_qc_report",
            "w3_challenge_panel_adjudication_report",
        ],
        "execution_blockers": [
            "AF2-Multimer/ColabFold runtime has not been probed on Cayuga in this artifact",
            "execution input FASTA/MSA manifest is not emitted here",
            "approval-gated command wrapper is not emitted here",
            "explicit approval is required before any API/network/GPU/HPC execution",
        ],
        "recommended_next_action": (
            "Probe/select the Cayuga ColabFold runtime and generate an execution-input manifest "
            "for the 18-row challenge panel; do not submit or query external services without explicit approval."
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    selected = rep.get("selected_predictor_protocol", {})
    runtime = rep.get("runtime_probe_required", {})
    lines = [
        "# M6d W3 Predictor Selection Card",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit, no-API, no-GPU selection card. It selects a future predictor/protocol but emits no execution inputs or command wrapper.",
        "",
        "## Selected Predictor/Protocol",
        "",
        f"- ID: `{selected.get('predictor_or_protocol_id')}`",
        f"- Family: `{selected.get('model_or_protocol_family')}`",
        f"- Version: `{selected.get('version')}`",
        f"- MSA policy: {selected.get('msa_policy')}",
        f"- Template policy: {selected.get('template_policy')}",
        f"- Runtime: {selected.get('runtime_environment')}",
        f"- Signal source: `{selected.get('signal_source')}`",
        f"- Label source: `{selected.get('label_source')}`",
        f"- Approval gate: `{selected.get('approval_gate')}`",
        "",
        "## Candidate Review",
        "",
    ]
    for item in rep.get("candidate_review", []):
        lines.append(f"- `{item.get('candidate')}`: `{item.get('decision')}` -- {item.get('reason')}")
    lines.extend([
        "",
        "## Runtime Probe Required",
        "",
        f"- Required: `{runtime.get('required')}`",
        f"- Reason: {runtime.get('reason')}",
    ])
    for check in runtime.get("checks", []):
        lines.append(f"- {check}")
    lines.extend(["", "## Execution Blockers", ""])
    lines.extend(f"- {blocker}" for blocker in rep.get("execution_blockers", []))
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
    ap.add_argument("--w3-third-predictor-contract", default="results/m6d_w3_third_predictor_contract.json")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_predictor_selection_card.json")
    ap.add_argument("--out-md", default="results/m6d_w3_predictor_selection_card.md")
    args = ap.parse_args(argv)

    rep = build_selection_card(
        _load_json(args.w3_third_predictor_contract),
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    selected = rep["selected_predictor_protocol"]["predictor_or_protocol_id"]
    print(
        "status={status} audit_ok={ok} selected={selected} runtime_ready={runtime} execution_ready={ready} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            selected=selected,
            runtime=rep["runtime_ready"],
            ready=rep["execution_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
