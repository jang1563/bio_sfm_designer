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
_MANUAL_WORKFLOW_COMMAND_KEYS = (
    "setup_environment",
    "submit_if_explicitly_approved",
    "receipt_monitor_after_submit",
    "job_state_query_after_receipt",
    "sync_job_state_probe_after_query",
    "strict_postsubmit_status_before_sync",
    "sync_back_after_sync_ready",
    "completion_after_sync",
    "postsync_replay",
)
_APPROVAL_SCOPE_KEYS = (
    "manifest",
    "target_ids",
    "n_targets",
    "n_ready_targets",
    "min_targets",
    "records_per_target_planned",
    "planned_design_records",
    "expected_job_pairs",
    "expected_slurm_jobs",
    "job_pair_model",
    "target_alpha",
    "panel_out",
    "completion_after_sync",
    "sync_back_after_jobs_finish",
    "submit_receipt",
    "submit_summary",
    "no_submit",
    "can_claim_w2_generalization",
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


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _public_approval_scope(packet: Dict[str, Any]) -> Dict[str, Any]:
    scope = packet.get("approval_scope") if isinstance(packet.get("approval_scope"), dict) else {}
    return {key: scope.get(key) for key in _APPROVAL_SCOPE_KEYS}


def _approval_scope_ok(scope: Dict[str, Any], packet: Dict[str, Any]) -> bool:
    n_ready = _int_or_none(scope.get("n_ready_targets"))
    n_targets = _int_or_none(scope.get("n_targets"))
    min_targets = _int_or_none(scope.get("min_targets"))
    records_per_target = _int_or_none(scope.get("records_per_target_planned"))
    planned_records = _int_or_none(scope.get("planned_design_records"))
    expected_job_pairs = _int_or_none(scope.get("expected_job_pairs"))
    expected_slurm_jobs = _int_or_none(scope.get("expected_slurm_jobs"))
    target_ids = scope.get("target_ids")
    return (
        bool(scope.get("manifest"))
        and isinstance(target_ids, list)
        and n_ready is not None
        and n_targets is not None
        and min_targets is not None
        and len(target_ids) == n_ready
        and n_targets >= n_ready
        and n_ready >= min_targets
        and records_per_target is not None
        and records_per_target > 0
        and planned_records == n_ready * records_per_target
        and expected_job_pairs == n_ready
        and expected_slurm_jobs == n_ready * 2
        and scope.get("job_pair_model") == "ProteinMPNN -> Boltz"
        and scope.get("target_alpha") == packet.get("target_alpha")
        and bool(scope.get("panel_out"))
        and bool(scope.get("completion_after_sync"))
        and bool(scope.get("sync_back_after_jobs_finish"))
        and scope.get("no_submit") is True
        and scope.get("can_claim_w2_generalization") is False
    )


def _portable_commands(runbook: Dict[str, Any], packet: Dict[str, Any]) -> Dict[str, str]:
    approval = runbook.get("approval") if isinstance(runbook.get("approval"), dict) else {}
    post = runbook.get("post_submit") if isinstance(runbook.get("post_submit"), dict) else {}
    approval_env_var = str(approval.get("required_env_var") or packet.get("panel_approval_env_var") or "")
    approval_env_value = str(approval.get("required_env_value") or packet.get("panel_approval_env_value") or "")
    submit_script = "results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh"
    receipt_monitor = str(post.get("receipt_monitor_script") or "results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh")
    job_state_query = str(post.get("job_state_query_plan_after_probe") or "results/m6d_w2_target_family_redesign_v11_job_state_query.sh")
    postsubmit_driver = str(post.get("postsubmit_driver_script") or "results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh")
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
        "postsubmit_driver_after_submit": f"bash {postsubmit_driver}",
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


def _command_present(commands: Dict[str, str], key: str) -> bool:
    text = str(commands.get(key) or "").strip()
    return bool(text) and text != "bash"


def _post_approval_workflow(
    commands: Dict[str, str],
    postsubmit_driver_polling: Dict[str, Any],
) -> Dict[str, Any]:
    manual_steps: List[Dict[str, Any]] = []
    for i, key in enumerate(_MANUAL_WORKFLOW_COMMAND_KEYS, start=1):
        manual_steps.append({
            "step": i,
            "id": key,
            "command_key": key,
            "command_present": _command_present(commands, key),
            "requires_explicit_approval": key == "submit_if_explicitly_approved",
            "is_sync_ready_gate": key == "strict_postsubmit_status_before_sync",
        })
    manual_step_ids = [str(step["id"]) for step in manual_steps]
    strict_i = manual_step_ids.index("strict_postsubmit_status_before_sync")
    sync_i = manual_step_ids.index("sync_back_after_sync_ready")
    return {
        "manual_steps": manual_steps,
        "manual_step_count": len(manual_steps),
        "manual_step_ids": manual_step_ids,
        "all_manual_commands_present": all(step["command_present"] is True for step in manual_steps),
        "strict_sync_ready_gate_step": "strict_postsubmit_status_before_sync",
        "requires_sync_ready_before_record_sync": (
            strict_i < sync_i
            and "--require-sync-ready" in str(commands.get("strict_postsubmit_status_before_sync") or "")
        ),
        "includes_receipt_monitor": "receipt_monitor_after_submit" in manual_step_ids,
        "includes_job_state_query": "job_state_query_after_receipt" in manual_step_ids,
        "includes_job_state_probe_sync": "sync_job_state_probe_after_query" in manual_step_ids,
        "includes_sync_back": "sync_back_after_sync_ready" in manual_step_ids,
        "includes_completion": "completion_after_sync" in manual_step_ids,
        "includes_postsync_interpretation": "postsync_replay" in manual_step_ids,
        "driver_command_key": "postsubmit_driver_after_submit",
        "driver_command_present": _command_present(commands, "postsubmit_driver_after_submit"),
        "driver_proceeds_only_when_sync_ready": (
            postsubmit_driver_polling.get("proceeds_only_when_sync_ready") is True
        ),
    }


def _post_approval_workflow_ok(workflow: Dict[str, Any]) -> bool:
    return (
        workflow.get("manual_step_count") == len(_MANUAL_WORKFLOW_COMMAND_KEYS)
        and workflow.get("all_manual_commands_present") is True
        and workflow.get("requires_sync_ready_before_record_sync") is True
        and workflow.get("includes_receipt_monitor") is True
        and workflow.get("includes_job_state_query") is True
        and workflow.get("includes_job_state_probe_sync") is True
        and workflow.get("includes_sync_back") is True
        and workflow.get("includes_completion") is True
        and workflow.get("includes_postsync_interpretation") is True
        and workflow.get("driver_command_present") is True
        and workflow.get("driver_proceeds_only_when_sync_ready") is True
    )


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


def _shell_syntax_checks_ok(remote_readiness: Dict[str, Any]) -> bool:
    rows = remote_readiness.get("shell_syntax_checks")
    checks = rows if isinstance(rows, list) else []
    return (
        bool(checks)
        and all(
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("local_returncode") == 0
            and row.get("remote_returncode") == 0
            for row in checks
        )
    )


def build_bundle(
    *,
    runbook: Dict[str, Any],
    packet: Dict[str, Any],
    preflight: Dict[str, Any],
    decision_state: Dict[str, Any],
    remote_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    commands = _portable_commands(runbook, packet)
    post = runbook.get("post_submit") if isinstance(runbook.get("post_submit"), dict) else {}
    postsubmit_driver_polling = post.get("postsubmit_driver_polling")
    if not isinstance(postsubmit_driver_polling, dict):
        postsubmit_driver_polling = {}
    post_approval_workflow = _post_approval_workflow(commands, postsubmit_driver_polling)
    approval_scope = _public_approval_scope(packet)
    remote_shell_syntax_ok = _shell_syntax_checks_ok(remote_readiness)
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
    if not _approval_scope_ok(approval_scope, packet):
        failures.append({
            "kind": "approval_scope_not_ready",
            "observed": approval_scope,
        })
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
    if remote_readiness.get("no_submit") is not True:
        failures.append({"kind": "remote_readiness_submit_drift", "observed": remote_readiness.get("no_submit")})
    if remote_readiness.get("can_claim_w2_generalization") is not False:
        failures.append({
            "kind": "remote_readiness_claim_boundary_drift",
            "observed": remote_readiness.get("can_claim_w2_generalization"),
        })
    if remote_readiness.get("n_failures") != 0:
        failures.append({"kind": "remote_readiness_failures_present", "observed": remote_readiness.get("n_failures")})
    if remote_shell_syntax_ok is not True:
        failures.append({
            "kind": "remote_readiness_shell_syntax_not_ok",
            "observed": {
                "n_shell_syntax_checks": remote_readiness.get("n_shell_syntax_checks"),
                "shell_syntax_checks_ok": remote_shell_syntax_ok,
            },
        })
    if not _strict_postsubmit_command_ok(commands.get("strict_postsubmit_status_before_sync"), packet):
        failures.append({
            "kind": "strict_postsubmit_command_not_portable_or_complete",
            "observed": commands.get("strict_postsubmit_status_before_sync"),
        })
    if not _post_approval_workflow_ok(post_approval_workflow):
        failures.append({
            "kind": "post_approval_workflow_not_complete",
            "observed": {
                "manual_step_count": post_approval_workflow.get("manual_step_count"),
                "all_manual_commands_present": post_approval_workflow.get("all_manual_commands_present"),
                "requires_sync_ready_before_record_sync": post_approval_workflow.get(
                    "requires_sync_ready_before_record_sync"
                ),
                "includes_postsync_interpretation": post_approval_workflow.get(
                    "includes_postsync_interpretation"
                ),
                "driver_command_present": post_approval_workflow.get("driver_command_present"),
                "driver_proceeds_only_when_sync_ready": post_approval_workflow.get(
                    "driver_proceeds_only_when_sync_ready"
                ),
            },
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
        "prerequisites": {
            "submission_decision": {
                "status": decision_state.get("status"),
                "audit_ok": decision_state.get("audit_ok"),
                "no_submit": decision_state.get("no_submit"),
                "submitted": decision_state.get("submitted"),
                "can_claim_w2_generalization": decision_state.get("can_claim_w2_generalization"),
            },
            "remote_readiness": {
                "status": remote_readiness.get("status"),
                "audit_ok": remote_readiness.get("audit_ok"),
                "no_submit": remote_readiness.get("no_submit"),
                "can_claim_w2_generalization": remote_readiness.get("can_claim_w2_generalization"),
                "n_exact_checks": remote_readiness.get("n_exact_checks"),
                "n_semantic_checks": remote_readiness.get("n_semantic_checks"),
                "n_absence_checks": remote_readiness.get("n_absence_checks"),
                "n_shell_syntax_checks": remote_readiness.get("n_shell_syntax_checks"),
                "shell_syntax_checks_ok": remote_shell_syntax_ok,
                "n_failures": remote_readiness.get("n_failures"),
            },
        },
        "target_contract": {
            "manifest": packet.get("manifest"),
            "target_alpha": packet.get("target_alpha"),
            "min_targets": (runbook.get("post_submit") or {}).get("min_targets")
            if isinstance(runbook.get("post_submit"), dict) else None,
            "min_records_per_target": (runbook.get("post_submit") or {}).get("min_records_per_target")
            if isinstance(runbook.get("post_submit"), dict) else None,
        },
        "approval_scope": approval_scope,
        "portable_commands": commands,
        "post_approval_workflow": post_approval_workflow,
        "postsubmit_driver_polling": postsubmit_driver_polling,
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
    workflow = rep.get("post_approval_workflow") if isinstance(rep.get("post_approval_workflow"), dict) else {}
    scope = rep.get("approval_scope") if isinstance(rep.get("approval_scope"), dict) else {}
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
        "## Approval Scope",
        "",
        f"- manifest: `{scope.get('manifest')}`",
        f"- targets: `{scope.get('n_ready_targets')}` ready of `{scope.get('n_targets')}` total",
        f"- target ids: `{', '.join(scope.get('target_ids') or [])}`",
        f"- planned designs: `{scope.get('planned_design_records')}` "
        f"({scope.get('records_per_target_planned')} per target)",
        f"- expected Slurm jobs: `{scope.get('expected_slurm_jobs')}` "
        f"(`{scope.get('job_pair_model')}` pairs)",
        f"- target alpha: `{scope.get('target_alpha')}`",
        "",
        "## Portable Commands",
        "",
    ]
    for key in (
        "setup_environment",
        "submit_if_explicitly_approved",
        "receipt_monitor_after_submit",
        "postsubmit_driver_after_submit",
        "job_state_query_after_receipt",
        "sync_job_state_probe_after_query",
        "strict_postsubmit_status_before_sync",
        "sync_back_after_sync_ready",
        "completion_after_sync",
        "postsync_replay",
    ):
        lines.extend([f"### {key}", "", "```bash", str(commands.get(key) or ""), "```", ""])
    lines.extend([
        "## Post-Approval Workflow",
        "",
        f"- manual step count: `{workflow.get('manual_step_count')}`",
        f"- all manual commands present: `{workflow.get('all_manual_commands_present')}`",
        f"- sync-ready gate before record sync: `{workflow.get('requires_sync_ready_before_record_sync')}`",
        f"- includes post-sync interpretation: `{workflow.get('includes_postsync_interpretation')}`",
        f"- driver proceeds only when sync-ready: `{workflow.get('driver_proceeds_only_when_sync_ready')}`",
        "",
    ])
    for step in workflow.get("manual_steps") or []:
        if isinstance(step, dict):
            lines.append(
                f"- {step.get('step')}. `{step.get('id')}` "
                f"(command present: `{step.get('command_present')}`)"
            )
    lines.append("")
    lines.extend([
        "## Postsubmit Driver Polling",
        "",
        "```text",
        json.dumps(rep.get("postsubmit_driver_polling") or {}, sort_keys=True),
        "```",
        "",
    ])
    prereqs = rep.get("prerequisites") if isinstance(rep.get("prerequisites"), dict) else {}
    remote = prereqs.get("remote_readiness") if isinstance(prereqs.get("remote_readiness"), dict) else {}
    lines.extend([
        "## Prerequisites",
        "",
        f"- remote readiness status: `{remote.get('status')}`",
        f"- remote exact checks: `{remote.get('n_exact_checks')}`",
        f"- remote shell syntax checks: `{remote.get('n_shell_syntax_checks')}`",
        f"- remote shell syntax checks ok: `{remote.get('shell_syntax_checks_ok')}`",
        f"- remote failures: `{remote.get('n_failures')}`",
        "",
    ])
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
