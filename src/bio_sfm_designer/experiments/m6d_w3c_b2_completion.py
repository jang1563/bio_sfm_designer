"""Audit, retrieve, and adjudicate the frozen W3c-B2 native screen."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from bio_sfm_designer.experiments.m6d_w3c_b2_approval import (
    APPROVAL_PHRASE,
    verify_packet_integrity,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_native_screen import (
    LRMSD_THRESHOLD_ANGSTROM,
    PREDICTOR_IDS,
    TARGET_IDS,
    evaluate_records,
    render_report_markdown,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_producer import (
    _strict_metrics,
    load_context,
    load_object,
    sha256_file,
    validate_runtime_observation_file,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_submit_journal import (
    summarize as summarize_submission,
)


PACKET_PATH = "results/m6d_w3c_b2_prediction_approval_packet.json"
RECEIPT_PATH = "results/m6d_w3c_b2_submit_receipt.jsonl"
SUMMARY_PATH = "results/m6d_w3c_b2_submit_receipt_summary.json"
SACCT_PATH = "results/m6d_w3c_b2_sacct.tsv"
ACCOUNTING_PATH = "results/m6d_w3c_b2_completion_accounting.json"
ACCOUNTING_MD_PATH = "results/m6d_w3c_b2_completion_accounting.md"
RECORDS_PATH = "results/m6d_w3c_b2_native_records.jsonl"
REPORT_PATH = "results/m6d_w3c_b2_native_recoverability_report.json"
REPORT_MD_PATH = "results/m6d_w3c_b2_native_recoverability_report.md"
COMPLETION_PATH = "results/m6d_w3c_b2_completion.json"
COMPLETION_MD_PATH = "results/m6d_w3c_b2_completion.md"
MAXIMUM_JOBS = 16
MAXIMUM_SECONDS_PER_JOB = 3600
MAXIMUM_H100_GPU_SECONDS = 16 * 3600
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^[0-9]+(?:_[0-9]+)?$")
_ACTIVE_STATES = {
    "CONFIGURING",
    "COMPLETING",
    "PENDING",
    "REQUEUED",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "RESIZING",
    "RUNNING",
    "SIGNALING",
    "SUSPENDED",
}


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(value)
    return rows


def _binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required W3c-B2 artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path),
    }


def _failure(
    failures: List[Dict[str, Any]],
    kind: str,
    message: str,
    **context: Any,
) -> None:
    failures.append(
        {
            "kind": kind,
            "message": message,
            **{key: value for key, value in context.items() if value is not None},
        }
    )


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().upper().rstrip("+").split(" ", 1)[0]


def _base_job_id(value: Any) -> str:
    return str(value or "").strip().split(".", 1)[0]


def _elapsed_seconds(value: str, *, job_id: str) -> int:
    if not value:
        return 0
    try:
        elapsed = int(value)
    except ValueError as exc:
        raise ValueError(
            f"Slurm job {job_id} has non-integer ElapsedRaw={value!r}"
        ) from exc
    if elapsed < 0:
        raise ValueError(f"Slurm job {job_id} has negative ElapsedRaw")
    return elapsed


def parse_sacct(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse exact top-level Slurm allocation rows from a parsable snapshot."""

    rows: Dict[str, Dict[str, Any]] = {}
    header: Optional[List[str]] = None
    required = {
        "jobname",
        "state",
        "exitcode",
        "elapsedraw",
        "reqtres",
        "alloctres",
    }
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        parts = [part.strip() for part in raw_line.split("|")]
        lowered = [part.lower() for part in parts]
        if "state" in lowered and ("jobidraw" in lowered or "jobid" in lowered):
            header = lowered
            missing = required - set(header)
            if missing:
                raise ValueError(
                    "sacct snapshot lacks required fields: " + ",".join(sorted(missing))
                )
            continue
        if header is None:
            continue
        values = {
            header[index]: parts[index] for index in range(min(len(header), len(parts)))
        }
        raw_job_id = values.get("jobidraw") or values.get("jobid") or ""
        job_id = _base_job_id(raw_job_id)
        if not job_id or raw_job_id != job_id:
            continue
        if job_id in rows:
            raise ValueError(f"duplicate top-level sacct row for job {job_id}")
        rows[job_id] = {
            "job_id": job_id,
            "job_name": values.get("jobname") or "",
            "state": _normalize_state(values.get("state")),
            "exit_code": values.get("exitcode") or "",
            "elapsed_seconds": _elapsed_seconds(
                values.get("elapsedraw") or "", job_id=job_id
            ),
            "req_tres": values.get("reqtres") or "",
            "alloc_tres": values.get("alloctres") or "",
            "node_list": values.get("nodelist") or "",
            "start": values.get("start") or "",
            "end": values.get("end") or "",
        }
    if header is None:
        raise ValueError("sacct snapshot has no parsable header")
    return rows


