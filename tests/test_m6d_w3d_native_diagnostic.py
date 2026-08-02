import copy
import json
from pathlib import Path

import pytest

from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as mod


def _load_protocol():
    return json.loads(Path(mod.PROTOCOL_PATH).read_text())


def _build(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    readiness_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness.md"
    readiness = mod.run(
        manifest_path=str(manifest_path),
        readiness_path=str(readiness_path),
        readiness_md_path=str(markdown_path),
    )
    manifest = json.loads(manifest_path.read_text())
    return manifest, readiness, markdown_path.read_text()


def _prospective_rows(manifest, successes):
    rows = []
    for cell in manifest["cells"]:
        if cell["cell_status"] != "prospective_not_authorized":
            continue
        key = (cell["representation_id"], cell["predictor_id"])
        rows.append({
            "target_id": cell["target_id"],
            "representation_id": cell["representation_id"],
            "predictor_id": cell["predictor_id"],
            "success": cell["target_id"] in successes.get(key, set()),
        })
    return rows


def test_run_locks_exact_factorial_scope_without_authority(tmp_path):
    manifest, readiness, markdown = _build(tmp_path)

    assert manifest["target_ids"] == mod.TARGET_IDS
    assert manifest["predictor_ids"] == mod.PREDICTOR_IDS
    assert manifest["representation_ids"] == mod.REPRESENTATION_IDS
    assert manifest["total_factorial_cells"] == 32
    assert manifest["completed_locked_baseline_cells"] == 8
    assert manifest["prospective_cells"] == 24
    assert manifest["baseline_successes"] == 2
    assert manifest["baseline_success_target_ids"] == ["5E5M_AB", "5JSB_AB"]
    assert readiness["source_hashes_verified"] == len(mod.SOURCE_PATHS)
    assert readiness["posthoc_disclosure_complete"] is True
    assert readiness["decision_rules_locked"] is True
    assert readiness["input_producer_implemented"] is True
    assert readiness["materialized_input_hashes_verified"] == 24
    assert readiness["representation_semantics_verified"] == 24
    assert readiness["new_runtime_wrappers_implemented"] is True
    assert readiness["wrapper_static_no_prediction_validation_complete"] is True
    assert readiness["no_prediction_runtime_validation_complete"] is True
    assert readiness["execution_ready"] is False
    assert readiness["predictor_evaluations_authorized"] == 0
    assert readiness["h100_gpu_hours_authorized"] == 0.0
    assert readiness["proteinmpnn_designs"] == 0
    assert readiness["api_calls"] == 0
    assert readiness["no_submit"] is True
    assert "retrospective-baseline/prospective-completion" in markdown


def test_protocol_rejects_posthoc_filtering_or_authority_escalation():
    protocol = _load_protocol()
    protocol["design_disclosure"][
        "target_or_record_filtering_after_baseline_outcomes_allowed"
    ] = True
    with pytest.raises(ValueError, match="post-hoc"):
        mod.validate_protocol(protocol)

    protocol = _load_protocol()
    protocol["authority"]["predictor_evaluations_authorized"] = 24
    protocol["authority"]["submission_allowed"] = True
    with pytest.raises(ValueError, match="authority"):
        mod.validate_protocol(protocol)


def test_protocol_rejects_decision_threshold_drift():
    protocol = _load_protocol()
    protocol["decision_contract"]["strong_directional_contrast"][
        "favored_only_minimum_targets"
    ] = 3
    with pytest.raises(ValueError, match="decision"):
        mod.validate_protocol(protocol)


def test_run_rejects_source_hash_drift(tmp_path):
    protocol = _load_protocol()
    protocol["source_bindings"]["w3c_b2_boltz_records"]["sha256"] = "0" * 64
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol))

    with pytest.raises(ValueError, match="source hash drifted"):
        mod.run(
            str(protocol_path),
            manifest_path=str(tmp_path / "manifest.json"),
            readiness_path=str(tmp_path / "readiness.json"),
            readiness_md_path=str(tmp_path / "readiness.md"),
        )


