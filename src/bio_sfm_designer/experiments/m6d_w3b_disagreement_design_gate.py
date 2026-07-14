"""Audit the prospective W3b predictor-disagreement gate without authorizing compute."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional

from .m6d_w2c_design_gate import certification_power
from .m6d_w3_mechanism_adjudication import adjudicate
from .m6d_w3b_target_selector import canonical_digest


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def evaluate(
    protocol: Dict[str, Any],
    predecessor_report: Dict[str, Any],
    target_manifest: Dict[str, Any],
    *,
    target_manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    locked = protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        raise ValueError("protocol must contain locked_scientific_protocol")
    failures: List[Dict[str, Any]] = []

    predecessor_checks = {
        "audit_ok": predecessor_report.get("audit_ok") is True,
        "joint_outcome": predecessor_report.get("joint_outcome") == "context_dependent_or_unresolved",
        "population_claim_false": predecessor_report.get(
            "can_claim_population_level_independent_predictor_robustness"
        ) is False,
        "w2c_reopen_false": predecessor_report.get("can_reopen_or_rescue_w2c") is False,
    }
    for name, passed in predecessor_checks.items():
        if not passed:
            _failure(failures, f"predecessor_{name}_failed", f"W3 predecessor check failed: {name}")

    evidence = locked.get("predecessor_evidence_use", {})
    if evidence.get("role") != "design_diagnostic_only":
        _failure(failures, "predecessor_role_invalid", "W3 evidence may be used only for design diagnosis")
    for field in (
        "reuse_w2c_rows_as_fit_certification_or_test",
        "reuse_w3_rows_as_fit_certification_or_test",
    ):
        if evidence.get(field) is not False:
            _failure(failures, f"{field}_allowed", "completed W2c/W3 rows cannot enter W3b splits")

    fresh = locked.get("fresh_target_contract", {})
    role_counts = {
        "fit": int(fresh.get("n_fit_targets") or 0),
        "certification": int(fresh.get("n_certification_targets") or 0),
        "held_out_test": int(fresh.get("n_held_out_test_targets") or 0),
    }
    n_targets = int(fresh.get("n_initial_targets") or 0)
    if role_counts != {"fit": 3, "certification": 3, "held_out_test": 2}:
        _failure(failures, "role_counts_invalid", "W3b requires a frozen 3/3/2 target-level split")
    if sum(role_counts.values()) != n_targets:
        _failure(failures, "role_counts_do_not_sum", "target roles must sum to n_initial_targets")
    for field in (
        "exclude_all_historical_registry_targets_and_sources",
        "exclude_w2b_targets_sources_and_target_sequences",
        "exclude_w2c_targets_sources_and_target_sequences",
        "exclude_w3_complex_target_ids",
        "label_blind_selection_and_role_assignment",
        "require_unique_source_pdb",
        "require_one_representative_per_target_sequence",
        "require_manifest_and_msa_sha_validation",
    ):
        if fresh.get(field) is not True:
            _failure(failures, f"fresh_target_{field}_not_locked", f"fresh-target rule must be true: {field}")

    predictor = locked.get("predictor_contract", {})
    predictor_rows = predictor.get("predictors", [])
    predictor_ids = [row.get("id") for row in predictor_rows if isinstance(row, dict)]
    if predictor_ids != ["boltz2_complex", "af2_multimer_colabfold_v1"]:
        _failure(failures, "predictor_pair_invalid", "W3b requires the frozen Boltz-2/AF2-Multimer pair")
    if float(predictor.get("label_threshold") or 0.0) != 4.0:
        _failure(failures, "label_threshold_invalid", "W3b requires the frozen 4 Angstrom label")
    pairing = predictor.get("candidate_pairing", {})
    for field in (
        "matched_candidate_sequence_sha256_required",
        "matched_target_msa_sha256_required",
        "missing_predictor_output_fails_pair_qc",
        "same_candidate_id_required",
    ):
        if pairing.get(field) is not True:
            _failure(failures, f"pairing_{field}_not_locked", f"pairing rule must be true: {field}")
    if predictor.get("same_prediction_time_network_policy") != "forbidden":
        _failure(failures, "prediction_network_not_forbidden", "prediction-time network access must be forbidden")

    fit = locked.get("fit_design", {})
    if int(fit.get("records_per_target") or 0) != 60:
        _failure(failures, "fit_size_invalid", "W3b fit requires 60 rows per fit target")
    if int(fit.get("minimum_total_accepted") or 0) != 90:
        _failure(failures, "fit_minimum_total_invalid", "W3b fit requires at least 90 accepted rows")
    if int(fit.get("minimum_accepted_per_target") or 0) != 15:
        _failure(failures, "fit_target_breadth_invalid", "W3b fit requires at least 15 accepts per target")
    if float(fit.get("maximum_empirical_false_accept_rate_per_predictor") or 1.0) != 0.08:
        _failure(failures, "fit_risk_cap_invalid", "W3b fit endpoint risk cap must remain 0.08")
    if fit.get("primary_gate", {}).get("name") != "matched_predictor_max_pae_plus_gap":
        _failure(failures, "primary_gate_invalid", "the disagreement-aware primary gate is not locked")
    if fit.get("comparator", {}).get("name") != "boltz_pae_only":
        _failure(failures, "comparator_invalid", "the Boltz-pAE-only comparator is not locked")

    certification = locked.get("certification_design", {})
    panel_delta = float(certification.get("panel_delta") or 0.0)
    endpoint_count = int(certification.get("n_target_predictor_endpoints") or 0)
    per_endpoint_delta = float(certification.get("per_endpoint_delta") or 0.0)
    expected_delta = panel_delta / endpoint_count if endpoint_count else None
    if certification.get("method") != "one_sided_clopper_pearson_exact":
        _failure(failures, "certification_method_invalid", "W3b requires exact one-sided Clopper-Pearson")
    if expected_delta is None or not math.isclose(
        per_endpoint_delta, expected_delta, rel_tol=0.0, abs_tol=1e-15
    ):
        _failure(
            failures,
            "per_endpoint_delta_mismatch",
            "delta must be Bonferroni-corrected over all target-predictor endpoints",
            expected=expected_delta,
            observed=per_endpoint_delta,
        )
    minimum_accepted = int(certification.get("minimum_accepted_per_target") or 0)
    target_alpha = float(certification.get("target_alpha") or 0.0)
    design_risk = float(certification.get("design_true_risk") or 0.0)
    power = certification_power(minimum_accepted, design_risk, target_alpha, per_endpoint_delta)
    if power["conditional_certification_power"] < float(
        certification.get("minimum_conditional_power") or 0.0
    ) - 1e-12:
        _failure(failures, "certification_power_below_floor", "W3b certification plan is underpowered")
    if int(certification.get("records_per_target") or 0) != 150 or minimum_accepted != 100:
        _failure(failures, "certification_sample_size_invalid", "W3b requires 150 rows and 100 accepts per certification target")
    if int(certification.get("minimum_certified_targets") or 0) != 2:
        _failure(failures, "certification_breadth_invalid", "at least two of three targets must certify")

    test = locked.get("held_out_test_design", {})
    if int(test.get("records_per_target") or 0) != 120:
        _failure(failures, "test_size_invalid", "W3b held-out test requires 120 rows per target")
    if test.get("certificate_can_change_from_test") is not False:
        _failure(failures, "test_can_change_certificate", "held-out test cannot change the certificate")
    if test.get("test_support_cannot_rescue_failed_certification") is not True:
        _failure(failures, "test_can_rescue_failure", "held-out test cannot rescue failed certification")

    budget = locked.get("compute_budget", {})
    candidate_total = (
        role_counts["fit"] * int(fit.get("records_per_target") or 0)
        + role_counts["certification"] * int(certification.get("records_per_target") or 0)
        + role_counts["held_out_test"] * int(test.get("records_per_target") or 0)
    )
    predictor_total = candidate_total * len(predictor_ids)
    if int(budget.get("maximum_candidate_designs") or 0) != candidate_total:
        _failure(failures, "candidate_budget_mismatch", "candidate budget does not equal the frozen stages")
    if int(budget.get("maximum_predictor_evaluations") or 0) != predictor_total:
        _failure(failures, "predictor_budget_mismatch", "predictor-evaluation budget does not equal two matched folds per candidate")
    if budget.get("no_adaptive_top_up") is not True:
        _failure(failures, "adaptive_top_up_allowed", "adaptive top-up must be forbidden")

    digest = canonical_digest(locked)
    manifest_rows = [row for row in target_manifest.get("targets", []) if isinstance(row, dict)]
    manifest_roles: Dict[str, int] = {role: 0 for role in role_counts}
    for row in manifest_rows:
        role = row.get("experimental_role")
        if role in manifest_roles:
            manifest_roles[str(role)] += 1
    target_ids = [str(row.get("id") or "") for row in manifest_rows]
    sources = [str(row.get("rcsb_id") or "").upper() for row in manifest_rows]
    sequences = [str(row.get("target_sequence_sha256") or "") for row in manifest_rows]
    if target_manifest.get("locked_scientific_digest") != digest:
        _failure(failures, "manifest_protocol_digest_mismatch", "target manifest uses a different locked protocol")
    if len(manifest_rows) != n_targets or manifest_roles != role_counts:
        _failure(failures, "manifest_role_counts_mismatch", "target manifest must realize the exact 3/3/2 split")
    if any(not value for value in target_ids) or len(set(target_ids)) != n_targets:
        _failure(failures, "manifest_target_identity_invalid", "target ids must be complete and unique")
    if any(not value for value in sources) or len(set(sources)) != n_targets:
        _failure(failures, "manifest_source_identity_invalid", "source PDB ids must be complete and unique")
    if any(not value for value in sequences) or len(set(sequences)) != n_targets:
        _failure(failures, "manifest_sequence_identity_invalid", "target-sequence hashes must be complete and unique")
    if target_manifest.get("label_data_consumed") is not False or target_manifest.get(
        "predictor_records_consumed"
    ) is not False:
        _failure(failures, "manifest_consumed_outcome_data", "target selection and role assignment must be label-blind")
    if target_manifest.get("cayuga_submission_allowed") is not False:
        _failure(failures, "manifest_submission_allowed", "target manifest must remain no-submit")

    manifest_sha: Optional[str] = None
    if target_manifest_path and os.path.isfile(target_manifest_path):
        manifest_sha = _file_sha256(target_manifest_path)
        expected_sha = protocol.get("execution_state", {}).get("target_manifest_sha256")
        if expected_sha is not None and manifest_sha != expected_sha:
            _failure(
                failures,
                "target_manifest_sha_mismatch",
                "target manifest hash differs from the execution-state lock",
                expected=expected_sha,
                observed=manifest_sha,
            )

    missing_msa_targets = [
        str(row.get("id") or "")
        for row in manifest_rows
        if not isinstance(row.get("target_msa"), str)
        or not os.path.isfile(str(row["target_msa"]))
        or os.path.getsize(str(row["target_msa"])) <= 0
        or not isinstance(row.get("target_msa_report"), str)
        or not os.path.isfile(str(row["target_msa_report"]))
        or os.path.getsize(str(row["target_msa_report"])) <= 0
    ]

    execution = protocol.get("execution_state", {})
    for field in (
        "approval_recorded",
        "cayuga_submission_allowed",
        "command_wrapper_emitted",
        "no_gpu_compute",
        "operator_approval_recorded",
    ):
        expected = field == "no_gpu_compute"
        if execution.get(field) is not expected:
            _failure(failures, f"execution_{field}_invalid", f"execution boundary failed: {field}")
    if execution.get("no_submit") is not True or execution.get("no_api_spend") is not True:
        _failure(failures, "execution_no_submit_boundary_invalid", "W3b must remain no-submit and no-API")
    if execution.get("evaluator_implemented") is not True:
        _failure(failures, "evaluator_not_implemented", "the frozen evaluator must exist before execution planning")

    qualified = not failures
    inputs_ready = qualified and not missing_msa_targets
    return {
        "artifact": "m6d_w3b_disagreement_design_gate",
        "audit_ok": qualified,
        "can_claim_w3b": False,
        "cayuga_submission_allowed": False,
        "certification_power": power,
        "compute_budget": {
            "maximum_candidate_designs": candidate_total,
            "maximum_h100_gpu_hours": budget.get("maximum_h100_gpu_hours"),
            "maximum_predictor_evaluations": predictor_total,
        },
        "design_power_qualified": qualified,
        "execution_ready": False,
        "failures": failures,
        "fresh_target_contract": {
            "manifest_sha256": manifest_sha,
            "missing_target_msa_targets": missing_msa_targets,
            "n_targets": len(manifest_rows),
            "role_counts": manifest_roles,
            "target_ids": target_ids,
            "target_msa_ready": not missing_msa_targets,
        },
        "inputs_ready": inputs_ready,
        "locked_scientific_digest": digest,
        "no_submit": True,
        "predecessor_checks": predecessor_checks,
        "status": (
            "w3b_design_power_qualified_inputs_ready_no_submit"
            if inputs_ready
            else "w3b_design_power_qualified_inputs_incomplete_no_submit"
            if qualified
            else "w3b_design_gate_blocked"
        ),
        "claim_boundary": (
            "Prospective design, target-role, and exact-power audit only. It does not authorize compute, "
            "certify a gate, establish biological binder success, or rescue W2c."
        ),
        "next_action": (
            "Prepare a separately hash-bound candidate-generation packet and stop for explicit approval; "
            "do not run ProteinMPNN or either predictor."
            if inputs_ready else
            "Precompute and hash-lock exactly the eight target MSAs under a separate approval boundary; "
            "do not generate candidates or run either predictor."
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    power = report["certification_power"]
    fresh = report["fresh_target_contract"]
    lines = [
        "# M6d W3b Disagreement-Gate Design Audit",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        f"Inputs ready: `{report['inputs_ready']}`.",
        f"Execution ready: `{report['execution_ready']}`.",
        f"Cayuga submission allowed: `{report['cayuga_submission_allowed']}`.",
        "",
        "## Prospective Design",
        "",
        f"- target roles: `{fresh['role_counts']}`",
        f"- target MSAs ready: `{fresh['target_msa_ready']}`",
        f"- missing target MSAs: `{', '.join(fresh['missing_target_msa_targets']) or 'none'}`",
        f"- maximum candidate designs: `{report['compute_budget']['maximum_candidate_designs']}`",
        f"- maximum matched predictor evaluations: `{report['compute_budget']['maximum_predictor_evaluations']}`",
        "",
        "## Exact Endpoint Power",
        "",
        f"- minimum accepted per certification target: `{power['accepted_rows']}`",
        f"- maximum certifiable false accepts: `{power['maximum_certifiable_false_accepts']}`",
        f"- conditional power at design risk 0.08: `{power['conditional_certification_power']:.6f}`",
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
        lines.extend(f"- `{row['kind']}`: {row['message']}" for row in report["failures"])
        lines.append("")
    return "\n".join(lines)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path} must contain JSON objects")
                rows.append(value)
    return rows


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--target-manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument("--w3-protocol", default="configs/m6d_w3_mechanism_panel_protocol.json")
    parser.add_argument(
        "--w3-records",
        default="tests/fixtures/m6d_w3_mechanism_panel_af2_records.jsonl",
    )
    parser.add_argument("--out-json", default="results/m6d_w3b_disagreement_design_gate.json")
    parser.add_argument("--out-md", default="results/m6d_w3b_disagreement_design_gate.md")
    args = parser.parse_args(argv)
    predecessor_report = adjudicate(_load_json(args.w3_protocol), _load_jsonl(args.w3_records))
    report = evaluate(
        _load_json(args.protocol),
        predecessor_report,
        _load_json(args.target_manifest),
        target_manifest_path=args.target_manifest,
    )
    _write(args.out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} power={report['certification_power']['conditional_certification_power']:.6f} "
        f"inputs_ready={report['inputs_ready']} no_submit={report['no_submit']}"
    )
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
