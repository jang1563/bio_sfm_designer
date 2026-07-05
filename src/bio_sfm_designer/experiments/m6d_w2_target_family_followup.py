"""Predeclare the no-spend follow-up contract after a negative W2 family panel.

This module consumes the authoritative target-wise panel report and its redesign
diagnostic. It does not submit jobs or certify W2. Its job is to freeze the next
scientific fork before more GPU is spent.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_BRANCH_ID = "w2_target_family_redesign_v8_success_enriched_gate_redesign"
DEFAULT_DATE = "2026-07-01"


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


def _target_id(row: Dict[str, Any]) -> str:
    for key in ("complex_target_id", "target_id", "id", "target"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _sorted_targets(values: Sequence[Any]) -> List[str]:
    return sorted(str(v) for v in values if isinstance(v, str) and v)


def _diagnostic_targets(diagnostic: Dict[str, Any], classification: str) -> List[str]:
    out = []
    for row in diagnostic.get("targets", []):
        if isinstance(row, dict) and row.get("classification") == classification:
            out.append(_target_id(row))
    return _sorted_targets(out)


def _panel_target_sets(panel_report: Dict[str, Any]) -> Dict[str, List[str]]:
    certified = []
    not_certified = []
    for row in panel_report.get("targets", []):
        if not isinstance(row, dict):
            continue
        target_id = _target_id(row)
        if bool(row.get("certified")):
            certified.append(target_id)
        elif row.get("status") == "not_certified" or not row.get("certified"):
            not_certified.append(target_id)
    return {
        "certified": _sorted_targets(certified),
        "not_certified": _sorted_targets(not_certified),
    }


def _manifest_summary(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {
            "available": False,
            "target_ids": [],
            "source_rcsb_ids": [],
            "n_targets": None,
            "source_manifest": None,
        }
    targets = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    target_ids = [_target_id(row) for row in targets]
    source_ids = [
        str(row.get("rcsb_id"))
        for row in targets
        if isinstance(row.get("rcsb_id"), str) and row.get("rcsb_id")
    ]
    return {
        "available": True,
        "target_ids": _sorted_targets(target_ids),
        "source_rcsb_ids": _sorted_targets(source_ids),
        "n_targets": len(targets),
        "source_manifest": manifest.get("source_manifest"),
    }


def build_contract(panel_report: Dict[str, Any],
                   redesign_diagnostic: Dict[str, Any],
                   manifest: Optional[Dict[str, Any]] = None, *,
                   branch_id: str = DEFAULT_BRANCH_ID,
                   date: str = DEFAULT_DATE) -> Dict[str, Any]:
    target_sets = _panel_target_sets(panel_report)
    low_success = _diagnostic_targets(
        redesign_diagnostic, "target_protocol_mismatch_low_success"
    )
    low_pae_holds = _diagnostic_targets(
        redesign_diagnostic, "underpowered_low_pae_acceptance"
    )
    split_holds = _diagnostic_targets(
        redesign_diagnostic, "underpowered_or_split_sensitive"
    )
    cutoff_failures = _diagnostic_targets(
        redesign_diagnostic, "low_pae_cutoff_not_transferable"
    )
    all_holds = _sorted_targets(low_pae_holds + split_holds + cutoff_failures)
    manifest_info = _manifest_summary(manifest)
    n_targets = int(panel_report.get("n_targets") or len(target_sets["not_certified"]))
    n_records = int(panel_report.get("n_records") or redesign_diagnostic.get("n_records") or 0)
    recommendation = redesign_diagnostic.get("summary", {}).get("recommendation")

    status = "no_spend_redesign_contract_required"
    if target_sets["certified"]:
        status = "mixed_target_readout_redesign_contract_required"
    if not target_sets["not_certified"]:
        status = "panel_certified_no_followup_contract_required"

    return {
        "artifact": "m6d_w2_target_family_followup_contract",
        "date": date,
        "branch_id": branch_id,
        "status": status,
        "can_mark_goal_complete": False,
        "source_panel_status": panel_report.get("panel_status"),
        "source_panel_ok": bool(panel_report.get("ok")),
        "source_diagnostic": redesign_diagnostic.get("diagnostic"),
        "diagnostic_recommendation": recommendation,
        "target_alpha": panel_report.get("target_alpha"),
        "n_targets": n_targets,
        "n_records": n_records,
        "ready_for_revised_manifest": False,
        "ready_for_target_msa_precompute": False,
        "ready_for_cayuga_submission": False,
        "claim_boundary": {
            "w2_multi_target_generalization": "not_supported",
            "panel_readout": "completed_negative_evaluable",
            "reason": "zero or insufficient target-wise certificates under the predeclared W2 gate",
            "gpu_spend": "blocked_until_followup_contract_preconditions_pass",
        },
        "source_manifest": manifest_info,
        "target_sets": {
            "target_wise_certified_controls": target_sets["certified"],
            "target_wise_not_certified": target_sets["not_certified"],
            "replace_or_redesign_low_success_targets": low_success,
            "hold_until_low_pae_acceptance_or_target_specific_calibration": all_holds,
            "cutoff_transfer_failure_targets": cutoff_failures,
        },
        "redesign_decision": {
            "selected_branch": branch_id,
            "selected_policy": "success_enriched_discovery_plus_gate_redesign",
            "rationale": (
                "The panel is evaluable but not certified target-wise. Low-success "
                "targets indicate target/protocol mismatch, while high-success/no-trust "
                "targets require a low-pAE acceptance or target-specific calibration policy."
            ),
            "do_not_do": [
                "do not pool the v7 records into a W2 generalization certificate",
                "do not spend more W2 panel GPU on low-success targets under the same protocol",
                "do not transfer the fixed t0.3 low-pAE cutoff as a certificate",
                "do not submit another manifest before strict target-wise preflight and replay commands exist",
            ],
        },
        "tracks": [
            {
                "name": "replacement_target_discovery",
                "priority": 1,
                "eligible_targets": "new_non_anchor_source_diverse_targets_only",
                "blocked_targets": low_success,
                "entry_gate": "no-spend structural discovery and sequence-diversity screen",
                "exit_gate": "at least three non-anchor targets pass manifest/preflight before Cayuga",
            },
            {
                "name": "low_pae_acceptance_gate_redesign",
                "priority": 2,
                "eligible_targets": all_holds,
                "blocked_targets": low_success,
                "entry_gate": "predeclare target-specific or family-calibrated RCPS before records are generated",
                "exit_gate": "each claimed target certifies at alpha<=0.2 target-wise; pooled-only tau stays diagnostic",
            },
            {
                "name": "generation_protocol_redesign",
                "priority": 3,
                "eligible_targets": low_success,
                "blocked_targets": [],
                "entry_gate": "new protocol id required before reusing low-success targets",
                "exit_gate": "pilot must show plausible success rate before broad W2 panel spend",
            },
        ],
        "manifest_preconditions": [
            "at least three non-anchor source-diverse targets",
            "sequence-diversity gate passes before full-panel claims",
            "no low-success target reused under the same generation/evaluation protocol",
            "low-pAE acceptance or target-specific calibration rule is predeclared",
            "single predictor_id, signal_source, label_source, and lrmsd_threshold per panel",
            "strict complex_target_manifest --require-files passes",
            "completion and panel-report replay commands are emitted before submission",
        ],
        "cayuga_unlock_conditions": [
            "candidate screen admits at least three non-anchor targets under this contract",
            "revised target manifest is written and linked from the goal anchor",
            "strict post-MSA manifest preflight passes",
            "receipt-preserving submit wrapper, completion plan, and panel report command are generated",
        ],
        "next_action": (
            "run a no-spend replacement-target discovery or gate-redesign screen under this contract; "
            "do not submit W2 panel jobs until the unlock conditions pass"
        ),
    }


def build_candidate_rules(contract: Dict[str, Any], *,
                          source_contract: str = "results/m6d_w2_target_family_redesign_v8_followup_contract.json") -> Dict[str, Any]:
    target_sets = contract.get("target_sets", {})
    blocked_targets = _sorted_targets(
        target_sets.get("replace_or_redesign_low_success_targets", [])
        + target_sets.get("hold_until_low_pae_acceptance_or_target_specific_calibration", [])
    )
    manifest = contract.get("source_manifest", {})
    source_ids = manifest.get("source_rcsb_ids", []) if isinstance(manifest, dict) else []
    return {
        "artifact": "m6d_w2_target_family_followup_candidate_rules",
        "date": contract.get("date"),
        "protocol_id": contract.get("branch_id"),
        "source_contract": source_contract,
        "ready_for_cayuga_submission": False,
        "excluded_targets_under_current_protocol": blocked_targets,
        "excluded_source_rcsb_ids": _sorted_targets(source_ids),
        "positive_controls_not_generalization_targets": target_sets.get(
            "target_wise_certified_controls", []
        ),
        "candidate_requirements": {
            "min_non_anchor_candidates_for_revised_manifest": 3,
            "min_ca_interface_contacts": 20,
            "require_source_pdb_deduplication": True,
            "require_sequence_diversity_gate": True,
            "max_largest_cluster_fraction_for_full_panel": 0.25,
            "require_prepared_pdb": True,
            "require_prep_report": True,
            "require_target_fasta": True,
            "require_target_fasta_report": True,
            "require_target_msa": True,
            "require_target_msa_report": True,
            "reject_current_protocol_low_success_targets": True,
            "reject_current_protocol_zero_trusted_targets_without_gate_redesign": True,
        },
        "gate_requirements": {
            "target_alpha": contract.get("target_alpha", 0.2),
            "require_target_wise_certificates": True,
            "disallow_pooled_only_claim": True,
            "fixed_low_pae_cutoff_transfer_allowed": False,
            "target_specific_or_family_rcps_must_be_predeclared": True,
        },
        "spend_gate": {
            "cayuga_submission_allowed": False,
            "unlock_conditions": contract.get("cayuga_unlock_conditions", []),
        },
        "can_mark_goal_complete": False,
    }


def render_markdown(contract: Dict[str, Any]) -> str:
    target_sets = contract.get("target_sets", {})
    lines = [
        "# W2 Target-Family Follow-up Contract",
        "",
        f"Date: {contract.get('date')}",
        f"Branch: `{contract.get('branch_id')}`",
        f"Status: `{contract.get('status')}`",
        f"Panel: `{contract.get('source_panel_status')}`; targets={contract.get('n_targets')} records={contract.get('n_records')}",
        f"Recommendation: `{contract.get('diagnostic_recommendation')}`",
        "",
        "## Claim Boundary",
        "",
        "This is a no-spend redesign contract, not W2 generalization evidence.",
        "",
        "## Target Sets",
        "",
    ]
    for key in [
        "target_wise_certified_controls",
        "target_wise_not_certified",
        "replace_or_redesign_low_success_targets",
        "hold_until_low_pae_acceptance_or_target_specific_calibration",
        "cutoff_transfer_failure_targets",
    ]:
        values = target_sets.get(key, [])
        joined = ", ".join(values) if values else "none"
        lines.append(f"- {key}: {joined}")
    lines.extend([
        "",
        "## Tracks",
        "",
        "| priority | track | entry gate | exit gate |",
        "|---:|---|---|---|",
    ])
    for track in contract.get("tracks", []):
        lines.append(
            f"| {track.get('priority')} | {track.get('name')} | "
            f"{track.get('entry_gate')} | {track.get('exit_gate')} |"
        )
    lines.extend([
        "",
        "## Manifest Preconditions",
        "",
    ])
    lines.extend(f"- {item}" for item in contract.get("manifest_preconditions", []))
    lines.extend([
        "",
        "## Cayuga Unlock Conditions",
        "",
    ])
    lines.extend(f"- {item}" for item in contract.get("cayuga_unlock_conditions", []))
    lines.extend([
        "",
        "## Next Action",
        "",
        contract.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel-report", required=True)
    ap.add_argument("--redesign-diagnostic", required=True)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--branch-id", default=DEFAULT_BRANCH_ID)
    ap.add_argument("--date", default=DEFAULT_DATE)
    ap.add_argument("--out-json", default="results/m6d_w2_target_family_redesign_v8_followup_contract.json")
    ap.add_argument("--out-md", default="results/m6d_w2_target_family_redesign_v8_followup_contract.md")
    ap.add_argument("--out-candidate-rules", default="configs/m6d_w2_target_family_redesign_v8_candidate_rules.json")
    args = ap.parse_args(argv)

    contract = build_contract(
        _load_json(args.panel_report),
        _load_json(args.redesign_diagnostic),
        _load_json(args.manifest) if args.manifest else None,
        branch_id=args.branch_id,
        date=args.date,
    )
    _write_json(args.out_json, contract)
    _write_text(args.out_md, render_markdown(contract))
    if args.out_candidate_rules:
        _write_json(
            args.out_candidate_rules,
            build_candidate_rules(contract, source_contract=args.out_json),
        )
    print(
        "status={status} branch={branch} ready_cayuga={ready} next={next_action}".format(
            status=contract["status"],
            branch=contract["branch_id"],
            ready=str(bool(contract["ready_for_cayuga_submission"])).lower(),
            next_action=contract["next_action"],
        )
    )
    print(f"wrote {args.out_json} and {args.out_md}")
    if args.out_candidate_rules:
        print(f"wrote {args.out_candidate_rules}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
