#!/usr/bin/env python3
"""Run Chai-1 through its Python API and persist metrics the CLI omits.

The `chai-lab fold` CLI writes CIFs and scalar ranking scores, but Chai's
`run_inference` return value also carries pAE/PDE/pLDDT tensors. W3 needs the
actual pAE matrix, not an ipTM proxy, so this wrapper saves those tensors next
to the ordinary Chai outputs.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def save_candidate_metric_arrays(candidates: Any, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    arrays = {
        "pae": _to_numpy(candidates.pae),
        "pde": _to_numpy(candidates.pde),
        "plddt": _to_numpy(candidates.plddt),
    }
    n_models = int(arrays["pae"].shape[0])
    saved: dict[str, Any] = {"n_models": n_models, "metrics": {}}
    for metric, arr in arrays.items():
        paths = []
        for model_idx in range(n_models):
            path = output_dir / f"{metric}.model_idx_{model_idx}.npz"
            np.savez(path, **{metric: arr[model_idx]})
            paths.append(str(path))
        saved["metrics"][metric] = {
            "shape": list(arr.shape),
            "paths": paths,
        }
    summary_path = output_dir / "chai_api_metrics_summary.json"
    with open(summary_path, "w") as handle:
        json.dump(saved, handle, indent=2, sort_keys=True)
        handle.write("\n")
    saved["summary_path"] = str(summary_path)
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Chai-1 API and save pAE/PDE/pLDDT arrays")
    parser.add_argument("--fasta", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--use-msa-server", action="store_true")
    parser.add_argument("--use-templates-server", action="store_true")
    parser.add_argument("--msa-directory", type=Path, default=None)
    parser.add_argument("--template-hits-path", type=Path, default=None)
    parser.add_argument("--num-trunk-recycles", type=int, default=3)
    parser.add_argument("--num-diffn-timesteps", type=int, default=200)
    parser.add_argument("--num-diffn-samples", type=int, default=5)
    parser.add_argument("--num-trunk-samples", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--device", default=None)
    args = parser.parse_args(argv)

    if args.out_dir.exists() and args.overwrite:
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    from chai_lab.chai1 import run_inference

    candidates = run_inference(
        args.fasta,
        output_dir=args.out_dir,
        use_msa_server=args.use_msa_server,
        use_templates_server=args.use_templates_server,
        msa_directory=args.msa_directory,
        template_hits_path=args.template_hits_path,
        num_trunk_recycles=args.num_trunk_recycles,
        num_diffn_timesteps=args.num_diffn_timesteps,
        num_diffn_samples=args.num_diffn_samples,
        num_trunk_samples=args.num_trunk_samples,
        seed=args.seed,
        device=args.device,
    )
    summary = save_candidate_metric_arrays(candidates, args.out_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
