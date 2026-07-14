"""Append and summarize the exact nine-job W3b fit submission journal."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import sha256_file


_WORKSTREAM = "m6d_w3b_fit_matched_predictors"
_STAGES = ("proteinmpnn_submitted", "boltz_submitted", "af2_submitted")
_JOB_FIELDS = {
    "proteinmpnn_submitted": "proteinmpnn_job_id",
    "boltz_submitted": "boltz_job_id",
    "af2_submitted": "af2_job_id",
}


def _job_id(value: Any, field: str) -> str:
    text = str(value or "")
    if not text or any(character.isspace() for character in text):
        raise ValueError(f"invalid {field}: {value!r}")
    return text


def load_events(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    events: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            events.append(value)
    return events


def target_state(
    events: Iterable[Mapping[str, Any]],
    target_id: str,
    packet_sha256: str,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "target_id": target_id,
        "proteinmpnn_job_id": None,
        "boltz_job_id": None,
        "af2_job_id": None,
        "stages": [],
        "events": {},
    }
    for event in events:
        if str(event.get("target_id") or "") != target_id:
            continue
        if event.get("workstream") != _WORKSTREAM:
            raise ValueError(f"target_id={target_id} has a conflicting workstream")
        if event.get("approval_packet_sha256") != packet_sha256:
            raise ValueError(f"target_id={target_id} has a conflicting approval packet")
        stage = str(event.get("stage") or "")
        if stage not in _STAGES:
            raise ValueError(f"target_id={target_id} has unsupported stage {stage!r}")
        if stage in state["stages"]:
            field = _JOB_FIELDS[stage]
            if state[field] != _job_id(event.get(field), field):
                raise ValueError(f"target_id={target_id} has conflicting {field}")
            continue
        expected_index = len(state["stages"])
        if _STAGES[expected_index] != stage:
            raise ValueError(f"target_id={target_id} journal stages are out of order")
        field = _JOB_FIELDS[stage]
        state[field] = _job_id(event.get(field), field)
        if stage != "proteinmpnn_submitted":
            generation = _job_id(event.get("proteinmpnn_job_id"), "proteinmpnn_job_id")
            if generation != state["proteinmpnn_job_id"]:
                raise ValueError(f"target_id={target_id} predictor dependency differs from generation job")
        state["stages"].append(stage)
        state["events"][stage] = dict(event)
    state["complete"] = state["stages"] == list(_STAGES)
    return state


def append_event(path: str, event: Dict[str, Any]) -> Dict[str, Any]:
    stage = str(event.get("stage") or "")
    target_id = str(event.get("target_id") or "")
    packet_sha256 = str(event.get("approval_packet_sha256") or "")
    if stage not in _STAGES or not target_id or len(packet_sha256) != 64:
        raise ValueError("invalid W3b fit journal event scope")
    if event.get("workstream") != _WORKSTREAM:
        raise ValueError("invalid W3b fit journal workstream")
    _job_id(event.get(_JOB_FIELDS[stage]), _JOB_FIELDS[stage])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    record = dict(event)
    record["timestamp_unix"] = int(record.get("timestamp_unix") or time.time())
    with open(path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = [json.loads(line) for line in handle if line.strip()]
        before = target_state(existing, target_id, packet_sha256)
        if stage in before["stages"]:
            field = _JOB_FIELDS[stage]
            if before[field] != _job_id(record.get(field), field):
                raise ValueError(f"target_id={target_id} already has a different {field}")
            return before
        if len(before["stages"]) >= len(_STAGES) or _STAGES[len(before["stages"])] != stage:
            raise ValueError(f"target_id={target_id} cannot append stage {stage}")
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target_state(load_events(path), target_id, packet_sha256)


def build_summary(packet_path: str, receipt_path: str) -> Dict[str, Any]:
    with open(packet_path) as handle:
        packet = json.load(handle)
    if not (
        isinstance(packet, dict)
        and packet.get("artifact") == "m6d_w3b_fit_approval_packet"
        and packet.get("status") == "w3b_fit_approval_packet_ready_no_submit"
        and packet.get("audit_ok") is True
        and packet.get("approval_recorded") is False
    ):
        raise ValueError("invalid W3b fit approval packet")
    packet_sha256 = sha256_file(packet_path)
    targets = packet.get("fit_targets")
    if not isinstance(targets, list) or len(targets) != 3:
        raise ValueError("W3b fit approval packet must contain exactly three targets")
    by_id = {
        str(row.get("target_id") or ""): row
        for row in targets
        if isinstance(row, dict)
    }
    if len(by_id) != 3 or any(row.get("records_planned") != 60 for row in by_id.values()):
        raise ValueError("W3b fit approval packet target scope is invalid")
    events = load_events(receipt_path)
    unexpected = sorted(
        {
            str(event.get("target_id") or "")
            for event in events
            if event.get("workstream") == _WORKSTREAM
        }
        - set(by_id)
        - {""}
    )
    if unexpected:
        raise ValueError("W3b fit journal has unexpected targets: " + ",".join(unexpected))
    states = {
        target_id: target_state(events, target_id, packet_sha256)
        for target_id in by_id
    }
    incomplete = sorted(target_id for target_id, state in states.items() if not state["complete"])
    if incomplete:
        raise ValueError("W3b fit journal has incomplete targets: " + ",".join(incomplete))
    for target_id, state in states.items():
        target = by_id[target_id]
        expected_paths = {
            "candidates": target.get("candidates"),
            "boltz_records": target.get("boltz_records"),
            "af2_records": target.get("af2_records"),
        }
        for stage, event in state["events"].items():
            mismatches = [
                field
                for field, expected in expected_paths.items()
                if event.get(field) != expected
            ]
            if mismatches:
                raise ValueError(
                    f"target_id={target_id} stage={stage} path mismatch: " + ",".join(mismatches)
                )
    scoped_events = [event for event in events if event.get("workstream") == _WORKSTREAM]
    if len(scoped_events) != 9:
        raise ValueError(f"W3b fit journal requires exactly nine events; observed {len(scoped_events)}")
    job_ids = [
        str(state[field])
        for state in states.values()
        for field in ("proteinmpnn_job_id", "boltz_job_id", "af2_job_id")
    ]
    if len(set(job_ids)) != 9:
        raise ValueError("W3b fit journal job IDs are not unique")
    return {
        "artifact": "m6d_w3b_fit_submit_receipt_summary",
        "version": 1,
        "status": "w3b_fit_jobs_submitted_awaiting_completion",
        "approval_packet": packet_path,
        "approval_packet_sha256": packet_sha256,
        "readiness_packet_digest_sha256": packet["readiness_packet_digest_sha256"],
        "receipt": receipt_path,
        "receipt_sha256": sha256_file(receipt_path),
        "workstream": _WORKSTREAM,
        "n_targets": 3,
        "n_candidate_designs": 180,
        "n_predictor_evaluations_planned": 360,
        "n_jobs": 9,
        "n_proteinmpnn_jobs": 3,
        "n_boltz_h100_jobs": 3,
        "n_af2_h100_jobs": 3,
        "targets": [
            {
                "target_id": target_id,
                "proteinmpnn_job_id": states[target_id]["proteinmpnn_job_id"],
                "boltz_job_id": states[target_id]["boltz_job_id"],
                "af2_job_id": states[target_id]["af2_job_id"],
            }
            for target_id in sorted(states)
        ],
        "can_claim_w3b": False,
        "claim_boundary": (
            "Scheduler provenance only. Submission and job completion are not fit evidence, "
            "do not freeze a gate, and support no W3b or biological-success claim."
        ),
        "next_action": "query all nine jobs, enforce cumulative GPU accounting, and sync only after terminal success",
    }


def _write_summary(path: str, summary: Mapping[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".w3b-fit-summary-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("--receipt", required=True)
    append.add_argument("--stage", choices=_STAGES, required=True)
    append.add_argument("--target-id", required=True)
    append.add_argument("--approval-packet", required=True)
    append.add_argument("--proteinmpnn-job-id", required=True)
    append.add_argument("--boltz-job-id")
    append.add_argument("--af2-job-id")
    append.add_argument("--candidates", required=True)
    append.add_argument("--boltz-records", required=True)
    append.add_argument("--af2-records", required=True)
    summary = subparsers.add_parser("summary")
    summary.add_argument("--approval-packet", required=True)
    summary.add_argument("--receipt", required=True)
    summary.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "summary":
        report = build_summary(args.approval_packet, args.receipt)
        _write_summary(args.out, report)
        print(f"status={report['status']} jobs={report['n_jobs']} claim=False")
        return 0
    packet_sha256 = sha256_file(args.approval_packet)
    event = {
        "artifact": "m6d_w3b_fit_submit_event",
        "version": 1,
        "workstream": _WORKSTREAM,
        "stage": args.stage,
        "target_id": args.target_id,
        "approval_packet": args.approval_packet,
        "approval_packet_sha256": packet_sha256,
        "proteinmpnn_job_id": args.proteinmpnn_job_id,
        "boltz_job_id": args.boltz_job_id,
        "af2_job_id": args.af2_job_id,
        "candidates": args.candidates,
        "boltz_records": args.boltz_records,
        "af2_records": args.af2_records,
    }
    state = append_event(args.receipt, event)
    print(f"target={args.target_id} stages={len(state['stages'])} complete={state['complete']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
