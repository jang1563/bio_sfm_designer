"""Observe the actual W3b predictor runtime before any prediction starts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    runtime_identity,
    validate_runtime_lock,
)


_BOLTZ_CHECKPOINTS = (
    (
        "boltz2_conf.ckpt",
        True,
        "structure_confidence_model",
    ),
    (
        "boltz2_aff.ckpt",
        False,
        "required_local_cache_affinity_model",
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_distribution_manifest(files: Iterable[Tuple[str, Path]]) -> Tuple[int, str]:
    rows = []
    for relative_path, path in sorted(files, key=lambda row: row[0]):
        if relative_path.endswith(".pyc") or not path.is_file():
            continue
        rows.append({
            "path": relative_path,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        })
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return len(rows), hashlib.sha256(payload).hexdigest()


def observe_boltz(cache_dir: Path, distribution_name: str = "boltz") -> Dict[str, Any]:
    distribution = importlib.metadata.distribution(distribution_name)
    files = [
        (str(relative), Path(distribution.locate_file(relative)))
        for relative in distribution.files or []
    ]
    file_count, manifest_sha256 = canonical_distribution_manifest(files)
    checkpoints: List[Dict[str, Any]] = []
    for name, active, role in _BOLTZ_CHECKPOINTS:
        path = cache_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"required local Boltz checkpoint is missing: {name}")
        checkpoints.append({
            "name": name,
            "active_for_structure_prediction": active,
            "bytes": path.stat().st_size,
            "role": role,
            "sha256": _sha256_file(path),
        })
    return {
        "predictor_id": "boltz2_complex",
        "runtime_family": "boltz",
        "model": "boltz2",
        "boltz_version": importlib.metadata.version(distribution_name),
        "distribution_file_count": file_count,
        "distribution_manifest_sha256": manifest_sha256,
        "cache_checkpoints": checkpoints,
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


def _af2_weights(data_dir: Path) -> Tuple[List[Dict[str, Any]], str]:
    params = data_dir / "params"
    marker = params / "download_complexes_multimer_v3_finished.txt"
    weights = sorted(params.glob("params_model_*_multimer_v3.npz"))
    if not marker.is_file() or len(weights) != 5:
        raise ValueError("AF2-Multimer v3 marker and exactly five parameter files are required")
    digest = hashlib.sha256()
    rows: List[Dict[str, Any]] = []
    for path in weights:
        file_sha256 = _sha256_file(path)
        digest.update(path.name.encode("utf-8"))
        digest.update(file_sha256.encode("ascii"))
        rows.append({
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256,
        })
    return rows, digest.hexdigest()


def observe_af2(runtime_path: Path, data_dir: Path, colabfold_version: str) -> Dict[str, Any]:
    if colabfold_version != "1.6.1":
        raise ValueError(f"ColabFold 1.6.1 is required; observed {colabfold_version}")
    if not runtime_path.is_file() or runtime_path.stat().st_size <= 0:
        raise ValueError("the locked ColabFold container is missing or empty")
    weights, weights_digest = _af2_weights(data_dir)
    return {
        "predictor_id": "af2_multimer_colabfold_v1",
        "runtime_family": "colabfold_af2_multimer",
        "colabfold_version": colabfold_version,
        "model_type": "alphafold2_multimer_v3",
        "container_image_uri": "docker://ghcr.io/sokrypton/colabfold:1.6.1-cuda12",
        "container_sha256": _sha256_file(runtime_path),
        "weights_manifest_sha256": weights_digest,
        "weights": weights,
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
        "weights_verified_from_runtime_receipt": "m6d_w3_mechanism_runtime_receipt",
    }


def verify_observation(
    identity: Dict[str, Any],
    predictor_id: str,
    protocol_path: str,
    runtime_lock_path: str,
) -> None:
    with open(runtime_lock_path) as handle:
        lock = json.load(handle)
    failures = validate_runtime_lock(lock, protocol_path)
    if failures:
        raise ValueError(f"W3b runtime lock is invalid: {failures[0]['kind']}")
    expected = runtime_identity(lock, predictor_id, protocol_path)
    if identity != expected:
        raise ValueError(f"observed runtime differs from frozen {predictor_id} identity")


def _write_json(path: str, value: Dict[str, Any]) -> None:
    destination = Path(path)
    if destination.exists():
        raise ValueError(f"refusing to overwrite runtime observation: {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    subparsers = parser.add_subparsers(dest="predictor", required=True)
    boltz = subparsers.add_parser("boltz2_complex")
    boltz.add_argument("--cache-dir", default=os.path.expanduser("~/.boltz"), type=Path)
    boltz.add_argument("--distribution", default="boltz")
    boltz.add_argument("--boltz-bin", required=True, type=Path)
    boltz.add_argument("--out", required=True)
    af2 = subparsers.add_parser("af2_multimer_colabfold_v1")
    af2.add_argument("--runtime-path", required=True, type=Path)
    af2.add_argument("--data-dir", required=True, type=Path)
    af2.add_argument("--colabfold-version", required=True)
    af2.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.predictor == "boltz2_complex":
        expected_binary = Path(sys.executable).parent / "boltz"
        if not args.boltz_bin.is_file() or args.boltz_bin.resolve() != expected_binary.resolve():
            raise ValueError("Boltz executable and observed Python environment differ")
        identity = observe_boltz(args.cache_dir, args.distribution)
    else:
        identity = observe_af2(args.runtime_path, args.data_dir, args.colabfold_version)
    verify_observation(identity, args.predictor, args.protocol, args.runtime_lock)
    _write_json(args.out, identity)
    print(f"predictor={args.predictor} runtime_identity_match=True prediction_executed=False")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
