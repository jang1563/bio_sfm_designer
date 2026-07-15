"""Tests for descriptive W3b fit-stop diagnostics."""

from bio_sfm_designer.experiments.m6d_w3b_fit_diagnostics import (
    diagnose_prepared_rows,
)


def test_all_wrong_required_target_proves_frozen_fit_impossible():
    rows = []
    for target_index, target_id in enumerate(("A", "B", "C")):
        for row_index in range(60):
            wrong = target_id == "A"
            boltz_pae = float(target_index * 10 + row_index + 1)
            af2_pae = boltz_pae + 0.5
            rows.append({
                "target_id": target_id,
                "candidate_id": f"{target_id}-{row_index}",
                "role": "fit",
                "wrong": {
                    "boltz2_complex": wrong,
                    "af2_multimer_colabfold_v1": wrong,
                },
                "boltz_pae": boltz_pae,
                "af2_pae": af2_pae,
                "max_pae": af2_pae,
                "pae_gap": 0.5,
                "boltz_lrmsd": 5.0 if wrong else 2.0,
                "af2_lrmsd": 6.0 if wrong else 2.5,
            })
    fit = {
        "minimum_total_accepted": 90,
        "minimum_accepted_per_target": 15,
        "maximum_empirical_false_accept_rate_per_predictor": 0.08,
    }

    report = diagnose_prepared_rows(rows, fit)

    assert report["frozen_fit_mathematically_impossible"] is True
    assert len(report["impossibility_proofs"]) == 2
    for proof in report["impossibility_proofs"]:
        assert proof["target_id"] == "A"
        assert proof["minimum_possible_global_false_accept_rate"] == 15 / 180
        assert proof["violates_cap_even_if_all_rows_accepted"] is True
    primary = report["exhaustive_threshold_diagnostics"]["primary"]
    comparator = report["exhaustive_threshold_diagnostics"]["comparator"]
    assert primary["best_risk_subject_to_frozen_coverage"][
        "worst_false_accept_rate"
    ] > 0.08
    assert comparator["best_risk_subject_to_frozen_coverage"][
        "worst_false_accept_rate"
    ] > 0.08
