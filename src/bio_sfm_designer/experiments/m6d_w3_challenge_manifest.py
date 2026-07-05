"""Materialize the M6d W3 adjudication challenge manifest without compute spend.

This converts the pinned 18-row W3 adjudication set into a future
third-predictor/protocol challenge-panel manifest. It is deliberately not an
execution wrapper: no jobs, APIs, or GPU commands are emitted, and the manifest
cannot support a positive independent-predictor robustness claim by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_READY_STATUS = "w3_challenge_manifest_ready_no_submit"
_BLOCKED_STATUS = "w3_challenge_manifest_blocked"
_EXPECTED_NEXT_STATUS = "w3_next_protocol_ready_no_spend"
_ALLOWED_ROLES = {"discordant_boltz_chai_label", "concordant_success_control"}
_PRIMARY_ROUTE = "third_independent_predictor_or_protocol"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: JSONL record is not an object")
            rows.append(obj)
    return rows


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str,
                 *, expected: Any = None, observed: Any = None) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        row["expected"] = expected
    if observed is not None:
        row["observed"] = observed
    failures.append(row)


def _counts(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    c = Counter(str(row.get("adjudication_role")) for row in rows)
    return {key: c[key] for key in sorted(c)}


def _target_ids(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(row.get("target_id")) for row in rows if isinstance(row.get("target_id"), str)]


def _route_names(next_protocol: Dict[str, Any]) -> List[str]:
    routes = next_protocol.get("recommended_next_routes")
    if not isinstance(routes, list):
        return []
    return [
        route.get("route")
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("route"), str)
    ]


def _validate_next_protocol(next_protocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if next_protocol.get("status") != _EXPECTED_NEXT_STATUS:
        _add_failure(
            failures,
            "w3_next_protocol_status_invalid",
            "challenge manifest requires the no-spend W3 next protocol to be ready",
            expected=_EXPECTED_NEXT_STATUS,
            observed=next_protocol.get("status"),
        )
    if next_protocol.get("audit_ok") is not True:
        _add_failure(
            failures,
            "w3_next_protocol_audit_not_ok",
            "challenge manifest requires the W3 next protocol audit to pass",
            expected=True,
            observed=next_protocol.get("audit_ok"),
        )
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if next_protocol.get(field) is not True:
            _add_failure(
                failures,
                f"w3_next_protocol_{field}_not_true",
                "challenge manifest must inherit the no-submit/no-spend boundary",
                expected=True,
                observed=next_protocol.get(field),
            )
    if next_protocol.get("can_claim_independent_predictor_robustness_now") is not False:
        _add_failure(
            failures,
            "w3_next_protocol_claim_leak",
            "challenge manifest cannot inherit a positive W3 robustness claim",
            expected=False,
            observed=next_protocol.get("can_claim_independent_predictor_robustness_now"),
        )
    if next_protocol.get("positive_claim_supported") is not False:
        _add_failure(
            failures,
            "w3_next_protocol_positive_claim_supported",
            "challenge manifest cannot inherit positive_claim_supported=True",
            expected=False,
            observed=next_protocol.get("positive_claim_supported"),
        )
    if _PRIMARY_ROUTE not in _route_names(next_protocol)[:1]:
        _add_failure(
            failures,
            "w3_next_protocol_primary_route_missing",
            "challenge manifest expects the primary next route to be a third independent predictor/protocol",
            expected=_PRIMARY_ROUTE,
            observed=_route_names(next_protocol)[:1],
        )
    return failures


def _validate_adjudication_rows(next_protocol: Dict[str, Any],
                                adjudication_rows: List[Dict[str, Any]],
                                adjudication_jsonl: str) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    contract = next_protocol.get("adjudication_set_contract")
    if not isinstance(contract, dict):
        _add_failure(
            failures,
            "w3_next_protocol_adjudication_contract_missing",
            "W3 next protocol must contain adjudication_set_contract",
        )
        contract = {}

    expected_sha = contract.get("jsonl_sha256")
    actual_sha = _sha256_file(adjudication_jsonl)
    if expected_sha != actual_sha:
        _add_failure(
            failures,
            "w3_challenge_adjudication_sha_mismatch",
            "adjudication JSONL must match the W3 next protocol contract",
            expected=expected_sha,
            observed=actual_sha,
        )
    expected_rows = contract.get("n_rows")
    if expected_rows != len(adjudication_rows):
        _add_failure(
            failures,
            "w3_challenge_adjudication_row_count_mismatch",
            "adjudication row count must match the W3 next protocol contract",
            expected=expected_rows,
            observed=len(adjudication_rows),
        )
    expected_counts = contract.get("required_counts_by_role") or contract.get("counts_by_role")
    actual_counts = _counts(adjudication_rows)
    if expected_counts != actual_counts:
        _add_failure(
            failures,
            "w3_challenge_adjudication_role_count_mismatch",
            "adjudication role counts must match the W3 next protocol contract",
            expected=expected_counts,
            observed=actual_counts,
        )

    target_ids = _target_ids(adjudication_rows)
    if len(set(target_ids)) != len(target_ids):
        _add_failure(
            failures,
            "w3_challenge_target_ids_not_unique",
            "challenge manifest requires unique target_id values",
            observed=target_ids,
        )
    required_fields = {
        "target_id",
        "adjudication_role",
        "label_a",
        "label_b",
        "predictor_a",
        "predictor_b",
        "complex_target_id_a",
        "complex_target_id_b",
        "signal_source_a",
        "signal_source_b",
        "label_source_a",
        "label_source_b",
        "lrmsd_threshold_a",
        "lrmsd_threshold_b",
    }
    for i, row in enumerate(adjudication_rows, 1):
        missing = sorted(field for field in required_fields if field not in row)
        if missing:
            _add_failure(
                failures,
                "w3_challenge_row_required_fields_missing",
                "adjudication row is missing fields needed for future result adjudication",
                expected=sorted(required_fields),
                observed={"row": i, "missing": missing},
            )
        if row.get("adjudication_role") not in _ALLOWED_ROLES:
            _add_failure(
                failures,
                "w3_challenge_row_role_invalid",
                "adjudication row has an unsupported role",
                expected=sorted(_ALLOWED_ROLES),
                observed={"row": i, "role": row.get("adjudication_role")},
            )
        if row.get("complex_target_id_agrees") is not True:
            _add_failure(
                failures,
                "w3_challenge_row_target_identity_not_strict",
                "challenge rows must preserve strict complex_target_id agreement",
                observed={"row": i, "target_id": row.get("target_id")},
            )
        if row.get("label_threshold_agrees") is not True:
            _add_failure(
                failures,
                "w3_challenge_row_threshold_not_strict",
                "challenge rows must preserve strict label-threshold agreement",
                observed={"row": i, "target_id": row.get("target_id")},
            )
    return failures


def _source_record_audit(source_records: Sequence[str],
                         selected_target_ids: Sequence[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    audits: List[Dict[str, Any]] = []
    selected = set(selected_target_ids)
    if not source_records:
        _add_failure(
            failures,
            "w3_challenge_source_records_missing",
            "challenge manifest should point to source record files covering selected target IDs",
        )
        return audits, failures
    for path in source_records:
        abs_path = os.path.abspath(path)
        item: Dict[str, Any] = {
            "path": path,
            "absolute_path": abs_path,
            "exists": os.path.exists(path),
            "n_records": 0,
            "selected_seen": 0,
            "missing_selected_target_ids": sorted(selected),
            "predictor_ids": [],
        }
        if not os.path.exists(path):
            _add_failure(
                failures,
                "w3_challenge_source_record_missing",
                "source record file does not exist",
                observed=path,
            )
            audits.append(item)
            continue
        seen = set()
        predictors = set()
        for row in _load_jsonl(path):
            item["n_records"] += 1
            tid = row.get("target_id")
            if isinstance(tid, str) and tid in selected:
                seen.add(tid)
            predictor = row.get("predictor_id")
            if isinstance(predictor, str):
                predictors.add(predictor)
        item["selected_seen"] = len(seen)
        item["missing_selected_target_ids"] = sorted(selected - seen)
        item["predictor_ids"] = sorted(predictors)
        if selected - seen:
            _add_failure(
                failures,
                "w3_challenge_source_record_target_ids_missing",
                "source record file does not cover all selected adjudication target IDs",
                expected=sorted(selected),
                observed={"path": path, "missing": sorted(selected - seen)},
            )
        audits.append(item)
    return audits, failures


def _manifest_rows(adjudication_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for i, row in enumerate(adjudication_rows, 1):
        rows.append({
            "challenge_rank": i,
            "target_id": row.get("target_id"),
            "adjudication_role": row.get("adjudication_role"),
            "selection_reason": row.get("adjudication_selection_reason"),
            "complex_target_id": row.get("complex_target_id_a"),
            "strict_target_identity": row.get("complex_target_id_agrees") is True,
            "strict_label_threshold": row.get("label_threshold_agrees") is True,
            "source_labels": {
                "predictor_a": row.get("predictor_a"),
                "label_a": row.get("label_a"),
                "predictor_b": row.get("predictor_b"),
                "label_b": row.get("label_b"),
                "label_agrees": row.get("label_agrees"),
            },
            "source_signals": {
                "signal_source_a": row.get("signal_source_a"),
                "pae_interaction_a": row.get("pae_interaction_a"),
                "signal_source_b": row.get("signal_source_b"),
                "pae_interaction_b": row.get("pae_interaction_b"),
            },
            "source_label_metrics": {
                "label_source_a": row.get("label_source_a"),
                "lrmsd_a": row.get("lrmsd_a"),
                "lrmsd_threshold_a": row.get("lrmsd_threshold_a"),
                "label_source_b": row.get("label_source_b"),
                "lrmsd_b": row.get("lrmsd_b"),
                "lrmsd_threshold_b": row.get("lrmsd_threshold_b"),
            },
        })
    return rows


def build_manifest(next_protocol: Dict[str, Any],
                   adjudication_rows: List[Dict[str, Any]],
                   *,
                   adjudication_jsonl: str,
                   source_records: Sequence[str],
                   report_date: Optional[str] = None) -> Dict[str, Any]:
    target_ids = _target_ids(adjudication_rows)
    source_audit, source_failures = _source_record_audit(source_records, target_ids)
    failures = []
    failures.extend(_validate_next_protocol(next_protocol))
    failures.extend(_validate_adjudication_rows(next_protocol, adjudication_rows, adjudication_jsonl))
    failures.extend(source_failures)
    audit_ok = not failures
    contract = next_protocol.get("decision_contract") if isinstance(next_protocol.get("decision_contract"), dict) else {}
    set_contract = (
        next_protocol.get("adjudication_set_contract")
        if isinstance(next_protocol.get("adjudication_set_contract"), dict)
        else {}
    )
    return {
        "artifact": "m6d_w3_challenge_manifest",
        "date": report_date or date.today().isoformat(),
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "execution_ready": False,
        "can_claim_independent_predictor_robustness_now": False,
        "claim_boundary": "not a positive robustness claim; challenge-panel input contract only",
        "source_next_protocol": next_protocol.get("_path"),
        "source_adjudication_jsonl": os.path.abspath(adjudication_jsonl),
        "source_adjudication_sha256": _sha256_file(adjudication_jsonl),
        "source_record_audit": source_audit,
        "challenge_panel": {
            "n_rows": len(adjudication_rows),
            "counts_by_role": _counts(adjudication_rows),
            "target_ids": target_ids,
            "source_contract": {
                "n_rows": set_contract.get("n_rows"),
                "counts_by_role": set_contract.get("counts_by_role"),
                "jsonl_sha256": set_contract.get("jsonl_sha256"),
            },
        },
        "recommended_next_route": _PRIMARY_ROUTE,
        "secondary_route": "stronger_chai_msa_template_protocol",
        "decision_contract": {
            "stage": contract.get("stage"),
            "discordant_alignment_threshold": contract.get("discordant_alignment_threshold"),
            "control_consistency_threshold": contract.get("control_consistency_threshold"),
            "threshold_note": contract.get("threshold_note"),
            "future_result_schema": contract.get("future_result_schema", []),
            "outcomes": contract.get("outcomes", []),
        },
        "execution_blockers": [
            "third predictor/protocol implementation is not selected in this manifest",
            "future predictor execution inputs and command wrapper are not emitted here",
            "explicit approval is required before any API/GPU/HPC execution",
        ],
        "rows": _manifest_rows(adjudication_rows),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    panel = rep.get("challenge_panel", {})
    decision = rep.get("decision_contract", {})
    lines = [
        "# M6d W3 Challenge Manifest",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        "",
        "This is a no-submit, no-API, no-GPU challenge-panel manifest. It is not a positive W3 robustness claim.",
        "",
        "## Challenge Panel",
        "",
        f"- Rows: `{panel.get('n_rows')}`",
        f"- Counts by role: `{panel.get('counts_by_role')}`",
        f"- Adjudication SHA-256: `{rep.get('source_adjudication_sha256')}`",
        "",
        "## Decision Contract",
        "",
        f"- Recommended next route: `{rep.get('recommended_next_route')}`",
        f"- Secondary route: `{rep.get('secondary_route')}`",
        f"- Discordant alignment threshold: `{decision.get('discordant_alignment_threshold')}`",
        f"- Control consistency threshold: `{decision.get('control_consistency_threshold')}`",
        f"- Claim boundary: `{rep.get('claim_boundary')}`",
        "",
        "## Source Records",
        "",
    ]
    for item in rep.get("source_record_audit", []):
        lines.append(
            "- `{path}`: selected_seen=`{seen}`, records=`{records}`, predictors=`{predictors}`".format(
                path=item.get("path"),
                seen=item.get("selected_seen"),
                records=item.get("n_records"),
                predictors=",".join(item.get("predictor_ids", [])),
            )
        )
    lines.extend(["", "## Execution Blockers", ""])
    lines.extend(f"- {blocker}" for blocker in rep.get("execution_blockers", []))
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('kind')}: {failure.get('message')}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--w3-next-protocol", default="results/m6d_w3_next_protocol.json")
    ap.add_argument("--adjudication-jsonl", default="results/m6d_w3_adjudication_set.jsonl")
    ap.add_argument("--source-records", action="append", default=[])
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out-json", default="results/m6d_w3_challenge_manifest.json")
    ap.add_argument("--out-md", default="results/m6d_w3_challenge_manifest.md")
    args = ap.parse_args(argv)

    source_records = args.source_records or [
        "hpc_outputs/m6d_followup_3PC8_AB_scale_t030/records_boltz_complex_t030.jsonl",
        "hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl",
    ]
    rep = build_manifest(
        _load_json(args.w3_next_protocol),
        _load_jsonl(args.adjudication_jsonl),
        adjudication_jsonl=args.adjudication_jsonl,
        source_records=source_records,
        report_date=args.date,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} rows={rows} execution_ready={ready} can_claim={claim}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            rows=rep["challenge_panel"]["n_rows"],
            ready=rep["execution_ready"],
            claim=rep["can_claim_independent_predictor_robustness_now"],
        )
    )
    return 0 if rep["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
