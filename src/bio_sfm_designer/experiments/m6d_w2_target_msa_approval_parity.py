"""Compare local and Cayuga W2 target-MSA approval packets.

This is a no-submit parity check. It reads JSON packet artifacts and verifies
that local and remote resume points agree on the approval boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from typing import Any, Dict, List, Optional


_COMPARE_FIELDS = (
    "artifact",
    "status",
    "approval_packet_ready",
    "can_submit_target_msa_if_user_explicitly_approves",
    "can_submit_proteinmpnn_boltz_panel",
    "explicit_submit_approval_required",
    "target_msa_approval_env_var",
    "target_msa_approval_env_value",
    "target_count",
    "target_ids",
    "pending_path_count",
    "pending_paths",
    "pending_paths_sha256",
    "submit_command_if_approved",
    "postsubmit_sync_back_command",
    "wrapper_guard_audit_ok",
    "wrapper_guard_static_ok",
    "wrapper_guard_no_env_run_ok",
    "wrapper_guard_script_sha256",
    "current_workstreams",
)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _load_remote_json(*, remote_host: Optional[str], remote_root: Optional[str], remote_path: str) -> Dict[str, Any]:
    if remote_host:
        if not remote_root:
            raise ValueError("--remote-root is required when --remote-host is used")
        cmd = ["ssh", remote_host, f"cd {remote_root} && cat {remote_path}"]
        proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
        obj = json.loads(proc.stdout)
    else:
        path = os.path.join(remote_root or "", remote_path)
        obj = _load_json(path)
    if not isinstance(obj, dict):
        raise ValueError(f"{remote_path} must contain a JSON object")
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


def _script_hashes(packet: Dict[str, Any]) -> Dict[str, Any]:
    scripts = packet.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    out = {}
    for role, info in scripts.items():
        if isinstance(info, dict):
            out[role] = {
                "exists": info.get("exists"),
                "nonempty": info.get("nonempty"),
                "sha256": info.get("sha256"),
            }
    return out


def build_parity(local_packet: Dict[str, Any],
                 remote_packet: Dict[str, Any],
                 *,
                 remote_host: Optional[str],
                 remote_root: Optional[str],
                 remote_path: str) -> Dict[str, Any]:
    mismatches: List[Dict[str, Any]] = []
    for field in _COMPARE_FIELDS:
        local_value = local_packet.get(field)
        remote_value = remote_packet.get(field)
        if local_value != remote_value:
            mismatches.append({
                "field": field,
                "local": local_value,
                "remote": remote_value,
            })
    local_failures = local_packet.get("failures")
    remote_failures = remote_packet.get("failures")
    if local_failures != remote_failures:
        mismatches.append({
            "field": "failures",
            "local": local_failures,
            "remote": remote_failures,
        })
    local_scripts = _script_hashes(local_packet)
    remote_scripts = _script_hashes(remote_packet)
    if local_scripts != remote_scripts:
        mismatches.append({
            "field": "scripts",
            "local": local_scripts,
            "remote": remote_scripts,
        })
    parity_ok = not mismatches
    return {
        "artifact": "m6d_w2_target_msa_approval_parity",
        "parity_ok": parity_ok,
        "status": "local_cayuga_approval_packet_agree" if parity_ok else "local_cayuga_approval_packet_mismatch",
        "mismatches": mismatches,
        "remote_host": remote_host,
        "remote_root": remote_root,
        "remote_path": remote_path,
        "local_status": local_packet.get("status"),
        "remote_status": remote_packet.get("status"),
        "approval_packet_ready": (
            local_packet.get("approval_packet_ready") is True
            and remote_packet.get("approval_packet_ready") is True
        ),
        "panel_submission_blocked": (
            local_packet.get("can_submit_proteinmpnn_boltz_panel") is False
            and remote_packet.get("can_submit_proteinmpnn_boltz_panel") is False
        ),
        "target_count": local_packet.get("target_count"),
        "pending_path_count": local_packet.get("pending_path_count"),
        "claim_boundary": "parity check only; does not submit target-MSA, ProteinMPNN, or Boltz jobs",
        "next_action": (
            "await explicit approval before target-MSA submission"
            if parity_ok else
            "fix local/Cayuga approval packet drift before any target-MSA approval or submission"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Target-MSA Approval Parity",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Parity OK: `{rep.get('parity_ok')}`.",
        "",
        rep.get("claim_boundary", ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| targets | {rep.get('target_count')} |",
        f"| pending target-MSA/report paths | {rep.get('pending_path_count')} |",
        f"| approval packet ready on both sides | {rep.get('approval_packet_ready')} |",
        f"| panel submission blocked on both sides | {rep.get('panel_submission_blocked')} |",
        "",
        "## Mismatches",
        "",
    ]
    mismatches = rep.get("mismatches") or []
    if mismatches:
        for item in mismatches:
            lines.append(f"- `{item.get('field')}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-packet", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--remote-host", default=None)
    ap.add_argument("--remote-root", default=None)
    ap.add_argument("--remote-packet", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_approval_parity.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_approval_parity.md")
    args = ap.parse_args(argv)

    rep = build_parity(
        _load_json(args.local_packet),
        _load_remote_json(
            remote_host=args.remote_host,
            remote_root=args.remote_root,
            remote_path=args.remote_packet,
        ),
        remote_host=args.remote_host,
        remote_root=args.remote_root,
        remote_path=args.remote_packet,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} parity_ok={parity} targets={targets} pending={pending}".format(
            status=rep["status"],
            parity=rep["parity_ok"],
            targets=rep["target_count"],
            pending=rep["pending_path_count"],
        )
    )
    return 0 if rep["parity_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
