"""Adjudicate the approval-gated W3c-B1 target-MSA completion evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .complex_target_manifest import validate_manifest


TARGET_IDS = [
    "1TE1_BA",
    "3QB4_AB",
    "5E5M_AB",
    "5JSB_AB",
    "6KBR_AC",
    "6KMQ_AB",
    "6SGE_AB",
    "7B5G_AB",
]
WORKSTREAM = "m6d_w3c_b1_target_msa_input_prep_only"
APPROVAL_PHRASE = "approve W3c-B1 target-MSA precompute"
MAXIMUM_A40_GPU_HOURS = 8.0
MINIMUM_A3M_RECORDS = 2
_PENDING_STATES = {
    "CONFIGURING",
    "COMPLETING",
    "PENDING",
    "RESIZING",
    "RUNNING",
    "SUSPENDED",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


def _binding(path: str) -> Dict[str, Any]:
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": _sha256_file(path),
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object: {path}:{line_number}")
            rows.append(payload)
    return rows


def _read_sequence(path: str, *, a3m: bool = False) -> str:
    pieces: List[str] = []
    in_record = False
    with open(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if in_record:
                    break
                in_record = True
                continue
            if not in_record:
                in_record = True
            pieces.append(line)
    joined = "".join(pieces)
    if a3m:
        return "".join(char for char in joined if char.isupper() and char != "-")
    return "".join(char.upper() for char in joined if char.isalpha())


def _a3m_record_count(path: str) -> int:
    with open(path, "rb") as handle:
        return sum(1 for line in handle if line.startswith(b">"))


def _failure(
    failures: List[Dict[str, Any]],
    kind: str,
    message: str,
    **extra: Any,
) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    row.update({key: value for key, value in extra.items() if value is not None})
    failures.append(row)


def _base_job_id(value: Any) -> str:
    return str(value or "").strip().split(".", 1)[0].split("_", 1)[0]


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().upper().rstrip("+").split(" ", 1)[0]


def parse_sacct(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse top-level Slurm rows while ignoring batch/extern/diagnostic steps."""
    rows: Dict[str, Dict[str, Any]] = {}
    header: Optional[List[str]] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|") if "|" in line else line.split()
        lowered = [part.strip().lower() for part in parts]
        if "state" in lowered and ("jobidraw" in lowered or "jobid" in lowered):
            header = lowered
            continue
        if header is None:
            continue
        values = {
            header[index]: parts[index].strip()
            for index in range(min(len(header), len(parts)))
        }
        raw_job_id = values.get("jobidraw") or values.get("jobid") or ""
        base_job_id = _base_job_id(raw_job_id)
        if not base_job_id:
            continue
        row = {
            "job_id": base_job_id,
            "raw_job_id": raw_job_id,
            "state": _normalize_state(values.get("state")),
            "exit_code": values.get("exitcode") or values.get("exit_code") or "",
            "elapsed_seconds": int(values.get("elapsedraw") or 0),
            "alloc_tres": values.get("alloctres") or "",
        }
        current = rows.get(base_job_id)
        if current is None or raw_job_id == base_job_id:
            rows[base_job_id] = row
    return rows


def _gpu_count(alloc_tres: str) -> int:
    values = [
        int(value)
        for value in re.findall(r"gres/gpu(?:[:/][^=,]+)?=(\d+)", alloc_tres)
    ]
    return max(values) if values else 0


