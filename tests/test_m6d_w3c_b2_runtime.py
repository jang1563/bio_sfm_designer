"""Tests for read-only W3c-B2 runtime reobservation and locking."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_runtime as mod


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "configs/m6d_w3c_validity_first_protocol.json"
NATIVE_MANIFEST = "configs/m6d_w3c_b2_native_screen_manifest.json"
B1_COMPLETION = "results/m6d_w3c_b1_target_msa_completion.json"
W3B_RUNTIME_LOCK = "configs/m6d_w3b_runtime_lock.json"
VALIDATION_SCRIPT = "hpc/validate_w3c_b2_runtime_no_prediction.sh"
RUNTIME_MODULE = (
    "src/bio_sfm_designer/experiments/m6d_w3c_b2_runtime.py"
)


def _load(path):
    return json.loads(Path(path).read_text())


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build_observations(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    transfer = _load(W3B_RUNTIME_LOCK)
    observations = {}
    paths = {}
    for predictor_id in mod.PREDICTOR_IDS:
        observation = mod.build_observation(
            predictor_id,
            transfer["predictor_runtime_identities"][predictor_id],
            protocol_path=PROTOCOL,
            native_manifest_path=NATIVE_MANIFEST,
            b1_completion_path=B1_COMPLETION,
            w3b_runtime_lock_path=W3B_RUNTIME_LOCK,
        )
        path = tmp_path / f"{predictor_id}.json"
        _write(path, observation)
        observations[predictor_id] = observation
        paths[predictor_id] = str(path)
    return observations, paths


def _readiness(observations, observation_paths):
    return mod.build_runtime_readiness(
        protocol_path=PROTOCOL,
        native_manifest_path=NATIVE_MANIFEST,
        b1_completion_path=B1_COMPLETION,
        w3b_runtime_lock_path=W3B_RUNTIME_LOCK,
        validation_script_path=VALIDATION_SCRIPT,
        runtime_module_path=RUNTIME_MODULE,
        observations=observations,
        observation_paths=observation_paths,
    )


def test_packet_is_ready_without_granting_compute_or_prediction(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    missing_paths = {
        predictor_id: str(tmp_path / f"missing-{predictor_id}.json")
        for predictor_id in mod.PREDICTOR_IDS
    }

    readiness = _readiness({}, missing_paths)

    assert readiness["status"] == (
        "w3c_b2_runtime_reobservation_packet_ready_no_submit"
    )
    assert readiness["audit_ok"] is True
    assert readiness["runtime_identity_ready"] is False
    assert readiness["runtime_observations_complete"] == 0
    assert readiness["prediction_executed"] is False
    assert readiness["gpu_compute_executed"] is False
    assert readiness["scheduler_command_executed"] is False
    assert readiness["can_run_predictors"] is False
    assert readiness["cayuga_submission_allowed"] is False


def test_exact_fresh_observations_build_runtime_lock(tmp_path, monkeypatch):
    observations, paths = _build_observations(tmp_path, monkeypatch)

    readiness = _readiness(observations, paths)
    lock = mod.build_runtime_lock(readiness, observations)

    assert readiness["status"] == (
        "w3c_b2_runtime_reobservation_complete_no_prediction"
    )
    assert readiness["runtime_identity_ready"] is True
    assert readiness["runtime_observations_complete"] == 2
    assert lock["status"] == (
        "w3c_b2_dual_predictor_runtime_reobserved_no_prediction"
    )
    assert lock["new_runtime_observations"] == 2
    assert lock["predictor_runtime_identity_sha256"] == readiness[
        "expected_predictor_runtime_identity_sha256"
    ]
    assert lock["prediction_executed"] is False
    assert lock["can_run_predictors"] is False


def test_observed_identity_drift_fails_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    transfer = _load(W3B_RUNTIME_LOCK)
    identity = copy.deepcopy(
        transfer["predictor_runtime_identities"]["boltz2_complex"]
    )
    identity["execution_parameters"]["sampling_steps"] = 200

    with pytest.raises(ValueError, match="differs from the exact transfer source"):
        mod.build_observation(
            "boltz2_complex",
            identity,
            protocol_path=PROTOCOL,
            native_manifest_path=NATIVE_MANIFEST,
            b1_completion_path=B1_COMPLETION,
            w3b_runtime_lock_path=W3B_RUNTIME_LOCK,
        )


def test_readiness_rejects_object_file_binding_mismatch(tmp_path, monkeypatch):
    observations, paths = _build_observations(tmp_path, monkeypatch)
    altered = copy.deepcopy(observations["boltz2_complex"])
    altered["claim_boundary"] = "changed after serialization"
    observations["boltz2_complex"] = altered

    readiness = _readiness(observations, paths)

    assert readiness["audit_ok"] is False
    assert readiness["runtime_identity_ready"] is False
    assert readiness["status"] == "w3c_b2_runtime_reobservation_blocked"
    assert any(
        row["predictor_id"] == "boltz2_complex"
        and "serialized_observation_binding" in row["checks_failed"]
        for row in readiness["failures"]
    )


def test_runtime_lock_rechecks_files_after_readiness(tmp_path, monkeypatch):
    observations, paths = _build_observations(tmp_path, monkeypatch)
    readiness = _readiness(observations, paths)
    Path(paths["boltz2_complex"]).write_text("{}\n")

    with pytest.raises(ValueError, match="observation binding invalid"):
        mod.build_runtime_lock(readiness, observations)


def test_validation_script_has_read_only_runtime_boundary():
    script = (ROOT / VALIDATION_SCRIPT).read_text()

    for forbidden in (
        "sbatch",
        "srun",
        "--nv",
        "boltz predict",
        "colabfold_batch",
    ):
        assert forbidden not in script
    assert "--network none" in script
    assert "PYTHONNOUSERSITE=1" in script


def test_packet_cli_materializes_readiness_without_runtime_lock(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(ROOT)
    readiness_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness.md"
    lock_path = tmp_path / "runtime-lock.json"

    rc = mod.main([
        "packet",
        "--protocol",
        PROTOCOL,
        "--native-manifest",
        NATIVE_MANIFEST,
        "--b1-completion",
        B1_COMPLETION,
        "--w3b-runtime-lock",
        W3B_RUNTIME_LOCK,
        "--boltz-observation",
        str(tmp_path / "missing-boltz.json"),
        "--af2-observation",
        str(tmp_path / "missing-af2.json"),
        "--out-readiness",
        str(readiness_path),
        "--out-readiness-md",
        str(markdown_path),
        "--out-runtime-lock",
        str(lock_path),
    ])

    assert rc == 0
    assert _load(readiness_path)["runtime_observations_complete"] == 0
    assert "Prediction executed: `False`" in markdown_path.read_text()
    assert not lock_path.exists()
