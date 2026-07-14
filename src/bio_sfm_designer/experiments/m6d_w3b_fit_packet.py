"""Build the no-submit W3b fit-stage approval-packet readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_object,
    load_target_context,
    sha256_file,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    canonical_sha256,
    validate_runtime_lock,
)


_APPROVAL_ENV = "BIO_SFM_APPROVE_W3B_FIT"
_APPROVAL_TOKEN = "approve-w3b-fit-180-matched-h100"
_APPROVAL_PHRASE = "approve W3b fit-stage 180-design matched Boltz-AF2 generation on H100"
_PRODUCER_PATHS = (
    "hpc/run_w3b_fit_guarded.sh",
    "hpc/m6d_w3b_fit_submit_with_receipt.sh",
    "hpc/run_generate_proteinmpnn_w3b_fit.sbatch",
    "hpc/generate_proteinmpnn_complex.py",
    "hpc/run_predict_boltz_w3b_fit.sbatch",
    "hpc/predict_boltz_w3b_complex.py",
    "hpc/run_predict_af2_w3b_fit.sbatch",
    "hpc/convert_w3b_af2_outputs.py",
    "src/bio_sfm_designer/experiments/m6d_w3_mechanism_panel.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_producer_contract.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_runtime_observation.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_structure_metrics.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_matched_records.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_runtime_lock.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_fit_submit_journal.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_fit_packet.py",
)
_SHELL_PATHS = (
    "hpc/run_w3b_fit_guarded.sh",
    "hpc/m6d_w3b_fit_submit_with_receipt.sh",
    "hpc/run_generate_proteinmpnn_w3b_fit.sbatch",
    "hpc/run_predict_boltz_w3b_fit.sbatch",
    "hpc/run_predict_af2_w3b_fit.sbatch",
)


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    failures.append({"kind": kind, **context})


def _file_binding(path: str) -> Dict[str, Any]:
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": sha256_file(path),
    }


def _validate_protocol(protocol: Mapping[str, Any], failures: List[Dict[str, Any]]) -> None:
    execution = protocol.get("execution_state")
    locked = protocol.get("locked_scientific_protocol")
    fit = locked.get("fit_design") if isinstance(locked, Mapping) else None
    fresh = locked.get("fresh_target_contract") if isinstance(locked, Mapping) else None
    budget = locked.get("compute_budget") if isinstance(locked, Mapping) else None
    predictor = locked.get("predictor_contract") if isinstance(locked, Mapping) else None
    if protocol.get("artifact") != "m6d_w3b_disagreement_gate_protocol":
        _failure(failures, "fit_packet_protocol_artifact_invalid")
    if not (
        isinstance(execution, Mapping)
        and execution.get("no_submit") is True
        and execution.get("approval_recorded") is False
        and execution.get("operator_approval_recorded") is False
        and execution.get("cayuga_submission_allowed") is False
    ):
        _failure(failures, "fit_packet_protocol_approval_boundary_invalid")
    if not (
        isinstance(fit, Mapping)
        and fit.get("records_per_target") == 60
        and fit.get("seed_namespace") == "w3b-fit-v1"
        and fit.get("target_roles_used") == ["fit"]
        and fit.get("thresholds_frozen_after_fit") is True
    ):
        _failure(failures, "fit_packet_scientific_fit_contract_invalid")
    if not (
        isinstance(fresh, Mapping)
        and fresh.get("n_fit_targets") == 3
        and fresh.get("n_certification_targets") == 3
        and fresh.get("n_held_out_test_targets") == 2
    ):
        _failure(failures, "fit_packet_target_role_contract_invalid")
    if not (
        isinstance(budget, Mapping)
        and budget.get("maximum_candidate_designs") == 870
        and budget.get("maximum_predictor_evaluations") == 1740
        and budget.get("maximum_h100_gpu_hours") == 24.0
        and budget.get("no_adaptive_top_up") is True
        and budget.get("stage_stop_after_fit_failure") is True
    ):
        _failure(failures, "fit_packet_compute_budget_contract_invalid")
    predictor_ids = {
        str(row.get("id") or "")
        for row in predictor.get("predictors", [])
        if isinstance(row, Mapping)
    } if isinstance(predictor, Mapping) else set()
    if predictor_ids != {"boltz2_complex", "af2_multimer_colabfold_v1"}:
        _failure(failures, "fit_packet_predictor_pair_invalid")


def _validate_producers(paths: Sequence[str], failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bindings: List[Dict[str, Any]] = []
    for path in paths:
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            _failure(failures, "fit_packet_producer_missing_or_empty", path=path)
            continue
        bindings.append(_file_binding(path))
    for path in _SHELL_PATHS:
        if path not in paths or not os.path.isfile(path):
            continue
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        if result.returncode != 0:
            _failure(failures, "fit_packet_shell_syntax_invalid", path=path)
    static_requirements = {
        "hpc/run_w3b_fit_guarded.sh": (
            _APPROVAL_ENV,
            _APPROVAL_TOKEN,
            "--verify-approval-packet",
            "BIO_SFM_SUBMIT_DRY_RUN",
        ),
        "hpc/m6d_w3b_fit_submit_with_receipt.sh": (
            _APPROVAL_ENV,
            _APPROVAL_TOKEN,
            "proteinmpnn_submitted",
            "boltz_submitted",
            "af2_submitted",
            "--dependency=",
            "afterok:",
            'PREDICT_TIME_LIMIT="04:00:00"',
            "--no-requeue",
        ),
        "hpc/run_generate_proteinmpnn_w3b_fit.sbatch": (
            _APPROVAL_ENV,
            _APPROVAL_TOKEN,
            '[ "$STAGE" = "fit" ]',
            "NUM_SEQ",
        ),
        "hpc/run_predict_boltz_w3b_fit.sbatch": (
            _APPROVAL_ENV,
            _APPROVAL_TOKEN,
            "m6d_w3b_runtime_observation",
            "boltz2_complex",
        ),
        "hpc/predict_boltz_w3b_complex.py": (
            '"--seed",\n        "0"',
            '"--recycling_steps",\n        "3"',
            '"--sampling_steps",\n        "100"',
            '"--write_full_pae"',
            '"templates: []',
        ),
        "hpc/run_predict_af2_w3b_fit.sbatch": (
            _APPROVAL_ENV,
            _APPROVAL_TOKEN,
            "--network none",
            "--model-type alphafold2_multimer_v3",
            "--random-seed 0",
            "--num-recycle 20",
            "--num-models 5",
        ),
    }
    for path, fragments in static_requirements.items():
        if path not in paths or not os.path.isfile(path):
            continue
        text = Path(path).read_text()
        missing = [fragment for fragment in fragments if fragment not in text]
        if missing:
            _failure(
                failures,
                "fit_packet_producer_static_contract_invalid",
                path=path,
                missing=missing,
            )
    return bindings


def _fit_targets(
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
    failures: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    manifest = load_object(execution_manifest_path)
    all_targets = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    role_counts = Counter(str(row.get("experimental_role") or "") for row in all_targets)
    if len(all_targets) != 8 or role_counts != {"fit": 3, "certification": 3, "held_out_test": 2}:
        _failure(
            failures,
            "fit_packet_execution_target_roles_invalid",
            n_targets=len(all_targets),
            role_counts=dict(role_counts),
        )
        return []
    fit_targets = [row for row in all_targets if row.get("experimental_role") == "fit"]
    validated: List[Dict[str, Any]] = []
    for target in fit_targets:
        target_id = str(target.get("id") or "")
        try:
            context = load_target_context(
                protocol_path,
                execution_manifest_path,
                input_lock_path,
                runtime_lock_path,
                target_id,
                "fit",
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            _failure(
                failures,
                "fit_packet_execution_target_invalid",
                target_id=target_id,
                message=str(exc),
            )
            continue
        row = context["target"]
        validated.append({
            "target_id": target_id,
            "records_planned": row["num_seq"],
            "seed_namespace": row["w3b_seed_namespace"],
            "proteinmpnn_seed": row["proteinmpnn_seed"],
            "proteinmpnn_temperature": row["temp"],
            "proteinmpnn_objective": row["objective"],
            "id_prefix": row["id_prefix"],
            "prepared_pdb": row["prepared_pdb"],
            "target_chain": row["target_chain"],
            "binder_chain": row["binder_chain"],
            "target_msa": row["target_msa"],
            "target_msa_sha256": row["target_msa_sha256"],
            "candidates": row["candidates"],
            "boltz_records": row["boltz_records"],
            "af2_records": row["af2_records"],
            "out_prefix": row["out_prefix"],
        })
    if len(validated) != 3 or sum(row["records_planned"] for row in validated) != 180:
        _failure(failures, "fit_packet_scope_totals_invalid")
    output_paths = [
        row[field]
        for row in validated
        for field in ("candidates", "boltz_records", "af2_records")
    ]
    if len(output_paths) != len(set(output_paths)):
        _failure(failures, "fit_packet_output_paths_not_unique")
    existing = [path for path in output_paths if os.path.exists(path)]
    if existing:
        _failure(failures, "fit_packet_initial_output_already_exists", paths=existing)
    return validated


def build_readiness(
    protocol_path: str,
    execution_readiness_path: str,
    runtime_readiness_path: str,
    matched_readiness_path: str,
    runtime_lock_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    producer_paths: Sequence[str] = _PRODUCER_PATHS,
) -> Dict[str, Any]:
    protocol = load_object(protocol_path)
    execution = load_object(execution_readiness_path)
    runtime = load_object(runtime_readiness_path)
    matched = load_object(matched_readiness_path)
    runtime_lock = load_object(runtime_lock_path)
    failures: List[Dict[str, Any]] = []
    _validate_protocol(protocol, failures)
    producer_bindings = _validate_producers(producer_paths, failures)
    runtime_failures = validate_runtime_lock(runtime_lock, protocol_path)
    failures.extend(runtime_failures)
    if not (
        execution.get("artifact") == "m6d_w3b_execution_lock_readiness"
        and execution.get("audit_ok") is True
        and execution.get("no_submit") is True
        and execution.get("protocol_sha256") == sha256_file(protocol_path)
    ):
        _failure(failures, "fit_packet_execution_readiness_invalid")
    if not (
        runtime.get("artifact") == "m6d_w3b_runtime_lock_readiness"
        and runtime.get("audit_ok") is True
        and runtime.get("runtime_identity_ready") is True
        and runtime.get("no_submit") is True
        and runtime.get("runtime_lock") == runtime_lock_path
        and runtime.get("runtime_lock_sha256") == sha256_file(runtime_lock_path)
        and runtime.get("runtime_lock_digest_sha256") == runtime_lock.get("runtime_lock_digest_sha256")
    ):
        _failure(failures, "fit_packet_runtime_readiness_invalid")
    if not (
        matched.get("artifact") == "m6d_w3b_matched_record_contract"
        and matched.get("audit_ok") is True
        and matched.get("runtime_identity_ready") is True
        and matched.get("no_submit") is True
        and matched.get("runtime_lock_sha256") == sha256_file(runtime_lock_path)
    ):
        _failure(failures, "fit_packet_matched_record_contract_invalid")

    execution_ready = execution.get("execution_lock_ready") is True
    runtime_ready = runtime.get("runtime_identity_ready") is True and not runtime_failures
    matched_ready = matched.get("assembly_ready") is True
    fit_targets: List[Dict[str, Any]] = []
    execution_bindings: List[Dict[str, Any]] = []
    if execution_ready:
        for path in (execution_manifest_path, input_lock_path):
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                _failure(failures, "fit_packet_execution_lock_artifact_missing", path=path)
            else:
                execution_bindings.append(_file_binding(path))
        if len(execution_bindings) == 2:
            fit_targets = _fit_targets(
                protocol_path,
                execution_manifest_path,
                input_lock_path,
                runtime_lock_path,
                failures,
            )
    else:
        coherent_waiting = (
            execution.get("status") == "w3b_execution_lock_awaiting_target_msa_approval_and_completion"
            and execution.get("execution_lock_ready") is False
            and matched.get("assembly_ready") is False
            and runtime.get("execution_lock_ready") is False
        )
        if not coherent_waiting:
            _failure(failures, "fit_packet_execution_waiting_state_incoherent")

    packet_ready = (
        execution_ready
        and runtime_ready
        and matched_ready
        and len(fit_targets) == 3
        and not failures
    )
    if failures:
        status = "w3b_fit_packet_readiness_blocked"
    elif packet_ready:
        status = "w3b_fit_packet_ready_awaiting_explicit_approval"
    else:
        status = "w3b_fit_packet_awaiting_target_msa_and_execution_lock"
    bound_artifacts = [
        _file_binding(protocol_path),
        _file_binding(execution_readiness_path),
        _file_binding(runtime_readiness_path),
        _file_binding(matched_readiness_path),
        _file_binding(runtime_lock_path),
        *execution_bindings,
        *producer_bindings,
    ]
    approval_contract = {
        "user_phrase": _APPROVAL_PHRASE,
        "environment_variable": _APPROVAL_ENV,
        "environment_value": _APPROVAL_TOKEN,
        "stage": "fit",
        "target_count": 3,
        "records_per_target": 60,
        "candidate_designs": 180,
        "matched_predictor_evaluations": 360,
        "proteinmpnn_cpu_jobs": 3,
        "boltz_h100_jobs": 3,
        "af2_h100_jobs": 3,
        "maximum_protocol_h100_gpu_hours_cumulative": 24.0,
        "maximum_fit_submission_h100_gpu_hours": 24.0,
        "maximum_walltime_per_h100_job_hours": 4.0,
        "requires_post_fit_slurm_gpu_accounting": True,
        "authorizes_certification": False,
        "authorizes_held_out_test": False,
        "authorizes_adaptive_top_up": False,
        "authorizes_claim": False,
    }
    digest_input = {
        "approval_contract": approval_contract,
        "bound_artifact_sha256": {
            row["path"]: row["sha256"]
            for row in bound_artifacts
        },
        "fit_targets": fit_targets,
        "runtime_lock_digest_sha256": runtime_lock.get("runtime_lock_digest_sha256"),
    }
    return {
        "artifact": "m6d_w3b_fit_packet_readiness",
        "version": 1,
        "status": status,
        "audit_ok": not failures,
        "fit_packet_ready": packet_ready,
        "execution_lock_ready": execution_ready,
        "runtime_identity_ready": runtime_ready,
        "matched_record_contract_ready": matched_ready,
        "explicit_fit_approval_recorded": False,
        "no_submit": True,
        "submitted_jobs": 0,
        "can_submit_fit_stage": False,
        "can_run_candidate_generation_or_prediction": False,
        "can_claim_w3b": False,
        "approval_contract": approval_contract,
        "fit_targets": fit_targets,
        "bound_artifacts": bound_artifacts,
        "packet_digest_sha256": canonical_sha256(digest_input),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Fit-stage packet readiness only. This artifact submits no job, records no approval, "
            "runs no candidate or predictor, and supports no W3b or biological-success claim."
        ),
        "next_action": (
            "request the exact, separately scoped W3b fit-stage approval"
            if packet_ready else
            "complete the separately approved eight-target MSA lifecycle and materialize the execution lock"
            if not failures else
            "repair fit-packet readiness failures before any W3b fit-stage approval"
        ),
    }


def build_approval_packet(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    if not (
        readiness.get("artifact") == "m6d_w3b_fit_packet_readiness"
        and readiness.get("status") == "w3b_fit_packet_ready_awaiting_explicit_approval"
        and readiness.get("audit_ok") is True
        and readiness.get("fit_packet_ready") is True
        and readiness.get("no_submit") is True
        and readiness.get("n_failures") == 0
    ):
        raise ValueError("W3b fit approval packet cannot be emitted before readiness is complete")
    return {
        "artifact": "m6d_w3b_fit_approval_packet",
        "version": 1,
        "status": "w3b_fit_approval_packet_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "approval_recorded": False,
        "submitted_jobs": 0,
        "can_claim_w3b": False,
        "approval_contract": readiness["approval_contract"],
        "fit_targets": readiness["fit_targets"],
        "bound_artifacts": readiness["bound_artifacts"],
        "readiness_packet_digest_sha256": readiness["packet_digest_sha256"],
        "claim_boundary": readiness["claim_boundary"],
    }


def verify_approval_packet(packet_path: str, readiness: Mapping[str, Any]) -> Dict[str, Any]:
    actual = load_object(packet_path)
    expected = build_approval_packet(readiness)
    verified = actual == expected
    return {
        "artifact": "m6d_w3b_fit_approval_packet_verification",
        "status": (
            "w3b_fit_approval_packet_verified_no_submit"
            if verified else
            "w3b_fit_approval_packet_verification_failed"
        ),
        "verified": verified,
        "packet": packet_path,
        "packet_sha256": sha256_file(packet_path),
        "readiness_packet_digest_sha256": readiness.get("packet_digest_sha256"),
        "no_submit": True,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3b Fit-Packet Readiness",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Fit packet ready: `{report['fit_packet_ready']}`.",
        f"Execution lock ready: `{report['execution_lock_ready']}`.",
        f"Runtime identity ready: `{report['runtime_identity_ready']}`.",
        f"Matched-record contract ready: `{report['matched_record_contract_ready']}`.",
        f"No submit: `{report['no_submit']}`.",
        "",
        str(report["claim_boundary"]),
        "",
        "## Frozen Fit Scope",
        "",
        "- fit targets: `3`",
        "- candidates: `180` (`60` per target)",
        "- matched predictor evaluations: `360`",
        "- certification/test jobs: `0`",
        f"- packet digest: `{report['packet_digest_sha256']}`",
        "",
        f"Next action: {report['next_action']}.",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- `{row['kind']}`" for row in report["failures"])
        lines.append("")
    return "\n".join(lines)


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--execution-readiness", default="results/m6d_w3b_execution_lock_readiness.json")
    parser.add_argument("--runtime-readiness", default="results/m6d_w3b_runtime_lock_readiness.json")
    parser.add_argument("--matched-readiness", default="results/m6d_w3b_matched_record_contract.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--out-readiness", default="results/m6d_w3b_fit_packet_readiness.json")
    parser.add_argument("--out-readiness-md", default="results/m6d_w3b_fit_packet_readiness.md")
    parser.add_argument("--emit-approval-packet", default=None)
    parser.add_argument("--verify-approval-packet", default=None)
    args = parser.parse_args(argv)
    report = build_readiness(
        args.protocol,
        args.execution_readiness,
        args.runtime_readiness,
        args.matched_readiness,
        args.runtime_lock,
        args.execution_manifest,
        args.input_lock,
    )
    if args.verify_approval_packet:
        verification = verify_approval_packet(args.verify_approval_packet, report)
        print(f"status={verification['status']} verified={verification['verified']} no_submit=True")
        return 0 if verification["verified"] else 2
    _write_json(args.out_readiness, report)
    Path(args.out_readiness_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_readiness_md).write_text(render_markdown(report))
    if args.emit_approval_packet:
        packet = build_approval_packet(report)
        _write_json(args.emit_approval_packet, packet)
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"fit_packet_ready={report['fit_packet_ready']} no_submit=True"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
