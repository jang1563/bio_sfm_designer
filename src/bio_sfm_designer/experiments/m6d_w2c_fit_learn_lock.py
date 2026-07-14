"""Build and verify the W2c threshold-learning manifest and immutable input lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional

from .complex_target_manifest import validate_manifest


_STAGE = "threshold_learning"
_OUTPUT_ROOT = "hpc_outputs/m6d_w2c_fit_learn_records"
_ARTIFACT_FIELDS = (
    "source_pdb",
    "prepared_pdb",
    "prep_report",
    "target_fasta",
    "target_fasta_report",
    "target_msa",
    "target_msa_report",
)
_REPORT_FIELDS = {"prep_report", "target_fasta_report", "target_msa_report"}


def _load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def deterministic_seed(namespace: str, target_id: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{target_id}".encode("utf-8")).digest()
    seed = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
    return seed or 1


def _protocol_contract(protocol: Dict[str, Any]) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    execution = protocol.get("execution_state")
    if not isinstance(locked, dict) or not isinstance(execution, dict):
        raise ValueError("W2c protocol is missing locked scientific or execution state")
    learning = locked.get("fit_design", {}).get("threshold_learning")
    target_ids = execution.get("target_ids")
    if not isinstance(learning, dict) or not isinstance(target_ids, list):
        raise ValueError("W2c protocol is missing threshold-learning or target-id state")
    target_ids = [str(value) for value in target_ids]
    if len(target_ids) != 8 or len(set(target_ids)) != 8:
        raise ValueError("W2c threshold learning requires exactly eight unique targets")
    records_per_target = learning.get("records_per_target")
    namespace = learning.get("seed_namespace")
    if records_per_target != 60 or namespace != "w2c-fit-learn-v1":
        raise ValueError("W2c threshold-learning scope does not match the locked 8 x 60 contract")
    return {
        "locked": locked,
        "execution": execution,
        "target_ids": target_ids,
        "records_per_target": int(records_per_target),
        "namespace": str(namespace),
    }


def _completion_targets(completion: Dict[str, Any], expected_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    rows = completion.get("targets")
    expected = list(expected_ids)
    if not (
        completion.get("status") == "target_msa_precompute_complete_8_of_8"
        and completion.get("audit_ok") is True
        and completion.get("n_targets") == 8
        and completion.get("n_target_msas") == 8
        and completion.get("n_target_msa_reports") == 8
        and completion.get("strict_manifest_ready_targets") == 8
        and completion.get("within_approved_gpu_hour_ceiling") is True
        and isinstance(rows, list)
        and len(rows) == 8
    ):
        raise ValueError("W2c target-MSA completion is not a valid 8/8 completion artifact")
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("W2c target-MSA completion contains a non-object target row")
        target_id = str(row.get("target_id") or "")
        if (
            not target_id
            or target_id in by_id
            or row.get("report_ok") is not True
            or not _is_sha256(row.get("target_msa_sha256"))
            or not _is_sha256(row.get("target_msa_report_sha256"))
        ):
            raise ValueError(f"invalid W2c target-MSA completion row: {target_id or '<missing>'}")
        by_id[target_id] = row
    if sorted(by_id) != sorted(expected):
        raise ValueError("W2c target-MSA completion targets do not match the protocol")
    return by_id


def build_stage_manifest(
    protocol_path: str,
    source_manifest_path: str,
    completion_path: str,
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    source = _load_object(source_manifest_path)
    completion = _load_object(completion_path)
    contract = _protocol_contract(protocol)
    expected_ids = contract["target_ids"]
    completion_by_id = _completion_targets(completion, expected_ids)
    execution = contract["execution"]
    source_sha256 = _sha256_file(source_manifest_path)
    if source_sha256 != execution.get("target_manifest_sha256"):
        raise ValueError("W2c source target manifest hash does not match the locked protocol")
    source_rows = source.get("targets")
    if not isinstance(source_rows, list):
        raise ValueError("W2c source target manifest is missing target rows")
    source_by_id = {
        str(row.get("id") or ""): row
        for row in source_rows
        if isinstance(row, dict) and row.get("id")
    }
    if list(source_by_id) != expected_ids:
        raise ValueError("W2c source target order does not match the locked protocol")
    defaults = source.get("defaults") if isinstance(source.get("defaults"), dict) else {}
    namespace = contract["namespace"]
    records_per_target = contract["records_per_target"]
    targets = []
    for target_id in expected_ids:
        source_target = source_by_id[target_id]
        completion_target = completion_by_id[target_id]
        out_prefix = f"{_OUTPUT_ROOT}/{target_id}"
        target = {
            key: source_target[key]
            for key in (
                "id",
                "rcsb_id",
                "source_pdb",
                "prepared_pdb",
                "prep_report",
                "target_chain",
                "binder_chain",
                "target_fasta",
                "target_fasta_report",
                "target_msa",
                "target_msa_report",
                "target_sequence_sha256",
                "selection_input_origin",
            )
        }
        target.update({
            "w2c_stage": _STAGE,
            "w2c_seed_namespace": namespace,
            "id_prefix": f"{namespace}-{target_id}",
            "num_seq": records_per_target,
            "seed": deterministic_seed(namespace, target_id),
            "temp": float(defaults.get("temp", 0.3)),
            "objective": str(defaults.get("objective", "binder")),
            "out_prefix": out_prefix,
            "candidates": f"{out_prefix}/candidates_proteinmpnn_complex.jsonl",
            "records": f"{out_prefix}/records_boltz_complex.jsonl",
            "target_msa_sha256": completion_target["target_msa_sha256"],
            "target_msa_report_sha256": completion_target["target_msa_report_sha256"],
        })
        targets.append(target)
    return {
        "artifact": "m6d_w2c_fit_learn_target_manifest",
        "version": 1,
        "status": "w2c_fit_learn_packet_no_submit",
        "cayuga_submission_allowed": False,
        "protocol": protocol_path,
        "protocol_sha256": _sha256_file(protocol_path),
        "source_manifest": source_manifest_path,
        "source_manifest_sha256": source_sha256,
        "target_msa_completion": completion_path,
        "target_msa_completion_sha256": _sha256_file(completion_path),
        "locked_scientific_digest": source.get("locked_scientific_digest"),
        "w2c_stage": _STAGE,
        "w2c_seed_namespace": namespace,
        "output_root": _OUTPUT_ROOT,
        "defaults": {
            "num_seq": records_per_target,
            "temp": float(defaults.get("temp", 0.3)),
            "objective": str(defaults.get("objective", "binder")),
        },
        "target_ids": expected_ids,
        "records_per_target": records_per_target,
        "total_records": len(expected_ids) * records_per_target,
        "targets": targets,
        "claim_boundary": (
            "Threshold-learning execution inputs only. This manifest authorizes no jobs and supports "
            "no W2c certificate or claim."
        ),
    }


def _canonical_report_binding(field: str, path: str, target: Dict[str, Any]) -> Dict[str, Any]:
    report = _load_object(path)
    for key in list(report):
        if key.endswith("_abs") or key in {"work_dir", "source_msa", "command"}:
            report.pop(key, None)
    if field == "prep_report":
        report["source_pdb"] = target.get("source_pdb")
        report["output_pdb"] = target.get("prepared_pdb")
    elif field == "target_fasta_report":
        for key in ("first_residue", "last_residue", "unknown_allowed"):
            report.pop(key, None)
        report["pdb"] = target.get("prepared_pdb")
        report["out"] = target.get("target_fasta")
    elif field == "target_msa_report":
        report["fasta"] = target.get("target_fasta")
        report["out"] = target.get("target_msa")
    return {
        "path": path,
        "hash_mode": "canonical_report_json_v1",
        "sha256": _canonical_sha256(report),
    }


def build_lock(
    protocol_path: str,
    source_manifest_path: str,
    completion_path: str,
    stage_manifest_path: str,
) -> Dict[str, Any]:
    expected_manifest = build_stage_manifest(protocol_path, source_manifest_path, completion_path)
    manifest = _load_object(stage_manifest_path)
    completion = _load_object(completion_path)
    contract = _protocol_contract(_load_object(protocol_path))
    completion_by_id = _completion_targets(completion, contract["target_ids"])
    failures = []
    if manifest != expected_manifest:
        failures.append({"kind": "stage_manifest_content_mismatch"})
    strict = validate_manifest(
        stage_manifest_path,
        require_files=True,
        min_targets=8,
        min_contacts=1,
    )
    if not strict.get("ok"):
        failures.extend(strict.get("failures") or [{"kind": "strict_manifest_failed"}])
    source = _load_object(source_manifest_path)
    source_by_id = {
        str(row.get("id") or ""): row
        for row in source.get("targets", [])
        if isinstance(row, dict) and row.get("id")
    }
    rows = manifest.get("targets") if isinstance(manifest.get("targets"), list) else []
    target_ids = [str(row.get("id") or "") for row in rows if isinstance(row, dict)]
    if target_ids != contract["target_ids"]:
        failures.append({
            "kind": "stage_target_ids_mismatch",
            "expected": contract["target_ids"],
            "actual": target_ids,
        })
    locked_targets = []
    for target in rows:
        if not isinstance(target, dict):
            failures.append({"kind": "non_object_target_row"})
            continue
        target_id = str(target.get("id") or "")
        source_target = source_by_id.get(target_id, {})
        completion_target = completion_by_id.get(target_id, {})
        expected_prefix = f"{contract['namespace']}-{target_id}"
        expected_out_prefix = f"{_OUTPUT_ROOT}/{target_id}"
        expected_outputs = {
            "out_prefix": expected_out_prefix,
            "candidates": f"{expected_out_prefix}/candidates_proteinmpnn_complex.jsonl",
            "records": f"{expected_out_prefix}/records_boltz_complex.jsonl",
        }
        actual_outputs = {key: target.get(key) for key in expected_outputs}
        if actual_outputs != expected_outputs:
            failures.append({
                "kind": "stage_output_path_mismatch",
                "target_id": target_id,
                "expected": expected_outputs,
                "actual": actual_outputs,
            })
        source_out_prefix = str(source_target.get("out_prefix") or "")
        source_records = str(source_target.get("records") or "")
        if (
            any(source_out_prefix and str(value).startswith(source_out_prefix) for value in actual_outputs.values())
            or source_records in actual_outputs.values()
        ):
            failures.append({"kind": "historical_output_path_collision", "target_id": target_id})
        expected_seed = deterministic_seed(contract["namespace"], target_id)
        if (
            target.get("w2c_stage") != _STAGE
            or target.get("w2c_seed_namespace") != contract["namespace"]
            or target.get("id_prefix") != expected_prefix
            or target.get("num_seq") != contract["records_per_target"]
            or target.get("seed") != expected_seed
        ):
            failures.append({"kind": "stage_execution_metadata_mismatch", "target_id": target_id})
        artifacts: Dict[str, Dict[str, Any]] = {}
        for field in _ARTIFACT_FIELDS:
            path = target.get(field)
            if not isinstance(path, str) or not path:
                failures.append({"kind": "missing_lock_artifact", "target_id": target_id, "field": field})
                continue
            if path != source_target.get(field):
                failures.append({"kind": "source_artifact_path_mismatch", "target_id": target_id, "field": field})
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                failures.append({
                    "kind": "missing_or_empty_lock_artifact",
                    "target_id": target_id,
                    "field": field,
                    "path": path,
                })
                continue
            raw_sha256 = _sha256_file(path)
            if field == "target_msa" and raw_sha256 != completion_target.get("target_msa_sha256"):
                failures.append({"kind": "target_msa_sha256_mismatch", "target_id": target_id})
            if (
                field == "target_msa_report"
                and raw_sha256 != completion_target.get("target_msa_report_sha256")
            ):
                failures.append({"kind": "target_msa_report_sha256_mismatch", "target_id": target_id})
            if field in _REPORT_FIELDS:
                artifacts[field] = _canonical_report_binding(field, path, target)
            else:
                artifacts[field] = {
                    "path": path,
                    "hash_mode": "raw_bytes_sha256",
                    "bytes": os.path.getsize(path),
                    "sha256": raw_sha256,
                }
        locked_targets.append({
            "target_id": target_id,
            "stage": _STAGE,
            "seed_namespace": contract["namespace"],
            "proteinmpnn_seed": expected_seed,
            "records_planned": contract["records_per_target"],
            "id_prefix": expected_prefix,
            "outputs": expected_outputs,
            "artifacts": artifacts,
        })
    binding = {
        "protocol_file_sha256": _sha256_file(protocol_path),
        "source_manifest_sha256": _sha256_file(source_manifest_path),
        "target_msa_completion_sha256": _sha256_file(completion_path),
        "stage_manifest_sha256": _sha256_file(stage_manifest_path),
        "stage": _STAGE,
        "seed_namespace": contract["namespace"],
        "records_per_target": contract["records_per_target"],
        "total_records": 8 * contract["records_per_target"],
        "targets": locked_targets,
    }
    return {
        "artifact": "m6d_w2c_fit_learn_input_lock",
        "version": 1,
        "status": "w2c_fit_learn_input_locked" if not failures else "w2c_fit_learn_input_lock_blocked",
        "audit_ok": not failures,
        "claim_boundary": (
            "Input and execution-provenance lock only. This does not authorize Cayuga jobs or support "
            "a W2c scientific claim."
        ),
        "protocol": protocol_path,
        "source_manifest": source_manifest_path,
        "target_msa_completion": completion_path,
        "stage_manifest": stage_manifest_path,
        "n_targets": len(locked_targets),
        "n_artifacts": sum(len(row["artifacts"]) for row in locked_targets),
        "lock_digest_sha256": _canonical_sha256(binding),
        "binding": binding,
        "failures": failures,
    }


def verify_lock(
    lock_path: str,
    protocol_path: str,
    source_manifest_path: str,
    completion_path: str,
    stage_manifest_path: str,
) -> Dict[str, Any]:
    expected = _load_object(lock_path)
    current = build_lock(protocol_path, source_manifest_path, completion_path, stage_manifest_path)
    digest_matches = expected.get("lock_digest_sha256") == current.get("lock_digest_sha256")
    verified = bool(expected.get("audit_ok") and current.get("audit_ok") and digest_matches)
    return {
        "artifact": "m6d_w2c_fit_learn_input_lock_verification",
        "status": "w2c_fit_learn_input_lock_verified" if verified else "w2c_fit_learn_input_lock_verification_failed",
        "verified": verified,
        "lock": lock_path,
        "expected_lock_digest_sha256": expected.get("lock_digest_sha256"),
        "actual_lock_digest_sha256": current.get("lock_digest_sha256"),
        "current_failures": current.get("failures") or [],
    }


def _write(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w2c_one_shot_protocol.json")
    parser.add_argument("--source-manifest", default="configs/m6d_w2c_fresh_targets.json")
    parser.add_argument("--completion", default="results/m6d_w2c_target_msa_completion.json")
    parser.add_argument("--stage-manifest", default="configs/m6d_w2c_fit_learn_targets.json")
    parser.add_argument("--emit-stage-manifest", action="store_true")
    parser.add_argument("--verify-lock", default=None)
    parser.add_argument("--out-lock", default=None)
    args = parser.parse_args(argv)
    if args.emit_stage_manifest:
        _write(
            args.stage_manifest,
            build_stage_manifest(args.protocol, args.source_manifest, args.completion),
        )
    report = (
        verify_lock(
            args.verify_lock,
            args.protocol,
            args.source_manifest,
            args.completion,
            args.stage_manifest,
        )
        if args.verify_lock
        else build_lock(
            args.protocol,
            args.source_manifest,
            args.completion,
            args.stage_manifest,
        )
    )
    if args.out_lock:
        _write(args.out_lock, report)
    print(f"status={report['status']} ok={report.get('verified', report.get('audit_ok', False))}")
    return 0 if report.get("verified", report.get("audit_ok", False)) else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
