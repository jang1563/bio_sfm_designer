"""Tests for the no-submit W3c-B2 prediction approval packet."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from bio_sfm_designer.experiments import m6d_w3c_b2_approval as mod
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "configs/m6d_w3c_b2_native_screen_manifest.json"
RUNTIME_READINESS = "results/m6d_w3c_b2_runtime_readiness.json"
RUNTIME_LOCK = "configs/m6d_w3c_b2_runtime_lock.json"
BOLTZ_OBSERVATION = "results/m6d_w3c_b2_boltz_runtime_observation.json"
AF2_OBSERVATION = "results/m6d_w3c_b2_af2_runtime_observation.json"
PACKET = "results/m6d_w3c_b2_prediction_approval_packet.json"
CAYUGA_VALIDATION = "results/m6d_w3c_b2_cayuga_no_submit_validation.json"


def _readiness():
    return mod.build_readiness(
        native_manifest_path=MANIFEST,
        runtime_readiness_path=RUNTIME_READINESS,
        runtime_lock_path=RUNTIME_LOCK,
        boltz_observation_path=BOLTZ_OBSERVATION,
        af2_observation_path=AF2_OBSERVATION,
    )


def test_committed_packet_is_frozen_and_grants_zero_authority(monkeypatch):
    monkeypatch.chdir(ROOT)

    packet = json.loads(Path(PACKET).read_text())

    assert packet["approval_recorded"] is False
    assert packet["no_submit"] is True
    assert packet["approval_contract"]["maximum_predictor_evaluations"] == 16
    assert packet["approval_contract"]["maximum_h100_gpu_hours"] == 16.0
    assert packet["approval_contract"]["proteinmpnn_designs"] == 0
    assert len(packet["execution_targets"]) == 8
    assert len(packet["initial_output_paths"]) == 77
    assert mod.verify_packet_integrity(PACKET) == []


def test_post_submission_outputs_block_packet_regeneration(monkeypatch):
    monkeypatch.chdir(ROOT)

    readiness = _readiness()

    assert readiness["audit_ok"] is False
    assert readiness["prediction_packet_ready"] is False
    assert readiness["can_submit_now"] is False
    assert readiness["submitted_jobs"] == 0
    assert readiness["predictor_evaluations_executed"] == 0
    assert readiness["h100_gpu_hours_consumed"] == 0.0
    assert readiness["failures"] == [{
        "kind": "initial_output_already_exists",
        "paths": [
            "results/m6d_w3c_b2_submit_receipt.jsonl",
            "results/m6d_w3c_b2_submit_receipt_summary.json",
        ],
    }]


def test_cayuga_no_submit_evidence_is_public_safe_and_source_bound(monkeypatch):
    monkeypatch.chdir(ROOT)
    evidence_text = Path(CAYUGA_VALIDATION).read_text()
    evidence = json.loads(evidence_text)

    assert evidence["validation_passed"] is True
    assert evidence["mirror"]["remote_packet_integrity_verified"] is True
    assert evidence["runtime_reobservation"]["observed_predictors"] == 2
    assert evidence["runtime_reobservation"]["prediction_executed"] is False
    assert evidence["execution"]["initial_output_paths_absent"] == 77
    assert evidence["execution"]["predictor_evaluations_enumerated"] == 16
    assert evidence["execution"]["scheduler_jobs_submitted"] == 0
    assert evidence["execution"]["receipt_created"] is False
    assert evidence["approval_boundary"]["predictor_evaluations_authorized"] == 0
    assert evidence["approval_boundary"]["h100_gpu_hours_authorized"] == 0.0
    for binding in evidence["mirror"]["artifacts"]:
        assert mod.sha256_file(binding["path"]) == binding["sha256"]
    for private_marker in ("/home/", "/athena/", "/Users/"):
        assert private_marker not in evidence_text


def test_self_rehashed_execution_path_drift_still_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    packet = json.loads(Path(PACKET).read_text())
    packet["execution_targets"][0]["boltz_record"] = "wrong.json"
    packet["packet_digest_sha256"] = canonical_sha256(
        mod._packet_digest_input(packet)
    )
    path = tmp_path / "forged-packet.json"
    path.write_text(json.dumps(packet))

    failures = mod.verify_packet_integrity(str(path))

    assert "execution_targets_not_manifest_derived" in failures


def test_producer_token_drift_blocks_readiness(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    producer_paths = copy.deepcopy(mod.PRODUCER_PATHS)
    original = Path(producer_paths["boltz_wrapper"]).read_text()
    drifted = tmp_path / "boltz.sbatch"
    drifted.write_text(original.replace(mod.APPROVAL_TOKEN, "wrong-token"))
    producer_paths["boltz_wrapper"] = str(drifted)

    readiness = mod.build_readiness(
        native_manifest_path=MANIFEST,
        runtime_readiness_path=RUNTIME_READINESS,
        runtime_lock_path=RUNTIME_LOCK,
        boltz_observation_path=BOLTZ_OBSERVATION,
        af2_observation_path=AF2_OBSERVATION,
        producer_paths=producer_paths,
    )

    assert readiness["audit_ok"] is False
    assert readiness["prediction_packet_ready"] is False
    assert any(
        row["kind"] == "approval_token_missing"
        for row in readiness["failures"]
    )


def test_shell_surfaces_are_syntax_valid_and_scope_locked(monkeypatch):
    monkeypatch.chdir(ROOT)
    submit = Path(mod.PRODUCER_PATHS["submit_wrapper"]).read_text()
    boltz = Path(mod.PRODUCER_PATHS["boltz_wrapper"]).read_text()
    af2 = Path(mod.PRODUCER_PATHS["af2_wrapper"]).read_text()

    assert "--dependency" not in submit
    assert "ProteinMPNN" not in submit + boltz + af2
    assert "--network none" in af2
    assert "#SBATCH --time=01:00:00" in boltz
    assert "#SBATCH --time=01:00:00" in af2
    assert "dry-run complete: 8 targets, 16 evaluations" in submit
