"""Integration check for the committed W3b terminal fit evidence."""

from pathlib import Path

from bio_sfm_designer.experiments.m6d_w3b_fit_completion import build_completion


ROOT = Path(__file__).resolve().parents[1]


def test_committed_w3b_fit_completion_is_terminal_and_blocks_certification(monkeypatch):
    monkeypatch.chdir(ROOT)
    report = build_completion(
        "results/m6d_w3b_fit_af2_recovery_completion.json",
        "results/m6d_w3b_fit_matched_records.jsonl",
        "results/m6d_w3b_fit_matched_record_assembly.json",
        "results/m6d_w3b_fit_gate_report.json",
        "results/m6d_w3b_fit_diagnostics.json",
    )

    assert report["status"] == "w3b_fit_complete_rule_not_found_terminal_stop"
    assert report["n_matched_records"] == 180
    assert report["fit_outcome"][
        "mathematically_impossible_under_frozen_constraints"
    ] is True
    assert report["observed_h100_allocation_seconds"] == 16641
    assert report["certification_reachable"] is False
    assert report["certification_jobs_submitted"] == 0
    assert report["can_claim_w3b"] is False
