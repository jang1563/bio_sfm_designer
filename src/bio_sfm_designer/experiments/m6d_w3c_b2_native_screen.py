"""Freeze and adjudicate the W3c-B2 native dual-predictor screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    validate_runtime_lock as validate_w3b_runtime_lock,
)


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
LRMSD_THRESHOLD_ANGSTROM = 4.0
MINIMUM_TARGETS_PASSING = 6
MAXIMUM_PREDICTOR_EVALUATIONS = 16
MAXIMUM_H100_GPU_HOURS = 16.0
SLURM_TIME_PER_EVALUATION = "01:00:00"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def _load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(value)
    return rows


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _binding(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError(f"bound artifact is missing or empty: {path}")
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": _sha256_file(path),
    }


def _stage(protocol: Mapping[str, Any], stage_id: str) -> Mapping[str, Any]:
    stages = protocol.get("stages")
    if not isinstance(stages, list):
        return {}
    return next(
        (
            row
            for row in stages
            if isinstance(row, dict) and row.get("stage") == stage_id
        ),
        {},
    )


def _pdb_chain_sequence(path: str, chain: str) -> str:
    sequence: List[str] = []
    seen: set[Tuple[str, str]] = set()
    with open(path) as handle:
        for line in handle:
            if line.startswith("ENDMDL"):
                break
            if (
                line[:6].strip() != "ATOM"
                or line[12:16].strip() != "CA"
                or line[16] not in (" ", "A")
                or line[21] != chain
            ):
                continue
            residue_id = (line[22:26].strip(), line[26].strip())
            if residue_id in seen:
                continue
            seen.add(residue_id)
            residue_name = line[17:20].strip()
            amino_acid = _AA3_TO_1.get(residue_name)
            if amino_acid is None:
                raise ValueError(
                    f"unsupported residue {residue_name!r} in {path} chain {chain}"
                )
            sequence.append(amino_acid)
    if not sequence:
        raise ValueError(f"chain {chain!r} has no modeled CA sequence in {path}")
    return "".join(sequence)


def _first_sequence(path: str, *, a3m: bool = False) -> str:
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


def _a3m_records(path: str) -> int:
    with open(path, "rb") as handle:
        return sum(line.startswith(b">") for line in handle)


def _protocol_failures(protocol: Mapping[str, Any]) -> List[str]:
    stage = _stage(protocol, "W3c-B2")
    runtime = protocol.get("runtime_boundary")
    claim = protocol.get("claim_boundary")
    checks = {
        "identity": (
            protocol.get("artifact") == "m6d_w3c_validity_first_protocol"
            and protocol.get("version") == 1
            and protocol.get("status")
            == "preregistered_target_discovery_only_no_submit"
        ),
        "scope": (
            stage.get("name") == "native dual-predictor recoverability screen"
            and stage.get("compute") == "Cayuga H100"
            and stage.get("targets") == 8
            and stage.get("native_sequences_per_target") == 1
            and stage.get("predictors") == PREDICTOR_IDS
            and stage.get("maximum_predictor_evaluations")
            == MAXIMUM_PREDICTOR_EVALUATIONS
            and stage.get("proteinmpnn_designs") == 0
            and stage.get("approval_required") is True
            and stage.get("approval_status") == "not_prepared"
        ),
        "decision_rule": (
            float(stage.get("lrmsd_success_threshold_angstrom") or 0.0)
            == LRMSD_THRESHOLD_ANGSTROM
            and stage.get("minimum_targets_passing") == MINIMUM_TARGETS_PASSING
            and stage.get("target_pass_rule")
            == (
                "Both predictors must produce strict-QC records with finite interface pAE "
                "and L-RMSD below 4.0 A against the native complex."
            )
        ),
        "runtime": (
            isinstance(runtime, dict)
            and runtime.get("w3b_runtime_may_transfer_only_by_exact_hash_match")
            is True
            and runtime.get("new_runtime_observation_required") is True
            and runtime.get("new_budget_lock_required_before_approval") is True
            and runtime.get("prediction_time_network_allowed") is False
            and runtime.get("templates_allowed") is False
            and runtime.get("seed") == 0
        ),
        "claim": (
            isinstance(claim, dict)
            and claim.get("native_screen_supports_generator_claim") is False
            and claim.get("native_screen_supports_trust_gate_claim") is False
            and claim.get("native_screen_supports_biological_binder_success_claim")
            is False
        ),
        "boundary": (
            protocol.get("no_submit") is True
            and protocol.get("cayuga_submission_allowed") is False
        ),
    }
    return [name for name, passed in checks.items() if not passed]


def _validate_b1_completion(
    completion: Mapping[str, Any],
    b1_manifest_path: str,
) -> Dict[str, Mapping[str, Any]]:
    bindings = completion.get("input_bindings")
    artifacts = completion.get("target_artifacts")
    if not (
        completion.get("artifact") == "m6d_w3c_b1_target_msa_completion"
        and completion.get("version") == 1
        and completion.get("status") == "target_msa_precompute_complete_8_of_8"
        and completion.get("audit_ok") is True
        and completion.get("completion_ok") is True
        and completion.get("target_ids") == TARGET_IDS
        and completion.get("n_target_msas") == 8
        and completion.get("strict_manifest_ready_targets") == 8
        and completion.get("can_prepare_w3c_b2_packet") is True
        and completion.get("can_submit_w3c_b2") is False
        and completion.get("failures") == []
        and isinstance(bindings, dict)
        and bindings.get("execution_manifest", {}).get("path") == b1_manifest_path
        and bindings.get("execution_manifest", {}).get("sha256")
        == _sha256_file(b1_manifest_path)
        and isinstance(artifacts, list)
        and [row.get("target_id") for row in artifacts] == TARGET_IDS
    ):
        raise ValueError("W3c-B1 completion does not open the B2 packet boundary")
    return {str(row["target_id"]): row for row in artifacts}


def _validate_w3b_runtime_source(
    runtime_lock: Mapping[str, Any],
    w3b_protocol_path: str,
) -> None:
    failures = validate_w3b_runtime_lock(dict(runtime_lock), w3b_protocol_path)
    if failures:
        raise ValueError(
            "W3b runtime transfer source is invalid: "
            + str(failures[0].get("kind"))
        )
    if set(runtime_lock.get("predictor_runtime_identity_sha256", {})) != set(
        PREDICTOR_IDS
    ):
        raise ValueError("W3b runtime transfer source lacks the exact predictor pair")


def build_native_manifest(
    protocol: Mapping[str, Any],
    b1_manifest: Mapping[str, Any],
    b1_completion: Mapping[str, Any],
    w3b_runtime_lock: Mapping[str, Any],
    *,
    protocol_path: str,
    b1_manifest_path: str,
    b1_completion_path: str,
    w3b_runtime_lock_path: str,
    w3b_protocol_path: str,
    output_root: str = "hpc_outputs/m6d_w3c_b2_native",
) -> Dict[str, Any]:
    protocol_failures = _protocol_failures(protocol)
    if protocol_failures:
        raise ValueError(
            "W3c-B2 protocol invariants failed: " + ", ".join(protocol_failures)
        )
    completion_by_id = _validate_b1_completion(b1_completion, b1_manifest_path)
    _validate_w3b_runtime_source(w3b_runtime_lock, w3b_protocol_path)
    targets = [
        row for row in b1_manifest.get("targets", []) if isinstance(row, dict)
    ]
    if not (
        b1_manifest.get("artifact") == "m6d_w3c_b1_target_msa_manifest"
        and b1_manifest.get("version") == 1
        and b1_manifest.get("target_count") == 8
        and b1_manifest.get("target_ids") == TARGET_IDS
        and [row.get("id") for row in targets] == TARGET_IDS
    ):
        raise ValueError("W3c-B1 manifest does not contain the exact B2 target panel")

    native_targets: List[Dict[str, Any]] = []
    output_paths: List[str] = []
    for target in targets:
        target_id = str(target["id"])
        completion_row = completion_by_id[target_id]
        prepared_pdb = str(target.get("prepared_pdb") or "")
        target_fasta = str(target.get("target_fasta") or "")
        target_msa = str(target.get("target_msa") or "")
        target_msa_report = str(target.get("target_msa_report") or "")
        for path in (prepared_pdb, target_fasta, target_msa, target_msa_report):
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                raise ValueError(f"W3c-B2 required input is missing: {target_id}: {path}")
        target_sequence = _pdb_chain_sequence(
            prepared_pdb, str(target["target_chain"])
        )
        binder_sequence = _pdb_chain_sequence(
            prepared_pdb, str(target["binder_chain"])
        )
        fasta_sequence = _first_sequence(target_fasta)
        msa_query = _first_sequence(target_msa, a3m=True)
        target_msa_sha256 = _sha256_file(target_msa)
        checks = {
            "target_sequence_hash": (
                _sequence_sha256(target_sequence)
                == target.get("target_sequence_sha256")
                == completion_row.get("target_sequence_sha256")
            ),
            "binder_sequence_hash": (
                _sequence_sha256(binder_sequence)
                == target.get("binder_sequence_sha256")
            ),
            "minimum_chain_lengths": (
                len(target_sequence) >= 40 and len(binder_sequence) >= 40
            ),
            "fasta_sequence": fasta_sequence == target_sequence,
            "msa_query": msa_query == target_sequence,
            "msa_hash": (
                target_msa_sha256 == completion_row.get("target_msa_sha256")
            ),
            "msa_report_hash": (
                _sha256_file(target_msa_report)
                == completion_row.get("target_msa_report_sha256")
            ),
            "completion_checks": (
                isinstance(completion_row.get("checks"), dict)
                and all(completion_row["checks"].values())
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise ValueError(
                f"W3c-B2 native input binding failed ({target_id}): "
                + ", ".join(failed)
            )
        target_root = f"{output_root}/{target_id}"
        outputs = {
            "boltz_record": f"{target_root}/boltz2_native_record.json",
            "af2_record": f"{target_root}/af2_multimer_native_record.json",
            "matched_record": f"{target_root}/matched_native_record.json",
            "boltz_output_dir": f"{target_root}/boltz_predictions",
            "af2_input_dir": f"{target_root}/af2_inputs",
            "af2_input_manifest": f"{target_root}/af2_input_manifest.json",
            "af2_output_dir": f"{target_root}/af2_predictions",
        }
        output_paths.extend(outputs.values())
        native_targets.append({
            "target_id": target_id,
            "native_candidate_id": f"w3c-b2-native-{target_id}",
            "rcsb_id": target["rcsb_id"],
            "target_chain": target["target_chain"],
            "binder_chain": target["binder_chain"],
            "prepared_pdb": prepared_pdb,
            "prepared_pdb_sha256": _sha256_file(prepared_pdb),
            "source_pdb": target["source_pdb"],
            "source_pdb_sha256": target["source_pdb_sha256"],
            "target_sequence_length": len(target_sequence),
            "target_sequence_sha256": _sequence_sha256(target_sequence),
            "binder_sequence_length": len(binder_sequence),
            "binder_sequence_sha256": _sequence_sha256(binder_sequence),
            "target_fasta": target_fasta,
            "target_fasta_sha256": _sha256_file(target_fasta),
            "target_msa": target_msa,
            "target_msa_sha256": target_msa_sha256,
            "target_msa_report": target_msa_report,
            "target_msa_report_sha256": _sha256_file(target_msa_report),
            "a3m_records": _a3m_records(target_msa),
            "predictors": PREDICTOR_IDS,
            "outputs": outputs,
            "checks": checks,
        })
    existing_outputs = [path for path in output_paths if os.path.exists(path)]
    if existing_outputs:
        raise ValueError(
            "W3c-B2 initial output paths already exist: " + ",".join(existing_outputs)
        )
    predictor_digests = dict(
        w3b_runtime_lock["predictor_runtime_identity_sha256"]
    )
    return {
        "artifact": "m6d_w3c_b2_native_screen_manifest",
        "version": 1,
        "status": "w3c_b2_native_screen_manifest_locked_no_submit",
        "scientific_question": protocol["scientific_question"],
        "bound_artifacts": {
            "protocol": _binding(protocol_path),
            "w3c_b1_execution_manifest": _binding(b1_manifest_path),
            "w3c_b1_completion": _binding(b1_completion_path),
            "w3b_runtime_transfer_source": _binding(w3b_runtime_lock_path),
            "w3b_runtime_source_protocol": _binding(w3b_protocol_path),
        },
        "target_count": 8,
        "target_ids": TARGET_IDS,
        "predictor_ids": PREDICTOR_IDS,
        "native_sequences_per_target": 1,
        "maximum_predictor_evaluations": MAXIMUM_PREDICTOR_EVALUATIONS,
        "proteinmpnn_designs": 0,
        "lrmsd_success_threshold_angstrom": LRMSD_THRESHOLD_ANGSTROM,
        "minimum_targets_passing": MINIMUM_TARGETS_PASSING,
        "target_pass_rule": (
            "Both frozen predictors must produce strict-QC records with finite interface "
            "pAE and L-RMSD below 4.0 A against the native complex."
        ),
        "stage_pass_rule": "At least six of eight targets must pass.",
        "runtime_contract": {
            "transfer_source": "configs/m6d_w3b_runtime_lock.json",
            "transfer_source_sha256": _sha256_file(w3b_runtime_lock_path),
            "transfer_source_digest_sha256": w3b_runtime_lock[
                "runtime_lock_digest_sha256"
            ],
            "expected_predictor_runtime_identity_sha256": predictor_digests,
            "exact_hash_match_required": True,
            "new_runtime_observation_required": True,
            "runtime_reobservation_complete": False,
            "seed": 0,
            "templates_allowed": False,
            "prediction_time_network_allowed": False,
        },
        "compute_budget": {
            "resource_per_evaluation": "h100:1",
            "maximum_walltime_per_evaluation": SLURM_TIME_PER_EVALUATION,
            "maximum_h100_gpu_hours": MAXIMUM_H100_GPU_HOURS,
            "maximum_boltz_evaluations": 8,
            "maximum_af2_evaluations": 8,
            "maximum_total_evaluations": MAXIMUM_PREDICTOR_EVALUATIONS,
            "no_retry_or_adaptive_top_up": True,
            "post_execution_slurm_accounting_required": True,
        },
        "targets": native_targets,
        "preexisting_output_paths": existing_outputs,
        "approval_recorded": False,
        "predictor_evaluations_authorized": 0,
        "submission_performed": False,
        "submitted_jobs": 0,
        "prediction_executed": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "claim_boundary": (
            "Preregistered native-recoverability input and decision lock only. This manifest "
            "authorizes zero prediction, zero ProteinMPNN work, and no scientific claim."
        ),
        "next_action": (
            "Reobserve both exact predictor runtimes without prediction, then prepare a "
            "separately guarded W3c-B2 H100 approval packet."
        ),
    }


def _runtime_lock_failures(
    runtime_lock: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: Optional[str] = None,
) -> List[str]:
    expected_digests = manifest.get("runtime_contract", {}).get(
        "expected_predictor_runtime_identity_sha256"
    )
    checks = {
        "identity": (
            runtime_lock.get("artifact") == "m6d_w3c_b2_runtime_lock"
            and runtime_lock.get("version") == 1
            and runtime_lock.get("status")
            == "w3c_b2_dual_predictor_runtime_reobserved_no_prediction"
            and runtime_lock.get("audit_ok") is True
        ),
        "manifest_binding": (
            manifest_sha256 is None
            or runtime_lock.get("native_screen_manifest_sha256") == manifest_sha256
        ),
        "predictor_pair": (
            runtime_lock.get("predictor_runtime_identity_sha256")
            == expected_digests
        ),
        "observation_boundary": (
            runtime_lock.get("new_runtime_observations") == 2
            and runtime_lock.get("prediction_executed") is False
            and runtime_lock.get("gpu_compute_executed") is False
            and runtime_lock.get("network_fetch_executed") is False
            and runtime_lock.get("submitted_jobs") == 0
        ),
        "authority": (
            runtime_lock.get("no_submit") is True
            and runtime_lock.get("cayuga_submission_allowed") is False
            and runtime_lock.get("can_run_predictors") is False
            and runtime_lock.get("can_claim_native_recoverability") is False
            and runtime_lock.get("failures") == []
        ),
    }
    return [name for name, passed in checks.items() if not passed]


def evaluate_records(
    manifest: Mapping[str, Any],
    runtime_lock: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: Optional[str] = None,
    runtime_lock_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    runtime_failures = _runtime_lock_failures(
        runtime_lock, manifest, manifest_sha256=manifest_sha256
    )
    failures.extend(
        {"kind": "runtime_lock_invalid", "check": check}
        for check in runtime_failures
    )
    targets = {
        str(row.get("target_id") or ""): row
        for row in manifest.get("targets", [])
        if isinstance(row, dict)
    }
    expected_pairs = {
        (target_id, predictor_id)
        for target_id in TARGET_IDS
        for predictor_id in PREDICTOR_IDS
    }
    observed: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    expected_runtime_digests = runtime_lock.get(
        "predictor_runtime_identity_sha256", {}
    )
    for record in records:
        target_id = str(record.get("complex_target_id") or "")
        predictor_id = str(record.get("predictor_id") or "")
        pair = (target_id, predictor_id)
        if pair not in expected_pairs:
            failures.append({"kind": "unexpected_record", "pair": list(pair)})
            continue
        if pair in observed:
            failures.append({"kind": "duplicate_record", "pair": list(pair)})
            continue
        observed[pair] = record
        target = targets[target_id]
        lrmsd = record.get("lrmsd_angstrom")
        interface_pae = record.get("interface_pae")
        finite_metrics = (
            isinstance(lrmsd, (int, float))
            and not isinstance(lrmsd, bool)
            and math.isfinite(float(lrmsd))
            and isinstance(interface_pae, (int, float))
            and not isinstance(interface_pae, bool)
            and math.isfinite(float(interface_pae))
        )
        expected_success = finite_metrics and float(lrmsd) < LRMSD_THRESHOLD_ANGSTROM
        output_bindings = record.get("output_bindings")
        bindings_valid = (
            isinstance(output_bindings, dict)
            and set(output_bindings) == {"model", "confidence"}
            and all(
                isinstance(binding, dict)
                and isinstance(binding.get("path"), str)
                and _is_sha256(binding.get("sha256"))
                for binding in output_bindings.values()
            )
        )
        checks = {
            "identity": (
                record.get("artifact")
                == "m6d_w3c_b2_native_prediction_record"
                and record.get("version") == 1
                and record.get("status") == "strict_qc_complete"
                and record.get("record_id")
                == f"w3c-b2-native-{target_id}-{predictor_id}"
                and record.get("native_candidate_id")
                == target["native_candidate_id"]
            ),
            "sequence_and_reference": (
                record.get("target_sequence_sha256")
                == target["target_sequence_sha256"]
                and record.get("binder_sequence_sha256")
                == target["binder_sequence_sha256"]
                and record.get("target_msa_sha256")
                == target["target_msa_sha256"]
                and record.get("reference_backbone_sha256")
                == target["prepared_pdb_sha256"]
            ),
            "runtime": (
                record.get("runtime_identity_sha256")
                == expected_runtime_digests.get(predictor_id)
                and (
                    runtime_lock_sha256 is None
                    or record.get("runtime_lock_sha256")
                    == runtime_lock_sha256
                )
            ),
            "prediction_contract": (
                record.get("seed") == 0
                and record.get("templates_used") is False
                and record.get("prediction_time_network_used") is False
            ),
            "metrics": (
                finite_metrics
                and record.get("lrmsd_threshold_angstrom")
                == LRMSD_THRESHOLD_ANGSTROM
                and record.get("success") is expected_success
            ),
            "strict_qc": record.get("strict_qc_passed") is True,
            "output_bindings": bindings_valid,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            failures.append({
                "kind": "record_contract_invalid",
                "pair": list(pair),
                "checks_failed": failed,
            })
    missing = sorted(expected_pairs - set(observed))
    if missing:
        failures.append({
            "kind": "missing_records",
            "pairs": [list(pair) for pair in missing],
        })

    target_results: List[Dict[str, Any]] = []
    for target_id in TARGET_IDS:
        predictor_results = []
        for predictor_id in PREDICTOR_IDS:
            record = observed.get((target_id, predictor_id))
            predictor_results.append({
                "predictor_id": predictor_id,
                "record_present": record is not None,
                "strict_qc_passed": (
                    record.get("strict_qc_passed") is True if record else False
                ),
                "interface_pae": record.get("interface_pae") if record else None,
                "lrmsd_angstrom": record.get("lrmsd_angstrom") if record else None,
                "success": record.get("success") is True if record else False,
            })
        target_results.append({
            "target_id": target_id,
            "predictors": predictor_results,
            "target_pass": all(row["success"] for row in predictor_results),
        })
    targets_passing = sum(row["target_pass"] for row in target_results)
    audit_ok = not failures
    stage_pass = audit_ok and targets_passing >= MINIMUM_TARGETS_PASSING
    return {
        "artifact": "m6d_w3c_b2_native_recoverability_report",
        "version": 1,
        "status": (
            "w3c_b2_native_recoverability_pass"
            if stage_pass
            else (
                "w3c_b2_native_recoverability_stop"
                if audit_ok
                else "w3c_b2_native_recoverability_adjudication_blocked"
            )
        ),
        "audit_ok": audit_ok,
        "stage_pass": stage_pass,
        "records_expected": 16,
        "records_observed": len(observed),
        "targets_expected": 8,
        "targets_passing": targets_passing,
        "minimum_targets_passing": MINIMUM_TARGETS_PASSING,
        "lrmsd_success_threshold_angstrom": LRMSD_THRESHOLD_ANGSTROM,
        "target_results": target_results,
        "proteinmpnn_designs": 0,
        "can_claim_native_recoverability_on_locked_panel": stage_pass,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "At most a native-recoverability result for the eight prospectively locked "
            "complexes under the exact two-predictor protocol. This is not generator, "
            "trust-gate, or biological binder-success evidence."
        ),
        "next_action": (
            "Preregister a separate generator-yield experiment."
            if stage_pass
            else (
                "Stop before candidate generation and revise representation or predictor scope."
                if audit_ok
                else "Repair record or provenance failures before scientific adjudication."
            )
        ),
    }


def render_manifest_markdown(manifest: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B2 Native-Screen Manifest",
        "",
        f"Status: `{manifest['status']}`.",
        f"No submit: `{manifest['no_submit']}`.",
        "",
        str(manifest["claim_boundary"]),
        "",
        "## Frozen Scope",
        "",
        "- targets: `8`",
        "- predictors: `boltz2_complex`, `af2_multimer_colabfold_v1`",
        "- native complexes per target: `1`",
        "- maximum predictor evaluations: `16`",
        "- L-RMSD success threshold: `<4.0 A`",
        "- target pass: both predictors pass strict QC and threshold",
        "- stage pass: at least `6/8` targets",
        "- ProteinMPNN designs: `0`",
        f"- maximum H100 GPU-hours: `{manifest['compute_budget']['maximum_h100_gpu_hours']}`",
        "- runtime reobservation complete: `False`",
        "",
        "## Targets",
        "",
        "| Target | Target aa | Binder aa | A3M records |",
        "|---|---:|---:|---:|",
    ]
    for row in manifest["targets"]:
        lines.append(
            f"| `{row['target_id']}` | {row['target_sequence_length']} | "
            f"{row['binder_sequence_length']} | {row['a3m_records']} |"
        )
    lines.extend(["", f"Next action: {manifest['next_action']}", ""])
    return "\n".join(lines)


def render_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B2 Native-Recoverability Report",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Stage pass: `{report['stage_pass']}`.",
        f"Targets passing: `{report['targets_passing']}` / `8`.",
        "",
        str(report["claim_boundary"]),
        "",
        f"Next action: {report['next_action']}",
        "",
    ]
    return "\n".join(lines)


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, destination)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", default="configs/m6d_w3c_validity_first_protocol.json"
    )
    parser.add_argument(
        "--b1-manifest", default="configs/m6d_w3c_b1_target_msa_manifest.json"
    )
    parser.add_argument(
        "--b1-completion",
        default="results/m6d_w3c_b1_target_msa_completion.json",
    )
    parser.add_argument(
        "--w3b-runtime-lock", default="configs/m6d_w3b_runtime_lock.json"
    )
    parser.add_argument(
        "--w3b-protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json"
    )
    parser.add_argument(
        "--out-manifest", default="configs/m6d_w3c_b2_native_screen_manifest.json"
    )
    parser.add_argument(
        "--out-manifest-md",
        default="results/m6d_w3c_b2_native_screen_manifest.md",
    )
    parser.add_argument("--records", default=None)
    parser.add_argument("--runtime-lock", default=None)
    parser.add_argument(
        "--out-report", default="results/m6d_w3c_b2_native_recoverability_report.json"
    )
    parser.add_argument(
        "--out-report-md",
        default="results/m6d_w3c_b2_native_recoverability_report.md",
    )
    args = parser.parse_args(argv)
    manifest = build_native_manifest(
        _load_object(args.protocol),
        _load_object(args.b1_manifest),
        _load_object(args.b1_completion),
        _load_object(args.w3b_runtime_lock),
        protocol_path=args.protocol,
        b1_manifest_path=args.b1_manifest,
        b1_completion_path=args.b1_completion,
        w3b_runtime_lock_path=args.w3b_runtime_lock,
        w3b_protocol_path=args.w3b_protocol,
    )
    _write_json(args.out_manifest, manifest)
    Path(args.out_manifest_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_manifest_md).write_text(render_manifest_markdown(manifest))
    if args.records or args.runtime_lock:
        if not args.records or not args.runtime_lock:
            raise ValueError("--records and --runtime-lock are required together")
        runtime_lock = _load_object(args.runtime_lock)
        report = evaluate_records(
            manifest,
            runtime_lock,
            _load_jsonl(args.records),
            manifest_sha256=_sha256_file(args.out_manifest),
            runtime_lock_sha256=_sha256_file(args.runtime_lock),
        )
        _write_json(args.out_report, report)
        Path(args.out_report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_report_md).write_text(render_report_markdown(report))
        print(
            f"status={report['status']} audit_ok={report['audit_ok']} "
            f"targets_passing={report['targets_passing']}"
        )
        return 0 if report["audit_ok"] else 2
    print(
        f"status={manifest['status']} targets={manifest['target_count']} "
        "predictor_evaluations_authorized=0 no_submit=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
