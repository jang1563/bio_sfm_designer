"""Build or verify the immutable W2b stage-input lock before Cayuga compute."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional

from .complex_target_manifest import validate_manifest


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


def _canonical_sha256(value: Dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_report_binding(field: str, path: str, target: Dict[str, Any]) -> Dict[str, Any]:
    report = _load_object(path)
    for key in list(report):
        if key.endswith("_abs") or key in {"work_dir", "source_msa", "command"}:
            report.pop(key, None)
    if field == "prep_report":
        report["source_pdb"] = target.get("source_pdb")
        report["output_pdb"] = target.get("prepared_pdb")
    elif field == "target_fasta_report":
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


def build_lock(protocol_path: str, manifest_path: str) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    manifest = _load_object(manifest_path)
    expected_targets = int(protocol["fresh_target_contract"]["n_initial_targets"])
    strict = validate_manifest(
        manifest_path,
        require_files=True,
        min_targets=expected_targets,
        min_contacts=20,
    )
    failures = [] if strict.get("ok") else list(strict.get("failures") or [])
    state = protocol.get("current_execution_state")
    if not isinstance(state, dict):
        state = {}
        failures.append({"kind": "missing_current_execution_state"})

    manifest_sha256 = _sha256_file(manifest_path)
    expected_manifest_sha256 = state.get("fit_manifest_sha256")
    if expected_manifest_sha256 != manifest_sha256:
        failures.append({
            "kind": "manifest_sha256_mismatch",
            "expected": expected_manifest_sha256,
            "actual": manifest_sha256,
        })
    protocol_digest = str(manifest.get("protocol_sha256") or "")
    if protocol_digest != state.get("locked_scientific_protocol_sha256"):
        failures.append({"kind": "scientific_protocol_digest_mismatch"})

    stage = str(manifest.get("w2b_stage") or "")
    namespace = str(manifest.get("w2b_seed_namespace") or "")
    stage_spec = protocol.get("generation_stages", {}).get(stage)
    if not isinstance(stage_spec, dict):
        failures.append({"kind": "unknown_w2b_stage", "stage": stage})
        stage_spec = {}
    if namespace != stage_spec.get("seed_namespace"):
        failures.append({
            "kind": "seed_namespace_mismatch",
            "stage": stage,
            "expected": stage_spec.get("seed_namespace"),
            "actual": namespace,
        })
    seed_map = state.get("stage_proteinmpnn_seeds")
    expected_seed = seed_map.get(stage) if isinstance(seed_map, dict) else None
    if not isinstance(expected_seed, int):
        failures.append({"kind": "missing_stage_proteinmpnn_seed", "stage": stage})

    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    expected_records = int(stage_spec.get("records_per_target") or 0)
    locked_targets = []
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or "")
        target_stage = str(target.get("w2b_stage") or stage)
        target_namespace = str(target.get("w2b_seed_namespace") or namespace)
        num_seq = int(target.get("num_seq", defaults.get("num_seq", 0)))
        seed = int(target.get("seed", defaults.get("seed", -1)))
        if target_stage != stage or target_namespace != namespace:
            failures.append({"kind": "target_stage_metadata_mismatch", "target_id": target_id})
        if num_seq != expected_records:
            failures.append({
                "kind": "target_record_budget_mismatch",
                "target_id": target_id,
                "expected": expected_records,
                "actual": num_seq,
            })
        if expected_seed is not None and seed != expected_seed:
            failures.append({
                "kind": "target_seed_mismatch",
                "target_id": target_id,
                "expected": expected_seed,
                "actual": seed,
            })
        artifacts = {}
        for field in _ARTIFACT_FIELDS:
            value = target.get(field)
            if not isinstance(value, str) or not value:
                failures.append({"kind": "missing_lock_artifact", "target_id": target_id, "field": field})
                continue
            if not os.path.isfile(value) or os.path.getsize(value) <= 0:
                failures.append({
                    "kind": "missing_or_empty_lock_artifact",
                    "target_id": target_id,
                    "field": field,
                    "path": value,
                })
                continue
            if field in _REPORT_FIELDS:
                artifacts[field] = _canonical_report_binding(field, value, target)
            else:
                artifacts[field] = {
                    "path": value,
                    "hash_mode": "raw_bytes_sha256",
                    "bytes": os.path.getsize(value),
                    "sha256": _sha256_file(value),
                }
        locked_targets.append({
            "target_id": target_id,
            "stage": target_stage,
            "seed_namespace": target_namespace,
            "proteinmpnn_seed": seed,
            "records_planned": num_seq,
            "id_prefix": str(target.get("id_prefix") or f"{target_namespace}-{target_id}"),
            "artifacts": artifacts,
        })

    binding = {
        "protocol_file_sha256": _sha256_file(protocol_path),
        "scientific_protocol_sha256": protocol_digest,
        "manifest_sha256": manifest_sha256,
        "stage": stage,
        "seed_namespace": namespace,
        "proteinmpnn_seed": expected_seed,
        "records_per_target": expected_records,
        "targets": locked_targets,
    }
    return {
        "artifact": "m6d_w2b_stage_input_lock",
        "version": 1,
        "status": "w2b_stage_input_locked" if not failures else "w2b_stage_input_lock_blocked",
        "audit_ok": not failures,
        "claim_boundary": (
            "Input and execution-provenance lock only. This does not authorize Cayuga jobs or support "
            "a W2b scientific claim."
        ),
        "protocol": protocol_path,
        "manifest": manifest_path,
        "n_targets": len(locked_targets),
        "n_artifacts": sum(len(row["artifacts"]) for row in locked_targets),
        "lock_digest_sha256": _canonical_sha256(binding),
        "binding": binding,
        "failures": failures,
    }


def verify_lock(lock_path: str, protocol_path: str, manifest_path: str) -> Dict[str, Any]:
    expected = _load_object(lock_path)
    current = build_lock(protocol_path, manifest_path)
    digest_matches = expected.get("lock_digest_sha256") == current.get("lock_digest_sha256")
    verified = bool(expected.get("audit_ok") and current.get("audit_ok") and digest_matches)
    return {
        "artifact": "m6d_w2b_stage_input_lock_verification",
        "status": "w2b_stage_input_lock_verified" if verified else "w2b_stage_input_lock_verification_failed",
        "verified": verified,
        "lock": lock_path,
        "expected_lock_digest_sha256": expected.get("lock_digest_sha256"),
        "actual_lock_digest_sha256": current.get("lock_digest_sha256"),
        "current_failures": current.get("failures") or [],
    }


def _write(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verify-lock", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    report = (
        verify_lock(args.verify_lock, args.protocol, args.manifest)
        if args.verify_lock
        else build_lock(args.protocol, args.manifest)
    )
    if args.out:
        _write(args.out, report)
    print(
        f"status={report['status']} "
        f"ok={report.get('verified', report.get('audit_ok', False))}"
    )
    return 0 if report.get("verified", report.get("audit_ok", False)) else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