def _gpu_count(alloc_tres: str) -> int:
    counts = []
    for token in alloc_tres.split(","):
        match = re.fullmatch(r"gres/gpu(?:[:/][^=,]+)?=(\d+)", token.strip())
        if match:
            counts.append(int(match.group(1)))
    return max(counts) if counts else 0


def _job_sort_key(value: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in value.split("_"))


def _validate_wrapper_resources(
    packet: Mapping[str, Any], failures: List[Dict[str, Any]]
) -> None:
    bindings = packet.get("bound_artifacts")
    if not isinstance(bindings, dict):
        _failure(
            failures,
            "packet_bindings_missing",
            "approval packet lacks bound producer artifacts",
        )
        return
    for name in ("boltz_wrapper", "af2_wrapper"):
        binding = bindings.get(name)
        path = binding.get("path") if isinstance(binding, dict) else None
        if not isinstance(path, str) or not os.path.isfile(path):
            _failure(
                failures,
                "bound_wrapper_missing",
                "packet-bound predictor wrapper is unavailable",
                wrapper=name,
            )
            continue
        text = Path(path).read_text()
        if (
            "#SBATCH --gres=gpu:h100:1" not in text
            or "#SBATCH --time=01:00:00" not in text
        ):
            _failure(
                failures,
                "bound_wrapper_resource_drift",
                "predictor wrapper is not locked to one H100 for one hour",
                wrapper=name,
            )
    submit_binding = bindings.get("submit_wrapper")
    submit_path = (
        submit_binding.get("path") if isinstance(submit_binding, dict) else None
    )
    if not isinstance(submit_path, str) or not os.path.isfile(submit_path):
        _failure(
            failures,
            "bound_submit_wrapper_missing",
            "packet-bound submit wrapper is unavailable",
        )
    else:
        submit_text = Path(submit_path).read_text()
        if submit_text.count("--no-requeue") != 2:
            _failure(
                failures,
                "bound_submit_requeue_contract_invalid",
                "submit wrapper must disable scheduler requeue for both predictors",
            )


