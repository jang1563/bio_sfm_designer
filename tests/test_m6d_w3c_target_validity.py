import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3c_target_validity import (
    build_audit,
    build_structure_fixture,
    main,
    render_markdown,
)


def _ca(serial, chain, residue, x, y, z):
    return (
        "ATOM  %5d  CA  ALA %s%4d    %8.3f%8.3f%8.3f  1.00 50.00           C\n"
        % (serial, chain, residue, x, y, z)
    )


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _write_pdb(path: Path, *, title, molecules, unit, assembly_chains, coordinates):
    lines = [f"TITLE     {title}\n"]
    for molecule_id, name, chains in molecules:
        lines.append(f"COMPND    MOL_ID: {molecule_id};\n")
        lines.append(f"COMPND    MOLECULE: {name};\n")
        lines.append(f"COMPND    CHAIN: {', '.join(chains)};\n")
    lines.extend(
        [
            "REMARK 350 BIOMOLECULE: 1\n",
            f"REMARK 350 AUTHOR DETERMINED BIOLOGICAL UNIT: {unit}\n",
            f"REMARK 350 APPLY THE FOLLOWING TO CHAINS: {', '.join(assembly_chains)}\n",
        ]
    )
    serial = 1
    for chain, y in coordinates:
        for residue in range(1, 41):
            x = (residue - 1) * 3.8
            lines.append(_ca(serial, chain, residue, x, y, 0.0))
            serial += 1
    lines.append("END\n")
    path.write_text("".join(lines))


