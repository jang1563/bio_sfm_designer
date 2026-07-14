"""Assemble strict W3b matched-predictor records from provenance-bound raw outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    runtime_identity as locked_runtime_identity,
    validate_runtime_lock,
)


_PREDICTORS = ("boltz2_complex", "af2_multimer_colabfold_v1")
_ROLES = ("fit", "certification", "held_out_test")
_RECEIPT_NAMES = {
    "boltz2_complex": "boltz2_runtime_receipt.json",
    "af2_multimer_colabfold_v1": "af2_multimer_runtime_receipt.json",
}
_SOURCES = {
    "boltz2_complex": ("boltz2_pae_interaction", "boltz2_lrmsd_to_reference"),
    "af2_multimer_colabfold_v1": (
        "af2_multimer_pae_interaction",
        "af2_multimer_lrmsd_to_reference",
    ),
}
_RECORD_PATH_FIELDS = {
    "boltz2_complex": "boltz_records",
    "af2_multimer_colabfold_v1": "af2_records",
}
_COPY_TOLERANCE = 1e-6
_COPY_FRACTION = 0.95


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


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sequence_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _file_binding(path: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(path, str) or not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return None
    return {"path": path, "bytes": os.path.getsize(path), "sha256": _sha256_file(path)}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _valid_sequence(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.upper()
        and all(character in "ACDEFGHIKLMNPQRSTVWYX" for character in value)
    )


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    row: Dict[str, Any] = {"kind": kind}
    row.update(context)
    failures.append(row)


def _stage_contract(protocol: Dict[str, Any], stage: str) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict) or stage not in _ROLES:
        raise ValueError("invalid W3b protocol or stage")
    key = {
        "fit": "fit_design",
        "certification": "certification_design",
        "held_out_test": "held_out_test_design",
    }[stage]
    contract = locked.get(key)
    if not isinstance(contract, dict):
        raise ValueError(f"W3b protocol is missing {key}")
    return contract


def _validate_execution_contract(
    protocol_path: str,
    manifest_path: str,
    lock_path: str,
    protocol: Dict[str, Any],
    manifest: Dict[str, Any],
    lock: Dict[str, Any],
    failures: List[Dict[str, Any]],
) -> None:
    protocol_sha256 = _sha256_file(protocol_path)
    manifest_sha256 = _sha256_file(manifest_path)
    scientific_digest = _canonical_sha256(protocol.get("locked_scientific_protocol"))
    if not (
        manifest.get("artifact") == "m6d_w3b_execution_target_manifest"
        and manifest.get("status") == "w3b_execution_inputs_locked_no_submit"
        and manifest.get("no_submit") is True
        and manifest.get("cayuga_submission_allowed") is False
        and manifest.get("protocol_sha256") == protocol_sha256
        and manifest.get("locked_scientific_digest") == scientific_digest
    ):
        _failure(failures, "execution_manifest_contract_invalid")
    binding = lock.get("binding") if isinstance(lock.get("binding"), dict) else {}
    if not (
        lock.get("artifact") == "m6d_w3b_execution_input_lock"
        and lock.get("status") == "w3b_execution_input_locked_no_submit"
        and lock.get("audit_ok") is True
        and lock.get("no_submit") is True
        and lock.get("can_generate_candidates_or_run_predictors") is False
        and binding.get("protocol_file_sha256") == protocol_sha256
        and binding.get("execution_manifest_sha256") == manifest_sha256
        and binding.get("locked_scientific_digest") == scientific_digest
    ):
        _failure(failures, "execution_input_lock_contract_invalid", lock=lock_path)


def _receipt_path(target: Dict[str, Any], predictor_id: str) -> str:
    return os.path.join(str(target["out_prefix"]), _RECEIPT_NAMES[predictor_id])


def build_runtime_receipt(
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
    predictor_id: str,
    target_id: str,
    observed_runtime_identity: Dict[str, Any],
) -> Dict[str, Any]:
    if predictor_id not in _PREDICTORS:
        raise ValueError(f"unsupported W3b predictor: {predictor_id}")
    protocol = _load_object(protocol_path)
    manifest = _load_object(execution_manifest_path)
    lock = _load_object(input_lock_path)
    runtime_lock = _load_object(runtime_lock_path)
    failures: List[Dict[str, Any]] = []
    _validate_execution_contract(
        protocol_path,
        execution_manifest_path,
        input_lock_path,
        protocol,
        manifest,
        lock,
        failures,
    )
    runtime_failures = validate_runtime_lock(runtime_lock, protocol_path)
    if runtime_failures:
        raise ValueError(f"W3b runtime lock is invalid: {runtime_failures[0]['kind']}")
    targets = {
        str(row.get("id") or ""): row
        for row in manifest.get("targets", [])
        if isinstance(row, dict)
    }
    target = targets.get(target_id)
    if not isinstance(target, dict):
        raise ValueError(f"target is absent from W3b execution manifest: {target_id}")
    runtime_identity = locked_runtime_identity(runtime_lock, predictor_id, protocol_path)
    if observed_runtime_identity != runtime_identity:
        raise ValueError(f"observed runtime identity differs from the frozen {predictor_id} identity")
    candidates_path = str(target["candidates"])
    target_msa_path = str(target["target_msa"])
    records_path = str(target[_RECORD_PATH_FIELDS[predictor_id]])
    for path in (candidates_path, target_msa_path, records_path):
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            raise ValueError(f"runtime receipt input is missing or empty: {path}")
    if _sha256_file(target_msa_path) != target.get("target_msa_sha256"):
        raise ValueError("runtime receipt target MSA differs from the execution lock")
    candidates = _load_jsonl(candidates_path)
    records = _load_jsonl(records_path)
    candidate_ids = [str(row.get("id") or "") for row in candidates]
    record_ids = [str(row.get("target_id") or "") for row in records]
    expected_count = int(target["num_seq"])
    if (
        failures
        or len(candidates) != expected_count
        or len(records) != expected_count
        or len(set(candidate_ids)) != expected_count
        or len(set(record_ids)) != expected_count
        or set(candidate_ids) != set(record_ids)
        or any(not value for value in candidate_ids + record_ids)
    ):
        raise ValueError("runtime receipt candidate/record set does not satisfy the frozen target scope")
    return {
        "artifact": "m6d_w3b_predictor_runtime_receipt",
        "status": "w3b_predictor_records_complete",
        "audit_ok": True,
        "no_submit": True,
        "predictor_id": predictor_id,
        "target_id": target_id,
        "experimental_role": target["experimental_role"],
        "seed_namespace": target["w3b_seed_namespace"],
        "seed": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
        "candidates": candidates_path,
        "candidates_sha256": _sha256_file(candidates_path),
        "target_msa": target_msa_path,
        "target_msa_sha256": target["target_msa_sha256"],
        "records": records_path,
        "records_sha256": _sha256_file(records_path),
        "n_records": expected_count,
        "runtime_lock": runtime_lock_path,
        "runtime_lock_sha256": _sha256_file(runtime_lock_path),
        "runtime_lock_digest_sha256": runtime_lock["runtime_lock_digest_sha256"],
        "runtime_identity": runtime_identity,
        "runtime_identity_sha256": _canonical_sha256(runtime_identity),
        "claim_boundary": (
            "Runtime provenance only. This receipt records completed predictor outputs and does not "
            "authorize jobs, certify a gate, or support a W3b claim."
        ),
    }


def _validate_receipt(
    receipt: Dict[str, Any],
    *,
    receipt_path: str,
    predictor_id: str,
    protocol_path: str,
    runtime_lock_path: str,
    runtime_lock: Dict[str, Any],
    target: Dict[str, Any],
    candidates_path: str,
    records_path: str,
    expected_count: int,
    failures: List[Dict[str, Any]],
) -> Optional[str]:
    target_id = str(target["id"])
    runtime = receipt.get("runtime_identity")
    runtime_digest = receipt.get("runtime_identity_sha256")
    expected_runtime = locked_runtime_identity(runtime_lock, predictor_id, protocol_path)
    expected_runtime_digest = runtime_lock["predictor_runtime_identity_sha256"][predictor_id]
    runtime_ok = (
        runtime == expected_runtime
        and runtime_digest == expected_runtime_digest
        and runtime_digest == _canonical_sha256(runtime)
    )
    expected = {
        "artifact": "m6d_w3b_predictor_runtime_receipt",
        "status": "w3b_predictor_records_complete",
        "audit_ok": True,
        "no_submit": True,
        "predictor_id": predictor_id,
        "target_id": target_id,
        "experimental_role": target["experimental_role"],
        "seed_namespace": target["w3b_seed_namespace"],
        "seed": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
        "candidates": candidates_path,
        "candidates_sha256": _sha256_file(candidates_path),
        "target_msa": target["target_msa"],
        "target_msa_sha256": target["target_msa_sha256"],
        "records": records_path,
        "records_sha256": _sha256_file(records_path),
        "n_records": expected_count,
        "runtime_lock": runtime_lock_path,
        "runtime_lock_sha256": _sha256_file(runtime_lock_path),
        "runtime_lock_digest_sha256": runtime_lock["runtime_lock_digest_sha256"],
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatches or not runtime_ok or not _is_sha256(runtime_digest):
        _failure(
            failures,
            "predictor_runtime_receipt_invalid",
            target_id=target_id,
            predictor_id=predictor_id,
            receipt=receipt_path,
            mismatches=mismatches,
            runtime_identity_ok=bool(runtime_ok),
            expected_runtime_identity_sha256=expected_runtime_digest,
            observed_runtime_identity_sha256=runtime_digest,
        )
        return None
    return str(runtime_digest)


def _indexed(rows: List[Dict[str, Any]], field: str, *, kind: str, failures: List[Dict[str, Any]], target_id: str) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(field) or "")
        if not value or value in indexed:
            _failure(failures, kind, target_id=target_id, value=value)
            continue
        indexed[value] = row
    return indexed


def _provenance_hash(provenance: Dict[str, Any], primary: str, alias: str) -> Any:
    return provenance.get(primary) if provenance.get(primary) is not None else provenance.get(alias)


def _validate_raw_record(
    record: Dict[str, Any],
    *,
    candidate: Dict[str, Any],
    predictor_id: str,
    target: Dict[str, Any],
    runtime_digest: Optional[str],
    failures: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidate_id = str(candidate["id"])
    target_id = str(target["id"])
    sequence = str(candidate["representation"])
    candidate_sha256 = _sequence_sha256(sequence)
    target_sequence_sha256 = _sequence_sha256(str(candidate["target_seq"]))
    provenance = record.get("provenance")
    pae = _as_float(record.get("pae_interaction"))
    lrmsd = _as_float(record.get("lrmsd"))
    threshold = _as_float(record.get("lrmsd_threshold"))
    truth = record.get("truth") if isinstance(record.get("truth"), dict) else {}
    label = truth.get("correct")
    signal_source, label_source = _SOURCES[predictor_id]
    provenance_ok = isinstance(provenance, dict)
    if provenance_ok:
        observed_candidate_hash = _provenance_hash(
            provenance,
            "candidate_sequence_sha256",
            "binder_sequence_sha256",
        )
        observed_msa_hash = _provenance_hash(provenance, "target_msa_sha256", "a3m_sha256")
        model_output_hash = _provenance_hash(provenance, "model_output_sha256", "model_pdb_sha256")
        provenance_ok = (
            observed_candidate_hash == candidate_sha256
            and observed_msa_hash == target["target_msa_sha256"]
            and provenance.get("target_sequence_sha256") == target_sequence_sha256
            and provenance.get("runtime_identity_sha256") == runtime_digest
            and provenance.get("seed") == 0
            and provenance.get("templates_used") is False
            and provenance.get("prediction_time_network_used") is False
            and _is_sha256(model_output_hash)
        )
    record_ok = (
        record.get("target_id") == candidate_id
        and record.get("complex_target_id") == target_id
        and record.get("predictor_id") == predictor_id
        and record.get("regime") == "complex"
        and record.get("signal_source") == signal_source
        and record.get("label_source") == label_source
        and record.get("interface_aligned") is True
        and pae is not None
        and pae >= 0.0
        and lrmsd is not None
        and lrmsd >= 0.0
        and threshold is not None
        and math.isclose(threshold, 4.0, abs_tol=1e-12)
        and isinstance(label, bool)
        and label is (lrmsd < threshold)
        and provenance_ok
    )
    if not record_ok:
        _failure(
            failures,
            "predictor_record_contract_invalid",
            target_id=target_id,
            candidate_id=candidate_id,
            predictor_id=predictor_id,
            provenance_ok=bool(provenance_ok),
        )
        return None
    return {
        "candidate_sequence_sha256": candidate_sha256,
        "label": label,
        "label_threshold": threshold,
        "lrmsd": lrmsd,
        "pae_interaction": pae,
        "seed": 0,
        "target_msa_sha256": target["target_msa_sha256"],
        "templates_used": False,
    }


def _assemble_target(
    target: Dict[str, Any],
    *,
    protocol_path: str,
    runtime_lock_path: str,
    runtime_lock: Dict[str, Any],
    expected_count: int,
    failures: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    target_id = str(target["id"])
    candidates_path = str(target["candidates"])
    target_msa_path = str(target["target_msa"])
    paths = {
        predictor_id: str(target[_RECORD_PATH_FIELDS[predictor_id]])
        for predictor_id in _PREDICTORS
    }
    required_paths = [
        target_msa_path,
        candidates_path,
        *paths.values(),
        *(_receipt_path(target, value) for value in _PREDICTORS),
    ]
    missing = [path for path in required_paths if not os.path.isfile(path) or os.path.getsize(path) <= 0]
    if missing:
        _failure(failures, "target_input_file_missing", target_id=target_id, paths=missing)
        return [], {"target_id": target_id, "missing_paths": missing}
    if _sha256_file(target_msa_path) != target.get("target_msa_sha256"):
        _failure(failures, "target_msa_file_hash_mismatch", target_id=target_id, path=target_msa_path)
    candidates = _load_jsonl(candidates_path)
    predictor_rows = {predictor_id: _load_jsonl(path) for predictor_id, path in paths.items()}
    if len(candidates) != expected_count:
        _failure(failures, "candidate_count_mismatch", target_id=target_id, expected=expected_count, observed=len(candidates))
    for predictor_id, rows in predictor_rows.items():
        if len(rows) != expected_count:
            _failure(
                failures,
                "predictor_record_count_mismatch",
                target_id=target_id,
                predictor_id=predictor_id,
                expected=expected_count,
                observed=len(rows),
            )
    candidate_by_id = _indexed(
        candidates,
        "id",
        kind="candidate_id_invalid_or_duplicate",
        failures=failures,
        target_id=target_id,
    )
    records_by_predictor = {
        predictor_id: _indexed(
            rows,
            "target_id",
            kind="predictor_candidate_id_invalid_or_duplicate",
            failures=failures,
            target_id=target_id,
        )
        for predictor_id, rows in predictor_rows.items()
    }
    expected_ids = set(candidate_by_id)
    for predictor_id, indexed in records_by_predictor.items():
        if set(indexed) != expected_ids:
            _failure(
                failures,
                "predictor_candidate_set_mismatch",
                target_id=target_id,
                predictor_id=predictor_id,
                missing=sorted(expected_ids - set(indexed)),
                unexpected=sorted(set(indexed) - expected_ids),
            )
    runtime_digests: Dict[str, Optional[str]] = {}
    receipt_bindings: Dict[str, Dict[str, Any]] = {}
    for predictor_id in _PREDICTORS:
        receipt_path = _receipt_path(target, predictor_id)
        receipt = _load_object(receipt_path)
        runtime_digests[predictor_id] = _validate_receipt(
            receipt,
            receipt_path=receipt_path,
            predictor_id=predictor_id,
            protocol_path=protocol_path,
            runtime_lock_path=runtime_lock_path,
            runtime_lock=runtime_lock,
            target=target,
            candidates_path=candidates_path,
            records_path=paths[predictor_id],
            expected_count=expected_count,
            failures=failures,
        )
        receipt_bindings[predictor_id] = {"path": receipt_path, "sha256": _sha256_file(receipt_path)}

    matched: List[Dict[str, Any]] = []
    prefix = f"{target['id_prefix']}-"
    for candidate_id in sorted(expected_ids):
        candidate = candidate_by_id[candidate_id]
        meta = candidate.get("meta") if isinstance(candidate.get("meta"), dict) else {}
        candidate_ok = (
            candidate_id.startswith(prefix)
            and candidate.get("regime") == "complex"
            and _valid_sequence(candidate.get("representation"))
            and _valid_sequence(candidate.get("target_seq"))
            and _sequence_sha256(str(candidate.get("target_seq"))) == target.get("target_sequence_sha256")
            and meta.get("complex_target_id") == target_id
        )
        if not candidate_ok:
            _failure(failures, "candidate_contract_invalid", target_id=target_id, candidate_id=candidate_id)
            continue
        predictors: Dict[str, Dict[str, Any]] = {}
        for predictor_id in _PREDICTORS:
            raw = records_by_predictor[predictor_id].get(candidate_id)
            if raw is None:
                continue
            prepared = _validate_raw_record(
                raw,
                candidate=candidate,
                predictor_id=predictor_id,
                target=target,
                runtime_digest=runtime_digests[predictor_id],
                failures=failures,
            )
            if prepared is not None:
                predictors[predictor_id] = prepared
        if set(predictors) != set(_PREDICTORS):
            continue
        matched.append({
            "candidate_id": candidate_id,
            "experimental_role": target["experimental_role"],
            "predictors": predictors,
            "seed_namespace": target["w3b_seed_namespace"],
            "target_id": target_id,
        })
    return matched, {
        "target_id": target_id,
        "expected_records": expected_count,
        "candidate_file": {"path": candidates_path, "sha256": _sha256_file(candidates_path)},
        "predictor_files": {
            predictor_id: {"path": path, "sha256": _sha256_file(path)}
            for predictor_id, path in paths.items()
        },
        "runtime_receipts": receipt_bindings,
        "n_matched_records": len(matched),
    }


def _numeric_copy_fraction(rows: List[Dict[str, Any]]) -> Optional[float]:
    if not rows:
        return None
    copied = 0
    for row in rows:
        boltz = row["predictors"]["boltz2_complex"]
        af2 = row["predictors"]["af2_multimer_colabfold_v1"]
        if (
            abs(float(boltz["pae_interaction"]) - float(af2["pae_interaction"])) <= _COPY_TOLERANCE
            and abs(float(boltz["lrmsd"]) - float(af2["lrmsd"])) <= _COPY_TOLERANCE
        ):
            copied += 1
    return copied / len(rows)


def assemble_stage(
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
    stage: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    protocol = _load_object(protocol_path)
    manifest = _load_object(execution_manifest_path)
    lock = _load_object(input_lock_path)
    runtime_lock = _load_object(runtime_lock_path)
    failures: List[Dict[str, Any]] = []
    _validate_execution_contract(
        protocol_path,
        execution_manifest_path,
        input_lock_path,
        protocol,
        manifest,
        lock,
        failures,
    )
    runtime_failures = validate_runtime_lock(runtime_lock, protocol_path)
    failures.extend(runtime_failures)
    contract = _stage_contract(protocol, stage)
    expected_per_target = int(contract["records_per_target"])
    targets = [
        row for row in manifest.get("targets", [])
        if isinstance(row, dict) and row.get("experimental_role") == stage
    ]
    locked_fresh = protocol["locked_scientific_protocol"]["fresh_target_contract"]
    expected_target_count = {
        "fit": int(locked_fresh["n_fit_targets"]),
        "certification": int(locked_fresh["n_certification_targets"]),
        "held_out_test": int(locked_fresh["n_held_out_test_targets"]),
    }[stage]
    if len(targets) != expected_target_count:
        _failure(
            failures,
            "stage_target_count_mismatch",
            stage=stage,
            expected=expected_target_count,
            observed=len(targets),
        )
    lock_targets = {
        str(row.get("target_id") or ""): row
        for row in lock.get("binding", {}).get("targets", [])
        if isinstance(row, dict)
    }
    matched: List[Dict[str, Any]] = []
    target_reports: List[Dict[str, Any]] = []
    for target in targets:
        target_id = str(target.get("id") or "")
        locked_target = lock_targets.get(target_id, {})
        current_msa_binding = _file_binding(target.get("target_msa"))
        if not (
            locked_target.get("target_msa_sha256") == target.get("target_msa_sha256")
            and current_msa_binding is not None
            and locked_target.get("artifacts", {}).get("target_msa") == current_msa_binding
            and current_msa_binding.get("sha256") == target.get("target_msa_sha256")
            and locked_target.get("outputs") == {
                key: target.get(key)
                for key in ("out_prefix", "candidates", "boltz_records", "af2_records", "matched_records")
            }
        ):
            _failure(failures, "target_execution_lock_mismatch", target_id=target_id)
        if runtime_failures:
            target_reports.append({
                "target_id": target_id,
                "expected_records": expected_per_target,
                "n_matched_records": 0,
                "blocked_by": "runtime_lock_invalid",
            })
            continue
        rows, target_report = _assemble_target(
            target,
            protocol_path=protocol_path,
            runtime_lock_path=runtime_lock_path,
            runtime_lock=runtime_lock,
            expected_count=expected_per_target,
            failures=failures,
        )
        matched.extend(rows)
        target_reports.append(target_report)
    expected_records = expected_target_count * expected_per_target
    counts = Counter(str(row["target_id"]) for row in matched)
    if len(matched) != expected_records or any(counts.get(str(target["id"]), 0) != expected_per_target for target in targets):
        _failure(
            failures,
            "matched_stage_record_count_mismatch",
            expected=expected_records,
            observed=len(matched),
        )
    copy_fraction = _numeric_copy_fraction(matched)
    if copy_fraction is not None and copy_fraction >= _COPY_FRACTION:
        _failure(
            failures,
            "predictor_numeric_copy_suspected",
            copy_fraction=copy_fraction,
            threshold=_COPY_FRACTION,
        )
    audit_ok = not failures
    return matched, {
        "artifact": "m6d_w3b_matched_record_assembly",
        "status": f"w3b_{stage}_matched_records_ready" if audit_ok else "w3b_matched_record_assembly_blocked",
        "audit_ok": audit_ok,
        "no_submit": True,
        "can_run_stage_evaluator": audit_ok,
        "can_claim_w3b": False,
        "stage": stage,
        "experimental_role": stage,
        "seed_namespace": contract["seed_namespace"],
        "protocol": protocol_path,
        "protocol_sha256": _sha256_file(protocol_path),
        "execution_manifest": execution_manifest_path,
        "execution_manifest_sha256": _sha256_file(execution_manifest_path),
        "input_lock": input_lock_path,
        "input_lock_sha256": _sha256_file(input_lock_path),
        "runtime_lock": runtime_lock_path,
        "runtime_lock_sha256": _sha256_file(runtime_lock_path),
        "runtime_lock_digest_sha256": runtime_lock.get("runtime_lock_digest_sha256"),
        "target_ids": [str(row["id"]) for row in targets],
        "records_per_target": expected_per_target,
        "expected_records": expected_records,
        "n_matched_records": len(matched),
        "matched_records_by_target": dict(sorted(counts.items())),
        "numeric_copy_fraction": copy_fraction,
        "numeric_copy_fraction_threshold": _COPY_FRACTION,
        "target_reports": target_reports,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Matched predictor input/QC evidence only. Assembly does not authorize compute, certify a gate, "
            "establish biological success, or support a W3b claim."
        ),
    }


def build_readiness(
    protocol_path: str,
    execution_readiness_path: str,
    runtime_readiness_path: str = "results/m6d_w3b_runtime_lock_readiness.json",
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    execution = _load_object(execution_readiness_path)
    runtime = _load_object(runtime_readiness_path)
    failures: List[Dict[str, Any]] = []
    for stage in _ROLES:
        _stage_contract(protocol, stage)
    if execution.get("audit_ok") is not True or execution.get("no_submit") is not True:
        _failure(failures, "execution_lock_readiness_invalid")
    if not (
        runtime.get("artifact") == "m6d_w3b_runtime_lock_readiness"
        and runtime.get("audit_ok") is True
        and runtime.get("runtime_identity_ready") is True
        and runtime.get("no_submit") is True
        and runtime.get("can_submit_fit_stage") is False
    ):
        _failure(failures, "runtime_lock_readiness_invalid")
    runtime_lock_path = runtime.get("runtime_lock")
    runtime_lock_current = False
    if isinstance(runtime_lock_path, str) and os.path.isfile(runtime_lock_path):
        current_lock = _load_object(runtime_lock_path)
        runtime_lock_current = (
            _sha256_file(runtime_lock_path) == runtime.get("runtime_lock_sha256")
            and current_lock.get("runtime_lock_digest_sha256") == runtime.get("runtime_lock_digest_sha256")
            and not validate_runtime_lock(current_lock, protocol_path)
        )
    if not runtime_lock_current:
        _failure(failures, "runtime_lock_readiness_binding_stale_or_invalid")
    execution_ready = execution.get("execution_lock_ready") is True
    runtime_ready = runtime.get("runtime_identity_ready") is True and runtime_lock_current
    ready = execution_ready and runtime_ready and not failures
    if failures:
        status = "w3b_matched_record_contract_blocked"
    elif ready:
        status = "w3b_matched_record_contract_ready_for_stage_inputs"
    else:
        status = "w3b_matched_record_contract_ready_awaiting_execution_lock"
    return {
        "artifact": "m6d_w3b_matched_record_contract",
        "status": status,
        "audit_ok": not failures,
        "assembly_ready": ready,
        "execution_lock_ready": execution_ready,
        "runtime_identity_ready": runtime_ready,
        "no_submit": True,
        "can_run_candidate_generation_or_prediction": False,
        "can_claim_w3b": False,
        "protocol": protocol_path,
        "protocol_sha256": _sha256_file(protocol_path),
        "execution_lock_readiness": execution_readiness_path,
        "execution_lock_readiness_sha256": _sha256_file(execution_readiness_path),
        "runtime_lock_readiness": runtime_readiness_path,
        "runtime_lock_readiness_sha256": _sha256_file(runtime_readiness_path),
        "runtime_lock": runtime.get("runtime_lock"),
        "runtime_lock_sha256": runtime.get("runtime_lock_sha256"),
        "runtime_lock_digest_sha256": runtime.get("runtime_lock_digest_sha256"),
        "required_predictors": list(_PREDICTORS),
        "required_runtime_receipt": {
            "seed": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
            "runtime_lock_sha256": "exact_file_sha256_required",
            "runtime_lock_digest_sha256": "exact_lock_digest_required",
            "runtime_identity_sha256": "canonical_sha256_required",
        },
        "required_record_provenance": [
            "candidate_sequence_sha256",
            "target_sequence_sha256",
            "target_msa_sha256",
            "runtime_identity_sha256",
            "model_output_sha256",
        ],
        "stage_records_per_target": {
            stage: int(_stage_contract(protocol, stage)["records_per_target"])
            for stage in _ROLES
        },
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Executable matched-record contract only. This artifact submits no work and supports no W3b claim."
        ),
        "next_action": (
            "prepare a separately approval-gated fit-stage runtime packet using the frozen execution lock"
            if ready else
            "complete the target-MSA lifecycle and materialize the frozen execution manifest/input lock"
            if runtime_ready else
            "repair the W3b runtime lock before any candidate or predictor stage"
        ),
    }


def render_readiness_markdown(report: Dict[str, Any]) -> str:
    return "\n".join([
        "# M6d W3b Matched-Record Contract",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Assembly ready: `{report['assembly_ready']}`.",
        f"Runtime identity ready: `{report['runtime_identity_ready']}`.",
        f"Execution lock ready: `{report['execution_lock_ready']}`.",
        f"No submit: `{report['no_submit']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- predictors: `{', '.join(report['required_predictors'])}`",
        f"- failures: `{report['n_failures']}`",
        "",
        f"Next action: {report['next_action']}.",
        "",
    ])


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--execution-readiness", default="results/m6d_w3b_execution_lock_readiness.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    parser.add_argument("--runtime-readiness", default="results/m6d_w3b_runtime_lock_readiness.json")
    parser.add_argument("--stage", choices=_ROLES, default=None)
    parser.add_argument("--out-records", default="results/m6d_w3b_matched_records.jsonl")
    parser.add_argument("--out-report", default="results/m6d_w3b_matched_record_assembly.json")
    parser.add_argument("--out-readiness", default="results/m6d_w3b_matched_record_contract.json")
    parser.add_argument("--out-readiness-md", default="results/m6d_w3b_matched_record_contract.md")
    parser.add_argument("--receipt-predictor", choices=_PREDICTORS, default=None)
    parser.add_argument("--receipt-target", default=None)
    parser.add_argument("--runtime-identity", default=None)
    parser.add_argument("--out-runtime-receipt", default=None)
    args = parser.parse_args(argv)
    if args.receipt_predictor is not None:
        if not args.receipt_target or not args.runtime_identity:
            parser.error("--receipt-predictor requires --receipt-target and --runtime-identity")
        runtime = _load_object(args.runtime_identity)
        receipt = build_runtime_receipt(
            args.protocol,
            args.execution_manifest,
            args.input_lock,
            args.runtime_lock,
            args.receipt_predictor,
            args.receipt_target,
            runtime,
        )
        manifest = _load_object(args.execution_manifest)
        target = next(row for row in manifest["targets"] if row.get("id") == args.receipt_target)
        out_receipt = args.out_runtime_receipt or _receipt_path(target, args.receipt_predictor)
        _write_json(out_receipt, receipt)
        print(
            f"status={receipt['status']} predictor={receipt['predictor_id']} "
            f"target={receipt['target_id']} no_submit=True"
        )
        return 0
    if args.stage is None:
        report = build_readiness(args.protocol, args.execution_readiness, args.runtime_readiness)
        _write_json(args.out_readiness, report)
        os.makedirs(os.path.dirname(args.out_readiness_md) or ".", exist_ok=True)
        with open(args.out_readiness_md, "w") as handle:
            handle.write(render_readiness_markdown(report))
        print(
            f"status={report['status']} audit_ok={report['audit_ok']} "
            f"assembly_ready={report['assembly_ready']} no_submit=True"
        )
        return 0 if report["audit_ok"] else 2
    records, report = assemble_stage(
        args.protocol,
        args.execution_manifest,
        args.input_lock,
        args.runtime_lock,
        args.stage,
    )
    _write_jsonl(args.out_records, records if report["audit_ok"] else [])
    report["output_records"] = args.out_records
    report["output_records_sha256"] = _sha256_file(args.out_records)
    _write_json(args.out_report, report)
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"records={report['n_matched_records']} no_submit=True"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