def _receipt_jobs(
    rows: Sequence[Mapping[str, Any]],
    *,
    packet_path: str,
    packet_sha256: str,
    failures: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    expected_pairs = [
        (target_id, predictor_id)
        for target_id in TARGET_IDS
        for predictor_id in PREDICTOR_IDS
    ]
    observed: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {
        pair: [] for pair in expected_pairs
    }
    unexpected_pairs: List[List[str]] = []
    for row in rows:
        pair = (
            str(row.get("target_id") or ""),
            str(row.get("predictor_id") or ""),
        )
        if pair not in observed:
            unexpected_pairs.append(list(pair))
            continue
        observed[pair].append(row)
    if unexpected_pairs:
        _failure(
            failures,
            "receipt_unexpected_pairs",
            "submission receipt contains target/predictor pairs outside scope",
            pairs=unexpected_pairs,
        )

    jobs: List[Dict[str, str]] = []
    for target_id, predictor_id in expected_pairs:
        pair_rows = observed[(target_id, predictor_id)]
        if len(pair_rows) != 1:
            _failure(
                failures,
                "receipt_pair_count_invalid",
                "receipt must contain exactly one row per frozen pair",
                target_id=target_id,
                predictor_id=predictor_id,
                observed=len(pair_rows),
            )
            continue
        row = pair_rows[0]
        job_id = str(row.get("job_id") or "")
        contract_ok = (
            row.get("artifact") == "m6d_w3c_b2_submission_receipt_row"
            and row.get("version") == 1
            and row.get("status") == "scheduler_job_submitted"
            and row.get("approval_packet") == packet_path
            and row.get("approval_packet_sha256") == packet_sha256
            and row.get("retry") is False
            and row.get("adaptive_top_up") is False
            and row.get("scientific_claim_authorized") is False
            and _JOB_ID.fullmatch(job_id) is not None
        )
        if not contract_ok:
            _failure(
                failures,
                "receipt_row_contract_invalid",
                "submission receipt row differs from the frozen one-shot contract",
                target_id=target_id,
                predictor_id=predictor_id,
            )
            continue
        jobs.append(
            {
                "target_id": target_id,
                "predictor_id": predictor_id,
                "job_id": job_id,
            }
        )
    job_ids = [row["job_id"] for row in jobs]
    if len(rows) != MAXIMUM_JOBS or len(jobs) != MAXIMUM_JOBS:
        _failure(
            failures,
            "receipt_scope_invalid",
            "submission receipt must contain exactly sixteen valid rows",
            observed=len(rows),
        )
    if len(job_ids) != len(set(job_ids)):
        _failure(
            failures,
            "receipt_job_ids_not_unique",
            "each frozen evaluation must map to one unique Slurm job",
        )
    return jobs


def build_accounting(
    packet_path: str,
    receipt_path: str,
    summary_path: str,
    sacct_path: str,
) -> Dict[str, Any]:
    """Reconcile the one-shot approval against current Slurm accounting."""

    packet = load_object(packet_path)
    receipt_rows = _load_jsonl(receipt_path)
    summary = load_object(summary_path)
    failures: List[Dict[str, Any]] = []
    integrity_failures = verify_packet_integrity(packet_path)
    if integrity_failures:
        _failure(
            failures,
            "approval_packet_integrity_failed",
            "approval packet or a hash-bound producer artifact drifted",
            checks=integrity_failures,
        )
    _validate_wrapper_resources(packet, failures)
    packet_sha256 = sha256_file(packet_path)
    jobs = _receipt_jobs(
        receipt_rows,
        packet_path=packet_path,
        packet_sha256=packet_sha256,
        failures=failures,
    )
    replayed_summary = summarize_submission(packet_path, receipt_path)
    if summary != replayed_summary:
        _failure(
            failures,
            "receipt_summary_replay_mismatch",
            "committed receipt summary does not replay from packet and journal",
        )

    contract = packet.get("approval_contract")
    if not (
        isinstance(contract, dict)
        and contract.get("user_phrase") == APPROVAL_PHRASE
        and contract.get("target_ids") == TARGET_IDS
        and contract.get("predictor_ids") == PREDICTOR_IDS
        and contract.get("maximum_predictor_evaluations") == MAXIMUM_JOBS
        and contract.get("maximum_scheduler_jobs") == MAXIMUM_JOBS
        and contract.get("resource_per_evaluation") == "h100:1"
        and contract.get("maximum_walltime_per_evaluation") == "01:00:00"
        and contract.get("maximum_h100_gpu_hours") == 16.0
        and contract.get("retry_or_adaptive_top_up_allowed") is False
        and contract.get("post_execution_slurm_accounting_required") is True
        and contract.get("proteinmpnn_designs") == 0
    ):
        _failure(
            failures,
            "approval_contract_invalid",
            "approval contract differs from the frozen W3c-B2 scope",
        )

    try:
        sacct_rows = parse_sacct(Path(sacct_path).read_text())
    except ValueError as exc:
        sacct_rows = {}
        _failure(
            failures,
            "sacct_snapshot_invalid",
            "Slurm accounting snapshot is not strictly parsable",
            detail=str(exc),
        )
    expected_job_ids = {row["job_id"] for row in jobs}
    observed_job_ids = set(sacct_rows)
    missing_job_ids = sorted(expected_job_ids - observed_job_ids, key=_job_sort_key)
    unexpected_job_ids = sorted(observed_job_ids - expected_job_ids, key=_job_sort_key)
    if missing_job_ids:
        _failure(
            failures,
            "jobs_missing_from_sacct",
            "approved job IDs are absent from the accounting snapshot",
            job_ids=missing_job_ids,
        )
    if unexpected_job_ids:
        _failure(
            failures,
            "unexpected_jobs_in_sacct",
            "accounting snapshot contains jobs outside the receipt",
            job_ids=unexpected_job_ids,
        )

    job_states: List[Dict[str, Any]] = []
    pending_jobs: List[str] = []
    terminal_failures: List[str] = []
    gpu_allocation_seconds = 0
    for submitted in jobs:
        job_id = submitted["job_id"]
        state = sacct_rows.get(job_id)
        if state is None:
            continue
        expected_job_name = (
            "biosfm-w3c-b2-boltz"
            if submitted["predictor_id"] == "boltz2_complex"
            else "biosfm-w3c-b2-af2"
        )
        requested_gpus = _gpu_count(str(state.get("req_tres") or ""))
        gpu_count = _gpu_count(str(state.get("alloc_tres") or ""))
        elapsed = int(state.get("elapsed_seconds") or 0)
        gpu_allocation_seconds += gpu_count * elapsed
        row = {
            **submitted,
            **state,
            "requested_gpus": requested_gpus,
            "gpus": gpu_count,
            "gpu_type": "h100",
            "gpu_type_provenance": ("hash_bound_predictor_wrapper_gres_directive"),
        }
        job_states.append(row)
        if state.get("job_name") != expected_job_name or requested_gpus != 1:
            _failure(
                failures,
                "job_request_contract_invalid",
                "Slurm job name or requested GPU count differs from its receipt pair",
                job_id=job_id,
                expected_job_name=expected_job_name,
                observed_job_name=state.get("job_name"),
                requested_gpus=requested_gpus,
            )
        normalized = str(state.get("state") or "")
        if normalized in _ACTIVE_STATES:
            pending_jobs.append(job_id)
            continue
        if normalized != "COMPLETED" or state.get("exit_code") != "0:0":
            terminal_failures.append(job_id)
            _failure(
                failures,
                "job_terminal_failure",
                "prediction job ended outside COMPLETED/0:0; no retry is authorized",
                job_id=job_id,
                target_id=submitted["target_id"],
                predictor_id=submitted["predictor_id"],
                state=normalized,
                exit_code=state.get("exit_code"),
            )
            continue
        if gpu_count != 1 or elapsed <= 0 or elapsed > MAXIMUM_SECONDS_PER_JOB:
            _failure(
                failures,
                "job_resource_contract_invalid",
                "completed job did not use one GPU within the one-hour ceiling",
                job_id=job_id,
                gpus=gpu_count,
                elapsed_seconds=elapsed,
            )

    if gpu_allocation_seconds > MAXIMUM_H100_GPU_SECONDS:
        _failure(
            failures,
            "h100_gpu_budget_exceeded",
            "observed allocation exceeds the approved sixteen H100 GPU-hours",
            observed_gpu_seconds=gpu_allocation_seconds,
            maximum_gpu_seconds=MAXIMUM_H100_GPU_SECONDS,
        )

    terminal_successes = sum(
        row["state"] == "COMPLETED"
        and row["exit_code"] == "0:0"
        and row["gpus"] == 1
        and 0 < row["elapsed_seconds"] <= MAXIMUM_SECONDS_PER_JOB
        for row in job_states
    )
    integrity_ok = not failures
    sync_allowed = (
        integrity_ok
        and len(job_states) == MAXIMUM_JOBS
        and terminal_successes == MAXIMUM_JOBS
        and not pending_jobs
        and not terminal_failures
    )
    if sync_allowed:
        status = "w3c_b2_jobs_complete_sync_unlocked"
        next_action = (
            "Sync only the eight packet-derived target output roots, then replay "
            "strict record and output-hash validation locally."
        )
    elif terminal_failures:
        status = "w3c_b2_terminal_failure_stop_no_retry"
        next_action = (
            "Preserve the terminal failure as the one-shot outcome; a new execution "
            "would require a separately hash-bound protocol and approval."
        )
    elif failures:
        status = "w3c_b2_accounting_blocked"
        next_action = "Repair accounting or provenance evidence before any sync."
    else:
        status = "w3c_b2_jobs_pending_sync_locked"
        next_action = (
            "Wait for all sixteen jobs to reach terminal state, then query again."
        )
    return {
        "artifact": "m6d_w3c_b2_completion_accounting",
        "version": 1,
        "status": status,
        "audit_ok": integrity_ok,
        "approval_consumed": len(jobs) == MAXIMUM_JOBS,
        "required_user_phrase": APPROVAL_PHRASE,
        "jobs_expected": MAXIMUM_JOBS,
        "jobs_in_receipt": len(jobs),
        "jobs_in_sacct": len(job_states),
        "jobs_terminal_success": terminal_successes,
        "jobs_pending": len(pending_jobs),
        "pending_job_ids": sorted(pending_jobs, key=_job_sort_key),
        "missing_job_ids": missing_job_ids,
        "unexpected_job_ids": unexpected_job_ids,
        "terminal_failure_job_ids": sorted(terminal_failures, key=_job_sort_key),
        "job_states": job_states,
        "gpu_resource_requested": "h100:1",
        "gpu_resource_provenance": (
            "packet-bound H100 wrapper directives plus sacct job name, request, "
            "and allocation counts"
        ),
        "gpu_allocation_seconds_total": gpu_allocation_seconds,
        "gpu_allocation_hours_total": gpu_allocation_seconds / 3600.0,
        "approved_h100_gpu_seconds": MAXIMUM_H100_GPU_SECONDS,
        "approved_h100_gpu_hours": 16.0,
        "within_approved_h100_budget": (
            gpu_allocation_seconds <= MAXIMUM_H100_GPU_SECONDS
        ),
        "sync_allowed": sync_allowed,
        "scientific_adjudication_allowed": False,
        "retry_or_adaptive_top_up_allowed": False,
        "additional_jobs_authorized": 0,
        "proteinmpnn_designs": 0,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "no_submit": True,
        "input_bindings": {
            "approval_packet": _binding(packet_path),
            "submission_receipt": _binding(receipt_path),
            "submission_summary": _binding(summary_path),
            "sacct_snapshot": _binding(sacct_path),
        },
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Scheduler accounting and retrieval authority only. This report cannot "
            "submit work or support a scientific claim."
        ),
        "next_action": next_action,
    }


