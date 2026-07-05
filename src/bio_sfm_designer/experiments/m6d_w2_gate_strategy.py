"""No-spend W2 gate-strategy redesign after an evaluable negative panel.

The target-family redesign diagnostic says which targets failed, but the next
science decision also needs to distinguish three different failure modes:

* target/protocol mismatch: low interface success, replace or redesign protocol;
* cutoff transfer failure: low-pAE cutoff accepts too many false designs;
* gate calibration/split failure: designs can be good, but the actual TrustGate
  path still does not certify a target-wise tau.

This helper consumes an existing panel report and diagnostic, replays only CPU
analyses on already-synced records, and emits a no-spend strategy artifact. It
does not authorize Cayuga submission.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_seed_sensitivity import _parse_seeds, run_sensitivity
from .complex_gate_sweep import load_merged_records


BRANCH_ID = "w2_target_family_redesign_v6_no_spend_gate_strategy"
_DEFAULT_ALPHAS = "0.3,0.2"


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


def _median(values: Iterable[Any]) -> Optional[float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return float(statistics.median(nums)) if nums else None


def _diagnostic_by_target(diagnostic: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in diagnostic.get("targets", []):
        if isinstance(row, dict) and row.get("complex_target_id"):
            out[str(row["complex_target_id"])] = row
    return out


def _record_target_id(path: str, rows: List[Dict[str, Any]]) -> str:
    for row in rows:
        value = row.get("complex_target_id")
        if value:
            return str(value)
    return os.path.basename(os.path.dirname(path))


def _label_class(success: int, failure: int) -> str:
    if success > 0 and failure > 0:
        return "mixed_success_failure"
    if success > 0:
        return "label_degenerate_all_success"
    if failure > 0:
        return "label_degenerate_all_failure"
    return "empty_or_unreadable"


def _strategy(row: Dict[str, Any]) -> str:
    classification = row.get("diagnostic_classification")
    label_class = row.get("label_class")
    target_cert = int(row.get("target_alpha_certified_count") or 0)
    baseline_cert = int(row.get("baseline_alpha_certified_count") or 0)
    n_seeds = int(row.get("n_seeds") or 0)

    if classification == "target_protocol_mismatch_low_success":
        return "replace_target_or_redesign_generation_protocol"
    if classification == "low_pae_cutoff_not_transferable":
        return "target_specific_calibration_required"
    if label_class != "mixed_success_failure":
        return "label_degeneracy_policy_required_before_gate_claim"
    if target_cert > 0:
        return "target_alpha_split_sensitive_scale_or_recalibration_candidate"
    if baseline_cert == n_seeds and n_seeds > 0:
        return "loose_alpha_anchor_not_target_alpha_certificate"
    if classification == "underpowered_low_pae_acceptance":
        return "low_pae_acceptance_strategy_required"
    if classification == "underpowered_or_split_sensitive":
        return "split_sensitivity_or_target_specific_scale_diagnostic"
    return "no_spend_review_required"


def _panel_records(panel_report: Dict[str, Any]) -> List[str]:
    records = panel_report.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("panel report must contain non-empty records list")
    return [str(path) for path in records]


def _target_row(path: str, diagnostic_rows: Dict[str, Dict[str, Any]], *,
                target_alpha: float, baseline_alpha: float, seeds: List[int],
                alphas: str, threshold: float) -> Dict[str, Any]:
    records = load_merged_records([path])
    target_id = _record_target_id(path, records)
    diagnostic = diagnostic_rows.get(target_id, {})
    success = sum(1 for row in records if float(row["lrmsd"]) < threshold)
    failure = len(records) - success
    sensitivity = run_sensitivity(
        [path],
        target_alpha=target_alpha,
        baseline_alpha=baseline_alpha,
        alphas=[float(a) for a in alphas.split(",") if a.strip()],
        seeds=seeds,
        threshold=threshold,
    )
    target_addl = sensitivity.get("target_estimated_additional_records") or {}
    baseline_addl_values = []
    for seed_row in sensitivity.get("per_seed", []):
        sweep = seed_row.get("sweep_by_alpha") or {}
        baseline = sweep.get(str(float(baseline_alpha))) or sweep.get(float(baseline_alpha))
        if isinstance(baseline, dict):
            # No extra-record estimate is emitted for baseline alpha, so keep coverage/trust evidence.
            pass
        addl = seed_row.get("target_estimated_additional_records")
        if isinstance(addl, (int, float)):
            baseline_addl_values.append(float(addl))
    label_class = _label_class(success, failure)
    target_cert_count = int(sensitivity.get("target_certified_count") or 0)
    baseline_cert_count = int(sensitivity.get("baseline_certified_count") or 0)
    n_seeds = int(sensitivity.get("n_seeds") or len(seeds))
    median_addl = target_addl.get("median")
    alpha_plan_gate_drift = (
        label_class != "mixed_success_failure"
        and target_cert_count == 0
        and isinstance(median_addl, (int, float))
        and float(median_addl) == 0.0
    )
    row = {
        "target": target_id,
        "records": path,
        "n_records": len(records),
        "success": success,
        "failure": failure,
        "success_rate": success / len(records) if records else None,
        "label_class": label_class,
        "diagnostic_classification": diagnostic.get("classification"),
        "diagnostic_action": diagnostic.get("recommended_action"),
        "median_pae_interaction": diagnostic.get("median_pae_interaction"),
        "protocol_cutoff_accepts": diagnostic.get("protocol_cutoff_accepts"),
        "protocol_cutoff_false_accept_rate": diagnostic.get("protocol_cutoff_false_accept_rate"),
        "target_alpha": target_alpha,
        "baseline_alpha": baseline_alpha,
        "n_seeds": n_seeds,
        "target_alpha_certified_count": target_cert_count,
        "target_alpha_certified_fraction": sensitivity.get("target_certified_fraction"),
        "baseline_alpha_certified_count": baseline_cert_count,
        "baseline_alpha_certified_fraction": sensitivity.get("baseline_certified_fraction"),
        "target_estimated_additional_records": target_addl,
        "target_estimated_additional_records_median": median_addl,
        "alpha_plan_gate_drift": alpha_plan_gate_drift,
        "gate_strategy": None,
    }
    row["gate_strategy"] = _strategy(row)
    return row


def build_report(panel_report: Dict[str, Any], diagnostic: Dict[str, Any], *,
                 branch_id: str = BRANCH_ID,
                 target_alpha: Optional[float] = None,
                 baseline_alpha: float = 0.3,
                 seeds: Iterable[int] = range(20),
                 alphas: str = _DEFAULT_ALPHAS,
                 threshold: float = 4.0) -> Dict[str, Any]:
    seed_list = list(seeds)
    if not seed_list:
        raise ValueError("at least one split seed is required")
    target_alpha_eff = float(target_alpha if target_alpha is not None else panel_report.get("target_alpha", 0.2))
    diagnostic_rows = _diagnostic_by_target(diagnostic)
    rows = [
        _target_row(
            path,
            diagnostic_rows,
            target_alpha=target_alpha_eff,
            baseline_alpha=baseline_alpha,
            seeds=seed_list,
            alphas=alphas,
            threshold=threshold,
        )
        for path in _panel_records(panel_report)
    ]
    groups: Dict[str, List[str]] = {}
    for row in rows:
        groups.setdefault(str(row["gate_strategy"]), []).append(str(row["target"]))

    spend_gate_blockers = []
    if groups.get("replace_target_or_redesign_generation_protocol"):
        spend_gate_blockers.append("low_success_target_protocol_mismatch")
    if groups.get("target_specific_calibration_required"):
        spend_gate_blockers.append("cutoff_transfer_failure")
    if groups.get("label_degeneracy_policy_required_before_gate_claim"):
        spend_gate_blockers.append("label_degenerate_gate_validation_policy_missing")
    if groups.get("low_pae_acceptance_strategy_required"):
        spend_gate_blockers.append("low_pae_acceptance_strategy_missing")

    return {
        "artifact": "m6d_w2_gate_strategy",
        "branch_id": branch_id,
        "date": "2026-06-30",
        "status": "no_spend_gate_strategy_required",
        "panel_report": panel_report.get("artifact", "complex_panel_report"),
        "panel_status": panel_report.get("panel_status"),
        "target_alpha": target_alpha_eff,
        "baseline_alpha": baseline_alpha,
        "threshold": threshold,
        "seeds": seed_list,
        "n_targets": len(rows),
        "n_records": sum(int(row["n_records"]) for row in rows),
        "target_wise_certified_targets": [
            str(row["complex_target_id"]) for row in panel_report.get("targets", [])
            if isinstance(row, dict) and row.get("certified") is True
            and row.get("complex_target_id")
        ],
        "gate_strategy_groups": {key: _unique_sorted(value) for key, value in groups.items()},
        "spend_gate": {
            "cayuga_submission_allowed": False,
            "blockers": spend_gate_blockers,
            "unlock_conditions": [
                "predeclare how label-degenerate all-success targets can be used without weakening the TrustGate validation contract",
                "predeclare target-specific calibration or low-pAE acceptance criteria for high-success/no-trust targets",
                "replace or redesign generation/evaluation for target_protocol_mismatch_low_success targets",
                "run candidate-pool and manifest design only after the gate strategy is linked from the goal anchor",
            ],
        },
        "claim_boundary": {
            "w2_multi_target_generalization": "not_supported",
            "panel_readout": "fully_evaluable_but_not_certified",
            "high_success_targets": "diagnostic_anchors_only_not_generalization",
            "alpha_plan_gate_drift": "planning estimates are not certificates when actual TrustGate validation returns no tau",
        },
        "targets": rows,
        "next_action": (
            "write a no-spend W2 redesign branch that either replaces protocol-mismatch targets or "
            "predeclares a target-specific calibration/low-pAE acceptance strategy before any Cayuga panel"
        ),
        "can_mark_goal_complete": False,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Gate Strategy",
        "",
        f"Status: `{rep['status']}`",
        f"Branch: `{rep['branch_id']}`",
        f"Targets: {rep['n_targets']}  Records: {rep['n_records']}",
        f"Target alpha: {rep['target_alpha']}  Baseline alpha: {rep['baseline_alpha']}",
        "",
        "## Claim Boundary",
        "",
        "- W2 multi-target generalization remains not supported.",
        "- High-success targets are diagnostics or anchors only until the gate strategy is predeclared.",
        "- Alpha-plan estimates are not certificates when the actual TrustGate path returns no tau.",
        "",
        "## Strategy Groups",
        "",
    ]
    for key, targets in sorted(rep.get("gate_strategy_groups", {}).items()):
        lines.append(f"- `{key}`: {', '.join(targets) if targets else 'none'}")
    lines.extend([
        "",
        "## Targets",
        "",
        "| target | label class | diagnostic | success | a0.2 seeds | a0.3 seeds | addl median | strategy |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ])
    for row in rep.get("targets", []):
        addl = row.get("target_estimated_additional_records_median")
        addl_text = "n/a" if addl is None else f"{float(addl):.0f}"
        lines.append(
            "| {target} | {label} | {diag} | {success}/{n} | {a02}/{seeds} | {a03}/{seeds} | "
            "{addl} | {strategy} |".format(
                target=row.get("target"),
                label=row.get("label_class"),
                diag=row.get("diagnostic_classification"),
                success=row.get("success"),
                n=row.get("n_records"),
                a02=row.get("target_alpha_certified_count"),
                a03=row.get("baseline_alpha_certified_count"),
                seeds=row.get("n_seeds"),
                addl=addl_text,
                strategy=row.get("gate_strategy"),
            )
        )
    blockers = rep.get("spend_gate", {}).get("blockers", [])
    lines.extend([
        "",
        "## Spend Gate",
        "",
        f"Cayuga submission allowed: `{str(rep.get('spend_gate', {}).get('cayuga_submission_allowed')).lower()}`",
        f"Blockers: {', '.join(blockers) if blockers else 'none'}",
        "",
        "## Next Action",
        "",
        str(rep.get("next_action")),
        "",
    ])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build the no-spend W2 gate-strategy redesign artifact")
    ap.add_argument("--panel-report", required=True)
    ap.add_argument("--redesign-diagnostic", required=True)
    ap.add_argument("--branch-id", default=BRANCH_ID)
    ap.add_argument("--target-alpha", type=float, default=None)
    ap.add_argument("--baseline-alpha", type=float, default=0.3)
    ap.add_argument("--alphas", default=_DEFAULT_ALPHAS)
    ap.add_argument("--seeds", default="0:20")
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args(argv)

    rep = build_report(
        _load_json(args.panel_report),
        _load_json(args.redesign_diagnostic),
        branch_id=args.branch_id,
        target_alpha=args.target_alpha,
        baseline_alpha=args.baseline_alpha,
        seeds=_parse_seeds(args.seeds),
        alphas=args.alphas,
        threshold=args.threshold,
    )
    _write_json(args.out_json, rep)
    if args.out_md:
        _write_text(args.out_md, render_markdown(rep))
    print(
        "# m6d w2 gate strategy  status={status} targets={targets} spend_allowed={allowed}".format(
            status=rep["status"],
            targets=rep["n_targets"],
            allowed=rep["spend_gate"]["cayuga_submission_allowed"],
        )
    )
    print(f"wrote {args.out_json}")
    if args.out_md:
        print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
