"""Predeclare a W2 post-panel decision protocol.

This helper is deliberately no-submit. It binds a representative
manifest, submit-ready report, and panel approval packet into a durable
decision protocol for what to do after a future explicitly approved
ProteinMPNN/Boltz panel run. The protocol keeps panel readiness separate from
W2 generalization evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set


_APPROVAL_READY_STATUS = "panel_approval_packet_ready"
_PROJECT_READY_STATUS = "post_panel_decision_protocol_ready"
_DEFAULT_PANEL_LABEL = "predeclared W2 Boltz-2 panel/protocol"


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


def _target_ids(manifest: Dict[str, Any]) -> List[str]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        return []
    ids = []
    for target in targets:
        if isinstance(target, dict) and isinstance(target.get("id"), str) and target["id"].strip():
            ids.append(target["id"].strip())
    return ids


def _record_paths(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or "").strip()
        records = str(target.get("records") or "").strip()
        if target_id and records:
            rows.append({"target_id": target_id, "records": records})
    return rows


def _as_set(values: Iterable[Any]) -> Set[str]:
    return {str(value) for value in values if str(value)}


def _target_set_check(targets: List[Dict[str, Any]],
                      expected_target_ids: Optional[Iterable[str]]) -> Dict[str, Any]:
    observed = sorted({
        str(row.get("complex_target_id")).strip()
        for row in targets
        if isinstance(row, dict) and str(row.get("complex_target_id") or "").strip()
    })
    if expected_target_ids is None:
        return {
            "expected_target_ids": None,
            "observed_target_ids": observed,
            "missing_target_ids": [],
            "unexpected_target_ids": [],
            "ok": True,
        }
    expected = sorted({str(target_id).strip() for target_id in expected_target_ids if str(target_id).strip()})
    expected_set = set(expected)
    observed_set = set(observed)
    return {
        "expected_target_ids": expected,
        "observed_target_ids": observed,
        "missing_target_ids": sorted(expected_set - observed_set),
        "unexpected_target_ids": sorted(observed_set - expected_set),
        "ok": expected_set == observed_set,
    }


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def _approval_ready(approval_packet: Dict[str, Any]) -> bool:
    checks = approval_packet.get("checks") if isinstance(approval_packet.get("checks"), dict) else {}
    required = (
        "target_msa_strict_ready",
        "panel_preflight_ready",
        "panel_dry_run_no_sbatch",
        "panel_guard_no_env_refuses",
        "submit_receipt_absent",
        "submit_summary_absent",
    )
    return (
        approval_packet.get("status") == _APPROVAL_READY_STATUS
        and approval_packet.get("approval_packet_ready") is True
        and approval_packet.get("can_submit_panel_if_user_explicitly_approves") is True
        and approval_packet.get("can_claim_w2_generalization") is False
        and all(checks.get(key) is True for key in required)
    )


def classify_panel_report(
    panel_report: Optional[Dict[str, Any]],
    *,
    target_alpha: float,
    min_targets: int,
    panel_label: str = _DEFAULT_PANEL_LABEL,
    expected_target_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(panel_report, dict):
        return {
            "status": "not_available_not_submitted",
            "w2_generalization_supported": False,
            "claim": "no W2 claim; panel records/report are not available",
            "next_action": "after explicit approved panel execution, sync records and run completion/report",
        }

    targets = panel_report.get("targets") if isinstance(panel_report.get("targets"), list) else []
    certified = [
        str(row.get("complex_target_id"))
        for row in targets
        if isinstance(row, dict) and row.get("certified") is True and row.get("complex_target_id")
    ]
    not_certified = [
        str(row.get("complex_target_id"))
        for row in targets
        if isinstance(row, dict) and row.get("certified") is not True and row.get("complex_target_id")
    ]
    target_set_check = _target_set_check(targets, expected_target_ids)
    alpha_matches = panel_report.get("target_alpha") == target_alpha
    target_count_ok = isinstance(panel_report.get("n_targets"), int) and panel_report["n_targets"] >= min_targets
    all_targets_certified = bool(targets) and len(certified) == len(targets)

    if not target_set_check["ok"]:
        return {
            "status": "panel_report_target_set_mismatch",
            "w2_generalization_supported": False,
            "certified_targets": certified,
            "not_certified_targets": not_certified,
            "target_set_check": target_set_check,
            "claim": "no W2 generalization claim; panel report targets do not match representative manifest",
            "next_action": "repair sync/report target-set contract before science interpretation",
        }

    if (
        panel_report.get("ok") is True
        and panel_report.get("panel_status") == "multi_target_certified"
        and alpha_matches
        and target_count_ok
        and all_targets_certified
        and not panel_report.get("failures")
    ):
        return {
            "status": "w2_generalization_supported_by_target_wise_panel",
            "w2_generalization_supported": True,
            "certified_targets": certified,
            "not_certified_targets": [],
            "target_set_check": target_set_check,
            "claim": f"W2 multi-target generalization is supported for the {panel_label}",
            "next_action": "preserve this as W2 evidence, then decide whether W3 robustness remains the limiting caveat",
        }

    if panel_report.get("panel_status") == "multi_target_evaluable_not_certified":
        return {
            "status": "w2_generalization_not_supported_target_wise",
            "w2_generalization_supported": False,
            "certified_targets": certified,
            "not_certified_targets": not_certified,
            "target_set_check": target_set_check,
            "claim": "no W2 generalization claim; any certified targets are target-specific only",
            "next_action": "diagnose certified versus failed targets and redesign the next W2 target/protocol branch",
        }

    return {
        "status": "panel_report_not_multi_target_proof",
        "w2_generalization_supported": False,
        "certified_targets": certified,
        "not_certified_targets": not_certified,
        "target_set_check": target_set_check,
        "claim": "no W2 generalization claim; repair panel/report contract before science interpretation",
        "next_action": "inspect panel report failures before spending or claiming",
    }


def build_protocol(
    *,
    target_manifest: Dict[str, Any],
    submit_ready: Dict[str, Any],
    approval_packet: Dict[str, Any],
    completion_report: Optional[Dict[str, Any]] = None,
    panel_report: Optional[Dict[str, Any]] = None,
    target_alpha: float = 0.2,
    min_targets: int = 14,
    min_records_per_target: int = 20,
    panel_label: str = _DEFAULT_PANEL_LABEL,
    completion_script: str = "results/m6d_w2_target_family_redesign_v9_completion.sh",
    sync_back_script: str = "results/m6d_w2_target_family_redesign_v9_sync_back.sh",
    completion_out: str = "results/m6d_w2_target_family_redesign_v9_completion.json",
    panel_report_out: str = "results/m6d_w2_target_family_redesign_v9_panel_report.json",
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    manifest_ids = _target_ids(target_manifest)
    submit_ids = submit_ready.get("target_ids") if isinstance(submit_ready.get("target_ids"), list) else []
    record_paths = _record_paths(target_manifest)

    if len(manifest_ids) < min_targets:
        _add_failure(
            failures,
            "too_few_manifest_targets",
            "representative manifest has fewer targets than the predeclared W2 panel minimum",
            observed=len(manifest_ids),
            expected=min_targets,
        )
    if len(record_paths) != len(manifest_ids):
        _add_failure(
            failures,
            "missing_manifest_record_paths",
            "every manifest target must have an expected records path before panel execution",
            observed=len(record_paths),
            expected=len(manifest_ids),
        )
    if submit_ready.get("ok") is not True:
        _add_failure(failures, "submit_ready_not_ok", "submit-ready report must pass before any panel protocol")
    if submit_ready.get("n_ready_targets") != len(manifest_ids):
        _add_failure(
            failures,
            "submit_ready_target_count_mismatch",
            "submit-ready target count must match representative manifest",
            observed=submit_ready.get("n_ready_targets"),
            expected=len(manifest_ids),
        )
    if submit_ids and _as_set(submit_ids) != _as_set(manifest_ids):
        _add_failure(
            failures,
            "submit_ready_target_ids_mismatch",
            "submit-ready target IDs must match representative manifest target IDs",
            observed=sorted(_as_set(submit_ids)),
            expected=sorted(_as_set(manifest_ids)),
        )
    if not _approval_ready(approval_packet):
        _add_failure(
            failures,
            "panel_approval_packet_not_ready_or_claim_drift",
            "panel approval packet must be ready while explicitly refusing any W2 claim",
            observed={
                "status": approval_packet.get("status"),
                "approval_packet_ready": approval_packet.get("approval_packet_ready"),
                "can_submit_panel_if_user_explicitly_approves": approval_packet.get(
                    "can_submit_panel_if_user_explicitly_approves"
                ),
                "can_claim_w2_generalization": approval_packet.get("can_claim_w2_generalization"),
            },
        )

    submit_receipt = approval_packet.get("submit_receipt")
    submit_summary = approval_packet.get("submit_summary")
    if isinstance(submit_receipt, str) and os.path.exists(submit_receipt):
        _add_failure(
            failures,
            "panel_submit_receipt_exists",
            "panel decision protocol is a pre-submit protocol; submit receipt already exists",
            path=submit_receipt,
        )
    if isinstance(submit_summary, str) and os.path.exists(submit_summary):
        _add_failure(
            failures,
            "panel_submit_summary_exists",
            "panel decision protocol is a pre-submit protocol; submit summary already exists",
            path=submit_summary,
        )

    completion_state = {
        "provided": isinstance(completion_report, dict),
        "status": completion_report.get("status") if isinstance(completion_report, dict) else "not_available_not_submitted",
        "ok": completion_report.get("ok") if isinstance(completion_report, dict) else False,
    }
    panel_result = classify_panel_report(
        panel_report,
        target_alpha=target_alpha,
        min_targets=min_targets,
        panel_label=panel_label,
        expected_target_ids=manifest_ids,
    )
    protocol_ready = not failures
    approval_env_var = approval_packet.get("panel_approval_env_var") or "panel approval env"
    approval_env_value = approval_packet.get("panel_approval_env_value") or "panel approval token"

    return {
        "artifact": "m6d_w2_panel_decision_protocol",
        "date": date.today().isoformat(),
        "status": _PROJECT_READY_STATUS if protocol_ready else "post_panel_decision_protocol_blocked",
        "audit_ok": protocol_ready,
        "no_submit": True,
        "can_submit_panel_if_user_explicitly_approves": (
            approval_packet.get("can_submit_panel_if_user_explicitly_approves") if protocol_ready else False
        ),
        "can_claim_w2_generalization_now": False,
        "claim_boundary": {
            "panel_approval_packet": "not approval and not evidence",
            "panel_submission": "requires explicit user approval env before any real submit",
            "panel_completion": "requires synced records for all manifest targets before report",
            "w2_multi_target_generalization": "not supported until target-wise panel certification passes",
            "pooled_diagnostic": "cannot override target-wise panel certification",
        },
        "inputs": {
            "target_manifest": target_manifest.get("_path"),
            "submit_ready": submit_ready.get("_path"),
            "approval_packet": approval_packet.get("_path"),
            "completion_report": completion_report.get("_path") if isinstance(completion_report, dict) else None,
            "panel_report": panel_report.get("_path") if isinstance(panel_report, dict) else None,
        },
        "panel_contract": {
            "panel_label": panel_label,
            "target_alpha": target_alpha,
            "min_targets": min_targets,
            "min_records_per_target": min_records_per_target,
            "n_manifest_targets": len(manifest_ids),
            "target_ids": manifest_ids,
            "expected_records": record_paths,
            "predictor_scope": "Boltz-2 complex panel only",
            "signal_source": "boltz2_pae_interaction",
            "label_source": "boltz2_lrmsd_to_reference",
        },
        "execution_sequence_if_explicitly_approved": [
            {
                "step": "submit_guarded_panel",
                "requires": f"explicit user approval plus {approval_env_var}={approval_env_value}",
                "command": approval_packet.get("submit_command_if_approved"),
            },
            {
                "step": "sync_back_after_jobs_finish",
                "requires": "all submitted ProteinMPNN/Boltz jobs finished",
                "command": approval_packet.get("sync_back_command_after_jobs_finish"),
            },
            {
                "step": "run_completion_gate",
                "requires": "records synced to every manifest records path",
                "command": f"BIO_SFM_PYTHON=/tmp/bio_sfm_science_venv/bin/python PYTHONNOUSERSITE=1 bash {completion_script}",
                "expected_output": completion_out,
            },
            {
                "step": "run_panel_report",
                "requires": "completion report status ready_for_panel_report",
                "expected_output": panel_report_out,
            },
        ],
        "decision_rules": [
            {
                "if": "completion blocks, records missing, bad JSONL, or complex_target_id mismatch",
                "then": "no W2 claim; repair sync/record contract before panel report",
            },
            {
                "if": "panel report is multi_target_certified at target_alpha with every target certified",
                "then": f"W2 generalization supported for the {panel_label}",
            },
            {
                "if": "panel report is evaluable but any target is not certified",
                "then": "no W2 generalization claim; certified targets, if any, are target-specific only",
            },
            {
                "if": "pooled diagnostic certifies but target-wise panel does not",
                "then": "treat pooled result as redesign diagnostic only, not W2 evidence",
            },
            {
                "if": "mixed predictor, mixed signal/label source, threshold mismatch, or missing target IDs appear",
                "then": "no W2 claim; repair provenance/contract before interpretation",
            },
        ],
        "current_completion_state": completion_state,
        "current_panel_result": panel_result,
        "next_action": (
            "await explicit user approval before guarded W2 panel submission"
            if protocol_ready
            else "repair protocol failures before any W2 panel approval"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Decision Protocol",
        "",
        f"Status: `{rep['status']}`.",
        f"Audit ok: `{rep['audit_ok']}`.",
        f"No submit: `{rep['no_submit']}`.",
        f"Can claim W2 generalization now: `{rep['can_claim_w2_generalization_now']}`.",
        "",
        "## Panel Contract",
        "",
    ]
    contract = rep["panel_contract"]
    lines.extend([
        f"- target_alpha: `{contract['target_alpha']}`",
        f"- panel_label: `{contract.get('panel_label')}`",
        f"- targets: `{contract['n_manifest_targets']}`",
        f"- min_records_per_target: `{contract['min_records_per_target']}`",
        f"- predictor_scope: `{contract['predictor_scope']}`",
        "",
        "## Decision Rules",
        "",
    ])
    for rule in rep["decision_rules"]:
        lines.append(f"- If {rule['if']}: {rule['then']}.")
    lines.extend(["", "## Current Panel Result", ""])
    result = rep["current_panel_result"]
    lines.extend([
        f"- status: `{result['status']}`",
        f"- W2 generalization supported: `{result['w2_generalization_supported']}`",
        f"- claim: {result['claim']}",
        "",
        "## Next Action",
        "",
        rep["next_action"],
        "",
    ])
    if rep.get("failures"):
        lines.extend(["## Failures", ""])
        for failure in rep["failures"]:
            lines.append(f"- {failure['kind']}: {failure['message']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="build no-submit W2 post-panel decision protocol")
    ap.add_argument("--target-manifest", default="configs/m6d_w2_target_family_redesign_v9_representative_targets.json")
    ap.add_argument("--submit-ready", default="results/m6d_w2_target_family_redesign_v9_submit_ready.json")
    ap.add_argument("--approval-packet", default="results/m6d_w2_target_family_redesign_v9_panel_approval_packet.json")
    ap.add_argument("--completion-report", default="results/m6d_w2_target_family_redesign_v9_completion.json")
    ap.add_argument("--panel-report", default="results/m6d_w2_target_family_redesign_v9_panel_report.json")
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--min-targets", type=int, default=14)
    ap.add_argument("--min-records-per-target", type=int, default=20)
    ap.add_argument("--panel-label", default=_DEFAULT_PANEL_LABEL)
    ap.add_argument("--completion-script", default="results/m6d_w2_target_family_redesign_v9_completion.sh")
    ap.add_argument("--sync-back-script", default="results/m6d_w2_target_family_redesign_v9_sync_back.sh")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_panel_decision_protocol.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_panel_decision_protocol.md")
    args = ap.parse_args(argv)

    completion_report = _load_json(args.completion_report) if os.path.exists(args.completion_report) else None
    panel_report = _load_json(args.panel_report) if os.path.exists(args.panel_report) else None
    rep = build_protocol(
        target_manifest=_load_json(args.target_manifest),
        submit_ready=_load_json(args.submit_ready),
        approval_packet=_load_json(args.approval_packet),
        completion_report=completion_report,
        panel_report=panel_report,
        target_alpha=args.target_alpha,
        min_targets=args.min_targets,
        min_records_per_target=args.min_records_per_target,
        panel_label=args.panel_label,
        completion_script=args.completion_script,
        sync_back_script=args.sync_back_script,
        completion_out=args.completion_report,
        panel_report_out=args.panel_report,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} no_submit={no_submit} can_claim_w2={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            no_submit=rep["no_submit"],
            claim=rep["can_claim_w2_generalization_now"],
        )
    )
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    if not rep["audit_ok"]:
        raise SystemExit(2)
    return rep


if __name__ == "__main__":
    main()