def render_accounting_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B2 Completion Accounting",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Sync allowed: `{report['sync_allowed']}`.",
        "",
        str(report["claim_boundary"]),
        "",
        f"- receipt jobs: `{report['jobs_in_receipt']}` / `16`",
        f"- terminal-success jobs: `{report['jobs_terminal_success']}` / `16`",
        f"- pending jobs: `{report['jobs_pending']}`",
        f"- H100 GPU-hours: `{report['gpu_allocation_hours_total']:.6f}` / `16.0`",
        f"- additional jobs authorized: `{report['additional_jobs_authorized']}`",
        f"- failures: `{report['n_failures']}`",
        "",
        f"Next action: {report['next_action']}",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(
            f"- `{row['kind']}`: {row['message']}" for row in report["failures"]
        )
        lines.append("")
    return "\n".join(lines)


def _path_within(path: str, root: str) -> bool:
    absolute_path = os.path.realpath(path)
    absolute_root = os.path.realpath(root)
    try:
        return os.path.commonpath([absolute_path, absolute_root]) == absolute_root
    except ValueError:
        return False


def _validate_file_binding(
    binding: Any,
    *,
    allowed_root: str,
    label: str,
) -> Dict[str, Any]:
    if not isinstance(binding, dict):
        raise ValueError(f"{label} binding is not a JSON object")
    path = binding.get("path")
    digest = binding.get("sha256")
    if not (
        isinstance(path, str)
        and path
        and _path_within(path, allowed_root)
        and isinstance(digest, str)
        and _SHA256.fullmatch(digest)
        and os.path.isfile(path)
        and os.path.getsize(path) > 0
        and sha256_file(path) == digest
    ):
        raise ValueError(f"{label} output binding failed path or hash validation")
    return {"path": path, "bytes": os.path.getsize(path), "sha256": digest}


