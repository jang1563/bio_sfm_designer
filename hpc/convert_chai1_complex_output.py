#!/usr/bin/env python3
"""Convert one Chai-1 complex smoke output into the strict complex record schema."""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import shlex
from pathlib import Path
from typing import Any, Iterable

import numpy as np

_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}


def _as_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ca_coords_from_pdb(path: str | Path, chain: str | None = None) -> list[tuple[float, float, float]]:
    coords: list[tuple[float, float, float]] = []
    seen = set()
    target_chain = chain
    with open(path) as handle:
        for line in handle:
            if line.startswith("ENDMDL"):
                break
            rec = line[:6].strip()
            if rec not in ("ATOM", "HETATM") or line[12:16].strip() != "CA":
                continue
            if rec == "HETATM" and line[17:20].strip() not in _MODIFIED_AA:
                continue
            if line[16] not in (" ", "A"):
                continue
            ch = line[21]
            if target_chain is None:
                target_chain = ch
            if ch != target_chain:
                continue
            reskey = (ch, line[22:27])
            if reskey in seen:
                continue
            seen.add(reskey)
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coords


def _atom_site_loop(path: str | Path) -> tuple[list[str], list[list[str]]]:
    fields: list[str] = []
    rows: list[list[str]] = []
    in_loop = False
    in_atom_site = False
    with open(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line == "loop_":
                in_loop = True
                in_atom_site = False
                fields = []
                continue
            if in_loop and line.startswith("_atom_site."):
                in_atom_site = True
                fields.append(line.split(".", 1)[1])
                continue
            if in_atom_site:
                if line == "#" or line.startswith("_"):
                    break
                rows.append(shlex.split(line))
    if not fields or not rows:
        raise ValueError(f"no _atom_site loop found in {path}")
    return fields, rows


def ca_coords_from_cif(path: str | Path, chain: str) -> list[tuple[float, float, float]]:
    fields, rows = _atom_site_loop(path)
    index = {field: i for i, field in enumerate(fields)}
    required = ("label_atom_id", "label_asym_id", "Cartn_x", "Cartn_y", "Cartn_z")
    missing = [field for field in required if field not in index]
    if missing:
        raise ValueError(f"{path} missing atom_site fields: {missing}")
    model_idx = index.get("pdbx_PDB_model_num")
    coords: list[tuple[float, float, float]] = []
    seen = set()
    for row in rows:
        if len(row) < len(fields):
            continue
        if model_idx is not None and row[model_idx] not in ("1", "1.0", "."):
            continue
        if row[index["label_atom_id"]] != "CA":
            continue
        if row[index["label_asym_id"]] != chain:
            continue
        seq = row[index.get("label_seq_id", index["Cartn_x"])]
        if seq in seen:
            continue
        seen.add(seq)
        coords.append((
            float(row[index["Cartn_x"]]),
            float(row[index["Cartn_y"]]),
            float(row[index["Cartn_z"]]),
        ))
    return coords


def _kabsch_transform(
    moving: Iterable[tuple[float, float, float]],
    reference: Iterable[tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    p = np.asarray(list(moving), dtype=float)
    q = np.asarray(list(reference), dtype=float)
    pm, qm = p.mean(0), q.mean(0)
    h = (p - pm).T @ (q - qm)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return r, pm, qm


def lrmsd(
    fold_target: list[tuple[float, float, float]],
    fold_binder: list[tuple[float, float, float]],
    ref_target: list[tuple[float, float, float]],
    ref_binder: list[tuple[float, float, float]],
) -> float:
    r, pm, qm = _kabsch_transform(fold_target, ref_target)
    moved_binder = (np.asarray(fold_binder, float) - pm) @ r.T + qm
    ref_binder_arr = np.asarray(ref_binder, float)
    return float(np.sqrt(((moved_binder - ref_binder_arr) ** 2).sum() / len(ref_binder_arr)))


def interface_pae(pae: np.ndarray, n_target: int) -> float:
    if pae.ndim != 2 or pae.shape[0] <= n_target or pae.shape[0] != pae.shape[1]:
        raise ValueError(f"bad pAE shape {pae.shape}; expected square target+binder matrix")
    return float((pae[:n_target, n_target:].mean() + pae[n_target:, :n_target].mean()) / 2.0)


def _scalar_npz(path: Path, key: str) -> float | None:
    if not path.exists():
        return None
    arr = np.load(path)[key]
    return _as_float(np.ravel(arr)[0])


def _best_model_index(chai_out: Path) -> int:
    best_idx = None
    best_score = None
    for path in sorted(chai_out.glob("scores.model_idx_*.npz")):
        idx = int(path.stem.split("_")[-1])
        score = _scalar_npz(path, "aggregate_score")
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_idx = idx
            best_score = score
    if best_idx is None:
        raise ValueError(f"no scores.model_idx_*.npz with aggregate_score found in {chai_out}")
    return best_idx


def _load_manifest(path: Path) -> dict[str, Any]:
    with open(path) as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest is not a JSON object: {path}")
    return manifest


def build_record(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_manifest(args.manifest)
    model_idx = _best_model_index(args.chai_out) if args.model_index == "best" else int(args.model_index)
    cif_path = args.chai_out / f"pred.model_idx_{model_idx}.cif"
    scores_path = args.chai_out / f"scores.model_idx_{model_idx}.npz"
    pae_path = args.chai_out / f"pae.model_idx_{model_idx}.npz"
    plddt_path = args.chai_out / f"plddt.model_idx_{model_idx}.npz"
    if not cif_path.exists():
        raise FileNotFoundError(cif_path)
    if not pae_path.exists():
        raise FileNotFoundError(f"missing Chai pAE file; rerun API wrapper: {pae_path}")

    target_chain = args.target_chain or manifest.get("target_chain") or "A"
    binder_chain = args.binder_chain or manifest.get("binder_chain") or "B"
    fold_target_chain = args.fold_target_chain
    fold_binder_chain = args.fold_binder_chain

    ref_target = _ca_coords_from_pdb(args.backbone, target_chain)
    ref_binder = _ca_coords_from_pdb(args.backbone, binder_chain)
    fold_target = ca_coords_from_cif(cif_path, fold_target_chain)
    fold_binder = ca_coords_from_cif(cif_path, fold_binder_chain)
    aligned = (
        len(ref_target) > 0
        and len(ref_binder) > 0
        and len(fold_target) == len(ref_target)
        and len(fold_binder) == len(ref_binder)
    )
    observed_lrmsd = lrmsd(fold_target, fold_binder, ref_target, ref_binder) if aligned else float("nan")
    success = bool(aligned and math.isfinite(observed_lrmsd) and observed_lrmsd < args.threshold)
    quality = round(max(0.0, 1.0 - observed_lrmsd / 10.0), 4) if math.isfinite(observed_lrmsd) else 0.0

    pae = np.load(pae_path)["pae"]
    n_target = int(manifest["target_sequence_length"])
    plddt = np.load(plddt_path)["plddt"] if plddt_path.exists() else None
    mean_plddt = float(np.nanmean(plddt) * 100.0) if plddt is not None else None

    rec = {
        "target_id": manifest["candidate_id"],
        "complex_target_id": manifest["complex_target_id"],
        "mean_plddt": round(mean_plddt, 3) if mean_plddt is not None else None,
        "regime": "complex",
        "predictor_id": manifest.get("predictor_id", "chai1_complex"),
        "signal_source": manifest.get("signal_source", "chai1_pae_interaction"),
        "label_source": manifest.get("label_source", "chai1_lrmsd_to_reference"),
        "iptm": round(_scalar_npz(scores_path, "iptm") or 0.0, 4),
        "ptm": round(_scalar_npz(scores_path, "ptm") or 0.0, 4),
        "aggregate_score": round(_scalar_npz(scores_path, "aggregate_score") or 0.0, 4),
        "pae_interaction": round(interface_pae(pae, n_target), 4),
        "truth": {"correct": success, "quality": quality},
        "lrmsd": round(observed_lrmsd, 4) if math.isfinite(observed_lrmsd) else None,
        "lrmsd_threshold": args.threshold,
        "interface_aligned": aligned,
        "target_chain": target_chain,
        "binder_chain": binder_chain,
        "fold_target_chain": fold_target_chain,
        "fold_binder_chain": fold_binder_chain,
        "refolder": "chai1_complex",
        "model_index": model_idx,
        "model_cif": os.fspath(cif_path),
        "scores_npz": os.fspath(scores_path),
        "pae_npz": os.fspath(pae_path),
    }
    return rec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert one Chai-1 complex output to a strict record")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--chai-out", required=True, type=Path)
    parser.add_argument("--backbone", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=4.0)
    parser.add_argument("--model-index", default="best")
    parser.add_argument("--target-chain", default=None)
    parser.add_argument("--binder-chain", default=None)
    parser.add_argument("--fold-target-chain", default="A")
    parser.add_argument("--fold-binder-chain", default="B")
    args = parser.parse_args(argv)

    rec = build_record(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as handle:
        handle.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"wrote 1 Chai complex record to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
