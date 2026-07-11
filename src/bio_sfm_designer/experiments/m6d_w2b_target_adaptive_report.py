"""Predeclared W2b target-adaptive fit/certification/test evaluator."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from bio_sfm_trust import clopper_pearson_upper_bound
except ImportError:  # compatible with the published trust-core v0.1.0 tag
    from ..trust._split_ltt_compat import clopper_pearson_upper_bound

from .complex_gate_sweep import load_merged_records
from .complex_records_qc import run_qc


def _group(rows: Iterable[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        target_id = str(row.get("complex_target_id") or "")
        grouped[target_id].append(row)
    return dict(grouped)


def _wrong(row: dict, threshold: float) -> int:
    return int(float(row["lrmsd"]) >= threshold)


def _auroc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    positive = [score for score, label in zip(scores, labels) if label]
    negative = [score for score, label in zip(scores, labels) if not label]
    if not positive or not negative:
        return None
    return sum(
        (pos > neg) + 0.5 * (pos == neg)
        for pos in positive
        for neg in negative
    ) / (len(positive) * len(negative))


def _fit_mode(rows: List[dict], protocol: Dict[str, Any], threshold: float) -> Dict[str, Any]:
    alpha = float(protocol["fit_stage_rule"]["target_alpha"])
    minimum_accepts = int(protocol["fit_stage_rule"]["minimum_fit_accepts"])
    wrong = [_wrong(row, threshold) for row in rows]
    empirical_all = sum(wrong) / len(wrong)
    if empirical_all <= alpha:
        return {
            "mode": "trust_all",
            "tau": None,
            "fit_accepts": len(rows),
            "fit_false_accepts": sum(wrong),
            "fit_false_accept_rate": empirical_all,
            "fit_auroc_pae": _auroc(
                [-float(row["pae_interaction"]) for row in rows],
                [1 - value for value in wrong],
            ),
            "eligible": True,
        }

    success = [1 - value for value in wrong]
    auroc = _auroc([-float(row["pae_interaction"]) for row in rows], success)
    auroc_floor = 0.65
    for mode in protocol["fit_stage_rule"]["ordered_modes"]:
        if mode["mode"] == "selective_pae":
            text = str(mode.get("condition", ""))
            marker = "at least "
            if "AUROC" in text and marker in text:
                try:
                    auroc_floor = float(text.split(marker, 1)[1].split(",", 1)[0])
                except ValueError:
                    pass
            break
    best: Optional[Dict[str, Any]] = None
    if auroc is not None and auroc >= auroc_floor:
        ordered = sorted((float(row["pae_interaction"]), value) for row, value in zip(rows, wrong))
        for tau in sorted({value for value, _ in ordered}):
            accepted = [value for pae, value in ordered if pae <= tau]
            empirical = sum(accepted) / len(accepted)
            if len(accepted) >= minimum_accepts and empirical <= alpha:
                best = {
                    "mode": "selective_pae",
                    "tau": tau,
                    "fit_accepts": len(accepted),
                    "fit_false_accepts": sum(accepted),
                    "fit_false_accept_rate": empirical,
                    "fit_auroc_pae": auroc,
                    "eligible": True,
                }
    if best is not None:
        return best
    return {
        "mode": "refuse",
        "tau": None,
        "fit_accepts": 0,
        "fit_false_accepts": 0,
        "fit_false_accept_rate": None,
        "fit_auroc_pae": auroc,
        "eligible": False,
    }


def _accepted(rows: List[dict], fit: Dict[str, Any]) -> List[dict]:
    if fit["mode"] == "trust_all":
        return list(rows)
    if fit["mode"] == "selective_pae":
        return [row for row in rows if float(row["pae_interaction"]) <= float(fit["tau"])]
    return []


def _threshold_matches(row: dict, expected: float) -> bool:
    try:
        return float(row["lrmsd_threshold"]) == expected
    except (KeyError, TypeError, ValueError):
        return False


def _stage_failures(
    protocol: Dict[str, Any],
    stage: str,
    rows: List[dict],
    expected_targets: Sequence[str],
    threshold: float,
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    expected_namespace = protocol["generation_stages"][stage]["seed_namespace"]
    expected_count = int(protocol["generation_stages"][stage]["records_per_target"])
    grouped = _group(rows)
    if "" in grouped:
        failures.append({"kind": "missing_complex_target_id", "stage": stage})
    unexpected = sorted(set(grouped) - set(expected_targets) - {""})
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
        if row.get("w2b_stage") != stage
        or row.get("w2b_seed_namespace") != expected_namespace
    ]
    if bad_metadata:
        failures.append({
            "kind": "stage_namespace_mismatch",
            "stage": stage,
            "count": len(bad_metadata),
            "examples": bad_metadata[:5],
        })
    bad_id_namespaces = [
        str(row.get("target_id") or "")
        for row in rows
        if not str(row.get("target_id") or "").startswith(
            f"{expected_namespace}-{str(row.get('complex_target_id') or '')}-"
        )
    ]
    if bad_id_namespaces:
        failures.append({
            "kind": "stage_candidate_id_namespace_mismatch",
            "stage": stage,
            "count": len(bad_id_namespaces),
            "examples": bad_id_namespaces[:5],
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
            "expected": threshold,
            "count": len(bad_thresholds),
            "examples": bad_thresholds[:5],
        })
    missing_representation = [
        str(row.get("target_id") or "")
        for row in rows
        if not isinstance(row.get("representation"), str) or not row["representation"]
    ]
    if missing_representation:
        failures.append({
            "kind": "missing_candidate_representation",
            "stage": stage,
            "count": len(missing_representation),
            "examples": missing_representation[:5],
        })
    candidate_ids = [str(row.get("target_id") or "") for row in rows]
    if "" in candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        failures.append({"kind": "missing_or_duplicate_candidate_id", "stage": stage})
    return failures


def evaluate(
    protocol: Dict[str, Any],
    fit_rows: Iterable[dict],
    certification_rows: Iterable[dict] = (),
    test_rows: Iterable[dict] = (),
    *,
    threshold: float = 4.0,
    qc_ok: bool = True,
) -> Dict[str, Any]:
    if protocol.get("certification_rule", {}).get("method") != "one_sided_clopper_pearson_exact":
        raise ValueError("W2b protocol must predeclare one_sided_clopper_pearson_exact")
    fit_rows = list(fit_rows)
    certification_rows = list(certification_rows)
    test_rows = list(test_rows)
    fit_groups = _group(fit_rows)
    target_ids = sorted(set(fit_groups) - {""})
    locked_target_ids = sorted(
        str(value)
        for value in protocol.get("current_execution_state", {}).get("fit_target_ids", [])
    )
    expected_initial = int(protocol["fresh_target_contract"]["n_initial_targets"])
    failures: List[Dict[str, Any]] = []
    if not qc_ok:
        failures.append({"kind": "complex_records_qc_failed"})
    if len(target_ids) != expected_initial:
        failures.append({
            "kind": "initial_target_count_mismatch",
            "observed": len(target_ids),
            "expected": expected_initial,
        })
    if locked_target_ids and target_ids != locked_target_ids:
        failures.append({
            "kind": "locked_initial_target_identity_mismatch",
            "observed": target_ids,
            "expected": locked_target_ids,
            "missing": sorted(set(locked_target_ids) - set(target_ids)),
            "unexpected": sorted(set(target_ids) - set(locked_target_ids)),
        })
    excluded = set(protocol["fresh_target_contract"].get("exclude_v11_new_representative_targets", []))
    reused = sorted(set(target_ids) & excluded)
    if reused:
        failures.append({"kind": "excluded_target_reuse", "targets": reused})
    failures.extend(_stage_failures(protocol, "fit", fit_rows, target_ids, threshold))

    fit_reports = {
        target_id: _fit_mode(fit_groups[target_id], protocol, threshold)
        for target_id in target_ids
        if fit_groups.get(target_id)
    }
    eligible = sorted(target_id for target_id, row in fit_reports.items() if row["eligible"])
    refused = sorted(set(target_ids) - set(eligible))
    if certification_rows:
        failures.extend(
            _stage_failures(protocol, "certification", certification_rows, eligible, threshold)
        )
    if test_rows:
        failures.extend(_stage_failures(protocol, "test", test_rows, eligible, threshold))

    stage_ids = {
        "fit": {str(row.get("target_id") or "") for row in fit_rows},
        "certification": {str(row.get("target_id") or "") for row in certification_rows},
        "test": {str(row.get("target_id") or "") for row in test_rows},
    }
    stage_rows = {
        "fit": fit_rows,
        "certification": certification_rows,
        "test": test_rows,
    }
    for left, right in (("fit", "certification"), ("fit", "test"), ("certification", "test")):
        overlap = sorted((stage_ids[left] & stage_ids[right]) - {""})
        if overlap:
            failures.append({
                "kind": "candidate_overlap_across_stages",
                "stages": [left, right],
                "count": len(overlap),
                "examples": overlap[:5],
            })
        left_sequences = {
            (str(row.get("complex_target_id") or ""), str(row.get("representation") or ""))
            for row in stage_rows[left]
            if row.get("complex_target_id") and row.get("representation")
        }
        right_sequences = {
            (str(row.get("complex_target_id") or ""), str(row.get("representation") or ""))
            for row in stage_rows[right]
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

    cert_groups = _group(certification_rows)
    test_groups = _group(test_rows)
    cert_rule = protocol["certification_rule"]
    alpha = float(cert_rule["target_alpha"])
    delta = float(cert_rule["per_target_delta"])
    minimum_cert_accepts = int(cert_rule["minimum_certification_accepts"])
    targets = []
    for target_id in target_ids:
        fit = fit_reports[target_id]
        target: Dict[str, Any] = {"target_id": target_id, "fit": fit}
        if fit["eligible"] and certification_rows:
            target_cert_rows = cert_groups.get(target_id, [])
            accepted = _accepted(target_cert_rows, fit)
            false_accepts = sum(_wrong(row, threshold) for row in accepted)
            cert_auroc = _auroc(
                [-float(row["pae_interaction"]) for row in target_cert_rows],
                [int(not _wrong(row, threshold)) for row in target_cert_rows],
            )
            ucb = (
                clopper_pearson_upper_bound(false_accepts, len(accepted), delta)
                if accepted else None
            )
            certified = (
                len(accepted) >= minimum_cert_accepts
                and ucb is not None
                and ucb <= alpha
            )
            target["certification"] = {
                "method": "one_sided_clopper_pearson_exact",
                "n": len(cert_groups.get(target_id, [])),
                "accepted": len(accepted),
                "false_accepts": false_accepts,
                "false_accept_rate": (
                    false_accepts / len(accepted) if accepted else None
                ),
                "ucb": ucb,
                "alpha": alpha,
                "delta": delta,
                "certified": certified,
                "diagnostic_auroc_pae": cert_auroc,
                "diagnostic_affects_certificate": False,
                "reason": (
                    "certified" if certified else
                    "too_few_accepted" if len(accepted) < minimum_cert_accepts else
                    "clopper_pearson_ucb_exceeds_alpha"
                ),
            }
        else:
            target["certification"] = None
        if fit["eligible"] and test_rows:
            accepted_test = _accepted(test_groups.get(target_id, []), fit)
            false_accepts_test = sum(_wrong(row, threshold) for row in accepted_test)
            target["test"] = {
                "n": len(test_groups.get(target_id, [])),
                "accepted": len(accepted_test),
                "false_accepts": false_accepts_test,
                "false_accept_rate": (
                    false_accepts_test / len(accepted_test) if accepted_test else None
                ),
                "affects_certificate": False,
            }
        else:
            target["test"] = None
        targets.append(target)

    certified_targets = [
        row["target_id"] for row in targets
        if row["certification"] and row["certification"]["certified"]
    ]
    selective_certified = [
        row["target_id"] for row in targets
        if row["target_id"] in certified_targets and row["fit"]["mode"] == "selective_pae"
    ]
    decision = protocol["panel_decision_rule"]
    minimum_certified = int(decision["minimum_certified_targets"])
    minimum_selective = int(decision["minimum_selective_pae_certified_targets"])
    certification_panel_gate_passed = (
        not failures
        and bool(certification_rows)
        and len(certified_targets) >= minimum_certified
        and len(selective_certified) >= minimum_selective
    )
    test_can_change_certificate = bool(cert_rule.get("test_split_affects_certificate", False))
    terminal_after_certification = (
        not failures
        and bool(certification_rows)
        and not certification_panel_gate_passed
        and not test_can_change_certificate
    )
    final_complete = certification_panel_gate_passed and bool(test_rows)
    success = (
        final_complete
        and not failures
    )
    if failures:
        status = "w2b_audit_failed"
    elif not eligible:
        status = "w2b_fit_complete_no_eligible_targets"
    elif not certification_rows:
        status = "w2b_fit_complete_awaiting_certification"
    elif terminal_after_certification:
        status = "w2b_certification_terminal_not_supported"
    elif not test_rows:
        status = "w2b_certification_complete_awaiting_test"
    elif success:
        status = decision["success_status"]
    else:
        status = "w2b_target_adaptive_viability_not_supported"
    return {
        "artifact": "m6d_w2b_target_adaptive_report",
        "status": status,
        "audit_ok": not failures,
        "can_claim_w2b_target_adaptive_viability": success,
        "can_claim_universal_w2_generalization": False,
        "lrmsd_threshold": threshold,
        "target_alpha": alpha,
        "panel_delta": float(cert_rule["panel_delta"]),
        "per_target_delta": delta,
        "n_initial_targets": len(target_ids),
        "initial_target_ids": target_ids,
        "locked_initial_target_ids": locked_target_ids,
        "fit_eligible_targets": eligible,
        "fit_refused_targets": refused,
        "certified_targets": certified_targets,
        "selective_pae_certified_targets": selective_certified,
        "panel_certification_gate": {
            "minimum_certified_targets": minimum_certified,
            "observed_certified_targets": len(certified_targets),
            "minimum_selective_pae_certified_targets": minimum_selective,
            "observed_selective_pae_certified_targets": len(selective_certified),
            "passed": certification_panel_gate_passed,
        },
        "terminal_after_certification": terminal_after_certification,
        "test_can_change_certificate": test_can_change_certificate,
        "test_required_for_final_reporting": (
            certification_panel_gate_passed and not bool(test_rows)
        ),
        "targets": targets,
        "failures": failures,
        "claim_boundary": (
            "W2b tests target-adaptive viability only. It cannot recertify v11 or support a universal "
            "zero-shot pAE threshold."
        ),
    }


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def run(
    protocol_path: str,
    fit_paths: Iterable[str],
    certification_paths: Iterable[str] = (),
    test_paths: Iterable[str] = (),
    *,
    threshold: float = 4.0,
) -> Dict[str, Any]:
    fit_paths = list(fit_paths)
    certification_paths = list(certification_paths)
    test_paths = list(test_paths)
    all_paths = fit_paths + certification_paths + test_paths
    qc = run_qc(
        all_paths,
        require_complex_target_id=True,
        require_provenance=True,
        require_chain_ids=True,
        expect_predictor_id="boltz2_complex",
        expect_signal_source="boltz2_pae_interaction",
        expect_label_source="boltz2_lrmsd_to_reference",
    )
    report = evaluate(
        _load_json(protocol_path),
        load_merged_records(fit_paths),
        load_merged_records(certification_paths),
        load_merged_records(test_paths),
        threshold=threshold,
        qc_ok=bool(qc["ok"]),
    )
    report["protocol"] = protocol_path
    report["records"] = {
        "fit": fit_paths,
        "certification": certification_paths,
        "test": test_paths,
    }
    report["qc"] = qc
    return report


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--fit-records", nargs="+", required=True)
    parser.add_argument("--certification-records", nargs="*", default=[])
    parser.add_argument("--test-records", nargs="*", default=[])
    parser.add_argument("--threshold", type=float, default=4.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = run(
        args.protocol,
        args.fit_records,
        args.certification_records,
        args.test_records,
        threshold=args.threshold,
    )
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"status={report['status']} audit_ok={report['audit_ok']} "
        f"certified={len(report['certified_targets'])}"
    )
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
