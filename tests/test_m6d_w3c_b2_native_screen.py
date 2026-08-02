import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3c_b2_native_screen as mod


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sequence_sha(sequence):
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _write_pdb(path, target_chain, binder_chain, target_sequence, binder_sequence):
    aa = {"A": "ALA", "G": "GLY"}
    lines = []
    atom_id = 1
    for chain, sequence, y in (
        (target_chain, target_sequence, 0.0),
        (binder_chain, binder_sequence, 4.0),
    ):
        for residue_id, residue in enumerate(sequence, 1):
            lines.append(
                f"ATOM  {atom_id:5d}  CA  {aa[residue]:>3} {chain}{residue_id:4d}    "
                f"{float(residue_id):8.3f}{y:8.3f}{0.0:8.3f}  1.00 20.00           C\n"
            )
            atom_id += 1
    lines.append("END\n")
    Path(path).write_text("".join(lines))


def _protocol():
    return {
        "artifact": "m6d_w3c_validity_first_protocol",
        "version": 1,
        "status": "preregistered_target_discovery_only_no_submit",
        "scientific_question": "Can both frozen predictors recover native complexes?",
        "stages": [
            {
                "stage": "W3c-B2",
                "name": "native dual-predictor recoverability screen",
                "compute": "Cayuga H100",
                "targets": 8,
                "native_sequences_per_target": 1,
                "predictors": mod.PREDICTOR_IDS,
                "maximum_predictor_evaluations": 16,
                "proteinmpnn_designs": 0,
                "approval_required": True,
                "approval_status": "not_prepared",
                "lrmsd_success_threshold_angstrom": 4.0,
                "minimum_targets_passing": 6,
                "target_pass_rule": (
                    "Both predictors must produce strict-QC records with finite interface "
                    "pAE and L-RMSD below 4.0 A against the native complex."
                ),
            }
        ],
        "runtime_boundary": {
            "w3b_runtime_may_transfer_only_by_exact_hash_match": True,
            "new_runtime_observation_required": True,
            "new_budget_lock_required_before_approval": True,
            "prediction_time_network_allowed": False,
            "templates_allowed": False,
            "seed": 0,
        },
        "claim_boundary": {
            "native_screen_supports_generator_claim": False,
            "native_screen_supports_trust_gate_claim": False,
            "native_screen_supports_biological_binder_success_claim": False,
        },
        "no_submit": True,
        "cayuga_submission_allowed": False,
    }


