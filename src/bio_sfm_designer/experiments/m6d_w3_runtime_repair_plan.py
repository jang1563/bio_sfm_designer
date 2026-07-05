"""Build the M6d W3 Cayuga runtime repair plan.

The runtime probe can fail for useful engineering reasons before any W3 science
claim is possible. This helper turns the observed no-submit Cayuga probe plus a
read-only Cayuga discovery snapshot into the next repair contract. It does not
submit jobs, install packages, query MSA/API services, run prediction, emit
execution inputs, or emit an approval-gated wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_REPORT_RECORDED_STATUS = "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit"
_REPAIR_READY_STATUS = "w3_runtime_repair_plan_ready_no_submit"
_REPAIR_BLOCKED_STATUS = "w3_runtime_repair_plan_blocked"
_DISCOVERY_ARTIFACT = "m6d_w3_cayuga_runtime_repair_discovery"
_REQUIRED_FAILED_CHECKS = {"env_discovery", "cli_help", "gpu_stack"}


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


def _sha256_file(path: Optional[str]) -> Optional[str]:
    if not isinstance(path, str) or not os.path.exists(path):
        return None
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


def _checks_by_kind(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    checks = report.get("observed_checks")
    if not isinstance(checks, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in checks:
        if isinstance(row, dict) and isinstance(row.get("kind"), str):
            out[row["kind"]] = row
    return out


def _validate_runtime_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if report.get("status") != _REPORT_RECORDED_STATUS:
        _add_failure(
            failures,
            "w3_runtime_repair_report_status_invalid",
            "runtime repair plan requires the recorded not-ready runtime-probe report",
            expected=_REPORT_RECORDED_STATUS,
            observed=report.get("status"),
        )
    if report.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_runtime_repair_report_audit_not_ok",
            "runtime repair plan requires the runtime-probe report audit to pass",
            expected=True,
            observed=report.get("audit_ok"),
        )
    if report.get("probe_surface") != "cayuga_gpu_no_submit":
        _add_failure(
            failures,
            "w3_runtime_repair_report_surface_invalid",
            "runtime repair plan should be based on the target Cayuga no-submit probe surface",
            expected="cayuga_gpu_no_submit",
            observed=report.get("probe_surface"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend", "probe_executed", "cayuga_probe_executed"):
        if report.get(field) is not True:
            _add_failure(
                failures,
                f"w3_runtime_repair_report_{field}_not_true",
                "runtime repair plan must inherit the no-submit completed-probe boundary",
                expected=True,
                observed=report.get(field),
            )
    for field in ("runtime_ready", "execution_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted",
                  "can_claim_independent_predictor_robustness_now"):
        if report.get(field) is not False:
            _add_failure(
                failures,
                f"w3_runtime_repair_report_{field}_drift",
                "runtime repair plan cannot start from a ready, executable, or claim-supporting report",
                expected=False,
                observed=report.get(field),
            )
    checks = _checks_by_kind(report)
    failed = {kind for kind, row in checks.items() if row.get("ok") is False}
    if not _REQUIRED_FAILED_CHECKS.issubset(failed):
        _add_failure(
            failures,
            "w3_runtime_repair_expected_blockers_missing",
            "runtime repair plan expects the known Cayuga runtime blockers to be present",
            expected=sorted(_REQUIRED_FAILED_CHECKS),
            observed=sorted(failed),
        )
    for kind in ("msa_policy", "dry_run_enumeration"):
        if checks.get(kind, {}).get("ok") is not True:
            _add_failure(
                failures,
                f"w3_runtime_repair_{kind}_not_ok",
                "runtime repair plan expects the non-runtime W3 probe checks to remain passing",
                expected=True,
                observed=checks.get(kind, {}).get("ok"),
            )
    return failures


def _validate_discovery(discovery: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if discovery.get("artifact") != _DISCOVERY_ARTIFACT:
        _add_failure(
            failures,
            "w3_runtime_repair_discovery_artifact_invalid",
            "runtime repair discovery must be the read-only Cayuga discovery artifact",
            expected=_DISCOVERY_ARTIFACT,
            observed=discovery.get("artifact"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend", "prediction_executed"):
        expected = False if field == "prediction_executed" else True
        if discovery.get(field) is not expected:
            _add_failure(
                failures,
                f"w3_runtime_repair_discovery_{field}_invalid",
                "runtime repair discovery must preserve no-submit/no-spend/no-prediction boundaries",
                expected=expected,
                observed=discovery.get(field),
            )
    command_presence = discovery.get("command_presence")
    if not isinstance(command_presence, dict):
        _add_failure(
            failures,
            "w3_runtime_repair_discovery_command_presence_missing",
            "runtime repair discovery must record command presence",
        )
    elif command_presence.get("colabfold_batch") != "missing":
        _add_failure(
            failures,
            "w3_runtime_repair_discovery_colabfold_unexpectedly_present",
            "this repair plan is for the current missing-colabfold runtime state",
            expected="missing",
            observed=command_presence.get("colabfold_batch"),
        )
    package_probe = discovery.get("python_package_probe")
    if not isinstance(package_probe, list) or not package_probe:
        _add_failure(
            failures,
            "w3_runtime_repair_discovery_python_probe_missing",
            "runtime repair discovery must record Python package probes",
        )
    return failures


def _command_presence(discovery: Dict[str, Any], name: str) -> Any:
    values = discovery.get("command_presence")
    if isinstance(values, dict):
        return values.get(name)
    return None


def _package_seen(discovery: Dict[str, Any], package: str) -> bool:
    probes = discovery.get("python_package_probe")
    if not isinstance(probes, list):
        return False
    for probe in probes:
        if isinstance(probe, dict):
            packages = probe.get("packages")
            if isinstance(packages, dict) and packages.get(package) is True:
                return True
    return False


def build_runtime_repair_plan(
    runtime_report: Dict[str, Any],
    discovery: Dict[str, Any],
    *,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    failures = _validate_runtime_report(runtime_report)
    failures.extend(_validate_discovery(discovery))
    ready = not failures
    checks = _checks_by_kind(runtime_report)
    failed_checks = sorted(kind for kind, row in checks.items() if row.get("ok") is False)
    passed_checks = sorted(kind for kind, row in checks.items() if row.get("ok") is True)

    repair_items = [
        {
            "id": "provision_colabfold_cli",
            "status": "required",
            "reason": "colabfold_batch is absent from PATH and from the checked localcolabfold/conda locations",
            "evidence": {
                "colabfold_batch": _command_presence(discovery, "colabfold_batch"),
                "candidate_paths": discovery.get("candidate_paths", []),
            },
            "done_when": "colabfold_batch exists in the selected W3 runtime and `colabfold_batch --help` passes in a no-submit probe",
        },
        {
            "id": "provision_jax_cuda_runtime",
            "status": "required",
            "reason": "jax and jaxlib are absent from the checked Python environments",
            "evidence": {
                "jax_seen": _package_seen(discovery, "jax"),
                "jaxlib_seen": _package_seen(discovery, "jaxlib"),
                "python_package_probe": discovery.get("python_package_probe", []),
            },
            "done_when": "the selected W3 runtime imports JAX/JAXLIB and sees a GPU device during a no-prediction probe",
        },
        {
            "id": "rerun_gpu_check_on_actual_gpu_surface",
            "status": "required_after_runtime_install",
            "reason": "the current read-only discovery ran on a login host, where nvidia-smi is present but not a proof of compute-node GPU readiness",
            "evidence": checks.get("gpu_stack", {}),
            "done_when": "the no-submit runtime probe records gpu_stack ok=true on the approved target GPU surface",
        },
        {
            "id": "preserve_msa_policy",
            "status": "already_ok_keep_guarded",
            "reason": "the current probe keeps public MSA/API/server use disabled",
            "evidence": checks.get("msa_policy", {}),
            "done_when": "future W3 execution inputs use local/precomputed MSA unless a separate explicit approval changes the policy",
        },
        {
            "id": "preserve_18_input_enumeration",
            "status": "already_ok_keep_guarded",
            "reason": "the challenge-panel dry-run enumeration currently passes without submitted jobs",
            "evidence": checks.get("dry_run_enumeration", {}),
            "done_when": "future execution-input manifest still enumerates the same audited 18-row challenge panel",
        },
    ]

    report_path = runtime_report.get("_path")
    discovery_path = discovery.get("_path")
    return {
        "artifact": "m6d_w3_runtime_repair_plan",
        "date": report_date or date.today().isoformat(),
        "status": _REPAIR_READY_STATUS if ready else _REPAIR_BLOCKED_STATUS,
        "audit_ok": ready,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "prediction_executed": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "runtime_ready": False,
        "execution_ready": False,
        "can_claim_independent_predictor_robustness_now": False,
        "selected_predictor_or_protocol_id": runtime_report.get("selected_predictor_or_protocol_id"),
        "source_runtime_probe_report": report_path,
        "source_runtime_probe_report_sha256": _sha256_file(report_path),
        "source_cayuga_runtime_repair_discovery": discovery_path,
        "source_cayuga_runtime_repair_discovery_sha256": _sha256_file(discovery_path),
        "failed_runtime_checks": failed_checks,
        "passed_runtime_checks": passed_checks,
        "repair_items": repair_items,
        "next_action": (
            "provision a W3-specific ColabFold/JAX CUDA runtime, then rerun the existing no-submit "
            "Cayuga runtime probe before generating execution inputs"
        ),
        "claim_boundary": (
            "runtime repair plan only; no prediction execution, no execution-input manifest, no command "
            "wrapper, no approval token, and no positive independent-predictor robustness claim"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3 Runtime Repair Plan",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| selected protocol | `{rep.get('selected_predictor_or_protocol_id')}` |",
        f"| runtime ready | `{rep.get('runtime_ready')}` |",
        f"| execution ready | `{rep.get('execution_ready')}` |",
        f"| failed checks | `{', '.join(rep.get('failed_runtime_checks') or [])}` |",
        f"| passed checks | `{', '.join(rep.get('passed_runtime_checks') or [])}` |",
        f"| execution inputs emitted | `{rep.get('execution_inputs_emitted')}` |",
        f"| command wrapper emitted | `{rep.get('command_wrapper_emitted')}` |",
        "",
        "## Repair Items",
        "",
    ]
    for item in rep.get("repair_items") or []:
        lines.append(f"- `{item.get('id')}`: {item.get('status')} - {item.get('reason')}")
    lines.extend(["", f"Recommended next action: {rep.get('next_action')}", ""])
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime-probe-report", default="results/m6d_w3_runtime_probe_report.json")
    ap.add_argument(
        "--cayuga-runtime-repair-discovery",
        default="results/m6d_w3_cayuga_runtime_repair_discovery.json",
    )
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_runtime_repair_plan.json")
    ap.add_argument("--out-md", default="results/m6d_w3_runtime_repair_plan.md")
    args = ap.parse_args(argv)

    rep = build_runtime_repair_plan(
        _load_json(args.runtime_probe_report),
        _load_json(args.cayuga_runtime_repair_discovery),
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} runtime_ready={runtime} execution_ready={execution} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            runtime=rep["runtime_ready"],
            execution=rep["execution_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
