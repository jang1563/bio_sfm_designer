"""Tests for W3c-B1 target-MSA completion adjudication."""

import hashlib
import json
import pathlib

from bio_sfm_designer.experiments import m6d_w3c_b1_target_msa_completion as completion


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPLETION_PATH = ROOT / "results/m6d_w3c_b1_target_msa_completion.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _synthetic_bundle(tmp_path):
    sbatch_path = tmp_path / "target_msa.sbatch"
    sbatch_path.write_text(
        "#!/usr/bin/env bash\n"
        "#SBATCH --gres=gpu:a40:1\n"
        "#SBATCH --time=01:00:00\n"
    )
    targets = []
    reports = []
    for index, target_id in enumerate(completion.TARGET_IDS):
        target_dir = tmp_path / target_id
        target_dir.mkdir()
        sequence = "ACDEFGHIK" + "A" * index
        fasta_path = target_dir / f"{target_id}.fasta"
        msa_path = target_dir / f"{target_id}.a3m"
        report_path = target_dir / f"{target_id}.a3m.report.json"
        fasta_path.write_text(f">{target_id}\n{sequence}\n")
        msa_path.write_text(
            f">{target_id}\n{sequence}\n>homolog\n{sequence}\n"
        )
        report = {
            "ok": True,
            "fasta": str(fasta_path),
            "fasta_sha256": _sha256(fasta_path),
            "out": str(msa_path),
            "out_sha256": _sha256(msa_path),
            "sequence_length": len(sequence),
            "out_sanitized_nul_bytes": 0,
            "reused_existing": False,
            "recovered_after_boltz_failure": False,
        }
        _write_json(report_path, report)
        reports.append(report)
        targets.append(
            {
                "id": target_id,
                "target_fasta": str(fasta_path),
                "target_msa": str(msa_path),
                "target_msa_report": str(report_path),
                "target_sequence_sha256": hashlib.sha256(
                    sequence.encode("ascii")
                ).hexdigest(),
            }
        )
    manifest = {
        "artifact": "m6d_w3c_b1_target_msa_manifest",
        "version": 1,
        "target_count": 8,
        "target_ids": completion.TARGET_IDS,
        "maximum_target_msa_queries": 8,
        "maximum_a40_gpu_hours": 8.0,
        "targets": targets,
    }
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)
    packet = {
        "artifact": "m6d_w3c_b1_target_msa_approval_packet",
        "status": "w3c_b1_packet_cayuga_validated_ready_for_exact_approval",
        "approval_packet_ready": True,
        "cayuga_no_submit_validation_status": "pass",
        "ready_to_request_exact_approval": True,
        "required_user_phrase": completion.APPROVAL_PHRASE,
        "target_ids": completion.TARGET_IDS,
        "target_count": 8,
        "maximum_target_msa_queries": 8,
        "maximum_a40_gpu_hours": 8.0,
        "can_submit_target_msa_if_explicitly_approved": True,
        "can_submit_proteinmpnn": False,
        "can_submit_structure_predictors": False,
        "can_prepare_w3c_b2": False,
        "bound_artifacts": {
            "execution_manifest": {
                "path": str(manifest_path),
                "sha256": _sha256(manifest_path),
            },
            "precompute_sbatch": {
                "path": str(sbatch_path),
                "sha256": _sha256(sbatch_path),
            },
        },
    }
    packet_path = tmp_path / "packet.json"
    _write_json(packet_path, packet)
    preflight = {
        "artifact": "m6d_w3c_b1_target_msa_input_preflight",
        "status": "w3c_b1_inputs_materialized_ready_for_approved_msa_submission",
        "audit_ok": True,
        "mode": "materialize",
        "target_count": 8,
        "target_ids": completion.TARGET_IDS,
        "source_pdbs_verified": 8,
        "target_fastas_verified": 8,
        "scheduler_jobs_submitted": 0,
        "target_msa_queries_submitted": 0,
        "proteinmpnn_designs": 0,
        "predictor_evaluations": 0,
    }
    preflight_path = tmp_path / "preflight.json"
    _write_json(preflight_path, preflight)
    receipt_rows = []
    for index, target in enumerate(targets):
        receipt_rows.append(
            {
                "target_id": target["id"],
                "status": "submitted",
                "job_id": str(1000 + index),
                "target_fasta": target["target_fasta"],
                "target_msa": target["target_msa"],
                "target_msa_report": target["target_msa_report"],
                "manifest": str(manifest_path),
                "manifest_sha256": _sha256(manifest_path),
                "workstream": completion.WORKSTREAM,
            }
        )
    receipt_path = tmp_path / "receipt.jsonl"
    receipt_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipt_rows)
    )
    summary = {
        "artifact": "m6d_w3c_b1_target_msa_receipt_summary",
        "status": "w3c_b1_target_msa_jobs_submitted_or_reused",
        "workstream": completion.WORKSTREAM,
        "execution_manifest": str(manifest_path),
        "execution_manifest_sha256": _sha256(manifest_path),
        "n_records": 8,
        "n_targets": 8,
        "target_ids": completion.TARGET_IDS,
        "status_counts": {"submitted": 8},
        "proteinmpnn_designs": 0,
        "predictor_evaluations": 0,
        "input_preflight": str(preflight_path),
        "input_preflight_sha256": _sha256(preflight_path),
    }
    summary_path = tmp_path / "summary.json"
    _write_json(summary_path, summary)
    sacct_lines = [
        "JobIDRaw|State|ExitCode|ElapsedRaw|AllocTRES|NodeList",
    ]
    for index in range(8):
        sacct_lines.append(
            f"{1000 + index}|COMPLETED|0:0|600|cpu=4,gres/gpu=1,mem=32G|node"
        )
    sacct_lines.append("1000.1|FAILED|1:0|0|cpu=4,gres/gpu=1,mem=32G|node")
    sacct_text = "\n".join(sacct_lines) + "\n"
    sacct_path = tmp_path / "sacct.tsv"
    sacct_path.write_text(sacct_text)
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "packet": packet,
        "packet_path": str(packet_path),
        "receipt_rows": receipt_rows,
        "receipt_path": str(receipt_path),
        "summary": summary,
        "summary_path": str(summary_path),
        "preflight": preflight,
        "preflight_path": str(preflight_path),
        "sacct_text": sacct_text,
        "sacct_path": str(sacct_path),
        "sbatch_path": str(sbatch_path),
        "targets": targets,
        "reports": reports,
    }


