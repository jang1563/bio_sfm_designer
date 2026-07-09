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
_DEFAULT_RECEIPT_MONITOR = "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh"
_DEFAULT_JOB_STATE_QUERY = "results/m6d_w2_target_family_redesign_v11_job_state_query.sh"
_DEFAULT_SACCT_STATES = "results/m6d_w2_target_family_redesign_v11_sacct_states.tsv"
_DEFAULT_POSTSYNC_REPLAY = "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh"
_DEFAULT_POSTSUBMIT_DRIVER = "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh"
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


def _manifest_target_ids(manifest: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(manifest, dict):
        return []
    ids = []
    for index, target in enumerate(manifest.get("targets", [])):
        if isinstance(target, dict):
            ids.append(str(target.get("id", f"target_{index}")))
    return ids


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_approval_scope(
    *,
    preflight: Dict[str, Any],
    runbook: Dict[str, Any],
    manifest_report: Dict[str, Any],
    manifest_obj: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    submit_ready = preflight.get("submit_ready") if isinstance(preflight.get("submit_ready"), dict) else {}
    post_submit = runbook.get("post_submit") if isinstance(runbook.get("post_submit"), dict) else {}
    submit_state = runbook.get("submit_state") if isinstance(runbook.get("submit_state"), dict) else {}
    manifest_defaults = manifest_obj.get("defaults") if isinstance(manifest_obj, dict) else {}
    if not isinstance(manifest_defaults, dict):
        manifest_defaults = {}

    target_ids = preflight.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids:
        target_ids = runbook.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids:
        target_ids = manifest_report.get("ready_targets")
    if not isinstance(target_ids, list) or not target_ids:
        target_ids = manifest_report.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids:
        target_ids = _manifest_target_ids(manifest_obj)
    target_ids = [str(target_id) for target_id in target_ids]

    n_ready_targets = _int_or_none(submit_ready.get("n_ready_targets"))
    if n_ready_targets is None:
        n_ready_targets = _int_or_none(manifest_report.get("n_ready_targets"))
    if n_ready_targets is None:
        n_ready_targets = len(target_ids)

    n_targets = _int_or_none(submit_ready.get("n_targets"))
    if n_targets is None:
        n_targets = _int_or_none(manifest_report.get("n_targets"))
    if n_targets is None:
        n_targets = len(target_ids)

    min_targets = _int_or_none(post_submit.get("min_targets"))
    if min_targets is None:
        min_targets = _int_or_none(submit_ready.get("min_targets"))
    if min_targets is None:
        min_targets = _int_or_none(manifest_report.get("min_targets"))

    records_per_target = _int_or_none(manifest_defaults.get("num_seq"))
    planned_records = n_ready_targets * records_per_target if n_ready_targets is not None and records_per_target else None
    expected_job_pairs = n_ready_targets
    expected_slurm_jobs = expected_job_pairs * 2 if expected_job_pairs is not None else None

    return {
        "manifest": runbook.get("manifest") or preflight.get("manifest"),
        "target_ids": target_ids,
        "n_targets": n_targets,
        "n_ready_targets": n_ready_targets,
        "min_targets": min_targets,
        "records_per_target_planned": records_per_target,
        "planned_design_records": planned_records,
        "expected_job_pairs": expected_job_pairs,
        "expected_slurm_jobs": expected_slurm_jobs,
        "job_pair_model": "ProteinMPNN -> Boltz",
        "target_alpha": post_submit.get("target_alpha"),
        "panel_out": post_submit.get("panel_out"),
        "completion_after_sync": post_submit.get("completion_command_after_sync"),
        "sync_back_after_jobs_finish": post_submit.get("sync_back_command_after_jobs_finish"),
        "submit_receipt": submit_state.get("submit_receipt"),
        "submit_summary": submit_state.get("submit_summary"),
        "no_submit": True,
        "can_claim_w2_generalization": False,
    }


def _approval_scope_ok(scope: Dict[str, Any], checks: Dict[str, Any]) -> bool:
    n_ready = _int_or_none(scope.get("n_ready_targets"))
    n_targets = _int_or_none(scope.get("n_targets"))
    min_targets = _int_or_none(scope.get("min_targets"))
    records_per_target = _int_or_none(scope.get("records_per_target_planned"))
    planned_records = _int_or_none(scope.get("planned_design_records"))
    expected_job_pairs = _int_or_none(scope.get("expected_job_pairs"))
    expected_slurm_jobs = _int_or_none(scope.get("expected_slurm_jobs"))
    target_ids = scope.get("target_ids")
    return (
        bool(scope.get("manifest"))
        and isinstance(target_ids, list)
        and n_ready is not None
        and n_targets is not None
        and min_targets is not None
        and len(target_ids) == n_ready
        and n_ready == checks.get("panel_submit_ready_targets")
        and n_targets >= n_ready
        and n_ready >= min_targets
        and records_per_target is not None
        and records_per_target > 0
        and planned_records == n_ready * records_per_target
        and expected_job_pairs == n_ready
        and expected_slurm_jobs == n_ready * 2
        and scope.get("job_pair_model") == "ProteinMPNN -> Boltz"
        and scope.get("target_alpha") is not None
        and bool(scope.get("panel_out"))
        and bool(scope.get("completion_after_sync"))
        and bool(scope.get("sync_back_after_jobs_finish"))
        and scope.get("no_submit") is True
        and scope.get("can_claim_w2_generalization") is False
    )


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
        'export PYTHONPATH="${PYTHONPATH:-src}"',
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
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
    sacct_states: str = _DEFAULT_SACCT_STATES,
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
        f"SACCT_STATES={shlex.quote(sacct_states)}",
        "export MANIFEST",
        "",
        'test -s "$MANIFEST" || { echo "manifest is missing or empty: $MANIFEST" >&2; exit 2; }',
        'test -s "$COMPLETION" || { echo "completion script is missing or empty: $COMPLETION" >&2; exit 2; }',
        'test -s "$RECEIPT" || { echo "submit receipt is missing locally; run receipt monitor first: $RECEIPT" >&2; exit 2; }',
        'test -s "$SUMMARY" || { echo "submit summary is missing locally; run receipt monitor first: $SUMMARY" >&2; exit 2; }',
        'mkdir -p "$LOCAL_ROOT/$(dirname "$JOB_STATES")"',
        (
            'rsync -avP "$REMOTE_ROOT/$JOB_STATES" "$LOCAL_ROOT/$JOB_STATES" || '
            '{ echo "remote job-state probe is missing; run the job-state query bridge first: $JOB_STATES" >&2; exit 2; }'
        ),
        'mkdir -p "$LOCAL_ROOT/$(dirname "$SACCT_STATES")"',
        'rsync -avP "$REMOTE_ROOT/$SACCT_STATES" "$LOCAL_ROOT/$SACCT_STATES" || true',
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


def render_postsubmit_driver_script(
    *,
    receipt_monitor_script: str,
    job_state_query_script: str,
    postsync_replay_script: str,
    job_state_probe: str,
    sacct_states: str,
    manifest: str = _DEFAULT_MANIFEST,
    submit_receipt: str = _DEFAULT_RECEIPT,
    submit_summary: str = _DEFAULT_SUMMARY,
    postsubmit_status: str = _DEFAULT_POSTSUBMIT_STATUS,
    remote_host: Optional[str] = None,
    remote_root: Optional[str] = None,
) -> str:
    remote_host_line = (
        f'REMOTE_HOST="${{CAYUGA_BIO_SFM_HOST:-{remote_host}}}"'
        if remote_host else
        'REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"'
    )
    remote_path_line = (
        f'REMOTE_PATH="${{CAYUGA_BIO_SFM_REMOTE_ROOT:-{remote_root}}}"'
        if remote_root else
        'REMOTE_PATH="${CAYUGA_BIO_SFM_REMOTE_ROOT:?set CAYUGA_BIO_SFM_REMOTE_ROOT}"'
    )
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Drive the W2 v11 post-submit ladder after an explicitly approved guarded submit.",
        "# This script never submits jobs; it requires an existing submit receipt.",
        "set -euo pipefail",
        "",
        remote_host_line,
        remote_path_line,
        'REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:-$REMOTE_HOST:$REMOTE_PATH}"',
        'LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"',
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        'export PYTHONPATH="${PYTHONPATH:-src}"',
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        f"RECEIPT_MONITOR={shlex.quote(receipt_monitor_script)}",
        f"JOB_STATE_QUERY={shlex.quote(job_state_query_script)}",
        f"POSTSYNC_REPLAY={shlex.quote(postsync_replay_script)}",
        f"MANIFEST={shlex.quote(manifest)}",
        f"RECEIPT={shlex.quote(submit_receipt)}",
        f"SUMMARY={shlex.quote(submit_summary)}",
        f"POSTSUBMIT={shlex.quote(postsubmit_status)}",
        f"JOB_STATES={shlex.quote(job_state_probe)}",
        f"SACCT_STATES={shlex.quote(sacct_states)}",
        'MAX_POLLS="${M6D_W2_POSTSUBMIT_MAX_POLLS:-120}"',
        'POLL_SECONDS="${M6D_W2_POSTSUBMIT_POLL_SECONDS:-300}"',
        "",
        'cd "$LOCAL_ROOT"',
        'test -s "$RECEIPT_MONITOR" || { echo "receipt monitor script is missing: $RECEIPT_MONITOR" >&2; exit 2; }',
        'test -s "$JOB_STATE_QUERY" || { echo "job-state query script is missing: $JOB_STATE_QUERY" >&2; exit 2; }',
        'test -s "$POSTSYNC_REPLAY" || { echo "post-sync replay script is missing: $POSTSYNC_REPLAY" >&2; exit 2; }',
        'test -s "$MANIFEST" || { echo "manifest is missing: $MANIFEST" >&2; exit 2; }',
        "",
        'poll=1',
        'while :; do',
        '  echo "W2 v11 postsubmit poll ${poll}/${MAX_POLLS}"',
        '  CAYUGA_BIO_SFM_ROOT="$REMOTE_ROOT" LOCAL_BIO_SFM_ROOT="$LOCAL_ROOT" BIO_SFM_PYTHON="$PYTHON_BIN" bash "$RECEIPT_MONITOR"',
        '  remote_cmd="$(printf \'cd %q && bash %q\' "$REMOTE_PATH" "$JOB_STATE_QUERY")"',
        '  ssh "$REMOTE_HOST" "$remote_cmd"',
        '  mkdir -p "$LOCAL_ROOT/$(dirname "$JOB_STATES")" "$LOCAL_ROOT/$(dirname "$SACCT_STATES")"',
        '  rsync -avP "$REMOTE_ROOT/$JOB_STATES" "$LOCAL_ROOT/$JOB_STATES"',
        '  rsync -avP "$REMOTE_ROOT/$SACCT_STATES" "$LOCAL_ROOT/$SACCT_STATES"',
        '  test -s "$LOCAL_ROOT/$JOB_STATES"',
        '  test -s "$LOCAL_ROOT/$SACCT_STATES"',
        '  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest "$MANIFEST" --receipt "$RECEIPT" --summary "$SUMMARY" --job-states "$JOB_STATES" --out-json "$POSTSUBMIT"',
        '  sync_ready="$("$PYTHON_BIN" - "$POSTSUBMIT" <<\'PY\'',
        "import json, sys",
        "with open(sys.argv[1]) as handle:",
        "    rep = json.load(handle)",
        "print('true' if rep.get('sync_ready') is True else 'false')",
        "PY",
        ')"',
        '  if [ "$sync_ready" = "true" ]; then',
        '    break',
        '  fi',
        '  if [ "$poll" -ge "$MAX_POLLS" ]; then',
        '    echo "postsubmit jobs are not sync-ready after ${MAX_POLLS} poll(s); leaving no-submit status for inspection: $POSTSUBMIT" >&2',
        '    exit 2',
        '  fi',
        '  sleep "$POLL_SECONDS"',
        '  poll=$((poll + 1))',
        'done',
        "",
        'BIO_SFM_PYTHON="$PYTHON_BIN" PYTHONNOUSERSITE=1 bash "$POSTSYNC_REPLAY"',
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


def _postsubmit_status_command(
    *,
    manifest: str,
    submit_receipt: str,
    submit_summary: str,
    job_state_probe: str,
    postsubmit_status: str,
) -> str:
    return shlex.join([
        "python", "-m", "bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status",
        "--manifest", manifest,
        "--receipt", submit_receipt,
        "--summary", submit_summary,
        "--job-states", job_state_probe,
        "--require-sync-ready",
        "--out-json", postsubmit_status,
    ])


def _postsubmit_driver_polling_contract() -> Dict[str, Any]:
    return {
        "max_polls_env_var": "M6D_W2_POSTSUBMIT_MAX_POLLS",
        "default_max_polls": 120,
        "poll_seconds_env_var": "M6D_W2_POSTSUBMIT_POLL_SECONDS",
        "default_poll_seconds": 300,
        "sync_ready_gate": "m6d_w2_panel_postsubmit_status.sync_ready",
        "proceeds_only_when_sync_ready": True,
    }


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
    receipt_monitor_script: str,
    job_state_query_script: str,
    sacct_states: str,
    postsubmit_driver_script: str,
    postsync_replay_script: str,
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
    remote_spec = f"{remote_host}:{remote_root}"
    receipt_monitor_command = (
        "CAYUGA_BIO_SFM_ROOT="
        + shlex.quote(remote_spec)
        + " bash "
        + shlex.quote(receipt_monitor_script)
    )
    job_state_query_command = (
        "ssh "
        + remote_host
        + " "
        + shlex.quote("cd " + remote_root + " && bash " + job_state_query_script)
    )
    job_state_probe_sync_dirs = sorted({
        os.path.dirname(job_state_probe) or ".",
        os.path.dirname(sacct_states) or ".",
    })
    job_state_probe_sync_command = (
        "mkdir -p "
        + " ".join(shlex.quote(path) for path in job_state_probe_sync_dirs)
        + " && rsync -avP "
        + shlex.quote(remote_spec + "/" + job_state_probe)
        + " "
        + shlex.quote(job_state_probe)
        + " && rsync -avP "
        + shlex.quote(remote_spec + "/" + sacct_states)
        + " "
        + shlex.quote(sacct_states)
    )
    job_state_query_bridge_command = job_state_query_command + " && " + job_state_probe_sync_command
    postsubmit_status_command = _postsubmit_status_command(
        manifest=manifest_path,
        submit_receipt=submit_receipt,
        submit_summary=submit_summary,
        job_state_probe=job_state_probe,
        postsubmit_status=postsubmit_status,
    )
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
            "receipt_monitor_script": receipt_monitor_script,
            "receipt_monitor_command_after_submit": receipt_monitor_command,
            "postsubmit_driver_script": postsubmit_driver_script,
            "postsubmit_driver_command_after_submit": "bash " + shlex.quote(postsubmit_driver_script),
            "postsubmit_driver_polling": _postsubmit_driver_polling_contract(),
            "job_state_probe_command_after_receipt_sync": (
                "python -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe"
            ),
            "job_state_probe_sync_after_query": job_state_probe_sync_command,
            "job_state_query_plan_after_probe": job_state_query_script,
            "job_state_query_command_after_probe": job_state_query_bridge_command,
            "sync_back_script": sync_back_script,
            "sync_back_command_after_jobs_finish": "bash " + shlex.quote(sync_back_script),
            "postsubmit_status": postsubmit_status,
            "job_state_probe": job_state_probe,
            "sacct_states": sacct_states,
            "postsubmit_sync_ready_gate": postsubmit_status_command,
            "postsubmit_status_command_before_sync": postsubmit_status_command,
            "completion_script": completion_script,
            "completion_command_after_sync": "bash " + shlex.quote(completion_script),
            "completion_out": completion_out,
            "postsync_replay_script": postsync_replay_script,
            "postsync_replay_command_after_sync_ready": "bash " + shlex.quote(postsync_replay_script),
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
        "After submit, sync receipt/summary only:",
        "",
        "```bash",
        str(post.get("receipt_monitor_command_after_submit") or ""),
        "```",
        "",
        "One-command no-submit post-submit driver after approved submit:",
        "",
        "```bash",
        str(post.get("postsubmit_driver_command_after_submit") or ""),
        "```",
        "",
        "Post-submit driver polling:",
        "",
        "```text",
        json.dumps(post.get("postsubmit_driver_polling") or {}, sort_keys=True),
        "```",
        "",
        "After receipt sync, generate and run the read-only job-state query:",
        "",
        "```bash",
        str(post.get("job_state_probe_command_after_receipt_sync") or ""),
        str(post.get("job_state_query_command_after_probe") or ""),
        "```",
        "",
        "The job-state query bridge syncs the remote probe JSON/TSV back locally before postsubmit status:",
        "",
        "```bash",
        str(post.get("job_state_probe_sync_after_query") or ""),
        "```",
        "",
        "Before record sync-back, require postsubmit sync-ready status:",
        "",
        "```bash",
        str(post.get("postsubmit_status_command_before_sync") or post.get("postsubmit_sync_ready_gate") or ""),
        "```",
        "",
        "After jobs finish and postsubmit status is sync-ready, sync back:",
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
        "Post-sync report and interpretation replay:",
        "",
        "```bash",
        str(post.get("postsync_replay_command_after_sync_ready") or ""),
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
    manifest_obj: Optional[Dict[str, Any]] = None,
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
    approval_scope = _build_approval_scope(
        preflight=preflight,
        runbook=runbook,
        manifest_report=manifest_report,
        manifest_obj=manifest_obj,
    )
    checks["approval_scope_ready"] = _approval_scope_ok(approval_scope, checks)
    failures = []
    for key in (
        "target_msa_strict_ready",
        "panel_preflight_ready",
        "panel_dry_run_no_sbatch",
        "panel_guard_no_env_refuses",
        "submit_receipt_absent",
        "submit_summary_absent",
        "approval_scope_ready",
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
        "manifest": runbook.get("manifest"),
        "submit_receipt": submit_state.get("submit_receipt"),
        "submit_summary": submit_state.get("submit_summary"),
        "submit_command_if_approved": approval.get("submit_command_if_explicitly_approved"),
        "dry_run_command": local_dry_run.get("command"),
        "sync_back_command_after_jobs_finish": post_submit.get("sync_back_command_after_jobs_finish"),
        "receipt_monitor_after_submit": post_submit.get("receipt_monitor_command_after_submit"),
        "postsubmit_driver_after_submit": post_submit.get("postsubmit_driver_command_after_submit"),
        "postsubmit_driver_script": post_submit.get("postsubmit_driver_script"),
        "postsubmit_driver_polling": post_submit.get("postsubmit_driver_polling"),
        "job_state_query_after_receipt": post_submit.get("job_state_query_command_after_probe"),
        "job_state_probe_sync_after_query": post_submit.get("job_state_probe_sync_after_query"),
        "postsubmit_status_before_sync": post_submit.get("postsubmit_status"),
        "job_state_probe_before_sync": post_submit.get("job_state_probe"),
        "sacct_states_before_sync": post_submit.get("sacct_states"),
        "postsubmit_sync_ready_gate": post_submit.get("postsubmit_sync_ready_gate"),
        "postsubmit_status_command_before_sync": post_submit.get("postsubmit_status_command_before_sync"),
        "completion_command_after_sync": post_submit.get("completion_command_after_sync"),
        "postsync_replay_after_sync": post_submit.get("postsync_replay_command_after_sync_ready"),
        "panel_out": post_submit.get("panel_out"),
        "target_alpha": post_submit.get("target_alpha"),
        "approval_scope": approval_scope,
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
    scope = rep.get("approval_scope") if isinstance(rep.get("approval_scope"), dict) else {}
    lines = [
        "# M6d W2 Panel Approval Packet",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Approval packet ready: `{rep.get('approval_packet_ready')}`.",
        f"Can submit panel if explicitly approved: `{rep.get('can_submit_panel_if_user_explicitly_approves')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        "Approval scope:",
        "",
        f"- manifest: `{scope.get('manifest')}`",
        f"- targets: `{scope.get('n_ready_targets')}` ready of `{scope.get('n_targets')}` total",
        f"- target ids: `{', '.join(scope.get('target_ids') or [])}`",
        f"- planned designs: `{scope.get('planned_design_records')}` "
        f"({scope.get('records_per_target_planned')} per target)",
        f"- expected Slurm jobs: `{scope.get('expected_slurm_jobs')}` "
        f"(`{scope.get('job_pair_model')}` pairs)",
        f"- target alpha: `{scope.get('target_alpha')}`",
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
        "Receipt/job-state bridge after explicit submit:",
        "",
        "```bash",
        str(rep.get("receipt_monitor_after_submit") or ""),
        str(rep.get("job_state_query_after_receipt") or ""),
        "```",
        "",
        "One-command no-submit post-submit driver:",
        "",
        "```bash",
        str(rep.get("postsubmit_driver_after_submit") or ""),
        "```",
        "",
        "Post-submit driver polling:",
        "",
        "```text",
        json.dumps(rep.get("postsubmit_driver_polling") or {}, sort_keys=True),
        "```",
        "",
        "Job-state probe sync after query:",
        "",
        "```bash",
        str(rep.get("job_state_probe_sync_after_query") or ""),
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
        "Post-sync replay after sync-ready status:",
        "",
        "```bash",
        str(rep.get("postsync_replay_after_sync") or ""),
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
    ap.add_argument("--receipt-monitor-script", default=_DEFAULT_RECEIPT_MONITOR)
    ap.add_argument("--job-state-query-script", default=_DEFAULT_JOB_STATE_QUERY)
    ap.add_argument("--sacct-states", default=_DEFAULT_SACCT_STATES)
    ap.add_argument("--postsync-replay-script", default=_DEFAULT_POSTSYNC_REPLAY)
    ap.add_argument("--postsubmit-driver-script", default=_DEFAULT_POSTSUBMIT_DRIVER)
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
            sacct_states=args.sacct_states,
            remote_spec=remote_spec,
        ),
    )
    _set_executable(args.sync_back_out)
    _write_text(
        args.postsubmit_driver_script,
        render_postsubmit_driver_script(
            receipt_monitor_script=args.receipt_monitor_script,
            job_state_query_script=args.job_state_query_script,
            postsync_replay_script=args.postsync_replay_script,
            job_state_probe=args.job_state_probe,
            sacct_states=args.sacct_states,
            manifest=args.manifest,
            submit_receipt=args.submit_receipt,
            submit_summary=args.submit_summary,
            postsubmit_status=args.postsubmit_status,
            remote_host=args.remote_host,
            remote_root=args.remote_root,
        ),
    )
    _set_executable(args.postsubmit_driver_script)

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
        receipt_monitor_script=args.receipt_monitor_script,
        job_state_query_script=args.job_state_query_script,
        sacct_states=args.sacct_states,
        postsubmit_driver_script=args.postsubmit_driver_script,
        postsync_replay_script=args.postsync_replay_script,
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
        manifest_obj=_load_json(args.manifest),
    )
    _write_json(args.approval_packet_out_json, approval_packet)
    _write_text(args.approval_packet_out_md, render_approval_packet_markdown(approval_packet))

    print(f"# guarded panel preflight  ok={preflight['audit_ok']} status={preflight['status']}")
    print(f"wrote {args.wrapper_out}")
    print(f"wrote {args.guard_out_json}")
    print(f"wrote {args.preflight_out_json}")
    print(f"wrote {args.runbook_out_json}")
    print(f"wrote {args.postsubmit_driver_script}")
    print(f"wrote {args.approval_packet_out_json}")
    return 0 if preflight["audit_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
