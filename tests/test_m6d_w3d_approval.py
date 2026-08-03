"""Tests for the no-submit W3d 24-evaluation approval packet."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from bio_sfm_designer.experiments import m6d_w3d_approval as mod
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "results/m6d_w3d_prediction_approval_packet.json"
READINESS = ROOT / "results/m6d_w3d_prediction_packet_readiness.json"


def test_committed_packet_is_reproducible_and_grants_zero_authority(monkeypatch):
    monkeypatch.chdir(ROOT)
    readiness = mod.build_readiness(require_input_files=False)
    packet = json.loads(PACKET.read_text())

    assert readiness == json.loads(READINESS.read_text())
    assert packet == mod.build_approval_packet(readiness)
    assert packet["approval_recorded"] is False
    assert packet["no_submit"] is True
    assert packet["can_submit_now"] is False
    assert packet["approval_contract"]["maximum_predictor_evaluations"] == 24
    assert packet["approval_contract"]["maximum_h100_gpu_hours"] == 24.0
    assert packet["approval_contract"]["proteinmpnn_designs"] == 0
    assert len(packet["execution_cells"]) == 24
    assert len(packet["initial_output_paths"]) == 53
    assert mod.verify_packet_integrity(str(PACKET.relative_to(ROOT))) == []


def test_packet_has_exact_prospective_predictor_counts(monkeypatch):
    monkeypatch.chdir(ROOT)
    packet = json.loads(PACKET.read_text())
    counts = {}
    for row in packet["execution_cells"]:
        counts[row["predictor_id"]] = counts.get(row["predictor_id"], 0) + 1

    assert counts == {"boltz2_complex": 8, "af2_multimer_colabfold_v1": 16}
    assert all(row["predictor_evaluations"] == 1 for row in packet["execution_cells"])
    assert all(row["maximum_h100_gpu_hours"] == 1.0 for row in packet["execution_cells"])


def test_self_rehashed_execution_cell_drift_still_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    packet = json.loads(PACKET.read_text())
    packet["execution_cells"][0]["output_dir"] = (
        "hpc_outputs/m6d_w3d_native_diagnostic/wrong/prediction"
    )
    packet["initial_output_paths"][0] = packet["execution_cells"][0]["output_dir"]
    packet["packet_digest_sha256"] = canonical_sha256(
        mod._packet_digest_input(packet)
    )
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(packet))

    failures = mod.verify_packet_integrity(str(path))

    assert "execution_cells_not_input_manifest_derived" in failures


def test_producer_token_drift_blocks_readiness(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    producer_paths = copy.deepcopy(mod.PRODUCER_PATHS)
    original = Path(producer_paths["submit_wrapper"]).read_text()
    drifted = tmp_path / "submit.sh"
    drifted.write_text(original.replace(mod.APPROVAL_TOKEN, "wrong-token"))
    producer_paths["submit_wrapper"] = str(drifted)

    readiness = mod.build_readiness(
        producer_paths=producer_paths,
        require_input_files=False,
    )

    assert readiness["audit_ok"] is False
    assert readiness["prediction_packet_ready"] is False
    assert any(
        row["kind"] == "approval_token_missing"
        for row in readiness["failures"]
    )


def test_submit_bridge_dry_run_never_calls_scheduler(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    marker = tmp_path / "scheduler-called"
    fake_sbatch = tmp_path / "sbatch"
    fake_sbatch.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n")
    fake_sbatch.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "BIO_SFM_SUBMIT_DRY_RUN": "1",
        "BIO_SFM_PYTHON": sys.executable,
        "SBATCH_BIN": str(fake_sbatch),
        "PYTHONPATH": (
            f"{ROOT / 'src'}:{ROOT.parent / 'bio-sfm-trust-core' / 'src'}"
        ),
        "PYTHONNOUSERSITE": "1",
    })

    completed = subprocess.run(
        ["bash", "hpc/m6d_w3d_submit_with_receipt.sh"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "24 evaluations, zero scheduler jobs" in completed.stdout
    assert not marker.exists()
