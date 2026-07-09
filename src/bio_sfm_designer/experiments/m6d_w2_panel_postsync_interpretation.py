"""Predeclare and audit W2 v11 post-sync panel interpretation.

This helper never submits jobs. It checks whether the post-submit status is
sync-ready, whether local panel records are present, and whether target-wise
panel interpretation already exists. It also emits a guarded replay script for
the future approved path: require sync-ready, sync records, run panel report,
refresh the decision protocol, then refresh this interpretation state.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
from typing import Any, Dict, List, Optional

from .complex_panel_completion import run_completion
from .m6d_w2_panel_decision_protocol import classify_panel_report


_DEFAULT_MANIFEST = "configs/m6d_w2_target_family_redesign_v11_representative_targets.json"
_DEFAULT_POSTSUBMIT = "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
_DEFAULT_JOB_STATES = "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
_DEFAULT_RECEIPT = "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl"
_DEFAULT_SUMMARY = "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json"
_DEFAULT_SYNC_BACK = "results/m6d_w2_target_family_redesign_v11_sync_back.sh"
_DEFAULT_COMPLETION_SCRIPT = "results/m6d_w2_target_family_redesign_v11_panel_completion.sh"
_DEFAULT_COMPLETION = "results/m6d_w2_target_family_redesign_v11_panel_completion.json"
_DEFAULT_PANEL_REPORT = "results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json"
_DEFAULT_DECISION_PROTOCOL = "results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json"
_DEFAULT_DECISION_PROTOCOL_MD = "results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.md"
_DEFAULT_SUBMIT_READY = "results/m6d_w2_target_family_redesign_v11_manifest_post_msa_require_files.json"
_DEFAULT_APPROVAL_PACKET = "results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json"
_DEFAULT_PANEL_LABEL = "W2 v11 Boltz-2 representative panel/protocol"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.md"
_DEFAULT_REPLAY = "results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _load_json_optional(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    return _load_json(path)


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str, *, executable: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if executable:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _records_from_manifest(manifest: Dict[str, Any]) -> List[str]:
    records = []
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or "target")
        out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
        record_path = str(target.get("records") or os.path.join(out_prefix, "records_boltz_complex.jsonl"))
        if record_path:
            records.append(record_path)
    return records


def _target_ids_from_manifest(manifest: Dict[str, Any]) -> List[str]:
    target_ids = []
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or "").strip()
        if target_id:
            target_ids.append(target_id)
    return target_ids


def _quote_paths(paths: List[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def render_replay_script(*,
                         manifest: str = _DEFAULT_MANIFEST,
                         postsubmit: str = _DEFAULT_POSTSUBMIT,
                         job_states: str = _DEFAULT_JOB_STATES,
                         receipt: str = _DEFAULT_RECEIPT,
                         summary: str = _DEFAULT_SUMMARY,
                         sync_back: str = _DEFAULT_SYNC_BACK,
                         panel_report: str = _DEFAULT_PANEL_REPORT,
                         decision_protocol: str = _DEFAULT_DECISION_PROTOCOL,
                         decision_protocol_md: str = _DEFAULT_DECISION_PROTOCOL_MD,
                         submit_ready: str = _DEFAULT_SUBMIT_READY,
                         approval_packet: str = _DEFAULT_APPROVAL_PACKET,
                         completion: str = _DEFAULT_COMPLETION,
                         completion_script: str = _DEFAULT_COMPLETION_SCRIPT,
                         out_json: str = _DEFAULT_OUT_JSON,
                         out_md: str = _DEFAULT_OUT_MD,
                         target_alpha: float = 0.2,
                         min_targets: int = 4,
                         min_records_per_target: int = 20,
                         panel_label: str = _DEFAULT_PANEL_LABEL,
                         records: Optional[List[str]] = None) -> str:
    record_args = _quote_paths(records or [])
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Replay W2 v11 post-sync completion, target-wise report, and decision interpretation.",
        "# This script does not submit jobs; it requires postsubmit sync-ready evidence first.",
        "set -euo pipefail",
        "PYTHON_BIN=\"${BIO_SFM_PYTHON:-${ENV_PY:-python3}}\"",
        "export PYTHONPATH=\"${PYTHONPATH:-src}\"",
        "export PYTHONNOUSERSITE=\"${PYTHONNOUSERSITE:-1}\"",
        f"MANIFEST={shlex.quote(manifest)}",
        f"RECEIPT={shlex.quote(receipt)}",
        f"SUMMARY={shlex.quote(summary)}",
        f"POSTSUBMIT={shlex.quote(postsubmit)}",
        f"JOB_STATES={shlex.quote(job_states)}",
        f"COMPLETION_SCRIPT={shlex.quote(completion_script)}",
        f"COMPLETION_REPORT={shlex.quote(completion)}",
        "test -s \"$MANIFEST\"",
        "test -s \"$RECEIPT\"",
        "test -s \"$SUMMARY\"",
        "test -s \"$POSTSUBMIT\"",
        "test -s \"$JOB_STATES\"",
        "test -s \"$COMPLETION_SCRIPT\"",
        (
            "\"$PYTHON_BIN\" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
            "--manifest \"$MANIFEST\" --receipt \"$RECEIPT\" --summary \"$SUMMARY\" "
            "--job-states \"$JOB_STATES\" --require-sync-ready --out-json \"$POSTSUBMIT\""
        ),
        f"bash {shlex.quote(sync_back)}",
        "BIO_SFM_PYTHON=\"$PYTHON_BIN\" PYTHONNOUSERSITE=1 bash \"$COMPLETION_SCRIPT\"",
        "test -s \"$COMPLETION_REPORT\"",
        (
            "\"$PYTHON_BIN\" -m bio_sfm_designer.experiments.complex_panel_report "
            f"--records {record_args} "
            f"--target-alpha {target_alpha} "
            f"--min-targets {min_targets} "
            f"--min-records-per-target {min_records_per_target} "
            f"--out {shlex.quote(panel_report)}"
        ),
        (
            "\"$PYTHON_BIN\" -m bio_sfm_designer.experiments.m6d_w2_panel_decision_protocol "
            f"--target-manifest {shlex.quote(manifest)} "
            f"--submit-ready {shlex.quote(submit_ready)} "
            f"--approval-packet {shlex.quote(approval_packet)} "
            f"--completion-report {shlex.quote(completion)} "
            f"--panel-report {shlex.quote(panel_report)} "
            f"--target-alpha {target_alpha} "
            f"--min-targets {min_targets} "
            f"--min-records-per-target {min_records_per_target} "
            f"--panel-label {shlex.quote(panel_label)} "
            f"--completion-script {shlex.quote(completion_script)} "
            f"--sync-back-script {shlex.quote(sync_back)} "
            f"--out-json {shlex.quote(decision_protocol)} "
            f"--out-md {shlex.quote(decision_protocol_md)}"
        ),
        (
            "\"$PYTHON_BIN\" -m bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation "
            f"--panel-label {shlex.quote(panel_label)} "
            f"--out-json {shlex.quote(out_json)} --out-md {shlex.quote(out_md)}"
        ),
        "",
    ])


def build_interpretation(*,
                         manifest_path: str = _DEFAULT_MANIFEST,
                         postsubmit_path: str = _DEFAULT_POSTSUBMIT,
                         completion_path: str = _DEFAULT_COMPLETION,
                         panel_report_path: str = _DEFAULT_PANEL_REPORT,
                         replay_script: str = _DEFAULT_REPLAY,
                         target_alpha: float = 0.2,
                         min_targets: int = 4,
                         min_records_per_target: int = 20,
                         panel_label: str = _DEFAULT_PANEL_LABEL) -> Dict[str, Any]:
    manifest = _load_json(manifest_path)
    postsubmit = _load_json_optional(postsubmit_path)
    completion_report = _load_json_optional(completion_path)
    panel_report = _load_json_optional(panel_report_path)
    records = _records_from_manifest(manifest)
    manifest_target_ids = _target_ids_from_manifest(manifest)
    failures: List[Dict[str, Any]] = []
    sync_ready = bool(isinstance(postsubmit, dict) and postsubmit.get("sync_ready") is True)
    completion_probe = run_completion(
        manifest_path,
        min_targets=min_targets,
        min_records_per_target=min_records_per_target,
        target_alpha=target_alpha,
        panel_out=panel_report_path,
        out_path=completion_path,
    )
    panel_result = classify_panel_report(
        panel_report,
        target_alpha=target_alpha,
        min_targets=min_targets,
        panel_label=panel_label,
        expected_target_ids=manifest_target_ids,
    )

    if panel_report is not None:
        if completion_report is None or completion_report.get("ok") is not True:
            failures.append({
                "kind": "panel_report_without_ready_completion",
                "message": "panel report exists without a ready completion artifact",
            })
        target_set_check = panel_result.get("target_set_check")
        if isinstance(target_set_check, dict) and target_set_check.get("ok") is not True:
            failures.append({
                "kind": "panel_report_target_set_mismatch",
                "message": "panel report target IDs must exactly match the representative manifest",
                "duplicate_target_ids": target_set_check.get("duplicate_target_ids") or [],
                "missing_target_ids": target_set_check.get("missing_target_ids") or [],
                "unexpected_target_ids": target_set_check.get("unexpected_target_ids") or [],
                "n_expected_targets": target_set_check.get("n_expected_targets"),
                "n_observed_rows": target_set_check.get("n_observed_rows"),
                "reported_n_targets": target_set_check.get("reported_n_targets"),
            })
        status = panel_result["status"]
        can_claim = panel_result["w2_generalization_supported"] is True and not failures
        next_action = panel_result.get("next_action", "inspect panel interpretation")
    elif sync_ready and completion_probe.get("ok") is True:
        status = "ready_for_target_wise_panel_report"
        can_claim = False
        next_action = f"run {replay_script} to generate target-wise panel report and refresh decision protocol"
    elif sync_ready:
        status = "sync_ready_records_missing_or_invalid"
        can_claim = False
        failures.extend(completion_probe.get("failures") or [])
        next_action = "run record sync-back or repair missing/malformed target records before panel report"
    else:
        status = "not_synced_not_interpretable"
        can_claim = False
        next_action = "await explicit approval, guarded submission, job completion, and sync-ready postsubmit status"

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_panel_postsync_interpretation",
        "status": status,
        "audit_ok": audit_ok,
        "no_submit": True,
        "submitted": bool(isinstance(postsubmit, dict) and postsubmit.get("submitted") is True),
        "sync_ready": sync_ready,
        "can_claim_w2_generalization": can_claim,
        "target_alpha": target_alpha,
        "panel_label": panel_label,
        "min_targets": min_targets,
        "min_records_per_target": min_records_per_target,
        "manifest": manifest_path,
        "postsubmit_status": postsubmit_path,
        "completion": completion_path,
        "panel_report": panel_report_path,
        "replay_script": replay_script,
        "records": records,
        "manifest_target_ids": manifest_target_ids,
        "completion_probe": {
            "status": completion_probe.get("status"),
            "ok": completion_probe.get("ok"),
            "n_completed_targets": completion_probe.get("n_completed_targets"),
            "n_manifest_targets": completion_probe.get("n_manifest_targets"),
            "n_failures": len(completion_probe.get("failures") or []),
        },
        "current_panel_result": panel_result,
        "failures": failures,
        "claim_boundary": "post-sync interpretation only; W2 claim requires target-wise multi_target_certified panel report",
        "next_action": next_action,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Post-Sync Interpretation",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        f"Sync ready: `{rep.get('sync_ready')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        f"- target alpha: `{rep.get('target_alpha')}`",
        f"- panel label: `{rep.get('panel_label')}`",
        f"- min targets: `{rep.get('min_targets')}`",
        f"- min records per target: `{rep.get('min_records_per_target')}`",
        f"- replay script: `{rep.get('replay_script')}`",
        "",
        "## Current Panel Result",
        "",
        f"- status: `{(rep.get('current_panel_result') or {}).get('status')}`",
        f"- W2 supported: `{(rep.get('current_panel_result') or {}).get('w2_generalization_supported')}`",
        "",
    ]
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
        lines.append("")
    lines.extend([
        "## Claim Boundary",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "## Next Action",
        "",
        str(rep.get("next_action") or ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=_DEFAULT_MANIFEST)
    ap.add_argument("--postsubmit-status", default=_DEFAULT_POSTSUBMIT)
    ap.add_argument("--job-states", default=_DEFAULT_JOB_STATES)
    ap.add_argument("--receipt", default=_DEFAULT_RECEIPT)
    ap.add_argument("--summary", default=_DEFAULT_SUMMARY)
    ap.add_argument("--sync-back", default=_DEFAULT_SYNC_BACK)
    ap.add_argument("--completion-script", default=_DEFAULT_COMPLETION_SCRIPT)
    ap.add_argument("--completion", default=_DEFAULT_COMPLETION)
    ap.add_argument("--panel-report", default=_DEFAULT_PANEL_REPORT)
    ap.add_argument("--decision-protocol", default=_DEFAULT_DECISION_PROTOCOL)
    ap.add_argument("--decision-protocol-md", default=_DEFAULT_DECISION_PROTOCOL_MD)
    ap.add_argument("--submit-ready", default=_DEFAULT_SUBMIT_READY)
    ap.add_argument("--approval-packet", default=_DEFAULT_APPROVAL_PACKET)
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--min-targets", type=int, default=4)
    ap.add_argument("--min-records-per-target", type=int, default=20)
    ap.add_argument("--panel-label", default=_DEFAULT_PANEL_LABEL)
    ap.add_argument("--emit-replay-script", default=_DEFAULT_REPLAY)
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    rep = build_interpretation(
        manifest_path=args.manifest,
        postsubmit_path=args.postsubmit_status,
        completion_path=args.completion,
        panel_report_path=args.panel_report,
        replay_script=args.emit_replay_script,
        target_alpha=args.target_alpha,
        min_targets=args.min_targets,
        min_records_per_target=args.min_records_per_target,
        panel_label=args.panel_label,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.emit_replay_script:
        manifest = _load_json(args.manifest)
        _write_text(
            args.emit_replay_script,
            render_replay_script(
                manifest=args.manifest,
                postsubmit=args.postsubmit_status,
                job_states=args.job_states,
                receipt=args.receipt,
                summary=args.summary,
                sync_back=args.sync_back,
                panel_report=args.panel_report,
                decision_protocol=args.decision_protocol,
                decision_protocol_md=args.decision_protocol_md,
                submit_ready=args.submit_ready,
                approval_packet=args.approval_packet,
                completion=args.completion,
                completion_script=args.completion_script,
                out_json=args.out_json,
                out_md=args.out_md,
                target_alpha=args.target_alpha,
                min_targets=args.min_targets,
                min_records_per_target=args.min_records_per_target,
                panel_label=args.panel_label,
                records=_records_from_manifest(manifest),
            ),
            executable=True,
        )
    print(
        "status={status} audit_ok={ok} sync_ready={sync} can_claim_w2={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            sync=rep["sync_ready"],
            claim=rep["can_claim_w2_generalization"],
        )
    )
    return 0 if rep.get("audit_ok") else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
