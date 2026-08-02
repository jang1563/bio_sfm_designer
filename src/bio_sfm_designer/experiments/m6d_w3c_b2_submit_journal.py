"""Append-only submission journal for the W3c-B2 native screen."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    PREDICTOR_IDS,
    TARGET_IDS,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_producer import sha256_file


_JOB_ID = re.compile(r"^[0-9]+(?:_[0-9]+)?$")


def _load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain an object")
            rows.append(value)
    return rows


def _validate_packet(packet: Mapping[str, Any]) -> None:
    contract = packet.get("approval_contract")
    targets = packet.get("execution_targets")
    if not (
        packet.get("artifact")
        == "m6d_w3c_b2_native_prediction_approval_packet"
        and packet.get("version") == 1
        and packet.get("status")
        == "w3c_b2_native_prediction_approval_packet_ready_no_submit"
        and packet.get("audit_ok") is True
        and packet.get("approval_recorded") is False
        and packet.get("no_submit") is True
        and packet.get("submitted_jobs") == 0
        and isinstance(contract, dict)
        and contract.get("target_ids") == TARGET_IDS
        and contract.get("predictor_ids") == PREDICTOR_IDS
        and contract.get("maximum_predictor_evaluations") == 16
        and contract.get("maximum_h100_gpu_hours") == 16.0
        and isinstance(targets, list)
        and [row.get("target_id") for row in targets] == TARGET_IDS
    ):
        raise ValueError("W3c-B2 approval packet scope is invalid")


def append(
    packet_path: str,
    receipt_path: str,
    target_id: str,
    predictor_id: str,
    job_id: str,
) -> Dict[str, Any]:
    packet = _load_object(packet_path)
    _validate_packet(packet)
    if target_id not in TARGET_IDS or predictor_id not in PREDICTOR_IDS:
        raise ValueError("W3c-B2 receipt target/predictor scope is invalid")
    if _JOB_ID.fullmatch(job_id) is None:
        raise ValueError(f"invalid Slurm job id: {job_id!r}")
    rows = _load_rows(receipt_path)
    observed_pairs = {
        (str(row.get("target_id")), str(row.get("predictor_id")))
        for row in rows
    }
    pair = (target_id, predictor_id)
    if pair in observed_pairs:
        raise ValueError(f"duplicate W3c-B2 submission receipt: {pair}")
    if len(rows) >= 16:
        raise ValueError("W3c-B2 submission receipt already reached its cap")
    row = {
        "artifact": "m6d_w3c_b2_submission_receipt_row",
        "version": 1,
        "status": "scheduler_job_submitted",
        "target_id": target_id,
        "predictor_id": predictor_id,
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
    _validate_packet(packet)
    rows = _load_rows(receipt_path)
    expected_pairs = {
        (target_id, predictor_id)
        for target_id in TARGET_IDS
        for predictor_id in PREDICTOR_IDS
    }
    observed_pairs = [
        (str(row.get("target_id")), str(row.get("predictor_id")))
        for row in rows
    ]
    row_contract_ok = all(
        row.get("artifact") == "m6d_w3c_b2_submission_receipt_row"
        and row.get("version") == 1
        and row.get("status") == "scheduler_job_submitted"
        and row.get("approval_packet") == packet_path
        and row.get("approval_packet_sha256") == sha256_file(packet_path)
        and row.get("retry") is False
        and row.get("adaptive_top_up") is False
        and row.get("scientific_claim_authorized") is False
        and _JOB_ID.fullmatch(str(row.get("job_id") or "")) is not None
        for row in rows
    )
    complete = (
        len(rows) == 16
        and len(set(observed_pairs)) == 16
        and set(observed_pairs) == expected_pairs
        and row_contract_ok
    )
    return {
        "artifact": "m6d_w3c_b2_submission_receipt_summary",
        "version": 1,
        "status": (
            "w3c_b2_all_sixteen_prediction_jobs_submitted"
            if complete
            else "w3c_b2_submission_receipt_incomplete_or_invalid"
        ),
        "audit_ok": complete,
        "submission_complete": complete,
        "jobs_expected": 16,
        "jobs_recorded": len(rows),
        "target_ids": TARGET_IDS,
        "predictor_ids": PREDICTOR_IDS,
        "approval_packet_sha256": sha256_file(packet_path),
        "receipt_sha256": sha256_file(receipt_path) if rows else None,
        "retry_jobs": 0,
        "adaptive_top_up_jobs": 0,
        "can_claim_native_recoverability": False,
        "claim_boundary": (
            "Scheduler submission evidence only. Scientific adjudication requires "
            "all sixteen strict prediction records and the frozen 6/8 rule."
        ),
    }


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--packet", required=True)
    append_parser.add_argument("--receipt", required=True)
    append_parser.add_argument("--target-id", choices=TARGET_IDS, required=True)
    append_parser.add_argument(
        "--predictor-id", choices=PREDICTOR_IDS, required=True
    )
    append_parser.add_argument("--job-id", required=True)
    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--packet", required=True)
    summary_parser.add_argument("--receipt", required=True)
    summary_parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "append":
        row = append(
            args.packet,
            args.receipt,
            args.target_id,
            args.predictor_id,
            args.job_id,
        )
        print(
            f"target={row['target_id']} predictor={row['predictor_id']} "
            f"job_id={row['job_id']}"
        )
        return 0
    report = summarize(args.packet, args.receipt)
    _write_json(args.out, report)
    print(
        f"status={report['status']} jobs={report['jobs_recorded']}/16"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
