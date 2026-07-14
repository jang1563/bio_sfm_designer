"""Audit W3b target-MSA readiness on Cayuga without submitting work."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
import subprocess
from typing import Any, Dict, Iterable, List, Optional


_APPROVAL_ENV = "BIO_SFM_APPROVE_W3B_TARGET_MSA"
_RECEIPT = "results/m6d_w3b_target_msa_receipt.jsonl"
_SUMMARY = "results/m6d_w3b_target_msa_receipt_summary.json"
_SHELL_PATHS = (
    "hpc/run_w3b_target_msa_guarded.sh",
    "results/m6d_w3b_target_msas.sh",
    "hpc/run_precompute_boltz_target_msa.sbatch",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


def _ssh(
    host: str,
    command: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={timeout}",
            host,
            f"bash -lc {shlex.quote(command)}",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout + 15,
    )


def _remote_path(root: str, rel_path: str) -> str:
    return os.path.join(root, rel_path)


def _read_remote(host: str, root: str, rel_path: str, *, timeout: int) -> Optional[bytes]:
    path = shlex.quote(_remote_path(root, rel_path))
    proc = _ssh(host, f"test -s {path} && cat -- {path}", timeout=timeout)
    return proc.stdout if proc.returncode == 0 else None


def _remote_exists(host: str, root: str, rel_path: str, *, timeout: int) -> bool:
    path = shlex.quote(_remote_path(root, rel_path))
    return _ssh(host, f"test -e {path}", timeout=timeout).returncode == 0


def _runtime_check(host: str, home_relative_path: str, *, timeout: int) -> bool:
    if not home_relative_path or home_relative_path.startswith("/") or ".." in home_relative_path.split("/"):
        raise ValueError("runtime paths must be safe paths relative to $HOME")
    command = f'test -x "$HOME/{home_relative_path}"'
    return _ssh(host, command, timeout=timeout).returncode == 0


def expected_artifacts(local_root: str, packet: Dict[str, Any], packet_path: str) -> List[Dict[str, str]]:
    artifacts: Dict[str, str] = {}
    for binding in packet.get("bound_artifacts", {}).values():
        if isinstance(binding, dict) and isinstance(binding.get("path"), str):
            artifacts[binding["path"]] = str(binding.get("sha256") or "")
    wrapper = packet.get("wrapper", {})
    if isinstance(wrapper, dict) and isinstance(wrapper.get("path"), str):
        artifacts[wrapper["path"]] = str(wrapper.get("sha256") or "")
    artifacts[packet_path] = _sha256_file(os.path.join(local_root, packet_path))
    return [
        {"path": path, "sha256": artifacts[path]}
        for path in sorted(artifacts)
    ]


def observe_remote(
    *,
    host: str,
    remote_root: str,
    expected: List[Dict[str, str]],
    target_ids: List[str],
    wrapper_path: str,
    runtime_python: str,
    runtime_boltz: str,
    timeout: int,
) -> Dict[str, Any]:
    exact: Dict[str, Dict[str, Any]] = {}
    for row in expected:
        rel_path = row["path"]
        value = _read_remote(host, remote_root, rel_path, timeout=timeout)
        exact[rel_path] = {
            "exists": value is not None,
            "bytes": len(value) if value is not None else 0,
            "sha256": _sha256_bytes(value) if value is not None else None,
        }

    syntax: Dict[str, int] = {}
    for rel_path in _SHELL_PATHS:
        path = shlex.quote(_remote_path(remote_root, rel_path))
        syntax[rel_path] = _ssh(host, f"bash -n {path}", timeout=timeout).returncode

    receipt_before = _remote_exists(host, remote_root, _RECEIPT, timeout=timeout)
    summary_before = _remote_exists(host, remote_root, _SUMMARY, timeout=timeout)
    target_line = "target-MSA precompute dry-run targets: " + ",".join(target_ids)
    wrapper = shlex.quote(wrapper_path)
    root = shlex.quote(remote_root)
    dry_command = "\n".join(
        [
            f"cd {root}",
            f"unset {_APPROVAL_ENV}",
            "TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \\",
            f'BIO_SFM_PYTHON="$HOME/{runtime_python}" \\',
            "PYTHONNOUSERSITE=1 \\",
            f"bash {wrapper}",
        ]
    )
    dry_proc = _ssh(host, dry_command, timeout=timeout)
    dry_stdout = dry_proc.stdout.decode("utf-8", errors="replace")
    dry_stderr = dry_proc.stderr.decode("utf-8", errors="replace")
    receipt_after = _remote_exists(host, remote_root, _RECEIPT, timeout=timeout)
    summary_after = _remote_exists(host, remote_root, _SUMMARY, timeout=timeout)

    return {
        "exact": exact,
        "shell_syntax_returncodes": syntax,
        "runtime": {
            "boltz_python_executable": _runtime_check(host, runtime_python, timeout=timeout),
            "boltz_cli_executable": _runtime_check(host, runtime_boltz, timeout=timeout),
            "sbatch_available": _ssh(host, "command -v sbatch >/dev/null 2>&1", timeout=timeout).returncode == 0,
        },
        "receipt_state": {
            "receipt_before": receipt_before,
            "summary_before": summary_before,
            "receipt_after": receipt_after,
            "summary_after": summary_after,
        },
        "dry_run": {
            "returncode": dry_proc.returncode,
            "no_scheduler_message_seen": "no scheduler jobs submitted; receipt untouched" in dry_stdout,
            "exact_target_line_seen": target_line in dry_stdout.splitlines(),
            "stdout_sha256": _sha256_bytes(dry_proc.stdout),
            "stderr_tail": dry_stderr[-1000:],
        },
    }


def evaluate_readiness(
    *,
    packet: Dict[str, Any],
    expected: List[Dict[str, str]],
    observed: Dict[str, Any],
    remote_host: str,
    remote_root_label: str,
    observed_at_utc: str,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    exact_checks: List[Dict[str, Any]] = []
    observed_exact = observed.get("exact", {})
    for expected_row in expected:
        path = expected_row["path"]
        actual = observed_exact.get(path, {})
        ok = (
            actual.get("exists") is True
            and int(actual.get("bytes") or 0) > 0
            and actual.get("sha256") == expected_row["sha256"]
        )
        row = {
            "path": path,
            "expected_sha256": expected_row["sha256"],
            "remote_sha256": actual.get("sha256"),
            "remote_bytes": int(actual.get("bytes") or 0),
            "ok": ok,
        }
        exact_checks.append(row)
        if not ok:
            failures.append({"kind": "remote_artifact_mismatch", "path": path})

    syntax_checks = [
        {"path": path, "returncode": returncode, "ok": returncode == 0}
        for path, returncode in sorted(observed.get("shell_syntax_returncodes", {}).items())
    ]
    for row in syntax_checks:
        if not row["ok"]:
            failures.append({"kind": "remote_shell_syntax_failed", "path": row["path"]})

    runtime = dict(observed.get("runtime", {}))
    for name in ("boltz_python_executable", "boltz_cli_executable", "sbatch_available"):
        if runtime.get(name) is not True:
            failures.append({"kind": "remote_runtime_missing", "check": name})

    receipt_state = dict(observed.get("receipt_state", {}))
    receipt_untouched = all(receipt_state.get(name) is False for name in (
        "receipt_before", "summary_before", "receipt_after", "summary_after"
    ))
    if not receipt_untouched:
        failures.append({"kind": "receipt_or_summary_present"})

    dry_run = dict(observed.get("dry_run", {}))
    dry_run_ok = (
        dry_run.get("returncode") == 0
        and dry_run.get("no_scheduler_message_seen") is True
        and dry_run.get("exact_target_line_seen") is True
        and receipt_untouched
    )
    if not dry_run_ok:
        failures.append({"kind": "remote_guarded_dry_run_failed"})

    packet_ready = (
        packet.get("approval_packet_ready") is True
        and packet.get("no_submit") is True
        and packet.get("can_submit_candidate_generation_or_candidate_level_prediction") is False
    )
    if not packet_ready:
        failures.append({"kind": "approval_packet_boundary_invalid"})

    audit_ok = not failures
    return {
        "artifact": "m6d_w3b_target_msa_remote_readiness",
        "status": "w3b_target_msa_remote_ready_awaiting_explicit_approval" if audit_ok else "w3b_target_msa_remote_readiness_blocked",
        "audit_ok": audit_ok,
        "no_submit": True,
        "explicit_approval_still_required": True,
        "can_submit_target_msa_if_explicitly_approved": audit_ok,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "can_claim_w3b": False,
        "observed_at_utc": observed_at_utc,
        "remote_host": remote_host,
        "remote_root": remote_root_label,
        "target_ids": list(packet.get("target_ids", [])),
        "exact_checks": exact_checks,
        "shell_syntax_checks": syntax_checks,
        "runtime": runtime,
        "receipt_state": receipt_state,
        "receipt_untouched": receipt_untouched,
        "dry_run": dry_run,
        "n_exact_checks": len(exact_checks),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Live Cayuga mirror/runtime and guarded dry-run evidence only. No scheduler job, GPU compute, "
            "candidate generation, candidate-level prediction, or W3b claim is authorized or produced."
        ),
        "next_action": (
            "wait for exact W3b target-MSA approval, then run the already staged guarded wrapper"
            if audit_ok else
            "repair Cayuga readiness failures and rerun this no-submit audit"
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3b Cayuga Target-MSA Readiness",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"No submit: `{report['no_submit']}`.",
        f"Explicit approval still required: `{report['explicit_approval_still_required']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- remote: `{report['remote_host']}:{report['remote_root']}`",
        f"- exact SHA checks: `{report['n_exact_checks']}`",
        f"- receipt untouched: `{report['receipt_untouched']}`",
        f"- dry-run return code: `{report['dry_run'].get('returncode')}`",
        f"- failures: `{report['n_failures']}`",
        "",
        f"Next action: {report['next_action']}.",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- `{failure['kind']}`" for failure in report["failures"])
        lines.append("")
    return "\n".join(lines)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", default=".")
    parser.add_argument("--remote-host", required=True)
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--remote-root-label", default="$HOME/bio_sfm_smoke")
    parser.add_argument("--packet", default="results/m6d_w3b_target_msa_approval_packet.json")
    parser.add_argument("--runtime-python", default=".conda/envs/boltz/bin/python")
    parser.add_argument("--runtime-boltz", default=".conda/envs/boltz/bin/boltz")
    parser.add_argument("--ssh-timeout", type=int, default=30)
    parser.add_argument("--out-json", default="results/m6d_w3b_target_msa_remote_readiness.json")
    parser.add_argument("--out-md", default="results/m6d_w3b_target_msa_remote_readiness.md")
    args = parser.parse_args(argv)

    local_root = os.path.abspath(args.local_root)
    packet = _load_json(os.path.join(local_root, args.packet))
    expected = expected_artifacts(local_root, packet, args.packet)
    target_ids = [str(value) for value in packet.get("target_ids", [])]
    wrapper_path = str(packet.get("wrapper", {}).get("path") or "")
    observed = observe_remote(
        host=args.remote_host,
        remote_root=args.remote_root,
        expected=expected,
        target_ids=target_ids,
        wrapper_path=wrapper_path,
        runtime_python=args.runtime_python,
        runtime_boltz=args.runtime_boltz,
        timeout=args.ssh_timeout,
    )
    observed_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = evaluate_readiness(
        packet=packet,
        expected=expected,
        observed=observed,
        remote_host=args.remote_host,
        remote_root_label=args.remote_root_label,
        observed_at_utc=observed_at,
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"exact={report['n_exact_checks']} failures={report['n_failures']} no_submit={report['no_submit']}"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
