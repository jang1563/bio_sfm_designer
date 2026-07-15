"""Tests for the no-submit W3b fit-stage packet boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from bio_sfm_designer.experiments.m6d_w3b_fit_packet import (
    build_approval_packet,
    build_readiness,
)
from bio_sfm_designer.experiments.m6d_w3b_execution_lock import (
    build_execution_manifest,
    build_input_lock,
    evaluate_readiness,
)
from bio_sfm_designer.experiments.m6d_w3b_matched_records import (
    build_readiness as build_matched_readiness,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    build_readiness as build_runtime_readiness,
    canonical_sha256,
)
from bio_sfm_designer.experiments.m6d_w3b_producer_contract import sha256_file


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _ready_fixture(tmp_path: Path, monkeypatch):
    protocol = _load("configs/m6d_w3b_disagreement_gate_protocol.json")
    source = _load("configs/m6d_w3b_fresh_targets.json")
    protocol_path = tmp_path / "protocol.json"
    source_path = tmp_path / "source.json"
    lifecycle_path = tmp_path / "lifecycle.json"
    target_artifacts = []
    for target in source["targets"]:
        target_id = target["id"]
        root = tmp_path / "inputs" / target_id
        sequence = "ACDEFGHIK"
        replacements = {
            "source_pdb": root / "source.pdb",
            "prepared_pdb": root / "prepared.pdb",
            "prep_report": root / "prepared.report.json",
            "target_fasta": root / "target.fasta",
            "target_fasta_report": root / "target.fasta.report.json",
            "target_msa": root / "target.a3m",
            "target_msa_report": root / "target.a3m.report.json",
        }
        root.mkdir(parents=True)
        replacements["source_pdb"].write_text("MODEL\nEND\n")
        replacements["prepared_pdb"].write_text("MODEL\nEND\n")
        _write_json(replacements["prep_report"], {"ok": True})
        replacements["target_fasta"].write_text(f">{target_id}\n{sequence}\n")
        _write_json(replacements["target_fasta_report"], {"ok": True})
        replacements["target_msa"].write_text(f">{target_id}\n{sequence}\n")
        _write_json(replacements["target_msa_report"], {"ok": True})
        target.update({key: str(value) for key, value in replacements.items()})
        target["target_sequence_sha256"] = hashlib.sha256(sequence.encode()).hexdigest()
        target_artifacts.append({
            "target_id": target_id,
            "target_sequence_sha256": target["target_sequence_sha256"],
            "expected_target_sequence_sha256": target["target_sequence_sha256"],
            "target_msa_sha256": sha256_file(replacements["target_msa"]),
            "target_msa_report_sha256": sha256_file(replacements["target_msa_report"]),
            "target_msa_report_ok": True,
        })
    _write_json(source_path, source)
    protocol["execution_state"]["target_manifest"] = str(source_path)
    protocol["execution_state"]["target_manifest_sha256"] = sha256_file(source_path)
    _write_json(protocol_path, protocol)
    lifecycle = {
        "artifact": "m6d_w3b_target_msa_lifecycle",
        "status": "target_msa_precompute_complete_8_of_8",
        "audit_ok": True,
        "completion_ok": True,
        "jobs_terminal_success": True,
        "within_gpu_budget": True,
        "n_targets": 8,
        "n_failures": 0,
        "manifest": str(source_path),
        "manifest_sha256": sha256_file(source_path),
        "strict_manifest": {"ok": True},
        "target_artifacts": target_artifacts,
    }
    _write_json(lifecycle_path, lifecycle)
    monkeypatch.setattr(
        "bio_sfm_designer.experiments.m6d_w3b_execution_lock._OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    execution_manifest_path = tmp_path / "execution.json"
    input_lock_path = tmp_path / "input_lock.json"
    _write_json(
        execution_manifest_path,
        build_execution_manifest(str(protocol_path), str(source_path), str(lifecycle_path)),
    )
    _write_json(
        input_lock_path,
        build_input_lock(
            str(protocol_path),
            str(source_path),
            str(lifecycle_path),
            str(execution_manifest_path),
        ),
    )
    execution_readiness_path = tmp_path / "execution_readiness.json"
    _write_json(
        execution_readiness_path,
        evaluate_readiness(str(protocol_path), str(source_path), str(lifecycle_path)),
    )
    runtime_lock = _load("configs/m6d_w3b_runtime_lock.json")
    runtime_lock["protocol"] = str(protocol_path)
    runtime_lock["protocol_sha256"] = sha256_file(protocol_path)
    runtime_lock["locked_scientific_digest"] = canonical_sha256(protocol["locked_scientific_protocol"])
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
    runtime_readiness_path = tmp_path / "runtime_readiness.json"
    _write_json(
        runtime_readiness_path,
        build_runtime_readiness(str(runtime_lock_path), str(execution_readiness_path)),
    )
    matched_readiness_path = tmp_path / "matched_readiness.json"
    _write_json(
        matched_readiness_path,
        build_matched_readiness(
            str(protocol_path),
            str(execution_readiness_path),
            str(runtime_readiness_path),
        ),
    )
    return {
        "protocol": protocol_path,
        "execution_manifest": execution_manifest_path,
        "input_lock": input_lock_path,
        "runtime_lock": runtime_lock_path,
        "execution_readiness": execution_readiness_path,
        "runtime_readiness": runtime_readiness_path,
        "matched_readiness": matched_readiness_path,
    }


def _current():
    return build_readiness(
        "configs/m6d_w3b_disagreement_gate_protocol.json",
        "results/m6d_w3b_execution_lock_readiness.json",
        "results/m6d_w3b_runtime_lock_readiness.json",
        "results/m6d_w3b_matched_record_contract.json",
        "configs/m6d_w3b_runtime_lock.json",
        "configs/m6d_w3b_execution_targets.json",
        "configs/m6d_w3b_execution_input_lock.json",
    )


def test_current_packet_is_clean_and_ready_for_explicit_fit_approval(monkeypatch):
    monkeypatch.chdir(ROOT)
    report = _current()

    assert report["audit_ok"] is True
    assert report["fit_packet_ready"] is True
    assert report["execution_lock_ready"] is True
    assert report["runtime_identity_ready"] is True
    assert report["can_submit_fit_stage"] is False
    assert report["submitted_jobs"] == 0
    assert report["status"] == "w3b_fit_packet_ready_awaiting_explicit_approval"
    assert report["approval_contract"]["candidate_designs"] == 180
    assert report["approval_contract"]["matched_predictor_evaluations"] == 360
    assert report["approval_contract"]["authorizes_certification"] is False
    assert report["approval_contract"]["authorizes_held_out_test"] is False
    assert len(report["bound_artifacts"]) >= 17


def test_current_readiness_emits_no_submit_approval_packet(monkeypatch):
    monkeypatch.chdir(ROOT)
    packet = build_approval_packet(_current())

    assert packet["status"] == "w3b_fit_approval_packet_ready_no_submit"
    assert packet["audit_ok"] is True
    assert packet["approval_recorded"] is False
    assert packet["submitted_jobs"] == 0


def test_approval_packet_preserves_exact_fit_scope(monkeypatch):
    monkeypatch.chdir(ROOT)
    readiness = _current()
    readiness = copy.deepcopy(readiness)
    readiness.update({
        "status": "w3b_fit_packet_ready_awaiting_explicit_approval",
        "audit_ok": True,
        "fit_packet_ready": True,
        "execution_lock_ready": True,
        "matched_record_contract_ready": True,
        "n_failures": 0,
        "failures": [],
        "fit_targets": [
            {"target_id": target_id, "records_planned": 60}
            for target_id in ("FIT_A", "FIT_B", "FIT_C")
        ],
    })

    packet = build_approval_packet(readiness)

    assert packet["status"] == "w3b_fit_approval_packet_ready_no_submit"
    assert packet["approval_recorded"] is False
    assert packet["submitted_jobs"] == 0
    assert packet["approval_contract"]["environment_value"] == "approve-w3b-fit-180-matched-h100"
    assert packet["approval_contract"]["candidate_designs"] == 180
    assert packet["approval_contract"]["matched_predictor_evaluations"] == 360


def test_complete_locks_emit_packet_and_bridge_dry_run_without_submit(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    paths = _ready_fixture(tmp_path, monkeypatch)
    readiness = build_readiness(
        str(paths["protocol"]),
        str(paths["execution_readiness"]),
        str(paths["runtime_readiness"]),
        str(paths["matched_readiness"]),
        str(paths["runtime_lock"]),
        str(paths["execution_manifest"]),
        str(paths["input_lock"]),
    )
    packet = build_approval_packet(readiness)
    packet_path = tmp_path / "fit_approval.json"
    _write_json(packet_path, packet)
    receipt = tmp_path / "receipt.jsonl"
    summary = tmp_path / "summary.json"
    environment = os.environ.copy()
    environment.update({
        "BIO_SFM_REPO_ROOT": str(ROOT),
        "BIO_SFM_PYTHON": sys.executable,
        "BIO_SFM_SUBMIT_DRY_RUN": "1",
        "W3B_FIT_APPROVAL_PACKET": str(packet_path),
        "W3B_FIT_RECEIPT": str(receipt),
        "W3B_FIT_SUMMARY": str(summary),
        "PROTOCOL": str(paths["protocol"]),
        "EXECUTION_MANIFEST": str(paths["execution_manifest"]),
        "INPUT_LOCK": str(paths["input_lock"]),
        "RUNTIME_LOCK": str(paths["runtime_lock"]),
        "EXECUTION_READINESS": str(paths["execution_readiness"]),
        "RUNTIME_READINESS": str(paths["runtime_readiness"]),
        "MATCHED_READINESS": str(paths["matched_readiness"]),
    })

    result = subprocess.run(
        ["bash", "hpc/m6d_w3b_fit_submit_with_receipt.sh"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert readiness["status"] == "w3b_fit_packet_ready_awaiting_explicit_approval"
    assert readiness["fit_packet_ready"] is True
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("60 ProteinMPNN -> matched H100 Boltz + AF2") == 3
    assert "180 candidates, 360 predictor evaluations, zero scheduler jobs" in result.stdout
    assert not receipt.exists()
    assert not summary.exists()
