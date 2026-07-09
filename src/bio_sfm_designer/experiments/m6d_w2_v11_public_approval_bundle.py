"""Build a public-safe W2 v11 approval bundle without submitting work.

The raw W2 v11 approval runbook is intentionally environment-specific: it can
contain a real Cayuga login host, remote checkout path, and Python path. This
helper distills the same approval boundary into a portable, tracked artifact
that keeps the execution order and strict gates visible without publishing
machine-specific paths.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


_DEFAULT_RUNBOOK = "results/m6d_w2_target_family_redesign_v11_approval_runbook.json"
_DEFAULT_PACKET = "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"
_DEFAULT_PREFLIGHT = "results/m6d_w2_target_family_redesign_v11_panel_preflight.json"
_DEFAULT_DECISION = "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json"
_DEFAULT_REMOTE_READY = "results/m6d_w2_target_family_redesign_v11_remote_submission_readiness.json"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_public_approval_bundle.md"
_BASE_FORBIDDEN_PUBLIC_SNIPPETS = (
    "/home/fs01/",
    "/Users/",
    ".conda/envs/boltz/bin/python",
)
_STRICT_POSTSUBMIT_FLAGS = (
    "--manifest",
    "--receipt",
    "--summary",
    "--job-states",
    "--require-sync-ready",
    "--out-json",
)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj.setdefault("_source_path", path)
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


def _strict_postsubmit_command_ok(command: Any, packet: Dict[str, Any]) -> bool:
    text = str(command or "")
    required_paths = (
        packet.get("manifest"),
        packet.get("submit_receipt"),
        packet.get("submit_summary"),
        packet.get("job_state_probe_before_sync"),
        packet.get("postsubmit_status_before_sync"),
    )
    return (
        "m6d_w2_panel_postsubmit_status" in text
        and all(flag in text for flag in _STRICT_POSTSUBMIT_FLAGS)
        and all(str(path) in text for path in required_paths if path)
    )


def _portable_commands(runbook: Dict[str, Any], packet: Dict[str, Any]) -> Dict[str, str]:
    approval = runbook.get("approval") if isinstance(runbook.get("approval"), dict) else {}
    post = runbook.get("post_submit") if isinstance(runbook.get("post_submit"), dict) else {}
    approval_env_var = str(approval.get("required_env_var") or packet.get("panel_approval_env_var") or "")
    approval_env_value = str(approval.get("required_env_value") or packet.get("panel_approval_env_value") or "")
    submit_script = "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh"
    receipt_monitor = str(post.get("receipt_monitor_script") or "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh")
    job_state_query = str(post.get("job_state_query_plan_after_probe") or "results/m6d_w2_target_family_redesign_v11_job_state_query.sh")
    sync_back = str(post.get("sync_back_script") or packet.get("sync_back_command_after_jobs_finish") or "")
    completion = str(post.get("completion_script") or packet.get("completion_command_after_sync") or "")
    postsync = str(post.get("postsync_replay_script") or packet.get("postsync_replay_after_sync") or "")
    if sync_back.startswith("bash "):
        sync_back = sync_back.split(" ", 1)[1]
    if completion.startswith("bash "):
        completion = completion.split(" ", 1)[1]
    if postsync.startswith("bash "):
        postsync = postsync.split(" ", 1)[1]
    return {
        "setup_environment": (
            "export CAYUGA_BIO_SFM_HOST=<hpc-login-host>\n"
            "export CAYUGA_BIO_SFM_REMOTE_ROOT=<remote-repo-root>\n"
            "export CAYUGA_BIO_SFM_ROOT=\"$CAYUGA_BIO_SFM_HOST:$CAYUGA_BIO_SFM_REMOTE_ROOT\"\n"
            "export BIO_SFM_PYTHON=<python-with-boltz-and-proteinmpnn-runtime>"
        ),
        "submit_if_explicitly_approved": (
            "ssh \"$CAYUGA_BIO_SFM_HOST\" "
            f"\"cd \\\"$CAYUGA_BIO_SFM_REMOTE_ROOT\\\" && BIO_SFM_PYTHON=\\\"$BIO_SFM_PYTHON\\\" "
            f"PYTHONNOUSERSITE=1 {approval_env_var}={approval_env_value} bash {submit_script}\""
        ),
        "receipt_monitor_after_submit": f"bash {receipt_monitor}",
        "job_state_query_after_receipt": (
            "ssh \"$CAYUGA_BIO_SFM_HOST\" "
            f"\"cd \\\"$CAYUGA_BIO_SFM_REMOTE_ROOT\\\" && bash {job_state_query}\""
        ),
        "sync_job_state_probe_after_query": (
            "mkdir -p results && "
            "rsync -avP \"$CAYUGA_BIO_SFM_ROOT/results/m6d_w2_target_family_redesign_v11_job_state_probe.json\" "
            "results/m6d_w2_target_family_redesign_v11_job_state_probe.json && "
            "rsync -avP \"$CAYUGA_BIO_SFM_ROOT/results/m6d_w2_target_family_redesign_v11_sacct_states.tsv\" "
            "results/m6d_w2_target_family_redesign_v11_sacct_states.tsv"
        ),
        "strict_postsubmit_status_before_sync": str(packet.get("postsubmit_status_command_before_sync") or ""),
        "sync_back_after_sync_ready": f"bash {sync_back}",
        "completion_after_sync": f"bash {completion}",
        "postsync_replay": f"bash {postsync}",
    }


def _forbidden_public_snippets() -> List[str]:
    snippets = list(_BASE_FORBIDDEN_PUBLIC_SNIPPETS)
    for value in (
        os.path.expanduser("~"),
        os.environ.get("USER"),
        os.environ.get("LOGNAME"),
        os.environ.get("CAYUGA_BIO_SFM_HOST"),
    ):
        if value and value != "~" and value not in snippets:
            snippets.append(value)
    return snippets


def _contains_forbidden_public_text(obj: Dict[str, Any]) -> List[str]:
    text = json.dumps(obj, sort_keys=True)
    return [snippet for snippet in _forbidden_public_snippets() if snippet in text]


def build_bundle(
    *,
    runbook: Dict[str, Any],
    packet: Dict[str, Any],
    preflight: Dict[str, Any],
    decision_state: Dict[str, Any],
    remote_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    commands = _portable_commands(runbook, packet)
    failures: List[Dict[str, Any]] = []
    if runbook.get("status") != "approval_runbook_ready_not_submitted":
        failures.append({"kind": "runbook_not_ready", "observed": runbook.get("status")})
    submit_state = runbook.get("submit_state") if isinstance(runbook.get("submit_state"), dict) else {}
    if submit_state.get("submitted") is not False:
        failures.append({"kind": "runbook_submit_state_not_false", "observed": submit_state.get("submitted")})
    if packet.get("status") != "panel_approval_packet_ready" or packet.get("audit_ok") is not True:
        failures.append({
            "kind": "approval_packet_not_ready",
            "observed": {"status": packet.get("status"), "audit_ok": packet.get("audit_ok")},
        })
    if packet.get("can_claim_w2_generalization") is not False:
        failures.append({"kind": "approval_packet_claim_boundary_drift", "observed": packet.get("can_claim_w2_generalization")})
    if preflight.get("status") != "panel_preflight_dry_run_passed_not_submitted" or preflight.get("audit_ok") is not True:
        failures.append({
            "kind": "preflight_not_ready",
            "observed": {"status": preflight.get("status"), "audit_ok": preflight.get("audit_ok")},
        })
    if decision_state.get("status") != "awaiting_explicit_panel_submission_approval":
        failures.append({"kind": "decision_state_not_awaiting_approval", "observed": decision_state.get("status")})
    for key, expected in (("no_submit", True), ("submitted", False), ("can_claim_w2_generalization", False)):
        if decision_state.get(key) is not expected:
            failures.append({"kind": "decision_state_boundary_drift", "field": key, "observed": decision_state.get(key)})
    if remote_readiness.get("status") != "remote_submission_readiness_ok" or remote_readiness.get("audit_ok") is not True:
        failures.append({
            "kind": "remote_readiness_not_ok",
            "observed": {"status": remote_readiness.get("status"), "audit_ok": remote_readiness.get("audit_ok")},
        })
    if not _strict_postsubmit_command_ok(commands.get("strict_postsubmit_status_before_sync"), packet):
        failures.append({
            "kind": "strict_postsubmit_command_not_portable_or_complete",
            "observed": commands.get("strict_postsubmit_status_before_sync"),
        })

    bundle: Dict[str, Any] = {
        "artifact": "m6d_w2_v11_public_approval_bundle",
        "status": "public_approval_bundle_ready_not_submitted",
        "audit_ok": True,
        "no_submit": True,
        "submitted": False,
        "can_claim_w2_generalization": False,
        "approval_boundary": {
            "explicit_approval_required": True,
            "approval_must_explicitly_name": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "continuation_phrases_are_approval": False,
            "machine_gate": (
                f"{packet.get('panel_approval_env_var')}={packet.get('panel_approval_env_value')}"
            ),
        },
        "source_artifacts": {
            "runbook": runbook.get("_source_path"),
            "approval_packet": packet.get("_source_path"),
            "preflight": preflight.get("_source_path"),
            "submission_decision_state": decision_state.get("_source_path"),
            "remote_readiness": remote_readiness.get("_source_path"),
        },
        "target_contract": {
            "manifest": packet.get("manifest"),
            "target_alpha": packet.get("target_alpha"),
            "min_targets": (runbook.get("post_submit") or {}).get("min_targets")
            if isinstance(runbook.get("post_submit"), dict) else None,
            "min_records_per_target": (runbook.get("post_submit") or {}).get("min_records_per_target")
            if isinstance(runbook.get("post_submit"), dict) else None,
        },
        "portable_commands": commands,
        "claim_boundary": (
            "not W2 evidence until explicit approval, successful submit receipt, completed jobs, "
            "sync-back, completion, target-wise report, and refreshed interpretation"
        ),
        "failures": failures,
        "next_action": (
            "await explicit approval before using submit_if_explicitly_approved; otherwise keep no-submit state"
        ),
    }
    forbidden = _contains_forbidden_public_text(bundle)
    if forbidden:
        failures.append({
            "kind": "public_bundle_contains_environment_specific_text",
            "snippets": forbidden,
        })
    bundle["audit_ok"] = not failures
    bundle["status"] = "public_approval_bundle_ready_not_submitted" if not failures else "public_approval_bundle_blocked"
    return bundle


def render_markdown(rep: Dict[str, Any]) -> str:
    commands = rep.get("portable_commands") if isinstance(rep.get("portable_commands"), dict) else {}
    lines = [
        "# W2 v11 Public Approval Bundle",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        "## Approval Boundary",
        "",
        f"- explicit approval required: `{rep.get('approval_boundary', {}).get('explicit_approval_required')}`",
        f"- approval must name: `{rep.get('approval_boundary', {}).get('approval_must_explicitly_name')}`",
        f"- continuation phrases are approval: `{rep.get('approval_boundary', {}).get('continuation_phrases_are_approval')}`",
        f"- machine gate: `{rep.get('approval_boundary', {}).get('machine_gate')}`",
        "",
        "## Portable Commands",
        "",
    ]
    for key in (
        "setup_environment",
        "submit_if_explicitly_approved",
        "receipt_monitor_after_submit",
        "job_state_query_after_receipt",
        "sync_job_state_probe_after_query",
        "strict_postsubmit_status_before_sync",
        "sync_back_after_sync_ready",
        "completion_after_sync",
        "postsync_replay",
    ):
        lines.extend([f"### {key}", "", "```bash", str(commands.get(key) or ""), "```", ""])
    lines.extend([
        "## Claim Boundary",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "## Failures",
        "",
    ])
    failures = rep.get("failures") if isinstance(rep.get("failures"), list) else []
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runbook", default=_DEFAULT_RUNBOOK)
    ap.add_argument("--approval-packet", default=_DEFAULT_PACKET)
    ap.add_argument("--preflight", default=_DEFAULT_PREFLIGHT)
    ap.add_argument("--submission-decision", default=_DEFAULT_DECISION)
    ap.add_argument("--remote-readiness", default=_DEFAULT_REMOTE_READY)
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    rep = build_bundle(
        runbook=_load_json(args.runbook),
        packet=_load_json(args.approval_packet),
        preflight=_load_json(args.preflight),
        decision_state=_load_json(args.submission_decision),
        remote_readiness=_load_json(args.remote_readiness),
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"status={rep['status']} audit_ok={rep['audit_ok']} no_submit={rep['no_submit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
