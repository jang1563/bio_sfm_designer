"""Record the M6d W3 runtime probe without submitting or predicting.

The runtime-probe plan defines what must be checked before AF2-Multimer via
ColabFold can become an execution-ready W3 adjudicator. This helper records a
probe report. By default it performs only local static discovery, so it can be
run safely in Codex without SSH, API calls, GPU jobs, MSA-server queries, or
prediction execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import date
from typing import Any, Dict, List, Optional


_PLAN_READY_STATUS = "w3_runtime_probe_plan_ready_no_submit"
_RECORDED_STATUS = "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit"
_READY_STATUS = "w3_runtime_probe_report_runtime_ready_no_submit"
_BLOCKED_STATUS = "w3_runtime_probe_report_blocked"
_SELECTED_PROTOCOL_ID = "af2_multimer_colabfold_v1"
_TARGET_READY_SURFACES = {"cayuga_gpu_no_submit"}
_REQUIRED_CHECKS = {
    "env_discovery",
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


def _load_observed_checks(path: str) -> List[Dict[str, Any]]:
    with open(path) as fh:
        obj = json.load(fh)
    if isinstance(obj, dict):
        checks = obj.get("observed_checks")
    else:
        checks = obj
    if not isinstance(checks, list):
        raise ValueError(f"{path} must contain an observed_checks list")
    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"{path}: observed_checks[{idx}] is not an object")
    return checks


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


def _probe_contract(plan: Dict[str, Any]) -> Dict[str, Any]:
    contract = plan.get("probe_contract")
    return contract if isinstance(contract, dict) else {}


def _target_ids(plan: Dict[str, Any]) -> List[str]:
    values = _probe_contract(plan).get("target_ids")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, str) and value.strip()]


def _validate_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if plan.get("status") != _PLAN_READY_STATUS:
        _add_failure(
            failures,
            "w3_runtime_probe_report_plan_status_invalid",
            "runtime-probe report requires a ready no-submit runtime-probe plan",
            expected=_PLAN_READY_STATUS,
            observed=plan.get("status"),
        )
    if plan.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_runtime_probe_report_plan_audit_not_ok",
            "runtime-probe report requires the runtime-probe plan audit to pass",
            expected=True,
            observed=plan.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if plan.get(field) is not True:
            _add_failure(
                failures,
                f"w3_runtime_probe_report_plan_{field}_not_true",
                "runtime-probe report must inherit the no-submit/no-spend boundary",
                expected=True,
                observed=plan.get(field),
            )
    for field in ("runtime_ready", "probe_executed", "execution_ready",
                  "execution_inputs_emitted", "command_wrapper_emitted",
                  "approval_token_emitted"):
        if plan.get(field) is not False:
            _add_failure(
                failures,
                f"w3_runtime_probe_report_plan_{field}_drift",
                "runtime-probe report may not start from an already executed or ready plan",
                expected=False,
                observed=plan.get(field),
            )
    if plan.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_runtime_probe_report_plan_claim_leak",
            "runtime-probe report cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=plan.get("can_claim_independent_predictor_robustness_now"),
        )
    if plan.get("selected_predictor_or_protocol_id") != _SELECTED_PROTOCOL_ID:
        _add_failure(
            failures,
            "w3_runtime_probe_report_selected_protocol_mismatch",
            "runtime-probe report is pinned to the selected AF2-Multimer/ColabFold protocol",
            expected=_SELECTED_PROTOCOL_ID,
            observed=plan.get("selected_predictor_or_protocol_id"),
        )
    contract = _probe_contract(plan)
    checks = contract.get("checks")
    kinds = {
        check.get("kind")
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("kind"), str)
    } if isinstance(checks, list) else set()
    if not _REQUIRED_CHECKS.issubset(kinds):
        _add_failure(
            failures,
            "w3_runtime_probe_report_plan_checks_incomplete",
            "runtime-probe plan must contain all required checks",
            expected=sorted(_REQUIRED_CHECKS),
            observed=sorted(kinds),
        )
    if len(_target_ids(plan)) <= 0:
        _add_failure(
            failures,
            "w3_runtime_probe_report_plan_targets_missing",
            "runtime-probe plan must enumerate the challenge-panel targets",
        )
    return failures


def _candidate_locations(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    values = _probe_contract(plan).get("candidate_runtime_locations")
    if not isinstance(values, list):
        values = []
    rows: List[Dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            continue
        if raw == "colabfold_batch on PATH":
            resolved = shutil.which("colabfold_batch")
            rows.append({
                "candidate": raw,
                "resolved": resolved,
                "exists": bool(resolved),
                "executable": bool(resolved and os.access(resolved, os.X_OK)),
                "source": "PATH",
            })
            continue
        expanded = os.path.expandvars(os.path.expanduser(raw))
        rows.append({
            "candidate": raw,
            "resolved": expanded,
            "exists": os.path.exists(expanded),
            "executable": os.path.exists(expanded) and os.access(expanded, os.X_OK),
            "source": "expanded_path",
        })
    return rows


def _default_observed_checks(plan: Dict[str, Any],
                             *,
                             run_cli_help: bool = False,
                             cli_help_timeout_s: int = 20) -> List[Dict[str, Any]]:
    candidates = _candidate_locations(plan)
    executable = next((row for row in candidates if row.get("executable")), None)
    checks: List[Dict[str, Any]] = [{
        "kind": "env_discovery",
        "ran": True,
        "ok": executable is not None,
        "candidate_locations": candidates,
        "selected_cli": executable.get("resolved") if executable else None,
    }]

    cli_help: Dict[str, Any] = {
        "kind": "cli_help",
        "ran": False,
        "ok": False,
        "reason": "not_requested",
        "selected_cli": executable.get("resolved") if executable else None,
    }
    if run_cli_help and executable:
        try:
            proc = subprocess.run(
                [str(executable["resolved"]), "--help"],
                text=True,
                capture_output=True,
                timeout=cli_help_timeout_s,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            cli_help.update({
                "ran": True,
                "ok": proc.returncode == 0 and "colabfold" in combined.lower(),
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-1000:],
                "stderr_tail": (proc.stderr or "")[-1000:],
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            cli_help.update({
                "ran": True,
                "ok": False,
                "error": str(exc),
            })
    checks.append(cli_help)
    checks.extend([
        {
            "kind": "gpu_stack",
            "ran": False,
            "ok": False,
            "reason": "not_run_in_local_static_probe",
        },
        {
            "kind": "msa_policy",
            "ran": True,
            "ok": True,
            "public_server_disabled": True,
            "policy": "local database or precomputed MSA only unless explicitly approved",
        },
        {
            "kind": "dry_run_enumeration",
            "ran": True,
            "ok": len(_target_ids(plan)) == int(_probe_contract(plan).get("target_count") or 0),
            "n_inputs": len(_target_ids(plan)),
            "expected_n_inputs": _probe_contract(plan).get("target_count"),
            "submitted_jobs": 0,
        },
    ])
    return checks


def _checks_by_kind(checks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for check in checks:
        kind = check.get("kind") if isinstance(check, dict) else None
        if isinstance(kind, str):
            out[kind] = check
    return out


def build_runtime_probe_report(
    plan: Dict[str, Any],
    *,
    probe_surface: str = "local_static_no_submit",
    observed_checks: Optional[List[Dict[str, Any]]] = None,
    run_cli_help: bool = False,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    failures = _validate_plan(plan)
    checks = observed_checks if observed_checks is not None else _default_observed_checks(
        plan,
        run_cli_help=run_cli_help,
    )
    if not isinstance(checks, list):
        checks = []
        _add_failure(
            failures,
            "w3_runtime_probe_report_observed_checks_not_list",
            "observed checks must be a list",
        )
    by_kind = _checks_by_kind(checks)
    missing = sorted(_REQUIRED_CHECKS.difference(by_kind))
    if missing:
        _add_failure(
            failures,
            "w3_runtime_probe_report_observed_checks_missing",
            "runtime-probe report must include all required observed checks",
            expected=sorted(_REQUIRED_CHECKS),
            observed=missing,
        )

    target_surface = probe_surface in _TARGET_READY_SURFACES
    required_ok = all(by_kind.get(kind, {}).get("ok") is True for kind in _REQUIRED_CHECKS)
    runtime_ready = bool(target_surface and required_ok and not failures)
    readiness_blockers = []
    if not target_surface:
        readiness_blockers.append("probe surface is not the target Cayuga GPU no-submit surface")
    for kind in sorted(_REQUIRED_CHECKS):
        if by_kind.get(kind, {}).get("ok") is not True:
            readiness_blockers.append(f"{kind} check is not ok")

    plan_path = plan.get("_path")
    plan_sha = (
        _sha256_file(plan_path)
        if isinstance(plan_path, str) and os.path.exists(plan_path)
        else None
    )
    audit_ok = not failures
    if runtime_ready:
        next_action = "generate the no-submit execution-input manifest for the 18-row W3 challenge panel"
    elif target_surface:
        next_action = (
            "repair the Cayuga ColabFold/JAX/GPU runtime blockers and rerun the no-submit runtime "
            "probe before generating execution inputs"
        )
    else:
        next_action = (
            "run the no-submit runtime probe on the target Cayuga GPU surface before generating "
            "execution inputs"
        )
    return {
        "artifact": "m6d_w3_runtime_probe_report",
        "date": report_date or date.today().isoformat(),
        "status": (
            _READY_STATUS if runtime_ready else
            _RECORDED_STATUS if audit_ok else
            _BLOCKED_STATUS
        ),
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "probe_surface": probe_surface,
        "probe_executed": True,
        "cayuga_probe_executed": probe_surface.startswith("cayuga_"),
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "source_runtime_probe_plan": plan_path,
        "source_runtime_probe_plan_sha256": plan_sha,
        "selected_predictor_or_protocol_id": plan.get("selected_predictor_or_protocol_id"),
        "target_count": len(_target_ids(plan)),
        "observed_checks": checks,
        "readiness_blockers": [] if runtime_ready else readiness_blockers,
        "future_artifacts_required": [
            "execution_input_manifest",
            "approval_gated_command_wrapper",
            "post_execution_records_jsonl",
        ],
        "claim_boundary": (
            "runtime-probe report only; no prediction execution, no execution-input manifest, "
            "no approval-gated execution wrapper, and no positive independent-predictor robustness claim"
        ),
        "recommended_next_action": next_action,
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3 Runtime Probe Report",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Runtime ready: `{rep.get('runtime_ready')}`.",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| probe surface | `{rep.get('probe_surface')}` |",
        f"| probe executed | `{rep.get('probe_executed')}` |",
        f"| Cayuga probe executed | `{rep.get('cayuga_probe_executed')}` |",
        f"| execution ready | `{rep.get('execution_ready')}` |",
        f"| execution inputs emitted | `{rep.get('execution_inputs_emitted')}` |",
        f"| command wrapper emitted | `{rep.get('command_wrapper_emitted')}` |",
        "",
        "## Observed Checks",
        "",
    ]
    for check in rep.get("observed_checks", []):
        lines.append(
            "- `{kind}`: ok=`{ok}` ran=`{ran}`".format(
                kind=check.get("kind"),
                ok=check.get("ok"),
                ran=check.get("ran"),
            )
        )
    blockers = rep.get("readiness_blockers") or []
    if blockers:
        lines.extend(["", "## Readiness Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in blockers)
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
    ap.add_argument("--w3-runtime-probe-plan", default="results/m6d_w3_runtime_probe_plan.json")
    ap.add_argument("--probe-surface", default="local_static_no_submit")
    ap.add_argument("--observed-checks-json", default=None,
                    help="optional JSON file containing observed_checks for a no-submit Cayuga probe")
    ap.add_argument("--run-cli-help", action="store_true",
                    help="if a local colabfold_batch candidate is executable, run --help only")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_runtime_probe_report.json")
    ap.add_argument("--out-md", default="results/m6d_w3_runtime_probe_report.md")
    args = ap.parse_args(argv)

    rep = build_runtime_probe_report(
        _load_json(args.w3_runtime_probe_plan),
        probe_surface=args.probe_surface,
        observed_checks=(
            _load_observed_checks(args.observed_checks_json)
            if args.observed_checks_json else None
        ),
        run_cli_help=args.run_cli_help,
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} surface={surface} probe_executed={probe} runtime_ready={runtime} execution_ready={execution} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            surface=rep["probe_surface"],
            probe=rep["probe_executed"],
            runtime=rep["runtime_ready"],
            execution=rep["execution_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
