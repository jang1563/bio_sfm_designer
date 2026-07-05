"""Freeze the W2 target-family redesign branch after a negative expanded panel.

This step follows an evaluable-but-not-certified W2 panel. It turns the target
triage diagnostic into a no-spend branch design and candidate-rule artifact.
It does not emit a Cayuga submit plan.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


BRANCH_ID = "w2_target_family_redesign_v1"


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


def _unique_sorted(values: Iterable[Any]) -> List[str]:
    return sorted({str(value) for value in values if isinstance(value, str) and value})


def _source_ids(target_ids: Iterable[str]) -> List[str]:
    return _unique_sorted(str(target_id).split("_", 1)[0] for target_id in target_ids)


def _targets_by_classification(diagnostic: Dict[str, Any], classification: str) -> List[str]:
    return _unique_sorted(
        row.get("complex_target_id")
        for row in diagnostic.get("targets", [])
        if isinstance(row, dict) and row.get("classification") == classification
    )


def _target_stats(diagnostic: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for row in diagnostic.get("targets", []):
        if not isinstance(row, dict) or not row.get("complex_target_id"):
            continue
        out.append({
            "target": row.get("complex_target_id"),
            "classification": row.get("classification"),
            "recommended_action": row.get("recommended_action"),
            "n_records": row.get("n_records"),
            "success": row.get("success"),
            "success_rate": row.get("success_rate"),
            "median_pae_interaction": row.get("median_pae_interaction"),
            "median_lrmsd": row.get("median_lrmsd"),
            "protocol_cutoff_accepts": row.get("protocol_cutoff_accepts"),
            "protocol_cutoff_false_accepts": row.get("protocol_cutoff_false_accepts"),
            "protocol_cutoff_false_accept_rate": row.get("protocol_cutoff_false_accept_rate"),
        })
    return out


def build_report(diagnostic: Dict[str, Any],
                 previous_rules: Optional[Dict[str, Any]] = None, *,
                 branch_id: str = BRANCH_ID) -> Dict[str, Any]:
    previous_rules = previous_rules if isinstance(previous_rules, dict) else {}
    low_success = _unique_sorted(diagnostic.get("summary", {}).get("low_success_targets", []))
    target_specific_certified = _targets_by_classification(diagnostic, "already_certified")
    retain_or_retest = _targets_by_classification(diagnostic, "underpowered_or_split_sensitive")
    signal_strategy_hold = _targets_by_classification(diagnostic, "underpowered_low_pae_acceptance")
    cutoff_failures = _unique_sorted(diagnostic.get("summary", {}).get("cutoff_failure_targets", []))

    previous_excluded = _unique_sorted(previous_rules.get("excluded_targets_under_current_protocol", []))
    previous_anchors = _unique_sorted(previous_rules.get("anchors_not_for_immediate_scale", []))
    previous_positive = _unique_sorted(previous_rules.get("positive_controls_not_generalization_targets", []))

    excluded_under_current_protocol = _unique_sorted(
        previous_excluded + low_success + signal_strategy_hold + cutoff_failures
    )
    anchors_not_for_immediate_scale = _unique_sorted(previous_anchors + retain_or_retest)
    positive_controls_not_generalization_targets = _unique_sorted(
        previous_positive + target_specific_certified
    )
    excluded_source_ids = _unique_sorted(
        _source_ids(excluded_under_current_protocol)
        + _source_ids(anchors_not_for_immediate_scale)
        + _source_ids(positive_controls_not_generalization_targets)
    )
    n_targets = diagnostic.get("n_targets")
    if not isinstance(n_targets, int):
        n_targets = len(_target_stats(diagnostic))
    n_target_specific_certified = len(target_specific_certified)
    n_not_certified = max(0, n_targets - n_target_specific_certified)

    status = (
        "target_family_redesign_rules_ready_for_candidate_pool_screen"
        if diagnostic.get("panel_status") == "multi_target_evaluable_not_certified"
        else "target_family_redesign_input_status_unexpected"
    )
    next_action = (
        "run the no-spend candidate-pool screen with the emitted target-family redesign rules"
        if status == "target_family_redesign_rules_ready_for_candidate_pool_screen"
        else "inspect the panel diagnostic before emitting candidate-pool claims"
    )

    return {
        "artifact": "m6d_w2_target_family_redesign",
        "branch_id": branch_id,
        "date": "2026-06-30",
        "status": status,
        "panel_status": diagnostic.get("panel_status"),
        "target_alpha": diagnostic.get("target_alpha"),
        "n_targets": diagnostic.get("n_targets"),
        "n_records": diagnostic.get("n_records"),
        "ready_for_candidate_pool_screen": status == "target_family_redesign_rules_ready_for_candidate_pool_screen",
        "ready_for_revised_manifest": False,
        "ready_for_cayuga_submission": False,
        "claim_boundary": {
            "w2_multi_target_generalization": "not_supported",
            "pooled_diagnostic": "not_sufficient_for_w2_certificate",
            "target_wise_gate": (
                f"panel not certified; {n_target_specific_certified}/{n_targets} current targets "
                f"certified target-wise and {n_not_certified}/{n_targets} did not certify; "
                "target-specific certificates are not W2 generalization"
            ),
            "cayuga_submission": "blocked_until_revised_manifest_and_strict_preflight",
        },
        "target_sets": {
            "drop_or_redesign_targets": low_success,
            "target_specific_certified_targets": target_specific_certified,
            "certified_targets_not_generalization_targets": target_specific_certified,
            "retain_or_retest_targets": retain_or_retest,
            "signal_strategy_hold_targets": signal_strategy_hold,
            "cutoff_failure_targets": cutoff_failures,
            "previously_excluded_targets": previous_excluded,
            "excluded_targets_under_current_protocol": excluded_under_current_protocol,
            "excluded_source_ids_under_current_protocol": excluded_source_ids,
            "anchors_not_for_immediate_scale": anchors_not_for_immediate_scale,
            "previous_positive_controls_not_generalization_targets": previous_positive,
            "positive_controls_not_generalization_targets": positive_controls_not_generalization_targets,
        },
        "target_stats": _target_stats(diagnostic),
        "candidate_rule_policy": {
            "exclude_low_success_targets": True,
            "exclude_signal_strategy_hold_targets_until_protocol_changes": True,
            "retain_retest_targets_are_not_broad_w2_generalization_targets": True,
            "carry_forward_previous_exclusions": True,
            "carry_forward_positive_controls": True,
            "treat_target_specific_certificates_as_positive_controls_not_w2_generalization": True,
            "disallow_pooled_only_claim": True,
        },
        "manifest_preconditions": [
            "run the local no-spend candidate-pool screen under the emitted target-family rules",
            "admit at least three non-anchor, source-diverse candidates before manifest design",
            "exclude low-success targets unless a new protocol id is declared",
            "hold signal-strategy targets unless the confidence-signal contract changes",
            "treat target-specific certified targets as positive controls, not new W2 candidate sources",
            "keep predictor_id, signal_source, label_source, and lrmsd_threshold fixed within a panel",
            "strict prepared-PDB, target FASTA/MSA/report, and completion/report replay preflight before any Cayuga spend",
        ],
        "next_artifacts_to_create": [
            f"configs/{branch_id}_candidate_rules.json",
            f"results/{branch_id}_candidate_pool.json",
            f"results/{branch_id}_manifest_design.json",
        ],
        "next_action": next_action,
        "can_mark_goal_complete": False,
    }


def build_candidate_rules(rep: Dict[str, Any],
                          previous_rules: Optional[Dict[str, Any]] = None, *,
                          source_design: str = "results/m6d_w2_target_family_redesign_v1_design.json",
                          gate_strategy_report: Optional[str] = None) -> Dict[str, Any]:
    previous_rules = previous_rules if isinstance(previous_rules, dict) else {}
    target_sets = rep.get("target_sets", {})
    candidate_requirements = dict(previous_rules.get("candidate_requirements") or {})
    if not candidate_requirements:
        candidate_requirements = {
            "min_ca_interface_contacts": 20,
            "min_non_anchor_candidates_for_revised_manifest": 3,
            "reject_current_protocol_zero_low_pae_accept_targets": True,
            "require_prep_report": True,
            "require_prepared_pdb": True,
            "require_source_pdb_deduplication": True,
            "require_target_fasta": True,
            "require_target_fasta_report": True,
            "require_target_msa": True,
            "require_target_msa_report": True,
        }
    candidate_requirements["require_source_pdb_deduplication"] = True
    candidate_requirements["reject_current_protocol_zero_low_pae_accept_targets"] = True

    panel_contract = dict(previous_rules.get("panel_contract") or {})
    if not panel_contract:
        panel_contract = {
            "complex_target_id": "required",
            "label_source": "single_value_required",
            "lrmsd_threshold": "single_value_required",
            "predictor_id": "single_value_required",
            "signal_source": "single_value_required",
            "target_alpha": 0.2,
        }
    pilot_requirements = dict(previous_rules.get("pilot_evidence_requirements") or {})
    if not pilot_requirements:
        pilot_requirements = {
            "disallow_pooled_only_claim": True,
            "failure_status_to_preserve": "multi_target_evaluable_not_certified",
            "min_records_per_target": 20,
            "require_target_wise_readout": True,
            "required_panel_report_status_before_claim": "multi_target_certified",
        }
    pilot_requirements["disallow_pooled_only_claim"] = True
    pilot_requirements["required_panel_report_status_before_claim"] = "multi_target_certified"

    unlock_conditions = [
        "at least three non-anchor candidates pass this target-family rule set",
        "a revised target manifest is generated from admitted candidates",
        "strict complex_target_manifest --require-files passes",
        "completion and panel-report replay commands are emitted before submission",
        "the goal anchor links the revised manifest and preflight report before any sbatch",
    ]
    gate_strategy_preconditions = []
    if gate_strategy_report:
        gate_strategy_preconditions = [
            "resolve gate-strategy blockers before any W2 Cayuga panel",
            "predeclare label-degeneracy handling for all-success targets before using them as gate evidence",
            "predeclare target-specific calibration or low-pAE acceptance criteria for high-success/no-trust targets",
        ]
        unlock_conditions = gate_strategy_preconditions + unlock_conditions

    return {
        "artifact": "m6d_w2_target_family_redesign_candidate_rules",
        "branch_id": rep.get("branch_id", BRANCH_ID),
        "date": rep.get("date"),
        "source_design": source_design,
        "gate_strategy_report": gate_strategy_report,
        "gate_strategy_preconditions": gate_strategy_preconditions,
        "selected_design": rep.get("branch_id", BRANCH_ID),
        "protocol_id": rep.get("branch_id", BRANCH_ID),
        "ready_for_cayuga_submission": False,
        "excluded_targets_under_current_protocol": target_sets.get("excluded_targets_under_current_protocol", []),
        "excluded_source_ids_under_current_protocol": target_sets.get(
            "excluded_source_ids_under_current_protocol", []
        ),
        "drop_or_redesign_targets": target_sets.get("drop_or_redesign_targets", []),
        "signal_strategy_hold_targets": target_sets.get("signal_strategy_hold_targets", []),
        "positive_controls_not_generalization_targets": target_sets.get(
            "positive_controls_not_generalization_targets", []
        ),
        "certified_targets_not_generalization_targets": target_sets.get(
            "certified_targets_not_generalization_targets", []
        ),
        "anchors_not_for_immediate_scale": target_sets.get("anchors_not_for_immediate_scale", []),
        "candidate_requirements": candidate_requirements,
        "pilot_evidence_requirements": pilot_requirements,
        "panel_contract": panel_contract,
        "spend_gate": {
            "cayuga_submission_allowed": False,
            "unlock_conditions": unlock_conditions,
        },
        "claim_boundary": rep.get("claim_boundary", {}),
        "can_mark_goal_complete": False,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    target_sets = rep.get("target_sets", {})

    def _list(values: Any) -> str:
        if not values:
            return "none"
        return ", ".join(str(value) for value in values)

    lines = [
        "# M6d W2 Target-Family Redesign",
        "",
        f"Date: {rep.get('date')}",
        f"Branch: `{rep.get('branch_id')}`",
        f"Status: `{rep.get('status')}`",
        f"Panel status: `{rep.get('panel_status')}`",
        f"Targets: {rep.get('n_targets')}  Records: {rep.get('n_records')}",
        f"Ready for candidate-pool screen: `{str(bool(rep.get('ready_for_candidate_pool_screen'))).lower()}`",
        f"Ready for revised manifest: `{str(bool(rep.get('ready_for_revised_manifest'))).lower()}`",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`",
        "",
        "## Claim Boundary",
        "",
        "- The input W2 panel/readout is completed negative evidence, not a generalization certificate.",
        "- Pooled-only diagnostics are not sufficient for W2.",
        "- Cayuga submission is blocked until a revised manifest and strict preflight exist.",
        "",
        "## Target Sets",
        "",
        f"- drop/redesign: {_list(target_sets.get('drop_or_redesign_targets'))}",
        f"- retain/retest only: {_list(target_sets.get('retain_or_retest_targets'))}",
        f"- hold for signal strategy: {_list(target_sets.get('signal_strategy_hold_targets'))}",
        f"- target-specific certified, not W2 generalization: {_list(target_sets.get('target_specific_certified_targets'))}",
        f"- excluded under current protocol: {_list(target_sets.get('excluded_targets_under_current_protocol'))}",
        f"- excluded source PDBs under current protocol: {_list(target_sets.get('excluded_source_ids_under_current_protocol'))}",
        f"- anchors not for immediate scale: {_list(target_sets.get('anchors_not_for_immediate_scale'))}",
        f"- positive controls, not W2 generalization: {_list(target_sets.get('positive_controls_not_generalization_targets'))}",
        "",
        "## Target Diagnostics",
        "",
        "| target | class | success rate | median pAE | cutoff accepts | action |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rep.get("target_stats", []):
        success_rate = row.get("success_rate")
        pae = row.get("median_pae_interaction")
        lines.append(
            "| {target} | {klass} | {success} | {pae} | {accepts} | {action} |".format(
                target=row.get("target"),
                klass=row.get("classification"),
                success="n/a" if success_rate is None else f"{float(success_rate):.3f}",
                pae="n/a" if pae is None else f"{float(pae):.3f}",
                accepts=row.get("protocol_cutoff_accepts"),
                action=row.get("recommended_action"),
            )
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
    ap.add_argument("--redesign-diagnostic", default="results/m6d_w2_expanded_next_branch_redesign_diagnostic.json")
    ap.add_argument("--previous-rules", default="configs/m6d_w2_next_branch_candidate_rules.json")
    ap.add_argument("--branch-id", default=BRANCH_ID)
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v1_design.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v1_design.md")
    ap.add_argument("--emit-candidate-rules", default="configs/m6d_w2_target_family_redesign_v1_candidate_rules.json")
    ap.add_argument("--gate-strategy-report", default=None)
    args = ap.parse_args(argv)

    previous_rules = _load_json(args.previous_rules) if args.previous_rules else None
    rep = build_report(_load_json(args.redesign_diagnostic), previous_rules, branch_id=args.branch_id)
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.emit_candidate_rules:
        _write_json(
            args.emit_candidate_rules,
            build_candidate_rules(
                rep,
                previous_rules,
                source_design=args.out_json,
                gate_strategy_report=args.gate_strategy_report,
            ),
        )
    print(f"wrote {args.out_json} and {args.out_md}")
    if args.emit_candidate_rules:
        print(f"wrote {args.emit_candidate_rules}")
    print(
        "status={status} branch={branch} excluded={excluded} ready_for_pool={ready}".format(
            status=rep["status"],
            branch=rep["branch_id"],
            excluded=len(rep["target_sets"]["excluded_targets_under_current_protocol"]),
            ready=rep["ready_for_candidate_pool_screen"],
        )
    )
    return 0 if rep["ready_for_candidate_pool_screen"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
