"""Audit the terminal partial W3d panel without retries or new compute."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from bio_sfm_designer.experiments import m6d_w3d_execution as execution
from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as diagnostic
from bio_sfm_designer.experiments import m6d_w3d_submit_journal as journal
from bio_sfm_designer.experiments.m6d_w3c_b2_completion import (
    _gpu_count,
    parse_sacct,
)
from bio_sfm_designer.experiments.m6d_w3d_approval import (
    verify_packet_integrity,
)
from bio_sfm_designer.experiments.m6d_w3d_input_runtime import (
    _parse_a3m_records,
    sha256_file,
)


PACKET_PATH = "results/m6d_w3d_prediction_approval_packet.json"
RECEIPT_PATH = "results/m6d_w3d_submit_receipt.jsonl"
SUMMARY_PATH = "results/m6d_w3d_submit_receipt_summary.json"
SACCT_PATH = "results/m6d_w3d_sacct.tsv"
NODE_SNAPSHOT_PATH = "results/m6d_w3d_h100_node_snapshot.txt"
ACCOUNTING_PATH = "results/m6d_w3d_terminal_accounting.json"
ACCOUNTING_MD_PATH = "results/m6d_w3d_terminal_accounting.md"
AVAILABLE_RECORDS_PATH = "results/m6d_w3d_available_records.jsonl"
FAILURE_EVIDENCE_PATH = "results/m6d_w3d_query_only_af2_failure_evidence.jsonl"
REPORT_PATH = "results/m6d_w3d_terminal_stop.json"
REPORT_MD_PATH = "results/m6d_w3d_terminal_stop.md"
LOG_DIR = "hpc_outputs/logs"

BOLTZ_ID = "boltz2_complex"
AF2_ID = "af2_multimer_colabfold_v1"
TARGET_MSA = "target_msa_binder_query"
QUERY_ONLY = "query_only_both_chains"
MAXIMUM_JOBS = 24
MAXIMUM_SECONDS_PER_JOB = 3600
MAXIMUM_H100_GPU_SECONDS = MAXIMUM_JOBS * MAXIMUM_SECONDS_PER_JOB
STATUS = "w3d_terminal_partial_result_native_validity_impossibility_stop"


def _load_object(path: str) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, raw_line in enumerate(Path(path).read_text().splitlines(), 1):
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(value)
    return rows


def _binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"required W3d terminal evidence is missing: {path}")
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
            raise ValueError(f"refusing to overwrite divergent W3d artifact: {path}")
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
    _write_text_idempotent(
        path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )


def _packet_cells(packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cells = packet.get("execution_cells")
    if not isinstance(cells, list) or len(cells) != MAXIMUM_JOBS:
        raise ValueError("W3d terminal packet does not contain exactly 24 cells")
    rows = [dict(row) for row in cells if isinstance(row, dict)]
    if len(rows) != MAXIMUM_JOBS or len({row.get("cell_id") for row in rows}) != 24:
        raise ValueError("W3d terminal packet cells are malformed or duplicated")
    return rows


def _failure_cell(cell: Mapping[str, Any]) -> bool:
    return (
        cell.get("representation_id") == QUERY_ONLY
        and cell.get("predictor_id") == AF2_ID
    )


def _validate_node_snapshot(text: str) -> str:
    if not (
        "NodeName=g0004" in text
        and "NodeHostName=g0004" in text
        and "Gres=gpu:h100:4" in text
        and "CfgTRES=cpu=128,mem=1000G,billing=128,gres/gpu=4" in text
    ):
        raise ValueError("W3d terminal node snapshot does not prove the H100 node")
    return "g0004"


def build_accounting(
    packet_path: str = PACKET_PATH,
    receipt_path: str = RECEIPT_PATH,
    summary_path: str = SUMMARY_PATH,
    sacct_path: str = SACCT_PATH,
    node_snapshot_path: str = NODE_SNAPSHOT_PATH,
) -> Dict[str, Any]:
    """Reconcile the exact receipt against terminal Slurm accounting."""

    packet_failures = verify_packet_integrity(packet_path)
    if packet_failures:
        raise ValueError(
            "W3d approval packet integrity failed: " + ",".join(packet_failures)
        )
    packet = _load_object(packet_path)
    cells = _packet_cells(packet)
    receipt_rows = _load_jsonl(receipt_path)
    expected_summary = journal.summarize(packet_path, receipt_path)
    if _load_object(summary_path) != expected_summary:
        raise ValueError("W3d submission summary does not replay from the receipt")
    if not (
        expected_summary.get("audit_ok") is True
        and expected_summary.get("jobs_recorded") == MAXIMUM_JOBS
        and expected_summary.get("retry_jobs") == 0
        and expected_summary.get("adaptive_top_up_jobs") == 0
    ):
        raise ValueError("W3d submission receipt is not the exact one-shot panel")

    by_cell = {str(row["cell_id"]): row for row in cells}
    receipt_by_job: Dict[str, Dict[str, Any]] = {}
    for row in receipt_rows:
        job_id = str(row.get("job_id") or "")
        cell_id = str(row.get("cell_id") or "")
        if cell_id not in by_cell or job_id in receipt_by_job:
            raise ValueError("W3d receipt contains an unknown cell or duplicate job")
        receipt_by_job[job_id] = row
    if len(receipt_by_job) != MAXIMUM_JOBS:
        raise ValueError("W3d receipt does not contain 24 unique jobs")

    sacct_rows = parse_sacct(Path(sacct_path).read_text())
    if set(sacct_rows) != set(receipt_by_job):
        raise ValueError("W3d sacct job IDs differ from the exact receipt")
    h100_node = _validate_node_snapshot(Path(node_snapshot_path).read_text())

    job_states: List[Dict[str, Any]] = []
    terminal_failures: List[Dict[str, Any]] = []
    elapsed_total = 0
    for cell in cells:
        receipt = next(
            row for row in receipt_rows if row.get("cell_id") == cell["cell_id"]
        )
        job_id = str(receipt["job_id"])
        job = sacct_rows[job_id]
        elapsed = job["elapsed_seconds"]
        if not (
            0 < elapsed <= MAXIMUM_SECONDS_PER_JOB
            and _gpu_count(job["req_tres"]) == 1
            and _gpu_count(job["alloc_tres"]) == 1
            and job["node_list"] == h100_node
        ):
            raise ValueError(f"{cell['cell_id']}: Slurm H100 evidence is invalid")
        expected_failure = _failure_cell(cell)
        if expected_failure:
            terminal_ok = job["state"] == "FAILED" and job["exit_code"] == "1:0"
        else:
            terminal_ok = job["state"] == "COMPLETED" and job["exit_code"] == "0:0"
        if not terminal_ok:
            raise ValueError(f"{cell['cell_id']}: terminal state pattern drifted")
        elapsed_total += elapsed
        normalized = {
            "cell_id": cell["cell_id"],
            "target_id": cell["target_id"],
            "representation_id": cell["representation_id"],
            "predictor_id": cell["predictor_id"],
            "job_id": job_id,
            "job_name": job["job_name"],
            "state": job["state"],
            "exit_code": job["exit_code"],
            "elapsed_seconds": elapsed,
            "requested_gpus": 1,
            "allocated_gpus": 1,
            "gpu_type": "h100",
            "node_list": job["node_list"],
            "start": job["start"],
            "end": job["end"],
        }
        job_states.append(normalized)
        if expected_failure:
            terminal_failures.append(normalized)

    if elapsed_total > MAXIMUM_H100_GPU_SECONDS:
        raise ValueError("W3d terminal execution exceeded the approved H100 ceiling")
    failed_job_ids = [row["job_id"] for row in terminal_failures]
    failed_cell_ids = [row["cell_id"] for row in terminal_failures]
    return {
        "artifact": "m6d_w3d_terminal_accounting",
        "version": 1,
        "status": "w3d_terminal_partial_result_no_retry",
        "audit_ok": False,
        "evidence_audit_ok": True,
        "approval_consumed": True,
        "terminal_accounting_complete": True,
        "jobs_expected": MAXIMUM_JOBS,
        "jobs_in_receipt": MAXIMUM_JOBS,
        "jobs_in_sacct": MAXIMUM_JOBS,
        "jobs_terminal": MAXIMUM_JOBS,
        "jobs_terminal_success": 16,
        "jobs_terminal_failure": 8,
        "jobs_pending": 0,
        "job_states": job_states,
        "terminal_failure_job_ids": failed_job_ids,
        "terminal_failure_cell_ids": failed_cell_ids,
        "failure_pattern": "all_eight_query_only_af2_cells_failed",
        "gpu_allocation_seconds_total": elapsed_total,
        "gpu_allocation_hours_total": elapsed_total / 3600.0,
        "approved_h100_gpu_seconds": MAXIMUM_H100_GPU_SECONDS,
        "within_approved_h100_budget": True,
        "retry_or_adaptive_top_up_allowed": False,
        "additional_jobs_authorized": 0,
        "proteinmpnn_designs_authorized": 0,
        "api_calls_authorized": 0,
        "complete_case_adjudication_allowed": False,
        "bindings": {
            "approval_packet": _binding(packet_path),
            "submission_receipt": _binding(receipt_path),
            "submission_summary": _binding(summary_path),
            "sacct_snapshot": _binding(sacct_path),
            "h100_node_snapshot": _binding(node_snapshot_path),
        },
    }


def _validate_relative_binding(
    binding: Mapping[str, Any], *, root: Path, output_dir: Path
) -> Path:
    path_value = binding.get("path")
    if not isinstance(path_value, str):
        raise ValueError("W3d output binding lacks a path")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("W3d output binding is not repository-relative")
    path = (root / relative).resolve()
    resolved_output = output_dir.resolve()
    if resolved_output != path and resolved_output not in path.parents:
        raise ValueError("W3d output binding escapes the packet cell")
    if binding != execution._binding(path, root=root):
        raise ValueError("W3d output binding failed exact file replay")
    return path


def _validate_completed_log(
    *, cell: Mapping[str, Any], job_id: str, log_dir: str
) -> Dict[str, Any]:
    predictor_id = str(cell["predictor_id"])
    stem = "biosfm-w3d-af2" if predictor_id == AF2_ID else "biosfm-w3d-boltz"
    stdout_path = str(Path(log_dir) / f"{stem}-{job_id}.out")
    stderr_path = str(Path(log_dir) / f"{stem}-{job_id}.err")
    stdout = Path(stdout_path).read_text()
    required = [
        "W3d packet verification passed: 24 evaluations, no submit",
        f"cell={cell['cell_id']} input_valid=True prediction_executed=False",
        f"predictor={predictor_id} reobserved=True prediction_executed=False",
        f"cell={cell['cell_id']} runtime_valid=True prediction_executed=False",
        f"cell={cell['cell_id']} predictor={predictor_id}",
        "strict_qc=True",
    ]
    if predictor_id == AF2_ID:
        required.extend(("W3d AF2 GPU preflight devices:", "Running on GPU"))
    else:
        required.append("Number of failed examples: 0")
    if any(token not in stdout for token in required):
        raise ValueError(f"{cell['cell_id']}: completed log signature is incomplete")
    return {
        "stdout": _binding(stdout_path),
        "stderr": _binding(stderr_path),
        "runtime_reobserved": True,
        "strict_qc_completion_logged": True,
    }


def validate_completed_record(
    cell: Mapping[str, Any],
    job_id: str,
    *,
    log_dir: str = LOG_DIR,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Replay one available W3d record from its exact bound outputs."""

    context = execution.load_cell_context(
        str(cell["target_id"]),
        str(cell["representation_id"]),
        str(cell["predictor_id"]),
        require_files=True,
    )
    record_path = str(cell["record_path"])
    record = _load_object(record_path)
    if not (
        record.get("artifact") == "m6d_w3d_native_prediction_record"
        and record.get("version") == 1
        and record.get("status") == "strict_qc_complete"
        and record.get("record_id") == cell["cell_id"]
        and record.get("cell_id") == cell["cell_id"]
        and record.get("target_id") == cell["target_id"]
        and record.get("representation_id") == cell["representation_id"]
        and record.get("predictor_id") == cell["predictor_id"]
        and record.get("runtime_identity_sha256") == cell["runtime_identity_sha256"]
        and record.get("strict_qc_passed") is True
        and isinstance(record.get("success"), bool)
        and record.get("seed") == 0
        and record.get("templates_used") is False
        and record.get("prediction_time_network_used") is False
    ):
        raise ValueError(f"{cell['cell_id']}: strict-QC record identity drifted")
    root = context["project_root"]
    if record.get("input_binding") != execution._binding(
        context["input_path"], root=root
    ):
        raise ValueError(f"{cell['cell_id']}: input binding drifted")
    outputs = record.get("output_bindings")
    auxiliary = record.get("auxiliary_output_bindings")
    if not isinstance(outputs, dict) or set(outputs) != {"model", "confidence"}:
        raise ValueError(f"{cell['cell_id']}: output binding scope drifted")
    model_path = _validate_relative_binding(
        outputs["model"], root=root, output_dir=context["output_dir"]
    )
    confidence_path = _validate_relative_binding(
        outputs["confidence"], root=root, output_dir=context["output_dir"]
    )
    if cell["predictor_id"] == BOLTZ_ID:
        if not isinstance(auxiliary, dict) or set(auxiliary) != {"pae"}:
            raise ValueError(f"{cell['cell_id']}: Boltz pAE binding is missing")
        pae_path = _validate_relative_binding(
            auxiliary["pae"], root=root, output_dir=context["output_dir"]
        )
        with np.load(pae_path) as archive:
            if len(archive.files) != 1:
                raise ValueError(f"{cell['cell_id']}: Boltz pAE archive drifted")
            pae = np.asarray(archive[archive.files[0]], dtype=float)
    else:
        if auxiliary != {}:
            raise ValueError(f"{cell['cell_id']}: AF2 auxiliary bindings drifted")
        scores = _load_object(str(confidence_path))
        pae = np.asarray(scores.get("pae"), dtype=float)
    observed_pae, observed_lrmsd = execution._strict_metrics(context, model_path, pae)
    if not (
        math.isclose(
            float(record.get("interface_pae")),
            round(float(observed_pae), 4),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            float(record.get("lrmsd_angstrom")),
            float(observed_lrmsd),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        and record.get("ligand_rmsd_angstrom") == record.get("lrmsd_angstrom")
        and record.get("lrmsd_threshold_angstrom")
        == diagnostic.LRMSD_THRESHOLD_ANGSTROM
        and record.get("success")
        is (observed_lrmsd < diagnostic.LRMSD_THRESHOLD_ANGSTROM)
    ):
        raise ValueError(f"{cell['cell_id']}: native metrics do not replay")
    evidence = {
        "cell_id": cell["cell_id"],
        "target_id": cell["target_id"],
        "representation_id": cell["representation_id"],
        "predictor_id": cell["predictor_id"],
        "job_id": job_id,
        "record": _binding(record_path),
        "input": record["input_binding"],
        "outputs": record["output_bindings"],
        "auxiliary_outputs": record["auxiliary_output_bindings"],
        "logs": _validate_completed_log(cell=cell, job_id=job_id, log_dir=log_dir),
        "interface_pae": record["interface_pae"],
        "lrmsd_angstrom": record["lrmsd_angstrom"],
        "success": record["success"],
        "strict_qc_replayed": True,
    }
    return record, evidence


def validate_query_only_af2_failure(
    cell: Mapping[str, Any],
    job_id: str,
    *,
    log_dir: str = LOG_DIR,
) -> Dict[str, Any]:
    """Validate the exact query-only AF2 feature-generation failure."""

    if not _failure_cell(cell):
        raise ValueError("W3d failure validator received a non-query-only AF2 cell")
    context = execution.load_cell_context(
        str(cell["target_id"]), QUERY_ONLY, AF2_ID, require_files=True
    )
    if context["record_path"].exists():
        raise ValueError(f"{cell['cell_id']}: failed cell unexpectedly has a record")
    header, records = _parse_a3m_records(context["input_path"].read_text())
    input_cell = context["cell"]
    if not (
        header
        == (
            f"#{input_cell['target_sequence_length']},"
            f"{input_cell['binder_sequence_length']}\t1,1"
        )
        and len(records) == 1
        and records[0][0] == ">101\t102"
    ):
        raise ValueError(f"{cell['cell_id']}: failed query-only A3M drifted")

    output_files = (
        [path for path in context["output_dir"].rglob("*") if path.is_file()]
        if context["output_dir"].exists()
        else []
    )
    model_outputs = [
        path
        for path in output_files
        if path.suffix == ".pdb" or "_scores_rank_" in path.name
    ]
    if model_outputs:
        raise ValueError(f"{cell['cell_id']}: failed cell produced model outputs")

    stdout_path = str(Path(log_dir) / f"biosfm-w3d-af2-{job_id}.out")
    stderr_path = str(Path(log_dir) / f"biosfm-w3d-af2-{job_id}.err")
    stdout = Path(stdout_path).read_text()
    stderr = Path(stderr_path).read_text()
    required_stdout = [
        "W3d packet verification passed: 24 evaluations, no submit",
        f"cell={cell['cell_id']} input_valid=True prediction_executed=False",
        f"predictor={AF2_ID} reobserved=True prediction_executed=False",
        f"cell={cell['cell_id']} runtime_valid=True prediction_executed=False",
        "W3d AF2 GPU preflight devices:",
        "Running on GPU",
        f"Could not generate input features {cell['cell_id']}: "
        "MSA 0 must contain at least one sequence.",
        "ValueError: MSA 0 must contain at least one sequence.",
    ]
    expected_converter_error = (
        f"ValueError: {cell['cell_id']}: expected one W3d AF2 rank-001 "
        "model and score file"
    )
    if (
        any(token not in stdout for token in required_stdout)
        or expected_converter_error not in stderr
        or "recycle=" in stdout
        or "rank_001_" in stdout
    ):
        raise ValueError(f"{cell['cell_id']}: failure signature drifted")
    return {
        "artifact": "m6d_w3d_query_only_af2_failure_evidence",
        "version": 1,
        "cell_id": cell["cell_id"],
        "target_id": cell["target_id"],
        "representation_id": QUERY_ONLY,
        "predictor_id": AF2_ID,
        "job_id": job_id,
        "input": execution._binding(
            context["input_path"], root=context["project_root"]
        ),
        "stdout": _binding(stdout_path),
        "stderr": _binding(stderr_path),
        "paired_query_rows_observed": 1,
        "unpaired_monomer_query_rows_observed": 0,
        "homolog_rows_observed": 0,
        "failure_class": "pre_model_feature_generation_query_only_a3m_encoding",
        "terminal_error": "MSA 0 must contain at least one sequence.",
        "gpu_preflight_passed": True,
        "input_feature_generation_failed": True,
        "model_inference_started": False,
        "model_outputs_observed": 0,
        "strict_qc_record_observed": False,
        "scientific_outcome_observed": False,
    }


def _baseline_rows(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for cell in manifest.get("cells", []):
        if not isinstance(cell, dict):
            continue
        if cell.get("cell_status") != "completed_locked_w3c_b2_baseline":
            continue
        outcome = cell.get("baseline_outcome")
        if not isinstance(outcome, dict) or not isinstance(
            outcome.get("success"), bool
        ):
            raise ValueError("W3d baseline outcome is malformed")
        rows.append(
            {
                "target_id": cell["target_id"],
                "representation_id": cell["representation_id"],
                "predictor_id": cell["predictor_id"],
                "success": outcome["success"],
            }
        )
    if len(rows) != 8 or sum(row["success"] for row in rows) != 2:
        raise ValueError("W3d locked baseline no longer contains 2/8 successes")
    return rows


def adjudicate_partial_matrix(
    manifest: Mapping[str, Any],
    available_records: Sequence[Mapping[str, Any]],
    failure_evidence: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Prove the stage pass impossible while leaving localization unevaluable."""

    baseline = _baseline_rows(manifest)
    available_keys = {
        (
            str(row.get("target_id") or ""),
            str(row.get("representation_id") or ""),
            str(row.get("predictor_id") or ""),
        )
        for row in available_records
    }
    expected_available = {
        (target_id, TARGET_MSA, AF2_ID) for target_id in diagnostic.TARGET_IDS
    } | {(target_id, QUERY_ONLY, BOLTZ_ID) for target_id in diagnostic.TARGET_IDS}
    failed_keys = {
        (
            str(row.get("target_id") or ""),
            str(row.get("representation_id") or ""),
            str(row.get("predictor_id") or ""),
        )
        for row in failure_evidence
    }
    expected_failed = {
        (target_id, QUERY_ONLY, AF2_ID) for target_id in diagnostic.TARGET_IDS
    }
    if available_keys != expected_available or failed_keys != expected_failed:
        raise ValueError("W3d partial evidence scope is incomplete or extended")
    if not all(
        row.get("strict_qc_passed") is True and isinstance(row.get("success"), bool)
        for row in available_records
    ):
        raise ValueError("W3d available records do not all pass strict QC")

    observed = [*baseline, *available_records]
    cell_summaries: List[Dict[str, Any]] = []
    for representation_id in diagnostic.REPRESENTATION_IDS:
        for predictor_id in diagnostic.PREDICTOR_IDS:
            rows = [
                row
                for row in observed
                if row["representation_id"] == representation_id
                and row["predictor_id"] == predictor_id
            ]
            observed_count = len(rows)
            successes = sum(bool(row["success"]) for row in rows)
            missing = 8 - observed_count
            cell_summaries.append(
                {
                    "representation_id": representation_id,
                    "predictor_id": predictor_id,
                    "targets_expected": 8,
                    "targets_observed": observed_count,
                    "successes_observed": successes,
                    "missing_outcomes": missing,
                    "minimum_successes": successes,
                    "maximum_successes": successes + missing,
                    "qualified_observed": (
                        observed_count == 8
                        and successes >= diagnostic.MINIMUM_CELL_SUCCESSES
                    ),
                    "qualification_still_possible": (
                        successes + missing >= diagnostic.MINIMUM_CELL_SUCCESSES
                    ),
                }
            )
    by_cell = {
        (row["representation_id"], row["predictor_id"]): row for row in cell_summaries
    }
    representation_bounds = []
    for representation_id in diagnostic.REPRESENTATION_IDS:
        predictors = [
            by_cell[(representation_id, predictor_id)]
            for predictor_id in diagnostic.PREDICTOR_IDS
        ]
        representation_bounds.append(
            {
                "representation_id": representation_id,
                "both_predictors_can_still_qualify": all(
                    row["qualification_still_possible"] for row in predictors
                ),
                "blocking_predictor_ids": [
                    row["predictor_id"]
                    for row in predictors
                    if not row["qualification_still_possible"]
                ],
            }
        )
    maximum_recovered = sum(
        row["both_predictors_can_still_qualify"] for row in representation_bounds
    )
    if maximum_recovered != 0:
        raise ValueError("W3d partial outcomes do not prove the frozen stop")
    return {
        "cell_summaries": cell_summaries,
        "representation_bounds": representation_bounds,
        "maximum_possible_recovered_representations": maximum_recovered,
        "native_validity_recovery_mathematically_impossible": True,
        "complete_case_localization_evaluable": False,
        "complete_case_adjudication_performed": False,
    }


def adjudicate_terminal_stop(
    packet_path: str = PACKET_PATH,
    receipt_path: str = RECEIPT_PATH,
    summary_path: str = SUMMARY_PATH,
    sacct_path: str = SACCT_PATH,
    node_snapshot_path: str = NODE_SNAPSHOT_PATH,
    *,
    log_dir: str = LOG_DIR,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    accounting = build_accounting(
        packet_path,
        receipt_path,
        summary_path,
        sacct_path,
        node_snapshot_path,
    )
    packet = _load_object(packet_path)
    cells = _packet_cells(packet)
    jobs = {row["cell_id"]: row for row in accounting["job_states"]}
    available_records: List[Dict[str, Any]] = []
    record_evidence: List[Dict[str, Any]] = []
    failure_evidence: List[Dict[str, Any]] = []
    for cell in cells:
        job = jobs[cell["cell_id"]]
        if job["state"] == "COMPLETED":
            record, evidence = validate_completed_record(
                cell, job["job_id"], log_dir=log_dir
            )
            available_records.append(record)
            record_evidence.append(evidence)
        else:
            failure_evidence.append(
                validate_query_only_af2_failure(cell, job["job_id"], log_dir=log_dir)
            )
    if len(available_records) != 16 or len(failure_evidence) != 8:
        raise ValueError("W3d terminal evidence is not the exact 16/8 pattern")

    bindings = packet.get("bound_artifacts")
    if not isinstance(bindings, dict):
        raise ValueError("W3d packet bound artifacts are missing")
    manifest_path = str(bindings["factorial_manifest"]["path"])
    manifest = _load_object(manifest_path)
    partial = adjudicate_partial_matrix(manifest, available_records, failure_evidence)
    success_counts = {
        f"{representation_id}|{predictor_id}": next(
            row["successes_observed"]
            for row in partial["cell_summaries"]
            if row["representation_id"] == representation_id
            and row["predictor_id"] == predictor_id
        )
        for representation_id in diagnostic.REPRESENTATION_IDS
        for predictor_id in diagnostic.PREDICTOR_IDS
    }
    report = {
        "artifact": "m6d_w3d_terminal_stop",
        "version": 1,
        "status": STATUS,
        "audit_ok": True,
        "execution_terminal": True,
        "scientific_stop_complete": True,
        "stage_pass": False,
        "approval_consumed": True,
        "jobs_terminal": 24,
        "jobs_completed": 16,
        "jobs_failed": 8,
        "prospective_records_expected": 24,
        "prospective_records_strict_qc": 16,
        "prospective_records_missing": 8,
        "failed_representation_id": QUERY_ONLY,
        "failed_predictor_id": AF2_ID,
        "failure_class": "pre_model_feature_generation_query_only_a3m_encoding",
        "failure_is_scientific_negative": False,
        "failure_is_input_representation_implementation_defect": True,
        "complete_case_adjudication_required": True,
        "complete_case_adjudication_performed": False,
        "complete_matrix_localization_evaluable": False,
        "available_cell_success_counts": success_counts,
        "partial_matrix": partial,
        "native_validity_recovered": False,
        "native_validity_recovery_mathematically_impossible": True,
        "candidate_generation_scientifically_reachable": False,
        "candidate_generation_authorized": False,
        "proteinmpnn_designs_authorized": 0,
        "additional_predictor_evaluations_authorized": 0,
        "retry_or_adaptive_top_up_allowed": False,
        "target_substitution_allowed": False,
        "can_claim_complete_matrix_localization": False,
        "can_claim_native_recoverability_estimate": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "observed_h100_gpu_seconds": accounting["gpu_allocation_seconds_total"],
        "observed_h100_gpu_hours": accounting["gpu_allocation_hours_total"],
        "record_evidence": record_evidence,
        "source_bindings": {
            "approval_packet": _binding(packet_path),
            "submission_receipt": _binding(receipt_path),
            "submission_summary": _binding(summary_path),
            "sacct_snapshot": _binding(sacct_path),
            "h100_node_snapshot": _binding(node_snapshot_path),
            "factorial_manifest": _binding(manifest_path),
        },
        "claim_boundary": (
            "The frozen native-validity pass is impossible because at least one "
            "fully observed predictor is below 6/8 under each representation. The "
            "missing query-only AF2 cell prevents complete-matrix bottleneck "
            "localization and is an input-encoding failure, not a scientific negative."
        ),
        "next_action": (
            "Close W3d without retry. Any corrected query-only AF2 encoding must be "
            "a separately preregistered successor; generator and gate work remain blocked."
        ),
    }
    return report, accounting, available_records, failure_evidence


def render_accounting_markdown(accounting: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# M6d W3d Terminal Accounting",
            "",
            f"Status: `{accounting['status']}`.",
            f"Terminal jobs: `{accounting['jobs_terminal']}/24`.",
            f"Completed jobs: `{accounting['jobs_terminal_success']}`.",
            f"Failed jobs: `{accounting['jobs_terminal_failure']}`.",
            f"Observed H100 GPU-hours: `{accounting['gpu_allocation_hours_total']:.6f}`.",
            "",
            "All eight failures are query-only AF2 cells. Retry, replacement, and adaptive top-up authority is zero.",
            "",
        ]
    )


def render_report_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# M6d W3d Terminal Stop",
            "",
            f"Status: `{report['status']}`.",
            f"Audit ok: `{report['audit_ok']}`.",
            f"Stage pass: `{report['stage_pass']}`.",
            f"Strict-QC prospective records: `{report['prospective_records_strict_qc']}/24`.",
            f"Observed H100 GPU-hours: `{report['observed_h100_gpu_hours']:.6f}`.",
            "",
            "## Decision",
            "",
            "The frozen native-validity pass is mathematically impossible: target-MSA has 2/8 Boltz and 2/8 AF2 successes, while query-only has 1/8 Boltz successes. Each representation therefore has a fully observed predictor below the required 6/8, regardless of the missing query-only AF2 outcomes.",
            "",
            "The full representation-by-predictor localization is not evaluable. All eight query-only AF2 jobs failed before model inference because the A3M encoding omitted runtime-required unpaired monomer query rows. This is an implementation failure, not a scientific negative.",
            "",
            str(report["claim_boundary"]),
            "",
            f"Next action: {report['next_action']}",
            "",
        ]
    )


def run(
    packet_path: str = PACKET_PATH,
    receipt_path: str = RECEIPT_PATH,
    summary_path: str = SUMMARY_PATH,
    sacct_path: str = SACCT_PATH,
    node_snapshot_path: str = NODE_SNAPSHOT_PATH,
    *,
    log_dir: str = LOG_DIR,
    accounting_path: str = ACCOUNTING_PATH,
    accounting_md_path: str = ACCOUNTING_MD_PATH,
    available_records_path: str = AVAILABLE_RECORDS_PATH,
    failure_evidence_path: str = FAILURE_EVIDENCE_PATH,
    report_path: str = REPORT_PATH,
    report_md_path: str = REPORT_MD_PATH,
) -> Dict[str, Any]:
    report, accounting, available_records, failure_evidence = adjudicate_terminal_stop(
        packet_path,
        receipt_path,
        summary_path,
        sacct_path,
        node_snapshot_path,
        log_dir=log_dir,
    )
    _write_json_idempotent(accounting_path, accounting)
    _write_text_idempotent(accounting_md_path, render_accounting_markdown(accounting))
    _write_jsonl_idempotent(available_records_path, available_records)
    _write_jsonl_idempotent(failure_evidence_path, failure_evidence)
    report["public_evidence_bindings"] = {
        "terminal_accounting": _binding(accounting_path),
        "available_records": _binding(available_records_path),
        "query_only_af2_failures": _binding(failure_evidence_path),
    }
    _write_json_idempotent(report_path, report)
    _write_text_idempotent(report_md_path, render_report_markdown(report))
    return report


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", default=PACKET_PATH)
    parser.add_argument("--receipt", default=RECEIPT_PATH)
    parser.add_argument("--summary", default=SUMMARY_PATH)
    parser.add_argument("--sacct", default=SACCT_PATH)
    parser.add_argument("--node-snapshot", default=NODE_SNAPSHOT_PATH)
    parser.add_argument("--log-dir", default=LOG_DIR)
    parser.add_argument("--accounting", default=ACCOUNTING_PATH)
    parser.add_argument("--accounting-md", default=ACCOUNTING_MD_PATH)
    parser.add_argument("--available-records", default=AVAILABLE_RECORDS_PATH)
    parser.add_argument("--failure-evidence", default=FAILURE_EVIDENCE_PATH)
    parser.add_argument("--report", default=REPORT_PATH)
    parser.add_argument("--report-md", default=REPORT_MD_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run(
        args.packet,
        args.receipt,
        args.summary,
        args.sacct,
        args.node_snapshot,
        log_dir=args.log_dir,
        accounting_path=args.accounting,
        accounting_md_path=args.accounting_md,
        available_records_path=args.available_records,
        failure_evidence_path=args.failure_evidence,
        report_path=args.report,
        report_md_path=args.report_md,
    )
    print(
        f"status={report['status']} jobs=24 records=16 failures=8 "
        f"stage_pass={report['stage_pass']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
