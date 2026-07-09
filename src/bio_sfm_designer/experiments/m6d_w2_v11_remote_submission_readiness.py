"""Audit W2 v11 Cayuga mirror readiness before any real panel submission.

This is a no-submit guardrail. It checks exact hashes for submit-critical
scripts/source/config files, compares semantic fields for generated JSONs that
may contain machine-specific paths, and verifies that submit receipts are still
absent locally and remotely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple


_DEFAULT_REMOTE_HOST = ""
_DEFAULT_REMOTE_ROOT = ""
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.md"

_EXACT_SHA_PATHS = [
    "configs/m6d_w2_target_family_redesign_v11_representative_targets.json",
    "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh",
    "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh",
    "results/m6d_w2_target_family_redesign_v11_job_state_query.sh",
    "results/m6d_w2_target_family_redesign_v11_sync_back.sh",
    "results/m6d_w2_target_family_redesign_v11_panel_completion.sh",
    "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh",
    "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh",
    "results/m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_guarded_preflight.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_receipt_monitor.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_job_state_probe.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_postsubmit_status.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_postsync_interpretation.py",
    "src/bio_sfm_designer/experiments/m6d_w2_panel_decision_protocol.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_submission_decision_state.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_approval_intent_audit.py",
    "src/bio_sfm_designer/experiments/m6d_w2_v11_remote_submission_readiness.py",
    "src/bio_sfm_designer/experiments/m6d_local_cayuga_mirror_audit.py",
    "src/bio_sfm_designer/experiments/complex_project_status.py",
    "src/bio_sfm_designer/experiments/complex_panel_completion.py",
    "src/bio_sfm_designer/experiments/complex_panel_report.py",
    "hpc/generate_proteinmpnn_complex.py",
    "hpc/predict_boltz_complex.py",
    "hpc/run_generate_proteinmpnn_complex.sbatch",
    "hpc/run_predict_boltz_complex.sbatch",
]

_SEMANTIC_JSON_FIELDS = {
    "results/m6d_w2_target_family_redesign_v11_panel_preflight.json": [
        "status",
        "audit_ok",
        "submit_ready.ok",
        "submit_ready.n_targets",
        "submit_ready.n_ready_targets",
        "panel_wrapper_guard.approval_env_var",
        "panel_wrapper_guard.approval_env_value",
        "panel_wrapper_guard.dry_run_env_var",
        "panel_wrapper_guard.no_env_non_dry_refuses_before_receipt",
    ],
    "results/m6d_w2_target_family_redesign_v11_panel_wrapper_guard_audit.json": [
        "status",
        "audit_ok",
        "panel_approval_env_var",
        "panel_approval_env_value",
        "static_audit.ok",
        "no_env_run.ok",
        "no_env_run.ran",
        "no_env_run.returncode",
        "no_env_run.receipt_exists_before",
        "no_env_run.receipt_exists_after",
        "no_env_run.refusal_message_seen",
    ],
    "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json": [
        "status",
        "audit_ok",
        "approval_packet_ready",
        "can_submit_panel_if_user_explicitly_approves",
        "can_claim_w2_generalization",
        "panel_approval_env_var",
        "panel_approval_env_value",
        "receipt_monitor_after_submit",
        "postsubmit_driver_after_submit",
        "postsubmit_driver_polling.max_polls_env_var",
        "postsubmit_driver_polling.default_max_polls",
        "postsubmit_driver_polling.poll_seconds_env_var",
        "postsubmit_driver_polling.default_poll_seconds",
        "postsubmit_driver_polling.proceeds_only_when_sync_ready",
        "postsubmit_driver_polling.sync_ready_gate",
        "job_state_query_after_receipt",
        "job_state_probe_sync_after_query",
        "postsubmit_status_before_sync",
        "job_state_probe_before_sync",
        "sacct_states_before_sync",
        "postsubmit_sync_ready_gate",
        "postsubmit_status_command_before_sync",
        "postsync_replay_after_sync",
        "checks.target_msa_strict_ready",
        "checks.panel_preflight_ready",
        "checks.panel_dry_run_no_sbatch",
        "checks.panel_guard_no_env_refuses",
        "checks.submit_receipt_absent",
        "checks.submit_summary_absent",
        "checks.approval_scope_ready",
        "approval_scope.n_ready_targets",
        "approval_scope.records_per_target_planned",
        "approval_scope.planned_design_records",
        "approval_scope.expected_job_pairs",
        "approval_scope.expected_slurm_jobs",
        "approval_scope.target_alpha",
    ],
    "results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json": [
        "status",
        "audit_ok",
        "no_submit",
        "can_submit_panel_if_user_explicitly_approves",
        "can_claim_w2_generalization_now",
        "claim_boundary.w2_multi_target_generalization",
        "panel_contract.panel_label",
        "current_panel_result.status",
        "current_panel_result.w2_generalization_supported",
    ],
    "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json": [
        "status",
        "audit_ok",
        "no_submit",
        "sync_ready",
        "can_claim_w2_generalization",
        "claim_boundary",
        "current_panel_result.status",
        "current_panel_result.w2_generalization_supported",
    ],
    "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.json": [
        "status",
        "audit_ok",
        "no_submit",
        "submitted",
        "can_claim_w2_generalization",
        "claim_boundary",
        "post_approval_workflow.script_chain_static_ok",
    ],
    "results/m6d_w2_target_family_redesign_v11_project_status.json": [
        "workstreams.W2_multi_target_panel.status",
        "workstreams.W2_multi_target_panel.complete",
        "workstreams.W2_multi_target_panel.panel_approval_packet_ready",
        "workstreams.W2_multi_target_panel.panel_decision_protocol_ready",
        "workstreams.W2_multi_target_panel.panel_decision_no_submit",
        "workstreams.W2_multi_target_panel.panel_decision_can_claim_w2_now",
    ],
}

_ABSENT_PATHS = [
    "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl",
    "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json",
]


def _default_shell_syntax_paths(paths: Iterable[str]) -> List[str]:
    return [path for path in paths if path.endswith((".sh", ".sbatch"))]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _field(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


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


def _remote_exists(remote_root: str, rel_path: str, *, remote_host: Optional[str], ssh_timeout: int) -> bool:
    if not remote_host:
        return os.path.exists(os.path.join(remote_root, rel_path))
    path = os.path.join(remote_root, rel_path)
    proc = _run_ssh(remote_host, "test -e " + shlex.quote(path), ssh_timeout)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())


def _bash_syntax_local(root: str, rel_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-n", os.path.join(root, rel_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _bash_syntax_remote(remote_root: str,
                        rel_path: str,
                        *,
                        remote_host: Optional[str],
                        ssh_timeout: int) -> subprocess.CompletedProcess:
    if not remote_host:
        return _bash_syntax_local(remote_root, rel_path)
    path = os.path.join(remote_root, rel_path)
    return _run_ssh(remote_host, "bash -n " + shlex.quote(path), ssh_timeout)


def _read_pair(
    local_root: str,
    remote_root: str,
    rel_path: str,
    *,
    remote_host: Optional[str],
    ssh_timeout: int,
) -> Tuple[Optional[bytes], Optional[bytes], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    local: Optional[bytes] = None
    remote: Optional[bytes] = None
    try:
        local = _read_local(local_root, rel_path)
    except Exception as exc:
        failures.append({"kind": "local_file_read_failed", "path": rel_path, "error": str(exc)})
    try:
        remote = _read_remote(remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout)
    except Exception as exc:
        failures.append({"kind": "remote_file_read_failed", "path": rel_path, "error": str(exc)})
    return local, remote, failures


def _parse_semantic_field_specs(items: Iterable[str]) -> Dict[str, List[str]]:
    specs: Dict[str, List[str]] = {}
    for item in items:
        if ":" not in item:
            raise ValueError(f"semantic field spec must be RELPATH:field, got {item!r}")
        path, field = item.split(":", 1)
        if not path or not field:
            raise ValueError(f"semantic field spec must be RELPATH:field, got {item!r}")
        specs.setdefault(path, []).append(field)
    return specs


def build_readiness(
    *,
    local_root: str,
    remote_root: str,
    remote_host: Optional[str],
    exact_sha_paths: Iterable[str] = _EXACT_SHA_PATHS,
    semantic_json_fields: Dict[str, List[str]] = _SEMANTIC_JSON_FIELDS,
    absent_paths: Iterable[str] = _ABSENT_PATHS,
    shell_syntax_paths: Optional[Iterable[str]] = None,
    ssh_timeout: int = 30,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    exact_checks: List[Dict[str, Any]] = []
    semantic_checks: List[Dict[str, Any]] = []
    absence_checks: List[Dict[str, Any]] = []
    shell_syntax_checks: List[Dict[str, Any]] = []
    exact_paths = list(exact_sha_paths)
    syntax_paths = list(shell_syntax_paths) if shell_syntax_paths is not None else _default_shell_syntax_paths(exact_paths)

    for rel_path in exact_paths:
        local, remote, read_failures = _read_pair(
            local_root, remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout
        )
        failures.extend(read_failures)
        row: Dict[str, Any] = {"path": rel_path, "ok": False}
        if local is not None:
            row["local_sha256"] = _sha256(local)
            row["local_bytes"] = len(local)
        if remote is not None:
            row["remote_sha256"] = _sha256(remote)
            row["remote_bytes"] = len(remote)
        if local is not None and remote is not None:
            row["ok"] = (
                row["local_sha256"] == row["remote_sha256"]
                and row["local_bytes"] > 0
                and row["remote_bytes"] > 0
            )
            if row["local_bytes"] == 0 or row["remote_bytes"] == 0:
                failures.append({
                    "kind": "exact_file_empty",
                    "path": rel_path,
                    "local_bytes": row["local_bytes"],
                    "remote_bytes": row["remote_bytes"],
                })
            elif row["local_sha256"] != row["remote_sha256"]:
                failures.append({
                    "kind": "exact_sha_mismatch",
                    "path": rel_path,
                    "local_sha256": row["local_sha256"],
                    "remote_sha256": row["remote_sha256"],
                })
        exact_checks.append(row)

    for rel_path, fields in semantic_json_fields.items():
        local, remote, read_failures = _read_pair(
            local_root, remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout
        )
        failures.extend(read_failures)
        row: Dict[str, Any] = {"path": rel_path, "ok": False, "fields": []}
        if local is None or remote is None:
            semantic_checks.append(row)
            continue
        try:
            local_obj = json.loads(local.decode("utf-8"))
            remote_obj = json.loads(remote.decode("utf-8"))
        except Exception as exc:
            failures.append({"kind": "json_parse_failed", "path": rel_path, "error": str(exc)})
            semantic_checks.append(row)
            continue
        field_failures = []
        for field in fields:
            local_value = _field(local_obj, field)
            remote_value = _field(remote_obj, field)
            ok = local_value == remote_value
            row["fields"].append({
                "field": field,
                "ok": ok,
                "local": local_value,
                "remote": remote_value,
            })
            if not ok:
                field_failures.append({
                    "kind": "semantic_field_mismatch",
                    "path": rel_path,
                    "field": field,
                    "local": local_value,
                    "remote": remote_value,
                })
        row["ok"] = not field_failures
        failures.extend(field_failures)
        semantic_checks.append(row)

    for rel_path in absent_paths:
        local_exists = os.path.exists(os.path.join(local_root, rel_path))
        row: Dict[str, Any] = {"path": rel_path, "ok": False, "local_exists": local_exists}
        try:
            remote_exists = _remote_exists(remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout)
            row["remote_exists"] = remote_exists
        except Exception as exc:
            row["remote_exists"] = None
            failures.append({"kind": "remote_absence_check_failed", "path": rel_path, "error": str(exc)})
            absence_checks.append(row)
            continue
        row["ok"] = not local_exists and not row["remote_exists"]
        if not row["ok"]:
            failures.append({
                "kind": "submit_receipt_or_summary_present",
                "path": rel_path,
                "local_exists": local_exists,
                "remote_exists": row["remote_exists"],
            })
        absence_checks.append(row)

    for rel_path in syntax_paths:
        row: Dict[str, Any] = {"path": rel_path, "ok": False}
        try:
            local_proc = _bash_syntax_local(local_root, rel_path)
            row["local_returncode"] = local_proc.returncode
            row["local_stderr_tail"] = local_proc.stderr.decode("utf-8", errors="replace")[-1000:]
        except Exception as exc:
            row["local_returncode"] = None
            row["local_stderr_tail"] = str(exc)[-1000:]
        try:
            remote_proc = _bash_syntax_remote(
                remote_root, rel_path, remote_host=remote_host, ssh_timeout=ssh_timeout
            )
            row["remote_returncode"] = remote_proc.returncode
            row["remote_stderr_tail"] = remote_proc.stderr.decode("utf-8", errors="replace")[-1000:]
        except Exception as exc:
            row["remote_returncode"] = None
            row["remote_stderr_tail"] = str(exc)[-1000:]
        row["ok"] = row.get("local_returncode") == 0 and row.get("remote_returncode") == 0
        if row.get("local_returncode") != 0:
            failures.append({
                "kind": "local_shell_syntax_failed",
                "path": rel_path,
                "returncode": row.get("local_returncode"),
                "stderr_tail": row.get("local_stderr_tail"),
            })
        if row.get("remote_returncode") != 0:
            failures.append({
                "kind": "remote_shell_syntax_failed",
                "path": rel_path,
                "returncode": row.get("remote_returncode"),
                "stderr_tail": row.get("remote_stderr_tail"),
            })
        shell_syntax_checks.append(row)

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_v11_remote_submission_readiness",
        "status": "remote_submission_readiness_ok" if audit_ok else "remote_submission_readiness_blocked",
        "audit_ok": audit_ok,
        "no_submit": True,
        "can_submit_panel_if_user_explicitly_approves": audit_ok,
        "can_claim_w2_generalization": False,
        "local_root": os.path.abspath(local_root),
        "remote_host": remote_host or "",
        "remote_root": remote_root,
        "exact_checks": exact_checks,
        "semantic_checks": semantic_checks,
        "absence_checks": absence_checks,
        "shell_syntax_checks": shell_syntax_checks,
        "n_exact_checks": len(exact_checks),
        "n_semantic_checks": len(semantic_checks),
        "n_absence_checks": len(absence_checks),
        "n_shell_syntax_checks": len(shell_syntax_checks),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "no-submit remote readiness audit; it only supports the execution decision boundary, "
            "not W2 generalization evidence"
        ),
        "next_action": (
            "remote mirror is ready; still wait for explicit user approval before guarded W2 v11 panel submission"
            if audit_ok else
            "repair remote readiness failures before any explicit-approval panel submission"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 v11 Remote Submission Readiness",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Can submit panel if explicitly approved: `{rep.get('can_submit_panel_if_user_explicitly_approves')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        f"Remote: `{rep.get('remote_host')}:{rep.get('remote_root')}`.",
        "",
        "| check type | count |",
        "|---|---:|",
        f"| exact SHA checks | {rep.get('n_exact_checks')} |",
        f"| semantic JSON checks | {rep.get('n_semantic_checks')} |",
        f"| receipt absence checks | {rep.get('n_absence_checks')} |",
        f"| shell syntax checks | {rep.get('n_shell_syntax_checks')} |",
        f"| failures | {rep.get('n_failures')} |",
        "",
        "Claim boundary: this audit does not submit jobs and does not create W2 panel evidence.",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            detail = failure.get("field") or failure.get("error") or ""
            lines.append(f"- `{failure.get('kind')}` `{failure.get('path')}` {detail}")
        lines.append("")
    lines.extend(["## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-root", default=".")
    ap.add_argument("--remote-host", default=os.environ.get("CAYUGA_BIO_SFM_HOST", _DEFAULT_REMOTE_HOST))
    ap.add_argument("--remote-root", default=os.environ.get("CAYUGA_BIO_SFM_ROOT", _DEFAULT_REMOTE_ROOT))
    ap.add_argument("--exact-path", action="append", default=None)
    ap.add_argument("--semantic-field", action="append", default=None, help="Repeat RELPATH:field")
    ap.add_argument("--absent-path", action="append", default=None)
    ap.add_argument("--shell-syntax-path", action="append", default=None)
    ap.add_argument("--ssh-timeout", type=int, default=30)
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)
    if not args.remote_root:
        ap.error("--remote-root or CAYUGA_BIO_SFM_ROOT is required for remote readiness checks")

    semantic_specs = (
        _parse_semantic_field_specs(args.semantic_field)
        if args.semantic_field is not None else
        _SEMANTIC_JSON_FIELDS
    )
    rep = build_readiness(
        local_root=args.local_root,
        remote_root=args.remote_root,
        remote_host=args.remote_host or None,
        exact_sha_paths=args.exact_path if args.exact_path is not None else _EXACT_SHA_PATHS,
        semantic_json_fields=semantic_specs,
        absent_paths=args.absent_path if args.absent_path is not None else _ABSENT_PATHS,
        shell_syntax_paths=args.shell_syntax_path,
        ssh_timeout=args.ssh_timeout,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} exact={exact} semantic={semantic} absent={absent} syntax={syntax} failures={failures}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            exact=rep["n_exact_checks"],
            semantic=rep["n_semantic_checks"],
            absent=rep["n_absence_checks"],
            syntax=rep["n_shell_syntax_checks"],
            failures=rep["n_failures"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
