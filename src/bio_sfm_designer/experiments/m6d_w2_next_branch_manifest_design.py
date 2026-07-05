"""Build the W2 next-branch target manifest from admitted local candidates.

This is the step after `m6d_w2_next_branch_candidate_pool.py` reports
`ready_for_revised_manifest=true`. It freezes the target set for strict
preflight, but it does not authorize Cayuga ProteinMPNN/Boltz submission.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bio_sfm_designer.experiments.m6d_w2_next_branch_candidate_pool import (
    DEFAULT_INVENTORY_MANIFESTS,
)


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


def _inventory_targets(paths: Iterable[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, Any]]:
    targets: Dict[str, Dict[str, Any]] = {}
    target_sources: Dict[str, str] = {}
    defaults: Dict[str, Any] = {}
    for path in paths:
        manifest = _load_json(path)
        if not defaults and isinstance(manifest.get("defaults"), dict):
            defaults = dict(manifest["defaults"])
        for target in manifest.get("targets", []):
            if not isinstance(target, dict):
                continue
            target_id = _target_id(target)
            if not target_id:
                continue
            targets[target_id] = dict(target)
            target_sources[target_id] = path
    return targets, target_sources, defaults


def _admitted_targets(candidate_pool: Dict[str, Any]) -> List[str]:
    declared = candidate_pool.get("admitted_targets")
    if isinstance(declared, list):
        return [str(target) for target in declared if isinstance(target, str) and target]
    out = []
    for row in candidate_pool.get("screened_targets", []):
        if isinstance(row, dict) and row.get("admitted_for_next_branch") and row.get("target"):
            out.append(str(row["target"]))
    return out


def build_manifest_design(candidate_pool: Dict[str, Any],
                          inventory_manifests: List[str],
                          *,
                          out_manifest: str,
                          min_targets: Optional[int] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    inventory, target_sources, defaults = _inventory_targets(inventory_manifests)
    admitted = _admitted_targets(candidate_pool)
    min_required = int(
        min_targets
        if min_targets is not None
        else candidate_pool.get("min_non_anchor_candidates_for_revised_manifest", 3)
    )

    failures: List[Dict[str, Any]] = []
    if candidate_pool.get("ready_for_revised_manifest") is not True:
        failures.append({
            "kind": "candidate_pool_not_ready",
            "message": "candidate pool did not authorize revised manifest design",
        })
    if len(admitted) < min_required:
        failures.append({
            "kind": "too_few_admitted_targets",
            "message": f"{len(admitted)} admitted targets < required {min_required}",
        })

    selected_targets = []
    selected_sources = []
    for target_id in admitted:
        target = inventory.get(target_id)
        if target is None:
            failures.append({
                "kind": "missing_inventory_target",
                "target_id": target_id,
                "message": "admitted target is absent from inventory manifests",
            })
            continue
        row = dict(target)
        row["_next_branch_admission"] = {
            "candidate_pool": "results/m6d_w2_next_branch_candidate_pool.json",
            "source_manifest": target_sources.get(target_id),
            "verdict": "admitted_for_next_branch_candidate_pool",
        }
        selected_targets.append(row)
        source = row.get("rcsb_id")
        if isinstance(source, str) and source:
            selected_sources.append(source)

    duplicate_sources = sorted(
        source for source in set(selected_sources)
        if selected_sources.count(source) > 1
    )
    if duplicate_sources:
        failures.append({
            "kind": "duplicate_source_pdb",
            "message": "selected targets are not source-diverse",
            "sources": duplicate_sources,
        })

    manifest = {
        "_note": (
            "M6d W2 expanded next-branch manifest generated from admitted local "
            "candidate-pool targets. This freezes a target set for strict preflight; "
            "it is not a W2 certificate and not a Cayuga submission authorization."
        ),
        "defaults": defaults or {"num_seq": 100, "objective": "binder", "seed": 37, "temp": 0.3},
        "targets": selected_targets,
    }

    ready_for_preflight = not failures and len(selected_targets) >= min_required
    status = (
        "next_branch_manifest_ready_for_strict_preflight"
        if ready_for_preflight
        else "next_branch_manifest_design_blocked"
    )
    report = {
        "artifact": "m6d_w2_next_branch_manifest_design",
        "date": "2026-06-30",
        "status": status,
        "candidate_pool_status": candidate_pool.get("status"),
        "candidate_pool": "results/m6d_w2_next_branch_candidate_pool.json",
        "target_manifest": out_manifest,
        "inventory_manifests": inventory_manifests,
        "min_targets": min_required,
        "n_admitted_targets": len(admitted),
        "n_selected_targets": len(selected_targets),
        "n_unique_selected_sources": len(set(selected_sources)),
        "selected_targets": [str(row.get("id")) for row in selected_targets],
        "selected_sources": sorted(set(selected_sources)),
        "duplicate_sources": duplicate_sources,
        "ready_for_strict_preflight": ready_for_preflight,
        "ready_for_cayuga_submission": False,
        "failures": failures,
        "claim_boundary": {
            "target_set": "predeclared_next_branch_candidates",
            "w2_multi_target_generalization": "not_supported_until_panel_report_certifies",
            "cayuga_submission": "not_authorized_by_this_artifact",
            "source_diversity": "one_selected_target_per_source_pdb_required",
        },
        "next_action": (
            "run complex_target_manifest --require-files on the emitted target manifest"
            if ready_for_preflight else
            "fix manifest-design blockers before strict preflight"
        ),
        "can_mark_goal_complete": False,
    }
    return report, manifest


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Next-Branch Manifest Design",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for strict preflight: `{str(bool(rep.get('ready_for_strict_preflight'))).lower()}`.",
        f"Ready for Cayuga submission: `{str(bool(rep.get('ready_for_cayuga_submission'))).lower()}`.",
        f"Target manifest: `{rep.get('target_manifest')}`.",
        "",
        "## Summary",
        "",
        f"- admitted targets: {rep.get('n_admitted_targets')}",
        f"- selected targets: {rep.get('n_selected_targets')}",
        f"- unique selected source PDBs: {rep.get('n_unique_selected_sources')}",
        f"- duplicate sources: {', '.join(rep.get('duplicate_sources') or []) or 'none'}",
        "",
        "## Selected Targets",
        "",
        "| target | source |",
        "|---|---|",
    ]
    sources = {str(source) for source in rep.get("selected_sources", [])}
    selected = rep.get("selected_targets", [])
    source_by_target = {}
    for target_id in selected:
        prefix = str(target_id).split("_", 1)[0]
        if prefix in sources:
            source_by_target[str(target_id)] = prefix
    for target_id in selected:
        lines.append(f"| {target_id} | {source_by_target.get(str(target_id), 'n/a')} |")
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        "- This artifact freezes the next-branch target set only.",
        "- It does not certify W2 multi-target generalization.",
        "- It does not authorize Cayuga ProteinMPNN/Boltz submission.",
        "",
        "## Failures",
        "",
    ])
    failures = rep.get("failures") or []
    if failures:
        for failure in failures:
            target = f" target={failure.get('target_id')}" if failure.get("target_id") else ""
            lines.append(f"- `{failure.get('kind')}`{target}: {failure.get('message')}")
    else:
        lines.append("- none")
    lines.extend([
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
    ap.add_argument("--inventory-manifest", action="append", dest="inventory_manifests", default=None)
    ap.add_argument("--min-targets", type=int, default=None)
    ap.add_argument("--out-manifest", default="configs/m6d_w2_expanded_next_branch_targets.json")
    ap.add_argument("--out-json", default="results/m6d_w2_next_branch_manifest_design.json")
    ap.add_argument("--out-md", default="results/m6d_w2_next_branch_manifest_design.md")
    args = ap.parse_args(argv)

    rep, manifest = build_manifest_design(
        _load_json(args.candidate_pool),
        args.inventory_manifests or DEFAULT_INVENTORY_MANIFESTS,
        out_manifest=args.out_manifest,
        min_targets=args.min_targets,
    )
    _write_json(args.out_manifest, manifest)
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(f"wrote {args.out_manifest}")
    print(f"wrote {args.out_json} and {args.out_md}")
    print(
        "status={status} selected={selected} unique_sources={sources} preflight_ready={ready}".format(
            status=rep["status"],
            selected=rep["n_selected_targets"],
            sources=rep["n_unique_selected_sources"],
            ready=rep["ready_for_strict_preflight"],
        )
    )
    return 0 if rep["ready_for_strict_preflight"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
