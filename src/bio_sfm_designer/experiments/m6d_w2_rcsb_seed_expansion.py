"""Build a reproducible RCSB source-seed expansion for W2 redesign.

This is a no-GPU planning step. It queries or replays the RCSB Search API for
entry IDs, removes current-protocol failed/held sources and already-screened
seed sources, and emits a seed config for local structural intake.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


RCSB_SEARCH_ENDPOINT = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_SEARCH_DOCS = "https://search.rcsb.org/"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _upper_ids(values: Iterable[Any]) -> List[str]:
    out = []
    for value in values:
        if isinstance(value, str) and value.strip():
            out.append(value.strip().upper())
    return sorted(set(out))


def _seed_ids(seed_config: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(seed_config, dict):
        return []
    out = []
    for row in seed_config.get("seeds", []):
        if isinstance(row, str):
            out.append(row)
        elif isinstance(row, dict):
            out.append(row.get("rcsb_id"))
    return _upper_ids(out)


def _rules_excluded_sources(rules: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(rules, dict):
        return []
    explicit = list(rules.get("excluded_source_ids_under_current_protocol", []) or [])
    explicit.extend(list(rules.get("excluded_source_rcsb_ids", []) or []))
    target_derived = [
        str(target).split("_", 1)[0]
        for target in rules.get("excluded_targets_under_current_protocol", []) or []
        if isinstance(target, str)
    ]
    anchors = [
        str(target).split("_", 1)[0]
        for target in rules.get("anchors_not_for_immediate_scale", []) or []
        if isinstance(target, str)
    ]
    positives = [
        str(target).split("_", 1)[0]
        for target in rules.get("positive_controls_not_generalization_targets", []) or []
        if isinstance(target, str)
    ]
    return _upper_ids(explicit + target_derived + anchors + positives)


def build_query(*,
                rows: int = 500,
                min_protein_entities: int = 2,
                max_resolution: float = 3.0) -> Dict[str, Any]:
    return {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.polymer_entity_count_protein",
                        "operator": "greater_or_equal",
                        "value": min_protein_entities,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.resolution_combined",
                        "operator": "less_or_equal",
                        "value": max_resolution,
                    },
                },
            ],
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "paginate": {"start": 0, "rows": rows},
            "sort": [{"sort_by": "score", "direction": "desc"}],
        },
    }


def run_search(query: Dict[str, Any], *, endpoint: str = RCSB_SEARCH_ENDPOINT,
               timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        obj = json.load(response)
    if not isinstance(obj, dict):
        raise ValueError("RCSB response must be a JSON object")
    return obj


def _response_ids(response: Dict[str, Any]) -> List[str]:
    out = []
    for row in response.get("result_set", []) or []:
        if isinstance(row, str):
            out.append(row)
        elif isinstance(row, dict):
            out.append(row.get("identifier"))
    # Preserve response order while removing duplicates.
    seen: Set[str] = set()
    ordered = []
    for value in out:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_seed_expansion(response: Dict[str, Any], *,
                         rules: Optional[Dict[str, Any]] = None,
                         previous_seed_configs: Optional[Sequence[Dict[str, Any]]] = None,
                         max_seeds: int = 80,
                         query: Optional[Dict[str, Any]] = None,
                         date: Optional[str] = None,
                         branch_id: str = "w2_target_family_redesign_v1",
                         min_sequence_clusters: int = 3,
                         max_largest_cluster_fraction: float = 0.5) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    excluded_sources = _rules_excluded_sources(rules)
    already_screened = _upper_ids(
        seed
        for config in previous_seed_configs or []
        for seed in _seed_ids(config)
    )
    excluded = set(excluded_sources).union(already_screened)
    raw_ids = _response_ids(response)
    selected = []
    dropped = []
    for entry_id in raw_ids:
        if entry_id in excluded:
            dropped.append({"rcsb_id": entry_id, "reason": "excluded_or_already_screened_source"})
            continue
        if len(selected) < max_seeds:
            selected.append(entry_id)
        else:
            dropped.append({"rcsb_id": entry_id, "reason": "beyond_max_seeds"})

    seed_config = {
        "_note": (
            "W2 target-family redesign source-seed expansion from RCSB Search API. "
            "This is local/no-spend source intake only and does not authorize target-MSA precompute "
            "or Cayuga ProteinMPNN/Boltz submission."
        ),
        "selection_boundary": {
            "branch_id": branch_id,
            "rcsb_search_endpoint": RCSB_SEARCH_ENDPOINT,
            "rcsb_search_docs": RCSB_SEARCH_DOCS,
            "excluded_current_protocol_sources": excluded_sources,
            "already_screened_seed_sources": already_screened,
            "source_diverse_selection_required": True,
            "sequence_diversity_audit_required_before_msa": True,
            "min_sequence_clusters": min_sequence_clusters,
            "max_largest_cluster_fraction": max_largest_cluster_fraction,
            "cayuga_submission_allowed": False,
            "w2_generalization_claim_supported": False,
        },
        "seeds": [{"rcsb_id": entry_id} for entry_id in selected],
    }

    report = {
        "artifact": "m6d_w2_rcsb_seed_expansion",
        "branch_id": branch_id,
        "date": date or _dt.date.today().isoformat(),
        "status": "seed_expansion_ready_for_local_structural_intake" if selected else "seed_expansion_empty",
        "ready_for_local_structural_intake": bool(selected),
        "ready_for_target_msa_precompute": False,
        "ready_for_cayuga_submission": False,
        "rcsb_search_endpoint": RCSB_SEARCH_ENDPOINT,
        "rcsb_search_docs": RCSB_SEARCH_DOCS,
        "query": query,
        "response_total_count": response.get("total_count"),
        "n_response_ids": len(raw_ids),
        "n_selected_seeds": len(selected),
        "n_dropped": len(dropped),
        "max_seeds": max_seeds,
        "sequence_diversity_preconditions": {
            "audit_required_before_target_msa_precompute": True,
            "min_sequence_clusters": min_sequence_clusters,
            "max_largest_cluster_fraction": max_largest_cluster_fraction,
        },
        "excluded_source_ids": excluded_sources,
        "already_screened_seed_sources": already_screened,
        "selected_seed_ids": selected,
        "dropped_preview": dropped[:50],
        "claim_boundary": {
            "seed_expansion": "source_id_planning_only",
            "w2_multi_target_generalization": "not_supported",
            "sequence_diversity": "must be audited from target FASTA before full-panel MSA spend",
            "target_msa_precompute": "not_authorized_until_local_structural_intake_admits_candidates",
            "cayuga_submission": "not_authorized_until_manifest_require_files_and_completion_paths_pass",
        },
        "next_action": (
            "run local structural intake with --fetch on the emitted seed config"
            if selected else
            "revise RCSB query before structural intake"
        ),
        "can_mark_goal_complete": False,
    }
    return report, seed_config


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 RCSB Seed Expansion",
        "",
        f"Date: {rep.get('date')}",
        f"Branch: `{rep.get('branch_id')}`",
        f"Status: `{rep.get('status')}`",
        f"RCSB total count: {rep.get('response_total_count')}",
        f"Response IDs considered: {rep.get('n_response_ids')}",
        f"Selected seeds: {rep.get('n_selected_seeds')}",
        f"Ready for local structural intake: `{str(bool(rep.get('ready_for_local_structural_intake'))).lower()}`",
        f"Ready for target-MSA precompute: `{str(bool(rep.get('ready_for_target_msa_precompute'))).lower()}`",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`",
        "",
        "## Query Source",
        "",
        f"- endpoint: `{rep.get('rcsb_search_endpoint')}`",
        f"- docs: {rep.get('rcsb_search_docs')}",
        "",
        "## Selected Seeds",
        "",
        ", ".join(rep.get("selected_seed_ids", [])) or "none",
        "",
        "## Claim Boundary",
        "",
        "- This is source-ID planning only.",
        "- It does not support W2 generalization.",
        "- It requires target-sequence diversity audit before full-panel target-MSA precompute.",
        "- It does not authorize target-MSA precompute or Cayuga submission.",
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-rules", default="configs/m6d_w2_target_family_redesign_v1_candidate_rules.json")
    ap.add_argument("--previous-seed-config", action="append", dest="previous_seed_configs", default=None)
    ap.add_argument("--search-response", default=None,
                    help="Replay a saved RCSB search response instead of making a live request")
    ap.add_argument("--rows", type=int, default=500)
    ap.add_argument("--max-seeds", type=int, default=80)
    ap.add_argument("--min-protein-entities", type=int, default=2)
    ap.add_argument("--max-resolution", type=float, default=3.0)
    ap.add_argument("--branch-id", default="w2_target_family_redesign_v1")
    ap.add_argument("--min-sequence-clusters", type=int, default=3)
    ap.add_argument("--max-largest-cluster-fraction", type=float, default=0.5)
    ap.add_argument("--date", default=None)
    ap.add_argument("--out-query", default="results/m6d_w2_target_family_redesign_v1_rcsb_seed_expansion_query.json")
    ap.add_argument("--out-response", default="results/m6d_w2_target_family_redesign_v1_rcsb_seed_expansion_response.json")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v1_rcsb_seed_expansion.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v1_rcsb_seed_expansion.md")
    ap.add_argument("--out-seed-config", default="configs/m6d_w2_target_family_redesign_v1_rcsb_seed_expansion.json")
    args = ap.parse_args(argv)

    query = build_query(
        rows=args.rows,
        min_protein_entities=args.min_protein_entities,
        max_resolution=args.max_resolution,
    )
    response = _load_json(args.search_response) if args.search_response else run_search(query)
    previous_seed_configs = [
        _load_json(path)
        for path in (args.previous_seed_configs or [])
    ]
    rep, seed_config = build_seed_expansion(
        response,
        rules=_load_json(args.candidate_rules) if args.candidate_rules else None,
        previous_seed_configs=previous_seed_configs,
        max_seeds=args.max_seeds,
        query=query,
        date=args.date,
        branch_id=args.branch_id,
        min_sequence_clusters=args.min_sequence_clusters,
        max_largest_cluster_fraction=args.max_largest_cluster_fraction,
    )
    _write_json(args.out_query, query)
    _write_json(args.out_response, response)
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    _write_json(args.out_seed_config, seed_config)
    print(f"wrote {args.out_json}, {args.out_md}, and {args.out_seed_config}")
    print(f"wrote {args.out_query} and {args.out_response}")
    print(
        "status={status} response_ids={response_ids} selected={selected} ready={ready}".format(
            status=rep["status"],
            response_ids=rep["n_response_ids"],
            selected=rep["n_selected_seeds"],
            ready=rep["ready_for_local_structural_intake"],
        )
    )
    return 0 if rep["ready_for_local_structural_intake"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
