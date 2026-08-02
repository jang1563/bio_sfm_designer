"""Adjudicate the terminal partial W3c-B2 outcome without new compute."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bio_sfm_designer.experiments.m6d_w3c_b2_approval import (
    verify_packet_integrity,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_completion import (
    MAXIMUM_H100_GPU_SECONDS,
    MAXIMUM_JOBS,
    MAXIMUM_SECONDS_PER_JOB,
    PACKET_PATH,
    RECEIPT_PATH,
    SACCT_PATH,
    SUMMARY_PATH,
    _record_artifacts,
    _replay_native_metrics,
    build_accounting,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    LRMSD_THRESHOLD_ANGSTROM,
    MINIMUM_TARGETS_PASSING,
    PREDICTOR_IDS,
    TARGET_IDS,
    evaluate_records,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_producer import (
    _validate_af2_input_manifest,
    load_context,
    load_object,
    sha256_file,
    validate_runtime_observation_file,
)


BOLTZ_RECORDS_PATH = "results/m6d_w3c_b2_boltz_native_records.jsonl"
AF2_FAILURE_EVIDENCE_PATH = "results/m6d_w3c_b2_af2_failure_evidence.jsonl"
REPORT_PATH = "results/m6d_w3c_b2_terminal_stop.json"
REPORT_MD_PATH = "results/m6d_w3c_b2_terminal_stop.md"
LOG_DIR = "hpc_outputs/logs"
BOLTZ_ID = "boltz2_complex"
AF2_ID = "af2_multimer_colabfold_v1"
STATUS = "w3c_b2_terminal_partial_result_impossibility_stop"
_COLABFOLD_START = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} Running colabfold 1\.6\.1$"
)


def _binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required W3c-B2 terminal evidence is missing: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_text_idempotent(path: str, value: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_text() != value:
            raise ValueError(
                f"refusing to overwrite divergent W3c-B2 terminal artifact: {path}"
            )
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=str(destination.parent)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_idempotent(path: str, value: Mapping[str, Any]) -> None:
    _write_text_idempotent(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl_idempotent(path: str, rows: Sequence[Mapping[str, Any]]) -> None:
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    _write_text_idempotent(path, text)


def maximum_possible_conjunctive_passes(
    observed_predictor_successes: int,
    *,
    targets_expected: int = len(TARGET_IDS),
) -> int:
    """Upper-bound AND-gated target passes from one fully observed predictor."""

    if (
        isinstance(observed_predictor_successes, bool)
        or not isinstance(observed_predictor_successes, int)
        or isinstance(targets_expected, bool)
        or not isinstance(targets_expected, int)
        or targets_expected <= 0
        or not 0 <= observed_predictor_successes <= targets_expected
    ):
        raise ValueError("conjunctive-pass inputs are outside the frozen target scope")
    return observed_predictor_successes


def _validate_terminal_accounting(
    accounting: Mapping[str, Any],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Require the exact eight-success/eight-AF2-failure terminal pattern."""

    expected_pairs = {
        (target_id, predictor_id)
        for target_id in TARGET_IDS
        for predictor_id in PREDICTOR_IDS
    }
    rows = accounting.get("job_states")
    if not isinstance(rows, list):
        raise ValueError("W3c-B2 terminal accounting lacks job states")
    by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError("W3c-B2 terminal accounting contains a non-object job row")
        pair = (
            str(raw_row.get("target_id") or ""),
            str(raw_row.get("predictor_id") or ""),
        )
        if pair in by_pair:
            raise ValueError(f"duplicate terminal accounting pair: {pair}")
        by_pair[pair] = raw_row
    if set(by_pair) != expected_pairs:
        raise ValueError("W3c-B2 terminal accounting pair scope is incomplete or extended")
    job_ids = [str(row.get("job_id") or "") for row in by_pair.values()]
    if len(set(job_ids)) != MAXIMUM_JOBS or any(not job_id for job_id in job_ids):
        raise ValueError("W3c-B2 terminal accounting job IDs are incomplete or duplicated")

    common_ok = (
        accounting.get("artifact") == "m6d_w3c_b2_completion_accounting"
        and accounting.get("version") == 1
        and accounting.get("status") == "w3c_b2_terminal_failure_stop_no_retry"
        and accounting.get("audit_ok") is False
        and accounting.get("approval_consumed") is True
        and accounting.get("jobs_expected") == MAXIMUM_JOBS
        and accounting.get("jobs_in_receipt") == MAXIMUM_JOBS
        and accounting.get("jobs_in_sacct") == MAXIMUM_JOBS
        and accounting.get("jobs_terminal_success") == len(TARGET_IDS)
        and accounting.get("jobs_pending") == 0
        and accounting.get("pending_job_ids") == []
        and accounting.get("missing_job_ids") == []
        and accounting.get("unexpected_job_ids") == []
        and accounting.get("sync_allowed") is False
        and accounting.get("within_approved_h100_budget") is True
        and accounting.get("approved_h100_gpu_seconds")
        == MAXIMUM_H100_GPU_SECONDS
        and accounting.get("retry_or_adaptive_top_up_allowed") is False
        and accounting.get("additional_jobs_authorized") == 0
        and accounting.get("proteinmpnn_designs") == 0
        and accounting.get("no_submit") is True
    )
    if not common_ok:
        raise ValueError("W3c-B2 terminal accounting contract is not the frozen stop state")

    terminal_failure_ids: List[str] = []
    elapsed_total = 0
    for target_id in TARGET_IDS:
        boltz = by_pair[(target_id, BOLTZ_ID)]
        af2 = by_pair[(target_id, AF2_ID)]
        for row in (boltz, af2):
            elapsed = row.get("elapsed_seconds")
            if (
                isinstance(elapsed, bool)
                or not isinstance(elapsed, int)
                or not 0 < elapsed <= MAXIMUM_SECONDS_PER_JOB
                or row.get("requested_gpus") != 1
                or row.get("gpus") != 1
                or row.get("gpu_type") != "h100"
            ):
                raise ValueError("W3c-B2 terminal job resource evidence is invalid")
            elapsed_total += elapsed
        if not (
            boltz.get("state") == "COMPLETED"
            and boltz.get("exit_code") == "0:0"
        ):
            raise ValueError(f"{target_id}: Boltz was not the terminal-success job")
        if not (af2.get("state") == "FAILED" and af2.get("exit_code") == "1:0"):
            raise ValueError(f"{target_id}: AF2 was not the exact terminal-failure job")
        terminal_failure_ids.append(str(af2.get("job_id") or ""))

    if not (
        accounting.get("gpu_allocation_seconds_total") == elapsed_total
        and accounting.get("gpu_allocation_hours_total") == elapsed_total / 3600.0
        and elapsed_total <= MAXIMUM_H100_GPU_SECONDS
        and set(accounting.get("terminal_failure_job_ids") or [])
        == set(terminal_failure_ids)
        and len(accounting.get("terminal_failure_job_ids") or [])
        == len(terminal_failure_ids)
    ):
        raise ValueError("W3c-B2 terminal accounting totals or failed-job IDs drifted")

    failures = accounting.get("failures")
    if not isinstance(failures, list) or accounting.get("n_failures") != len(TARGET_IDS):
        raise ValueError("W3c-B2 terminal accounting failure count is not exactly eight")
    observed_failures = {
        (
            str(row.get("target_id") or ""),
            str(row.get("predictor_id") or ""),
            str(row.get("job_id") or ""),
            str(row.get("state") or ""),
            str(row.get("exit_code") or ""),
        )
        for row in failures
        if isinstance(row, dict) and row.get("kind") == "job_terminal_failure"
    }
    expected_failures = {
        (
            target_id,
            AF2_ID,
            str(by_pair[(target_id, AF2_ID)]["job_id"]),
            "FAILED",
            "1:0",
        )
        for target_id in TARGET_IDS
    }
    if observed_failures != expected_failures or len(failures) != len(observed_failures):
        raise ValueError("W3c-B2 accounting contains failures beyond the eight AF2 jobs")
    return by_pair


