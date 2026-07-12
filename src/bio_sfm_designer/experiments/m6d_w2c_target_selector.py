"""Select eight label-blind W2c targets after historical and W2b exclusion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _target_id(row: Dict[str, Any]) -> str:
    return str(row.get("id") or row.get("complex_target_id") or "")


def _source_id(row: Dict[str, Any]) -> str:
    return str(row.get("rcsb_id") or "").upper()


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


def _historical_exclusions(registry: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    targets: Set[str] = set()
    sources: Set[str] = set()
    for row in registry.get("targets", []):
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "")
        if target_id:
            targets.add(target_id)
        for source in row.get("source_rcsb_ids", []):
            if str(source):
                sources.add(str(source).upper())
    return targets, sources


def _predecessor_exclusions(manifest: Dict[str, Any]) -> Tuple[Set[str], Set[str], Set[str]]:
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
        fasta = row.get("target_fasta")
        if isinstance(fasta, str) and os.path.isfile(fasta):
            sequences.add(hashlib.sha256(_fasta_sequence(fasta).encode("ascii")).hexdigest())
    return targets, sources, sequences


def select_targets(
    representative_manifest: Dict[str, Any],
    protocol: Dict[str, Any],
    historical_registry: Dict[str, Any],
    predecessor_manifest: Dict[str, Any],
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    n_targets = int(locked["fresh_target_contract"]["n_initial_targets"])
    rows = [row for row in representative_manifest.get("targets", []) if isinstance(row, dict)]
    if len(rows) < n_targets:
        raise ValueError(f"need at least {n_targets} representative targets, got {len(rows)}")

    target_ids = [_target_id(row) for row in rows]
    source_ids = [_source_id(row) for row in rows]
    if any(not value for value in target_ids) or len(target_ids) != len(set(target_ids)):
        raise ValueError("representative target ids must be non-empty and unique")
    if any(not value for value in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("representative source RCSB ids must be non-empty and unique")

    historical_targets, historical_sources = _historical_exclusions(historical_registry)
    predecessor_targets, predecessor_sources, predecessor_sequences = _predecessor_exclusions(
        predecessor_manifest
    )
    required_input_fields = (
        "source_pdb",
        "prepared_pdb",
        "prep_report",
        "target_fasta",
        "target_fasta_report",
    )
    protocol_digest = _canonical_digest(locked)
    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    seen_sequence_hashes: Set[str] = set()
    for row in rows:
        target_id = _target_id(row)
        source_id = _source_id(row)
        reasons: List[str] = []
        if target_id in historical_targets:
            reasons.append("historical_target_overlap")
        if source_id in historical_sources:
            reasons.append("historical_source_overlap")
        if target_id in predecessor_targets:
            reasons.append("w2b_target_overlap")
        if source_id in predecessor_sources:
            reasons.append("w2b_source_overlap")
        missing_inputs = [
            field for field in required_input_fields
            if not isinstance(row.get(field), str)
            or not os.path.isfile(str(row[field]))
            or os.path.getsize(str(row[field])) <= 0
        ]
        if missing_inputs:
            reasons.append("missing_structural_or_fasta_input")
        sequence_hash: Optional[str] = None
        if not missing_inputs:
            sequence = _fasta_sequence(str(row["target_fasta"]))
            sequence_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            if sequence_hash in predecessor_sequences:
                reasons.append("w2b_sequence_overlap")
            if sequence_hash in seen_sequence_hashes:
                reasons.append("candidate_sequence_duplicate")
            seen_sequence_hashes.add(sequence_hash)
        candidate = {
            **row,
            "target_sequence_sha256": sequence_hash,
            "selection_input_origin": "w2b_unselected_label_blind_representative_pool",
            "w2c_out_root": f"hpc_outputs/m6d_w2c_records/{target_id}",
        }
        if reasons:
            excluded.append({
                "target_id": target_id,
                "source_rcsb_id": source_id,
                "reasons": sorted(set(reasons)),
            })
        else:
            eligible.append(candidate)

    if len(eligible) < n_targets:
        raise ValueError(f"only {len(eligible)} W2c-eligible representatives remain; need {n_targets}")
    ranked = sorted(
        (
            hashlib.sha256(f"{protocol_digest}:{_target_id(row)}".encode("utf-8")).hexdigest(),
            _target_id(row),
            row,
        )
        for row in eligible
    )
    selected = ranked[:n_targets]
    selected_rows = [row for _, _, row in selected]
    selected_target_ids = [target_id for _, target_id, _ in selected]
    selected_sources = [_source_id(row) for row in selected_rows]
    selected_sequences = [str(row["target_sequence_sha256"]) for row in selected_rows]
    if len(set(selected_sources)) != n_targets or len(set(selected_sequences)) != n_targets:
        raise ValueError("selected W2c targets must have unique sources and target sequences")

    ranking = [
        {"rank": rank, "target_id": target_id, "selection_hash": selection_hash}
        for rank, (selection_hash, target_id, _) in enumerate(selected, 1)
    ]
    defaults = dict(representative_manifest.get("defaults") or {})
    defaults["num_seq"] = int(locked["fit_design"]["threshold_learning"]["records_per_target"])
    missing_msa_targets = [
        _target_id(row) for row in selected_rows
        if not isinstance(row.get("target_msa"), str)
        or not os.path.isfile(str(row["target_msa"]))
        or os.path.getsize(str(row["target_msa"])) <= 0
        or not isinstance(row.get("target_msa_report"), str)
        or not os.path.isfile(str(row["target_msa_report"]))
        or os.path.getsize(str(row["target_msa_report"])) <= 0
    ]
    return {
        "report": {
            "artifact": "m6d_w2c_target_selector",
            "status": "w2c_fresh_targets_selected_awaiting_msa_no_submit",
            "audit_ok": True,
            "locked_scientific_digest": protocol_digest,
            "selection_rule": "ascending sha256(locked_scientific_digest + ':' + target_id)",
            "n_representative_candidates": len(rows),
            "n_historical_registry_targets": len(historical_targets),
            "n_w2b_predecessor_targets": len(predecessor_targets),
            "n_eligible_after_exclusion": len(eligible),
            "n_selected": len(selected_rows),
            "selected_target_ids": selected_target_ids,
            "selected_source_rcsb_ids": selected_sources,
            "ranking": ranking,
            "excluded": excluded,
            "label_data_consumed": False,
            "predictor_records_consumed": False,
            "registry_fields_consumed": ["target_id", "source_rcsb_ids"],
            "input_reuse_scope": "label_blind_structural_input_prep_only_no_W2b_candidate_or_predictor_rows",
            "missing_target_msa_targets": missing_msa_targets,
            "target_msa_precompute_needed": bool(missing_msa_targets),
            "ready_for_cayuga_record_generation": False,
            "ready_for_cayuga_submission": False,
            "can_claim_w2c": False,
            "next_action": (
                "Precompute and hash-lock target MSAs for the eight selected targets under a separate "
                "guarded no-record-generation approval boundary."
            ),
        },
        "manifest": {
            "artifact": "m6d_w2c_fresh_target_manifest",
            "status": "selected_awaiting_target_msa_no_submit",
            "source_manifest": "configs/m6d_w2b_target_adaptive_cluster_representatives.json",
            "source_reuse_boundary": "unselected_label_blind_structural_inputs_only",
            "locked_scientific_digest": protocol_digest,
            "selection_rule": "ascending sha256(locked_scientific_digest + ':' + target_id)",
            "defaults": defaults,
            "representative_target_ids": selected_target_ids,
            "targets": selected_rows,
            "cayuga_submission_allowed": False,
        },
    }


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
    parser.add_argument("--protocol", default="configs/m6d_w2c_one_shot_protocol.json")
    parser.add_argument(
        "--historical-registry",
        default="configs/m6d_w2_historical_target_registry.json",
    )
    parser.add_argument(
        "--predecessor-manifest",
        default="configs/m6d_w2b_target_adaptive_fit_targets.json",
    )
    parser.add_argument("--out-json", default="results/m6d_w2c_target_selection.json")
    parser.add_argument("--out-manifest", default="configs/m6d_w2c_fresh_targets.json")
    args = parser.parse_args(argv)
    output = select_targets(
        _load_json(args.representative_manifest),
        _load_json(args.protocol),
        _load_json(args.historical_registry),
        _load_json(args.predecessor_manifest),
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
