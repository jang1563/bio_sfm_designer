"""Evaluate the locked W2c learning, independent-screen, and certification stages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from bio_sfm_trust import clopper_pearson_upper_bound
except ImportError:  # compatible with the published trust-core v0.1.0 tag
    from ..trust._split_ltt_compat import clopper_pearson_upper_bound

from .complex_gate_sweep import load_merged_records
from .complex_records_qc import run_qc


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _group(rows: Iterable[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("complex_target_id") or "")].append(row)
    return dict(grouped)


def _wrong(row: dict, threshold: float) -> int:
    return int(float(row["lrmsd"]) >= threshold)


def _auroc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    positive = [score for score, label in zip(scores, labels) if label]
    negative = [score for score, label in zip(scores, labels) if not label]
    if not positive or not negative:
        return None
    return sum(
        (positive_score > negative_score) + 0.5 * (positive_score == negative_score)
        for positive_score in positive
        for negative_score in negative
    ) / (len(positive) * len(negative))


def _acceptance_lcb(accepted: int, generated: int, delta: float) -> float:
    return 1.0 - clopper_pearson_upper_bound(generated - accepted, generated, delta)


def _learn_threshold(rows: List[dict], fit: Dict[str, Any], threshold: float) -> Dict[str, Any]:
    rule = fit["threshold_learning"]
    minimum_accepts = int(rule["minimum_accepted"])
    empirical_cap = float(rule["maximum_empirical_false_accept_rate"])
    minimum_auroc = float(rule["minimum_auroc"])
    wrong = [_wrong(row, threshold) for row in rows]
    success = [1 - value for value in wrong]
    auroc = _auroc([-float(row["pae_interaction"]) for row in rows], success)
    best: Optional[Dict[str, Any]] = None
    if auroc is not None and auroc >= minimum_auroc:
        ordered = sorted((float(row["pae_interaction"]), value) for row, value in zip(rows, wrong))
        for tau in sorted({pae for pae, _ in ordered}):
            accepted = [value for pae, value in ordered if pae <= tau]
            empirical = sum(accepted) / len(accepted)
            if len(accepted) >= minimum_accepts and empirical <= empirical_cap:
                best = {
                    "mode": "selective_pae",
                    "tau": tau,
                    "accepted": len(accepted),
                    "false_accepts": sum(accepted),
                    "false_accept_rate": empirical,
                    "auroc_pae": auroc,
                    "candidate": True,
                }
    if best is not None:
        return best
    return {
        "mode": "refuse",
        "tau": None,
        "accepted": 0,
        "false_accepts": 0,
        "false_accept_rate": None,
        "auroc_pae": auroc,
        "candidate": False,
    }


def _accepted(rows: Iterable[dict], tau: Optional[float]) -> List[dict]:
    if tau is None:
        return []
    return [row for row in rows if float(row["pae_interaction"]) <= float(tau)]


def _screen_rule(
    rows: List[dict],
    learned: Dict[str, Any],
    fit: Dict[str, Any],
    threshold: float,
) -> Dict[str, Any]:
    rule = fit["independent_screen"]
    if not rows:
        return {
            "mode": "selective_pae" if learned["candidate"] else "refuse",
            "tau": learned["tau"],
            "n": 0,
            "accepted": 0,
            "false_accepts": 0,
            "false_accept_rate": None,
            "risk_ucb": None,
            "risk_delta": float(rule["risk_delta"]),
            "acceptance_rate_lcb": None,
            "acceptance_rate_delta": float(rule["acceptance_rate_delta"]),
            "eligible": False,
            "reason": "missing_screen_rows",
        }
    accepted = _accepted(rows, learned["tau"])
    false_accepts = sum(_wrong(row, threshold) for row in accepted)
    empirical = false_accepts / len(accepted) if accepted else None
    risk_ucb = (
        clopper_pearson_upper_bound(false_accepts, len(accepted), float(rule["risk_delta"]))
        if accepted else None
    )
    acceptance_lcb = _acceptance_lcb(
        len(accepted), len(rows), float(rule["acceptance_rate_delta"])
    )
    eligible = (
        learned["candidate"]
        and len(accepted) >= int(rule["minimum_accepted"])
        and empirical is not None
        and empirical <= float(rule["maximum_empirical_false_accept_rate"])
        and risk_ucb is not None
        and risk_ucb <= float(rule["maximum_risk_ucb"])
        and acceptance_lcb >= float(rule["minimum_acceptance_rate_lcb"])
    )
    if not learned["candidate"]:
        reason = "learning_refused"
    elif len(accepted) < int(rule["minimum_accepted"]):
        reason = "too_few_screen_accepts"
    elif empirical is None or empirical > float(rule["maximum_empirical_false_accept_rate"]):
        reason = "screen_empirical_risk_above_cap"
    elif risk_ucb is None or risk_ucb > float(rule["maximum_risk_ucb"]):
        reason = "screen_risk_ucb_above_cap"
    elif acceptance_lcb < float(rule["minimum_acceptance_rate_lcb"]):
        reason = "screen_acceptance_rate_lcb_below_floor"
    else:
        reason = "eligible"
    return {
        "mode": "selective_pae" if learned["candidate"] else "refuse",
        "tau": learned["tau"],
        "n": len(rows),
        "accepted": len(accepted),
        "false_accepts": false_accepts,
        "false_accept_rate": empirical,
        "risk_ucb": risk_ucb,
        "risk_delta": float(rule["risk_delta"]),
        "acceptance_rate_lcb": acceptance_lcb,
        "acceptance_rate_delta": float(rule["acceptance_rate_delta"]),
        "eligible": eligible,
        "reason": reason,
    }


def _threshold_matches(row: dict, expected: float) -> bool:
    try:
        return float(row["lrmsd_threshold"]) == expected
    except (KeyError, TypeError, ValueError):
        return False


def _stage_failures(
    rows: List[dict],
    *,
    stage: str,
    namespace: str,
    expected_targets: Sequence[str],
    expected_count: int,
    threshold: float,
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    grouped = _group(rows)
    unexpected = sorted(set(grouped) - set(expected_targets) - {""})
    if "" in grouped:
        failures.append({"kind": "missing_complex_target_id", "stage": stage})
    if unexpected:
        failures.append({"kind": "unexpected_stage_targets", "stage": stage, "targets": unexpected})
    for target_id in expected_targets:
        count = len(grouped.get(target_id, []))
        if count != expected_count:
            failures.append({
                "kind": "stage_record_count_mismatch",
                "stage": stage,
                "target_id": target_id,
                "observed": count,
                "expected": expected_count,
            })
    bad_metadata = [
        str(row.get("target_id") or "")
        for row in rows
        if row.get("w2c_stage") != stage or row.get("w2c_seed_namespace") != namespace
    ]
    if bad_metadata:
        failures.append({
            "kind": "stage_namespace_mismatch",
            "stage": stage,
            "count": len(bad_metadata),
            "examples": bad_metadata[:5],
        })
    bad_ids = [
        str(row.get("target_id") or "")
        for row in rows
        if not str(row.get("target_id") or "").startswith(
            f"{namespace}-{str(row.get('complex_target_id') or '')}-"
        )
    ]
    if bad_ids:
        failures.append({
            "kind": "stage_candidate_id_namespace_mismatch",
            "stage": stage,
            "count": len(bad_ids),
            "examples": bad_ids[:5],
        })
    bad_thresholds = [
        str(row.get("target_id") or "")
        for row in rows
        if not _threshold_matches(row, threshold)
    ]
    if bad_thresholds:
        failures.append({
            "kind": "stage_lrmsd_threshold_mismatch",
            "stage": stage,
            "count": len(bad_thresholds),
            "examples": bad_thresholds[:5],
        })
    candidate_ids = [str(row.get("target_id") or "") for row in rows]
    if "" in candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        failures.append({"kind": "missing_or_duplicate_candidate_id", "stage": stage})
    missing_representations = [
        value for value, row in zip(candidate_ids, rows)
        if not isinstance(row.get("representation"), str) or not row["representation"]
    ]
    if missing_representations:
        failures.append({
            "kind": "missing_candidate_representation",
            "stage": stage,
            "count": len(missing_representations),
            "examples": missing_representations[:5],
        })
    return failures


def _cross_stage_failures(stages: Dict[str, List[dict]]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    names = list(stages)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            left_ids = {str(row.get("target_id") or "") for row in stages[left]} - {""}
            right_ids = {str(row.get("target_id") or "") for row in stages[right]} - {""}
            id_overlap = sorted(left_ids & right_ids)
            if id_overlap:
                failures.append({
                    "kind": "candidate_overlap_across_stages",
                    "stages": [left, right],
                    "count": len(id_overlap),
                    "examples": id_overlap[:5],
                })
            left_sequences = {
                (str(row.get("complex_target_id") or ""), str(row.get("representation") or ""))
                for row in stages[left]
                if row.get("complex_target_id") and row.get("representation")
            }
            right_sequences = {
                (str(row.get("complex_target_id") or ""), str(row.get("representation") or ""))
                for row in stages[right]
                if row.get("complex_target_id") and row.get("representation")
            }
            sequence_overlap = sorted(left_sequences & right_sequences)
            if sequence_overlap:
                failures.append({
                    "kind": "candidate_sequence_overlap_across_stages",
                    "stages": [left, right],
                    "count": len(sequence_overlap),
                    "examples": [f"{target}:{sequence}" for target, sequence in sequence_overlap[:5]],
                })
    return failures


def evaluate_threshold_learning(
    protocol: Dict[str, Any],
    learning_rows: Iterable[dict],
    *,
    threshold: float = 4.0,
    qc_ok: bool = True,
    qc_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Freeze or refuse W2c thresholds without consuming later-stage rows."""
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    rows = list(learning_rows)
    groups = _group(rows)
    target_ids = sorted(set(groups) - {""})
    expected_n = int(locked["fresh_target_contract"]["n_initial_targets"])
    learning_rule = locked["fit_design"]["threshold_learning"]
    minimum_selective = int(
        locked["panel_decision_rule"]["minimum_selective_pae_certified_targets"]
    )
    failures: List[Dict[str, Any]] = []
    if not qc_ok:
        failures.append({"kind": "complex_records_qc_failed"})
    if len(target_ids) != expected_n:
        failures.append({
            "kind": "initial_target_count_mismatch",
            "observed": len(target_ids),
            "expected": expected_n,
        })
    locked_target_ids = sorted(
        str(value) for value in protocol.get("execution_state", {}).get("target_ids", [])
    )
    if locked_target_ids and target_ids != locked_target_ids:
        failures.append({
            "kind": "locked_initial_target_identity_mismatch",
            "observed": target_ids,
            "expected": locked_target_ids,
        })
    failures.extend(_stage_failures(
        rows,
        stage="threshold_learning",
        namespace=str(learning_rule["seed_namespace"]),
        expected_targets=target_ids,
        expected_count=int(learning_rule["records_per_target"]),
        threshold=threshold,
    ))
    learned = {
        target_id: _learn_threshold(groups.get(target_id, []), locked["fit_design"], threshold)
        for target_id in target_ids
    }
    candidate_targets = sorted(
        target_id for target_id, rule in learned.items() if rule.get("candidate") is True
    )
    audit_ok = not failures
    candidate_floor_reachable = len(candidate_targets) >= minimum_selective
    terminal = audit_ok and not candidate_floor_reachable
    if failures:
        status = "w2c_threshold_learning_audit_failed"
    elif terminal:
        status = "w2c_threshold_learning_terminal_not_supported"
    else:
        status = "w2c_threshold_learning_complete_awaiting_screen_packet"
    return {
        "artifact": "m6d_w2c_threshold_learning_report",
        "status": status,
        "audit_ok": audit_ok,
        "can_claim_w2c_selective_target_adaptive_viability": False,
        "can_claim_universal_w2_generalization": False,
        "independent_screen_generation_approved": False,
        "certification_generation_approved": False,
        "locked_scientific_digest": _canonical_digest(locked),
        "lrmsd_threshold": threshold,
        "n_initial_targets": len(target_ids),
        "initial_target_ids": target_ids,
        "threshold_candidate_targets": candidate_targets,
        "n_threshold_candidate_targets": len(candidate_targets),
        "minimum_selective_targets_required": minimum_selective,
        "candidate_floor_reachable": candidate_floor_reachable,
        "terminal_after_threshold_learning": terminal,
        "threshold_decisions_frozen": audit_ok,
        "targets": [
            {
                "target_id": target_id,
                "learning": learned[target_id],
                "decision_frozen": audit_ok,
            }
            for target_id in target_ids
        ],
        "qc": qc_report,
        "failures": failures,
        "claim_boundary": (
            "Threshold-learning evidence only. This report freezes or refuses target-specific pAE "
            "rules but does not evaluate, authorize, or support independent screening, certification, "
            "W2c viability, or universal W2 generalization."
        ),
        "next_action": (
            "Close W2c before independent-screen compute because fewer than the required selective "
            "targets can remain eligible under the frozen learning decisions."
            if terminal else
            "Prepare a separate hash-bound independent-screen packet and require explicit approval; "
            "do not retune the frozen learning decisions."
            if audit_ok else
            "Repair threshold-learning QC or provenance failures without changing locked scientific rules."
        ),
    }


