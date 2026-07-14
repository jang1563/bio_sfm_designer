"""Validate W3b producer inputs and materialize matched AF2 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    canonical_sha256,
    validate_runtime_lock,
)


_STAGES = ("fit", "certification", "held_out_test")
_STAGE_DESIGNS = {
    "fit": "fit_design",
    "certification": "certification_design",
    "held_out_test": "held_out_test_design",
}
_SEQUENCE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYX]+$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_object(path: Union[str, os.PathLike]) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Union[str, os.PathLike]) -> List[Dict[str, Any]]:
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


def sha256_file(path: Union[str, os.PathLike]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _failure(failures: List[Dict[str, Any]], kind: str, **context: Any) -> None:
    failures.append({"kind": kind, **context})


def _stage_contract(protocol: Mapping[str, Any], stage: str) -> Mapping[str, Any]:
    if stage not in _STAGES:
        raise ValueError(f"unsupported W3b stage: {stage}")
    locked = protocol.get("locked_scientific_protocol")
    contract = locked.get(_STAGE_DESIGNS[stage]) if isinstance(locked, Mapping) else None
    if not isinstance(contract, Mapping):
        raise ValueError(f"W3b protocol is missing {_STAGE_DESIGNS[stage]}")
    return contract


def load_target_context(
    protocol_path: str,
    execution_manifest_path: str,
    input_lock_path: str,
    runtime_lock_path: str,
    target_id: str,
    stage: str,
    *,
    require_target_files: bool = True,
) -> Dict[str, Any]:
    """Return a target only after all W3b execution and runtime locks agree."""
    protocol = load_object(protocol_path)
    manifest = load_object(execution_manifest_path)
    input_lock = load_object(input_lock_path)
    runtime_lock = load_object(runtime_lock_path)
    failures: List[Dict[str, Any]] = []

    protocol_sha256 = sha256_file(protocol_path)
    manifest_sha256 = sha256_file(execution_manifest_path)
    scientific_digest = canonical_sha256(protocol.get("locked_scientific_protocol"))
    if not (
        protocol.get("artifact") == "m6d_w3b_disagreement_gate_protocol"
        and manifest.get("artifact") == "m6d_w3b_execution_target_manifest"
        and manifest.get("status") == "w3b_execution_inputs_locked_no_submit"
        and manifest.get("no_submit") is True
        and manifest.get("cayuga_submission_allowed") is False
        and manifest.get("protocol_sha256") == protocol_sha256
        and manifest.get("locked_scientific_digest") == scientific_digest
    ):
        _failure(failures, "execution_manifest_contract_invalid")

    binding = input_lock.get("binding") if isinstance(input_lock.get("binding"), dict) else {}
    if not (
        input_lock.get("artifact") == "m6d_w3b_execution_input_lock"
        and input_lock.get("status") == "w3b_execution_input_locked_no_submit"
        and input_lock.get("audit_ok") is True
        and input_lock.get("no_submit") is True
        and input_lock.get("can_generate_candidates_or_run_predictors") is False
        and binding.get("protocol_file_sha256") == protocol_sha256
        and binding.get("execution_manifest_sha256") == manifest_sha256
        and binding.get("locked_scientific_digest") == scientific_digest
    ):
        _failure(failures, "execution_input_lock_contract_invalid")

    runtime_failures = validate_runtime_lock(runtime_lock, protocol_path)
    failures.extend(runtime_failures)
    targets = {
        str(row.get("id") or ""): row
        for row in manifest.get("targets", [])
        if isinstance(row, dict)
    }
    target = targets.get(target_id)
    if not isinstance(target, dict):
        _failure(failures, "execution_target_missing", target_id=target_id)
        target = {}

    contract = _stage_contract(protocol, stage)
    expected_count = int(contract["records_per_target"])
    expected_namespace = str(contract["seed_namespace"])
    if not (
        target.get("experimental_role") == stage
        and target.get("w3b_stage") == stage
        and target.get("w3b_seed_namespace") == expected_namespace
        and target.get("num_seq") == expected_count
        and target.get("id_prefix") == f"{expected_namespace}-{target_id}"
        and _is_sha256(target.get("target_sequence_sha256"))
        and _is_sha256(target.get("target_msa_sha256"))
    ):
        _failure(failures, "execution_target_stage_contract_invalid", target_id=target_id)

    lock_targets = {
        str(row.get("target_id") or ""): row
        for row in binding.get("targets", [])
        if isinstance(row, dict)
    }
    lock_target = lock_targets.get(target_id)
    expected_outputs = {
        key: target.get(key)
        for key in ("out_prefix", "candidates", "boltz_records", "af2_records", "matched_records")
    }
    if not (
        isinstance(lock_target, dict)
        and lock_target.get("experimental_role") == stage
        and lock_target.get("seed_namespace") == expected_namespace
        and lock_target.get("records_planned") == expected_count
        and lock_target.get("id_prefix") == target.get("id_prefix")
        and lock_target.get("target_msa_sha256") == target.get("target_msa_sha256")
        and lock_target.get("outputs") == expected_outputs
    ):
        _failure(failures, "execution_target_input_lock_mismatch", target_id=target_id)
        lock_target = {}

    if require_target_files:
        artifacts = lock_target.get("artifacts") if isinstance(lock_target, dict) else None
        artifacts = artifacts if isinstance(artifacts, dict) else {}
        for field in ("prepared_pdb", "target_msa"):
            path = target.get(field)
            locked = artifacts.get(field)
            if not (
                isinstance(path, str)
                and os.path.isfile(path)
                and os.path.getsize(path) > 0
                and isinstance(locked, dict)
                and locked.get("path") == path
                and locked.get("bytes") == os.path.getsize(path)
                and locked.get("sha256") == sha256_file(path)
            ):
                _failure(failures, "execution_target_artifact_invalid", target_id=target_id, field=field)
        target_msa = target.get("target_msa")
        if (
            isinstance(target_msa, str)
            and os.path.isfile(target_msa)
            and sha256_file(target_msa) != target.get("target_msa_sha256")
        ):
            _failure(failures, "execution_target_msa_hash_mismatch", target_id=target_id)

    if failures:
        kinds = ",".join(str(row["kind"]) for row in failures)
        raise ValueError(f"W3b producer context is invalid for {target_id}: {kinds}")
    return {
        "protocol": protocol,
        "execution_manifest": manifest,
        "input_lock": input_lock,
        "runtime_lock": runtime_lock,
        "target": target,
        "lock_target": lock_target,
        "stage": stage,
        "expected_count": expected_count,
        "seed_namespace": expected_namespace,
        "bindings": {
            "protocol_sha256": protocol_sha256,
            "execution_manifest_sha256": manifest_sha256,
            "input_lock_sha256": sha256_file(input_lock_path),
            "runtime_lock_sha256": sha256_file(runtime_lock_path),
            "runtime_lock_digest_sha256": runtime_lock["runtime_lock_digest_sha256"],
        },
    }


def validate_candidates(
    context: Mapping[str, Any],
    candidates_path: str,
) -> List[Dict[str, Any]]:
    target = context["target"]
    expected_count = int(context["expected_count"])
    rows = load_jsonl(candidates_path)
    failures: List[Dict[str, Any]] = []
    if candidates_path != target.get("candidates"):
        _failure(failures, "candidate_path_differs_from_execution_manifest")
    if len(rows) != expected_count:
        _failure(failures, "candidate_count_mismatch", expected=expected_count, observed=len(rows))
    expected_ids = {
        f"{target['id_prefix']}-{index}"
        for index in range(expected_count)
    }
    observed_ids = [str(row.get("id") or "") for row in rows]
    if len(set(observed_ids)) != len(observed_ids) or set(observed_ids) != expected_ids:
        _failure(failures, "candidate_id_set_invalid")

    sequences: List[str] = []
    for row in rows:
        candidate_id = str(row.get("id") or "")
        binder = row.get("representation")
        target_sequence = row.get("target_seq")
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if not (
            isinstance(binder, str)
            and _SEQUENCE.fullmatch(binder)
            and isinstance(target_sequence, str)
            and _SEQUENCE.fullmatch(target_sequence)
            and sequence_sha256(target_sequence) == target.get("target_sequence_sha256")
            and row.get("regime") == "complex"
            and row.get("parent_id") is None
            and meta.get("complex_target_id") == target.get("id")
            and meta.get("id_prefix") == target.get("id_prefix")
            and meta.get("target_chain") == target.get("target_chain")
            and meta.get("design_chain") == target.get("binder_chain")
        ):
            _failure(failures, "candidate_contract_invalid", candidate_id=candidate_id)
        if isinstance(binder, str):
            sequences.append(binder)
    if len(set(sequences)) != len(sequences):
        _failure(
            failures,
            "duplicate_candidate_sequence",
            expected_unique=len(sequences),
            observed_unique=len(set(sequences)),
        )
    if failures:
        kinds = ",".join(str(row["kind"]) for row in failures)
        raise ValueError(f"W3b candidates are invalid: {kinds}")
    return sorted(rows, key=lambda row: int(str(row["id"]).rsplit("-", 1)[1]))


def prepare_af2_inputs(
    context: Mapping[str, Any],
    candidates_path: str,
    input_dir: str,
    manifest_path: str,
) -> Dict[str, Any]:
    """Create one annotated complex A3M per locked candidate, atomically."""
    target = context["target"]
    rows = validate_candidates(context, candidates_path)
    destination = Path(input_dir)
    manifest_destination = Path(manifest_path)
    if destination.exists() or manifest_destination.exists():
        raise ValueError("W3b AF2 input directory and manifest must both be absent")
    staging = destination.with_name(destination.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    target_msa_path = Path(str(target["target_msa"]))
    target_msa_text = target_msa_path.read_text()
    target_msa_sha256 = sha256_file(target_msa_path)
    private_rows: List[Dict[str, Any]] = []
    try:
        for candidate in rows:
            candidate_id = str(candidate["id"])
            if not _SAFE_ID.fullmatch(candidate_id):
                raise ValueError(f"unsafe W3b candidate id for AF2 filename: {candidate_id}")
            target_sequence = str(candidate["target_seq"])
            binder_sequence = str(candidate["representation"])
            a3m = build_annotated_multimer_a3m(
                target_msa_text,
                target_sequence,
                binder_sequence,
            )
            staged_path = staging / f"{candidate_id}.a3m"
            staged_path.write_text(a3m)
            final_path = destination / staged_path.name
            private_rows.append({
                "candidate_id": candidate_id,
                "complex_target_id": target["id"],
                "experimental_role": context["stage"],
                "seed_namespace": context["seed_namespace"],
                "target_sequence": target_sequence,
                "binder_sequence": binder_sequence,
                "target_sequence_sha256": sequence_sha256(target_sequence),
                "candidate_sequence_sha256": sequence_sha256(binder_sequence),
                "target_msa": str(target_msa_path),
                "target_msa_sha256": target_msa_sha256,
                "a3m_path": str(final_path),
                "a3m_sha256": hashlib.sha256(a3m.encode("utf-8")).hexdigest(),
                "reference_backbone": target["prepared_pdb"],
                "reference_backbone_sha256": sha256_file(target["prepared_pdb"]),
                "target_chain": target["target_chain"],
                "binder_chain": target["binder_chain"],
            })
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    payload = {
        "artifact": "m6d_w3b_af2_input_manifest",
        "version": 1,
        "status": "w3b_af2_inputs_ready_for_locked_prediction",
        "target_id": target["id"],
        "experimental_role": context["stage"],
        "seed_namespace": context["seed_namespace"],
        "n_candidates": len(private_rows),
        "candidates": candidates_path,
        "candidates_sha256": sha256_file(candidates_path),
        "input_dir": input_dir,
        "target_msa_sha256": target_msa_sha256,
        "bindings": dict(context["bindings"]),
        "prediction_contract": {
            "model_type": "alphafold2_multimer_v3",
            "models": 5,
            "num_seeds": 1,
            "random_seed": 0,
            "recycles": 20,
            "rank_by": "multimer",
            "relax_models": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
        },
        "rows": private_rows,
    }
    manifest_destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_destination.with_name(manifest_destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest_destination)
    return payload


def _context_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    return load_target_context(
        args.protocol,
        args.execution_manifest,
        args.input_lock,
        args.runtime_lock,
        args.target_id,
        args.stage,
    )


def _add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--stage", choices=_STAGES, required=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    target_parser = subparsers.add_parser("target", help="validate one locked execution target")
    _add_context_arguments(target_parser)
    target_parser.add_argument("--prepared-pdb")
    target_parser.add_argument("--target-msa")
    target_parser.add_argument("--target-chain")
    target_parser.add_argument("--binder-chain")
    target_parser.add_argument("--candidates")
    target_parser.add_argument("--boltz-records")
    target_parser.add_argument("--af2-records")
    candidate_parser = subparsers.add_parser("candidates", help="validate locked candidate output")
    _add_context_arguments(candidate_parser)
    candidate_parser.add_argument("--candidates", required=True)
    af2_parser = subparsers.add_parser("prepare-af2", help="materialize matched AF2 A3Ms")
    _add_context_arguments(af2_parser)
    af2_parser.add_argument("--candidates", required=True)
    af2_parser.add_argument("--input-dir", required=True)
    af2_parser.add_argument("--out-manifest", required=True)
    args = parser.parse_args(argv)
    context = _context_from_args(args)
    if args.command == "target":
        target = context["target"]
        expected = {
            "prepared_pdb": args.prepared_pdb,
            "target_msa": args.target_msa,
            "target_chain": args.target_chain,
            "binder_chain": args.binder_chain,
            "candidates": args.candidates,
            "boltz_records": args.boltz_records,
            "af2_records": args.af2_records,
        }
        mismatches = [
            field
            for field, supplied in expected.items()
            if supplied is not None and supplied != target.get(field)
        ]
        if mismatches:
            raise ValueError("W3b invocation differs from execution manifest: " + ",".join(mismatches))
        print(f"target={args.target_id} stage={args.stage} contract_ok=True")
        return 0
    if args.command == "candidates":
        rows = validate_candidates(context, args.candidates)
        print(f"target={args.target_id} stage={args.stage} candidates={len(rows)} contract_ok=True")
        return 0
    payload = prepare_af2_inputs(context, args.candidates, args.input_dir, args.out_manifest)
    print(
        f"target={args.target_id} stage={args.stage} "
        f"af2_inputs={payload['n_candidates']} contract_ok=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
