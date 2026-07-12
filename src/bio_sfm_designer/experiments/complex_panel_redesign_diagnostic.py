"""Diagnose negative W2 complex-panel evidence for target/protocol redesign.

`complex_panel_report.py` owns the certification decision. This helper keeps the
next scientific action explicit when a panel is evaluable but not certified:
which targets look like protocol/target mismatches, which are merely
underpowered, and whether the scoped W1 protocol cutoff transfers.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Any, Dict, Iterable, List, Optional


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _resolve_path(path: str, *, base_dir: str) -> str:
    if os.path.isabs(path):
        return path
    if os.path.exists(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(base_dir, path))


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            rec = json.loads(text)
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{line_no}: JSONL record is not an object")
            rows.append(rec)
    return rows


def _float_value(rec: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = rec.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
    return None


def _median(values: Iterable[float]) -> Optional[float]:
    values = list(values)
    if not values:
        return None
    return float(statistics.median(values))


def _target_panel_row(panel_report: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    for row in panel_report.get("targets", []):
        if isinstance(row, dict) and row.get("complex_target_id") == target_id:
            return row
    return {}


def _protocol_cutoff(protocol_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(protocol_summary, dict):
        return {
            "available": False,
            "risk_tau": None,
            "pae_cutoff": None,
            "source": None,
        }
    t030 = protocol_summary.get("t030_protocol")
    if not isinstance(t030, dict):
        return {
            "available": False,
            "risk_tau": None,
            "pae_cutoff": None,
            "source": None,
        }
    tau = t030.get("target_tau")
    if not isinstance(tau, (int, float)):
        return {
            "available": False,
            "risk_tau": None,
            "pae_cutoff": None,
            "source": "t030_protocol.target_tau",
        }
    return {
        "available": True,
        "risk_tau": float(tau),
        "pae_cutoff": float(tau) * 30.0,
        "source": "t030_protocol.target_tau_x_30",
        "note": "Complex risk currently maps pAE_interaction to risk as pAE/30.",
    }


def _classify_target(*, success_rate: float, protocol_accepts: int,
                     protocol_false_accept_rate: Optional[float],
                     certified: bool,
                     min_success_rate: float,
                     min_protocol_accepts: int,
                     max_protocol_false_accept_rate: float) -> str:
    if certified:
        return "already_certified"
    if success_rate < min_success_rate:
        return "target_protocol_mismatch_low_success"
    if protocol_accepts < min_protocol_accepts:
        return "underpowered_low_pae_acceptance"
    if (
        protocol_false_accept_rate is not None
        and protocol_false_accept_rate > max_protocol_false_accept_rate
    ):
        return "low_pae_cutoff_not_transferable"
    return "underpowered_or_split_sensitive"


def _target_action(classification: str) -> str:
    if classification == "already_certified":
        return "retain_as_positive_control"
    if classification == "target_protocol_mismatch_low_success":
        return "replace_target_or_redesign_generation_protocol_before_more_gpu"
    if classification == "underpowered_low_pae_acceptance":
        return "do_not_scale_until_low_pae_acceptance_strategy_exists"
    if classification == "low_pae_cutoff_not_transferable":
        return "target_specific_calibration_required_before_cutoff_transfer"
    return "keep_as_anchor_or_scale_only_after_split_sensitivity_check"


def run_diagnostic(panel_report_path: str,
                   protocol_summary_path: Optional[str] = None, *,
                   min_success_rate: float = 0.25,
                   min_protocol_accepts: int = 10,
                   max_protocol_false_accept_rate: float = 0.2,
                   threshold: float = 4.0) -> Dict[str, Any]:
    panel_report = _load_json(panel_report_path)
    base_dir = os.path.dirname(os.path.abspath(panel_report_path)) or "."
    protocol_summary = _load_json(protocol_summary_path) if protocol_summary_path else None
    cutoff = _protocol_cutoff(protocol_summary)
    pae_cutoff = cutoff.get("pae_cutoff")

    target_rows = []
    records_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for record_path in panel_report.get("records", []):
        if not isinstance(record_path, str) or not record_path.strip():
            continue
        resolved = _resolve_path(record_path, base_dir=base_dir)
        rows = _load_jsonl(resolved)
        for row in rows:
            target_id = str(row.get("complex_target_id") or "unknown")
            records_by_target.setdefault(target_id, []).append(row)

    for target_id in sorted(records_by_target):
        rows = records_by_target[target_id]
        panel_row = _target_panel_row(panel_report, target_id)
        n = len(rows)
        successes = 0
        pae_values = []
        lrmsd_values = []
        protocol_accepts = 0
        protocol_false_accepts = 0
        for row in rows:
            lrmsd = _float_value(row, "lrmsd", "l_rmsd", "interface_lrmsd")
            row_threshold = _float_value(row, "lrmsd_threshold") or threshold
            pae = _float_value(row, "pae_interaction", "mean_pae_interaction", "pae_interaction_mean")
            if lrmsd is not None:
                lrmsd_values.append(lrmsd)
                if lrmsd < row_threshold:
                    successes += 1
            if pae is not None:
                pae_values.append(pae)
                if isinstance(pae_cutoff, (int, float)) and pae <= float(pae_cutoff):
                    protocol_accepts += 1
                    if lrmsd is not None and lrmsd >= row_threshold:
                        protocol_false_accepts += 1
        success_rate = successes / n if n else 0.0
        protocol_false_accept_rate = (
            protocol_false_accepts / protocol_accepts
            if protocol_accepts else None
        )
        certified = bool(panel_row.get("certified"))
        classification = _classify_target(
            success_rate=success_rate,
            protocol_accepts=protocol_accepts,
            protocol_false_accept_rate=protocol_false_accept_rate,
            certified=certified,
            min_success_rate=min_success_rate,
            min_protocol_accepts=min_protocol_accepts,
            max_protocol_false_accept_rate=max_protocol_false_accept_rate,
        )
        target_rows.append({
            "complex_target_id": target_id,
            "classification": classification,
            "recommended_action": _target_action(classification),
            "certified": certified,
            "n_records": n,
            "success": successes,
            "failure": n - successes,
            "success_rate": success_rate,
            "panel_status": panel_row.get("status"),
            "panel_trust_all_false_accept_rate": panel_row.get("trust_all_false_accept_rate"),
            "median_pae_interaction": _median(pae_values),
            "median_lrmsd": _median(lrmsd_values),
            "protocol_cutoff_accepts": protocol_accepts,
            "protocol_cutoff_false_accepts": protocol_false_accepts,
            "protocol_cutoff_false_accept_rate": protocol_false_accept_rate,
        })

    low_success = [
        row["complex_target_id"]
        for row in target_rows
        if row["classification"] == "target_protocol_mismatch_low_success"
    ]
    cutoff_failures = [
        row["complex_target_id"]
        for row in target_rows
        if row["classification"] == "low_pae_cutoff_not_transferable"
    ]
    underpowered = [
        row["complex_target_id"]
        for row in target_rows
        if row["classification"] in {
            "underpowered_low_pae_acceptance",
            "underpowered_or_split_sensitive",
        }
    ]
    if low_success:
        recommendation = "redesign_or_replace_low_success_targets"
    elif cutoff_failures:
        recommendation = "do_not_transfer_t030_cutoff_without_target_specific_calibration"
    elif underpowered:
        recommendation = "add_target_wise_scale_or_adjust_split"
    else:
        recommendation = "rerun_panel_report_or_inspect_unclassified_state"

    gpu_spend_gate = (
        "Do not spend more W2 panel GPU on targets classified as "
        "target_protocol_mismatch_low_success until the target is replaced or "
        "the generation/evaluation protocol is redesigned."
        if low_success else
        "Spend more W2 panel GPU only on target-wise hypotheses with explicit "
        "success-rate, predictor, signal, label, and threshold contracts."
    )

    return {
        "ok": True,
        "diagnostic": "complex_panel_redesign",
        "panel_report": os.path.abspath(panel_report_path),
        "protocol_summary": os.path.abspath(protocol_summary_path) if protocol_summary_path else None,
        "panel_status": panel_report.get("panel_status"),
        "target_alpha": panel_report.get("target_alpha"),
        "n_targets": len(target_rows),
        "n_records": sum(row["n_records"] for row in target_rows),
        "protocol_cutoff": cutoff,
        "thresholds": {
            "min_success_rate": min_success_rate,
            "min_protocol_accepts": min_protocol_accepts,
            "max_protocol_false_accept_rate": max_protocol_false_accept_rate,
            "label_threshold": threshold,
        },
        "targets": target_rows,
        "summary": {
            "low_success_targets": low_success,
            "cutoff_failure_targets": cutoff_failures,
            "underpowered_targets": underpowered,
            "recommendation": recommendation,
            "drop_or_redesign_targets": low_success,
            "retain_or_retest_targets": underpowered,
            "gpu_spend_gate": gpu_spend_gate,
            "next_manifest_policy": (
                "Require an explicit revised target manifest before another W2 panel run; "
                "keep evidence target-wise and do not pool across incompatible target/protocol states."
            ),
        },
        "next_action": (
            "replace or redesign low-success W2 targets before spending more panel GPU"
            if low_success else
            "inspect target-specific cutoff transfer and scale only targets with plausible success"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    def _fmt_float(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.3f}"

    cutoff = rep.get("protocol_cutoff") or {}
    lines = [
        "# W2 Panel Redesign Diagnostic",
        "",
        f"Panel status: `{rep.get('panel_status')}`",
        f"Targets: {rep.get('n_targets')}  Records: {rep.get('n_records')}",
        f"Recommendation: `{rep.get('summary', {}).get('recommendation')}`",
        "",
        "## Protocol Cutoff",
        "",
        f"- risk tau: {cutoff.get('risk_tau')}",
        f"- inferred pAE cutoff: {cutoff.get('pae_cutoff')}",
        f"- source: {cutoff.get('source')}",
        "",
        "## Targets",
        "",
        "| target | classification | n | success | success rate | median pAE | cutoff accepts | cutoff false accepts | cutoff FAR |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rep.get("targets", []):
        far = row.get("protocol_cutoff_false_accept_rate")
        far_text = "n/a" if far is None else f"{far:.3f}"
        lines.append(
            f"| {row['complex_target_id']} | {row['classification']} | "
            f"{row['n_records']} | {row['success']} | {_fmt_float(row['success_rate'])} | "
            f"{_fmt_float(row.get('median_pae_interaction'))} | "
            f"{row['protocol_cutoff_accepts']} | {row['protocol_cutoff_false_accepts']} | {far_text} |"
        )
    lines.extend([
        "",
        "## Redesign Gate",
        "",
        rep.get("summary", {}).get("gpu_spend_gate", ""),
        "",
        "## Target Actions",
        "",
        "| target | recommended action |",
        "|---|---|",
    ])
    for row in rep.get("targets", []):
        lines.append(f"| {row['complex_target_id']} | {row.get('recommended_action', 'n/a')} |")
    lines.extend([
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="diagnose negative W2 panel evidence for redesign")
    ap.add_argument("--panel-report", required=True)
    ap.add_argument("--protocol-summary", default=None)
    ap.add_argument("--min-success-rate", type=float, default=0.25)
    ap.add_argument("--min-protocol-accepts", type=int, default=10)
    ap.add_argument("--max-protocol-false-accept-rate", type=float, default=0.2)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args(argv)

    rep = run_diagnostic(
        args.panel_report,
        args.protocol_summary,
        min_success_rate=args.min_success_rate,
        min_protocol_accepts=args.min_protocol_accepts,
        max_protocol_false_accept_rate=args.max_protocol_false_accept_rate,
        threshold=args.threshold,
    )
    print(
        f"# complex panel redesign diagnostic  recommendation={rep['summary']['recommendation']} "
        f"targets={rep['n_targets']} records={rep['n_records']}"
    )
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.out_md:
        with open(args.out_md, "w") as fh:
            fh.write(render_markdown(rep))
        print(f"wrote {args.out_md}")
    return rep


if __name__ == "__main__":
    main()
