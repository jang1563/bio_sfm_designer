"""Tests for the separately approved W3b fit AF2 path recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery import (
    append_recovery_event,
    build_recovery_packet,
    build_recovery_summary,
    verify_recovery_target,
)
from bio_sfm_designer.experiments.m6d_w3b_producer_contract import sha256_file


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _observation(tmp_path: Path) -> Path:
    reports = []
    for index, target_id in enumerate(("FIT_A", "FIT_B", "FIT_C"), 1):
        root = tmp_path / target_id
        input_dir = root / "af2_inputs"
        output = root / "af2_predictions"
        input_dir.mkdir(parents=True)
        output.mkdir(parents=True)
        candidates = root / "candidates.jsonl"
        manifest = root / "af2_input_manifest.json"
        identity = root / "af2_observed_runtime_identity.json"
        candidate_rows = []
        manifest_rows = []
        aggregate = []
        for candidate_index in range(60):
            candidate_id = f"{target_id}-{candidate_index:03d}"
            candidate_rows.append({"id": candidate_id})
            a3m_path = input_dir / f"{candidate_id}.a3m"
            a3m_path.write_text(f">{candidate_id}\nACDEFGHIK\n")
            a3m_sha256 = sha256_file(a3m_path)
            manifest_rows.append({
                "candidate_id": candidate_id,
                "a3m_path": str(a3m_path),
                "a3m_sha256": a3m_sha256,
            })
            aggregate.append({"candidate_id": candidate_id, "sha256": a3m_sha256})
        candidates.write_text("".join(json.dumps(row) + "\n" for row in candidate_rows))
        _write_json(manifest, {
            "artifact": "manifest",
            "input_dir": str(input_dir),
            "rows": manifest_rows,
        })
        _write_json(identity, {"predictor_id": "af2_multimer_colabfold_v1"})
        reports.append({
            "target_id": target_id,
            "failed_af2": {"job_id": str(100 + index)},
            "partial_state": {
                "target_id": target_id,
                "candidates": {
                    "path": str(candidates),
                    "sha256": sha256_file(candidates),
                },
                "af2_input_manifest": {
                    "path": str(manifest),
                    "sha256": sha256_file(manifest),
                },
                "af2_runtime_identity": {
                    "path": str(identity),
                    "sha256": sha256_file(identity),
                },
                "af2_input_count": 60,
                "af2_input_digest_sha256": hashlib.sha256(
                    json.dumps(
                        aggregate, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest(),
                "af2_output_dir": str(output),
                "af2_records": str(root / "records_af2.jsonl"),
                "af2_runtime_receipt": str(root / "runtime_receipt.json"),
                "terminal_af2_outputs_absent": True,
            },
        })
    observation = {
        "artifact": "m6d_w3b_fit_initial_execution_observation",
        "version": 1,
        "status": "w3b_fit_af2_path_failure_recovery_eligible_no_submit",
        "audit_ok": True,
        "n_targets": 3,
        "n_af2_failed_before_prediction": 3,
        "initial_failed_af2_gpu_seconds": 38,
        "target_reports": reports,
        "recovery_submission_performed": False,
        "no_submit": True,
    }
    path = tmp_path / "observation.json"
    _write_json(path, observation)
    return path


def test_recovery_packet_is_separate_scope_and_stays_under_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    observation = _observation(tmp_path)

    packet = build_recovery_packet(str(observation))
    contract = packet["approval_contract"]

    assert packet["status"] == "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval"
    assert packet["approval_recorded"] is False
    assert packet["submitted_jobs"] == 0
    assert packet["no_submit"] is True
    assert contract["af2_h100_recovery_jobs"] == 3
    assert contract["proteinmpnn_jobs_authorized"] == 0
    assert contract["boltz_jobs_authorized"] == 0
    assert contract["recovery_time_limit"] == "03:59:30"
    assert contract["maximum_protocol_gpu_seconds_after_recovery"] < 24 * 3600
    assert contract["authorizes_certification"] is False
    assert contract["authorizes_held_out_test"] is False
    assert contract["user_phrase"].startswith("approve W3b AF2 fit recovery for failed jobs")


def test_recovery_packet_rejects_non_path_failure_observation(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    observation_path = _observation(tmp_path)
    observation = json.loads(observation_path.read_text())
    observation["status"] = "w3b_fit_jobs_submitted_awaiting_completion"
    _write_json(observation_path, observation)

    with pytest.raises(ValueError, match="not approval-packet eligible"):
        build_recovery_packet(str(observation_path))


def test_recovery_target_fails_closed_on_partial_hash_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    observation = _observation(tmp_path)
    packet_path = tmp_path / "packet.json"
    _write_json(packet_path, build_recovery_packet(str(observation)))
    target = verify_recovery_target(str(observation), str(packet_path), "FIT_A")
    assert target["verified"] is True

    candidate_path = Path(target["partial_state"]["candidates"]["path"])
    candidate_path.write_text('{"id":"changed"}\n')
    with pytest.raises(ValueError, match="partial hash drift"):
        verify_recovery_target(str(observation), str(packet_path), "FIT_A")


def test_recovery_target_fails_closed_on_a3m_content_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    observation = _observation(tmp_path)
    packet_path = tmp_path / "packet.json"
    _write_json(packet_path, build_recovery_packet(str(observation)))
    packet = json.loads(packet_path.read_text())
    target = next(row for row in packet["targets"] if row["target_id"] == "FIT_A")
    manifest = json.loads(
        Path(target["partial_state"]["af2_input_manifest"]["path"]).read_text()
    )
    Path(manifest["rows"][0]["a3m_path"]).write_text(">changed\nAAAAAAAAA\n")

    with pytest.raises(ValueError, match="input hash drift"):
        verify_recovery_target(str(observation), str(packet_path), "FIT_A")


def test_recovery_journal_requires_exact_three_unique_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    observation = _observation(tmp_path)
    packet_path = tmp_path / "packet.json"
    receipt_path = tmp_path / "receipt.jsonl"
    _write_json(packet_path, build_recovery_packet(str(observation)))

    for target_id, job_id in (("FIT_A", "201"), ("FIT_B", "202"), ("FIT_C", "203")):
        append_recovery_event(str(receipt_path), str(packet_path), target_id, job_id)
    summary = build_recovery_summary(str(packet_path), str(receipt_path))

    assert summary["status"] == "w3b_fit_af2_recovery_jobs_submitted_awaiting_completion"
    assert summary["n_af2_h100_recovery_jobs"] == 3
    assert summary["can_claim_w3b"] is False
    assert {row["recovery_af2_job_id"] for row in summary["targets"]} == {"201", "202", "203"}


def test_recovery_runner_uses_absolute_container_paths_and_no_requeue():
    wrapper = (ROOT / "hpc/run_predict_af2_w3b_fit_recovery.sbatch").read_text()
    bridge = (ROOT / "hpc/m6d_w3b_fit_af2_recovery_with_receipt.sh").read_text()

    assert 'colabfold_batch "$AF2_INPUT_ABS" "$AF2_OUTPUT_ABS"' in wrapper
    assert "BIO_SFM_APPROVE_W3B_AF2_RECOVERY" in wrapper
    assert "--network none" in wrapper
    assert "run_generate_proteinmpnn" not in bridge
    assert "run_predict_boltz" not in bridge
    assert "verify-target" in bridge
    assert "--no-requeue" in bridge
    assert "03:59:30" in wrapper
