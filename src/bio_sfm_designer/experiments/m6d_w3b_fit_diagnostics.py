"""Describe a terminal W3b fit failure without changing the frozen decision rule."""

from __future__ import annotations

import argparse
import json
import os
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bio_sfm_designer.experiments.m6d_w3b_disagreement_gate import (
    _accepted_stats,
    _prepare_rows,
)


_PREDICTORS = ("boltz2_complex", "af2_multimer_colabfold_v1")


def _compact_stats(stats: Dict[str, Any], targets: List[str]) -> Dict[str, Any]:
    return {
        "accepted": stats["accepted"],
        "accepted_per_target": {
            target: int(stats["accepted_per_target"].get(target, 0))
            for target in targets
        },
        "errors": stats["errors"],
        "false_accept_rates": stats["false_accept_rates"],
        "worst_false_accept_rate": stats["worst_false_accept_rate"],
    }


def _distribution(values: List[float]) -> Dict[str, float]:
    return {
        "minimum": min(values),
        "median": median(values),
        "maximum": max(values),
    }


def _enumerate_rules(
    rows: List[Dict[str, Any]], fit: Dict[str, Any]
) -> Dict[str, Any]:
    targets = sorted({str(row["target_id"]) for row in rows})
    minimum_total = int(fit["minimum_total_accepted"])
    minimum_per_target = int(fit["minimum_accepted_per_target"])
    risk_cap = float(fit["maximum_empirical_false_accept_rate_per_predictor"])

    def coverage_ok(stats: Dict[str, Any]) -> bool:
        return (
            stats["accepted"] >= minimum_total
            and all(
                stats["accepted_per_target"].get(target, 0) >= minimum_per_target
                for target in targets
            )
        )

    def risk_ok(stats: Dict[str, Any]) -> bool:
        return bool(stats["accepted"]) and all(
            value is not None and value <= risk_cap + 1e-12
            for value in stats["false_accept_rates"].values()
        )

    primary_coverage: List[Tuple[Any, ...]] = []
    primary_risk: List[Tuple[Any, ...]] = []
    for tau_max in sorted({float(row["max_pae"]) for row in rows}):
        for tau_gap in sorted({float(row["pae_gap"]) for row in rows}):
            stats = _accepted_stats(
                rows,
                lambda row, a=tau_max, b=tau_gap: (
                    row["max_pae"] <= a and row["pae_gap"] <= b
                ),
            )
            compact = _compact_stats(stats, targets)
            if coverage_ok(stats):
                primary_coverage.append(
                    (
                        stats["worst_false_accept_rate"],
                        -stats["accepted"],
                        tau_max,
                        tau_gap,
                        compact,
                    )
                )
            if risk_ok(stats):
                primary_risk.append(
                    (
                        -stats["accepted"],
                        -min(compact["accepted_per_target"].values()),
                        tau_max,
                        tau_gap,
                        compact,
                    )
                )

    comparator_coverage: List[Tuple[Any, ...]] = []
    comparator_risk: List[Tuple[Any, ...]] = []
    for tau_boltz in sorted({float(row["boltz_pae"]) for row in rows}):
        stats = _accepted_stats(
            rows, lambda row, threshold=tau_boltz: row["boltz_pae"] <= threshold
        )
        compact = _compact_stats(stats, targets)
        if coverage_ok(stats):
            comparator_coverage.append(
                (
                    stats["worst_false_accept_rate"],
                    -stats["accepted"],
                    tau_boltz,
                    compact,
                )
            )
        if risk_ok(stats):
            comparator_risk.append(
                (
                    -stats["accepted"],
                    -min(compact["accepted_per_target"].values()),
                    tau_boltz,
                    compact,
                )
            )

    best_primary_coverage = min(primary_coverage, default=None)
    best_primary_risk = min(primary_risk, default=None)
    best_comparator_coverage = min(comparator_coverage, default=None)
    best_comparator_risk = min(comparator_risk, default=None)
    return {
        "primary": {
            "coverage_feasible_rule_count": len(primary_coverage),
            "best_risk_subject_to_frozen_coverage": (
                {
                    **best_primary_coverage[-1],
                    "tau_max_pae": best_primary_coverage[2],
                    "tau_pae_gap": best_primary_coverage[3],
                }
                if best_primary_coverage
                else None
            ),
            "risk_feasible_rule_count": len(primary_risk),
            "best_coverage_subject_to_frozen_risk_cap": (
                {
                    **best_primary_risk[-1],
                    "tau_max_pae": best_primary_risk[2],
                    "tau_pae_gap": best_primary_risk[3],
                }
                if best_primary_risk
                else None
            ),
        },
        "comparator": {
            "coverage_feasible_rule_count": len(comparator_coverage),
            "best_risk_subject_to_frozen_coverage": (
                {
                    **best_comparator_coverage[-1],
                    "tau_boltz": best_comparator_coverage[2],
                }
                if best_comparator_coverage
                else None
            ),
            "risk_feasible_rule_count": len(comparator_risk),
            "best_coverage_subject_to_frozen_risk_cap": (
                {
                    **best_comparator_risk[-1],
                    "tau_boltz": best_comparator_risk[2],
                }
                if best_comparator_risk
                else None
            ),
        },
    }


