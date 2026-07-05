"""Render the revised M6d W2 target/protocol branch.

The current W2 evidence is negative for multi-target generalization. This tool
does not create a runnable Cayuga submission plan. It writes the branch that must
exist before the next runnable manifest: what evidence is frozen, what targets
are rejected, and what admission rules a future target candidate must satisfy.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_EXTRA_DIAGNOSTICS = [
    "results/m6c_w2_redesign_diagnostic.json",
    "results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json",
]


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


def _target_id(row: Dict[str, Any]) -> Optional[str]:
    value = row.get("target") or row.get("complex_target_id")
    return value if isinstance(value, str) and value else None


def _collect_targets(*reports: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    by_target: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        for row in report.get("targets", []):
            if not isinstance(row, dict):
                continue
            target = _target_id(row)
            if not target:
                continue
            out = by_target.setdefault(target, {"target": target})
            if "role" in row:
                out["protocol_role"] = row.get("role")
            if "classification" in row:
                out["classification"] = row.get("classification")
            if "recommended_action" in row:
                out["recommended_action"] = row.get("recommended_action")
            for key in (
                "success_rate",
                "median_pae_interaction",
                "protocol_cutoff_accepts",
                "protocol_cutoff_false_accept_rate",
                "alpha_0_2_seed_rate",
                "alpha_0_3_seed_rate",
                "median_extra_records_for_alpha_0_2",
            ):
                if key in row:
                    out[key] = row.get(key)
    return by_target


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _branch_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    target = row["target"]
    role = row.get("protocol_role")
    classification = row.get("classification")
    success_rate = _safe_float(row.get("success_rate"))
    alpha030 = _safe_float(row.get("alpha_0_3_seed_rate"))
    extra = _safe_float(row.get("median_extra_records_for_alpha_0_2"))
    cutoff_accepts = row.get("protocol_cutoff_accepts")

    reasons: List[str] = []
    if target == "3PC8_AB" or role == "freeze_target_specific_certificate":
        decision = "freeze_as_target_specific_positive_control"
        reasons.append("target-specific alpha=0.2 certificate exists after mini-scale")
        reasons.append("do not promote to multi-target generalization")
    elif target == "1BRS_AD" or role == "anchor_or_reference":
        decision = "retain_as_anchor_not_scale_target"
        reasons.append("anchor/reference target, but alpha=0.2 W2 generalization remains negative")
    elif classification == "target_protocol_mismatch_low_success":
        decision = "reject_for_current_w2_branch"
        reasons.append("low success target/protocol mismatch")
    elif classification == "underpowered_low_pae_acceptance":
        decision = "hold_until_low_pae_acceptance_strategy_changes"
        reasons.append("current protocol produced too little low-pAE acceptance")
    elif success_rate is not None and success_rate < 0.25:
        decision = "reject_for_current_w2_branch"
        reasons.append("success rate below minimum pilot threshold")
    elif alpha030 is not None and alpha030 >= 0.8 and extra is not None and extra <= 100:
        decision = "eligible_for_target_specific_pilot_only"
        reasons.append("near-certificate behavior, but still target-specific")
    else:
        decision = "hold_as_reference_only"
        reasons.append("insufficient evidence for broad-panel spend")

    if cutoff_accepts == 0:
        reasons.append("zero accepts under transferred low-pAE cutoff")
    if extra is not None and extra > 100:
        reasons.append("projected extra records for alpha=0.2 exceeds pilot threshold")

    return {
        **row,
        "branch_decision": decision,
        "decision_reasons": reasons,
    }


def build_report(goal_anchor: Dict[str, Any],
                 decision_protocol: Dict[str, Any],
                 redesign_diagnostic: Dict[str, Any],
                 followup_diagnostic: Dict[str, Any],
                 extra_diagnostics: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    w2_targets = decision_protocol.get("w2", {}).get("targets", [])
    w2_target_report = {"targets": w2_targets if isinstance(w2_targets, list) else []}
    extra_diagnostics = extra_diagnostics or []
    targets = [
        _branch_decision(row)
        for row in _collect_targets(
            *extra_diagnostics,
            redesign_diagnostic,
            followup_diagnostic,
            w2_target_report,
        ).values()
    ]
    targets.sort(key=lambda row: row["target"])

    ready_for_submit = False
    rejected = [
        row["target"] for row in targets
        if row["branch_decision"] in {
            "reject_for_current_w2_branch",
            "hold_until_low_pae_acceptance_strategy_changes",
        }
    ]
    frozen = [
        row["target"] for row in targets
        if row["branch_decision"] == "freeze_as_target_specific_positive_control"
    ]
    anchors = [
        row["target"] for row in targets
        if row["branch_decision"] == "retain_as_anchor_not_scale_target"
    ]

    return {
        "artifact": "m6d_w2_revised_branch",
        "date": "2026-06-30",
        "status": "candidate_discovery_required_before_next_w2_submission",
        "ready_for_cayuga_submission": ready_for_submit,
        "goal_objective": goal_anchor.get("objective"),
        "claim_boundary": {
            "w2_multi_target_generalization": "not_supported",
            "current_branch": "pilot_first_target_screen_before_broad_panel",
            "positive_controls_are_not_generalization": True,
        },
        "selected_branch": {
            "name": "pilot_first_target_screen_v1",
            "rationale": (
                "Completed W2 panels and the fresh-discovery unique-source pilot were "
                "evaluable but alpha=0.2 negative. Available non-anchor candidates either "
                "failed as target/protocol mismatches or produced too little low-pAE "
                "acceptance. The next branch must discover new success-enriched targets or "
                "redesign the generation/evaluation protocol before broad panel GPU spend."
            ),
            "not_a_submit_plan_reason": (
                "No current non-anchor target set satisfies the admission rules for a "
                "new broad W2 panel."
            ),
        },
        "target_decisions": targets,
        "target_sets": {
            "frozen_target_specific_positive_controls": frozen,
            "anchors_not_for_immediate_scale": anchors,
            "rejected_or_held_targets": rejected,
        },
        "future_candidate_admission_rules": [
            "exclude targets already classified as target_protocol_mismatch_low_success",
            "exclude current-protocol targets with zero low-pAE cutoff accepts unless the generation/evaluation protocol changes",
            "require local source PDB, prepared heterodimer PDB, target FASTA, target MSA, and reports before submission",
            "require no numbering-gap or chain-identity surprises except explicitly reviewed anchors",
            "require at least 20 CA-interface contacts in the prepared heterodimer",
            "run a pilot branch before broad panel submission; do not pool pilot evidence across targets",
            "promote to a broad W2 panel only after at least three non-anchor targets have target-wise pilot evidence under the same predictor, signal source, label source, and L-RMSD threshold",
        ],
        "next_artifacts_to_create": [
            "a new candidate-pool screen from fresh target discovery or a changed generation/evaluation protocol",
            "a revised target manifest only after at least three non-anchor candidates pass admission",
            "target FASTA/MSA/report preflight for any revised manifest",
            "complex_panel_completion before any future complex_panel_report",
        ],
        "can_mark_goal_complete": False,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Revised Branch",
        "",
        f"Date: {rep.get('date')}",
        "",
        "## Branch",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for Cayuga submission: `{str(rep.get('ready_for_cayuga_submission')).lower()}`.",
        "",
        rep["selected_branch"]["rationale"],
        "",
        f"Not a submit plan: {rep['selected_branch']['not_a_submit_plan_reason']}",
        "",
        "## Target Decisions",
        "",
        "| target | branch decision | classification | success rate | low-pAE accepts | alpha0.3 seed rate | median extra records |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rep.get("target_decisions", []):
        lines.append(
            "| {target} | {decision} | {classification} | {success} | {accepts} | {alpha030} | {extra} |".format(
                target=row.get("target"),
                decision=row.get("branch_decision"),
                classification=_fmt(row.get("classification")),
                success=_fmt(row.get("success_rate")),
                accepts=_fmt(row.get("protocol_cutoff_accepts")),
                alpha030=_fmt(row.get("alpha_0_3_seed_rate")),
                extra=_fmt(row.get("median_extra_records_for_alpha_0_2")),
            )
        )
    lines.extend([
        "",
        "## Admission Rules",
        "",
    ])
    lines.extend(f"- {rule}" for rule in rep.get("future_candidate_admission_rules", []))
    lines.extend([
        "",
        "## Next Artifacts",
        "",
    ])
    lines.extend(f"{i}. {item}" for i, item in enumerate(rep.get("next_artifacts_to_create", []), 1))
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--goal-anchor", default="results/m6d_goal_mode_current_anchor.json")
    ap.add_argument("--decision-protocol", default="results/m6d_w2_w3_decision_protocol.json")
    ap.add_argument("--redesign-diagnostic", default="results/m6d_redesign_panel_diagnostic.json")
    ap.add_argument("--followup-diagnostic", default="results/m6d_followup_panel_diagnostic.json")
    ap.add_argument(
        "--extra-diagnostic",
        action="append",
        dest="extra_diagnostics",
        default=None,
        help="additional W2 diagnostic JSON to fold into branch decisions",
    )
    ap.add_argument("--out-json", default="results/m6d_w2_revised_branch.json")
    ap.add_argument("--out-md", default="results/m6d_w2_revised_branch.md")
    args = ap.parse_args(argv)

    rep = build_report(
        _load_json(args.goal_anchor),
        _load_json(args.decision_protocol),
        _load_json(args.redesign_diagnostic),
        _load_json(args.followup_diagnostic),
        [_load_json(path) for path in (args.extra_diagnostics or DEFAULT_EXTRA_DIAGNOSTICS)],
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} ready_for_cayuga_submission={ready} targets={n} complete={complete}".format(
            status=rep["status"],
            ready=rep["ready_for_cayuga_submission"],
            n=len(rep["target_decisions"]),
            complete=rep["can_mark_goal_complete"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
