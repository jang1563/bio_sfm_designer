"""Build the guarded W3 runtime provisioning packet.

The W3 repair plan says ColabFold/JAX runtime provisioning is required, but
blind installs or stale download commands would be unsafe. This packet emits a
guarded validation script for a future explicit runtime provisioning step. The
script refuses to run without an approval environment variable and validates
only an explicitly supplied existing ColabFold binary or Apptainer/Singularity
image. It does not submit jobs, download files, install packages, query
MSA/API services, run prediction, emit execution inputs, or emit a W3 claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional


_REPAIR_READY_STATUS = "w3_runtime_repair_plan_ready_no_submit"
_PACKET_READY_STATUS = "w3_runtime_provision_packet_ready_no_submit"
_PACKET_BLOCKED_STATUS = "w3_runtime_provision_packet_blocked"
_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION"
_APPROVAL_TOKEN = "approve-w3-runtime-provision"
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
    "pip install",
    "conda install",
    "mamba install",
    "micromamba install",
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


def _repair_ids(repair_plan: Dict[str, Any]) -> List[str]:
    rows = repair_plan.get("repair_items")
    if not isinstance(rows, list):
        return []
    return [
        str(row.get("id"))
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def _validate_repair_plan(repair_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if repair_plan.get("status") != _REPAIR_READY_STATUS:
        _add_failure(
            failures,
            "w3_runtime_provision_repair_plan_status_invalid",
            "runtime provisioning packet requires a ready no-submit repair plan",
            expected=_REPAIR_READY_STATUS,
            observed=repair_plan.get("status"),
        )
    if repair_plan.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_runtime_provision_repair_plan_audit_not_ok",
            "runtime provisioning packet requires the repair-plan audit to pass",
            expected=True,
            observed=repair_plan.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if repair_plan.get(field) is not True:
            _add_failure(
                failures,
                f"w3_runtime_provision_repair_plan_{field}_not_true",
                "runtime provisioning packet must inherit no-submit/no-spend boundaries",
                expected=True,
                observed=repair_plan.get(field),
            )
    for field in ("runtime_ready", "execution_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted",
                  "can_claim_independent_predictor_robustness_now"):
        if repair_plan.get(field) is not False:
            _add_failure(
                failures,
                f"w3_runtime_provision_repair_plan_{field}_drift",
                "runtime provisioning packet cannot inherit ready/executable/claiming state",
                expected=False,
                observed=repair_plan.get(field),
            )
    required = {"provision_colabfold_cli", "provision_jax_cuda_runtime"}
    observed = set(_repair_ids(repair_plan))
    if not required.issubset(observed):
        _add_failure(
            failures,
            "w3_runtime_provision_required_repair_items_missing",
            "runtime provisioning packet requires ColabFold CLI and JAX/CUDA repair items",
            expected=sorted(required),
            observed=sorted(observed),
        )
    return failures


def render_provision_script(*, receipt_path: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# W3 guarded runtime provisioning validation for AF2-Multimer/ColabFold.
# This script does not submit jobs, download files, install packages, query
# MSA/API services, run prediction, or emit W3 execution inputs. It only
# validates an explicitly supplied existing runtime after approval.

APPROVAL_ENV_VAR="{_APPROVAL_ENV_VAR}"
APPROVAL_TOKEN="{_APPROVAL_TOKEN}"
RECEIPT="${{M6D_W3_RUNTIME_PROVISION_RECEIPT:-{receipt_path}}}"

if [ "${{{_APPROVAL_ENV_VAR}:-}}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3 runtime provisioning validation without explicit approval env:" >&2
  echo "  export $APPROVAL_ENV_VAR=$APPROVAL_TOKEN" >&2
  exit 64
fi

if [ -z "${{W3_COLABFOLD_BIN:-}}" ] && [ -z "${{W3_COLABFOLD_SIF:-}}" ]; then
  echo "refusing W3 runtime provisioning validation without W3_COLABFOLD_BIN or W3_COLABFOLD_SIF" >&2
  exit 65
fi

mkdir -p "$(dirname "$RECEIPT")"

if [ -n "${{W3_COLABFOLD_BIN:-}}" ]; then
  if [ ! -x "$W3_COLABFOLD_BIN" ]; then
    echo "W3_COLABFOLD_BIN is not executable: $W3_COLABFOLD_BIN" >&2
    exit 66
  fi
  help_output="$("$W3_COLABFOLD_BIN" --help 2>&1 | tail -80)"
  python3 - "$RECEIPT" "$W3_COLABFOLD_BIN" "$help_output" <<'PY'
import json, sys
receipt, runtime, help_output = sys.argv[1:4]
payload = {{
    "artifact": "m6d_w3_runtime_provision_receipt",
    "mode": "existing_colabfold_binary",
    "runtime": runtime,
    "help_checked": True,
    "help_mentions_colabfold": "colabfold" in help_output.lower(),
    "prediction_executed": False,
    "submitted_jobs": 0,
    "execution_inputs_emitted": False,
}}
with open(receipt, "w") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\\n")
PY
  exit 0
fi

if [ ! -f "$W3_COLABFOLD_SIF" ]; then
  echo "W3_COLABFOLD_SIF is not a file: $W3_COLABFOLD_SIF" >&2
  exit 67
fi
APPTAINER_BIN="${{APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}}"
if [ -z "$APPTAINER_BIN" ]; then
  echo "apptainer/singularity runtime is unavailable" >&2
  exit 68
fi
help_output="$("$APPTAINER_BIN" exec "$W3_COLABFOLD_SIF" colabfold_batch --help 2>&1 | tail -80)"
python3 - "$RECEIPT" "$W3_COLABFOLD_SIF" "$APPTAINER_BIN" "$help_output" <<'PY'
import json, sys
receipt, image, apptainer_bin, help_output = sys.argv[1:5]
payload = {{
    "artifact": "m6d_w3_runtime_provision_receipt",
    "mode": "apptainer_colabfold_image",
    "image": image,
    "apptainer_bin": apptainer_bin,
    "help_checked": True,
    "help_mentions_colabfold": "colabfold" in help_output.lower(),
    "prediction_executed": False,
    "submitted_jobs": 0,
    "execution_inputs_emitted": False,
}}
with open(receipt, "w") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\\n")
PY
"""


