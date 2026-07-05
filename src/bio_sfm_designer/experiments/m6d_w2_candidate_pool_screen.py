"""Screen the current known W2 target-candidate pool.

This is a no-spend pre-manifest screen. It combines previous target manifests,
panel diagnostics, and the revised W2 branch decision to decide whether any
known non-anchor target is eligible for a new pilot branch. It intentionally
does not emit a runnable Cayuga submit plan.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_MANIFESTS = [
    "configs/m6d_candidate_complex_targets.json",
    "configs/m6d_redesign_complex_targets.json",
    "configs/m6d_followup_complex_targets.json",
    "configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json",
]

DEFAULT_DIAGNOSTICS = [
    "results/m6c_w2_redesign_diagnostic.json",
    "results/m6d_redesign_panel_diagnostic.json",
    "results/m6d_followup_panel_diagnostic.json",
    "results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json",
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


def _is_nonempty_file(path: Any) -> bool:
    return isinstance(path, str) and os.path.exists(path) and os.path.getsize(path) > 0


def _target_id(row: Dict[str, Any]) -> Optional[str]:
    value = row.get("id") or row.get("target") or row.get("complex_target_id")
    return value if isinstance(value, str) and value else None


def _manifest_targets(paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
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
            for key in (
                "rcsb_id",
                "source_pdb",
                "prepared_pdb",
                "prep_report",
                "target_chain",
                "binder_chain",
                "target_fasta",
                "target_msa",
                "target_msa_report",
                "records",
                "allow_numbering_gaps",
            ):
                if key in target:
                    row[key] = target.get(key)
    return out


def _diagnostic_targets(paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        diagnostic = _load_json(path)
        for target in diagnostic.get("targets", []):
            if not isinstance(target, dict):
                continue
            target_id = _target_id(target)
            if not target_id:
                continue
            row = out.setdefault(target_id, {"diagnostic_sources": []})
            row["diagnostic_sources"].append(path)
            for key in (
                "classification",
                "recommended_action",
                "success_rate",
                "success",
                "failure",
                "median_pae_interaction",
                "median_lrmsd",
                "protocol_cutoff_accepts",
                "protocol_cutoff_false_accept_rate",
                "panel_trust_all_false_accept_rate",
            ):
                if key in target:
                    row[key] = target.get(key)
    return out


def _branch_decisions(branch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for target in branch.get("target_decisions", []):
        if not isinstance(target, dict):
            continue
        target_id = _target_id(target)
        if target_id:
            out[target_id] = target
    return out


def _prep_report(path: Any) -> Dict[str, Any]:
    if not _is_nonempty_file(path):
        return {}
    try:
        with open(str(path)) as fh:
            obj = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _structural_preflight(candidate: Dict[str, Any], *, min_contacts: int) -> Dict[str, Any]:
    report = _prep_report(candidate.get("prep_report"))
    failures: List[str] = []
    if not report:
        failures.append("missing_or_bad_prep_report")
    if not _is_nonempty_file(candidate.get("source_pdb")):
        failures.append("missing_source_pdb")
    if not _is_nonempty_file(candidate.get("prepared_pdb")):
        failures.append("missing_prepared_pdb")
    if not _is_nonempty_file(candidate.get("target_fasta")):
        failures.append("missing_target_fasta")
    if not _is_nonempty_file(candidate.get("target_msa")):
        failures.append("missing_target_msa")
    if not _is_nonempty_file(candidate.get("target_msa_report")):
        failures.append("missing_target_msa_report")

    allow_gaps = bool(candidate.get("allow_numbering_gaps"))
    target_gaps = report.get("target_numbering_gaps") if report else None
    binder_gaps = report.get("binder_numbering_gaps") if report else None
    if target_gaps and not allow_gaps:
        failures.append("target_numbering_gaps")
    if binder_gaps and not allow_gaps:
        failures.append("binder_numbering_gaps")
    contacts = report.get("ca_interface_contacts") if report else None
    if not isinstance(contacts, int) or contacts < min_contacts:
        failures.append("insufficient_interface_contacts")

    return {
        "ok": not failures,
        "failures": failures,
        "target_ca_residues": report.get("target_ca_residues"),
        "binder_ca_residues": report.get("binder_ca_residues"),
        "ca_interface_contacts": contacts,
        "min_ca_distance": report.get("min_ca_distance"),
        "target_numbering_gaps": target_gaps,
        "binder_numbering_gaps": binder_gaps,
    }


def _screen_candidate(candidate: Dict[str, Any],
                      branch_row: Optional[Dict[str, Any]],
                      *,
                      min_contacts: int) -> Dict[str, Any]:
    structural = _structural_preflight(candidate, min_contacts=min_contacts)
    classification = candidate.get("classification")
    branch_decision = branch_row.get("branch_decision") if isinstance(branch_row, dict) else None
    reasons: List[str] = []
    admitted = False

    if branch_decision == "freeze_as_target_specific_positive_control":
        verdict = "frozen_positive_control_not_admitted"
        reasons.append("target-specific positive control is not a W2 generalization candidate")
    elif branch_decision == "retain_as_anchor_not_scale_target":
        verdict = "anchor_not_admitted"
        reasons.append("anchor/reference target is not an immediate non-anchor pilot candidate")
    elif branch_decision in {
        "reject_for_current_w2_branch",
        "hold_until_low_pae_acceptance_strategy_changes",
    }:
        verdict = branch_decision
        reasons.extend(branch_row.get("decision_reasons") or [])
    elif classification == "target_protocol_mismatch_low_success":
        verdict = "reject_for_current_w2_branch"
        reasons.append("prior diagnostic classified target as target/protocol mismatch")
    elif classification == "underpowered_low_pae_acceptance":
        verdict = "hold_until_low_pae_acceptance_strategy_changes"
        reasons.append("prior diagnostic showed low-pAE acceptance problem")
    elif not structural["ok"]:
        verdict = "structural_preflight_blocked"
        reasons.extend(structural["failures"])
    else:
        verdict = "admitted_for_pilot_candidate_pool"
        admitted = True
        reasons.append("no known negative W2 evidence and structural preflight passed")

    return {
        "target": candidate["target"],
        "verdict": verdict,
        "admitted_for_pilot": admitted,
        "branch_decision": branch_decision,
        "classification": classification,
        "success_rate": candidate.get("success_rate"),
        "protocol_cutoff_accepts": candidate.get("protocol_cutoff_accepts"),
        "median_pae_interaction": candidate.get("median_pae_interaction"),
        "seen_in_manifests": candidate.get("seen_in_manifests", []),
        "structural_preflight": structural,
        "reasons": reasons,
    }


def build_report(manifest_paths: List[str],
                 diagnostic_paths: List[str],
                 revised_branch: Dict[str, Any],
                 *,
                 min_contacts: int = 20) -> Dict[str, Any]:
    candidates = _manifest_targets(manifest_paths)
    diagnostics = _diagnostic_targets(diagnostic_paths)
    branches = _branch_decisions(revised_branch)

    screened = []
    for target_id in sorted(candidates):
        candidate = dict(candidates[target_id])
        candidate.update(diagnostics.get(target_id, {}))
        screened.append(_screen_candidate(candidate, branches.get(target_id), min_contacts=min_contacts))

    admitted = [row for row in screened if row["admitted_for_pilot"]]
    status = (
        "pilot_candidates_admitted"
        if admitted else "no_current_non_anchor_admissions"
    )
    return {
        "artifact": "m6d_w2_candidate_pool_screen",
        "date": "2026-06-30",
        "status": status,
        "ready_for_revised_manifest": bool(admitted),
        "ready_for_cayuga_submission": False,
        "n_candidates": len(screened),
        "n_admitted_for_pilot": len(admitted),
        "manifest_inputs": manifest_paths,
        "diagnostic_inputs": diagnostic_paths,
        "min_contacts": min_contacts,
        "claim_boundary": {
            "candidate_pool_screen": "local_no_spend_pre_manifest_screen",
            "w2_multi_target_generalization": "not_supported",
            "cayuga_submission": "not_ready",
        },
        "screened_targets": screened,
        "next_action": (
            "create a fresh target-discovery pool or change the generation/evaluation protocol; "
            "do not emit a revised W2 submit manifest from the current known pool"
        ),
        "can_mark_goal_complete": False,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Candidate-Pool Screen",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for revised manifest: `{str(rep.get('ready_for_revised_manifest')).lower()}`.",
        f"Ready for Cayuga submission: `{str(rep.get('ready_for_cayuga_submission')).lower()}`.",
        "",
        "| target | verdict | admitted | classification | success rate | low-pAE accepts | contacts | structural ok |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in rep.get("screened_targets", []):
        structural = row.get("structural_preflight", {})
        lines.append(
            "| {target} | {verdict} | {admitted} | {classification} | {success} | {accepts} | {contacts} | {struct_ok} |".format(
                target=row.get("target"),
                verdict=row.get("verdict"),
                admitted=str(bool(row.get("admitted_for_pilot"))).lower(),
                classification=_fmt(row.get("classification")),
                success=_fmt(row.get("success_rate")),
                accepts=_fmt(row.get("protocol_cutoff_accepts")),
                contacts=_fmt(structural.get("ca_interface_contacts")),
                struct_ok=str(bool(structural.get("ok"))).lower(),
            )
        )
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        "- This is a local no-spend pre-manifest screen.",
        "- It does not support W2 multi-target generalization.",
        "- It does not authorize Cayuga submission.",
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-manifest", action="append", dest="manifests", default=None)
    ap.add_argument("--diagnostic", action="append", dest="diagnostics", default=None)
    ap.add_argument("--revised-branch", default="results/m6d_w2_revised_branch.json")
    ap.add_argument("--min-contacts", type=int, default=20)
    ap.add_argument("--out-json", default="results/m6d_w2_candidate_pool_screen.json")
    ap.add_argument("--out-md", default="results/m6d_w2_candidate_pool_screen.md")
    args = ap.parse_args(argv)

    manifests = args.manifests or DEFAULT_MANIFESTS
    diagnostics = args.diagnostics or DEFAULT_DIAGNOSTICS
    rep = build_report(
        manifests,
        diagnostics,
        _load_json(args.revised_branch),
        min_contacts=args.min_contacts,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} candidates={n} admitted={admitted} ready_for_manifest={ready}".format(
            status=rep["status"],
            n=rep["n_candidates"],
            admitted=rep["n_admitted_for_pilot"],
            ready=rep["ready_for_revised_manifest"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
