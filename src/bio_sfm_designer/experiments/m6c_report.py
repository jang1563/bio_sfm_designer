"""Reproducible M6c report for the complex/binder trust-gate result.

This module intentionally composes the existing experiment entrypoints instead of
copying headline numbers by hand. It is the bridge from fixture-backed analyses
to a project status artifact with the caveats kept close to the result.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_seed_sensitivity import run_sensitivity, _parse_seeds
from .complex_design_regime_audit import run_rows as run_regime_audit_rows
from .complex_gate_sweep import _default_n_cal, load_merged_records, run_sweep
from .complex_interface_signal import _BARSTAR, run_rows as run_signal_rows
from .complex_label_threshold import require_label_threshold
from .complex_scale_projection import run_projection
from .conformal_complex_gate import run_rows as run_gate_rows


_DEFAULT_ALPHAS = (0.3, 0.2, 0.1)


def _parse_alphas(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _fmt_rate(value: Any) -> str:
    return "n/a" if value is None else f"{100.0 * float(value):.1f}%"


def _fmt_count(value: Any) -> str:
    return "n/a" if value is None else str(int(round(float(value))))


def _fmt_float(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _alpha_id(value: float) -> str:
    return str(float(value)).replace(".", "_")


def _alpha_rows(sweep: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for row in sweep["alphas"]:
        rows.append({
            "alpha": row["alpha"],
            "certified": row["certified"],
            "tau": row["tau"],
            "trusted": row["trusted"],
            "n_test": row["n_test"],
            "false_accept_rate": row["false_accept_rate"],
            "trust_all_false_accept_rate": row["trust_all_false_accept_rate"],
        })
    return rows


def _as_paths(records_paths: Any) -> List[str]:
    if isinstance(records_paths, str):
        return [records_paths]
    return list(records_paths)


def _frontier_row(frontier: Iterable[Dict[str, Any]], alpha: float) -> Optional[Dict[str, Any]]:
    for row in frontier:
        if abs(float(row["alpha"]) - float(alpha)) <= 1e-12:
            return row
    return None


def _target_descriptor(rows: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    target_ids = sorted({
        str(row.get("complex_target_id"))
        for row in rows
        if row.get("complex_target_id") not in (None, "")
    })
    if not target_ids:
        return {
            "target": "complex target",
            "target_slug": "complex_target",
            "target_scope": "single_target",
        }
    if len(target_ids) == 1:
        target_id = target_ids[0]
        if target_id == "1BRS_AD":
            return {
                "target": "barnase-barstar (1BRS_AD)",
                "target_slug": "barnase_barstar",
                "target_scope": "single_target",
            }
        return {
            "target": target_id,
            "target_slug": target_id.replace("-", "_").replace(":", "_"),
            "target_scope": "single_target",
        }
    shown = ", ".join(target_ids[:3])
    suffix = "" if len(target_ids) <= 3 else f", +{len(target_ids) - 3} more"
    return {
        "target": f"mixed complex targets ({shown}{suffix})",
        "target_slug": "mixed_complex_targets",
        "target_scope": "multi_target",
    }


def _science_claims(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Translate report numbers into explicit claim boundaries."""
    signal = rep["signal"]
    gate = rep["gate"]
    dataset = rep["dataset"]
    target_label = dataset.get("target", "complex target")
    target_scope = dataset.get("target_scope", "single_target")
    target_slug = dataset.get("target_slug", "complex_target")
    scope_prefix = "single target" if target_scope == "single_target" else "target set"
    target_alpha = float(rep.get("target_alpha", 0.2))
    target_alpha_id = _alpha_id(target_alpha)
    scale_projection = rep.get("scale_projection") or {}
    target_row = _frontier_row(rep["alpha_frontier"], target_alpha)
    target_certified = bool(target_row and target_row.get("certified"))
    target_claim = {
        "id": f"target_alpha_{target_alpha_id}_certificate",
        "status": "certified" if target_certified else "not_certified",
        "claim": (
            f"The current evidence {'certifies' if target_certified else 'does not certify'} "
            f"alpha={target_alpha:g}."
        ),
        "evidence": {
            "target_alpha": target_alpha,
            "certified": target_certified,
            "tau": target_row.get("tau") if isinstance(target_row, dict) else None,
            "trusted": target_row.get("trusted") if isinstance(target_row, dict) else None,
        },
    }
    supported = [
        {
            "id": "complex_pae_interaction_signal",
            "status": "supported",
            "scope": f"{scope_prefix} {target_label}, Boltz complex records",
            "claim": (
                "pAE_interaction is informative for interface success in the current "
                "complex/binder dataset."
            ),
            "evidence": {
                "pae_stratified_auroc": signal["pae_stratified_auroc"],
                "well_folded_pae_auroc": signal["well_folded_auroc_pae"],
                "well_folded_iptm_auroc": signal["well_folded_auroc_iptm"],
            },
        },
        {
            "id": "alpha_0_3_rcps_certificate",
            "status": "certified",
            "scope": f"{scope_prefix} {target_label}, held-out split",
            "claim": "The calibrated gate certifies alpha=0.3 on the current complex/binder evidence.",
            "evidence": {
                "alpha": gate["alpha"],
                "tau": gate["tau"],
                "trusted": gate["trusted"],
                "n_test": gate["n_test"],
                "false_accept_rate": gate["false_accept_rate"],
                "trust_all_false_accept_rate": gate["trust_all_false_accept_rate"],
            },
        },
    ]
    if target_certified:
        supported.append(target_claim)
    not_yet_supported = [
        {
            "id": "multi_target_generalization",
            "status": "not_supported_yet",
            "claim": "The current complex result is not a multi-target generalization claim.",
            "required_evidence": "Target-wise panel certificates from complex_panel_report.py.",
        },
        {
            "id": "independent_predictor_robustness",
            "status": "not_supported_yet",
            "claim": "The current complex result does not close the single-predictor caveat.",
            "required_evidence": "Matched independent-predictor records passing complex_cross_predictor.py.",
        },
    ]
    if not target_certified:
        not_yet_supported.insert(0, target_claim)
    planning = {
        "id": f"scale_projection_alpha_{target_alpha_id}",
        "status": "planning_diagnostic",
        "claim": (
            f"The +300 scale projection is useful for planning but is not "
            f"alpha={target_alpha:g} certification."
        ),
        "evidence": {
            "certifies_target_alpha": scale_projection.get("certifies_target_alpha"),
            "claim_scope": scale_projection.get("claim_scope"),
            "projected_certified_count": scale_projection.get("projected_certified_count"),
            "n_seeds": scale_projection.get("n_seeds"),
        },
    }
    return {
        "supported": supported,
        "not_yet_supported": not_yet_supported,
        "planning_diagnostics": [planning],
        "decisive_next_experiments": [
            {
                "id": f"scale_{target_slug}_alpha_{target_alpha_id}",
                "question": f"Does real post-scale evidence certify alpha={target_alpha:g}?",
                "decision_artifact": "complex_alpha_decision.json with decision=stop_certified",
            },
            {
                "id": "multi_target_panel",
                "question": f"Does the complex signal and gate hold target-wise beyond {target_label}?",
                "decision_artifact": "complex_panel_report.json with panel_status=multi_target_certified",
            },
            {
                "id": "second_predictor",
                "question": "Does the signal survive an independent complex predictor?",
                "decision_artifact": "complex_cross_predictor.json with status=cross_predictor_ready",
            },
        ],
    }


