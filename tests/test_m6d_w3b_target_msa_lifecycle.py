"""Tests for the W3b target-MSA post-approval lifecycle."""

import hashlib
import json

from bio_sfm_designer.experiments.m6d_w3b_target_msa_lifecycle import evaluate_lifecycle


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _fixture(tmp_path, *, with_msas=True):
    targets = []
    for index in range(8):
        target_id = f"T{index}"
        directory = tmp_path / target_id
        directory.mkdir()
        prepared = directory / "prepared.pdb"
        fasta = directory / "target.fasta"
        fasta_report = directory / "target.fasta.report.json"
        msa = directory / "target.a3m"
        msa_report = directory / "target.a3m.report.json"
        sequence = "ACDEFG"
        prepared.write_text("ATOM\n")
        fasta.write_text(f">{target_id}\n{sequence}\n")
        _write_json(
            fasta_report,
            {
                "chain": "A",
                "length": len(sequence),
                "out": str(fasta),
                "out_sha256": _sha(fasta),
                "pdb": str(prepared),
                "pdb_sha256": _sha(prepared),
                "sequence": sequence,
            },
        )
        if with_msas:
            msa.write_text(f">{target_id}\n{sequence}\n>hit\n{sequence}\n")
            _write_json(
                msa_report,
                {
                    "fasta": str(fasta),
                    "fasta_sha256": _sha(fasta),
                    "ok": True,
                    "out": str(msa),
                    "out_sha256": _sha(msa),
                    "sequence_length": len(sequence),
                },
            )
        targets.append(
            {
                "binder_chain": "B",
                "id": target_id,
                "prepared_pdb": str(prepared),
                "target_chain": "A",
                "target_fasta": str(fasta),
                "target_fasta_report": str(fasta_report),
                "target_msa": str(msa),
                "target_msa_report": str(msa_report),
                "target_sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            }
        )
    manifest = {"targets": targets}
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)
    bindings = {
        "manifest": {"path": str(manifest_path), "sha256": _sha(manifest_path)},
        "protocol": {"path": "protocol.json", "sha256": "1" * 64},
        "selection": {"path": "selection.json", "sha256": "2" * 64},
        "design_gate": {"path": "design.json", "sha256": "3" * 64},
        "plan": {"path": "plan.sh", "sha256": "4" * 64},
    }
    packet = {
        "approval_packet_ready": True,
        "bound_artifacts": bindings,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "maximum_a40_gpu_hours": 8.0,
        "no_submit": True,
        "target_count": 8,
        "target_ids": [target["id"] for target in targets],
    }
    receipt = []
    for index, target in enumerate(targets):
        receipt.append(
            {
                "job_id": str(1000 + index),
                "manifest": str(manifest_path),
                "manifest_sha256": _sha(manifest_path),
                "status": "submitted",
                "target_fasta": target["target_fasta"],
                "target_id": target["id"],
                "target_msa": target["target_msa"],
                "target_msa_report": target["target_msa_report"],
                "workstream": "m6d_w3b_target_msa_input_prep_only",
            }
        )
    summary = {
        "artifact": "m6d_w3b_target_msa_receipt_summary",
        "design_gate": "design.json",
        "design_gate_sha256": "3" * 64,
        "manifest": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "n_records": 8,
        "n_targets": 8,
        "plan": "plan.sh",
        "plan_sha256": "4" * 64,
        "protocol": "protocol.json",
        "protocol_sha256": "1" * 64,
        "selection": "selection.json",
        "selection_sha256": "2" * 64,
        "status_counts": {"submitted": 8},
        "target_ids": sorted(target["id"] for target in targets),
        "workstream": "m6d_w3b_target_msa_input_prep_only",
    }
    return manifest, str(manifest_path), packet, receipt, summary, targets


