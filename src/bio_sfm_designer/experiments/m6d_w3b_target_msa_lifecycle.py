"""Audit and replay the approval-gated W3b target-MSA lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .complex_target_manifest import validate_manifest


_WORKSTREAM = "m6d_w3b_target_msa_input_prep_only"
_RECEIPT = "results/m6d_w3b_target_msa_receipt.jsonl"
_SUMMARY = "results/m6d_w3b_target_msa_receipt_summary.json"
_SACCT = "results/m6d_w3b_target_msa_sacct.tsv"
_OUT_JSON = "results/m6d_w3b_target_msa_lifecycle.json"
_OUT_MD = "results/m6d_w3b_target_msa_lifecycle.md"
_QUERY = "results/m6d_w3b_target_msa_job_state_query.sh"
_SYNC = "results/m6d_w3b_target_msa_sync_back.sh"
_MAX_GPU_HOURS = 8.0
_PENDING_STATES = {"CONFIGURING", "COMPLETING", "PENDING", "RUNNING", "RESIZING", "SUSPENDED"}
_FAILED_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


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


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_json_optional(path: str) -> Optional[Dict[str, Any]]:
    return _load_json(path) if os.path.isfile(path) else None


def _load_jsonl_optional(path: str) -> Optional[List[Dict[str, Any]]]:
    if not os.path.isfile(path):
        return None
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


def _failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    row.update({key: value for key, value in extra.items() if value is not None})
    failures.append(row)


def _base_job_id(value: Any) -> str:
    return str(value or "").strip().split(".", 1)[0].split("_", 1)[0]


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().upper().rstrip("+").split(" ", 1)[0]


def parse_sacct(text: str) -> Dict[str, Dict[str, Any]]:
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
            "node_list": values.get("nodelist") or "",
        }
        current = rows.get(base_job_id)
        if current is None or raw_job_id == base_job_id:
            rows[base_job_id] = row
    return rows


def _gpu_count(alloc_tres: str) -> int:
    values = [int(value) for value in re.findall(r"gres/gpu(?:[:/][^=,]+)?=(\d+)", alloc_tres)]
    return max(values) if values else 0


def _validate_packet(
    packet: Dict[str, Any],
    *,
    manifest_path: str,
    manifest_sha256: str,
    target_ids: List[str],
    failures: List[Dict[str, Any]],
) -> None:
    if packet.get("approval_packet_ready") is not True or packet.get("no_submit") is not True:
        _failure(failures, "approval_packet_not_ready", "W3b target-MSA approval packet is not ready/no-submit")
    if packet.get("can_submit_candidate_generation_or_candidate_level_prediction") is not False:
        _failure(failures, "approval_scope_expanded", "approval packet permits candidate-level work")
    if packet.get("target_ids") != target_ids or packet.get("target_count") != len(target_ids):
        _failure(failures, "approval_target_set_mismatch", "approval packet target set differs from the manifest")
    if float(packet.get("maximum_a40_gpu_hours") or 0.0) != _MAX_GPU_HOURS:
        _failure(failures, "approval_budget_mismatch", "approval packet must remain capped at 8 A40 GPU-hours")
    binding = packet.get("bound_artifacts", {}).get("manifest", {})
    if binding.get("path") != manifest_path or binding.get("sha256") != manifest_sha256:
        _failure(failures, "approval_manifest_binding_mismatch", "approval packet does not bind the current manifest")


def _validate_receipt(
    receipt_rows: List[Dict[str, Any]],
    *,
    targets: List[Dict[str, Any]],
    manifest_path: str,
    manifest_sha256: str,
    failures: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    targets_by_id = {str(target["id"]): target for target in targets}
    rows_by_id: Dict[str, List[Dict[str, Any]]] = {target_id: [] for target_id in targets_by_id}
    status_counts: Dict[str, int] = {}
    for row in receipt_rows:
        target_id = str(row.get("target_id") or "")
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        if target_id not in rows_by_id:
            _failure(failures, "receipt_unexpected_target", "receipt contains an unexpected target", target_id=target_id)
            continue
        rows_by_id[target_id].append(row)
    submitted: List[Dict[str, Any]] = []
    for target_id, target in targets_by_id.items():
        rows = rows_by_id[target_id]
        if len(rows) != 1:
            _failure(
                failures,
                "receipt_target_row_count_invalid",
                "receipt must contain exactly one row per target",
                target_id=target_id,
                observed=len(rows),
            )
            continue
        row = rows[0]
        status = str(row.get("status") or "")
        if status not in {"submitted", "validated_existing"}:
            _failure(failures, "receipt_status_invalid", "receipt status is not accepted", target_id=target_id, observed=status)
        if row.get("manifest") != manifest_path or row.get("manifest_sha256") != manifest_sha256:
            _failure(failures, "receipt_manifest_mismatch", "receipt manifest provenance differs", target_id=target_id)
        if row.get("workstream") != _WORKSTREAM:
            _failure(failures, "receipt_workstream_mismatch", "receipt workstream differs", target_id=target_id)
        for field in ("target_fasta", "target_msa", "target_msa_report"):
            if row.get(field) != target.get(field):
                _failure(
                    failures,
                    "receipt_path_mismatch",
                    "receipt path differs from manifest",
                    target_id=target_id,
                    field=field,
                )
        if status == "submitted":
            job_id = str(row.get("job_id") or "").strip()
            if not job_id or any(char.isspace() for char in job_id):
                _failure(failures, "receipt_job_id_invalid", "submitted receipt row lacks a parsable job id", target_id=target_id)
            else:
                submitted.append({"target_id": target_id, "job_id": _base_job_id(job_id)})
    if len(receipt_rows) != len(targets):
        _failure(
            failures,
            "receipt_row_count_invalid",
            "receipt row count differs from the eight-target scope",
            expected=len(targets),
            observed=len(receipt_rows),
        )
    return submitted, status_counts


def _validate_summary(
    summary: Dict[str, Any],
    *,
    packet: Dict[str, Any],
    target_ids: List[str],
    status_counts: Dict[str, int],
    manifest_path: str,
    manifest_sha256: str,
    failures: List[Dict[str, Any]],
) -> None:
    if summary.get("artifact") != "m6d_w3b_target_msa_receipt_summary":
        _failure(failures, "receipt_summary_artifact_invalid", "receipt summary artifact identity differs")
    if summary.get("manifest") != manifest_path or summary.get("manifest_sha256") != manifest_sha256:
        _failure(failures, "receipt_summary_manifest_mismatch", "receipt summary manifest provenance differs")
    if summary.get("workstream") != _WORKSTREAM:
        _failure(failures, "receipt_summary_workstream_mismatch", "receipt summary workstream differs")
    if summary.get("n_records") != len(target_ids) or summary.get("n_targets") != len(target_ids):
        _failure(failures, "receipt_summary_count_mismatch", "receipt summary does not cover all eight targets")
    if sorted(str(value) for value in summary.get("target_ids", [])) != sorted(target_ids):
        _failure(failures, "receipt_summary_target_mismatch", "receipt summary target set differs")
    if summary.get("status_counts") != status_counts:
        _failure(failures, "receipt_summary_status_mismatch", "receipt summary status counts differ from receipt")
    for name in ("protocol", "selection", "design_gate", "plan"):
        binding = packet.get("bound_artifacts", {}).get(name, {})
        if summary.get(name) != binding.get("path") or summary.get(f"{name}_sha256") != binding.get("sha256"):
            _failure(failures, "receipt_summary_binding_mismatch", f"receipt summary {name} binding differs")


def _target_artifacts(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for target in targets:
        fasta = str(target["target_fasta"])
        msa = str(target["target_msa"])
        report_path = str(target["target_msa_report"])
        sequence = _read_sequence(fasta)
        report = _load_json(report_path)
        artifacts.append({
            "target_id": str(target["id"]),
            "sequence_length": len(sequence),
            "target_sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            "expected_target_sequence_sha256": str(target.get("target_sequence_sha256") or ""),
            "target_fasta": fasta,
            "target_fasta_sha256": _sha256_file(fasta),
            "target_msa": msa,
            "target_msa_bytes": os.path.getsize(msa),
            "target_msa_sha256": _sha256_file(msa),
            "target_msa_report": report_path,
            "target_msa_report_sha256": _sha256_file(report_path),
            "target_msa_report_ok": report.get("ok") is True,
        })
    return artifacts


def evaluate_lifecycle(
    *,
    manifest: Dict[str, Any],
    manifest_path: str,
    packet: Dict[str, Any],
    receipt_rows: Optional[List[Dict[str, Any]]],
    summary: Optional[Dict[str, Any]],
    sacct_text: Optional[str],
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    requirements: List[str] = []
    targets = [target for target in manifest.get("targets", []) if isinstance(target, dict)]
    target_ids = [str(target.get("id") or "") for target in targets]
    manifest_sha256 = _sha256_file(manifest_path)
    if len(targets) != 8 or len(set(target_ids)) != 8 or any(not target_id for target_id in target_ids):
        _failure(failures, "manifest_target_scope_invalid", "W3b lifecycle requires exactly eight unique targets")
    _validate_packet(
        packet,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        target_ids=target_ids,
        failures=failures,
    )

    msa_presence = {
        str(target["id"]): {
            "target_msa_exists": os.path.isfile(str(target.get("target_msa") or "")),
            "target_msa_report_exists": os.path.isfile(str(target.get("target_msa_report") or "")),
        }
        for target in targets
    }
    receipt_present = receipt_rows is not None
    summary_present = summary is not None
    submitted_jobs: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {}
    job_rows: List[Dict[str, Any]] = []
    gpu_allocation_seconds = 0
    jobs_terminal_success = False
    strict_manifest: Optional[Dict[str, Any]] = None
    target_artifacts: List[Dict[str, Any]] = []

    if not receipt_present and not summary_present:
        if any(
            state["target_msa_exists"] or state["target_msa_report_exists"]
            for state in msa_presence.values()
        ):
            _failure(failures, "orphan_msa_without_receipt", "MSA artifacts exist before an approved receipt was created")
        requirements.append("exact W3b target-MSA approval and guarded submission")
        status = "target_msa_not_submitted_awaiting_explicit_approval"
    elif receipt_present != summary_present:
        _failure(failures, "receipt_summary_partial", "receipt and summary must either both exist or both be absent")
        status = "target_msa_lifecycle_blocked"
    else:
        assert receipt_rows is not None and summary is not None
        submitted_jobs, status_counts = _validate_receipt(
            receipt_rows,
            targets=targets,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            failures=failures,
        )
        _validate_summary(
            summary,
            packet=packet,
            target_ids=target_ids,
            status_counts=status_counts,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            failures=failures,
        )
        if failures:
            status = "target_msa_lifecycle_blocked"
        elif submitted_jobs and sacct_text is None:
            requirements.append("read-only sacct query for submitted target-MSA jobs")
            status = "target_msa_submitted_awaiting_job_state_query"
        else:
            sacct_rows = parse_sacct(sacct_text or "")
            pending_jobs: List[str] = []
            terminal_failures: List[str] = []
            for submitted in submitted_jobs:
                job_id = submitted["job_id"]
                state = sacct_rows.get(job_id)
                if state is None:
                    pending_jobs.append(job_id)
                    job_rows.append({**submitted, "state": "MISSING_FROM_SACCT"})
                    continue
                row = {**submitted, **state}
                row["gpu_type"] = "a40" if "a40" in str(row.get("alloc_tres", "")).lower() else "unknown"
                row["gpus"] = _gpu_count(str(row.get("alloc_tres", "")))
                job_rows.append(row)
                if row["state"] in _PENDING_STATES:
                    pending_jobs.append(job_id)
                elif row["state"] == "COMPLETED" and row.get("exit_code") == "0:0":
                    if row["gpu_type"] != "a40" or row["gpus"] != 1:
                        _failure(
                            failures,
                            "job_gpu_allocation_invalid",
                            "completed target-MSA job was not proven to use exactly one A40",
                            job_id=job_id,
                        )
                    gpu_allocation_seconds += int(row.get("elapsed_seconds") or 0) * int(row.get("gpus") or 0)
                else:
                    terminal_failures.append(job_id)
                    _failure(
                        failures,
                        "job_terminal_failure",
                        "target-MSA job ended outside COMPLETED/0:0",
                        job_id=job_id,
                        state=row.get("state"),
                        exit_code=row.get("exit_code"),
                    )
            gpu_hours = gpu_allocation_seconds / 3600.0
            if gpu_hours > _MAX_GPU_HOURS:
                _failure(failures, "gpu_budget_exceeded", "target-MSA allocation exceeded 8 A40 GPU-hours")
            if failures or terminal_failures:
                status = "target_msa_lifecycle_blocked"
            elif pending_jobs:
                requirements.append("all submitted target-MSA jobs reach COMPLETED/0:0")
                status = "target_msa_jobs_pending"
            else:
                jobs_terminal_success = True
                strict_manifest = validate_manifest(
                    manifest_path,
                    require_files=True,
                    min_targets=8,
                    target_ids=target_ids,
                )
                if not strict_manifest["ok"]:
                    allowed_sync_fields = {"target_msa", "target_msa_report"}
                    strict_failures = strict_manifest.get("failures", [])
                    only_sync_missing = bool(strict_failures) and all(
                        failure.get("kind") == "missing_file"
                        and failure.get("field") in allowed_sync_fields
                        for failure in strict_failures
                    )
                    if only_sync_missing:
                        requirements.append("sync the eight target-MSA/report pairs from Cayuga")
                        status = "target_msa_jobs_complete_local_sync_required"
                    else:
                        _failure(
                            failures,
                            "strict_manifest_validation_failed",
                            "post-MSA strict manifest validation found non-sync blockers",
                            failures_by_kind=strict_manifest.get("failures_by_kind"),
                        )
                        status = "target_msa_lifecycle_blocked"
                else:
                    target_artifacts = _target_artifacts(targets)
                    for artifact in target_artifacts:
                        if artifact["target_sequence_sha256"] != artifact["expected_target_sequence_sha256"]:
                            _failure(
                                failures,
                                "frozen_target_sequence_hash_mismatch",
                                "synced target FASTA differs from the frozen target sequence",
                                target_id=artifact["target_id"],
                            )
                    status = (
                        "target_msa_precompute_complete_8_of_8"
                        if not failures else
                        "target_msa_lifecycle_blocked"
                    )

    completion_ok = status == "target_msa_precompute_complete_8_of_8" and not failures
    audit_ok = not failures
    gpu_hours = gpu_allocation_seconds / 3600.0
    return {
        "artifact": "m6d_w3b_target_msa_lifecycle",
        "status": status,
        "audit_ok": audit_ok,
        "completion_ok": completion_ok,
        "no_submit": True,
        "submitted": receipt_present,
        "explicit_approval_still_required": not receipt_present,
        "can_run_post_msa_design_gate": completion_ok,
        "can_submit_candidate_generation_or_candidate_level_prediction": False,
        "can_claim_w3b": False,
        "manifest": manifest_path,
        "manifest_sha256": manifest_sha256,
        "target_ids": target_ids,
        "n_targets": len(target_ids),
        "msa_presence": msa_presence,
        "receipt_present": receipt_present,
        "summary_present": summary_present,
        "receipt_status_counts": status_counts,
        "submitted_jobs": submitted_jobs,
        "job_states": job_rows,
        "jobs_terminal_success": jobs_terminal_success,
        "gpu_allocation_seconds": gpu_allocation_seconds,
        "gpu_allocation_hours": gpu_hours,
        "maximum_a40_gpu_hours": _MAX_GPU_HOURS,
        "within_gpu_budget": gpu_hours <= _MAX_GPU_HOURS,
        "strict_manifest": strict_manifest,
        "target_artifacts": target_artifacts,
        "requirements": requirements,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Target-MSA lifecycle provenance only. This tool never submits work and cannot authorize "
            "candidate generation, candidate-level prediction, a gate certificate, or a W3b claim."
        ),
        "next_action": (
            "rerun the design audit into post-MSA outputs, then stop for a separate candidate-generation approval packet"
            if completion_ok else
            requirements[0]
            if requirements else
            "repair lifecycle blockers before any downstream W3b stage"
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3b Target-MSA Lifecycle",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Completion ok: `{report['completion_ok']}`.",
        f"No submit: `{report['no_submit']}`.",
        f"Explicit approval still required: `{report['explicit_approval_still_required']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- targets: `{report['n_targets']}`",
        f"- submitted jobs: `{len(report['submitted_jobs'])}`",
        f"- jobs terminal success: `{report['jobs_terminal_success']}`",
        f"- A40 GPU-hours: `{report['gpu_allocation_hours']:.6f}` / `{report['maximum_a40_gpu_hours']}`",
        f"- failures: `{report['n_failures']}`",
        "",
        f"Next action: {report['next_action']}.",
        "",
    ]
    if report["requirements"]:
        lines.extend(["## Remaining Requirements", ""])
        lines.extend(f"- {value}" for value in report["requirements"])
        lines.append("")
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- `{failure['kind']}`: {failure['message']}" for failure in report["failures"])
        lines.append("")
    return "\n".join(lines)


def render_query_script(
    *,
    manifest_path: str,
    packet_path: str,
    receipt_path: str,
    summary_path: str,
    sacct_path: str,
    out_json: str,
    out_md: str,
) -> str:
    module = "bio_sfm_designer.experiments.m6d_w3b_target_msa_lifecycle"
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Read-only W3b target-MSA Slurm query. This script never calls sbatch.",
        "set -euo pipefail",
        'REPO_ROOT="${BIO_SFM_REPO_ROOT:-$PWD}"',
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        'BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$REPO_ROOT/../bio-sfm-trust-core/src}"',
        'if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then',
        '  export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"',
        "else",
        '  export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
        "fi",
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        f"RECEIPT={shlex.quote(receipt_path)}",
        f"SUMMARY={shlex.quote(summary_path)}",
        f"SACCT={shlex.quote(sacct_path)}",
        'test -s "$RECEIPT" || { echo "W3b target-MSA receipt is absent; no approved submission to query" >&2; exit 2; }',
        'test -s "$SUMMARY" || { echo "W3b target-MSA receipt summary is absent" >&2; exit 2; }',
        'job_ids="$("$PYTHON_BIN" - "$RECEIPT" <<\'PY\'',
        "import json",
        "import sys",
        "ids = []",
        "with open(sys.argv[1]) as handle:",
        "    for line in handle:",
        "        if not line.strip():",
        "            continue",
        "        row = json.loads(line)",
        "        if row.get('status') == 'submitted':",
        "            ids.append(str(row.get('job_id') or '').strip())",
        "if any(not value or any(ch.isspace() for ch in value) for value in ids):",
        "    raise SystemExit('receipt contains a non-parsable submitted job id')",
        "print(','.join(ids))",
        "PY",
        ')"',
        'mkdir -p "$(dirname "$SACCT")"',
        'if [ -n "$job_ids" ]; then',
        '  sacct -P -j "$job_ids" --format=JobIDRaw,State,ExitCode,ElapsedRaw,AllocTRES,NodeList > "$SACCT"',
        "else",
        "  printf 'JobIDRaw|State|ExitCode|ElapsedRaw|AllocTRES|NodeList|\\n' > \"$SACCT\"",
        "fi",
        'test -s "$SACCT"',
        (
            f'"$PYTHON_BIN" -m {module} '
            f"--manifest {shlex.quote(manifest_path)} --approval-packet {shlex.quote(packet_path)} "
            '--receipt "$RECEIPT" --summary "$SUMMARY" --sacct "$SACCT" '
            f"--out-json {shlex.quote(out_json)} --out-md {shlex.quote(out_md)} "
            '--emit-query "" --emit-sync ""'
        ),
        "",
    ])


def render_sync_script(
    *,
    manifest_path: str,
    packet_path: str,
    receipt_path: str,
    summary_path: str,
    sacct_path: str,
    query_path: str,
    out_json: str,
    out_md: str,
) -> str:
    module = "bio_sfm_designer.experiments.m6d_w3b_target_msa_lifecycle"
    design_module = "bio_sfm_designer.experiments.m6d_w3b_disagreement_design_gate"
    execution_lock_module = "bio_sfm_designer.experiments.m6d_w3b_execution_lock"
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Pull only W3b target input-prep artifacts and replay strict CPU validation.",
        "# This script never submits jobs and never pulls candidate-level predictor output.",
        "set -euo pipefail",
        'REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"',
        'REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:-bio_sfm_smoke}"',
        'LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"',
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        f"MANIFEST={shlex.quote(manifest_path)}",
        f"PACKET={shlex.quote(packet_path)}",
        f"RECEIPT={shlex.quote(receipt_path)}",
        f"SUMMARY={shlex.quote(summary_path)}",
        f"SACCT={shlex.quote(sacct_path)}",
        f"QUERY={shlex.quote(query_path)}",
        f"OUT_JSON={shlex.quote(out_json)}",
        f"OUT_MD={shlex.quote(out_md)}",
        'cd "$LOCAL_ROOT"',
        'BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$LOCAL_ROOT/../bio-sfm-trust-core/src}"',
        'if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then',
        '  export PYTHONPATH="$LOCAL_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"',
        "else",
        '  export PYTHONPATH="$LOCAL_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
        "fi",
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        "printf -v remote_command 'cd %q && BIO_SFM_PYTHON=$HOME/.conda/envs/boltz/bin/python PYTHONNOUSERSITE=1 bash %q' \"$REMOTE_ROOT\" \"$QUERY\"",
        'ssh "$REMOTE_HOST" "$remote_command"',
        'for relpath in "$RECEIPT" "$SUMMARY" "$SACCT" "$OUT_JSON"; do',
        '  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"',
        '  rsync -avP "$REMOTE_HOST:$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"',
        '  test -s "$LOCAL_ROOT/$relpath"',
        "done",
        'jobs_ready="$("$PYTHON_BIN" - "$OUT_JSON" <<\'PY\'',
        "import json",
        "import sys",
        "with open(sys.argv[1]) as handle:",
        "    report = json.load(handle)",
        "print('1' if report.get('jobs_terminal_success') else '0')",
        "PY",
        ')"',
        'test "$jobs_ready" = 1 || { echo "W3b target-MSA jobs are not all terminal-success; do not sync inputs yet" >&2; exit 2; }',
        'artifact_paths="$("$PYTHON_BIN" - "$MANIFEST" <<\'PY\'',
        "import json",
        "import sys",
        "with open(sys.argv[1]) as handle:",
        "    manifest = json.load(handle)",
        "fields = ('source_pdb', 'prepared_pdb', 'prep_report', 'target_fasta', 'target_fasta_report', 'target_msa', 'target_msa_report')",
        "seen = set()",
        "for target in manifest.get('targets', []):",
        "    for field in fields:",
        "        value = target.get(field)",
        "        if isinstance(value, str) and value and value not in seen:",
        "            seen.add(value)",
        "            print(value)",
        "PY",
        ')"',
        'while IFS= read -r relpath; do',
        '  [ -n "$relpath" ] || continue',
        '  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"',
        '  rsync -avP "$REMOTE_HOST:$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"',
        '  test -s "$LOCAL_ROOT/$relpath"',
        'done <<< "$artifact_paths"',
        (
            f'"$PYTHON_BIN" -m {module} --manifest "$MANIFEST" --approval-packet "$PACKET" '
            '--receipt "$RECEIPT" --summary "$SUMMARY" --sacct "$SACCT" '
            '--out-json "$OUT_JSON" --out-md "$OUT_MD" --emit-query "" --emit-sync ""'
        ),
        'completion_ok="$("$PYTHON_BIN" - "$OUT_JSON" <<\'PY\'',
        "import json",
        "import sys",
        "with open(sys.argv[1]) as handle:",
        "    report = json.load(handle)",
        "print('1' if report.get('completion_ok') else '0')",
        "PY",
        ')"',
        'test "$completion_ok" = 1 || { echo "W3b target-MSA completion validation failed" >&2; exit 2; }',
        (
            f'"$PYTHON_BIN" -m {design_module} '
            '--out-json results/m6d_w3b_disagreement_design_gate_post_msa.json '
            '--out-md results/m6d_w3b_disagreement_design_gate_post_msa.md'
        ),
        (
            f'"$PYTHON_BIN" -m {execution_lock_module} '
            '--protocol configs/m6d_w3b_disagreement_gate_protocol.json '
            '--source-manifest "$MANIFEST" --lifecycle "$OUT_JSON" --emit-execution-lock'
        ),
        "echo 'W3b target-MSA inputs and execution lock validated; stop before candidate generation or candidate-level prediction.'",
        "",
    ])


def _write(path: str, text: str, *, executable: bool = False) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--approval-packet", default="results/m6d_w3b_target_msa_approval_packet.json")
    parser.add_argument("--receipt", default=_RECEIPT)
    parser.add_argument("--summary", default=_SUMMARY)
    parser.add_argument("--sacct", default=_SACCT)
    parser.add_argument("--out-json", default=_OUT_JSON)
    parser.add_argument("--out-md", default=_OUT_MD)
    parser.add_argument("--emit-query", default=_QUERY)
    parser.add_argument("--emit-sync", default=_SYNC)
    args = parser.parse_args(argv)
    manifest = _load_json(args.manifest)
    packet = _load_json(args.approval_packet)
    receipt_rows = _load_jsonl_optional(args.receipt)
    summary = _load_json_optional(args.summary)
    sacct_text = open(args.sacct).read() if os.path.isfile(args.sacct) else None
    report = evaluate_lifecycle(
        manifest=manifest,
        manifest_path=args.manifest,
        packet=packet,
        receipt_rows=receipt_rows,
        summary=summary,
        sacct_text=sacct_text,
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    _write(
        args.emit_query,
        render_query_script(
            manifest_path=args.manifest,
            packet_path=args.approval_packet,
            receipt_path=args.receipt,
            summary_path=args.summary,
            sacct_path=args.sacct,
            out_json=args.out_json,
            out_md=args.out_md,
        ),
        executable=True,
    )
    _write(
        args.emit_sync,
        render_sync_script(
            manifest_path=args.manifest,
            packet_path=args.approval_packet,
            receipt_path=args.receipt,
            summary_path=args.summary,
            sacct_path=args.sacct,
            query_path=args.emit_query or _QUERY,
            out_json=args.out_json,
            out_md=args.out_md,
        ),
        executable=True,
    )
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} completion_ok={report['completion_ok']} "
        f"submitted={report['submitted']} failures={report['n_failures']} no_submit={report['no_submit']}"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
