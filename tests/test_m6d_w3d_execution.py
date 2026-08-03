"""Tests for W3d prospective cell execution and strict-QC conversion."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from bio_sfm_designer.experiments import m6d_w3d_execution as mod


ROOT = Path(__file__).resolve().parents[1]


def _context(tmp_path: Path, predictor_id: str):
    root = tmp_path.resolve()
    representation_id = "query_only_both_chains"
    cell_id = f"w3d-test-{representation_id}-{predictor_id}"
    input_name = "w3d.yaml" if predictor_id == "boltz2_complex" else f"{cell_id}.a3m"
    input_path = root / "hpc_outputs/m6d_w3d_native_diagnostic/test/input" / input_name
    input_path.parent.mkdir(parents=True)
    input_path.write_text("input\n")
    reference = root / "hpc_outputs/m6d_w3c_b1_targets/test/reference.pdb"
    reference.parent.mkdir(parents=True)
    reference.write_text("ATOM\n")
    runtime_receipt = root / "runtime.json"
    runtime_receipt.write_text("{}\n")
    output_dir = root / "hpc_outputs/m6d_w3d_native_diagnostic/test/prediction"
    record_path = root / "hpc_outputs/m6d_w3d_native_diagnostic/test/strict_qc_record.json"
    cell = {
        "cell_id": cell_id,
        "target_id": "test",
        "representation_id": representation_id,
        "predictor_id": predictor_id,
        "target_sequence_length": 2,
        "binder_sequence_length": 2,
        "target_sequence_sha256": "a" * 64,
        "binder_sequence_sha256": "b" * 64,
        "target_msa_sha256": None,
        "input_path": input_path.relative_to(root).as_posix(),
        "input_bytes": input_path.stat().st_size,
        "input_sha256": mod.input_runtime.sha256_file(input_path),
        "planned_output_dir": output_dir.relative_to(root).as_posix(),
        "planned_record": record_path.relative_to(root).as_posix(),
        "runtime_identity_sha256": "c" * 64,
    }
    return {
        "project_root": root,
        "runtime_receipt_path": runtime_receipt,
        "cell": cell,
        "target": {
            "target_id": "test",
            "target_chain": "A",
            "binder_chain": "B",
            "prepared_pdb_sha256": mod.input_runtime.sha256_file(reference),
        },
        "input_path": input_path,
        "output_dir": output_dir,
        "record_path": record_path,
        "reference_path": reference,
    }


def test_committed_cell_context_validates_without_raw_files(monkeypatch):
    monkeypatch.chdir(ROOT)

    context = mod.load_cell_context(
        "1TE1_BA",
        "query_only_both_chains",
        "boltz2_complex",
        require_files=False,
    )

    assert context["cell"]["cell_id"] == (
        "w3d-1TE1_BA-query_only_both_chains-boltz2_complex"
    )
    assert context["cell"]["prediction_authorized"] is False


def test_retrospective_baseline_cell_cannot_be_loaded(monkeypatch):
    monkeypatch.chdir(ROOT)

    with pytest.raises(ValueError, match="missing or duplicated"):
        mod.load_cell_context(
            "1TE1_BA",
            "target_msa_binder_query",
            "boltz2_complex",
            require_files=False,
        )


def test_run_boltz_uses_frozen_command_and_writes_one_record(monkeypatch, tmp_path):
    context = _context(tmp_path, "boltz2_complex")
    monkeypatch.setattr(mod, "validate_runtime_observation_file", lambda *args: {})
    monkeypatch.setattr(mod, "_strict_metrics", lambda *args: (3.25, 2.5))
    observed = {}

    def fake_run(command, check):
        observed["command"] = command
        observed["check"] = check
        staging = Path(command[command.index("--out_dir") + 1])
        root = staging / "boltz_results_test/predictions/w3d"
        root.mkdir(parents=True)
        (root / "w3d_model_0.pdb").write_text("ATOM\n")
        (root / "confidence_w3d_model_0.json").write_text(json.dumps({
            "complex_plddt": 0.8,
            "ptm": 0.7,
            "iptm": 0.6,
        }))
        np.savez(root / "pae_w3d_model_0.npz", np.ones((4, 4)))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    record = mod.run_boltz(
        context,
        runtime_observation_path="runtime.json",
        boltz_bin="/bin/boltz",
    )

    assert observed["check"] is True
    assert "--no_kernels" in observed["command"]
    assert observed["command"][observed["command"].index("--sampling_steps") + 1] == "100"
    assert record["strict_qc_passed"] is True
    assert record["success"] is True
    assert context["record_path"].is_file()


def test_convert_af2_writes_representation_bound_record(monkeypatch, tmp_path):
    context = _context(tmp_path, "af2_multimer_colabfold_v1")
    monkeypatch.setattr(mod, "validate_runtime_observation_file", lambda *args: {})
    monkeypatch.setattr(mod, "_strict_metrics", lambda *args: (4.5, 6.0))
    context["output_dir"].mkdir(parents=True)
    candidate_id = context["input_path"].stem
    tag = "rank_001_alphafold2_multimer_v3_model_1_seed_000"
    (context["output_dir"] / f"{candidate_id}_unrelaxed_{tag}.pdb").write_text("ATOM\n")
    (context["output_dir"] / f"{candidate_id}_scores_{tag}.json").write_text(
        json.dumps({
            "pae": np.ones((4, 4)).tolist(),
            "plddt": [80.0] * 4,
            "ptm": 0.7,
            "iptm": 0.6,
        })
    )

    record = mod.convert_af2(context, runtime_observation_path="runtime.json")

    assert record["representation_id"] == "query_only_both_chains"
    assert record["strict_qc_passed"] is True
    assert record["success"] is False
    assert record["ligand_rmsd_angstrom"] == 6.0
    assert context["record_path"].is_file()