def evaluate(
    protocol: Dict[str, Any],
    learning_rows: Iterable[dict],
    screen_rows: Iterable[dict],
    certification_rows: Iterable[dict] = (),
    *,
    threshold: float = 4.0,
    qc_ok: bool = True,
    qc_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    learning_rows = list(learning_rows)
    screen_rows = list(screen_rows)
    certification_rows = list(certification_rows)
    learning_groups = _group(learning_rows)
    target_ids = sorted(set(learning_groups) - {""})
    expected_n = int(locked["fresh_target_contract"]["n_initial_targets"])
    failures: List[Dict[str, Any]] = []
    if not qc_ok:
        failures.append({"kind": "complex_records_qc_failed"})
    if len(target_ids) != expected_n:
        failures.append({
            "kind": "initial_target_count_mismatch",
            "observed": len(target_ids),
            "expected": expected_n,
        })
    locked_target_ids = sorted(str(value) for value in protocol.get("execution_state", {}).get("target_ids", []))
    if locked_target_ids and target_ids != locked_target_ids:
        failures.append({
            "kind": "locked_initial_target_identity_mismatch",
            "observed": target_ids,
            "expected": locked_target_ids,
        })

    fit = locked["fit_design"]
    learning_rule = fit["threshold_learning"]
    screen_rule = fit["independent_screen"]
    certification_rule = locked["certification_design"]
    failures.extend(_stage_failures(
        learning_rows,
        stage="threshold_learning",
        namespace=str(learning_rule["seed_namespace"]),
        expected_targets=target_ids,
        expected_count=int(learning_rule["records_per_target"]),
        threshold=threshold,
    ))
    failures.extend(_stage_failures(
        screen_rows,
        stage="independent_screen",
        namespace=str(screen_rule["seed_namespace"]),
        expected_targets=target_ids,
        expected_count=int(screen_rule["records_per_target"]),
        threshold=threshold,
    ))

    learned = {
        target_id: _learn_threshold(learning_groups.get(target_id, []), fit, threshold)
        for target_id in target_ids
    }
    screen_groups = _group(screen_rows)
    screened = {
        target_id: _screen_rule(screen_groups.get(target_id, []), learned[target_id], fit, threshold)
        for target_id in target_ids
    }
    eligible = sorted(target_id for target_id in target_ids if screened[target_id]["eligible"])
    minimum_selective = int(locked["panel_decision_rule"]["minimum_selective_pae_certified_targets"])
    if certification_rows:
        failures.extend(_stage_failures(
            certification_rows,
            stage="certification",
            namespace=str(certification_rule["seed_namespace"]),
            expected_targets=eligible,
            expected_count=int(certification_rule["records_per_target"]),
            threshold=threshold,
        ))
    stages = {
        "threshold_learning": learning_rows,
        "independent_screen": screen_rows,
        "certification": certification_rows,
    }
    failures.extend(_cross_stage_failures(stages))

    certification_groups = _group(certification_rows)
    target_reports: List[Dict[str, Any]] = []
    for target_id in target_ids:
        certification: Optional[Dict[str, Any]] = None
        if target_id in eligible and certification_rows:
            rows = certification_groups.get(target_id, [])
            accepted = _accepted(rows, learned[target_id]["tau"])
            false_accepts = sum(_wrong(row, threshold) for row in accepted)
            ucb = (
                clopper_pearson_upper_bound(
                    false_accepts,
                    len(accepted),
                    float(certification_rule["per_target_delta"]),
                )
                if accepted else None
            )
            certified = (
                len(accepted) >= int(certification_rule["minimum_accepted"])
                and ucb is not None
                and ucb <= float(certification_rule["target_alpha"])
            )
            certification = {
                "method": certification_rule["method"],
                "n": len(rows),
                "accepted": len(accepted),
                "false_accepts": false_accepts,
                "false_accept_rate": false_accepts / len(accepted) if accepted else None,
                "ucb": ucb,
                "alpha": float(certification_rule["target_alpha"]),
                "delta": float(certification_rule["per_target_delta"]),
                "certified": certified,
                "reason": (
                    "certified" if certified else
                    "too_few_accepted" if len(accepted) < int(certification_rule["minimum_accepted"]) else
                    "clopper_pearson_ucb_exceeds_alpha"
                ),
            }
        target_reports.append({
            "target_id": target_id,
            "learning": learned[target_id],
            "independent_screen": screened[target_id],
            "certification": certification,
        })

    certified_targets = [
        row["target_id"] for row in target_reports
        if row["certification"] and row["certification"]["certified"]
    ]
    panel_passed = (
        not failures
        and bool(certification_rows)
        and len(certified_targets) >= int(locked["panel_decision_rule"]["minimum_certified_targets"])
        and len(certified_targets) >= minimum_selective
    )
    if failures:
        status = "w2c_audit_failed"
    elif len(eligible) < minimum_selective:
        status = "w2c_fit_screen_terminal_not_supported"
    elif not certification_rows:
        status = "w2c_fit_screen_complete_awaiting_certification"
    elif panel_passed:
        status = "w2c_selective_target_adaptive_viability_supported"
    else:
        status = "w2c_certification_terminal_not_supported"
    return {
        "artifact": "m6d_w2c_one_shot_report",
        "status": status,
        "audit_ok": not failures,
        "can_claim_w2c_selective_target_adaptive_viability": panel_passed,
        "can_claim_universal_w2_generalization": False,
        "locked_scientific_digest": _canonical_digest(locked),
        "lrmsd_threshold": threshold,
        "n_initial_targets": len(target_ids),
        "initial_target_ids": target_ids,
        "fit_screen_eligible_targets": eligible,
        "certified_targets": certified_targets,
        "panel_gate": {
            "minimum_certified_targets": int(locked["panel_decision_rule"]["minimum_certified_targets"]),
            "minimum_selective_pae_certified_targets": minimum_selective,
            "observed_certified_targets": len(certified_targets),
            "observed_selective_pae_certified_targets": len(certified_targets),
            "passed": panel_passed,
        },
        "terminal_after_fit_screen": not failures and len(eligible) < minimum_selective,
        "adaptive_top_up_allowed": False,
        "targets": target_reports,
        "qc": qc_report,
        "failures": failures,
        "claim_boundary": (
            "W2c is selective-pAE-only and target-adaptive. Even a positive panel would not support a "
            "universal threshold, zero-shot W2 generalization, or independent-predictor robustness."
        ),
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w2c_one_shot_protocol.json")
    parser.add_argument("--threshold-learning-records", nargs="+", required=True)
    parser.add_argument("--independent-screen-records", nargs="*", default=[])
    parser.add_argument("--certification-records", nargs="*", default=[])
    parser.add_argument("--learning-only", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.learning_only and (args.independent_screen_records or args.certification_records):
        parser.error("--learning-only forbids independent-screen and certification inputs")
    if not args.learning_only and not args.independent_screen_records:
        parser.error("--independent-screen-records is required unless --learning-only is set")

    all_paths = [
        *args.threshold_learning_records,
        *args.independent_screen_records,
        *args.certification_records,
    ]
    qc = run_qc(
        all_paths,
        require_complex_target_id=True,
        require_provenance=True,
        require_chain_ids=True,
        expect_predictor_id="boltz2_complex",
        expect_signal_source="boltz2_pae_interaction",
        expect_label_source="boltz2_lrmsd_to_reference",
    )
    if args.learning_only:
        report = evaluate_threshold_learning(
            _load_json(args.protocol),
            load_merged_records(args.threshold_learning_records),
            qc_ok=qc.get("ok") is True,
            qc_report=qc,
        )
    else:
        report = evaluate(
            _load_json(args.protocol),
            load_merged_records(args.threshold_learning_records),
            load_merged_records(args.independent_screen_records),
            load_merged_records(args.certification_records),
            qc_ok=qc.get("ok") is True,
            qc_report=qc,
        )
    _write_json(args.out, report)
    if args.learning_only:
        print(
            f"status={report['status']} "
            f"candidates={report['n_threshold_candidate_targets']} audit_ok={report['audit_ok']}"
        )
    else:
        print(
            f"status={report['status']} eligible={len(report['fit_screen_eligible_targets'])} "
            f"certified={len(report['certified_targets'])} audit_ok={report['audit_ok']}"
        )
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