def validate_af2_preinference_logs(
    *,
    target_id: str,
    input_dir: str,
    a3m_sha256: str,
    stdout_path: str,
    stderr_path: str,
) -> Dict[str, Any]:
    """Validate the narrow ColabFold input-resolution failure signature."""

    stdout = Path(stdout_path).read_text()
    stderr = Path(stderr_path).read_text()
    required_stdout = {
        "approval": (
            "status=w3c_b2_approval_packet_verified_no_submit "
            "verified=True no_submit=True"
        ),
        "context": (
            f"target={target_id} predictor={AF2_ID} context_valid=True "
            "prediction_executed=False"
        ),
        "input": (
            f"target={target_id} af2_input_ready=True a3m_sha256={a3m_sha256}"
        ),
        "runtime": (
            f"predictor={AF2_ID} reobserved=True prediction_executed=False"
        ),
        "gpu_preflight": "W3c-B2 AF2 GPU preflight devices: [CudaDevice(id=0)]",
    }
    missing = [name for name, line in required_stdout.items() if line not in stdout]
    if missing or not any(_COLABFOLD_START.fullmatch(line) for line in stdout.splitlines()):
        raise ValueError(
            f"{target_id}: AF2 stdout lacks the frozen pre-inference signature"
        )
    expected_error = f"OSError: {input_dir} could not be found"
    stderr_lines = stderr.splitlines()
    if not (
        stderr_lines
        and stderr_lines[-1] == expected_error
        and stderr.count(expected_error) == 1
        and "queries, is_complex = get_queries(args.input, args.sort_queries_by)"
        in stderr
        and "raise OSError(f\"{input_path} could not be found\")" in stderr
    ):
        raise ValueError(
            f"{target_id}: AF2 stderr is not the exact input-resolution failure"
        )
    return {
        "stdout": _binding(stdout_path),
        "stderr": _binding(stderr_path),
        "terminal_error": expected_error,
        "failure_class": "pre_inference_container_relative_input_path_resolution",
        "gpu_preflight_passed": True,
        "colabfold_process_started": True,
        "query_parsing_reached": True,
        "model_inference_started": False,
    }


