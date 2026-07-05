"""Audit the M6d W3 negative robustness adjudication without running predictors.

This is a no-spend reproducibility check for the completed Boltz-vs-Chai
comparison. It verifies that the selected W3 protocol is a negative robustness
result, that the materialized adjudication JSONL is intact, and that the
decision protocol still matches the cross-predictor report it summarizes.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

from bio_sfm_designer.experiments.complex_project_status import (
    _w3_adjudication_set_artifact_audit,
    _w3_decision_protocol_failures,
)


_NEGATIVE_STATUS = "negative_robustness_result_adjudicated"
_NEGATIVE_VERDICT = "negative_robustness_result_for_no_msa_chai"
_NEGATIVE_BOUNDARY = "independent_predictor_robustness_not_supported"
_EXPECTED_FAILURE_KIND = "label_agreement_below_min"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
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


def _first_pair(cross_predictor: Dict[str, Any]) -> Dict[str, Any]:
    pairs = cross_predictor.get("pairs")
    if isinstance(pairs, list) and pairs and isinstance(pairs[0], dict):
        return pairs[0]
    return {}


def _failure_kinds(cross_predictor: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for failure in cross_predictor.get("failures") or []:
        if isinstance(failure, dict) and isinstance(failure.get("kind"), str):
            out.append(failure["kind"])
    return sorted(set(out))


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _compare_cross_predictor(decision_protocol: Dict[str, Any],
                             cross_predictor: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if cross_predictor is None:
        return failures

    w3 = decision_protocol.get("w3") if isinstance(decision_protocol.get("w3"), dict) else {}
    pair = _first_pair(cross_predictor)
    cross_failure_kinds = _failure_kinds(cross_predictor)
    w3_failure_kinds = sorted(str(x) for x in (w3.get("cross_predictor_failure_kinds") or []))

    if cross_predictor.get("ok") is not False:
        _add_failure(
            failures,
            "w3_cross_predictor_not_negative",
            "W3 negative robustness audit expects the cross-predictor report to be non-passing",
            expected=False,
            observed=cross_predictor.get("ok"),
        )
    if _EXPECTED_FAILURE_KIND not in cross_failure_kinds:
        _add_failure(
            failures,
            "w3_cross_predictor_negative_signal_missing",
            "cross-predictor report must contain the predeclared label-agreement failure",
            expected=_EXPECTED_FAILURE_KIND,
            observed=cross_failure_kinds,
        )
    if w3_failure_kinds != cross_failure_kinds:
        _add_failure(
            failures,
            "w3_cross_predictor_failure_kind_mismatch",
            "decision protocol and cross-predictor report disagree on failure kinds",
            expected=cross_failure_kinds,
            observed=w3_failure_kinds,
        )

    comparisons = [
        ("label_agreement", pair.get("label_agreement"), w3.get("label_agreement")),
        (
            "min_label_agreement",
            pair.get("min_label_agreement") or cross_predictor.get("min_label_agreement"),
            w3.get("min_label_agreement"),
        ),
        ("matched_overlap", pair.get("n_overlap") or cross_predictor.get("n_match_rows"), w3.get("matched_overlap")),
    ]
    for field, expected, observed in comparisons:
        if expected is not None and observed != expected:
            _add_failure(
                failures,
                f"w3_cross_predictor_{field}_mismatch",
                f"decision protocol and cross-predictor report disagree on {field}",
                expected=expected,
                observed=observed,
            )
    return failures


def build_audit(decision_protocol: Dict[str, Any],
                cross_predictor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    w3 = decision_protocol.get("w3") if isinstance(decision_protocol.get("w3"), dict) else {}
    artifact_audit = _w3_adjudication_set_artifact_audit(w3)
    failures = []
    failures.extend(_w3_decision_protocol_failures(decision_protocol))
    failures.extend(_compare_cross_predictor(decision_protocol, cross_predictor))

    audit_ok = not failures
    return {
        "artifact": "m6d_w3_adjudication_audit",
        "audit_ok": audit_ok,
        "status": _NEGATIVE_STATUS if audit_ok else "w3_adjudication_audit_blocked",
        "can_mark_goal_complete": False,
        "positive_claim_supported": False,
        "claim_boundary": w3.get("claim_boundary"),
        "expected_claim_boundary": _NEGATIVE_BOUNDARY,
        "current_protocol_verdict": w3.get("current_protocol_verdict"),
        "expected_current_protocol_verdict": _NEGATIVE_VERDICT,
        "selected_protocol": w3.get("selected_protocol"),
        "strict_adjudication_integrity": w3.get("strict_adjudication_integrity"),
        "strict_adjudication_integrity_blockers": w3.get("strict_adjudication_integrity_blockers", []),
        "cross_predictor_failure_kinds": w3.get("cross_predictor_failure_kinds", []),
        "label_agreement": w3.get("label_agreement"),
        "min_label_agreement": w3.get("min_label_agreement"),
        "matched_overlap": w3.get("matched_overlap"),
        "adjudication_set": w3.get("adjudication_set", {}),
        "adjudication_set_artifact": w3.get("adjudication_set_artifact"),
        "adjudication_set_artifact_audit": artifact_audit,
        "decision_protocol": decision_protocol.get("_path"),
        "cross_predictor": cross_predictor.get("_path") if isinstance(cross_predictor, dict) else None,
        "failures": failures,
        "next_action": (
            "preserve W3 as a negative no-MSA Chai robustness result; any future W3 spend must use the adjudication set"
            if audit_ok else
            "repair W3 decision/adjudication evidence before treating predictor disagreement as resolved"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W3 Adjudication Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-spend audit. It does not run predictors and does not support a positive W3 robustness claim.",
        "",
        "| item | value |",
        "|---|---:|",
        f"| label agreement | {rep.get('label_agreement')} |",
        f"| minimum label agreement | {rep.get('min_label_agreement')} |",
        f"| matched overlap | {rep.get('matched_overlap')} |",
        f"| strict adjudication integrity | {rep.get('strict_adjudication_integrity')} |",
        f"| positive claim supported | {rep.get('positive_claim_supported')} |",
        "",
        f"Selected protocol: `{rep.get('selected_protocol')}`.",
        f"Claim boundary: `{rep.get('claim_boundary')}`.",
        "",
    ]
    artifact_audit = rep.get("adjudication_set_artifact_audit")
    if isinstance(artifact_audit, dict):
        lines.extend([
            "Adjudication set artifact:",
            f"- Path: `{artifact_audit.get('path')}`",
            f"- Rows: `{artifact_audit.get('n_rows')}`",
            f"- SHA-256: `{artifact_audit.get('actual_sha256')}`",
            f"- Counts by role: `{artifact_audit.get('counts_by_role')}`",
            "",
        ])
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
        lines.append("")
    lines.extend([
        f"Next action: {rep.get('next_action')}",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decision-protocol", default="results/m6d_w2_w3_decision_protocol.json")
    ap.add_argument("--cross-predictor", default="results/m6c_cross_predictor.json")
    ap.add_argument("--out-json", default="results/m6d_w3_adjudication_audit.json")
    ap.add_argument("--out-md", default="results/m6d_w3_adjudication_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(
        _load_json(args.decision_protocol),
        _load_json(args.cross_predictor) if args.cross_predictor else None,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} verdict={verdict} rows={rows}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            verdict=rep.get("current_protocol_verdict"),
            rows=(rep.get("adjudication_set_artifact_audit") or {}).get("n_rows"),
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