def _fixture(tmp_path: Path):
    pass_pdb = tmp_path / "pass.pdb"
    truncated_pdb = tmp_path / "truncated.pdb"
    semantic_fail_pdb = tmp_path / "semantic_fail.pdb"
    _write_pdb(
        pass_pdb,
        title="TARGET BINDER DIMER",
        molecules=[("1", "TARGET", ["A"]), ("2", "BINDER", ["B"])],
        unit="DIMERIC",
        assembly_chains=["A", "B"],
        coordinates=[("A", 0.0), ("B", 5.0)],
    )
    _write_pdb(
        truncated_pdb,
        title="TARGET BINDER TRIMER",
        molecules=[
            ("1", "TARGET", ["C"]),
            ("2", "BINDER", ["D"]),
            ("3", "REQUIRED PARTNER", ["E"]),
        ],
        unit="TRIMERIC",
        assembly_chains=["C", "D", "E"],
        coordinates=[("C", 0.0), ("D", 5.0), ("E", 10.0)],
    )
    _write_pdb(
        semantic_fail_pdb,
        title="INTERNAL SUBUNIT DIMER",
        molecules=[("1", "SUBUNIT", ["F", "G"])],
        unit="DIMERIC",
        assembly_chains=["F", "G"],
        coordinates=[("F", 0.0), ("G", 5.0)],
    )

    targets = [
        {
            "id": "pass_AB",
            "rcsb_id": "PASS",
            "source_pdb": str(pass_pdb),
            "target_chain": "A",
            "binder_chain": "B",
        },
        {
            "id": "truncated_CD",
            "rcsb_id": "TRUN",
            "source_pdb": str(truncated_pdb),
            "target_chain": "C",
            "binder_chain": "D",
        },
        {
            "id": "semantic_fail_FG",
            "rcsb_id": "FAIL",
            "source_pdb": str(semantic_fail_pdb),
            "target_chain": "F",
            "binder_chain": "G",
        },
    ]
    pool = tmp_path / "pool.json"
    annotations = tmp_path / "annotations.json"
    w2b = tmp_path / "w2b.json"
    w2c = tmp_path / "w2c.json"
    w3b = tmp_path / "w3b.json"
    _write_json(pool, {"targets": targets})
    _write_json(
        annotations,
        {
            "created_after_historical_outcomes_observed": True,
            "historical_predictor_labels_used": False,
            "public_replay_structure_fixture": str(tmp_path / "structure_fixture.json"),
            "cayuga_submission_allowed": False,
            "policy": {
                "expected_representative_pool_targets": 3,
                "expected_targets_per_historical_branch": 1,
                "expected_successor_targets": 8,
                "strict_eligibility_requires_semantic_pass": True,
                "strict_eligibility_also_requires_complete_author_determined_dimer": True,
                "historical_targets_are_diagnostic_only": True,
                "successor_targets_must_be_screened_prospectively": True,
            },
            "targets": [
                {
                    "id": "pass_AB",
                    "semantic_context": "target_binder_like",
                    "semantic_verdict": "pass",
                    "rationale": "complete distinct partners",
                },
                {
                    "id": "truncated_CD",
                    "semantic_context": "incomplete_trimer",
                    "semantic_verdict": "needs_reformulation",
                    "rationale": "required partner omitted",
                },
                {
                    "id": "semantic_fail_FG",
                    "semantic_context": "internal_subunits",
                    "semantic_verdict": "out_of_scope",
                    "rationale": "not a target-binder system",
                },
            ],
        },
    )
    _write_json(w2b, {"targets": [targets[0]]})
    _write_json(w2c, {"targets": [targets[1]]})
    _write_json(w3b, {"targets": [targets[2]]})
    protocol = tmp_path / "protocol.json"
    _write_json(
        protocol,
        {
            "artifact": "m6d_w3c_validity_first_protocol",
            "version": 1,
            "status": "preregistered_target_discovery_only_no_submit",
            "target_discovery": {
                "required_targets": 8,
                "fresh_source_required": True,
                "exclude_all_historical_target_ids": True,
                "exclude_all_historical_rcsb_sources": True,
                "exclude_all_historical_target_sequence_hashes": True,
                "selection_may_use_predictor_outputs": False,
                "selection_may_use_generated_design_labels": False,
            },
            "target_validity_gate": {
                "author_determined_biological_unit": "DIMERIC",
                "selected_pair_must_be_complete_protein_assembly": True,
                "selected_chains_must_be_distinct_molecule_entities": True,
                "manual_target_binder_semantic_verdict": "pass",
                "minimum_ca_residues_per_chain": 40,
                "ca_contact_cutoff_angstrom": 8.0,
                "minimum_ca_contact_pairs": 20,
                "unreviewed_numbering_gaps_allowed": False,
                "manual_exceptions_after_predictor_output": False,
            },
            "stages": [
                {
                    "stage": "W3c-A",
                    "proteinmpnn_designs": 0,
                    "predictor_evaluations": 0,
                    "approval_required": False,
                },
                {
                    "stage": "W3c-B1",
                    "maximum_target_msa_queries": 8,
                    "proteinmpnn_designs": 0,
                    "predictor_evaluations": 0,
                    "approval_required": True,
                    "approval_status": "not_prepared",
                },
                {
                    "stage": "W3c-B2",
                    "targets": 8,
                    "native_sequences_per_target": 1,
                    "predictors": ["boltz2_complex", "af2_multimer_colabfold_v1"],
                    "maximum_predictor_evaluations": 16,
                    "proteinmpnn_designs": 0,
                    "lrmsd_success_threshold_angstrom": 4.0,
                    "minimum_targets_passing": 6,
                    "approval_required": True,
                    "approval_status": "not_prepared",
                },
            ],
            "post_native_boundary": {
                "generator_protocol_prepared": False,
                "trust_gate_protocol_prepared": False,
                "certification_protocol_prepared": False,
                "native_screen_may_select_gate_thresholds": False,
                "native_screen_may_select_generator_settings": False,
                "next_protocol_requires_separate_preregistration": True,
                "next_compute_requires_separate_exact_approval": True,
            },
            "runtime_boundary": {
                "w3b_runtime_may_transfer_only_by_exact_hash_match": True,
                "new_runtime_observation_required": True,
                "new_budget_lock_required_before_approval": True,
                "prediction_time_network_allowed": False,
                "templates_allowed": False,
                "seed": 0,
            },
            "claim_boundary": {
                "target_discovery_supports_binder_design_claim": False,
                "native_screen_supports_generator_claim": False,
                "native_screen_supports_trust_gate_claim": False,
                "native_screen_supports_biological_binder_success_claim": False,
            },
            "no_submit": True,
            "cayuga_submission_allowed": False,
        },
    )
    structure_fixture = tmp_path / "structure_fixture.json"
    _write_json(structure_fixture, build_structure_fixture(str(pool)))
    return pool, annotations, w2b, w2c, w3b, protocol, structure_fixture


