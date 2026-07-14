"""Fit, certify, and test the frozen W3b matched-predictor disagreement gate."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    from bio_sfm_trust import clopper_pearson_upper_bound
except ImportError:
    from ..trust._split_ltt_compat import clopper_pearson_upper_bound


_PREDICTORS = ("boltz2_complex", "af2_multimer_colabfold_v1")
_ROLES = ("fit", "certification", "held_out_test")


def _failure(failures: List[Dict[str, Any]], kind: str, message: str, **context: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update(context)
    failures.append(row)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _prepare_rows(
    protocol: Dict[str, Any],
    target_manifest: Dict[str, Any],
    records: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    locked = protocol["locked_scientific_protocol"]
    threshold = float(locked["predictor_contract"]["label_threshold"])
    manifest_roles = {
        str(row.get("id") or ""): str(row.get("experimental_role") or "")
        for row in target_manifest.get("targets", [])
        if isinstance(row, dict)
    }
    expected_namespaces = {
        "fit": locked["fit_design"]["seed_namespace"],
        "certification": locked["certification_design"]["seed_namespace"],
        "held_out_test": locked["held_out_test_design"]["seed_namespace"],
    }
    seen: set[str] = set()
    prepared: List[Dict[str, Any]] = []
    for index, source in enumerate(records):
        if not isinstance(source, dict):
            _failure(failures, "record_not_object", "record must be an object", index=index)
            continue
        candidate_id = str(source.get("candidate_id") or "")
        target_id = str(source.get("target_id") or "")
        role = str(source.get("experimental_role") or "")
        if not candidate_id or candidate_id in seen:
            _failure(failures, "candidate_id_invalid", "candidate ids must be non-empty and unique", candidate_id=candidate_id)
            continue
        seen.add(candidate_id)
        if target_id not in manifest_roles:
            _failure(failures, "unknown_target", "record target is absent from the frozen manifest", candidate_id=candidate_id, target_id=target_id)
            continue
        if role != manifest_roles[target_id] or role not in _ROLES:
            _failure(failures, "role_mismatch", "record role differs from the frozen target role", candidate_id=candidate_id, target_id=target_id)
            continue
        if source.get("seed_namespace") != expected_namespaces[role]:
            _failure(failures, "seed_namespace_mismatch", "record uses the wrong frozen stage namespace", candidate_id=candidate_id)
            continue
        predictors = source.get("predictors")
        if not isinstance(predictors, dict) or set(predictors) != set(_PREDICTORS):
            _failure(failures, "predictor_pair_incomplete", "record must contain exactly the frozen predictor pair", candidate_id=candidate_id)
            continue

        values: Dict[str, Dict[str, Any]] = {}
        row_invalid = False
        for predictor_id in _PREDICTORS:
            pred = predictors.get(predictor_id)
            if not isinstance(pred, dict):
                row_invalid = True
                break
            pae = _as_float(pred.get("pae_interaction"))
            lrmsd = _as_float(pred.get("lrmsd"))
            label_threshold = _as_float(pred.get("label_threshold"))
            label = pred.get("label")
            if pae is None or pae < 0.0 or lrmsd is None or lrmsd < 0.0:
                row_invalid = True
                break
            if label_threshold is None or not math.isclose(label_threshold, threshold, abs_tol=1e-12):
                row_invalid = True
                break
            expected_label = lrmsd < threshold
            if label is not expected_label:
                row_invalid = True
                break
            if pred.get("templates_used") is not False or pred.get("seed") != 0:
                row_invalid = True
                break
            values[predictor_id] = {
                "candidate_sequence_sha256": pred.get("candidate_sequence_sha256"),
                "label": expected_label,
                "lrmsd": lrmsd,
                "pae_interaction": pae,
                "target_msa_sha256": pred.get("target_msa_sha256"),
            }
        if row_invalid:
            _failure(failures, "predictor_contract_invalid", "predictor fields violate the frozen matched protocol", candidate_id=candidate_id)
            continue
        candidate_hashes = {values[p]["candidate_sequence_sha256"] for p in _PREDICTORS}
        msa_hashes = {values[p]["target_msa_sha256"] for p in _PREDICTORS}
        if len(candidate_hashes) != 1 or None in candidate_hashes or "" in candidate_hashes:
            _failure(failures, "candidate_sequence_hash_mismatch", "predictors must fold the same candidate sequence", candidate_id=candidate_id)
            continue
        if len(msa_hashes) != 1 or None in msa_hashes or "" in msa_hashes:
            _failure(failures, "target_msa_hash_mismatch", "predictors must use the same target MSA", candidate_id=candidate_id)
            continue

        boltz_pae = float(values[_PREDICTORS[0]]["pae_interaction"])
        af2_pae = float(values[_PREDICTORS[1]]["pae_interaction"])
        prepared.append({
            "af2_pae": af2_pae,
            "candidate_id": candidate_id,
            "boltz_pae": boltz_pae,
            "max_pae": max(boltz_pae, af2_pae),
            "pae_gap": abs(boltz_pae - af2_pae),
            "role": role,
            "target_id": target_id,
            "wrong": {
                predictor_id: not bool(values[predictor_id]["label"])
                for predictor_id in _PREDICTORS
            },
        })
    return prepared, failures


def _accepted_stats(
    rows: List[Dict[str, Any]],
    accept: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    accepted = [row for row in rows if accept(row)]
    by_target = Counter(str(row["target_id"]) for row in accepted)
    errors = {
        predictor: sum(1 for row in accepted if row["wrong"][predictor])
        for predictor in _PREDICTORS
    }
    rates = {
        predictor: errors[predictor] / len(accepted) if accepted else None
        for predictor in _PREDICTORS
    }
    return {
        "accepted": len(accepted),
        "accepted_candidate_ids": [str(row["candidate_id"]) for row in accepted],
        "accepted_per_target": dict(sorted(by_target.items())),
        "errors": errors,
        "false_accept_rates": rates,
        "worst_false_accept_rate": max(rates.values()) if accepted else None,
    }


def _fit_rules(rows: List[Dict[str, Any]], fit: Dict[str, Any]) -> Dict[str, Any]:
    minimum_total = int(fit["minimum_total_accepted"])
    minimum_per_target = int(fit["minimum_accepted_per_target"])
    risk_cap = float(fit["maximum_empirical_false_accept_rate_per_predictor"])
    targets = sorted({str(row["target_id"]) for row in rows})

    def qualifies(stats: Dict[str, Any]) -> bool:
        return (
            stats["accepted"] >= minimum_total
            and all(stats["accepted_per_target"].get(target, 0) >= minimum_per_target for target in targets)
            and all(
                rate is not None and rate <= risk_cap + 1e-12
                for rate in stats["false_accept_rates"].values()
            )
        )

    primary_candidates: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for tau_max in sorted({float(row["max_pae"]) for row in rows}):
        for tau_gap in sorted({float(row["pae_gap"]) for row in rows}):
            stats = _accepted_stats(
                rows,
                lambda row, a=tau_max, b=tau_gap: row["max_pae"] <= a and row["pae_gap"] <= b,
            )
            if qualifies(stats):
                minimum_target = min(stats["accepted_per_target"].get(target, 0) for target in targets)
                key = (-stats["accepted"], -minimum_target, stats["worst_false_accept_rate"], tau_max, tau_gap)
                primary_candidates.append((key, {**stats, "tau_max_pae": tau_max, "tau_pae_gap": tau_gap}))

    comparator_candidates: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for tau_boltz in sorted({float(row["boltz_pae"]) for row in rows}):
        stats = _accepted_stats(rows, lambda row, a=tau_boltz: row["boltz_pae"] <= a)
        if qualifies(stats):
            minimum_target = min(stats["accepted_per_target"].get(target, 0) for target in targets)
            key = (-stats["accepted"], -minimum_target, stats["worst_false_accept_rate"], tau_boltz)
            comparator_candidates.append((key, {**stats, "tau_boltz": tau_boltz}))

    primary = min(primary_candidates, default=(None, None), key=lambda item: item[0])[1]
    comparator = min(comparator_candidates, default=(None, None), key=lambda item: item[0])[1]
    return {
        "comparator": comparator,
        "primary": primary,
        "primary_candidate_rules_considered": len(primary_candidates),
        "comparator_candidate_rules_considered": len(comparator_candidates),
        "rules_frozen": primary is not None and comparator is not None,
    }


def _primary_accept(rule: Dict[str, Any], row: Dict[str, Any]) -> bool:
    return row["max_pae"] <= rule["tau_max_pae"] and row["pae_gap"] <= rule["tau_pae_gap"]


def _comparator_accept(rule: Dict[str, Any], row: Dict[str, Any]) -> bool:
    return row["boltz_pae"] <= rule["tau_boltz"]


def _certify(
    rows: List[Dict[str, Any]],
    primary_rule: Dict[str, Any],
    design: Dict[str, Any],
) -> Dict[str, Any]:
    alpha = float(design["target_alpha"])
    delta = float(design["per_endpoint_delta"])
    minimum_accepted = int(design["minimum_accepted_per_target"])
    target_reports: List[Dict[str, Any]] = []
    for target in sorted({str(row["target_id"]) for row in rows}):
        target_rows = [row for row in rows if row["target_id"] == target]
        stats = _accepted_stats(target_rows, lambda row: _primary_accept(primary_rule, row))
        endpoint_reports: Dict[str, Dict[str, Any]] = {}
        for predictor in _PREDICTORS:
            errors = int(stats["errors"][predictor])
            accepted = int(stats["accepted"])
            ucb = clopper_pearson_upper_bound(errors, accepted, delta) if accepted else 1.0
            endpoint_reports[predictor] = {
                "accepted": accepted,
                "certified": accepted >= minimum_accepted and ucb <= alpha + 1e-12,
                "false_accept_rate": stats["false_accept_rates"][predictor],
                "false_accepts": errors,
                "risk_ucb": ucb,
            }
        target_reports.append({
            "accepted": stats["accepted"],
            "certified": all(report["certified"] for report in endpoint_reports.values()),
            "endpoints": endpoint_reports,
            "target_id": target,
        })
    n_certified = sum(1 for row in target_reports if row["certified"])
    minimum_targets = int(design["minimum_certified_targets"])
    return {
        "minimum_certified_targets": minimum_targets,
        "n_certified_targets": n_certified,
        "panel_certified": n_certified >= minimum_targets,
        "targets": target_reports,
    }


def _test_comparison(
    rows: List[Dict[str, Any]],
    primary_rule: Dict[str, Any],
    comparator_rule: Dict[str, Any],
    design: Dict[str, Any],
) -> Dict[str, Any]:
    target_reports: List[Dict[str, Any]] = []
    pooled_primary_rows: List[Dict[str, Any]] = []
    pooled_comparator_rows: List[Dict[str, Any]] = []
    all_target_no_worse = True
    all_target_channel_active = True
    all_target_minimum_coverage = True
    minimum_accepted = int(design["minimum_accepted_per_target"])
    for target in sorted({str(row["target_id"]) for row in rows}):
        target_rows = [row for row in rows if row["target_id"] == target]
        primary_stats = _accepted_stats(target_rows, lambda row: _primary_accept(primary_rule, row))
        comparator_stats = _accepted_stats(target_rows, lambda row: _comparator_accept(comparator_rule, row))
        primary_ids = set(primary_stats["accepted_candidate_ids"])
        comparator_ids = set(comparator_stats["accepted_candidate_ids"])
        disagreement_abstentions = len(comparator_ids - primary_ids)
        primary_worst = primary_stats["worst_false_accept_rate"]
        comparator_worst = comparator_stats["worst_false_accept_rate"]
        no_worse = (
            primary_worst is not None
            and comparator_worst is not None
            and primary_worst <= comparator_worst + 1e-12
        )
        coverage_ok = primary_stats["accepted"] >= minimum_accepted
        channel_active = disagreement_abstentions > 0
        all_target_no_worse = all_target_no_worse and no_worse
        all_target_minimum_coverage = all_target_minimum_coverage and coverage_ok
        all_target_channel_active = all_target_channel_active and channel_active
        pooled_primary_rows.extend(row for row in target_rows if row["candidate_id"] in primary_ids)
        pooled_comparator_rows.extend(row for row in target_rows if row["candidate_id"] in comparator_ids)
        target_reports.append({
            "comparator": comparator_stats,
            "disagreement_abstentions": disagreement_abstentions,
            "minimum_coverage_passed": coverage_ok,
            "primary": primary_stats,
            "primary_risk_no_worse": no_worse,
            "target_id": target,
        })

    primary_pooled = _accepted_stats(pooled_primary_rows, lambda row: True)
    comparator_pooled = _accepted_stats(pooled_comparator_rows, lambda row: True)
    primary_worst = primary_pooled["worst_false_accept_rate"]
    comparator_worst = comparator_pooled["worst_false_accept_rate"]
    coverage_retention = (
        primary_pooled["accepted"] / comparator_pooled["accepted"]
        if comparator_pooled["accepted"]
        else None
    )
    risk_improvement = (
        comparator_worst - primary_worst
        if comparator_worst is not None and primary_worst is not None
        else None
    )
    support = (
        all_target_no_worse
        and all_target_minimum_coverage
        and all_target_channel_active
        and coverage_retention is not None
        and coverage_retention + 1e-12 >= float(design["minimum_pooled_coverage_retention"])
        and risk_improvement is not None
        and risk_improvement + 1e-12
        >= float(design["minimum_pooled_worst_predictor_risk_improvement"])
    )
    return {
        "all_targets_disagreement_channel_active": all_target_channel_active,
        "all_targets_minimum_coverage_passed": all_target_minimum_coverage,
        "all_targets_primary_risk_no_worse": all_target_no_worse,
        "comparator_pooled": comparator_pooled,
        "pooled_coverage_retention": coverage_retention,
        "pooled_worst_predictor_risk_improvement": risk_improvement,
        "primary_pooled": primary_pooled,
        "supported": support,
        "targets": target_reports,
    }


def evaluate(
    protocol: Dict[str, Any],
    target_manifest: Dict[str, Any],
    records: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    prepared, failures = _prepare_rows(protocol, target_manifest, records)
    manifest_targets = [row for row in target_manifest.get("targets", []) if isinstance(row, dict)]
    role_targets = {
        role: sorted(str(row.get("id") or "") for row in manifest_targets if row.get("experimental_role") == role)
        for role in _ROLES
    }
    role_designs = {
        "fit": locked["fit_design"],
        "certification": locked["certification_design"],
        "held_out_test": locked["held_out_test_design"],
    }
    rows_by_role = {role: [row for row in prepared if row["role"] == role] for role in _ROLES}
    for role in _ROLES:
        role_rows = rows_by_role[role]
        if not role_rows:
            continue
        expected = int(role_designs[role]["records_per_target"])
        counts = Counter(str(row["target_id"]) for row in role_rows)
        if set(counts) != set(role_targets[role]):
            _failure(failures, f"{role}_target_set_mismatch", "stage rows do not cover exactly the frozen target role")
        for target in role_targets[role]:
            if counts.get(target, 0) != expected:
                _failure(
                    failures,
                    f"{role}_record_count_mismatch",
                    "stage target does not have the frozen record count",
                    expected=expected,
                    observed=counts.get(target, 0),
                    target_id=target,
                )

    fit_report: Dict[str, Any] = {"rules_frozen": False}
    certification_report: Optional[Dict[str, Any]] = None
    test_report: Optional[Dict[str, Any]] = None
    if not failures and rows_by_role["fit"]:
        fit_report = _fit_rules(rows_by_role["fit"], locked["fit_design"])
    if rows_by_role["certification"] and not fit_report.get("rules_frozen"):
        _failure(failures, "certification_before_frozen_fit", "certification rows cannot be used without frozen fit rules")
    if not failures and fit_report.get("rules_frozen") and rows_by_role["certification"]:
        certification_report = _certify(
            rows_by_role["certification"],
            fit_report["primary"],
            locked["certification_design"],
        )
    if rows_by_role["held_out_test"] and not (
        certification_report and certification_report.get("panel_certified")
    ):
        _failure(failures, "test_before_successful_certification", "test rows cannot rescue or precede successful certification")
    if not failures and certification_report and rows_by_role["held_out_test"]:
        test_report = _test_comparison(
            rows_by_role["held_out_test"],
            fit_report["primary"],
            fit_report["comparator"],
            locked["held_out_test_design"],
        )

    if failures:
        status = "w3b_gate_audit_blocked"
    elif not rows_by_role["fit"]:
        status = "w3b_awaiting_fit_records"
    elif not fit_report.get("rules_frozen"):
        status = "w3b_fit_rule_not_found_stop"
    elif not rows_by_role["certification"]:
        status = "w3b_fit_rules_frozen_awaiting_certification"
    elif not certification_report or not certification_report.get("panel_certified"):
        status = "w3b_certification_not_supported_stop_before_test"
    elif not rows_by_role["held_out_test"]:
        status = "w3b_certified_awaiting_held_out_test"
    elif test_report and test_report.get("supported"):
        status = "w3b_disagreement_gate_certified_and_test_supported"
    else:
        status = "w3b_certified_but_test_not_supported"

    bounded_claim = status == "w3b_disagreement_gate_certified_and_test_supported"
    return {
        "artifact": "m6d_w3b_disagreement_gate_report",
        "audit_ok": not failures,
        "can_claim_bounded_disagreement_gate_viability": bounded_claim,
        "can_claim_biological_binder_success": False,
        "can_claim_population_level_independent_predictor_robustness": False,
        "can_reopen_or_rescue_w2c": False,
        "certification": certification_report,
        "failures": failures,
        "fit": fit_report,
        "record_counts": {role: len(rows_by_role[role]) for role in _ROLES},
        "status": status,
        "test": test_report,
        "test_can_change_certificate": False,
        "claim_boundary": (
            "Even a positive result is limited to matched-predictor structural-proxy risk under the frozen "
            "targets and runtimes; it is not wet-lab success, universal robustness, or W2c rescue."
        ),
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} is not an object")
            rows.append(value)
    return rows


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--target-manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--records", required=True)
    parser.add_argument("--out", default="results/m6d_w3b_disagreement_gate_report.json")
    args = parser.parse_args(argv)
    report = evaluate(_load_json(args.protocol), _load_json(args.target_manifest), _load_jsonl(args.records))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"status={report['status']} audit_ok={report['audit_ok']} claim={report['can_claim_bounded_disagreement_gate_viability']}")
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
