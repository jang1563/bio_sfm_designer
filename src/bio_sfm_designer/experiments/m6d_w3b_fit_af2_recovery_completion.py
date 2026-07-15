"""Audit terminal W3b fit AF2 recovery jobs without authorizing more compute."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_jsonl,
    load_object,
    sha256_file,
)


_RECOVERY_TIME_LIMIT_SECONDS = 3 * 3600 + 59 * 60
_SCHEDULER_ROUNDED_SECONDS = 4 * 3600
_PROTOCOL_LIMIT_SECONDS = 24 * 3600
_EXPECTED_OUTPUTS_PER_TARGET = 60 * 5


def _file_binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required recovery-completion artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=str(destination.parent)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_sacct(path: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    with open(path) as handle:
        reader = csv.reader(handle, delimiter="|")
        for values in reader:
            if len(values) < 6 or not values[0].strip():
                continue
            job_id, state, exit_code, elapsed_raw, alloc_tres, node_list = values[:6]
            job_id = job_id.strip()
            if job_id.lower() == "jobidraw":
                continue
            rows[job_id] = {
                "job_id": job_id,
                "state": state.split()[0].split("+")[0],
                "exit_code": exit_code,
                "elapsed_seconds": int(elapsed_raw),
                "alloc_tres": alloc_tres,
                "node_list": node_list,
            }
    if not rows:
        raise ValueError("recovery sacct snapshot contains no allocation rows")
    return rows


def _read_scontrol(path: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for line in Path(path).read_text().splitlines():
        job_match = re.search(r"(?:^|\s)JobId=(\d+)(?:\s|$)", line)
        if not job_match:
            continue
        job_id = job_match.group(1)
        values: Dict[str, Any] = {"job_id": job_id}
        for key in ("JobState", "Requeue", "TimeLimit", "TresPerNode"):
            match = re.search(rf"(?:^|\s){key}=([^\s]+)", line)
            if not match:
                raise ValueError(f"scontrol snapshot job {job_id} lacks {key}")
            values[key] = match.group(1)
        rows[job_id] = values
    if not rows:
        raise ValueError("post-correction scontrol snapshot contains no jobs")
    return rows


def _validate_terminal_outputs(
    target_id: str,
    job_id: str,
    partial: Mapping[str, Any],
    *,
    log_root: str,
) -> Dict[str, Any]:
    candidates_binding = partial.get("candidates")
    if not isinstance(candidates_binding, dict):
        raise ValueError(f"target_id={target_id} lacks the recovery candidate binding")
    candidates_path = str(candidates_binding.get("path") or "")
    if sha256_file(candidates_path) != candidates_binding.get("sha256"):
        raise ValueError(f"target_id={target_id} candidate hash drift after recovery")

    records_path = str(partial.get("af2_records") or "")
    receipt_path = str(partial.get("af2_runtime_receipt") or "")
    records = load_jsonl(records_path)
    receipt = load_object(receipt_path)
    record_ids = [str(row.get("target_id") or "") for row in records]
    if not (
        len(records) == 60
        and len(set(record_ids)) == 60
        and all(record_ids)
        and receipt.get("artifact") == "m6d_w3b_predictor_runtime_receipt"
        and receipt.get("status") == "w3b_predictor_records_complete"
        and receipt.get("audit_ok") is True
        and receipt.get("no_submit") is True
        and receipt.get("predictor_id") == "af2_multimer_colabfold_v1"
        and receipt.get("target_id") == target_id
        and receipt.get("experimental_role") == "fit"
        and receipt.get("n_records") == 60
        and receipt.get("records") == records_path
        and receipt.get("records_sha256") == sha256_file(records_path)
        and receipt.get("candidates") == candidates_path
        and receipt.get("candidates_sha256") == candidates_binding.get("sha256")
    ):
        raise ValueError(f"target_id={target_id} terminal AF2 record/receipt contract failed")

    output_dir = Path(str(partial.get("af2_output_dir") or ""))
    score_count = len(list(output_dir.glob("*_scores_rank_*.json")))
    pdb_count = len(list(output_dir.glob("*_unrelaxed_rank_*.pdb")))
    done_count = len(list(output_dir.glob("*.done.txt")))
    if not (
        score_count == _EXPECTED_OUTPUTS_PER_TARGET
        and pdb_count == _EXPECTED_OUTPUTS_PER_TARGET
        and done_count == 60
    ):
        raise ValueError(
            f"target_id={target_id} AF2 output cardinality is incomplete: "
            f"scores={score_count} pdbs={pdb_count} done={done_count}"
        )
    return {
        "records": _file_binding(records_path),
        "runtime_receipt": _file_binding(receipt_path),
        "n_records": len(records),
        "n_score_json": score_count,
        "n_unrelaxed_pdb": pdb_count,
        "n_done_markers": done_count,
        "stdout_log": _file_binding(
            str(Path(log_root) / f"biosfm-w3b-fit-af2r-{job_id}.out")
        ),
        "stderr_log": _file_binding(
            str(Path(log_root) / f"biosfm-w3b-fit-af2r-{job_id}.err")
        ),
    }


def build_completion(
    initial_observation_path: str,
    approval_packet_path: str,
    submission_receipt_path: str,
    submission_summary_path: str,
    sacct_path: str,
    scontrol_post_correction_path: str,
    *,
    log_root: str = "hpc_outputs/logs",
) -> Dict[str, Any]:
    observation = load_object(initial_observation_path)
    packet = load_object(approval_packet_path)
    summary = load_object(submission_summary_path)
    sacct = _read_sacct(sacct_path)
    scontrol = _read_scontrol(scontrol_post_correction_path)
    packet_targets = {
        str(row.get("target_id") or ""): row
        for row in packet.get("targets", [])
        if isinstance(row, dict)
    }
    summary_targets = {
        str(row.get("target_id") or ""): row
        for row in summary.get("targets", [])
        if isinstance(row, dict)
    }
    contract = packet.get("approval_contract")
    if not isinstance(contract, dict):
        raise ValueError("recovery approval packet lacks its contract")
    job_ids = sorted(
        (str(row.get("recovery_af2_job_id") or "") for row in summary_targets.values()),
        key=int,
    )
    if not (
        observation.get("artifact") == "m6d_w3b_fit_initial_execution_observation"
        and observation.get("status")
        == "w3b_fit_af2_path_failure_recovery_eligible_no_submit"
        and observation.get("audit_ok") is True
        and observation.get("initial_failed_af2_gpu_seconds") == 38
        and packet.get("artifact") == "m6d_w3b_fit_af2_recovery_approval_packet"
        and packet.get("status")
        == "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval"
        and packet.get("observation", {}).get("sha256")
        == sha256_file(initial_observation_path)
        and summary.get("artifact") == "m6d_w3b_fit_af2_recovery_submit_summary"
        and summary.get("status")
        == "w3b_fit_af2_recovery_jobs_submitted_awaiting_completion"
        and summary.get("approval_packet_sha256") == sha256_file(approval_packet_path)
        and summary.get("receipt_sha256") == sha256_file(submission_receipt_path)
        and summary.get("n_af2_h100_recovery_jobs") == 3
        and len(packet_targets) == len(summary_targets) == 3
        and set(packet_targets) == set(summary_targets)
        and len(job_ids) == len(set(job_ids)) == 3
        and set(job_ids) == set(sacct) == set(scontrol)
        and contract.get("recovery_time_limit") == "03:59:30"
        and contract.get("requeue") is False
        and contract.get("proteinmpnn_jobs_authorized") == 0
        and contract.get("boltz_jobs_authorized") == 0
        and contract.get("authorizes_certification") is False
        and contract.get("authorizes_held_out_test") is False
        and contract.get("authorizes_claim") is False
    ):
        raise ValueError("W3b AF2 recovery completion evidence is not scope-consistent")

    for job_id, row in scontrol.items():
        if not (
            row["Requeue"] == "0"
            and row["TimeLimit"] == "03:59:00"
            and row["TresPerNode"] == "gres/gpu:h100:1"
        ):
            raise ValueError(f"job_id={job_id} post-correction Slurm contract failed")

    terminal_success = True
    target_reports: List[Dict[str, Any]] = []
    for target_id in sorted(packet_targets):
        submitted = summary_targets[target_id]
        packet_target = packet_targets[target_id]
        job_id = str(submitted["recovery_af2_job_id"])
        state = sacct[job_id]
        if not (
            submitted.get("failed_af2_job_id") == packet_target.get("failed_af2_job_id")
            and "gres/gpu=1" in state["alloc_tres"]
            and state["elapsed_seconds"] <= _RECOVERY_TIME_LIMIT_SECONDS
        ):
            raise ValueError(f"target_id={target_id} recovery scheduler accounting failed")
        succeeded = state["state"] == "COMPLETED" and state["exit_code"] == "0:0"
        terminal_success = terminal_success and succeeded
        outputs = None
        if succeeded:
            outputs = _validate_terminal_outputs(
                target_id,
                job_id,
                packet_target["partial_state"],
                log_root=log_root,
            )
        target_reports.append({
            "target_id": target_id,
            "failed_af2_job_id": submitted["failed_af2_job_id"],
            "recovery_af2_job": state,
            "post_correction_slurm": scontrol[job_id],
            "terminal_success": succeeded,
            "outputs": outputs,
        })

    initial_failed_seconds = int(observation["initial_failed_af2_gpu_seconds"])
    original_boltz_seconds = int(contract["maximum_original_boltz_gpu_seconds"])
    requested_worst_case = int(contract["maximum_protocol_gpu_seconds_after_recovery"])
    rounded_worst_case = (
        original_boltz_seconds + initial_failed_seconds + 3 * _SCHEDULER_ROUNDED_SECONDS
    )
    corrected_worst_case = (
        original_boltz_seconds + initial_failed_seconds + 3 * _RECOVERY_TIME_LIMIT_SECONDS
    )
    if not (
        requested_worst_case < _PROTOCOL_LIMIT_SECONDS
        and rounded_worst_case > _PROTOCOL_LIMIT_SECONDS
        and corrected_worst_case < _PROTOCOL_LIMIT_SECONDS
    ):
        raise ValueError("W3b AF2 recovery time-limit correction arithmetic failed")

    status = (
        "w3b_fit_af2_recovery_completed_ready_for_matched_assembly"
        if terminal_success
        else "w3b_fit_af2_recovery_terminal_failure_stop"
    )
    return {
        "artifact": "m6d_w3b_fit_af2_recovery_completion",
        "version": 1,
        "status": status,
        "audit_ok": True,
        "approval_consumed": True,
        "n_recovery_jobs": 3,
        "n_recovery_jobs_completed": sum(
            1 for row in target_reports if row["terminal_success"]
        ),
        "terminal_success": terminal_success,
        "can_run_fit_assembler": terminal_success,
        "can_submit_more_recovery_jobs": False,
        "can_submit_certification": False,
        "can_claim_w3b": False,
        "initial_observation": _file_binding(initial_observation_path),
        "approval_packet": _file_binding(approval_packet_path),
        "submission_receipt": _file_binding(submission_receipt_path),
        "submission_summary": _file_binding(submission_summary_path),
        "sacct_snapshot": _file_binding(sacct_path),
        "scontrol_post_correction_snapshot": _file_binding(
            scontrol_post_correction_path
        ),
        "scheduler_time_limit_correction": {
            "packet_requested": "03:59:30",
            "slurm_initial_effective_observed": "04:00:00",
            "initial_observation_kind": "operator_observed_before_correction",
            "post_correction_effective": "03:59:00",
            "requested_worst_case_gpu_seconds": requested_worst_case,
            "rounded_worst_case_gpu_seconds": rounded_worst_case,
            "corrected_worst_case_gpu_seconds": corrected_worst_case,
            "protocol_limit_gpu_seconds": _PROTOCOL_LIMIT_SECONDS,
            "corrected_margin_seconds": _PROTOCOL_LIMIT_SECONDS
            - corrected_worst_case,
        },
        "observed_recovery_gpu_seconds": sum(
            int(row["recovery_af2_job"]["elapsed_seconds"])
            for row in target_reports
        ),
        "targets": target_reports,
        "claim_boundary": (
            "Terminal AF2 fit-recovery evidence only. It authorizes no retry, certification, "
            "held-out test, adaptive top-up, or W3b/biological-success claim."
        ),
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--initial-observation",
        default="results/m6d_w3b_fit_initial_execution_observation.json",
    )
    parser.add_argument(
        "--approval-packet",
        default="results/m6d_w3b_fit_af2_recovery_approval_packet.json",
    )
    parser.add_argument(
        "--submission-receipt",
        default="results/m6d_w3b_fit_af2_recovery_submit_receipt.jsonl",
    )
    parser.add_argument(
        "--submission-summary",
        default="results/m6d_w3b_fit_af2_recovery_submit_summary.json",
    )
    parser.add_argument("--sacct", required=True)
    parser.add_argument("--scontrol-post-correction", required=True)
    parser.add_argument("--log-root", default="hpc_outputs/logs")
    parser.add_argument(
        "--out", default="results/m6d_w3b_fit_af2_recovery_completion.json"
    )
    args = parser.parse_args(argv)
    report = build_completion(
        args.initial_observation,
        args.approval_packet,
        args.submission_receipt,
        args.submission_summary,
        args.sacct,
        args.scontrol_post_correction,
        log_root=args.log_root,
    )
    _write_json(args.out, report)
    print(
        f"status={report['status']} completed={report['n_recovery_jobs_completed']}/3 "
        f"assembler={report['can_run_fit_assembler']} claim=False"
    )
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
