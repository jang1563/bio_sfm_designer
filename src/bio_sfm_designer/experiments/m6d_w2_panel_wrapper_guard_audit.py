"""Audit a W2 panel submit wrapper approval guard without submitting jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from typing import Any, Dict, List, Optional


_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_PANEL"
_APPROVAL_TOKEN = "approve-v9-panel-submit"
_DRY_RUN_ENV_VAR = "M6D_W2_V9_SUBMIT_DRY_RUN"
_REFUSAL = "refusing v9 panel submission without explicit approval env"
_SHARED_WRAPPER_MARKER = 'm6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh"'


def _read_text(path: str) -> str:
    with open(path) as fh:
        return fh.read()


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
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _index(text: str, marker: str) -> Optional[int]:
    idx = text.find(marker)
    return idx if idx >= 0 else None


def _last_index(text: str, marker: str) -> Optional[int]:
    idx = text.rfind(marker)
    return idx if idx >= 0 else None


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def _static_audit(
    wrapper_path: str,
    receipt_path: str,
    text: str,
    *,
    approval_env_var: str = _APPROVAL_ENV_VAR,
    approval_token: str = _APPROVAL_TOKEN,
    dry_run_env_var: str = _DRY_RUN_ENV_VAR,
    refusal_message: str = _REFUSAL,
    shared_wrapper_marker: str = _SHARED_WRAPPER_MARKER,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    markers = {
        "approval_env_var": approval_env_var,
        "approval_token": approval_token,
        "dry_run_env_var": dry_run_env_var,
        "bio_sfm_submit_dry_run_export": "export BIO_SFM_SUBMIT_DRY_RUN=",
        "dry_run_guard": 'if [ "${BIO_SFM_SUBMIT_DRY_RUN:-0}" = "1" ]; then',
        "approval_guard": f'if [ "${{{approval_env_var}:-}}" != "$APPROVAL_TOKEN" ]; then',
        "refusal_message": refusal_message,
        "refusal_exit": "exit 2",
        "shared_wrapper_exec": shared_wrapper_marker,
        "receipt_assignment": f'export SUBMIT_RECEIPT="${{SUBMIT_RECEIPT:-{receipt_path}}}"',
    }
    positions = {name: _index(text, marker) for name, marker in markers.items()}
    positions["final_shared_wrapper_exec"] = _last_index(text, markers["shared_wrapper_exec"])
    for name, pos in positions.items():
        if pos is None:
            _add_failure(
                failures,
                "wrapper_missing_marker",
                "panel wrapper is missing a required approval/receipt guard marker",
                marker=name,
                expected=markers[name],
            )

    dry = positions.get("dry_run_guard")
    guard = positions.get("approval_guard")
    refusal = positions.get("refusal_message")
    refusal_exit = positions.get("refusal_exit")
    shared_exec = positions.get("final_shared_wrapper_exec")
    if dry is not None and guard is not None and not dry < guard:
        _add_failure(
            failures,
            "dry_run_not_before_approval_guard",
            "dry-run branch must be checked before the real-run approval guard",
        )
    if guard is not None and shared_exec is not None and not guard < shared_exec:
        _add_failure(
            failures,
            "approval_guard_not_before_shared_submit_wrapper",
            "approval guard must run before delegating to the shared submit wrapper",
        )
    if refusal is not None and shared_exec is not None and not refusal < shared_exec:
        _add_failure(
            failures,
            "refusal_message_not_before_shared_submit_wrapper",
            "approval refusal must appear before the shared submit wrapper",
        )
    if refusal_exit is not None and shared_exec is not None and not refusal_exit < shared_exec:
        _add_failure(
            failures,
            "refusal_exit_not_before_shared_submit_wrapper",
            "approval refusal exit must appear before the shared submit wrapper",
        )
    if "sbatch" in text:
        _add_failure(
            failures,
            "wrapper_contains_sbatch",
            "panel wrapper must delegate to the shared wrapper and must not call sbatch directly",
        )

    return {
        "ok": not failures,
        "wrapper": wrapper_path,
        "wrapper_sha256": _sha256_file(wrapper_path),
        "receipt": receipt_path,
        "positions": positions,
        "dry_run_before_approval_guard": dry is not None and guard is not None and dry < guard,
        "approval_guard_before_shared_submit_wrapper": (
            guard is not None and shared_exec is not None and guard < shared_exec
        ),
        "failures": failures,
    }


def _run_no_env_check(
    wrapper_path: str,
    receipt_path: str,
    *,
    static_ok: bool,
    approval_env_var: str = _APPROVAL_ENV_VAR,
    dry_run_env_var: str = _DRY_RUN_ENV_VAR,
    refusal_message: str = _REFUSAL,
) -> Dict[str, Any]:
    if not static_ok:
        return {
            "ran": False,
            "ok": False,
            "reason": "static_audit_failed",
            "receipt": receipt_path,
        }
    receipt_existed_before = os.path.exists(receipt_path)
    if receipt_existed_before:
        return {
            "ran": False,
            "ok": False,
            "reason": "receipt_exists_before_no_env_check",
            "receipt_exists_before": True,
            "receipt": receipt_path,
        }

    env = os.environ.copy()
    env.pop(approval_env_var, None)
    env.pop(dry_run_env_var, None)
    env["BIO_SFM_SUBMIT_DRY_RUN"] = "0"
    proc = subprocess.run(["bash", wrapper_path], text=True, capture_output=True, env=env)
    receipt_exists_after = os.path.exists(receipt_path)
    stderr = proc.stderr[-2000:]
    stdout = proc.stdout[-2000:]
    ok = proc.returncode == 2 and refusal_message in proc.stderr and not receipt_exists_after
    return {
        "ran": True,
        "ok": ok,
        "returncode": proc.returncode,
        "stderr_tail": stderr,
        "stdout_tail": stdout,
        "refusal_message_seen": refusal_message in proc.stderr,
        "receipt_exists_before": receipt_existed_before,
        "receipt_exists_after": receipt_exists_after,
        "receipt": receipt_path,
    }


def build_audit(
    wrapper_path: str,
    receipt_path: str,
    *,
    run_no_env_check: bool = False,
    approval_env_var: str = _APPROVAL_ENV_VAR,
    approval_token: str = _APPROVAL_TOKEN,
    dry_run_env_var: str = _DRY_RUN_ENV_VAR,
    refusal_message: str = _REFUSAL,
    shared_wrapper_marker: str = _SHARED_WRAPPER_MARKER,
    panel_label: str = "W2 panel",
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    text = ""
    if not os.path.exists(wrapper_path):
        _add_failure(failures, "wrapper_missing", "panel wrapper does not exist", path=wrapper_path)
    else:
        text = _read_text(wrapper_path)
        if not text.strip():
            _add_failure(failures, "wrapper_empty", "panel wrapper is empty", path=wrapper_path)

    static = _static_audit(
        wrapper_path,
        receipt_path,
        text,
        approval_env_var=approval_env_var,
        approval_token=approval_token,
        dry_run_env_var=dry_run_env_var,
        refusal_message=refusal_message,
        shared_wrapper_marker=shared_wrapper_marker,
    ) if text else {
        "ok": False,
        "wrapper": wrapper_path,
        "wrapper_sha256": None,
        "receipt": receipt_path,
        "positions": {},
        "dry_run_before_approval_guard": False,
        "approval_guard_before_shared_submit_wrapper": False,
        "failures": [],
    }
    failures.extend(static.get("failures", []))
    no_env = (
        _run_no_env_check(
            wrapper_path,
            receipt_path,
            static_ok=not failures,
            approval_env_var=approval_env_var,
            dry_run_env_var=dry_run_env_var,
            refusal_message=refusal_message,
        )
        if run_no_env_check else
        {"ran": False, "ok": None, "reason": "not_requested", "receipt": receipt_path}
    )
    if run_no_env_check and no_env.get("ok") is not True:
        _add_failure(
            failures,
            "no_env_runtime_guard_failed",
            "panel wrapper no-env execution must exit before receipt creation",
            observed=no_env,
        )

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_panel_wrapper_guard_audit",
        "status": "panel_wrapper_guard_ok" if audit_ok else "panel_wrapper_guard_failed",
        "audit_ok": audit_ok,
        "claim_boundary": "no-submit panel wrapper guard audit only; does not approve or run ProteinMPNN/Boltz jobs",
        "wrapper": wrapper_path,
        "receipt": receipt_path,
        "panel_label": panel_label,
        "panel_approval_env_var": approval_env_var,
        "panel_approval_env_value": approval_token,
        "dry_run_env_var": dry_run_env_var,
        "refusal_message": refusal_message,
        "shared_wrapper_marker": shared_wrapper_marker,
        "static_audit": static,
        "no_env_run": no_env,
        "failures": failures,
        "next_action": (
            f"wait for explicit approval before {panel_label} submission"
            if audit_ok else
            "repair the panel wrapper guard before approval or submission"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    static = rep.get("static_audit") if isinstance(rep.get("static_audit"), dict) else {}
    no_env = rep.get("no_env_run") if isinstance(rep.get("no_env_run"), dict) else {}
    lines = [
        "# M6d W2 Panel Wrapper Guard Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| static audit ok | {static.get('ok')} |",
        f"| no-env run checked | {no_env.get('ran')} |",
        f"| no-env run ok | {no_env.get('ok')} |",
        f"| no-env return code | {no_env.get('returncode')} |",
        f"| receipt exists after no-env run | {no_env.get('receipt_exists_after')} |",
        "",
        "Required approval environment:",
        "",
        "```bash",
        f"export {rep.get('panel_approval_env_var')}={rep.get('panel_approval_env_value')}",
        "```",
        "",
        "Dry-run remains available with:",
        "",
        "```bash",
        f"export {rep.get('dry_run_env_var')}=1",
        "```",
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
    ap.add_argument("--wrapper", default="results/m6d_w2_target_family_redesign_v9_submit_with_receipt.sh")
    ap.add_argument("--receipt", default="results/m6d_w2_target_family_redesign_v9_submit_receipt.jsonl")
    ap.add_argument("--approval-env-var", default=_APPROVAL_ENV_VAR)
    ap.add_argument("--approval-token", default=_APPROVAL_TOKEN)
    ap.add_argument("--dry-run-env-var", default=_DRY_RUN_ENV_VAR)
    ap.add_argument("--refusal-message", default=_REFUSAL)
    ap.add_argument("--shared-wrapper-marker", default=_SHARED_WRAPPER_MARKER)
    ap.add_argument("--panel-label", default="W2 panel")
    ap.add_argument("--run-no-env-check", action="store_true")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_panel_wrapper_guard_audit.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_panel_wrapper_guard_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(
        args.wrapper,
        args.receipt,
        run_no_env_check=args.run_no_env_check,
        approval_env_var=args.approval_env_var,
        approval_token=args.approval_token,
        dry_run_env_var=args.dry_run_env_var,
        refusal_message=args.refusal_message,
        shared_wrapper_marker=args.shared_wrapper_marker,
        panel_label=args.panel_label,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"# panel wrapper guard audit  ok={rep['audit_ok']} status={rep['status']}")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
