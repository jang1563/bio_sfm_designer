"""Render the current M6d W2/W3 goal-mode decision protocol.

This helper turns the current local evidence into a durable no-spend decision
artifact. It does not submit jobs. Its job is to keep W2 target redesign and W3
predictor-disagreement handling explicit before any Cayuga/API work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _load_jsonl(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    rows: List[Dict[str, Any]] = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            rec = json.loads(text)
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{line_no}: JSONL record is not an object")
            rows.append(rec)
    return rows


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    return n


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


def _ratio_from_text(text: Any) -> Optional[Tuple[int, int]]:
    if not isinstance(text, str) or "/" not in text:
        return None
    prefix = text.split()[0]
    left, right = prefix.split("/", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None


def _rate_from_ratio_text(text: Any) -> Optional[float]:
    ratio = _ratio_from_text(text)
    if not ratio:
        return None
    num, den = ratio
    return num / den if den else None


def _median_extra_records(value: Any) -> Optional[float]:
    if not isinstance(value, dict):
        return None
    median = value.get("median")
    return float(median) if isinstance(median, (int, float)) else None


def _index_by_target(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        target = row.get("target") or row.get("complex_target_id")
        if isinstance(target, str) and target:
            out[target] = row
    return out


def _w2_branch(science_actions: Dict[str, Any],
               panel_diagnostic: Dict[str, Any]) -> Dict[str, Any]:
    triage = _index_by_target(science_actions.get("target_triage", []))
    diagnostics = _index_by_target(panel_diagnostic.get("targets", []))
    targets: List[Dict[str, Any]] = []

    for target in sorted(set(triage) | set(diagnostics)):
        triage_row = triage.get(target, {})
        diag_row = diagnostics.get(target, {})
        alpha030_rate = _rate_from_ratio_text(triage_row.get("alpha_0_3_seed_sensitivity"))
        alpha020_rate = _rate_from_ratio_text(triage_row.get("alpha_0_2_seed_sensitivity"))
        median_extra = _median_extra_records(
            triage_row.get("estimated_additional_records_for_alpha_0_2")
        )
        classification = diag_row.get("classification")
        action = triage_row.get("action") or diag_row.get("recommended_action")

        if target == "3PC8_AB":
            role = "freeze_target_specific_certificate"
        elif classification == "target_protocol_mismatch_low_success":
            role = "drop_or_replace"
        elif alpha030_rate is not None and alpha030_rate >= 0.8 and (
            median_extra is None or median_extra <= 100
        ):
            role = "near_candidate_for_target_specific_scale"
        elif classification == "underpowered_or_split_sensitive":
            role = "anchor_or_reference"
        else:
            role = "do_not_scale_under_current_protocol"

        targets.append({
            "target": target,
            "role": role,
            "classification": classification,
            "success_rate": diag_row.get("success_rate"),
            "alpha_0_2_seed_rate": alpha020_rate,
            "alpha_0_3_seed_rate": alpha030_rate,
            "median_extra_records_for_alpha_0_2": median_extra,
            "recommended_action": action,
        })

    return {
        "status": "redesign_required_before_more_broad_panel_gpu",
        "current_result": "current W2 panel is evaluable but not alpha=0.2 certified",
        "claim_boundary": "multi_target_generalization_not_supported",
        "selected_policy": "staged_target_screen_before_broad_panel",
        "target_rules": [
            "freeze target-specific certificates as target-specific evidence only",
            "drop or replace target_protocol_mismatch_low_success targets",
            "require pilot evidence before broad W2 panel spend",
            "prefer candidates with alpha=0.3 split-seed certification rate >=0.8 and projected extra records for alpha=0.2 <=100",
            "require target FASTA/MSA/report preflight and panel completion before any panel report",
        ],
        "targets": targets,
    }


def _first_pair(cross: Dict[str, Any]) -> Dict[str, Any]:
    pairs = cross.get("pairs")
    if isinstance(pairs, list) and pairs and isinstance(pairs[0], dict):
        return pairs[0]
    return {}


def _failure_kinds(cross: Dict[str, Any]) -> List[str]:
    kinds = []
    for failure in cross.get("failures", []):
        if isinstance(failure, dict):
            kind = failure.get("kind")
            if isinstance(kind, str) and kind:
                kinds.append(kind)
    return sorted(set(kinds))


def _bool_field(obj: Dict[str, Any], field: str) -> bool:
    return obj.get(field) is True


def _strict_adjudication_integrity(pair: Dict[str, Any],
                                   failure_kinds: Iterable[str]) -> Tuple[bool, List[str]]:
    blockers: List[str] = []
    kinds = set(failure_kinds)
    non_agreement_failures = kinds - {"label_agreement_below_min"}
    if non_agreement_failures:
        blockers.append("cross_predictor_has_non_agreement_failures")
    required_true = [
        "meets_min_overlap",
        "meets_min_labeled_overlap",
        "complex_target_id_complete",
        "complex_target_id_agree",
        "label_threshold_complete",
        "label_threshold_agree",
        "provenance_complete",
        "distinct_signal_sources",
        "distinct_label_sources",
    ]
    for field in required_true:
        if not _bool_field(pair, field):
            blockers.append(field)
    if pair.get("copied_numeric_values") is True:
        blockers.append("copied_numeric_values")
    return not blockers, blockers


def _w3_adjudication_set(matches: List[Dict[str, Any]], controls: int) -> Dict[str, Any]:
    discordant: List[str] = []
    concordant: List[str] = []
    for row in matches:
        target_id = row.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            continue
        if row.get("label_a") != row.get("label_b"):
            discordant.append(target_id)
        elif row.get("label_a") is True and row.get("label_b") is True:
            concordant.append(target_id)
    return {
        "discordant_target_ids": sorted(discordant),
        "concordant_success_control_ids": sorted(concordant)[:controls],
        "control_selection": f"first {controls} sorted concordant-success ids",
    }


def _w3_adjudication_rows(matches: List[Dict[str, Any]], controls: int) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in matches:
        target_id = row.get("target_id")
        if isinstance(target_id, str) and target_id:
            by_id[target_id] = row

    selected = _w3_adjudication_set(matches, controls)
    rows: List[Dict[str, Any]] = []
    for role, ids, reason in [
        (
            "discordant_boltz_chai_label",
            selected["discordant_target_ids"],
            "label_a != label_b",
        ),
        (
            "concordant_success_control",
            selected["concordant_success_control_ids"],
            selected["control_selection"],
        ),
    ]:
        for rank, target_id in enumerate(ids, 1):
            source = dict(by_id[target_id])
            source.update({
                "adjudication_rank": rank,
                "adjudication_role": role,
                "adjudication_selection_reason": reason,
                "selected_protocol": "adjudicated_disagreement_protocol_v1",
            })
            rows.append(source)
    return rows


def materialize_w3_adjudication_set(matches: List[Dict[str, Any]],
                                    *,
                                    controls: int,
                                    source_matches: str,
                                    out_jsonl: str,
                                    out_summary: str) -> Dict[str, Any]:
    rows = _w3_adjudication_rows(matches, controls)
    n_rows = _write_jsonl(out_jsonl, rows)
    counts: Dict[str, int] = {}
    target_ids_by_role: Dict[str, List[str]] = {}
    for row in rows:
        role = str(row.get("adjudication_role"))
        counts[role] = counts.get(role, 0) + 1
        target_ids_by_role.setdefault(role, []).append(str(row.get("target_id")))

    summary = {
        "artifact": "m6d_w3_adjudication_set",
        "claim_boundary": "not a positive robustness claim; input set for future W3 adjudication only",
        "controls_requested": controls,
        "counts_by_role": counts,
        "n_rows": n_rows,
        "out_jsonl": out_jsonl,
        "out_jsonl_sha256": _sha256_file(out_jsonl),
        "out_summary": out_summary,
        "selected_protocol": "adjudicated_disagreement_protocol_v1",
        "source_matches": source_matches,
        "target_ids_by_role": target_ids_by_role,
    }
    _write_json(out_summary, summary)
    return summary


def _w3_branch(cross_predictor: Dict[str, Any],
               matches: List[Dict[str, Any]],
               *,
               controls: int) -> Dict[str, Any]:
    pair = _first_pair(cross_predictor)
    failure_kinds = _failure_kinds(cross_predictor)
    integrity_ok, integrity_blockers = _strict_adjudication_integrity(pair, failure_kinds)
    label_agreement = pair.get("label_agreement")
    min_label_agreement = pair.get("min_label_agreement") or cross_predictor.get("min_label_agreement")
    current_passes = bool(cross_predictor.get("ok"))
    disagreement = (
        isinstance(label_agreement, (int, float))
        and isinstance(min_label_agreement, (int, float))
        and label_agreement < min_label_agreement
    )

    if current_passes:
        current_protocol_verdict = "cross_predictor_ready"
        selected_protocol = "preserve_positive_cross_predictor_result"
        next_spend_gate = "no W3 disagreement spend required"
    elif disagreement and integrity_ok:
        current_protocol_verdict = "negative_robustness_result_for_no_msa_chai"
        selected_protocol = "adjudicated_disagreement_protocol_v1"
        next_spend_gate = (
            "do not rerun no-MSA Chai; any further W3 spend must use the adjudication set "
            "with either a third predictor/protocol or a stronger Chai MSA/template protocol"
        )
    else:
        current_protocol_verdict = "unresolved_contract_or_overlap_blocker"
        selected_protocol = "repair_contract_before_science_claim"
        next_spend_gate = "repair QC/contract/overlap blockers before any robustness claim"

    return {
        "status": "protocol_selected",
        "current_protocol_verdict": current_protocol_verdict,
        "selected_protocol": selected_protocol,
        "claim_boundary": (
            "independent_predictor_robustness_not_supported"
            if not current_passes else "independent_predictor_robustness_supported"
        ),
        "label_agreement": label_agreement,
        "min_label_agreement": min_label_agreement,
        "matched_overlap": pair.get("n_overlap") or cross_predictor.get("n_match_rows"),
        "both_success": pair.get("both_success"),
        "both_failure": pair.get("both_failure"),
        "boltz_only_success": pair.get("predictor_a_only_success"),
        "chai_only_success": pair.get("predictor_b_only_success"),
        "pae_interaction_pearson": pair.get("pae_interaction_pearson"),
        "lrmsd_pearson": pair.get("lrmsd_pearson"),
        "numeric_copy_fraction": pair.get("numeric_copy_fraction"),
        "cross_predictor_failure_kinds": failure_kinds,
        "strict_adjudication_integrity": integrity_ok,
        "strict_adjudication_integrity_blockers": integrity_blockers,
        "next_spend_gate": next_spend_gate,
        "adjudication_set": _w3_adjudication_set(matches, controls),
        "protocol_rules": [
            "treat the completed no-MSA Chai comparison as a negative robustness result under that protocol",
            "do not close the single-predictor caveat from Chai records alone",
            "use the deterministic discordant-plus-control adjudication set before any new W3 spend",
            "predeclare the acceptance rule before running a third predictor or stronger Chai MSA/template protocol",
            "keep label threshold, target identity, chain identity, and provenance checks strict",
        ],
    }


def build_report(goal_anchor: Dict[str, Any],
                 science_actions: Dict[str, Any],
                 panel_diagnostic: Dict[str, Any],
                 cross_predictor: Dict[str, Any],
                 matches: List[Dict[str, Any]],
                 *,
                 controls: int = 6,
                 report_date: str = "2026-06-30") -> Dict[str, Any]:
    return {
        "artifact": "m6d_w2_w3_decision_protocol",
        "date": report_date,
        "goal_objective": goal_anchor.get("objective"),
        "goal_status_inherited": goal_anchor.get("current_status"),
        "overall_status": "w2_w3_decision_protocol_selected_goal_still_active",
        "can_mark_goal_complete": False,
        "completion_boundary": (
            "W2 target generalization still needs a redesigned target/protocol branch; "
            "W3 robustness is negative for no-MSA Chai and requires adjudication for any future positive claim."
        ),
        "w1": {
            "status": goal_anchor.get("current_status", {}).get("w1"),
            "claim_boundary": "preserve as target-specific certified evidence",
        },
        "w2": _w2_branch(science_actions, panel_diagnostic),
        "w3": _w3_branch(cross_predictor, matches, controls=controls),
        "w4": {
            "status": goal_anchor.get("current_status", {}).get("w4"),
            "claim_boundary": "preserve as fail-closed closed-loop plumbing evidence only",
        },
        "next_actions": [
            "Use W2 staged target-screen rules before building a revised target manifest.",
            "Treat the current no-MSA Chai W3 comparison as a negative robustness result.",
            "If W3 is pursued further, run only a predeclared adjudication protocol on discordant plus control designs.",
            "Refresh project status after the next meaningful W2 or W3 artifact is written.",
        ],
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2/W3 Decision Protocol",
        "",
        f"Date: {rep.get('date')}",
        "",
        "## Summary",
        "",
        f"Overall status: `{rep.get('overall_status')}`.",
        "",
        rep.get("completion_boundary", ""),
        "",
        "## W2 Target-Redesign Protocol",
        "",
        f"Status: `{rep['w2'].get('status')}`.",
        "",
        "Selected policy: `staged_target_screen_before_broad_panel`.",
        "",
        "| target | role | classification | alpha0.3 seed rate | median extra records | action |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in rep["w2"].get("targets", []):
        lines.append(
            "| {target} | {role} | {classification} | {alpha030} | {extra} | {action} |".format(
                target=row.get("target"),
                role=row.get("role"),
                classification=_fmt(row.get("classification")),
                alpha030=_fmt(row.get("alpha_0_3_seed_rate")),
                extra=_fmt(row.get("median_extra_records_for_alpha_0_2")),
                action=_fmt(row.get("recommended_action")),
            )
        )
    lines.extend([
        "",
        "Rules:",
    ])
    lines.extend(f"- {rule}" for rule in rep["w2"].get("target_rules", []))
    lines.extend([
        "",
        "## W3 Predictor-Disagreement Protocol",
        "",
        f"Status: `{rep['w3'].get('status')}`.",
        f"Current protocol verdict: `{rep['w3'].get('current_protocol_verdict')}`.",
        f"Selected protocol: `{rep['w3'].get('selected_protocol')}`.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| label agreement | {_fmt(rep['w3'].get('label_agreement'))} |",
        f"| minimum label agreement | {_fmt(rep['w3'].get('min_label_agreement'))} |",
        f"| matched overlap | {_fmt(rep['w3'].get('matched_overlap'))} |",
        f"| both success | {_fmt(rep['w3'].get('both_success'))} |",
        f"| Boltz-failure / Chai-success | {_fmt(rep['w3'].get('chai_only_success'))} |",
        f"| numeric-copy fraction | {_fmt(rep['w3'].get('numeric_copy_fraction'))} |",
        f"| strict adjudication integrity | {_fmt(rep['w3'].get('strict_adjudication_integrity'))} |",
        "",
        f"Cross-predictor failure kinds: `{', '.join(rep['w3'].get('cross_predictor_failure_kinds', [])) or 'none'}`.",
        "",
        f"Next spend gate: {rep['w3'].get('next_spend_gate')}",
        "",
        "Adjudication set:",
    ])
    adj = rep["w3"].get("adjudication_set", {})
    lines.append(f"- Discordant designs: {len(adj.get('discordant_target_ids', []))}")
    lines.append(f"- Concordant-success controls: {len(adj.get('concordant_success_control_ids', []))}")
    artifact = rep["w3"].get("adjudication_set_artifact")
    if isinstance(artifact, dict):
        lines.append(
            f"- Materialized JSONL: `{artifact.get('out_jsonl')}` "
            f"({artifact.get('n_rows')} rows; sha256 `{artifact.get('out_jsonl_sha256')}`)"
        )
        lines.append(f"- Summary JSON: `{artifact.get('out_summary')}`")
    lines.extend([
        "",
        "Rules:",
    ])
    lines.extend(f"- {rule}" for rule in rep["w3"].get("protocol_rules", []))
    lines.extend([
        "",
        "## Next Actions",
        "",
    ])
    lines.extend(f"{i}. {item}" for i, item in enumerate(rep.get("next_actions", []), 1))
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--goal-anchor", default="results/m6d_goal_mode_current_anchor.json")
    ap.add_argument("--science-actions", default="results/m6d_followup_next_science_actions.json")
    ap.add_argument("--w2-panel-diagnostic", default="results/m6d_followup_panel_diagnostic.json")
    ap.add_argument("--w3-cross-predictor", default="results/m6c_cross_predictor.json")
    ap.add_argument("--w3-matches", default="results/m6c_cross_predictor_matches.jsonl")
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--emit-w3-adjudication-set-jsonl", default=None,
                    help="optional JSONL path for the full discordant-plus-control W3 adjudication set")
    ap.add_argument("--emit-w3-adjudication-summary", default=None,
                    help="optional summary JSON path for --emit-w3-adjudication-set-jsonl")
    ap.add_argument("--out-json", default="results/m6d_w2_w3_decision_protocol.json")
    ap.add_argument("--out-md", default="results/m6d_w2_w3_decision_protocol.md")
    args = ap.parse_args(argv)

    matches = _load_jsonl(args.w3_matches)
    rep = build_report(
        _load_json(args.goal_anchor),
        _load_json(args.science_actions),
        _load_json(args.w2_panel_diagnostic),
        _load_json(args.w3_cross_predictor),
        matches,
        controls=args.controls,
        report_date=args.date,
    )
    if args.emit_w3_adjudication_set_jsonl:
        summary_path = (
            args.emit_w3_adjudication_summary
            or os.path.splitext(args.emit_w3_adjudication_set_jsonl)[0] + "_summary.json"
        )
        rep["w3"]["adjudication_set_artifact"] = materialize_w3_adjudication_set(
            matches,
            controls=args.controls,
            source_matches=args.w3_matches,
            out_jsonl=args.emit_w3_adjudication_set_jsonl,
            out_summary=summary_path,
        )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} w2={w2} w3={w3} complete={complete}".format(
            status=rep["overall_status"],
            w2=rep["w2"]["status"],
            w3=rep["w3"]["current_protocol_verdict"],
            complete=rep["can_mark_goal_complete"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
