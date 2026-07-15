"""Bind completed W3b fit recovery, matched records, and the frozen terminal decision."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_jsonl,
    load_object,
    sha256_file,
)


def _file_binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required W3b fit-completion artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def build_completion(
    recovery_completion_path: str,
    matched_records_path: str,
    assembly_report_path: str,
    gate_report_path: str,
    diagnostics_path: str,
) -> Dict[str, Any]:
    recovery = load_object(recovery_completion_path)
    assembly = load_object(assembly_report_path)
    gate = load_object(gate_report_path)
    diagnostics = load_object(diagnostics_path)
    records = load_jsonl(matched_records_path)
    candidate_ids = [str(row.get("candidate_id") or "") for row in records]
    proof_predictors = {
        str(row.get("predictor_id") or "")
        for row in diagnostics.get("impossibility_proofs", [])
        if isinstance(row, dict)
        and row.get("target_id") == "1FSK_LJ"
        and row.get("violates_cap_even_if_all_rows_accepted") is True
    }
    if not (
        recovery.get("artifact") == "m6d_w3b_fit_af2_recovery_completion"
        and recovery.get("status")
        == "w3b_fit_af2_recovery_completed_ready_for_matched_assembly"
        and recovery.get("audit_ok") is True
        and recovery.get("terminal_success") is True
        and recovery.get("n_recovery_jobs") == 3
        and recovery.get("n_recovery_jobs_completed") == 3
        and recovery.get("can_run_fit_assembler") is True
        and recovery.get("can_submit_more_recovery_jobs") is False
        and recovery.get("can_submit_certification") is False
        and recovery.get("can_claim_w3b") is False
        and assembly.get("artifact") == "m6d_w3b_matched_record_assembly"
        and assembly.get("status") == "w3b_fit_matched_records_ready"
        and assembly.get("audit_ok") is True
        and assembly.get("stage") == "fit"
        and assembly.get("expected_records") == 180
        and assembly.get("n_matched_records") == 180
        and assembly.get("can_run_stage_evaluator") is True
        and assembly.get("can_claim_w3b") is False
        and len(records) == len(set(candidate_ids)) == 180
        and all(candidate_ids)
        and gate.get("artifact") == "m6d_w3b_disagreement_gate_report"
        and gate.get("status") == "w3b_fit_rule_not_found_stop"
        and gate.get("audit_ok") is True
        and gate.get("record_counts")
        == {"fit": 180, "certification": 0, "held_out_test": 0}
        and gate.get("fit", {}).get("rules_frozen") is False
        and gate.get("fit", {}).get("primary") is None
        and gate.get("fit", {}).get("comparator") is None
        and gate.get("can_claim_bounded_disagreement_gate_viability") is False
        and diagnostics.get("artifact") == "m6d_w3b_fit_diagnostics"
        and diagnostics.get("status")
        == "w3b_fit_terminal_negative_diagnostics_complete"
        and diagnostics.get("audit_ok") is True
        and diagnostics.get("n_records") == 180
        and diagnostics.get("frozen_fit_mathematically_impossible") is True
        and diagnostics.get("certification_reachable") is False
        and diagnostics.get("certification_submission_authorized") is False
        and diagnostics.get("held_out_test_reachable") is False
        and diagnostics.get("can_claim_w3b") is False
        and proof_predictors
        == {"boltz2_complex", "af2_multimer_colabfold_v1"}
    ):
        raise ValueError("W3b fit completion inputs do not support the terminal frozen stop")

    initial_path = str(recovery.get("initial_observation", {}).get("path") or "")
    if sha256_file(initial_path) != recovery.get("initial_observation", {}).get("sha256"):
        raise ValueError("W3b initial execution observation binding is stale")
    initial = load_object(initial_path)
    initial_boltz_seconds = sum(
        int(row.get("boltz", {}).get("elapsed_seconds") or 0)
        for row in initial.get("target_reports", [])
        if isinstance(row, dict)
    )
    failed_af2_seconds = int(initial.get("initial_failed_af2_gpu_seconds") or 0)
    recovery_af2_seconds = int(recovery.get("observed_recovery_gpu_seconds") or 0)
    observed_h100_seconds = initial_boltz_seconds + failed_af2_seconds + recovery_af2_seconds
    primary = diagnostics["exhaustive_threshold_diagnostics"]["primary"]
    comparator = diagnostics["exhaustive_threshold_diagnostics"]["comparator"]
    target_reports = {
        str(row["target_id"]): row for row in diagnostics["target_reports"]
    }
    return {
        "artifact": "m6d_w3b_fit_completion",
        "version": 1,
        "status": "w3b_fit_complete_rule_not_found_terminal_stop",
        "audit_ok": True,
        "approval_consumed": True,
        "initial_fit_jobs_submitted": 9,
        "af2_recovery_jobs_submitted": 3,
        "jobs_completed_successfully": 9,
        "jobs_failed_before_prediction": 3,
        "replacement_jobs_completed_successfully": 3,
        "observed_h100_allocation_seconds": observed_h100_seconds,
        "observed_h100_allocation_hours": observed_h100_seconds / 3600.0,
        "h100_accounting": {
            "initial_boltz_seconds": initial_boltz_seconds,
            "initial_failed_af2_seconds": failed_af2_seconds,
            "recovery_af2_seconds": recovery_af2_seconds,
            "corrected_worst_case_seconds": recovery[
                "scheduler_time_limit_correction"
            ]["corrected_worst_case_gpu_seconds"],
            "protocol_limit_seconds": recovery[
                "scheduler_time_limit_correction"
            ]["protocol_limit_gpu_seconds"],
        },
        "n_fit_targets": 3,
        "n_matched_records": 180,
        "matched_records_by_target": assembly["matched_records_by_target"],
        "local_remote_sha256_parity": True,
        "fit_outcome": {
            "status": gate["status"],
            "primary_rules_frozen": False,
            "comparator_rules_frozen": False,
            "primary_qualifying_rules": gate["fit"][
                "primary_candidate_rules_considered"
            ],
            "comparator_qualifying_rules": gate["fit"][
                "comparator_candidate_rules_considered"
            ],
            "mathematically_impossible_under_frozen_constraints": True,
            "impossibility_target": "1FSK_LJ",
            "impossibility_predictors": sorted(proof_predictors),
            "minimum_possible_global_false_accept_rate": 15 / 180,
            "frozen_empirical_risk_cap": 0.08,
            "best_primary_worst_risk_at_frozen_coverage": primary[
                "best_risk_subject_to_frozen_coverage"
            ]["worst_false_accept_rate"],
            "best_primary_coverage_at_frozen_risk_cap": primary[
                "best_coverage_subject_to_frozen_risk_cap"
            ]["accepted"],
            "best_comparator_worst_risk_at_frozen_coverage": comparator[
                "best_risk_subject_to_frozen_coverage"
            ]["worst_false_accept_rate"],
            "best_comparator_coverage_at_frozen_risk_cap": comparator[
                "best_coverage_subject_to_frozen_risk_cap"
            ]["accepted"],
        },
        "target_endpoint_summary": {
            target_id: report["endpoints"]
            for target_id, report in sorted(target_reports.items())
        },
        "certification_reachable": False,
        "certification_compute_approved": False,
        "certification_jobs_submitted": 0,
        "held_out_test_reachable": False,
        "held_out_test_jobs_submitted": 0,
        "adaptive_top_up_allowed": False,
        "can_claim_w3b": False,
        "can_claim_biological_binder_success": False,
        "recovery_completion": _file_binding(recovery_completion_path),
        "matched_records": _file_binding(matched_records_path),
        "matched_record_assembly": _file_binding(assembly_report_path),
        "frozen_gate_report": _file_binding(gate_report_path),
        "post_fit_diagnostics": _file_binding(diagnostics_path),
        "next_action": (
            "Preserve W3b as a terminal negative fit result. Submit no certification or held-out-test "
            "compute; preregister a successor only after deciding whether to study generator failure, "
            "target heterogeneity, or a different trust signal."
        ),
        "claim_boundary": (
            "The preregistered W3b fit failed before certification. This is negative structural-proxy "
            "evidence, not a certificate, wet-lab binder result, or population-level predictor claim."
        ),
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recovery-completion",
        default="results/m6d_w3b_fit_af2_recovery_completion.json",
    )
    parser.add_argument(
        "--matched-records", default="results/m6d_w3b_fit_matched_records.jsonl"
    )
    parser.add_argument(
        "--assembly-report",
        default="results/m6d_w3b_fit_matched_record_assembly.json",
    )
    parser.add_argument(
        "--gate-report", default="results/m6d_w3b_fit_gate_report.json"
    )
    parser.add_argument(
        "--diagnostics", default="results/m6d_w3b_fit_diagnostics.json"
    )
    parser.add_argument("--out", default="results/m6d_w3b_fit_completion.json")
    args = parser.parse_args(argv)
    report = build_completion(
        args.recovery_completion,
        args.matched_records,
        args.assembly_report,
        args.gate_report,
        args.diagnostics,
    )
    _write_json(args.out, report)
    print(
        f"status={report['status']} records={report['n_matched_records']} "
        "certification=False claim=False"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
