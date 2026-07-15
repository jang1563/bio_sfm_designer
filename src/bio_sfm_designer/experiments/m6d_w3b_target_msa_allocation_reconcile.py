"""Reconcile Cayuga A40 subtype evidence without altering raw Slurm accounting.

Cayuga's ``sacct AllocTRES`` reports ``gres/gpu=1`` but omits the GPU subtype.
This post-submit adapter may add ``a40`` in memory only when independent,
hash-bound Slurm and node evidence proves the exact allocation.  It never
submits work and never suppresses failures outside that telemetry mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .m6d_w3b_target_msa_lifecycle import (
    evaluate_lifecycle,
    parse_sacct,
    render_markdown as render_lifecycle_markdown,
)


_EXPECTED_FAILURE = "job_gpu_allocation_invalid"
_EXPECTED_PARTITION = "scu-gpu"
_EXPECTED_TRES_PER_NODE = "gres/gpu:a40:1"
_EXPECTED_SBATCH_DIRECTIVES = (
    "#SBATCH --partition=scu-gpu",
    "#SBATCH --gres=gpu:a40:1",
    "#SBATCH --time=01:00:00",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _load_object(path: str) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, raw_line in enumerate(Path(path).read_text().splitlines(), 1):
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        rows.append(value)
    return rows


def _key_value_record(line: str) -> Dict[str, str]:
    return {
        key: value
        for key, value in re.findall(r"(?:^| )([A-Za-z][A-Za-z0-9_/]*)=(\S*)", line.strip())
    }


def parse_scontrol_jobs(text: str) -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for line in text.splitlines():
        record = _key_value_record(line)
        job_id = record.get("JobId")
        if not job_id:
            continue
        if job_id in records:
            raise ValueError(f"duplicate scontrol JobId={job_id}")
        records[job_id] = record
    return records


def parse_scontrol_nodes(text: str) -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for line in text.splitlines():
        record = _key_value_record(line)
        node_name = record.get("NodeName")
        if not node_name:
            continue
        if node_name in records:
            raise ValueError(f"duplicate scontrol NodeName={node_name}")
        records[node_name] = record
    return records


def _gpu_count(alloc_tres: str) -> int:
    values = [
        int(value)
        for value in re.findall(r"gres/gpu(?:[:/][^=,]+)?=(\d+)", alloc_tres)
    ]
    return max(values) if values else 0


def normalize_sacct_a40(
    sacct_text: str,
    *,
    proven_job_ids: Sequence[str],
) -> Tuple[str, List[str]]:
    lines = sacct_text.splitlines()
    header_index: Optional[int] = None
    header: List[str] = []
    for index, line in enumerate(lines):
        parts = line.split("|")
        lowered = [part.strip().lower() for part in parts]
        if "state" in lowered and "alloctres" in lowered and (
            "jobidraw" in lowered or "jobid" in lowered
        ):
            header_index = index
            header = lowered
            break
    if header_index is None:
        raise ValueError("raw sacct text lacks a parseable header")
    job_index = header.index("jobidraw") if "jobidraw" in header else header.index("jobid")
    alloc_index = header.index("alloctres")
    proven = set(proven_job_ids)
    normalized: List[str] = []
    for index in range(header_index + 1, len(lines)):
        parts = lines[index].split("|")
        if max(job_index, alloc_index) >= len(parts):
            continue
        raw_job_id = parts[job_index].strip()
        if raw_job_id not in proven:
            continue
        alloc_tres = parts[alloc_index]
        if "gres/gpu:a40=1" in alloc_tres:
            normalized.append(raw_job_id)
            continue
        if "gres/gpu=1" not in alloc_tres:
            raise ValueError(f"job {raw_job_id} lacks the generic one-GPU AllocTRES record")
        parts[alloc_index] = alloc_tres.replace("gres/gpu=1", "gres/gpu:a40=1", 1)
        lines[index] = "|".join(parts)
        normalized.append(raw_job_id)
    if set(normalized) != proven:
        missing = sorted(proven - set(normalized))
        raise ValueError(f"raw sacct lacks primary allocation rows for: {','.join(missing)}")
    return "\n".join(lines) + ("\n" if sacct_text.endswith("\n") else ""), sorted(normalized)


def _failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    row.update(extra)
    failures.append(row)


def reconcile_lifecycle(
    *,
    manifest: Dict[str, Any],
    manifest_path: str,
    packet: Dict[str, Any],
    receipt_rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
    sacct_text: str,
    scontrol_submit_text: str,
    scontrol_nodes_text: str,
    precompute_sbatch_path: str,
    evidence_paths: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    original = evaluate_lifecycle(
        manifest=manifest,
        manifest_path=manifest_path,
        packet=packet,
        receipt_rows=receipt_rows,
        summary=summary,
        sacct_text=sacct_text,
    )
    failures: List[Dict[str, Any]] = []
    submitted = [row for row in receipt_rows if row.get("status") == "submitted"]
    job_ids = [str(row.get("job_id") or "").strip() for row in submitted]
    expected_job_ids = set(job_ids)
    if len(job_ids) != 8 or len(expected_job_ids) != 8 or any(not value for value in job_ids):
        _failure(failures, "allocation_receipt_scope_invalid", "reconciliation requires eight unique submitted jobs")

    raw_failures = original.get("failures") if isinstance(original.get("failures"), list) else []
    raw_failure_jobs = {
        str(row.get("job_id") or "")
        for row in raw_failures
        if isinstance(row, dict) and row.get("kind") == _EXPECTED_FAILURE
    }
    if (
        len(raw_failures) != 8
        or any(row.get("kind") != _EXPECTED_FAILURE for row in raw_failures if isinstance(row, dict))
        or raw_failure_jobs != expected_job_ids
    ):
        _failure(
            failures,
            "allocation_reconciliation_scope_invalid",
            "raw lifecycle failures are not exactly the eight expected GPU-subtype telemetry failures",
        )
    if not all(
        value.get("target_msa_exists") and value.get("target_msa_report_exists")
        for value in original.get("msa_presence", {}).values()
    ):
        _failure(failures, "allocation_reconciliation_inputs_missing", "all eight MSA/report pairs must exist locally")

    binding = packet.get("bound_artifacts", {}).get("precompute_sbatch", {})
    if binding.get("path") != precompute_sbatch_path or binding.get("sha256") != _sha256_file(precompute_sbatch_path):
        _failure(failures, "allocation_sbatch_binding_invalid", "precompute sbatch differs from the approved hash binding")
    sbatch_text = Path(precompute_sbatch_path).read_text()
    missing_directives = [value for value in _EXPECTED_SBATCH_DIRECTIVES if value not in sbatch_text]
    if missing_directives:
        _failure(
            failures,
            "allocation_sbatch_directive_missing",
            "approved sbatch lacks the frozen A40 resource directive",
            missing=missing_directives,
        )

    try:
        scontrol_jobs = parse_scontrol_jobs(scontrol_submit_text)
        scontrol_nodes = parse_scontrol_nodes(scontrol_nodes_text)
    except ValueError as exc:
        _failure(failures, "allocation_scontrol_parse_failed", str(exc))
        scontrol_jobs = {}
        scontrol_nodes = {}
    if set(scontrol_jobs) != expected_job_ids:
        _failure(failures, "allocation_scontrol_job_set_mismatch", "submit-time scontrol evidence does not cover exactly eight receipt jobs")
    for job_id in sorted(expected_job_ids):
        record = scontrol_jobs.get(job_id, {})
        if record.get("Partition") != _EXPECTED_PARTITION:
            _failure(failures, "allocation_partition_invalid", "job was not requested in the frozen GPU partition", job_id=job_id)
        if record.get("TresPerNode") != _EXPECTED_TRES_PER_NODE:
            _failure(failures, "allocation_tres_per_node_invalid", "job lacks exact submit-time A40 request evidence", job_id=job_id)
        if not str(record.get("Command") or "").endswith("/hpc/run_precompute_boltz_target_msa.sbatch"):
            _failure(failures, "allocation_command_invalid", "job command differs from the approved MSA sbatch", job_id=job_id)

    sacct_rows = parse_sacct(sacct_text)
    terminal_nodes: Dict[str, str] = {}
    for job_id in sorted(expected_job_ids):
        row = sacct_rows.get(job_id, {})
        if row.get("state") != "COMPLETED" or row.get("exit_code") != "0:0":
            _failure(failures, "allocation_terminal_state_invalid", "job is not COMPLETED/0:0", job_id=job_id)
        if _gpu_count(str(row.get("alloc_tres") or "")) != 1:
            _failure(failures, "allocation_gpu_count_invalid", "raw sacct does not prove exactly one allocated GPU", job_id=job_id)
        node = str(row.get("node_list") or "")
        if not node or node in {"None", "None assigned", "(null)"} or "," in node or "[" in node:
            _failure(failures, "allocation_node_invalid", "job lacks one concrete terminal node", job_id=job_id)
        else:
            terminal_nodes[job_id] = node
    for job_id, node in sorted(terminal_nodes.items()):
        gres = str(scontrol_nodes.get(node, {}).get("Gres") or "")
        if not re.search(r"(?:^|,)gpu:a40:\d+(?:\(|,|$)", gres):
            _failure(failures, "allocation_node_inventory_invalid", "terminal node is not proven to expose A40 GPUs", job_id=job_id, node=node)

    evidence = {
        "artifact": "m6d_w3b_target_msa_allocation_telemetry_reconciliation",
        "status": "allocation_telemetry_reconciliation_blocked" if failures else "allocation_telemetry_reconciled",
        "audit_ok": not failures,
        "reason": "Cayuga sacct AllocTRES omits the GPU subtype while retaining the one-GPU allocation count.",
        "allowed_correction": "Add a40 only in memory for the eight exact primary sacct rows after independent proof.",
        "raw_lifecycle_status": original.get("status"),
        "raw_lifecycle_failures": raw_failures,
        "job_ids": sorted(expected_job_ids),
        "terminal_nodes": terminal_nodes,
        "raw_sacct_sha256": _sha256_bytes(sacct_text.encode()),
        "scontrol_submit_sha256": _sha256_bytes(scontrol_submit_text.encode()),
        "scontrol_nodes_sha256": _sha256_bytes(scontrol_nodes_text.encode()),
        "precompute_sbatch": precompute_sbatch_path,
        "precompute_sbatch_sha256": _sha256_file(precompute_sbatch_path),
        "evidence_paths": dict(evidence_paths or {}),
        "n_failures": len(failures),
        "failures": failures,
        "no_submit": True,
    }
    if failures:
        blocked = dict(original)
        blocked["status"] = "target_msa_lifecycle_blocked"
        blocked["audit_ok"] = False
        blocked["completion_ok"] = False
        blocked["jobs_terminal_success"] = False
        blocked["allocation_telemetry_reconciliation"] = evidence
        blocked["failures"] = list(raw_failures) + failures
        blocked["n_failures"] = len(blocked["failures"])
        return blocked

    try:
        normalized_sacct, normalized_jobs = normalize_sacct_a40(
            sacct_text,
            proven_job_ids=sorted(expected_job_ids),
        )
    except ValueError as exc:
        _failure(failures, "allocation_sacct_normalization_failed", str(exc))
        evidence["status"] = "allocation_telemetry_reconciliation_blocked"
        evidence["audit_ok"] = False
        evidence["n_failures"] = len(failures)
        evidence["failures"] = failures
        blocked = dict(original)
        blocked["allocation_telemetry_reconciliation"] = evidence
        blocked["failures"] = list(raw_failures) + failures
        blocked["n_failures"] = len(blocked["failures"])
        return blocked

    corrected = evaluate_lifecycle(
        manifest=manifest,
        manifest_path=manifest_path,
        packet=packet,
        receipt_rows=receipt_rows,
        summary=summary,
        sacct_text=normalized_sacct,
    )
    evidence["normalized_job_ids"] = normalized_jobs
    evidence["normalized_sacct_sha256"] = _sha256_bytes(normalized_sacct.encode())
    corrected["allocation_telemetry_reconciliation"] = evidence
    corrected["telemetry_reconciliation_applied"] = True
    corrected["claim_boundary"] = (
        str(corrected["claim_boundary"])
        + " The reconciliation changes no raw accounting, scientific input, threshold, role, or compute scope."
    )
    return corrected


def render_markdown(report: Mapping[str, Any]) -> str:
    base = render_lifecycle_markdown(dict(report)).rstrip()
    evidence = report.get("allocation_telemetry_reconciliation", {})
    return "\n".join([
        base,
        "",
        "## Allocation Telemetry Reconciliation",
        "",
        f"- status: `{evidence.get('status')}`",
        f"- audit ok: `{evidence.get('audit_ok')}`",
        f"- raw sacct SHA-256: `{evidence.get('raw_sacct_sha256')}`",
        f"- submit-time scontrol SHA-256: `{evidence.get('scontrol_submit_sha256')}`",
        f"- node inventory SHA-256: `{evidence.get('scontrol_nodes_sha256')}`",
        f"- normalized primary jobs: `{len(evidence.get('normalized_job_ids', []))}`",
        "",
        "Raw Slurm accounting remains unchanged; only the omitted A40 subtype is restored in memory after independent proof.",
        "",
    ])


def _write(path: str, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, destination)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--approval-packet", default="results/m6d_w3b_target_msa_approval_packet.json")
    parser.add_argument("--receipt", default="results/m6d_w3b_target_msa_receipt.jsonl")
    parser.add_argument("--summary", default="results/m6d_w3b_target_msa_receipt_summary.json")
    parser.add_argument("--sacct", default="results/m6d_w3b_target_msa_sacct.tsv")
    parser.add_argument("--scontrol-submit", default="results/m6d_w3b_target_msa_scontrol_submit.txt")
    parser.add_argument("--scontrol-nodes", default="results/m6d_w3b_target_msa_scontrol_nodes.txt")
    parser.add_argument("--precompute-sbatch", default="hpc/run_precompute_boltz_target_msa.sbatch")
    parser.add_argument("--out-json", default="results/m6d_w3b_target_msa_lifecycle.json")
    parser.add_argument("--out-md", default="results/m6d_w3b_target_msa_lifecycle.md")
    args = parser.parse_args(argv)
    report = reconcile_lifecycle(
        manifest=_load_object(args.manifest),
        manifest_path=args.manifest,
        packet=_load_object(args.approval_packet),
        receipt_rows=_load_jsonl(args.receipt),
        summary=_load_object(args.summary),
        sacct_text=Path(args.sacct).read_text(),
        scontrol_submit_text=Path(args.scontrol_submit).read_text(),
        scontrol_nodes_text=Path(args.scontrol_nodes).read_text(),
        precompute_sbatch_path=args.precompute_sbatch,
        evidence_paths={
            "raw_sacct": args.sacct,
            "scontrol_submit": args.scontrol_submit,
            "scontrol_nodes": args.scontrol_nodes,
        },
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"completion_ok={report['completion_ok']} failures={report['n_failures']} no_submit=True"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