def test_representation_specific_result_is_distinct_and_recovers_native_validity(
    tmp_path,
):
    manifest, _, _ = _build(tmp_path)
    low = {"5E5M_AB", "5JSB_AB"}
    high = set(mod.TARGET_IDS[:6])
    rows = _prospective_rows(
        manifest,
        {
            ("target_msa_binder_query", "af2_multimer_colabfold_v1"): low,
            ("query_only_both_chains", "boltz2_complex"): high,
            ("query_only_both_chains", "af2_multimer_colabfold_v1"): high,
        },
    )
    decision = mod.adjudicate_prospective_outcomes(manifest, rows)

    assert decision["localization"] == "representation_specific_native_recovery_failure"
    assert decision["favored_representation_id"] == "query_only_both_chains"
    assert decision["bottleneck_representation_id"] == "target_msa_binder_query"
    assert decision["native_validity_recovered"] is True
    assert decision["native_validity_recovered_representation_ids"] == [
        "query_only_both_chains"
    ]
    assert decision["candidate_generation_scientifically_reachable"] is True
    assert decision["candidate_generation_authorized"] is False


def test_predictor_specific_result_does_not_unlock_native_validity(tmp_path):
    manifest, _, _ = _build(tmp_path)
    low = {"5E5M_AB", "5JSB_AB"}
    high = set(mod.TARGET_IDS[:6])
    rows = _prospective_rows(
        manifest,
        {
            ("target_msa_binder_query", "af2_multimer_colabfold_v1"): high,
            ("query_only_both_chains", "boltz2_complex"): low,
            ("query_only_both_chains", "af2_multimer_colabfold_v1"): high,
        },
    )
    decision = mod.adjudicate_prospective_outcomes(manifest, rows)

    assert decision["localization"] == "predictor_specific_native_recovery_failure"
    assert decision["favored_predictor_id"] == "af2_multimer_colabfold_v1"
    assert decision["bottleneck_predictor_id"] == "boltz2_complex"
    assert decision["native_validity_recovered"] is False
    assert decision["candidate_generation_scientifically_reachable"] is False


def test_crossed_winners_are_classified_as_interaction(tmp_path):
    manifest, _, _ = _build(tmp_path)
    low = {"5E5M_AB", "5JSB_AB"}
    high = set(mod.TARGET_IDS[:6])
    rows = _prospective_rows(
        manifest,
        {
            ("target_msa_binder_query", "af2_multimer_colabfold_v1"): high,
            ("query_only_both_chains", "boltz2_complex"): high,
            ("query_only_both_chains", "af2_multimer_colabfold_v1"): low,
        },
    )
    decision = mod.adjudicate_prospective_outcomes(manifest, rows)

    assert decision["localization"] == "predictor_by_representation_interaction"
    assert decision["native_validity_recovered"] is False


def test_complete_case_rule_rejects_missing_or_baseline_injected_rows(tmp_path):
    manifest, _, _ = _build(tmp_path)
    rows = _prospective_rows(manifest, {})

    with pytest.raises(ValueError, match="all 24 prospective outcomes"):
        mod.adjudicate_prospective_outcomes(manifest, rows[:-1])

    injected = rows + [{
        "target_id": "1TE1_BA",
        "representation_id": "target_msa_binder_query",
        "predictor_id": "boltz2_complex",
        "success": True,
    }]
    with pytest.raises(ValueError, match="unexpected"):
        mod.adjudicate_prospective_outcomes(manifest, injected)


def test_adjudication_rejects_baseline_mutation(tmp_path):
    manifest, _, _ = _build(tmp_path)
    tampered = copy.deepcopy(manifest)
    baseline = next(
        cell
        for cell in tampered["cells"]
        if cell["cell_status"] == "completed_locked_w3c_b2_baseline"
        and cell["baseline_outcome"]["success"] is False
    )
    baseline["baseline_outcome"]["success"] = True

    with pytest.raises(ValueError, match="baseline outcomes"):
        mod.adjudicate_prospective_outcomes(tampered, _prospective_rows(tampered, {}))