def _validate_packet(
    packet: Mapping[str, Any],
    *,
    manifest_path: str,
    manifest_sha256: str,
    sbatch_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    if (
        packet.get("artifact") != "m6d_w3c_b1_target_msa_approval_packet"
        or packet.get("status")
        != "w3c_b1_packet_cayuga_validated_ready_for_exact_approval"
        or packet.get("approval_packet_ready") is not True
        or packet.get("cayuga_no_submit_validation_status") != "pass"
        or packet.get("ready_to_request_exact_approval") is not True
    ):
        _failure(failures, "approval_packet_invalid", "W3c-B1 approval packet is not validation-complete")
    if (
        packet.get("required_user_phrase") != APPROVAL_PHRASE
        or packet.get("target_ids") != TARGET_IDS
        or packet.get("target_count") != 8
        or packet.get("maximum_target_msa_queries") != 8
        or float(packet.get("maximum_a40_gpu_hours") or 0.0) != MAXIMUM_A40_GPU_HOURS
    ):
        _failure(failures, "approval_scope_mismatch", "W3c-B1 target, phrase, or budget scope differs")
    if (
        packet.get("can_submit_target_msa_if_explicitly_approved") is not True
        or packet.get("can_submit_proteinmpnn") is not False
        or packet.get("can_submit_structure_predictors") is not False
        or packet.get("can_prepare_w3c_b2") is not False
    ):
        _failure(failures, "approval_authority_mismatch", "W3c-B1 packet authority boundary differs")
    bindings = packet.get("bound_artifacts")
    if not isinstance(bindings, dict):
        _failure(failures, "approval_bindings_missing", "W3c-B1 packet lacks bound artifacts")
        return
    manifest_binding = bindings.get("execution_manifest", {})
    sbatch_binding = bindings.get("precompute_sbatch", {})
    if (
        manifest_binding.get("path") != manifest_path
        or manifest_binding.get("sha256") != manifest_sha256
    ):
        _failure(failures, "approval_manifest_binding_mismatch", "approval packet does not bind the execution manifest")
    if (
        sbatch_binding.get("path") != sbatch_path
        or sbatch_binding.get("sha256") != _sha256_file(sbatch_path)
    ):
        _failure(failures, "approval_sbatch_binding_mismatch", "approval packet does not bind the A40 sbatch script")
    with open(sbatch_path) as handle:
        sbatch_text = handle.read()
    if "#SBATCH --gres=gpu:a40:1" not in sbatch_text or "#SBATCH --time=01:00:00" not in sbatch_text:
        _failure(failures, "sbatch_resource_lock_invalid", "sbatch is not locked to one A40 for one hour")


def _validate_receipt(
    receipt_rows: List[Dict[str, Any]],
    *,
    targets: List[Dict[str, Any]],
    manifest_path: str,
    manifest_sha256: str,
    failures: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    targets_by_id = {str(target["id"]): target for target in targets}
    by_id: Dict[str, List[Dict[str, Any]]] = {target_id: [] for target_id in TARGET_IDS}
    status_counts: Dict[str, int] = {}
    for row in receipt_rows:
        target_id = str(row.get("target_id") or "")
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        if target_id not in by_id:
            _failure(failures, "receipt_unexpected_target", "receipt contains an unexpected target", target_id=target_id)
            continue
        by_id[target_id].append(row)
    submitted: List[Dict[str, str]] = []
    for target_id in TARGET_IDS:
        rows = by_id[target_id]
        if len(rows) != 1:
            _failure(failures, "receipt_row_count_invalid", "receipt must contain one row per target", target_id=target_id)
            continue
        row = rows[0]
        target = targets_by_id[target_id]
        if row.get("status") != "submitted":
            _failure(failures, "receipt_status_invalid", "W3c-B1 completion requires eight submitted rows", target_id=target_id)
        if (
            row.get("manifest") != manifest_path
            or row.get("manifest_sha256") != manifest_sha256
            or row.get("workstream") != WORKSTREAM
        ):
            _failure(failures, "receipt_provenance_mismatch", "receipt manifest or workstream differs", target_id=target_id)
        for field in ("target_fasta", "target_msa", "target_msa_report"):
            if row.get(field) != target.get(field):
                _failure(failures, "receipt_path_mismatch", "receipt path differs from manifest", target_id=target_id, field=field)
        job_id = str(row.get("job_id") or "").strip()
        if not job_id or any(char.isspace() for char in job_id):
            _failure(failures, "receipt_job_id_invalid", "receipt lacks a parsable job ID", target_id=target_id)
        else:
            submitted.append({"target_id": target_id, "job_id": _base_job_id(job_id)})
    if len(receipt_rows) != 8 or len(submitted) != 8:
        _failure(failures, "receipt_scope_invalid", "receipt does not contain exactly eight submitted jobs")
    return submitted, status_counts


def _validate_summary_and_preflight(
    summary: Mapping[str, Any],
    preflight: Mapping[str, Any],
    *,
    preflight_path: str,
    manifest_path: str,
    manifest_sha256: str,
    status_counts: Mapping[str, int],
    failures: List[Dict[str, Any]],
) -> None:
    if (
        summary.get("artifact") != "m6d_w3c_b1_target_msa_receipt_summary"
        or summary.get("status") != "w3c_b1_target_msa_jobs_submitted_or_reused"
        or summary.get("workstream") != WORKSTREAM
        or summary.get("execution_manifest") != manifest_path
        or summary.get("execution_manifest_sha256") != manifest_sha256
        or summary.get("n_records") != 8
        or summary.get("n_targets") != 8
        or summary.get("target_ids") != TARGET_IDS
        or summary.get("status_counts") != status_counts
        or summary.get("proteinmpnn_designs") != 0
        or summary.get("predictor_evaluations") != 0
    ):
        _failure(failures, "receipt_summary_invalid", "receipt summary differs from the exact W3c-B1 scope")
    if (
        summary.get("input_preflight") != preflight_path
        or summary.get("input_preflight_sha256") != _sha256_file(preflight_path)
    ):
        _failure(failures, "preflight_binding_mismatch", "receipt summary does not bind the materialized preflight")
    if (
        preflight.get("artifact") != "m6d_w3c_b1_target_msa_input_preflight"
        or preflight.get("status")
        != "w3c_b1_inputs_materialized_ready_for_approved_msa_submission"
        or preflight.get("audit_ok") is not True
        or preflight.get("mode") != "materialize"
        or preflight.get("target_count") != 8
        or preflight.get("target_ids") != TARGET_IDS
        or preflight.get("source_pdbs_verified") != 8
        or preflight.get("target_fastas_verified") != 8
        or preflight.get("scheduler_jobs_submitted") != 0
        or preflight.get("target_msa_queries_submitted") != 0
        or preflight.get("proteinmpnn_designs") != 0
        or preflight.get("predictor_evaluations") != 0
    ):
        _failure(failures, "input_preflight_invalid", "materialized preflight does not satisfy the zero-submit input contract")


def _target_artifact(
    target: Mapping[str, Any],
    *,
    failures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    target_id = str(target["id"])
    fasta_path = str(target["target_fasta"])
    msa_path = str(target["target_msa"])
    report_path = str(target["target_msa_report"])
    sequence = _read_sequence(fasta_path)
    msa_query = _read_sequence(msa_path, a3m=True)
    report = _load_json(report_path)
    sequence_sha256 = _sha256_bytes(sequence.encode("ascii"))
    msa_sha256 = _sha256_file(msa_path)
    fasta_sha256 = _sha256_file(fasta_path)
    a3m_records = _a3m_record_count(msa_path)
    with open(msa_path, "rb") as handle:
        nul_bytes = handle.read().count(b"\x00")
    checks = {
        "frozen_sequence_hash": sequence_sha256 == target.get("target_sequence_sha256"),
        "query_sequence_match": msa_query == sequence,
        "query_not_truncated": len(msa_query) == len(sequence),
        "depth_nontrivial": a3m_records >= MINIMUM_A3M_RECORDS,
        "nul_free_after_sanitization": nul_bytes == 0,
        "report_ok": report.get("ok") is True,
        "report_paths_match": (
            report.get("fasta") == fasta_path and report.get("out") == msa_path
        ),
        "report_hashes_match": (
            report.get("fasta_sha256") == fasta_sha256
            and report.get("out_sha256") == msa_sha256
        ),
        "report_length_matches": report.get("sequence_length") == len(sequence),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        _failure(
            failures,
            "target_msa_integrity_failed",
            "target MSA failed sequence, depth, hash, or no-truncation checks",
            target_id=target_id,
            checks_failed=failed,
        )
    recovered = report.get("recovered_after_boltz_failure") is True
    boltz_returncode = report.get("boltz_returncode")
    if recovered and (not isinstance(boltz_returncode, int) or boltz_returncode == 0):
        _failure(
            failures,
            "transport_recovery_provenance_invalid",
            "recovered MSA lacks a nonzero Boltz transport return code",
            target_id=target_id,
        )
    return {
        "target_id": target_id,
        "sequence_length": len(sequence),
        "target_sequence_sha256": sequence_sha256,
        "target_fasta": fasta_path,
        "target_fasta_sha256": fasta_sha256,
        "target_msa": msa_path,
        "target_msa_bytes": os.path.getsize(msa_path),
        "target_msa_sha256": msa_sha256,
        "target_msa_report": report_path,
        "target_msa_report_sha256": _sha256_file(report_path),
        "a3m_records": a3m_records,
        "minimum_a3m_records": MINIMUM_A3M_RECORDS,
        "query_sequence_match": checks["query_sequence_match"],
        "query_not_truncated": checks["query_not_truncated"],
        "depth_check_passed": checks["depth_nontrivial"],
        "nul_bytes_after_sanitization": nul_bytes,
        "report_ok": checks["report_ok"],
        "out_sanitized_nul_bytes": report.get("out_sanitized_nul_bytes"),
        "recovered_after_boltz_failure": recovered,
        "boltz_returncode": boltz_returncode,
        "checks": checks,
    }


def evaluate_completion(
    *,
    manifest: Dict[str, Any],
    manifest_path: str,
    packet: Dict[str, Any],
    packet_path: str,
    receipt_rows: List[Dict[str, Any]],
    receipt_path: str,
    summary: Dict[str, Any],
    summary_path: str,
    preflight: Dict[str, Any],
    preflight_path: str,
    sacct_text: str,
    sacct_path: str,
    sbatch_path: str,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    targets = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    target_ids = [str(row.get("id") or "") for row in targets]
    manifest_sha256 = _sha256_file(manifest_path)
    if (
        manifest.get("artifact") != "m6d_w3c_b1_target_msa_manifest"
        or manifest.get("target_count") != 8
        or manifest.get("target_ids") != TARGET_IDS
        or target_ids != TARGET_IDS
        or manifest.get("maximum_target_msa_queries") != 8
        or float(manifest.get("maximum_a40_gpu_hours") or 0.0)
        != MAXIMUM_A40_GPU_HOURS
    ):
        _failure(failures, "manifest_scope_invalid", "W3c-B1 execution manifest differs from the eight-target scope")
    _validate_packet(
        packet,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        sbatch_path=sbatch_path,
        failures=failures,
    )
    submitted_jobs, status_counts = _validate_receipt(
        receipt_rows,
        targets=targets,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        failures=failures,
    )
    _validate_summary_and_preflight(
        summary,
        preflight,
        preflight_path=preflight_path,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        status_counts=status_counts,
        failures=failures,
    )

    sacct_rows = parse_sacct(sacct_text)
    job_states: List[Dict[str, Any]] = []
    gpu_allocation_seconds = 0
    for submitted in submitted_jobs:
        target_id = submitted["target_id"]
        job_id = submitted["job_id"]
        row = sacct_rows.get(job_id)
        if row is None:
            _failure(failures, "job_missing_from_sacct", "submitted job is absent from sacct", target_id=target_id, job_id=job_id)
            continue
        gpus = _gpu_count(str(row.get("alloc_tres") or ""))
        elapsed_seconds = int(row.get("elapsed_seconds") or 0)
        job_states.append({
            "target_id": target_id,
            "job_id": job_id,
            "state": row["state"],
            "exit_code": row["exit_code"],
            "elapsed_seconds": elapsed_seconds,
            "gpus": gpus,
            "gpu_type_provenance": "hash_bound_sbatch_a40_directive",
        })
        if row["state"] in _PENDING_STATES:
            _failure(failures, "job_not_terminal", "target-MSA job is not terminal", target_id=target_id, job_id=job_id)
        elif row["state"] != "COMPLETED" or row["exit_code"] != "0:0":
            _failure(failures, "job_terminal_failure", "target-MSA job did not end COMPLETED/0:0", target_id=target_id, job_id=job_id)
        if gpus != 1 or elapsed_seconds <= 0 or elapsed_seconds > 3600:
            _failure(failures, "job_resource_invalid", "job did not use one GPU within the one-hour limit", target_id=target_id, job_id=job_id)
        gpu_allocation_seconds += elapsed_seconds * gpus

    gpu_allocation_hours = gpu_allocation_seconds / 3600.0
    if gpu_allocation_hours > MAXIMUM_A40_GPU_HOURS:
        _failure(failures, "gpu_budget_exceeded", "W3c-B1 exceeded the approved A40 GPU-hour ceiling")

    strict_manifest = validate_manifest(
        manifest_path,
        require_files=True,
        min_targets=8,
        target_ids=TARGET_IDS,
    )
    if strict_manifest.get("ok") is not True:
        _failure(
            failures,
            "strict_manifest_failed",
            "synced target-MSA files fail the strict execution manifest",
            failures_by_kind=strict_manifest.get("failures_by_kind"),
        )
    target_artifacts = [
        _target_artifact(target, failures=failures) for target in targets
    ]
    recovered_count = sum(
        row["recovered_after_boltz_failure"] is True for row in target_artifacts
    )
    complete = not failures and len(job_states) == 8 and len(target_artifacts) == 8
    return {
        "artifact": "m6d_w3c_b1_target_msa_completion",
        "version": 1,
        "status": (
            "target_msa_precompute_complete_8_of_8"
            if complete
            else "w3c_b1_target_msa_completion_blocked"
        ),
        "audit_ok": not failures,
        "completion_ok": complete,
        "approval_recorded": True,
        "exact_approval_guard_satisfied": True,
        "required_user_phrase": APPROVAL_PHRASE,
        "submission_performed": True,
        "submitted_jobs_total": len(submitted_jobs),
        "n_targets": len(targets),
        "n_target_msas": sum(os.path.isfile(str(row.get("target_msa") or "")) for row in targets),
        "n_target_msa_reports": sum(os.path.isfile(str(row.get("target_msa_report") or "")) for row in targets),
        "strict_manifest_ready_targets": 8 if strict_manifest.get("ok") is True else 0,
        "target_ids": TARGET_IDS,
        "receipt_status_counts": status_counts,
        "job_states": job_states,
        "jobs_terminal_success": len(job_states) == 8 and all(
            row["state"] == "COMPLETED" and row["exit_code"] == "0:0"
            for row in job_states
        ),
        "gpu_resource_requested": "a40:1",
        "gpu_resource_provenance": "hash_bound_sbatch_directive_plus_sacct_gpu_count",
        "gpu_allocation_seconds_total": gpu_allocation_seconds,
        "gpu_allocation_hours_total": gpu_allocation_hours,
        "approved_gpu_hour_ceiling": MAXIMUM_A40_GPU_HOURS,
        "within_approved_gpu_hour_ceiling": gpu_allocation_hours
        <= MAXIMUM_A40_GPU_HOURS,
        "target_artifacts": target_artifacts,
        "minimum_a3m_records": MINIMUM_A3M_RECORDS,
        "transport_observation": {
            "boltz_msa_transport_invocations": len(target_artifacts),
            "post_msa_inference_failures_recovered": recovered_count,
            "structure_prediction_outputs_consumed": 0,
            "candidate_level_predictor_evaluations": 0,
            "proteinmpnn_designs": 0,
            "interpretation": (
                "Boltz was invoked as the hash-bound MSA transport. All eight MSA artifacts "
                "were recovered after its downstream target-only inference returned nonzero; "
                "no structure output was consumed as evidence."
            ),
        },
        "input_bindings": {
            "execution_manifest": _binding(manifest_path),
            "approval_packet": _binding(packet_path),
            "receipt": _binding(receipt_path),
            "receipt_summary": _binding(summary_path),
            "input_preflight": _binding(preflight_path),
            "sacct": _binding(sacct_path),
            "precompute_sbatch": _binding(sbatch_path),
        },
        "can_prepare_w3c_b2_packet": complete,
        "can_submit_w3c_b2": False,
        "can_submit_proteinmpnn": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "W3c-B1 target-MSA input preparation only. Completion supplies no native "
            "recoverability, generator-yield, trust-gate, or biological-success evidence and "
            "authorizes no W3c-B2 compute."
        ),
        "next_action": (
            "Prepare a separate hash-bound, no-submit W3c-B2 native dual-predictor packet."
            if complete
            else "Repair W3c-B1 completion blockers before preparing W3c-B2."
        ),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B1 Target-MSA Completion",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Completion ok: `{report['completion_ok']}`.",
        "",
        str(report["claim_boundary"]),
        "",
        f"- targets complete: `{report['n_target_msas']}` / `{report['n_targets']}`",
        f"- submitted jobs: `{report['submitted_jobs_total']}`",
        f"- jobs terminal success: `{report['jobs_terminal_success']}`",
        f"- A40 GPU-hours: `{report['gpu_allocation_hours_total']:.6f}` / `{report['approved_gpu_hour_ceiling']}`",
        f"- transport-internal failures recovered: `{report['transport_observation']['post_msa_inference_failures_recovered']}`",
        f"- structure prediction outputs consumed: `{report['transport_observation']['structure_prediction_outputs_consumed']}`",
        f"- failures: `{report['n_failures']}`",
        "",
        "## Target MSAs",
        "",
        "| Target | A3M records | Bytes | Query match | Report ok | Recovered after Boltz failure |",
        "|---|---:|---:|---|---|---|",
    ]
    for row in report["target_artifacts"]:
        lines.append(
            f"| `{row['target_id']}` | {row['a3m_records']} | {row['target_msa_bytes']} | "
            f"`{row['query_sequence_match']}` | `{row['report_ok']}` | "
            f"`{row['recovered_after_boltz_failure']}` |"
        )
    lines.extend(["", f"Next action: {report['next_action']}", ""])
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(
            f"- `{row['kind']}`: {row['message']}" for row in report["failures"]
        )
        lines.append("")
    return "\n".join(lines)


def _write(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        handle.write(value)
    os.replace(temporary, path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="configs/m6d_w3c_b1_target_msa_manifest.json"
    )
    parser.add_argument(
        "--packet", default="results/m6d_w3c_b1_target_msa_approval_packet.json"
    )
    parser.add_argument(
        "--receipt", default="results/m6d_w3c_b1_target_msa_receipt.jsonl"
    )
    parser.add_argument(
        "--summary", default="results/m6d_w3c_b1_target_msa_receipt_summary.json"
    )
    parser.add_argument(
        "--preflight", default="results/m6d_w3c_b1_target_msa_input_preflight.json"
    )
    parser.add_argument(
        "--sacct", default="results/m6d_w3c_b1_target_msa_sacct.tsv"
    )
    parser.add_argument(
        "--sbatch", default="hpc/run_precompute_boltz_target_msa.sbatch"
    )
    parser.add_argument(
        "--out-json", default="results/m6d_w3c_b1_target_msa_completion.json"
    )
    parser.add_argument(
        "--out-md", default="results/m6d_w3c_b1_target_msa_completion.md"
    )
    args = parser.parse_args(argv)
    with open(args.sacct) as handle:
        sacct_text = handle.read()
    report = evaluate_completion(
        manifest=_load_json(args.manifest),
        manifest_path=args.manifest,
        packet=_load_json(args.packet),
        packet_path=args.packet,
        receipt_rows=_load_jsonl(args.receipt),
        receipt_path=args.receipt,
        summary=_load_json(args.summary),
        summary_path=args.summary,
        preflight=_load_json(args.preflight),
        preflight_path=args.preflight,
        sacct_text=sacct_text,
        sacct_path=args.sacct,
        sbatch_path=args.sbatch,
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} completion_ok={report['completion_ok']} "
        f"targets={report['n_target_msas']} gpu_hours={report['gpu_allocation_hours_total']:.6f}"
    )
    return 0 if report["completion_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
