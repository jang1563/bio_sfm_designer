"""Audit the no-submit W2c one-shot successor design.

W2c is a new experiment, not an extension or recertification of W2b.  This
module checks the locked scientific design, its exact-binomial power, and the
hard boundary that keeps all execution disabled until fresh targets and an
implemented evaluator are available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional

try:
    from bio_sfm_trust import clopper_pearson_upper_bound
except ImportError:  # compatible with the published trust-core v0.1.0 tag
    from ..trust._split_ltt_compat import clopper_pearson_upper_bound


_W2B_TERMINAL_STATUS = "w2b_certification_terminal_not_supported"
_W2C_READY_STATUS = "w2c_design_power_qualified_no_submit"


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(
        math.comb(n, value)
        * probability ** value
        * (1.0 - probability) ** (n - value)
        for value in range(k + 1)
    )


def maximum_certifiable_false_accepts(n: int, alpha: float, delta: float) -> int:
    """Return the largest error count whose exact upper bound is at most alpha."""
    if n <= 0:
        raise ValueError("n must be positive")
    qualified = [
        false_accepts
        for false_accepts in range(n + 1)
        if clopper_pearson_upper_bound(false_accepts, n, delta) <= alpha
    ]
    return max(qualified, default=-1)


def certification_power(
    n: int,
    design_risk: float,
    alpha: float,
    delta: float,
) -> Dict[str, Any]:
    max_false = maximum_certifiable_false_accepts(n, alpha, delta)
    power = _binomial_cdf(max_false, n, design_risk) if max_false >= 0 else 0.0
    return {
        "accepted_rows": n,
        "design_true_risk": design_risk,
        "maximum_certifiable_false_accepts": max_false,
        "maximum_certifiable_empirical_risk": (
            max_false / n if max_false >= 0 else None
        ),
        "conditional_certification_power": power,
    }


def _acceptance_rate_lower_bound(accepted: int, generated: int, delta: float) -> float:
    if not 0 <= accepted <= generated:
        raise ValueError("accepted must be between zero and generated")
    if generated <= 0:
        raise ValueError("generated must be positive")
    return 1.0 - clopper_pearson_upper_bound(generated - accepted, generated, delta)


def _failure(
    failures: List[Dict[str, Any]],
    kind: str,
    message: str,
    *,
    expected: Any = None,
    observed: Any = None,
) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _predecessor_namespaces(protocol: Dict[str, Any]) -> List[str]:
    stages = protocol.get("generation_stages")
    if not isinstance(stages, dict):
        return []
    return sorted(
        str(stage.get("seed_namespace"))
        for stage in stages.values()
        if isinstance(stage, dict) and stage.get("seed_namespace")
    )


def evaluate(
    protocol: Dict[str, Any],
    predecessor_report: Dict[str, Any],
    predecessor_protocol: Dict[str, Any],
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")

    failures: List[Dict[str, Any]] = []
    if predecessor_report.get("status") != _W2B_TERMINAL_STATUS:
        _failure(
            failures,
            "predecessor_not_terminal",
            "W2c requires the terminal W2b result",
            expected=_W2B_TERMINAL_STATUS,
            observed=predecessor_report.get("status"),
        )
    predecessor_checks = {
        "audit_ok": predecessor_report.get("audit_ok") is True,
        "panel_gate_failed": predecessor_report.get("panel_certification_gate", {}).get("passed") is False,
        "terminal_after_certification": predecessor_report.get("terminal_after_certification") is True,
        "test_cannot_change_certificate": predecessor_report.get("test_can_change_certificate") is False,
        "positive_w2b_claim_false": predecessor_report.get("can_claim_w2b_target_adaptive_viability") is False,
        "universal_w2_claim_false": predecessor_report.get("can_claim_universal_w2_generalization") is False,
        "test_rows_absent": not predecessor_report.get("records", {}).get("test"),
    }
    for name, passed in predecessor_checks.items():
        if not passed:
            _failure(
                failures,
                f"predecessor_{name}_failed",
                f"predecessor invariant failed: {name}",
            )

    evidence_use = locked.get("predecessor_evidence_use", {})
    if evidence_use.get("role") != "design_diagnostic_only":
        _failure(failures, "predecessor_role_invalid", "W2b may be used only for design diagnosis")
    if evidence_use.get("reuse_rows_as_fit_or_certification") is not False:
        _failure(failures, "predecessor_row_reuse_allowed", "W2b rows must not enter W2c fit or certification")

    fresh = locked.get("fresh_target_contract", {})
    n_targets = int(fresh.get("n_initial_targets") or 0)
    if n_targets < 3:
        _failure(failures, "too_few_initial_targets", "W2c requires at least three fresh initial targets")
    for field in (
        "exclude_all_historical_registry_targets",
        "exclude_predecessor_target_ids",
        "require_unique_source_pdb",
        "require_one_representative_per_sequence_cluster",
        "require_manifest_and_msa_sha_validation",
    ):
        if fresh.get(field) is not True:
            _failure(failures, f"fresh_target_{field}_not_locked", f"fresh-target rule must be true: {field}")

    fit = locked.get("fit_design", {})
    learning = fit.get("threshold_learning", {})
    screen = fit.get("independent_screen", {})
    learning_records = int(learning.get("records_per_target") or 0)
    screen_records = int(screen.get("records_per_target") or 0)
    screen_min_accepts = int(screen.get("minimum_accepted") or 0)
    screen_empirical_cap = float(screen.get("maximum_empirical_false_accept_rate") or 0.0)
    screen_ucb_cap = float(screen.get("maximum_risk_ucb") or 0.0)
    screen_delta = float(screen.get("risk_delta") or 0.0)
    acceptance_delta = float(screen.get("acceptance_rate_delta") or 0.0)
    acceptance_lcb_floor = float(screen.get("minimum_acceptance_rate_lcb") or 0.0)
    target_alpha = float(locked.get("certification_design", {}).get("target_alpha") or 0.0)

    if learning_records <= 0 or screen_records <= 0:
        _failure(failures, "fit_stage_size_invalid", "both fit substages require positive record counts")
    if fit.get("substage_candidate_overlap_allowed") is not False:
        _failure(failures, "fit_substage_overlap_allowed", "threshold learning and fit screening must be disjoint")
    if fit.get("eligible_mode") != "selective_pae_only":
        _failure(failures, "nonselective_fit_mode_allowed", "only selective_pae may become W2c eligible")
    if fit.get("trust_all_counts_toward_panel_success") is not False:
        _failure(failures, "trust_all_counts_toward_success", "trust_all controls must not count toward W2c success")
    if not 0.0 < screen_empirical_cap < screen_ucb_cap < target_alpha:
        _failure(
            failures,
            "fit_risk_margin_invalid",
            "fit empirical cap and fit UCB cap must both be below certification alpha",
        )
    if not 0.0 < screen_delta < 1.0 or not 0.0 < acceptance_delta < 1.0:
        _failure(failures, "fit_delta_invalid", "fit-screen confidence deltas must be probabilities")
    if not 0 < screen_min_accepts <= screen_records:
        _failure(failures, "fit_minimum_accepts_invalid", "fit-screen minimum accepts exceed generated rows")

    screen_max_false = math.floor(screen_empirical_cap * screen_min_accepts + 1e-12)
    screen_ucb = (
        clopper_pearson_upper_bound(screen_max_false, screen_min_accepts, screen_delta)
        if screen_min_accepts > 0 and 0.0 < screen_delta < 1.0
        else None
    )
    acceptance_lcb = (
        _acceptance_rate_lower_bound(screen_min_accepts, screen_records, acceptance_delta)
        if 0 < screen_min_accepts <= screen_records and 0.0 < acceptance_delta < 1.0
        else None
    )
    if screen_ucb is not None and screen_ucb > screen_ucb_cap + 1e-12:
        _failure(
            failures,
            "fit_screen_ucb_cap_unattainable",
            "declared minimum fit screen does not satisfy its UCB cap",
            expected=f"<= {screen_ucb_cap}",
            observed=screen_ucb,
        )
    if acceptance_lcb is not None and acceptance_lcb < acceptance_lcb_floor - 1e-12:
        _failure(
            failures,
            "fit_acceptance_lcb_floor_unattainable",
            "declared minimum fit screen does not satisfy its acceptance-rate lower bound",
            expected=f">= {acceptance_lcb_floor}",
            observed=acceptance_lcb,
        )

    certification = locked.get("certification_design", {})
    panel_delta = float(certification.get("panel_delta") or 0.0)
    per_target_delta = float(certification.get("per_target_delta") or 0.0)
    records_per_target = int(certification.get("records_per_target") or 0)
    minimum_accepted = int(certification.get("minimum_accepted") or 0)
    design_risk = float(certification.get("design_true_risk") or 0.0)
    minimum_power = float(certification.get("minimum_conditional_power") or 0.0)
    expected_per_target_delta = panel_delta / n_targets if n_targets else None
    if certification.get("method") != "one_sided_clopper_pearson_exact":
        _failure(failures, "certification_method_invalid", "W2c requires exact one-sided Clopper-Pearson")
    if expected_per_target_delta is None or not math.isclose(
        per_target_delta, expected_per_target_delta, rel_tol=0.0, abs_tol=1e-12
    ):
        _failure(
            failures,
            "per_target_delta_mismatch",
            "per-target delta must Bonferroni-correct over every initial target",
            expected=expected_per_target_delta,
            observed=per_target_delta,
        )
    if not 0.0 < design_risk < target_alpha < 1.0:
        _failure(failures, "certification_risk_margin_invalid", "design risk must be below target alpha")
    if not 0 < minimum_accepted <= records_per_target:
        _failure(failures, "certification_minimum_accepts_invalid", "minimum accepts exceed generated rows")

    power = (
        certification_power(minimum_accepted, design_risk, target_alpha, per_target_delta)
        if minimum_accepted > 0 and 0.0 < design_risk < 1.0 and 0.0 < target_alpha < 1.0
        and 0.0 < per_target_delta < 1.0
        else {
            "accepted_rows": minimum_accepted,
            "design_true_risk": design_risk,
            "maximum_certifiable_false_accepts": -1,
            "maximum_certifiable_empirical_risk": None,
            "conditional_certification_power": 0.0,
        }
    )
    if power["conditional_certification_power"] < minimum_power - 1e-12:
        _failure(
            failures,
            "certification_power_below_floor",
            "planned minimum accepted rows do not meet the conditional power floor",
            expected=f">= {minimum_power}",
            observed=power["conditional_certification_power"],
        )

    panel = locked.get("panel_decision_rule", {})
    minimum_certified = int(panel.get("minimum_certified_targets") or 0)
    minimum_selective = int(panel.get("minimum_selective_pae_certified_targets") or 0)
    if minimum_certified < 3 or minimum_selective != minimum_certified:
        _failure(
            failures,
            "panel_selective_requirement_invalid",
            "all W2c panel certificates must be selective and at least three are required",
        )
    if panel.get("trust_all_certificates_count") is not False:
        _failure(failures, "trust_all_certificate_count_enabled", "trust_all certificates cannot satisfy W2c")

    stage_namespaces = [
        str(learning.get("seed_namespace") or ""),
        str(screen.get("seed_namespace") or ""),
        str(certification.get("seed_namespace") or ""),
    ]
    predecessor_namespaces = _predecessor_namespaces(predecessor_protocol)
    if any(not value for value in stage_namespaces) or len(stage_namespaces) != len(set(stage_namespaces)):
        _failure(failures, "w2c_namespace_invalid", "W2c stage namespaces must be non-empty and distinct")
    overlap = sorted(set(stage_namespaces) & set(predecessor_namespaces))
    if overlap:
        _failure(
            failures,
            "predecessor_namespace_reuse",
            "W2c namespaces must be disjoint from W2b",
            observed=overlap,
        )

    execution = protocol.get("execution_state", {})
    execution_controls = {
        "hpc_submission_allowed": execution.get("hpc_submission_allowed") is False,
        "command_wrapper_emitted": execution.get("command_wrapper_emitted") is False,
        "operator_approval_absent": execution.get("operator_approval_recorded") is False,
    }
    for name, passed in execution_controls.items():
        if not passed:
            _failure(failures, f"execution_{name}_failed", f"execution boundary failed: {name}")

    target_manifest_path = execution.get("target_manifest")
    target_manifest_present = isinstance(target_manifest_path, str) and bool(target_manifest_path)
    target_manifest_integrity_ok = False
    target_manifest_ids: List[str] = []
    target_msa_ready = False
    if target_manifest_present:
        if not os.path.isfile(str(target_manifest_path)):
            _failure(failures, "target_manifest_missing", "declared W2c target manifest does not exist")
        else:
            observed_sha = _file_sha256(str(target_manifest_path))
            expected_sha = execution.get("target_manifest_sha256")
            if observed_sha != expected_sha:
                _failure(
                    failures,
                    "target_manifest_sha_mismatch",
                    "W2c target manifest hash does not match execution state",
                    expected=expected_sha,
                    observed=observed_sha,
                )
            with open(str(target_manifest_path)) as handle:
                target_manifest = json.load(handle)
            if not isinstance(target_manifest, dict):
                _failure(failures, "target_manifest_not_object", "W2c target manifest must be a JSON object")
                target_manifest = {}
            target_rows = target_manifest.get("targets", [])
            target_manifest_ids = sorted(
                str(row.get("id") or row.get("complex_target_id") or "")
                for row in target_rows if isinstance(row, dict)
            )
            expected_ids = sorted(str(value) for value in execution.get("target_ids", []))
            if (
                len(target_manifest_ids) != n_targets
                or any(not value for value in target_manifest_ids)
                or len(target_manifest_ids) != len(set(target_manifest_ids))
                or target_manifest_ids != expected_ids
            ):
                _failure(
                    failures,
                    "target_manifest_identity_mismatch",
                    "W2c target manifest must match the eight locked execution target ids",
                    expected=expected_ids,
                    observed=target_manifest_ids,
                )
            if target_manifest.get("locked_scientific_digest") != _canonical_sha256(locked):
                _failure(failures, "target_manifest_protocol_digest_mismatch", "target manifest uses a different scientific digest")
            if target_manifest.get("hpc_submission_allowed") is not False:
                _failure(failures, "target_manifest_submission_not_blocked", "target manifest must remain no-submit")
            target_msa_ready = bool(target_rows) and all(
                isinstance(row.get("target_msa"), str)
                and os.path.isfile(str(row["target_msa"]))
                and os.path.getsize(str(row["target_msa"])) > 0
                and isinstance(row.get("target_msa_report"), str)
                and os.path.isfile(str(row["target_msa_report"]))
                and os.path.getsize(str(row["target_msa_report"])) > 0
                for row in target_rows if isinstance(row, dict)
            )
            target_manifest_integrity_ok = not any(
                failure["kind"].startswith("target_manifest_") for failure in failures
            )

    design_power_qualified = not failures
    return {
        "artifact": "m6d_w2c_design_gate",
        "status": _W2C_READY_STATUS if design_power_qualified else "w2c_design_gate_blocked",
        "audit_ok": design_power_qualified,
        "design_power_qualified": design_power_qualified,
        "execution_ready": False,
        "no_submit": True,
        "hpc_submission_allowed": False,
        "can_claim_w2c": False,
        "locked_scientific_digest": _canonical_sha256(locked),
        "predecessor": {
            "status": predecessor_report.get("status"),
            "checks": predecessor_checks,
            "evidence_role": evidence_use.get("role"),
            "rows_reused": False,
            "initial_target_ids": predecessor_report.get("initial_target_ids", []),
            "stage_namespaces": predecessor_namespaces,
        },
        "fresh_target_contract": {
            "n_initial_targets": n_targets,
            "target_manifest": execution.get("target_manifest"),
            "excludes_predecessor_targets": fresh.get("exclude_predecessor_target_ids") is True,
        },
        "fit_design": {
            "eligible_mode": fit.get("eligible_mode"),
            "trust_all_counts_toward_panel_success": fit.get("trust_all_counts_toward_panel_success"),
            "threshold_learning_records_per_target": learning_records,
            "independent_screen_records_per_target": screen_records,
            "minimum_screen_accepts": screen_min_accepts,
            "maximum_screen_false_accepts_at_minimum": screen_max_false,
            "screen_risk_ucb_at_minimum": screen_ucb,
            "screen_risk_ucb_cap": screen_ucb_cap,
            "screen_acceptance_rate_lcb_at_minimum": acceptance_lcb,
            "screen_acceptance_rate_lcb_floor": acceptance_lcb_floor,
        },
        "certification_design": {
            "target_alpha": target_alpha,
            "panel_delta": panel_delta,
            "per_target_delta": per_target_delta,
            "records_per_target": records_per_target,
            "minimum_accepted": minimum_accepted,
            "minimum_conditional_power": minimum_power,
            **power,
        },
        "panel_decision_rule": {
            "minimum_certified_targets": minimum_certified,
            "minimum_selective_pae_certified_targets": minimum_selective,
            "trust_all_certificates_count": panel.get("trust_all_certificates_count"),
        },
        "compute_budget": locked.get("compute_budget", {}),
        "execution_controls": execution_controls,
        "execution_readiness": {
            "target_manifest_present": target_manifest_present,
            "target_manifest_integrity_ok": target_manifest_integrity_ok,
            "target_manifest_ids": target_manifest_ids,
            "target_msa_ready": target_msa_ready,
            "evaluator_implemented": execution.get("evaluator_implemented") is True,
            "evaluator_module": execution.get("evaluator_module"),
            "command_wrapper_emitted": execution.get("command_wrapper_emitted") is True,
            "operator_approval_recorded": execution.get("operator_approval_recorded") is True,
        },
        "remaining_unlock_conditions": protocol.get("remaining_unlock_conditions", []),
        "failures": failures,
        "claim_boundary": (
            "This is a planning and power artifact only. It does not reuse W2b rows, select W2c targets, "
            "authorize compute, certify a gate, or support W2/W2c generalization."
        ),
        "next_action": (
            "Implement the locked W2c evaluator and build an eight-target fresh manifest with complete "
            "historical/sequence/source exclusion before any execution packet or approval request."
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    power = report["certification_design"]
    fit = report["fit_design"]
    lines = [
        "# M6d W2c Design Gate",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Execution ready: `{report['execution_ready']}`.",
        f"external HPC submission allowed: `{report['hpc_submission_allowed']}`.",
        "",
        "## Scientific Design",
        "",
        f"- initial fresh targets: `{report['fresh_target_contract']['n_initial_targets']}`",
        f"- evaluator implemented: `{report['execution_readiness']['evaluator_implemented']}`",
        f"- target manifest present: `{report['execution_readiness']['target_manifest_present']}`",
        f"- target manifest integrity ok: `{report['execution_readiness']['target_manifest_integrity_ok']}`",
        f"- target MSAs ready: `{report['execution_readiness']['target_msa_ready']}`",
        f"- eligible gate mode: `{fit['eligible_mode']}`",
        f"- threshold-learning rows per target: `{fit['threshold_learning_records_per_target']}`",
        f"- independent fit-screen rows per target: `{fit['independent_screen_records_per_target']}`",
        f"- fit-screen minimum accepts: `{fit['minimum_screen_accepts']}`",
        f"- fit-screen risk UCB at the minimum: `{fit['screen_risk_ucb_at_minimum']:.6f}`",
        f"- fit-screen risk UCB cap: `{fit['screen_risk_ucb_cap']}`",
        "",
        "## Exact Certification Power",
        "",
        f"- target alpha: `{power['target_alpha']}`",
        f"- per-target delta: `{power['per_target_delta']}`",
        f"- generated rows per eligible target: `{power['records_per_target']}`",
        f"- minimum accepted rows: `{power['minimum_accepted']}`",
        f"- design true risk: `{power['design_true_risk']}`",
        f"- maximum certifiable false accepts: `{power['maximum_certifiable_false_accepts']}`",
        f"- conditional certification power: `{power['conditional_certification_power']:.6f}`",
        f"- required power: `{power['minimum_conditional_power']}`",
        "",
        "## Claim Boundary",
        "",
        report["claim_boundary"],
        "",
        "## Next Action",
        "",
        report["next_action"],
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(
            f"- `{failure['kind']}`: {failure['message']}"
            for failure in report["failures"]
        )
        lines.append("")
    return "\n".join(lines)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w2c_one_shot_protocol.json")
    parser.add_argument(
        "--predecessor-report",
        default="results/m6d_w2b_target_adaptive_certification_report.json",
    )
    parser.add_argument(
        "--predecessor-protocol",
        default="configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json",
    )
    parser.add_argument("--out-json", default="results/m6d_w2c_design_gate.json")
    parser.add_argument("--out-md", default="results/m6d_w2c_design_gate.md")
    args = parser.parse_args(argv)

    report = evaluate(
        _load_json(args.protocol),
        _load_json(args.predecessor_report),
        _load_json(args.predecessor_protocol),
    )
    report["inputs"] = {
        "protocol": args.protocol,
        "protocol_sha256": _file_sha256(args.protocol),
        "predecessor_report": args.predecessor_report,
        "predecessor_report_sha256": _file_sha256(args.predecessor_report),
        "predecessor_protocol": args.predecessor_protocol,
        "predecessor_protocol_sha256": _file_sha256(args.predecessor_protocol),
    }
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} power="
        f"{report['certification_design']['conditional_certification_power']:.6f} "
        f"execution_ready={report['execution_ready']} no_submit={report['no_submit']}"
    )
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