def _record_artifacts(
    record: Mapping[str, Any],
    *,
    target_root: str,
    predictor_output_root: str,
    expected_auxiliary_name: str,
) -> Dict[str, Any]:
    output_bindings = record.get("output_bindings")
    if not isinstance(output_bindings, dict) or set(output_bindings) != {
        "model",
        "confidence",
    }:
        raise ValueError("native record must bind exactly model and confidence outputs")
    outputs = {
        name: _validate_file_binding(
            output_bindings[name],
            allowed_root=predictor_output_root,
            label=name,
        )
        for name in ("model", "confidence")
    }
    auxiliary = record.get("auxiliary_output_bindings")
    if not isinstance(auxiliary, dict) or set(auxiliary) != {expected_auxiliary_name}:
        raise ValueError(
            "native record auxiliary binding differs from the predictor contract"
        )
    outputs[expected_auxiliary_name] = _validate_file_binding(
        auxiliary[expected_auxiliary_name],
        allowed_root=target_root,
        label=expected_auxiliary_name,
    )
    return outputs


def _replay_native_metrics(
    context: Mapping[str, Any],
    record: Mapping[str, Any],
    predictor_id: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, float]:
    model_path = str(artifacts["model"]["path"])
    if predictor_id == "boltz2_complex":
        with np.load(str(artifacts["pae"]["path"])) as archive:
            if len(archive.files) != 1:
                raise ValueError("Boltz pAE archive must contain exactly one array")
            pae = np.asarray(archive[archive.files[0]], dtype=float)
    else:
        scores = load_object(str(artifacts["confidence"]["path"]))
        pae = np.asarray(scores.get("pae"), dtype=float)
    interface_pae, lrmsd = _strict_metrics(context, model_path, pae)
    recorded_pae = record.get("interface_pae")
    recorded_lrmsd = record.get("lrmsd_angstrom")
    expected_success = lrmsd < LRMSD_THRESHOLD_ANGSTROM
    if not (
        isinstance(recorded_pae, (int, float))
        and not isinstance(recorded_pae, bool)
        and math.isclose(
            float(recorded_pae), round(float(interface_pae), 4), abs_tol=5e-5
        )
        and isinstance(recorded_lrmsd, (int, float))
        and not isinstance(recorded_lrmsd, bool)
        and math.isclose(
            float(recorded_lrmsd), float(lrmsd), rel_tol=1e-9, abs_tol=1e-8
        )
        and record.get("success") is expected_success
    ):
        raise ValueError(
            f"{predictor_id} record metrics do not replay from bound outputs"
        )
    return {
        "interface_pae": round(float(interface_pae), 4),
        "lrmsd_angstrom": float(lrmsd),
    }


