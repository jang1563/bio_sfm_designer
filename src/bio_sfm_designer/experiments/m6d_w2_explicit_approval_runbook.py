"""Build and audit the W2 v9 explicit-approval runbook without submitting work.

This artifact is the operator-facing bridge between the current no-submit state
and a later explicit target-MSA approval. It records the exact command order and
checks that the runbook still authorizes only target-MSA input prep, not
ProteinMPNN/Boltz panel work or a W2 science claim.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_TARGET_MSA"
_APPROVAL_TOKEN = "approve-v9-target-msa-precompute"
_APPROVAL_PACKET_STATUS = "awaiting_explicit_target_msa_approval"
_GATE_STATUS = "pre_submit_gate_ready_awaiting_explicit_approval"
_POSTSUBMIT_STATUS = "postsubmit_replay_ready_awaiting_target_msa_submission_and_completion"


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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _contains_approval(command: Any) -> bool:
    text = str(command or "")
    return _APPROVAL_ENV_VAR in text and _APPROVAL_TOKEN in text


def build_runbook(approval_packet: Dict[str, Any],
                  gate_audit: Dict[str, Any],
                  postsubmit_plan: Dict[str, Any],
                  completion_audit: Dict[str, Any],
                  mirror_audit: Dict[str, Any]) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []

    submit_command = approval_packet.get("submit_command_if_approved")
    sync_command = approval_packet.get("postsubmit_sync_back_command")
    gate_submit = gate_audit.get("submit_command_if_approved")
    gate_sync = gate_audit.get("postsubmit_sync_back_command")
    postsubmit_submit = postsubmit_plan.get("pre_submit_command_if_approved")
    postsubmit_sync = postsubmit_plan.get("sync_back_command_after_jobs_finish")

    if approval_packet.get("status") != _APPROVAL_PACKET_STATUS:
        _add_failure(failures, "approval_packet_status_not_ready",
                     "approval packet must remain in awaiting-explicit-approval state",
                     expected=_APPROVAL_PACKET_STATUS, observed=approval_packet.get("status"))
    if approval_packet.get("approval_packet_ready") is not True:
        _add_failure(failures, "approval_packet_not_ready",
                     "approval packet must be ready before building the runbook")
    if approval_packet.get("can_submit_target_msa_if_user_explicitly_approves") is not True:
        _add_failure(failures, "target_msa_not_ready_if_approved",
                     "runbook requires target-MSA input prep to be approval-ready")
    if approval_packet.get("can_submit_proteinmpnn_boltz_panel") is not False:
        _add_failure(failures, "panel_submission_not_blocked",
                     "runbook must not authorize ProteinMPNN/Boltz panel work")
    if approval_packet.get("wrapper_guard_audit_ok") is not True:
        _add_failure(failures, "wrapper_guard_not_attached",
                     "approval packet must include a passing wrapper guard audit")

    if gate_audit.get("status") != _GATE_STATUS or gate_audit.get("audit_ok") is not True:
        _add_failure(failures, "gate_audit_not_ready",
                     "target-MSA gate audit must pass before building the runbook",
                     expected={"status": _GATE_STATUS, "audit_ok": True},
                     observed={"status": gate_audit.get("status"), "audit_ok": gate_audit.get("audit_ok")})
    if gate_audit.get("ready_for_panel_submission") is not False:
        _add_failure(failures, "gate_allows_panel_submission",
                     "gate audit must keep panel submission blocked")
    if gate_audit.get("ready_for_target_msa_submission_if_explicitly_approved") is not True:
        _add_failure(failures, "gate_not_target_msa_approval_ready",
                     "gate audit must be ready only for explicitly approved target-MSA input prep")

    if postsubmit_plan.get("status") != _POSTSUBMIT_STATUS:
        _add_failure(failures, "postsubmit_plan_status_not_waiting",
                     "postsubmit plan must be waiting for target-MSA submission/completion",
                     expected=_POSTSUBMIT_STATUS, observed=postsubmit_plan.get("status"))

    if submit_command != gate_submit or submit_command != postsubmit_submit:
        _add_failure(failures, "submit_command_drift",
                     "approval packet, gate audit, and postsubmit plan must record the same submit command",
                     expected=submit_command,
                     observed={"gate": gate_submit, "postsubmit": postsubmit_submit})
    if sync_command != gate_sync or sync_command != postsubmit_sync:
        _add_failure(failures, "sync_command_drift",
                     "approval packet, gate audit, and postsubmit plan must record the same sync-back command",
                     expected=sync_command,
                     observed={"gate": gate_sync, "postsubmit": postsubmit_sync})
    if not _contains_approval(submit_command):
        _add_failure(failures, "submit_command_missing_approval_env",
                     "submit command must carry the explicit approval env token",
                     expected=f"{_APPROVAL_ENV_VAR}={_APPROVAL_TOKEN}", observed=submit_command)

    if approval_packet.get("target_count") != 14 or approval_packet.get("pending_path_count") != 28:
        _add_failure(failures, "unexpected_target_or_pending_count",
                     "current W2 v9 runbook expects 14 targets and 28 pending MSA/report paths",
                     expected={"target_count": 14, "pending_path_count": 28},
                     observed={
                         "target_count": approval_packet.get("target_count"),
                         "pending_path_count": approval_packet.get("pending_path_count"),
                     })
    if gate_audit.get("target_count") != approval_packet.get("target_count"):
        _add_failure(failures, "target_count_drift",
                     "gate and approval packet target counts must agree",
                     expected=approval_packet.get("target_count"), observed=gate_audit.get("target_count"))
    if gate_audit.get("pending_path_count") != approval_packet.get("pending_path_count"):
        _add_failure(failures, "pending_count_drift",
                     "gate and approval packet pending path counts must agree",
                     expected=approval_packet.get("pending_path_count"), observed=gate_audit.get("pending_path_count"))

    if completion_audit.get("audit_ok") is not True or completion_audit.get("can_mark_goal_complete") is not False:
        _add_failure(failures, "completion_boundary_not_active",
                     "goal completion audit must pass while keeping the goal active",
                     observed={
                         "audit_ok": completion_audit.get("audit_ok"),
                         "can_mark_goal_complete": completion_audit.get("can_mark_goal_complete"),
                     })
    if mirror_audit.get("audit_ok") is not True:
        _add_failure(failures, "mirror_audit_not_ok",
                     "local/Cayuga mirror audit must pass before using the runbook",
                     observed={"status": mirror_audit.get("status"), "n_failures": mirror_audit.get("n_failures")})

    audit_ok = not failures
    steps = [
        {
            "step": "confirm_explicit_user_approval",
            "command": "",
            "required": True,
            "note": "Do not continue unless the user explicitly approves v9 target-MSA input prep.",
        },
        {
            "step": "run_target_msa_input_prep_on_cayuga",
            "command": submit_command,
            "required": True,
            "note": "This is target-MSA input prep only; it is not panel submission.",
        },
        {
            "step": "wait_for_target_msa_jobs",
            "command": "check Cayuga job completion and receipt before sync-back",
            "required": True,
            "note": "Do not run panel work while jobs are pending or receipt is incomplete.",
        },
        {
            "step": "sync_back_target_msa_outputs",
            "command": sync_command,
            "required": True,
            "note": "Pull target MSA/report outputs and rerun post-sync replay gates.",
        },
        {
            "step": "rerun_completion_and_strict_require_files",
            "command": "use post-sync outputs from results/m6d_w2_target_family_redesign_v9_postsubmit_replay_plan.json",
            "required": True,
            "note": "Only after strict --require-files passes can a later panel plan be considered.",
        },
    ]
    return {
        "artifact": "m6d_w2_explicit_approval_runbook",
        "status": "explicit_approval_runbook_ready" if audit_ok else "explicit_approval_runbook_blocked",
        "audit_ok": audit_ok,
        "can_mark_goal_complete": False,
        "claim_boundary": {
            "target_msa_input_prep": "allowed only after explicit approval",
            "proteinmpnn_boltz_panel_submission": "blocked until target-MSA sync-back and strict replay pass",
            "w2_multi_target_generalization": "not_supported",
        },
        "target_count": approval_packet.get("target_count"),
        "pending_path_count": approval_packet.get("pending_path_count"),
        "target_msa_approval_env_var": _APPROVAL_ENV_VAR,
        "target_msa_approval_env_value": _APPROVAL_TOKEN,
        "submit_command_if_approved": submit_command,
        "postsubmit_sync_back_command": sync_command,
        "post_sync_outputs": postsubmit_plan.get("post_sync_outputs", {}),
        "approval_packet": approval_packet.get("_path"),
        "gate_audit": gate_audit.get("_path"),
        "postsubmit_plan": postsubmit_plan.get("_path"),
        "completion_audit": completion_audit.get("_path"),
        "mirror_audit": mirror_audit.get("_path"),
        "runbook_steps": steps,
        "failures": failures,
        "next_action": (
            "await explicit approval; then follow runbook_steps in order"
            if audit_ok else
            "repair runbook audit failures before requesting or using explicit approval"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Explicit-Approval Runbook",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Can mark goal complete: `{rep.get('can_mark_goal_complete')}`.",
        "",
        "This runbook does not submit work. It records the command order to use only after explicit approval.",
        "",
        "| item | value |",
        "|---|---:|",
        f"| targets | {rep.get('target_count')} |",
        f"| pending target-MSA/report paths | {rep.get('pending_path_count')} |",
        "",
        "## Steps",
        "",
    ]
    for i, step in enumerate(rep.get("runbook_steps", []), 1):
        lines.append(f"{i}. {step.get('step')}")
        if step.get("command"):
            lines.extend(["", "```bash", str(step.get("command")), "```"])
        lines.append(f"   - {step.get('note')}")
        lines.append("")
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
        lines.append("")
    lines.extend([f"Next action: {rep.get('next_action')}", ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--approval-packet", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--gate-audit", default="results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.json")
    ap.add_argument("--postsubmit-plan", default="results/m6d_w2_target_family_redesign_v9_postsubmit_replay_plan.json")
    ap.add_argument("--completion-audit", default="results/m6d_goal_completion_audit.json")
    ap.add_argument("--mirror-audit", default="results/m6d_local_cayuga_mirror_audit.json")
    ap.add_argument("--out-json", default="results/m6d_w2_explicit_approval_runbook.json")
    ap.add_argument("--out-md", default="results/m6d_w2_explicit_approval_runbook.md")
    args = ap.parse_args(argv)

    rep = build_runbook(
        _load_json(args.approval_packet),
        _load_json(args.gate_audit),
        _load_json(args.postsubmit_plan),
        _load_json(args.completion_audit),
        _load_json(args.mirror_audit),
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} targets={targets} pending={pending}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            targets=rep["target_count"],
            pending=rep["pending_path_count"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
