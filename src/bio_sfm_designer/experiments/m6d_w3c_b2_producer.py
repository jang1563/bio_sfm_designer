"""Strict producers for the frozen W3c-B2 native-complex screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
)
from bio_sfm_designer.experiments.m6d_w3b_structure_metrics import (
    ca_coords,
    interface_pae,
    lrmsd,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    LRMSD_THRESHOLD_ANGSTROM,
    PREDICTOR_IDS,
    TARGET_IDS,
    _first_sequence,
    _pdb_chain_sequence,
    _runtime_lock_failures,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_runtime import (
    validate_observation,
    validate_runtime_lock_artifact,
)


def load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256_file(path: Union[str, os.PathLike]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    if destination.exists():
        raise ValueError(f"refusing to overwrite W3c-B2 artifact: {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def _bound_path(manifest: Mapping[str, Any], name: str) -> str:
    bindings = manifest.get("bound_artifacts")
    binding = bindings.get(name) if isinstance(bindings, dict) else None
    path = binding.get("path") if isinstance(binding, dict) else None
    if (
        not isinstance(path, str)
        or not os.path.isfile(path)
        or binding.get("sha256") != sha256_file(path)
    ):
        raise ValueError(f"W3c-B2 bound artifact drifted: {name}")
    return path


def load_context(
    manifest_path: str,
    runtime_lock_path: str,
    target_id: str,
    predictor_id: str,
) -> Dict[str, Any]:
    """Load one target only after every frozen input and runtime binding agrees."""

    manifest = load_object(manifest_path)
    runtime_lock = load_object(runtime_lock_path)
    manifest_sha256 = sha256_file(manifest_path)
    if not (
        manifest.get("artifact") == "m6d_w3c_b2_native_screen_manifest"
        and manifest.get("version") == 1
        and manifest.get("status")
        == "w3c_b2_native_screen_manifest_locked_no_submit"
        and manifest.get("target_ids") == TARGET_IDS
        and manifest.get("predictor_ids") == PREDICTOR_IDS
        and manifest.get("target_count") == 8
        and manifest.get("maximum_predictor_evaluations") == 16
        and manifest.get("proteinmpnn_designs") == 0
        and manifest.get("predictor_evaluations_authorized") == 0
        and manifest.get("prediction_executed") is False
        and manifest.get("no_submit") is True
        and manifest.get("cayuga_submission_allowed") is False
    ):
        raise ValueError("W3c-B2 native-screen manifest boundary is invalid")
    if predictor_id not in PREDICTOR_IDS:
        raise ValueError(f"unsupported W3c-B2 predictor: {predictor_id}")
    runtime_failures = _runtime_lock_failures(
        runtime_lock,
        manifest,
        manifest_sha256=manifest_sha256,
    )
    if runtime_failures:
        raise ValueError(
            "W3c-B2 runtime lock is invalid: " + ",".join(runtime_failures)
        )
    materialized_runtime_failures = validate_runtime_lock_artifact(
        runtime_lock,
        manifest,
        runtime_lock_path=runtime_lock_path,
        native_manifest_path=manifest_path,
    )
    if materialized_runtime_failures:
        raise ValueError(
            "W3c-B2 materialized runtime lock is invalid: "
            + ",".join(materialized_runtime_failures)
        )

    for name in (
        "protocol",
        "w3c_b1_execution_manifest",
        "w3c_b1_completion",
        "w3b_runtime_transfer_source",
        "w3b_runtime_source_protocol",
    ):
        _bound_path(manifest, name)
    targets = {
        str(row.get("target_id") or ""): row
        for row in manifest.get("targets", [])
        if isinstance(row, dict)
    }
    if list(targets) != TARGET_IDS or target_id not in targets:
        raise ValueError(f"W3c-B2 target scope is invalid: {target_id}")
    target = targets[target_id]
    prepared_pdb = str(target.get("prepared_pdb") or "")
    target_msa = str(target.get("target_msa") or "")
    target_fasta = str(target.get("target_fasta") or "")
    for path, expected_sha256, label in (
        (prepared_pdb, target.get("prepared_pdb_sha256"), "prepared_pdb"),
        (target_msa, target.get("target_msa_sha256"), "target_msa"),
        (target_fasta, target.get("target_fasta_sha256"), "target_fasta"),
    ):
        if (
            not os.path.isfile(path)
            or os.path.getsize(path) <= 0
            or sha256_file(path) != expected_sha256
        ):
            raise ValueError(f"{target_id}: W3c-B2 input drifted: {label}")
    target_sequence = _pdb_chain_sequence(
        prepared_pdb, str(target["target_chain"])
    )
    binder_sequence = _pdb_chain_sequence(
        prepared_pdb, str(target["binder_chain"])
    )
    if not (
        len(target_sequence) == target.get("target_sequence_length")
        and sequence_sha256(target_sequence)
        == target.get("target_sequence_sha256")
        and len(binder_sequence) == target.get("binder_sequence_length")
        and sequence_sha256(binder_sequence)
        == target.get("binder_sequence_sha256")
        and _first_sequence(target_fasta) == target_sequence
        and _first_sequence(target_msa, a3m=True) == target_sequence
    ):
        raise ValueError(f"{target_id}: W3c-B2 native sequence binding drifted")
    outputs = target.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError(f"{target_id}: W3c-B2 output contract is missing")
    return {
        "manifest_path": manifest_path,
        "runtime_lock_path": runtime_lock_path,
        "manifest": manifest,
        "runtime_lock": runtime_lock,
        "target": target,
        "target_sequence": target_sequence,
        "binder_sequence": binder_sequence,
        "predictor_id": predictor_id,
        "bindings": {
            "native_screen_manifest_sha256": manifest_sha256,
            "runtime_lock_sha256": sha256_file(runtime_lock_path),
            "runtime_lock_digest_sha256": runtime_lock[
                "runtime_lock_digest_sha256"
            ],
        },
    }


def validate_runtime_observation_file(
    context: Mapping[str, Any],
    observation_path: str,
) -> Dict[str, Any]:
    observation = load_object(observation_path)
    manifest = context["manifest"]
    predictor_id = str(context["predictor_id"])
    failed = validate_observation(
        observation,
        predictor_id,
        protocol_path=_bound_path(manifest, "protocol"),
        native_manifest_path=str(context["manifest_path"]),
        b1_completion_path=_bound_path(manifest, "w3c_b1_completion"),
        w3b_runtime_lock_path=_bound_path(
            manifest, "w3b_runtime_transfer_source"
        ),
    )
    expected_identity = context["runtime_lock"][
        "predictor_runtime_identities"
    ][predictor_id]
    expected_digest = context["runtime_lock"][
        "predictor_runtime_identity_sha256"
    ][predictor_id]
    if (
        failed
        or observation.get("runtime_identity") != expected_identity
        or observation.get("runtime_identity_sha256") != expected_digest
    ):
        raise ValueError(
            f"observed {predictor_id} runtime differs from the W3c-B2 lock: "
            + ",".join(failed)
        )
    return observation


def prepare_af2_input(
    context: Mapping[str, Any],
    input_dir: str,
    manifest_path: str,
) -> Dict[str, Any]:
    target = context["target"]
    expected = target["outputs"]
    if (
        input_dir != expected["af2_input_dir"]
        or manifest_path != expected["af2_input_manifest"]
    ):
        raise ValueError("W3c-B2 AF2 input paths differ from the native manifest")
    destination = Path(input_dir)
    manifest_destination = Path(manifest_path)
    if destination.exists() or manifest_destination.exists():
        raise ValueError("W3c-B2 AF2 input artifacts must be absent")
    staging = destination.with_name(destination.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    candidate_id = str(target["native_candidate_id"])
    a3m = build_annotated_multimer_a3m(
        Path(str(target["target_msa"])).read_text(),
        str(context["target_sequence"]),
        str(context["binder_sequence"]),
    )
    staged_path = staging / f"{candidate_id}.a3m"
    staged_path.write_text(a3m)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, destination)
    final_path = destination / staged_path.name
    payload = {
        "artifact": "m6d_w3c_b2_af2_input_manifest",
        "version": 1,
        "status": "w3c_b2_native_af2_input_ready_for_locked_prediction",
        "target_id": target["target_id"],
        "native_candidate_id": candidate_id,
        "input_dir": input_dir,
        "a3m_path": str(final_path),
        "a3m_sha256": sha256_file(final_path),
        "target_sequence_sha256": target["target_sequence_sha256"],
        "binder_sequence_sha256": target["binder_sequence_sha256"],
        "target_msa_sha256": target["target_msa_sha256"],
        "reference_backbone_sha256": target["prepared_pdb_sha256"],
        "bindings": dict(context["bindings"]),
        "prediction_contract": {
            "model_type": "alphafold2_multimer_v3",
            "models": 5,
            "num_seeds": 1,
            "random_seed": 0,
            "recycles": 20,
            "rank_by": "multimer",
            "relax_models": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
        },
    }
    _write_json(manifest_path, payload)
    return payload


def _rank_zero_boltz_files(output_dir: Path) -> Dict[str, Path]:
    name = "w3cb2"
    roots = list(output_dir.glob(f"boltz_results_*/predictions/{name}"))
    if len(roots) != 1:
        raise ValueError(
            f"expected one W3c-B2 Boltz prediction directory; observed {len(roots)}"
        )
    root = roots[0]
    expected = {
        "model": list(root.glob(f"{name}_model_0.pdb")),
        "confidence": list(root.glob(f"confidence_{name}_model_0.json")),
        "pae": list(root.glob(f"pae_{name}_model_0.npz")),
    }
    if any(len(paths) != 1 for paths in expected.values()):
        counts = {key: len(paths) for key, paths in expected.items()}
        raise ValueError(f"incomplete W3c-B2 Boltz outputs: {counts}")
    return {key: paths[0] for key, paths in expected.items()}


def _rank_one_af2_files(
    output_dir: Path,
    candidate_id: str,
) -> Tuple[Path, Path, str]:
    models = sorted(output_dir.glob(f"{candidate_id}_unrelaxed_rank_001_*.pdb"))
    scores = sorted(output_dir.glob(f"{candidate_id}_scores_rank_001_*.json"))
    if len(models) != 1 or len(scores) != 1:
        raise ValueError(
            f"{candidate_id}: expected one AF2 rank-001 model and score file"
        )
    model_tag = models[0].name.replace(
        f"{candidate_id}_unrelaxed_", ""
    ).removesuffix(".pdb")
    score_tag = scores[0].name.replace(
        f"{candidate_id}_scores_", ""
    ).removesuffix(".json")
    if model_tag != score_tag:
        raise ValueError(f"{candidate_id}: AF2 model and score tags differ")
    return models[0], scores[0], model_tag


def _strict_metrics(
    context: Mapping[str, Any],
    model_path: str,
    pae: np.ndarray,
) -> Tuple[float, float]:
    target = context["target"]
    target_length = int(target["target_sequence_length"])
    binder_length = int(target["binder_sequence_length"])
    expected_size = target_length + binder_length
    matrix = np.asarray(pae, dtype=float)
    if matrix.shape != (expected_size, expected_size):
        raise ValueError("W3c-B2 pAE shape differs from the locked complex length")
    reference_target = ca_coords(
        str(target["prepared_pdb"]), str(target["target_chain"])
    )
    reference_binder = ca_coords(
        str(target["prepared_pdb"]), str(target["binder_chain"])
    )
    fold_target = ca_coords(model_path, "A")
    fold_binder = ca_coords(model_path, "B")
    if not (
        len(reference_target) == len(fold_target) == target_length
        and len(reference_binder) == len(fold_binder) == binder_length
    ):
        raise ValueError("W3c-B2 model/reference CA lengths differ from the lock")
    return (
        interface_pae(matrix, target_length),
        lrmsd(fold_target, fold_binder, reference_target, reference_binder),
    )


def _record(
    context: Mapping[str, Any],
    model_path: str,
    confidence_path: str,
    observed_interface_pae: float,
    observed_lrmsd: float,
    *,
    auxiliary_bindings: Optional[Mapping[str, Mapping[str, str]]] = None,
    confidence_metrics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    target = context["target"]
    predictor_id = str(context["predictor_id"])
    if not all(
        math.isfinite(value)
        for value in (observed_interface_pae, observed_lrmsd)
    ):
        raise ValueError("W3c-B2 native metrics must be finite")
    return {
        "artifact": "m6d_w3c_b2_native_prediction_record",
        "version": 1,
        "status": "strict_qc_complete",
        "record_id": f"w3c-b2-native-{target['target_id']}-{predictor_id}",
        "native_candidate_id": target["native_candidate_id"],
        "complex_target_id": target["target_id"],
        "predictor_id": predictor_id,
        "target_sequence_sha256": target["target_sequence_sha256"],
        "binder_sequence_sha256": target["binder_sequence_sha256"],
        "target_msa_sha256": target["target_msa_sha256"],
        "reference_backbone_sha256": target["prepared_pdb_sha256"],
        "runtime_identity_sha256": context["runtime_lock"][
            "predictor_runtime_identity_sha256"
        ][predictor_id],
        "runtime_lock_sha256": context["bindings"]["runtime_lock_sha256"],
        "seed": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
        "interface_pae": round(float(observed_interface_pae), 4),
        "lrmsd_angstrom": float(observed_lrmsd),
        "lrmsd_threshold_angstrom": LRMSD_THRESHOLD_ANGSTROM,
        "success": observed_lrmsd < LRMSD_THRESHOLD_ANGSTROM,
        "strict_qc_passed": True,
        "output_bindings": {
            "model": {
                "path": model_path,
                "sha256": sha256_file(model_path),
            },
            "confidence": {
                "path": confidence_path,
                "sha256": sha256_file(confidence_path),
            },
        },
        "auxiliary_output_bindings": dict(auxiliary_bindings or {}),
        "confidence_metrics": dict(confidence_metrics or {}),
    }


def run_boltz(
    context: Mapping[str, Any],
    runtime_observation_path: str,
    boltz_bin: str,
) -> Dict[str, Any]:
    validate_runtime_observation_file(context, runtime_observation_path)
    target = context["target"]
    output_dir = Path(str(target["outputs"]["boltz_output_dir"]))
    record_path = str(target["outputs"]["boltz_record"])
    if output_dir.exists() or os.path.exists(record_path):
        raise ValueError("W3c-B2 Boltz outputs must be absent")
    staging = output_dir.with_name(output_dir.name + ".tmp")
    if staging.exists():
        raise ValueError("W3c-B2 Boltz staging directory already exists")
    input_dir = staging / "input"
    prediction_dir = staging / "prediction"
    input_dir.mkdir(parents=True)
    yaml_path = input_dir / "w3cb2.yaml"
    yaml_path.write_text(
        "version: 1\n"
        "sequences:\n"
        "  - protein:\n"
        "      id: A\n"
        f"      sequence: {context['target_sequence']}\n"
        f"      msa: {json.dumps(os.path.abspath(str(target['target_msa'])))}\n"
        "  - protein:\n"
        "      id: B\n"
        f"      sequence: {context['binder_sequence']}\n"
        "      msa: empty\n"
        "templates: []\n"
    )
    command = [
        boltz_bin,
        "predict",
        str(input_dir),
        "--out_dir",
        str(prediction_dir),
        "--no_kernels",
        "--output_format",
        "pdb",
        "--accelerator",
        "gpu",
        "--devices",
        "1",
        "--model",
        "boltz2",
        "--seed",
        "0",
        "--recycling_steps",
        "3",
        "--diffusion_samples",
        "1",
        "--sampling_steps",
        "100",
        "--write_full_pae",
    ]
    subprocess.run(command, check=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, output_dir)
    files = _rank_zero_boltz_files(output_dir / "prediction")
    with open(files["confidence"]) as handle:
        confidence = json.load(handle)
    with np.load(files["pae"]) as archive:
        if len(archive.files) != 1:
            raise ValueError("W3c-B2 Boltz output must contain one pAE array")
        pae = np.asarray(archive[archive.files[0]], dtype=float)
    metrics = {
        "complex_plddt": float(confidence["complex_plddt"]),
        "ptm": float(confidence["ptm"]),
        "iptm": float(confidence["iptm"]),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("W3c-B2 Boltz confidence metrics must be finite")
    observed_pae, observed_lrmsd = _strict_metrics(
        context, str(files["model"]), pae
    )
    record = _record(
        context,
        str(files["model"]),
        str(files["confidence"]),
        observed_pae,
        observed_lrmsd,
        auxiliary_bindings={
            "pae": {
                "path": str(files["pae"]),
                "sha256": sha256_file(files["pae"]),
            }
        },
        confidence_metrics=metrics,
    )
    _write_json(record_path, record)
    return record


def _validate_af2_input_manifest(
    context: Mapping[str, Any],
    manifest_path: str,
) -> Dict[str, Any]:
    target = context["target"]
    value = load_object(manifest_path)
    a3m_path = value.get("a3m_path")
    if not (
        value.get("artifact") == "m6d_w3c_b2_af2_input_manifest"
        and value.get("status")
        == "w3c_b2_native_af2_input_ready_for_locked_prediction"
        and value.get("target_id") == target["target_id"]
        and value.get("native_candidate_id") == target["native_candidate_id"]
        and value.get("input_dir") == target["outputs"]["af2_input_dir"]
        and value.get("target_sequence_sha256")
        == target["target_sequence_sha256"]
        and value.get("binder_sequence_sha256")
        == target["binder_sequence_sha256"]
        and value.get("target_msa_sha256") == target["target_msa_sha256"]
        and value.get("reference_backbone_sha256")
        == target["prepared_pdb_sha256"]
        and value.get("bindings") == context["bindings"]
        and isinstance(a3m_path, str)
        and os.path.isfile(a3m_path)
        and value.get("a3m_sha256") == sha256_file(a3m_path)
        and value.get("prediction_contract")
        == {
            "model_type": "alphafold2_multimer_v3",
            "models": 5,
            "num_seeds": 1,
            "random_seed": 0,
            "recycles": 20,
            "rank_by": "multimer",
            "relax_models": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
        }
    ):
        raise ValueError("W3c-B2 AF2 input manifest drifted")
    return value


def convert_af2(
    context: Mapping[str, Any],
    runtime_observation_path: str,
    input_manifest_path: str,
    output_dir: str,
) -> Dict[str, Any]:
    validate_runtime_observation_file(context, runtime_observation_path)
    target = context["target"]
    if (
        input_manifest_path != target["outputs"]["af2_input_manifest"]
        or output_dir != target["outputs"]["af2_output_dir"]
    ):
        raise ValueError("W3c-B2 AF2 paths differ from the native manifest")
    _validate_af2_input_manifest(context, input_manifest_path)
    record_path = str(target["outputs"]["af2_record"])
    if os.path.exists(record_path):
        raise ValueError("W3c-B2 AF2 record must be absent")
    model, scores_path, model_tag = _rank_one_af2_files(
        Path(output_dir), str(target["native_candidate_id"])
    )
    scores = load_object(str(scores_path))
    pae = np.asarray(scores.get("pae"), dtype=float)
    plddt = np.asarray(scores.get("plddt"), dtype=float)
    expected_size = int(target["target_sequence_length"]) + int(
        target["binder_sequence_length"]
    )
    if (
        plddt.size != expected_size
        or not np.isfinite(plddt).all()
        or not math.isfinite(float(scores.get("iptm")))
        or not math.isfinite(float(scores.get("ptm")))
    ):
        raise ValueError("W3c-B2 AF2 confidence arrays or metrics are invalid")
    observed_pae, observed_lrmsd = _strict_metrics(
        context, str(model), pae
    )
    record = _record(
        context,
        str(model),
        str(scores_path),
        observed_pae,
        observed_lrmsd,
        auxiliary_bindings={
            "input_manifest": {
                "path": input_manifest_path,
                "sha256": sha256_file(input_manifest_path),
            }
        },
        confidence_metrics={
            "mean_plddt": float(np.mean(plddt)),
            "ptm": float(scores["ptm"]),
            "iptm": float(scores["iptm"]),
            "model_tag": model_tag,
        },
    )
    _write_json(record_path, record)
    return record


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="configs/m6d_w3c_b2_native_screen_manifest.json",
    )
    parser.add_argument(
        "--runtime-lock", default="configs/m6d_w3c_b2_runtime_lock.json"
    )
    parser.add_argument("--target-id", choices=TARGET_IDS, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    target = subparsers.add_parser("target")
    target.add_argument("--predictor-id", choices=PREDICTOR_IDS, required=True)
    prepare = subparsers.add_parser("prepare-af2")
    prepare.add_argument("--input-dir", required=True)
    prepare.add_argument("--out-manifest", required=True)
    boltz = subparsers.add_parser("run-boltz")
    boltz.add_argument("--runtime-observation", required=True)
    boltz.add_argument("--boltz-bin", required=True)
    af2 = subparsers.add_parser("convert-af2")
    af2.add_argument("--runtime-observation", required=True)
    af2.add_argument("--input-manifest", required=True)
    af2.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    predictor_id = (
        args.predictor_id
        if args.command == "target"
        else (
            "boltz2_complex"
            if args.command == "run-boltz"
            else "af2_multimer_colabfold_v1"
        )
    )
    context = load_context(
        args.manifest,
        args.runtime_lock,
        args.target_id,
        predictor_id,
    )
    if args.command == "target":
        print(
            f"target={args.target_id} predictor={predictor_id} "
            "context_valid=True prediction_executed=False"
        )
        return 0
    if args.command == "prepare-af2":
        payload = prepare_af2_input(
            context, args.input_dir, args.out_manifest
        )
        print(
            f"target={args.target_id} af2_input_ready=True "
            f"a3m_sha256={payload['a3m_sha256']}"
        )
        return 0
    if args.command == "run-boltz":
        record = run_boltz(
            context, args.runtime_observation, args.boltz_bin
        )
    else:
        record = convert_af2(
            context,
            args.runtime_observation,
            args.input_manifest,
            args.output_dir,
        )
    print(
        f"target={args.target_id} predictor={predictor_id} "
        f"success={record['success']} strict_qc=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
