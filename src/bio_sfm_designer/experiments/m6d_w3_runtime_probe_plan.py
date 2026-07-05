"""Plan the M6d W3 runtime probe without executing it.

The W3 predictor selection card chooses an AF2-Multimer/ColabFold-style
protocol, but it intentionally leaves runtime probing, input manifests, command
wrappers, and any GPU/API/HPC work behind later gates. This helper writes the
next no-submit artifact: a runtime-probe plan that says what must be checked
before execution can be prepared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_READY_STATUS = "w3_runtime_probe_plan_ready_no_submit"
_BLOCKED_STATUS = "w3_runtime_probe_plan_blocked"
_SELECTION_READY_STATUS = "w3_predictor_selection_card_ready_no_submit"
_SELECTED_PROTOCOL_ID = "af2_multimer_colabfold_v1"
_REQUIRED_PROBE_KINDS = {
    "cli_help",
    "gpu_stack",
    "msa_policy",
    "dry_run_enumeration",
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


def _selected(selection_card: Dict[str, Any]) -> Dict[str, Any]:
    selected = selection_card.get("selected_predictor_protocol")
    return selected if isinstance(selected, dict) else {}


def _target_ids(selection_card: Dict[str, Any]) -> List[str]:
    panel = selection_card.get("challenge_panel_contract")
    if not isinstance(panel, dict):
        return []
    values = panel.get("target_ids")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, str) and value.strip()]


def _validate_selection_card(selection_card: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if selection_card.get("status") != _SELECTION_READY_STATUS:
        _add_failure(
            failures,
            "w3_runtime_probe_selection_status_invalid",
            "runtime-probe plan requires a ready W3 predictor selection card",
            expected=_SELECTION_READY_STATUS,
            observed=selection_card.get("status"),
        )
    if selection_card.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_runtime_probe_selection_audit_not_ok",
            "runtime-probe plan requires the selection-card audit to pass",
            expected=True,
            observed=selection_card.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if selection_card.get(field) is not True:
            _add_failure(
                failures,
                f"w3_runtime_probe_selection_{field}_not_true",
                "runtime-probe plan must inherit the no-submit/no-spend boundary",
                expected=True,
                observed=selection_card.get(field),
            )
    for field in ("runtime_ready", "execution_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted"):
        if selection_card.get(field) is not False:
            _add_failure(
                failures,
                f"w3_runtime_probe_selection_{field}_drift",
                "runtime-probe plan may not start from an executed or execution-ready selection card",
                expected=False,
                observed=selection_card.get(field),
            )
    if selection_card.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_runtime_probe_selection_claim_leak",
            "runtime-probe plan cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=selection_card.get("can_claim_independent_predictor_robustness_now"),
        )

    selected = _selected(selection_card)
    if selected.get("predictor_or_protocol_id") != _SELECTED_PROTOCOL_ID:
        _add_failure(
            failures,
            "w3_runtime_probe_selected_protocol_mismatch",
            "runtime-probe plan is pinned to the selected AF2-Multimer/ColabFold protocol",
            expected=_SELECTED_PROTOCOL_ID,
            observed=selected.get("predictor_or_protocol_id"),
        )
    runtime_probe = selection_card.get("runtime_probe_required")
    checks = runtime_probe.get("checks") if isinstance(runtime_probe, dict) else None
    if not isinstance(runtime_probe, dict) or runtime_probe.get("required") is not True:
        _add_failure(
            failures,
            "w3_runtime_probe_requirement_missing",
            "selection card must keep runtime probing required before any execution input manifest",
        )
    if not isinstance(checks, list) or not checks:
        _add_failure(
            failures,
            "w3_runtime_probe_requirement_checks_missing",
            "selection card must list the runtime checks that the plan will refine",
        )
    future = selection_card.get("future_artifacts_required")
    required_future = {"execution_input_manifest", "approval_gated_command_wrapper"}
    if not isinstance(future, list) or not required_future.issubset(set(future)):
        _add_failure(
            failures,
            "w3_runtime_probe_future_artifacts_incomplete",
            "selection card must still require execution_input_manifest and approval_gated_command_wrapper",
        )
    return failures


def _probe_contract(selection_card: Dict[str, Any]) -> Dict[str, Any]:
    selected = _selected(selection_card)
    target_ids = _target_ids(selection_card)
    return {
        "selected_predictor_or_protocol_id": selected.get("predictor_or_protocol_id"),
        "selected_model_or_protocol_family": selected.get("model_or_protocol_family"),
        "runtime_surface": "Cayuga AF2-Multimer/ColabFold runtime probe",
        "target_partition_candidates": [
            "scu-gpu",
            "gpu partition pending probe",
        ],
        "candidate_runtime_locations": [
            "$HOME/localcolabfold/.pixi/envs/default/bin/colabfold_batch",
            "$HOME/.conda/envs/colabfold/bin/colabfold_batch",
            "colabfold_batch on PATH",
        ],
        "target_count": len(target_ids),
        "target_ids": target_ids,
        "checks": [
            {
                "kind": "env_discovery",
                "status": "planned_not_executed",
                "requirement": "identify the active ColabFold/localcolabfold environment without installing software",
            },
            {
                "kind": "cli_help",
                "status": "planned_not_executed",
                "requirement": "verify colabfold_batch help is available in the selected environment",
            },
            {
                "kind": "gpu_stack",
                "status": "planned_not_executed",
                "requirement": "verify CUDA/JAX/GPU compatibility on the selected Cayuga GPU partition",
            },
            {
                "kind": "msa_policy",
                "status": "planned_not_executed",
                "requirement": (
                    "resolve MSA source to local databases or precomputed MSAs; public MMseqs2/API/server "
                    "queries stay disabled unless explicitly approved"
                ),
            },
            {
                "kind": "dry_run_enumeration",
                "status": "planned_not_executed",
                "requirement": "future dry-run wrapper must enumerate all challenge-panel inputs without submitting jobs",
            },
        ],
    }


def build_runtime_probe_plan(selection_card: Dict[str, Any],
                             *,
                             report_date: Optional[str] = None) -> Dict[str, Any]:
    failures = _validate_selection_card(selection_card)
    audit_ok = not failures
    selection_path = selection_card.get("_path")
    selection_sha = (
        _sha256_file(selection_path)
        if isinstance(selection_path, str) and os.path.exists(selection_path)
        else None
    )
    selected = _selected(selection_card)
    return {
        "artifact": "m6d_w3_runtime_probe_plan",
        "date": report_date or date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "runtime_probe_ready": False,
        "runtime_ready": False,
        "probe_executed": False,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "source_predictor_selection_card": selection_path,
        "source_predictor_selection_card_sha256": selection_sha,
        "selected_predictor_or_protocol_id": selected.get("predictor_or_protocol_id"),
        "selected_model_or_protocol_family": selected.get("model_or_protocol_family"),
        "probe_contract": _probe_contract(selection_card),
        "future_artifacts_required": [
            "runtime_probe_report",
            "execution_input_manifest",
            "approval_gated_command_wrapper",
        ],
        "execution_blockers": [
            "runtime probe has not been executed",
            "execution input FASTA/MSA manifest is not emitted here",
            "approval-gated command wrapper is not emitted here",
            "approval token is not emitted here",
            "no API/network/GPU/HPC execution is authorized by this plan",
        ],
        "claim_boundary": (
            "runtime-probe planning only; not a runtime-ready result, not an execution manifest, "
            "and not a positive independent-predictor robustness claim"
        ),
        "recommended_next_action": (
            "Run and record a no-submit runtime probe report only after choosing the probe surface; "
            "do not submit jobs or query external services."
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    contract = rep.get("probe_contract") if isinstance(rep.get("probe_contract"), dict) else {}
    lines = [
        "# M6d W3 Runtime Probe Plan",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit, no-API, no-GPU runtime-probe plan. No runtime probe was executed, and this artifact emits no execution inputs, command wrapper, or approval token.",
        "",
        "## Selected Predictor/Protocol",
        "",
        f"- ID: `{rep.get('selected_predictor_or_protocol_id')}`",
        f"- Family: `{rep.get('selected_model_or_protocol_family')}`",
        f"- Source selection card: `{rep.get('source_predictor_selection_card')}`",
        "",
        "## Probe Contract",
        "",
        f"- Runtime surface: {contract.get('runtime_surface')}",
        f"- Target count: `{contract.get('target_count')}`",
        f"- Target partition candidates: {', '.join(contract.get('target_partition_candidates', []))}",
        "",
        "Candidate runtime locations:",
    ]
    for location in contract.get("candidate_runtime_locations", []):
        lines.append(f"- `{location}`")
    lines.extend(["", "Required checks:"])
    for check in contract.get("checks", []):
        lines.append(
            "- `{kind}`: `{status}` -- {requirement}".format(
                kind=check.get("kind"),
                status=check.get("status"),
                requirement=check.get("requirement"),
            )
        )
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
    ap.add_argument("--w3-predictor-selection-card", default="results/m6d_w3_predictor_selection_card.json")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_runtime_probe_plan.json")
    ap.add_argument("--out-md", default="results/m6d_w3_runtime_probe_plan.md")
    args = ap.parse_args(argv)

    rep = build_runtime_probe_plan(
        _load_json(args.w3_predictor_selection_card),
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} selected={selected} probe_executed={probe} runtime_ready={runtime} execution_ready={execution} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            selected=rep["selected_predictor_or_protocol_id"],
            probe=rep["probe_executed"],
            runtime=rep["runtime_ready"],
            execution=rep["execution_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
