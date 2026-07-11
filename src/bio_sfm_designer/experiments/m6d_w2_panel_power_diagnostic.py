"""Post-hoc power diagnostic for a split-LTT multi-target panel.

This does not certify or reinterpret a panel. It checks whether the declared
Hoeffding/Bonferroni design had enough certification samples to make the target
alpha attainable even in the best case of zero false accepts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional


def _minimum_accepted(alpha: float, delta: float) -> int:
    return math.ceil(math.log(1.0 / delta) / (2.0 * alpha * alpha))


def _split_sizes(n_records: int) -> Dict[str, int]:
    n_cal = max(1, min(n_records - 1, int((2 * n_records) / 3)))
    n_fit = n_cal // 2
    return {
        "n_records": n_records,
        "n_cal": n_cal,
        "n_fit": n_fit,
        "n_certification": n_cal - n_fit,
        "n_test": n_records - n_cal,
    }


def _minimum_records(minimum_accepted: int) -> Dict[str, int]:
    for n_records in range(3, 1_000_001):
        sizes = _split_sizes(n_records)
        if sizes["n_certification"] >= minimum_accepted:
            return sizes
    raise ValueError("minimum record search exceeded one million records")


def _target_id(row: Dict[str, Any]) -> str:
    return str(row.get("complex_target_id") or row.get("target_id") or "")


def diagnose(panel_report: Dict[str, Any]) -> Dict[str, Any]:
    targets = panel_report.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("panel report must contain non-empty targets")
    alpha = float(panel_report.get("target_alpha"))
    panel_delta = float(panel_report.get("panel_delta"))
    n_targets = int(panel_report.get("n_targets") or len(targets))
    if not (0.0 < alpha < 1.0):
        raise ValueError("target_alpha must be between 0 and 1")
    if not (0.0 < panel_delta < 1.0):
        raise ValueError("panel_delta must be between 0 and 1")
    if n_targets != len(targets):
        raise ValueError("reported n_targets does not match target rows")

    per_target_delta = panel_delta / n_targets
    minimum_accepted = _minimum_accepted(alpha, per_target_delta)
    minimum_split = _minimum_records(minimum_accepted)
    rows: List[Dict[str, Any]] = []
    helpful: List[str] = []
    inverse: List[str] = []
    undefined: List[str] = []
    all_success: List[str] = []
    all_failure: List[str] = []
    success_rates: List[float] = []
    aurocs: List[float] = []

    for target in sorted(targets, key=_target_id):
        target_id = _target_id(target)
        n_records = int(target.get("n_records") or 0)
        n_certification = int(target.get("n_certification") or 0)
        success = int(target.get("success") or 0)
        failure = int(target.get("failure") or 0)
        if not target_id or n_records <= 0 or n_certification <= 0:
            raise ValueError(f"invalid target power fields for {target_id or '<missing>'}")
        if success + failure != n_records:
            raise ValueError(f"success/failure count mismatch for {target_id}")
        floor = math.sqrt(math.log(1.0 / per_target_delta) / (2.0 * n_certification))
        success_rate = success / n_records
        success_rates.append(success_rate)
        auroc = target.get("auroc_pae")
        if auroc is None:
            undefined.append(target_id)
        else:
            value = float(auroc)
            aurocs.append(value)
            if value > 0.5:
                helpful.append(target_id)
            elif value < 0.5:
                inverse.append(target_id)
        if success == n_records:
            all_success.append(target_id)
        if failure == n_records:
            all_failure.append(target_id)
        rows.append({
            "target_id": target_id,
            "n_records": n_records,
            "n_certification": n_certification,
            "success": success,
            "failure": failure,
            "success_rate": success_rate,
            "auroc_pae": auroc,
            "hoeffding_zero_error_ucb_floor": floor,
            "minimum_zero_error_accepted": minimum_accepted,
            "certification_possible_at_current_split": n_certification >= minimum_accepted,
            "observed_status": target.get("status"),
            "observed_reason": target.get("not_certified_reason"),
        })

    structurally_underpowered = [
        row["target_id"] for row in rows
        if not row["certification_possible_at_current_split"]
    ]
    current_records = sorted({row["n_records"] for row in rows})
    additional = {
        row["target_id"]: max(0, minimum_split["n_records"] - row["n_records"])
        for row in rows
    }
    return {
        "artifact": "m6d_w2_panel_power_diagnostic",
        "status": (
            "declared_alpha_structurally_unattainable_at_current_split"
            if structurally_underpowered else
            "declared_alpha_attainable_in_zero_error_best_case"
        ),
        "audit_ok": True,
        "post_hoc": True,
        "can_recertify_current_panel": False,
        "panel_status": panel_report.get("panel_status"),
        "target_alpha": alpha,
        "panel_delta": panel_delta,
        "per_target_delta": per_target_delta,
        "n_targets": n_targets,
        "current_records_per_target": current_records,
        "minimum_zero_error_accepted": minimum_accepted,
        "minimum_records_per_target_for_zero_error_hoeffding_possibility": minimum_split,
        "additional_records_per_target_to_reach_best_case_floor": additional,
        "structurally_underpowered_targets": structurally_underpowered,
        "all_targets_structurally_underpowered": len(structurally_underpowered) == n_targets,
        "targets": rows,
        "signal_heterogeneity": {
            "success_rate_min": min(success_rates),
            "success_rate_max": max(success_rates),
            "auroc_pae_min_defined": min(aurocs) if aurocs else None,
            "auroc_pae_max_defined": max(aurocs) if aurocs else None,
            "helpful_direction_targets": helpful,
            "inverse_direction_targets": inverse,
            "undefined_one_class_targets": undefined,
            "all_success_targets": all_success,
            "all_failure_targets": all_failure,
        },
        "claim_boundary": (
            "This is a post-hoc design diagnostic. It cannot change the predeclared bound, "
            "certify the current panel, or justify a W2 generalization claim."
        ),
        "next_action": (
            "Predeclare the next W2 protocol before more compute: either increase per-target records "
            "enough for the chosen Hoeffding/Bonferroni split, or validate a tighter finite-sample "
            "bound and target-conditional hypothesis on new held-out targets."
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    split = report["minimum_records_per_target_for_zero_error_hoeffding_possibility"]
    lines = [
        "# W2 Panel Power Diagnostic",
        "",
        f"Status: `{report['status']}`.",
        f"Post-hoc: `{report['post_hoc']}`.",
        f"Can recertify current panel: `{report['can_recertify_current_panel']}`.",
        "",
        f"- target alpha: `{report['target_alpha']}`",
        f"- panel delta: `{report['panel_delta']}`",
        f"- per-target delta: `{report['per_target_delta']}`",
        f"- minimum zero-error accepted samples: `{report['minimum_zero_error_accepted']}`",
        f"- minimum records per target under the current split: `{split['n_records']}`",
        f"- resulting fit/certification/test: `{split['n_fit']}/{split['n_certification']}/{split['n_test']}`",
        "",
        "## Targets",
        "",
        "| target | success | AUROC | cert n | zero-error floor | attainable |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["targets"]:
        auroc = "n/a" if row["auroc_pae"] is None else f"{row['auroc_pae']:.3f}"
        lines.append(
            f"| {row['target_id']} | {row['success']}/{row['n_records']} | {auroc} | "
            f"{row['n_certification']} | {row['hoeffding_zero_error_ucb_floor']:.3f} | "
            f"{row['certification_possible_at_current_split']} |"
        )
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        report["claim_boundary"],
        "",
        "## Next Action",
        "",
        report["next_action"],
        "",
    ])
    return "\n".join(lines)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        obj = json.load(handle)
    if not isinstance(obj, dict):
        raise ValueError("panel report must contain a JSON object")
    return obj


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-report", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args(argv)
    report = diagnose(_load_json(args.panel_report))
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} targets={report['n_targets']} "
        f"minimum_records={report['minimum_records_per_target_for_zero_error_hoeffding_possibility']['n_records']} "
        f"can_recertify={report['can_recertify_current_panel']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