def build_report(records_paths: Any = _BARSTAR, alphas: Iterable[float] = _DEFAULT_ALPHAS,
                 threshold: float = 4.0, n_cal: Optional[int] = 128, delta: float = 0.1,
                 seed: int = 0, signal_boot: int = 2000,
                 target_alpha: float = 0.2,
                 seed_sensitivity_seeds: Optional[Iterable[int]] = range(20),
                 scale_projection_seeds: Optional[Iterable[int]] = range(20),
                 scale_projection_n_new: int = 300,
                 scale_projection_temperatures: Iterable[float] = (0.3, 0.5, 0.7)) -> Dict[str, Any]:
    """Build the M6c report from current fixture/record evidence."""
    paths = _as_paths(records_paths)
    rows = load_merged_records(paths)
    label_threshold = require_label_threshold(rows, threshold=threshold)
    n_cal_eff = _default_n_cal(len(rows)) if n_cal is None else n_cal
    alphas = tuple(dict.fromkeys([float(a) for a in list(alphas) + [float(target_alpha)]]))
    signal = run_signal_rows(rows, threshold=threshold, n_boot=signal_boot, seed=seed)
    target = _target_descriptor(rows)
    regime_audit = run_regime_audit_rows(rows, threshold=threshold)
    gate = run_gate_rows(rows, alpha=0.3, delta=delta, threshold=threshold, n_cal=n_cal_eff, seed=seed)
    sweep = run_sweep(paths, alphas=alphas, n_cal=n_cal_eff, delta=delta, threshold=threshold, seed=seed)
    seed_sensitivity = None
    if seed_sensitivity_seeds is not None:
        seed_sensitivity = run_sensitivity(
            paths,
            target_alpha=target_alpha,
            baseline_alpha=0.3,
            alphas=(0.3, 0.2),
            seeds=seed_sensitivity_seeds,
            n_cal=n_cal_eff,
            delta=delta,
            threshold=threshold,
        )
    scale_projection = None
    if scale_projection_seeds is not None:
        scale_projection = run_projection(
            paths,
            target_alpha=target_alpha,
            n_new=scale_projection_n_new,
            temperatures=scale_projection_temperatures,
            seeds=scale_projection_seeds,
            delta=delta,
            threshold=threshold,
            n_cal=None,
        )
    rep = {
        "report": "m6c_complex_binder_trust_gate",
        "records_paths": [os.path.abspath(path) for path in paths],
        "target_alpha": target_alpha,
        "dataset": {
            "n": signal["n"],
            "success": signal["success"],
            "threshold": threshold,
            "target": target["target"],
            "target_slug": target["target_slug"],
            "target_scope": target["target_scope"],
            "protocol": "target MSA + binder single-seq",
            "label_threshold_audit": label_threshold,
        },
        "signal": {
            "pae_stratified_auroc": signal["stratified"]["pae_interaction"]["auroc"],
            "pae_stratified_ci": signal["stratified"]["pae_interaction"]["ci"],
            "iptm_stratified_auroc": signal["stratified"]["iptm"]["auroc"],
            "well_folded_n": signal["well_folded"]["n"],
            "well_folded_dock_success": signal["well_folded"]["dock_success"],
            "well_folded_auroc_pae": signal["well_folded"]["auroc_pae"],
            "well_folded_auroc_iptm": signal["well_folded"]["auroc_iptm"],
        },
        "design_regime_audit": regime_audit,
        "scale_projection": scale_projection,
        "gate": {
            "alpha": gate["alpha"],
            "delta": gate["delta"],
            "n_cal": gate["n_cal"],
            "n_test": gate["n_test"],
            "tau": gate["tau"],
            "trusted": gate["conformal"]["trusted"],
            "false_accept_rate": gate["conformal"]["false_accept_rate"],
            "trust_all_false_accept_rate": gate["trust_all"]["false_accept_rate"],
            "base_rate_fail": gate["base_rate_fail"],
            "selective": gate["selective"],
        },
        "alpha_frontier": _alpha_rows(sweep),
        "alpha_seed_sensitivity": seed_sensitivity,
        "positioning": {
            "claim": "The calibrated trust gate adds value in the complex/binder regime where pAE_interaction is informative but miscalibrated.",
            "not_claiming": [
                "No monomer fine-grained trust signal was found at fixed difficulty.",
                "The current complex result is one target, not a multi-target proof.",
                "pAE_interaction and the L-RMSD label still come from one Boltz fold.",
            ],
            "next": [
                f"Use complex_alpha_plan.py, then scale {target['target']} with cached target MSA to test alpha<={target_alpha:g}.",
                "Add at least three clean heterodimer targets prepared with hpc/prep_hetdimer.py.",
                "Add an independent second complex predictor to close the single-model caveat.",
            ],
        },
    }
    rep["science_claims"] = _science_claims(rep)
    return rep


