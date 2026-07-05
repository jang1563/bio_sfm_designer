"""One-command post-HPC M6c analysis bundle.

Runs the same records list through:
  1. complex_records_qc
  2. complex_gate_sweep
  3. complex_alpha_plan
  4. complex_alpha_decision
  5. m6c_report

This keeps the post-scale evidence set synchronized across all artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional

from .complex_alpha_decision import run_decision
from .complex_alpha_plan import run_plan
from .complex_gate_sweep import run_sweep
from .complex_project_status import render_text as render_status_text
from .complex_project_status import run_status
from .complex_records_qc import run_qc
from .conformal_complex_gate import _DEFAULT_FIXTURE
from .complex_alpha_seed_sensitivity import _parse_seeds
from .m6c_report import build_report, render_markdown

_DEFAULT_ALPHAS = (0.3, 0.2, 0.1)


def _parse_alphas(text: str) -> List[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _claim_ids(claims: Dict[str, Any], section: str) -> List[str]:
    items = claims.get(section)
    if not isinstance(items, list):
        return []
    return [item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def run_bundle(records: Iterable[str], out_dir: str = "results/m6c_posthoc",
               alphas: Iterable[float] = _DEFAULT_ALPHAS, *, target_alpha: float = 0.2,
               n_cal: Optional[int] = None, delta: float = 0.1, threshold: float = 4.0,
               seed: int = 0, signal_boot: int = 2000,
               seed_sensitivity_seeds: Optional[Iterable[int]] = range(20),
               scale_projection_seeds: Optional[Iterable[int]] = range(20),
               scale_projection_n_new: int = 300,
               scale_projection_temperatures: Iterable[float] = (0.3, 0.5, 0.7),
               require_complex_target_id: bool = False,
               require_provenance: bool = False,
               require_chain_ids: bool = False) -> Dict[str, Any]:
    records = list(records)
    alphas = tuple(float(a) for a in alphas)
    os.makedirs(out_dir, exist_ok=True)

    qc = run_qc(records, require_complex_target_id=require_complex_target_id,
                require_provenance=require_provenance,
                require_chain_ids=require_chain_ids)
    paths = {
        "qc": os.path.join(out_dir, "complex_records_qc.json"),
        "sweep": os.path.join(out_dir, "complex_gate_sweep.json"),
        "plan": os.path.join(out_dir, "complex_alpha_plan.json"),
        "decision": os.path.join(out_dir, "complex_alpha_decision.json"),
        "seed_sensitivity": os.path.join(out_dir, "complex_alpha_seed_sensitivity.json"),
        "design_regime_audit": os.path.join(out_dir, "complex_design_regime_audit.json"),
        "scale_projection": os.path.join(out_dir, "complex_scale_projection.json"),
        "report_json": os.path.join(out_dir, "m6c_report.json"),
        "report_md": os.path.join(out_dir, "m6c_report.md"),
        "manifest": os.path.join(out_dir, "manifest.json"),
        "project_status_json": os.path.join(out_dir, "project_status.json"),
        "project_status_txt": os.path.join(out_dir, "project_status.txt"),
    }
    _write_json(paths["qc"], qc)
    decision = run_decision(records, target_alpha=target_alpha, alphas=alphas, n_cal=n_cal,
                            delta=delta, threshold=threshold, seed=seed,
                            require_complex_target_id=require_complex_target_id,
                            require_provenance=require_provenance,
                            require_chain_ids=require_chain_ids)
    _write_json(paths["decision"], decision)
    if not qc["ok"] or not decision.get("ok", True):
        status = run_status(decision_path=paths["decision"], target_alpha=target_alpha)
        _write_json(paths["project_status_json"], status)
        _write_text(paths["project_status_txt"], render_status_text(status))
        return {
            "ok": False,
            "records": records,
            "out_dir": os.path.abspath(out_dir),
            "paths": paths,
            "qc": qc,
            "decision": decision,
            "project_status": status,
        }

    sweep = run_sweep(records, alphas=alphas, n_cal=n_cal, delta=delta,
                      threshold=threshold, seed=seed)
    plan = run_plan(records, alphas=alphas, n_cal=n_cal, delta=delta,
                    threshold=threshold, seed=seed)
    report = build_report(records, alphas=alphas, threshold=threshold, n_cal=n_cal,
                          delta=delta, seed=seed, signal_boot=signal_boot,
                          target_alpha=target_alpha,
                          seed_sensitivity_seeds=seed_sensitivity_seeds,
                          scale_projection_seeds=scale_projection_seeds,
                          scale_projection_n_new=scale_projection_n_new,
                          scale_projection_temperatures=scale_projection_temperatures)
    report_md = render_markdown(report)
    _write_json(paths["sweep"], sweep)
    _write_json(paths["plan"], plan)
    if isinstance(report.get("alpha_seed_sensitivity"), dict):
        _write_json(paths["seed_sensitivity"], report["alpha_seed_sensitivity"])
    if isinstance(report.get("design_regime_audit"), dict):
        _write_json(paths["design_regime_audit"], report["design_regime_audit"])
    if isinstance(report.get("scale_projection"), dict):
        _write_json(paths["scale_projection"], report["scale_projection"])
    _write_json(paths["report_json"], report)
    _write_text(paths["report_md"], report_md)
    seed_sensitivity = report.get("alpha_seed_sensitivity") or {}
    regime_audit = report.get("design_regime_audit") or {}
    scale_projection = report.get("scale_projection") or {}
    science_claims = report.get("science_claims") or {}
    manifest = {
        "ok": True,
        "records": [os.path.abspath(path) for path in records],
        "out_dir": os.path.abspath(out_dir),
        "alphas": list(alphas),
        "target_alpha": target_alpha,
        "n_cal": sweep["n_cal"],
        "delta": delta,
        "threshold": threshold,
        "seed": seed,
        "require_complex_target_id": require_complex_target_id,
        "require_provenance": require_provenance,
        "require_chain_ids": require_chain_ids,
        "paths": {key: os.path.abspath(path) for key, path in paths.items()},
        "summary": {
            "n_records": sweep["n_records"],
            "qc_failures": qc["n_failures"],
            "label_threshold_audit": decision.get("label_threshold_audit"),
            "certified_alphas": [row["alpha"] for row in sweep["alphas"] if row["certified"]],
            "alpha_decision": decision["decision"],
            "estimated_additional_records": decision.get("estimated_additional_records"),
            "seed_sensitivity_decision": seed_sensitivity.get("decision"),
            "target_alpha_seed_certified_count": seed_sensitivity.get("target_certified_count"),
            "target_alpha_seed_n": seed_sensitivity.get("n_seeds"),
            "baseline_alpha_seed_certified_count": seed_sensitivity.get("baseline_certified_count"),
            "design_regime_decision": regime_audit.get("decision"),
            "temperature_success_rates": {
                str(row.get("temperature")): row.get("success_rate")
                for row in regime_audit.get("strata", [])
                if row.get("temperature") is not None
            },
            "scale_projection_decision": scale_projection.get("decision"),
            "scale_projection_evidence_level": scale_projection.get("evidence_level"),
            "scale_projection_claim_scope": scale_projection.get("claim_scope"),
            "scale_projection_certifies_target_alpha": scale_projection.get("certifies_target_alpha"),
            "scale_projection_projected_certified_count": scale_projection.get("projected_certified_count"),
            "scale_projection_n_seeds": scale_projection.get("n_seeds"),
            "scale_projection_n_new": scale_projection.get("n_new"),
            "science_claims_supported": _claim_ids(science_claims, "supported"),
            "science_claims_not_yet_supported": _claim_ids(science_claims, "not_yet_supported"),
            "science_claims_planning_diagnostics": _claim_ids(science_claims, "planning_diagnostics"),
            "science_claims_decisive_next": _claim_ids(science_claims, "decisive_next_experiments"),
            "next_batch": decision.get("next_batch"),
        },
    }
    _write_json(paths["manifest"], manifest)
    status = run_status(posthoc_manifest_path=paths["manifest"], target_alpha=target_alpha)
    _write_json(paths["project_status_json"], status)
    _write_text(paths["project_status_txt"], render_status_text(status))
    return {
        "ok": True,
        "records": records,
        "out_dir": os.path.abspath(out_dir),
        "paths": paths,
        "qc": qc,
        "sweep": sweep,
        "plan": plan,
        "decision": decision,
        "report": report,
        "manifest": manifest,
        "project_status": status,
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="run QC+sweep+plan+report for M6c complex records")
    ap.add_argument("--records", nargs="+", default=[_DEFAULT_FIXTURE],
                    help="one or more complex records JSONL files")
    ap.add_argument("--out-dir", default="results/m6c_posthoc")
    ap.add_argument("--alphas", default="0.3,0.2,0.1")
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--ncal", type=int, default=None,
                    help="calibration split size; default=floor(2/3*n)")
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--signal-boot", type=int, default=2000,
                    help="bootstrap samples for the report signal CI; lower in tests/smokes")
    ap.add_argument("--seed-sensitivity-seeds", default="0:20",
                    help="comma-separated seeds or start:stop[:step] range for alpha split-sensitivity")
    ap.add_argument("--skip-seed-sensitivity", action="store_true",
                    help="omit the alpha seed-sensitivity artifact")
    ap.add_argument("--scale-projection-seeds", default="0:20",
                    help="comma-separated seeds or start:stop[:step] range for next-batch projection")
    ap.add_argument("--scale-projection-n-new", type=int, default=300,
                    help="additional records to bootstrap for the next-batch projection")
    ap.add_argument("--scale-projection-temperatures", default="0.3,0.5,0.7",
                    help="comma-separated temperatures for balanced scale projection")
    ap.add_argument("--skip-scale-projection", action="store_true",
                    help="omit the empirical next-batch scale projection")
    ap.add_argument("--require-complex-target-id", action="store_true",
                    help="strict QC: require complex_target_id before alpha claims")
    ap.add_argument("--require-provenance", action="store_true",
                    help="strict QC: require predictor_id, signal_source, and label_source")
    ap.add_argument("--require-chain-ids", action="store_true",
                    help="strict QC: require target_chain and binder_chain")
    args = ap.parse_args(argv)

    sensitivity_seeds = None if args.skip_seed_sensitivity else _parse_seeds(args.seed_sensitivity_seeds)
    projection_seeds = None if args.skip_scale_projection else _parse_seeds(args.scale_projection_seeds)
    rep = run_bundle(args.records, args.out_dir, _parse_alphas(args.alphas),
                     target_alpha=args.target_alpha, n_cal=args.ncal, delta=args.delta,
                     threshold=args.threshold, seed=args.seed, signal_boot=args.signal_boot,
                     seed_sensitivity_seeds=sensitivity_seeds,
                     scale_projection_seeds=projection_seeds,
                     scale_projection_n_new=args.scale_projection_n_new,
                     scale_projection_temperatures=_parse_alphas(args.scale_projection_temperatures),
                     require_complex_target_id=args.require_complex_target_id,
                     require_provenance=args.require_provenance,
                     require_chain_ids=args.require_chain_ids)
    print(f"# complex posthoc bundle  ok={rep['ok']} out={rep['out_dir']}")
    print(f"  qc: {rep['paths']['qc']}")
    if not rep["ok"]:
        print(f"  decision: {rep['paths']['decision']} ({rep['decision']['decision']})")
        print(f"  QC failed with {rep['qc']['n_failures']} failure(s)", file=sys.stderr)
        sys.exit(2)
    print(f"  sweep: {rep['paths']['sweep']}")
    print(f"  plan: {rep['paths']['plan']}")
    print(f"  decision: {rep['paths']['decision']} ({rep['decision']['decision']})")
    if isinstance(rep.get("report", {}).get("alpha_seed_sensitivity"), dict):
        print(f"  seed_sensitivity: {rep['paths']['seed_sensitivity']}")
    if isinstance(rep.get("report", {}).get("design_regime_audit"), dict):
        print(f"  design_regime_audit: {rep['paths']['design_regime_audit']}")
    if isinstance(rep.get("report", {}).get("scale_projection"), dict):
        print(f"  scale_projection: {rep['paths']['scale_projection']}")
    print(f"  report_md: {rep['paths']['report_md']}")
    print(f"  report_json: {rep['paths']['report_json']}")
    print(f"  manifest: {rep['paths']['manifest']}")
    print(f"  project_status: {rep['paths']['project_status_json']}")
    return rep


if __name__ == "__main__":
    main()
