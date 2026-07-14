"""Build the immutable W3b matched-predictor execution manifest and input lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


_ROLES = ("fit", "certification", "held_out_test")
_ARTIFACT_FIELDS = (
    "source_pdb",
    "prepared_pdb",
    "prep_report",
    "target_fasta",
    "target_fasta_report",
    "target_msa",
    "target_msa_report",
)
_SOURCE_FIELDS = (
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
    "experimental_role",
    "role_rank",
    "role_selection_hash",
    "selection_hash",
    "selection_input_origin",
)
_OUTPUT_ROOT = "hpc_outputs/m6d_w3b_matched"


def _load_object(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
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


def _stage_contracts(protocol: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("W3b protocol is missing locked_scientific_protocol")
    contracts = {
        "fit": locked.get("fit_design"),
        "certification": locked.get("certification_design"),
        "held_out_test": locked.get("held_out_test_design"),
    }
    expected = {
        "fit": (60, "w3b-fit-v1"),
        "certification": (150, "w3b-cert-v1"),
        "held_out_test": (120, "w3b-test-v1"),
    }
    for role, contract in contracts.items():
        if not isinstance(contract, dict):
            raise ValueError(f"W3b protocol is missing the {role} design")
        records, namespace = expected[role]
        if contract.get("records_per_target") != records or contract.get("seed_namespace") != namespace:
            raise ValueError(f"W3b {role} design differs from the frozen record/namespace contract")
    return {role: dict(contract) for role, contract in contracts.items()}


def _expected_target_contract(protocol: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    execution = protocol.get("execution_state")
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(execution, dict) or not isinstance(locked, dict):
        raise ValueError("W3b protocol is missing execution or scientific state")
    targets = [row for row in source.get("targets", []) if isinstance(row, dict)]
    target_ids = [str(row.get("id") or "") for row in targets]
    if len(target_ids) != 8 or len(set(target_ids)) != 8 or any(not value for value in target_ids):
        raise ValueError("W3b execution lock requires exactly eight unique source targets")
    role_counts = Counter(str(row.get("experimental_role") or "") for row in targets)
    expected_counts = {
        "fit": int(locked["fresh_target_contract"]["n_fit_targets"]),
        "certification": int(locked["fresh_target_contract"]["n_certification_targets"]),
        "held_out_test": int(locked["fresh_target_contract"]["n_held_out_test_targets"]),
    }
    if dict(role_counts) != expected_counts:
        raise ValueError("W3b source target roles differ from the frozen 3/3/2 contract")
    return {
        "execution": execution,
        "locked": locked,
        "targets": targets,
        "target_ids": target_ids,
        "role_counts": expected_counts,
        "stages": _stage_contracts(protocol),
    }


def evaluate_readiness(
    protocol_path: str,
    source_manifest_path: str,
    lifecycle_path: str,
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    source = _load_object(source_manifest_path)
    lifecycle = _load_object(lifecycle_path)
    contract = _expected_target_contract(protocol, source)
    failures: List[Dict[str, Any]] = []
    requirements: List[str] = []
    source_sha256 = _sha256_file(source_manifest_path)
    if contract["execution"].get("target_manifest") != source_manifest_path:
        failures.append({"kind": "protocol_source_manifest_path_mismatch"})
    if contract["execution"].get("target_manifest_sha256") != source_sha256:
        failures.append({"kind": "protocol_source_manifest_sha256_mismatch"})
    if lifecycle.get("manifest") != source_manifest_path or lifecycle.get("manifest_sha256") != source_sha256:
        failures.append({"kind": "lifecycle_source_manifest_binding_mismatch"})

    lifecycle_complete = (
        lifecycle.get("artifact") == "m6d_w3b_target_msa_lifecycle"
        and lifecycle.get("status") == "target_msa_precompute_complete_8_of_8"
        and lifecycle.get("audit_ok") is True
        and lifecycle.get("completion_ok") is True
        and lifecycle.get("jobs_terminal_success") is True
        and lifecycle.get("within_gpu_budget") is True
        and lifecycle.get("n_targets") == 8
        and lifecycle.get("n_failures") == 0
        and isinstance(lifecycle.get("strict_manifest"), dict)
        and lifecycle["strict_manifest"].get("ok") is True
    )
    target_bindings: List[Dict[str, Any]] = []
    if lifecycle_complete:
        rows = lifecycle.get("target_artifacts")
        if not isinstance(rows, list) or len(rows) != 8:
            failures.append({"kind": "lifecycle_target_artifact_count_invalid"})
            rows = []
        by_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                failures.append({"kind": "lifecycle_target_artifact_not_object"})
                continue
            target_id = str(row.get("target_id") or "")
            if not target_id or target_id in by_id:
                failures.append({"kind": "lifecycle_target_artifact_id_invalid", "target_id": target_id})
                continue
            by_id[target_id] = row
        if list(by_id) != contract["target_ids"]:
            failures.append({
                "kind": "lifecycle_target_artifact_order_or_set_mismatch",
                "expected": contract["target_ids"],
                "actual": list(by_id),
            })
        source_by_id = {str(row["id"]): row for row in contract["targets"]}
        for target_id in contract["target_ids"]:
            row = by_id.get(target_id, {})
            source_target = source_by_id[target_id]
            msa_path = str(source_target.get("target_msa") or "")
            report_path = str(source_target.get("target_msa_report") or "")
            msa_sha256 = row.get("target_msa_sha256")
            report_sha256 = row.get("target_msa_report_sha256")
            if not _is_sha256(msa_sha256) or not _is_sha256(report_sha256):
                failures.append({"kind": "lifecycle_target_hash_invalid", "target_id": target_id})
                continue
            if row.get("target_msa_report_ok") is not True:
                failures.append({"kind": "lifecycle_target_msa_report_not_ok", "target_id": target_id})
            if row.get("target_sequence_sha256") != source_target.get("target_sequence_sha256"):
                failures.append({"kind": "lifecycle_target_sequence_hash_mismatch", "target_id": target_id})
            if not os.path.isfile(msa_path) or _sha256_file(msa_path) != msa_sha256:
                failures.append({"kind": "target_msa_file_hash_mismatch", "target_id": target_id})
            if not os.path.isfile(report_path) or _sha256_file(report_path) != report_sha256:
                failures.append({"kind": "target_msa_report_file_hash_mismatch", "target_id": target_id})
            target_bindings.append({
                "target_id": target_id,
                "target_msa": msa_path,
                "target_msa_sha256": msa_sha256,
                "target_msa_report": report_path,
                "target_msa_report_sha256": report_sha256,
            })
    else:
        expected_waiting_state = (
            lifecycle.get("status") == "target_msa_not_submitted_awaiting_explicit_approval"
            and lifecycle.get("audit_ok") is True
            and lifecycle.get("completion_ok") is False
            and lifecycle.get("submitted") is False
            and lifecycle.get("explicit_approval_still_required") is True
            and lifecycle.get("n_failures") == 0
        )
        if expected_waiting_state:
            requirements.append("complete the separately approved eight-target MSA precompute and strict sync-back replay")
        else:
            failures.append({"kind": "target_msa_lifecycle_not_complete_or_coherent"})

    ready = lifecycle_complete and not failures and len(target_bindings) == 8
    if failures:
        status = "w3b_execution_lock_readiness_blocked"
    elif ready:
        status = "w3b_execution_lock_ready_for_manifest_materialization"
    else:
        status = "w3b_execution_lock_awaiting_target_msa_approval_and_completion"
    return {
        "artifact": "m6d_w3b_execution_lock_readiness",
        "status": status,
        "audit_ok": not failures,
        "execution_lock_ready": ready,
        "no_submit": True,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "protocol": protocol_path,
        "protocol_sha256": _sha256_file(protocol_path),
        "source_manifest": source_manifest_path,
        "source_manifest_sha256": source_sha256,
        "target_msa_lifecycle": lifecycle_path,
        "target_msa_lifecycle_sha256": _sha256_file(lifecycle_path),
        "target_ids": contract["target_ids"],
        "role_counts": contract["role_counts"],
        "target_bindings": target_bindings,
        "requirements": requirements,
        "n_failures": len(failures),
        "failures": failures,
        "claim_boundary": (
            "Execution-input provenance only. This readiness check never submits work and cannot authorize "
            "candidate generation, predictor execution, certification, or a W3b claim."
        ),
        "next_action": (
            "materialize the immutable execution manifest and input lock, then prepare a separate fit-stage approval packet"
            if ready else
            requirements[0]
            if requirements else
            "repair execution-lock readiness before any W3b candidate or predictor stage"
        ),
    }


def build_execution_manifest(
    protocol_path: str,
    source_manifest_path: str,
    lifecycle_path: str,
) -> Dict[str, Any]:
    readiness = evaluate_readiness(protocol_path, source_manifest_path, lifecycle_path)
    if not readiness["execution_lock_ready"]:
        raise ValueError(f"W3b execution manifest is not ready: {readiness['status']}")
    protocol = _load_object(protocol_path)
    source = _load_object(source_manifest_path)
    contract = _expected_target_contract(protocol, source)
    bindings = {row["target_id"]: row for row in readiness["target_bindings"]}
    predictors = protocol["locked_scientific_protocol"]["predictor_contract"]["predictors"]
    defaults = source.get("defaults") if isinstance(source.get("defaults"), dict) else {}
    targets: List[Dict[str, Any]] = []
    for source_target in contract["targets"]:
        target_id = str(source_target["id"])
        role = str(source_target["experimental_role"])
        stage = contract["stages"][role]
        namespace = str(stage["seed_namespace"])
        records = int(stage["records_per_target"])
        out_prefix = f"{_OUTPUT_ROOT}/{role}/{target_id}"
        target = {field: source_target[field] for field in _SOURCE_FIELDS}
        target.update({
            "w3b_stage": role,
            "w3b_seed_namespace": namespace,
            "proteinmpnn_seed": deterministic_seed(namespace, target_id),
            "id_prefix": f"{namespace}-{target_id}",
            "num_seq": records,
            "temp": float(defaults.get("temp", 0.3)),
            "objective": str(defaults.get("objective", "binder")),
            "target_msa_sha256": bindings[target_id]["target_msa_sha256"],
            "target_msa_report_sha256": bindings[target_id]["target_msa_report_sha256"],
            "out_prefix": out_prefix,
            "candidates": f"{out_prefix}/candidates_proteinmpnn_complex.jsonl",
            "boltz_records": f"{out_prefix}/records_boltz_complex.jsonl",
            "af2_records": f"{out_prefix}/records_af2_multimer.jsonl",
            "matched_records": f"{out_prefix}/records_w3b_matched.jsonl",
        })
        targets.append(target)
    total_candidates = sum(int(row["num_seq"]) for row in targets)
    maximum_designs = int(contract["locked"]["compute_budget"]["maximum_candidate_designs"])
    maximum_evaluations = int(contract["locked"]["compute_budget"]["maximum_predictor_evaluations"])
    if total_candidates != maximum_designs or 2 * total_candidates != maximum_evaluations:
        raise ValueError("W3b execution manifest totals differ from the frozen compute budget")
    return {
        "artifact": "m6d_w3b_execution_target_manifest",
        "version": 1,
        "status": "w3b_execution_inputs_locked_no_submit",
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_generate_candidates_or_run_predictors": False,
        "protocol": protocol_path,
        "protocol_sha256": _sha256_file(protocol_path),
        "source_manifest": source_manifest_path,
        "source_manifest_sha256": _sha256_file(source_manifest_path),
        "target_msa_lifecycle": lifecycle_path,
        "target_msa_lifecycle_sha256": _sha256_file(lifecycle_path),
        "locked_scientific_digest": source.get("locked_scientific_digest"),
        "output_root": _OUTPUT_ROOT,
        "target_ids": contract["target_ids"],
        "role_counts": contract["role_counts"],
        "total_candidate_designs": total_candidates,
        "total_matched_predictor_evaluations": 2 * total_candidates,
        "predictor_contract": predictors,
        "targets": targets,
        "claim_boundary": (
            "Immutable W3b execution inputs only. This manifest authorizes no jobs and supports no gate, "
            "certificate, biological-success, or predictor-robustness claim."
        ),
    }


def build_input_lock(
    protocol_path: str,
    source_manifest_path: str,
    lifecycle_path: str,
    execution_manifest_path: str,
) -> Dict[str, Any]:
    expected = build_execution_manifest(protocol_path, source_manifest_path, lifecycle_path)
    actual = _load_object(execution_manifest_path)
    failures: List[Dict[str, Any]] = []
    if actual != expected:
        failures.append({"kind": "execution_manifest_content_mismatch"})
    lifecycle = _load_object(lifecycle_path)
    lifecycle_by_id = {
        str(row.get("target_id") or ""): row
        for row in lifecycle.get("target_artifacts", [])
        if isinstance(row, dict)
    }
    locked_targets: List[Dict[str, Any]] = []
    for target in expected["targets"]:
        target_id = str(target["id"])
        artifacts: Dict[str, Dict[str, Any]] = {}
        for field in _ARTIFACT_FIELDS:
            path = target.get(field)
            if not isinstance(path, str) or not os.path.isfile(path) or os.path.getsize(path) <= 0:
                failures.append({"kind": "missing_or_empty_lock_artifact", "target_id": target_id, "field": field})
                continue
            artifacts[field] = {
                "path": path,
                "bytes": os.path.getsize(path),
                "sha256": _sha256_file(path),
            }
        lifecycle_target = lifecycle_by_id.get(target_id, {})
        if artifacts.get("target_msa", {}).get("sha256") != lifecycle_target.get("target_msa_sha256"):
            failures.append({"kind": "target_msa_lifecycle_hash_mismatch", "target_id": target_id})
        if artifacts.get("target_msa_report", {}).get("sha256") != lifecycle_target.get("target_msa_report_sha256"):
            failures.append({"kind": "target_msa_report_lifecycle_hash_mismatch", "target_id": target_id})
        locked_targets.append({
            "target_id": target_id,
            "experimental_role": target["experimental_role"],
            "seed_namespace": target["w3b_seed_namespace"],
            "proteinmpnn_seed": target["proteinmpnn_seed"],
            "records_planned": target["num_seq"],
            "id_prefix": target["id_prefix"],
            "target_msa_sha256": target["target_msa_sha256"],
            "outputs": {
                key: target[key]
                for key in ("out_prefix", "candidates", "boltz_records", "af2_records", "matched_records")
            },
            "artifacts": artifacts,
        })
    binding = {
        "protocol_file_sha256": _sha256_file(protocol_path),
        "source_manifest_sha256": _sha256_file(source_manifest_path),
        "target_msa_lifecycle_sha256": _sha256_file(lifecycle_path),
        "execution_manifest_sha256": _sha256_file(execution_manifest_path),
        "locked_scientific_digest": expected.get("locked_scientific_digest"),
        "total_candidate_designs": expected["total_candidate_designs"],
        "total_matched_predictor_evaluations": expected["total_matched_predictor_evaluations"],
        "predictor_contract": expected["predictor_contract"],
        "targets": locked_targets,
    }
    return {
        "artifact": "m6d_w3b_execution_input_lock",
        "version": 1,
        "status": "w3b_execution_input_locked_no_submit" if not failures else "w3b_execution_input_lock_blocked",
        "audit_ok": not failures,
        "no_submit": True,
        "can_generate_candidates_or_run_predictors": False,
        "can_claim_w3b": False,
        "protocol": protocol_path,
        "source_manifest": source_manifest_path,
        "target_msa_lifecycle": lifecycle_path,
        "execution_manifest": execution_manifest_path,
        "n_targets": len(locked_targets),
        "n_artifacts": sum(len(row["artifacts"]) for row in locked_targets),
        "lock_digest_sha256": _canonical_sha256(binding),
        "binding": binding,
        "failures": failures,
        "claim_boundary": (
            "Immutable execution-input provenance only. This lock never submits jobs and cannot authorize "
            "candidate generation, predictor execution, certification, or a W3b claim."
        ),
    }


def verify_lock(
    lock_path: str,
    protocol_path: str,
    source_manifest_path: str,
    lifecycle_path: str,
    execution_manifest_path: str,
) -> Dict[str, Any]:
    expected = _load_object(lock_path)
    current = build_input_lock(
        protocol_path,
        source_manifest_path,
        lifecycle_path,
        execution_manifest_path,
    )
    digest_matches = expected.get("lock_digest_sha256") == current.get("lock_digest_sha256")
    verified = bool(expected.get("audit_ok") and current.get("audit_ok") and digest_matches)
    return {
        "artifact": "m6d_w3b_execution_input_lock_verification",
        "status": "w3b_execution_input_lock_verified" if verified else "w3b_execution_input_lock_verification_failed",
        "verified": verified,
        "lock": lock_path,
        "expected_lock_digest_sha256": expected.get("lock_digest_sha256"),
        "actual_lock_digest_sha256": current.get("lock_digest_sha256"),
        "current_failures": current.get("failures") or [],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3b Execution-Lock Readiness",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Execution lock ready: `{report['execution_lock_ready']}`.",
        f"No submit: `{report['no_submit']}`.",
        "",
        report["claim_boundary"],
        "",
        f"- targets: `{len(report['target_ids'])}`",
        f"- manifest-bound MSA hashes: `{len(report['target_bindings'])}`",
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
        lines.extend(f"- `{row['kind']}`" for row in report["failures"])
        lines.append("")
    return "\n".join(lines)


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--source-manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--lifecycle", default="results/m6d_w3b_target_msa_lifecycle.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--out-readiness", default="results/m6d_w3b_execution_lock_readiness.json")
    parser.add_argument("--out-readiness-md", default="results/m6d_w3b_execution_lock_readiness.md")
    parser.add_argument("--emit-execution-lock", action="store_true")
    parser.add_argument("--verify-lock", default=None)
    args = parser.parse_args(argv)
    readiness = evaluate_readiness(args.protocol, args.source_manifest, args.lifecycle)
    _write_json(args.out_readiness, readiness)
    _write_text(args.out_readiness_md, render_markdown(readiness))
    if args.verify_lock:
        report = verify_lock(
            args.verify_lock,
            args.protocol,
            args.source_manifest,
            args.lifecycle,
            args.execution_manifest,
        )
        print(f"status={report['status']} verified={report['verified']}")
        return 0 if report["verified"] else 2
    if args.emit_execution_lock:
        if not readiness["execution_lock_ready"]:
            print(f"status={readiness['status']} audit_ok={readiness['audit_ok']} ready=False no_submit=True")
            return 2
        manifest = build_execution_manifest(args.protocol, args.source_manifest, args.lifecycle)
        _write_json(args.execution_manifest, manifest)
        lock = build_input_lock(
            args.protocol,
            args.source_manifest,
            args.lifecycle,
            args.execution_manifest,
        )
        _write_json(args.input_lock, lock)
        print(f"status={lock['status']} audit_ok={lock['audit_ok']} no_submit=True")
        return 0 if lock["audit_ok"] else 2
    print(
        f"status={readiness['status']} audit_ok={readiness['audit_ok']} "
        f"ready={readiness['execution_lock_ready']} no_submit=True"
    )
    return 0 if readiness["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
