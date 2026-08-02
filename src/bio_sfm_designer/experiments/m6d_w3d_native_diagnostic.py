"""Freeze the W3d native representation-by-predictor diagnostic, without compute."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROTOCOL_PATH = "configs/m6d_w3d_native_diagnostic_protocol.json"
MANIFEST_PATH = "configs/m6d_w3d_native_diagnostic_manifest.json"
READINESS_PATH = "results/m6d_w3d_native_diagnostic_readiness.json"
READINESS_MD_PATH = "results/m6d_w3d_native_diagnostic_readiness.md"
INPUT_MANIFEST_PATH = "configs/m6d_w3d_prospective_input_manifest.json"
INPUT_RUNTIME_READINESS_PATH = "results/m6d_w3d_input_runtime_readiness.json"

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
PREDICTOR_IDS = ["boltz2_complex", "af2_multimer_colabfold_v1"]
REPRESENTATION_IDS = ["target_msa_binder_query", "query_only_both_chains"]
BASELINE_PREDICTOR_ID = "boltz2_complex"
BASELINE_REPRESENTATION_ID = "target_msa_binder_query"
LRMSD_THRESHOLD_ANGSTROM = 4.0
MINIMUM_CELL_SUCCESSES = 6
MAXIMUM_UNFAVORED_SUCCESSES = 2
MINIMUM_FAVORED_ONLY = 4
MAXIMUM_UNFAVORED_ONLY = 1
TOTAL_FACTORIAL_CELLS = 32
BASELINE_CELLS = 8
PROSPECTIVE_CELLS = 24
STATUS = "w3d_native_representation_predictor_protocol_locked_no_submit"

SOURCE_PATHS = {
    "w3c_b2_native_manifest": "configs/m6d_w3c_b2_native_screen_manifest.json",
    "w3c_b2_runtime_lock": "configs/m6d_w3c_b2_runtime_lock.json",
    "w3c_b2_terminal_stop": "results/m6d_w3c_b2_terminal_stop.json",
    "w3c_b2_boltz_records": "results/m6d_w3c_b2_boltz_native_records.jsonl",
    "w3c_b2_af2_failure_evidence": (
        "results/m6d_w3c_b2_af2_failure_evidence.jsonl"
    ),
    "w3c_b2_boltz_wrapper": "hpc/run_predict_boltz_w3c_b2_native.sbatch",
    "w3c_b2_af2_wrapper": "hpc/run_predict_af2_w3c_b2_native.sbatch",
    "w3c_b2_producer": (
        "src/bio_sfm_designer/experiments/m6d_w3c_b2_producer.py"
    ),
}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
        raise ValueError(f"required W3d source is missing or empty: {path}")
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    """Fail closed on scientific-scope, leakage, decision, or authority drift."""

    _require(
        protocol.get("artifact") == "m6d_w3d_native_diagnostic_protocol"
        and protocol.get("version") == 1
        and protocol.get("status") == STATUS,
        "W3d protocol identity drifted",
    )
    predecessor = protocol.get("predecessor")
    _require(
        isinstance(predecessor, dict)
        and predecessor.get("stage") == "W3c-B2"
        and predecessor.get("closed_without_retry") is True
        and predecessor.get("frozen_stage_pass_impossible") is True
        and predecessor.get("maximum_possible_dual_predictor_passes") == 2
        and predecessor.get("minimum_required_dual_predictor_passes") == 6,
        "W3d predecessor boundary drifted",
    )
    disclosure = protocol.get("design_disclosure")
    _require(
        isinstance(disclosure, dict)
        and disclosure.get(
            "successor_question_formulated_after_w3c_b2_baseline_outcomes"
        )
        is True
        and disclosure.get("baseline_cell_is_retrospective") is True
        and disclosure.get("remaining_cells_are_prospective_after_this_lock") is True
        and disclosure.get("fully_prospective_four_cell_claim_allowed") is False
        and disclosure.get("all_eight_predecessor_targets_retained") is True
        and disclosure.get("target_or_record_filtering_after_baseline_outcomes_allowed")
        is False
        and disclosure.get("baseline_outcomes_may_tune_future_rules") is False
        and disclosure.get("future_outcomes_may_change_scope_or_rules") is False,
        "W3d post-hoc disclosure or leakage boundary drifted",
    )
    target_scope = protocol.get("target_scope")
    _require(
        isinstance(target_scope, dict)
        and target_scope.get("target_count") == len(TARGET_IDS)
        and target_scope.get("target_ids") == TARGET_IDS
        and target_scope.get("target_order_frozen") is True
        and target_scope.get("target_dropping_allowed") is False
        and target_scope.get("replacement_targets_allowed") is False,
        "W3d target scope drifted",
    )
    design = protocol.get("factorial_design")
    _require(
        isinstance(design, dict)
        and design.get("predictor_ids") == PREDICTOR_IDS
        and design.get("representation_ids") == REPRESENTATION_IDS
        and design.get("total_factorial_cells") == TOTAL_FACTORIAL_CELLS
        and design.get("completed_locked_baseline_cells") == BASELINE_CELLS
        and design.get("prospective_cells") == PROSPECTIVE_CELLS
        and design.get("complete_case_adjudication_required") is True
        and design.get("partial_panel_decisions_allowed") is False,
        "W3d factorial design drifted",
    )
    baseline = protocol.get("baseline_reuse")
    _require(
        isinstance(baseline, dict)
        and baseline.get("representation_id") == BASELINE_REPRESENTATION_ID
        and baseline.get("predictor_id") == BASELINE_PREDICTOR_ID
        and baseline.get("records") == BASELINE_CELLS
        and baseline.get("reuse_requires_exact_source_hashes") is True
        and baseline.get("rerun_allowed") is False,
        "W3d baseline reuse contract drifted",
    )
    endpoint = protocol.get("primary_endpoint")
    _require(
        isinstance(endpoint, dict)
        and endpoint.get("metric") == "ligand_rmsd_angstrom"
        and endpoint.get("threshold_angstrom") == LRMSD_THRESHOLD_ANGSTROM
        and endpoint.get("strict_less_than") is True
        and endpoint.get("interface_pae_is_a_qc_value_not_a_selection_threshold")
        is True
        and endpoint.get("minimum_cell_successes_for_qualification")
        == MINIMUM_CELL_SUCCESSES,
        "W3d endpoint contract drifted",
    )
    decision = protocol.get("decision_contract")
    contrast = decision.get("strong_directional_contrast") if isinstance(
        decision, dict
    ) else None
    _require(
        isinstance(contrast, dict)
        and contrast.get("favored_cell_minimum_successes")
        == MINIMUM_CELL_SUCCESSES
        and contrast.get("unfavored_cell_maximum_successes")
        == MAXIMUM_UNFAVORED_SUCCESSES
        and contrast.get("favored_only_minimum_targets") == MINIMUM_FAVORED_ONLY
        and contrast.get("unfavored_only_maximum_targets")
        == MAXIMUM_UNFAVORED_ONLY
        and decision.get("threshold_tuning_after_outcomes_allowed") is False
        and decision.get("target_exclusion_after_outcomes_allowed") is False
        and decision.get("adaptive_top_up_allowed") is False,
        "W3d decision contract drifted",
    )
    representation = protocol.get("representation_contract")
    _require(
        isinstance(representation, dict)
        and representation.get(
            "factor_defined_by_evolutionary_information_not_file_format"
        )
        is True
        and set(representation) >= set(REPRESENTATION_IDS)
        and representation.get("templates_allowed") is False
        and representation.get("prediction_time_network_allowed") is False,
        "W3d representation contract drifted",
    )
    runtime = protocol.get("runtime_contract")
    runtime_ids = (
        runtime.get("predictor_runtime_identity_sha256")
        if isinstance(runtime, dict)
        else None
    )
    _require(
        isinstance(runtime_ids, dict)
        and list(runtime_ids) == PREDICTOR_IDS
        and all(_is_sha256(runtime_ids[predictor]) for predictor in PREDICTOR_IDS)
        and runtime.get("seed") == 0
        and runtime.get("templates_allowed") is False
        and runtime.get("prediction_time_network_allowed") is False
        and runtime.get("same_model_and_sampling_settings_across_representations_required")
        is True
        and runtime.get("new_no_prediction_runtime_validation_required") is True
        and runtime.get("af2_absolute_container_visible_input_and_output_paths_required")
        is True
        and runtime.get("af2_container_working_directory_must_be_explicit") is True
        and runtime.get("old_w3c_b2_af2_wrapper_reusable_for_execution") is False
        and runtime.get("old_failed_af2_job_ids_may_be_recovered") is False,
        "W3d runtime contract drifted",
    )
    compute = protocol.get("proposed_future_compute")
    _require(
        isinstance(compute, dict)
        and compute.get("new_predictor_evaluations") == PROSPECTIVE_CELLS
        and compute.get("new_boltz_evaluations") == 8
        and compute.get("new_af2_evaluations") == 16
        and compute.get("maximum_future_h100_gpu_hours_if_separately_approved")
        == 24.0
        and compute.get("maximum_target_msa_queries") == 0
        and compute.get("proteinmpnn_designs") == 0
        and compute.get("api_calls") == 0
        and compute.get("retries") == 0
        and compute.get("adaptive_top_ups") == 0,
        "W3d proposed compute scope drifted",
    )
    authority = protocol.get("authority")
    _require(
        isinstance(authority, dict)
        and authority.get("protocol_preparation_only") is True
        and authority.get("predictor_evaluations_authorized") == 0
        and authority.get("h100_gpu_hours_authorized") == 0.0
        and authority.get("target_msa_queries_authorized") == 0
        and authority.get("proteinmpnn_designs_authorized") == 0
        and authority.get("api_calls_authorized") == 0
        and authority.get("submission_allowed") is False
        and authority.get("approval_packet_prepared") is False
        and authority.get("explicit_compute_approval_required_later") is True
        and protocol.get("no_submit") is True
        and protocol.get("cayuga_submission_allowed") is False,
        "W3d authority boundary drifted",
    )
    claims = protocol.get("claim_boundary")
    _require(
        isinstance(claims, dict)
        and claims.get("can_claim_fully_prospective_factorial_result") is False
        and claims.get("can_claim_native_recoverability") is False
        and claims.get("can_claim_generator_yield") is False
        and claims.get("can_claim_trust_gate") is False
        and claims.get("can_claim_biological_binder_success") is False,
        "W3d claim boundary drifted",
    )
    source_bindings = protocol.get("source_bindings")
    _require(
        isinstance(source_bindings, dict)
        and set(source_bindings) == set(SOURCE_PATHS),
        "W3d source-binding scope drifted",
    )
    for name, expected_path in SOURCE_PATHS.items():
        binding = source_bindings.get(name)
        _require(
            isinstance(binding, dict)
            and binding.get("path") == expected_path
            and _is_sha256(binding.get("sha256")),
            f"W3d source binding drifted: {name}",
        )


def _verify_source_bindings(protocol: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    bindings: Dict[str, Dict[str, Any]] = {}
    protocol_bindings = protocol["source_bindings"]
    for name, path in SOURCE_PATHS.items():
        actual = _binding(path)
        if actual["sha256"] != protocol_bindings[name]["sha256"]:
            raise ValueError(f"W3d source hash drifted: {name}")
        bindings[name] = actual
    return bindings


def _validate_predecessor(
    protocol: Mapping[str, Any],
    native_manifest: Mapping[str, Any],
    runtime_lock: Mapping[str, Any],
    terminal: Mapping[str, Any],
    af2_failures: Sequence[Mapping[str, Any]],
) -> None:
    _require(
        native_manifest.get("artifact") == "m6d_w3c_b2_native_screen_manifest"
        and native_manifest.get("status")
        == "w3c_b2_native_screen_manifest_locked_no_submit"
        and native_manifest.get("target_ids") == TARGET_IDS
        and native_manifest.get("predictor_ids") == PREDICTOR_IDS
        and native_manifest.get("lrmsd_success_threshold_angstrom")
        == LRMSD_THRESHOLD_ANGSTROM
        and native_manifest.get("minimum_targets_passing")
        == MINIMUM_CELL_SUCCESSES,
        "W3c-B2 native manifest is not the frozen predecessor",
    )
    expected_runtime_ids = protocol["runtime_contract"][
        "predictor_runtime_identity_sha256"
    ]
    runtime_identities = runtime_lock.get("predictor_runtime_identities")
    boltz_parameters = (
        runtime_identities.get("boltz2_complex", {}).get("execution_parameters")
        if isinstance(runtime_identities, dict)
        else None
    )
    af2_parameters = (
        runtime_identities.get("af2_multimer_colabfold_v1", {}).get(
            "execution_parameters"
        )
        if isinstance(runtime_identities, dict)
        else None
    )
    _require(
        runtime_lock.get("artifact") == "m6d_w3c_b2_runtime_lock"
        and runtime_lock.get("predictor_runtime_identity_sha256")
        == expected_runtime_ids
        and isinstance(boltz_parameters, dict)
        and boltz_parameters.get("prediction_time_network_used") is False
        and boltz_parameters.get("templates") is False
        and boltz_parameters.get("seed") == 0
        and isinstance(af2_parameters, dict)
        and af2_parameters.get("prediction_time_network_used") is False
        and af2_parameters.get("templates") is False
        and af2_parameters.get("random_seed") == 0
        and runtime_lock.get("prediction_executed") is False
        and runtime_lock.get("network_fetch_executed") is False,
        "W3c-B2 runtime lock is not reusable by exact identity",
    )
    _require(
        terminal.get("artifact") == "m6d_w3c_b2_terminal_stop"
        and terminal.get("status")
        == "w3c_b2_terminal_partial_result_impossibility_stop"
        and terminal.get("audit_ok") is True
        and terminal.get("scientific_stop_complete") is True
        and terminal.get("stage_pass") is False
        and terminal.get("boltz_records_replayed") == BASELINE_CELLS
        and terminal.get("boltz_successes") == 2
        and terminal.get("af2_failures_before_model_inference") == BASELINE_CELLS
        and terminal.get("maximum_possible_dual_predictor_target_passes") == 2
        and terminal.get("minimum_targets_passing") == MINIMUM_CELL_SUCCESSES
        and terminal.get("af2_recovery_authorized") is False
        and terminal.get("additional_jobs_authorized") == 0
        and terminal.get("no_submit") is True,
        "W3c-B2 terminal stop is not the frozen predecessor outcome",
    )
    _require(
        len(af2_failures) == BASELINE_CELLS
        and [row.get("target_id") for row in af2_failures] == TARGET_IDS
        and all(
            row.get("artifact")
            == "m6d_w3c_b2_af2_terminal_failure_evidence"
            and row.get("predictor_id") == "af2_multimer_colabfold_v1"
            and row.get("failure_class")
            == "pre_inference_container_relative_input_path_resolution"
            and row.get("model_inference_started") is False
            and row.get("predictor_record_present") is False
            for row in af2_failures
        ),
        "W3c-B2 AF2 failure evidence is incomplete or changed",
    )


def _validate_baseline_records(
    native_manifest: Mapping[str, Any],
    runtime_lock: Mapping[str, Any],
    terminal: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    targets = native_manifest.get("targets")
    terminal_results = terminal.get("boltz_results")
    _require(
        isinstance(targets, list)
        and [row.get("target_id") for row in targets] == TARGET_IDS,
        "W3c-B2 target rows are incomplete or reordered",
    )
    _require(
        isinstance(terminal_results, list)
        and [row.get("target_id") for row in terminal_results] == TARGET_IDS,
        "W3c-B2 terminal Boltz rows are incomplete or reordered",
    )
    _require(
        len(records) == BASELINE_CELLS
        and [row.get("complex_target_id") for row in records] == TARGET_IDS,
        "W3d baseline must contain all eight W3c-B2 Boltz records in frozen order",
    )
    runtime_id = runtime_lock["predictor_runtime_identity_sha256"][
        BASELINE_PREDICTOR_ID
    ]
    validated: Dict[str, Dict[str, Any]] = {}
    for target, terminal_row, record in zip(targets, terminal_results, records):
        target_id = str(target["target_id"])
        interface_pae = record.get("interface_pae")
        lrmsd = record.get("lrmsd_angstrom")
        numeric = (
            isinstance(interface_pae, (int, float))
            and not isinstance(interface_pae, bool)
            and math.isfinite(float(interface_pae))
            and isinstance(lrmsd, (int, float))
            and not isinstance(lrmsd, bool)
            and math.isfinite(float(lrmsd))
            and float(lrmsd) >= 0.0
        )
        success = numeric and float(lrmsd) < LRMSD_THRESHOLD_ANGSTROM
        _require(
            record.get("artifact") == "m6d_w3c_b2_native_prediction_record"
            and record.get("version") == 1
            and record.get("status") == "strict_qc_complete"
            and record.get("complex_target_id") == target_id
            and record.get("predictor_id") == BASELINE_PREDICTOR_ID
            and record.get("target_sequence_sha256")
            == target.get("target_sequence_sha256")
            and record.get("binder_sequence_sha256")
            == target.get("binder_sequence_sha256")
            and record.get("target_msa_sha256") == target.get("target_msa_sha256")
            and record.get("reference_backbone_sha256")
            == target.get("prepared_pdb_sha256")
            and record.get("runtime_identity_sha256") == runtime_id
            and record.get("seed") == 0
            and record.get("templates_used") is False
            and record.get("prediction_time_network_used") is False
            and record.get("strict_qc_passed") is True
            and record.get("lrmsd_threshold_angstrom")
            == LRMSD_THRESHOLD_ANGSTROM
            and numeric
            and record.get("success") is success,
            f"{target_id}: baseline Boltz record contract drifted",
        )
        _require(
            terminal_row.get("predictor_id") == BASELINE_PREDICTOR_ID
            and terminal_row.get("strict_qc_passed") is True
            and math.isclose(
                float(terminal_row.get("interface_pae")),
                float(interface_pae),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and math.isclose(
                float(terminal_row.get("lrmsd_angstrom")),
                float(lrmsd),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and terminal_row.get("success") is success,
            f"{target_id}: terminal report and baseline record disagree",
        )
        validated[target_id] = {
            "record_id": record["record_id"],
            "canonical_record_sha256": _canonical_sha256(record),
            "runtime_identity_sha256": runtime_id,
            "interface_pae": float(interface_pae),
            "lrmsd_angstrom": float(lrmsd),
            "success": success,
            "strict_qc_passed": True,
        }
    return validated


def build_manifest(
    protocol: Mapping[str, Any],
    native_manifest: Mapping[str, Any],
    runtime_lock: Mapping[str, Any],
    terminal: Mapping[str, Any],
    baseline_records: Sequence[Mapping[str, Any]],
    af2_failures: Sequence[Mapping[str, Any]],
    *,
    protocol_path: str = PROTOCOL_PATH,
) -> Dict[str, Any]:
    validate_protocol(protocol)
    _require(
        _load_object(protocol_path) == protocol,
        "in-memory W3d protocol differs from the bound protocol file",
    )
    source_bindings = _verify_source_bindings(protocol)
    _validate_predecessor(
        protocol, native_manifest, runtime_lock, terminal, af2_failures
    )
    baseline = _validate_baseline_records(
        native_manifest, runtime_lock, terminal, baseline_records
    )
    protocol_binding = _binding(protocol_path)
    targets_by_id = {
        str(row["target_id"]): row for row in native_manifest["targets"]
    }
    targets: List[Dict[str, Any]] = []
    cells: List[Dict[str, Any]] = []
    output_root = "hpc_outputs/m6d_w3d_native_diagnostic"
    for target_id in TARGET_IDS:
        source = targets_by_id[target_id]
        targets.append({
            "target_id": target_id,
            "target_chain": source["target_chain"],
            "binder_chain": source["binder_chain"],
            "target_sequence_length": source["target_sequence_length"],
            "binder_sequence_length": source["binder_sequence_length"],
            "target_sequence_sha256": source["target_sequence_sha256"],
            "binder_sequence_sha256": source["binder_sequence_sha256"],
            "target_msa": source["target_msa"],
            "target_msa_sha256": source["target_msa_sha256"],
            "target_msa_records": source["a3m_records"],
            "reference_backbone": source["prepared_pdb"],
            "reference_backbone_sha256": source["prepared_pdb_sha256"],
        })
        for representation_id in REPRESENTATION_IDS:
            for predictor_id in PREDICTOR_IDS:
                is_baseline = (
                    representation_id == BASELINE_REPRESENTATION_ID
                    and predictor_id == BASELINE_PREDICTOR_ID
                )
                cell_root = (
                    f"{output_root}/{target_id}/{representation_id}/{predictor_id}"
                )
                cell: Dict[str, Any] = {
                    "cell_id": (
                        f"w3d-{target_id}-{representation_id}-{predictor_id}"
                    ),
                    "target_id": target_id,
                    "representation_id": representation_id,
                    "predictor_id": predictor_id,
                    "cell_status": (
                        "completed_locked_w3c_b2_baseline"
                        if is_baseline
                        else "prospective_not_authorized"
                    ),
                    "prospective_after_protocol_lock": not is_baseline,
                    "new_prediction_required": not is_baseline,
                    "prediction_authorized": False,
                    "planned_output_root": None if is_baseline else cell_root,
                    "planned_record": (
                        None if is_baseline else f"{cell_root}/strict_qc_record.json"
                    ),
                }
                if is_baseline:
                    cell["baseline_outcome"] = baseline[target_id]
                cells.append(cell)

    _require(len(cells) == TOTAL_FACTORIAL_CELLS, "W3d cell count is not 32")
    _require(
        sum(
            row["cell_status"] == "completed_locked_w3c_b2_baseline"
            for row in cells
        )
        == BASELINE_CELLS,
        "W3d baseline cell count is not eight",
    )
    _require(
        sum(row["cell_status"] == "prospective_not_authorized" for row in cells)
        == PROSPECTIVE_CELLS,
        "W3d prospective cell count is not 24",
    )
    return {
        "artifact": "m6d_w3d_native_diagnostic_manifest",
        "version": 1,
        "status": STATUS,
        "audit_ok": True,
        "scientific_question": protocol["scientific_question"],
        "design_type": "retrospective_baseline_prospective_factorial_completion",
        "fully_prospective_four_cell_claim_allowed": False,
        "target_count": len(TARGET_IDS),
        "target_ids": TARGET_IDS,
        "predictor_ids": PREDICTOR_IDS,
        "representation_ids": REPRESENTATION_IDS,
        "total_factorial_cells": TOTAL_FACTORIAL_CELLS,
        "completed_locked_baseline_cells": BASELINE_CELLS,
        "prospective_cells": PROSPECTIVE_CELLS,
        "baseline_successes": sum(row["success"] for row in baseline.values()),
        "baseline_success_target_ids": [
            target_id for target_id in TARGET_IDS if baseline[target_id]["success"]
        ],
        "targets": targets,
        "cells": cells,
        "representation_contract": protocol["representation_contract"],
        "primary_endpoint": protocol["primary_endpoint"],
        "decision_contract": protocol["decision_contract"],
        "runtime_contract": protocol["runtime_contract"],
        "proposed_future_compute": protocol["proposed_future_compute"],
        "authority": protocol["authority"],
        "protocol_binding": protocol_binding,
        "source_bindings": source_bindings,
        "repo_only_replay": (
            "The manifest and readiness audit replay tracked hashes, metadata, records, "
            "and terminal evidence without requiring the original HPC prediction files."
        ),
        "prediction_executed": False,
        "predictor_evaluations_authorized": 0,
        "h100_gpu_hours_authorized": 0.0,
        "proteinmpnn_designs": 0,
        "api_calls": 0,
        "approval_packet_prepared": False,
        "submission_performed": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "claim_boundary": protocol["claim_boundary"]["maximum_current_claim"],
        "next_action": protocol["next_action"],
    }


def _strong_contrast(
    successes_a: Mapping[str, bool],
    successes_b: Mapping[str, bool],
    label_a: str,
    label_b: str,
) -> Dict[str, Any]:
    a_only = [
        target_id
        for target_id in TARGET_IDS
        if successes_a[target_id] and not successes_b[target_id]
    ]
    b_only = [
        target_id
        for target_id in TARGET_IDS
        if successes_b[target_id] and not successes_a[target_id]
    ]
    both = [
        target_id
        for target_id in TARGET_IDS
        if successes_a[target_id] and successes_b[target_id]
    ]
    neither = [
        target_id
        for target_id in TARGET_IDS
        if not successes_a[target_id] and not successes_b[target_id]
    ]
    count_a = sum(successes_a.values())
    count_b = sum(successes_b.values())
    winner: Optional[str] = None
    if (
        count_a >= MINIMUM_CELL_SUCCESSES
        and count_b <= MAXIMUM_UNFAVORED_SUCCESSES
        and len(a_only) >= MINIMUM_FAVORED_ONLY
        and len(b_only) <= MAXIMUM_UNFAVORED_ONLY
    ):
        winner = label_a
    elif (
        count_b >= MINIMUM_CELL_SUCCESSES
        and count_a <= MAXIMUM_UNFAVORED_SUCCESSES
        and len(b_only) >= MINIMUM_FAVORED_ONLY
        and len(a_only) <= MAXIMUM_UNFAVORED_ONLY
    ):
        winner = label_b
    return {
        "label_a": label_a,
        "label_b": label_b,
        "successes_a": count_a,
        "successes_b": count_b,
        "a_only_target_ids": a_only,
        "b_only_target_ids": b_only,
        "both_target_ids": both,
        "neither_target_ids": neither,
        "strong_directional_winner": winner,
    }


def adjudicate_success_matrix(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Apply the frozen W3d localization rules to a complete 32-cell matrix."""

    expected = {
        (target_id, representation_id, predictor_id)
        for target_id in TARGET_IDS
        for representation_id in REPRESENTATION_IDS
        for predictor_id in PREDICTOR_IDS
    }
    observed: Dict[Tuple[str, str, str], bool] = {}
    for row in rows:
        key = (
            str(row.get("target_id") or ""),
            str(row.get("representation_id") or ""),
            str(row.get("predictor_id") or ""),
        )
        success = row.get("success")
        if key in observed:
            raise ValueError(f"duplicate W3d outcome cell: {key}")
        if key not in expected:
            raise ValueError(f"unexpected W3d outcome cell: {key}")
        if not isinstance(success, bool):
            raise ValueError(f"W3d outcome success must be boolean: {key}")
        observed[key] = success
    if set(observed) != expected:
        missing = sorted(expected - set(observed))
        raise ValueError(f"W3d complete-case matrix required; missing={missing}")

    by_cell: Dict[Tuple[str, str], Dict[str, bool]] = {}
    cell_summaries: List[Dict[str, Any]] = []
    for representation_id in REPRESENTATION_IDS:
        for predictor_id in PREDICTOR_IDS:
            values = {
                target_id: observed[(target_id, representation_id, predictor_id)]
                for target_id in TARGET_IDS
            }
            by_cell[(representation_id, predictor_id)] = values
            success_ids = [
                target_id for target_id in TARGET_IDS if values[target_id]
            ]
            cell_summaries.append({
                "representation_id": representation_id,
                "predictor_id": predictor_id,
                "successes": len(success_ids),
                "success_target_ids": success_ids,
                "cell_qualified": len(success_ids) >= MINIMUM_CELL_SUCCESSES,
            })

    representation_comparisons: List[Dict[str, Any]] = []
    for predictor_id in PREDICTOR_IDS:
        comparison = _strong_contrast(
            by_cell[(REPRESENTATION_IDS[0], predictor_id)],
            by_cell[(REPRESENTATION_IDS[1], predictor_id)],
            REPRESENTATION_IDS[0],
            REPRESENTATION_IDS[1],
        )
        comparison["matched_within_predictor_id"] = predictor_id
        representation_comparisons.append(comparison)

    predictor_comparisons: List[Dict[str, Any]] = []
    for representation_id in REPRESENTATION_IDS:
        comparison = _strong_contrast(
            by_cell[(representation_id, PREDICTOR_IDS[0])],
            by_cell[(representation_id, PREDICTOR_IDS[1])],
            PREDICTOR_IDS[0],
            PREDICTOR_IDS[1],
        )
        comparison["matched_within_representation_id"] = representation_id
        predictor_comparisons.append(comparison)

    representation_winners = [
        row["strong_directional_winner"]
        for row in representation_comparisons
        if row["strong_directional_winner"] is not None
    ]
    predictor_winners = [
        row["strong_directional_winner"]
        for row in predictor_comparisons
        if row["strong_directional_winner"] is not None
    ]
    representation_consistent = (
        len(representation_winners) == len(PREDICTOR_IDS)
        and len(set(representation_winners)) == 1
    )
    predictor_consistent = (
        len(predictor_winners) == len(REPRESENTATION_IDS)
        and len(set(predictor_winners)) == 1
    )
    crossover = (
        len(set(representation_winners)) > 1
        or len(set(predictor_winners)) > 1
    )
    if crossover:
        localization = "predictor_by_representation_interaction"
    elif representation_consistent and predictor_consistent:
        localization = "multi_axis_nonseparable"
    elif representation_consistent:
        localization = "representation_specific_native_recovery_failure"
    elif predictor_consistent:
        localization = "predictor_specific_native_recovery_failure"
    elif representation_winners or predictor_winners:
        localization = "partial_localization_not_replicated_across_orthogonal_factor"
    else:
        localization = "mixed_or_unresolved"

    cell_lookup = {
        (row["representation_id"], row["predictor_id"]): row
        for row in cell_summaries
    }
    recovered_representations = [
        representation_id
        for representation_id in REPRESENTATION_IDS
        if all(
            cell_lookup[(representation_id, predictor_id)]["cell_qualified"]
            for predictor_id in PREDICTOR_IDS
        )
    ]
    result: Dict[str, Any] = {
        "artifact": "m6d_w3d_native_diagnostic_decision",
        "version": 1,
        "status": "w3d_complete_matrix_adjudicated",
        "audit_ok": True,
        "records_expected": TOTAL_FACTORIAL_CELLS,
        "records_observed": len(observed),
        "cell_summaries": cell_summaries,
        "representation_comparisons": representation_comparisons,
        "predictor_comparisons": predictor_comparisons,
        "localization": localization,
        "native_validity_recovered": bool(recovered_representations),
        "native_validity_recovered_representation_ids": recovered_representations,
        "candidate_generation_scientifically_reachable": bool(
            recovered_representations
        ),
        "candidate_generation_authorized": False,
        "proteinmpnn_designs_authorized": 0,
        "additional_predictor_evaluations_authorized": 0,
        "threshold_tuning_allowed": False,
        "target_exclusion_allowed": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
    }
    if representation_consistent:
        favored = representation_winners[0]
        result["favored_representation_id"] = favored
        result["bottleneck_representation_id"] = next(
            value for value in REPRESENTATION_IDS if value != favored
        )
    if predictor_consistent:
        favored = predictor_winners[0]
        result["favored_predictor_id"] = favored
        result["bottleneck_predictor_id"] = next(
            value for value in PREDICTOR_IDS if value != favored
        )
    return result