def _evaluate(bundle, monkeypatch):
    monkeypatch.setattr(
        completion,
        "validate_manifest",
        lambda *_args, **_kwargs: {"ok": True, "failures_by_kind": {}},
    )
    kwargs = {key: value for key, value in bundle.items() if key not in {"targets", "reports"}}
    return completion.evaluate_completion(**kwargs)


def test_completion_accepts_exact_eight_job_scope_and_ignores_step_rows(
    tmp_path, monkeypatch
):
    report = _evaluate(_synthetic_bundle(tmp_path), monkeypatch)

    assert report["status"] == "target_msa_precompute_complete_8_of_8"
    assert report["completion_ok"] is True
    assert report["submitted_jobs_total"] == 8
    assert report["jobs_terminal_success"] is True
    assert report["gpu_allocation_seconds_total"] == 4800
    assert report["n_target_msas"] == 8
    assert report["can_prepare_w3c_b2_packet"] is True
    assert report["can_submit_w3c_b2"] is False
    assert report["failures"] == []


def test_completion_fails_closed_on_query_or_job_drift(tmp_path, monkeypatch):
    bundle = _synthetic_bundle(tmp_path)
    first_msa = pathlib.Path(bundle["targets"][0]["target_msa"])
    first_msa.write_text(">query\nAAAAAAAAA\n>homolog\nAAAAAAAAA\n")
    sacct_path = pathlib.Path(bundle["sacct_path"])
    failed_sacct = bundle["sacct_text"].replace(
        "1001|COMPLETED|0:0|600", "1001|FAILED|1:0|600"
    )
    sacct_path.write_text(failed_sacct)
    bundle["sacct_text"] = failed_sacct

    report = _evaluate(bundle, monkeypatch)

    assert report["completion_ok"] is False
    assert report["can_prepare_w3c_b2_packet"] is False
    assert {
        failure["kind"] for failure in report["failures"]
    } >= {"target_msa_integrity_failed", "job_terminal_failure"}


def test_committed_completion_preserves_honest_boundary():
    report = json.loads(COMPLETION_PATH.read_text())

    assert report["status"] == "target_msa_precompute_complete_8_of_8"
    assert report["completion_ok"] is True
    assert report["n_target_msas"] == 8
    assert min(row["a3m_records"] for row in report["target_artifacts"]) == 96
    assert all(row["query_sequence_match"] for row in report["target_artifacts"])
    assert report["transport_observation"]["post_msa_inference_failures_recovered"] == 8
    assert report["transport_observation"]["structure_prediction_outputs_consumed"] == 0
    assert report["can_submit_w3c_b2"] is False
    assert report["can_claim_native_recoverability"] is False
