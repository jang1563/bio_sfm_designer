"""Tests for the strict W3c-B2 native predictor producers."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_producer as mod
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    PREDICTOR_IDS,
    TARGET_IDS,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_runtime import (
    validate_runtime_lock_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "configs/m6d_w3c_b2_native_screen_manifest.json"
RUNTIME_LOCK = "configs/m6d_w3c_b2_runtime_lock.json"
OBSERVATIONS = {
    "boltz2_complex": "results/m6d_w3c_b2_boltz_runtime_observation.json",
    "af2_multimer_colabfold_v1": (
        "results/m6d_w3c_b2_af2_runtime_observation.json"
    ),
}


def _write_pdb(path, binder_offset=4.0):
    lines = []
    atom_id = 1
    coordinates = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    for chain, offset in (("A", 0.0), ("B", binder_offset)):
        for residue_id, (x, y, z) in enumerate(coordinates, 1):
            lines.append(
                f"ATOM  {atom_id:5d}  CA  ALA {chain}{residue_id:4d}    "
                f"{x:8.3f}{y + offset:8.3f}{z:8.3f}  "
                "1.00 20.00           C\n"
            )
            atom_id += 1
    lines.append("END\n")
    Path(path).write_text("".join(lines))


def _synthetic_context(tmp_path, predictor_id):
    reference = tmp_path / "reference.pdb"
    target_msa = tmp_path / "target.a3m"
    _write_pdb(reference)
    target_msa.write_text(">query\nAAAA\n")
    return {
        "manifest": {},
        "runtime_lock": {
            "predictor_runtime_identity_sha256": {
                predictor_id: "a" * 64,
            }
        },
        "target": {
            "target_id": "TEST_AB",
            "native_candidate_id": "w3c-b2-native-TEST_AB",
            "target_chain": "A",
            "binder_chain": "B",
            "prepared_pdb": str(reference),
            "prepared_pdb_sha256": mod.sha256_file(reference),
            "target_msa": str(target_msa),
            "target_sequence_length": 4,
            "binder_sequence_length": 4,
            "target_sequence_sha256": mod.sequence_sha256("AAAA"),
            "binder_sequence_sha256": mod.sequence_sha256("AAAA"),
            "target_msa_sha256": "b" * 64,
            "outputs": {},
        },
        "target_sequence": "AAAA",
        "binder_sequence": "AAAA",
        "predictor_id": predictor_id,
        "bindings": {
            "native_screen_manifest_sha256": "c" * 64,
            "runtime_lock_sha256": "d" * 64,
            "runtime_lock_digest_sha256": "e" * 64,
        },
    }


def test_all_sixteen_locked_contexts_validate(monkeypatch):
    monkeypatch.chdir(ROOT)

    for target_id in TARGET_IDS:
        for predictor_id in PREDICTOR_IDS:
            context = mod.load_context(
                MANIFEST,
                RUNTIME_LOCK,
                target_id,
                predictor_id,
            )
            observation = mod.validate_runtime_observation_file(
                context, OBSERVATIONS[predictor_id]
            )
            assert observation["predictor_id"] == predictor_id


def test_materialized_runtime_lock_rejects_serialized_drift(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(ROOT)
    manifest = mod.load_object(MANIFEST)
    lock = mod.load_object(RUNTIME_LOCK)
    lock["submitted_jobs"] = 1
    path = tmp_path / "drifted-lock.json"
    path.write_text(json.dumps(lock))

    failures = validate_runtime_lock_artifact(
        lock,
        manifest,
        runtime_lock_path=str(path),
        native_manifest_path=MANIFEST,
    )

    assert "identity_or_authority" in failures


def test_prepare_af2_input_uses_locked_native_sequences(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    context = mod.load_context(
        MANIFEST,
        RUNTIME_LOCK,
        TARGET_IDS[0],
        "af2_multimer_colabfold_v1",
    )
    context = copy.deepcopy(context)
    input_dir = tmp_path / "af2-input"
    input_manifest = tmp_path / "af2-input.json"
    context["target"]["outputs"]["af2_input_dir"] = str(input_dir)
    context["target"]["outputs"]["af2_input_manifest"] = str(
        input_manifest
    )

    payload = mod.prepare_af2_input(
        context, str(input_dir), str(input_manifest)
    )

    a3m = Path(payload["a3m_path"]).read_text()
    expected_header = (
        f"#{context['target']['target_sequence_length']},"
        f"{context['target']['binder_sequence_length']}\t1,1"
    )
    assert a3m.startswith(expected_header + "\n")
    assert payload["prediction_contract"]["random_seed"] == 0
    assert payload["prediction_contract"]["templates_used"] is False


def test_run_boltz_emits_one_strict_native_record(
    tmp_path, monkeypatch
):
    context = _synthetic_context(tmp_path, "boltz2_complex")
    output_dir = tmp_path / "boltz-output"
    record_path = tmp_path / "boltz-record.json"
    context["target"]["outputs"] = {
        "boltz_output_dir": str(output_dir),
        "boltz_record": str(record_path),
    }
    monkeypatch.setattr(
        mod, "validate_runtime_observation_file", lambda *_: {}
    )
    observed_command = []

    def fake_run(command, check):
        assert check is True
        observed_command.extend(command)
        prediction = (
            Path(command[command.index("--out_dir") + 1])
            / "boltz_results_test/predictions/w3cb2"
        )
        prediction.mkdir(parents=True)
        model = prediction / "w3cb2_model_0.pdb"
        _write_pdb(model)
        (prediction / "confidence_w3cb2_model_0.json").write_text(
            json.dumps({"complex_plddt": 0.8, "ptm": 0.7, "iptm": 0.6})
        )
        np.savez(prediction / "pae_w3cb2_model_0.npz", np.ones((8, 8)))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    record = mod.run_boltz(context, "observation.json", "/bin/boltz")

    assert observed_command[1] == "predict"
    assert "--no_kernels" in observed_command
    assert observed_command[observed_command.index("--seed") + 1] == "0"
    assert record["strict_qc_passed"] is True
    assert record["success"] is True
    assert record["predictor_id"] == "boltz2_complex"
    assert json.loads(record_path.read_text()) == record


def test_convert_af2_emits_one_strict_native_record(
    tmp_path, monkeypatch
):
    context = _synthetic_context(tmp_path, "af2_multimer_colabfold_v1")
    output_dir = tmp_path / "af2-output"
    output_dir.mkdir()
    record_path = tmp_path / "af2-record.json"
    input_manifest = tmp_path / "af2-input.json"
    context["target"]["outputs"] = {
        "af2_input_manifest": str(input_manifest),
        "af2_output_dir": str(output_dir),
        "af2_record": str(record_path),
    }
    input_manifest.write_text("{}\n")
    candidate_id = context["target"]["native_candidate_id"]
    model = output_dir / f"{candidate_id}_unrelaxed_rank_001_test.pdb"
    scores = output_dir / f"{candidate_id}_scores_rank_001_test.json"
    _write_pdb(model)
    scores.write_text(
        json.dumps({
            "pae": np.ones((8, 8)).tolist(),
            "plddt": [80.0] * 8,
            "ptm": 0.7,
            "iptm": 0.6,
        })
    )
    monkeypatch.setattr(
        mod, "validate_runtime_observation_file", lambda *_: {}
    )
    monkeypatch.setattr(mod, "_validate_af2_input_manifest", lambda *_: {})

    record = mod.convert_af2(
        context,
        "observation.json",
        str(input_manifest),
        str(output_dir),
    )

    assert record["strict_qc_passed"] is True
    assert record["success"] is True
    assert record["predictor_id"] == "af2_multimer_colabfold_v1"
    assert record["confidence_metrics"]["model_tag"] == "rank_001_test"


def test_runtime_observation_identity_drift_is_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(ROOT)
    context = mod.load_context(
        MANIFEST,
        RUNTIME_LOCK,
        TARGET_IDS[0],
        "boltz2_complex",
    )
    observation = mod.load_object(OBSERVATIONS["boltz2_complex"])
    observation["runtime_identity"]["execution_parameters"][
        "sampling_steps"
    ] = 200
    path = tmp_path / "drifted-observation.json"
    path.write_text(json.dumps(observation))

    with pytest.raises(ValueError, match="differs from the W3c-B2 lock"):
        mod.validate_runtime_observation_file(context, str(path))
