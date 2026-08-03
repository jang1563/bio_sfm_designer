"""Append-only scheduler submission journal for the W3d 24-cell panel."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as diagnostic
from bio_sfm_designer.experiments.m6d_w3d_input_runtime import sha256_file


_JOB_ID = re.compile(r"^[0-9]+(?:_[0-9]+)?$")


def _load_object(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain an object")
            rows.append(value)
    return rows


def _execution_map(packet: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    cells = packet.get("execution_cells")
    if not isinstance(cells, list):
        raise ValueError("W3d approval packet execution cells are missing")
    mapped = {
        str(row.get("cell_id")): dict(row)
        for row in cells
        if isinstance(row, dict) and isinstance(row.get("cell_id"), str)
    }
    if len(cells) != 24 or len(mapped) != 24:
        raise ValueError("W3d approval packet must contain 24 unique cells")
    return mapped


def _validate_packet(packet_path: str, packet: Mapping[str, Any]) -> None:
    from bio_sfm_designer.experiments.m6d_w3d_approval import (
        verify_packet_integrity,
    )

    if verify_packet_integrity(packet_path):
        raise ValueError("W3d approval packet integrity validation failed")
    contract = packet.get("approval_contract")
    if not (
        packet.get("artifact") == "m6d_w3d_prediction_approval_packet"
        and packet.get("version") == 1
        and packet.get("status")
        == "w3d_prediction_approval_packet_ready_no_submit"
        and packet.get("audit_ok") is True
        and packet.get("approval_recorded") is False
        and packet.get("no_submit") is True
        and packet.get("submitted_jobs") == 0
        and isinstance(contract, dict)
        and contract.get("target_ids") == diagnostic.TARGET_IDS
        and contract.get("predictor_ids") == diagnostic.PREDICTOR_IDS
        and contract.get("representation_ids") == diagnostic.REPRESENTATION_IDS
        and contract.get("maximum_predictor_evaluations") == 24
        and contract.get("maximum_h100_gpu_hours") == 24.0
    ):
        raise ValueError("W3d approval packet scope is invalid")
    _execution_map(packet)


def append(
    packet_path: str,
    receipt_path: str,
    cell_id: str,
    job_id: str,
) -> Dict[str, Any]:
    packet = _load_object(packet_path)
    _validate_packet(packet_path, packet)
    cells = _execution_map(packet)
    if cell_id not in cells:
        raise ValueError(f"W3d receipt cell is outside the frozen scope: {cell_id}")
    if _JOB_ID.fullmatch(job_id) is None:
        raise ValueError(f"invalid Slurm job id: {job_id!r}")
    rows = _load_rows(receipt_path)
    observed = {str(row.get("cell_id")) for row in rows}
    if cell_id in observed:
        raise ValueError(f"duplicate W3d submission receipt: {cell_id}")
    if len(rows) >= 24:
        raise ValueError("W3d submission receipt already reached its cap")
    cell = cells[cell_id]
    row = {
        "artifact": "m6d_w3d_submission_receipt_row",
        "version": 1,
        "status": "scheduler_job_submitted",
        "cell_id": cell_id,
        "target_id": cell["target_id"],
        "representation_id": cell["representation_id"],
        "predictor_id": cell["predictor_id"],
        "job_id": job_id,
        "approval_packet": packet_path,
        "approval_packet_sha256": sha256_file(packet_path),
        "retry": False,
        "adaptive_top_up": False,
        "scientific_claim_authorized": False,
    }
    destination = Path(receipt_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        os.write(
            descriptor,
            (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"),
        )
    finally:
        os.close(descriptor)
    return row


def summarize(packet_path: str, receipt_path: str) -> Dict[str, Any]:
    packet = _load_object(packet_path)
    _validate_packet(packet_path, packet)
    cells = _execution_map(packet)
    rows = _load_rows(receipt_path)
    expected_ids = set(cells)
    observed_ids = [str(row.get("cell_id")) for row in rows]
    packet_sha256 = sha256_file(packet_path)
    row_contract_ok = all(
        row.get("artifact") == "m6d_w3d_submission_receipt_row"
        and row.get("version") == 1
        and row.get("status") == "scheduler_job_submitted"
        and row.get("cell_id") in cells
        and row.get("target_id") == cells[row["cell_id"]]["target_id"]
        and row.get("representation_id")
        == cells[row["cell_id"]]["representation_id"]
        and row.get("predictor_id") == cells[row["cell_id"]]["predictor_id"]
        and row.get("approval_packet") == packet_path
        and row.get("approval_packet_sha256") == packet_sha256
        and row.get("retry") is False
        and row.get("adaptive_top_up") is False
        and row.get("scientific_claim_authorized") is False
        and _JOB_ID.fullmatch(str(row.get("job_id") or "")) is not None
        for row in rows
    )
    complete = (
        len(rows) == 24
        and len(set(observed_ids)) == 24
        and set(observed_ids) == expected_ids
        and row_contract_ok
    )
    predictor_counts = {
        predictor_id: sum(
            row.get("predictor_id") == predictor_id for row in rows
        )
        for predictor_id in diagnostic.PREDICTOR_IDS
    }
    return {
        "artifact": "m6d_w3d_submission_receipt_summary",
        "version": 1,
        "status": (
            "w3d_all_twenty_four_prediction_jobs_submitted"
            if complete
            else "w3d_submission_receipt_incomplete_or_invalid"
        ),
        "audit_ok": complete,
        "submission_complete": complete,
        "jobs_expected": 24,
        "jobs_recorded": len(rows),
        "target_ids": diagnostic.TARGET_IDS,
        "predictor_ids": diagnostic.PREDICTOR_IDS,
        "representation_ids": diagnostic.REPRESENTATION_IDS,
        "predictor_job_counts": predictor_counts,
        "approval_packet_sha256": packet_sha256,
        "receipt_sha256": sha256_file(receipt_path) if rows else None,
        "retry_jobs": 0,
        "adaptive_top_up_jobs": 0,
        "can_claim_native_recoverability": False,
        "claim_boundary": (
            "Scheduler submission evidence only. Scientific adjudication requires "
            "all 24 strict-QC records and the frozen complete-case W3d rules."
        ),
    }


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--packet", required=True)
    append_parser.add_argument("--receipt", required=True)
    append_parser.add_argument("--cell-id", required=True)
    append_parser.add_argument("--job-id", required=True)
    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--packet", required=True)
    summary_parser.add_argument("--receipt", required=True)
    summary_parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "append":
        row = append(args.packet, args.receipt, args.cell_id, args.job_id)
        print(
            f"cell={row['cell_id']} predictor={row['predictor_id']} "
            f"job_id={row['job_id']}"
        )
        return 0
    report = summarize(args.packet, args.receipt)
    _write_json(args.out, report)
    print(f"status={report['status']} jobs={report['jobs_recorded']}/24")
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
