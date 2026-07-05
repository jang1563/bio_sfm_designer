"""Design the next no-spend W2 target/protocol branch.

This artifact comes after W2 panels are evaluable-but-negative and the known
candidate pool admits zero current-protocol targets. It is deliberately not a
Cayuga submit plan. It records the next branch design constraints before a new
manifest can be written.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


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


def _targets_with_decision(revised_branch: Dict[str, Any], decision: str) -> List[str]:
    return [
        str(row.get("target"))
        for row in revised_branch.get("target_decisions", [])
        if isinstance(row, dict) and row.get("branch_decision") == decision and row.get("target")
    ]


def _fresh_low_success_targets(fresh_diagnostic: Dict[str, Any]) -> List[str]:
    return [
        str(row.get("complex_target_id"))
        for row in fresh_diagnostic.get("targets", [])
        if (
            isinstance(row, dict)
            and row.get("classification") == "target_protocol_mismatch_low_success"
            and row.get("complex_target_id")
        )
    ]


def _known_pool_summary(candidate_screen: Dict[str, Any]) -> Dict[str, Any]:
    screened = [
        row for row in candidate_screen.get("screened_targets", [])
        if isinstance(row, dict)
    ]
    verdict_counts: Dict[str, int] = {}
    for row in screened:
        verdict = str(row.get("verdict") or "unknown")
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    return {
        "status": candidate_screen.get("status"),
        "n_candidates": candidate_screen.get("n_candidates", len(screened)),
        "n_admitted_for_pilot": candidate_screen.get("n_admitted_for_pilot", 0),
        "ready_for_revised_manifest": bool(candidate_screen.get("ready_for_revised_manifest")),
        "ready_for_cayuga_submission": bool(candidate_screen.get("ready_for_cayuga_submission")),
        "verdict_counts": verdict_counts,
    }


def build_report(revised_branch: Dict[str, Any],
                 candidate_screen: Dict[str, Any],
                 fresh_diagnostic: Dict[str, Any],
                 *,
                 w3_decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pool = _known_pool_summary(candidate_screen)
    rejected = revised_branch.get("target_sets", {}).get("rejected_or_held_targets", [])
    frozen = revised_branch.get("target_sets", {}).get("frozen_target_specific_positive_controls", [])
    anchors = revised_branch.get("target_sets", {}).get("anchors_not_for_immediate_scale", [])
    fresh_low_success = _fresh_low_success_targets(fresh_diagnostic)
    held_low_pae = _targets_with_decision(
        revised_branch,
        "hold_until_low_pae_acceptance_strategy_changes",
    )

    blocked_reasons: List[str] = []
    if pool["n_admitted_for_pilot"] == 0:
        blocked_reasons.append("known_candidate_pool_has_zero_admissions")
    if fresh_low_success:
        blocked_reasons.append("fresh_unique_source_pilot_low_success_for_all_targets")
    if not pool["ready_for_revised_manifest"]:
        blocked_reasons.append("no_revised_manifest_authorized")
    if not pool["ready_for_cayuga_submission"]:
        blocked_reasons.append("no_cayuga_submission_authorized")

    if pool["n_admitted_for_pilot"] > 0:
        selected = "build_revised_manifest_from_admitted_candidates"
        status = "candidate_pool_has_admissions_manifest_design_required"
        next_action = "write a revised manifest from admitted candidates, then run strict manifest preflight"
    elif fresh_low_success:
        selected = "protocol_redesign_plus_success_enriched_discovery_v1"
        status = "no_spend_protocol_and_target_redesign_required"
        next_action = (
            "apply the candidate-rules config to build a no-spend next-branch candidate pool"
        )
    else:
        selected = "fresh_success_enriched_target_discovery_v1"
        status = "fresh_target_discovery_required"
        next_action = (
            "expand candidate discovery under the candidate-rules config before manifest design"
        )

    w3_status = None
    if isinstance(w3_decision, dict):
        w3_status = {
            "status": w3_decision.get("w3", {}).get("status"),
            "claim_boundary": w3_decision.get("w3", {}).get("claim_boundary"),
            "selected_protocol": w3_decision.get("w3", {}).get("selected_protocol"),
            "current_protocol_verdict": w3_decision.get("w3", {}).get("current_protocol_verdict"),
            "coupling_rule": (
                "W2 redesign may use Boltz-only records as current single-predictor evidence, "
                "but W3 robustness remains unresolved until an adjudicated predictor protocol passes."
            ),
        }

    return {
        "artifact": "m6d_w2_next_branch_design",
        "date": "2026-06-30",
        "status": status,
        "selected_design": selected,
        "ready_for_revised_manifest": pool["ready_for_revised_manifest"],
        "ready_for_cayuga_submission": False,
        "known_pool": pool,
        "blocked_reasons": blocked_reasons,
        "evidence_inputs": {
            "revised_branch_status": revised_branch.get("status"),
            "candidate_pool_status": candidate_screen.get("status"),
            "fresh_diagnostic_recommendation": fresh_diagnostic.get("summary", {}).get("recommendation"),
        },
        "target_sets": {
            "frozen_target_specific_positive_controls": frozen,
            "anchors_not_for_immediate_scale": anchors,
            "rejected_or_held_targets": rejected,
            "fresh_low_success_targets": fresh_low_success,
            "held_until_low_pae_strategy_changes": held_low_pae,
        },
        "design_tracks": [
            {
                "name": "success_enriched_target_discovery",
                "priority": 1,
                "purpose": "find new non-anchor heterodimer targets before another broad W2 panel",
                "entry_gate": "local/no-spend structural discovery and candidate-pool screen",
                "admission_rules": [
                    "exclude all current rejected_or_held targets under the current protocol",
                    "deduplicate source PDBs before claiming target independence",
                    "require prepared heterodimer, target FASTA, target MSA, reports, and >=20 CA-interface contacts",
                    "require at least three non-anchor candidates before any broad panel manifest",
                ],
                "exit_to_cayuga": (
                    "only after a revised manifest passes strict require-files preflight and "
                    "complex_panel_completion/report replay paths are emitted"
                ),
            },
            {
                "name": "protocol_redesign_for_low_pae_acceptance",
                "priority": 2,
                "purpose": "change generation/evaluation assumptions for targets that have success but no low-pAE accepts",
                "entry_gate": "predeclare the changed protocol before reusing held targets",
                "admission_rules": [
                    "do not reuse held targets as W2 evidence under the current protocol",
                    "if temperature, MSA/template, backbone, or interface-definition changes, give the branch a new protocol id",
                    "pilot target-wise before broad panel claims",
                    "keep predictor_id, signal_source, label_source, and lrmsd_threshold fixed within a panel",
                ],
                "exit_to_cayuga": (
                    "only after the protocol id, target set, alpha target, and completion/report commands are frozen"
                ),
            },
            {
                "name": "source_redundancy_audit",
                "priority": 3,
                "purpose": "use the full six fresh chain-pair inventory only as source-redundancy evidence",
                "entry_gate": "no generalization claim; source PDBs are not independent target families",
                "admission_rules": [
                    "keep intra-source chain pairs separate from multi-target generalization",
                    "use the audit to learn failure modes before expanding seed discovery",
                ],
                "exit_to_cayuga": "not a submit track unless promoted by a separate predeclared audit plan",
            },
        ],
        "manifest_preconditions": [
            "at least three non-anchor candidates admitted by the no-spend screen",
            "no candidate classified as target_protocol_mismatch_low_success under the same protocol",
            "no current-protocol zero-low-pAE-accept target unless protocol id changes",
            "single predictor_id, signal_source, label_source, and lrmsd_threshold per panel",
            "strict target FASTA/MSA/report and prepared-PDB preflight",
            "completion and panel-report replay commands emitted before submission",
        ],
        "next_artifacts_to_create": [
            "results/m6d_w2_next_branch_candidate_pool.json",
            "results/m6d_w2_next_branch_manifest_preflight.json",
        ],
        "generated_artifacts": {
            "candidate_rules_config": "configs/m6d_w2_next_branch_candidate_rules.json",
        },
        "w3_coupling": w3_status,
        "next_action": next_action,
        "can_mark_goal_complete": False,
    }


def build_candidate_rules(rep: Dict[str, Any], *, source_design: str = "results/m6d_w2_next_branch_design.json") -> Dict[str, Any]:
    target_sets = rep.get("target_sets", {})
    return {
        "artifact": "m6d_w2_next_branch_candidate_rules",
        "date": rep.get("date"),
        "source_design": source_design,
        "selected_design": rep.get("selected_design"),
        "protocol_id": rep.get("selected_design"),
        "ready_for_cayuga_submission": False,
        "excluded_targets_under_current_protocol": sorted(set(
            target_sets.get("rejected_or_held_targets", [])
            + target_sets.get("fresh_low_success_targets", [])
        )),
        "positive_controls_not_generalization_targets": target_sets.get(
            "frozen_target_specific_positive_controls", []
        ),
        "anchors_not_for_immediate_scale": target_sets.get("anchors_not_for_immediate_scale", []),
        "candidate_requirements": {
            "min_non_anchor_candidates_for_revised_manifest": 3,
            "min_ca_interface_contacts": 20,
            "require_source_pdb_deduplication": True,
            "require_prepared_pdb": True,
            "require_prep_report": True,
            "require_target_fasta": True,
            "require_target_fasta_report": True,
            "require_target_msa": True,
            "require_target_msa_report": True,
            "reject_current_protocol_zero_low_pae_accept_targets": True,
        },
        "pilot_evidence_requirements": {
            "require_target_wise_readout": True,
            "min_records_per_target": 20,
            "disallow_pooled_only_claim": True,
            "required_panel_report_status_before_claim": "multi_target_certified",
            "failure_status_to_preserve": "multi_target_evaluable_not_certified",
        },
        "panel_contract": {
            "predictor_id": "single_value_required",
            "signal_source": "single_value_required",
            "label_source": "single_value_required",
            "lrmsd_threshold": "single_value_required",
            "complex_target_id": "required",
            "target_alpha": 0.2,
        },
        "spend_gate": {
            "cayuga_submission_allowed": False,
            "unlock_conditions": [
                "at least three non-anchor candidates pass this local rule set",
                "a revised target manifest is generated from admitted candidates",
                "strict complex_target_manifest --require-files passes",
                "completion and panel-report replay commands are emitted before submission",
            ],
        },
        "can_mark_goal_complete": False,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    pool = rep.get("known_pool", {})
    lines = [
        "# M6d W2 Next Branch Design",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Selected design: `{rep.get('selected_design')}`.",
        f"Ready for revised manifest: `{str(bool(rep.get('ready_for_revised_manifest'))).lower()}`.",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`.",
        "",
        "## Known Pool",
        "",
        f"- candidates: {pool.get('n_candidates')}",
        f"- admitted for pilot: {pool.get('n_admitted_for_pilot')}",
        f"- status: `{pool.get('status')}`",
        "",
        "## Blocked Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in rep.get("blocked_reasons", []))
    lines.extend([
        "",
        "## Target Sets",
        "",
    ])
    for key, values in rep.get("target_sets", {}).items():
        joined = ", ".join(values) if values else "none"
        lines.append(f"- {key}: {joined}")
    lines.extend([
        "",
        "## Design Tracks",
        "",
        "| priority | track | purpose | exit to Cayuga |",
        "|---:|---|---|---|",
    ])
    for track in rep.get("design_tracks", []):
        lines.append(
            f"| {track.get('priority')} | {track.get('name')} | "
            f"{track.get('purpose')} | {track.get('exit_to_cayuga')} |"
        )
    lines.extend([
        "",
        "## Manifest Preconditions",
        "",
    ])
    lines.extend(f"- {item}" for item in rep.get("manifest_preconditions", []))
    lines.extend([
        "",
        "## Next Artifacts",
        "",
    ])
    lines.extend(f"{i}. {item}" for i, item in enumerate(rep.get("next_artifacts_to_create", []), 1))
    lines.extend([
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--revised-branch", default="results/m6d_w2_revised_branch.json")
    ap.add_argument("--candidate-screen", default="results/m6d_w2_candidate_pool_screen.json")
    ap.add_argument("--fresh-diagnostic", default="results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json")
    ap.add_argument("--w3-decision", default="results/m6d_w2_w3_decision_protocol.json")
    ap.add_argument("--out-json", default="results/m6d_w2_next_branch_design.json")
    ap.add_argument("--out-md", default="results/m6d_w2_next_branch_design.md")
    ap.add_argument("--emit-candidate-rules", default="configs/m6d_w2_next_branch_candidate_rules.json")
    args = ap.parse_args(argv)

    rep = build_report(
        _load_json(args.revised_branch),
        _load_json(args.candidate_screen),
        _load_json(args.fresh_diagnostic),
        w3_decision=_load_json(args.w3_decision) if args.w3_decision else None,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.emit_candidate_rules:
        _write_json(args.emit_candidate_rules, build_candidate_rules(rep, source_design=args.out_json))
    print(f"wrote {args.out_json} and {args.out_md}")
    if args.emit_candidate_rules:
        print(f"wrote {args.emit_candidate_rules}")
    print(
        "status={status} selected={selected} candidates={n} admitted={admitted} ready={ready}".format(
            status=rep["status"],
            selected=rep["selected_design"],
            n=rep["known_pool"]["n_candidates"],
            admitted=rep["known_pool"]["n_admitted_for_pilot"],
            ready=rep["ready_for_cayuga_submission"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
