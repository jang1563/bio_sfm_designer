"""Tests for the lifecycle-derived W3b execution manifest and input lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3b_execution_lock import (
    build_execution_manifest,
    build_input_lock,
    deterministic_seed,
    evaluate_readiness,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, sort_keys=True) + "\n")
    else:
        path.write_text(str(value))


def _completed_fixture(tmp_path: Path):
    protocol = _load("configs/m6d_w3b_disagreement_gate_protocol.json")
    source = _load("configs/m6d_w3b_fresh_targets.json")
    protocol_path = tmp_path / "protocol.json"
    source_path = tmp_path / "source.json"
    lifecycle_path = tmp_path / "lifecycle.json"
    target_artifacts = []
    for target in source["targets"]:
        target_id = target["id"]
        target_root = tmp_path / "inputs" / target_id
        replacements = {
            "source_pdb": target_root / "source.pdb",
            "prepared_pdb": target_root / "prepared.pdb",
            "prep_report": target_root / "prepared.report.json",
            "target_fasta": target_root / "target.fasta",
            "target_fasta_report": target_root / "target.fasta.report.json",
            "target_msa": target_root / "target.a3m",
            "target_msa_report": target_root / "target.a3m.report.json",
        }
        sequence = "ACDEFGHIK"
        _write(replacements["source_pdb"], "MODEL\nEND\n")
        _write(replacements["prepared_pdb"], "MODEL\nEND\n")
        _write(replacements["prep_report"], {"ok": True})
        _write(replacements["target_fasta"], f">{target_id}\n{sequence}\n")
        _write(replacements["target_fasta_report"], {"ok": True})
        _write(replacements["target_msa"], f">{target_id}\n{sequence}\n")
        _write(replacements["target_msa_report"], {"ok": True})
        target.update({key: str(value) for key, value in replacements.items()})
        target["target_sequence_sha256"] = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        target_artifacts.append({
            "target_id": target_id,
            "target_sequence_sha256": target["target_sequence_sha256"],
            "expected_target_sequence_sha256": target["target_sequence_sha256"],
            "target_msa_sha256": _sha(replacements["target_msa"]),
            "target_msa_report_sha256": _sha(replacements["target_msa_report"]),
            "target_msa_report_ok": True,
        })
    _write(source_path, source)
    protocol["execution_state"]["target_manifest"] = str(source_path)
    protocol["execution_state"]["target_manifest_sha256"] = _sha(source_path)
    _write(protocol_path, protocol)
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
        "manifest_sha256": _sha(source_path),
        "strict_manifest": {"ok": True},
        "target_artifacts": target_artifacts,
    }
    _write(lifecycle_path, lifecycle)
    return protocol_path, source_path, lifecycle_path


def test_current_repo_is_coherent_and_execution_lock_ready(monkeypatch):
    monkeypatch.chdir(ROOT)
    report = evaluate_readiness(
        "configs/m6d_w3b_disagreement_gate_protocol.json",
        "configs/m6d_w3b_fresh_targets.json",
        "results/m6d_w3b_target_msa_lifecycle.json",
    )

    assert report["audit_ok"] is True
    assert report["execution_lock_ready"] is True
    assert report["status"] == "w3b_execution_lock_ready_for_manifest_materialization"
    assert report["failures"] == []


def test_completed_lifecycle_builds_frozen_870_design_manifest(tmp_path):
    protocol_path, source_path, lifecycle_path = _completed_fixture(tmp_path)
    report = evaluate_readiness(str(protocol_path), str(source_path), str(lifecycle_path))
    manifest = build_execution_manifest(str(protocol_path), str(source_path), str(lifecycle_path))

    assert report["audit_ok"] is True
    assert report["execution_lock_ready"] is True
    assert manifest["total_candidate_designs"] == 870
    assert manifest["total_matched_predictor_evaluations"] == 1740
    assert manifest["role_counts"] == {"fit": 3, "certification": 3, "held_out_test": 2}
    assert [row["num_seq"] for row in manifest["targets"]] == [60, 60, 60, 150, 150, 150, 120, 120]
    assert len({row["out_prefix"] for row in manifest["targets"]}) == 8
    for target in manifest["targets"]:
        assert len(target["target_msa_sha256"]) == 64
        assert target["proteinmpnn_seed"] == deterministic_seed(target["w3b_seed_namespace"], target["id"])
        assert target["id_prefix"].startswith(target["w3b_seed_namespace"])


def test_execution_input_lock_is_deterministic_and_no_submit(tmp_path):
    protocol_path, source_path, lifecycle_path = _completed_fixture(tmp_path)
    manifest_path = tmp_path / "execution.json"
    _write(manifest_path, build_execution_manifest(str(protocol_path), str(source_path), str(lifecycle_path)))
    first = build_input_lock(str(protocol_path), str(source_path), str(lifecycle_path), str(manifest_path))
    second = build_input_lock(str(protocol_path), str(source_path), str(lifecycle_path), str(manifest_path))

    assert first["audit_ok"] is True
    assert first["status"] == "w3b_execution_input_locked_no_submit"
    assert first["no_submit"] is True
    assert first["can_generate_candidates_or_run_predictors"] is False
    assert first["n_targets"] == 8
    assert first["n_artifacts"] == 56
    assert first["lock_digest_sha256"] == second["lock_digest_sha256"]


def test_stale_lifecycle_msa_hash_blocks_materialization(tmp_path):
    protocol_path, source_path, lifecycle_path = _completed_fixture(tmp_path)
    lifecycle = json.loads(lifecycle_path.read_text())
    lifecycle["target_artifacts"][0]["target_msa_sha256"] = "f" * 64
    _write(lifecycle_path, lifecycle)
    report = evaluate_readiness(str(protocol_path), str(source_path), str(lifecycle_path))

    assert report["execution_lock_ready"] is False
    assert "target_msa_file_hash_mismatch" in {row["kind"] for row in report["failures"]}
    with pytest.raises(ValueError, match="not ready"):
        build_execution_manifest(str(protocol_path), str(source_path), str(lifecycle_path))


def test_tampered_execution_manifest_blocks_input_lock(tmp_path):
    protocol_path, source_path, lifecycle_path = _completed_fixture(tmp_path)
    manifest = build_execution_manifest(str(protocol_path), str(source_path), str(lifecycle_path))
    manifest["targets"][0]["num_seq"] = 61
    manifest_path = tmp_path / "execution.json"
    _write(manifest_path, manifest)
    report = build_input_lock(str(protocol_path), str(source_path), str(lifecycle_path), str(manifest_path))

    assert report["audit_ok"] is False
    assert "execution_manifest_content_mismatch" in {row["kind"] for row in report["failures"]}
