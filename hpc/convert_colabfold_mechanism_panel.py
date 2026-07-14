#!/usr/bin/env python3
"""Convert ColabFold W3 mechanism-panel outputs to strict complex records."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}
_PACKET_STATUS = "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            rows.append(value)
    return rows


def validate_conversion_inputs(
    packet: Mapping[str, Any], manifest_path: Path, private_rows: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Revalidate the preregistered packet before interpreting predictor output."""
    failures: List[Dict[str, Any]] = []
    execution = packet.get("execution_packet")
    if packet.get("status") != _PACKET_STATUS or packet.get("audit_ok") is not True:
        failures.append({"kind": "packet_not_preregistered_and_audited"})
    if not isinstance(execution, dict):
        failures.append({"kind": "execution_packet_missing"})
        execution = {}
    observed_manifest_sha = _sha256_file(manifest_path)
    if observed_manifest_sha != execution.get("private_manifest_sha256"):
        failures.append({
            "kind": "private_manifest_sha_mismatch",
            "expected": execution.get("private_manifest_sha256"),
            "observed": observed_manifest_sha,
        })

    public_rows = packet.get("rows")
    if not isinstance(public_rows, list):
        failures.append({"kind": "public_rows_missing"})
        public_rows = []
    public_by_id = {
        str(row.get("case_id")): row for row in public_rows if isinstance(row, dict)
    }
    private_by_id = {
        str(row.get("case_id")): row for row in private_rows if isinstance(row, Mapping)
    }
    if (
        len(public_rows) != 58
        or len(public_by_id) != 58
        or len(private_rows) != 58
        or len(private_by_id) != 58
    ):
        failures.append({
            "kind": "conversion_case_count_or_identity_invalid",
            "public_rows": len(public_rows),
            "public_ids": len(public_by_id),
            "private_rows": len(private_rows),
            "private_ids": len(private_by_id),
        })
    if set(public_by_id) != set(private_by_id):
        failures.append({"kind": "public_private_case_identity_mismatch"})
    for case_id, public in public_by_id.items():
        private = private_by_id.get(case_id)
        if private is None:
            continue
        mismatches = [
            key for key, expected in public.items() if private.get(key) != expected
        ]
        if mismatches:
            failures.append({
                "kind": "public_private_case_metadata_mismatch",
                "case_id": case_id,
                "fields": mismatches,
            })
    return failures


def _ca_coords(path: Path, chain: str) -> List[Tuple[float, float, float]]:
    coords: List[Tuple[float, float, float]] = []
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
            key = (line[21], line[22:27])
            if key in seen:
                continue
            seen.add(key)
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coords


