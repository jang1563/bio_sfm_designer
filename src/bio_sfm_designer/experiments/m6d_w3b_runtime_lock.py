"""Freeze and audit the exact dual-predictor runtime contract for W3b."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple


_PREDICTORS = ("boltz2_complex", "af2_multimer_colabfold_v1")
_BOLTZ_VERSION = "2.2.1"
_BOLTZ_DISTRIBUTION_FILE_COUNT = 116
_BOLTZ_DISTRIBUTION_SHA256 = "8e101bde6e7faaff1b143efdd15f29362eef2fd9e099093906ade6fe83dd034a"
_BOLTZ_CHECKPOINTS = {
    "boltz2_conf.ckpt": {
        "active_for_structure_prediction": True,
        "bytes": 2286561469,
        "role": "structure_confidence_model",
        "sha256": "090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1",
    },
    "boltz2_aff.ckpt": {
        "active_for_structure_prediction": False,
        "bytes": 2062139170,
        "role": "required_local_cache_affinity_model",
        "sha256": "dcc5cd3722b1c9eaa34267e4ae32f55cbbf1963f4c19319381ccfa30fdd2ca9e",
    },
}
_AF2_CONTAINER_URI = "docker://ghcr.io/sokrypton/colabfold:1.6.1-cuda12"
_AF2_CONTAINER_SHA256 = "e26689bc357e8aaf5210ed43499e565d2a440ea6efde5a8a42cbdc4f6a83e566"
_AF2_WEIGHTS_MANIFEST_SHA256 = "2e0fb58c94a04975715d3a97f459224ff37a966d5672b3aeceec4f652935eb64"
_AF2_WEIGHTS = {
    "params_model_1_multimer_v3.npz": (373043148, "611da8fc7478928f68de12e8b226260ef1f4ce62bcc29b008572e52f4f212959"),
    "params_model_2_multimer_v3.npz": (373043148, "51362b0844382ae0f5720c59b81dd13a43eea40fbf9995dd2573bdab88865378"),
    "params_model_3_multimer_v3.npz": (373043148, "46d9bcad288edc7ad5a6362ee8e5f84307a69712e00e6c36b1ef9daf96ebc9ce"),
    "params_model_4_multimer_v3.npz": (373043148, "59bdabd2d69c07fe26b37882d544acbd1b9f89f196828f4220da49e0610b572c"),
    "params_model_5_multimer_v3.npz": (373043148, "917742be5a105d6b80f13f1f13f20459f27ec3fdcd34ea088b359f4502d6177f"),
}


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


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    row: Dict[str, Any] = {"kind": kind}
    row.update(context)
    failures.append(row)


def _weight_map(rows: Any) -> Dict[str, Tuple[Any, Any]]:
    if not isinstance(rows, list):
        return {}
    mapped: Dict[str, Tuple[Any, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            return {}
        name = str(row["name"])
        if name in mapped:
            return {}
        mapped[name] = (row.get("size_bytes"), row.get("sha256"))
    return mapped


def _checkpoint_map(rows: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    mapped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            return {}
        name = str(row["name"])
        if name in mapped:
            return {}
        mapped[name] = {key: value for key, value in row.items() if key != "name"}
    return mapped


def _protocol_failures(protocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    execution = protocol.get("execution_state")
    locked = protocol.get("locked_scientific_protocol")
    predictor_contract = locked.get("predictor_contract") if isinstance(locked, dict) else None
    predictors = predictor_contract.get("predictors") if isinstance(predictor_contract, dict) else None
    by_id = {
        str(row.get("id") or ""): row
        for row in predictors or []
        if isinstance(row, dict)
    }
    if protocol.get("artifact") != "m6d_w3b_disagreement_gate_protocol":
        _failure(failures, "runtime_lock_protocol_artifact_invalid")
    if not isinstance(execution, dict) or not isinstance(locked, dict):
        _failure(failures, "runtime_lock_protocol_structure_invalid")
        return failures
    if not (
        execution.get("no_submit") is True
        and execution.get("no_gpu_compute") is True
        and execution.get("no_api_spend") is True
        and execution.get("cayuga_submission_allowed") is False
        and execution.get("approval_recorded") is False
        and execution.get("operator_approval_recorded") is False
    ):
        _failure(failures, "runtime_lock_protocol_approval_boundary_invalid")
    if set(by_id) != set(_PREDICTORS):
        _failure(
            failures,
            "runtime_lock_protocol_predictor_set_invalid",
            expected=list(_PREDICTORS),
            observed=sorted(by_id),
        )
        return failures
    boltz = by_id["boltz2_complex"]
    af2 = by_id["af2_multimer_colabfold_v1"]
    common_ok = all(
        row.get("seed") == 0
        and row.get("templates") is False
        and row.get("binder_msa") == "single_sequence"
        and row.get("runtime_identity_receipt_required") is True
        for row in by_id.values()
    )
    if not common_ok or predictor_contract.get("same_prediction_time_network_policy") != "forbidden":
        _failure(failures, "runtime_lock_protocol_common_predictor_policy_invalid")
    if boltz.get("target_msa") != "reuse_hash_locked_target_msa":
        _failure(failures, "runtime_lock_protocol_boltz_msa_policy_invalid")
    if not (
        af2.get("target_msa") == "reuse_same_hash_locked_target_msa"
        and af2.get("required_colabfold_version") == "1.6.1"
        and af2.get("model_type") == "alphafold2_multimer_v3"
    ):
        _failure(failures, "runtime_lock_protocol_af2_policy_invalid")
    return failures


def _boltz_observation_failures(observation: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    identity = observation.get("runtime_identity")
    interface = observation.get("runtime_interface")
    if not (
        observation.get("artifact") == "m6d_w3b_boltz_runtime_observation"
        and observation.get("status") == "w3b_boltz_runtime_observed_read_only_no_prediction"
        and observation.get("audit_ok") is True
        and observation.get("no_submit") is True
        and observation.get("prediction_executed") is False
        and observation.get("gpu_compute_executed") is False
        and observation.get("network_fetch_executed") is False
        and observation.get("submitted_jobs") == 0
        and observation.get("raw_cayuga_paths_published") is False
    ):
        _failure(failures, "runtime_lock_boltz_observation_boundary_invalid")
    if not isinstance(identity, dict) or not isinstance(interface, dict):
        _failure(failures, "runtime_lock_boltz_observation_structure_invalid")
        return failures
    if not (
        identity.get("model") == "boltz2"
        and identity.get("boltz_version") == _BOLTZ_VERSION
        and identity.get("distribution_file_count") == _BOLTZ_DISTRIBUTION_FILE_COUNT
        and identity.get("distribution_manifest_sha256") == _BOLTZ_DISTRIBUTION_SHA256
        and _checkpoint_map(identity.get("cache_checkpoints")) == _BOLTZ_CHECKPOINTS
    ):
        _failure(failures, "runtime_lock_boltz_identity_drift")
    expected_interface = {
        "accelerator_default": "gpu",
        "checkpoint_flag_available": True,
        "devices_default": 1,
        "diffusion_samples_default": 1,
        "model_default": "boltz2",
        "recycling_steps_default": 3,
        "sampling_steps_default": 200,
        "seed_default": None,
        "seed_flag_available": True,
        "use_msa_server_default": False,
        "write_full_pae_default": True,
    }
    if interface != expected_interface:
        _failure(failures, "runtime_lock_boltz_cli_contract_drift")
    return failures


def _af2_source_failures(runtime: Dict[str, Any], provision: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if not (
        runtime.get("artifact") == "m6d_w3_mechanism_runtime_receipt"
        and runtime.get("status") == "w3_mechanism_runtime_ready_no_prediction"
        and runtime.get("runtime_mode") == "apptainer_colabfold_image"
        and runtime.get("colabfold_version") == "1.6.1"
        and runtime.get("model_type") == "alphafold2_multimer_v3"
        and runtime.get("runtime_sha256") == _AF2_CONTAINER_SHA256
        and runtime.get("weights_manifest_sha256") == _AF2_WEIGHTS_MANIFEST_SHA256
        and _weight_map(runtime.get("weights")) == _AF2_WEIGHTS
        and runtime.get("prediction_executed") is False
        and runtime.get("network_fetch_executed") is False
        and runtime.get("submitted_jobs") == 0
    ):
        _failure(failures, "runtime_lock_af2_runtime_receipt_invalid_or_drifted")
    if not (
        provision.get("artifact") == "m6d_w3_runtime_provision_receipt"
        and provision.get("status") == "w3_runtime_provisioned_and_validated_no_prediction"
        and provision.get("image_uri") == _AF2_CONTAINER_URI
        and provision.get("colabfold_version") == "1.6.1"
        and provision.get("model_type") == "alphafold2_multimer_v3"
        and provision.get("runtime_sha256") == _AF2_CONTAINER_SHA256
        and provision.get("weights_manifest_sha256") == _AF2_WEIGHTS_MANIFEST_SHA256
        and provision.get("gpu_used") is False
        and provision.get("prediction_executed") is False
        and provision.get("submitted_jobs") == 0
    ):
        _failure(failures, "runtime_lock_af2_provision_receipt_invalid_or_drifted")
    if (
        runtime.get("runtime_sha256") != provision.get("runtime_sha256")
        or runtime.get("weights_manifest_sha256") != provision.get("weights_manifest_sha256")
    ):
        _failure(failures, "runtime_lock_af2_source_receipts_disagree")
    return failures


def _boltz_identity() -> Dict[str, Any]:
    return {
        "predictor_id": "boltz2_complex",
        "runtime_family": "boltz",
        "model": "boltz2",
        "boltz_version": _BOLTZ_VERSION,
        "distribution_file_count": _BOLTZ_DISTRIBUTION_FILE_COUNT,
        "distribution_manifest_sha256": _BOLTZ_DISTRIBUTION_SHA256,
        "cache_checkpoints": [
            {"name": name, **_BOLTZ_CHECKPOINTS[name]}
            for name in ("boltz2_conf.ckpt", "boltz2_aff.ckpt")
        ],
        "execution_parameters": {
            "accelerator": "gpu",
            "binder_msa": "single_sequence",
            "devices": 1,
            "diffusion_samples": 1,
            "model": "boltz2",
            "no_kernels": True,
            "output_format": "pdb",
            "prediction_time_network_used": False,
            "python_no_user_site": True,
            "recycling_steps": 3,
            "sampling_steps": 100,
            "seed": 0,
            "target_msa": "reuse_hash_locked_target_msa",
            "templates": False,
            "use_msa_server": False,
            "write_full_pae": True,
        },
    }


def _af2_identity(runtime: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "predictor_id": "af2_multimer_colabfold_v1",
        "runtime_family": "colabfold_af2_multimer",
        "colabfold_version": "1.6.1",
        "model_type": "alphafold2_multimer_v3",
        "container_image_uri": _AF2_CONTAINER_URI,
        "container_sha256": _AF2_CONTAINER_SHA256,
        "weights_manifest_sha256": _AF2_WEIGHTS_MANIFEST_SHA256,
        "weights": [
            {
                "name": name,
                "size_bytes": _AF2_WEIGHTS[name][0],
                "sha256": _AF2_WEIGHTS[name][1],
            }
            for name in sorted(_AF2_WEIGHTS)
        ],
        "execution_parameters": {
            "binder_msa": "single_sequence",
            "models": 5,
            "num_seeds": 1,
            "prediction_time_network_used": False,
            "random_seed": 0,
            "rank_by": "multimer",
            "recycles": 20,
            "relax_models": 0,
            "target_msa": "reuse_same_hash_locked_target_msa",
            "templates": False,
        },
        "weights_verified_from_runtime_receipt": runtime.get("artifact"),
    }


def _identity_failures(predictor_id: str, identity: Any) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if not isinstance(identity, dict):
        return [{"kind": "runtime_lock_identity_not_object", "predictor_id": predictor_id}]
    if predictor_id == "boltz2_complex":
        if identity != _boltz_identity():
            _failure(failures, "runtime_lock_boltz_frozen_identity_invalid")
        return failures
    expected_af2 = _af2_identity({"artifact": "m6d_w3_mechanism_runtime_receipt"})
    if identity != expected_af2:
        _failure(failures, "runtime_lock_af2_frozen_identity_invalid")
    return failures


def build_runtime_lock(
    protocol_path: str,
    boltz_observation_path: str,
    af2_runtime_receipt_path: str,
    af2_provision_receipt_path: str,
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    boltz_observation = _load_object(boltz_observation_path)
    af2_runtime = _load_object(af2_runtime_receipt_path)
    af2_provision = _load_object(af2_provision_receipt_path)
    failures = _protocol_failures(protocol)
    failures.extend(_boltz_observation_failures(boltz_observation))
    failures.extend(_af2_source_failures(af2_runtime, af2_provision))
    identities = {
        "boltz2_complex": _boltz_identity(),
        "af2_multimer_colabfold_v1": _af2_identity(af2_runtime),
    }
    identity_digests = {
        predictor_id: canonical_sha256(identity)
        for predictor_id, identity in identities.items()
    }
    protocol_sha256 = _sha256_file(protocol_path)
    locked_scientific_digest = canonical_sha256(protocol.get("locked_scientific_protocol"))
    source_bindings = {
        "protocol": {"path": protocol_path, "sha256": protocol_sha256},
        "boltz_runtime_observation": {
            "path": boltz_observation_path,
            "sha256": _sha256_file(boltz_observation_path),
        },
        "af2_runtime_receipt": {
            "path": af2_runtime_receipt_path,
            "sha256": _sha256_file(af2_runtime_receipt_path),
        },
        "af2_provision_receipt": {
            "path": af2_provision_receipt_path,
            "sha256": _sha256_file(af2_provision_receipt_path),
        },
    }
    digest_input = {
        "protocol_sha256": protocol_sha256,
        "locked_scientific_digest": locked_scientific_digest,
        "predictor_runtime_identities": identities,
        "predictor_runtime_identity_sha256": identity_digests,
        "source_sha256": {
            key: value["sha256"] for key, value in source_bindings.items()
        },
    }
    ready = not failures
    return {
        "artifact": "m6d_w3b_runtime_lock",
        "version": 1,
        "status": (
            "w3b_dual_predictor_runtime_locked_no_submit"
            if ready else
            "w3b_dual_predictor_runtime_lock_blocked"
        ),
        "audit_ok": ready,
        "runtime_identity_ready": ready,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_compute": True,
        "prediction_executed": False,
        "submitted_jobs": 0,
        "cayuga_submission_allowed": False,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "protocol": protocol_path,
        "protocol_sha256": protocol_sha256,
        "locked_scientific_digest": locked_scientific_digest,
        "source_bindings": source_bindings,
        "predictor_runtime_identities": identities,
        "predictor_runtime_identity_sha256": identity_digests,
        "runtime_lock_digest_sha256": canonical_sha256(digest_input),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Runtime identity and execution-parameter provenance only. This lock submits no work, "
            "authorizes no compute, and supports no W3b or biological-success claim."
        ),
    }


def validate_runtime_lock(lock: Dict[str, Any], protocol_path: str) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    protocol = _load_object(protocol_path)
    failures.extend(_protocol_failures(protocol))
    if not (
        lock.get("artifact") == "m6d_w3b_runtime_lock"
        and lock.get("version") == 1
        and lock.get("status") == "w3b_dual_predictor_runtime_locked_no_submit"
        and lock.get("audit_ok") is True
        and lock.get("runtime_identity_ready") is True
        and lock.get("no_submit") is True
        and lock.get("no_api_spend") is True
        and lock.get("no_gpu_compute") is True
        and lock.get("prediction_executed") is False
        and lock.get("submitted_jobs") == 0
        and lock.get("cayuga_submission_allowed") is False
        and lock.get("can_generate_candidates_or_run_predictors") is False
        and lock.get("can_claim_w3b") is False
        and lock.get("n_failures") == 0
        and lock.get("failures") == []
    ):
        _failure(failures, "runtime_lock_boundary_or_status_invalid")
    protocol_sha256 = _sha256_file(protocol_path)
    scientific_digest = canonical_sha256(protocol.get("locked_scientific_protocol"))
    if lock.get("protocol_sha256") != protocol_sha256:
        _failure(failures, "runtime_lock_protocol_sha256_mismatch")
    if lock.get("locked_scientific_digest") != scientific_digest:
        _failure(failures, "runtime_lock_scientific_digest_mismatch")
    identities = lock.get("predictor_runtime_identities")
    identity_digests = lock.get("predictor_runtime_identity_sha256")
    if not isinstance(identities, dict) or set(identities) != set(_PREDICTORS):
        _failure(failures, "runtime_lock_predictor_identity_set_invalid")
        identities = {}
    if not isinstance(identity_digests, dict) or set(identity_digests) != set(_PREDICTORS):
        _failure(failures, "runtime_lock_predictor_digest_set_invalid")
        identity_digests = {}
    for predictor_id in _PREDICTORS:
        identity = identities.get(predictor_id)
        failures.extend(_identity_failures(predictor_id, identity))
        observed_digest = identity_digests.get(predictor_id)
        if not _is_sha256(observed_digest) or observed_digest != canonical_sha256(identity):
            _failure(failures, "runtime_lock_predictor_digest_invalid", predictor_id=predictor_id)
    source_bindings = lock.get("source_bindings")
    source_sha256: Dict[str, Any] = {}
    if not isinstance(source_bindings, dict):
        _failure(failures, "runtime_lock_source_bindings_invalid")
    else:
        for key in ("protocol", "boltz_runtime_observation", "af2_runtime_receipt", "af2_provision_receipt"):
            binding = source_bindings.get(key)
            if not isinstance(binding, dict) or not _is_sha256(binding.get("sha256")):
                _failure(failures, "runtime_lock_source_binding_invalid", source=key)
                continue
            source_sha256[key] = binding["sha256"]
            path = binding.get("path")
            if (
                not isinstance(path, str)
                or not os.path.isfile(path)
                or _sha256_file(path) != binding["sha256"]
            ):
                _failure(failures, "runtime_lock_source_file_hash_mismatch", source=key)
        protocol_binding = source_bindings.get("protocol")
        if not isinstance(protocol_binding, dict) or protocol_binding.get("sha256") != protocol_sha256:
            _failure(failures, "runtime_lock_protocol_source_binding_mismatch")
    digest_input = {
        "protocol_sha256": protocol_sha256,
        "locked_scientific_digest": scientific_digest,
        "predictor_runtime_identities": identities,
        "predictor_runtime_identity_sha256": identity_digests,
        "source_sha256": source_sha256,
    }
    if lock.get("runtime_lock_digest_sha256") != canonical_sha256(digest_input):
        _failure(failures, "runtime_lock_digest_mismatch")
    return failures


def runtime_identity(lock: Dict[str, Any], predictor_id: str, protocol_path: str) -> Dict[str, Any]:
    if predictor_id not in _PREDICTORS:
        raise ValueError(f"unsupported W3b predictor: {predictor_id}")
    failures = validate_runtime_lock(lock, protocol_path)
    if failures:
        raise ValueError(f"W3b runtime lock is invalid: {failures[0]['kind']}")
    return dict(lock["predictor_runtime_identities"][predictor_id])


def build_readiness(runtime_lock_path: str, execution_readiness_path: str) -> Dict[str, Any]:
    lock = _load_object(runtime_lock_path)
    execution = _load_object(execution_readiness_path)
    protocol_path = str(lock.get("protocol") or "")
    failures = validate_runtime_lock(lock, protocol_path) if os.path.isfile(protocol_path) else [
        {"kind": "runtime_lock_protocol_file_missing"}
    ]
    if execution.get("audit_ok") is not True or execution.get("no_submit") is not True:
        _failure(failures, "runtime_lock_execution_readiness_invalid")
    if execution.get("protocol_sha256") != lock.get("protocol_sha256"):
        _failure(failures, "runtime_lock_execution_protocol_binding_mismatch")
    runtime_ready = not failures
    execution_lock_ready = execution.get("execution_lock_ready") is True
    stage_ready = runtime_ready and execution_lock_ready
    if failures:
        status = "w3b_runtime_lock_readiness_blocked"
    elif stage_ready:
        status = "w3b_runtime_lock_ready_for_separate_fit_approval_packet"
    else:
        status = "w3b_runtime_locked_awaiting_execution_lock"
    return {
        "artifact": "m6d_w3b_runtime_lock_readiness",
        "status": status,
        "audit_ok": not failures,
        "runtime_identity_ready": runtime_ready,
        "execution_lock_ready": execution_lock_ready,
        "fit_packet_prerequisites_ready": stage_ready,
        "no_submit": True,
        "can_submit_fit_stage": False,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "runtime_lock": runtime_lock_path,
        "runtime_lock_sha256": _sha256_file(runtime_lock_path),
        "runtime_lock_digest_sha256": lock.get("runtime_lock_digest_sha256"),
        "execution_lock_readiness": execution_readiness_path,
        "execution_lock_readiness_sha256": _sha256_file(execution_readiness_path),
        "predictor_runtime_identity_sha256": lock.get("predictor_runtime_identity_sha256"),
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Runtime readiness only. No W3b target MSA, candidate, predictor, scheduler, API, or GPU action "
            "is authorized by this artifact."
        ),
        "next_action": (
            "prepare a separately approval-gated fit-stage packet bound to both locks"
            if stage_ready else
            "obtain exact approval for the eight-target W3b target-MSA precompute, then materialize the execution lock"
            if runtime_ready else
            "repair runtime-lock provenance before any W3b compute"
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    return "\n".join([
        "# M6d W3b Runtime-Lock Readiness",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Runtime identity ready: `{report['runtime_identity_ready']}`.",
        f"Execution lock ready: `{report['execution_lock_ready']}`.",
        f"Fit packet prerequisites ready: `{report['fit_packet_prerequisites_ready']}`.",
        f"No submit: `{report['no_submit']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- runtime lock digest: `{report['runtime_lock_digest_sha256']}`",
        f"- failures: `{report['n_failures']}`",
        "",
        f"Next action: {report['next_action']}.",
        "",
    ])


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--boltz-observation", default="results/m6d_w3b_boltz_runtime_observation.json")
    parser.add_argument("--af2-runtime-receipt", default="results/m6d_w3_mechanism_runtime_receipt.json")
    parser.add_argument("--af2-provision-receipt", default="results/m6d_w3_runtime_provision_receipt.json")
    parser.add_argument("--execution-readiness", default="results/m6d_w3b_execution_lock_readiness.json")
    parser.add_argument("--out-lock", default="configs/m6d_w3b_runtime_lock.json")
    parser.add_argument("--out-readiness", default="results/m6d_w3b_runtime_lock_readiness.json")
    parser.add_argument("--out-readiness-md", default="results/m6d_w3b_runtime_lock_readiness.md")
    args = parser.parse_args(argv)
    lock = build_runtime_lock(
        args.protocol,
        args.boltz_observation,
        args.af2_runtime_receipt,
        args.af2_provision_receipt,
    )
    _write_json(args.out_lock, lock)
    readiness = build_readiness(args.out_lock, args.execution_readiness)
    _write_json(args.out_readiness, readiness)
    _write_text(args.out_readiness_md, render_markdown(readiness))
    print(
        f"status={readiness['status']} audit_ok={readiness['audit_ok']} "
        f"runtime_ready={readiness['runtime_identity_ready']} no_submit=True"
    )
    return 0 if readiness["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
