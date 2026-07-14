#!/usr/bin/env python3
"""Hash a pre-staged ColabFold runtime and AF2-Multimer weights without prediction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Sequence


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_receipt(*, runtime_mode: str, runtime_path: Path, data_dir: Path,
                  colabfold_version: str) -> dict:
    if runtime_mode not in ("existing_colabfold_binary", "apptainer_colabfold_image"):
        raise ValueError(f"unsupported runtime mode: {runtime_mode}")
    if colabfold_version != "1.6.1":
        raise ValueError(f"ColabFold 1.6.1 is required; observed {colabfold_version}")
    if not runtime_path.is_file():
        raise FileNotFoundError(runtime_path)
    params = data_dir / "params"
    marker = params / "download_complexes_multimer_v3_finished.txt"
    weights = sorted(params.glob("params_model_*_multimer_v3.npz"))
    if not marker.is_file() or len(weights) != 5:
        raise ValueError(
            "local AF2-Multimer v3 success marker and exactly five model files are required"
        )
    weights_digest = hashlib.sha256()
    weight_rows = []
    for path in weights:
        digest = _sha256_file(path)
        weights_digest.update(path.name.encode("utf-8"))
        weights_digest.update(digest.encode("ascii"))
        weight_rows.append({"name": path.name, "sha256": digest, "size_bytes": path.stat().st_size})
    return {
        "artifact": "m6d_w3_mechanism_runtime_receipt",
        "status": "w3_mechanism_runtime_ready_no_prediction",
        "runtime_mode": runtime_mode,
        "runtime_path": os.path.abspath(runtime_path),
        "runtime_sha256": _sha256_file(runtime_path),
        "colabfold_version": colabfold_version,
        "model_type": "alphafold2_multimer_v3",
        "data_dir": os.path.abspath(data_dir),
        "weights_success_marker": os.path.abspath(marker),
        "weights_manifest_sha256": weights_digest.hexdigest(),
        "weights": weight_rows,
        "prediction_executed": False,
        "submitted_jobs": 0,
        "network_fetch_executed": False,
        "claim_boundary": "runtime and local-weight identity only; no prediction or scheduler action",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the no-prediction W3 runtime receipt")
    parser.add_argument("--runtime-mode", required=True)
    parser.add_argument("--runtime-path", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--colabfold-version", required=True)
    parser.add_argument("--out", default="results/m6d_w3_mechanism_runtime_receipt.json", type=Path)
    args = parser.parse_args(argv)
    receipt = build_receipt(
        runtime_mode=args.runtime_mode,
        runtime_path=args.runtime_path,
        data_dir=args.data_dir,
        colabfold_version=args.colabfold_version,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"wrote no-prediction W3 runtime receipt to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
