"""Tests for the fail-closed W3c-B2 completion and retrieval bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_completion as mod


ROOT = Path(__file__).resolve().parents[1]
PACKET = "results/m6d_w3c_b2_prediction_approval_packet.json"
RECEIPT = "results/m6d_w3c_b2_submit_receipt.jsonl"
SUMMARY = "results/m6d_w3c_b2_submit_receipt_summary.json"


def _receipt_rows():
    return [
        json.loads(line)
        for line in (ROOT / RECEIPT).read_text().splitlines()
        if line.strip()
    ]


def _sacct(
    *,
    pending_job=None,
    failed_job=None,
    elapsed_seconds=60,
    omit_job=None,
    extra_job=None,
):
    lines = [
        "JobIDRaw|JobName|State|ExitCode|ElapsedRaw|ReqTRES|AllocTRES|"
        "NodeList|Start|End|"
    ]
    for receipt in _receipt_rows():
        job_id = receipt["job_id"]
        job_name = (
            "biosfm-w3c-b2-boltz"
            if receipt["predictor_id"] == "boltz2_complex"
            else "biosfm-w3c-b2-af2"
        )
        if job_id == omit_job:
            continue
        if job_id == pending_job:
            lines.append(
                f"{job_id}|{job_name}|PENDING|0:0|0|gres/gpu=1|||Unknown|Unknown|"
            )
        elif job_id == failed_job:
            lines.append(
                f"{job_id}|{job_name}|FAILED|1:0|17|gres/gpu=1|"
                "billing=1,gres/gpu=1|g0004|a|b|"
            )
        else:
            lines.append(
                f"{job_id}|{job_name}|COMPLETED|0:0|{elapsed_seconds}|"
                "gres/gpu=1|"
                "billing=1,gres/gpu=1|g0004|a|b|"
            )
        lines.append(f"{job_id}.batch|batch|COMPLETED|0:0|1|cpu=1|cpu=1|g0004|a|b|")
    if extra_job:
        lines.append(
            f"{extra_job}|biosfm-w3c-b2-boltz|COMPLETED|0:0|60|"
            "gres/gpu=1|billing=1,gres/gpu=1|g0004|a|b|"
        )
    return "\n".join(lines) + "\n"


def _account(tmp_path, monkeypatch, sacct_text):
    monkeypatch.chdir(ROOT)
    sacct = tmp_path / "sacct.tsv"
    sacct.write_text(sacct_text)
    return mod.build_accounting(PACKET, RECEIPT, SUMMARY, str(sacct))


def test_pending_job_keeps_sync_locked_without_audit_failure(tmp_path, monkeypatch):
    report = _account(
        tmp_path,
        monkeypatch,
        _sacct(pending_job=_receipt_rows()[3]["job_id"]),
    )

    assert report["status"] == "w3c_b2_jobs_pending_sync_locked"
    assert report["audit_ok"] is True
    assert report["sync_allowed"] is False
    assert report["jobs_terminal_success"] == 15
    assert report["jobs_pending"] == 1
    assert report["additional_jobs_authorized"] == 0
    assert report["retry_or_adaptive_top_up_allowed"] is False


def test_exact_sixteen_terminal_jobs_unlock_only_sync(tmp_path, monkeypatch):
    report = _account(tmp_path, monkeypatch, _sacct())

    assert report["status"] == "w3c_b2_jobs_complete_sync_unlocked"
    assert report["audit_ok"] is True
    assert report["sync_allowed"] is True
    assert report["jobs_terminal_success"] == 16
    assert report["gpu_allocation_seconds_total"] == 16 * 60
    assert report["scientific_adjudication_allowed"] is False
    assert report["can_claim_native_recoverability"] is False


def test_terminal_failure_is_permanent_stop_without_retry(tmp_path, monkeypatch):
    failed_job = _receipt_rows()[5]["job_id"]
    report = _account(tmp_path, monkeypatch, _sacct(failed_job=failed_job))

    assert report["status"] == "w3c_b2_terminal_failure_stop_no_retry"
    assert report["audit_ok"] is False
    assert report["sync_allowed"] is False
    assert report["terminal_failure_job_ids"] == [failed_job]
    assert "job_terminal_failure" in {row["kind"] for row in report["failures"]}
    assert report["additional_jobs_authorized"] == 0


def test_missing_and_unexpected_jobs_fail_closed(tmp_path, monkeypatch):
    missing = _receipt_rows()[0]["job_id"]
    report = _account(
        tmp_path,
        monkeypatch,
        _sacct(omit_job=missing, extra_job="9999999"),
    )

    assert report["status"] == "w3c_b2_accounting_blocked"
    assert report["audit_ok"] is False
    assert report["sync_allowed"] is False
    assert report["missing_job_ids"] == [missing]
    assert report["unexpected_job_ids"] == ["9999999"]


def test_per_job_and_total_h100_budget_are_both_enforced(tmp_path, monkeypatch):
    report = _account(tmp_path, monkeypatch, _sacct(elapsed_seconds=3601))

    assert report["audit_ok"] is False
    kinds = {row["kind"] for row in report["failures"]}
    assert "job_resource_contract_invalid" in kinds
    assert "h100_gpu_budget_exceeded" in kinds
    assert report["within_approved_h100_budget"] is False


def test_scheduler_job_name_is_bound_to_the_receipt_predictor(tmp_path, monkeypatch):
    text = _sacct().replace(
        "3171272|biosfm-w3c-b2-boltz|",
        "3171272|biosfm-w3c-b2-af2|",
        1,
    )
    report = _account(tmp_path, monkeypatch, text)

    assert report["audit_ok"] is False
    assert report["sync_allowed"] is False
    assert "job_request_contract_invalid" in {row["kind"] for row in report["failures"]}


def test_parse_sacct_ignores_steps_and_rejects_duplicate_allocations():
    text = (
        "JobIDRaw|JobName|State|ExitCode|ElapsedRaw|ReqTRES|AllocTRES|"
        "NodeList|Start|End|\n"
        "123|job|COMPLETED|0:0|60|gres/gpu=1|gres/gpu=1|g0004|a|b|\n"
        "123.batch|batch|COMPLETED|0:0|59|cpu=1|cpu=1|g0004|a|b|\n"
    )
    assert list(mod.parse_sacct(text)) == ["123"]

    with pytest.raises(ValueError, match="duplicate top-level"):
        mod.parse_sacct(text + text.splitlines()[1] + "\n")


def test_record_output_bindings_require_local_hashes_and_target_root(tmp_path):
    target_root = tmp_path / "target"
    predictor_root = target_root / "prediction"
    predictor_root.mkdir(parents=True)
    model = predictor_root / "model.pdb"
    confidence = predictor_root / "scores.json"
    pae = predictor_root / "pae.npz"
    model.write_text("MODEL\n")
    confidence.write_text("{}\n")
    pae.write_bytes(b"pae")

    def binding(path):
        return {"path": str(path), "sha256": mod.sha256_file(path)}

    record = {
        "output_bindings": {
            "model": binding(model),
            "confidence": binding(confidence),
        },
        "auxiliary_output_bindings": {"pae": binding(pae)},
    }
    outputs = mod._record_artifacts(
        record,
        target_root=str(target_root),
        predictor_output_root=str(predictor_root),
        expected_auxiliary_name="pae",
    )
    assert set(outputs) == {"model", "confidence", "pae"}

    outside = tmp_path / "outside.pdb"
    outside.write_text("MODEL\n")
    record["output_bindings"]["model"] = binding(outside)
    with pytest.raises(ValueError, match="path or hash"):
        mod._record_artifacts(
            record,
            target_root=str(target_root),
            predictor_output_root=str(predictor_root),
            expected_auxiliary_name="pae",
        )

    escaped = predictor_root / "escaped.pdb"
    escaped.symlink_to(outside)
    record["output_bindings"]["model"] = binding(escaped)
    with pytest.raises(ValueError, match="path or hash"):
        mod._record_artifacts(
            record,
            target_root=str(target_root),
            predictor_output_root=str(predictor_root),
            expected_auxiliary_name="pae",
        )


def test_native_metrics_must_replay_from_bound_predictor_outputs(tmp_path, monkeypatch):
    model = tmp_path / "model.pdb"
    confidence = tmp_path / "scores.json"
    model.write_text("MODEL\n")
    confidence.write_text(json.dumps({"pae": [[1.0]]}))
    artifacts = {
        "model": {"path": str(model)},
        "confidence": {"path": str(confidence)},
    }
    record = {
        "interface_pae": 3.1416,
        "lrmsd_angstrom": 2.5,
        "success": True,
    }
    monkeypatch.setattr(mod, "_strict_metrics", lambda *_: (3.141592, 2.5))

    replayed = mod._replay_native_metrics(
        {}, record, "af2_multimer_colabfold_v1", artifacts
    )
    assert replayed == {"interface_pae": 3.1416, "lrmsd_angstrom": 2.5}

    record["lrmsd_angstrom"] = 2.6
    with pytest.raises(ValueError, match="do not replay"):
        mod._replay_native_metrics({}, record, "af2_multimer_colabfold_v1", artifacts)


def test_finalizer_assembles_exact_order_and_is_idempotent(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    runtime_lock_path = tmp_path / "runtime-lock.json"
    packet_path = tmp_path / "packet.json"
    accounting_path = tmp_path / "accounting.json"
    records_path = tmp_path / "native-records.jsonl"
    report_path = tmp_path / "report.json"
    report_md_path = tmp_path / "report.md"
    completion_path = tmp_path / "completion.json"
    completion_md_path = tmp_path / "completion.md"
    runtime_lock_path.write_text("{}\n")
    accounting_path.write_text("{}\n")
    execution_targets = []
    manifest_targets = []
    expected_pairs = []

    for target_id in mod.TARGET_IDS:
        root = tmp_path / "outputs" / target_id
        boltz_root = root / "boltz"
        af2_root = root / "af2"
        boltz_root.mkdir(parents=True)
        af2_root.mkdir()
        paths = {
            "boltz_record": root / "boltz.json",
            "af2_record": root / "af2.json",
            "matched_record": root / "matched.json",
            "boltz_runtime_observation": root / "boltz-runtime.json",
            "af2_runtime_observation": root / "af2-runtime.json",
            "boltz_output_dir": boltz_root,
            "af2_output_dir": af2_root,
        }
        paths["boltz_runtime_observation"].write_text("{}\n")
        paths["af2_runtime_observation"].write_text("{}\n")
        for predictor_id in mod.PREDICTOR_IDS:
            predictor_root = (
                boltz_root if predictor_id == "boltz2_complex" else af2_root
            )
            model = predictor_root / "model.pdb"
            confidence = predictor_root / "confidence.json"
            model.write_text(f"MODEL {predictor_id}\n")
            confidence.write_text("{}\n")
            if predictor_id == "boltz2_complex":
                auxiliary_name = "pae"
                auxiliary = predictor_root / "pae.npz"
                record_path = paths["boltz_record"]
            else:
                auxiliary_name = "input_manifest"
                auxiliary = root / "af2-input.json"
                record_path = paths["af2_record"]
            auxiliary.write_text("aux\n")

            def file_binding(path):
                return {
                    "path": str(path),
                    "sha256": mod.sha256_file(path),
                }

            record = {
                "complex_target_id": target_id,
                "predictor_id": predictor_id,
                "record_id": f"w3c-b2-native-{target_id}-{predictor_id}",
                "strict_qc_passed": True,
                "interface_pae": 2.0,
                "lrmsd_angstrom": 2.0,
                "success": True,
                "output_bindings": {
                    "model": file_binding(model),
                    "confidence": file_binding(confidence),
                },
                "auxiliary_output_bindings": {auxiliary_name: file_binding(auxiliary)},
            }
            record_path.write_text(json.dumps(record) + "\n")
            expected_pairs.append((target_id, predictor_id))
        execution_targets.append(
            {
                "target_id": target_id,
                "native_candidate_id": f"w3c-b2-native-{target_id}",
                **{name: str(path) for name, path in paths.items()},
            }
        )
        manifest_targets.append(
            {
                "target_id": target_id,
                "outputs": {"matched_record": str(paths["matched_record"])},
            }
        )
    manifest_path.write_text(json.dumps({"targets": manifest_targets}) + "\n")
    packet = {
        "bound_artifacts": {
            "native_screen_manifest": {"path": str(manifest_path)},
            "runtime_lock": {"path": str(runtime_lock_path)},
        },
        "execution_targets": execution_targets,
        "initial_output_paths": [
            str(records_path),
            str(report_path),
            str(report_md_path),
        ],
    }
    packet_path.write_text(json.dumps(packet) + "\n")
    accounting = {
        "input_bindings": {"approval_packet": {"path": str(packet_path)}},
        "gpu_allocation_seconds_total": 960,
        "gpu_allocation_hours_total": 960 / 3600,
    }
    monkeypatch.setattr(mod, "_replay_accounting", lambda *_: accounting)
    monkeypatch.setattr(mod, "load_context", lambda *_: {})
    monkeypatch.setattr(mod, "validate_runtime_observation_file", lambda *_: {})
    monkeypatch.setattr(mod, "_replay_native_metrics", lambda *_: {})

    def evaluate(_manifest, _runtime_lock, records, **_kwargs):
        assert [
            (row["complex_target_id"], row["predictor_id"]) for row in records
        ] == expected_pairs
        return {
            "artifact": "m6d_w3c_b2_native_recoverability_report",
            "status": "w3c_b2_native_recoverability_pass",
            "audit_ok": True,
            "stage_pass": True,
            "targets_passing": 8,
            "minimum_targets_passing": 6,
            "claim_boundary": "locked-panel native recovery only",
            "next_action": "prepare a separately approved generator-yield protocol",
        }

    monkeypatch.setattr(mod, "evaluate_records", evaluate)
    kwargs = {
        "records_path": str(records_path),
        "report_path": str(report_path),
        "report_md_path": str(report_md_path),
        "completion_path": str(completion_path),
        "completion_md_path": str(completion_md_path),
    }

    completion = mod.finalize(str(accounting_path), **kwargs)
    replayed = mod.finalize(str(accounting_path), **kwargs)

    assert replayed == completion
    assert completion["records_observed"] == 16
    assert completion["matched_target_records"] == 8
    assert completion["verified_predictor_output_files"] == 48
    assert completion["replayed_metric_records"] == 16
    assert len(records_path.read_text().splitlines()) == 16
    assert all(Path(row["matched_record"]).is_file() for row in execution_targets)


def test_completion_bridge_has_no_submission_or_retry_surface(monkeypatch):
    monkeypatch.chdir(ROOT)
    script = Path("hpc/m6d_w3c_b2_complete_and_sync.sh").read_text()

    assert "sacct -P" in script
    assert "--require-sync-ready" in script
    assert "sync-roots" in script
    assert "rsync -aP" in script
    assert "sbatch" not in script
    assert "srun" not in script
    assert "scancel" not in script
    assert "ProteinMPNN" not in script
    assert "--dependency" not in script


def test_committed_packet_exposes_eight_exact_sync_roots(monkeypatch):
    monkeypatch.chdir(ROOT)
    roots = mod.packet_sync_roots(PACKET)

    assert len(roots) == len(set(roots)) == 8
    assert roots == [
        f"hpc_outputs/m6d_w3c_b2_native/{target_id}" for target_id in mod.TARGET_IDS
    ]
