"""Tests for the no-compute W3c-B2 terminal partial-result adjudicator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_terminal_stop as mod


def _accounting():
    job_states = []
    failures = []
    failed_ids = []
    elapsed_total = 0
    for index, target_id in enumerate(mod.TARGET_IDS):
        for offset, predictor_id in enumerate(mod.PREDICTOR_IDS):
            job_id = str(1000 + index * 2 + offset)
            failed = predictor_id == mod.AF2_ID
            elapsed = 10 + offset
            elapsed_total += elapsed
            row = {
                "target_id": target_id,
                "predictor_id": predictor_id,
                "job_id": job_id,
                "state": "FAILED" if failed else "COMPLETED",
                "exit_code": "1:0" if failed else "0:0",
                "elapsed_seconds": elapsed,
                "requested_gpus": 1,
                "gpus": 1,
                "gpu_type": "h100",
            }
            job_states.append(row)
            if failed:
                failed_ids.append(job_id)
                failures.append({
                    "kind": "job_terminal_failure",
                    "message": "prediction job ended outside COMPLETED/0:0",
                    "target_id": target_id,
                    "predictor_id": predictor_id,
                    "job_id": job_id,
                    "state": "FAILED",
                    "exit_code": "1:0",
                })
    return {
        "artifact": "m6d_w3c_b2_completion_accounting",
        "version": 1,
        "status": "w3c_b2_terminal_failure_stop_no_retry",
        "audit_ok": False,
        "approval_consumed": True,
        "jobs_expected": 16,
        "jobs_in_receipt": 16,
        "jobs_in_sacct": 16,
        "jobs_terminal_success": 8,
        "jobs_pending": 0,
        "pending_job_ids": [],
        "missing_job_ids": [],
        "unexpected_job_ids": [],
        "terminal_failure_job_ids": failed_ids,
        "job_states": job_states,
        "gpu_allocation_seconds_total": elapsed_total,
        "gpu_allocation_hours_total": elapsed_total / 3600.0,
        "approved_h100_gpu_seconds": mod.MAXIMUM_H100_GPU_SECONDS,
        "within_approved_h100_budget": True,
        "sync_allowed": False,
        "retry_or_adaptive_top_up_allowed": False,
        "additional_jobs_authorized": 0,
        "proteinmpnn_designs": 0,
        "no_submit": True,
        "n_failures": 8,
        "failures": failures,
    }


def _write_valid_logs(
    root: Path,
    *,
    target_id: str,
    job_id: str,
    input_dir: str,
    a3m_sha256: str,
):
    stdout = root / f"biosfm-w3c-b2-af2-{job_id}.out"
    stderr = root / f"biosfm-w3c-b2-af2-{job_id}.err"
    stdout.write_text(
        "status=w3c_b2_approval_packet_verified_no_submit verified=True no_submit=True\n"
        f"target={target_id} predictor={mod.AF2_ID} context_valid=True prediction_executed=False\n"
        f"target={target_id} af2_input_ready=True a3m_sha256={a3m_sha256}\n"
        f"predictor={mod.AF2_ID} reobserved=True prediction_executed=False\n"
        "W3c-B2 AF2 GPU preflight devices: [CudaDevice(id=0)]\n"
        "2026-08-02 12:46:23,950 Running colabfold 1.6.1\n"
    )
    stderr.write_text(
        "Traceback (most recent call last):\n"
        "  File \"/usr/local/bin/colabfold_batch\", line 7, in <module>\n"
        "    sys.exit(main())\n"
        "  File \"/usr/local/lib/python3.12/site-packages/colabfold/batch.py\", line 2139, in main\n"
        "    queries, is_complex = get_queries(args.input, args.sort_queries_by)\n"
        "  File \"/usr/local/lib/python3.12/site-packages/colabfold/input.py\", line 275, in get_queries\n"
        "    raise OSError(f\"{input_path} could not be found\")\n"
        f"OSError: {input_dir} could not be found\n"
    )
    return stdout, stderr


def _synthetic_panel(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    runtime_lock_path = tmp_path / "runtime-lock.json"
    packet_path = tmp_path / "packet.json"
    receipt_path = tmp_path / "receipt.jsonl"
    summary_path = tmp_path / "summary.json"
    sacct_path = tmp_path / "sacct.tsv"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    manifest_path.write_text("{}\n")
    runtime_lock_path.write_text("{}\n")
    receipt_path.write_text("{}\n")
    summary_path.write_text("{}\n")
    sacct_path.write_text("header\n")
    accounting = _accounting()
    job_rows = {
        (row["target_id"], row["predictor_id"]): row
        for row in accounting["job_states"]
    }
    execution_targets = []
    for index, target_id in enumerate(mod.TARGET_IDS):
        root = tmp_path / target_id
        input_dir = root / "af2_inputs"
        input_dir.mkdir(parents=True)
        a3m = input_dir / f"w3c-b2-native-{target_id}.a3m"
        a3m.write_text(">query\nAAAA\n")
        input_manifest = root / "af2_input_manifest.json"
        input_manifest.write_text(json.dumps({
            "a3m_path": str(a3m),
            "a3m_sha256": mod.sha256_file(a3m),
        }) + "\n")
        boltz_record = root / "boltz2_native_record.json"
        boltz_record.write_text(json.dumps({
            "complex_target_id": target_id,
            "predictor_id": mod.BOLTZ_ID,
            "strict_qc_passed": True,
            "interface_pae": float(index + 1),
            "lrmsd_angstrom": 2.0 if index < 2 else 8.0,
            "success": index < 2,
        }) + "\n")
        boltz_observation = root / "boltz_runtime_observation.json"
        af2_observation = root / "af2_runtime_observation.json"
        boltz_observation.write_text("{}\n")
        af2_observation.write_text("{}\n")
        af2_job = job_rows[(target_id, mod.AF2_ID)]
        _write_valid_logs(
            log_dir,
            target_id=target_id,
            job_id=af2_job["job_id"],
            input_dir=str(input_dir),
            a3m_sha256=mod.sha256_file(a3m),
        )
        execution_targets.append({
            "target_id": target_id,
            "boltz_record": str(boltz_record),
            "boltz_runtime_observation": str(boltz_observation),
            "boltz_output_dir": str(root / "boltz_predictions"),
            "af2_record": str(root / "af2_multimer_native_record.json"),
            "af2_runtime_observation": str(af2_observation),
            "af2_input_manifest": str(input_manifest),
            "af2_input_dir": str(input_dir),
            "af2_output_dir": str(root / "af2_predictions"),
        })
    packet_path.write_text(json.dumps({
        "bound_artifacts": {
            "native_screen_manifest": {"path": str(manifest_path)},
            "runtime_lock": {"path": str(runtime_lock_path)},
        },
        "execution_targets": execution_targets,
    }) + "\n")
    return {
        "packet": packet_path,
        "receipt": receipt_path,
        "summary": summary_path,
        "sacct": sacct_path,
        "log_dir": log_dir,
        "accounting": accounting,
    }


def _install_synthetic_dependencies(monkeypatch, panel):
    monkeypatch.setattr(mod, "verify_packet_integrity", lambda *_: [])
    monkeypatch.setattr(mod, "build_accounting", lambda *_: panel["accounting"])
    monkeypatch.setattr(mod, "load_context", lambda *_: {})
    monkeypatch.setattr(mod, "validate_runtime_observation_file", lambda *_: {})
    monkeypatch.setattr(
        mod,
        "_validate_af2_input_manifest",
        lambda _context, path: mod.load_object(path),
    )
    monkeypatch.setattr(
        mod,
        "_record_artifacts",
        lambda *_args, **_kwargs: {
            "model": {"path": "model.pdb", "sha256": "a" * 64},
            "confidence": {"path": "confidence.json", "sha256": "b" * 64},
            "pae": {"path": "pae.npz", "sha256": "c" * 64},
        },
    )
    monkeypatch.setattr(
        mod,
        "_replay_native_metrics",
        lambda _context, record, _predictor, _artifacts: {
            "interface_pae": record["interface_pae"],
            "lrmsd_angstrom": record["lrmsd_angstrom"],
        },
    )
    monkeypatch.setattr(
        mod,
        "evaluate_records",
        lambda *_args, **_kwargs: {
            "audit_ok": False,
            "stage_pass": False,
            "records_expected": 16,
            "records_observed": 8,
            "failures": [{
                "kind": "missing_records",
                "pairs": [[target_id, mod.AF2_ID] for target_id in mod.TARGET_IDS],
            }],
        },
    )


def test_conjunctive_upper_bound_makes_two_of_eight_unreachable():
    assert mod.maximum_possible_conjunctive_passes(2) == 2
    assert mod.maximum_possible_conjunctive_passes(2) < mod.MINIMUM_TARGETS_PASSING
    with pytest.raises(ValueError, match="outside the frozen target scope"):
        mod.maximum_possible_conjunctive_passes(9)


def test_all_eight_af2_logs_require_exact_preinference_signature(tmp_path):
    for index, target_id in enumerate(mod.TARGET_IDS):
        input_dir = f"hpc_outputs/m6d_w3c_b2_native/{target_id}/af2_inputs"
        stdout, stderr = _write_valid_logs(
            tmp_path,
            target_id=target_id,
            job_id=str(index),
            input_dir=input_dir,
            a3m_sha256="a" * 64,
        )
        evidence = mod.validate_af2_preinference_logs(
            target_id=target_id,
            input_dir=input_dir,
            a3m_sha256="a" * 64,
            stdout_path=str(stdout),
            stderr_path=str(stderr),
        )
        assert evidence["model_inference_started"] is False
        assert evidence["failure_class"].startswith("pre_inference")

    stderr.write_text(stderr.read_text().replace("could not be found", "missing", 1))
    with pytest.raises(ValueError, match="exact input-resolution failure"):
        mod.validate_af2_preinference_logs(
            target_id=mod.TARGET_IDS[-1],
            input_dir=input_dir,
            a3m_sha256="a" * 64,
            stdout_path=str(stdout),
            stderr_path=str(stderr),
        )


def test_terminal_accounting_rejects_missing_or_unexpected_scope():
    accounting = _accounting()
    assert len(mod._validate_terminal_accounting(accounting)) == 16

    accounting["missing_job_ids"] = ["1000"]
    with pytest.raises(ValueError, match="frozen stop state"):
        mod._validate_terminal_accounting(accounting)

    accounting = _accounting()
    accounting["job_states"][1]["job_id"] = accounting["job_states"][0]["job_id"]
    with pytest.raises(ValueError, match="job IDs are incomplete or duplicated"):
        mod._validate_terminal_accounting(accounting)


def test_synthetic_terminal_panel_runs_end_to_end_and_is_idempotent(
    tmp_path, monkeypatch
):
    panel = _synthetic_panel(tmp_path)
    _install_synthetic_dependencies(monkeypatch, panel)
    outputs = {
        "boltz_records_path": str(tmp_path / "boltz.jsonl"),
        "af2_failure_evidence_path": str(tmp_path / "af2.jsonl"),
        "report_path": str(tmp_path / "report.json"),
        "report_md_path": str(tmp_path / "report.md"),
    }
    args = [
        str(panel["packet"]),
        str(panel["receipt"]),
        str(panel["summary"]),
        str(panel["sacct"]),
    ]
    report = mod.run(*args, log_dir=str(panel["log_dir"]), **outputs)
    replayed = mod.run(*args, log_dir=str(panel["log_dir"]), **outputs)

    assert replayed == report
    assert report["status"] == mod.STATUS
    assert report["audit_ok"] is True
    assert report["boltz_successes"] == 2
    assert report["maximum_possible_dual_predictor_target_passes"] == 2
    assert report["frozen_pass_mathematically_impossible"] is True
    assert report["af2_terminal_failures"] == 8
    assert len(Path(outputs["boltz_records_path"]).read_text().splitlines()) == 8
    assert len(Path(outputs["af2_failure_evidence_path"]).read_text().splitlines()) == 8


def test_invalid_boltz_hash_or_metric_replay_fails_closed(tmp_path, monkeypatch):
    panel = _synthetic_panel(tmp_path)
    _install_synthetic_dependencies(monkeypatch, panel)

    def invalid_hash(*_args, **_kwargs):
        raise ValueError("model output binding failed path or hash validation")

    monkeypatch.setattr(mod, "_record_artifacts", invalid_hash)
    with pytest.raises(ValueError, match="path or hash"):
        mod.adjudicate_terminal_stop(
            str(panel["packet"]),
            str(panel["receipt"]),
            str(panel["summary"]),
            str(panel["sacct"]),
            log_dir=str(panel["log_dir"]),
        )

    _install_synthetic_dependencies(monkeypatch, panel)

    def invalid_metric(*_args, **_kwargs):
        raise ValueError("record metrics do not replay from bound outputs")

    monkeypatch.setattr(mod, "_replay_native_metrics", invalid_metric)
    with pytest.raises(ValueError, match="do not replay"):
        mod.adjudicate_terminal_stop(
            str(panel["packet"]),
            str(panel["receipt"]),
            str(panel["summary"]),
            str(panel["sacct"]),
            log_dir=str(panel["log_dir"]),
        )


def test_terminal_adjudicator_has_no_retry_or_submission_authority(
    tmp_path, monkeypatch
):
    panel = _synthetic_panel(tmp_path)
    _install_synthetic_dependencies(monkeypatch, panel)
    report, _records, _failures = mod.adjudicate_terminal_stop(
        str(panel["packet"]),
        str(panel["receipt"]),
        str(panel["summary"]),
        str(panel["sacct"]),
        log_dir=str(panel["log_dir"]),
    )
    source = Path(mod.__file__).read_text()

    assert report["af2_recovery_authorized"] is False
    assert report["retry_or_adaptive_top_up_allowed"] is False
    assert report["additional_jobs_authorized"] == 0
    assert report["no_submit"] is True
    assert "subprocess" not in source
    assert "sbatch" not in source
    assert "srun" not in source
    assert "scancel" not in source