def _bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "validate_w3b_runtime_lock", lambda *_: [])
    protocol_path = tmp_path / "protocol.json"
    b1_manifest_path = tmp_path / "b1.json"
    completion_path = tmp_path / "completion.json"
    w3b_lock_path = tmp_path / "w3b-lock.json"
    w3b_protocol_path = tmp_path / "w3b-protocol.json"
    protocol = _protocol()
    protocol_path.write_text(json.dumps(protocol))
    w3b_protocol_path.write_text("{}")
    predictor_digests = {
        "boltz2_complex": "1" * 64,
        "af2_multimer_colabfold_v1": "2" * 64,
    }
    w3b_lock = {
        "runtime_lock_digest_sha256": "3" * 64,
        "predictor_runtime_identity_sha256": predictor_digests,
    }
    w3b_lock_path.write_text(json.dumps(w3b_lock))
    targets = []
    completion_rows = []
    for index, target_id in enumerate(mod.TARGET_IDS):
        root = tmp_path / target_id
        root.mkdir()
        target_sequence = "A" * (40 + index)
        binder_sequence = "G" * (41 + index)
        prepared_pdb = root / "prepared.pdb"
        target_fasta = root / "target.fasta"
        target_msa = root / "target.a3m"
        target_msa_report = root / "target.a3m.report.json"
        _write_pdb(
            prepared_pdb,
            "A",
            "B",
            target_sequence,
            binder_sequence,
        )
        target_fasta.write_text(f">{target_id}\n{target_sequence}\n")
        target_msa.write_text(
            f">query\n{target_sequence}\n>hit\n{target_sequence}\n"
        )
        target_msa_report.write_text("{}")
        targets.append({
            "id": target_id,
            "rcsb_id": target_id[:4],
            "target_chain": "A",
            "binder_chain": "B",
            "prepared_pdb": str(prepared_pdb),
            "source_pdb": f"sources/{target_id}.pdb",
            "source_pdb_sha256": "4" * 64,
            "target_fasta": str(target_fasta),
            "target_msa": str(target_msa),
            "target_msa_report": str(target_msa_report),
            "target_sequence_sha256": _sequence_sha(target_sequence),
            "binder_sequence_sha256": _sequence_sha(binder_sequence),
        })
        completion_rows.append({
            "target_id": target_id,
            "target_sequence_sha256": _sequence_sha(target_sequence),
            "target_msa_sha256": _sha(target_msa),
            "target_msa_report_sha256": _sha(target_msa_report),
            "checks": {"strict": True},
        })
    b1_manifest = {
        "artifact": "m6d_w3c_b1_target_msa_manifest",
        "version": 1,
        "target_count": 8,
        "target_ids": mod.TARGET_IDS,
        "targets": targets,
    }
    b1_manifest_path.write_text(json.dumps(b1_manifest))
    completion = {
        "artifact": "m6d_w3c_b1_target_msa_completion",
        "version": 1,
        "status": "target_msa_precompute_complete_8_of_8",
        "audit_ok": True,
        "completion_ok": True,
        "target_ids": mod.TARGET_IDS,
        "n_target_msas": 8,
        "strict_manifest_ready_targets": 8,
        "can_prepare_w3c_b2_packet": True,
        "can_submit_w3c_b2": False,
        "failures": [],
        "input_bindings": {
            "execution_manifest": {
                "path": str(b1_manifest_path),
                "sha256": _sha(b1_manifest_path),
            }
        },
        "target_artifacts": completion_rows,
    }
    completion_path.write_text(json.dumps(completion))
    return {
        "protocol": protocol,
        "protocol_path": str(protocol_path),
        "b1_manifest": b1_manifest,
        "b1_manifest_path": str(b1_manifest_path),
        "completion": completion,
        "completion_path": str(completion_path),
        "w3b_lock": w3b_lock,
        "w3b_lock_path": str(w3b_lock_path),
        "w3b_protocol_path": str(w3b_protocol_path),
    }


def _manifest(bundle, tmp_path):
    return mod.build_native_manifest(
        bundle["protocol"],
        bundle["b1_manifest"],
        bundle["completion"],
        bundle["w3b_lock"],
        protocol_path=bundle["protocol_path"],
        b1_manifest_path=bundle["b1_manifest_path"],
        b1_completion_path=bundle["completion_path"],
        w3b_runtime_lock_path=bundle["w3b_lock_path"],
        w3b_protocol_path=bundle["w3b_protocol_path"],
        output_root=str(tmp_path / "outputs"),
    )


def _runtime_lock(manifest):
    return {
        "artifact": "m6d_w3c_b2_runtime_lock",
        "version": 1,
        "status": "w3c_b2_dual_predictor_runtime_reobserved_no_prediction",
        "audit_ok": True,
        "predictor_runtime_identity_sha256": manifest["runtime_contract"][
            "expected_predictor_runtime_identity_sha256"
        ],
        "new_runtime_observations": 2,
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "network_fetch_executed": False,
        "submitted_jobs": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_run_predictors": False,
        "can_claim_native_recoverability": False,
        "failures": [],
    }


def _records(manifest, runtime_lock, passing_targets=6):
    rows = []
    digests = runtime_lock["predictor_runtime_identity_sha256"]
    for target_index, target in enumerate(manifest["targets"]):
        for predictor_id in mod.PREDICTOR_IDS:
            success = target_index < passing_targets
            lrmsd = 2.0 if success else 5.0
            rows.append({
                "artifact": "m6d_w3c_b2_native_prediction_record",
                "version": 1,
                "status": "strict_qc_complete",
                "record_id": (
                    f"w3c-b2-native-{target['target_id']}-{predictor_id}"
                ),
                "native_candidate_id": target["native_candidate_id"],
                "complex_target_id": target["target_id"],
                "predictor_id": predictor_id,
                "target_sequence_sha256": target["target_sequence_sha256"],
                "binder_sequence_sha256": target["binder_sequence_sha256"],
                "target_msa_sha256": target["target_msa_sha256"],
                "reference_backbone_sha256": target["prepared_pdb_sha256"],
                "runtime_identity_sha256": digests[predictor_id],
                "seed": 0,
                "templates_used": False,
                "prediction_time_network_used": False,
                "interface_pae": 3.0,
                "lrmsd_angstrom": lrmsd,
                "lrmsd_threshold_angstrom": 4.0,
                "success": success,
                "strict_qc_passed": True,
                "output_bindings": {
                    "model": {"path": "model.pdb", "sha256": "a" * 64},
                    "confidence": {"path": "scores.json", "sha256": "b" * 64},
                },
            })
    return rows


