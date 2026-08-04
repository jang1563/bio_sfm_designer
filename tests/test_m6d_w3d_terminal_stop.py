"""Tests for the no-retry W3d terminal partial-result adjudicator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3d_execution as execution
from bio_sfm_designer.experiments import m6d_w3d_terminal_stop as mod


ROOT = Path(__file__).resolve().parents[1]


def _manifest():
    return {
        "cells": [
            {
                "target_id": target_id,
                "representation_id": mod.TARGET_MSA,
                "predictor_id": mod.BOLTZ_ID,
                "cell_status": "completed_locked_w3c_b2_baseline",
                "baseline_outcome": {"success": index < 2},
            }
            for index, target_id in enumerate(mod.diagnostic.TARGET_IDS)
        ]
    }


def _available_records():
    rows = []
    for index, target_id in enumerate(mod.diagnostic.TARGET_IDS):
        rows.extend(
            (
                {
                    "target_id": target_id,
                    "representation_id": mod.TARGET_MSA,
                    "predictor_id": mod.AF2_ID,
                    "strict_qc_passed": True,
                    "success": index < 2,
                },
                {
                    "target_id": target_id,
                    "representation_id": mod.QUERY_ONLY,
                    "predictor_id": mod.BOLTZ_ID,
                    "strict_qc_passed": True,
                    "success": index == 0,
                },
            )
        )
    return rows


def _failure_evidence():
    return [
        {
            "target_id": target_id,
            "representation_id": mod.QUERY_ONLY,
            "predictor_id": mod.AF2_ID,
        }
        for target_id in mod.diagnostic.TARGET_IDS
    ]


def test_partial_matrix_proves_stage_stop_without_complete_case():
    result = mod.adjudicate_partial_matrix(
        _manifest(), _available_records(), _failure_evidence()
    )

    assert result["maximum_possible_recovered_representations"] == 0
    assert result["native_validity_recovery_mathematically_impossible"] is True
    assert result["complete_case_localization_evaluable"] is False
    assert result["complete_case_adjudication_performed"] is False
    by_cell = {
        (row["representation_id"], row["predictor_id"]): row
        for row in result["cell_summaries"]
    }
    assert by_cell[(mod.TARGET_MSA, mod.BOLTZ_ID)]["successes_observed"] == 2
    assert by_cell[(mod.TARGET_MSA, mod.AF2_ID)]["successes_observed"] == 2
    assert by_cell[(mod.QUERY_ONLY, mod.BOLTZ_ID)]["successes_observed"] == 1
    assert by_cell[(mod.QUERY_ONLY, mod.AF2_ID)]["maximum_successes"] == 8


def test_partial_matrix_rejects_missing_scope_or_failed_strict_qc():
    with pytest.raises(ValueError, match="scope is incomplete"):
        mod.adjudicate_partial_matrix(
            _manifest(), _available_records(), _failure_evidence()[:-1]
        )

    records = _available_records()
    records[0]["strict_qc_passed"] = False
    with pytest.raises(ValueError, match="do not all pass strict QC"):
        mod.adjudicate_partial_matrix(_manifest(), records, _failure_evidence())


def _accounting_fixture(tmp_path: Path):
    cells = []
    receipt_rows = []
    sacct_rows = [
        "JobIDRaw|JobName|State|ExitCode|ElapsedRaw|ReqTRES|AllocTRES|NodeList|Start|End"
    ]
    job_id = 1000
    for target_id in mod.diagnostic.TARGET_IDS:
        for representation_id, predictor_id in (
            (mod.TARGET_MSA, mod.AF2_ID),
            (mod.QUERY_ONLY, mod.BOLTZ_ID),
            (mod.QUERY_ONLY, mod.AF2_ID),
        ):
            cell_id = f"{target_id}-{representation_id}-{predictor_id}"
            cells.append(
                {
                    "cell_id": cell_id,
                    "target_id": target_id,
                    "representation_id": representation_id,
                    "predictor_id": predictor_id,
                }
            )
            receipt_rows.append({"cell_id": cell_id, "job_id": str(job_id)})
            failed = representation_id == mod.QUERY_ONLY and predictor_id == mod.AF2_ID
            state, exit_code = ("FAILED", "1:0") if failed else ("COMPLETED", "0:0")
            name = (
                "biosfm-w3d-af2" if predictor_id == mod.AF2_ID else "biosfm-w3d-boltz"
            )
            sacct_rows.append(
                "|".join(
                    (
                        str(job_id),
                        name,
                        state,
                        exit_code,
                        "10",
                        "billing=8,cpu=8,gres/gpu=1,mem=128G,node=1",
                        "billing=8,cpu=8,gres/gpu=1,mem=128G,node=1",
                        "g0004",
                        "2026-08-03T10:00:00",
                        "2026-08-03T10:00:10",
                    )
                )
            )
            job_id += 1
    packet = tmp_path / "packet.json"
    receipt = tmp_path / "receipt.jsonl"
    summary = tmp_path / "summary.json"
    sacct = tmp_path / "sacct.tsv"
    node = tmp_path / "node.txt"
    packet.write_text(json.dumps({"execution_cells": cells}) + "\n")
    receipt.write_text("".join(json.dumps(row) + "\n" for row in receipt_rows))
    summary_value = {
        "audit_ok": True,
        "jobs_recorded": 24,
        "retry_jobs": 0,
        "adaptive_top_up_jobs": 0,
    }
    summary.write_text(json.dumps(summary_value) + "\n")
    sacct.write_text("\n".join(sacct_rows) + "\n")
    node.write_text(
        "NodeName=g0004 NodeHostName=g0004\n"
        "Gres=gpu:h100:4\n"
        "CfgTRES=cpu=128,mem=1000G,billing=128,gres/gpu=4\n"
    )
    return packet, receipt, summary, sacct, node, summary_value


def test_terminal_accounting_requires_exact_16_success_8_failure_pattern(
    tmp_path, monkeypatch
):
    packet, receipt, summary, sacct, node, summary_value = _accounting_fixture(tmp_path)
    monkeypatch.setattr(mod, "verify_packet_integrity", lambda *_: [])
    monkeypatch.setattr(mod.journal, "summarize", lambda *_: summary_value)

    accounting = mod.build_accounting(
        str(packet), str(receipt), str(summary), str(sacct), str(node)
    )

    assert accounting["evidence_audit_ok"] is True
    assert accounting["jobs_terminal"] == 24
    assert accounting["jobs_terminal_success"] == 16
    assert accounting["jobs_terminal_failure"] == 8
    assert accounting["gpu_allocation_seconds_total"] == 240
    assert accounting["additional_jobs_authorized"] == 0

    text = sacct.read_text().replace(
        "1002|biosfm-w3d-af2|FAILED|1:0", "1002|biosfm-w3d-af2|COMPLETED|0:0"
    )
    sacct.write_text(text)
    with pytest.raises(ValueError, match="terminal state pattern drifted"):
        mod.build_accounting(
            str(packet), str(receipt), str(summary), str(sacct), str(node)
        )


def _write_completed_log(log_dir: Path, job_id: str, cell_id: str):
    stdout = log_dir / f"biosfm-w3d-af2-{job_id}.out"
    stderr = log_dir / f"biosfm-w3d-af2-{job_id}.err"
    stdout.write_text(
        "W3d packet verification passed: 24 evaluations, no submit\n"
        f"cell={cell_id} input_valid=True prediction_executed=False\n"
        f"predictor={mod.AF2_ID} reobserved=True prediction_executed=False\n"
        f"cell={cell_id} runtime_valid=True prediction_executed=False\n"
        "W3d AF2 GPU preflight devices: [CudaDevice(id=0)]\n"
        "Running on GPU\n"
        f"cell={cell_id} predictor={mod.AF2_ID} success=True strict_qc=True\n"
    )
    stderr.write_text("runtime warning only\n")


def test_completed_record_replays_bound_outputs(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    input_path = root / "hpc_outputs/input.a3m"
    output_dir = root / "hpc_outputs/prediction"
    record_path = root / "hpc_outputs/record.json"
    model = output_dir / "model.pdb"
    scores = output_dir / "scores.json"
    input_path.parent.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    input_path.write_text("input\n")
    model.write_text("model\n")
    scores.write_text(json.dumps({"pae": [[0.0]]}) + "\n")
    cell = {
        "cell_id": "cell-af2",
        "target_id": "target",
        "representation_id": mod.TARGET_MSA,
        "predictor_id": mod.AF2_ID,
        "record_path": str(record_path),
        "runtime_identity_sha256": "a" * 64,
    }
    context = {
        "project_root": root,
        "input_path": input_path,
        "output_dir": output_dir,
        "record_path": record_path,
    }
    record = {
        "artifact": "m6d_w3d_native_prediction_record",
        "version": 1,
        "status": "strict_qc_complete",
        "record_id": cell["cell_id"],
        "cell_id": cell["cell_id"],
        "target_id": cell["target_id"],
        "representation_id": cell["representation_id"],
        "predictor_id": cell["predictor_id"],
        "runtime_identity_sha256": cell["runtime_identity_sha256"],
        "strict_qc_passed": True,
        "success": True,
        "seed": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
        "input_binding": execution._binding(input_path, root=root),
        "output_bindings": {
            "model": execution._binding(model, root=root),
            "confidence": execution._binding(scores, root=root),
        },
        "auxiliary_output_bindings": {},
        "interface_pae": 10.1235,
        "lrmsd_angstrom": 3.0,
        "ligand_rmsd_angstrom": 3.0,
        "lrmsd_threshold_angstrom": 4.0,
    }
    record_path.write_text(json.dumps(record) + "\n")
    log_dir = root / "logs"
    log_dir.mkdir()
    _write_completed_log(log_dir, "1000", cell["cell_id"])
    monkeypatch.setattr(
        execution, "load_cell_context", lambda *_args, **_kwargs: context
    )
    monkeypatch.setattr(execution, "_strict_metrics", lambda *_args: (10.12345, 3.0))

    replayed, evidence = mod.validate_completed_record(
        cell, "1000", log_dir=str(log_dir)
    )

    assert replayed == record
    assert evidence["strict_qc_replayed"] is True
    assert evidence["logs"]["runtime_reobserved"] is True


def _write_failed_logs(log_dir: Path, job_id: str, cell_id: str):
    stdout = log_dir / f"biosfm-w3d-af2-{job_id}.out"
    stderr = log_dir / f"biosfm-w3d-af2-{job_id}.err"
    stdout.write_text(
        "W3d packet verification passed: 24 evaluations, no submit\n"
        f"cell={cell_id} input_valid=True prediction_executed=False\n"
        f"predictor={mod.AF2_ID} reobserved=True prediction_executed=False\n"
        f"cell={cell_id} runtime_valid=True prediction_executed=False\n"
        "W3d AF2 GPU preflight devices: [CudaDevice(id=0)]\n"
        "Running on GPU\n"
        f"Could not generate input features {cell_id}: MSA 0 must contain at least one sequence.\n"
        "ValueError: MSA 0 must contain at least one sequence.\n"
    )
    stderr.write_text(
        f"ValueError: {cell_id}: expected one W3d AF2 rank-001 model and score file\n"
    )
    return stdout


def test_query_only_failure_is_pre_model_encoding_evidence(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    input_path = root / "hpc_outputs/input.a3m"
    output_dir = root / "hpc_outputs/prediction"
    record_path = root / "hpc_outputs/record.json"
    input_path.parent.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    input_path.write_text("#4,4\t1,1\n>101\t102\nAAAACCCC\n")
    cell = {
        "cell_id": "cell-query-af2",
        "target_id": "target",
        "representation_id": mod.QUERY_ONLY,
        "predictor_id": mod.AF2_ID,
    }
    context = {
        "project_root": root,
        "cell": {
            "target_sequence_length": 4,
            "binder_sequence_length": 4,
        },
        "input_path": input_path,
        "output_dir": output_dir,
        "record_path": record_path,
    }
    log_dir = root / "logs"
    log_dir.mkdir()
    stdout = _write_failed_logs(log_dir, "1000", cell["cell_id"])
    monkeypatch.setattr(
        execution, "load_cell_context", lambda *_args, **_kwargs: context
    )

    evidence = mod.validate_query_only_af2_failure(cell, "1000", log_dir=str(log_dir))

    assert evidence["unpaired_monomer_query_rows_observed"] == 0
    assert evidence["model_inference_started"] is False
    assert evidence["scientific_outcome_observed"] is False

    stdout.write_text(stdout.read_text() + "recycle=0\n")
    with pytest.raises(ValueError, match="failure signature drifted"):
        mod.validate_query_only_af2_failure(cell, "1000", log_dir=str(log_dir))


def test_committed_public_terminal_evidence_replays_partial_decision(monkeypatch):
    monkeypatch.chdir(ROOT)
    manifest = json.loads(
        Path("configs/m6d_w3d_native_diagnostic_manifest.json").read_text()
    )
    records = mod._load_jsonl(mod.AVAILABLE_RECORDS_PATH)
    failures = mod._load_jsonl(mod.FAILURE_EVIDENCE_PATH)
    report = json.loads(Path(mod.REPORT_PATH).read_text())

    partial = mod.adjudicate_partial_matrix(manifest, records, failures)

    assert partial == report["partial_matrix"]
    assert report["status"] == mod.STATUS
    assert report["stage_pass"] is False
    assert report["complete_case_adjudication_performed"] is False
    assert report["additional_predictor_evaluations_authorized"] == 0


def test_terminal_module_has_no_scheduler_or_api_execution_route():
    source = Path(mod.__file__).read_text()

    assert "subprocess" not in source
    assert "sbatch" not in source
    assert "scancel" not in source
    assert "ProteinMPNN" not in source
    assert "requests." not in source
