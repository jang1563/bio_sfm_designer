"""Tests for strict W3b matched-predictor record assembly."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3b_disagreement_gate import evaluate
from bio_sfm_designer.experiments.m6d_w3b_matched_records import (
    assemble_stage,
    build_readiness,
    build_runtime_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
PREDICTORS = ("boltz2_complex", "af2_multimer_colabfold_v1")
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def _canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _runtime(predictor_id: str):
    lock = _load("configs/m6d_w3b_runtime_lock.json")
    return lock["predictor_runtime_identities"][predictor_id]


def _fixture(tmp_path: Path):
    protocol = _load("configs/m6d_w3b_disagreement_gate_protocol.json")
    protocol_path = tmp_path / "protocol.json"
    manifest_path = tmp_path / "execution.json"
    lock_path = tmp_path / "lock.json"
    runtime_lock_path = tmp_path / "runtime_lock.json"
    _write_json(protocol_path, protocol)
    scientific_digest = _canonical_sha(protocol["locked_scientific_protocol"])
    runtime_lock = _load("configs/m6d_w3b_runtime_lock.json")
    runtime_lock["protocol"] = str(protocol_path)
    runtime_lock["protocol_sha256"] = _sha(protocol_path)
    runtime_lock["locked_scientific_digest"] = scientific_digest
    runtime_lock["source_bindings"]["protocol"] = {
        "path": str(protocol_path),
        "sha256": _sha(protocol_path),
    }
    runtime_lock["runtime_lock_digest_sha256"] = _canonical_sha({
        "protocol_sha256": _sha(protocol_path),
        "locked_scientific_digest": scientific_digest,
        "predictor_runtime_identities": runtime_lock["predictor_runtime_identities"],
        "predictor_runtime_identity_sha256": runtime_lock["predictor_runtime_identity_sha256"],
        "source_sha256": {
            key: value["sha256"]
            for key, value in runtime_lock["source_bindings"].items()
        },
    })
    _write_json(runtime_lock_path, runtime_lock)
    targets = []
    lock_targets = []
    for index, target_id in enumerate(("FIT_A", "FIT_B", "FIT_C")):
        out_prefix = tmp_path / "outputs" / target_id
        target_sequence = "ACDEFGHIK"
        target_msa = tmp_path / "inputs" / target_id / "target.a3m"
        target_msa.parent.mkdir(parents=True, exist_ok=True)
        target_msa.write_text(f">{target_id}\n{target_sequence}\n")
        target = {
            "id": target_id,
            "experimental_role": "fit",
            "w3b_seed_namespace": "w3b-fit-v1",
            "id_prefix": f"w3b-fit-v1-{target_id}",
            "num_seq": 60,
            "target_sequence_sha256": hashlib.sha256(target_sequence.encode()).hexdigest(),
            "target_msa": str(target_msa),
            "target_msa_sha256": _sha(target_msa),
            "out_prefix": str(out_prefix),
            "candidates": str(out_prefix / "candidates_proteinmpnn_complex.jsonl"),
            "boltz_records": str(out_prefix / "records_boltz_complex.jsonl"),
            "af2_records": str(out_prefix / "records_af2_multimer.jsonl"),
            "matched_records": str(out_prefix / "records_w3b_matched.jsonl"),
        }
        candidates = []
        raw = {predictor_id: [] for predictor_id in PREDICTORS}
        for row_index in range(60):
            candidate_id = f"{target['id_prefix']}-{row_index:03d}"
            binder = "MNPQ" + ALPHABET[row_index // 20] + ALPHABET[row_index % 20] + "RST"
            candidate_hash = hashlib.sha256(binder.encode()).hexdigest()
            candidates.append({
                "id": candidate_id,
                "regime": "complex",
                "representation": binder,
                "target_seq": target_sequence,
                "meta": {"complex_target_id": target_id},
            })
            for predictor_index, predictor_id in enumerate(PREDICTORS):
                runtime = _runtime(predictor_id)
                success = row_index < 50
                pae = 2.0 + 0.2 * predictor_index + row_index / 1000.0
                lrmsd = (2.0 if success else 8.0) + 0.1 * predictor_index
                signal, label_source = {
                    "boltz2_complex": ("boltz2_pae_interaction", "boltz2_lrmsd_to_reference"),
                    "af2_multimer_colabfold_v1": (
                        "af2_multimer_pae_interaction",
                        "af2_multimer_lrmsd_to_reference",
                    ),
                }[predictor_id]
                raw[predictor_id].append({
                    "target_id": candidate_id,
                    "complex_target_id": target_id,
                    "predictor_id": predictor_id,
                    "regime": "complex",
                    "signal_source": signal,
                    "label_source": label_source,
                    "interface_aligned": True,
                    "pae_interaction": pae,
                    "lrmsd": lrmsd,
                    "lrmsd_threshold": 4.0,
                    "truth": {"correct": success},
                    "provenance": {
                        "candidate_sequence_sha256": candidate_hash,
                        "target_sequence_sha256": target["target_sequence_sha256"],
                        "target_msa_sha256": target["target_msa_sha256"],
                        "runtime_identity_sha256": _canonical_sha(runtime),
                        "model_output_sha256": f"{row_index + 1 + predictor_index:064x}",
                        "seed": 0,
                        "templates_used": False,
                        "prediction_time_network_used": False,
                    },
                })
        candidate_path = Path(target["candidates"])
        _write_jsonl(candidate_path, candidates)
        for predictor_id in PREDICTORS:
            record_path = Path(target[{"boltz2_complex": "boltz_records", "af2_multimer_colabfold_v1": "af2_records"}[predictor_id]])
            _write_jsonl(record_path, raw[predictor_id])
            runtime = _runtime(predictor_id)
            receipt_path = out_prefix / {
                "boltz2_complex": "boltz2_runtime_receipt.json",
                "af2_multimer_colabfold_v1": "af2_multimer_runtime_receipt.json",
            }[predictor_id]
            _write_json(receipt_path, {
                "artifact": "m6d_w3b_predictor_runtime_receipt",
                "status": "w3b_predictor_records_complete",
                "audit_ok": True,
                "no_submit": True,
                "predictor_id": predictor_id,
                "target_id": target_id,
                "experimental_role": "fit",
                "seed_namespace": "w3b-fit-v1",
                "seed": 0,
                "templates_used": False,
                "prediction_time_network_used": False,
                "candidates": str(candidate_path),
                "candidates_sha256": _sha(candidate_path),
                "target_msa": str(target_msa),
                "target_msa_sha256": target["target_msa_sha256"],
                "records": str(record_path),
                "records_sha256": _sha(record_path),
                "n_records": 60,
                "runtime_lock": str(runtime_lock_path),
                "runtime_lock_sha256": _sha(runtime_lock_path),
                "runtime_lock_digest_sha256": runtime_lock["runtime_lock_digest_sha256"],
                "runtime_identity": runtime,
                "runtime_identity_sha256": _canonical_sha(runtime),
            })
        targets.append(target)
        lock_targets.append({
            "target_id": target_id,
            "target_msa_sha256": target["target_msa_sha256"],
            "artifacts": {
                "target_msa": {
                    "path": str(target_msa),
                    "bytes": target_msa.stat().st_size,
                    "sha256": target["target_msa_sha256"],
                },
            },
            "outputs": {
                key: target[key]
                for key in ("out_prefix", "candidates", "boltz_records", "af2_records", "matched_records")
            },
        })
    manifest = {
        "artifact": "m6d_w3b_execution_target_manifest",
        "status": "w3b_execution_inputs_locked_no_submit",
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "protocol_sha256": _sha(protocol_path),
        "locked_scientific_digest": scientific_digest,
        "targets": targets,
    }
    _write_json(manifest_path, manifest)
    lock = {
        "artifact": "m6d_w3b_execution_input_lock",
        "status": "w3b_execution_input_locked_no_submit",
        "audit_ok": True,
        "no_submit": True,
        "can_generate_candidates_or_run_predictors": False,
        "binding": {
            "protocol_file_sha256": _sha(protocol_path),
            "execution_manifest_sha256": _sha(manifest_path),
            "locked_scientific_digest": scientific_digest,
            "targets": lock_targets,
        },
    }
    _write_json(lock_path, lock)
    return protocol_path, manifest_path, lock_path, runtime_lock_path


def test_current_matched_record_contract_is_stage_input_ready():
    report = build_readiness(
        str(ROOT / "configs/m6d_w3b_disagreement_gate_protocol.json"),
        str(ROOT / "results/m6d_w3b_execution_lock_readiness.json"),
    )

    assert report["audit_ok"] is True
    assert report["assembly_ready"] is True
    assert report["status"] == "w3b_matched_record_contract_ready_for_stage_inputs"
    assert report["required_runtime_receipt"]["seed"] == 0


def test_matched_readiness_rejects_stale_runtime_lock_binding(tmp_path):
    runtime_readiness = _load("results/m6d_w3b_runtime_lock_readiness.json")
    runtime_readiness["runtime_lock_sha256"] = "f" * 64
    runtime_readiness_path = tmp_path / "runtime_readiness.json"
    _write_json(runtime_readiness_path, runtime_readiness)

    report = build_readiness(
        str(ROOT / "configs/m6d_w3b_disagreement_gate_protocol.json"),
        str(ROOT / "results/m6d_w3b_execution_lock_readiness.json"),
        str(runtime_readiness_path),
    )

    assert report["audit_ok"] is False
    assert "runtime_lock_readiness_binding_stale_or_invalid" in {
        row["kind"] for row in report["failures"]
    }


def test_full_fit_assembly_is_evaluator_ready(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is True
    assert report["n_matched_records"] == 180
    assert report["numeric_copy_fraction"] == 0.0
    evaluated = evaluate(_load("configs/m6d_w3b_disagreement_gate_protocol.json"), json.loads(manifest_path.read_text()), records)
    assert evaluated["audit_ok"] is True
    assert evaluated["status"] == "w3b_fit_rules_frozen_awaiting_certification"


def test_duplicate_candidate_sequence_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    target = manifest["targets"][0]
    candidates_path = Path(target["candidates"])
    candidates = [json.loads(line) for line in candidates_path.read_text().splitlines()]
    candidates[1]["representation"] = candidates[0]["representation"]
    duplicate_hash = hashlib.sha256(candidates[0]["representation"].encode()).hexdigest()
    _write_jsonl(candidates_path, candidates)

    for filename, field in (
        ("boltz2_runtime_receipt.json", "boltz_records"),
        ("af2_multimer_runtime_receipt.json", "af2_records"),
    ):
        records_path = Path(target[field])
        records = [json.loads(line) for line in records_path.read_text().splitlines()]
        records[1]["provenance"]["candidate_sequence_sha256"] = duplicate_hash
        _write_jsonl(records_path, records)
        receipt_path = Path(target["out_prefix"]) / filename
        receipt = json.loads(receipt_path.read_text())
        receipt["candidates_sha256"] = _sha(candidates_path)
        receipt["records_sha256"] = _sha(records_path)
        _write_json(receipt_path, receipt)

    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "candidate_sequence_invalid_or_duplicate" in {
        row["kind"] for row in report["failures"]
    }


def test_runtime_receipt_builder_binds_exact_target_files(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    target = manifest["targets"][0]
    receipt = build_runtime_receipt(
        str(protocol_path),
        str(manifest_path),
        str(lock_path),
        str(runtime_lock_path),
        "boltz2_complex",
        target["id"],
        _runtime("boltz2_complex"),
    )

    assert receipt["audit_ok"] is True
    assert receipt["seed"] == 0
    assert receipt["n_records"] == 60
    assert receipt["candidates_sha256"] == _sha(Path(target["candidates"]))
    assert receipt["target_msa_sha256"] == target["target_msa_sha256"]
    assert receipt["records_sha256"] == _sha(Path(target["boltz_records"]))


def test_runtime_receipt_builder_rejects_observed_runtime_drift(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    observed = copy.deepcopy(_runtime("boltz2_complex"))
    observed["boltz_version"] = "2.2.2"

    with pytest.raises(ValueError, match="differs from the frozen"):
        build_runtime_receipt(
            str(protocol_path),
            str(manifest_path),
            str(lock_path),
            str(runtime_lock_path),
            "boltz2_complex",
            manifest["targets"][0]["id"],
            observed,
        )


def test_self_consistent_wrong_receipt_runtime_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    receipt_path = Path(manifest["targets"][0]["out_prefix"]) / "boltz2_runtime_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["runtime_identity"]["execution_parameters"]["sampling_steps"] = 200
    receipt["runtime_identity_sha256"] = _canonical_sha(receipt["runtime_identity"])
    _write_json(receipt_path, receipt)

    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "predictor_runtime_receipt_invalid" in {row["kind"] for row in report["failures"]}


def test_same_wrong_msa_in_both_predictors_fails(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    target = manifest["targets"][0]
    for field in ("boltz_records", "af2_records"):
        path = Path(target[field])
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["provenance"]["target_msa_sha256"] = "f" * 64
        _write_jsonl(path, rows)
    for filename, field in (("boltz2_runtime_receipt.json", "boltz_records"), ("af2_multimer_runtime_receipt.json", "af2_records")):
        receipt_path = Path(target["out_prefix"]) / filename
        receipt = json.loads(receipt_path.read_text())
        receipt["records_sha256"] = _sha(Path(target[field]))
        _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    lock = json.loads(lock_path.read_text())
    lock["binding"]["execution_manifest_sha256"] = _sha(manifest_path)
    _write_json(lock_path, lock)
    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "predictor_record_contract_invalid" in {row["kind"] for row in report["failures"]}


def test_missing_af2_output_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    af2_path = Path(manifest["targets"][1]["af2_records"])
    af2_path.unlink()
    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "target_input_file_missing" in {row["kind"] for row in report["failures"]}


def test_unseeded_runtime_receipt_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    receipt_path = Path(manifest["targets"][2]["out_prefix"]) / "boltz2_runtime_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["seed"] = None
    _write_json(receipt_path, receipt)
    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "predictor_runtime_receipt_invalid" in {row["kind"] for row in report["failures"]}


def test_target_msa_drift_after_lock_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    Path(manifest["targets"][0]["target_msa"]).write_text(">drift\nCCCCCCCCC\n")
    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "target_msa_file_hash_mismatch" in {row["kind"] for row in report["failures"]}


def test_numeric_copy_across_predictors_fails_closed(tmp_path):
    protocol_path, manifest_path, lock_path, runtime_lock_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    for target in manifest["targets"]:
        boltz_rows = [json.loads(line) for line in Path(target["boltz_records"]).read_text().splitlines()]
        af2_path = Path(target["af2_records"])
        af2_rows = [json.loads(line) for line in af2_path.read_text().splitlines()]
        for boltz, af2 in zip(boltz_rows, af2_rows):
            af2["pae_interaction"] = boltz["pae_interaction"]
            af2["lrmsd"] = boltz["lrmsd"]
        _write_jsonl(af2_path, af2_rows)
        receipt_path = Path(target["out_prefix"]) / "af2_multimer_runtime_receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["records_sha256"] = _sha(af2_path)
        _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    lock = json.loads(lock_path.read_text())
    lock["binding"]["execution_manifest_sha256"] = _sha(manifest_path)
    _write_json(lock_path, lock)
    _records, report = assemble_stage(
        str(protocol_path), str(manifest_path), str(lock_path), str(runtime_lock_path), "fit"
    )

    assert report["audit_ok"] is False
    assert "predictor_numeric_copy_suspected" in {row["kind"] for row in report["failures"]}
