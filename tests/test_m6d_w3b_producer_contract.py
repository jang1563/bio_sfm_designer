"""Tests for the W3b-only producer context and AF2 input materialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_target_context,
    prepare_af2_inputs,
    sha256_file,
    validate_candidates,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _binder(index: int) -> str:
    return "MNPQ" + ALPHABET[index // 20] + ALPHABET[index % 20] + "RST"


def _fixture(tmp_path: Path):
    protocol = _load("configs/m6d_w3b_disagreement_gate_protocol.json")
    protocol_path = tmp_path / "protocol.json"
    _write_json(protocol_path, protocol)
    target_id = "FIT_A"
    target_sequence = "ACDEFGHIK"
    prepared_pdb = tmp_path / "inputs" / target_id / "prepared.pdb"
    target_msa = tmp_path / "inputs" / target_id / "target.a3m"
    prepared_pdb.parent.mkdir(parents=True)
    prepared_pdb.write_text("MODEL\nEND\n")
    target_msa.write_text(f">{target_id}\n{target_sequence}\n>hit\nAC-EFGHIK\n")
    out_prefix = tmp_path / "outputs" / target_id
    target = {
        "id": target_id,
        "experimental_role": "fit",
        "w3b_stage": "fit",
        "w3b_seed_namespace": "w3b-fit-v1",
        "proteinmpnn_seed": 123,
        "id_prefix": f"w3b-fit-v1-{target_id}",
        "num_seq": 60,
        "target_sequence_sha256": hashlib.sha256(target_sequence.encode()).hexdigest(),
        "target_msa": str(target_msa),
        "target_msa_sha256": sha256_file(target_msa),
        "prepared_pdb": str(prepared_pdb),
        "target_chain": "A",
        "binder_chain": "B",
        "out_prefix": str(out_prefix),
        "candidates": str(out_prefix / "candidates_proteinmpnn_complex.jsonl"),
        "boltz_records": str(out_prefix / "records_boltz_complex.jsonl"),
        "af2_records": str(out_prefix / "records_af2_multimer.jsonl"),
        "matched_records": str(out_prefix / "records_w3b_matched.jsonl"),
    }
    manifest = {
        "artifact": "m6d_w3b_execution_target_manifest",
        "status": "w3b_execution_inputs_locked_no_submit",
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "protocol_sha256": sha256_file(protocol_path),
        "locked_scientific_digest": canonical_sha256(protocol["locked_scientific_protocol"]),
        "targets": [target],
    }
    manifest_path = tmp_path / "execution.json"
    _write_json(manifest_path, manifest)
    outputs = {
        key: target[key]
        for key in ("out_prefix", "candidates", "boltz_records", "af2_records", "matched_records")
    }
    lock = {
        "artifact": "m6d_w3b_execution_input_lock",
        "status": "w3b_execution_input_locked_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "can_generate_candidates_or_run_predictors": False,
        "binding": {
            "protocol_file_sha256": sha256_file(protocol_path),
            "execution_manifest_sha256": sha256_file(manifest_path),
            "locked_scientific_digest": manifest["locked_scientific_digest"],
            "targets": [{
                "target_id": target_id,
                "experimental_role": "fit",
                "seed_namespace": "w3b-fit-v1",
                "records_planned": 60,
                "id_prefix": target["id_prefix"],
                "target_msa_sha256": target["target_msa_sha256"],
                "outputs": outputs,
                "artifacts": {
                    "prepared_pdb": {
                        "path": str(prepared_pdb),
                        "bytes": prepared_pdb.stat().st_size,
                        "sha256": sha256_file(prepared_pdb),
                    },
                    "target_msa": {
                        "path": str(target_msa),
                        "bytes": target_msa.stat().st_size,
                        "sha256": sha256_file(target_msa),
                    },
                },
            }],
        },
    }
    lock_path = tmp_path / "input_lock.json"
    _write_json(lock_path, lock)
    runtime_lock = _load("configs/m6d_w3b_runtime_lock.json")
    runtime_lock["protocol"] = str(protocol_path)
    runtime_lock["protocol_sha256"] = sha256_file(protocol_path)
    runtime_lock["locked_scientific_digest"] = manifest["locked_scientific_digest"]
    runtime_lock["source_bindings"]["protocol"] = {
        "path": str(protocol_path),
        "sha256": sha256_file(protocol_path),
    }
    runtime_lock["runtime_lock_digest_sha256"] = canonical_sha256({
        "protocol_sha256": runtime_lock["protocol_sha256"],
        "locked_scientific_digest": runtime_lock["locked_scientific_digest"],
        "predictor_runtime_identities": runtime_lock["predictor_runtime_identities"],
        "predictor_runtime_identity_sha256": runtime_lock["predictor_runtime_identity_sha256"],
        "source_sha256": {
            key: value["sha256"]
            for key, value in runtime_lock["source_bindings"].items()
        },
    })
    runtime_lock_path = tmp_path / "runtime_lock.json"
    _write_json(runtime_lock_path, runtime_lock)
    candidates = [{
        "id": f"{target['id_prefix']}-{index}",
        "representation": _binder(index),
        "target_seq": target_sequence,
        "regime": "complex",
        "parent_id": None,
        "meta": {
            "complex_target_id": target_id,
            "id_prefix": target["id_prefix"],
            "target_chain": "A",
            "design_chain": "B",
        },
    } for index in range(60)]
    candidates_path = Path(target["candidates"])
    _write_jsonl(candidates_path, candidates)
    return (
        protocol_path,
        manifest_path,
        lock_path,
        runtime_lock_path,
        target,
        candidates_path,
        candidates,
    )


def _context(fixture):
    protocol, manifest, lock, runtime, target, _, _ = fixture
    return load_target_context(
        str(protocol), str(manifest), str(lock), str(runtime), target["id"], "fit"
    )


def test_locked_context_and_unique_candidates_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    fixture = _fixture(tmp_path)
    context = _context(fixture)
    rows = validate_candidates(context, str(fixture[5]))

    assert context["expected_count"] == 60
    assert len(rows) == 60
    assert len({row["representation"] for row in rows}) == 60


def test_duplicate_candidate_sequence_fails_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    fixture = _fixture(tmp_path)
    fixture[6][1]["representation"] = fixture[6][0]["representation"]
    _write_jsonl(fixture[5], fixture[6])

    with pytest.raises(ValueError, match="duplicate_candidate_sequence"):
        validate_candidates(_context(fixture), str(fixture[5]))


def test_tampered_target_msa_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    fixture = _fixture(tmp_path)
    Path(fixture[4]["target_msa"]).write_text(">FIT_A\nAAAAAAAAA\n")

    with pytest.raises(ValueError, match="execution_target_artifact_invalid"):
        _context(fixture)


def test_af2_inputs_are_matched_and_atomic(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    fixture = _fixture(tmp_path)
    input_dir = tmp_path / "af2_inputs"
    manifest_path = tmp_path / "af2_inputs.json"
    payload = prepare_af2_inputs(
        _context(fixture),
        str(fixture[5]),
        str(input_dir),
        str(manifest_path),
    )

    assert payload["n_candidates"] == 60
    assert len(list(input_dir.glob("*.a3m"))) == 60
    first = Path(payload["rows"][0]["a3m_path"]).read_text().splitlines()
    assert first[:3] == ["#9,9\t1,1", ">101\t102", "ACDEFGHIKMNPQAARST"]
    assert payload["prediction_contract"]["prediction_time_network_used"] is False
    assert manifest_path.is_file()
