"""Reobserve and bind W3c-B2 predictor runtimes without prediction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256
from bio_sfm_designer.experiments.m6d_w3b_runtime_observation import (
    observe_af2,
    observe_boltz,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import PREDICTOR_IDS


def _load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binding(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError(f"bound artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": _sha256_file(path),
    }


def _serialized_object_matches(path: str, value: Mapping[str, Any]) -> bool:
    try:
        return _load_object(path) == dict(value)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_transfer_source(
    runtime_lock: Mapping[str, Any],
    manifest: Mapping[str, Any],
    runtime_lock_path: str,
) -> None:
    identities = runtime_lock.get("predictor_runtime_identities")
    digests = runtime_lock.get("predictor_runtime_identity_sha256")
    contract = manifest.get("runtime_contract")
    checks = {
        "runtime_identity": (
            runtime_lock.get("artifact") == "m6d_w3b_runtime_lock"
            and runtime_lock.get("version") == 1
            and runtime_lock.get("status")
            == "w3b_dual_predictor_runtime_locked_no_submit"
            and runtime_lock.get("audit_ok") is True
            and runtime_lock.get("runtime_identity_ready") is True
        ),
        "predictor_pair": (
            isinstance(identities, dict)
            and set(identities) == set(PREDICTOR_IDS)
            and isinstance(digests, dict)
            and set(digests) == set(PREDICTOR_IDS)
            and all(
                digests[predictor_id]
                == canonical_sha256(identities[predictor_id])
                for predictor_id in PREDICTOR_IDS
            )
        ),
        "manifest_transfer_binding": (
            isinstance(contract, dict)
            and contract.get("transfer_source") == runtime_lock_path
            and contract.get("transfer_source_sha256")
            == _sha256_file(runtime_lock_path)
            and contract.get("transfer_source_digest_sha256")
            == runtime_lock.get("runtime_lock_digest_sha256")
            and contract.get("expected_predictor_runtime_identity_sha256")
            == digests
            and contract.get("new_runtime_observation_required") is True
            and contract.get("runtime_reobservation_complete") is False
        ),
        "authority": (
            runtime_lock.get("no_submit") is True
            and runtime_lock.get("prediction_executed") is False
            and runtime_lock.get("submitted_jobs") == 0
            and runtime_lock.get("cayuga_submission_allowed") is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(
            "W3c-B2 runtime transfer source invalid: " + ", ".join(failed)
        )


def build_observation(
    predictor_id: str,
    runtime_identity: Mapping[str, Any],
    *,
    protocol_path: str,
    native_manifest_path: str,
    b1_completion_path: str,
    w3b_runtime_lock_path: str,
) -> Dict[str, Any]:
    if predictor_id not in PREDICTOR_IDS:
        raise ValueError(f"unsupported W3c-B2 predictor: {predictor_id}")
    manifest = _load_object(native_manifest_path)
    transfer = _load_object(w3b_runtime_lock_path)
    _validate_transfer_source(transfer, manifest, w3b_runtime_lock_path)
    expected_identity = transfer["predictor_runtime_identities"][predictor_id]
    expected_digest = transfer["predictor_runtime_identity_sha256"][predictor_id]
    observed_identity = dict(runtime_identity)
    observed_digest = canonical_sha256(observed_identity)
    if observed_identity != expected_identity or observed_digest != expected_digest:
        raise ValueError(
            f"observed {predictor_id} runtime differs from the exact transfer source"
        )
    return {
        "artifact": "m6d_w3c_b2_runtime_observation",
        "version": 1,
        "status": "w3c_b2_runtime_reobserved_read_only_no_prediction",
        "audit_ok": True,
        "predictor_id": predictor_id,
        "bindings": {
            "protocol": _binding(protocol_path),
            "native_screen_manifest": _binding(native_manifest_path),
            "w3c_b1_completion": _binding(b1_completion_path),
            "w3b_runtime_transfer_source": _binding(w3b_runtime_lock_path),
        },
        "runtime_identity": observed_identity,
        "runtime_identity_sha256": observed_digest,
        "transfer_identity_sha256": expected_digest,
        "exact_hash_match": True,
        "observation_mode": "read_only_hash_and_metadata",
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "network_fetch_executed": False,
        "scheduler_command_executed": False,
        "submitted_jobs": 0,
        "raw_cayuga_paths_published": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_run_predictors": False,
        "can_claim_native_recoverability": False,
        "claim_boundary": (
            "Read-only runtime identity reobservation only. This artifact records no "
            "prediction, scheduler action, compute approval, or scientific result."
        ),
    }


def validate_observation(
    observation: Mapping[str, Any],
    predictor_id: str,
    *,
    protocol_path: str,
    native_manifest_path: str,
    b1_completion_path: str,
    w3b_runtime_lock_path: str,
) -> List[str]:
    transfer = _load_object(w3b_runtime_lock_path)
    expected_identity = transfer.get("predictor_runtime_identities", {}).get(
        predictor_id
    )
    expected_digest = transfer.get("predictor_runtime_identity_sha256", {}).get(
        predictor_id
    )
    bindings = observation.get("bindings")
    expected_bindings = {
        "protocol": (protocol_path, _sha256_file(protocol_path)),
        "native_screen_manifest": (
            native_manifest_path,
            _sha256_file(native_manifest_path),
        ),
        "w3c_b1_completion": (
            b1_completion_path,
            _sha256_file(b1_completion_path),
        ),
        "w3b_runtime_transfer_source": (
            w3b_runtime_lock_path,
            _sha256_file(w3b_runtime_lock_path),
        ),
    }
    checks = {
        "identity": (
            observation.get("artifact") == "m6d_w3c_b2_runtime_observation"
            and observation.get("version") == 1
            and observation.get("status")
            == "w3c_b2_runtime_reobserved_read_only_no_prediction"
            and observation.get("audit_ok") is True
            and observation.get("predictor_id") == predictor_id
        ),
        "bindings": (
            isinstance(bindings, dict)
            and set(bindings) == set(expected_bindings)
            and all(
                isinstance(bindings.get(name), dict)
                and bindings[name].get("path") == path
                and bindings[name].get("sha256") == sha256
                for name, (path, sha256) in expected_bindings.items()
            )
        ),
        "runtime_identity": (
            observation.get("runtime_identity") == expected_identity
            and observation.get("runtime_identity_sha256") == expected_digest
            and observation.get("transfer_identity_sha256") == expected_digest
            and observation.get("exact_hash_match") is True
            and _is_sha256(expected_digest)
        ),
        "read_only_boundary": (
            observation.get("observation_mode")
            == "read_only_hash_and_metadata"
            and observation.get("prediction_executed") is False
            and observation.get("gpu_compute_executed") is False
            and observation.get("network_fetch_executed") is False
            and observation.get("scheduler_command_executed") is False
            and observation.get("submitted_jobs") == 0
            and observation.get("raw_cayuga_paths_published") is False
        ),
        "authority": (
            observation.get("no_submit") is True
            and observation.get("cayuga_submission_allowed") is False
            and observation.get("can_run_predictors") is False
            and observation.get("can_claim_native_recoverability") is False
        ),
    }
    return [name for name, passed in checks.items() if not passed]


def build_runtime_readiness(
    *,
    protocol_path: str,
    native_manifest_path: str,
    b1_completion_path: str,
    w3b_runtime_lock_path: str,
    validation_script_path: str,
    runtime_module_path: str,
    observations: Mapping[str, Mapping[str, Any]],
    observation_paths: Mapping[str, str],
) -> Dict[str, Any]:
    manifest = _load_object(native_manifest_path)
    transfer = _load_object(w3b_runtime_lock_path)
    _validate_transfer_source(transfer, manifest, w3b_runtime_lock_path)
    failures: List[Dict[str, Any]] = []
    if set(observation_paths) != set(PREDICTOR_IDS):
        failures.append({
            "kind": "runtime_observation_path_scope_invalid",
            "expected": PREDICTOR_IDS,
            "observed": sorted(observation_paths),
        })
    valid_observations: Dict[str, Mapping[str, Any]] = {}
    for predictor_id, observation in observations.items():
        if predictor_id not in PREDICTOR_IDS:
            failures.append({
                "kind": "unexpected_runtime_observation",
                "predictor_id": predictor_id,
            })
            continue
        failed_checks = validate_observation(
            observation,
            predictor_id,
            protocol_path=protocol_path,
            native_manifest_path=native_manifest_path,
            b1_completion_path=b1_completion_path,
            w3b_runtime_lock_path=w3b_runtime_lock_path,
        )
        observation_path = observation_paths.get(predictor_id)
        if not isinstance(observation_path, str) or not _serialized_object_matches(
            observation_path, observation
        ):
            failed_checks.append("serialized_observation_binding")
        if failed_checks:
            failures.append({
                "kind": "runtime_observation_invalid",
                "predictor_id": predictor_id,
                "checks_failed": failed_checks,
            })
        else:
            valid_observations[predictor_id] = observation
    observation_count = len(valid_observations)
    runtime_ready = observation_count == 2 and not failures
    if failures:
        status = "w3c_b2_runtime_reobservation_blocked"
    elif runtime_ready:
        status = "w3c_b2_runtime_reobservation_complete_no_prediction"
    elif observation_count == 1:
        status = "w3c_b2_runtime_reobservation_partial_no_prediction"
    else:
        status = "w3c_b2_runtime_reobservation_packet_ready_no_submit"
    bound_artifacts = {
        "protocol": _binding(protocol_path),
        "native_screen_manifest": _binding(native_manifest_path),
        "w3c_b1_completion": _binding(b1_completion_path),
        "w3b_runtime_transfer_source": _binding(w3b_runtime_lock_path),
        "validation_script": _binding(validation_script_path),
        "runtime_module": _binding(runtime_module_path),
    }
    observation_bindings = {
        predictor_id: _binding(observation_paths[predictor_id])
        for predictor_id in PREDICTOR_IDS
        if predictor_id in valid_observations
    }
    return {
        "artifact": "m6d_w3c_b2_runtime_readiness",
        "version": 1,
        "status": status,
        "audit_ok": not failures,
        "runtime_identity_ready": runtime_ready,
        "runtime_observations_expected": 2,
        "runtime_observations_complete": observation_count,
        "predictor_ids": PREDICTOR_IDS,
        "expected_predictor_runtime_identity_sha256": transfer[
            "predictor_runtime_identity_sha256"
        ],
        "bound_artifacts": bound_artifacts,
        "runtime_observation_bindings": observation_bindings,
        "validation_command": (
            "bash hpc/validate_w3c_b2_runtime_no_prediction.sh"
        ),
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "network_fetch_executed": False,
        "scheduler_command_executed": False,
        "submitted_jobs": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_prepare_prediction_approval_packet": runtime_ready,
        "can_run_predictors": False,
        "can_claim_native_recoverability": False,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Runtime reobservation readiness only. The script executes no prediction, "
            "GPU compute, network fetch, scheduler command, or scientific adjudication."
        ),
        "next_action": (
            "Prepare the hash-bound W3c-B2 prediction approval packet without submission."
            if runtime_ready
            else "Run the read-only Cayuga runtime reobservation with no scheduler or prediction."
        ),
    }


def build_runtime_lock(
    readiness: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    if not (
        readiness.get("artifact") == "m6d_w3c_b2_runtime_readiness"
        and readiness.get("status")
        == "w3c_b2_runtime_reobservation_complete_no_prediction"
        and readiness.get("audit_ok") is True
        and readiness.get("runtime_identity_ready") is True
        and readiness.get("runtime_observations_complete") == 2
        and readiness.get("failures") == []
    ):
        raise ValueError("W3c-B2 runtime lock requires two valid new observations")
    if set(observations) != set(PREDICTOR_IDS):
        raise ValueError("W3c-B2 runtime lock requires the exact predictor pair")
    bound = readiness.get("bound_artifacts")
    observation_bindings = readiness.get("runtime_observation_bindings")
    if not isinstance(bound, dict) or not isinstance(observation_bindings, dict):
        raise ValueError("W3c-B2 runtime lock bindings are missing")
    expected_bound_names = {
        "protocol",
        "native_screen_manifest",
        "w3c_b1_completion",
        "w3b_runtime_transfer_source",
        "validation_script",
        "runtime_module",
    }
    if set(bound) != expected_bound_names or set(observation_bindings) != set(
        PREDICTOR_IDS
    ):
        raise ValueError("W3c-B2 runtime lock binding scope is invalid")
    for name, artifact_binding in bound.items():
        path = artifact_binding.get("path") if isinstance(artifact_binding, dict) else None
        if not isinstance(path, str) or artifact_binding != _binding(path):
            raise ValueError(f"W3c-B2 runtime lock source binding drifted: {name}")
    transfer = _load_object(bound["w3b_runtime_transfer_source"]["path"])
    manifest = _load_object(bound["native_screen_manifest"]["path"])
    _validate_transfer_source(
        transfer,
        manifest,
        bound["w3b_runtime_transfer_source"]["path"],
    )
    expected_digests = readiness.get(
        "expected_predictor_runtime_identity_sha256"
    )
    for predictor_id in PREDICTOR_IDS:
        failed_checks = validate_observation(
            observations[predictor_id],
            predictor_id,
            protocol_path=bound["protocol"]["path"],
            native_manifest_path=bound["native_screen_manifest"]["path"],
            b1_completion_path=bound["w3c_b1_completion"]["path"],
            w3b_runtime_lock_path=bound["w3b_runtime_transfer_source"]["path"],
        )
        observation_binding = observation_bindings[predictor_id]
        path = (
            observation_binding.get("path")
            if isinstance(observation_binding, dict)
            else None
        )
        if (
            failed_checks
            or not isinstance(path, str)
            or observation_binding != _binding(path)
            or not _serialized_object_matches(path, observations[predictor_id])
            or not isinstance(expected_digests, dict)
            or observations[predictor_id].get("runtime_identity_sha256")
            != expected_digests.get(predictor_id)
        ):
            raise ValueError(
                f"W3c-B2 runtime observation binding invalid: {predictor_id}"
            )
    identities = {
        predictor_id: dict(observations[predictor_id]["runtime_identity"])
        for predictor_id in PREDICTOR_IDS
    }
    identity_digests = {
        predictor_id: str(observations[predictor_id]["runtime_identity_sha256"])
        for predictor_id in PREDICTOR_IDS
    }
    digest_input = {
        "protocol_sha256": bound["protocol"]["sha256"],
        "native_screen_manifest_sha256": bound["native_screen_manifest"][
            "sha256"
        ],
        "w3c_b1_completion_sha256": bound["w3c_b1_completion"]["sha256"],
        "transfer_source_sha256": bound["w3b_runtime_transfer_source"][
            "sha256"
        ],
        "predictor_runtime_identity_sha256": identity_digests,
        "runtime_observation_sha256": {
            predictor_id: observation_bindings[predictor_id]["sha256"]
            for predictor_id in PREDICTOR_IDS
        },
    }
    return {
        "artifact": "m6d_w3c_b2_runtime_lock",
        "version": 1,
        "status": "w3c_b2_dual_predictor_runtime_reobserved_no_prediction",
        "audit_ok": True,
        "protocol_sha256": bound["protocol"]["sha256"],
        "native_screen_manifest_sha256": bound["native_screen_manifest"][
            "sha256"
        ],
        "w3c_b1_completion_sha256": bound["w3c_b1_completion"]["sha256"],
        "transfer_source_sha256": bound["w3b_runtime_transfer_source"][
            "sha256"
        ],
        "predictor_runtime_identities": identities,
        "predictor_runtime_identity_sha256": identity_digests,
        "runtime_observation_bindings": observation_bindings,
        "runtime_lock_digest_sha256": canonical_sha256(digest_input),
        "new_runtime_observations": 2,
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "network_fetch_executed": False,
        "scheduler_command_executed": False,
        "submitted_jobs": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_run_predictors": False,
        "can_claim_native_recoverability": False,
        "n_failures": 0,
        "failures": [],
        "claim_boundary": (
            "Exact W3c-B2 runtime identity lock only. This lock records no prediction, "
            "compute approval, scientific result, or downstream authority."
        ),
    }


def validate_runtime_lock_artifact(
    runtime_lock: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    runtime_lock_path: str,
    native_manifest_path: str,
) -> List[str]:
    """Revalidate a materialized W3c-B2 lock against every source file."""

    failures: List[str] = []
    if not (
        runtime_lock.get("artifact") == "m6d_w3c_b2_runtime_lock"
        and runtime_lock.get("version") == 1
        and runtime_lock.get("status")
        == "w3c_b2_dual_predictor_runtime_reobserved_no_prediction"
        and runtime_lock.get("audit_ok") is True
        and runtime_lock.get("new_runtime_observations") == 2
        and runtime_lock.get("prediction_executed") is False
        and runtime_lock.get("gpu_compute_executed") is False
        and runtime_lock.get("network_fetch_executed") is False
        and runtime_lock.get("scheduler_command_executed") is False
        and runtime_lock.get("submitted_jobs") == 0
        and runtime_lock.get("no_submit") is True
        and runtime_lock.get("cayuga_submission_allowed") is False
        and runtime_lock.get("can_run_predictors") is False
        and runtime_lock.get("can_claim_native_recoverability") is False
        and runtime_lock.get("failures") == []
    ):
        failures.append("identity_or_authority")
    try:
        if _load_object(runtime_lock_path) != dict(runtime_lock):
            failures.append("serialized_runtime_lock")
        if _load_object(native_manifest_path) != dict(manifest):
            failures.append("serialized_native_manifest")
    except (OSError, ValueError, json.JSONDecodeError):
        failures.append("serialized_artifact_unreadable")
        return failures
    bound = manifest.get("bound_artifacts")
    required_bound = {
        "protocol",
        "w3c_b1_completion",
        "w3b_runtime_transfer_source",
    }
    if not isinstance(bound, dict) or not required_bound.issubset(bound):
        failures.append("native_manifest_source_bindings")
        return failures
    source_fields = {
        "protocol": "protocol_sha256",
        "w3c_b1_completion": "w3c_b1_completion_sha256",
        "w3b_runtime_transfer_source": "transfer_source_sha256",
    }
    source_paths: Dict[str, str] = {}
    for name, lock_field in source_fields.items():
        binding = bound.get(name)
        path = binding.get("path") if isinstance(binding, dict) else None
        try:
            valid = (
                isinstance(path, str)
                and binding == _binding(path)
                and runtime_lock.get(lock_field) == binding.get("sha256")
            )
        except (OSError, ValueError):
            valid = False
        if not valid:
            failures.append(f"source_binding:{name}")
        elif isinstance(path, str):
            source_paths[name] = path
    if runtime_lock.get("native_screen_manifest_sha256") != _sha256_file(
        native_manifest_path
    ):
        failures.append("native_manifest_sha256")
    identities = runtime_lock.get("predictor_runtime_identities")
    identity_digests = runtime_lock.get("predictor_runtime_identity_sha256")
    if not (
        isinstance(identities, dict)
        and set(identities) == set(PREDICTOR_IDS)
        and isinstance(identity_digests, dict)
        and set(identity_digests) == set(PREDICTOR_IDS)
        and all(
            identity_digests[predictor_id]
            == canonical_sha256(identities[predictor_id])
            for predictor_id in PREDICTOR_IDS
        )
        and identity_digests
        == manifest.get("runtime_contract", {}).get(
            "expected_predictor_runtime_identity_sha256"
        )
    ):
        failures.append("runtime_identities")
    observation_bindings = runtime_lock.get("runtime_observation_bindings")
    observation_sha256: Dict[str, str] = {}
    for predictor_id in PREDICTOR_IDS:
        binding = (
            observation_bindings.get(predictor_id)
            if isinstance(observation_bindings, dict)
            else None
        )
        path = binding.get("path") if isinstance(binding, dict) else None
        try:
            observation = _load_object(path) if isinstance(path, str) else {}
            valid = (
                isinstance(path, str)
                and binding == _binding(path)
                and not validate_observation(
                    observation,
                    predictor_id,
                    protocol_path=source_paths["protocol"],
                    native_manifest_path=native_manifest_path,
                    b1_completion_path=source_paths["w3c_b1_completion"],
                    w3b_runtime_lock_path=source_paths[
                        "w3b_runtime_transfer_source"
                    ],
                )
                and isinstance(identities, dict)
                and isinstance(identity_digests, dict)
                and observation.get("runtime_identity")
                == identities[predictor_id]
                and observation.get("runtime_identity_sha256")
                == identity_digests[predictor_id]
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            valid = False
        if not valid:
            failures.append(f"runtime_observation:{predictor_id}")
        elif isinstance(binding, dict):
            observation_sha256[predictor_id] = str(binding["sha256"])
    if not failures:
        digest_input = {
            "protocol_sha256": runtime_lock["protocol_sha256"],
            "native_screen_manifest_sha256": runtime_lock[
                "native_screen_manifest_sha256"
            ],
            "w3c_b1_completion_sha256": runtime_lock[
                "w3c_b1_completion_sha256"
            ],
            "transfer_source_sha256": runtime_lock["transfer_source_sha256"],
            "predictor_runtime_identity_sha256": identity_digests,
            "runtime_observation_sha256": observation_sha256,
        }
        if runtime_lock.get("runtime_lock_digest_sha256") != canonical_sha256(
            digest_input
        ):
            failures.append("runtime_lock_digest")
    return failures


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# M6d W3c-B2 Runtime Readiness",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Runtime identity ready: `{report['runtime_identity_ready']}`.",
        f"Observations complete: `{report['runtime_observations_complete']}` / `2`.",
        f"Prediction executed: `{report['prediction_executed']}`.",
        f"GPU compute executed: `{report['gpu_compute_executed']}`.",
        f"Scheduler command executed: `{report['scheduler_command_executed']}`.",
        "",
        str(report["claim_boundary"]),
        "",
        f"Next action: {report['next_action']}",
        "",
    ])


def _write_json(path: str, value: Mapping[str, Any], *, refuse_overwrite: bool) -> None:
    destination = Path(path)
    if refuse_overwrite and destination.exists():
        raise ValueError(f"refusing to overwrite runtime artifact: {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--protocol", default="configs/m6d_w3c_validity_first_protocol.json"
    )
    parser.add_argument(
        "--native-manifest",
        default="configs/m6d_w3c_b2_native_screen_manifest.json",
    )
    parser.add_argument(
        "--b1-completion",
        default="results/m6d_w3c_b1_target_msa_completion.json",
    )
    parser.add_argument(
        "--w3b-runtime-lock", default="configs/m6d_w3b_runtime_lock.json"
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    boltz = subparsers.add_parser("observe-boltz")
    _common_arguments(boltz)
    boltz.add_argument("--cache-dir", required=True, type=Path)
    boltz.add_argument("--distribution", default="boltz")
    boltz.add_argument("--boltz-bin", required=True, type=Path)
    boltz.add_argument(
        "--out", default="results/m6d_w3c_b2_boltz_runtime_observation.json"
    )
    af2 = subparsers.add_parser("observe-af2")
    _common_arguments(af2)
    af2.add_argument("--runtime-path", required=True, type=Path)
    af2.add_argument("--data-dir", required=True, type=Path)
    af2.add_argument("--colabfold-version", required=True)
    af2.add_argument(
        "--out", default="results/m6d_w3c_b2_af2_runtime_observation.json"
    )
    packet = subparsers.add_parser("packet")
    _common_arguments(packet)
    packet.add_argument(
        "--validation-script",
        default="hpc/validate_w3c_b2_runtime_no_prediction.sh",
    )
    packet.add_argument(
        "--runtime-module",
        default=(
            "src/bio_sfm_designer/experiments/m6d_w3c_b2_runtime.py"
        ),
    )
    packet.add_argument(
        "--boltz-observation",
        default="results/m6d_w3c_b2_boltz_runtime_observation.json",
    )
    packet.add_argument(
        "--af2-observation",
        default="results/m6d_w3c_b2_af2_runtime_observation.json",
    )
    packet.add_argument(
        "--out-readiness",
        default="results/m6d_w3c_b2_runtime_readiness.json",
    )
    packet.add_argument(
        "--out-readiness-md",
        default="results/m6d_w3c_b2_runtime_readiness.md",
    )
    packet.add_argument(
        "--out-runtime-lock",
        default="configs/m6d_w3c_b2_runtime_lock.json",
    )
    args = parser.parse_args(argv)
    if args.command == "observe-boltz":
        expected_binary = Path(sys.executable).parent / "boltz"
        if (
            not args.boltz_bin.is_file()
            or args.boltz_bin.resolve() != expected_binary.resolve()
        ):
            raise ValueError("Boltz executable and observed Python environment differ")
        identity = observe_boltz(args.cache_dir, args.distribution)
        observation = build_observation(
            "boltz2_complex",
            identity,
            protocol_path=args.protocol,
            native_manifest_path=args.native_manifest,
            b1_completion_path=args.b1_completion,
            w3b_runtime_lock_path=args.w3b_runtime_lock,
        )
        _write_json(args.out, observation, refuse_overwrite=True)
        print("predictor=boltz2_complex reobserved=True prediction_executed=False")
        return 0
    if args.command == "observe-af2":
        identity = observe_af2(
            args.runtime_path, args.data_dir, args.colabfold_version
        )
        observation = build_observation(
            "af2_multimer_colabfold_v1",
            identity,
            protocol_path=args.protocol,
            native_manifest_path=args.native_manifest,
            b1_completion_path=args.b1_completion,
            w3b_runtime_lock_path=args.w3b_runtime_lock,
        )
        _write_json(args.out, observation, refuse_overwrite=True)
        print(
            "predictor=af2_multimer_colabfold_v1 reobserved=True "
            "prediction_executed=False"
        )
        return 0

    observation_paths = {
        "boltz2_complex": args.boltz_observation,
        "af2_multimer_colabfold_v1": args.af2_observation,
    }
    observations = {
        predictor_id: _load_object(path)
        for predictor_id, path in observation_paths.items()
        if os.path.isfile(path)
    }
    readiness = build_runtime_readiness(
        protocol_path=args.protocol,
        native_manifest_path=args.native_manifest,
        b1_completion_path=args.b1_completion,
        w3b_runtime_lock_path=args.w3b_runtime_lock,
        validation_script_path=args.validation_script,
        runtime_module_path=args.runtime_module,
        observations=observations,
        observation_paths=observation_paths,
    )
    _write_json(args.out_readiness, readiness, refuse_overwrite=False)
    Path(args.out_readiness_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_readiness_md).write_text(render_markdown(readiness))
    if readiness["runtime_identity_ready"]:
        runtime_lock = build_runtime_lock(readiness, observations)
        if os.path.exists(args.out_runtime_lock):
            if _load_object(args.out_runtime_lock) != runtime_lock:
                raise ValueError(
                    "existing W3c-B2 runtime lock differs from fresh observations"
                )
        else:
            _write_json(args.out_runtime_lock, runtime_lock, refuse_overwrite=True)
    print(
        f"status={readiness['status']} audit_ok={readiness['audit_ok']} "
        f"observations={readiness['runtime_observations_complete']} "
        "prediction_executed=False"
    )
    return 0 if readiness["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
