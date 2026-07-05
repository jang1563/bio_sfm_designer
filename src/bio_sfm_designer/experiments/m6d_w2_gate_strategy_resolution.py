"""Resolve the W2 gate-strategy blockers into a no-spend next protocol.

This artifact is deliberately procedural: it does not certify W2, does not
submit Cayuga jobs, and does not relax TrustGate. It turns the v5/v6 gate
strategy into a predeclared policy for the next W2 branch.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


DEFAULT_BRANCH_ID = "w2_target_family_redesign_v7_calibratable_discovery"


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


def _targets(groups: Dict[str, Any], key: str) -> List[str]:
    value = groups.get(key, [])
    if not isinstance(value, list):
        return []
    return sorted(str(v) for v in value if isinstance(v, str) and v)


def _min_candidates(candidate_rules: Dict[str, Any]) -> int:
    req = candidate_rules.get("candidate_requirements", {})
    value = req.get("min_non_anchor_candidates_for_revised_manifest", 3)
    return int(value) if isinstance(value, int) else 3


def _policy_targets(groups: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "label_degenerate_targets": _targets(
            groups, "label_degeneracy_policy_required_before_gate_claim"
        ),
        "low_pae_strategy_targets": _targets(groups, "low_pae_acceptance_strategy_required"),
        "replacement_or_protocol_redesign_targets": _targets(
            groups, "replace_target_or_redesign_generation_protocol"
        ),
        "split_sensitive_targets": _targets(
            groups, "target_alpha_split_sensitive_scale_or_recalibration_candidate"
        ),
        "target_specific_calibration_targets": _targets(
            groups, "target_specific_calibration_required"
        ),
    }


def _blocker_resolution(gate_strategy: Dict[str, Any],
                        policy_targets: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    blockers = gate_strategy.get("spend_gate", {}).get("blockers", [])
    if not isinstance(blockers, list):
        blockers = []
    out: List[Dict[str, Any]] = []
    for blocker in blockers:
        if blocker == "label_degenerate_gate_validation_policy_missing":
            out.append({
                "blocker": blocker,
                "resolution": "fail_closed_positive_controls_only",
                "affected_targets": policy_targets["label_degenerate_targets"],
                "decision": (
                    "Do not change TrustGate one-class behavior. All-success targets are "
                    "diagnostic positive controls only until mixed-label or predeclared "
                    "decoy-negative calibration evidence exists."
                ),
                "unlocks_cayuga_submission": False,
            })
        elif blocker in {"low_pae_acceptance_strategy_missing", "cutoff_transfer_failure"}:
            affected = sorted(
                set(policy_targets["low_pae_strategy_targets"])
                | set(policy_targets["target_specific_calibration_targets"])
                | set(policy_targets["split_sensitive_targets"])
            )
            out.append({
                "blocker": blocker,
                "resolution": "forbid_fixed_cutoff_transfer_require_predeclared_rcps",
                "affected_targets": affected,
                "decision": (
                    "Do not transfer the fixed low-pAE cutoff as a certificate. The next "
                    "W2 branch may use the same TrustGate algorithm with target-specific "
                    "or explicitly family-calibrated RCPS, but every claimed target must "
                    "certify target-wise at alpha<=0.2."
                ),
                "unlocks_cayuga_submission": False,
            })
        elif blocker == "low_success_target_protocol_mismatch":
            out.append({
                "blocker": blocker,
                "resolution": "replace_targets_or_declare_new_generation_protocol",
                "affected_targets": policy_targets["replacement_or_protocol_redesign_targets"],
                "decision": (
                    "Do not spend more panel GPU on these targets under the current "
                    "generation/evaluation protocol. Replace them or declare a new protocol id."
                ),
                "unlocks_cayuga_submission": False,
            })
        else:
            out.append({
                "blocker": str(blocker),
                "resolution": "manual_review_required",
                "affected_targets": [],
                "decision": "No automatic resolution is defined.",
                "unlocks_cayuga_submission": False,
            })
    return out


def build_report(gate_strategy: Dict[str, Any],
                 candidate_pool: Dict[str, Any],
                 candidate_rules: Optional[Dict[str, Any]] = None,
                 *,
                 branch_id: str = DEFAULT_BRANCH_ID) -> Dict[str, Any]:
    rules = candidate_rules or {}
    groups = gate_strategy.get("gate_strategy_groups", {})
    if not isinstance(groups, dict):
        groups = {}
    policy_targets = _policy_targets(groups)
    min_candidates = _min_candidates(rules)
    admitted = int(candidate_pool.get("n_admitted_for_next_branch") or 0)
    ready_for_manifest = bool(candidate_pool.get("ready_for_revised_manifest"))
    ready_for_cayuga = False
    pool_status = candidate_pool.get("status")

    return {
        "artifact": "m6d_w2_gate_strategy_resolution",
        "date": "2026-06-30",
        "branch_id": branch_id,
        "source_gate_strategy_branch": gate_strategy.get("branch_id"),
        "source_candidate_rules": rules.get("artifact"),
        "source_candidate_pool_status": pool_status,
        "status": (
            "gate_strategy_resolved_discovery_required"
            if admitted < min_candidates
            else "gate_strategy_resolved_manifest_design_possible"
        ),
        "can_mark_goal_complete": False,
        "ready_for_revised_manifest": ready_for_manifest,
        "ready_for_target_msa_precompute": False,
        "ready_for_cayuga_submission": ready_for_cayuga,
        "claim_boundary": {
            "w2_multi_target_generalization": "not_supported",
            "trustgate_policy": "do_not_relax_one_class_or_replace_actual_tau_with_alpha_plan",
            "candidate_pool": "local_no_spend_inventory_screen_only",
            "cayuga_submission": "blocked_until_new_manifest_and_strict_preflight",
        },
        "candidate_pool_readout": {
            "n_candidates": candidate_pool.get("n_candidates"),
            "n_admitted_for_next_branch": admitted,
            "n_source_redundancy_audit_only": candidate_pool.get("n_source_redundancy_audit_only"),
            "source_redundancy_audit_targets": candidate_pool.get("source_redundancy_audit_targets", []),
            "minimum_required_for_manifest": min_candidates,
            "ready_for_revised_manifest": ready_for_manifest,
            "ready_for_cayuga_submission": candidate_pool.get("ready_for_cayuga_submission"),
        },
        "selected_policies": {
            "label_degeneracy": {
                "policy": "fail_closed_positive_controls_only",
                "targets": policy_targets["label_degenerate_targets"],
                "requirements_to_reopen": [
                    "mixed success/failure evidence under the same target and threshold",
                    "or predeclared decoy/spike-in negatives that preserve the target identity",
                    "actual TrustGate tau must exist; alpha-plan estimates cannot substitute",
                ],
            },
            "low_pae_and_cutoff": {
                "policy": "no_fixed_cutoff_transfer_target_specific_or_family_rcps_only",
                "targets": sorted(
                    set(policy_targets["low_pae_strategy_targets"])
                    | set(policy_targets["target_specific_calibration_targets"])
                    | set(policy_targets["split_sensitive_targets"])
                ),
                "requirements_to_reopen": [
                    "predeclare target-specific or family-calibrated RCPS before records are generated",
                    "target-wise alpha<=0.2 certificate for every claimed target",
                    "split-seed sensitivity reported before any broad W2 claim",
                    "pooled-only tau remains diagnostic only",
                ],
            },
            "protocol_mismatch": {
                "policy": "replace_targets_or_declare_new_generation_protocol",
                "targets": policy_targets["replacement_or_protocol_redesign_targets"],
                "requirements_to_reopen": [
                    "new target source outside excluded sources",
                    "or new generation/evaluation protocol id before reusing a failed target",
                    "strict manifest, input-prep, completion, and panel-report replay before sbatch",
                ],
            },
            "panel_claim": {
                "policy": "multi_target_claim_requires_per_target_certificates",
                "minimum_targets": min_candidates,
                "requirements": [
                    "at least three non-anchor source-diverse targets",
                    "each target certifies target-wise at alpha<=0.2 under the predeclared algorithm",
                    "no pooled-only certificate and no target-specific control promoted to W2",
                ],
            },
        },
        "blocker_resolution": _blocker_resolution(gate_strategy, policy_targets),
        "next_branch_protocol": {
            "protocol_id": branch_id,
            "purpose": "discover or redesign targets that can produce mixed-label calibratable W2 evidence",
            "starting_state": (
                "current v6 inventory has insufficient admitted targets"
                if admitted < min_candidates else "candidate pool can proceed to manifest design"
            ),
            "next_action": (
                "expand target discovery beyond excluded sources under this policy"
                if admitted < min_candidates else "write revised manifest and run strict require-files preflight"
            ),
            "cayuga_unlock_conditions": [
                "candidate screen admits at least three non-anchor source-diverse targets",
                "revised manifest is written and linked from the goal anchor",
                "strict complex_target_manifest --require-files passes",
                "receipt-preserving ProteinMPNN/Boltz submit wrapper is generated",
                "completion and panel-report replay commands are generated before submission",
            ],
        },
        "next_actions": [
            "Do not submit the current v6 inventory to Cayuga.",
            "Use the fail-closed label-degeneracy policy for all-success targets.",
            "Use target-specific or explicitly family-calibrated RCPS; do not transfer a fixed low-pAE cutoff.",
            "Expand target discovery beyond excluded sources or declare a new generation/evaluation protocol id.",
            "Only build a revised W2 manifest after at least three non-anchor candidates pass the no-spend screen.",
        ],
    }


def build_protocol_config(rep: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "artifact": "m6d_w2_calibratable_discovery_protocol_config",
        "date": rep.get("date"),
        "protocol_id": rep.get("branch_id"),
        "source_resolution": "results/m6d_w2_target_family_redesign_v6_gate_strategy_resolution.json",
        "ready_for_cayuga_submission": False,
        "claim_boundary": rep.get("claim_boundary"),
        "candidate_pool_readout": rep.get("candidate_pool_readout"),
        "selected_policies": rep.get("selected_policies"),
        "cayuga_unlock_conditions": rep.get("next_branch_protocol", {}).get("cayuga_unlock_conditions", []),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Gate-Strategy Resolution",
        "",
        f"Date: {rep.get('date')}",
        f"Status: `{rep.get('status')}`",
        f"Next protocol: `{rep.get('branch_id')}`",
        f"Ready for revised manifest: `{str(rep.get('ready_for_revised_manifest')).lower()}`",
        f"Ready for target-MSA precompute: `{str(rep.get('ready_for_target_msa_precompute')).lower()}`",
        f"Ready for Cayuga submission: `{str(rep.get('ready_for_cayuga_submission')).lower()}`",
        "",
        "## Claim Boundary",
        "",
        "- W2 multi-target generalization remains not supported.",
        "- Do not relax one-class TrustGate behavior.",
        "- Alpha-plan estimates cannot replace an actual TrustGate tau.",
        "- The current candidate pool is local no-spend screening only.",
        "",
        "## Candidate Pool Readout",
        "",
    ]
    pool = rep.get("candidate_pool_readout", {})
    lines.extend([
        f"- candidates screened: {pool.get('n_candidates')}",
        f"- admitted for next branch: {pool.get('n_admitted_for_next_branch')}",
        f"- minimum required for manifest: {pool.get('minimum_required_for_manifest')}",
        f"- source-redundancy audit only: {pool.get('n_source_redundancy_audit_only')}",
        "",
        "## Selected Policies",
        "",
    ])
    policies = rep.get("selected_policies", {})
    for name in ["label_degeneracy", "low_pae_and_cutoff", "protocol_mismatch", "panel_claim"]:
        policy = policies.get(name, {})
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- policy: `{policy.get('policy')}`")
        targets = policy.get("targets")
        if isinstance(targets, list):
            lines.append(f"- targets: {', '.join(targets) if targets else 'none'}")
        reqs = policy.get("requirements_to_reopen") or policy.get("requirements") or []
        for req in reqs:
            lines.append(f"- {req}")
        lines.append("")
    lines.extend([
        "## Blocker Resolution",
        "",
        "| blocker | resolution | targets | unlocks Cayuga |",
        "|---|---|---|---:|",
    ])
    for row in rep.get("blocker_resolution", []):
        targets = row.get("affected_targets", [])
        lines.append(
            "| {blocker} | {resolution} | {targets} | {unlock} |".format(
                blocker=row.get("blocker"),
                resolution=row.get("resolution"),
                targets=", ".join(targets) if targets else "none",
                unlock=str(row.get("unlocks_cayuga_submission")).lower(),
            )
        )
    lines.extend([
        "",
        "## Next Branch",
        "",
        f"Protocol id: `{rep.get('next_branch_protocol', {}).get('protocol_id')}`",
        "",
        str(rep.get("next_branch_protocol", {}).get("next_action")),
        "",
        "Cayuga unlock conditions:",
    ])
    for item in rep.get("next_branch_protocol", {}).get("cayuga_unlock_conditions", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Next Actions",
        "",
    ])
    lines.extend(f"{i}. {item}" for i, item in enumerate(rep.get("next_actions", []), 1))
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate-strategy", default="results/m6d_w2_target_family_redesign_v5_gate_strategy.json")
    ap.add_argument("--candidate-pool", default="results/m6d_w2_target_family_redesign_v6_candidate_pool.json")
    ap.add_argument("--candidate-rules", default="configs/m6d_w2_target_family_redesign_v6_candidate_rules.json")
    ap.add_argument("--branch-id", default=DEFAULT_BRANCH_ID)
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v6_gate_strategy_resolution.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v6_gate_strategy_resolution.md")
    ap.add_argument("--out-protocol-config", default=None)
    args = ap.parse_args(argv)

    rep = build_report(
        _load_json(args.gate_strategy),
        _load_json(args.candidate_pool),
        _load_json(args.candidate_rules),
        branch_id=args.branch_id,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.out_protocol_config:
        _write_json(args.out_protocol_config, build_protocol_config(rep))
    print(
        "status={status} protocol={protocol} admitted={admitted} cayuga={cayuga}".format(
            status=rep["status"],
            protocol=rep["branch_id"],
            admitted=rep["candidate_pool_readout"]["n_admitted_for_next_branch"],
            cayuga=rep["ready_for_cayuga_submission"],
        )
    )
    print(f"wrote {args.out_json} and {args.out_md}")
    if args.out_protocol_config:
        print(f"wrote {args.out_protocol_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
