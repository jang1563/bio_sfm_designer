"""Build a guarded W2 panel wrapper and no-submit preflight artifact."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .complex_target_manifest import validate_manifest
from .m6d_w2_panel_wrapper_guard_audit import build_audit, render_markdown as render_guard_markdown


_DEFAULT_WORKSTREAM = "m6d_w2_target_family_redesign_v11"
_DEFAULT_MANIFEST = "configs/m6d_w2_target_family_redesign_v11_representative_targets.json"
_DEFAULT_WRAPPER = "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh"
_DEFAULT_RECEIPT = "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl"
_DEFAULT_SUMMARY = "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json"
_DEFAULT_POSTSUBMIT_STATUS = "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
_DEFAULT_JOB_STATE_PROBE = "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
_DEFAULT_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V11_PANEL"
_DEFAULT_APPROVAL_TOKEN = "approve-v11-panel-submit"
_DEFAULT_DRY_RUN_ENV_VAR = "M6D_W2_V11_SUBMIT_DRY_RUN"
_DEFAULT_SHARED_WRAPPER = "m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh"
_DEFAULT_CAYUGA_PYTHON = ""
_PUBLIC_REMOTE_HOST = "${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"
_PUBLIC_REMOTE_ROOT = "${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT}"
_PUBLIC_CAYUGA_PYTHON = "${BIO_SFM_PYTHON:?set BIO_SFM_PYTHON}"
_DRY_RUN_TARGET_RE = re.compile(r"^dry-run [^:]+: ProteinMPNN -> ")


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
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


def _target_ids(manifest_path: str) -> List[str]:
    manifest = _load_json(manifest_path)
    ids = []
    for index, target in enumerate(manifest.get("targets", [])):
        if isinstance(target, dict):
            ids.append(str(target.get("id", f"target_{index}")))
    return ids


def _record_paths(manifest_path: str) -> List[str]:
    manifest = _load_json(manifest_path)
    paths = []
    for index, target in enumerate(manifest.get("targets", [])):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id", f"target_{index}"))
        out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
        paths.append(str(target.get("records") or os.path.join(out_prefix, "records_boltz_complex.jsonl")))
    return paths


def _completion_command(
    *,
    manifest: str,
    min_targets: int,
    min_records_per_target: int,
    target_alpha: float,
    panel_out: str,
    completion_out: str,
    emit_plan: Optional[str] = None,
) -> str:
    parts = [
        "python", "-m", "bio_sfm_designer.experiments.complex_panel_completion",
        "--manifest", manifest,
        "--min-targets", str(min_targets),
        "--min-records-per-target", str(min_records_per_target),
        "--target-alpha", str(target_alpha),
        "--panel-out", panel_out,
        "--out", completion_out,
    ]
    if emit_plan:
        parts.extend(["--emit-plan", emit_plan])
    return shlex.join(parts)


def render_completion_script(
    *,
    manifest: str,
    min_targets: int,
    min_records_per_target: int,
    target_alpha: float,
    panel_out: str,
    completion_out: str,
) -> str:
    command = _completion_command(
        manifest=manifest,
        min_targets=min_targets,
        min_records_per_target=min_records_per_target,
        target_alpha=target_alpha,
        panel_out=panel_out,
        completion_out=completion_out,
    )
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Replay the v11 panel completion gate after records are synced back.",
        "set -euo pipefail",
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        "",
        command.replace("python -m ", '"$PYTHON_BIN" -m ', 1),
        "",
    ])


def render_sync_back_script(
    *,
    manifest: str,
    completion_script: str,
    submit_receipt: str,
    submit_summary: str,
    postsubmit_status: str = _DEFAULT_POSTSUBMIT_STATUS,
    job_state_probe: str = _DEFAULT_JOB_STATE_PROBE,
    remote_spec: str,
) -> str:
    remote_root_line = (
        f'REMOTE_ROOT="${{CAYUGA_BIO_SFM_ROOT:-{remote_spec}}}"'
        if remote_spec else
        'REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}"'
    )
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Sync completed W2 panel records back from Cayuga, then replay the local completion gate.",
        "# Run only after the submitted Boltz jobs in the submit receipt have finished.",
        "set -euo pipefail",
        "",
        remote_root_line,
        'LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"',
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        'export PYTHONPATH="${PYTHONPATH:-src}"',
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        f"MANIFEST={shlex.quote(manifest)}",
        f"COMPLETION={shlex.quote(completion_script)}",
        f"RECEIPT={shlex.quote(submit_receipt)}",
        f"SUMMARY={shlex.quote(submit_summary)}",
        f"POSTSUBMIT={shlex.quote(postsubmit_status)}",
        f"JOB_STATES={shlex.quote(job_state_probe)}",
        "export MANIFEST",
        "",
        'test -s "$MANIFEST" || { echo "manifest is missing or empty: $MANIFEST" >&2; exit 2; }',
        'test -s "$COMPLETION" || { echo "completion script is missing or empty: $COMPLETION" >&2; exit 2; }',
        'test -s "$RECEIPT" || { echo "submit receipt is missing locally; run receipt monitor first: $RECEIPT" >&2; exit 2; }',
        'test -s "$SUMMARY" || { echo "submit summary is missing locally; run receipt monitor first: $SUMMARY" >&2; exit 2; }',
        'test -s "$JOB_STATES" || { echo "job-state probe is missing locally; run the job-state query/probe before sync-back: $JOB_STATES" >&2; exit 2; }',
        "",
        (
            '"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status '
            '--manifest "$MANIFEST" --receipt "$RECEIPT" --summary "$SUMMARY" '
            '--job-states "$JOB_STATES" --require-sync-ready '
            '--out-json "$POSTSUBMIT"'
        ),
        "",
        'record_paths="$("$PYTHON_BIN" - <<\'PY\'',
        "import json, os",
        'with open(os.environ["MANIFEST"]) as handle:',
        "    manifest = json.load(handle)",
        'for target in manifest.get("targets", []):',
        "    if not isinstance(target, dict):",
        "        continue",
        '    target_id = str(target.get("id", "target"))',
        '    out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")',
        '    records = str(target.get("records") or f"{out_prefix}/records_boltz_complex.jsonl")',
        "    if records:",
        "        print(records)",
        "PY",
        ')"',
        "",
        'if [ -z "$record_paths" ]; then',
        '  echo "manifest has no record paths: $MANIFEST" >&2',
        "  exit 2",
        "fi",
        "",
        'while IFS= read -r relpath; do',
        '  if [ -z "$relpath" ]; then',
        "    continue",
        "  fi",
        '  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"',
        '  rsync -avP "$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"',
        '  test -s "$LOCAL_ROOT/$relpath"',
        'done <<< "$record_paths"',
        "",
        'mkdir -p "$LOCAL_ROOT/results"',
        'rsync -avP "$REMOTE_ROOT/$RECEIPT" "$REMOTE_ROOT/$SUMMARY" "$LOCAL_ROOT/results/"',
        'test -s "$LOCAL_ROOT/$RECEIPT"',
        'test -s "$LOCAL_ROOT/$SUMMARY"',
        "",
        'BIO_SFM_PYTHON="$PYTHON_BIN" PYTHONNOUSERSITE=1 bash "$COMPLETION"',
        "",
    ])


def render_guarded_wrapper(
    *,
    manifest: str,
    submit_receipt: str,
    submit_summary: str,
    workstream: str,
    approval_env_var: str,
    approval_token: str,
    dry_run_env_var: str,
    shared_wrapper: str = _DEFAULT_SHARED_WRAPPER,
    cayuga_python: str = _DEFAULT_CAYUGA_PYTHON,
) -> str:
    record_artifact = f"{workstream}_submit_record"
    summary_artifact = f"{workstream}_submit_receipt_summary"
    refusal = f"refusing {workstream.split('_')[-1]} panel submission without explicit approval env:"
    lines = [
        "#!/usr/bin/env bash",
        f"# Submit {workstream} through the shared receipt-preserving wrapper.",
        f"# Run with {dry_run_env_var}=1 first.",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        "",
        f"export MANIFEST=\"${{MANIFEST:-{manifest}}}\"",
        f"export SUBMIT_RECEIPT=\"${{SUBMIT_RECEIPT:-{submit_receipt}}}\"",
        f"export SUBMIT_SUMMARY=\"${{SUBMIT_SUMMARY:-{submit_summary}}}\"",
        f"export WORKSTREAM=\"${{WORKSTREAM:-{workstream}}}\"",
        f"export SUBMIT_RECORD_ARTIFACT=\"${{SUBMIT_RECORD_ARTIFACT:-{record_artifact}}}\"",
        f"export SUBMIT_SUMMARY_ARTIFACT=\"${{SUBMIT_SUMMARY_ARTIFACT:-{summary_artifact}}}\"",
        f"export BIO_SFM_SUBMIT_DRY_RUN=\"${{{dry_run_env_var}:-${{BIO_SFM_SUBMIT_DRY_RUN:-0}}}}\"",
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        "",
    ]
    if cayuga_python:
        lines.extend([
            f"if [ -z \"${{BIO_SFM_PYTHON:-}}\" ] && [ -x {shlex.quote(cayuga_python)} ]; then",
            f"  export BIO_SFM_PYTHON={shlex.quote(cayuga_python)}",
            "fi",
            "",
        ])
    lines.extend([
        f"APPROVAL_ENV_VAR=\"{approval_env_var}\"",
        f"APPROVAL_TOKEN=\"{approval_token}\"",
        "",
        'if [ "${BIO_SFM_SUBMIT_DRY_RUN:-0}" = "1" ]; then',
        f"  exec \"$SCRIPT_DIR/{shared_wrapper}\"",
        "fi",
        "",
        f"if [ \"${{{approval_env_var}:-}}\" != \"$APPROVAL_TOKEN\" ]; then",
        f"  echo \"{refusal}\" >&2",
        '  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2',
        f"  echo \"dry-run remains available with {dry_run_env_var}=1 and does not touch the submit receipt\" >&2",
        "  exit 2",
        "fi",
        "",
        f"exec \"$SCRIPT_DIR/{shared_wrapper}\"",
        "",
    ])
    return "\n".join(lines)


def _set_executable(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _dry_run_command(wrapper_path: str, dry_run_env_var: str, python_bin: str) -> str:
    return (
        f"{dry_run_env_var}=1 BIO_SFM_PYTHON={shlex.quote(python_bin)} "
        f"PYTHONNOUSERSITE=1 bash {shlex.quote(wrapper_path)}"
    )


def _run_local_dry_run(
    *,
    wrapper_path: str,
    submit_receipt: str,
    submit_summary: str,
    dry_run_env_var: str,
    approval_env_var: str,
    python_bin: str,
) -> Dict[str, Any]:
    env = os.environ.copy()
    env[dry_run_env_var] = "1"
    env.pop(approval_env_var, None)
    env["BIO_SFM_PYTHON"] = python_bin
    env["PYTHONNOUSERSITE"] = "1"
    before_receipt = os.path.exists(submit_receipt)
    before_summary = os.path.exists(submit_summary)
    proc = subprocess.run(["bash", wrapper_path], text=True, capture_output=True, env=env)
    stdout = proc.stdout
    stderr = proc.stderr
    return {
        "command": _dry_run_command(wrapper_path, dry_run_env_var, python_bin),
        "exit_code": proc.returncode,
        "n_targets_enumerated": sum(1 for line in stdout.splitlines() if _DRY_RUN_TARGET_RE.match(line)),
        "sbatch_called": "Submitted batch job" in stdout or "Submitted batch job" in stderr,
        "receipt_exists_before": before_receipt,
        "summary_exists_before": before_summary,
        "receipt_exists_after": os.path.exists(submit_receipt),
        "summary_exists_after": os.path.exists(submit_summary),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def _remote_dry_run_command(
    *,
    host: str,
    remote_root: str,
    wrapper_path: str,
    dry_run_env_var: str,
    cayuga_python: str,
) -> str:
    remote = (
        f"cd {remote_root} && {dry_run_env_var}=1 BIO_SFM_PYTHON={cayuga_python} "
        f"PYTHONNOUSERSITE=1 PYTHONPATH=src:../bio-sfm-trust-core/src bash {wrapper_path}"
    )
    return "ssh " + host + " " + shlex.quote(remote)


def build_preflight(
    *,
    manifest_path: str,
    manifest_report_path: str,
    wrapper_path: str,
    submit_receipt: str,
    submit_summary: str,
    workstream: str,
    approval_env_var: str,
    approval_token: str,
    dry_run_env_var: str,
    manifest_report: Dict[str, Any],
    wrapper_guard: Dict[str, Any],
    local_dry_run: Optional[Dict[str, Any]] = None,
    remote_host: Optional[str] = None,
    remote_root: Optional[str] = None,
    cayuga_python: str = _DEFAULT_CAYUGA_PYTHON,
) -> Dict[str, Any]:
    target_ids = _target_ids(manifest_path)
    local = local_dry_run or {"ran": False, "reason": "not_requested"}
    failures: List[Dict[str, Any]] = []
    if manifest_report.get("ok") is not True:
        failures.append({"kind": "manifest_not_ready", "message": "manifest require-files report is not ok"})
    if wrapper_guard.get("audit_ok") is not True:
        failures.append({"kind": "wrapper_guard_not_ok", "message": "wrapper guard audit is not ok"})
    if local_dry_run is not None:
        if local_dry_run.get("exit_code") != 0:
            failures.append({"kind": "local_dry_run_failed", "message": "local dry-run exited nonzero"})
        if local_dry_run.get("receipt_exists_after") is not False or local_dry_run.get("summary_exists_after") is not False:
            failures.append({"kind": "local_dry_run_touched_receipt", "message": "dry-run must not create receipt/summary"})

    remote_command = None
    if remote_host and remote_root:
        remote_command = _remote_dry_run_command(
            host=remote_host,
            remote_root=remote_root,
            wrapper_path=wrapper_path,
            dry_run_env_var=dry_run_env_var,
            cayuga_python=cayuga_python,
        )

    return {
        "artifact": f"{workstream}_panel_preflight",
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "panel_preflight_dry_run_passed_not_submitted" if not failures else "panel_preflight_blocked",
        "audit_ok": not failures,
        "manifest": manifest_path,
        "target_ids": target_ids,
        "submit_ready": {
            "path": manifest_report_path,
            "ok": manifest_report.get("ok"),
            "n_targets": manifest_report.get("n_targets"),
            "n_ready_targets": manifest_report.get("n_ready_targets"),
            "min_targets": manifest_report.get("min_targets"),
            "min_contacts": manifest_report.get("min_contacts"),
            "require_files": manifest_report.get("require_files"),
            "failures_by_kind": manifest_report.get("failures_by_kind", {}),
        },
        "artifacts": {
            "submit_wrapper": wrapper_path,
            "wrapper_guard": wrapper_guard.get("_path"),
            "submit_receipt": submit_receipt,
            "submit_summary": submit_summary,
        },
        "local_dry_run": local,
        "cayuga_dry_run": {
            "host": remote_host,
            "remote_root": remote_root,
            "command": remote_command,
        } if remote_command else {"ran": False, "reason": "not_requested"},
        "panel_wrapper_guard": {
            "path": wrapper_guard.get("_path"),
            "status": wrapper_guard.get("status"),
            "approval_env_var": approval_env_var,
            "approval_env_value": approval_token,
            "dry_run_env_var": dry_run_env_var,
            "no_env_non_dry_refuses_before_receipt": (
                wrapper_guard.get("no_env_run", {}).get("ok") is True
                and wrapper_guard.get("no_env_run", {}).get("receipt_exists_after") is False
            ),
        },
        "claim_boundary": {
            "proteinmpnn_boltz_panel_submission": "not_submitted",
            "w2_multi_target_generalization": "not_supported",
            "evidence_status": (
                "preflight and approval-boundary only; not W2 panel evidence until records sync back, "
                "completion passes, and target-wise panel report certifies"
            ),
        },
        "failures": failures,
        "next_action": (
            f"Wait for explicit user approval before running {wrapper_path}; then wait, sync records back, "
            "run completion, and only then run the target-wise panel report."
            if not failures else
            "repair preflight failures before approval or submission"
        ),
    }


def build_runbook(
    *,
    manifest_path: str,
    wrapper_path: str,
    submit_receipt: str,
    submit_summary: str,
    postsubmit_status: str,
    job_state_probe: str,
    sync_back_script: str,
    completion_script: str,
    completion_out: str,
    panel_out: str,
    workstream: str,
    approval_env_var: str,
    approval_token: str,
    dry_run_env_var: str,
    remote_host: str,
    remote_root: str,
    cayuga_python: str,
    target_alpha: float,
    min_targets: int,
    min_records_per_target: int,
) -> Dict[str, Any]:
    remote_submit = (
        "cd "
        + remote_root
        + " && BIO_SFM_PYTHON="
        + cayuga_python
        + " PYTHONNOUSERSITE=1 "
        + approval_env_var
        + "="
        + approval_token
        + " bash "
        + wrapper_path
    )
    submit_command = "ssh " + remote_host + " " + shlex.quote(remote_submit)
    return {
        "artifact": f"{workstream}_approval_runbook",
        "status": "approval_runbook_ready_not_submitted",
        "submit_state": {
            "submitted": False,
            "submit_receipt": submit_receipt,
            "submit_summary": submit_summary,
            "local_submit_receipt_exists": os.path.exists(submit_receipt),
            "local_submit_summary_exists": os.path.exists(submit_summary),
        },
        "manifest": manifest_path,
        "target_ids": _target_ids(manifest_path),
        "record_paths": _record_paths(manifest_path),
        "approval": {
            "required_env_var": approval_env_var,
            "required_env_value": approval_token,
            "dry_run_env_var": dry_run_env_var,
            "submit_command_if_explicitly_approved": submit_command,
        },
        "post_submit": {
            "sync_back_script": sync_back_script,
            "sync_back_command_after_jobs_finish": "bash " + shlex.quote(sync_back_script),
            "postsubmit_status": postsubmit_status,
            "job_state_probe": job_state_probe,
            "postsubmit_sync_ready_gate": (
                "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
                "--require-sync-ready"
            ),
            "completion_script": completion_script,
            "completion_command_after_sync": "bash " + shlex.quote(completion_script),
            "completion_out": completion_out,
            "panel_out": panel_out,
            "target_alpha": target_alpha,
            "min_targets": min_targets,
            "min_records_per_target": min_records_per_target,
        },
        "claim_boundary": (
            "not W2 panel evidence until explicit approval, successful submit receipt, completed Boltz jobs, "
            "sync-back, complex_panel_completion ok=true, and complex_panel_report target-wise interpretation"
        ),
        "next_action": "await explicit approval before running submit_command_if_explicitly_approved",
    }


def render_runbook_markdown(rep: Dict[str, Any]) -> str:
    approval = rep.get("approval") if isinstance(rep.get("approval"), dict) else {}
    post = rep.get("post_submit") if isinstance(rep.get("post_submit"), dict) else {}
    ids = rep.get("target_ids") if isinstance(rep.get("target_ids"), list) else []
    lines = [
        "# M6d W2 Panel Approval Runbook",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Submitted: `{rep.get('submit_state', {}).get('submitted')}`.",
        "",
        f"Manifest: `{rep.get('manifest')}`.",
        f"Target IDs: {', '.join('`' + str(target_id) + '`' for target_id in ids)}.",
        "",
        "Required approval environment:",
        "",
        "```bash",
        f"export {approval.get('required_env_var')}={approval.get('required_env_value')}",
        "```",
        "",
        "Submit command if explicitly approved:",
        "",
        "```bash",
        str(approval.get("submit_command_if_explicitly_approved") or ""),
        "```",
        "",
        "After jobs finish, sync back:",
        "",
        "```bash",
        str(post.get("sync_back_command_after_jobs_finish") or ""),
        "```",
        "",
        "The sync-back script first requires postsubmit sync-ready evidence:",
        "",
        "```bash",
        str(post.get("postsubmit_sync_ready_gate") or ""),
        "```",
        "",
        "After sync-back, completion gate:",
        "",
        "```bash",
        str(post.get("completion_command_after_sync") or ""),
        "```",
        "",
        "Claim boundary: " + str(rep.get("claim_boundary") or ""),
        "",
        "Next action: " + str(rep.get("next_action") or ""),
        "",
    ]
    return "\n".join(lines)


def build_approval_packet(
    *,
    preflight: Dict[str, Any],
    runbook: Dict[str, Any],
    wrapper_guard: Dict[str, Any],
    manifest_report: Dict[str, Any],
    approval_env_var: str,
    approval_token: str,
) -> Dict[str, Any]:
    submit_state = runbook.get("submit_state") if isinstance(runbook.get("submit_state"), dict) else {}
    approval = runbook.get("approval") if isinstance(runbook.get("approval"), dict) else {}
    post_submit = runbook.get("post_submit") if isinstance(runbook.get("post_submit"), dict) else {}
    local_dry_run = preflight.get("local_dry_run") if isinstance(preflight.get("local_dry_run"), dict) else {}
    no_env = wrapper_guard.get("no_env_run") if isinstance(wrapper_guard.get("no_env_run"), dict) else {}
    checks = {
        "target_msa_strict_ready": manifest_report.get("ok") is True,
        "panel_preflight_ready": (
            preflight.get("status") == "panel_preflight_dry_run_passed_not_submitted"
            and preflight.get("audit_ok") is True
        ),
        "panel_submit_ready_targets": preflight.get("submit_ready", {}).get("n_ready_targets"),
        "panel_dry_run_no_sbatch": (
            local_dry_run.get("exit_code") == 0
            and local_dry_run.get("sbatch_called") is False
            and local_dry_run.get("receipt_exists_after") is False
            and local_dry_run.get("summary_exists_after") is False
        ),
        "panel_guard_no_env_refuses": (
            wrapper_guard.get("audit_ok") is True
            and no_env.get("ok") is True
            and no_env.get("receipt_exists_after") is False
        ),
        "submit_receipt_absent": submit_state.get("local_submit_receipt_exists") is False,
        "submit_summary_absent": submit_state.get("local_submit_summary_exists") is False,
    }
    failures = []
    for key in (
        "target_msa_strict_ready",
        "panel_preflight_ready",
        "panel_dry_run_no_sbatch",
        "panel_guard_no_env_refuses",
        "submit_receipt_absent",
        "submit_summary_absent",
    ):
        if checks.get(key) is not True:
            failures.append({
                "kind": "approval_check_failed",
                "check": key,
                "message": f"{key} must be true before approval packet readiness",
                "observed": checks.get(key),
            })
    ready = not failures
    return {
        "artifact": "m6d_w2_panel_approval_packet",
        "status": "panel_approval_packet_ready" if ready else "panel_approval_packet_blocked",
        "audit_ok": ready,
        "approval_packet_ready": ready,
        "can_submit_panel_if_user_explicitly_approves": ready,
        "can_claim_w2_generalization": False,
        "panel_approval_env_var": approval_env_var,
        "panel_approval_env_value": approval_token,
        "inputs": {
            "preflight": preflight.get("artifact"),
            "runbook": runbook.get("artifact"),
            "wrapper_guard": wrapper_guard.get("artifact"),
            "manifest_report": manifest_report.get("manifest"),
        },
        "submit_receipt": submit_state.get("submit_receipt"),
        "submit_summary": submit_state.get("submit_summary"),
        "submit_command_if_approved": approval.get("submit_command_if_explicitly_approved"),
        "dry_run_command": local_dry_run.get("command"),
        "sync_back_command_after_jobs_finish": post_submit.get("sync_back_command_after_jobs_finish"),
        "postsubmit_status_before_sync": post_submit.get("postsubmit_status"),
        "job_state_probe_before_sync": post_submit.get("job_state_probe"),
        "postsubmit_sync_ready_gate": post_submit.get("postsubmit_sync_ready_gate"),
        "completion_command_after_sync": post_submit.get("completion_command_after_sync"),
        "panel_out": post_submit.get("panel_out"),
        "target_alpha": post_submit.get("target_alpha"),
        "checks": checks,
        "claim_boundary": {
            "panel_submission": "allowed only after explicit approval env is supplied",
            "w2_multi_target_generalization": "not_supported",
            "evidence_status": (
                "not W2 evidence until records sync back, completion passes, and target-wise panel report certifies"
            ),
        },
        "failures": failures,
        "next_action": (
            "wait for explicit user approval before running submit_command_if_approved"
            if ready else
            "repair approval packet failures before any panel submission"
        ),
    }


def render_approval_packet_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Approval Packet",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Approval packet ready: `{rep.get('approval_packet_ready')}`.",
        f"Can submit panel if explicitly approved: `{rep.get('can_submit_panel_if_user_explicitly_approves')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        "Required approval environment:",
        "",
        "```bash",
        f"export {rep.get('panel_approval_env_var')}={rep.get('panel_approval_env_value')}",
        "```",
        "",
        "Submit command if explicitly approved:",
        "",
        "```bash",
        str(rep.get("submit_command_if_approved") or ""),
        "```",
        "",
        "Sync-back command after jobs finish:",
        "",
        "```bash",
        str(rep.get("sync_back_command_after_jobs_finish") or ""),
        "```",
        "",
        "Postsubmit sync-ready gate before record sync-back:",
        "",
        "```bash",
        str(rep.get("postsubmit_sync_ready_gate") or ""),
        "```",
        "",
        "Claim boundary: panel submission is not W2 evidence until records sync back, completion passes, and target-wise panel report certifies.",
        "",
        "## Failures",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def render_preflight_markdown(rep: Dict[str, Any]) -> str:
    ids = rep.get("target_ids") if isinstance(rep.get("target_ids"), list) else []
    submit_ready = rep.get("submit_ready") if isinstance(rep.get("submit_ready"), dict) else {}
    guard = rep.get("panel_wrapper_guard") if isinstance(rep.get("panel_wrapper_guard"), dict) else {}
    local = rep.get("local_dry_run") if isinstance(rep.get("local_dry_run"), dict) else {}
    lines = [
        "# M6d W2 Panel Guarded Preflight",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        f"Manifest: `{rep.get('manifest')}`.",
        f"Targets ready: `{submit_ready.get('n_ready_targets')}/{submit_ready.get('n_targets')}`.",
        f"Target IDs: {', '.join('`' + str(target_id) + '`' for target_id in ids)}.",
        "",
        "Guarded wrapper:",
        "",
        "```bash",
        str(rep.get("artifacts", {}).get("submit_wrapper") or ""),
        "```",
        "",
        "Required approval environment:",
        "",
        "```bash",
        f"export {guard.get('approval_env_var')}={guard.get('approval_env_value')}",
        "```",
        "",
        "Local dry-run:",
        "",
        "```bash",
        str(local.get("command") or "not requested"),
        "```",
        "",
        "Claim boundary: this is an approval-boundary artifact only. It is not W2 panel evidence until records sync back, completion passes, and the target-wise panel report certifies.",
        "",
        "## Failures",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=_DEFAULT_MANIFEST)
    ap.add_argument("--workstream", default=_DEFAULT_WORKSTREAM)
    ap.add_argument("--wrapper-out", default=_DEFAULT_WRAPPER)
    ap.add_argument("--submit-receipt", default=_DEFAULT_RECEIPT)
    ap.add_argument("--submit-summary", default=_DEFAULT_SUMMARY)
    ap.add_argument("--postsubmit-status", default=_DEFAULT_POSTSUBMIT_STATUS)
    ap.add_argument("--job-state-probe", default=_DEFAULT_JOB_STATE_PROBE)
    ap.add_argument("--manifest-report", default="results/m6d_w2_target_family_redesign_v11_manifest_post_msa_require_files.json")
    ap.add_argument("--guard-out-json", default="results/m6d_w2_target_family_redesign_v11_panel_wrapper_guard_audit.json")
    ap.add_argument("--guard-out-md", default="results/m6d_w2_target_family_redesign_v11_panel_wrapper_guard_audit.md")
    ap.add_argument("--preflight-out-json", default="results/m6d_w2_target_family_redesign_v11_panel_preflight.json")
    ap.add_argument("--preflight-out-md", default="results/m6d_w2_target_family_redesign_v11_panel_preflight.md")
    ap.add_argument("--runbook-out-json", default="results/m6d_w2_target_family_redesign_v11_approval_runbook.json")
    ap.add_argument("--runbook-out-md", default="results/m6d_w2_target_family_redesign_v11_approval_runbook.md")
    ap.add_argument("--approval-packet-out-json", default="results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json")
    ap.add_argument("--approval-packet-out-md", default="results/m6d_w2_target_family_redesign_v11_panel_approval_packet.md")
    ap.add_argument("--sync-back-out", default="results/m6d_w2_target_family_redesign_v11_sync_back.sh")
    ap.add_argument("--completion-out", default="results/m6d_w2_target_family_redesign_v11_panel_completion.json")
    ap.add_argument("--completion-script-out", default="results/m6d_w2_target_family_redesign_v11_panel_completion.sh")
    ap.add_argument("--panel-out", default="results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json")
    ap.add_argument("--approval-env-var", default=_DEFAULT_APPROVAL_ENV_VAR)
    ap.add_argument("--approval-token", default=_DEFAULT_APPROVAL_TOKEN)
    ap.add_argument("--dry-run-env-var", default=_DEFAULT_DRY_RUN_ENV_VAR)
    ap.add_argument("--shared-wrapper", default=_DEFAULT_SHARED_WRAPPER)
    ap.add_argument("--min-targets", type=int, default=4)
    ap.add_argument("--min-contacts", type=int, default=20)
    ap.add_argument("--min-records-per-target", type=int, default=20)
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--local-python", default=sys.executable)
    ap.add_argument("--cayuga-python", default=os.environ.get("BIO_SFM_PYTHON", _DEFAULT_CAYUGA_PYTHON))
    ap.add_argument("--remote-host", default=None)
    ap.add_argument("--remote-root", default=None)
    ap.add_argument("--run-local-dry-run", action="store_true")
    args = ap.parse_args(argv)

    wrapper = render_guarded_wrapper(
        manifest=args.manifest,
        submit_receipt=args.submit_receipt,
        submit_summary=args.submit_summary,
        workstream=args.workstream,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
        dry_run_env_var=args.dry_run_env_var,
        shared_wrapper=args.shared_wrapper,
        cayuga_python=args.cayuga_python,
    )
    _write_text(args.wrapper_out, wrapper)
    _set_executable(args.wrapper_out)
    remote_spec = (
        f"{args.remote_host}:{args.remote_root}"
        if args.remote_host and args.remote_root else
        ""
    )
    _write_text(
        args.completion_script_out,
        render_completion_script(
            manifest=args.manifest,
            min_targets=args.min_targets,
            min_records_per_target=args.min_records_per_target,
            target_alpha=args.target_alpha,
            panel_out=args.panel_out,
            completion_out=args.completion_out,
        ),
    )
    _set_executable(args.completion_script_out)
    _write_text(
        args.sync_back_out,
        render_sync_back_script(
            manifest=args.manifest,
            completion_script=args.completion_script_out,
            submit_receipt=args.submit_receipt,
            submit_summary=args.submit_summary,
            postsubmit_status=args.postsubmit_status,
            job_state_probe=args.job_state_probe,
            remote_spec=remote_spec,
        ),
    )
    _set_executable(args.sync_back_out)

    manifest_report = validate_manifest(
        args.manifest,
        require_files=True,
        min_targets=args.min_targets,
        min_contacts=args.min_contacts,
    )
    _write_json(args.manifest_report, manifest_report)

    guard = build_audit(
        args.wrapper_out,
        args.submit_receipt,
        run_no_env_check=True,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
        dry_run_env_var=args.dry_run_env_var,
        refusal_message=f"refusing {args.workstream.split('_')[-1]} panel submission without explicit approval env",
        shared_wrapper_marker=f"{args.shared_wrapper}\"",
        panel_label=args.workstream,
    )
    guard["_path"] = os.path.abspath(args.guard_out_json)
    _write_json(args.guard_out_json, guard)
    _write_text(args.guard_out_md, render_guard_markdown(guard))

    local_dry_run = None
    if args.run_local_dry_run:
        local_dry_run = _run_local_dry_run(
            wrapper_path=args.wrapper_out,
            submit_receipt=args.submit_receipt,
            submit_summary=args.submit_summary,
            dry_run_env_var=args.dry_run_env_var,
            approval_env_var=args.approval_env_var,
            python_bin=args.local_python,
        )

    preflight = build_preflight(
        manifest_path=args.manifest,
        manifest_report_path=args.manifest_report,
        wrapper_path=args.wrapper_out,
        submit_receipt=args.submit_receipt,
        submit_summary=args.submit_summary,
        workstream=args.workstream,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
        dry_run_env_var=args.dry_run_env_var,
        manifest_report=manifest_report,
        wrapper_guard=guard,
        local_dry_run=local_dry_run,
        remote_host=args.remote_host,
        remote_root=args.remote_root,
        cayuga_python=args.cayuga_python,
    )
    _write_json(args.preflight_out_json, preflight)
    _write_text(args.preflight_out_md, render_preflight_markdown(preflight))
    runbook = build_runbook(
        manifest_path=args.manifest,
        wrapper_path=args.wrapper_out,
        submit_receipt=args.submit_receipt,
        submit_summary=args.submit_summary,
        postsubmit_status=args.postsubmit_status,
        job_state_probe=args.job_state_probe,
        sync_back_script=args.sync_back_out,
        completion_script=args.completion_script_out,
        completion_out=args.completion_out,
        panel_out=args.panel_out,
        workstream=args.workstream,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
        dry_run_env_var=args.dry_run_env_var,
        remote_host=args.remote_host or _PUBLIC_REMOTE_HOST,
        remote_root=args.remote_root or _PUBLIC_REMOTE_ROOT,
        cayuga_python=args.cayuga_python or _PUBLIC_CAYUGA_PYTHON,
        target_alpha=args.target_alpha,
        min_targets=args.min_targets,
        min_records_per_target=args.min_records_per_target,
    )
    _write_json(args.runbook_out_json, runbook)
    _write_text(args.runbook_out_md, render_runbook_markdown(runbook))
    approval_packet = build_approval_packet(
        preflight=preflight,
        runbook=runbook,
        wrapper_guard=guard,
        manifest_report=manifest_report,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
    )
    _write_json(args.approval_packet_out_json, approval_packet)
    _write_text(args.approval_packet_out_md, render_approval_packet_markdown(approval_packet))

    print(f"# guarded panel preflight  ok={preflight['audit_ok']} status={preflight['status']}")
    print(f"wrote {args.wrapper_out}")
    print(f"wrote {args.guard_out_json}")
    print(f"wrote {args.preflight_out_json}")
    print(f"wrote {args.runbook_out_json}")
    print(f"wrote {args.approval_packet_out_json}")
    return 0 if preflight["audit_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