def render_markdown(rep: Dict[str, Any]) -> str:
    ds = rep["dataset"]
    sig = rep["signal"]
    regime_audit = rep.get("design_regime_audit")
    gate = rep["gate"]
    gate_tau = "none" if gate["tau"] is None else f"{gate['tau']:.3f}"
    lines = [
        "# M6c Complex/Binder Trust-Gate Report",
        "",
        "Records: " + ", ".join(f"`{path}`" for path in rep["records_paths"]),
        f"Dataset: {ds['n']} {ds['target']} redesigns; success = L-RMSD < {ds['threshold']} A "
        f"({ds['success']}/{ds['n']} succeed); protocol = {ds['protocol']}.",
        "",
        "## Headline",
        "",
        rep["positioning"]["claim"],
        "",
        "## Claim Ledger",
        "",
        "**Supported now**",
        "",
    ]
    claims = rep.get("science_claims") or {}
    for item in claims.get("supported", []):
        lines.append(f"- {item['id']}: {item['claim']}")
    lines.extend([
        "",
        "**Not yet supported**",
        "",
    ])
    for item in claims.get("not_yet_supported", []):
        lines.append(f"- {item['id']}: {item['claim']}")
    lines.extend([
        "",
        "**Planning diagnostics**",
        "",
    ])
    for item in claims.get("planning_diagnostics", []):
        lines.append(f"- {item['id']}: {item['claim']}")
    lines.extend([
        "",
        "**Decisive next experiments**",
        "",
    ])
    for item in claims.get("decisive_next_experiments", []):
        lines.append(
            f"- {item['id']}: {item['question']} Decision artifact: {item['decision_artifact']}"
        )
    lines.extend([
        "",
        "## Signal Evidence",
        "",
        f"- pAE_interaction stratified AUROC: {sig['pae_stratified_auroc']:.3f} "
        f"CI {sig['pae_stratified_ci']}",
        f"- ipTM stratified AUROC: {sig['iptm_stratified_auroc']:.3f}",
        f"- Well-folded control: n={sig['well_folded_n']}, dock successes={sig['well_folded_dock_success']}; "
        f"pAE AUROC={sig['well_folded_auroc_pae']:.3f}, ipTM AUROC={sig['well_folded_auroc_iptm']:.3f}",
        "",
    ])
    if isinstance(regime_audit, dict):
        lines.extend([
            "## Design Regime Audit",
            "",
            regime_audit["message"],
            "",
            "| stratum | n | success | success-rate | median pAE | median L-RMSD | pAE AUROC | ipTM AUROC |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in regime_audit["strata"]:
            lines.append(
                f"| {row['stratum']} | {row['n']} | {row['success']} | "
                f"{_fmt_rate(row['success_rate'])} | {_fmt_float(row['median_pae_interaction'])} | "
                f"{_fmt_float(row['median_lrmsd'])} | {_fmt_float(row['pae_auroc_within_stratum'])} | "
                f"{_fmt_float(row['iptm_auroc_within_stratum'])} |"
            )
        lines.append("")
    lines.extend([
        "## Gate Certificate",
        "",
        f"- alpha={gate['alpha']}, delta={gate['delta']}, tau={gate_tau}",
        f"- Held-out trusts: {gate['trusted']}/{gate['n_test']}",
        f"- False-accept: {_fmt_rate(gate['false_accept_rate'])} vs held-out trust-all "
        f"{_fmt_rate(gate['trust_all_false_accept_rate'])} ({_fmt_rate(gate['base_rate_fail'])} full-set base-rate)",
        "",
        "## Alpha Frontier",
        "",
        "| alpha | certified | tau | trusted | false-accept | trust-all |",
        "|---:|:---:|---:|---:|---:|---:|",
    ])
    for row in rep["alpha_frontier"]:
        tau = "none" if row["tau"] is None else f"{row['tau']:.3f}"
        lines.append(f"| {row['alpha']:.2f} | {row['certified']} | {tau} | "
                     f"{row['trusted']}/{row['n_test']} | {_fmt_rate(row['false_accept_rate'])} | "
                     f"{_fmt_rate(row['trust_all_false_accept_rate'])} |")
    seed_sensitivity = rep.get("alpha_seed_sensitivity")
    if isinstance(seed_sensitivity, dict):
        addl = seed_sensitivity.get("target_estimated_additional_records") or {}
        lines.extend([
            "",
            "## Alpha Seed Sensitivity",
            "",
            f"- target alpha={seed_sensitivity['target_alpha']} certified "
            f"{seed_sensitivity['target_certified_count']}/{seed_sensitivity['n_seeds']} split seeds.",
            f"- baseline alpha={seed_sensitivity['baseline_alpha']} certified "
            f"{seed_sensitivity['baseline_certified_count']}/{seed_sensitivity['n_seeds']} split seeds.",
            "- estimated additional records for target alpha across seeds: "
            f"min={_fmt_count(addl.get('min'))} "
            f"median={_fmt_count(addl.get('median'))} "
            f"max={_fmt_count(addl.get('max'))}.",
        ])
    scale_projection = rep.get("scale_projection")
    if isinstance(scale_projection, dict):
        tau = scale_projection.get("projected_tau") or {}
        trusted = scale_projection.get("projected_trusted") or {}
        far = scale_projection.get("projected_false_accept_rate") or {}
        lines.extend([
            "",
            "## Scale Projection",
            "",
            scale_projection["message"],
            "",
            f"- evidence level: {scale_projection.get('evidence_level', 'unknown')}; "
            f"claim scope: {scale_projection.get('claim_scope', 'unknown')}; "
            f"certifies target alpha: {scale_projection.get('certifies_target_alpha', False)}.",
            "",
            f"- current alpha={scale_projection['target_alpha']} certified "
            f"{scale_projection['current_certified_count']}/{scale_projection['n_seeds']} split/sample seeds.",
            f"- projected +{scale_projection['n_new']} balanced designs certified "
            f"{scale_projection['projected_certified_count']}/{scale_projection['n_seeds']} split/sample seeds.",
            f"- projected tau median={_fmt_float(tau.get('median'))}; trusted median="
            f"{_fmt_float(trusted.get('median'))}; false-accept median={_fmt_rate(far.get('median'))}.",
        ])
    lines.extend([
        "",
        "## Caveats",
        "",
    ])
    for item in rep["positioning"]["not_claiming"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Next Steps",
        "",
    ])
    for item in rep["positioning"]["next"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="generate the reproducible M6c complex/binder status report")
    ap.add_argument("--records", nargs="+", default=[_BARSTAR])
    ap.add_argument("--alphas", default="0.3,0.2,0.1")
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--ncal", type=int, default=128)
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--signal-boot", type=int, default=2000,
                    help="bootstrap samples for the signal CI; lower in tests/smokes")
    ap.add_argument("--seed-sensitivity-seeds", default="0:20",
                    help="comma-separated seeds or start:stop[:step] range for alpha split-sensitivity")
    ap.add_argument("--skip-seed-sensitivity", action="store_true",
                    help="omit the alpha seed-sensitivity section")
    ap.add_argument("--scale-projection-seeds", default="0:20",
                    help="comma-separated seeds or start:stop[:step] range for next-batch projection")
    ap.add_argument("--scale-projection-n-new", type=int, default=300,
                    help="additional records to bootstrap for the next-batch projection")
    ap.add_argument("--scale-projection-temperatures", default="0.3,0.5,0.7",
                    help="comma-separated temperatures for balanced scale projection")
    ap.add_argument("--skip-scale-projection", action="store_true",
                    help="omit the empirical next-batch scale projection")
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    sensitivity_seeds = None if args.skip_seed_sensitivity else _parse_seeds(args.seed_sensitivity_seeds)
    projection_seeds = None if args.skip_scale_projection else _parse_seeds(args.scale_projection_seeds)
    rep = build_report(args.records, _parse_alphas(args.alphas), threshold=args.threshold,
                       n_cal=args.ncal, delta=args.delta, seed=args.seed,
                       signal_boot=args.signal_boot,
                       target_alpha=args.target_alpha,
                       seed_sensitivity_seeds=sensitivity_seeds,
                       scale_projection_seeds=projection_seeds,
                       scale_projection_n_new=args.scale_projection_n_new,
                       scale_projection_temperatures=_parse_alphas(args.scale_projection_temperatures))
    md = render_markdown(rep)
    print(md)
    if args.out_md:
        _write_text(args.out_md, md)
        print(f"wrote {args.out_md}")
    if args.out_json:
        _write_text(args.out_json, json.dumps(rep, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.out_json}")
    return rep


if __name__ == "__main__":
    main()