def _static_script_audit(script_text: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    for marker in _FORBIDDEN_SCRIPT_MARKERS:
        if marker in script_text:
            _add_failure(
                failures,
                "w3_runtime_provision_script_forbidden_marker",
                "provisioning validation script must not contain scheduler, download, or install commands",
                observed=marker.strip(),
            )
    required = [
        _APPROVAL_ENV_VAR,
        _APPROVAL_TOKEN,
        "W3_COLABFOLD_BIN",
        "W3_COLABFOLD_SIF",
        "colabfold_batch --help",
        "prediction_executed",
        "submitted_jobs",
    ]
    for marker in required:
        if marker not in script_text:
            _add_failure(
                failures,
                "w3_runtime_provision_script_missing_marker",
                "provisioning validation script is missing a required guard marker",
                observed=marker,
            )
    return {
        "ok": not failures,
        "forbidden_markers": list(_FORBIDDEN_SCRIPT_MARKERS),
        "failures": failures,
    }


def build_provision_packet(
    repair_plan: Dict[str, Any],
    *,
    script_path: str,
    receipt_path: str,
    script_text: str,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    failures = _validate_repair_plan(repair_plan)
    static_audit = _static_script_audit(script_text)
    failures.extend(static_audit.get("failures", []))
    ready = not failures
    repair_path = repair_plan.get("_path")
    return {
        "artifact": "m6d_w3_runtime_provision_packet",
        "date": report_date or date.today().isoformat(),
        "status": _PACKET_READY_STATUS if ready else _PACKET_BLOCKED_STATUS,
        "audit_ok": ready,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "network_fetch_emitted": False,
        "install_executed": False,
        "provision_validation_executed": False,
        "prediction_executed": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "approval_token_emitted": False,
        "runtime_ready": False,
        "execution_ready": False,
        "can_claim_independent_predictor_robustness_now": False,
        "approval_env_var": _APPROVAL_ENV_VAR,
        "approval_env_value": _APPROVAL_TOKEN,
        "source_runtime_repair_plan": repair_path,
        "source_runtime_repair_plan_sha256": _sha256_file(repair_path),
        "script": script_path,
        "receipt": receipt_path,
        "accepted_runtime_inputs": ["W3_COLABFOLD_BIN", "W3_COLABFOLD_SIF"],
        "static_script_audit": static_audit,
        "next_action": (
            "stage or provide an existing ColabFold runtime through W3_COLABFOLD_BIN or W3_COLABFOLD_SIF, "
            "then run this guarded validation script only with explicit approval"
        ),
        "claim_boundary": (
            "runtime provisioning validation packet only; no submit, no download/install command, no prediction, "
            "no execution inputs, no command wrapper, and no positive W3 robustness claim"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3 Runtime Provision Packet",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "Required approval environment:",
        "",
        "```sh",
        f"export {rep.get('approval_env_var')}={rep.get('approval_env_value')}",
        "```",
        "",
        "| item | value |",
        "|---|---:|",
        f"| script | `{rep.get('script')}` |",
        f"| receipt | `{rep.get('receipt')}` |",
        f"| runtime ready | `{rep.get('runtime_ready')}` |",
        f"| execution ready | `{rep.get('execution_ready')}` |",
        f"| install executed | `{rep.get('install_executed')}` |",
        f"| prediction executed | `{rep.get('prediction_executed')}` |",
        f"| execution inputs emitted | `{rep.get('execution_inputs_emitted')}` |",
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
    ap.add_argument("--runtime-repair-plan", default="results/m6d_w3_runtime_repair_plan.json")
    ap.add_argument("--script", default="results/m6d_w3_runtime_provision_colabfold_guarded.sh")
    ap.add_argument("--receipt", default="results/m6d_w3_runtime_provision_receipt.json")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_runtime_provision_packet.json")
    ap.add_argument("--out-md", default="results/m6d_w3_runtime_provision_packet.md")
    args = ap.parse_args(argv)

    script_text = render_provision_script(receipt_path=args.receipt)
    rep = build_provision_packet(
        _load_json(args.runtime_repair_plan),
        script_path=args.script,
        receipt_path=args.receipt,
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
        "status={status} audit_ok={ok} script={script} runtime_ready={runtime} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            script=rep["script"],
            runtime=rep["runtime_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
