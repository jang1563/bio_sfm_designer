"""Apply W2 next-branch rules to the local no-spend candidate inventory.

This is the artifact after `m6d_w2_next_branch_design.py`. It does not fetch
new structures and does not emit a Cayuga submit plan. It applies the candidate
rules to local manifests and makes source-redundant leftovers explicit.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set


DEFAULT_INVENTORY_MANIFESTS = [
    "configs/m6d_candidate_complex_targets.json",
    "configs/m6d_redesign_complex_targets.json",
    "configs/m6d_followup_complex_targets.json",
    "configs/m6d_w2_fresh_discovery_complex_targets.json",
    "configs/m6d_w2_expanded_discovery_complex_targets.json",
]


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


def _target_id(row: Dict[str, Any]) -> Optional[str]:
    value = row.get("id") or row.get("target") or row.get("complex_target_id")
    return value if isinstance(value, str) and value else None


def _is_nonempty_file(path: Any) -> bool:
    return isinstance(path, str) and os.path.exists(path) and os.path.getsize(path) > 0


def _load_prep_report(path: Any) -> Dict[str, Any]:
    if not _is_nonempty_file(path):
        return {}
    try:
        with open(str(path)) as fh:
            obj = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _inventory_targets(paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        manifest = _load_json(path)
        for target in manifest.get("targets", []):
            if not isinstance(target, dict):
                continue
            target_id = _target_id(target)
            if not target_id:
                continue
            row = out.setdefault(target_id, {"target": target_id, "seen_in_manifests": []})
            row["seen_in_manifests"].append(path)
            for key, value in target.items():
                if key not in {"targets"}:
                    row[key] = value
    return out


def _structural_preflight(candidate: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    req = rules.get("candidate_requirements", {})
    report = _load_prep_report(candidate.get("prep_report"))
    failures: List[str] = []
    path_checks = {
        "source_pdb": "require_source_pdb",
        "prepared_pdb": "require_prepared_pdb",
        "prep_report": "require_prep_report",
        "target_fasta": "require_target_fasta",
        "target_fasta_report": "require_target_fasta_report",
        "target_msa": "require_target_msa",
        "target_msa_report": "require_target_msa_report",
    }
    for field, requirement in path_checks.items():
        if req.get(requirement, False) and not _is_nonempty_file(candidate.get(field)):
            failures.append(f"missing_{field}")

    min_contacts = req.get("min_ca_interface_contacts", 20)
    contacts = report.get("ca_interface_contacts") if report else None
    if not isinstance(contacts, int) or contacts < min_contacts:
        failures.append("insufficient_interface_contacts")
    target_gaps = report.get("target_numbering_gaps") if report else None
    binder_gaps = report.get("binder_numbering_gaps") if report else None
    if target_gaps and not candidate.get("allow_numbering_gaps"):
        failures.append("target_numbering_gaps")
    if binder_gaps and not candidate.get("allow_numbering_gaps"):
        failures.append("binder_numbering_gaps")
    return {
        "ok": not failures,
        "failures": failures,
        "ca_interface_contacts": contacts,
        "min_ca_distance": report.get("min_ca_distance"),
        "target_ca_residues": report.get("target_ca_residues"),
        "binder_ca_residues": report.get("binder_ca_residues"),
        "target_numbering_gaps": target_gaps,
        "binder_numbering_gaps": binder_gaps,
    }


def _source_ids_for_targets(candidates: Dict[str, Dict[str, Any]], targets: Set[str]) -> Set[str]:
    out: Set[str] = set()
    for target_id in targets:
        row = candidates.get(target_id)
        source = row.get("rcsb_id") if isinstance(row, dict) else None
        if isinstance(source, str) and source:
            out.add(source)
    return out


def _screen_candidate(candidate: Dict[str, Any],
                      rules: Dict[str, Any],
                      *,
                      excluded_sources: Set[str],
                      admitted_sources: Set[str]) -> Dict[str, Any]:
    target = str(candidate["target"])
    excluded = set(rules.get("excluded_targets_under_current_protocol", []))
    positive = set(rules.get("positive_controls_not_generalization_targets", []))
    anchors = set(rules.get("anchors_not_for_immediate_scale", []))
    req = rules.get("candidate_requirements", {})
    structural = _structural_preflight(candidate, rules)
    source = candidate.get("rcsb_id")
    reasons: List[str] = []
    admitted = False
    audit_only = False

    if target in positive:
        verdict = "positive_control_not_generalization"
        reasons.append("target-specific positive control cannot count as W2 generalization")
    elif target in anchors:
        verdict = "anchor_not_immediate_scale"
        reasons.append("anchor/reference target cannot unlock a new broad W2 panel")
    elif target in excluded:
        verdict = "excluded_current_protocol"
        reasons.append("target is excluded by current W2 candidate rules")
    elif (
        req.get("require_source_pdb_deduplication", False)
        and isinstance(source, str)
        and source in excluded_sources
    ):
        verdict = "source_redundancy_audit_only"
        audit_only = True
        reasons.append("source PDB already produced an excluded current-protocol target")
        reasons.append("source-redundant chain pairs are not independent W2 evidence")
    elif not structural["ok"]:
        verdict = "structural_or_input_preflight_blocked"
        reasons.extend(structural["failures"])
    elif (
        req.get("require_source_pdb_deduplication", False)
        and isinstance(source, str)
        and source in admitted_sources
    ):
        verdict = "source_redundancy_audit_only"
        audit_only = True
        reasons.append("another chain pair from this source PDB is already admitted")
        reasons.append("source-redundant chain pairs are not independent W2 evidence")
    else:
        verdict = "admitted_for_next_branch_candidate_pool"
        admitted = True
        reasons.append("candidate passes local no-spend rules")

    return {
        "target": target,
        "rcsb_id": source,
        "verdict": verdict,
        "admitted_for_next_branch": admitted,
        "source_redundancy_audit_only": audit_only,
        "seen_in_manifests": candidate.get("seen_in_manifests", []),
        "structural_preflight": structural,
        "reasons": reasons,
    }


def _target_msa_precompute_blocked(row: Dict[str, Any]) -> bool:
    if row.get("verdict") != "structural_or_input_preflight_blocked":
        return False
    reasons = set(str(reason) for reason in row.get("reasons", []))
    msa_reasons = {"missing_target_msa", "missing_target_msa_report"}
    if not reasons.intersection(msa_reasons):
        return False
    return reasons.issubset(msa_reasons)


def build_report(rules: Dict[str, Any],
                 inventory_manifests: List[str],
                 *,
                 source_design: Optional[Dict[str, Any]] = None,
                 source_audit_plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    candidates = _inventory_targets(inventory_manifests)
    excluded_targets = set(rules.get("excluded_targets_under_current_protocol", []))
    explicit_excluded_sources = {
        str(source)
        for source in rules.get("excluded_source_ids_under_current_protocol", [])
        if isinstance(source, str) and source
    }
    excluded_sources = _source_ids_for_targets(candidates, excluded_targets).union(explicit_excluded_sources)
    admitted_sources: Set[str] = set()
    screened = []
    for target_id in sorted(candidates):
        row = _screen_candidate(
            candidates[target_id],
            rules,
            excluded_sources=excluded_sources,
            admitted_sources=admitted_sources,
        )
        screened.append(row)
        if row["admitted_for_next_branch"] and isinstance(row.get("rcsb_id"), str):
            admitted_sources.add(str(row["rcsb_id"]))
    admitted = [row for row in screened if row["admitted_for_next_branch"]]
    audit_only = [row for row in screened if row["source_redundancy_audit_only"]]
    target_msa_blocked = [row for row in screened if _target_msa_precompute_blocked(row)]
    verdict_counts: Dict[str, int] = {}
    for row in screened:
        verdict = row["verdict"]
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    min_candidates = int(
        rules.get("candidate_requirements", {}).get("min_non_anchor_candidates_for_revised_manifest", 3)
    )
    ready_for_manifest = len(admitted) >= min_candidates
    if ready_for_manifest:
        status = "next_branch_candidates_ready_for_manifest_design"
    elif admitted:
        status = "insufficient_admitted_candidates_expand_discovery"
    elif target_msa_blocked:
        status = "target_msa_precompute_required_for_expanded_candidates"
    elif audit_only:
        status = "no_admitted_candidates_source_redundancy_audit_only"
    else:
        status = "no_admitted_candidates_expand_discovery"

    return {
        "artifact": "m6d_w2_next_branch_candidate_pool",
        "date": "2026-06-30",
        "status": status,
        "protocol_id": rules.get("protocol_id"),
        "selected_design": rules.get("selected_design"),
        "ready_for_revised_manifest": ready_for_manifest,
        "ready_for_cayuga_submission": False,
        "n_candidates": len(screened),
        "n_admitted_for_next_branch": len(admitted),
        "n_source_redundancy_audit_only": len(audit_only),
        "n_target_msa_precompute_blocked": len(target_msa_blocked),
        "min_non_anchor_candidates_for_revised_manifest": min_candidates,
        "inventory_manifests": inventory_manifests,
        "source_design_status": source_design.get("status") if isinstance(source_design, dict) else None,
        "source_redundancy_audit_plan_status": (
            source_audit_plan.get("status") if isinstance(source_audit_plan, dict) else None
        ),
        "excluded_sources_from_current_protocol": sorted(excluded_sources),
        "verdict_counts": verdict_counts,
        "admitted_targets": [row["target"] for row in admitted],
        "source_redundancy_audit_targets": [row["target"] for row in audit_only],
        "target_msa_precompute_blocked_targets": [row["target"] for row in target_msa_blocked],
        "screened_targets": screened,
        "claim_boundary": {
            "candidate_pool": "local_no_spend_inventory_screen",
            "w2_multi_target_generalization": "not_supported",
            "cayuga_submission": "not_ready",
            "source_redundant_candidates": "audit_only_not_independent_target_evidence",
            "target_msa_precompute": "allowed_next_step_not_submission",
        },
        "next_action": _next_action(
            ready_for_manifest=ready_for_manifest,
            n_admitted=len(admitted),
            min_candidates=min_candidates,
            n_target_msa_blocked=len(target_msa_blocked),
            has_audit_only=bool(audit_only),
            source_audit_plan_exists=isinstance(source_audit_plan, dict),
        ),
        "can_mark_goal_complete": False,
    }


def _next_action(*, ready_for_manifest: bool, n_admitted: int,
                 min_candidates: int, n_target_msa_blocked: int,
                 has_audit_only: bool,
                 source_audit_plan_exists: bool = False) -> str:
    if ready_for_manifest:
        return "write a revised manifest from admitted next-branch candidates and run strict preflight"
    if n_admitted:
        return (
            f"expand target discovery until at least {min_candidates} non-anchor candidates "
            "are admitted by the local rule set"
        )
    if n_target_msa_blocked:
        return (
            f"precompute target MSAs/reports for {n_target_msa_blocked} expanded discovery candidates, "
            "then rerun the candidate-pool screen; Cayuga ProteinMPNN/Boltz submission remains blocked "
            "until strict require-files preflight passes"
        )
    if has_audit_only:
        if source_audit_plan_exists:
            return (
                "expand target discovery beyond excluded sources; the source-redundancy audit plan "
                "already exists and does not authorize submission"
            )
        return "expand target discovery beyond excluded sources or write a separate source-redundancy audit plan"
    return "expand target discovery beyond excluded sources before manifest design"


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Next-Branch Candidate Pool",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for revised manifest: `{str(bool(rep.get('ready_for_revised_manifest'))).lower()}`.",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`.",
        "",
        "## Summary",
        "",
        f"- candidates screened: {rep.get('n_candidates')}",
        f"- admitted for next branch: {rep.get('n_admitted_for_next_branch')}",
        f"- source-redundancy audit only: {rep.get('n_source_redundancy_audit_only')}",
        f"- target-MSA precompute blocked: {rep.get('n_target_msa_precompute_blocked', 0)}",
        f"- excluded sources: {', '.join(rep.get('excluded_sources_from_current_protocol', [])) or 'none'}",
        "",
        "## Screened Targets",
        "",
        "| target | source | verdict | admitted | audit only | contacts | structural ok |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rep.get("screened_targets", []):
        structural = row.get("structural_preflight", {})
        lines.append(
            "| {target} | {source} | {verdict} | {admitted} | {audit} | {contacts} | {struct_ok} |".format(
                target=row.get("target"),
                source=row.get("rcsb_id") or "n/a",
                verdict=row.get("verdict"),
                admitted=str(bool(row.get("admitted_for_next_branch"))).lower(),
                audit=str(bool(row.get("source_redundancy_audit_only"))).lower(),
                contacts=structural.get("ca_interface_contacts"),
                struct_ok=str(bool(structural.get("ok"))).lower(),
            )
        )
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        "- This is a local no-spend inventory screen.",
        "- It does not support W2 multi-target generalization.",
        "- It does not authorize Cayuga submission.",
        "- Source-redundant candidates are audit-only unless promoted by a separate predeclared audit plan.",
        "- Target-MSA precompute is an allowed next input-prep step, not a ProteinMPNN/Boltz submit gate.",
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-rules", default="configs/m6d_w2_next_branch_candidate_rules.json")
    ap.add_argument("--source-design", default="results/m6d_w2_next_branch_design.json")
    ap.add_argument("--source-audit-plan", default="results/m6d_w2_source_redundancy_audit_plan.json")
    ap.add_argument("--inventory-manifest", action="append", dest="inventory_manifests", default=None)
    ap.add_argument("--out-json", default="results/m6d_w2_next_branch_candidate_pool.json")
    ap.add_argument("--out-md", default="results/m6d_w2_next_branch_candidate_pool.md")
    args = ap.parse_args(argv)

    manifests = args.inventory_manifests or DEFAULT_INVENTORY_MANIFESTS
    source_design = _load_json(args.source_design) if args.source_design else None
    source_audit_plan = (
        _load_json(args.source_audit_plan)
        if args.source_audit_plan and os.path.exists(args.source_audit_plan)
        else None
    )
    rep = build_report(
        _load_json(args.candidate_rules),
        manifests,
        source_design=source_design,
        source_audit_plan=source_audit_plan,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} candidates={n} admitted={admitted} audit_only={audit} ready={ready}".format(
            status=rep["status"],
            n=rep["n_candidates"],
            admitted=rep["n_admitted_for_next_branch"],
            audit=rep["n_source_redundancy_audit_only"],
            ready=rep["ready_for_revised_manifest"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
