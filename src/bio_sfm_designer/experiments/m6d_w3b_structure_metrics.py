"""Shared strict structure metrics for the two W3b predictor producers."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

import numpy as np


_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}
Coordinate = Tuple[float, float, float]


def ca_coords(path: str, chain: str) -> List[Coordinate]:
    coordinates: List[Coordinate] = []
    seen = set()
    with open(path) as handle:
        for line in handle:
            if line.startswith("ENDMDL"):
                break
            record = line[:6].strip()
            if record not in ("ATOM", "HETATM") or line[12:16].strip() != "CA":
                continue
            if record == "HETATM" and line[17:20].strip() not in _MODIFIED_AA:
                continue
            if line[16] not in (" ", "A") or line[21] != chain:
                continue
            residue = (line[21], line[22:27])
            if residue in seen:
                continue
            seen.add(residue)
            coordinates.append((
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            ))
    return coordinates


def _kabsch_transform(
    moving: Iterable[Coordinate],
    reference: Iterable[Coordinate],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    moving_array = np.asarray(list(moving), dtype=float)
    reference_array = np.asarray(list(reference), dtype=float)
    if moving_array.shape != reference_array.shape or moving_array.ndim != 2 or moving_array.shape[1] != 3:
        raise ValueError("Kabsch inputs must be nonempty, equal-length Nx3 coordinate arrays")
    if moving_array.shape[0] == 0:
        raise ValueError("Kabsch inputs must not be empty")
    moving_mean = moving_array.mean(0)
    reference_mean = reference_array.mean(0)
    covariance = (moving_array - moving_mean).T @ (reference_array - reference_mean)
    u, _, vt = np.linalg.svd(covariance)
    sign = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag([1.0, 1.0, sign]) @ u.T
    return rotation, moving_mean, reference_mean


def lrmsd(
    fold_target: Sequence[Coordinate],
    fold_binder: Sequence[Coordinate],
    reference_target: Sequence[Coordinate],
    reference_binder: Sequence[Coordinate],
) -> float:
    if len(fold_binder) != len(reference_binder) or not fold_binder:
        raise ValueError("folded and reference binder CA arrays must have equal nonzero length")
    rotation, moving_mean, reference_mean = _kabsch_transform(fold_target, reference_target)
    moved = (np.asarray(fold_binder, dtype=float) - moving_mean) @ rotation.T + reference_mean
    reference = np.asarray(reference_binder, dtype=float)
    value = float(np.sqrt(((moved - reference) ** 2).sum() / len(reference)))
    if not np.isfinite(value):
        raise ValueError("target-aligned L-RMSD is not finite")
    return value


def interface_pae(pae: np.ndarray, target_length: int) -> float:
    matrix = np.asarray(pae, dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[0] != matrix.shape[1]
        or not 0 < target_length < matrix.shape[0]
        or not np.isfinite(matrix).all()
    ):
        raise ValueError(f"invalid pAE matrix shape/content for target length {target_length}")
    value = float(
        (
            matrix[:target_length, target_length:].mean()
            + matrix[target_length:, :target_length].mean()
        )
        / 2.0
    )
    if not np.isfinite(value) or value < 0.0:
        raise ValueError("interface pAE is not a finite nonnegative value")
    return value
