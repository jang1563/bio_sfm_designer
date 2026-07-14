"""Tests for the frozen W3b dual-predictor runtime lock."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    build_readiness,
    build_runtime_lock,
    canonical_sha256,
    main,
    runtime_identity,
    validate_runtime_lock,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "configs/m6d_w3b_disagreement_gate_protocol.json"
BOLTZ = ROOT / "results/m6d_w3b_boltz_runtime_observation.json"
AF2_RUNTIME = ROOT / "results/m6d_w3_mechanism_runtime_receipt.json"
AF2_PROVISION = ROOT / "results/m6d_w3_runtime_provision_receipt.json"
EXECUTION_READINESS = ROOT / "results/m6d_w3b_execution_lock_readiness.json"


def _load(path: Path):
    return json.loads(path.read_text())


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _build(
    *,
    protocol: Path = PROTOCOL,
    boltz: Path = BOLTZ,
    af2_runtime: Path = AF2_RUNTIME,
    af2_provision: Path = AF2_PROVISION,
):
    return build_runtime_lock(
        str(protocol),
        str(boltz),
        str(af2_runtime),
        str(af2_provision),
    )


def _recompute_lock_digest(lock) -> None:
    identities = lock["predictor_runtime_identities"]
    digests = {
        predictor_id: canonical_sha256(identity)
        for predictor_id, identity in identities.items()
    }
    lock["predictor_runtime_identity_sha256"] = digests
    lock["runtime_lock_digest_sha256"] = canonical_sha256({
        "protocol_sha256": lock["protocol_sha256"],
        "locked_scientific_digest": lock["locked_scientific_digest"],
        "predictor_runtime_identities": identities,
        "predictor_runtime_identity_sha256": digests,
        "source_sha256": {
            key: value["sha256"]
            for key, value in lock["source_bindings"].items()
        },
    })


def test_current_runtime_lock_is_coherent_and_no_submit():
    lock = _build()

    assert lock["audit_ok"] is True
    assert lock["runtime_identity_ready"] is True
    assert lock["cayuga_submission_allowed"] is False
    assert lock["can_generate_candidates_or_run_predictors"] is False
    assert lock["n_failures"] == 0
    assert validate_runtime_lock(lock, str(PROTOCOL)) == []
    boltz = runtime_identity(lock, "boltz2_complex", str(PROTOCOL))
    af2 = runtime_identity(lock, "af2_multimer_colabfold_v1", str(PROTOCOL))
    assert boltz["boltz_version"] == "2.2.1"
    assert boltz["execution_parameters"]["seed"] == 0
    assert boltz["execution_parameters"]["sampling_steps"] == 100
    assert af2["container_sha256"] == "e26689bc357e8aaf5210ed43499e565d2a440ea6efde5a8a42cbdc4f6a83e566"
    assert len(af2["weights"]) == 5


def test_boltz_checkpoint_drift_blocks_lock(tmp_path):
    observation = _load(BOLTZ)
    observation["runtime_identity"]["cache_checkpoints"][0]["sha256"] = "f" * 64
    path = tmp_path / "boltz.json"
    _write(path, observation)

    lock = _build(boltz=path)

    assert lock["audit_ok"] is False
    assert "runtime_lock_boltz_identity_drift" in {row["kind"] for row in lock["failures"]}


def test_af2_container_or_weight_drift_blocks_lock(tmp_path):
    runtime = _load(AF2_RUNTIME)
    runtime["runtime_sha256"] = "e" * 64
    runtime_path = tmp_path / "runtime.json"
    _write(runtime_path, runtime)

    lock = _build(af2_runtime=runtime_path)

    kinds = {row["kind"] for row in lock["failures"]}
    assert lock["audit_ok"] is False
    assert "runtime_lock_af2_runtime_receipt_invalid_or_drifted" in kinds
    assert "runtime_lock_af2_source_receipts_disagree" in kinds


def test_protocol_approval_or_compute_drift_blocks_lock(tmp_path):
    protocol = _load(PROTOCOL)
    protocol["execution_state"]["approval_recorded"] = True
    protocol["execution_state"]["no_gpu_compute"] = False
    protocol_path = tmp_path / "protocol.json"
    _write(protocol_path, protocol)

    lock = _build(protocol=protocol_path)

    assert lock["audit_ok"] is False
    assert "runtime_lock_protocol_approval_boundary_invalid" in {
        row["kind"] for row in lock["failures"]
    }


def test_self_consistent_but_wrong_runtime_identity_fails_validation():
    lock = _build()
    lock = copy.deepcopy(lock)
    lock["predictor_runtime_identities"]["boltz2_complex"]["execution_parameters"]["sampling_steps"] = 200
    _recompute_lock_digest(lock)

    failures = validate_runtime_lock(lock, str(PROTOCOL))

    assert "runtime_lock_boltz_frozen_identity_invalid" in {row["kind"] for row in failures}


def test_rehashed_source_binding_cannot_hide_source_file_drift():
    lock = _build()
    lock = copy.deepcopy(lock)
    lock["source_bindings"]["boltz_runtime_observation"]["sha256"] = "f" * 64
    _recompute_lock_digest(lock)

    failures = validate_runtime_lock(lock, str(PROTOCOL))

    assert "runtime_lock_source_file_hash_mismatch" in {row["kind"] for row in failures}


def test_current_readiness_is_runtime_ready_but_execution_locked(tmp_path):
    lock_path = tmp_path / "runtime_lock.json"
    _write(lock_path, _build())

    report = build_readiness(str(lock_path), str(EXECUTION_READINESS))

    assert report["audit_ok"] is True
    assert report["runtime_identity_ready"] is True
    assert report["execution_lock_ready"] is False
    assert report["fit_packet_prerequisites_ready"] is False
    assert report["can_submit_fit_stage"] is False
    assert report["status"] == "w3b_runtime_locked_awaiting_execution_lock"


def test_execution_readiness_from_different_protocol_is_blocked(tmp_path):
    lock_path = tmp_path / "runtime_lock.json"
    execution_path = tmp_path / "execution_readiness.json"
    _write(lock_path, _build())
    execution = _load(EXECUTION_READINESS)
    execution["protocol_sha256"] = "f" * 64
    _write(execution_path, execution)

    report = build_readiness(str(lock_path), str(execution_path))

    assert report["audit_ok"] is False
    assert "runtime_lock_execution_protocol_binding_mismatch" in {
        row["kind"] for row in report["failures"]
    }


def test_cli_materializes_lock_and_readiness_without_compute(tmp_path):
    lock_path = tmp_path / "runtime_lock.json"
    readiness_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness.md"

    rc = main([
        "--protocol", str(PROTOCOL),
        "--boltz-observation", str(BOLTZ),
        "--af2-runtime-receipt", str(AF2_RUNTIME),
        "--af2-provision-receipt", str(AF2_PROVISION),
        "--execution-readiness", str(EXECUTION_READINESS),
        "--out-lock", str(lock_path),
        "--out-readiness", str(readiness_path),
        "--out-readiness-md", str(markdown_path),
    ])

    assert rc == 0
    assert _load(lock_path)["audit_ok"] is True
    assert _load(readiness_path)["runtime_identity_ready"] is True
    assert "No submit: `True`" in markdown_path.read_text()
