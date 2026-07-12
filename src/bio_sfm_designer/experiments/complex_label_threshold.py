"""Shared L-RMSD label-threshold audit for complex/binder analyses."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional


def _as_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def label_threshold_audit(rows: Iterable[dict], *, threshold: float,
                          tolerance: float = 1e-9) -> Dict[str, Any]:
    values = set()
    mismatches = []
    n_records = 0
    for index, rec in enumerate(rows, 1):
        n_records = index
        observed = _as_float(rec.get("lrmsd_threshold"))
        if observed is not None:
            values.add(observed)
        if observed is None or abs(observed - threshold) > tolerance:
            mismatches.append({
                "line": index,
                "target_id": rec.get("target_id"),
                "lrmsd_threshold": rec.get("lrmsd_threshold"),
                "expected_threshold": threshold,
            })
    return {
        "ok": not mismatches,
        "expected_threshold": threshold,
        "tolerance": tolerance,
        "record_thresholds": sorted(values),
        "n_records": n_records,
        "n_mismatches": len(mismatches),
        "examples": mismatches[:5],
    }


def require_label_threshold(rows: Iterable[dict], *, threshold: float,
                            tolerance: float = 1e-9) -> Dict[str, Any]:
    audit = label_threshold_audit(rows, threshold=threshold, tolerance=tolerance)
    if not audit["ok"]:
        raise ValueError(
            "record lrmsd_threshold metadata must match analysis threshold "
            f"{threshold}: {audit['n_mismatches']} mismatch(es)"
        )
    return audit
