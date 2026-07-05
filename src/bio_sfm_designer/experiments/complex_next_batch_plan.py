"""Render Cayuga commands for the next M6c alpha-tightening scale batch.

`complex_alpha_decision.py` decides whether more records are justified and, if
so, emits a `next_batch` block. This helper turns that block plus a target
manifest entry into concrete, temp-specific sbatch commands with distinct JSONL
paths, avoiding accidental output overwrites across ProteinMPNN temperatures.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from typing import Any, Dict, Iterable, List, Optional

from .complex_target_manifest import validate_manifest


class TargetPreflightError(ValueError):
    """Selected-target manifest preflight failed before Cayuga submission."""

    def __init__(self, target_id: str, preflight_report: Dict[str, Any]) -> None:
        self.target_id = target_id
        self.preflight_report = preflight_report
        kinds = ", ".join(
            f"{k}={v}"
            for k, v in sorted(preflight_report.get("failures_by_kind", {}).items())
        )
        super().__init__(f"target manifest preflight failed for {target_id}: {kinds}")


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _find_target(manifest: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise ValueError("manifest must contain a targets list")
    for target in targets:
        if isinstance(target, dict) and str(target.get("id")) == str(target_id):
            return target
    raise ValueError(f"target id not found in manifest: {target_id}")


def _require_str(obj: Dict[str, Any], field: str, *, label: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} missing required field {field}")
    return value


def _temp_tag(temp: float) -> str:
    scaled = int(round(float(temp) * 100))
    if abs(float(temp) * 100 - scaled) < 1e-8:
        return f"t{scaled:03d}"
    text = str(temp).replace("-", "m").replace(".", "p")
    return f"t{text}"


def _env_assign(**values: str) -> str:
    return " ".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def _safe_token(text: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("._")
    return token or "batch"


def _records_arg(paths: Iterable[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def _target_setting(manifest: Dict[str, Any], target: Dict[str, Any],
                    field: str, default: Any) -> str:
    defaults = manifest.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    return str(target.get(field, defaults.get(field, default)))


def _require_strict_decision_qc(decision: Dict[str, Any]) -> None:
    qc = decision.get("qc")
    if not isinstance(qc, dict):
        raise ValueError(
            "decision JSON is missing qc; rerun complex_alpha_decision or "
            "complex_posthoc_bundle with --require-complex-target-id --require-provenance --require-chain-ids"
        )
    if qc.get("ok") is not True:
        raise ValueError("decision JSON QC did not pass; fix records before emitting a scale batch")
    if (qc.get("require_complex_target_id") is not True
            or qc.get("require_provenance") is not True
            or qc.get("require_chain_ids") is not True):
        raise ValueError(
            "decision JSON was not produced with strict QC; rerun with "
            "--require-complex-target-id --require-provenance --require-chain-ids"
        )


def build_next_batch_plan(*, manifest_path: str, decision_path: str, target_id: str,
                          previous_records: Iterable[str] = (),
                          posthoc_out_dir: str = "results/m6c_posthoc",
                          out_prefix: Optional[str] = None,
                          require_files: bool = False,
                          min_contacts: int = 1,
                          strict_qc: bool = True) -> Dict[str, Any]:
    manifest = _load_json(manifest_path)
    decision = _load_json(decision_path)
    target = _find_target(manifest, target_id)
    preflight = None
    if require_files:
        preflight = validate_manifest(
            manifest_path,
            require_files=True,
            min_targets=1,
            min_contacts=min_contacts,
            target_ids=[target_id],
        )
        if not preflight["ok"]:
            raise TargetPreflightError(target_id, preflight)
    next_batch = decision.get("next_batch")
    if not isinstance(next_batch, dict):
        raise ValueError("decision JSON is missing next_batch")

    action = str(next_batch.get("action"))
    target_alpha = decision.get("target_alpha", next_batch.get("target_alpha"))
    if action != "run_scale_batch":
        plan = {
            "ok": True,
            "action": action,
            "target_id": target_id,
            "target_alpha": target_alpha,
            "commands": [],
            "records": list(previous_records),
            "preflight": preflight,
            "strict_qc": strict_qc,
            "message": f"no scale batch emitted for action={action}",
        }
        plan["plan_text"] = render_plan_text(plan)
        return plan
    if strict_qc:
        _require_strict_decision_qc(decision)

    prepared_pdb = _require_str(target, "prepared_pdb", label="target")
    target_chain = _require_str(target, "target_chain", label="target")
    binder_chain = _require_str(target, "binder_chain", label="target")
    target_msa = _require_str(target, "target_msa", label="target")
    seed = _target_setting(manifest, target, "seed", 37)
    objective = _target_setting(manifest, target, "objective", "binder")
    prefix = out_prefix or target.get("out_prefix") or os.path.join("hpc_outputs", "m6c_targets", str(target_id))
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("out_prefix must be a non-empty string")
    batch_namespace = _safe_token(os.path.basename(os.path.normpath(prefix)) or target_id)

    temperatures = next_batch.get("temperatures")
    if not isinstance(temperatures, list) or not temperatures:
        raise ValueError("next_batch.temperatures must be a non-empty list")
    num_seq = next_batch.get("num_seq_per_temperature")
    if not isinstance(num_seq, int) or num_seq <= 0:
        raise ValueError("next_batch.num_seq_per_temperature must be a positive integer")

    commands: List[Dict[str, Any]] = []
    records: List[str] = []
    candidates: List[str] = []
    for temp in temperatures:
        temp_value = float(temp)
        tag = _temp_tag(temp_value)
        gen_var = f"GEN_{tag.upper()}"
        cand = os.path.join(prefix, f"candidates_proteinmpnn_complex_{tag}.jsonl")
        rec = os.path.join(prefix, f"records_boltz_complex_{tag}.jsonl")
        id_prefix = f"{objective}-mpnnX-{target_id}-{batch_namespace}-{tag}"
        candidates.append(cand)
        records.append(rec)
        gen_cmd = (
            f"{gen_var}=$("
            + _env_assign(
                PDB=prepared_pdb,
                TARGET_CHAIN=target_chain,
                DESIGN_CHAIN=binder_chain,
                NUM_SEQ=str(num_seq),
                TEMP=str(temp_value),
                SEED=seed,
                OBJECTIVE=objective,
                COMPLEX_ID=str(target_id),
                ID_PREFIX=id_prefix,
                OUT=cand,
            )
            + " sbatch --parsable hpc/run_generate_proteinmpnn_complex.sbatch)"
        )
        pred_cmd = (
            _env_assign(
                CANDIDATES=cand,
                BACKBONE=prepared_pdb,
                TARGET_CHAIN=target_chain,
                BINDER_CHAIN=binder_chain,
                COMPLEX_ID=str(target_id),
                TARGET_MSA=target_msa,
                OUT=rec,
            )
            + f" sbatch --dependency=afterok:${{{gen_var}}} "
            + "hpc/run_predict_boltz_complex.sbatch"
        )
        commands.append({
            "temperature": temp_value,
            "tag": tag,
            "generate_job_var": gen_var,
            "candidates": cand,
            "records": rec,
            "seed": seed,
            "objective": objective,
            "id_prefix": id_prefix,
            "complex_target_id": str(target_id),
            "generate_command": gen_cmd,
            "predict_command": pred_cmd,
        })

    all_records = list(previous_records) + records
    posthoc_command = (
        "python -m bio_sfm_designer.experiments.complex_posthoc_bundle "
        f"--records {_records_arg(all_records)} "
        f"--target-alpha {target_alpha} "
        f"--out-dir {shlex.quote(posthoc_out_dir)}"
    )
    if strict_qc:
        posthoc_command += " --require-complex-target-id --require-provenance --require-chain-ids"
    plan = {
        "ok": True,
        "action": action,
        "target_id": target_id,
        "target_alpha": target_alpha,
        "manifest": os.path.abspath(manifest_path),
        "manifest_arg": manifest_path,
        "decision": os.path.abspath(decision_path),
        "require_files": require_files,
        "min_contacts": min_contacts,
        "out_prefix": prefix,
        "batch_namespace": batch_namespace,
        "seed": seed,
        "objective": objective,
        "num_seq_per_temperature": num_seq,
        "recommended_total_candidates": next_batch.get("recommended_total_candidates"),
        "commands": commands,
        "candidates": candidates,
        "records": all_records,
        "new_records": records,
        "posthoc_out_dir": posthoc_out_dir,
        "posthoc_command": posthoc_command,
        "preflight": preflight,
        "strict_qc": strict_qc,
    }
    plan["plan_text"] = render_plan_text(plan)
    return plan


def render_plan_text(plan: Dict[str, Any]) -> str:
    lines = [
        "# M6c next alpha-tightening batch plan",
        "# Run this from the staged repo root on Cayuga unless noted otherwise.",
        "set -euo pipefail",
        "",
    ]
    if plan.get("action") != "run_scale_batch":
        lines.extend([
            f"# action={plan.get('action')}; no scale batch emitted.",
            f"# {plan.get('message', '')}",
            "",
        ])
        return "\n".join(lines)

    lines.extend([
        f"# target={plan['target_id']} target_alpha={plan['target_alpha']}",
        f"# NUM_SEQ={plan['num_seq_per_temperature']} per temperature; "
        f"recommended_total={plan.get('recommended_total_candidates')}",
    ])
    if plan.get("strict_qc"):
        lines.append("# strict QC: posthoc rerun requires complex_target_id, chain ids, and predictor/source provenance")
    if plan.get("diagnostic_only"):
        lines.append("# diagnostic only: saved without --require-files; do not use for production Cayuga submission or claims")
    preflight = plan.get("preflight")
    if isinstance(preflight, dict):
        lines.append(f"# selected-target preflight ok={preflight.get('ok')} require_files={preflight.get('require_files')}")
    if plan.get("require_files"):
        lines.extend([
            "# Re-run selected-target file/report preflight at execution time before any sbatch.",
            "python -m bio_sfm_designer.experiments.complex_target_manifest "
            f"--manifest {shlex.quote(str(plan.get('manifest_arg', plan['manifest'])))} "
            f"--target-id {shlex.quote(str(plan['target_id']))} "
            "--require-files "
            f"--min-contacts {shlex.quote(str(plan.get('min_contacts', 1)))}",
        ])
    lines.extend([
        f"mkdir -p {shlex.quote(plan['out_prefix'])}",
        "",
        "# Submit one ProteinMPNN job per temperature, then one dependent Boltz job per output.",
    ])
    for cmd in plan["commands"]:
        lines.extend([
            f"# temp={cmd['temperature']} tag={cmd['tag']}",
            cmd["generate_command"],
            cmd["predict_command"],
            "",
        ])
    lines.extend([
        "# After the jobs finish and records are synced locally, rerun the synchronized posthoc bundle:",
        "# If this plan was written with --out, first validate synced records with:",
        "# python -m bio_sfm_designer.experiments.complex_scale_completion --plan <next_batch_plan.json>",
        "# " + plan["posthoc_command"],
        "",
    ])
    return "\n".join(lines)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="emit temp-specific Cayuga commands for the next M6c scale batch")
    ap.add_argument("--manifest", required=True, help="target manifest JSON")
    ap.add_argument("--decision", required=True, help="complex_alpha_decision.json")
    ap.add_argument("--target-id", required=True)
    ap.add_argument("--previous-records", nargs="*", default=[],
                    help="records already included in the alpha decision, for the follow-up posthoc command")
    ap.add_argument("--posthoc-out-dir", default="results/m6c_posthoc")
    ap.add_argument("--out-prefix", default=None,
                    help="override target out_prefix for generated candidates/records")
    ap.add_argument("--require-files", action="store_true",
                    help="run selected-target manifest preflight before emitting commands")
    ap.add_argument("--allow-unchecked-files", action="store_true",
                    help="diagnostic escape hatch: allow saving a runnable plan without --require-files")
    ap.add_argument("--min-contacts", type=int, default=1,
                    help="minimum CA contacts in prep_report when --require-files checks it")
    ap.add_argument("--no-strict-qc", action="store_true",
                    help="legacy escape hatch: skip strict decision-QC check and omit strict posthoc flags")
    ap.add_argument("--out", default=None, help="optional JSON plan path")
    ap.add_argument("--emit-plan", default=None, help="optional shell plan path")
    args = ap.parse_args(argv)

    try:
        plan = build_next_batch_plan(
            manifest_path=args.manifest,
            decision_path=args.decision,
            target_id=args.target_id,
            previous_records=args.previous_records,
            posthoc_out_dir=args.posthoc_out_dir,
            out_prefix=args.out_prefix,
            require_files=args.require_files,
            min_contacts=args.min_contacts,
            strict_qc=not args.no_strict_qc,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"complex next batch plan failed: {exc}", file=sys.stderr)
        sys.exit(2)

    saving_plan = bool(args.out or args.emit_plan)
    if (saving_plan and plan.get("action") == "run_scale_batch"
            and not args.require_files and not args.allow_unchecked_files):
        print(
            "saving a run_scale_batch plan requires --require-files; "
            "use --allow-unchecked-files only for legacy diagnostics",
            file=sys.stderr,
        )
        sys.exit(2)
    if saving_plan and plan.get("action") == "run_scale_batch" and args.allow_unchecked_files:
        plan["diagnostic_only"] = True
        plan["unchecked_files_allowed"] = True
        plan["diagnostic_reason"] = "saved without --require-files via --allow-unchecked-files"
        plan["plan_text"] = render_plan_text(plan)

    print(plan["plan_text"])
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({k: v for k, v in plan.items() if k != "plan_text"}, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.emit_plan:
        with open(args.emit_plan, "w") as fh:
            fh.write(plan["plan_text"])
        print(f"wrote {args.emit_plan}")
    return plan


if __name__ == "__main__":
    main()