def adjudicate_prospective_outcomes(
    manifest: Mapping[str, Any],
    prospective_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Combine immutable baseline outcomes with exactly 24 prospective outcomes."""

    cells = manifest.get("cells")
    _require(
        manifest.get("artifact") == "m6d_w3d_native_diagnostic_manifest"
        and manifest.get("status") == STATUS
        and manifest.get("target_ids") == TARGET_IDS
        and manifest.get("predictor_ids") == PREDICTOR_IDS
        and manifest.get("representation_ids") == REPRESENTATION_IDS
        and isinstance(cells, list)
        and len(cells) == TOTAL_FACTORIAL_CELLS,
        "W3d adjudication manifest is outside the frozen scope",
    )
    baseline_rows: List[Dict[str, Any]] = []
    expected_prospective = set()
    for cell in cells:
        _require(isinstance(cell, dict), "W3d manifest contains a non-object cell")
        key = (
            str(cell.get("target_id") or ""),
            str(cell.get("representation_id") or ""),
            str(cell.get("predictor_id") or ""),
        )
        if cell.get("cell_status") == "completed_locked_w3c_b2_baseline":
            outcome = cell.get("baseline_outcome")
            _require(
                key[1] == BASELINE_REPRESENTATION_ID
                and key[2] == BASELINE_PREDICTOR_ID
                and isinstance(outcome, dict)
                and isinstance(outcome.get("success"), bool)
                and _is_sha256(outcome.get("canonical_record_sha256")),
                f"W3d baseline cell drifted: {key}",
            )
            baseline_rows.append({
                "target_id": key[0],
                "representation_id": key[1],
                "predictor_id": key[2],
                "success": outcome["success"],
            })
        elif cell.get("cell_status") == "prospective_not_authorized":
            expected_prospective.add(key)
        else:
            raise ValueError(f"W3d cell status drifted: {key}")
    _require(
        len(baseline_rows) == BASELINE_CELLS
        and [row["target_id"] for row in baseline_rows] == TARGET_IDS
        and sum(row["success"] for row in baseline_rows) == 2,
        "W3d baseline outcomes are incomplete, reordered, or changed",
    )
    _require(
        len(expected_prospective) == PROSPECTIVE_CELLS,
        "W3d prospective scope is not exactly 24 cells",
    )

    observed_prospective = set()
    normalized: List[Dict[str, Any]] = []
    for row in prospective_rows:
        key = (
            str(row.get("target_id") or ""),
            str(row.get("representation_id") or ""),
            str(row.get("predictor_id") or ""),
        )
        if key in observed_prospective:
            raise ValueError(f"duplicate W3d prospective outcome cell: {key}")
        if key not in expected_prospective:
            raise ValueError(f"unexpected W3d prospective outcome cell: {key}")
        if not isinstance(row.get("success"), bool):
            raise ValueError(f"W3d prospective success must be boolean: {key}")
        observed_prospective.add(key)
        normalized.append({
            "target_id": key[0],
            "representation_id": key[1],
            "predictor_id": key[2],
            "success": row["success"],
        })
    if observed_prospective != expected_prospective:
        missing = sorted(expected_prospective - observed_prospective)
        raise ValueError(
            f"W3d requires all 24 prospective outcomes; missing={missing}"
        )
    decision = adjudicate_success_matrix(baseline_rows + normalized)
    decision.update({
        "design_type": "retrospective_baseline_prospective_factorial_completion",
        "completed_locked_baseline_cells": BASELINE_CELLS,
        "prospective_cells_adjudicated": PROSPECTIVE_CELLS,
        "fully_prospective_four_cell_claim_allowed": False,
    })
    return decision


def build_readiness(
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    manifest_path: str = MANIFEST_PATH,
) -> Dict[str, Any]:
    validate_protocol(protocol)
    _require(
        _load_object(manifest_path) == manifest,
        "in-memory W3d manifest differs from the bound manifest file",
    )
    cells = manifest.get("cells")
    _require(
        manifest.get("artifact") == "m6d_w3d_native_diagnostic_manifest"
        and manifest.get("version") == 1
        and manifest.get("status") == STATUS
        and manifest.get("audit_ok") is True
        and manifest.get("target_ids") == TARGET_IDS
        and manifest.get("predictor_ids") == PREDICTOR_IDS
        and manifest.get("representation_ids") == REPRESENTATION_IDS
        and isinstance(cells, list)
        and len(cells) == TOTAL_FACTORIAL_CELLS
        and manifest.get("completed_locked_baseline_cells") == BASELINE_CELLS
        and manifest.get("prospective_cells") == PROSPECTIVE_CELLS
        and manifest.get("baseline_successes") == 2
        and manifest.get("baseline_success_target_ids")
        == ["5E5M_AB", "5JSB_AB"],
        "W3d manifest is not the exact frozen factorial scope",
    )
    expected_cells = [
        (target_id, representation_id, predictor_id)
        for target_id in TARGET_IDS
        for representation_id in REPRESENTATION_IDS
        for predictor_id in PREDICTOR_IDS
    ]
    observed_cells = [
        (row.get("target_id"), row.get("representation_id"), row.get("predictor_id"))
        for row in cells
        if isinstance(row, dict)
    ]
    _require(
        observed_cells == expected_cells,
        "W3d manifest cell order or membership drifted",
    )
    _require(
        all(row.get("prediction_authorized") is False for row in cells),
        "W3d manifest unexpectedly authorizes prediction",
    )
    from bio_sfm_designer.experiments import m6d_w3d_input_runtime

    input_manifest = _load_object(INPUT_MANIFEST_PATH)
    input_runtime_readiness = _load_object(INPUT_RUNTIME_READINESS_PATH)
    m6d_w3d_input_runtime.validate_input_manifest(
        input_manifest,
        input_manifest_path=INPUT_MANIFEST_PATH,
        require_files=False,
    )
    m6d_w3d_input_runtime.validate_public_readiness(
        input_runtime_readiness,
        input_manifest_path=INPUT_MANIFEST_PATH,
    )
    runtime_validation_complete = input_runtime_readiness[
        "no_prediction_runtime_validation_complete"
    ]
    return {
        "artifact": "m6d_w3d_native_diagnostic_readiness",
        "version": 1,
        "status": STATUS,
        "audit_ok": True,
        "protocol_locked": True,
        "source_hashes_verified": len(SOURCE_PATHS),
        "target_count": len(TARGET_IDS),
        "target_ids": TARGET_IDS,
        "predictor_ids": PREDICTOR_IDS,
        "representation_ids": REPRESENTATION_IDS,
        "factorial_cells": TOTAL_FACTORIAL_CELLS,
        "completed_locked_baseline_cells": BASELINE_CELLS,
        "completed_locked_baseline_successes": 2,
        "prospective_cells": PROSPECTIVE_CELLS,
        "prospective_boltz_cells": 8,
        "prospective_af2_cells": 16,
        "all_predecessor_targets_retained": True,
        "posthoc_disclosure_complete": True,
        "decision_rules_locked": True,
        "complete_case_adjudication_required": True,
        "outcome_adjudicator_implemented": True,
        "cpu_only_preparation_complete": True,
        "input_producer_implemented": True,
        "materialized_input_files": 24,
        "materialized_input_hashes_verified": 24,
        "representation_semantics_verified": 24,
        "new_runtime_wrappers_implemented": True,
        "wrapper_static_no_prediction_validation_complete": True,
        "af2_absolute_path_contract_implemented": True,
        "af2_explicit_container_working_directory_implemented": True,
        "no_prediction_runtime_validation_complete": runtime_validation_complete,
        "input_manifest_binding": _binding(INPUT_MANIFEST_PATH),
        "input_runtime_readiness_binding": _binding(
            INPUT_RUNTIME_READINESS_PATH
        ),
        "input_runtime_preparation_status": input_runtime_readiness["status"],
        "approval_packet_prepared": False,
        "execution_ready": False,
        "prediction_executed": False,
        "predictor_evaluations_authorized": 0,
        "h100_gpu_hours_authorized": 0.0,
        "maximum_future_h100_gpu_hours_if_separately_approved": 24.0,
        "target_msa_queries_authorized": 0,
        "proteinmpnn_designs": 0,
        "api_calls": 0,
        "retries_authorized": 0,
        "adaptive_top_ups_authorized": 0,
        "old_w3c_b2_job_recovery_authorized": False,
        "submission_performed": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_fully_prospective_factorial_result": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "protocol_binding": manifest["protocol_binding"],
        "manifest_binding": _binding(manifest_path),
        "source_bindings": manifest["source_bindings"],
        "claim_boundary": protocol["claim_boundary"]["maximum_current_claim"],
        "protocol_next_action": protocol["next_action"],
        "next_action": input_runtime_readiness["next_action"],
    }


def render_markdown(readiness: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3d Native Representation-by-Predictor Diagnostic",
        "",
        f"Status: `{readiness['status']}`.",
        f"Audit ok: `{readiness['audit_ok']}`.",
        f"Execution ready: `{readiness['execution_ready']}`.",
        "",
        "## Frozen Design",
        "",
        "| Representation | Boltz | AF2 |",
        "|---|---:|---:|",
        "| target MSA + binder query | 8 locked baseline | 8 prospective |",
        "| query-only both chains | 8 prospective | 8 prospective |",
        "",
        f"- targets retained: `{readiness['target_count']}` / `8`",
        f"- total factorial cells: `{readiness['factorial_cells']}`",
        f"- immutable baseline cells: `{readiness['completed_locked_baseline_cells']}`",
        f"- prospective cells: `{readiness['prospective_cells']}`",
        f"- materialized inputs verified: `{readiness['materialized_input_hashes_verified']}` / `24`",
        f"- representation semantics verified: `{readiness['representation_semantics_verified']}` / `24`",
        f"- no-prediction wrappers implemented: `{readiness['new_runtime_wrappers_implemented']}`",
        f"- exact Cayuga runtime validation complete: `{readiness['no_prediction_runtime_validation_complete']}`",
        f"- currently authorized predictor evaluations: `{readiness['predictor_evaluations_authorized']}`",
        f"- currently authorized H100 GPU-hours: `{readiness['h100_gpu_hours_authorized']}`",
        "",
        "## Locked Baseline",
        "",
        "| Target | interface pAE | L-RMSD (A) | Success |",
        "|---|---:|---:|:---:|",
    ]
    for cell in manifest["cells"]:
        if cell["cell_status"] != "completed_locked_w3c_b2_baseline":
            continue
        outcome = cell["baseline_outcome"]
        lines.append(
            "| {target} | {pae:.4f} | {lrmsd:.6f} | {success} |".format(
                target=cell["target_id"],
                pae=outcome["interface_pae"],
                lrmsd=outcome["lrmsd_angstrom"],
                success=outcome["success"],
            )
        )
    lines.extend([
        "",
        "## Interpretation Boundary",
        "",
        (
            "This is a retrospective-baseline/prospective-completion diagnostic, not a "
            "fully prospective four-cell experiment. All eight baseline targets are retained, "
            "and the remaining 24 cells and decision rules are frozen before new outcomes."
        ),
        "",
        str(readiness["claim_boundary"]),
        "",
        f"Next action: {readiness['next_action']}",
        "",
    ])
    return "\n".join(lines)


def run(
    protocol_path: str = PROTOCOL_PATH,
    *,
    manifest_path: str = MANIFEST_PATH,
    readiness_path: str = READINESS_PATH,
    readiness_md_path: str = READINESS_MD_PATH,
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    validate_protocol(protocol)
    native_manifest = _load_object(SOURCE_PATHS["w3c_b2_native_manifest"])
    runtime_lock = _load_object(SOURCE_PATHS["w3c_b2_runtime_lock"])
    terminal = _load_object(SOURCE_PATHS["w3c_b2_terminal_stop"])
    baseline_records = _load_jsonl(SOURCE_PATHS["w3c_b2_boltz_records"])
    af2_failures = _load_jsonl(SOURCE_PATHS["w3c_b2_af2_failure_evidence"])
    manifest = build_manifest(
        protocol,
        native_manifest,
        runtime_lock,
        terminal,
        baseline_records,
        af2_failures,
        protocol_path=protocol_path,
    )
    _write_json_idempotent(manifest_path, manifest)
    readiness = build_readiness(protocol, manifest, manifest_path=manifest_path)
    _write_json_idempotent(readiness_path, readiness)
    _write_text_idempotent(
        readiness_md_path, render_markdown(readiness, manifest)
    )
    return readiness


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=PROTOCOL_PATH)
    parser.add_argument("--manifest", default=MANIFEST_PATH)
    parser.add_argument("--readiness", default=READINESS_PATH)
    parser.add_argument("--readiness-md", default=READINESS_MD_PATH)
    args = parser.parse_args(argv)
    readiness = run(
        args.protocol,
        manifest_path=args.manifest,
        readiness_path=args.readiness,
        readiness_md_path=args.readiness_md,
    )
    print(
        f"status={readiness['status']} audit_ok={readiness['audit_ok']} "
        f"baseline={readiness['completed_locked_baseline_cells']} "
        f"prospective={readiness['prospective_cells']} "
        "authorized=0 no_submit=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
