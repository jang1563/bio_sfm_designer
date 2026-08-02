"""Tests for the append-only W3c-B2 submission journal."""

from __future__ import annotations

from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_submit_journal as mod
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    PREDICTOR_IDS,
    TARGET_IDS,
)


ROOT = Path(__file__).resolve().parents[1]
PACKET = "results/m6d_w3c_b2_prediction_approval_packet.json"


def test_exact_sixteen_rows_complete_submission_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    receipt = tmp_path / "receipt.jsonl"
    job_id = 1000
    for target_id in TARGET_IDS:
        for predictor_id in PREDICTOR_IDS:
            mod.append(
                PACKET,
                str(receipt),
                target_id,
                predictor_id,
                str(job_id),
            )
            job_id += 1

    summary = mod.summarize(PACKET, str(receipt))

    assert summary["audit_ok"] is True
    assert summary["submission_complete"] is True
    assert summary["jobs_recorded"] == 16
    assert summary["retry_jobs"] == 0
    assert summary["adaptive_top_up_jobs"] == 0
    assert summary["can_claim_native_recoverability"] is False


def test_duplicate_pair_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    receipt = tmp_path / "receipt.jsonl"
    mod.append(
        PACKET,
        str(receipt),
        TARGET_IDS[0],
        PREDICTOR_IDS[0],
        "1000",
    )

    with pytest.raises(ValueError, match="duplicate"):
        mod.append(
            PACKET,
            str(receipt),
            TARGET_IDS[0],
            PREDICTOR_IDS[0],
            "1001",
        )


def test_invalid_job_id_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)

    with pytest.raises(ValueError, match="invalid Slurm job id"):
        mod.append(
            PACKET,
            str(tmp_path / "receipt.jsonl"),
            TARGET_IDS[0],
            PREDICTOR_IDS[0],
            "not-a-job",
        )
