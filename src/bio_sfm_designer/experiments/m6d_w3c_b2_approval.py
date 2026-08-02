"""Build and verify the no-submit W3c-B2 prediction approval packet."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    PREDICTOR_IDS,
    TARGET_IDS,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_producer import (
    load_context,
    load_object,
    sha256_file,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_runtime import (
    build_runtime_lock,
    build_runtime_readiness,
)


APPROVAL_PHRASE = "approve W3c-B2 native dual-predictor screen on H100"
APPROVAL_ENV = "BIO_SFM_APPROVE_W3C_B2_NATIVE"
APPROVAL_TOKEN = "approve-w3c-b2-native-16-h100"
SUBMIT_WRAPPER = "hpc/m6d_w3c_b2_submit_with_receipt.sh"
PRODUCER_PATHS = {
    "approval_module": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_approval.py"
    ),
    "native_screen_module": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_native_screen.py"
    ),
    "producer_module": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_producer.py"
    ),
    "runtime_module": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_runtime.py"
    ),
    "journal_module": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_submit_journal.py"
    ),
    "runtime_validation_script": (
        "hpc/validate_w3c_b2_runtime_no_prediction.sh"
    ),
    "boltz_wrapper": "hpc/run_predict_boltz_w3c_b2_native.sbatch",
    "af2_wrapper": "hpc/run_predict_af2_w3c_b2_native.sbatch",
    "submit_wrapper": SUBMIT_WRAPPER,
}


def _binding(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError(f"bound W3c-B2 artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": sha256_file(path),
    }


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    failures.append({"kind": kind, **context})


def _validate_producer_surface(
    paths: Mapping[str, str],
    failures: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    bindings = {name: _binding(path) for name, path in paths.items()}
    sources = {name: Path(path).read_text() for name, path in paths.items()}
    token_surfaces = (
        "boltz_wrapper",
        "af2_wrapper",
        "submit_wrapper",
    )
    for name in token_surfaces:
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
            "observe-boltz",
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
            "--random-seed 0",
            "--num-seeds 1",
            "--num-relax 0",
            "observe-af2",
            "convert-af2",
        )
    ):
        _failure(failures, "af2_wrapper_contract_invalid")
    submit = sources["submit_wrapper"]
    if not all(
        value in submit
        for value in (
            "BIO_SFM_SUBMIT_DRY_RUN",
            "--time=\"$PREDICT_TIME_LIMIT\"",
            "boltz2_complex",
            "af2_multimer_colabfold_v1",
            "dry-run complete: 8 targets, 16 evaluations, zero scheduler jobs",
        )
    ) or any(
        forbidden in submit
        for forbidden in ("--dependency", "ProteinMPNN", "adaptive_top_up")
    ):
        _failure(failures, "submit_wrapper_scope_invalid")
    producer = sources["producer_module"]
    if not all(
        value in producer
        for value in (
            '"templates: []\\n"',
            '"--seed",\n        "0"',
            '"--sampling_steps",\n        "100"',
            "strict_qc_passed",
            "runtime_lock_sha256",
        )
    ):
        _failure(failures, "native_producer_contract_invalid")
    return bindings


def _execution_targets(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for target in manifest["targets"]:
        outputs = target["outputs"]
        root = str(Path(outputs["boltz_record"]).parent)
        rows.append({
            "target_id": target["target_id"],
            "native_candidate_id": target["native_candidate_id"],
            "target_sequence_sha256": target["target_sequence_sha256"],
            "binder_sequence_sha256": target["binder_sequence_sha256"],
            "target_msa_sha256": target["target_msa_sha256"],
            "reference_backbone_sha256": target["prepared_pdb_sha256"],
            "boltz_runtime_observation": (
                f"{root}/boltz_runtime_observation.json"
            ),
            "af2_runtime_observation": f"{root}/af2_runtime_observation.json",
            "boltz_output_dir": outputs["boltz_output_dir"],
            "boltz_record": outputs["boltz_record"],
            "af2_input_dir": outputs["af2_input_dir"],
            "af2_input_manifest": outputs["af2_input_manifest"],
            "af2_output_dir": outputs["af2_output_dir"],
            "af2_record": outputs["af2_record"],
            "matched_record": outputs["matched_record"],
            "predictor_evaluations": 2,
            "maximum_h100_gpu_hours": 2.0,
        })
    return rows


def _initial_output_paths(targets: Sequence[Mapping[str, Any]]) -> List[str]:
    fields = (
        "boltz_runtime_observation",
        "af2_runtime_observation",
        "boltz_output_dir",
        "boltz_record",
        "af2_input_dir",
        "af2_input_manifest",
        "af2_output_dir",
        "af2_record",
        "matched_record",
    )
    return [str(row[field]) for row in targets for field in fields] + [
        "results/m6d_w3c_b2_submit_receipt.jsonl",
        "results/m6d_w3c_b2_submit_receipt_summary.json",
        "results/m6d_w3c_b2_native_records.jsonl",
        "results/m6d_w3c_b2_native_recoverability_report.json",
        "results/m6d_w3c_b2_native_recoverability_report.md",
    ]


def _approval_contract() -> Dict[str, Any]:
    return {
        "user_phrase": APPROVAL_PHRASE,
        "environment_variable": APPROVAL_ENV,
        "environment_value": APPROVAL_TOKEN,
        "stage": "W3c-B2",
        "target_ids": TARGET_IDS,
        "predictor_ids": PREDICTOR_IDS,
        "native_sequences_per_target": 1,
        "boltz_evaluations": 8,
        "af2_evaluations": 8,
        "maximum_predictor_evaluations": 16,
        "maximum_scheduler_jobs": 16,
        "resource_per_evaluation": "h100:1",
        "maximum_walltime_per_evaluation": "01:00:00",
        "maximum_h100_gpu_hours": 16.0,
        "seed": 0,
        "templates_allowed": False,
        "prediction_time_network_allowed": False,
        "proteinmpnn_designs": 0,
        "retry_or_adaptive_top_up_allowed": False,
        "post_execution_slurm_accounting_required": True,
        "authorizes_generator_claim": False,
        "authorizes_trust_gate_claim": False,
        "authorizes_biological_binder_success_claim": False,
        "authorizes_native_recoverability_claim_before_adjudication": False,
    }


def _packet_digest_input(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "approval_contract": packet["approval_contract"],
        "execution_targets": packet["execution_targets"],
        "initial_output_paths": packet["initial_output_paths"],
        "bound_artifact_sha256": {
            name: binding["sha256"]
            for name, binding in packet["bound_artifacts"].items()
        },
        "runtime_lock_digest_sha256": packet[
            "runtime_lock_digest_sha256"
        ],
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
    native_manifest_path: str,
    runtime_readiness_path: str,
    runtime_lock_path: str,
    boltz_observation_path: str,
    af2_observation_path: str,
    producer_paths: Mapping[str, str] = PRODUCER_PATHS,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    manifest = load_object(native_manifest_path)
    runtime_readiness = load_object(runtime_readiness_path)
    runtime_lock = load_object(runtime_lock_path)
    observations = {
        "boltz2_complex": load_object(boltz_observation_path),
        "af2_multimer_colabfold_v1": load_object(af2_observation_path),
    }
    observation_paths = {
        "boltz2_complex": boltz_observation_path,
        "af2_multimer_colabfold_v1": af2_observation_path,
    }
    runtime_current = False
    producer_bindings = _validate_producer_surface(producer_paths, failures)
    manifest_bound = manifest.get("bound_artifacts", {})
    try:
        recomputed_runtime_readiness = build_runtime_readiness(
            protocol_path=manifest_bound["protocol"]["path"],
            native_manifest_path=native_manifest_path,
            b1_completion_path=manifest_bound["w3c_b1_completion"]["path"],
            w3b_runtime_lock_path=manifest_bound[
                "w3b_runtime_transfer_source"
            ]["path"],
            validation_script_path=producer_paths[
                "runtime_validation_script"
            ],
            runtime_module_path=producer_paths["runtime_module"],
            observations=observations,
            observation_paths=observation_paths,
        )
        if runtime_readiness != recomputed_runtime_readiness:
            _failure(failures, "runtime_readiness_not_current")
        expected_runtime_lock = build_runtime_lock(
            recomputed_runtime_readiness, observations
        )
        if runtime_lock != expected_runtime_lock:
            _failure(failures, "runtime_lock_not_current")
        runtime_current = (
            runtime_readiness == recomputed_runtime_readiness
            and runtime_lock == expected_runtime_lock
        )
    except (KeyError, OSError, ValueError) as exc:
        _failure(failures, "runtime_revalidation_failed", message=str(exc))
    contexts = []
    for target_id in TARGET_IDS:
        for predictor_id in PREDICTOR_IDS:
            try:
                contexts.append(
                    load_context(
                        native_manifest_path,
                        runtime_lock_path,
                        target_id,
                        predictor_id,
                    )
                )
            except (OSError, ValueError) as exc:
                _failure(
                    failures,
                    "native_context_invalid",
                    target_id=target_id,
                    predictor_id=predictor_id,
                    message=str(exc),
                )
    targets = _execution_targets(manifest)
    if not (
        len(contexts) == 16
        and [row["target_id"] for row in targets] == TARGET_IDS
        and sum(row["predictor_evaluations"] for row in targets) == 16
        and sum(row["maximum_h100_gpu_hours"] for row in targets) == 16.0
    ):
        _failure(failures, "execution_target_scope_invalid")
    initial_output_paths = _initial_output_paths(targets)
    if len(initial_output_paths) != len(set(initial_output_paths)):
        _failure(failures, "initial_output_paths_not_unique")
    existing = [path for path in initial_output_paths if os.path.exists(path)]
    if existing:
        _failure(failures, "initial_output_already_exists", paths=existing)
    budget = manifest.get("compute_budget")
    if not (
        isinstance(budget, dict)
        and budget.get("maximum_h100_gpu_hours") == 16.0
        and budget.get("maximum_boltz_evaluations") == 8
        and budget.get("maximum_af2_evaluations") == 8
        and budget.get("maximum_total_evaluations") == 16
        and budget.get("maximum_walltime_per_evaluation") == "01:00:00"
        and budget.get("no_retry_or_adaptive_top_up") is True
    ):
        _failure(failures, "compute_budget_invalid")
    bound_artifacts = {
        "native_screen_manifest": _binding(native_manifest_path),
        "runtime_readiness": _binding(runtime_readiness_path),
        "runtime_lock": _binding(runtime_lock_path),
        "boltz_runtime_observation": _binding(boltz_observation_path),
        "af2_runtime_observation": _binding(af2_observation_path),
        **producer_bindings,
    }
    contract = _approval_contract()
    digest_input = {
        "approval_contract": contract,
        "execution_targets": targets,
        "initial_output_paths": initial_output_paths,
        "bound_artifact_sha256": {
            name: binding["sha256"]
            for name, binding in bound_artifacts.items()
        },
        "runtime_lock_digest_sha256": runtime_lock.get(
            "runtime_lock_digest_sha256"
        ),
    }
    ready = not failures
    return {
        "artifact": "m6d_w3c_b2_prediction_packet_readiness",
        "version": 1,
        "status": (
            "w3c_b2_prediction_packet_ready_awaiting_explicit_approval"
            if ready
            else "w3c_b2_prediction_packet_readiness_blocked"
        ),
        "audit_ok": ready,
        "prediction_packet_ready": ready,
        "runtime_identity_ready": (
            runtime_readiness.get("runtime_identity_ready") is True
            and runtime_current
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
        "execution_targets": targets,
        "initial_output_paths": initial_output_paths,
        "bound_artifacts": bound_artifacts,
        "runtime_lock_digest_sha256": runtime_lock.get(
            "runtime_lock_digest_sha256"
        ),
        "packet_digest_sha256": canonical_sha256(digest_input),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Hash-bound approval readiness only. It authorizes zero work now and "
            "supports no native-recoverability, generator, trust-gate, or biological claim."
        ),
        "next_action": (
            f"Request the exact approval phrase: {APPROVAL_PHRASE}"
            if ready
            else "Repair packet-readiness failures before requesting approval."
        ),
    }


def build_approval_packet(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    if not (
        readiness.get("artifact")
        == "m6d_w3c_b2_prediction_packet_readiness"
        and readiness.get("status")
        == "w3c_b2_prediction_packet_ready_awaiting_explicit_approval"
        and readiness.get("audit_ok") is True
        and readiness.get("prediction_packet_ready") is True
        and readiness.get("runtime_identity_ready") is True
        and readiness.get("approval_recorded") is False
        and readiness.get("no_submit") is True
        and readiness.get("n_failures") == 0
    ):
        raise ValueError(
            "W3c-B2 approval packet requires complete no-submit readiness"
        )
    packet = {
        "artifact": "m6d_w3c_b2_native_prediction_approval_packet",
        "version": 1,
        "status": (
            "w3c_b2_native_prediction_approval_packet_ready_no_submit"
        ),
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
        "execution_targets": readiness["execution_targets"],
        "initial_output_paths": readiness["initial_output_paths"],
        "bound_artifacts": readiness["bound_artifacts"],
        "runtime_lock_digest_sha256": readiness[
            "runtime_lock_digest_sha256"
        ],
        "readiness_packet_digest_sha256": readiness[
            "packet_digest_sha256"
        ],
        "submit_command_if_explicitly_approved": (
            f"{APPROVAL_ENV}={APPROVAL_TOKEN} bash {SUBMIT_WRAPPER}"
        ),
        "claim_boundary": readiness["claim_boundary"],
    }
    packet["packet_digest_sha256"] = canonical_sha256(
        _packet_digest_input(packet)
    )
    return packet


def verify_packet_integrity(packet_path: str) -> List[str]:
    packet = load_object(packet_path)
    failures: List[str] = []
    if not (
        packet.get("artifact")
        == "m6d_w3c_b2_native_prediction_approval_packet"
        and packet.get("version") == 1
        and packet.get("status")
        == "w3c_b2_native_prediction_approval_packet_ready_no_submit"
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
    targets = packet.get("execution_targets")
    if not (
        isinstance(targets, list)
        and [row.get("target_id") for row in targets] == TARGET_IDS
        and all(row.get("predictor_evaluations") == 2 for row in targets)
    ):
        failures.append("execution_targets")
    bindings = packet.get("bound_artifacts")
    expected_binding_names = {
        "native_screen_manifest",
        "runtime_readiness",
        "runtime_lock",
        "boltz_runtime_observation",
        "af2_runtime_observation",
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
        manifest_path = bindings["native_screen_manifest"]["path"]
        runtime_lock_path = bindings["runtime_lock"]["path"]
        manifest = load_object(manifest_path)
        expected_targets = _execution_targets(manifest)
        if targets != expected_targets:
            failures.append("execution_targets_not_manifest_derived")
        if packet.get("initial_output_paths") != _initial_output_paths(
            expected_targets
        ):
            failures.append("initial_output_paths_not_manifest_derived")
        runtime_lock = load_object(runtime_lock_path)
        if packet.get("runtime_lock_digest_sha256") != runtime_lock.get(
            "runtime_lock_digest_sha256"
        ):
            failures.append("runtime_lock_digest_binding")
        for target_id in TARGET_IDS:
            for predictor_id in PREDICTOR_IDS:
                try:
                    load_context(
                        manifest_path,
                        runtime_lock_path,
                        target_id,
                        predictor_id,
                    )
                except (OSError, ValueError):
                    failures.append(
                        f"context:{target_id}:{predictor_id}"
                    )
    return failures


def render_markdown(readiness: Mapping[str, Any]) -> str:
    return "\n".join([
        "# M6d W3c-B2 Prediction Approval Readiness",
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
        "- Boltz evaluations: `8`",
        "- AF2-Multimer evaluations: `8`",
        "- maximum H100 GPU-hours: `16.0`",
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
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--native-manifest",
        default="configs/m6d_w3c_b2_native_screen_manifest.json",
    )
    parser.add_argument(
        "--runtime-readiness",
        default="results/m6d_w3c_b2_runtime_readiness.json",
    )
    parser.add_argument(
        "--runtime-lock", default="configs/m6d_w3c_b2_runtime_lock.json"
    )
    parser.add_argument(
        "--boltz-observation",
        default="results/m6d_w3c_b2_boltz_runtime_observation.json",
    )
    parser.add_argument(
        "--af2-observation",
        default="results/m6d_w3c_b2_af2_runtime_observation.json",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    _add_source_args(prepare)
    prepare.add_argument(
        "--out-readiness",
        default="results/m6d_w3c_b2_prediction_packet_readiness.json",
    )
    prepare.add_argument(
        "--out-readiness-md",
        default="results/m6d_w3c_b2_prediction_packet_readiness.md",
    )
    prepare.add_argument(
        "--out-packet",
        default="results/m6d_w3c_b2_prediction_approval_packet.json",
    )
    verify = subparsers.add_parser("verify")
    verify.add_argument("--packet", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify":
        failures = verify_packet_integrity(args.packet)
        print(
            "status="
            + (
                "w3c_b2_approval_packet_verified_no_submit"
                if not failures
                else "w3c_b2_approval_packet_verification_failed"
            )
            + f" verified={not failures} no_submit=True"
        )
        return 0 if not failures else 2
    readiness = build_readiness(
        native_manifest_path=args.native_manifest,
        runtime_readiness_path=args.runtime_readiness,
        runtime_lock_path=args.runtime_lock,
        boltz_observation_path=args.boltz_observation,
        af2_observation_path=args.af2_observation,
    )
    _write_json(args.out_readiness, readiness)
    Path(args.out_readiness_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_readiness_md).write_text(render_markdown(readiness))
    if readiness["prediction_packet_ready"]:
        _write_json(args.out_packet, build_approval_packet(readiness))
    print(
        f"status={readiness['status']} ready={readiness['prediction_packet_ready']} "
        "jobs_authorized=0 no_submit=True"
    )
    return 0 if readiness["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