def _kabsch_transform(moving: Iterable[Tuple[float, float, float]],
                      reference: Iterable[Tuple[float, float, float]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    p = np.asarray(list(moving), dtype=float)
    q = np.asarray(list(reference), dtype=float)
    moving_mean, reference_mean = p.mean(0), q.mean(0)
    covariance = (p - moving_mean).T @ (q - reference_mean)
    u, _, vt = np.linalg.svd(covariance)
    sign = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag([1.0, 1.0, sign]) @ u.T
    return rotation, moving_mean, reference_mean


def lrmsd(fold_target: Sequence[Tuple[float, float, float]],
          fold_binder: Sequence[Tuple[float, float, float]],
          ref_target: Sequence[Tuple[float, float, float]],
          ref_binder: Sequence[Tuple[float, float, float]]) -> float:
    rotation, moving_mean, reference_mean = _kabsch_transform(fold_target, ref_target)
    moved = (np.asarray(fold_binder, dtype=float) - moving_mean) @ rotation.T + reference_mean
    reference = np.asarray(ref_binder, dtype=float)
    return float(np.sqrt(((moved - reference) ** 2).sum() / len(reference)))


def interface_pae(pae: np.ndarray, n_target: int) -> float:
    if pae.ndim != 2 or pae.shape[0] != pae.shape[1] or not 0 < n_target < pae.shape[0]:
        raise ValueError(f"invalid pAE matrix shape {pae.shape} for target length {n_target}")
    return float((pae[:n_target, n_target:].mean() + pae[n_target:, :n_target].mean()) / 2.0)


def _ranked_files(output_dir: Path, case_id: str) -> Tuple[Path, Path, str]:
    pdbs = sorted(output_dir.glob(f"{case_id}_unrelaxed_rank_001_*.pdb"))
    scores = sorted(output_dir.glob(f"{case_id}_scores_rank_001_*.json"))
    if len(pdbs) != 1 or len(scores) != 1:
        raise ValueError(
            f"{case_id}: expected one rank-001 PDB and score JSON; "
            f"observed pdb={len(pdbs)} scores={len(scores)}"
        )
    pdb_tag = pdbs[0].name.replace(f"{case_id}_unrelaxed_", "").replace(".pdb", "")
    score_tag = scores[0].name.replace(f"{case_id}_scores_", "").replace(".json", "")
    if pdb_tag != score_tag:
        raise ValueError(f"{case_id}: rank-001 PDB and score tags differ")
    return pdbs[0], scores[0], pdb_tag


def build_record(case: Mapping[str, Any], output_dir: Path,
                 threshold: float = 4.0) -> Dict[str, Any]:
    case_id = str(case["case_id"])
    pdb_path, scores_path, model_tag = _ranked_files(output_dir, case_id)
    with open(scores_path) as handle:
        scores = json.load(handle)
    if not isinstance(scores, dict):
        raise ValueError(f"{case_id}: score JSON must contain an object")
    pae = np.asarray(scores["pae"], dtype=float)
    plddt = np.asarray(scores["plddt"], dtype=float)
    reference_path = Path(str(case["reference_backbone_path"]))
    if _sha256_file(reference_path) != case["reference_backbone_sha256"]:
        raise ValueError(f"{case_id}: reference backbone SHA256 mismatch")
    a3m_path = Path(str(case["a3m_path"]))
    if _sha256_file(a3m_path) != case["a3m_sha256"]:
        raise ValueError(f"{case_id}: A3M SHA256 mismatch")

    ref_target = _ca_coords(reference_path, str(case["target_chain"]))
    ref_binder = _ca_coords(reference_path, str(case["binder_chain"]))
    fold_target = _ca_coords(pdb_path, "A")
    fold_binder = _ca_coords(pdb_path, "B")
    target_length = len(str(case["target_sequence"]))
    binder_length = len(str(case["binder_sequence"]))
    expected_size = target_length + binder_length
    if pae.shape != (expected_size, expected_size) or plddt.size != expected_size:
        raise ValueError(
            f"{case_id}: score dimensions differ from locked target+binder length {expected_size}"
        )
    if not np.isfinite(pae).all() or not np.isfinite(plddt).all():
        raise ValueError(f"{case_id}: score arrays contain non-finite values")
    observed_lengths = {
        "reference_target": len(ref_target),
        "fold_target": len(fold_target),
        "locked_target": target_length,
        "reference_binder": len(ref_binder),
        "fold_binder": len(fold_binder),
        "locked_binder": binder_length,
    }
    aligned = (
        len(ref_target) == len(fold_target) == target_length
        and len(ref_binder) == len(fold_binder) == binder_length
        and target_length > 0
        and binder_length > 0
    )
    if not aligned:
        raise ValueError(f"{case_id}: target/binder CA lengths do not match locks: {observed_lengths}")
    observed_lrmsd = lrmsd(fold_target, fold_binder, ref_target, ref_binder)
    if not math.isfinite(observed_lrmsd):
        raise ValueError(f"{case_id}: target-aligned LRMSD is not finite")
    iptm = float(scores["iptm"])
    ptm = float(scores["ptm"])
    if not math.isfinite(iptm) or not math.isfinite(ptm):
        raise ValueError(f"{case_id}: ipTM or pTM is not finite")
    success = observed_lrmsd < threshold
    quality = max(0.0, 1.0 - observed_lrmsd / 10.0)
    return {
        "case_id": case_id,
        "target_id": str(case["source_target_id"]),
        "complex_target_id": str(case["complex_target_id"]),
        "mean_plddt": round(float(np.mean(plddt)), 3),
        "regime": "complex",
        "predictor_id": "af2_multimer_colabfold_v1",
        "signal_source": "af2_multimer_pae_interaction",
        "label_source": "af2_multimer_lrmsd_to_reference",
        "iptm": round(iptm, 4),
        "ptm": round(ptm, 4),
        "pae_interaction": round(interface_pae(pae, target_length), 4),
        "truth": {"correct": success, "quality": round(quality, 4)},
        "lrmsd": observed_lrmsd,
        "lrmsd_threshold": threshold,
        "interface_aligned": aligned,
        "target_chain": str(case["target_chain"]),
        "binder_chain": str(case["binder_chain"]),
        "fold_target_chain": "A",
        "fold_binder_chain": "B",
        "refolder": "af2_multimer_colabfold_v1",
        "model_tag": model_tag,
        "model_pdb": os.fspath(pdb_path),
        "scores_json": os.fspath(scores_path),
        "provenance": {
            "panel_block": case["panel_block"],
            "panel_role": case["panel_role"],
            "a3m_sha256": case["a3m_sha256"],
            "reference_backbone_sha256": case["reference_backbone_sha256"],
            "target_sequence_sha256": case["target_sequence_sha256"],
            "binder_sequence_sha256": case["binder_sequence_sha256"],
            "model_pdb_sha256": _sha256_file(pdb_path),
            "scores_json_sha256": _sha256_file(scores_path),
        },
    }


def convert_panel(private_rows: Sequence[Mapping[str, Any]], output_dir: Path,
                  threshold: float = 4.0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for case in private_rows:
        try:
            records.append(build_record(case, output_dir, threshold))
        except (KeyError, OSError, TypeError, ValueError) as exc:
            failures.append({"case_id": case.get("case_id"), "kind": "conversion_failed", "message": str(exc)})
    ids = [row["case_id"] for row in records]
    if len(ids) != len(set(ids)):
        failures.append({"kind": "duplicate_case_id"})
    if len(private_rows) != 58 or len(records) != 58:
        failures.append({
            "kind": "record_count_invalid",
            "expected": 58,
            "input_rows": len(private_rows),
            "converted_records": len(records),
        })
    report = {
        "artifact": "m6d_w3_mechanism_panel_colabfold_conversion",
        "status": "conversion_complete" if not failures else "conversion_blocked",
        "ok": not failures,
        "n_input_rows": len(private_rows),
        "n_records": len(records),
        "predictor_id": "af2_multimer_colabfold_v1",
        "lrmsd_threshold": threshold,
        "failures": failures,
    }
    return records, report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert the W3 ColabFold mechanism panel")
    parser.add_argument("--packet", default="configs/m6d_w3_mechanism_panel_protocol.json", type=Path)
    parser.add_argument("--private-manifest", default="results/m6d_w3_mechanism_panel_inputs.jsonl", type=Path)
    parser.add_argument("--output-dir", default="hpc_outputs/m6d_w3_mechanism_panel_af2", type=Path)
    parser.add_argument("--out-records", default="results/m6d_w3_mechanism_panel_af2_records.jsonl", type=Path)
    parser.add_argument("--out-report", default="results/m6d_w3_mechanism_panel_af2_conversion.json", type=Path)
    parser.add_argument("--threshold", default=4.0, type=float)
    args = parser.parse_args(argv)
    private_rows = _load_jsonl(args.private_manifest)
    input_failures = validate_conversion_inputs(
        _load_json(args.packet), args.private_manifest, private_rows
    )
    if input_failures:
        records = []
        report = {
            "artifact": "m6d_w3_mechanism_panel_colabfold_conversion",
            "status": "conversion_blocked",
            "ok": False,
            "n_input_rows": len(private_rows),
            "n_records": 0,
            "predictor_id": "af2_multimer_colabfold_v1",
            "lrmsd_threshold": args.threshold,
            "input_verification_ok": False,
            "failures": input_failures,
        }
    else:
        records, report = convert_panel(private_rows, args.output_dir, args.threshold)
        report["input_verification_ok"] = True
    report["packet"] = os.fspath(args.packet)
    report["private_manifest_sha256"] = _sha256_file(args.private_manifest)
    args.out_records.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_records, "w") as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_report, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
