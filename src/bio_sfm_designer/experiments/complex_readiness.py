"""Project-level readiness preflight for M6 complex/binder scale-up.

This module ties the narrow validators together before a Cayuga spend:
alpha-decision next-batch planning, multi-target manifest readiness,
second-predictor contract, and closed-loop batch readiness. It intentionally
delegates the scientific checks to the focused tools so this stays a
reproducible audit layer, not a second source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from typing import Any, Dict, Iterable, List, Optional

from .complex_next_batch_plan import (
    TargetPreflightError,
    build_next_batch_plan,
    render_plan_text as render_scale_plan_text,
)
from .complex_predictor_contract import validate_contract
from .complex_project_status import run_status
from .complex_target_manifest import render_hpc_plan, render_target_msa_plan, validate_manifest
from .run_batch_round import preflight_batch_round


_MAX_RENDERED_FAILURES = 20
_INPUT_PREP_FIELDS = {
    "source_pdb",
    "prepared_pdb",
    "target_fasta",
    "target_fasta_report",
    "target_msa",
    "target_msa_report",
    "prep_report",
}
_INPUT_PREP_FAILURE_KINDS = {
    "missing_file",
    "empty_file",
    "bad_target_fasta_report",
    "target_fasta_report_missing_field",
    "target_fasta_report_mismatch",
    "bad_target_msa_report",
    "target_msa_report_not_ok",
    "target_msa_report_missing_field",
    "target_msa_report_mismatch",
}
_PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _decision_from_manifest(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    manifest = _load_json(path)
    paths = manifest.get("paths")
    if isinstance(paths, dict):
        decision = paths.get("decision")
        if isinstance(decision, str) and decision.strip():
            return decision
    return None


def _check(name: str, status: str, ok: bool, required: bool, message: str,
           next_action: str, *, evidence: Optional[str] = None,
           details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "name": name,
        "status": status,
        "ok": ok,
        "required": required,
        "message": message,
        "next_action": next_action,
    }
    if evidence:
        out["evidence"] = os.path.abspath(evidence)
    if details is not None:
        out["details"] = details
    return out


def _missing(name: str, required: bool, message: str, next_action: str) -> Dict[str, Any]:
    status = "missing_required" if required else "not_requested"
    return _check(name, status, not required, required, message, next_action)


def _artifact_json(artifact: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in artifact.items() if k != "plan_text"}


def _append_option(parts: List[str], flag: str, value: Optional[Any]) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value:
        return
    parts.extend([flag, str(value)])


def _render_batch_round_plan(*, candidates_path: str, records_path: str,
                             verdicts_path: Optional[str], target: str,
                             objective: str, lam: float, assay_budget: int,
                             out_dir: str,
                             allow_missing_verdicts: bool,
                             prevalidate_records_paths: Iterable[str] = (),
                             conformal_alpha: Optional[float] = None,
                             conformal_delta: float = 0.1,
                             sync_back_plan: Optional[str] = None) -> str:
    parts = [
        "python", "-m", "bio_sfm_designer.experiments.run_batch_round",
        "--candidates", candidates_path,
        "--records", records_path,
        "--target", target,
        "--objective", objective,
        "--lam", str(lam),
        "--assay-budget", str(assay_budget),
        "--out", out_dir,
        "--strict-complex-records",
    ]
    if verdicts_path:
        parts.extend(["--verdicts", verdicts_path])
    if allow_missing_verdicts:
        parts.append("--allow-missing-verdicts")
    prevalidate_records = [str(path) for path in prevalidate_records_paths if str(path)]
    if prevalidate_records:
        parts.append("--prevalidate-records")
        parts.extend(prevalidate_records)
    if conformal_alpha is not None or prevalidate_records:
        _append_option(parts, "--conformal-alpha", conformal_alpha)
        _append_option(parts, "--conformal-delta", conformal_delta)
    _append_option(parts, "--emit-sync-back-plan", sync_back_plan)
    return "\n".join([
        "# W4 closed-loop DBTL consumer; writes <out>/preflight.json, campaign.jsonl, and summary.json.",
        shlex.join(parts),
    ])


def _readiness_command_from_args(args: argparse.Namespace) -> str:
    parts = ["python", "-m", "bio_sfm_designer.experiments.complex_readiness"]
    has_batch_context = any([
        args.batch_candidates,
        args.batch_records,
        args.batch_verdicts,
        args.batch_target,
        args.batch_prevalidate_records,
        args.batch_conformal_alpha is not None,
        args.allow_missing_batch_verdicts,
        args.require_batch_round,
        args.batch_preflight,
        args.batch_summary,
        args.batch_campaign,
        args.batch_sync_back_plan,
    ])
    _append_option(parts, "--decision", args.decision)
    _append_option(parts, "--posthoc-manifest", args.posthoc_manifest)
    _append_option(parts, "--target-manifest", args.target_manifest)
    _append_option(parts, "--input-prep-completion", args.input_prep_completion)
    _append_option(parts, "--scale-target-id", args.scale_target_id)
    if args.previous_records:
        parts.append("--previous-records")
        parts.extend(str(path) for path in args.previous_records)
    _append_option(parts, "--posthoc-out-dir", args.posthoc_out_dir)
    if args.require_files:
        parts.append("--require-files")
    _append_option(parts, "--min-contacts", args.min_contacts)
    if args.no_strict_qc:
        parts.append("--no-strict-qc")
    if getattr(args, "allow_unchecked_files", False):
        parts.append("--allow-unchecked-files")
    _append_option(parts, "--panel-min-targets", args.panel_min_targets)
    _append_option(parts, "--second-predictor-contract", args.second_predictor_contract)
    if args.run_second_record_qc:
        parts.append("--run-second-record-qc")
    if args.require_scale_plan:
        parts.append("--require-scale-plan")
    if args.require_panel_manifest:
        parts.append("--require-panel-manifest")
    if args.require_second_predictor:
        parts.append("--require-second-predictor")
    _append_option(parts, "--target-alpha", args.target_alpha)
    _append_option(parts, "--batch-candidates", args.batch_candidates)
    _append_option(parts, "--batch-records", args.batch_records)
    _append_option(parts, "--batch-verdicts", args.batch_verdicts)
    _append_option(parts, "--batch-target", args.batch_target)
    if has_batch_context:
        _append_option(parts, "--batch-objective", args.batch_objective)
        _append_option(parts, "--batch-lam", args.batch_lam)
        _append_option(parts, "--batch-assay-budget", args.batch_assay_budget)
        _append_option(parts, "--batch-out", args.batch_out)
    if args.batch_prevalidate_records:
        parts.append("--batch-prevalidate-records")
        parts.extend(str(path) for path in args.batch_prevalidate_records)
    if args.batch_conformal_alpha is not None or args.batch_prevalidate_records:
        _append_option(parts, "--batch-conformal-alpha", args.batch_conformal_alpha)
        _append_option(parts, "--batch-conformal-delta", args.batch_conformal_delta)
    if args.allow_missing_batch_verdicts:
        parts.append("--allow-missing-batch-verdicts")
    if args.require_batch_round:
        parts.append("--require-batch-round")
    _append_option(parts, "--batch-sync-back-plan", args.batch_sync_back_plan)
    _append_option(parts, "--batch-preflight", args.batch_preflight)
    _append_option(parts, "--batch-summary", args.batch_summary)
    _append_option(parts, "--batch-campaign", args.batch_campaign)
    _append_option(parts, "--out", args.out)
    _append_option(parts, "--emit-plan", args.emit_plan)
    _append_option(parts, "--emit-scale-plan", args.emit_scale_plan)
    return shlex.join(parts)


def _unavailable_scale_plan(rep: Dict[str, Any]) -> Dict[str, Any]:
    scale_check = next((check for check in rep.get("checks", [])
                        if check.get("name") == "scale_next_batch"), None)
    details = scale_check.get("details", {}) if isinstance(scale_check, dict) else {}
    out = {
        "ok": False,
        "action": "unavailable",
        "status": scale_check.get("status") if isinstance(scale_check, dict) else rep.get("status"),
        "readiness_status": rep.get("status"),
        "next_action": scale_check.get("next_action") if isinstance(scale_check, dict) else rep.get("next_action"),
        "message": scale_check.get("message") if isinstance(scale_check, dict) else "scale plan is not available",
        "reason": "scale_next_batch plan is not available until readiness is ready",
        "target_id": details.get("target_id") if isinstance(details, dict) else None,
        "target_alpha": rep.get("target_alpha"),
        "records": [],
        "new_records": [],
        "commands": [],
    }
    if rep.get("self_command"):
        out["readiness_command"] = rep["self_command"]
    if isinstance(scale_check, dict):
        out["scale_check"] = scale_check
    return out


def _failure_text(failure: Any) -> str:
    if not isinstance(failure, dict):
        return str(failure)
    kind = str(failure.get("kind", "failure"))
    target = failure.get("target_id")
    field = failure.get("field")
    message = str(failure.get("message", "")).strip()
    labels = [kind]
    if target is not None:
        labels.append(f"target={target}")
    if field is not None:
        labels.append(f"field={field}")
    if message:
        return f"{' '.join(labels)} -- {message}"
    return " ".join(labels)


def _check_failures(check: Dict[str, Any], *,
                    max_failures: int = _MAX_RENDERED_FAILURES) -> List[str]:
    details = check.get("details")
    if not isinstance(details, dict):
        return []
    failures = details.get("failures")
    if not isinstance(failures, list) or not failures:
        pending = details.get("pending_artifacts")
        if not isinstance(pending, list) or not pending:
            return []
        failures = [
            {
                "kind": artifact.get("error", "pending_artifact"),
                "target_id": artifact.get("target_id"),
                "field": artifact.get("field"),
                "path": artifact.get("path"),
            }
            for artifact in pending
            if isinstance(artifact, dict)
        ]
    lines = [_failure_text(failure) for failure in failures[:max_failures]]
    remaining = len(failures) - len(lines)
    if remaining > 0:
        lines.append(f"... {remaining} more failure(s); inspect the JSON report for the full list")
    return lines


def _science_claim_chunks(science_claims: Any) -> List[str]:
    if not isinstance(science_claims, dict):
        return []
    chunks = []
    for key in ("supported", "not_yet_supported", "planning_diagnostics", "decisive_next"):
        values = science_claims.get(key)
        if isinstance(values, list) and values:
            chunks.append(f"{key}={','.join(str(value) for value in values)}")
    return chunks


def _targets_by_id(manifest_path: str) -> Dict[str, Dict[str, Any]]:
    manifest = _load_json(manifest_path)
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        return {}
    out = {}
    for target in targets:
        if isinstance(target, dict) and target.get("id") is not None:
            out[str(target["id"])] = target
    return out


def _target_has_valid_rcsb_id(target: Dict[str, Any]) -> bool:
    value = target.get("rcsb_id")
    return isinstance(value, str) and bool(_PDB_ID_RE.fullmatch(value.strip()))


def _failure_field_map(failures: List[Any]) -> Dict[str, set]:
    by_target: Dict[str, set] = {}
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        target_id = failure.get("target_id")
        field = failure.get("field")
        if target_id is None or field is None:
            continue
        by_target.setdefault(str(target_id), set()).add(str(field))
    return by_target


def _input_prep_waiting(preflight_report: Dict[str, Any],
                        *,
                        manifest_path: Optional[str] = None) -> bool:
    failures = preflight_report.get("failures")
    if not isinstance(failures, list) or not failures:
        return False
    for failure in failures:
        if not isinstance(failure, dict):
            return False
        if failure.get("kind") not in _INPUT_PREP_FAILURE_KINDS:
            return False
        field = failure.get("field")
        if field not in _INPUT_PREP_FIELDS:
            return False
    if manifest_path is None:
        return False
    try:
        targets = _targets_by_id(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    by_target = _failure_field_map(failures)
    for target_id, failed_fields in by_target.items():
        target = targets.get(target_id)
        if target is None:
            return False
        source_configured = isinstance(target.get("source_pdb"), str) and bool(str(target.get("source_pdb")).strip())
        source_available_or_repairable = "source_pdb" not in failed_fields or _target_has_valid_rcsb_id(target)
        prepared_available_or_repairable = (
            "prepared_pdb" not in failed_fields
            or (source_configured and source_available_or_repairable)
        )
        prep_report_available_or_repairable = (
            "prep_report" not in failed_fields
            or (source_configured and source_available_or_repairable)
        )
        fasta_available_or_repairable = (
            "target_fasta" not in failed_fields
            or prepared_available_or_repairable
        )
        fasta_report_available_or_repairable = (
            "target_fasta_report" not in failed_fields
            or fasta_available_or_repairable
        )
        msa_available_or_repairable = (
            "target_msa" not in failed_fields
            or fasta_report_available_or_repairable
        )
        msa_report_available_or_repairable = (
            "target_msa_report" not in failed_fields
            or msa_available_or_repairable
        )
        if not all([
            source_available_or_repairable,
            prepared_available_or_repairable,
            prep_report_available_or_repairable,
            fasta_available_or_repairable,
            fasta_report_available_or_repairable,
            msa_available_or_repairable,
            msa_report_available_or_repairable,
        ]):
            return False
    return True


def _ordered_steps(checks: List[Dict[str, Any]], plans: Dict[str, Dict[str, Any]],
                   *, require_files: bool) -> List[Dict[str, Any]]:
    by_name = {check["name"]: check for check in checks}
    steps: List[Dict[str, Any]] = []

    def add(step_id: str, status: str, description: str, *,
            plan_section: Optional[str] = None,
            depends_on: Iterable[str] = ()) -> None:
        step: Dict[str, Any] = {
            "id": step_id,
            "status": status,
            "description": description,
            "depends_on": list(depends_on),
        }
        if plan_section:
            step["plan_section"] = plan_section
        steps.append(step)

    has_msa_plan = "target_msa_precompute" in plans
    if has_msa_plan:
        add(
            "target_msa_precompute",
            "available",
            "Run first when target .a3m/report files are missing; existing MSAs are validated and reports are refreshed locally.",
            plan_section="target_msa_precompute",
        )

    upstream = ["target_msa_precompute"] if has_msa_plan and require_files else []
    scale = by_name.get("scale_next_batch")
    if scale and scale["status"] != "not_requested":
        add(
            "scale_next_batch",
            scale["status"],
            scale["next_action"],
            plan_section="scale_next_batch" if "scale_next_batch" in plans else None,
            depends_on=upstream,
        )
        if scale["status"] == "ready":
            add(
                "scale_posthoc",
                "after_hpc",
                "After scale records are synced, run complex_scale_completion on the saved plan JSON, then run the posthoc command.",
                plan_section="scale_next_batch",
                depends_on=["scale_next_batch"],
            )

    panel = by_name.get("multi_target_manifest")
    if panel and panel["status"] != "not_requested":
        add(
            "multi_target_panel",
            panel["status"],
            panel["next_action"],
            plan_section="multi_target_panel" if "multi_target_panel" in plans else None,
            depends_on=upstream,
        )
        if panel["status"] == "ready":
            add(
                "panel_completion",
                "after_hpc",
                "After panel records are synced, run complex_panel_completion on the manifest before complex_panel_report.",
                depends_on=["multi_target_panel"],
            )

    second = by_name.get("second_predictor_contract")
    if second and second["status"] != "not_requested":
        add(
            "second_predictor_contract",
            second["status"],
            second["next_action"],
            plan_section="second_predictor" if "second_predictor" in plans else None,
        )
        if second["status"] == "ready":
            add(
                "cross_predictor_report",
                "after_contract",
                "Run the emitted cross-predictor command, then refresh complex_project_status.py with the report.",
                plan_section="second_predictor" if "second_predictor" in plans else None,
                depends_on=["second_predictor_contract"],
            )

    evidence_refresh_deps = {
        step["id"] for step in steps
        if (
            (step["id"] in {"scale_posthoc", "panel_completion"} and step["status"] == "after_hpc")
            or (step["id"] == "cross_predictor_report" and step["status"] == "after_contract")
        )
    }

    batch = by_name.get("closed_loop_batch")
    if batch and batch["status"] != "not_requested":
        add(
            "closed_loop_batch",
            batch["status"],
            batch["next_action"],
            plan_section="closed_loop_batch" if "closed_loop_batch" in plans else None,
            depends_on=sorted(evidence_refresh_deps),
        )

    refresh_deps = set(evidence_refresh_deps)
    if batch and batch["status"] == "ready":
        refresh_deps.add("closed_loop_batch")
    if refresh_deps:
        add(
            "project_status_refresh",
            "after_posthoc",
            "After posthoc, panel, cross-predictor, or batch artifacts are written, refresh complex_project_status.py.",
            depends_on=sorted(refresh_deps),
        )
    return steps


def _blocked_check_lines(rep: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for check in rep.get("checks", []):
        if check.get("ok") is True:
            continue
        failures = _check_failures(check)
        if not failures:
            continue
        lines.append(f"# {check['name']}: {check['status']}")
        for failure in failures:
            lines.append(f"# - {failure}")
        details = check.get("details")
        sync_back_plan = details.get("sync_back_plan") if isinstance(details, dict) else None
        if isinstance(sync_back_plan, str) and sync_back_plan.strip():
            lines.append(f"# sync_back: bash {sync_back_plan}")
    return lines


def render_plan_text(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6c complex/binder readiness plan",
        "# Review before Cayuga submission; generated by complex_readiness.py.",
        "set -euo pipefail",
        "",
        f"# readiness status={rep['status']} ok={rep['ok']}",
        f"# next_action={rep['next_action']}",
    ]
    claim_chunks = _science_claim_chunks(rep.get("posthoc_science_claims"))
    if claim_chunks:
        lines.append(f"# posthoc_science_claims={' '.join(claim_chunks)}")
        audit = rep.get("posthoc_science_claims_audit")
        if isinstance(audit, dict):
            lines.append(
                f"# posthoc_science_claims_audit={audit.get('status')} "
                f"ok={audit.get('ok')}"
            )
    lines.append("")
    if rep.get("ordered_steps"):
        lines.append("# ordered_steps")
        for i, step in enumerate(rep["ordered_steps"], 1):
            depends = ",".join(step.get("depends_on", [])) or "none"
            section = step.get("plan_section", "none")
            lines.append(
                f"# {i}. {step['id']} status={step['status']} "
                f"depends_on={depends} plan_section={section}"
            )
            lines.append(f"#    {step['description']}")
        lines.append("")
    if rep.get("self_command"):
        lines.extend([
            "# rerun_readiness_after_prep",
            f"# {rep['self_command']}",
            "",
        ])
    blocker_lines = _blocked_check_lines(rep)
    if blocker_lines:
        lines.append("# blockers")
        lines.extend(blocker_lines)
        lines.append("")
    for name, artifact in rep.get("plans", {}).items():
        plan_text = artifact.get("plan_text")
        if not plan_text:
            continue
        lines.extend([
            f"# --- {name} ---",
            plan_text.rstrip(),
            "",
        ])
    return "\n".join(lines)


def render_text(rep: Dict[str, Any]) -> str:
    lines = [
        f"# complex readiness  status={rep['status']} ok={rep['ok']}",
        f"next_action: {rep['next_action']}",
        "",
    ]
    claim_chunks = _science_claim_chunks(rep.get("posthoc_science_claims"))
    if claim_chunks:
        lines.append(f"posthoc_science_claims: {' '.join(claim_chunks)}")
        audit = rep.get("posthoc_science_claims_audit")
        if isinstance(audit, dict):
            lines.append(
                f"posthoc_science_claims_audit: {audit.get('status')} "
                f"ok={audit.get('ok')}"
            )
        lines.append("")
    if rep.get("ordered_steps"):
        lines.append("ordered_steps:")
        for i, step in enumerate(rep["ordered_steps"], 1):
            depends = ",".join(step.get("depends_on", [])) or "none"
            lines.append(
                f"{i}. {step['id']}: {step['status']} "
                f"(depends_on={depends})"
            )
            lines.append(f"   next: {step['description']}")
        lines.append("")
    for check in rep["checks"]:
        lines.append(
            f"- {check['name']}: {check['status']} "
            f"(ok={check['ok']} required={check['required']})"
        )
        lines.append(f"  next: {check['next_action']}")
        if check.get("message"):
            lines.append(f"  note: {check['message']}")
        failures = _check_failures(check)
        if failures:
            lines.append("  failures:")
            lines.extend(f"  - {failure}" for failure in failures)
    lines.append("")
    return "\n".join(lines)


def _resolve_decision(decision_path: Optional[str], posthoc_manifest_path: Optional[str]) -> Optional[str]:
    if decision_path:
        return decision_path
    inferred = _decision_from_manifest(posthoc_manifest_path)
    return inferred


def run_readiness(*, decision_path: Optional[str] = None,
                  posthoc_manifest_path: Optional[str] = None,
                  target_manifest_path: Optional[str] = None,
                  input_prep_completion_path: Optional[str] = None,
                  scale_target_id: Optional[str] = None,
                  previous_records: Iterable[str] = (),
                  posthoc_out_dir: str = "results/m6c_posthoc_next",
                  require_files: bool = False,
                  min_contacts: int = 1,
                  strict_qc: bool = True,
                  panel_min_targets: int = 3,
                  second_predictor_contract_path: Optional[str] = None,
                  run_second_record_qc: bool = False,
                  require_scale_plan: bool = False,
                  require_panel_manifest: bool = False,
                  require_second_predictor: bool = False,
                  batch_candidates_path: Optional[str] = None,
                  batch_records_path: Optional[str] = None,
                  batch_verdicts_path: Optional[str] = None,
                  batch_target: Optional[str] = None,
                  batch_objective: str = "interface_quality",
                  batch_lam: float = 0.5,
                  batch_assay_budget: int = 1000,
                  batch_out_dir: str = "results/round_0",
                  batch_prevalidate_records: Iterable[str] = (),
                  batch_conformal_alpha: Optional[float] = None,
                  batch_conformal_delta: float = 0.1,
                  allow_missing_batch_verdicts: bool = False,
                  require_batch_round: bool = False,
                  batch_sync_back_plan: Optional[str] = None,
                  batch_preflight_path: Optional[str] = None,
                  batch_summary_path: Optional[str] = None,
                  batch_campaign_path: Optional[str] = None,
                  target_alpha: float = 0.2) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    plans: Dict[str, Dict[str, Any]] = {}
    resolved_decision = _resolve_decision(decision_path, posthoc_manifest_path)
    batch_prevalidate_records = list(batch_prevalidate_records)

    try:
        status = run_status(
            posthoc_manifest_path=posthoc_manifest_path,
            decision_path=resolved_decision,
            input_prep_completion_path=input_prep_completion_path,
            batch_preflight_path=batch_preflight_path,
            batch_summary_path=batch_summary_path,
            batch_campaign_path=batch_campaign_path,
            target_alpha=target_alpha,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        status = {
            "ok": False,
            "status": "roadmap_status_failed",
            "complete": False,
            "next_action": f"fix roadmap status inputs: {exc}",
            "error": str(exc),
        }
    posthoc_science_claims = (
        status.get("posthoc_science_claims")
        if isinstance(status.get("posthoc_science_claims"), dict)
        else {}
    )
    posthoc_science_claims_audit = (
        status.get("posthoc_science_claims_audit")
        if isinstance(status.get("posthoc_science_claims_audit"), dict)
        else {"ok": True, "status": "not_applicable"}
    )

    requested_any = any([
        require_scale_plan,
        require_panel_manifest,
        require_second_predictor,
        bool(scale_target_id),
        bool(target_manifest_path),
        bool(input_prep_completion_path),
        bool(second_predictor_contract_path),
        require_batch_round,
        bool(batch_candidates_path),
        bool(batch_records_path),
        bool(batch_verdicts_path),
        bool(batch_target),
        bool(batch_prevalidate_records),
        batch_conformal_alpha is not None,
        bool(batch_preflight_path),
        bool(batch_summary_path),
        bool(batch_campaign_path),
    ])
    if target_manifest_path:
        try:
            msa_target_ids = [scale_target_id] if scale_target_id else None
            plans["target_msa_precompute"] = {
                "plan_text": render_target_msa_plan(target_manifest_path, target_ids=msa_target_ids),
                "target_ids": msa_target_ids,
            }
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    if status.get("ok") is not True:
        checks.append(_check(
            "roadmap_status",
            str(status.get("status") or "blocked"),
            False,
            True,
            "roadmap status refresh failed",
            str(status.get("next_action") or "fix roadmap status inputs, then rerun readiness"),
            details={"error": status.get("error")},
        ))

    if posthoc_science_claims_audit.get("ok") is False:
        checks.append(_check(
            "posthoc_science_claims",
            str(posthoc_science_claims_audit.get("status") or "blocked"),
            False,
            True,
            "posthoc manifest science-claim summary is not trustworthy",
            str(
                posthoc_science_claims_audit.get("next_action")
                or "regenerate the posthoc bundle and source M6c report"
            ),
            evidence=(
                posthoc_science_claims_audit.get("report_json")
                if isinstance(posthoc_science_claims_audit.get("report_json"), str)
                else posthoc_manifest_path
            ),
            details={
                "claims": posthoc_science_claims,
                "audit": posthoc_science_claims_audit,
            },
        ))

    if input_prep_completion_path:
        try:
            input_prep_completion = _load_json(input_prep_completion_path)
            input_prep_ready = (
                input_prep_completion.get("ok") is True
                and input_prep_completion.get("status") == "ready_for_require_files"
            )
            checks.append(_check(
                "input_prep_completion",
                "ready" if input_prep_ready else "blocked",
                input_prep_ready,
                True,
                (
                    f"{input_prep_completion.get('n_nonempty', 0)}/"
                    f"{input_prep_completion.get('n_artifacts', 0)} input-prep artifact(s) nonempty"
                ),
                (
                    "run manifest_command, then rerun readiness with --require-files"
                    if input_prep_ready else
                    "sync/fix pending_artifacts, then rerun complex_input_prep_completion.py"
                ),
                evidence=input_prep_completion_path,
                details={
                    "ready_targets": input_prep_completion.get("ready_targets", []),
                    "blocked_targets": input_prep_completion.get("blocked_targets", []),
                    "pending_artifacts": input_prep_completion.get("pending_artifacts", []),
                    "artifacts_by_target": input_prep_completion.get("artifacts_by_target", {}),
                    "manifest_command": input_prep_completion.get("manifest_command"),
                },
            ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append(_check(
                "input_prep_completion",
                "blocked",
                False,
                True,
                str(exc),
                "rerun complex_input_prep_completion.py after target input-prep files are synced",
                evidence=input_prep_completion_path,
            ))

    if require_scale_plan or scale_target_id:
        if not resolved_decision or not target_manifest_path or not scale_target_id:
            checks.append(_missing(
                "scale_next_batch",
                True,
                "scale planning needs --decision or --posthoc-manifest, --target-manifest, and --scale-target-id",
                "provide the missing scale-plan inputs before Cayuga submission",
            ))
        else:
            try:
                scale_plan = build_next_batch_plan(
                    manifest_path=target_manifest_path,
                    decision_path=resolved_decision,
                    target_id=scale_target_id,
                    previous_records=previous_records,
                    posthoc_out_dir=posthoc_out_dir,
                    require_files=require_files,
                    min_contacts=min_contacts,
                    strict_qc=strict_qc,
                )
                plans["scale_next_batch"] = {
                    "plan_text": scale_plan["plan_text"],
                    "plan_json": _artifact_json(scale_plan),
                    "records": scale_plan.get("records", []),
                    "new_records": scale_plan.get("new_records", []),
                    "posthoc_command": scale_plan.get("posthoc_command"),
                }
                action = scale_plan.get("action")
                if action == "run_scale_batch" and scale_plan.get("commands"):
                    checks.append(_check(
                        "scale_next_batch",
                        "ready",
                        True,
                        require_scale_plan,
                        f"rendered {len(scale_plan['commands'])} generate/predict command pair(s)",
                        "submit the emitted temp-specific Cayuga plan",
                        evidence=resolved_decision,
                        details={
                            "target_id": scale_plan.get("target_id"),
                            "target_alpha": scale_plan.get("target_alpha"),
                            "new_records": scale_plan.get("new_records", []),
                            "strict_qc": scale_plan.get("strict_qc"),
                        },
                    ))
                else:
                    checks.append(_check(
                        "scale_next_batch",
                        "not_needed",
                        True,
                        require_scale_plan,
                        f"decision action={action}; no scale commands emitted",
                        "follow the alpha decision instead of submitting a scale batch",
                        evidence=resolved_decision,
                    ))
            except TargetPreflightError as exc:
                report = exc.preflight_report
                waiting_on_input_prep = (
                    _input_prep_waiting(report, manifest_path=target_manifest_path)
                    and "target_msa_precompute" in plans
                )
                scale_status = "waiting_on_input_prep" if waiting_on_input_prep else "blocked"
                scale_next_action = (
                    "run the emitted target_msa_precompute input-prep plan, then rerun readiness with --require-files"
                    if waiting_on_input_prep else
                    "fix decision/manifest/preflight before Cayuga scale submission"
                )
                checks.append(_check(
                    "scale_next_batch",
                    scale_status,
                    False,
                    True,
                    str(exc),
                    scale_next_action,
                    evidence=target_manifest_path,
                    details={
                        "target_id": exc.target_id,
                        "input_prep_plan_available": waiting_on_input_prep,
                        "failures_by_kind": report.get("failures_by_kind", {}),
                        "failures": report.get("failures", []),
                        "n_targets": report.get("n_targets"),
                        "n_ready_targets": report.get("n_ready_targets"),
                        "ready_targets": report.get("ready_targets", []),
                        "target_ids": report.get("target_ids"),
                        "input_prep_artifacts": report.get("input_prep_artifacts", []),
                    },
                ))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                checks.append(_check(
                    "scale_next_batch",
                    "blocked",
                    False,
                    True,
                    str(exc),
                    "fix decision/manifest/preflight before Cayuga scale submission",
                    evidence=resolved_decision or target_manifest_path,
                ))
    else:
        checks.append(_missing(
            "scale_next_batch",
            False,
            "no scale target requested",
            "pass --scale-target-id with decision and target manifest when preparing the next alpha batch",
        ))

    run_panel_check = bool(target_manifest_path) and (require_panel_manifest or not scale_target_id)
    if run_panel_check:
        try:
            panel_report = validate_manifest(
                target_manifest_path,
                require_files=require_files,
                min_targets=panel_min_targets,
                min_contacts=min_contacts,
            )
            if panel_report["ok"]:
                plans["multi_target_panel"] = {"plan_text": render_hpc_plan(panel_report, target_manifest_path)}
                checks.append(_check(
                    "multi_target_manifest",
                    "ready",
                    True,
                    require_panel_manifest,
                    f"{panel_report['n_ready_targets']} ready target(s) for panel submission",
                    "run the emitted panel submit plan, then complex_panel_report.py",
                    evidence=target_manifest_path,
                    details={
                        "n_targets": panel_report.get("n_targets"),
                        "n_ready_targets": panel_report.get("n_ready_targets"),
                        "require_files": panel_report.get("require_files"),
                        "require_records": panel_report.get("require_records"),
                        "input_prep_artifacts": panel_report.get("input_prep_artifacts", []),
                    },
                ))
            else:
                waiting_on_input_prep = (
                    _input_prep_waiting(panel_report, manifest_path=target_manifest_path)
                    and "target_msa_precompute" in plans
                )
                panel_status = "waiting_on_input_prep" if waiting_on_input_prep else "blocked"
                panel_next_action = (
                    "run the emitted target_msa_precompute input-prep plan, then rerun readiness with --require-files"
                    if waiting_on_input_prep else
                    "fix target manifest/prep/MSA failures before panel spend"
                )
                checks.append(_check(
                    "multi_target_manifest",
                    panel_status,
                    False,
                    True,
                    json.dumps(panel_report.get("failures_by_kind", {}), sort_keys=True),
                    panel_next_action,
                    evidence=target_manifest_path,
                    details={
                        "input_prep_plan_available": waiting_on_input_prep,
                        "failures_by_kind": panel_report.get("failures_by_kind", {}),
                        "failures": panel_report.get("failures", []),
                        "input_prep_artifacts": panel_report.get("input_prep_artifacts", []),
                    },
                ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append(_check(
                "multi_target_manifest",
                "blocked",
                False,
                True,
                str(exc),
                "fix target manifest before panel spend",
                evidence=target_manifest_path,
            ))
    else:
        checks.append(_missing(
            "multi_target_manifest",
            require_panel_manifest,
            "no panel manifest check requested",
            "provide --target-manifest without --scale-target-id, or add --require-panel-manifest, to preflight the >=3-target panel",
        ))

    if second_predictor_contract_path:
        try:
            contract_report = validate_contract(
                second_predictor_contract_path,
                require_files=require_files,
                run_record_qc=run_second_record_qc,
            )
            plans["second_predictor"] = {"plan_text": contract_report["plan_text"]}
            if contract_report["ok"]:
                checks.append(_check(
                    "second_predictor_contract",
                    "ready",
                    True,
                    require_second_predictor,
                    f"contract validated for {contract_report['secondary_predictor']['predictor_id']}",
                    "run the emitted strict QC and cross-predictor commands after records are synced",
                    evidence=second_predictor_contract_path,
                    details={
                        "secondary_predictor": contract_report.get("secondary_predictor", {}),
                        "secondary_records": contract_report.get("secondary_records", []),
                    },
                ))
            else:
                checks.append(_check(
                    "second_predictor_contract",
                    "blocked",
                    False,
                    True,
                    json.dumps(contract_report.get("failures", []), sort_keys=True),
                    "fix the contract or second-predictor records before cross-predictor claims",
                    evidence=second_predictor_contract_path,
                    details={"failures": contract_report.get("failures", [])},
                ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append(_check(
                "second_predictor_contract",
                "blocked",
                False,
                True,
                str(exc),
                "fix the second-predictor contract before cross-predictor claims",
                evidence=second_predictor_contract_path,
            ))
    else:
        checks.append(_missing(
            "second_predictor_contract",
            require_second_predictor,
            "no second-predictor contract provided",
            "copy configs/template_second_predictor_contract.json once a real independent predictor is selected",
        ))

    run_batch_check = any([
        require_batch_round,
        bool(batch_candidates_path),
        bool(batch_records_path),
        bool(batch_verdicts_path),
        bool(batch_target),
    ])
    if run_batch_check:
        missing_inputs = []
        if not batch_candidates_path:
            missing_inputs.append("--batch-candidates")
        if not batch_records_path:
            missing_inputs.append("--batch-records")
        if not batch_target:
            missing_inputs.append("--batch-target")
        if missing_inputs:
            checks.append(_missing(
                "closed_loop_batch",
                True,
                "batch round planning needs " + ", ".join(missing_inputs),
                "provide synchronized candidates/records and a batch target before W4 routing",
            ))
        else:
            try:
                batch_preflight = preflight_batch_round(
                    batch_candidates_path,
                    batch_records_path,
                    verdicts_path=batch_verdicts_path,
                    require_verdict_coverage=not allow_missing_batch_verdicts,
                    strict_complex_records=True,
                    prevalidate_records_paths=batch_prevalidate_records,
                    lam=batch_lam,
                    conformal_alpha=batch_conformal_alpha,
                    conformal_delta=batch_conformal_delta,
                )
                if batch_preflight["ok"]:
                    plans["closed_loop_batch"] = {
                        "plan_text": _render_batch_round_plan(
                            candidates_path=batch_candidates_path,
                            records_path=batch_records_path,
                            verdicts_path=batch_verdicts_path,
                            target=batch_target,
                            objective=batch_objective,
                            lam=batch_lam,
                            assay_budget=batch_assay_budget,
                            out_dir=batch_out_dir,
                            allow_missing_verdicts=allow_missing_batch_verdicts,
                            prevalidate_records_paths=batch_prevalidate_records,
                            conformal_alpha=batch_conformal_alpha,
                            conformal_delta=batch_conformal_delta,
                            sync_back_plan=batch_sync_back_plan,
                        ),
                        "preflight": batch_preflight,
                    }
                    checks.append(_check(
                        "closed_loop_batch",
                        "ready",
                        True,
                        require_batch_round,
                        f"strict batch preflight covered {batch_preflight['n_candidates']} candidate(s)",
                        "run the emitted W4 batch command, then refresh complex_project_status.py with preflight/summary/campaign artifacts",
                        evidence=batch_candidates_path,
                        details={
                            "candidates": batch_candidates_path,
                            "records": batch_records_path,
                            "verdicts": batch_verdicts_path,
                            "out": batch_out_dir,
                            "n_candidates": batch_preflight.get("n_candidates"),
                            "n_records": batch_preflight.get("n_records"),
                            "n_verdicts": batch_preflight.get("n_verdicts"),
                            "strict_complex_records": batch_preflight.get("strict_complex_records"),
                            "gate_prevalidation": batch_preflight.get("gate_prevalidation"),
                            "sync_back_plan": batch_sync_back_plan,
                        },
                    ))
                else:
                    checks.append(_check(
                        "closed_loop_batch",
                        "blocked",
                        False,
                        True,
                        json.dumps(batch_preflight.get("failures", []), sort_keys=True),
                        "fix batch preflight failures before W4 routing",
                        evidence=batch_candidates_path,
                        details={
                            "candidates": batch_candidates_path,
                            "records": batch_records_path,
                            "verdicts": batch_verdicts_path,
                            "failures": batch_preflight.get("failures", []),
                            "pending_artifacts": batch_preflight.get("pending_artifacts", []),
                            "n_candidates": batch_preflight.get("n_candidates"),
                            "n_records": batch_preflight.get("n_records"),
                            "n_verdicts": batch_preflight.get("n_verdicts"),
                            "sync_back_plan": batch_sync_back_plan,
                        },
                    ))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                checks.append(_check(
                    "closed_loop_batch",
                    "blocked",
                    False,
                    True,
                    str(exc),
                    "fix synchronized candidates/records/verdicts before W4 routing",
                    evidence=batch_candidates_path or batch_records_path,
                ))
    else:
        checks.append(_missing(
            "closed_loop_batch",
            require_batch_round,
            "no W4 batch-round check requested",
            "pass --batch-candidates, --batch-records, --batch-verdicts, and --batch-target after synced artifacts exist",
        ))

    run_batch_artifact_check = any([
        bool(batch_preflight_path),
        bool(batch_summary_path),
        bool(batch_campaign_path),
    ])
    if run_batch_artifact_check:
        workstreams = status.get("workstreams") if isinstance(status, dict) else None
        w4 = workstreams.get("W4_closed_loop_DBTL") if isinstance(workstreams, dict) else None
        if isinstance(w4, dict):
            complete = bool(w4.get("complete"))
            checks.append(_check(
                "closed_loop_artifacts",
                str(w4.get("status", "unknown")),
                complete,
                not complete,
                str(w4.get("message", f"W4 status={w4.get('status')}")),
                str(w4.get("next_action", "inspect W4 batch artifacts")),
                evidence=w4.get("evidence") or batch_summary_path or batch_preflight_path,
                details={
                    "preflight": w4.get("preflight") or batch_preflight_path,
                    "summary": w4.get("summary") or batch_summary_path,
                    "campaign": w4.get("campaign") or batch_campaign_path,
                    "n_candidates": w4.get("n_candidates"),
                    "n_routed": w4.get("n_routed"),
                    "failures": w4.get("failures", []),
                },
            ))
        else:
            checks.append(_check(
                "closed_loop_artifacts",
                "blocked",
                False,
                True,
                status.get("next_action", "roadmap status did not include W4") if isinstance(status, dict)
                else "roadmap status did not include W4",
                "fix W4 project-status artifact inputs before treating the closed loop as complete",
                evidence=batch_summary_path or batch_preflight_path,
            ))
    else:
        checks.append(_missing(
            "closed_loop_artifacts",
            False,
            "no W4 batch artifacts supplied for roadmap-status refresh",
            "pass --batch-preflight and --batch-summary after run_batch_round.py writes them",
        ))

    if not requested_any:
        checks.append(_check(
            "readiness_inputs",
            "missing_required",
            False,
            True,
            "no readiness checks were requested",
            "provide at least one of --scale-target-id, --target-manifest, --second-predictor-contract, or --batch-candidates/--batch-records",
        ))

    ok = all(check["ok"] for check in checks)
    if ok:
        overall = "ready"
        next_action = "review the emitted plan sections, then run the relevant Cayuga or local commands"
    else:
        failed_statuses = {check.get("status") for check in checks if check.get("ok") is not True}
        overall = "waiting_on_input_prep" if failed_statuses == {"waiting_on_input_prep"} else "blocked"
        next_action = next((check["next_action"] for check in checks if not check["ok"]), "inspect readiness checks")
    rep = {
        "ok": ok,
        "status": overall,
        "next_action": next_action,
        "require_files": require_files,
        "strict_qc": strict_qc,
        "target_alpha": target_alpha,
        "resolved_decision": os.path.abspath(resolved_decision) if resolved_decision else None,
        "roadmap_status": status,
        "posthoc_science_claims": posthoc_science_claims,
        "posthoc_science_claims_audit": posthoc_science_claims_audit,
        "checks": checks,
        "plans": plans,
    }
    rep["ordered_steps"] = _ordered_steps(checks, plans, require_files=require_files)
    rep["plan_text"] = render_plan_text(rep)
    return rep


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="preflight M6c complex/binder readiness before Cayuga spend")
    ap.add_argument("--decision", default=None, help="complex_alpha_decision.json")
    ap.add_argument("--posthoc-manifest", default=None,
                    help="posthoc bundle manifest; used to infer the decision path when --decision is omitted")
    ap.add_argument("--target-manifest", default=None,
                    help="complex target manifest for scale or panel planning")
    ap.add_argument("--input-prep-completion", default=None,
                    help="complex_input_prep_completion.py JSON report to include in roadmap status")
    ap.add_argument("--scale-target-id", default=None,
                    help="target id to render the next alpha-tightening batch for")
    ap.add_argument("--previous-records", nargs="*", default=[],
                    help="records already included in the alpha decision, for follow-up posthoc command")
    ap.add_argument("--posthoc-out-dir", default="results/m6c_posthoc_next")
    ap.add_argument("--require-files", action="store_true",
                    help="require referenced target/record files to exist where applicable")
    ap.add_argument("--min-contacts", type=int, default=1)
    ap.add_argument("--no-strict-qc", action="store_true",
                    help="legacy escape hatch for scale planning; not for real claims")
    ap.add_argument("--allow-unchecked-files", action="store_true",
                    help="diagnostic escape hatch: allow saving a runnable scale plan without --require-files")
    ap.add_argument("--panel-min-targets", type=int, default=3)
    ap.add_argument("--second-predictor-contract", default=None)
    ap.add_argument("--run-second-record-qc", action="store_true",
                    help="run strict QC on second-predictor records from the contract")
    ap.add_argument("--require-scale-plan", action="store_true")
    ap.add_argument("--require-panel-manifest", action="store_true")
    ap.add_argument("--require-second-predictor", action="store_true")
    ap.add_argument("--batch-candidates", default=None,
                    help="W4 candidates JSONL synced from the generate stage")
    ap.add_argument("--batch-records", default=None,
                    help="W4 structure records JSONL synced from the predict stage")
    ap.add_argument("--batch-verdicts", default=None,
                    help="optional W4 screen verdicts JSONL")
    ap.add_argument("--batch-target", default=None,
                    help="run_batch_round.py --target text for the closed-loop batch")
    ap.add_argument("--batch-objective", default="interface_quality")
    ap.add_argument("--batch-lam", type=float, default=0.5)
    ap.add_argument("--batch-assay-budget", type=int, default=1000)
    ap.add_argument("--batch-out", default="results/round_0")
    ap.add_argument("--batch-prevalidate-records", nargs="*", default=[],
                    help="prior verified records JSONL used to prevalidate the W4 gate")
    ap.add_argument("--batch-conformal-alpha", type=float, default=None,
                    help="optional RCPS false-accept target for the W4 prevalidated gate")
    ap.add_argument("--batch-conformal-delta", type=float, default=0.1)
    ap.add_argument("--allow-missing-batch-verdicts", action="store_true",
                    help="diagnostic W4 escape hatch mirroring run_batch_round.py")
    ap.add_argument("--require-batch-round", action="store_true")
    ap.add_argument("--batch-sync-back-plan", default=None,
                    help="run_batch_round.py --emit-sync-back-plan path for W4 missing batch JSONLs")
    ap.add_argument("--batch-preflight", default=None,
                    help="existing run_batch_round.py preflight.json artifact for roadmap status")
    ap.add_argument("--batch-summary", default=None,
                    help="existing run_batch_round.py summary.json artifact for roadmap status")
    ap.add_argument("--batch-campaign", default=None,
                    help="optional existing campaign.jsonl path for roadmap status")
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--out", default=None, help="optional JSON readiness report")
    ap.add_argument("--emit-plan", default=None, help="optional shell readiness plan")
    ap.add_argument("--emit-scale-plan", default=None,
                    help="optional JSON next-batch plan for later complex_scale_completion --plan")
    args = ap.parse_args(argv)

    try:
        rep = run_readiness(
            decision_path=args.decision,
            posthoc_manifest_path=args.posthoc_manifest,
            target_manifest_path=args.target_manifest,
            input_prep_completion_path=args.input_prep_completion,
            scale_target_id=args.scale_target_id,
            previous_records=args.previous_records,
            posthoc_out_dir=args.posthoc_out_dir,
            require_files=args.require_files,
            min_contacts=args.min_contacts,
            strict_qc=not args.no_strict_qc,
            panel_min_targets=args.panel_min_targets,
            second_predictor_contract_path=args.second_predictor_contract,
            run_second_record_qc=args.run_second_record_qc,
            require_scale_plan=args.require_scale_plan,
            require_panel_manifest=args.require_panel_manifest,
            require_second_predictor=args.require_second_predictor,
            batch_candidates_path=args.batch_candidates,
            batch_records_path=args.batch_records,
            batch_verdicts_path=args.batch_verdicts,
            batch_target=args.batch_target,
            batch_objective=args.batch_objective,
            batch_lam=args.batch_lam,
            batch_assay_budget=args.batch_assay_budget,
            batch_out_dir=args.batch_out,
            batch_prevalidate_records=args.batch_prevalidate_records,
            batch_conformal_alpha=args.batch_conformal_alpha,
            batch_conformal_delta=args.batch_conformal_delta,
            allow_missing_batch_verdicts=args.allow_missing_batch_verdicts,
            require_batch_round=args.require_batch_round,
            batch_sync_back_plan=args.batch_sync_back_plan,
            batch_preflight_path=args.batch_preflight,
            batch_summary_path=args.batch_summary,
            batch_campaign_path=args.batch_campaign,
            target_alpha=args.target_alpha,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex readiness failed: {exc}", file=sys.stderr)
        sys.exit(2)

    rep["self_command"] = _readiness_command_from_args(args)
    scale_json_to_write = None
    scale_check = next((check for check in rep.get("checks", [])
                        if check.get("name") == "scale_next_batch"), None)
    scale = rep.get("plans", {}).get("scale_next_batch")
    scale_json = scale.get("plan_json") if isinstance(scale, dict) else None
    saving_artifacts = bool(args.out or args.emit_plan or args.emit_scale_plan)
    if saving_artifacts and isinstance(scale_json, dict) and scale_json.get("action") == "run_scale_batch":
        if not args.require_files and not args.allow_unchecked_files:
            print(
                "saving readiness artifacts with a runnable scale plan requires --require-files; "
                "use --allow-unchecked-files only for legacy diagnostics",
                file=sys.stderr,
            )
            sys.exit(2)
        if not args.require_files and args.allow_unchecked_files:
            scale_json["diagnostic_only"] = True
            scale_json["unchecked_files_allowed"] = True
            scale_json["diagnostic_reason"] = "saved without --require-files via --allow-unchecked-files"
            if isinstance(scale, dict):
                scale["plan_json"] = scale_json
                scale["plan_text"] = render_scale_plan_text(scale_json)
    rep["plan_text"] = render_plan_text(rep)
    if args.emit_scale_plan:
        if not isinstance(scale_check, dict) or scale_check.get("status") == "not_requested":
            print(
                "--emit-scale-plan requires --scale-target-id or --require-scale-plan; "
                "not overwriting the scale-plan path because no scale check was requested",
                file=sys.stderr,
            )
            sys.exit(2)
        if not isinstance(scale_json, dict):
            scale_json = _unavailable_scale_plan(rep)
        scale_json_to_write = scale_json

    print(render_text(rep))
    if args.out:
        with open(args.out, "w") as fh:
            obj = {k: v for k, v in rep.items() if k != "plan_text"}
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.emit_plan:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_plan)) or ".", exist_ok=True)
        with open(args.emit_plan, "w") as fh:
            fh.write(rep["plan_text"])
        print(f"wrote {args.emit_plan}")
    if args.emit_scale_plan:
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_scale_plan)) or ".", exist_ok=True)
        with open(args.emit_scale_plan, "w") as fh:
            json.dump(scale_json_to_write, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.emit_scale_plan}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