def _sacct(*, pending_job=None):
    lines = ["JobIDRaw|State|ExitCode|ElapsedRaw|AllocTRES|NodeList|"]
    for index in range(8):
        job_id = str(1000 + index)
        state = "RUNNING" if job_id == pending_job else "COMPLETED"
        exit_code = "0:0" if state == "COMPLETED" else "0:0"
        lines.append(
            f"{job_id}|{state}|{exit_code}|60|cpu=4,gres/gpu=1,gres/gpu:a40=1,mem=32G|g000{index % 2 + 1}|"
        )
    return "\n".join(lines) + "\n"


def _evaluate(state, *, receipt=True, sacct=None):
    manifest, manifest_path, packet, receipt_rows, summary, _targets = state
    return evaluate_lifecycle(
        manifest=manifest,
        manifest_path=manifest_path,
        packet=packet,
        receipt_rows=receipt_rows if receipt else None,
        summary=summary if receipt else None,
        sacct_text=sacct,
    )


def test_current_absent_receipt_is_coherent_no_submit_state(tmp_path):
    report = _evaluate(_fixture(tmp_path, with_msas=False), receipt=False)

    assert report["status"] == "target_msa_not_submitted_awaiting_explicit_approval"
    assert report["audit_ok"] is True
    assert report["completion_ok"] is False
    assert report["explicit_approval_still_required"] is True
    assert report["can_submit_candidate_generation_or_candidate_level_prediction"] is False


def test_eight_completed_a40_jobs_and_strict_inputs_complete(tmp_path):
    report = _evaluate(_fixture(tmp_path), sacct=_sacct())

    assert report["status"] == "target_msa_precompute_complete_8_of_8"
    assert report["audit_ok"] is True
    assert report["completion_ok"] is True
    assert report["jobs_terminal_success"] is True
    assert len(report["target_artifacts"]) == 8
    assert report["gpu_allocation_seconds"] == 480
    assert report["within_gpu_budget"] is True
    assert report["can_run_post_msa_design_gate"] is True
    assert report["can_submit_candidate_generation_or_candidate_level_prediction"] is False


def test_pending_job_waits_without_claiming_completion(tmp_path):
    report = _evaluate(_fixture(tmp_path), sacct=_sacct(pending_job="1003"))

    assert report["status"] == "target_msa_jobs_pending"
    assert report["audit_ok"] is True
    assert report["completion_ok"] is False
    assert report["jobs_terminal_success"] is False
    assert report["requirements"] == ["all submitted target-MSA jobs reach COMPLETED/0:0"]


def test_stale_msa_report_hash_fails_closed(tmp_path):
    state = _fixture(tmp_path)
    msa = tmp_path / "T2" / "target.a3m"
    msa.write_text(msa.read_text() + ">new-hit\nACDEFG\n")
    report = _evaluate(state, sacct=_sacct())

    assert report["status"] == "target_msa_lifecycle_blocked"
    assert report["audit_ok"] is False
    assert "target_msa_report_mismatch" in report["strict_manifest"]["failures_by_kind"]


def test_fasta_a3m_query_mismatch_and_scope_expansion_fail_closed(tmp_path):
    state = _fixture(tmp_path)
    manifest, _manifest_path, packet, _receipt, _summary, _targets = state
    msa = tmp_path / "T4" / "target.a3m"
    msa.write_text(">T4\nCCCCCC\n")
    report_data = json.loads((tmp_path / "T4" / "target.a3m.report.json").read_text())
    report_data["out_sha256"] = _sha(msa)
    _write_json(tmp_path / "T4" / "target.a3m.report.json", report_data)
    packet["can_submit_candidate_generation_or_candidate_level_prediction"] = True
    report = _evaluate(state, sacct=_sacct())

    assert report["status"] == "target_msa_lifecycle_blocked"
    kinds = {failure["kind"] for failure in report["failures"]}
    assert "approval_scope_expanded" in kinds
    packet["can_submit_candidate_generation_or_candidate_level_prediction"] = False
    report = _evaluate(state, sacct=_sacct())
    assert "target_msa_mismatch" in report["strict_manifest"]["failures_by_kind"]
