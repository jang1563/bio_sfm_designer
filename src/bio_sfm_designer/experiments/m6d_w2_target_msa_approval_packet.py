"""Build a no-submit W2 target-MSA approval packet.

The packet is the last local/Cayuga-replayable checkpoint before a human chooses
whether to run the target-MSA input-prep wrapper. It never submits jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set


_W2_READY_STATUS = "target_msa_gate_ready_awaiting_explicit_approval"
_W3_NEGATIVE_STATUS = "negative_robustness_result_adjudicated"
_APPROVAL_ENV_VAR = "BIO_SFM_APPROVE_V9_TARGET_MSA"
_APPROVAL_TOKEN = "approve-v9-target-msa-precompute"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _read_text(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def _read_paths(path: str) -> List[str]:
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip()]


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def _target_rows(target_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    targets = target_manifest.get("targets")
    if not isinstance(targets, list):
        return []
    return [row for row in targets if isinstance(row, dict)]


def _target_ids(target_manifest: Dict[str, Any]) -> List[str]:
    ids = []
    for row in _target_rows(target_manifest):
        target_id = row.get("id")
        if isinstance(target_id, str) and target_id:
            ids.append(target_id)
    return ids


def _expected_target_msa_paths(target_manifest: Dict[str, Any]) -> Set[str]:
    paths: Set[str] = set()
    for row in _target_rows(target_manifest):
        for field in ("target_msa", "target_msa_report"):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                paths.add(value)
    return paths


def _workstreams(project_status: Dict[str, Any]) -> Dict[str, Any]:
    workstreams = project_status.get("workstreams")
    return workstreams if isinstance(workstreams, dict) else {}


def _script_info(path: str, text: str) -> Dict[str, Any]:
    return {
        "path": path,
        "exists": os.path.exists(path),
        "nonempty": bool(text.strip()),
        "sha256": _sha256_file(path),
    }


def build_packet(project_status: Dict[str, Any],
                 gate_audit: Dict[str, Any],
                 target_manifest: Dict[str, Any],
                 wrapper_guard_audit: Optional[Dict[str, Any]],
                 pending_paths: Iterable[str],
                 *,
                 pending_paths_path: str,
                 submit_wrapper_path: str,
                 sync_back_script_path: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    pending = sorted(str(path) for path in pending_paths)
    pending_set = set(pending)
    expected_paths = _expected_target_msa_paths(target_manifest)
    target_ids = _target_ids(target_manifest)
    workstreams = _workstreams(project_status)
    w2 = workstreams.get("W2_multi_target_panel", {})
    w3 = workstreams.get("W3_independent_predictor", {})
    w4 = workstreams.get("W4_closed_loop_DBTL", {})

    submit_text = _read_text(submit_wrapper_path) if os.path.exists(submit_wrapper_path) else ""
    sync_text = _read_text(sync_back_script_path) if os.path.exists(sync_back_script_path) else ""

    if project_status.get("goal_progress") != "local_artifact_work_required":
        _failure(
            failures,
            "project_goal_progress_not_approval_ready",
            "project status must be at the local-artifact W2 approval gate",
            observed=project_status.get("goal_progress"),
        )
    if project_status.get("remaining") != 1:
        _failure(
            failures,
            "project_remaining_requirements_not_one",
            "W2 should be the only remaining goal-mode requirement",
            observed=project_status.get("remaining"),
        )
    if w2.get("status") != _W2_READY_STATUS:
        _failure(failures, "w2_status_not_ready", "W2 is not at the target-MSA approval gate",
                 observed=w2.get("status"))
    if w3.get("status") != _W3_NEGATIVE_STATUS or w3.get("positive_claim_supported") is not False:
        _failure(
            failures,
            "w3_not_adjudicated_negative",
            "W3 must be preserved as a negative robustness result before W2 approval",
            observed={"status": w3.get("status"), "positive_claim_supported": w3.get("positive_claim_supported")},
        )
    if w4.get("status") != "closed_loop_round_complete":
        _failure(failures, "w4_not_closed_loop_complete", "W4 closed-loop plumbing evidence is not closed",
                 observed=w4.get("status"))

    if gate_audit.get("audit_ok") is not True:
        _failure(failures, "gate_audit_not_ok", "target-MSA gate audit must pass before approval",
                 observed=gate_audit.get("audit_ok"))
    if gate_audit.get("explicit_submit_approval_required") is not True:
        _failure(failures, "approval_not_required", "gate audit must require explicit submit approval")
    if gate_audit.get("ready_for_target_msa_submission_if_explicitly_approved") is not True:
        _failure(failures, "target_msa_not_ready_if_approved", "target-MSA wrapper is not ready even with approval")
    if gate_audit.get("ready_for_panel_submission") is not False:
        _failure(failures, "panel_submission_not_blocked", "ProteinMPNN/Boltz panel submission must remain blocked")
    if gate_audit.get("pending_path_count") != len(pending):
        _failure(
            failures,
            "pending_path_count_mismatch",
            "pending path file length differs from gate audit",
            expected=gate_audit.get("pending_path_count"),
            observed=len(pending),
        )
    if gate_audit.get("target_count") != len(target_ids):
        _failure(
            failures,
            "target_count_mismatch",
            "target manifest target count differs from gate audit",
            expected=gate_audit.get("target_count"),
            observed=len(target_ids),
        )
    if pending_set != expected_paths:
        _failure(
            failures,
            "pending_paths_do_not_match_manifest_target_msa_fields",
            "pending paths must be exactly target_msa and target_msa_report for every target",
            missing_from_pending=sorted(expected_paths - pending_set),
            unexpected_pending=sorted(pending_set - expected_paths),
        )

    submit_command = gate_audit.get("submit_command_if_approved")
    sync_command = gate_audit.get("postsubmit_sync_back_command")
    if submit_command != w2.get("submit_command_if_approved"):
        _failure(failures, "submit_command_project_gate_mismatch",
                 "project status and gate audit submit commands differ",
                 project=w2.get("submit_command_if_approved"), gate=submit_command)
    if sync_command != w2.get("postsubmit_sync_back_command"):
        _failure(failures, "sync_command_project_gate_mismatch",
                 "project status and gate audit sync-back commands differ",
                 project=w2.get("postsubmit_sync_back_command"), gate=sync_command)
    if _APPROVAL_ENV_VAR not in str(submit_command or "") or _APPROVAL_TOKEN not in str(submit_command or ""):
        _failure(
            failures,
            "submit_command_missing_approval_env",
            "approved submit command must carry the explicit target-MSA approval environment variable",
            required=f"{_APPROVAL_ENV_VAR}={_APPROVAL_TOKEN}",
        )
    wrapper_guard_ok = None
    wrapper_guard_static_ok = None
    wrapper_guard_no_env_ok = None
    wrapper_guard_script_sha256 = None
    if not isinstance(wrapper_guard_audit, dict):
        _failure(
            failures,
            "wrapper_guard_audit_missing",
            "wrapper guard audit must be present before target-MSA approval",
        )
    else:
        wrapper_guard_ok = wrapper_guard_audit.get("audit_ok") is True
        static_audit = (
            wrapper_guard_audit.get("static_audit")
            if isinstance(wrapper_guard_audit.get("static_audit"), dict)
            else {}
        )
        no_env_run = (
            wrapper_guard_audit.get("no_env_run")
            if isinstance(wrapper_guard_audit.get("no_env_run"), dict)
            else {}
        )
        wrapper_guard_static_ok = static_audit.get("ok") is True
        wrapper_guard_no_env_ok = no_env_run.get("ok") is True
        wrapper_guard_script_sha256 = static_audit.get("wrapper_sha256")
        if not wrapper_guard_ok:
            _failure(
                failures,
                "wrapper_guard_audit_not_ok",
                "wrapper guard audit must pass before target-MSA approval",
                observed=wrapper_guard_audit.get("status"),
            )
        if not wrapper_guard_static_ok:
            _failure(
                failures,
                "wrapper_guard_static_audit_not_ok",
                "wrapper guard static audit must pass before target-MSA approval",
            )
        if not wrapper_guard_no_env_ok:
            _failure(
                failures,
                "wrapper_guard_no_env_run_not_ok",
                "wrapper guard no-env run must prove the wrapper exits before receipt creation",
                observed=no_env_run,
            )
        if no_env_run.get("receipt_exists_after") is True:
            _failure(
                failures,
                "wrapper_guard_receipt_created_without_approval",
                "wrapper guard audit observed receipt creation without approval env",
                observed=no_env_run.get("receipt"),
            )

    for path, text, kind in (
        (submit_wrapper_path, submit_text, "submit_wrapper"),
        (sync_back_script_path, sync_text, "sync_back_script"),
    ):
        if not os.path.exists(path):
            _failure(failures, f"{kind}_missing", f"{kind} does not exist", path=path)
        elif not text.strip():
            _failure(failures, f"{kind}_empty", f"{kind} is empty", path=path)

    required_submit_snippets = [
        "TARGET_MSA_PRECOMPUTE_DRY_RUN",
        "TARGET_MSA_PRECOMPUTE_RECEIPT",
        _APPROVAL_ENV_VAR,
        _APPROVAL_TOKEN,
        "refusing v9 target-MSA submission without explicit approval env",
        "bash \"$PLAN\"",
        "target-MSA input-prep provenance only",
    ]
    for snippet in required_submit_snippets:
        if snippet not in submit_text:
            _failure(failures, "submit_wrapper_missing_guard", "submit wrapper is missing a required guard",
                     snippet=snippet)
    disallowed_submit_snippets = [
        "run_generate_proteinmpnn_complex",
        "generate_proteinmpnn_complex.py",
        "run_predict_boltz_complex",
        "predict_boltz_complex.py",
    ]
    for snippet in disallowed_submit_snippets:
        if snippet in submit_text:
            _failure(failures, "submit_wrapper_contains_panel_job", "target-MSA wrapper must not launch panel jobs",
                     snippet=snippet)

    required_sync_snippets = [
        "rsync -avP",
        "--require-files",
        "complex_input_prep_completion",
        "complex_target_manifest",
        "Run only after v9 target-MSA input-prep jobs have finished.",
    ]
    for snippet in required_sync_snippets:
        if snippet not in sync_text:
            _failure(failures, "sync_back_script_missing_guard", "sync-back script is missing a required guard",
                     snippet=snippet)

    packet_ready = not failures
    return {
        "artifact": "m6d_w2_target_msa_approval_packet",
        "status": "awaiting_explicit_target_msa_approval" if packet_ready else "approval_packet_blocked",
        "approval_packet_ready": packet_ready,
        "can_submit_target_msa_if_user_explicitly_approves": packet_ready,
        "can_submit_proteinmpnn_boltz_panel": False,
        "explicit_submit_approval_required": True,
        "target_msa_approval_env_var": _APPROVAL_ENV_VAR,
        "target_msa_approval_env_value": _APPROVAL_TOKEN,
        "claim_boundary": (
            "approval packet covers target-MSA input prep only; it does not authorize W2 generalization "
            "or ProteinMPNN/Boltz panel submission"
        ),
        "failures": failures,
        "target_count": len(target_ids),
        "target_ids": target_ids,
        "pending_path_count": len(pending),
        "pending_paths": pending_paths_path,
        "pending_paths_sha256": _sha256_text("\n".join(pending) + ("\n" if pending else "")),
        "submit_command_if_approved": submit_command,
        "postsubmit_sync_back_command": sync_command,
        "wrapper_guard_audit": (
            wrapper_guard_audit.get("_path") if isinstance(wrapper_guard_audit, dict) else None
        ),
        "wrapper_guard_audit_ok": wrapper_guard_ok,
        "wrapper_guard_static_ok": wrapper_guard_static_ok,
        "wrapper_guard_no_env_run_ok": wrapper_guard_no_env_ok,
        "wrapper_guard_script_sha256": wrapper_guard_script_sha256,
        "scripts": {
            "submit_wrapper": _script_info(submit_wrapper_path, submit_text),
            "sync_back": _script_info(sync_back_script_path, sync_text),
        },
        "evidence": {
            "project_status": project_status.get("_path"),
            "gate_audit": gate_audit.get("_path"),
            "target_manifest": target_manifest.get("_path"),
        },
        "current_workstreams": {
            "W1_M6c_scale_up": workstreams.get("W1_M6c_scale_up", {}).get("status"),
            "W2_multi_target_panel": w2.get("status"),
            "W3_independent_predictor": w3.get("status"),
            "W4_closed_loop_DBTL": w4.get("status"),
        },
        "next_action": (
            "await explicit approval; if approved, run submit_command_if_approved, wait for jobs, "
            "then run postsubmit_sync_back_command and rerun strict require-files readiness"
            if packet_ready else
            "fix approval-packet failures before requesting or using target-MSA approval"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Target-MSA Approval Packet",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Approval packet ready: `{rep.get('approval_packet_ready')}`.",
        "",
        rep.get("claim_boundary", ""),
        "",
        "| item | value |",
        "|---|---:|",
        f"| targets | {rep.get('target_count')} |",
        f"| pending target-MSA/report paths | {rep.get('pending_path_count')} |",
        f"| panel submission allowed | {rep.get('can_submit_proteinmpnn_boltz_panel')} |",
        "",
        "## Commands",
        "",
        "Required approval environment for a real target-MSA run:",
        "",
        "```bash",
        f"export {rep.get('target_msa_approval_env_var')}={rep.get('target_msa_approval_env_value')}",
        "```",
        "",
        "Target-MSA command if explicitly approved:",
        "",
        "```bash",
        str(rep.get("submit_command_if_approved") or ""),
        "```",
        "",
        "Post-submit sync/replay command after jobs finish:",
        "",
        "```bash",
        str(rep.get("postsubmit_sync_back_command") or ""),
        "```",
        "",
        "## Workstreams",
        "",
    ]
    for key, value in rep.get("current_workstreams", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    failures = rep.get("failures") or []
    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-status", default="results/m6c_project_status_w2_followup.json")
    ap.add_argument("--gate-audit", default="results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.json")
    ap.add_argument("--target-manifest", default="configs/m6d_w2_target_family_redesign_v9_representative_targets.json")
    ap.add_argument("--wrapper-guard-audit", default="results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.json")
    ap.add_argument("--pending-paths", default="results/m6d_w2_target_family_redesign_v9_pending_input_prep_paths.txt")
    ap.add_argument("--submit-wrapper", default="results/m6d_w2_target_family_redesign_v9_target_msa_with_receipt.sh")
    ap.add_argument("--sync-back-script", default="results/m6d_w2_target_family_redesign_v9_msa_sync_back.sh")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_approval_packet.md")
    args = ap.parse_args(argv)

    rep = build_packet(
        _load_json(args.project_status),
        _load_json(args.gate_audit),
        _load_json(args.target_manifest),
        _load_json(args.wrapper_guard_audit),
        _read_paths(args.pending_paths),
        pending_paths_path=args.pending_paths,
        submit_wrapper_path=args.submit_wrapper,
        sync_back_script_path=args.sync_back_script,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} ready={ready} targets={targets} pending={pending}".format(
            status=rep["status"],
            ready=rep["approval_packet_ready"],
            targets=rep["target_count"],
            pending=rep["pending_path_count"],
        )
    )
    return 0 if rep["approval_packet_ready"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
