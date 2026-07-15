"""Tests for terminal W3b AF2 fit-recovery accounting and output gating."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery_completion import (
    build_completion,
)
from bio_sfm_designer.experiments.m6d_w3b_producer_contract import sha256_file


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _fixture(tmp_path: Path, *, failed_job: Optional[str] = None):
    observation_path = tmp_path / "initial.json"
    _write_json(
        observation_path,
        {
            "artifact": "m6d_w3b_fit_initial_execution_observation",
            "status": "w3b_fit_af2_path_failure_recovery_eligible_no_submit",
            "audit_ok": True,
            "initial_failed_af2_gpu_seconds": 38,
        },
    )
    targets = []
    summary_targets = []
    sacct_rows = []
    scontrol_rows = ["2026-07-15T14:00:00+09:00"]
    log_root = tmp_path / "logs"
    log_root.mkdir()
    for index, target_id in enumerate(("FIT_A", "FIT_B", "FIT_C"), 1):
        failed_id = str(100 + index)
        recovery_id = str(200 + index)
        root = tmp_path / target_id
        output = root / "af2_predictions"
        output.mkdir(parents=True)
        candidates = root / "candidates.jsonl"
        records = root / "records_af2.jsonl"
        receipt = root / "af2_receipt.json"
        candidate_rows = [{"id": f"{target_id}-{row}"} for row in range(60)]
        candidates.write_text("".join(json.dumps(row) + "\n" for row in candidate_rows))
        terminal_success = recovery_id != failed_job
        if terminal_success:
            records.write_text(
                "".join(
                    json.dumps({"target_id": f"{target_id}-{row}"}) + "\n"
                    for row in range(60)
                )
            )
            _write_json(
                receipt,
                {
                    "artifact": "m6d_w3b_predictor_runtime_receipt",
                    "status": "w3b_predictor_records_complete",
                    "audit_ok": True,
                    "no_submit": True,
                    "predictor_id": "af2_multimer_colabfold_v1",
                    "target_id": target_id,
                    "experimental_role": "fit",
                    "n_records": 60,
                    "records": str(records),
                    "records_sha256": sha256_file(records),
                    "candidates": str(candidates),
                    "candidates_sha256": sha256_file(candidates),
                },
            )
            for row in range(60):
                (output / f"{target_id}-{row}.done.txt").write_text("done\n")
                for model in range(5):
                    (output / f"{target_id}-{row}_scores_rank_{model}.json").write_text("{}\n")
                    (output / f"{target_id}-{row}_unrelaxed_rank_{model}.pdb").write_text("ATOM\n")
            (log_root / f"biosfm-w3b-fit-af2r-{recovery_id}.out").write_text("ok\n")
            (log_root / f"biosfm-w3b-fit-af2r-{recovery_id}.err").write_text("warning\n")
        targets.append(
            {
                "target_id": target_id,
                "failed_af2_job_id": failed_id,
                "partial_state": {
                    "candidates": {
                        "path": str(candidates),
                        "sha256": sha256_file(candidates),
                    },
                    "af2_output_dir": str(output),
                    "af2_records": str(records),
                    "af2_runtime_receipt": str(receipt),
                },
            }
        )
        summary_targets.append(
            {
                "target_id": target_id,
                "failed_af2_job_id": failed_id,
                "recovery_af2_job_id": recovery_id,
            }
        )
        state = "FAILED" if recovery_id == failed_job else "COMPLETED"
        exit_code = "1:0" if recovery_id == failed_job else "0:0"
        sacct_rows.append(
            f"{recovery_id}|{state}|{exit_code}|120|billing=8,cpu=8,gres/gpu=1,mem=128G,node=1|g0004"
        )
        scontrol_rows.append(
            f"JobId={recovery_id} JobState=RUNNING Requeue=0 TimeLimit=03:59:00 "
            "TresPerNode=gres/gpu:h100:1"
        )

    packet_path = tmp_path / "packet.json"
    _write_json(
        packet_path,
        {
            "artifact": "m6d_w3b_fit_af2_recovery_approval_packet",
            "status": "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval",
            "observation": {"sha256": sha256_file(observation_path)},
            "approval_contract": {
                "recovery_time_limit": "03:59:30",
                "requeue": False,
                "proteinmpnn_jobs_authorized": 0,
                "boltz_jobs_authorized": 0,
                "authorizes_certification": False,
                "authorizes_held_out_test": False,
                "authorizes_claim": False,
                "maximum_original_boltz_gpu_seconds": 43200,
                "maximum_protocol_gpu_seconds_after_recovery": 86348,
            },
            "targets": targets,
        },
    )
    submit_receipt = tmp_path / "submit.jsonl"
    submit_receipt.write_text("{}\n")
    summary_path = tmp_path / "summary.json"
    _write_json(
        summary_path,
        {
            "artifact": "m6d_w3b_fit_af2_recovery_submit_summary",
            "status": "w3b_fit_af2_recovery_jobs_submitted_awaiting_completion",
            "approval_packet_sha256": sha256_file(packet_path),
            "receipt_sha256": sha256_file(submit_receipt),
            "n_af2_h100_recovery_jobs": 3,
            "targets": summary_targets,
        },
    )
    sacct = tmp_path / "sacct.tsv"
    sacct.write_text("\n".join(sacct_rows) + "\n")
    scontrol = tmp_path / "scontrol.txt"
    scontrol.write_text("\n".join(scontrol_rows) + "\n")
    return {
        "initial": str(observation_path),
        "packet": str(packet_path),
        "receipt": str(submit_receipt),
        "summary": str(summary_path),
        "sacct": str(sacct),
        "scontrol": str(scontrol),
        "log_root": str(log_root),
    }


def _build(paths):
    return build_completion(
        paths["initial"],
        paths["packet"],
        paths["receipt"],
        paths["summary"],
        paths["sacct"],
        paths["scontrol"],
        log_root=paths["log_root"],
    )


def test_completion_opens_only_matched_assembly_and_corrects_rounding(tmp_path):
    report = _build(_fixture(tmp_path))

    assert report["status"] == "w3b_fit_af2_recovery_completed_ready_for_matched_assembly"
    assert report["n_recovery_jobs_completed"] == 3
    assert report["can_run_fit_assembler"] is True
    assert report["can_submit_certification"] is False
    assert report["can_claim_w3b"] is False
    correction = report["scheduler_time_limit_correction"]
    assert correction["rounded_worst_case_gpu_seconds"] == 86438
    assert correction["corrected_worst_case_gpu_seconds"] == 86258
    assert correction["corrected_margin_seconds"] == 142


def test_terminal_recovery_failure_stops_without_requiring_outputs(tmp_path):
    report = _build(_fixture(tmp_path, failed_job="202"))

    assert report["audit_ok"] is True
    assert report["status"] == "w3b_fit_af2_recovery_terminal_failure_stop"
    assert report["n_recovery_jobs_completed"] == 2
    assert report["can_run_fit_assembler"] is False
    assert report["can_submit_more_recovery_jobs"] is False


def test_completion_rejects_time_limit_drift(tmp_path):
    paths = _fixture(tmp_path)
    snapshot = Path(paths["scontrol"])
    snapshot.write_text(snapshot.read_text().replace("03:59:00", "04:00:00", 1))

    with pytest.raises(ValueError, match="post-correction Slurm contract failed"):
        _build(paths)
