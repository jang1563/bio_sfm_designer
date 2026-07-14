"""Apply the preregistered joint adjudication to completed W3 AF2 records."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


_PACKET_STATUS = "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit"


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            rows.append(value)
    return rows


def _record_label(row: Mapping[str, Any]) -> Optional[bool]:
    truth = row.get("truth")
    if not isinstance(truth, dict) or not isinstance(truth.get("correct"), bool):
        return None
    return bool(truth["correct"])


def adjudicate(packet: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    rows = list(records)
    public_rows = packet.get("rows")
    if packet.get("status") != _PACKET_STATUS or packet.get("audit_ok") is not True:
        failures.append({"kind": "packet_not_preregistered_and_audited"})
    if not isinstance(public_rows, list) or len(public_rows) != 58:
        failures.append({"kind": "packet_row_count_invalid", "observed": len(public_rows or [])})
        public_rows = []
    public = {str(row.get("case_id")): row for row in public_rows if isinstance(row, dict)}
    by_case: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if not case_id or case_id in by_case:
            failures.append({"kind": "missing_or_duplicate_result_case_id", "case_id": case_id})
            continue
        by_case[case_id] = row
        expected = public.get(case_id)
        if expected is None:
            failures.append({"kind": "unexpected_result_case_id", "case_id": case_id})
            continue
        checks = {
            "target_id": expected.get("source_target_id"),
            "complex_target_id": expected.get("complex_target_id"),
            "predictor_id": "af2_multimer_colabfold_v1",
            "signal_source": "af2_multimer_pae_interaction",
            "label_source": "af2_multimer_lrmsd_to_reference",
            "lrmsd_threshold": 4.0,
            "interface_aligned": True,
        }
        for field, expected_value in checks.items():
            if row.get(field) != expected_value:
                failures.append({
                    "kind": "result_contract_mismatch",
                    "case_id": case_id,
                    "field": field,
                    "expected": expected_value,
                    "observed": row.get(field),
                })
        label = _record_label(row)
        if label is None:
            failures.append({"kind": "result_label_missing", "case_id": case_id})
        for field in ("lrmsd", "pae_interaction", "mean_plddt"):
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                failures.append({
                    "kind": "result_metric_missing_or_invalid",
                    "case_id": case_id,
                    "field": field,
                })
                continue
            if not math.isfinite(value):
                failures.append({
                    "kind": "result_metric_nonfinite",
                    "case_id": case_id,
                    "field": field,
                })
            if field == "lrmsd" and label is not None and (value < 4.0) is not label:
                failures.append({
                    "kind": "result_label_lrmsd_mismatch",
                    "case_id": case_id,
                    "lrmsd": value,
                    "label": label,
                })
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            failures.append({"kind": "result_provenance_missing", "case_id": case_id})
            provenance = {}
        expected_provenance = {
            "panel_block": expected.get("panel_block"),
            "panel_role": expected.get("panel_role"),
            "a3m_sha256": expected.get("a3m_sha256"),
            "reference_backbone_sha256": expected.get("reference_backbone_sha256"),
            "target_sequence_sha256": expected.get("target_sequence_sha256"),
            "binder_sequence_sha256": expected.get("binder_sequence_sha256"),
        }
        for field, expected_value in expected_provenance.items():
            if provenance.get(field) != expected_value:
                failures.append({
                    "kind": "result_provenance_mismatch",
                    "case_id": case_id,
                    "field": field,
                    "expected": expected_value,
                    "observed": provenance.get(field),
                })
    missing = sorted(set(public) - set(by_case))
    if missing:
        failures.append({"kind": "result_cases_missing", "count": len(missing), "examples": missing[:5]})
    if len(rows) != 58:
        failures.append({"kind": "result_row_count_invalid", "expected": 58, "observed": len(rows)})

    discordant = []
    controls = []
    w2c = []
    for case_id, expected in public.items():
        observed = by_case.get(case_id)
        if observed is None or _record_label(observed) is None:
            continue
        item = (expected, _record_label(observed))
        if expected.get("panel_block") == "boltz_chai_3pc8_challenge":
            if expected.get("panel_role") == "discordant_boltz_chai_label":
                discordant.append(item)
            elif expected.get("panel_role") == "concordant_success_control":
                controls.append(item)
        elif expected.get("panel_block") == "w2c_pae_order_statistics":
            w2c.append(item)

    boltz_align = sum(label == expected.get("source_boltz2_label") for expected, label in discordant)
    chai_align = sum(label == expected.get("source_chai1_label") for expected, label in discordant)
    control_successes = sum(label is True for _, label in controls)
    if len(discordant) == 12 and len(controls) == 6 and control_successes >= 5 and boltz_align >= 10:
        three_pc8_outcome = "boltz_supported_on_challenge_panel"
    elif len(discordant) == 12 and len(controls) == 6 and control_successes >= 5 and chai_align >= 10:
        three_pc8_outcome = "chai_supported_on_challenge_panel"
    else:
        three_pc8_outcome = "mixed_or_contract_blocked"

    agreement_by_target: Dict[str, List[bool]] = defaultdict(list)
    for expected, label in w2c:
        agreement_by_target[str(expected.get("complex_target_id"))].append(
            label == expected.get("source_boltz2_label")
        )
    global_agreement = sum(sum(values) for values in agreement_by_target.values())
    targets_at_least_four = sum(len(values) == 5 and sum(values) >= 4 for values in agreement_by_target.values())
    if len(w2c) == 40 and len(agreement_by_target) == 8 and global_agreement >= 32 and targets_at_least_four >= 6:
        w2c_outcome = "boltz_supported_on_w2c_mechanism_panel"
    elif len(w2c) == 40 and len(agreement_by_target) == 8 and (global_agreement <= 24 or targets_at_least_four <= 3):
        w2c_outcome = "strong_predictor_label_instability"
    else:
        w2c_outcome = "mixed_or_contract_blocked"

    if failures:
        joint = "contract_blocked"
    elif (
        three_pc8_outcome == "boltz_supported_on_challenge_panel"
        and w2c_outcome == "boltz_supported_on_w2c_mechanism_panel"
    ):
        joint = "boltz_supported_target_or_coverage_mechanism"
    elif (
        three_pc8_outcome == "chai_supported_on_challenge_panel"
        and w2c_outcome == "strong_predictor_label_instability"
    ):
        joint = "predictor_protocol_disagreement_dominant"
    else:
        joint = "context_dependent_or_unresolved"

    report = {
        "artifact": "m6d_w3_mechanism_panel_adjudication",
        "status": "adjudicated" if not failures else "adjudication_blocked",
        "audit_ok": not failures,
        "failures": failures,
        "three_pc8": {
            "n_discordant": len(discordant),
            "n_controls": len(controls),
            "aligns_with_boltz": boltz_align,
            "aligns_with_chai": chai_align,
            "control_successes": control_successes,
            "outcome": three_pc8_outcome,
        },
        "w2c": {
            "n_rows": len(w2c),
            "n_targets": len(agreement_by_target),
            "label_agreement_with_boltz": global_agreement,
            "label_agreement_fraction": global_agreement / 40.0 if len(w2c) == 40 else None,
            "targets_with_at_least_4_of_5_agreement": targets_at_least_four,
            "agreement_by_target": {
                target: {"agrees": sum(values), "n": len(values)}
                for target, values in sorted(agreement_by_target.items())
            },
            "outcome": w2c_outcome,
        },
        "joint_outcome": joint,
        "can_claim_population_level_independent_predictor_robustness": False,
        "can_reopen_or_rescue_w2c": False,
        "claim_boundary": (
            "This adjudicates only the preregistered 58-case mechanism panel. It can support a "
            "bounded failure-mechanism interpretation but not population-level robustness or W2c rescue."
        ),
    }
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    three = report.get("three_pc8") or {}
    w2c = report.get("w2c") or {}
    return "\n".join([
        "# M6d W3 mechanism-panel adjudication",
        "",
        f"Status: `{report.get('status')}`.",
        "",
        "## 3PC8 block",
        "",
        f"- Boltz alignments: {three.get('aligns_with_boltz')}/12",
        f"- Chai alignments: {three.get('aligns_with_chai')}/12",
        f"- Successful controls: {three.get('control_successes')}/6",
        f"- Outcome: `{three.get('outcome')}`",
        "",
        "## W2c block",
        "",
        f"- Global Boltz label agreement: {w2c.get('label_agreement_with_boltz')}/40",
        f"- Targets with at least 4/5 agreement: {w2c.get('targets_with_at_least_4_of_5_agreement')}/8",
        f"- Outcome: `{w2c.get('outcome')}`",
        "",
        "## Joint outcome",
        "",
        f"`{report.get('joint_outcome')}`",
        "",
        str(report.get("claim_boundary")),
        "",
    ])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Adjudicate the completed W3 mechanism panel")
    parser.add_argument("--packet", default="configs/m6d_w3_mechanism_panel_protocol.json")
    parser.add_argument("--records", default="results/m6d_w3_mechanism_panel_af2_records.jsonl")
    parser.add_argument("--out-json", default="results/m6d_w3_mechanism_panel_adjudication.json")
    parser.add_argument("--out-md", default="results/m6d_w3_mechanism_panel_adjudication.md")
    args = parser.parse_args(argv)
    report = adjudicate(_load_json(args.packet), _load_jsonl(args.records))
    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.makedirs(os.path.dirname(args.out_md) or ".", exist_ok=True)
    with open(args.out_md, "w") as handle:
        handle.write(render_markdown(report))
    return 0 if report["audit_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
