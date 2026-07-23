"""Build the hash-bound, no-submit W3c-B1 target-MSA approval packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional


APPROVAL_ENV = "BIO_SFM_APPROVE_W3C_B1_TARGET_MSA"
APPROVAL_TOKEN = "approve-w3c-b1-target-msa-precompute"
APPROVAL_PHRASE = "approve W3c-B1 target-MSA precompute"
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
MAXIMUM_TARGET_MSA_QUERIES = 8
MAXIMUM_A40_GPU_HOURS = 8.0
SLURM_TIME = "01:00:00"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value)


def _normalize_manifest_audit(path: str, manifest_path: str) -> None:
    payload = _load_json(path)
    recorded = payload.get("manifest")
    allowed = {manifest_path, os.path.abspath(manifest_path)}
    if recorded not in allowed:
        raise ValueError(
            f"pre-MSA manifest audit points to an unexpected manifest: {recorded!r}"
        )
    if payload.get("ok") is not True or payload.get("n_targets") != 8:
        raise ValueError("pre-MSA manifest audit is not ready for all eight W3c-B1 targets")
    if payload.get("n_ready_targets") != 8 or payload.get("failures") != []:
        raise ValueError("pre-MSA manifest audit contains readiness failures")
    payload["manifest"] = manifest_path
    _write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binding(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError(f"bound artifact is missing or empty: {path}")
    return {"path": path, "bytes": os.path.getsize(path), "sha256": _sha256(path)}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _failure(failures: List[Dict[str, str]], kind: str, message: str) -> None:
    failures.append({"kind": kind, "message": message})


def _stage(protocol: Mapping[str, Any], stage_id: str) -> Mapping[str, Any]:
    stages = protocol.get("stages")
    if not isinstance(stages, list):
        return {}
    return next(
        (row for row in stages if isinstance(row, dict) and row.get("stage") == stage_id),
        {},
    )


def _target_rows(payload: Mapping[str, Any], label: str) -> List[Dict[str, Any]]:
    rows = payload.get("targets")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must contain object target rows")
    return [dict(row) for row in rows]


def build_execution_manifest(
    locked_manifest: Mapping[str, Any],
    fresh_lock: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    locked_manifest_path: str,
    fresh_lock_path: str,
    protocol_path: str,
    output_root: str = "hpc_outputs/m6d_w3c_b1_targets",
) -> Dict[str, Any]:
    stage_b1 = _stage(protocol, "W3c-B1")
    rows = _target_rows(locked_manifest, "W3c-A locked manifest")
    lock_rows = _target_rows(fresh_lock, "W3c-A fresh-target lock")
    lock_by_id = {str(row.get("target_id")): row for row in lock_rows}
    target_ids = [str(row.get("id") or "") for row in rows]
    inputs = fresh_lock.get("inputs") if isinstance(fresh_lock.get("inputs"), dict) else {}
    locked_binding = inputs.get("locked_manifest")
    protocol_binding = inputs.get("validity_first_protocol")

    checks = {
        "locked_manifest_identity": (
            locked_manifest.get("artifact") == "m6d_w3c_fresh_target_manifest"
            and locked_manifest.get("version") == 1
            and locked_manifest.get("status")
            == "representation_locked_awaiting_separate_target_msa_packet_no_submit"
        ),
        "locked_manifest_targets_exact": (
            locked_manifest.get("target_count") == 8
            and locked_manifest.get("target_ids") == TARGET_IDS
            and target_ids == TARGET_IDS
            and len(set(target_ids)) == 8
        ),
        "locked_manifest_boundary": (
            locked_manifest.get("target_msa_queries_authorized") == 0
            and locked_manifest.get("proteinmpnn_designs") == 0
            and locked_manifest.get("predictor_evaluations") == 0
            and locked_manifest.get("no_submit") is True
            and locked_manifest.get("cayuga_submission_allowed") is False
        ),
        "fresh_lock_identity": (
            fresh_lock.get("artifact") == "m6d_w3c_fresh_target_lock"
            and fresh_lock.get("version") == 1
            and fresh_lock.get("status")
            == "w3c_a_fresh_target_representation_lock_complete_no_submit"
            and fresh_lock.get("audit_ok") is True
            and fresh_lock.get("w3c_a_complete") is True
        ),
        "fresh_lock_boundary": (
            fresh_lock.get("w3c_b1_target_msa_packet_prepared") is False
            and fresh_lock.get("target_msa_queries_authorized") == 0
            and fresh_lock.get("proteinmpnn_designs") == 0
            and fresh_lock.get("predictor_evaluations") == 0
            and fresh_lock.get("no_submit") is True
            and fresh_lock.get("cayuga_submission_allowed") is False
        ),
        "fresh_lock_targets_exact": (
            list(lock_by_id) == TARGET_IDS and len(lock_by_id) == 8
        ),
        "fresh_lock_manifest_binding": (
            isinstance(locked_binding, dict)
            and locked_binding.get("path") == locked_manifest_path
            and locked_binding.get("sha256") == _sha256(locked_manifest_path)
        ),
        "fresh_lock_protocol_binding": (
            isinstance(protocol_binding, dict)
            and protocol_binding.get("path") == protocol_path
            and protocol_binding.get("sha256") == _sha256(protocol_path)
        ),
        "protocol_identity": (
            protocol.get("artifact") == "m6d_w3c_validity_first_protocol"
            and protocol.get("version") == 1
            and protocol.get("status") == "preregistered_target_discovery_only_no_submit"
        ),
        "protocol_b1_scope": (
            stage_b1.get("name") == "target-MSA preparation"
            and stage_b1.get("compute") == "Cayuga A40"
            and stage_b1.get("maximum_target_msa_queries") == MAXIMUM_TARGET_MSA_QUERIES
            and stage_b1.get("proteinmpnn_designs") == 0
            and stage_b1.get("predictor_evaluations") == 0
            and stage_b1.get("approval_required") is True
            and stage_b1.get("approval_status") == "not_prepared"
        ),
        "protocol_boundary": (
            protocol.get("no_submit") is True
            and protocol.get("cayuga_submission_allowed") is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3c-B1 execution manifest gate failed: {', '.join(failed)}")

    execution_rows: List[Dict[str, Any]] = []
    for row in rows:
        target_id = str(row["id"])
        lock_row = lock_by_id[target_id]
        source = lock_row.get("source_pdb")
        if not isinstance(source, dict):
            raise ValueError(f"W3c-A source binding missing: {target_id}")
        row_checks = {
            "source_hash_exact": (
                _is_sha256(row.get("source_pdb_sha256"))
                and row.get("source_pdb_sha256") == source.get("sha256")
            ),
            "source_path_exact": row.get("source_pdb") == source.get("path"),
            "source_url_exact": row.get("source_pdb_url") == source.get("rcsb_download_url"),
            "target_hash_exact": (
                _is_sha256(row.get("target_sequence_sha256"))
                and row.get("target_sequence_sha256")
                == lock_row.get("target_sequence_sha256")
            ),
            "binder_hash_exact": (
                _is_sha256(row.get("binder_sequence_sha256"))
                and row.get("binder_sequence_sha256")
                == lock_row.get("binder_sequence_sha256")
            ),
            "chain_roles_exact": (
                row.get("target_chain") == lock_row.get("target", {}).get("chain")
                and row.get("binder_chain") == lock_row.get("binder", {}).get("chain")
            ),
            "semantic_pass": row.get("semantic_verdict") == "pass",
        }
        row_failed = [name for name, passed in row_checks.items() if not passed]
        if row_failed:
            raise ValueError(f"W3c-B1 target binding failed ({target_id}): {', '.join(row_failed)}")

        target_dir = f"{output_root}/{target_id}"
        target_chain = str(row["target_chain"])
        execution_rows.append(
            {
                **row,
                "prepared_pdb": f"{target_dir}/prepared_{target_id}.pdb",
                "prep_report": f"{target_dir}/prepared_{target_id}.report.json",
                "target_fasta": f"{target_dir}/{target_id}_{target_chain}.fasta",
                "target_fasta_report": (
                    f"{target_dir}/{target_id}_{target_chain}.fasta.report.json"
                ),
                "target_msa": f"{target_dir}/{target_id}_{target_chain}.a3m",
                "target_msa_report": (
                    f"{target_dir}/{target_id}_{target_chain}.a3m.report.json"
                ),
            }
        )

    return {
        "artifact": "m6d_w3c_b1_target_msa_manifest",
        "version": 1,
        "status": "inputs_locked_awaiting_exact_approval_no_submit",
        "inputs": {
            "w3c_a_locked_manifest": _binding(locked_manifest_path),
            "w3c_a_fresh_target_lock": _binding(fresh_lock_path),
            "validity_first_protocol": _binding(protocol_path),
        },
        "target_count": 8,
        "target_ids": TARGET_IDS,
        "targets": execution_rows,
        "compute_resource": "Cayuga A40",
        "slurm_time_per_query": SLURM_TIME,
        "maximum_target_msa_queries": MAXIMUM_TARGET_MSA_QUERIES,
        "maximum_a40_gpu_hours": MAXIMUM_A40_GPU_HOURS,
        "target_msa_queries_authorized": 0,
        "target_msa_queries_if_exactly_approved": MAXIMUM_TARGET_MSA_QUERIES,
        "proteinmpnn_designs_authorized": 0,
        "predictor_evaluations_authorized": 0,
        "approval_recorded": False,
        "submission_performed": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "claim_boundary": (
            "Input and budget lock only. This manifest authorizes no target-MSA query, "
            "ProteinMPNN design, structure-predictor evaluation, or scientific claim."
        ),
    }


def build_packet(
    locked_manifest: Mapping[str, Any],
    fresh_lock: Mapping[str, Any],
    protocol: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    *,
    locked_manifest_path: str,
    fresh_lock_path: str,
    protocol_path: str,
    execution_manifest_path: str,
    runtime_bindings: Mapping[str, str],
    wrapper_path: str,
    receipt_path: str,
) -> Dict[str, Any]:
    failures: List[Dict[str, str]] = []
    try:
        expected_manifest = build_execution_manifest(
            locked_manifest,
            fresh_lock,
            protocol,
            locked_manifest_path=locked_manifest_path,
            fresh_lock_path=fresh_lock_path,
            protocol_path=protocol_path,
        )
    except ValueError as exc:
        expected_manifest = None
        _failure(failures, "execution_manifest_source_invalid", str(exc))
    if expected_manifest is not None and execution_manifest != expected_manifest:
        _failure(
            failures,
            "execution_manifest_drift",
            "checked-in W3c-B1 execution manifest differs from the deterministic W3c-A derivation",
        )

    target_rows = _target_rows(execution_manifest, "W3c-B1 execution manifest")
    target_ids = [str(row.get("id") or "") for row in target_rows]
    if target_ids != TARGET_IDS or len(set(target_ids)) != 8:
        _failure(failures, "target_panel_invalid", "W3c-B1 must contain the exact eight W3c-A targets")
    if execution_manifest.get("maximum_target_msa_queries") != 8:
        _failure(failures, "query_budget_invalid", "W3c-B1 must remain capped at eight MSA queries")
    if float(execution_manifest.get("maximum_a40_gpu_hours") or 0.0) != 8.0:
        _failure(failures, "gpu_budget_invalid", "W3c-B1 must remain capped at eight A40 GPU-hours")
    if (
        execution_manifest.get("target_msa_queries_authorized") != 0
        or execution_manifest.get("proteinmpnn_designs_authorized") != 0
        or execution_manifest.get("predictor_evaluations_authorized") != 0
        or execution_manifest.get("approval_recorded") is not False
        or execution_manifest.get("submission_performed") is not False
        or execution_manifest.get("no_submit") is not True
        or execution_manifest.get("cayuga_submission_allowed") is not False
    ):
        _failure(failures, "execution_authority_leak", "W3c-B1 packet inputs must remain no-submit")

    existing_msas = [
        str(row["target_msa"])
        for row in target_rows
        if isinstance(row.get("target_msa"), str) and os.path.exists(str(row["target_msa"]))
    ]
    if existing_msas:
        _failure(
            failures,
            "preexisting_target_msa",
            "target-MSA outputs already exist; adjudicate provenance before creating an initial packet",
        )
    if os.path.exists(receipt_path):
        _failure(failures, "preexisting_receipt", f"submission receipt already exists: {receipt_path}")

    bound_artifacts: Dict[str, Dict[str, Any]] = {}
    for name, path in runtime_bindings.items():
        try:
            bound_artifacts[name] = _binding(path)
        except ValueError as exc:
            _failure(failures, f"{name}_missing", str(exc))

    wrapper_text = ""
    if not os.path.isfile(wrapper_path) or os.path.getsize(wrapper_path) <= 0:
        _failure(failures, "wrapper_missing", f"guarded wrapper is missing: {wrapper_path}")
    else:
        with open(wrapper_path) as handle:
            wrapper_text = handle.read()
    if wrapper_text:
        if APPROVAL_ENV not in wrapper_text or APPROVAL_TOKEN not in wrapper_text:
            _failure(failures, "wrapper_approval_identity_mismatch", "wrapper lacks the exact approval guard")
        for name, binding in bound_artifacts.items():
            marker = f'EXPECTED_{name.upper()}_SHA256="{binding["sha256"]}"'
            if marker not in wrapper_text:
                _failure(
                    failures,
                    f"wrapper_{name}_hash_mismatch",
                    f"wrapper does not bind the current {name} hash",
                )
        for forbidden in ("generate_proteinmpnn", "run_predict_boltz", "predict_af2"):
            if forbidden in wrapper_text.lower():
                _failure(failures, "wrapper_scope_expanded", f"forbidden command surface: {forbidden}")

    plan_path = runtime_bindings.get("plan")
    plan_text = ""
    if isinstance(plan_path, str) and os.path.isfile(plan_path):
        with open(plan_path) as handle:
            plan_text = handle.read()
    if plan_text:
        if f"TARGET_MSA_PRECOMPUTE_MANIFEST={execution_manifest_path}" not in plan_text:
            _failure(failures, "plan_manifest_path_mismatch", "MSA plan uses a different manifest")
        if _sha256(execution_manifest_path) not in plan_text:
            _failure(failures, "plan_manifest_hash_mismatch", "MSA plan lacks the execution-manifest hash")
        if plan_text.count("sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch") != 8:
            _failure(failures, "plan_query_count_invalid", "MSA plan must contain exactly eight sbatch calls")
        for target_id in TARGET_IDS:
            if target_id not in plan_text:
                _failure(failures, "plan_target_missing", f"MSA plan omits {target_id}")

    sbatch_path = runtime_bindings.get("precompute_sbatch")
    sbatch_text = ""
    if isinstance(sbatch_path, str) and os.path.isfile(sbatch_path):
        with open(sbatch_path) as handle:
            sbatch_text = handle.read()
    if (
        "#SBATCH --gres=gpu:a40:1" not in sbatch_text
        or f"#SBATCH --time={SLURM_TIME}" not in sbatch_text
    ):
        _failure(failures, "slurm_budget_drift", "precompute sbatch is not locked to one A40 for one hour")

    ready = not failures
    source_bindings = [
        {
            "target_id": row["id"],
            "source_pdb": row["source_pdb"],
            "source_pdb_sha256": row["source_pdb_sha256"],
            "target_chain": row["target_chain"],
            "target_sequence_sha256": row["target_sequence_sha256"],
            "target_fasta": row["target_fasta"],
            "target_msa": row["target_msa"],
            "target_msa_report": row["target_msa_report"],
        }
        for row in target_rows
    ]
    return {
        "artifact": "m6d_w3c_b1_target_msa_approval_packet",
        "version": 1,
        "status": (
            "w3c_b1_packet_prepared_cayuga_no_submit_validation_required"
            if ready
            else "w3c_b1_target_msa_approval_packet_blocked"
        ),
        "approval_packet_ready": ready,
        "approval_recorded": False,
        "submission_performed": False,
        "explicit_approval_required": True,
        "required_user_phrase": APPROVAL_PHRASE,
        "approval_env_var": APPROVAL_ENV,
        "approval_env_value": APPROVAL_TOKEN,
        "submit_command_if_approved": f"{APPROVAL_ENV}={APPROVAL_TOKEN} bash {wrapper_path}",
        "bound_artifacts": bound_artifacts,
        "wrapper": {
            "path": wrapper_path,
            "sha256": _sha256(wrapper_path) if wrapper_text else None,
        },
        "target_count": len(target_ids),
        "target_ids": target_ids,
        "target_source_bindings": source_bindings,
        "maximum_target_msa_queries": 8,
        "maximum_a40_gpu_hours": 8.0,
        "slurm_time_per_query": SLURM_TIME,
        "target_msa_queries_authorized_by_this_packet": 0,
        "target_msa_queries_if_explicitly_approved": 8,
        "can_submit_target_msa_if_explicitly_approved": ready,
        "cayuga_no_submit_validation_required": True,
        "cayuga_no_submit_validation_status": "not_run",
        "ready_to_request_exact_approval": False,
        "can_submit_proteinmpnn": False,
        "can_submit_structure_predictors": False,
        "can_prepare_w3c_b2": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "receipt_path": receipt_path,
        "receipt_exists": os.path.exists(receipt_path),
        "preexisting_target_msa_paths": existing_msas,
        "failures": failures,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "claim_boundary": (
            "This no-submit packet can authorize exactly eight target-MSA input-prep queries only after "
            "the exact approval phrase. It never authorizes ProteinMPNN, either structure predictor, "
            "W3c-B2 preparation, or any scientific claim."
        ),
        "next_action": (
            "Mirror the packet-bound artifacts to Cayuga and run the guarded wrapper in dry-run mode. "
            f"Only after hash parity and zero-submit behavior pass should the exact phrase "
            f"'{APPROVAL_PHRASE}' be requested."
        ),
    }


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# M6d W3c-B1 target-MSA approval packet",
        "",
        f"Status: `{packet['status']}`.",
        f"Approval packet ready: `{packet['approval_packet_ready']}`.",
        f"No submit: `{packet['no_submit']}`.",
        "",
        "## Scope",
        "",
        f"- targets: `{packet['target_count']}`",
        f"- target-MSA queries authorized now: `{packet['target_msa_queries_authorized_by_this_packet']}`",
        f"- target-MSA queries after exact approval: `{packet['target_msa_queries_if_explicitly_approved']}`",
        f"- maximum A40 GPU-hours: `{packet['maximum_a40_gpu_hours']}`",
        f"- ProteinMPNN allowed: `{packet['can_submit_proteinmpnn']}`",
        f"- structure predictors allowed: `{packet['can_submit_structure_predictors']}`",
        f"- Cayuga no-submit validation: `{packet['cayuga_no_submit_validation_status']}`",
        f"- ready to request exact approval: `{packet['ready_to_request_exact_approval']}`",
        "",
        "## Exact approval",
        "",
        f"Required user phrase: `{packet['required_user_phrase']}`",
        "",
        "Command only after that exact approval:",
        "",
        "```bash",
        str(packet["submit_command_if_approved"]),
        "```",
        "",
        "## Claim boundary",
        "",
        str(packet["claim_boundary"]),
        "",
    ]
    if packet["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(
            f"- `{row['kind']}`: {row['message']}" for row in packet["failures"]
        )
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locked-manifest", default="configs/m6d_w3c_fresh_targets.json")
    parser.add_argument("--fresh-target-lock", default="results/m6d_w3c_fresh_target_lock.json")
    parser.add_argument("--protocol", default="configs/m6d_w3c_validity_first_protocol.json")
    parser.add_argument(
        "--execution-manifest",
        default="configs/m6d_w3c_b1_target_msa_manifest.json",
    )
    parser.add_argument("--emit-execution-manifest", action="store_true")
    parser.add_argument("--plan", default="results/m6d_w3c_b1_target_msas.sh")
    parser.add_argument(
        "--manifest-audit",
        default="results/m6d_w3c_b1_target_manifest_pre_msa.json",
    )
    parser.add_argument(
        "--preflight",
        default="src/bio_sfm_designer/experiments/m6d_w3c_b1_target_msa_preflight.py",
    )
    parser.add_argument("--precompute-sbatch", default="hpc/run_precompute_boltz_target_msa.sbatch")
    parser.add_argument("--precompute-python", default="hpc/precompute_boltz_target_msa.py")
    parser.add_argument("--prep-heterodimer", default="hpc/prep_hetdimer.py")
    parser.add_argument("--extract-chain-fasta", default="hpc/extract_chain_fasta.py")
    parser.add_argument("--structure-fixture", default="tests/fixtures/m6d_w3c_fresh_structure_fixture.json")
    parser.add_argument(
        "--historical-overlap-registry",
        default="configs/m6d_w3c_historical_overlap_registry.json",
    )
    parser.add_argument("--wrapper", default="hpc/run_w3c_b1_target_msa_guarded.sh")
    parser.add_argument("--receipt", default="results/m6d_w3c_b1_target_msa_receipt.jsonl")
    parser.add_argument(
        "--out-json",
        default="results/m6d_w3c_b1_target_msa_approval_packet.json",
    )
    parser.add_argument(
        "--out-md",
        default="results/m6d_w3c_b1_target_msa_approval_packet.md",
    )
    args = parser.parse_args(argv)

    locked_manifest = _load_json(args.locked_manifest)
    fresh_lock = _load_json(args.fresh_target_lock)
    protocol = _load_json(args.protocol)
    if args.emit_execution_manifest:
        manifest = build_execution_manifest(
            locked_manifest,
            fresh_lock,
            protocol,
            locked_manifest_path=args.locked_manifest,
            fresh_lock_path=args.fresh_target_lock,
            protocol_path=args.protocol,
        )
        _write(args.execution_manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.execution_manifest}")
        return 0

    _normalize_manifest_audit(args.manifest_audit, args.execution_manifest)
    runtime_bindings = {
        "locked_manifest": args.locked_manifest,
        "fresh_target_lock": args.fresh_target_lock,
        "protocol": args.protocol,
        "execution_manifest": args.execution_manifest,
        "structure_fixture": args.structure_fixture,
        "historical_overlap_registry": args.historical_overlap_registry,
        "plan": args.plan,
        "preflight": args.preflight,
        "precompute_sbatch": args.precompute_sbatch,
        "precompute_python": args.precompute_python,
        "prep_heterodimer": args.prep_heterodimer,
        "extract_chain_fasta": args.extract_chain_fasta,
    }
    packet = build_packet(
        locked_manifest,
        fresh_lock,
        protocol,
        _load_json(args.execution_manifest),
        locked_manifest_path=args.locked_manifest,
        fresh_lock_path=args.fresh_target_lock,
        protocol_path=args.protocol,
        execution_manifest_path=args.execution_manifest,
        runtime_bindings=runtime_bindings,
        wrapper_path=args.wrapper,
        receipt_path=args.receipt,
    )
    _write(args.out_json, json.dumps(packet, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(packet))
    print(
        f"status={packet['status']} ready={packet['approval_packet_ready']} "
        f"no_submit={packet['no_submit']}"
    )
    return 0 if packet["approval_packet_ready"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
