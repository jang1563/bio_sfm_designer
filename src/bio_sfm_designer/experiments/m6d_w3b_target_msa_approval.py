"""Build the hash-bound, no-submit W3b target-MSA approval packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional


_APPROVAL_ENV = "BIO_SFM_APPROVE_W3B_TARGET_MSA"
_APPROVAL_TOKEN = "approve-w3b-target-msa-precompute"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failure(failures: List[Dict[str, Any]], kind: str, message: str) -> None:
    failures.append({"kind": kind, "message": message})


def build_packet(
    protocol: Dict[str, Any],
    manifest: Dict[str, Any],
    selection: Dict[str, Any],
    design_gate: Dict[str, Any],
    *,
    bindings: Dict[str, str],
    wrapper_path: str,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    target_rows = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    target_ids = [str(row.get("id") or "") for row in target_rows]
    missing_msa = [
        str(row.get("id") or "")
        for row in target_rows
        if not isinstance(row.get("target_msa"), str)
        or not os.path.isfile(str(row["target_msa"]))
        or not isinstance(row.get("target_msa_report"), str)
        or not os.path.isfile(str(row["target_msa_report"]))
    ]
    if protocol.get("status") != "w3b_disagreement_gate_preregistered_no_submit":
        _failure(failures, "protocol_status_invalid", "W3b protocol is not at the preregistered no-submit state")
    execution = protocol.get("execution_state", {})
    approval = execution.get("target_msa_precompute", {})
    if execution.get("no_submit") is not True or execution.get("cayuga_submission_allowed") is not False:
        _failure(failures, "protocol_execution_boundary_invalid", "W3b protocol must remain no-submit")
    if approval.get("approval_env_var") != _APPROVAL_ENV or approval.get("approval_env_value") != _APPROVAL_TOKEN:
        _failure(failures, "approval_token_mismatch", "protocol approval identity differs from the guarded wrapper")
    if approval.get("approval_recorded") is not False:
        _failure(failures, "approval_already_recorded", "approval packet must be generated before approval is recorded")
    if approval.get("approval_packet_ready") is not True or approval.get("command_wrapper_emitted") is not True:
        _failure(failures, "msa_packet_state_invalid", "MSA packet and guarded wrapper must be recorded as ready")
    if approval.get("command_wrapper") != wrapper_path or approval.get("plan") != bindings.get("plan"):
        _failure(failures, "msa_execution_path_mismatch", "protocol MSA wrapper or plan path differs from the packet")
    if float(approval.get("maximum_a40_gpu_hours") or 0.0) != 8.0:
        _failure(failures, "msa_budget_invalid", "target-MSA approval must remain capped at 8 A40 GPU-hours")
    if design_gate.get("audit_ok") is not True or design_gate.get("design_power_qualified") is not True:
        _failure(failures, "design_gate_not_qualified", "W3b design/power audit must pass before MSA approval")
    if design_gate.get("inputs_ready") is not False or design_gate.get("execution_ready") is not False:
        _failure(failures, "design_gate_readiness_invalid", "MSA packet is only for the input-incomplete state")
    if design_gate.get("fresh_target_contract", {}).get("missing_target_msa_targets") != missing_msa:
        _failure(failures, "missing_msa_set_mismatch", "manifest and design gate disagree on missing target MSAs")
    if selection.get("selected_target_ids") != target_ids:
        _failure(failures, "selection_manifest_target_mismatch", "selection and manifest target order differ")
    if selection.get("label_data_consumed") is not False or selection.get("predictor_records_consumed") is not False:
        _failure(failures, "selection_consumed_outcomes", "target selection must remain label-blind")
    if len(target_ids) != 8 or len(set(target_ids)) != 8 or len(missing_msa) != 8:
        _failure(failures, "target_count_invalid", "approval scope must be exactly eight missing target MSAs")

    wrapper_text = open(wrapper_path).read() if os.path.isfile(wrapper_path) else ""
    if not wrapper_text:
        _failure(failures, "wrapper_missing", "guarded W3b target-MSA wrapper is missing")
    if _APPROVAL_ENV not in wrapper_text or _APPROVAL_TOKEN not in wrapper_text:
        _failure(failures, "wrapper_approval_guard_missing", "wrapper lacks the exact approval guard")
    for forbidden in ("generate_proteinmpnn", "run_predict_boltz", "colabfold_batch"):
        if forbidden in wrapper_text:
            _failure(failures, "wrapper_scope_expanded", f"wrapper contains forbidden execution surface: {forbidden}")

    bound_artifacts: Dict[str, Dict[str, str]] = {}
    for name, path in bindings.items():
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            _failure(failures, f"{name}_missing", f"bound artifact is missing: {path}")
            continue
        bound_artifacts[name] = {"path": path, "sha256": _sha256(path)}
    if wrapper_text:
        for name, binding in bound_artifacts.items():
            marker = f'EXPECTED_{name.upper()}_SHA256="{binding["sha256"]}"'
            if marker not in wrapper_text:
                _failure(failures, f"wrapper_{name}_hash_mismatch", f"wrapper does not bind current {name} hash")
        if not re.search(r'^PLAN="results/m6d_w3b_target_msas\.sh"$', wrapper_text, re.MULTILINE):
            _failure(failures, "wrapper_plan_path_invalid", "wrapper does not use the frozen W3b MSA plan")

    ready = not failures
    return {
        "artifact": "m6d_w3b_target_msa_approval_packet",
        "approval_packet_ready": ready,
        "bound_artifacts": bound_artifacts,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "can_submit_target_msa_if_explicitly_approved": ready,
        "claim_boundary": (
            "Approval covers exactly eight target-MSA input-prep jobs, capped at 8 A40 GPU-hours. "
            "It does not authorize candidate generation, candidate-level Boltz/AF2 prediction, or a W3b claim."
        ),
        "explicit_approval_required": True,
        "failures": failures,
        "maximum_a40_gpu_hours": 8.0,
        "missing_target_msa_targets": missing_msa,
        "no_submit": True,
        "status": "awaiting_explicit_w3b_target_msa_approval" if ready else "w3b_target_msa_approval_packet_blocked",
        "submit_command_if_approved": (
            f"{_APPROVAL_ENV}={_APPROVAL_TOKEN} bash {wrapper_path}"
        ),
        "target_count": len(target_ids),
        "target_ids": target_ids,
        "target_msa_approval_env_value": _APPROVAL_TOKEN,
        "target_msa_approval_env_var": _APPROVAL_ENV,
        "wrapper": {"path": wrapper_path, "sha256": _sha256(wrapper_path) if wrapper_text else None},
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3b Target-MSA Approval Packet",
        "",
        f"Status: `{report['status']}`.",
        f"Approval packet ready: `{report['approval_packet_ready']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- targets: `{report['target_count']}`",
        f"- maximum A40 GPU-hours: `{report['maximum_a40_gpu_hours']}`",
        "- candidate generation or candidate-level prediction allowed: "
        f"`{report['can_submit_candidate_generation_or_candidate_level_prediction']}`",
        "",
        "Command only after explicit approval:",
        "",
        "```bash",
        report["submit_command_if_approved"],
        "```",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- `{row['kind']}`: {row['message']}" for row in report["failures"])
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
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--selection", default="results/m6d_w3b_target_selection.json")
    parser.add_argument("--design-gate", default="results/m6d_w3b_disagreement_design_gate.json")
    parser.add_argument("--plan", default="results/m6d_w3b_target_msas.sh")
    parser.add_argument("--precompute-sbatch", default="hpc/run_precompute_boltz_target_msa.sbatch")
    parser.add_argument("--precompute-python", default="hpc/precompute_boltz_target_msa.py")
    parser.add_argument("--prep-heterodimer", default="hpc/prep_hetdimer.py")
    parser.add_argument("--extract-chain-fasta", default="hpc/extract_chain_fasta.py")
    parser.add_argument(
        "--lifecycle",
        default="src/bio_sfm_designer/experiments/m6d_w3b_target_msa_lifecycle.py",
    )
    parser.add_argument(
        "--manifest-validator",
        default="src/bio_sfm_designer/experiments/complex_target_manifest.py",
    )
    parser.add_argument(
        "--execution-lock-tool",
        default="src/bio_sfm_designer/experiments/m6d_w3b_execution_lock.py",
    )
    parser.add_argument("--job-state-query", default="results/m6d_w3b_target_msa_job_state_query.sh")
    parser.add_argument("--sync-back", default="results/m6d_w3b_target_msa_sync_back.sh")
    parser.add_argument("--wrapper", default="hpc/run_w3b_target_msa_guarded.sh")
    parser.add_argument("--out-json", default="results/m6d_w3b_target_msa_approval_packet.json")
    parser.add_argument("--out-md", default="results/m6d_w3b_target_msa_approval_packet.md")
    args = parser.parse_args(argv)
    bindings = {
        "manifest": args.manifest,
        "protocol": args.protocol,
        "selection": args.selection,
        "design_gate": args.design_gate,
        "plan": args.plan,
        "precompute_sbatch": args.precompute_sbatch,
        "precompute_python": args.precompute_python,
        "prep_heterodimer": args.prep_heterodimer,
        "extract_chain_fasta": args.extract_chain_fasta,
        "lifecycle": args.lifecycle,
        "manifest_validator": args.manifest_validator,
        "execution_lock_tool": args.execution_lock_tool,
        "job_state_query": args.job_state_query,
        "sync_back": args.sync_back,
    }
    report = build_packet(
        _load_json(args.protocol),
        _load_json(args.manifest),
        _load_json(args.selection),
        _load_json(args.design_gate),
        bindings=bindings,
        wrapper_path=args.wrapper,
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(f"status={report['status']} ready={report['approval_packet_ready']} no_submit={report['no_submit']}")
    return 0 if report["approval_packet_ready"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