def _write_text_idempotent(path: str, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_text() != text:
            raise ValueError(f"refusing to overwrite divergent W3c-B2 artifact: {path}")
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=str(destination.parent)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_idempotent(path: str, value: Mapping[str, Any]) -> None:
    _write_text_idempotent(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _replay_accounting(accounting_path: str) -> Dict[str, Any]:
    accounting = load_object(accounting_path)
    bindings = accounting.get("input_bindings")
    if not isinstance(bindings, dict):
        raise ValueError("W3c-B2 accounting report lacks input bindings")
    required = {
        "approval_packet",
        "submission_receipt",
        "submission_summary",
        "sacct_snapshot",
    }
    if set(bindings) != required:
        raise ValueError("W3c-B2 accounting input binding set differs")
    for name in required:
        binding = bindings[name]
        path = binding.get("path") if isinstance(binding, dict) else None
        if not isinstance(path, str) or binding != _binding(path):
            raise ValueError(f"W3c-B2 accounting binding drifted: {name}")
    replayed = build_accounting(
        bindings["approval_packet"]["path"],
        bindings["submission_receipt"]["path"],
        bindings["submission_summary"]["path"],
        bindings["sacct_snapshot"]["path"],
    )
    if accounting != replayed:
        raise ValueError("W3c-B2 accounting report does not replay exactly")
    if not (
        accounting.get("audit_ok") is True
        and accounting.get("sync_allowed") is True
        and accounting.get("jobs_terminal_success") == MAXIMUM_JOBS
        and accounting.get("additional_jobs_authorized") == 0
        and accounting.get("retry_or_adaptive_top_up_allowed") is False
    ):
        raise ValueError("W3c-B2 outputs remain locked by terminal accounting")
    return accounting


def _matched_record(
    target: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    record_paths: Mapping[str, str],
    runtime_observation_paths: Mapping[str, str],
) -> Dict[str, Any]:
    predictor_rows = []
    for predictor_id in PREDICTOR_IDS:
        record = records[predictor_id]
        predictor_rows.append(
            {
                "predictor_id": predictor_id,
                "record": _binding(record_paths[predictor_id]),
                "runtime_observation": _binding(
                    runtime_observation_paths[predictor_id]
                ),
                "strict_qc_passed": record.get("strict_qc_passed") is True,
                "interface_pae": record.get("interface_pae"),
                "lrmsd_angstrom": record.get("lrmsd_angstrom"),
                "success": record.get("success") is True,
            }
        )
    return {
        "artifact": "m6d_w3c_b2_matched_native_record",
        "version": 1,
        "status": "w3c_b2_native_predictor_pair_complete",
        "target_id": target["target_id"],
        "native_candidate_id": target["native_candidate_id"],
        "predictor_ids": PREDICTOR_IDS,
        "predictors": predictor_rows,
        "target_pass": all(row["success"] for row in predictor_rows),
        "strict_qc_passed": all(row["strict_qc_passed"] for row in predictor_rows),
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
    }


def finalize(
    accounting_path: str,
    *,
    records_path: str = RECORDS_PATH,
    report_path: str = REPORT_PATH,
    report_md_path: str = REPORT_MD_PATH,
    completion_path: str = COMPLETION_PATH,
    completion_md_path: str = COMPLETION_MD_PATH,
) -> Dict[str, Any]:
    """Validate synced outputs and apply the frozen native-recovery rule."""

    accounting = _replay_accounting(accounting_path)
    packet_path = accounting["input_bindings"]["approval_packet"]["path"]
    packet = load_object(packet_path)
    bindings = packet["bound_artifacts"]
    manifest_path = str(bindings["native_screen_manifest"]["path"])
    runtime_lock_path = str(bindings["runtime_lock"]["path"])
    manifest = load_object(manifest_path)
    runtime_lock = load_object(runtime_lock_path)
    expected_final_paths = {records_path, report_path, report_md_path}
    if not expected_final_paths.issubset(set(packet["initial_output_paths"])):
        raise ValueError("W3c-B2 final result paths differ from the approval packet")

    manifest_targets = {
        str(row.get("target_id") or ""): row
        for row in manifest.get("targets", [])
        if isinstance(row, dict)
    }
    execution_targets = packet.get("execution_targets")
    if not (
        isinstance(execution_targets, list)
        and [row.get("target_id") for row in execution_targets] == TARGET_IDS
        and list(manifest_targets) == TARGET_IDS
    ):
        raise ValueError("W3c-B2 packet/manifest target order differs")

    ordered_records: List[Dict[str, Any]] = []
    matched: List[Tuple[str, Dict[str, Any]]] = []
    verified_output_files = 0
    replayed_metric_records = 0
    for execution_target in execution_targets:
        target_id = str(execution_target["target_id"])
        manifest_target = manifest_targets[target_id]
        target_root = str(Path(execution_target["boltz_record"]).parent)
        records_by_predictor: Dict[str, Dict[str, Any]] = {}
        paths_by_predictor: Dict[str, str] = {}
        observations_by_predictor: Dict[str, str] = {}
        for predictor_id in PREDICTOR_IDS:
            if predictor_id == "boltz2_complex":
                record_path = str(execution_target["boltz_record"])
                observation_path = str(execution_target["boltz_runtime_observation"])
                predictor_root = str(execution_target["boltz_output_dir"])
                auxiliary_name = "pae"
            else:
                record_path = str(execution_target["af2_record"])
                observation_path = str(execution_target["af2_runtime_observation"])
                predictor_root = str(execution_target["af2_output_dir"])
                auxiliary_name = "input_manifest"
            context = load_context(
                manifest_path, runtime_lock_path, target_id, predictor_id
            )
            validate_runtime_observation_file(context, observation_path)
            record = load_object(record_path)
            artifacts = _record_artifacts(
                record,
                target_root=target_root,
                predictor_output_root=predictor_root,
                expected_auxiliary_name=auxiliary_name,
            )
            _replay_native_metrics(context, record, predictor_id, artifacts)
            verified_output_files += len(artifacts)
            replayed_metric_records += 1
            records_by_predictor[predictor_id] = record
            paths_by_predictor[predictor_id] = record_path
            observations_by_predictor[predictor_id] = observation_path
            ordered_records.append(record)
        matched_path = str(execution_target["matched_record"])
        if matched_path != manifest_target["outputs"]["matched_record"]:
            raise ValueError(f"{target_id}: matched-record path drifted")
        matched.append(
            (
                matched_path,
                _matched_record(
                    execution_target,
                    records_by_predictor,
                    paths_by_predictor,
                    observations_by_predictor,
                ),
            )
        )

    scientific_report = evaluate_records(
        manifest,
        runtime_lock,
        ordered_records,
        manifest_sha256=sha256_file(manifest_path),
        runtime_lock_sha256=sha256_file(runtime_lock_path),
    )
    if scientific_report.get("audit_ok") is not True:
        raise ValueError(
            "W3c-B2 synced records failed the frozen scientific contract: "
            + json.dumps(scientific_report.get("failures"), sort_keys=True)
        )

    for path, value in matched:
        _write_json_idempotent(path, value)
    records_text = "".join(
        json.dumps(record, sort_keys=True) + "\n" for record in ordered_records
    )
    _write_text_idempotent(records_path, records_text)
    _write_json_idempotent(report_path, scientific_report)
    _write_text_idempotent(report_md_path, render_report_markdown(scientific_report))

    stage_pass = scientific_report["stage_pass"] is True
    completion = {
        "artifact": "m6d_w3c_b2_completion",
        "version": 1,
        "status": (
            "w3c_b2_complete_native_recoverability_pass"
            if stage_pass
            else "w3c_b2_complete_native_recoverability_stop"
        ),
        "audit_ok": True,
        "completion_ok": True,
        "approval_consumed": True,
        "scientific_adjudication_complete": True,
        "stage_pass": stage_pass,
        "targets_passing": scientific_report["targets_passing"],
        "minimum_targets_passing": scientific_report["minimum_targets_passing"],
        "records_expected": MAXIMUM_JOBS,
        "records_observed": len(ordered_records),
        "matched_target_records": len(matched),
        "verified_predictor_output_files": verified_output_files,
        "replayed_metric_records": replayed_metric_records,
        "observed_h100_gpu_seconds": accounting["gpu_allocation_seconds_total"],
        "observed_h100_gpu_hours": accounting["gpu_allocation_hours_total"],
        "retry_or_adaptive_top_up_allowed": False,
        "additional_jobs_authorized": 0,
        "proteinmpnn_designs": 0,
        "can_claim_native_recoverability_on_locked_panel": stage_pass,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "accounting": _binding(accounting_path),
        "native_records": _binding(records_path),
        "matched_records": [_binding(path) for path, _value in matched],
        "native_recoverability_report": _binding(report_path),
        "native_recoverability_report_markdown": _binding(report_md_path),
        "claim_boundary": scientific_report["claim_boundary"],
        "next_action": scientific_report["next_action"],
    }
    _write_json_idempotent(completion_path, completion)
    _write_text_idempotent(completion_md_path, render_completion_markdown(completion))
    return completion


def render_completion_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# M6d W3c-B2 Completion",
            "",
            f"Status: `{report['status']}`.",
            f"Audit ok: `{report['audit_ok']}`.",
            f"Stage pass: `{report['stage_pass']}`.",
            f"Targets passing: `{report['targets_passing']}` / `8`.",
            "",
            str(report["claim_boundary"]),
            "",
            f"- records: `{report['records_observed']}` / `16`",
            f"- matched targets: `{report['matched_target_records']}` / `8`",
            f"- H100 GPU-hours: `{report['observed_h100_gpu_hours']:.6f}`",
            f"- additional jobs authorized: `{report['additional_jobs_authorized']}`",
            "",
            f"Next action: {report['next_action']}",
            "",
        ]
    )


