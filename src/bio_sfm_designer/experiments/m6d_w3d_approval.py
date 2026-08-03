"""Build and verify the no-submit W3d 24-evaluation approval packet."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments import m6d_w3d_input_runtime as input_runtime
from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as diagnostic
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256


APPROVAL_PHRASE = (
    "approve W3d representation-by-predictor 24-evaluation panel on H100"
)
APPROVAL_ENV = "BIO_SFM_APPROVE_W3D_PANEL"
APPROVAL_TOKEN = "approve-w3d-native-factorial-24-h100"
SUBMIT_WRAPPER = "hpc/m6d_w3d_submit_with_receipt.sh"
PACKET_PATH = "results/m6d_w3d_prediction_approval_packet.json"
READINESS_PATH = "results/m6d_w3d_prediction_packet_readiness.json"
READINESS_MD_PATH = "results/m6d_w3d_prediction_packet_readiness.md"
NATIVE_READINESS_PATH = "results/m6d_w3d_native_diagnostic_readiness.json"
INPUT_READINESS_PATH = input_runtime.READINESS_PATH
PRODUCER_PATHS = {
    "approval_module": (
        "src/bio_sfm_designer/experiments/m6d_w3d_approval.py"
    ),
    "execution_module": (
        "src/bio_sfm_designer/experiments/m6d_w3d_execution.py"
    ),
    "journal_module": (
        "src/bio_sfm_designer/experiments/m6d_w3d_submit_journal.py"
    ),
    "diagnostic_module": (
        "src/bio_sfm_designer/experiments/m6d_w3d_native_diagnostic.py"
    ),
    "input_runtime_module": (
        "src/bio_sfm_designer/experiments/m6d_w3d_input_runtime.py"
    ),
    "boltz_runtime_validation": (
        "hpc/validate_w3d_boltz_runtime_no_prediction.sh"
    ),
    "af2_runtime_validation": (
        "hpc/validate_w3d_af2_runtime_no_prediction.sh"
    ),
    "runtime_validation_orchestrator": (
        "hpc/validate_w3d_runtime_no_prediction.sh"
    ),
    "boltz_wrapper": "hpc/run_predict_boltz_w3d_native.sbatch",
    "af2_wrapper": "hpc/run_predict_af2_w3d_native.sbatch",
    "submit_wrapper": SUBMIT_WRAPPER,
}


def _load_object(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _binding(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError(f"bound W3d artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": input_runtime.sha256_file(path),
    }


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    failures.append({"kind": kind, **context})


def _validate_producer_surface(
    paths: Mapping[str, str],
    failures: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    bindings = {name: _binding(path) for name, path in paths.items()}
    sources = {
        name: Path(path).read_text(encoding="utf-8")
        for name, path in paths.items()
    }
    for name in ("boltz_wrapper", "af2_wrapper", "submit_wrapper"):
        if APPROVAL_TOKEN not in sources[name]:
            _failure(failures, "approval_token_missing", producer=name)
    boltz = sources["boltz_wrapper"]
    if not all(
        value in boltz
        for value in (
            "#SBATCH --gres=gpu:h100:1",
            "#SBATCH --time=01:00:00",
            "HF_HUB_OFFLINE=1",
            "TRANSFORMERS_OFFLINE=1",
            "validate-cell",
            "validate-runtime",
            "run-boltz",
        )
    ):
        _failure(failures, "boltz_wrapper_contract_invalid")
    af2 = sources["af2_wrapper"]
    if not all(
        value in af2
        for value in (
            "#SBATCH --gres=gpu:h100:1",
            "#SBATCH --time=01:00:00",
            "--network none",
            "--pwd \"$PROJECT_ROOT\"",
            "--bind \"$PROJECT_ROOT:$PROJECT_ROOT\"",
            "--random-seed 0",
            "--num-seeds 1",
            "--num-recycle 20",
            "--num-relax 0",
            "validate-cell",
            "validate-runtime",
            "convert-af2",
        )
    ):
        _failure(failures, "af2_wrapper_contract_invalid")
    submit = sources["submit_wrapper"]
    if not all(
        value in submit
        for value in (
            "BIO_SFM_SUBMIT_DRY_RUN",
            "--no-requeue",
            "--time=\"$PREDICT_TIME_LIMIT\"",
            "m6d_w3d_submit_journal append",
            "m6d_w3d_submit_journal summary",
            "8 Boltz + 16 AF2 = 24 evaluations, zero scheduler jobs",
        )
    ) or any(
        forbidden in submit
        for forbidden in ("--dependency", "ProteinMPNN", "adaptive_top_up")
    ):
        _failure(failures, "submit_wrapper_scope_invalid")
    execution = sources["execution_module"]
    if not all(
        value in execution
        for value in (
            '"--no_kernels"',
            '"--sampling_steps"',
            '"100"',
            "strict_qc_passed",
            "ligand_rmsd_angstrom",
            "runtime_receipt_sha256",
        )
    ):
        _failure(failures, "execution_module_contract_invalid")
    return bindings


def _execution_cells(input_manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cells = input_manifest.get("cells")
    if not isinstance(cells, list):
        raise ValueError("W3d input manifest cells are missing")
    rows = []
    for cell in cells:
        if not isinstance(cell, dict):
            raise ValueError("W3d input manifest contains a non-object cell")
        rows.append({
            "cell_id": cell["cell_id"],
            "target_id": cell["target_id"],
            "representation_id": cell["representation_id"],
            "predictor_id": cell["predictor_id"],
            "input_path": cell["input_path"],
            "input_bytes": cell["input_bytes"],
            "input_sha256": cell["input_sha256"],
            "output_dir": cell["planned_output_dir"],
            "record_path": cell["planned_record"],
            "runtime_identity_sha256": cell["runtime_identity_sha256"],
            "predictor_evaluations": 1,
            "maximum_h100_gpu_hours": 1.0,
        })
    return rows


def _initial_output_paths(cells: Sequence[Mapping[str, Any]]) -> List[str]:
    return [
        str(row[field])
        for row in cells
        for field in ("output_dir", "record_path")
    ] + [
        "results/m6d_w3d_submit_receipt.jsonl",
        "results/m6d_w3d_submit_receipt_summary.json",
        "results/m6d_w3d_prospective_records.jsonl",
        "results/m6d_w3d_native_diagnostic_outcome.json",
        "results/m6d_w3d_native_diagnostic_outcome.md",
    ]


def _approval_contract() -> Dict[str, Any]:
    return {
        "user_phrase": APPROVAL_PHRASE,
        "environment_variable": APPROVAL_ENV,
        "environment_value": APPROVAL_TOKEN,
        "stage": "W3d",
        "target_ids": diagnostic.TARGET_IDS,
        "predictor_ids": diagnostic.PREDICTOR_IDS,
        "representation_ids": diagnostic.REPRESENTATION_IDS,
        "design_type": (
            "retrospective_baseline_prospective_factorial_completion"
        ),
        "completed_baseline_cells_reused_without_rerun": 8,
        "prospective_boltz_evaluations": 8,
        "prospective_af2_evaluations": 16,
        "maximum_predictor_evaluations": 24,
        "maximum_scheduler_jobs": 24,
        "resource_per_evaluation": "h100:1",
        "maximum_walltime_per_evaluation": "01:00:00",
        "maximum_h100_gpu_hours": 24.0,
        "seed": 0,
        "templates_allowed": False,
        "prediction_time_network_allowed": False,
        "target_msa_queries": 0,
        "proteinmpnn_designs": 0,
        "retry_or_adaptive_top_up_allowed": False,
        "target_dropping_allowed": False,
        "partial_panel_adjudication_allowed": False,
        "complete_case_adjudication_required": True,
        "post_execution_slurm_accounting_required": True,
        "authorizes_generator_claim": False,
        "authorizes_trust_gate_claim": False,
        "authorizes_biological_binder_success_claim": False,
        "authorizes_native_recoverability_claim_before_adjudication": False,
    }


def _packet_digest_input(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "approval_contract": packet["approval_contract"],
        "execution_cells": packet["execution_cells"],
        "initial_output_paths": packet["initial_output_paths"],
        "bound_artifact_sha256": {
            name: binding["sha256"]
            for name, binding in packet["bound_artifacts"].items()
        },
        "readiness_packet_digest_sha256": packet[
            "readiness_packet_digest_sha256"
        ],
        "submit_command_if_explicitly_approved": packet[
            "submit_command_if_explicitly_approved"
        ],
        "claim_boundary": packet["claim_boundary"],
    }


def build_readiness(
    *,
    protocol_path: str = diagnostic.PROTOCOL_PATH,
    factorial_manifest_path: str = diagnostic.MANIFEST_PATH,
    native_readiness_path: str = NATIVE_READINESS_PATH,
    input_manifest_path: str = input_runtime.INPUT_MANIFEST_PATH,
    input_readiness_path: str = INPUT_READINESS_PATH,
    runtime_receipt_path: str = input_runtime.RUNTIME_RECEIPT_PATH,
    producer_paths: Mapping[str, str] = PRODUCER_PATHS,
    require_input_files: bool = True,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    protocol = _load_object(protocol_path)
    factorial_manifest = _load_object(factorial_manifest_path)
    native_readiness = _load_object(native_readiness_path)
    input_manifest = _load_object(input_manifest_path)
    input_readiness = _load_object(input_readiness_path)
    runtime_receipt = _load_object(runtime_receipt_path)
    producer_bindings = _validate_producer_surface(producer_paths, failures)
    try:
        diagnostic.validate_protocol(protocol)
        expected_native_readiness = diagnostic.build_readiness(
            protocol,
            factorial_manifest,
            manifest_path=factorial_manifest_path,
        )
        if native_readiness != expected_native_readiness:
            _failure(failures, "native_readiness_not_current")
        input_runtime.validate_input_manifest(
            input_manifest,
            input_manifest_path=input_manifest_path,
            project_root=".",
            require_files=require_input_files,
        )
        input_runtime.validate_public_readiness(
            input_readiness,
            input_manifest_path=input_manifest_path,
        )
        input_runtime.validate_runtime_receipt(
            runtime_receipt,
            input_manifest_path=input_manifest_path,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        _failure(failures, "source_revalidation_failed", message=str(exc))

    cells = _execution_cells(input_manifest)
    predictor_counts = Counter(row["predictor_id"] for row in cells)
    combinations = {
        (row["target_id"], row["representation_id"], row["predictor_id"])
        for row in cells
    }
    expected_combinations = {
        (
            cell["target_id"],
            cell["representation_id"],
            cell["predictor_id"],
        )
        for cell in factorial_manifest["cells"]
        if cell.get("cell_status") == "prospective_not_authorized"
    }
    if not (
        len(cells) == 24
        and len(combinations) == 24
        and combinations == expected_combinations
        and predictor_counts
        == {"boltz2_complex": 8, "af2_multimer_colabfold_v1": 16}
        and sum(row["predictor_evaluations"] for row in cells) == 24
        and sum(row["maximum_h100_gpu_hours"] for row in cells) == 24.0
    ):
        _failure(failures, "execution_cell_scope_invalid")
    initial_output_paths = _initial_output_paths(cells)
    if len(initial_output_paths) != 53 or len(set(initial_output_paths)) != 53:
        _failure(failures, "initial_output_path_scope_invalid")
    existing = [path for path in initial_output_paths if os.path.exists(path)]
    if existing:
        _failure(failures, "initial_output_already_exists", paths=existing)
    proposed = protocol.get("proposed_future_compute")
    if not (
        isinstance(proposed, dict)
        and proposed.get("new_predictor_evaluations") == 24
        and proposed.get("new_boltz_evaluations") == 8
        and proposed.get("new_af2_evaluations") == 16
        and proposed.get("maximum_future_h100_gpu_hours_if_separately_approved")
        == 24.0
        and proposed.get("maximum_walltime_per_evaluation") == "01:00:00"
        and proposed.get("resource_per_evaluation") == "h100:1"
        and proposed.get("maximum_target_msa_queries") == 0
        and proposed.get("proteinmpnn_designs") == 0
        and proposed.get("api_calls") == 0
        and proposed.get("retries") == 0
        and proposed.get("adaptive_top_ups") == 0
        and proposed.get("post_execution_slurm_accounting_required") is True
    ):
        _failure(failures, "compute_budget_invalid")
    if not (
        native_readiness.get("approval_packet_prepared") is False
        and native_readiness.get("execution_ready") is False
        and native_readiness.get("predictor_evaluations_authorized") == 0
        and native_readiness.get("h100_gpu_hours_authorized") == 0.0
        and native_readiness.get("no_submit") is True
        and runtime_receipt.get("approval_packet_prepared") is False
        and runtime_receipt.get("can_run_predictors") is False
        and runtime_receipt.get("predictor_evaluations_authorized") == 0
        and runtime_receipt.get("h100_gpu_hours_authorized") == 0.0
        and runtime_receipt.get("no_submit") is True
    ):
        _failure(failures, "source_authority_not_closed")

    bound_artifacts = {
        "protocol": _binding(protocol_path),
        "factorial_manifest": _binding(factorial_manifest_path),
        "native_readiness": _binding(native_readiness_path),
        "input_manifest": _binding(input_manifest_path),
        "input_readiness": _binding(input_readiness_path),
        "runtime_receipt": _binding(runtime_receipt_path),
        "runtime_lock": _binding(input_runtime.RUNTIME_LOCK_PATH),
        "native_source_manifest": _binding(input_runtime.NATIVE_MANIFEST_PATH),
        **producer_bindings,
    }
    contract = _approval_contract()
    digest_input = {
        "approval_contract": contract,
        "execution_cells": cells,
        "initial_output_paths": initial_output_paths,
        "bound_artifact_sha256": {
            name: binding["sha256"]
            for name, binding in bound_artifacts.items()
        },
    }
    ready = not failures
    return {
        "artifact": "m6d_w3d_prediction_packet_readiness",
        "version": 1,
        "status": (
            "w3d_prediction_packet_ready_awaiting_explicit_approval"
            if ready
            else "w3d_prediction_packet_readiness_blocked"
        ),
        "audit_ok": ready,
        "prediction_packet_ready": ready,
        "runtime_identity_ready": (
            runtime_receipt.get("runtime_observations_complete") == 2
            and runtime_receipt.get("absolute_path_probes_complete") == 24
        ),
        "approval_recorded": False,
        "no_submit": True,
        "submitted_jobs": 0,
        "predictor_evaluations_executed": 0,
        "h100_gpu_hours_consumed": 0.0,
        "can_submit_now": False,
        "can_run_predictors_now": False,
        "can_claim_native_recoverability": False,
        "approval_contract": contract,
        "execution_cells": cells,
        "initial_output_paths": initial_output_paths,
        "bound_artifacts": bound_artifacts,
        "packet_digest_sha256": canonical_sha256(digest_input),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Hash-bound W3d approval readiness only. It authorizes zero work now "
            "and supports no native-recoverability, generator, trust-gate, or "
            "biological claim."
        ),
        "next_action": (
            f"Request the exact approval phrase: {APPROVAL_PHRASE}"
            if ready
            else "Repair W3d packet-readiness failures before requesting approval."
        ),
    }


def build_approval_packet(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    if not (
        readiness.get("artifact") == "m6d_w3d_prediction_packet_readiness"
        and readiness.get("status")
        == "w3d_prediction_packet_ready_awaiting_explicit_approval"
        and readiness.get("audit_ok") is True
        and readiness.get("prediction_packet_ready") is True
        and readiness.get("runtime_identity_ready") is True
        and readiness.get("approval_recorded") is False
        and readiness.get("no_submit") is True
        and readiness.get("n_failures") == 0
    ):
        raise ValueError("W3d approval packet requires complete no-submit readiness")
    packet = {
        "artifact": "m6d_w3d_prediction_approval_packet",
        "version": 1,
        "status": "w3d_prediction_approval_packet_ready_no_submit",
        "audit_ok": True,
        "approval_recorded": False,
        "no_submit": True,
        "submitted_jobs": 0,
        "predictor_evaluations_executed": 0,
        "h100_gpu_hours_consumed": 0.0,
        "can_submit_now": False,
        "can_run_predictors_now": False,
        "can_claim_native_recoverability": False,
        "approval_contract": readiness["approval_contract"],
        "execution_cells": readiness["execution_cells"],
        "initial_output_paths": readiness["initial_output_paths"],
        "bound_artifacts": readiness["bound_artifacts"],
        "readiness_packet_digest_sha256": readiness["packet_digest_sha256"],
        "submit_command_if_explicitly_approved": (
            f"{APPROVAL_ENV}={APPROVAL_TOKEN} bash {SUBMIT_WRAPPER}"
        ),
        "claim_boundary": readiness["claim_boundary"],
        "next_action": readiness["next_action"],
    }
    packet["packet_digest_sha256"] = canonical_sha256(
        _packet_digest_input(packet)
    )
    return packet


def verify_packet_integrity(packet_path: str) -> List[str]:
    packet = _load_object(packet_path)
    failures: List[str] = []
    if not (
        packet.get("artifact") == "m6d_w3d_prediction_approval_packet"
        and packet.get("version") == 1
        and packet.get("status")
        == "w3d_prediction_approval_packet_ready_no_submit"
        and packet.get("audit_ok") is True
        and packet.get("approval_recorded") is False
        and packet.get("no_submit") is True
        and packet.get("submitted_jobs") == 0
        and packet.get("predictor_evaluations_executed") == 0
        and packet.get("h100_gpu_hours_consumed") == 0.0
        and packet.get("can_submit_now") is False
        and packet.get("can_run_predictors_now") is False
        and packet.get("can_claim_native_recoverability") is False
        and packet.get("approval_contract") == _approval_contract()
        and packet.get("submit_command_if_explicitly_approved")
        == f"{APPROVAL_ENV}={APPROVAL_TOKEN} bash {SUBMIT_WRAPPER}"
    ):
        failures.append("identity_scope_or_authority")
    cells = packet.get("execution_cells")
    if not (
        isinstance(cells, list)
        and len(cells) == 24
        and len({row.get("cell_id") for row in cells if isinstance(row, dict)})
        == 24
        and Counter(
            row.get("predictor_id") for row in cells if isinstance(row, dict)
        )
        == {"boltz2_complex": 8, "af2_multimer_colabfold_v1": 16}
    ):
        failures.append("execution_cells")
    bindings = packet.get("bound_artifacts")
    expected_binding_names = {
        "protocol",
        "factorial_manifest",
        "native_readiness",
        "input_manifest",
        "input_readiness",
        "runtime_receipt",
        "runtime_lock",
        "native_source_manifest",
        *PRODUCER_PATHS,
    }
    if not isinstance(bindings, dict) or set(bindings) != expected_binding_names:
        failures.append("bound_artifacts")
    else:
        for name, binding in bindings.items():
            path = binding.get("path") if isinstance(binding, dict) else None
            try:
                valid = isinstance(path, str) and binding == _binding(path)
            except (OSError, ValueError):
                valid = False
            if not valid:
                failures.append(f"bound_artifact:{name}")
    try:
        expected_digest = canonical_sha256(_packet_digest_input(packet))
    except (KeyError, TypeError):
        expected_digest = None
    if packet.get("packet_digest_sha256") != expected_digest:
        failures.append("packet_digest")
    if not failures and isinstance(bindings, dict):
        input_manifest_path = bindings["input_manifest"]["path"]
        runtime_receipt_path = bindings["runtime_receipt"]["path"]
        input_manifest = _load_object(input_manifest_path)
        try:
            input_runtime.validate_input_manifest(
                input_manifest,
                input_manifest_path=input_manifest_path,
                require_files=False,
            )
            input_runtime.validate_runtime_receipt(
                _load_object(runtime_receipt_path),
                input_manifest_path=input_manifest_path,
            )
        except (OSError, TypeError, ValueError):
            failures.append("input_or_runtime_revalidation")
        expected_cells = _execution_cells(input_manifest)
        if cells != expected_cells:
            failures.append("execution_cells_not_input_manifest_derived")
        if packet.get("initial_output_paths") != _initial_output_paths(
            expected_cells
        ):
            failures.append("initial_output_paths_not_cell_derived")
    return failures


def render_markdown(readiness: Mapping[str, Any]) -> str:
    return "\n".join([
        "# M6d W3d Prediction Approval Readiness",
        "",
        f"Status: `{readiness['status']}`.",
        f"Audit ok: `{readiness['audit_ok']}`.",
        f"Packet ready: `{readiness['prediction_packet_ready']}`.",
        f"Runtime identity ready: `{readiness['runtime_identity_ready']}`.",
        f"No submit: `{readiness['no_submit']}`.",
        "",
        str(readiness["claim_boundary"]),
        "",
        "## Frozen Scope",
        "",
        "- targets: `8`",
        "- prospective Boltz evaluations: `8`",
        "- prospective AF2-Multimer evaluations: `16`",
        "- total predictor evaluations: `24`",
        "- maximum H100 GPU-hours: `24.0`",
        "- target-MSA queries: `0`",
        "- ProteinMPNN designs: `0`",
        "- retry/adaptive top-up: `False`",
        "- current jobs authorized: `0`",
        "",
        f"Next action: {readiness['next_action']}",
        "",
    ])


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def _write_text(path: str, value: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, destination)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--out-readiness", default=READINESS_PATH)
    prepare.add_argument("--out-readiness-md", default=READINESS_MD_PATH)
    prepare.add_argument("--out-packet", default=PACKET_PATH)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--packet", default=PACKET_PATH)
    args = parser.parse_args(argv)
    if args.command == "verify":
        failures = verify_packet_integrity(args.packet)
        if failures:
            print("W3d packet verification failed: " + ", ".join(failures))
            return 2
        print("W3d packet verification passed: 24 evaluations, no submit")
        return 0
    readiness = build_readiness()
    _write_json(args.out_readiness, readiness)
    _write_text(args.out_readiness_md, render_markdown(readiness))
    if not readiness["audit_ok"]:
        print(
            f"W3d packet readiness blocked: {readiness['n_failures']} failure(s)"
        )
        return 2
    packet = build_approval_packet(readiness)
    _write_json(args.out_packet, packet)
    print(
        "W3d approval packet prepared: 24 evaluations, "
        "approval_recorded=false, no_submit=true"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