def test_build_audit_separates_structure_and_semantics(tmp_path):
    paths = _fixture(tmp_path)
    report = build_audit(
        *(str(path) for path in paths[:5]),
        protocol_path=str(paths[5]),
        structure_fixture_path=str(paths[6]),
    )

    assert report["audit_ok"] is True
    assert report["summary"]["n_targets"] == 3
    assert report["summary"]["n_structurally_complete_two_chain"] == 2
    assert report["summary"]["n_strict_target_binder_eligible"] == 1
    assert report["summary"]["strict_target_binder_eligible_ids"] == ["pass_AB"]
    assert report["historical_branch_summary"]["W2b"]["n_strict_target_binder_eligible"] == 1
    assert report["historical_branch_summary"]["W2c"]["n_structurally_complete_two_chain"] == 0
    assert report["historical_branch_summary"]["W3b"]["n_structurally_complete_two_chain"] == 1

    by_id = {row["target_id"]: row for row in report["targets"]}
    truncated = by_id["truncated_CD"]
    assert truncated["omitted_protein_chains"] == ["E"]
    assert truncated["omitted_chain_interfaces"][0]["ca_contact_pairs"] > 0
    assert truncated["strict_target_binder_eligible"] is False
    assert by_id["semantic_fail_FG"]["selected_chains_share_molecule_entity"] is True
    assert "do not estimate" in report["historical_claim_reset"]
    assert "No compute" in render_markdown(report)


def test_build_audit_replays_without_local_source_pdbs(tmp_path):
    paths = _fixture(tmp_path)
    pool = json.loads(paths[0].read_text())
    for target in pool["targets"]:
        Path(target["source_pdb"]).unlink()

    report = build_audit(
        *(str(path) for path in paths[:5]),
        protocol_path=str(paths[5]),
        structure_fixture_path=str(paths[6]),
    )

    assert report["audit_ok"] is True
    assert report["inputs"]["local_source_pdbs_verified"] is False
    assert report["summary"]["n_strict_target_binder_eligible"] == 1


def test_build_audit_rejects_structure_fixture_pool_drift(tmp_path):
    paths = _fixture(tmp_path)
    fixture = json.loads(paths[6].read_text())
    fixture["pool_manifest_sha256"] = "0" * 64
    _write_json(paths[6], fixture)

    with pytest.raises(ValueError, match="structure_fixture_pool_binding_exact"):
        build_audit(
            *(str(path) for path in paths[:5]),
            protocol_path=str(paths[5]),
            structure_fixture_path=str(paths[6]),
        )


def test_build_audit_rejects_annotation_drift(tmp_path):
    paths = list(_fixture(tmp_path))
    annotations = json.loads(paths[1].read_text())
    annotations["targets"].pop()
    _write_json(paths[1], annotations)

    with pytest.raises(ValueError, match="semantic_annotations_exact"):
        build_audit(
            *(str(path) for path in paths[:5]),
            protocol_path=str(paths[5]),
            structure_fixture_path=str(paths[6]),
        )


def test_cli_writes_json_and_markdown(tmp_path):
    paths = _fixture(tmp_path)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    result = main(
        [
            "--pool-manifest",
            str(paths[0]),
            "--semantic-annotations",
            str(paths[1]),
            "--w2b-manifest",
            str(paths[2]),
            "--w2c-manifest",
            str(paths[3]),
            "--w3b-manifest",
            str(paths[4]),
            "--protocol",
            str(paths[5]),
            "--structure-fixture",
            str(paths[6]),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert result == 0
    assert json.loads(out_json.read_text())["audit_ok"] is True
    assert "strict target-binder eligible" in out_md.read_text()
