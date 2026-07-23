import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments.m6d_w3c_fresh_target_lock import (
    build_lock,
    main,
    render_markdown,
)


_CANDIDATES = "configs/m6d_w3c_fresh_target_candidates.json"
_OVERLAP = "configs/m6d_w3c_historical_overlap_registry.json"
_PROTOCOL = "configs/m6d_w3c_validity_first_protocol.json"
_FIXTURE = "tests/fixtures/m6d_w3c_fresh_structure_fixture.json"


def _build(**kwargs):
    return build_lock(
        _CANDIDATES,
        _OVERLAP,
        _PROTOCOL,
        _FIXTURE,
        **kwargs,
    )


def test_public_fixture_builds_exact_eight_target_lock():
    output = _build()
    report = output["report"]
    manifest = output["manifest"]

    assert report["audit_ok"] is True
    assert report["status"] == "w3c_a_fresh_target_representation_lock_complete_no_submit"
    assert report["summary"]["locked_targets"] == 8
    assert report["summary"]["minimum_ca_contact_pairs"] >= 20
    assert len(set(report["summary"]["source_rcsb_ids"])) == 8
    assert all(report["checks"].values())
    assert all(all(row["checks"].values()) for row in report["targets"])
    assert manifest["target_count"] == 8
    assert manifest["target_msa_queries_authorized"] == 0
    assert manifest["proteinmpnn_designs"] == 0
    assert manifest["predictor_evaluations"] == 0
    assert manifest["cayuga_submission_allowed"] is False
    assert "representation validity" in render_markdown(report)


def test_lock_rejects_candidate_config_fixture_drift(tmp_path):
    candidates = json.loads(Path(_CANDIDATES).read_text())
    candidates["targets"][0]["semantic_rationale"] += " changed"
    changed = tmp_path / "changed_candidates.json"
    changed.write_text(json.dumps(candidates, indent=2) + "\n")

    with pytest.raises(ValueError, match="fixture_candidate_binding"):
        build_lock(str(changed), _OVERLAP, _PROTOCOL, _FIXTURE)


def test_lock_rejects_historical_target_sequence_overlap(tmp_path):
    overlap = json.loads(Path(_OVERLAP).read_text())
    selected_hash = json.loads(Path(_FIXTURE).read_text())["targets"][0][
        "selected_sequences"
    ]["target_sequence_sha256"]
    overlap["excluded_target_sequence_sha256"].append(selected_hash)
    changed = tmp_path / "changed_overlap.json"
    changed.write_text(json.dumps(overlap, indent=2) + "\n")

    with pytest.raises(ValueError, match="fresh_target_sequence"):
        build_lock(_CANDIDATES, str(changed), _PROTOCOL, _FIXTURE)


def test_cli_public_replay_writes_no_submit_artifacts(tmp_path):
    out_manifest = tmp_path / "manifest.json"
    out_json = tmp_path / "lock.json"
    out_md = tmp_path / "lock.md"
    result = main(
        [
            "--out-manifest",
            str(out_manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert result == 0
    report = json.loads(out_json.read_text())
    assert report["inputs"]["local_source_pdbs_verified"] is False
    assert report["inputs"]["locked_manifest"]["sha256"]
    assert report["target_msa_queries_authorized"] == 0
    assert report["cayuga_submission_allowed"] is False
    assert out_md.read_text().startswith("# M6d W3c-A")


def test_cli_refuses_unverified_canonical_overwrite():
    canonical = Path("results/m6d_w3c_fresh_target_lock.json")
    before = canonical.read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert canonical.read_bytes() == before
