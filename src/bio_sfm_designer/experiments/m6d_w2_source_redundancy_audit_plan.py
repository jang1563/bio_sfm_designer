"""Plan a W2 source-redundancy audit without authorizing submission.

The next-branch candidate pool may contain chain pairs from source PDBs that
already failed under the current protocol. Those candidates are useful only for
auditing within-source failure modes unless a separate audit is explicitly
predeclared. This tool writes that audit plan and keeps it out of W2
generalization evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional


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


def _diagnostic_by_target(fresh_diagnostic: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in fresh_diagnostic.get("targets", []):
        if isinstance(row, dict) and row.get("complex_target_id"):
            out[str(row["complex_target_id"])] = row
    return out


def _screened_by_source(candidate_pool: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidate_pool.get("screened_targets", []):
        if not isinstance(row, dict):
            continue
        source = row.get("rcsb_id")
        if isinstance(source, str) and source:
            out.setdefault(source, []).append(row)
    return out


def _source_group(source: str,
                  rows: List[Dict[str, Any]],
                  diagnostic_targets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    audit_targets = [
        row for row in rows
        if row.get("source_redundancy_audit_only")
    ]
    failed_current_protocol = [
        row for row in rows
        if row.get("verdict") == "excluded_current_protocol"
    ]
    failed_summary = []
    for row in failed_current_protocol:
        target = str(row.get("target"))
        diagnostic = diagnostic_targets.get(target, {})
        failed_summary.append({
            "target": target,
            "classification": diagnostic.get("classification"),
            "success_rate": diagnostic.get("success_rate"),
            "protocol_cutoff_accepts": diagnostic.get("protocol_cutoff_accepts"),
            "verdict": row.get("verdict"),
        })
    audit_summary = []
    for row in audit_targets:
        structural = row.get("structural_preflight") or {}
        audit_summary.append({
            "target": row.get("target"),
            "verdict": row.get("verdict"),
            "ca_interface_contacts": structural.get("ca_interface_contacts"),
            "min_ca_distance": structural.get("min_ca_distance"),
            "reason": row.get("reasons", []),
        })
    return {
        "source": source,
        "failed_current_protocol_targets": failed_summary,
        "audit_only_targets": audit_summary,
        "n_failed_current_protocol_targets": len(failed_summary),
        "n_audit_only_targets": len(audit_summary),
        "audit_question": (
            "Do source-redundant chain pairs repeat the same current-protocol failure mode, "
            "without counting as independent W2 target evidence?"
        ),
    }


def build_report(candidate_pool: Dict[str, Any],
                 fresh_diagnostic: Dict[str, Any],
                 *,
                 source_manifest: Optional[str] = None) -> Dict[str, Any]:
    diagnostic_targets = _diagnostic_by_target(fresh_diagnostic)
    by_source = _screened_by_source(candidate_pool)
    groups = [
        _source_group(source, rows, diagnostic_targets)
        for source, rows in sorted(by_source.items())
        if any(row.get("source_redundancy_audit_only") for row in rows)
    ]
    audit_targets = [
        target["target"]
        for group in groups
        for target in group.get("audit_only_targets", [])
    ]
    status = (
        "source_redundancy_audit_plan_ready_no_submit"
        if audit_targets else
        "no_source_redundancy_audit_targets"
    )
    return {
        "artifact": "m6d_w2_source_redundancy_audit_plan",
        "date": "2026-06-30",
        "status": status,
        "ready_for_cayuga_submission": False,
        "ready_for_w2_generalization_claim": False,
        "source_manifest": source_manifest,
        "candidate_pool": "results/m6d_w2_next_branch_candidate_pool.json",
        "fresh_diagnostic": "results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json",
        "n_sources": len(groups),
        "n_audit_targets": len(audit_targets),
        "audit_targets": audit_targets,
        "source_groups": groups,
        "claim_boundary": {
            "audit_scope": "within_source_failure_mode_only",
            "w2_multi_target_generalization": "not_supported",
            "source_redundant_candidates": "not_independent_target_evidence",
            "cayuga_submission": "not_authorized_by_this_plan",
        },
        "promotion_rules": [
            "write a separate audit manifest before any audit execution",
            "label the workstream source_redundancy_audit, not W2_generalization",
            "do not pool audit-only records with independent target panels",
            "keep each source PDB grouped in the analysis report",
            "run complex_panel_completion and a dedicated audit report before interpreting audit records",
        ],
        "next_action": (
            "expand target discovery beyond excluded sources; run this audit only if a separate "
            "source-redundancy failure-mode question is explicitly selected"
        ),
        "can_mark_goal_complete": False,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Source-Redundancy Audit Plan",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`.",
        f"Ready for W2 generalization claim: `{str(bool(rep.get('ready_for_w2_generalization_claim'))).lower()}`.",
        "",
        "## Scope",
        "",
        "This is a within-source failure-mode audit plan. It is not independent multi-target evidence.",
        "",
        "## Source Groups",
        "",
        "| source | failed current-protocol targets | audit-only targets | audit question |",
        "|---|---|---|---|",
    ]
    for group in rep.get("source_groups", []):
        failed = ", ".join(row.get("target", "n/a") for row in group.get("failed_current_protocol_targets", [])) or "none"
        audit = ", ".join(row.get("target", "n/a") for row in group.get("audit_only_targets", [])) or "none"
        lines.append(
            f"| {group.get('source')} | {failed} | {audit} | {group.get('audit_question')} |"
        )
    lines.extend([
        "",
        "## Promotion Rules",
        "",
    ])
    lines.extend(f"- {rule}" for rule in rep.get("promotion_rules", []))
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        "- This plan does not authorize Cayuga submission.",
        "- Audit-only candidates are not independent W2 target evidence.",
        "- Audit records must not be pooled with independent target panels.",
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-pool", default="results/m6d_w2_next_branch_candidate_pool.json")
    ap.add_argument("--fresh-diagnostic", default="results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json")
    ap.add_argument("--source-manifest", default="configs/m6d_w2_fresh_discovery_complex_targets.json")
    ap.add_argument("--out-json", default="results/m6d_w2_source_redundancy_audit_plan.json")
    ap.add_argument("--out-md", default="results/m6d_w2_source_redundancy_audit_plan.md")
    args = ap.parse_args(argv)

    rep = build_report(
        _load_json(args.candidate_pool),
        _load_json(args.fresh_diagnostic),
        source_manifest=args.source_manifest,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} sources={sources} audit_targets={targets} ready={ready}".format(
            status=rep["status"],
            sources=rep["n_sources"],
            targets=rep["n_audit_targets"],
            ready=rep["ready_for_cayuga_submission"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
