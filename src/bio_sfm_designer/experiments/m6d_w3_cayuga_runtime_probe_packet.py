"""Build the guarded W3 Cayuga runtime-probe packet.

This packet writes a no-submit shell script for recording the target Cayuga
runtime probe for the selected AF2-Multimer/ColabFold protocol. The script does
not submit jobs, does not query MSA/API services, and does not run prediction.
It only records environment/CLI/GPU-stack checks plus dry-run enumeration into
the same runtime-probe report schema used locally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_PLAN_READY_STATUS = "w3_runtime_probe_plan_ready_no_submit"
_LOCAL_REPORT_STATUS = "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit"
_PACKET_READY_STATUS = "w3_cayuga_runtime_probe_packet_ready_no_submit"
_PACKET_BLOCKED_STATUS = "w3_cayuga_runtime_probe_packet_blocked"
_SELECTED_PROTOCOL_ID = "af2_multimer_colabfold_v1"
_FORBIDDEN_SCRIPT_MARKERS = (
    " sbatch ",
    "\nsbatch ",
    " srun ",
    "\nsrun ",
    " qsub ",
    "\nqsub ",
    " bsub ",
    "\nbsub ",
    "curl ",
    "wget ",
)


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


def _sha256_file(path: str) -> Optional[str]:
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


def _target_ids(plan: Dict[str, Any]) -> List[str]:
    contract = plan.get("probe_contract")
    if not isinstance(contract, dict):
        return []
    values = contract.get("target_ids")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, str) and value.strip()]


def _validate_inputs(plan: Dict[str, Any], local_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if plan.get("status") != _PLAN_READY_STATUS or plan.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_cayuga_probe_plan_not_ready",
            "Cayuga probe packet requires a ready no-submit runtime-probe plan",
            expected=_PLAN_READY_STATUS,
            observed={"status": plan.get("status"), "audit_ok": plan.get("audit_ok")},
        )
    if plan.get("selected_predictor_or_protocol_id") != _SELECTED_PROTOCOL_ID:
        _add_failure(
            failures,
            "w3_cayuga_probe_selected_protocol_mismatch",
            "Cayuga probe packet is pinned to the selected AF2-Multimer/ColabFold protocol",
            expected=_SELECTED_PROTOCOL_ID,
            observed=plan.get("selected_predictor_or_protocol_id"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if plan.get(field) is not True:
            _add_failure(
                failures,
                f"w3_cayuga_probe_plan_{field}_not_true",
                "Cayuga probe packet must inherit no-submit/no-spend boundaries",
                expected=True,
                observed=plan.get(field),
            )
    if len(_target_ids(plan)) <= 0:
        _add_failure(
            failures,
            "w3_cayuga_probe_plan_targets_missing",
            "Cayuga probe packet requires enumerated challenge-panel target IDs",
        )

    if local_report.get("status") != _LOCAL_REPORT_STATUS or local_report.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_cayuga_probe_local_report_not_ready",
            "Cayuga probe packet should extend the local-static no-submit runtime-probe report",
            expected=_LOCAL_REPORT_STATUS,
            observed={"status": local_report.get("status"), "audit_ok": local_report.get("audit_ok")},
        )
    if local_report.get("probe_surface") != "local_static_no_submit":
        _add_failure(
            failures,
            "w3_cayuga_probe_local_report_surface_mismatch",
            "Cayuga probe packet expects the current report to be local-static only",
            expected="local_static_no_submit",
            observed=local_report.get("probe_surface"),
        )
    if local_report.get("runtime_ready") is not False or local_report.get("execution_ready") is not False:
        _add_failure(
            failures,
            "w3_cayuga_probe_local_report_ready_drift",
            "local-static report cannot already be runtime/execution ready",
            expected={"runtime_ready": False, "execution_ready": False},
            observed={
                "runtime_ready": local_report.get("runtime_ready"),
                "execution_ready": local_report.get("execution_ready"),
            },
        )
    if local_report.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_cayuga_probe_local_report_claim_leak",
            "Cayuga probe packet cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=local_report.get("can_claim_independent_predictor_robustness_now"),
        )
    return failures


def render_probe_script(*,
                        plan_path: str,
                        observed_checks_path: str,
                        report_json_path: str,
                        report_md_path: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# W3 no-submit runtime probe for AF2-Multimer/ColabFold.
# This script records environment checks only. It does not submit scheduler jobs,
# query external MSA/API services, or run ColabFold prediction.

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
REPO_ROOT="${{BIO_SFM_REPO_ROOT:-$(cd "${{SCRIPT_DIR}}/.." && pwd)}}"
cd "$REPO_ROOT"

PYTHON_BIN="${{BIO_SFM_PYTHON:-python3}}"
export PYTHONNOUSERSITE="${{PYTHONNOUSERSITE:-1}}"
BIO_SFM_TRUST_CORE_SRC="${{BIO_SFM_TRUST_CORE_SRC:-${{REPO_ROOT%/}}/../bio-sfm-trust-core/src}}"
BIO_SFM_PYTHONPATH="${{REPO_ROOT%/}}/src"
if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then
  BIO_SFM_PYTHONPATH="${{BIO_SFM_PYTHONPATH}}:${{BIO_SFM_TRUST_CORE_SRC}}"
fi
export PYTHONPATH="${{BIO_SFM_PYTHONPATH}}${{PYTHONPATH:+:${{PYTHONPATH}}}}"

PLAN_PATH="${{M6D_W3_RUNTIME_PROBE_PLAN:-{plan_path}}}"
OBSERVED_CHECKS_JSON="${{M6D_W3_RUNTIME_PROBE_OBSERVED_CHECKS:-{observed_checks_path}}}"
REPORT_JSON="${{M6D_W3_RUNTIME_PROBE_REPORT_JSON:-{report_json_path}}}"
REPORT_MD="${{M6D_W3_RUNTIME_PROBE_REPORT_MD:-{report_md_path}}}"

mkdir -p "$(dirname "$OBSERVED_CHECKS_JSON")" "$(dirname "$REPORT_JSON")" "$(dirname "$REPORT_MD")"

"$PYTHON_BIN" - "$PLAN_PATH" "$OBSERVED_CHECKS_JSON" <<'PY'
import json
import os
import shutil
import subprocess
import sys

plan_path, out_path = sys.argv[1:3]
with open(plan_path) as fh:
    plan = json.load(fh)

contract = plan.get("probe_contract") or {{}}
target_ids = [x for x in contract.get("target_ids", []) if isinstance(x, str) and x]
expected_n = contract.get("target_count")

candidates = []
for raw in contract.get("candidate_runtime_locations", []):
    if not isinstance(raw, str) or not raw.strip():
        continue
    if raw == "colabfold_batch on PATH":
        resolved = shutil.which("colabfold_batch")
        source = "PATH"
    else:
        resolved = os.path.expandvars(os.path.expanduser(raw))
        source = "expanded_path"
    candidates.append({{
        "candidate": raw,
        "resolved": resolved,
        "exists": bool(resolved and os.path.exists(resolved)),
        "executable": bool(resolved and os.path.exists(resolved) and os.access(resolved, os.X_OK)),
        "source": source,
    }})

selected = next((row["resolved"] for row in candidates if row.get("executable")), None)
observed_checks = [{{
    "kind": "env_discovery",
    "ran": True,
    "ok": selected is not None,
    "candidate_locations": candidates,
    "selected_cli": selected,
}}]

cli_help = {{
    "kind": "cli_help",
    "ran": False,
    "ok": False,
    "selected_cli": selected,
    "reason": "colabfold_batch_not_found",
}}
if selected:
    try:
        proc = subprocess.run(
            [selected, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
        )
        combined = (proc.stdout or "") + "\\n" + (proc.stderr or "")
        cli_help.update({{
            "ran": True,
            "ok": proc.returncode == 0 and "colabfold" in combined.lower(),
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-1000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
        }})
    except Exception as exc:
        cli_help.update({{"ran": True, "ok": False, "error": str(exc)}})
observed_checks.append(cli_help)

gpu = {{
    "kind": "gpu_stack",
    "ran": True,
    "ok": False,
    "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
    "nvidia_smi_ok": False,
    "jax_import_ok": False,
    "jax_gpu_device_seen": False,
}}
if shutil.which("nvidia-smi"):
    proc = subprocess.run(
        ["nvidia-smi", "-L"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=20,
    )
    gpu.update({{
        "nvidia_smi_ok": proc.returncode == 0 and bool(proc.stdout.strip()),
        "nvidia_smi_returncode": proc.returncode,
        "nvidia_smi_stdout_tail": (proc.stdout or "")[-1000:],
        "nvidia_smi_stderr_tail": (proc.stderr or "")[-1000:],
    }})
try:
    import jax  # type: ignore
    devices = [str(device).lower() for device in jax.devices()]
    gpu.update({{
        "jax_import_ok": True,
        "jax_devices": devices,
        "jax_gpu_device_seen": any("gpu" in item or "cuda" in item for item in devices),
    }})
except Exception as exc:
    gpu["jax_error"] = str(exc)
gpu["ok"] = bool(gpu.get("nvidia_smi_ok") and gpu.get("jax_gpu_device_seen"))
observed_checks.append(gpu)

observed_checks.append({{
    "kind": "msa_policy",
    "ran": True,
    "ok": True,
    "public_server_disabled": True,
    "policy": "local database or precomputed MSA only unless explicitly approved",
}})
observed_checks.append({{
    "kind": "dry_run_enumeration",
    "ran": True,
    "ok": len(target_ids) == int(expected_n or 0),
    "n_inputs": len(target_ids),
    "expected_n_inputs": expected_n,
    "submitted_jobs": 0,
}})

out = {{
    "artifact": "m6d_w3_runtime_probe_observed_checks",
    "probe_surface": "cayuga_gpu_no_submit",
    "selected_predictor_or_protocol_id": plan.get("selected_predictor_or_protocol_id"),
    "target_count": len(target_ids),
    "observed_checks": observed_checks,
}}
with open(out_path, "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
    fh.write("\\n")
PY

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3_runtime_probe_report \\
  --w3-runtime-probe-plan "$PLAN_PATH" \\
  --probe-surface cayuga_gpu_no_submit \\
  --observed-checks-json "$OBSERVED_CHECKS_JSON" \\
  --out-json "$REPORT_JSON" \\
  --out-md "$REPORT_MD"
"""


