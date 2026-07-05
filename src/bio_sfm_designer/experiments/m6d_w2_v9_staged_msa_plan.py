"""Create a no-submit staged target-MSA plan for W2 v9.

The existing W2 v9 approval packet covers the full 14-target target-MSA input
prep. This helper does not submit work. It ranks the v9 representative targets
and emits a smaller pilot manifest so the next approval decision can choose
between full-batch MSA prep and a cheaper staged path.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


DEFAULT_PRIOR_NEGATIVE_PANEL_REPORTS = [
    "results/m6d_w2_fresh_discovery_unique_source_pilot_panel_report.json",
    "results/m6d_w2_expanded_next_branch_panel_report.json",
]


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
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


def _target_id(row: Dict[str, Any]) -> str:
    for key in ("complex_target_id", "target_id", "id", "target"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _source_id(row: Dict[str, Any]) -> str:
    for key in ("rcsb_id", "source_pdb_id", "source_rcsb_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    target = _target_id(row)
    return target.split("_", 1)[0] if "_" in target else target


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _prior_negative_targets(paths: Sequence[str]) -> Tuple[Set[str], Set[str]]:
    targets: Set[str] = set()
    sources: Set[str] = set()
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        report = _load_json(path)
        for row in report.get("targets", []):
            if not isinstance(row, dict):
                continue
            if bool(row.get("certified")):
                continue
            target = _target_id(row)
            targets.add(target)
            sources.add(target.split("_", 1)[0] if "_" in target else _source_id(row))
    return targets, sources


def _cluster_lookup(sequence_diversity: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for cluster in sequence_diversity.get("clusters", []):
        if not isinstance(cluster, dict):
            continue
        cluster_id = int(cluster.get("cluster_id") or 0)
        for target in cluster.get("target_ids", []):
            if isinstance(target, str):
                out[target] = cluster_id
    return out


def _rank_candidate(row: Dict[str, Any],
                    *,
                    cluster_id: Optional[int],
                    prior_negative_targets: Set[str],
                    prior_negative_sources: Set[str]) -> Dict[str, Any]:
    target = _target_id(row)
    source = _source_id(row)
    contacts = _as_float(row.get("ca_interface_contacts"))
    target_len = _as_float(row.get("target_ca_residues"))
    binder_len = _as_float(row.get("binder_ca_residues"))
    seq_identity = _as_float(row.get("chain_sequence_identity"))
    min_distance = _as_float(row.get("min_ca_distance"), default=99.0)

    contact_score = min(contacts / 120.0, 2.0)
    compact_bonus = 0.25 if target_len <= 160 and binder_len <= 150 else 0.0
    short_tail_bonus = 0.10 if min_distance <= 4.5 else 0.0
    length_penalty = max(target_len - 180.0, 0.0) / 100.0 + max(binder_len - 150.0, 0.0) / 100.0
    weak_interface_penalty = 0.35 if contacts < 30 else 0.0
    sequence_identity_penalty = min(seq_identity, 1.0) * 0.4
    prior_target_penalty = 1.0 if target in prior_negative_targets else 0.0
    prior_source_penalty = 0.4 if source in prior_negative_sources else 0.0
    score = (
        contact_score
        + compact_bonus
        + short_tail_bonus
        - length_penalty
        - weak_interface_penalty
        - sequence_identity_penalty
        - prior_target_penalty
        - prior_source_penalty
    )

    reasons = []
    if contacts >= 100:
        reasons.append("high_contact_interface")
    elif contacts >= 40:
        reasons.append("moderate_contact_interface")
    else:
        reasons.append("low_contact_caution")
    if compact_bonus:
        reasons.append("compact_target_binder")
    if weak_interface_penalty:
        reasons.append("interface_contact_floor_risk")
    if prior_target_penalty or prior_source_penalty:
        reasons.append("prior_negative_target_or_source_penalty")
    if length_penalty:
        reasons.append("large_target_or_binder_penalty")

    return {
        "target_id": target,
        "source_pdb_id": source,
        "cluster_id": cluster_id,
        "score": round(score, 6),
        "features": {
            "ca_interface_contacts": contacts,
            "target_ca_residues": target_len,
            "binder_ca_residues": binder_len,
            "chain_sequence_identity": seq_identity,
            "min_ca_distance": min_distance,
        },
        "penalties": {
            "length_penalty": round(length_penalty, 6),
            "weak_interface_penalty": weak_interface_penalty,
            "sequence_identity_penalty": round(sequence_identity_penalty, 6),
            "prior_target_penalty": prior_target_penalty,
            "prior_source_penalty": prior_source_penalty,
        },
        "reasons": reasons,
    }


def _stage_targets(ranking: Sequence[Dict[str, Any]],
                   *,
                   pilot_size: int,
                   expansion_size: int) -> Dict[str, List[str]]:
    ordered = [row["target_id"] for row in ranking]
    pilot = ordered[:pilot_size]
    expansion = ordered[pilot_size:pilot_size + expansion_size]
    full_followup = ordered[pilot_size + expansion_size:]
    return {
        "pilot_target_msa_targets": pilot,
        "expansion_target_msa_targets": expansion,
        "full_followup_targets": full_followup,
    }


def _subset_manifest(full_manifest: Dict[str, Any], target_ids: Iterable[str]) -> Dict[str, Any]:
    target_set = set(target_ids)
    targets = [
        row for row in full_manifest.get("targets", [])
        if isinstance(row, dict) and _target_id(row) in target_set
    ]
    return {
        "_note": (
            "No-submit pilot subset for W2 v9 target-MSA planning. This is not a "
            "ProteinMPNN/Boltz submit plan and does not replace the full v9 approval packet."
        ),
        "defaults": full_manifest.get("defaults", {}),
        "targets": targets,
    }


def build_plan(discovery_pool: Dict[str, Any],
               sequence_diversity: Dict[str, Any],
               followup_contract: Dict[str, Any],
               approval_packet: Dict[str, Any],
               target_manifest: Dict[str, Any],
               *,
               prior_negative_panel_reports: Sequence[str] = DEFAULT_PRIOR_NEGATIVE_PANEL_REPORTS,
               pilot_size: int = 3,
               expansion_size: int = 5,
               pilot_manifest_path: Optional[str] = None) -> Dict[str, Any]:
    selected = [
        row for row in discovery_pool.get("selected_candidates", [])
        if isinstance(row, dict)
    ]
    cluster_by_target = _cluster_lookup(sequence_diversity)
    prior_targets, prior_sources = _prior_negative_targets(prior_negative_panel_reports)

    ranking = [
        _rank_candidate(
            row,
            cluster_id=cluster_by_target.get(_target_id(row)),
            prior_negative_targets=prior_targets,
            prior_negative_sources=prior_sources,
        )
        for row in selected
    ]
    ranking.sort(key=lambda row: (-row["score"], row["target_id"]))
    stages = _stage_targets(ranking, pilot_size=pilot_size, expansion_size=expansion_size)

    failures: List[Dict[str, Any]] = []
    if followup_contract.get("ready_for_cayuga_submission") is not False:
        failures.append({"kind": "contract_submission_boundary_drift"})
    if approval_packet.get("can_submit_proteinmpnn_boltz_panel") is not False:
        failures.append({"kind": "approval_packet_allows_panel_submission"})
    if approval_packet.get("target_count") != len(selected):
        failures.append({
            "kind": "approval_packet_target_count_mismatch",
            "expected": len(selected),
            "observed": approval_packet.get("target_count"),
        })
    if sequence_diversity.get("ok") is not True:
        failures.append({"kind": "sequence_diversity_not_ok"})
    if len(stages["pilot_target_msa_targets"]) < 3:
        failures.append({"kind": "pilot_has_fewer_than_three_targets"})

    pilot_manifest = _subset_manifest(target_manifest, stages["pilot_target_msa_targets"])
    if pilot_manifest_path:
        _write_json(pilot_manifest_path, pilot_manifest)

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_v9_staged_msa_plan",
        "status": "staged_target_msa_plan_ready_no_submit" if audit_ok else "staged_target_msa_plan_blocked",
        "audit_ok": audit_ok,
        "can_mark_goal_complete": False,
        "claim_boundary": {
            "target_msa_input_prep": "not executed; requires explicit approval",
            "proteinmpnn_boltz_panel_submission": "blocked",
            "w2_multi_target_generalization": "not_supported",
            "staged_plan": "decision support only; existing approval packet still covers the full 14-target batch",
        },
        "n_candidates": len(selected),
        "pilot_size": pilot_size,
        "expansion_size": expansion_size,
        "ranking_policy": {
            "prefer": [
                "higher interface contact count",
                "compact target/binder sizes",
                "low sequence identity between chains",
                "no exact target/source from prior negative W2 panels",
            ],
            "penalize": [
                "low interface-contact count",
                "large target or binder chains",
                "prior negative target/source reuse",
            ],
        },
        "prior_negative_targets": sorted(prior_targets),
        "prior_negative_sources": sorted(prior_sources),
        "stages": stages,
        "ranking": ranking,
        "pilot_manifest": {
            "path": pilot_manifest_path,
            "n_targets": len(pilot_manifest["targets"]),
            "target_ids": [_target_id(row) for row in pilot_manifest["targets"]],
        },
        "approval_boundary": {
            "current_approval_packet_target_count": approval_packet.get("target_count"),
            "current_approval_packet_pending_path_count": approval_packet.get("pending_path_count"),
            "current_packet_scope": "full_v9_batch",
            "staged_execution_requires": "regenerate or approve a subset-specific target-MSA wrapper before any staged submission",
        },
        "failures": failures,
        "next_action": (
            "choose staged pilot versus full 14-target MSA approval; if staged, regenerate subset-specific wrapper before submit"
            if audit_ok else
            "repair staged-plan failures before using it for W2 decisions"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 v9 Staged Target-MSA Plan",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Can mark goal complete: `{rep.get('can_mark_goal_complete')}`.",
        "",
        "This is a no-submit decision artifact. It does not approve or run target-MSA jobs.",
        "",
        "## Stages",
        "",
    ]
    stages = rep.get("stages") if isinstance(rep.get("stages"), dict) else {}
    for key in ("pilot_target_msa_targets", "expansion_target_msa_targets", "full_followup_targets"):
        lines.append(f"- {key}: {', '.join(stages.get(key, [])) or 'none'}")
    lines.extend(["", "## Top Ranked Targets", "", "| rank | target | source | score | reasons |", "|---:|---|---|---:|---|"])
    for i, row in enumerate(rep.get("ranking", [])[:10], 1):
        lines.append(
            "| {rank} | {target} | {source} | {score:.3f} | {reasons} |".format(
                rank=i,
                target=row.get("target_id"),
                source=row.get("source_pdb_id"),
                score=float(row.get("score") or 0.0),
                reasons=", ".join(row.get("reasons") or []),
            )
        )
    boundary = rep.get("approval_boundary") if isinstance(rep.get("approval_boundary"), dict) else {}
    lines.extend([
        "",
        "## Approval Boundary",
        "",
        f"- current packet scope: `{boundary.get('current_packet_scope')}`",
        f"- staged execution requires: {boundary.get('staged_execution_requires')}",
        "",
        f"Next action: {rep.get('next_action')}",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--discovery-pool", default="results/m6d_w2_target_family_redesign_v9_discovery_pool.json")
    ap.add_argument("--sequence-diversity", default="results/m6d_w2_target_family_redesign_v9_sequence_diversity.json")
    ap.add_argument("--followup-contract", default="results/m6d_w2_target_family_redesign_v9_followup_contract.json")
    ap.add_argument("--approval-packet", default="results/m6d_w2_target_family_redesign_v9_approval_packet.json")
    ap.add_argument("--target-manifest", default="configs/m6d_w2_target_family_redesign_v9_representative_targets.json")
    ap.add_argument("--prior-negative-panel-report", action="append", default=None)
    ap.add_argument("--pilot-size", type=int, default=3)
    ap.add_argument("--expansion-size", type=int, default=5)
    ap.add_argument("--pilot-manifest", default="configs/m6d_w2_target_family_redesign_v9_pilot_msa_targets.json")
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v9_staged_msa_plan.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v9_staged_msa_plan.md")
    args = ap.parse_args(argv)

    prior_reports = args.prior_negative_panel_report or DEFAULT_PRIOR_NEGATIVE_PANEL_REPORTS
    rep = build_plan(
        _load_json(args.discovery_pool),
        _load_json(args.sequence_diversity),
        _load_json(args.followup_contract),
        _load_json(args.approval_packet),
        _load_json(args.target_manifest),
        prior_negative_panel_reports=prior_reports,
        pilot_size=args.pilot_size,
        expansion_size=args.expansion_size,
        pilot_manifest_path=args.pilot_manifest,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(render_markdown(rep))
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    print(f"wrote {args.pilot_manifest}")
    return 0 if rep.get("audit_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
