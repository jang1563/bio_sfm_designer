"""Select a label-blind W2b fit panel from sequence-cluster representatives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional


_LOCKED_SELECTION_FIELDS = (
    "objective",
    "claim_scope",
    "fresh_target_contract",
    "generation_stages",
    "fit_stage_rule",
    "certification_rule",
    "panel_decision_rule",
    "compute_budget",
    "post_hoc_changes_forbidden",
)


def _canonical_digest(value: Dict[str, Any]) -> str:
    locked = {key: value[key] for key in _LOCKED_SELECTION_FIELDS if key in value}
    missing = sorted(set(_LOCKED_SELECTION_FIELDS) - set(locked))
    if missing:
        raise ValueError(f"protocol missing locked selection fields: {missing}")
    payload = json.dumps(locked, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _target_id(row: Dict[str, Any]) -> str:
    return str(row.get("id") or row.get("complex_target_id") or "")


def select_targets(
    representative_manifest: Dict[str, Any],
    protocol: Dict[str, Any],
) -> Dict[str, Any]:
    rows = [row for row in representative_manifest.get("targets", []) if isinstance(row, dict)]
    n_targets = int(protocol["fresh_target_contract"]["n_initial_targets"])
    fit_stage = protocol["generation_stages"]["fit"]
    if len(rows) < n_targets:
        raise ValueError(f"need at least {n_targets} representative targets, got {len(rows)}")
    target_ids = [_target_id(row) for row in rows]
    if any(not value for value in target_ids) or len(target_ids) != len(set(target_ids)):
        raise ValueError("representative target ids must be present and unique")
    source_ids = [str(row.get("rcsb_id") or "").upper() for row in rows]
    if any(not value for value in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("representative source RCSB ids must be present and unique")

    protocol_digest = _canonical_digest(protocol)
    ranked = sorted(
        (
            hashlib.sha256(f"{protocol_digest}:{_target_id(row)}".encode("utf-8")).hexdigest(),
            _target_id(row),
            row,
        )
        for row in rows
    )
    selected = ranked[:n_targets]
    selected_rows = []
    ranking = []
    for rank, (score, target_id, row) in enumerate(selected, 1):
        selected_rows.append({
            **row,
            "w2b_stage": "fit",
            "w2b_seed_namespace": fit_stage["seed_namespace"],
        })
        ranking.append({"rank": rank, "target_id": target_id, "selection_hash": score})
    defaults = dict(representative_manifest.get("defaults") or {})
    defaults["num_seq"] = int(fit_stage["records_per_target"])
    return {
        "report": {
            "artifact": "m6d_w2b_target_selector",
            "status": "w2b_fresh_fit_manifest_selected_not_compute_authority",
            "audit_ok": True,
            "protocol_sha256": protocol_digest,
            "selection_rule": "ascending sha256(locked_scientific_protocol_sha256 + ':' + target_id)",
            "protocol_digest_fields": list(_LOCKED_SELECTION_FIELDS),
            "n_representative_candidates": len(rows),
            "n_selected": len(selected_rows),
            "selected_target_ids": [row["target_id"] for row in ranking],
            "selected_source_rcsb_ids": [str(row["rcsb_id"]).upper() for row in selected_rows],
            "ranking": ranking,
            "label_data_consumed": False,
            "ready_for_target_msa_precompute": False,
            "ready_for_cayuga_submission": False,
            "can_claim_w2b": False,
            "next_action": "run historical overlap and strict pre-MSA manifest audits on the selected fit manifest",
        },
        "manifest": {
            "_note": (
                "W2b label-blind fresh fit panel selected from sequence-cluster representatives. "
                "This is pre-MSA planning evidence and not Cayuga submission authority."
            ),
            "source_manifest": representative_manifest.get("source_manifest"),
            "protocol_sha256": protocol_digest,
            "selection_rule": "ascending sha256(locked_scientific_protocol_sha256 + ':' + target_id)",
            "protocol_digest_fields": list(_LOCKED_SELECTION_FIELDS),
            "defaults": defaults,
            "representative_target_ids": [row["target_id"] for row in ranking],
            "w2b_stage": "fit",
            "w2b_seed_namespace": fit_stage["seed_namespace"],
            "targets": selected_rows,
        },
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representative-manifest", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-manifest", required=True)
    args = parser.parse_args(argv)
    output = select_targets(
        _load_json(args.representative_manifest),
        _load_json(args.protocol),
    )
    _write_json(args.out_json, output["report"])
    _write_json(args.out_manifest, output["manifest"])
    print(
        f"status={output['report']['status']} selected={output['report']['n_selected']} "
        f"cayuga={output['report']['ready_for_cayuga_submission']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
