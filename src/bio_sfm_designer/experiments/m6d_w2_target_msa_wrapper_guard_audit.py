"""Audit the W2 v9 target-MSA wrapper approval guard without submitting jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from typing import Any, Dict, List, Optional


_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_TARGET_MSA"
_APPROVAL_TOKEN = "approve-v9-target-msa-precompute"
_REFUSAL = "refusing v9 target-MSA submission without explicit approval env"


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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def _static_audit(wrapper_path: str, receipt_path: str, text: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    markers = {
        "approval_env_var": _APPROVAL_ENV_VAR,
        "approval_token": _APPROVAL_TOKEN,
        "dry_run_guard": "TARGET_MSA_PRECOMPUTE_DRY_RUN",
        "approval_guard": f'if [ "${{{_APPROVAL_ENV_VAR}:-}}" != "$APPROVAL_TOKEN" ]; then',
        "refusal_message": _REFUSAL,
        "refusal_exit": "exit 2",
        "receipt_mkdir": 'mkdir -p "$(dirname "$RECEIPT")"',
        "receipt_truncate": ': > "$RECEIPT"',
        "receipt_assignment": f'RECEIPT="{receipt_path}"',
    }
    positions = {name: _index(text, marker) for name, marker in markers.items()}
    for name, pos in positions.items():
        if pos is None:
            _add_failure(
                failures,
                "wrapper_missing_marker",
                "target-MSA wrapper is missing a required approval/receipt guard marker",
                marker=name,
                expected=markers[name],
            )

    dry = positions.get("dry_run_guard")
    guard = positions.get("approval_guard")
    mkdir = positions.get("receipt_mkdir")
    truncate = positions.get("receipt_truncate")
    refusal = positions.get("refusal_message")
    refusal_exit = positions.get("refusal_exit")
    if dry is not None and guard is not None and not dry < guard:
        _add_failure(failures, "dry_run_not_before_approval_guard",
                     "dry-run branch must be checked before the real-run approval guard")
    if guard is not None and mkdir is not None and not guard < mkdir:
        _add_failure(failures, "approval_guard_not_before_receipt_mkdir",
                     "approval guard must run before receipt directory creation")
    if guard is not None and truncate is not None and not guard < truncate:
        _add_failure(failures, "approval_guard_not_before_receipt_truncate",
                     "approval guard must run before receipt truncation")
    if refusal is not None and truncate is not None and not refusal < truncate:
        _add_failure(failures, "refusal_message_not_before_receipt_truncate",
                     "approval refusal must appear before receipt truncation")
    if refusal_exit is not None and truncate is not None and not refusal_exit < truncate:
        _add_failure(failures, "refusal_exit_not_before_receipt_truncate",
                     "approval refusal exit must appear before receipt truncation")
    if "sbatch" in text:
        _add_failure(failures, "wrapper_contains_sbatch",
                     "target-MSA wrapper must delegate to the plan and must not call sbatch directly")

    return {
        "ok": not failures,
        "wrapper": wrapper_path,
        "wrapper_sha256": _sha256_file(wrapper_path),
        "receipt": receipt_path,
        "positions": positions,
        "receipt_truncate_after_approval_guard": (
            guard is not None and truncate is not None and guard < truncate
        ),
        "dry_run_before_approval_guard": (
            dry is not None and guard is not None and dry < guard
        ),
        "failures": failures,
    }


def _run_no_env_check(wrapper_path: str, receipt_path: str, *, static_ok: bool) -> Dict[str, Any]:
    if not static_ok:
        return {
            "ran": False,
            "ok": False,
            "reason": "static_audit_failed",
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
    env.pop(_APPROVAL_ENV_VAR, None)
    env.pop("TARGET_MSA_PRECOMPUTE_DRY_RUN", None)
    proc = subprocess.run(
        ["bash", wrapper_path],
        text=True,
        capture_output=True,
        env=env,
    )
    receipt_exists_after = os.path.exists(receipt_path)
    stderr = proc.stderr[-2000:]
    stdout = proc.stdout[-2000:]
    ok = proc.returncode == 2 and _REFUSAL in proc.stderr and not receipt_exists_after
    return {
        "ran": True,
        "ok": ok,
        "returncode": proc.returncode,
        "stderr_tail": stderr,
        "stdout_tail": stdout,
        "refusal_message_seen": _REFUSAL in proc.stderr,
        "receipt_exists_before": receipt_existed_before,
        "receipt_exists_after": receipt_exists_after,
        "receipt": receipt_path,
    }


def build_audit(wrapper_path: str,
                receipt_path: str,
                *,
                run_no_env_check: bool = False) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    text = ""
    if not os.path.exists(wrapper_path):
        _add_failure(failures, "wrapper_missing", "target-MSA wrapper does not exist", path=wrapper_path)
    else:
        text = _read_text(wrapper_path)
        if not text.strip():
            _add_failure(failures, "wrapper_empty", "target-MSA wrapper is empty", path=wrapper_path)
    static = _static_audit(wrapper_path, receipt_path, text) if text else {
        "ok": False,
        "wrapper": wrapper_path,
        "wrapper_sha256": None,
        "receipt": receipt_path,
        "positions": {},
        "receipt_truncate_after_approval_guard": False,
        "dry_run_before_approval_guard": False,
        "failures": [],
    }
    failures.extend(static.get("failures", []))
    no_env = (
        _run_no_env_check(wrapper_path, receipt_path, static_ok=not failures)
        if run_no_env_check else
        {"ran": False, "ok": None, "reason": "not_requested", "receipt": receipt_path}
    )
    if run_no_env_check and no_env.get("ok") is not True:
        _add_failure(failures, "no_env_runtime_guard_failed",
                     "wrapper no-env execution must exit before receipt creation",
                     observed=no_env)
    audit_ok = not failures
    return {
        "artifact": "m6d_w2_target_msa_wrapper_guard_audit",
        "status": "wrapper_guard_ok" if audit_ok else "wrapper_guard_failed",
        "audit_ok": audit_ok,
        "claim_boundary": "no-submit wrapper guard audit only; does not approve or run target-MSA jobs",
        "wrapper": wrapper_path,
        "receipt": receipt_path,
        "target_msa_approval_env_var": _APPROVAL_ENV_VAR,
        "target_msa_approval_env_value": _APPROVAL_TOKEN,
        "static_audit": static,
        "no_env_run": no_env,
        "failures": failures,
        "next_action": (
            "keep waiting for explicit approval before target-MSA submission"
            if audit_ok else
            "repair the wrapper guard before target-MSA approval or submission"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    no_env = rep.get("no_env_run") if isinstance(rep.get("no_env_run"), dict) else {}
    static = rep.get("static_audit") if isinstance(rep.get("static_audit"), dict) else {}
    lines = [
        "# M6d W2 Target-MSA Wrapper Guard Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        rep.get("claim_boundary", ""),
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
        f"export {rep.get('target_msa_approval_env_var')}={rep.get('target_msa_approval_env_value')}",
        "```",
        "",
    ]
    failures = rep.get("failures") or []
    lines.extend(["## Failures", ""])
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wrapper", default="results/m6d_w2_target_family_redesign_v9_target_msa_with_receipt.sh")
    ap.add_argument("--receipt", default="results/m6d_w2_target_family_redesign_v9_target_msa_precompute_receipt.jsonl")
    ap.add_argument("--run-no-env-check", action="store_true")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(args.wrapper, args.receipt, run_no_env_check=args.run_no_env_check)
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} static={static} no_env={no_env}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            static=rep["static_audit"].get("ok"),
            no_env=rep["no_env_run"].get("ok"),
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
