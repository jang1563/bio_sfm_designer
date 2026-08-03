"""Validate and convert the frozen W3d prospective prediction cells."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from bio_sfm_designer.experiments import m6d_w3d_input_runtime as input_runtime
from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as diagnostic
from bio_sfm_designer.experiments.m6d_w3b_structure_metrics import (
    ca_coords,
    interface_pae,
    lrmsd,
)


INPUT_MANIFEST_PATH = input_runtime.INPUT_MANIFEST_PATH
RUNTIME_RECEIPT_PATH = input_runtime.RUNTIME_RECEIPT_PATH
NATIVE_MANIFEST_PATH = input_runtime.NATIVE_MANIFEST_PATH
LRMSD_THRESHOLD_ANGSTROM = 4.0


def _load_object(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json_no_overwrite(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite W3d artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _repo_relative_path(value: Any, *, prefix: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("W3d execution path must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("W3d execution path must be repository-relative")
    normalized = path.as_posix()
    if normalized != prefix and not normalized.startswith(prefix + "/"):
        raise ValueError(f"W3d execution path must remain under {prefix}")
    return normalized


def _resolve_repo_path(root: Path, value: Any, *, prefix: str) -> Path:
    relative = _repo_relative_path(value, prefix=prefix)
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("W3d execution path escapes the project root")
    return resolved


def _binding(path: Path, *, root: Path) -> Dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"W3d bound file is missing or empty: {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": input_runtime.sha256_file(path),
    }


def _cell_key(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(row.get("target_id") or ""),
        str(row.get("representation_id") or ""),
        str(row.get("predictor_id") or ""),
    )


def load_cell_context(
    target_id: str,
    representation_id: str,
    predictor_id: str,
    *,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
    runtime_receipt_path: str = RUNTIME_RECEIPT_PATH,
    project_root: str = ".",
    require_files: bool = True,
) -> Dict[str, Any]:
    """Load one prospective cell after all frozen bindings agree."""

    root = Path(project_root).resolve()
    input_manifest = _load_object(input_manifest_path)
    input_runtime.validate_input_manifest(
        input_manifest,
        input_manifest_path=input_manifest_path,
        project_root=root,
        require_files=require_files,
    )
    runtime_receipt = _load_object(runtime_receipt_path)
    input_runtime.validate_runtime_receipt(
        runtime_receipt,
        input_manifest_path=input_manifest_path,
    )
    key = (target_id, representation_id, predictor_id)
    matching = [
        row
        for row in input_manifest["cells"]
        if isinstance(row, dict) and _cell_key(row) == key
    ]
    if len(matching) != 1:
        raise ValueError(f"W3d prospective cell is missing or duplicated: {key}")
    cell = matching[0]
    if cell.get("prediction_authorized") is not False:
        raise ValueError("W3d source input manifest unexpectedly authorizes prediction")

    native_binding = input_manifest.get("native_manifest_binding")
    if not isinstance(native_binding, dict):
        raise ValueError("W3d native-manifest binding is missing")
    native_path = str(native_binding.get("path") or "")
    native_manifest = _load_object(native_path)
    if native_binding != input_runtime._binding(native_path):
        raise ValueError("W3d native-manifest binding drifted")
    targets = native_manifest.get("targets")
    matching_targets = [
        row
        for row in targets if isinstance(row, dict) and row.get("target_id") == target_id
    ] if isinstance(targets, list) else []
    if len(matching_targets) != 1:
        raise ValueError(f"W3d native target is missing or duplicated: {target_id}")
    target = matching_targets[0]
    if not (
        cell.get("target_sequence_sha256") == target.get("target_sequence_sha256")
        and cell.get("binder_sequence_sha256") == target.get("binder_sequence_sha256")
        and cell.get("target_sequence_length") == target.get("target_sequence_length")
        and cell.get("binder_sequence_length") == target.get("binder_sequence_length")
        and isinstance(target.get("prepared_pdb_sha256"), str)
        and isinstance(target.get("target_chain"), str)
        and isinstance(target.get("binder_chain"), str)
    ):
        raise ValueError("W3d cell and native-target identity disagree")

    input_path = _resolve_repo_path(
        root,
        cell["input_path"],
        prefix="hpc_outputs/m6d_w3d_native_diagnostic",
    )
    output_dir = _resolve_repo_path(
        root,
        cell["planned_output_dir"],
        prefix="hpc_outputs/m6d_w3d_native_diagnostic",
    )
    record_path = _resolve_repo_path(
        root,
        cell["planned_record"],
        prefix="hpc_outputs/m6d_w3d_native_diagnostic",
    )
    reference_path = _resolve_repo_path(
        root,
        target["prepared_pdb"],
        prefix="hpc_outputs/m6d_w3c_b1_targets",
    )
    if require_files:
        if not (
            input_path.is_file()
            and input_path.stat().st_size == cell["input_bytes"]
            and input_runtime.sha256_file(input_path) == cell["input_sha256"]
        ):
            raise ValueError("W3d cell input is missing or hash-drifted")
        if not (
            reference_path.is_file()
            and input_runtime.sha256_file(reference_path)
            == target["prepared_pdb_sha256"]
        ):
            raise ValueError("W3d reference backbone is missing or hash-drifted")
    return {
        "project_root": root,
        "input_manifest": input_manifest,
        "runtime_receipt": runtime_receipt,
        "runtime_receipt_path": Path(runtime_receipt_path),
        "cell": cell,
        "target": target,
        "input_path": input_path,
        "output_dir": output_dir,
        "record_path": record_path,
        "reference_path": reference_path,
    }


def validate_expected_paths(
    context: Mapping[str, Any],
    *,
    input_path: str,
    output_dir: str,
    record_path: str,
) -> None:
    cell = context["cell"]
    if not (
        input_path == cell["input_path"]
        and output_dir == cell["planned_output_dir"]
        and record_path == cell["planned_record"]
    ):
        raise ValueError("W3d wrapper paths differ from the hash-bound cell")


def validate_runtime_observation_file(
    context: Mapping[str, Any],
    observation_path: str,
) -> Dict[str, Any]:
    observation = _load_object(observation_path)
    predictor_id = context["cell"]["predictor_id"]
    input_runtime._validate_runtime_observation(observation, predictor_id)
    if (
        observation.get("runtime_identity_sha256")
        != context["cell"]["runtime_identity_sha256"]
    ):
        raise ValueError("W3d runtime observation differs from the cell lock")
    return observation


def _strict_metrics(
    context: Mapping[str, Any],
    model_path: Path,
    pae: np.ndarray,
) -> Tuple[float, float]:
    cell = context["cell"]
    target = context["target"]
    target_length = int(cell["target_sequence_length"])
    binder_length = int(cell["binder_sequence_length"])
    expected_size = target_length + binder_length
    matrix = np.asarray(pae, dtype=float)
    if matrix.shape != (expected_size, expected_size) or not np.isfinite(matrix).all():
        raise ValueError("W3d pAE matrix differs from the locked complex length")
    reference_target = ca_coords(str(context["reference_path"]), target["target_chain"])
    reference_binder = ca_coords(str(context["reference_path"]), target["binder_chain"])
    fold_target = ca_coords(str(model_path), "A")
    fold_binder = ca_coords(str(model_path), "B")
    if not (
        len(reference_target) == len(fold_target) == target_length
        and len(reference_binder) == len(fold_binder) == binder_length
    ):
        raise ValueError("W3d model/reference CA lengths differ from the lock")
    return (
        interface_pae(matrix, target_length),
        lrmsd(fold_target, fold_binder, reference_target, reference_binder),
    )


def _record(
    context: Mapping[str, Any],
    *,
    model_path: Path,
    confidence_path: Path,
    observed_interface_pae: float,
    observed_lrmsd: float,
    auxiliary_bindings: Optional[Mapping[str, Mapping[str, Any]]] = None,
    confidence_metrics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if not all(
        math.isfinite(value)
        for value in (observed_interface_pae, observed_lrmsd)
    ):
        raise ValueError("W3d native metrics must be finite")
    root = context["project_root"]
    cell = context["cell"]
    return {
        "artifact": "m6d_w3d_native_prediction_record",
        "version": 1,
        "status": "strict_qc_complete",
        "record_id": cell["cell_id"],
        "cell_id": cell["cell_id"],
        "target_id": cell["target_id"],
        "representation_id": cell["representation_id"],
        "predictor_id": cell["predictor_id"],
        "target_sequence_sha256": cell["target_sequence_sha256"],
        "binder_sequence_sha256": cell["binder_sequence_sha256"],
        "target_msa_sha256": cell["target_msa_sha256"],
        "reference_backbone_sha256": context["target"]["prepared_pdb_sha256"],
        "input_binding": _binding(context["input_path"], root=root),
        "runtime_identity_sha256": cell["runtime_identity_sha256"],
        "runtime_receipt_sha256": input_runtime.sha256_file(
            context["runtime_receipt_path"]
        ),
        "seed": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
        "interface_pae": round(float(observed_interface_pae), 4),
        "lrmsd_angstrom": float(observed_lrmsd),
        "ligand_rmsd_angstrom": float(observed_lrmsd),
        "lrmsd_threshold_angstrom": LRMSD_THRESHOLD_ANGSTROM,
        "success": observed_lrmsd < LRMSD_THRESHOLD_ANGSTROM,
        "strict_qc_passed": True,
        "output_bindings": {
            "model": _binding(model_path, root=root),
            "confidence": _binding(confidence_path, root=root),
        },
        "auxiliary_output_bindings": dict(auxiliary_bindings or {}),
        "confidence_metrics": dict(confidence_metrics or {}),
    }


def _rank_zero_boltz_files(output_dir: Path, name: str) -> Dict[str, Path]:
    roots = list(output_dir.glob(f"boltz_results_*/predictions/{name}"))
    if len(roots) != 1:
        raise ValueError(
            f"expected one W3d Boltz prediction directory; observed {len(roots)}"
        )
    expected = {
        "model": list(roots[0].glob(f"{name}_model_0.pdb")),
        "confidence": list(roots[0].glob(f"confidence_{name}_model_0.json")),
        "pae": list(roots[0].glob(f"pae_{name}_model_0.npz")),
    }
    if any(len(paths) != 1 for paths in expected.values()):
        counts = {key: len(paths) for key, paths in expected.items()}
        raise ValueError(f"incomplete W3d Boltz outputs: {counts}")
    return {key: paths[0] for key, paths in expected.items()}


def _rank_one_af2_files(output_dir: Path, candidate_id: str) -> Tuple[Path, Path, str]:
    models = sorted(output_dir.glob(f"{candidate_id}_unrelaxed_rank_001_*.pdb"))
    scores = sorted(output_dir.glob(f"{candidate_id}_scores_rank_001_*.json"))
    if len(models) != 1 or len(scores) != 1:
        raise ValueError(
            f"{candidate_id}: expected one W3d AF2 rank-001 model and score file"
        )
    model_tag = models[0].name.replace(
        f"{candidate_id}_unrelaxed_", ""
    ).removesuffix(".pdb")
    score_tag = scores[0].name.replace(
        f"{candidate_id}_scores_", ""
    ).removesuffix(".json")
    if model_tag != score_tag:
        raise ValueError(f"{candidate_id}: W3d AF2 model and score tags differ")
    return models[0], scores[0], model_tag


def run_boltz(
    context: Mapping[str, Any],
    *,
    runtime_observation_path: str,
    boltz_bin: str,
) -> Dict[str, Any]:
    if context["cell"]["predictor_id"] != "boltz2_complex":
        raise ValueError("W3d Boltz runner received a non-Boltz cell")
    validate_runtime_observation_file(context, runtime_observation_path)
    output_dir = context["output_dir"]
    record_path = context["record_path"]
    if output_dir.exists() or record_path.exists():
        raise ValueError("W3d Boltz output or record already exists")
    staging = output_dir.with_name(output_dir.name + ".tmp")
    if staging.exists():
        raise ValueError("W3d Boltz staging directory already exists")
    staging.parent.mkdir(parents=True, exist_ok=True)
    command = [
        boltz_bin,
        "predict",
        str(context["input_path"].parent),
        "--out_dir",
        str(staging),
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
    os.replace(staging, output_dir)
    files = _rank_zero_boltz_files(output_dir, context["input_path"].stem)
    confidence = _load_object(str(files["confidence"]))
    with np.load(files["pae"]) as archive:
        if len(archive.files) != 1:
            raise ValueError("W3d Boltz output must contain one pAE array")
        pae = np.asarray(archive[archive.files[0]], dtype=float)
    metrics = {
        "complex_plddt": float(confidence["complex_plddt"]),
        "ptm": float(confidence["ptm"]),
        "iptm": float(confidence["iptm"]),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("W3d Boltz confidence metrics must be finite")
    observed_pae, observed_lrmsd = _strict_metrics(context, files["model"], pae)
    record = _record(
        context,
        model_path=files["model"],
        confidence_path=files["confidence"],
        observed_interface_pae=observed_pae,
        observed_lrmsd=observed_lrmsd,
        auxiliary_bindings={
            "pae": _binding(files["pae"], root=context["project_root"])
        },
        confidence_metrics=metrics,
    )
    _write_json_no_overwrite(record_path, record)
    return record


def convert_af2(
    context: Mapping[str, Any],
    *,
    runtime_observation_path: str,
) -> Dict[str, Any]:
    if context["cell"]["predictor_id"] != "af2_multimer_colabfold_v1":
        raise ValueError("W3d AF2 converter received a non-AF2 cell")
    validate_runtime_observation_file(context, runtime_observation_path)
    output_dir = context["output_dir"]
    record_path = context["record_path"]
    if record_path.exists():
        raise ValueError("W3d AF2 strict-QC record already exists")
    candidate_id = context["input_path"].stem
    model, scores_path, model_tag = _rank_one_af2_files(output_dir, candidate_id)
    scores = _load_object(str(scores_path))
    pae = np.asarray(scores.get("pae"), dtype=float)
    plddt = np.asarray(scores.get("plddt"), dtype=float)
    expected_size = int(context["cell"]["target_sequence_length"]) + int(
        context["cell"]["binder_sequence_length"]
    )
    if not (
        plddt.size == expected_size
        and np.isfinite(plddt).all()
        and math.isfinite(float(scores.get("iptm")))
        and math.isfinite(float(scores.get("ptm")))
    ):
        raise ValueError("W3d AF2 confidence arrays or metrics are invalid")
    observed_pae, observed_lrmsd = _strict_metrics(context, model, pae)
    record = _record(
        context,
        model_path=model,
        confidence_path=scores_path,
        observed_interface_pae=observed_pae,
        observed_lrmsd=observed_lrmsd,
        confidence_metrics={
            "mean_plddt": float(np.mean(plddt)),
            "ptm": float(scores["ptm"]),
            "iptm": float(scores["iptm"]),
            "model_tag": model_tag,
        },
    )
    _write_json_no_overwrite(record_path, record)
    return record


def _context_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    return load_cell_context(
        args.target_id,
        args.representation_id,
        args.predictor_id,
        input_manifest_path=args.input_manifest,
        runtime_receipt_path=args.runtime_receipt,
        project_root=args.project_root,
        require_files=True,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", default=INPUT_MANIFEST_PATH)
    parser.add_argument("--runtime-receipt", default=RUNTIME_RECEIPT_PATH)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--target-id", choices=diagnostic.TARGET_IDS, required=True)
    parser.add_argument(
        "--representation-id", choices=diagnostic.REPRESENTATION_IDS, required=True
    )
    parser.add_argument(
        "--predictor-id", choices=diagnostic.PREDICTOR_IDS, required=True
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-cell")
    validate.add_argument("--expected-input-path", required=True)
    validate.add_argument("--expected-output-dir", required=True)
    validate.add_argument("--expected-record-path", required=True)
    runtime = subparsers.add_parser("validate-runtime")
    runtime.add_argument("--runtime-observation", required=True)
    boltz = subparsers.add_parser("run-boltz")
    boltz.add_argument("--runtime-observation", required=True)
    boltz.add_argument("--boltz-bin", required=True)
    af2 = subparsers.add_parser("convert-af2")
    af2.add_argument("--runtime-observation", required=True)
    args = parser.parse_args(argv)
    context = _context_from_args(args)
    if args.command == "validate-cell":
        validate_expected_paths(
            context,
            input_path=args.expected_input_path,
            output_dir=args.expected_output_dir,
            record_path=args.expected_record_path,
        )
        print(
            f"cell={context['cell']['cell_id']} input_valid=True "
            "prediction_executed=False"
        )
        return 0
    if args.command == "validate-runtime":
        validate_runtime_observation_file(context, args.runtime_observation)
        print(
            f"cell={context['cell']['cell_id']} runtime_valid=True "
            "prediction_executed=False"
        )
        return 0
    if args.command == "run-boltz":
        record = run_boltz(
            context,
            runtime_observation_path=args.runtime_observation,
            boltz_bin=args.boltz_bin,
        )
    else:
        record = convert_af2(
            context,
            runtime_observation_path=args.runtime_observation,
        )
    print(
        f"cell={record['cell_id']} predictor={record['predictor_id']} "
        f"success={record['success']} strict_qc=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
