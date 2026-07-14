"""Select and role-assign fresh W3b targets without consuming outcome labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _target_id(row: Dict[str, Any]) -> str:
    return str(row.get("id") or row.get("complex_target_id") or "")


def _source_id(row: Dict[str, Any]) -> str:
    return str(row.get("rcsb_id") or row.get("source_rcsb_id") or "").upper()


def _fasta_sequence(path: str) -> str:
    parts: List[str] = []
    with open(path) as handle:
        for line in handle:
            text = line.strip()
            if text and not text.startswith(">"):
                parts.append(text)
    sequence = "".join(parts).replace(" ", "").upper()
    if not sequence or not sequence.isalpha():
        raise ValueError(f"invalid FASTA sequence in {path}")
    return sequence


def _manifest_exclusions(manifest: Dict[str, Any]) -> Tuple[Set[str], Set[str], Set[str]]:
    targets: Set[str] = set()
    sources: Set[str] = set()
    sequences: Set[str] = set()
    for row in manifest.get("targets", []):
        if not isinstance(row, dict):
            continue
        target_id = _target_id(row)
        source_id = _source_id(row)
        if target_id:
            targets.add(target_id)
        if source_id:
            sources.add(source_id)
        sequence_sha = row.get("target_sequence_sha256")
        if isinstance(sequence_sha, str) and sequence_sha:
            sequences.add(sequence_sha)
        fasta = row.get("target_fasta")
        if isinstance(fasta, str) and os.path.isfile(fasta):
            sequence = _fasta_sequence(fasta)
            sequences.add(hashlib.sha256(sequence.encode("ascii")).hexdigest())
    return targets, sources, sequences


def _historical_exclusions(registry: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    targets: Set[str] = set()
    sources: Set[str] = set()
    for row in registry.get("targets", []):
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "")
        if target_id:
            targets.add(target_id)
        sources.update(str(value).upper() for value in row.get("source_rcsb_ids", []) if value)
    return targets, sources


def _w3_exclusions(protocol: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    targets: Set[str] = set()
    sources: Set[str] = set()
    for row in protocol.get("rows", []):
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("complex_target_id") or "")
        if not target_id:
            continue
        targets.add(target_id)
        sources.add(target_id.split("_", 1)[0].upper())
    return targets, sources


def select_targets(
    representative_manifest: Dict[str, Any],
    protocol: Dict[str, Any],
    historical_registry: Dict[str, Any],
    w2b_manifest: Dict[str, Any],
    w2c_manifest: Dict[str, Any],
    w3_protocol: Dict[str, Any],
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    contract = locked.get("fresh_target_contract", {})
    role_counts = {
        "fit": int(contract.get("n_fit_targets") or 0),
        "certification": int(contract.get("n_certification_targets") or 0),
        "held_out_test": int(contract.get("n_held_out_test_targets") or 0),
    }
    n_targets = int(contract.get("n_initial_targets") or 0)
    if sum(role_counts.values()) != n_targets or min(role_counts.values()) <= 0:
        raise ValueError("W3b role counts must be positive and sum to n_initial_targets")

    rows = [row for row in representative_manifest.get("targets", []) if isinstance(row, dict)]
    target_ids = [_target_id(row) for row in rows]
    source_ids = [_source_id(row) for row in rows]
    if any(not value for value in target_ids) or len(target_ids) != len(set(target_ids)):
        raise ValueError("representative target ids must be non-empty and unique")
    if any(not value for value in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("representative source ids must be non-empty and unique")

    historical_targets, historical_sources = _historical_exclusions(historical_registry)
    w2b_targets, w2b_sources, w2b_sequences = _manifest_exclusions(w2b_manifest)
    w2c_targets, w2c_sources, w2c_sequences = _manifest_exclusions(w2c_manifest)
    w3_targets, w3_sources = _w3_exclusions(w3_protocol)
    required_inputs = (
        "source_pdb",
        "prepared_pdb",
        "prep_report",
        "target_fasta",
        "target_fasta_report",
    )
    digest = canonical_digest(locked)
    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    seen_sequences: Set[str] = set()

    for row in rows:
        target_id = _target_id(row)
        source_id = _source_id(row)
        reasons: List[str] = []
        if target_id in historical_targets:
            reasons.append("historical_target_overlap")
        if source_id in historical_sources:
            reasons.append("historical_source_overlap")
        if target_id in w2b_targets:
            reasons.append("w2b_target_overlap")
        if source_id in w2b_sources:
            reasons.append("w2b_source_overlap")
        if target_id in w2c_targets:
            reasons.append("w2c_target_overlap")
        if source_id in w2c_sources:
            reasons.append("w2c_source_overlap")
        if target_id in w3_targets:
            reasons.append("w3_target_overlap")
        if source_id in w3_sources:
            reasons.append("w3_source_overlap")
        missing = [
            field
            for field in required_inputs
            if not isinstance(row.get(field), str)
            or not os.path.isfile(str(row[field]))
            or os.path.getsize(str(row[field])) <= 0
        ]
        if missing:
            reasons.append("missing_structural_or_fasta_input")

        sequence_sha: Optional[str] = None
        if not missing:
            sequence = _fasta_sequence(str(row["target_fasta"]))
            sequence_sha = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            if sequence_sha in w2b_sequences:
                reasons.append("w2b_sequence_overlap")
            if sequence_sha in w2c_sequences:
                reasons.append("w2c_sequence_overlap")
            if sequence_sha in seen_sequences:
                reasons.append("candidate_sequence_duplicate")
            seen_sequences.add(sequence_sha)

        candidate = {
            **row,
            "selection_input_origin": "unused_label_blind_representative_pool",
            "target_sequence_sha256": sequence_sha,
            "w3b_out_root": f"hpc_outputs/m6d_w3b_disagreement_records/{target_id}",
        }
        if reasons:
            excluded.append({
                "reasons": sorted(set(reasons)),
                "source_rcsb_id": source_id,
                "target_id": target_id,
            })
        else:
            eligible.append(candidate)

    if len(eligible) < n_targets:
        raise ValueError(f"only {len(eligible)} W3b-eligible targets remain; need {n_targets}")

    selected_ranked = sorted(
        (
            hashlib.sha256(f"{digest}:select:{_target_id(row)}".encode("utf-8")).hexdigest(),
            _target_id(row),
            row,
        )
        for row in eligible
    )[:n_targets]
    role_ranked = sorted(
        (
            hashlib.sha256(f"{digest}:role:{target_id}".encode("utf-8")).hexdigest(),
            target_id,
            selection_hash,
            row,
        )
        for selection_hash, target_id, row in selected_ranked
    )

    role_sequence: List[str] = []
    for role in ("fit", "certification", "held_out_test"):
        role_sequence.extend([role] * role_counts[role])
    selected_rows: List[Dict[str, Any]] = []
    ranking: List[Dict[str, Any]] = []
    for rank, ((role_hash, target_id, selection_hash, row), role) in enumerate(
        zip(role_ranked, role_sequence), 1
    ):
        enriched = {
            **row,
            "experimental_role": role,
            "role_rank": rank,
            "role_selection_hash": role_hash,
            "selection_hash": selection_hash,
        }
        selected_rows.append(enriched)
        ranking.append({
            "experimental_role": role,
            "rank": rank,
            "role_selection_hash": role_hash,
            "selection_hash": selection_hash,
            "target_id": target_id,
        })

    selected_sources = [_source_id(row) for row in selected_rows]
    selected_sequences = [str(row["target_sequence_sha256"]) for row in selected_rows]
    if len(set(selected_sources)) != n_targets or len(set(selected_sequences)) != n_targets:
        raise ValueError("W3b targets must have unique sources and target sequences")

    missing_msa_targets = [
        _target_id(row)
        for row in selected_rows
        if not isinstance(row.get("target_msa"), str)
        or not os.path.isfile(str(row["target_msa"]))
        or os.path.getsize(str(row["target_msa"])) <= 0
        or not isinstance(row.get("target_msa_report"), str)
        or not os.path.isfile(str(row["target_msa_report"]))
        or os.path.getsize(str(row["target_msa_report"])) <= 0
    ]
    records_by_role = {
        "fit": int(locked["fit_design"]["records_per_target"]),
        "certification": int(locked["certification_design"]["records_per_target"]),
        "held_out_test": int(locked["held_out_test_design"]["records_per_target"]),
    }
    defaults = dict(representative_manifest.get("defaults") or {})
    defaults["num_seq_by_role"] = records_by_role

    report = {
        "artifact": "m6d_w3b_target_selector",
        "audit_ok": True,
        "excluded": excluded,
        "input_reuse_scope": contract.get("input_reuse_scope"),
        "label_data_consumed": False,
        "locked_scientific_digest": digest,
        "missing_target_msa_targets": missing_msa_targets,
        "n_eligible_after_exclusion": len(eligible),
        "n_representative_candidates": len(rows),
        "n_selected": len(selected_rows),
        "predictor_records_consumed": False,
        "ranking": ranking,
        "ready_for_cayuga_submission": False,
        "role_counts": role_counts,
        "role_selection_rule": "ascending sha256(locked_scientific_digest + ':role:' + target_id)",
        "selected_source_rcsb_ids": selected_sources,
        "selected_target_ids": [_target_id(row) for row in selected_rows],
        "selection_rule": "ascending sha256(locked_scientific_digest + ':select:' + target_id)",
        "status": "w3b_fresh_targets_selected_awaiting_msa_no_submit",
        "target_msa_precompute_needed": bool(missing_msa_targets),
    }
    manifest = {
        "artifact": "m6d_w3b_fresh_target_manifest",
        "cayuga_submission_allowed": False,
        "defaults": defaults,
        "label_data_consumed": False,
        "locked_scientific_digest": digest,
        "predictor_records_consumed": False,
        "role_selection_rule": report["role_selection_rule"],
        "selection_rule": report["selection_rule"],
        "source_manifest": "configs/m6d_w2b_target_adaptive_cluster_representatives.json",
        "source_reuse_boundary": contract.get("input_reuse_scope"),
        "status": "selected_awaiting_target_msa_no_submit",
        "targets": selected_rows,
    }
    return {"manifest": manifest, "report": report}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--representative-manifest",
        default="configs/m6d_w2b_target_adaptive_cluster_representatives.json",
    )
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument(
        "--historical-registry",
        default="configs/m6d_w2_historical_target_registry.json",
    )
    parser.add_argument(
        "--w2b-manifest",
        default="configs/m6d_w2b_target_adaptive_fit_targets.json",
    )
    parser.add_argument("--w2c-manifest", default="configs/m6d_w2c_fresh_targets.json")
    parser.add_argument("--w3-protocol", default="configs/m6d_w3_mechanism_panel_protocol.json")
    parser.add_argument("--out-json", default="results/m6d_w3b_target_selection.json")
    parser.add_argument("--out-manifest", default="configs/m6d_w3b_fresh_targets.json")
    args = parser.parse_args(argv)
    output = select_targets(
        _load_json(args.representative_manifest),
        _load_json(args.protocol),
        _load_json(args.historical_registry),
        _load_json(args.w2b_manifest),
        _load_json(args.w2c_manifest),
        _load_json(args.w3_protocol),
    )
    _write_json(args.out_json, output["report"])
    _write_json(args.out_manifest, output["manifest"])
    print(
        f"status={output['report']['status']} selected={output['report']['n_selected']} "
        f"eligible={output['report']['n_eligible_after_exclusion']} "
        f"msa_missing={len(output['report']['missing_target_msa_targets'])}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
