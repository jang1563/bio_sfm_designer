"""Build a no-submit W2 v9 panel approval packet.

The packet fixes the exact guarded command for a future human-approved
ProteinMPNN/Boltz panel submission. It never submits jobs and never turns panel
readiness into W2 generalization evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


_EXECUTION_SYNCED_STATUS = "target_msa_outputs_synced_strict_require_files_passed"
_PANEL_PREFLIGHT_STATUS = "panel_preflight_dry_run_passed_not_submitted"
_WRAPPER_GUARD_STATUS = "panel_wrapper_guard_ok"
_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_PANEL"
_APPROVAL_TOKEN = "approve-v9-panel-submit"


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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def build_packet(
    execution_attempt: Dict[str, Any],
    panel_preflight: Dict[str, Any],
    wrapper_guard: Dict[str, Any],
    *,
    submit_receipt: str,
    submit_summary: str,
    remote_host: str,
    remote_root: str,
    local_python: str,
    cayuga_python: str,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    sync_back = execution_attempt.get("sync_back") if isinstance(execution_attempt.get("sync_back"), dict) else {}
    preflight_ready = (
        panel_preflight.get("submit_ready")
        if isinstance(panel_preflight.get("submit_ready"), dict)
        else {}
    )
    dry_run = panel_preflight.get("dry_run") if isinstance(panel_preflight.get("dry_run"), dict) else {}
    static_audit = wrapper_guard.get("static_audit") if isinstance(wrapper_guard.get("static_audit"), dict) else {}
    no_env = wrapper_guard.get("no_env_run") if isinstance(wrapper_guard.get("no_env_run"), dict) else {}

    if execution_attempt.get("status") != _EXECUTION_SYNCED_STATUS:
        _add_failure(
            failures,
            "target_msa_execution_not_synced",
            "target-MSA execution must be synced with strict require-files passing before panel approval",
            observed=execution_attempt.get("status"),
        )
    if sync_back.get("completed") is not True or sync_back.get("strict_require_files_ok") is not True:
        _add_failure(
            failures,
            "target_msa_sync_back_not_strict",
            "target-MSA sync-back and strict require-files must pass before panel approval",
            observed=sync_back,
        )
    if sync_back.get("ready_targets") != 14 or sync_back.get("post_sync_pending_path_count") != 0:
        _add_failure(
            failures,
            "target_msa_ready_count_mismatch",
            "panel approval requires 14 ready targets and zero pending post-sync paths",
            observed={
                "ready_targets": sync_back.get("ready_targets"),
                "post_sync_pending_path_count": sync_back.get("post_sync_pending_path_count"),
            },
        )

    if panel_preflight.get("status") != _PANEL_PREFLIGHT_STATUS:
        _add_failure(
            failures,
            "panel_preflight_status_not_ready",
            "panel preflight must be dry-run ready and not submitted",
            observed=panel_preflight.get("status"),
        )
    if preflight_ready.get("ok") is not True or preflight_ready.get("n_ready_targets") != 14:
        _add_failure(
            failures,
            "panel_submit_ready_not_ok",
            "panel submit-ready report must pass with 14 ready targets",
            observed=preflight_ready,
        )
    if dry_run.get("exit_code") != 0 or dry_run.get("sbatch_called") is not False:
        _add_failure(
            failures,
            "panel_dry_run_not_clean",
            "panel wrapper dry-run must pass without sbatch calls",
            observed=dry_run,
        )
    if dry_run.get("receipt_exists_after") is not False or dry_run.get("summary_exists_after") is not False:
        _add_failure(
            failures,
            "panel_dry_run_touched_receipt",
            "panel wrapper dry-run must leave submit receipt and summary absent",
            observed=dry_run,
        )

    if wrapper_guard.get("audit_ok") is not True or wrapper_guard.get("status") != _WRAPPER_GUARD_STATUS:
        _add_failure(
            failures,
            "panel_wrapper_guard_not_ok",
            "panel wrapper guard audit must pass before panel approval",
            observed={"audit_ok": wrapper_guard.get("audit_ok"), "status": wrapper_guard.get("status")},
        )
    if wrapper_guard.get("panel_approval_env_var") != _APPROVAL_ENV_VAR:
        _add_failure(
            failures,
            "panel_approval_env_var_mismatch",
            "panel approval env var mismatch",
            expected=_APPROVAL_ENV_VAR,
            observed=wrapper_guard.get("panel_approval_env_var"),
        )
    if wrapper_guard.get("panel_approval_env_value") != _APPROVAL_TOKEN:
        _add_failure(
            failures,
            "panel_approval_token_mismatch",
            "panel approval token mismatch",
            expected=_APPROVAL_TOKEN,
            observed=wrapper_guard.get("panel_approval_env_value"),
        )
    if static_audit.get("ok") is not True or static_audit.get("approval_guard_before_shared_submit_wrapper") is not True:
        _add_failure(
            failures,
            "panel_wrapper_static_guard_not_ok",
            "panel wrapper approval guard must run before the shared submit wrapper",
            observed=static_audit,
        )
    if no_env.get("ok") is not True or no_env.get("receipt_exists_after") is not False:
        _add_failure(
            failures,
            "panel_wrapper_no_env_guard_not_ok",
            "panel wrapper no-env run must refuse before receipt creation",
            observed=no_env,
        )
    if os.path.exists(submit_receipt) or os.path.exists(submit_summary):
        _add_failure(
            failures,
            "panel_submit_receipt_already_exists",
            "panel submit receipt/summary must be absent before first approved submission",
            observed={
                "receipt_exists": os.path.exists(submit_receipt),
                "summary_exists": os.path.exists(submit_summary),
            },
        )

    remote_command = (
        "ssh "
        + remote_host
        + " "
        + repr(
            "cd "
            + remote_root
            + " && BIO_SFM_PYTHON="
            + cayuga_python
            + " PYTHONNOUSERSITE=1 "
            + _APPROVAL_ENV_VAR
            + "="
            + _APPROVAL_TOKEN
            + " bash results/m6d_w2_target_family_redesign_v9_submit_with_receipt.sh"
        )
    )
    dry_run_command = (
        "M6D_W2_V9_SUBMIT_DRY_RUN=1 BIO_SFM_PYTHON="
        + local_python
        + " PYTHONNOUSERSITE=1 bash results/m6d_w2_target_family_redesign_v9_submit_with_receipt.sh"
    )
    sync_back_command = (
        "CAYUGA_BIO_SFM_ROOT="
        + remote_host
        + ":"
        + remote_root
        + " BIO_SFM_PYTHON="
        + local_python
        + " PYTHONPATH=src:../bio-sfm-trust-core/src bash "
        + "results/m6d_w2_target_family_redesign_v9_sync_back.sh"
    )

    packet_ready = not failures
    return {
        "artifact": "m6d_w2_panel_approval_packet",
        "status": "panel_approval_packet_ready" if packet_ready else "panel_approval_packet_blocked",
        "audit_ok": packet_ready,
        "approval_packet_ready": packet_ready,
        "can_submit_panel_if_user_explicitly_approves": packet_ready,
        "can_claim_w2_generalization": False,
        "panel_approval_env_var": _APPROVAL_ENV_VAR,
        "panel_approval_env_value": _APPROVAL_TOKEN,
        "inputs": {
            "execution_attempt": execution_attempt.get("_path"),
            "panel_preflight": panel_preflight.get("_path"),
            "wrapper_guard": wrapper_guard.get("_path"),
        },
        "submit_receipt": submit_receipt,
        "submit_summary": submit_summary,
        "submit_command_if_approved": remote_command,
        "dry_run_command": dry_run_command,
        "sync_back_command_after_jobs_finish": sync_back_command,
        "claim_boundary": {
            "panel_submission": "allowed only after explicit approval env is supplied",
            "w2_multi_target_generalization": "not_supported",
            "evidence_status": "not W2 evidence until records sync back, completion passes, and target-wise panel report certifies",
        },
        "checks": {
            "target_msa_strict_ready": (
                execution_attempt.get("status") == _EXECUTION_SYNCED_STATUS
                and sync_back.get("completed") is True
                and sync_back.get("strict_require_files_ok") is True
                and sync_back.get("ready_targets") == 14
                and sync_back.get("post_sync_pending_path_count") == 0
            ),
            "panel_preflight_ready": panel_preflight.get("status") == _PANEL_PREFLIGHT_STATUS,
            "panel_submit_ready_targets": preflight_ready.get("n_ready_targets"),
            "panel_dry_run_no_sbatch": dry_run.get("sbatch_called") is False,
            "panel_guard_no_env_refuses": no_env.get("ok") is True,
            "submit_receipt_absent": not os.path.exists(submit_receipt),
            "submit_summary_absent": not os.path.exists(submit_summary),
        },
        "failures": failures,
        "next_action": (
            "wait for explicit user approval before running submit_command_if_approved"
            if packet_ready else
            "repair packet failures before any W2 v9 panel submission"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
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
        "Dry-run command:",
        "",
        "```bash",
        str(rep.get("dry_run_command") or ""),
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execution-attempt", default="results/m6d_w2_target_family_redesign_v9_full14_target_msa_execution_attempt.json")
    ap.add_argument("--panel-preflight", default="results/m6d_w2_target_family_redesign_v9_panel_preflight.json")
    ap.add_argument("--wrapper-guard", default="results/m6d_w2_target_family_redesign_v9_panel_wrapper_guard_audit.json")
    ap.add_argument("--submit-receipt", default="results/m6d_w2_target_family_redesign_v9_submit_receipt.jsonl")
    ap.add_argument("--submit-summary", default="results/m6d_w2_target_family_redesign_v9_submit_receipt_summary.json")
    ap.add_argument("--remote-host", default="${CAYUGA_BIO_SFM_HOST}")
    ap.add_argument("--remote-root", default="${CAYUGA_BIO_SFM_ROOT_REMOTE}")
    ap.add_argument("--local-python", default="/tmp/bio_sfm_science_venv/bin/python")
    ap.add_argument("--cayuga-python", default="$HOME/.conda/envs/boltz/bin/python")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_panel_approval_packet.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_panel_approval_packet.md")
    args = ap.parse_args(argv)

    rep = build_packet(
        _load_json(args.execution_attempt),
        _load_json(args.panel_preflight),
        _load_json(args.wrapper_guard),
        submit_receipt=args.submit_receipt,
        submit_summary=args.submit_summary,
        remote_host=args.remote_host,
        remote_root=args.remote_root,
        local_python=args.local_python,
        cayuga_python=args.cayuga_python,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"# panel approval packet  ok={rep['audit_ok']} status={rep['status']}")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
