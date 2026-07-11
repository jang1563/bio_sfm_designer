"""Monitor W2 v11 panel submit receipt availability before record sync-back.

This helper never submits jobs and does not pull model records. It checks local
and Cayuga submit receipt/summary files, emits a receipt-only sync plan when the
remote receipt is ready, and then hands off to the W2 panel job-state probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import stat
import subprocess
from typing import Any, Dict, List, Optional, Tuple


_DEFAULT_RECEIPT = "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl"
_DEFAULT_SUMMARY = "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_receipt_monitor.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_receipt_monitor.md"
_DEFAULT_SYNC_PLAN = "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh"
_DEFAULT_JOB_STATE_PROBE = "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
_DEFAULT_JOB_STATE_PROBE_MD = "results/m6d_w2_target_family_redesign_v11_job_state_probe.md"
_DEFAULT_JOB_STATE_QUERY = "results/m6d_w2_target_family_redesign_v11_job_state_query.sh"
_DEFAULT_SACCT_STATES = "results/m6d_w2_target_family_redesign_v11_sacct_states.tsv"
_DEFAULT_EXPECTED_WORKSTREAM = "m6d_w2_target_family_redesign_v11"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str, *, executable: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if executable:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update({key: value for key, value in extra.items() if value is not None})
    failures.append(row)


def _read_local(root: str, rel_path: str) -> bytes:
    with open(os.path.join(root, rel_path), "rb") as fh:
        return fh.read()


def _run_ssh(remote_host: str, command: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", remote_host, command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _read_remote(remote_root: str, rel_path: str, *, remote_host: Optional[str], ssh_timeout: int) -> bytes:
    if not remote_host:
        return _read_local(remote_root, rel_path)
    path = os.path.join(remote_root, rel_path)
    proc = _run_ssh(remote_host, "cat " + shlex.quote(path), ssh_timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def _file_state(scope: str,
                rel_path: str,
                *,
                root: str,
                remote_host: Optional[str] = None,
                ssh_timeout: int = 30) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "scope": scope,
        "path": rel_path,
        "root": root,
        "remote_host": remote_host or "",
        "exists": False,
        "size_bytes": 0,
        "sha256": "",
    }
    try:
        data = (
            _read_remote(root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout)
            if scope == "remote"
            else _read_local(root, rel_path)
        )
    except Exception as exc:
        row["error"] = str(exc)
        return row
    row.update({
        "exists": True,
        "size_bytes": len(data),
        "sha256": _sha256(data),
    })
    return row


def _pair_ok(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return (
        local.get("exists") is True
        and remote.get("exists") is True
        and local.get("sha256")
        and local.get("sha256") == remote.get("sha256")
    )


def build_monitor(*,
                  local_root: str = ".",
                  remote_root: str = "",
                  remote_host: Optional[str] = None,
                  receipt_path: str = _DEFAULT_RECEIPT,
                  summary_path: str = _DEFAULT_SUMMARY,
                  sync_plan_path: str = _DEFAULT_SYNC_PLAN,
                  ssh_timeout: int = 30) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    local_receipt = _file_state("local", receipt_path, root=local_root)
    local_summary = _file_state("local", summary_path, root=local_root)
    remote_receipt = _file_state(
        "remote", receipt_path, root=remote_root, remote_host=remote_host, ssh_timeout=ssh_timeout
    ) if remote_root else {"scope": "remote", "path": receipt_path, "exists": None, "remote_checked": False}
    remote_summary = _file_state(
        "remote", summary_path, root=remote_root, remote_host=remote_host, ssh_timeout=ssh_timeout
    ) if remote_root else {"scope": "remote", "path": summary_path, "exists": None, "remote_checked": False}
    remote_checked = bool(remote_root)

    local_ready = local_receipt.get("exists") is True and local_summary.get("exists") is True
    remote_ready = remote_receipt.get("exists") is True and remote_summary.get("exists") is True
    local_partial = local_receipt.get("exists") is True or local_summary.get("exists") is True
    remote_partial = remote_receipt.get("exists") is True or remote_summary.get("exists") is True

    if local_partial and not local_ready:
        _add_failure(failures, "local_receipt_partial", "local receipt/summary pair is incomplete")
    if remote_partial and not remote_ready:
        _add_failure(failures, "remote_receipt_partial", "remote receipt/summary pair is incomplete")
    if local_ready and remote_ready:
        if not _pair_ok(local_receipt, remote_receipt):
            _add_failure(failures, "receipt_digest_mismatch", "local and remote receipt digests differ")
        if not _pair_ok(local_summary, remote_summary):
            _add_failure(failures, "summary_digest_mismatch", "local and remote summary digests differ")
    if local_ready and remote_checked and not remote_ready:
        _add_failure(
            failures,
            "local_receipt_without_remote_receipt",
            "local receipt/summary exists but remote receipt/summary is absent",
        )

    can_sync_receipt = remote_ready and not local_ready and not failures
    can_run_job_state_probe = local_ready and not failures
    if failures:
        status = "receipt_monitor_blocked"
    elif can_run_job_state_probe:
        status = "local_receipt_ready_for_job_state_probe"
    elif can_sync_receipt:
        status = "remote_receipt_ready_for_monitor_sync"
    elif not local_partial and not remote_partial:
        status = "receipt_absent_not_submitted"
    else:
        status = "receipt_monitor_waiting"

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_panel_receipt_monitor",
        "status": status,
        "audit_ok": audit_ok,
        "no_submit": True,
        "submitted": bool(local_ready or remote_ready),
        "remote_checked": remote_checked,
        "receipt": receipt_path,
        "summary": summary_path,
        "local_receipt": local_receipt,
        "local_summary": local_summary,
        "remote_receipt": remote_receipt,
        "remote_summary": remote_summary,
        "local_receipt_ready": local_ready,
        "remote_receipt_ready": remote_ready,
        "can_sync_receipt": can_sync_receipt,
        "can_run_job_state_probe": can_run_job_state_probe,
        "sync_plan": sync_plan_path,
        "job_state_probe_command": (
            "python -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe"
        ),
        "failures": failures,
        "claim_boundary": "receipt monitor only; no records sync, no job submission, no W2 evidence",
        "next_action": (
            f"run receipt-only sync plan {sync_plan_path}, then run job-state probe"
            if can_sync_receipt else
            "run job-state probe, then query Slurm states and postsubmit status"
            if can_run_job_state_probe else
            "await explicit approval and guarded panel submission before receipt monitoring"
            if status == "receipt_absent_not_submitted" else
            "repair receipt monitor blockers before job-state monitoring or record sync-back"
        ),
    }


def render_sync_plan(*,
                     receipt_path: str = _DEFAULT_RECEIPT,
                     summary_path: str = _DEFAULT_SUMMARY,
                     remote_root: str = "",
                     local_root: str = "$(pwd)",
                     expected_workstream: str = _DEFAULT_EXPECTED_WORKSTREAM,
                     job_state_probe: str = _DEFAULT_JOB_STATE_PROBE,
                     job_state_probe_md: str = _DEFAULT_JOB_STATE_PROBE_MD,
                     job_state_query: str = _DEFAULT_JOB_STATE_QUERY,
                     sacct_states: str = _DEFAULT_SACCT_STATES) -> str:
    remote_line = (
        f"REMOTE_ROOT=\"${{CAYUGA_BIO_SFM_ROOT:-{remote_root}}}\""
        if remote_root else
        "REMOTE_ROOT=\"${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT to user@host:/path}\""
    )
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Pull only W2 v11 submit receipt/summary before record sync-back.",
        "# This is read-only with respect to Cayuga jobs and does not submit work.",
        "set -euo pipefail",
        remote_line,
        f"LOCAL_ROOT=\"${{LOCAL_BIO_SFM_ROOT:-{local_root}}}\"",
        "PYTHON_BIN=\"${BIO_SFM_PYTHON:-${ENV_PY:-python3}}\"",
        f"RECEIPT={receipt_path}",
        f"SUMMARY={summary_path}",
        f"EXPECTED_WORKSTREAM={shlex.quote(expected_workstream)}",
        f"JOB_STATE_PROBE={shlex.quote(job_state_probe)}",
        f"JOB_STATE_PROBE_MD={shlex.quote(job_state_probe_md)}",
        f"JOB_STATE_QUERY={shlex.quote(job_state_query)}",
        f"SACCT_STATES={shlex.quote(sacct_states)}",
        "mkdir -p \"$LOCAL_ROOT/results\"",
        "for relpath in \"$RECEIPT\" \"$SUMMARY\"; do",
        "  rsync -avP \"$REMOTE_ROOT/$relpath\" \"$LOCAL_ROOT/$relpath\"",
        "  test -s \"$LOCAL_ROOT/$relpath\"",
        "done",
        "cd \"$LOCAL_ROOT\"",
        'BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$LOCAL_ROOT/../bio-sfm-trust-core/src}"',
        'if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then',
        '  export PYTHONPATH="$LOCAL_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"',
        'else',
        '  export PYTHONPATH="$LOCAL_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
        'fi',
        (
            "PYTHONNOUSERSITE=1 \"$PYTHON_BIN\" -m "
            "bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe "
            "--receipt \"$RECEIPT\" --expected-workstream \"$EXPECTED_WORKSTREAM\" "
            "--sacct-output-path \"$SACCT_STATES\" --emit-query-plan \"$JOB_STATE_QUERY\" "
            "--out-json \"$JOB_STATE_PROBE\" --out-md \"$JOB_STATE_PROBE_MD\""
        ),
        "",
    ])


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Receipt Monitor",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        "",
        f"- local receipt ready: `{rep.get('local_receipt_ready')}`",
        f"- remote receipt ready: `{rep.get('remote_receipt_ready')}`",
        f"- can sync receipt: `{rep.get('can_sync_receipt')}`",
        f"- can run job-state probe: `{rep.get('can_run_job_state_probe')}`",
        f"- sync plan: `{rep.get('sync_plan')}`",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
        lines.append("")
    lines.extend([
        "## Claim Boundary",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "## Next Action",
        "",
        str(rep.get("next_action") or ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-root", default=".")
    ap.add_argument("--remote-host", default=os.environ.get("CAYUGA_BIO_SFM_HOST", ""))
    ap.add_argument("--remote-root", default=os.environ.get("CAYUGA_BIO_SFM_ROOT", ""))
    ap.add_argument("--receipt", default=_DEFAULT_RECEIPT)
    ap.add_argument("--summary", default=_DEFAULT_SUMMARY)
    ap.add_argument("--ssh-timeout", type=int, default=30)
    ap.add_argument("--emit-sync-plan", default=_DEFAULT_SYNC_PLAN)
    ap.add_argument("--expected-workstream", default=_DEFAULT_EXPECTED_WORKSTREAM)
    ap.add_argument("--job-state-probe", default=_DEFAULT_JOB_STATE_PROBE)
    ap.add_argument("--job-state-probe-md", default=_DEFAULT_JOB_STATE_PROBE_MD)
    ap.add_argument("--job-state-query", default=_DEFAULT_JOB_STATE_QUERY)
    ap.add_argument("--sacct-states", default=_DEFAULT_SACCT_STATES)
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    rep = build_monitor(
        local_root=args.local_root,
        remote_root=args.remote_root,
        remote_host=args.remote_host or None,
        receipt_path=args.receipt,
        summary_path=args.summary,
        sync_plan_path=args.emit_sync_plan,
        ssh_timeout=args.ssh_timeout,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.emit_sync_plan:
        _write_text(
            args.emit_sync_plan,
            render_sync_plan(
                receipt_path=args.receipt,
                summary_path=args.summary,
                remote_root=(
                    f"{args.remote_host}:{args.remote_root}"
                    if args.remote_host and args.remote_root else args.remote_root
                ),
                expected_workstream=args.expected_workstream,
                job_state_probe=args.job_state_probe,
                job_state_probe_md=args.job_state_probe_md,
                job_state_query=args.job_state_query,
                sacct_states=args.sacct_states,
            ),
            executable=True,
        )
    print(
        "status={status} audit_ok={ok} local_ready={local} remote_ready={remote} can_sync={sync}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            local=rep["local_receipt_ready"],
            remote=rep["remote_receipt_ready"],
            sync=rep["can_sync_receipt"],
        )
    )
    return 0 if rep.get("audit_ok") else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
