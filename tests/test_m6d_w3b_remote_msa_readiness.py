"""Tests for the no-submit W3b Cayuga readiness audit."""

from bio_sfm_designer.experiments.m6d_w3b_remote_msa_readiness import evaluate_readiness


def _packet():
    return {
        "approval_packet_ready": True,
        "no_submit": True,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "target_ids": ["T1", "T2"],
    }


def _observed():
    return {
        "exact": {
            "a.json": {"exists": True, "bytes": 3, "sha256": "a" * 64},
            "run.sh": {"exists": True, "bytes": 4, "sha256": "b" * 64},
        },
        "shell_syntax_returncodes": {"run.sh": 0},
        "runtime": {
            "boltz_python_executable": True,
            "boltz_cli_executable": True,
            "lifecycle_module_importable": True,
            "sbatch_available": True,
        },
        "receipt_state": {
            "receipt_before": False,
            "summary_before": False,
            "receipt_after": False,
            "summary_after": False,
        },
        "dry_run": {
            "returncode": 0,
            "no_scheduler_message_seen": True,
            "exact_target_line_seen": True,
            "stdout_sha256": "c" * 64,
            "stderr_tail": "",
        },
        "postsubmit_query_refusal": {
            "returncode": 2,
            "receipt_absence_message_seen": True,
            "sacct_before": False,
            "sacct_after": False,
            "stderr_tail": "",
        },
    }


def test_ready_observations_preserve_explicit_approval_boundary():
    report = evaluate_readiness(
        packet=_packet(),
        expected=[
            {"path": "a.json", "sha256": "a" * 64},
            {"path": "run.sh", "sha256": "b" * 64},
        ],
        observed=_observed(),
        remote_host="hpc-login-host",
        remote_root_label="$HOME/bio_sfm_smoke",
        observed_at_utc="2026-07-14T00:00:00Z",
    )

    assert report["status"] == "w3b_target_msa_remote_ready_awaiting_explicit_approval"
    assert report["audit_ok"] is True
    assert report["no_submit"] is True
    assert report["explicit_approval_still_required"] is True
    assert report["can_submit_target_msa_if_explicitly_approved"] is True
    assert report["can_submit_candidate_generation_or_candidate_level_prediction"] is False
    assert report["can_claim_w3b"] is False
    assert report["receipt_untouched"] is True
    assert report["failures"] == []


def test_hash_drift_and_receipt_presence_fail_closed():
    observed = _observed()
    observed["exact"]["run.sh"]["sha256"] = "d" * 64
    observed["receipt_state"]["receipt_after"] = True
    report = evaluate_readiness(
        packet=_packet(),
        expected=[
            {"path": "a.json", "sha256": "a" * 64},
            {"path": "run.sh", "sha256": "b" * 64},
        ],
        observed=observed,
        remote_host="hpc-login-host",
        remote_root_label="$HOME/bio_sfm_smoke",
        observed_at_utc="2026-07-14T00:00:00Z",
    )

    assert report["status"] == "w3b_target_msa_remote_readiness_blocked"
    assert report["audit_ok"] is False
    assert report["can_submit_target_msa_if_explicitly_approved"] is False
    kinds = {failure["kind"] for failure in report["failures"]}
    assert "remote_artifact_mismatch" in kinds
    assert "receipt_or_summary_present" in kinds
    assert "remote_guarded_dry_run_failed" in kinds