def diagnose_prepared_rows(
    rows: List[Dict[str, Any]], fit: Dict[str, Any]
) -> Dict[str, Any]:
    targets = sorted({str(row["target_id"]) for row in rows})
    minimum_per_target = int(fit["minimum_accepted_per_target"])
    risk_cap = float(fit["maximum_empirical_false_accept_rate_per_predictor"])
    target_reports: List[Dict[str, Any]] = []
    impossibility_proofs: List[Dict[str, Any]] = []
    for target in targets:
        target_rows = [row for row in rows if row["target_id"] == target]
        endpoints: Dict[str, Any] = {}
        for predictor in _PREDICTORS:
            wrong = sum(bool(row["wrong"][predictor]) for row in target_rows)
            endpoints[predictor] = {
                "wrong": wrong,
                "correct": len(target_rows) - wrong,
                "wrong_fraction": wrong / len(target_rows),
            }
            if wrong == len(target_rows):
                lower_bound = minimum_per_target / len(rows)
                impossibility_proofs.append({
                    "target_id": target,
                    "predictor_id": predictor,
                    "all_target_rows_wrong": True,
                    "minimum_target_accepts": minimum_per_target,
                    "maximum_total_accepts": len(rows),
                    "minimum_possible_global_false_accept_rate": lower_bound,
                    "frozen_risk_cap": risk_cap,
                    "violates_cap_even_if_all_rows_accepted": lower_bound > risk_cap,
                })
        target_reports.append({
            "target_id": target,
            "n_rows": len(target_rows),
            "label_disagreements": sum(
                row["wrong"][_PREDICTORS[0]] != row["wrong"][_PREDICTORS[1]]
                for row in target_rows
            ),
            "endpoints": endpoints,
            "predictor_distributions": {
                "boltz2_complex": {
                    "lrmsd": _distribution(
                        [float(row["boltz_lrmsd"]) for row in target_rows]
                    ),
                    "pae_interaction": _distribution(
                        [float(row["boltz_pae"]) for row in target_rows]
                    ),
                },
                "af2_multimer_colabfold_v1": {
                    "lrmsd": _distribution(
                        [float(row["af2_lrmsd"]) for row in target_rows]
                    ),
                    "pae_interaction": _distribution(
                        [float(row["af2_pae"]) for row in target_rows]
                    ),
                },
            },
        })
    exhaustive = _enumerate_rules(rows, fit)
    return {
        "target_reports": target_reports,
        "impossibility_proofs": impossibility_proofs,
        "frozen_fit_mathematically_impossible": any(
            row["violates_cap_even_if_all_rows_accepted"]
            for row in impossibility_proofs
        ),
        "exhaustive_threshold_diagnostics": exhaustive,
    }


def build_diagnostics(
    protocol: Dict[str, Any],
    target_manifest: Dict[str, Any],
    records: List[Dict[str, Any]],
    gate_report: Dict[str, Any],
) -> Dict[str, Any]:
    prepared, failures = _prepare_rows(protocol, target_manifest, records)
    fit_rows = [row for row in prepared if row["role"] == "fit"]
    if not (
        not failures
        and len(fit_rows) == 180
        and gate_report.get("artifact") == "m6d_w3b_disagreement_gate_report"
        and gate_report.get("audit_ok") is True
        and gate_report.get("status") == "w3b_fit_rule_not_found_stop"
        and gate_report.get("record_counts", {}).get("fit") == 180
        and gate_report.get("fit", {}).get("rules_frozen") is False
        and gate_report.get("fit", {}).get("primary") is None
        and gate_report.get("fit", {}).get("comparator") is None
    ):
        raise ValueError("W3b post-fit diagnostics require the audited terminal fit-stop result")

    raw_by_id = {str(row["candidate_id"]): row for row in records}
    for row in fit_rows:
        source = raw_by_id[row["candidate_id"]]["predictors"]
        row["boltz_lrmsd"] = source[_PREDICTORS[0]]["lrmsd"]
        row["af2_lrmsd"] = source[_PREDICTORS[1]]["lrmsd"]
    fit = protocol["locked_scientific_protocol"]["fit_design"]
    diagnostic = diagnose_prepared_rows(fit_rows, fit)
    return {
        "artifact": "m6d_w3b_fit_diagnostics",
        "version": 1,
        "status": "w3b_fit_terminal_negative_diagnostics_complete",
        "audit_ok": True,
        "n_records": len(fit_rows),
        "fit_rule_status": gate_report["status"],
        "rules_frozen": False,
        "certification_reachable": False,
        "certification_submission_authorized": False,
        "held_out_test_reachable": False,
        "can_claim_w3b": False,
        **diagnostic,
        "interpretation": (
            "The frozen fit gate failed before certification. The all-wrong 1FSK_LJ endpoint and "
            "minimum per-target coverage make the 0.08 empirical-risk cap mathematically impossible; "
            "threshold retuning cannot repair this preregistered experiment."
        ),
        "claim_boundary": (
            "Post-fit descriptive diagnostics only. These calculations cannot change the frozen rule, "
            "authorize certification/test compute, or support a W3b or biological-success claim."
        ),
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json"
    )
    parser.add_argument(
        "--target-manifest", default="configs/m6d_w3b_execution_targets.json"
    )
    parser.add_argument(
        "--records", default="results/m6d_w3b_fit_matched_records.jsonl"
    )
    parser.add_argument(
        "--gate-report", default="results/m6d_w3b_fit_gate_report.json"
    )
    parser.add_argument("--out", default="results/m6d_w3b_fit_diagnostics.json")
    args = parser.parse_args(argv)
    report = build_diagnostics(
        _load_json(args.protocol),
        _load_json(args.target_manifest),
        _load_jsonl(args.records),
        _load_json(args.gate_report),
    )
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"status={report['status']} impossible="
        f"{report['frozen_fit_mathematically_impossible']} certification=False"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