def _validate_boltz_only_contract(
    report: Mapping[str, Any],
) -> None:
    failures = report.get("failures")
    expected_missing = {(target_id, AF2_ID) for target_id in TARGET_IDS}
    if not (
        report.get("audit_ok") is False
        and report.get("stage_pass") is False
        and report.get("records_expected") == MAXIMUM_JOBS
        and report.get("records_observed") == len(TARGET_IDS)
        and isinstance(failures, list)
        and len(failures) == 1
        and isinstance(failures[0], dict)
        and failures[0].get("kind") == "missing_records"
    ):
        raise ValueError("Boltz-only records violate the frozen record contract")
    observed_missing = {
        tuple(pair)
        for pair in failures[0].get("pairs", [])
        if isinstance(pair, list) and len(pair) == 2
    }
    if observed_missing != expected_missing:
        raise ValueError("Boltz-only evaluation is missing records beyond exact AF2 pairs")


def adjudicate_terminal_stop(
    packet_path: str,
    receipt_path: str,
    summary_path: str,
    sacct_path: str,
    *,
    log_dir: str = LOG_DIR,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Replay all available evidence and prove the frozen pass is unreachable."""

    packet_failures = verify_packet_integrity(packet_path)
    if packet_failures:
        raise ValueError(
            "W3c-B2 approval packet integrity failed: " + ",".join(packet_failures)
        )
    accounting = build_accounting(packet_path, receipt_path, summary_path, sacct_path)
    job_rows = _validate_terminal_accounting(accounting)
    packet = load_object(packet_path)
    bindings = packet.get("bound_artifacts")
    if not isinstance(bindings, dict):
        raise ValueError("W3c-B2 approval packet lacks bound artifacts")
    manifest_path = str(bindings["native_screen_manifest"]["path"])
    runtime_lock_path = str(bindings["runtime_lock"]["path"])
    manifest = load_object(manifest_path)
    runtime_lock = load_object(runtime_lock_path)
    execution_targets = packet.get("execution_targets")
    if not (
        isinstance(execution_targets, list)
        and [row.get("target_id") for row in execution_targets] == TARGET_IDS
    ):
        raise ValueError("W3c-B2 execution target order differs from the frozen packet")

    boltz_records: List[Dict[str, Any]] = []
    boltz_results: List[Dict[str, Any]] = []
    af2_failures: List[Dict[str, Any]] = []
    for execution_target in execution_targets:
        target_id = str(execution_target["target_id"])
        target_root = str(Path(str(execution_target["boltz_record"])).parent)

        boltz_context = load_context(
            manifest_path, runtime_lock_path, target_id, BOLTZ_ID
        )
        boltz_observation_path = str(execution_target["boltz_runtime_observation"])
        validate_runtime_observation_file(boltz_context, boltz_observation_path)
        boltz_record_path = str(execution_target["boltz_record"])
        boltz_record = load_object(boltz_record_path)
        artifacts = _record_artifacts(
            boltz_record,
            target_root=target_root,
            predictor_output_root=str(execution_target["boltz_output_dir"]),
            expected_auxiliary_name="pae",
        )
        replayed = _replay_native_metrics(
            boltz_context, boltz_record, BOLTZ_ID, artifacts
        )
        boltz_records.append(boltz_record)
        boltz_results.append({
            "target_id": target_id,
            "predictor_id": BOLTZ_ID,
            "record": _binding(boltz_record_path),
            "runtime_observation": _binding(boltz_observation_path),
            "verified_outputs": artifacts,
            "interface_pae": replayed["interface_pae"],
            "lrmsd_angstrom": replayed["lrmsd_angstrom"],
            "success": boltz_record.get("success") is True,
            "strict_qc_passed": boltz_record.get("strict_qc_passed") is True,
        })

        af2_context = load_context(
            manifest_path, runtime_lock_path, target_id, AF2_ID
        )
        af2_observation_path = str(execution_target["af2_runtime_observation"])
        validate_runtime_observation_file(af2_context, af2_observation_path)
        input_manifest_path = str(execution_target["af2_input_manifest"])
        input_manifest = _validate_af2_input_manifest(
            af2_context, input_manifest_path
        )
        input_dir = str(execution_target["af2_input_dir"])
        if not Path(input_dir).is_dir():
            raise ValueError(f"{target_id}: prepared AF2 input directory is absent")
        af2_record_path = str(execution_target["af2_record"])
        if os.path.exists(af2_record_path):
            raise ValueError(f"{target_id}: failed AF2 job unexpectedly produced a record")
        output_dir = Path(str(execution_target["af2_output_dir"]))
        output_files = (
            sorted(str(path) for path in output_dir.rglob("*") if path.is_file())
            if output_dir.exists()
            else []
        )
        if output_files:
            raise ValueError(f"{target_id}: failed AF2 job produced model output files")
        af2_job = job_rows[(target_id, AF2_ID)]
        job_id = str(af2_job["job_id"])
        stdout_path = str(Path(log_dir) / f"biosfm-w3c-b2-af2-{job_id}.out")
        stderr_path = str(Path(log_dir) / f"biosfm-w3c-b2-af2-{job_id}.err")
        log_evidence = validate_af2_preinference_logs(
            target_id=target_id,
            input_dir=input_dir,
            a3m_sha256=str(input_manifest["a3m_sha256"]),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        af2_failures.append({
            "artifact": "m6d_w3c_b2_af2_terminal_failure_evidence",
            "version": 1,
            "target_id": target_id,
            "predictor_id": AF2_ID,
            "job_id": job_id,
            "scheduler_state": af2_job["state"],
            "exit_code": af2_job["exit_code"],
            "elapsed_seconds": af2_job["elapsed_seconds"],
            "runtime_observation": _binding(af2_observation_path),
            "input_manifest": _binding(input_manifest_path),
            "a3m": _binding(str(input_manifest["a3m_path"])),
            "input_dir": input_dir,
            "af2_output_dir": str(output_dir),
            "af2_output_dir_present": output_dir.is_dir(),
            "af2_output_files": 0,
            "predictor_record_present": False,
            **log_evidence,
        })

    boltz_only = evaluate_records(
        manifest,
        runtime_lock,
        boltz_records,
        manifest_sha256=sha256_file(manifest_path),
        runtime_lock_sha256=sha256_file(runtime_lock_path),
    )
    _validate_boltz_only_contract(boltz_only)
    boltz_success_ids = [row["target_id"] for row in boltz_results if row["success"]]
    maximum_passes = maximum_possible_conjunctive_passes(len(boltz_success_ids))
    if maximum_passes >= MINIMUM_TARGETS_PASSING:
        raise ValueError(
            "available predictor results do not prove the frozen W3c-B2 pass impossible"
        )

    report = {
        "artifact": "m6d_w3c_b2_terminal_stop",
        "version": 1,
        "status": STATUS,
        "audit_ok": True,
        "execution_complete": False,
        "stage_decision_complete": True,
        "scientific_stop_complete": True,
        "stage_pass": False,
        "native_recoverability_fully_evaluable": False,
        "scheduler_jobs_expected": MAXIMUM_JOBS,
        "scheduler_jobs_terminal": MAXIMUM_JOBS,
        "predictor_records_expected": MAXIMUM_JOBS,
        "predictor_records_observed": len(boltz_records),
        "boltz_records_replayed": len(boltz_records),
        "boltz_strict_qc_records": sum(
            row["strict_qc_passed"] for row in boltz_results
        ),
        "boltz_successes": len(boltz_success_ids),
        "boltz_success_target_ids": boltz_success_ids,
        "boltz_failures": len(TARGET_IDS) - len(boltz_success_ids),
        "af2_terminal_failures": len(af2_failures),
        "af2_failures_before_model_inference": len(af2_failures),
        "maximum_possible_dual_predictor_target_passes": maximum_passes,
        "minimum_targets_passing": MINIMUM_TARGETS_PASSING,
        "frozen_pass_mathematically_impossible": True,
        "decision_rule": (
            "A target passes only when both predictors have L-RMSD < "
            f"{LRMSD_THRESHOLD_ANGSTROM:.1f} A; the stage passes at >= "
            f"{MINIMUM_TARGETS_PASSING}/{len(TARGET_IDS)} targets."
        ),
        "impossibility_proof": (
            f"Only {len(boltz_success_ids)}/{len(TARGET_IDS)} targets pass Boltz. "
            "Because dual-predictor target pass is conjunctive, at most "
            f"{maximum_passes}/{len(TARGET_IDS)} targets can pass even if every "
            "unobserved AF2 result is favorable. This is below the frozen "
            f"{MINIMUM_TARGETS_PASSING}/{len(TARGET_IDS)} threshold."
        ),
        "source_accounting_status": accounting["status"],
        "source_accounting_audit_ok": accounting["audit_ok"],
        "source_accounting_failures_expected": len(TARGET_IDS),
        "observed_h100_gpu_seconds": accounting["gpu_allocation_seconds_total"],
        "observed_h100_gpu_hours": accounting["gpu_allocation_hours_total"],
        "within_approved_h100_budget": True,
        "af2_recovery_scientifically_required_for_frozen_decision": False,
        "af2_recovery_authorized": False,
        "retry_or_adaptive_top_up_allowed": False,
        "additional_jobs_authorized": 0,
        "proteinmpnn_designs": 0,
        "no_submit": True,
        "can_claim_native_recoverability_on_locked_panel": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "boltz_results": boltz_results,
        "input_bindings": {
            "approval_packet": _binding(packet_path),
            "submission_receipt": _binding(receipt_path),
            "submission_summary": _binding(summary_path),
            "sacct_snapshot": _binding(sacct_path),
            "native_screen_manifest": _binding(manifest_path),
            "runtime_lock": _binding(runtime_lock_path),
        },
        "claim_boundary": (
            "This terminal partial result proves only that the frozen W3c-B2 "
            ">=6/8 pass criterion cannot be reached: Boltz succeeds on 2/8 and "
            "each target requires both predictors. It is not a complete dual-predictor "
            "native-recoverability estimate, generator-yield evidence, trust-gate "
            "evidence, or biological binder-success evidence."
        ),
        "next_action": (
            "Close W3c-B2 at the validity-first stop before candidate generation. "
            "Any AF2 recovery or successor representation/predictor study must be "
            "separately preregistered, hash-bound, and explicitly approved."
        ),
    }
    return report, boltz_records, af2_failures


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B2 Terminal Partial-Result Stop",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Frozen stage pass: `{report['stage_pass']}`.",
        "",
        str(report["impossibility_proof"]),
        "",
        f"- Boltz strict-QC records replayed: `{report['boltz_records_replayed']}` / `8`",
        f"- Boltz native successes: `{report['boltz_successes']}` / `8`",
        f"- AF2 pre-inference terminal failures: `{report['af2_failures_before_model_inference']}` / `8`",
        f"- maximum possible dual-predictor passes: `{report['maximum_possible_dual_predictor_target_passes']}` / `8`",
        f"- frozen stage threshold: `{report['minimum_targets_passing']}` / `8`",
        f"- H100 GPU-hours observed: `{report['observed_h100_gpu_hours']:.6f}` / `16.0`",
        f"- additional jobs authorized: `{report['additional_jobs_authorized']}`",
        "",
        "## Boltz Replay",
        "",
        "| Target | interface pAE | L-RMSD (A) | Success |",
        "|---|---:|---:|:---:|",
    ]
    lines.extend(
        "| {target_id} | {interface_pae:.4f} | {lrmsd_angstrom:.6f} | {success} |".format(
            **row
        )
        for row in report["boltz_results"]
    )
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        str(report["claim_boundary"]),
        "",
        f"Next action: {report['next_action']}",
        "",
    ])
    return "\n".join(lines)


def run(
    packet_path: str,
    receipt_path: str,
    summary_path: str,
    sacct_path: str,
    *,
    log_dir: str = LOG_DIR,
    boltz_records_path: str = BOLTZ_RECORDS_PATH,
    af2_failure_evidence_path: str = AF2_FAILURE_EVIDENCE_PATH,
    report_path: str = REPORT_PATH,
    report_md_path: str = REPORT_MD_PATH,
) -> Dict[str, Any]:
    report, boltz_records, af2_failures = adjudicate_terminal_stop(
        packet_path,
        receipt_path,
        summary_path,
        sacct_path,
        log_dir=log_dir,
    )
    _write_jsonl_idempotent(boltz_records_path, boltz_records)
    _write_jsonl_idempotent(af2_failure_evidence_path, af2_failures)
    report["evidence_bindings"] = {
        "boltz_native_records": _binding(boltz_records_path),
        "af2_failure_evidence": _binding(af2_failure_evidence_path),
    }
    _write_json_idempotent(report_path, report)
    _write_text_idempotent(report_md_path, render_markdown(report))
    return report


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", default=PACKET_PATH)
    parser.add_argument("--receipt", default=RECEIPT_PATH)
    parser.add_argument("--summary", default=SUMMARY_PATH)
    parser.add_argument("--sacct", default=SACCT_PATH)
    parser.add_argument("--log-dir", default=LOG_DIR)
    parser.add_argument("--boltz-records", default=BOLTZ_RECORDS_PATH)
    parser.add_argument("--af2-failure-evidence", default=AF2_FAILURE_EVIDENCE_PATH)
    parser.add_argument("--report", default=REPORT_PATH)
    parser.add_argument("--report-md", default=REPORT_MD_PATH)
    args = parser.parse_args(argv)
    report = run(
        args.packet,
        args.receipt,
        args.summary,
        args.sacct,
        log_dir=args.log_dir,
        boltz_records_path=args.boltz_records,
        af2_failure_evidence_path=args.af2_failure_evidence,
        report_path=args.report,
        report_md_path=args.report_md,
    )
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"boltz_successes={report['boltz_successes']}/8 "
        f"maximum_dual_passes={report['maximum_possible_dual_predictor_target_passes']}/8 "
        "additional_jobs_authorized=0 no_submit=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