def _static_script_audit(script_text: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    for marker in _FORBIDDEN_SCRIPT_MARKERS:
        if marker in script_text:
            _add_failure(
                failures,
                "w3_cayuga_probe_script_forbidden_marker",
                "probe script must not contain scheduler submit or network fetch commands",
                observed=marker.strip(),
            )
    required = [
        "--probe-surface cayuga_gpu_no_submit",
        "--observed-checks-json",
        "--help",
        "submitted_jobs",
        "nvidia-smi",
        "public_server_disabled",
    ]
    for marker in required:
        if marker not in script_text:
            _add_failure(
                failures,
                "w3_cayuga_probe_script_missing_marker",
                "probe script is missing a required no-submit probe marker",
                observed=marker,
            )
    return {
        "ok": not failures,
        "forbidden_markers": list(_FORBIDDEN_SCRIPT_MARKERS),
        "failures": failures,
    }


def build_packet(plan: Dict[str, Any],
                 local_report: Dict[str, Any],
                 *,
                 script_path: str,
                 observed_checks_path: str,
                 report_json_path: str,
                 report_md_path: str,
                 script_text: str,
                 report_date: Optional[str] = None) -> Dict[str, Any]:
    failures = _validate_inputs(plan, local_report)
    static_audit = _static_script_audit(script_text)
    failures.extend(static_audit.get("failures", []))
    ready = not failures
    plan_path = plan.get("_path")
    report_path = local_report.get("_path")
    return {
        "artifact": "m6d_w3_cayuga_runtime_probe_packet",
        "date": report_date or date.today().isoformat(),
        "status": _PACKET_READY_STATUS if ready else _PACKET_BLOCKED_STATUS,
        "audit_ok": ready,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "prediction_executed": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "selected_predictor_or_protocol_id": plan.get("selected_predictor_or_protocol_id"),
        "target_count": len(_target_ids(plan)),
        "source_runtime_probe_plan": plan_path,
        "source_runtime_probe_plan_sha256": _sha256_file(plan_path),
        "source_local_static_runtime_probe_report": report_path,
        "source_local_static_runtime_probe_report_sha256": _sha256_file(report_path),
        "script": script_path,
        "observed_checks_json": observed_checks_path,
        "future_runtime_probe_report_json": report_json_path,
        "future_runtime_probe_report_md": report_md_path,
        "static_script_audit": static_audit,
        "claim_boundary": (
            "Cayuga no-submit runtime probe packet only; it writes a probe script but does not run "
            "prediction, emit execution inputs, emit a command wrapper, or support a W3 robustness claim"
        ),
        "next_action": (
            "run this script on the target Cayuga GPU surface to refresh the runtime-probe report; "
            "do not submit scheduler jobs or query external services"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3 Cayuga Runtime Probe Packet",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| selected protocol | `{rep.get('selected_predictor_or_protocol_id')}` |",
        f"| target count | `{rep.get('target_count')}` |",
        f"| script | `{rep.get('script')}` |",
        f"| observed checks JSON | `{rep.get('observed_checks_json')}` |",
        f"| future report JSON | `{rep.get('future_runtime_probe_report_json')}` |",
        f"| prediction executed | `{rep.get('prediction_executed')}` |",
        f"| execution inputs emitted | `{rep.get('execution_inputs_emitted')}` |",
        f"| command wrapper emitted | `{rep.get('command_wrapper_emitted')}` |",
        "",
        f"Recommended next action: {rep.get('next_action')}",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--w3-runtime-probe-plan", default="results/m6d_w3_runtime_probe_plan.json")
    ap.add_argument("--local-runtime-probe-report", default="results/m6d_w3_runtime_probe_report_local_static.json")
    ap.add_argument("--script", default="results/m6d_w3_cayuga_runtime_probe_no_submit.sh")
    ap.add_argument("--observed-checks-json", default="results/m6d_w3_cayuga_runtime_probe_observed_checks.json")
    ap.add_argument("--future-report-json", default="results/m6d_w3_runtime_probe_report.json")
    ap.add_argument("--future-report-md", default="results/m6d_w3_runtime_probe_report.md")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_cayuga_runtime_probe_packet.json")
    ap.add_argument("--out-md", default="results/m6d_w3_cayuga_runtime_probe_packet.md")
    args = ap.parse_args(argv)

    script_text = render_probe_script(
        plan_path=args.w3_runtime_probe_plan,
        observed_checks_path=args.observed_checks_json,
        report_json_path=args.future_report_json,
        report_md_path=args.future_report_md,
    )
    rep = build_packet(
        _load_json(args.w3_runtime_probe_plan),
        _load_json(args.local_runtime_probe_report),
        script_path=args.script,
        observed_checks_path=args.observed_checks_json,
        report_json_path=args.future_report_json,
        report_md_path=args.future_report_md,
        script_text=script_text,
        report_date=args.date,
    )
    _write_text(args.script, script_text)
    try:
        os.chmod(args.script, 0o755)
    except OSError:
        pass
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} script={script} target_count={targets} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            script=rep["script"],
            targets=rep["target_count"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