def receipt_job_ids(packet_path: str, receipt_path: str) -> List[str]:
    packet_sha256 = sha256_file(packet_path)
    failures: List[Dict[str, Any]] = []
    jobs = _receipt_jobs(
        _load_jsonl(receipt_path),
        packet_path=packet_path,
        packet_sha256=packet_sha256,
        failures=failures,
    )
    if failures or len(jobs) != MAXIMUM_JOBS:
        raise ValueError("W3c-B2 receipt cannot supply the exact sixteen job IDs")
    return [row["job_id"] for row in jobs]


def packet_sync_roots(packet_path: str) -> List[str]:
    failures = verify_packet_integrity(packet_path)
    if failures:
        raise ValueError("W3c-B2 packet integrity failed: " + ",".join(failures))
    packet = load_object(packet_path)
    roots = [
        str(Path(row["boltz_record"]).parent) for row in packet["execution_targets"]
    ]
    if len(roots) != 8 or len(set(roots)) != 8:
        raise ValueError("W3c-B2 packet does not define eight unique sync roots")
    return roots


def _write(path: str, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, destination)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    jobs = subparsers.add_parser("job-ids")
    jobs.add_argument("--packet", default=PACKET_PATH)
    jobs.add_argument("--receipt", default=RECEIPT_PATH)

    roots = subparsers.add_parser("sync-roots")
    roots.add_argument("--packet", default=PACKET_PATH)

    account = subparsers.add_parser("account")
    account.add_argument("--packet", default=PACKET_PATH)
    account.add_argument("--receipt", default=RECEIPT_PATH)
    account.add_argument("--summary", default=SUMMARY_PATH)
    account.add_argument("--sacct", default=SACCT_PATH)
    account.add_argument("--out-json", default=ACCOUNTING_PATH)
    account.add_argument("--out-md", default=ACCOUNTING_MD_PATH)
    account.add_argument("--require-sync-ready", action="store_true")

    finish = subparsers.add_parser("finalize")
    finish.add_argument("--accounting", default=ACCOUNTING_PATH)
    finish.add_argument("--records", default=RECORDS_PATH)
    finish.add_argument("--report", default=REPORT_PATH)
    finish.add_argument("--report-md", default=REPORT_MD_PATH)
    finish.add_argument("--completion", default=COMPLETION_PATH)
    finish.add_argument("--completion-md", default=COMPLETION_MD_PATH)
    args = parser.parse_args(argv)

    if args.command == "job-ids":
        print(",".join(receipt_job_ids(args.packet, args.receipt)))
        return 0
    if args.command == "sync-roots":
        print("\n".join(packet_sync_roots(args.packet)))
        return 0
    if args.command == "account":
        report = build_accounting(args.packet, args.receipt, args.summary, args.sacct)
        _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
        _write(args.out_md, render_accounting_markdown(report))
        print(
            f"status={report['status']} audit_ok={report['audit_ok']} "
            f"terminal={report['jobs_terminal_success']}/16 "
            f"sync_allowed={report['sync_allowed']} no_submit=True"
        )
        if not report["audit_ok"]:
            return 2
        if args.require_sync_ready and not report["sync_allowed"]:
            return 3
        return 0
    report = finalize(
        args.accounting,
        records_path=args.records,
        report_path=args.report,
        report_md_path=args.report_md,
        completion_path=args.completion,
        completion_md_path=args.completion_md,
    )
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"targets_passing={report['targets_passing']}/8 "
        "additional_jobs_authorized=0"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
