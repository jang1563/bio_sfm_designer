"""Tests for W3d CPU input materialization and no-prediction runtime guards."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3d_input_runtime as mod
from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _af2_cell(representation_id, target_msa_text=None):
    return {
        "cell_id": f"test-{representation_id}",
        "representation_id": representation_id,
        "target_sequence_length": 4,
        "target_sequence_sha256": _sha("AAAA"),
        "binder_sequence_length": 4,
        "binder_sequence_sha256": _sha("CCCC"),
        "target_msa_records_in_input": (
            0 if target_msa_text is None else target_msa_text.count(">")
        ),
        "target_msa_sha256": (
            None if target_msa_text is None else _sha(target_msa_text)
        ),
        "external_msa_references": 0,
    }


def test_query_only_af2_contains_exactly_one_paired_query():
    payload = mod.build_query_only_a3m("AAAA", "CCCC")
    cell = _af2_cell("query_only_both_chains")

    mod._validate_af2_payload(cell, payload)

    assert payload.splitlines() == ["#4,4\t1,1", ">101\t102", "AAAACCCC"]


def test_target_msa_af2_round_trips_the_exact_frozen_msa():
    target_msa = ">query\nAAAA\n>homolog\nAA-A\n"
    payload = build_annotated_multimer_a3m(target_msa, "AAAA", "CCCC")
    cell = _af2_cell("target_msa_binder_query", target_msa)

    mod._validate_af2_payload(cell, payload)

    assert payload.count(">") == 4
    assert payload.endswith(">w3_designed_binder_query\n----CCCC\n")


def test_representation_semantic_drift_fails_closed():
    cell = _af2_cell("query_only_both_chains")
    payload = mod.build_query_only_a3m("AAAA", "CCCC")
    drifted = payload + ">unexpected_homolog\nAAAA----\n"

    with pytest.raises(ValueError, match="contains homolog rows"):
        mod._validate_af2_payload(cell, drifted)


def test_query_only_boltz_has_no_msa_or_template_reference():
    payload = mod.build_boltz_yaml(
        "AAAA", "CCCC", "query_only_both_chains"
    )
    cell = {
        "cell_id": "test-boltz",
        "representation_id": "query_only_both_chains",
        "target_sequence_length": 4,
        "target_sequence_sha256": _sha("AAAA"),
        "binder_sequence_length": 4,
        "binder_sequence_sha256": _sha("CCCC"),
        "external_msa_references": 0,
    }

    mod._validate_boltz_payload(cell, payload)

    assert payload.count("msa: empty") == 2
    assert "templates: []" in payload


def test_canonical_manifest_is_exactly_24_prospective_cells(monkeypatch):
    monkeypatch.chdir(ROOT)
    manifest = json.loads(Path(mod.INPUT_MANIFEST_PATH).read_text())

    mod.validate_input_manifest(manifest, require_files=False)

    assert len(manifest["cells"]) == 24
    assert sum(
        row["predictor_id"] == "boltz2_complex" for row in manifest["cells"]
    ) == 8
    assert sum(
        row["predictor_id"] == "af2_multimer_colabfold_v1"
        for row in manifest["cells"]
    ) == 16
    assert all(row["prediction_authorized"] is False for row in manifest["cells"])


def test_canonical_manifest_rejects_input_hash_or_authority_drift(monkeypatch):
    monkeypatch.chdir(ROOT)
    manifest = json.loads(Path(mod.INPUT_MANIFEST_PATH).read_text())
    manifest["cells"][0]["input_sha256"] = "0" * 64
    manifest["cells"][0]["prediction_authorized"] = True

    with pytest.raises(ValueError, match="input-cell contract drifted"):
        mod.validate_input_manifest(
            manifest,
            input_manifest_path="does-not-exist.json",
            require_files=False,
        )


def test_public_readiness_binds_wrappers_without_granting_compute(monkeypatch):
    monkeypatch.chdir(ROOT)
    readiness = json.loads(Path(mod.READINESS_PATH).read_text())

    mod.validate_public_readiness(readiness)

    assert readiness["materialized_input_hashes_verified"] == 24
    assert readiness["new_runtime_wrappers_implemented"] is True
    assert readiness["exact_cayuga_runtime_validation_complete"] is True
    assert readiness["execution_ready"] is False
    assert readiness["predictor_evaluations_authorized"] == 0
    assert readiness["h100_gpu_hours_authorized"] == 0.0


def test_runtime_wrappers_cannot_submit_or_predict(monkeypatch):
    monkeypatch.chdir(ROOT)
    bindings = mod._validate_wrapper_contracts()
    combined = "\n".join(
        Path(path).read_text() for path in mod.WRAPPER_PATHS.values()
    )

    assert set(bindings) == set(mod.WRAPPER_PATHS)
    for forbidden in ("sbatch", "srun", "--nv", "boltz predict", "colabfold_batch"):
        assert forbidden not in combined
    af2 = Path(mod.WRAPPER_PATHS["af2_multimer_colabfold_v1"]).read_text()
    assert '--pwd "$PROJECT_ROOT"' in af2
    assert '--bind "$PROJECT_ROOT:$PROJECT_ROOT"' in af2
    assert "--network none" in af2


def test_complete_readiness_requires_the_exact_runtime_receipt(monkeypatch):
    monkeypatch.chdir(ROOT)
    readiness = json.loads(Path(mod.READINESS_PATH).read_text())
    drifted = copy.deepcopy(readiness)
    drifted["runtime_receipt_binding"] = None

    with pytest.raises(ValueError, match="receipt binding is missing"):
        mod.validate_public_readiness(drifted)


def test_runtime_receipt_is_redacted_and_records_zero_compute(monkeypatch):
    monkeypatch.chdir(ROOT)
    receipt = json.loads(Path(mod.RUNTIME_RECEIPT_PATH).read_text())

    mod.validate_runtime_receipt(receipt)

    rendered = json.dumps(receipt, sort_keys=True)
    assert "/home/" not in rendered
    assert "/athena/" not in rendered
    assert receipt["absolute_path_probes_complete"] == 24
    assert len(receipt["path_probe_evidence"]["boltz2_complex"]) == 8
    assert len(
        receipt["path_probe_evidence"]["af2_multimer_colabfold_v1"]
    ) == 16
    assert all(
        row["raw_paths_published"] is False
        for rows in receipt["path_probe_evidence"].values()
        for row in rows
    )
    assert receipt["prediction_executed"] is False
    assert receipt["gpu_compute_executed"] is False
    assert receipt["scheduler_command_executed"] is False
    assert receipt["predictor_evaluations_authorized"] == 0


def test_probe_host_paths_cli_does_not_require_an_input_manifest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mod, "_load_jsonl", lambda _: [])
    monkeypatch.setattr(mod, "probe_host_paths", lambda _: [])
    output = tmp_path / "probes.jsonl"

    rc = mod.main([
        "probe-host-paths",
        "--path-plan",
        str(tmp_path / "plan.jsonl"),
        "--out",
        str(output),
    ])

    assert rc == 0
    assert output.read_text() == ""
