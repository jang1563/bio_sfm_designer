"""Tests for the append-only W3b fit scheduler journal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3b_fit_submit_journal import (
    append_event,
    build_summary,
)
from bio_sfm_designer.experiments.m6d_w3b_producer_contract import sha256_file


WORKSTREAM = "m6d_w3b_fit_matched_predictors"


def _packet(tmp_path: Path) -> Path:
    targets = []
    for target_id in ("FIT_A", "FIT_B", "FIT_C"):
        root = tmp_path / "outputs" / target_id
        targets.append({
            "target_id": target_id,
            "records_planned": 60,
            "candidates": str(root / "candidates.jsonl"),
            "boltz_records": str(root / "boltz.jsonl"),
            "af2_records": str(root / "af2.jsonl"),
        })
    packet = {
        "artifact": "m6d_w3b_fit_approval_packet",
        "version": 1,
        "status": "w3b_fit_approval_packet_ready_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "approval_recorded": False,
        "readiness_packet_digest_sha256": "a" * 64,
        "fit_targets": targets,
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    return path


def _event(packet: Path, target, stage: str, index: int):
    event = {
        "artifact": "m6d_w3b_fit_submit_event",
        "version": 1,
        "workstream": WORKSTREAM,
        "stage": stage,
        "target_id": target["target_id"],
        "approval_packet": str(packet),
        "approval_packet_sha256": sha256_file(packet),
        "proteinmpnn_job_id": str(1000 + 3 * index),
        "boltz_job_id": None,
        "af2_job_id": None,
        "candidates": target["candidates"],
        "boltz_records": target["boltz_records"],
        "af2_records": target["af2_records"],
    }
    if stage in ("boltz_submitted", "af2_submitted"):
        event["boltz_job_id"] = str(1001 + 3 * index)
    if stage == "af2_submitted":
        event["af2_job_id"] = str(1002 + 3 * index)
    return event


def test_complete_nine_event_journal_summarizes_exact_scope(tmp_path):
    packet = _packet(tmp_path)
    targets = json.loads(packet.read_text())["fit_targets"]
    receipt = tmp_path / "receipt.jsonl"
    for index, target in enumerate(targets):
        for stage in ("proteinmpnn_submitted", "boltz_submitted", "af2_submitted"):
            state = append_event(str(receipt), _event(packet, target, stage, index))
        assert state["complete"] is True

    summary = build_summary(str(packet), str(receipt))

    assert summary["status"] == "w3b_fit_jobs_submitted_awaiting_completion"
    assert summary["n_jobs"] == 9
    assert summary["n_candidate_designs"] == 180
    assert summary["n_predictor_evaluations_planned"] == 360
    assert summary["can_claim_w3b"] is False


def test_out_of_order_predictor_event_is_rejected(tmp_path):
    packet = _packet(tmp_path)
    target = json.loads(packet.read_text())["fit_targets"][0]
    receipt = tmp_path / "receipt.jsonl"

    with pytest.raises(ValueError, match="cannot append stage"):
        append_event(str(receipt), _event(packet, target, "boltz_submitted", 0))


def test_conflicting_duplicate_job_id_is_rejected(tmp_path):
    packet = _packet(tmp_path)
    target = json.loads(packet.read_text())["fit_targets"][0]
    receipt = tmp_path / "receipt.jsonl"
    first = _event(packet, target, "proteinmpnn_submitted", 0)
    append_event(str(receipt), first)
    conflicting = dict(first)
    conflicting["proteinmpnn_job_id"] = "9999"

    with pytest.raises(ValueError, match="different proteinmpnn_job_id"):
        append_event(str(receipt), conflicting)


def test_summary_rejects_record_path_drift(tmp_path):
    packet = _packet(tmp_path)
    targets = json.loads(packet.read_text())["fit_targets"]
    receipt = tmp_path / "receipt.jsonl"
    for index, target in enumerate(targets):
        for stage in ("proteinmpnn_submitted", "boltz_submitted", "af2_submitted"):
            event = _event(packet, target, stage, index)
            if target["target_id"] == "FIT_B" and stage == "af2_submitted":
                event["af2_records"] = "wrong.jsonl"
            append_event(str(receipt), event)

    with pytest.raises(ValueError, match="path mismatch"):
        build_summary(str(packet), str(receipt))