def test_build_native_manifest_locks_exact_no_submit_scope(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, monkeypatch)
    manifest = _manifest(bundle, tmp_path)

    assert manifest["target_ids"] == mod.TARGET_IDS
    assert manifest["predictor_ids"] == mod.PREDICTOR_IDS
    assert manifest["maximum_predictor_evaluations"] == 16
    assert manifest["compute_budget"]["maximum_h100_gpu_hours"] == 16.0
    assert manifest["predictor_evaluations_authorized"] == 0
    assert manifest["runtime_contract"]["runtime_reobservation_complete"] is False
    assert manifest["no_submit"] is True
    assert all(row["checks"]["minimum_chain_lengths"] for row in manifest["targets"])


def test_build_native_manifest_fails_closed_on_msa_query_drift(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, monkeypatch)
    target = bundle["b1_manifest"]["targets"][0]
    Path(target["target_msa"]).write_text(">query\nGGGG\n>hit\nGGGG\n")
    bundle["completion"]["target_artifacts"][0]["target_msa_sha256"] = _sha(
        target["target_msa"]
    )

    with pytest.raises(ValueError, match="msa_query"):
        _manifest(bundle, tmp_path)


def test_evaluator_passes_only_at_six_dual_predictor_targets(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, monkeypatch)
    manifest = _manifest(bundle, tmp_path)
    runtime_lock = _runtime_lock(manifest)
    report = mod.evaluate_records(
        manifest,
        runtime_lock,
        _records(manifest, runtime_lock, passing_targets=6),
    )

    assert report["audit_ok"] is True
    assert report["stage_pass"] is True
    assert report["targets_passing"] == 6
    assert report["can_claim_native_recoverability_on_locked_panel"] is True
    assert report["can_claim_generator_yield"] is False


def test_evaluator_stops_cleanly_below_six_targets(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, monkeypatch)
    manifest = _manifest(bundle, tmp_path)
    runtime_lock = _runtime_lock(manifest)
    report = mod.evaluate_records(
        manifest,
        runtime_lock,
        _records(manifest, runtime_lock, passing_targets=5),
    )

    assert report["audit_ok"] is True
    assert report["stage_pass"] is False
    assert report["status"] == "w3c_b2_native_recoverability_stop"
    assert report["targets_passing"] == 5


def test_evaluator_fails_closed_on_threshold_or_record_drift(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, monkeypatch)
    manifest = _manifest(bundle, tmp_path)
    runtime_lock = _runtime_lock(manifest)
    records = _records(manifest, runtime_lock, passing_targets=6)
    records[0]["lrmsd_angstrom"] = 4.0
    records[0]["success"] = True
    report = mod.evaluate_records(manifest, runtime_lock, records)

    assert report["audit_ok"] is False
    assert report["stage_pass"] is False
    assert any(row["kind"] == "record_contract_invalid" for row in report["failures"])


def test_committed_manifest_preserves_public_no_submit_boundary():
    path = Path("configs/m6d_w3c_b2_native_screen_manifest.json")
    manifest = json.loads(path.read_text())

    assert manifest["artifact"] == "m6d_w3c_b2_native_screen_manifest"
    assert manifest["target_ids"] == mod.TARGET_IDS
    assert manifest["predictor_ids"] == mod.PREDICTOR_IDS
    assert manifest["predictor_evaluations_authorized"] == 0
    assert manifest["prediction_executed"] is False
    assert manifest["no_submit"] is True
    assert manifest["cayuga_submission_allowed"] is False
