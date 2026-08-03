"""Tests for the append-only W3d submission journal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3d_submit_journal as mod


ROOT = Path(__file__).resolve().parents[1]
PACKET = "results/m6d_w3d_prediction_approval_packet.json"


def test_complete_journal_records_exactly_the_packet_cells(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    packet = json.loads(Path(PACKET).read_text())
    receipt = tmp_path / "receipt.jsonl"

    for index, cell in enumerate(packet["execution_cells"], 1):
        mod.append(PACKET, str(receipt), cell["cell_id"], str(900000 + index))
    summary = mod.summarize(PACKET, str(receipt))

    assert summary["audit_ok"] is True
    assert summary["jobs_recorded"] == 24
    assert summary["predictor_job_counts"] == {
        "boltz2_complex": 8,
        "af2_multimer_colabfold_v1": 16,
    }
    assert summary["retry_jobs"] == 0
    assert summary["adaptive_top_up_jobs"] == 0
    assert summary["can_claim_native_recoverability"] is False


def test_duplicate_or_out_of_scope_receipt_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    packet = json.loads(Path(PACKET).read_text())
    receipt = tmp_path / "receipt.jsonl"
    cell_id = packet["execution_cells"][0]["cell_id"]
    mod.append(PACKET, str(receipt), cell_id, "900001")

    with pytest.raises(ValueError, match="duplicate"):
        mod.append(PACKET, str(receipt), cell_id, "900002")
    with pytest.raises(ValueError, match="outside the frozen scope"):
        mod.append(PACKET, str(receipt), "w3d-not-a-cell", "900003")
    with pytest.raises(ValueError, match="invalid Slurm job id"):
        mod.append(
            PACKET,
            str(tmp_path / "other.jsonl"),
            cell_id,
            "not-a-job",
        )


def test_partial_journal_cannot_claim_complete(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    packet = json.loads(Path(PACKET).read_text())
    receipt = tmp_path / "receipt.jsonl"
    mod.append(
        PACKET,
        str(receipt),
        packet["execution_cells"][0]["cell_id"],
        "900001",
    )

    summary = mod.summarize(PACKET, str(receipt))

    assert summary["audit_ok"] is False
    assert summary["submission_complete"] is False
    assert summary["jobs_recorded"] == 1
