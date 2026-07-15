"""Audit and guard the W3b fit AF2 path-only recovery."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
)
from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_jsonl,
    load_object,
    load_target_context,
    sha256_file,
    validate_candidates,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_observation import (
    verify_observation,
)


_ENVIRONMENT_VARIABLE = "BIO_SFM_APPROVE_W3B_AF2_RECOVERY"
_WORKSTREAM = "m6d_w3b_fit_af2_path_recovery"
_RECOVERY_TIME_LIMIT = "03:59:30"
_RECOVERY_SECONDS_PER_JOB = 3 * 3600 + 59 * 60 + 30
_ORIGINAL_BOLTZ_MAX_SECONDS = 3 * 4 * 3600
_PROTOCOL_MAX_SECONDS = 24 * 3600
_RECOVERY_WRAPPER = "hpc/run_predict_af2_w3b_fit_recovery.sbatch"
_RECOVERY_BRIDGE = "hpc/m6d_w3b_fit_af2_recovery_with_receipt.sh"
_RECOVERY_MODULE = (
    "src/bio_sfm_designer/experiments/m6d_w3b_fit_af2_recovery.py"
)
_BOUND_RUNTIME_PATHS = (
    "hpc/convert_w3b_af2_outputs.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_matched_records.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_producer_contract.py",
    "src/bio_sfm_designer/experiments/m6d_w3b_runtime_observation.py",
)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: str, value: Mapping[str, Any], *, overwrite: bool = False) -> None:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise ValueError(f"refusing to overwrite recovery artifact: {path}")
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


def _file_binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required recovery artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path),
    }


def _read_sacct(job_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ordered = [str(job_id) for job_id in job_ids]
    command = [
        "sacct",
        "-j",
        ",".join(ordered),
        "--allocations",
        "--noheader",
        "--parsable2",
        "--starttime",
        "1970-01-01",
        "--format",
        "JobIDRaw,State,ExitCode,ElapsedRaw,AllocTRES,NodeList",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(f"sacct failed: {result.stderr.strip()}")
    rows: Dict[str, Dict[str, Any]] = {}
    reader = csv.reader(io.StringIO(result.stdout), delimiter="|")
    for values in reader:
        if len(values) < 6:
            continue
        job_id, state, exit_code, elapsed_raw, alloc_tres, node_list = values[:6]
        if job_id not in ordered:
            continue
        rows[job_id] = {
            "job_id": job_id,
            "state": state.split()[0].split("+")[0],
            "exit_code": exit_code,
            "elapsed_seconds": int(elapsed_raw),
            "alloc_tres": alloc_tres,
            "node_list": node_list,
        }
    missing = sorted(set(ordered) - set(rows))
    if missing:
        raise ValueError("sacct is missing jobs: " + ",".join(missing))
    return rows


def _validate_af2_partial(
    target: Mapping[str, Any],
    *,
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
) -> Dict[str, Any]:
    target_id = str(target["target_id"])
    context = load_target_context(
        protocol_path,
        execution_manifest_path,
        input_lock_path,
        runtime_lock_path,
        target_id,
        "fit",
    )
    candidates_path = str(target["candidates"])
    candidates = validate_candidates(context, candidates_path)
    if len(candidates) != 60:
        raise ValueError(f"target_id={target_id} requires exactly 60 candidates")

    root = Path(str(target["out_prefix"]))
    input_dir = root / "af2_inputs"
    input_manifest_path = root / "af2_input_manifest.json"
    output_dir = root / "af2_predictions"
    runtime_identity_path = root / "af2_observed_runtime_identity.json"
    runtime_receipt_path = root / "af2_multimer_runtime_receipt.json"
    records_path = Path(str(target["af2_records"]))
    manifest = load_object(input_manifest_path)
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    by_candidate = {
        str(row.get("candidate_id") or ""): row
        for row in rows
        if isinstance(row, dict)
    }
    if not (
        manifest.get("artifact") == "m6d_w3b_af2_input_manifest"
        and manifest.get("status") == "w3b_af2_inputs_ready_for_locked_prediction"
        and manifest.get("target_id") == target_id
        and manifest.get("experimental_role") == "fit"
        and manifest.get("seed_namespace") == "w3b-fit-v1"
        and manifest.get("n_candidates") == 60
        and manifest.get("candidates") == candidates_path
        and manifest.get("candidates_sha256") == sha256_file(candidates_path)
        and manifest.get("input_dir") == str(input_dir)
        and manifest.get("target_msa_sha256") == target.get("target_msa_sha256")
        and len(rows) == len(by_candidate) == 60
    ):
        raise ValueError(f"target_id={target_id} AF2 input manifest is invalid")

    target_msa_text = Path(str(target["target_msa"])).read_text()
    aggregate: List[Dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["id"])
        row = by_candidate.get(candidate_id)
        expected_path = input_dir / f"{candidate_id}.a3m"
        if not isinstance(row, dict) or row.get("a3m_path") != str(expected_path):
            raise ValueError(f"target_id={target_id} AF2 row path mismatch for {candidate_id}")
        expected_a3m = build_annotated_multimer_a3m(
            target_msa_text,
            str(candidate["target_seq"]),
            str(candidate["representation"]),
        )
        expected_sha256 = hashlib.sha256(expected_a3m.encode("utf-8")).hexdigest()
        if not expected_path.is_file() or sha256_file(expected_path) != expected_sha256:
            raise ValueError(f"target_id={target_id} AF2 input hash mismatch for {candidate_id}")
        if row.get("a3m_sha256") != expected_sha256:
            raise ValueError(f"target_id={target_id} AF2 manifest hash mismatch for {candidate_id}")
        aggregate.append({"candidate_id": candidate_id, "sha256": expected_sha256})

    if not output_dir.is_dir() or any(output_dir.iterdir()):
        raise ValueError(f"target_id={target_id} AF2 failed output directory must exist and be empty")
    if records_path.exists() or runtime_receipt_path.exists():
        raise ValueError(f"target_id={target_id} already has terminal AF2 artifacts")
    runtime_identity = load_object(runtime_identity_path)
    verify_observation(
        runtime_identity,
        "af2_multimer_colabfold_v1",
        protocol_path,
        runtime_lock_path,
    )
    return {
        "target_id": target_id,
        "candidates": _file_binding(candidates_path),
        "af2_input_manifest": _file_binding(str(input_manifest_path)),
        "af2_input_count": 60,
        "af2_input_digest_sha256": _canonical_sha256(aggregate),
        "af2_runtime_identity": _file_binding(str(runtime_identity_path)),
        "af2_output_dir": str(output_dir),
        "af2_output_dir_empty": True,
        "af2_records": str(records_path),
        "af2_runtime_receipt": str(runtime_receipt_path),
        "terminal_af2_outputs_absent": True,
    }


def observe_initial_execution(
    approval_packet_path: str,
    submission_receipt_path: str,
    submission_summary_path: str,
    *,
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
    log_root: str,
) -> Dict[str, Any]:
    packet = load_object(approval_packet_path)
    summary = load_object(submission_summary_path)
    if not (
        packet.get("artifact") == "m6d_w3b_fit_approval_packet"
        and packet.get("status") == "w3b_fit_approval_packet_ready_no_submit"
        and packet.get("approval_recorded") is False
        and summary.get("artifact") == "m6d_w3b_fit_submit_receipt_summary"
        and summary.get("status") == "w3b_fit_jobs_submitted_awaiting_completion"
        and summary.get("n_jobs") == 9
        and summary.get("approval_packet_sha256") == sha256_file(approval_packet_path)
        and summary.get("receipt_sha256") == sha256_file(submission_receipt_path)
    ):
        raise ValueError("initial W3b fit submission evidence is invalid")
    targets = {
        str(row["target_id"]): row
        for row in packet.get("fit_targets", [])
        if isinstance(row, dict)
    }
    submitted = {
        str(row["target_id"]): row
        for row in summary.get("targets", [])
        if isinstance(row, dict)
    }
    if set(targets) != set(submitted) or len(targets) != 3:
        raise ValueError("initial W3b fit target scope is invalid")
    job_ids = [
        str(submitted[target_id][field])
        for target_id in sorted(submitted)
        for field in ("proteinmpnn_job_id", "boltz_job_id", "af2_job_id")
    ]
    states = _read_sacct(job_ids)
    target_reports: List[Dict[str, Any]] = []
    failed_af2_seconds = 0
    for target_id in sorted(targets):
        jobs = submitted[target_id]
        proteinmpnn = states[str(jobs["proteinmpnn_job_id"])]
        boltz = states[str(jobs["boltz_job_id"])]
        af2 = states[str(jobs["af2_job_id"])]
        if not (proteinmpnn["state"] == "COMPLETED" and proteinmpnn["exit_code"] == "0:0"):
            raise ValueError(f"target_id={target_id} ProteinMPNN is not terminal-success")
        if boltz["state"] not in {"PENDING", "RUNNING", "COMPLETED"}:
            raise ValueError(f"target_id={target_id} Boltz state is not recovery-compatible")
        if not (af2["state"] == "FAILED" and af2["exit_code"] == "1:0"):
            raise ValueError(f"target_id={target_id} AF2 does not have the frozen path failure")
        if "gres/gpu=1" not in af2["alloc_tres"]:
            raise ValueError(f"target_id={target_id} failed AF2 job lacks one-GPU accounting")
        failed_af2_seconds += int(af2["elapsed_seconds"])
        error_path = Path(log_root) / f"biosfm-w3b-fit-af2-{af2['job_id']}.err"
        output_path = Path(log_root) / f"biosfm-w3b-fit-af2-{af2['job_id']}.out"
        error_text = error_path.read_text()
        output_text = output_path.read_text()
        missing_path = f"{targets[target_id]['out_prefix']}/af2_inputs could not be found"
        if not (
            missing_path in error_text
            and "OSError:" in error_text
            and "runtime_identity_match=True" in output_text
            and "W3b AF2 GPU preflight devices:" in output_text
        ):
            raise ValueError(f"target_id={target_id} AF2 failure signature is not path-only")
        partial = _validate_af2_partial(
            targets[target_id],
            protocol_path=protocol_path,
            execution_manifest_path=execution_manifest_path,
            input_lock_path=input_lock_path,
            runtime_lock_path=runtime_lock_path,
        )
        target_reports.append({
            "target_id": target_id,
            "proteinmpnn": proteinmpnn,
            "boltz": boltz,
            "failed_af2": af2,
            "failure_kind": "container_relative_input_path_not_found_before_prediction",
            "error_log": _file_binding(str(error_path)),
            "output_log": _file_binding(str(output_path)),
            "partial_state": partial,
        })
    if failed_af2_seconds + 3 * _RECOVERY_SECONDS_PER_JOB > 3 * 4 * 3600:
        raise ValueError("failed plus recovery AF2 allocation would exceed the original AF2 budget")
    return {
        "artifact": "m6d_w3b_fit_initial_execution_observation",
        "version": 1,
        "status": "w3b_fit_af2_path_failure_recovery_eligible_no_submit",
        "audit_ok": True,
        "approval_packet": _file_binding(approval_packet_path),
        "submission_receipt": _file_binding(submission_receipt_path),
        "submission_summary": _file_binding(submission_summary_path),
        "n_targets": 3,
        "n_initial_jobs": 9,
        "n_proteinmpnn_completed": 3,
        "n_af2_failed_before_prediction": 3,
        "initial_failed_af2_gpu_seconds": failed_af2_seconds,
        "target_reports": target_reports,
        "recovery_submission_performed": False,
        "no_submit": True,
        "can_claim_w3b": False,
        "claim_boundary": (
            "Operational failure evidence only. The initial AF2 jobs failed before prediction; "
            "no recovery compute, fit result, certification, held-out test, or claim is authorized."
        ),
    }


def _recovery_phrase(job_ids: Sequence[str]) -> str:
    return "approve W3b AF2 fit recovery for failed jobs " + ",".join(job_ids) + " on H100"


def _recovery_token(job_ids: Sequence[str]) -> str:
    return "approve-w3b-af2-fit-recovery-" + "-".join(job_ids) + "-h100"


def build_recovery_packet(
    observation_path: str,
    *,
    source_paths: Sequence[str] = (
        _RECOVERY_WRAPPER,
        _RECOVERY_BRIDGE,
        _RECOVERY_MODULE,
        *_BOUND_RUNTIME_PATHS,
    ),
) -> Dict[str, Any]:
    observation = load_object(observation_path)
    reports = observation.get("target_reports")
    if not (
        observation.get("artifact") == "m6d_w3b_fit_initial_execution_observation"
        and observation.get("status") == "w3b_fit_af2_path_failure_recovery_eligible_no_submit"
        and observation.get("audit_ok") is True
        and observation.get("n_targets") == 3
        and observation.get("n_af2_failed_before_prediction") == 3
        and observation.get("recovery_submission_performed") is False
        and observation.get("no_submit") is True
        and isinstance(reports, list)
        and len(reports) == 3
    ):
        raise ValueError("W3b AF2 recovery observation is not approval-packet eligible")
    job_ids = sorted(
        (str(report["failed_af2"]["job_id"]) for report in reports),
        key=int,
    )
    initial_seconds = int(observation["initial_failed_af2_gpu_seconds"])
    recovery_seconds = 3 * _RECOVERY_SECONDS_PER_JOB
    maximum_seconds = _ORIGINAL_BOLTZ_MAX_SECONDS + initial_seconds + recovery_seconds
    if maximum_seconds >= _PROTOCOL_MAX_SECONDS:
        raise ValueError("W3b AF2 recovery would violate the 24 H100 GPU-hour ceiling")
    bound_artifacts = [_file_binding(observation_path)] + [
        _file_binding(path) for path in source_paths
    ]
    contract = {
        "user_phrase": _recovery_phrase(job_ids),
        "environment_variable": _ENVIRONMENT_VARIABLE,
        "environment_value": _recovery_token(job_ids),
        "stage": "fit_af2_path_recovery",
        "failed_af2_job_ids": job_ids,
        "target_count": 3,
        "af2_h100_recovery_jobs": 3,
        "proteinmpnn_jobs_authorized": 0,
        "boltz_jobs_authorized": 0,
        "recovery_time_limit": _RECOVERY_TIME_LIMIT,
        "requeue": False,
        "initial_failed_af2_gpu_seconds": initial_seconds,
        "maximum_original_boltz_gpu_seconds": _ORIGINAL_BOLTZ_MAX_SECONDS,
        "maximum_recovery_af2_gpu_seconds": recovery_seconds,
        "maximum_protocol_gpu_seconds_after_recovery": maximum_seconds,
        "maximum_protocol_h100_gpu_hours": 24.0,
        "authorizes_certification": False,
        "authorizes_held_out_test": False,
        "authorizes_adaptive_top_up": False,
        "authorizes_claim": False,
    }
    digest = _canonical_sha256({
        "contract": contract,
        "bound_artifacts": {row["path"]: row["sha256"] for row in bound_artifacts},
        "targets": [
            {
                "target_id": row["target_id"],
                "failed_af2_job_id": row["failed_af2"]["job_id"],
                "partial_state": row["partial_state"],
            }
            for row in reports
        ],
    })
    return {
        "artifact": "m6d_w3b_fit_af2_recovery_approval_packet",
        "version": 1,
        "status": "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval",
        "audit_ok": True,
        "approval_recorded": False,
        "submitted_jobs": 0,
        "no_submit": True,
        "can_claim_w3b": False,
        "observation": _file_binding(observation_path),
        "approval_contract": contract,
        "targets": [
            {
                "target_id": row["target_id"],
                "failed_af2_job_id": row["failed_af2"]["job_id"],
                "partial_state": row["partial_state"],
            }
            for row in reports
        ],
        "bound_artifacts": bound_artifacts,
        "packet_digest_sha256": digest,
        "claim_boundary": (
            "Recovery of the three path-failed AF2 fit jobs only. It cannot rerun ProteinMPNN "
            "or Boltz, change candidates or MSAs, authorize later stages, or support a claim."
        ),
        "next_action": "wait for the exact recovery approval phrase; generic continuation is insufficient",
    }


def verify_recovery_packet(observation_path: str, packet_path: str) -> Dict[str, Any]:
    expected = build_recovery_packet(observation_path)
    actual = load_object(packet_path)
    verified = actual == expected
    return {
        "artifact": "m6d_w3b_fit_af2_recovery_packet_verification",
        "status": "verified_no_submit" if verified else "verification_failed",
        "verified": verified,
        "packet_sha256": sha256_file(packet_path),
        "no_submit": True,
    }


def _target_from_packet(packet: Mapping[str, Any], target_id: str) -> Mapping[str, Any]:
    matches = [
        target for target in packet.get("targets", [])
        if isinstance(target, dict) and target.get("target_id") == target_id
    ]
    if len(matches) != 1:
        raise ValueError(f"target_id={target_id} is not uniquely recovery-authorized")
    return matches[0]


def verify_recovery_target(
    observation_path: str,
    packet_path: str,
    target_id: str,
) -> Dict[str, Any]:
    verification = verify_recovery_packet(observation_path, packet_path)
    if verification["verified"] is not True:
        raise ValueError("W3b AF2 recovery packet verification failed")
    packet = load_object(packet_path)
    target = _target_from_packet(packet, target_id)
    partial = target["partial_state"]
    for key in ("candidates", "af2_input_manifest", "af2_runtime_identity"):
        binding = partial[key]
        if sha256_file(binding["path"]) != binding["sha256"]:
            raise ValueError(f"target_id={target_id} recovery partial hash drift: {key}")

    candidates = load_jsonl(partial["candidates"]["path"])
    manifest = load_object(partial["af2_input_manifest"]["path"])
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    by_candidate = {
        str(row.get("candidate_id") or ""): row
        for row in rows
        if isinstance(row, dict)
    }
    input_dir = Path(str(manifest.get("input_dir") or ""))
    if not (
        len(candidates) == 60
        and len(rows) == len(by_candidate) == 60
        and partial.get("af2_input_count") == 60
        and input_dir.is_dir()
    ):
        raise ValueError(f"target_id={target_id} AF2 recovery input set is invalid")
    aggregate: List[Dict[str, Any]] = []
    expected_paths = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        row = by_candidate.get(candidate_id)
        expected_path = input_dir / f"{candidate_id}.a3m"
        if not (
            isinstance(row, dict)
            and row.get("a3m_path") == str(expected_path)
            and expected_path.is_file()
        ):
            raise ValueError(
                f"target_id={target_id} AF2 recovery input path mismatch for {candidate_id}"
            )
        observed_sha256 = sha256_file(expected_path)
        if row.get("a3m_sha256") != observed_sha256:
            raise ValueError(
                f"target_id={target_id} AF2 recovery input hash drift for {candidate_id}"
            )
        expected_paths.add(expected_path)
        aggregate.append({"candidate_id": candidate_id, "sha256": observed_sha256})
    if set(input_dir.iterdir()) != expected_paths:
        raise ValueError(f"target_id={target_id} AF2 recovery input directory drift")
    if _canonical_sha256(aggregate) != partial.get("af2_input_digest_sha256"):
        raise ValueError(f"target_id={target_id} AF2 recovery input digest drift")

    output_dir = Path(str(partial["af2_output_dir"]))
    if not output_dir.is_dir() or any(output_dir.iterdir()):
        raise ValueError(f"target_id={target_id} AF2 recovery output is no longer empty")
    if Path(str(partial["af2_records"])).exists() or Path(
        str(partial["af2_runtime_receipt"])
    ).exists():
        raise ValueError(f"target_id={target_id} AF2 recovery terminal output already exists")
    return {
        "target_id": target_id,
        "failed_af2_job_id": target["failed_af2_job_id"],
        "approval_token": packet["approval_contract"]["environment_value"],
        "time_limit": packet["approval_contract"]["recovery_time_limit"],
        "partial_state": partial,
        "verified": True,
        "no_submit": True,
    }


def append_recovery_event(
    receipt_path: str,
    packet_path: str,
    target_id: str,
    job_id: str,
) -> None:
    packet = load_object(packet_path)
    _target_from_packet(packet, target_id)
    if not job_id or any(character.isspace() for character in job_id):
        raise ValueError("invalid W3b AF2 recovery job id")
    record = {
        "artifact": "m6d_w3b_fit_af2_recovery_submit_event",
        "version": 1,
        "workstream": _WORKSTREAM,
        "target_id": target_id,
        "job_id": job_id,
        "approval_packet": packet_path,
        "approval_packet_sha256": sha256_file(packet_path),
        "timestamp_unix": int(time.time()),
    }
    Path(receipt_path).parent.mkdir(parents=True, exist_ok=True)
    with open(receipt_path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = [json.loads(line) for line in handle if line.strip()]
        same = [row for row in existing if row.get("target_id") == target_id]
        if same:
            if len(same) == 1 and same[0].get("job_id") == job_id:
                return
            raise ValueError(f"target_id={target_id} already has a recovery job")
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def build_recovery_summary(packet_path: str, receipt_path: str) -> Dict[str, Any]:
    packet = load_object(packet_path)
    expected_targets = {
        str(row["target_id"]): str(row["failed_af2_job_id"])
        for row in packet.get("targets", [])
        if isinstance(row, dict)
    }
    events = []
    with open(receipt_path) as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
    if not (
        packet.get("artifact") == "m6d_w3b_fit_af2_recovery_approval_packet"
        and packet.get("status") == "w3b_fit_af2_recovery_packet_ready_awaiting_explicit_approval"
        and len(expected_targets) == 3
        and len(events) == 3
    ):
        raise ValueError("W3b AF2 recovery summary scope is invalid")
    by_target = {str(row.get("target_id")): row for row in events}
    if set(by_target) != set(expected_targets):
        raise ValueError("W3b AF2 recovery receipt target set is invalid")
    packet_sha256 = sha256_file(packet_path)
    job_ids = []
    targets = []
    for target_id in sorted(expected_targets):
        event = by_target[target_id]
        if not (
            event.get("workstream") == _WORKSTREAM
            and event.get("approval_packet_sha256") == packet_sha256
        ):
            raise ValueError(f"target_id={target_id} recovery receipt binding is invalid")
        job_id = str(event.get("job_id") or "")
        if not job_id or any(character.isspace() for character in job_id):
            raise ValueError(f"target_id={target_id} recovery job id is invalid")
        job_ids.append(job_id)
        targets.append({
            "target_id": target_id,
            "failed_af2_job_id": expected_targets[target_id],
            "recovery_af2_job_id": job_id,
        })
    if len(set(job_ids)) != 3:
        raise ValueError("W3b AF2 recovery job ids are not unique")
    return {
        "artifact": "m6d_w3b_fit_af2_recovery_submit_summary",
        "version": 1,
        "status": "w3b_fit_af2_recovery_jobs_submitted_awaiting_completion",
        "approval_packet": packet_path,
        "approval_packet_sha256": packet_sha256,
        "receipt": receipt_path,
        "receipt_sha256": sha256_file(receipt_path),
        "n_targets": 3,
        "n_af2_h100_recovery_jobs": 3,
        "targets": targets,
        "can_claim_w3b": False,
        "claim_boundary": "Scheduler provenance only; recovery submission is not fit evidence.",
    }


def _emit_targets(packet_path: str) -> None:
    packet = load_object(packet_path)
    for target in packet["targets"]:
        partial = target["partial_state"]
        print("\t".join([
            str(target["target_id"]),
            str(target["failed_af2_job_id"]),
            str(partial["candidates"]["path"]),
            str(partial["af2_input_manifest"]["path"]),
            str(Path(partial["af2_input_manifest"]["path"]).parent / "af2_inputs"),
            str(partial["af2_output_dir"]),
            str(partial["af2_records"]),
            str(partial["af2_runtime_identity"]["path"]),
            str(partial["af2_runtime_receipt"]),
        ]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe = subparsers.add_parser("observe")
    observe.add_argument("--approval-packet", required=True)
    observe.add_argument("--submission-receipt", required=True)
    observe.add_argument("--submission-summary", required=True)
    observe.add_argument("--log-root", default="hpc_outputs/logs")
    observe.add_argument("--out", required=True)
    emit = subparsers.add_parser("emit-packet")
    emit.add_argument("--observation", required=True)
    emit.add_argument("--out", required=True)
    verify = subparsers.add_parser("verify-packet")
    verify.add_argument("--observation", required=True)
    verify.add_argument("--packet", required=True)
    target = subparsers.add_parser("verify-target")
    target.add_argument("--observation", required=True)
    target.add_argument("--packet", required=True)
    target.add_argument("--target-id", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("--packet", required=True)
    append.add_argument("--receipt", required=True)
    append.add_argument("--target-id", required=True)
    append.add_argument("--job-id", required=True)
    summary = subparsers.add_parser("summary")
    summary.add_argument("--packet", required=True)
    summary.add_argument("--receipt", required=True)
    summary.add_argument("--out", required=True)
    targets = subparsers.add_parser("emit-targets")
    targets.add_argument("--packet", required=True)
    args = parser.parse_args(argv)

    if args.command == "observe":
        report = observe_initial_execution(
            args.approval_packet,
            args.submission_receipt,
            args.submission_summary,
            protocol_path=args.protocol,
            execution_manifest_path=args.execution_manifest,
            input_lock_path=args.input_lock,
            runtime_lock_path=args.runtime_lock,
            log_root=args.log_root,
        )
        _write_json(args.out, report)
        print(f"status={report['status']} af2_failed=3 no_submit=True")
        return 0
    if args.command == "emit-packet":
        packet = build_recovery_packet(args.observation)
        _write_json(args.out, packet)
        print(f"status={packet['status']} jobs=3 no_submit=True")
        return 0
    if args.command == "verify-packet":
        report = verify_recovery_packet(args.observation, args.packet)
        print(f"status={report['status']} verified={report['verified']} no_submit=True")
        return 0 if report["verified"] else 2
    if args.command == "verify-target":
        report = verify_recovery_target(args.observation, args.packet, args.target_id)
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.command == "append":
        append_recovery_event(args.receipt, args.packet, args.target_id, args.job_id)
        print(f"target={args.target_id} recovery_job={args.job_id} recorded=True")
        return 0
    if args.command == "summary":
        report = build_recovery_summary(args.packet, args.receipt)
        _write_json(args.out, report)
        print(f"status={report['status']} jobs=3 claim=False")
        return 0
    _emit_targets(args.packet)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
