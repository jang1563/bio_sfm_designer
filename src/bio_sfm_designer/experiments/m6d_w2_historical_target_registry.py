"""Build and enforce a registry of previously evaluated W2 targets.

Manifest presence alone is not evidence that a target was evaluated. This
registry starts from panel-report target rows, then uses manifests only to add
source-PDB and protocol provenance. A future confirmatory panel fails closed
when it reuses an evaluated target or source structure.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence


DEFAULT_REPORT_GLOBS = [
    "results/m6c_panel_report.json",
    "results/m6d_redesign_panel_report.json",
    "results/m6d_followup_panel_report.json",
    "results/m6d_w2_*panel_report*.json",
]
DEFAULT_MANIFEST_GLOBS = [
    "configs/m6d_candidate_complex_targets.json",
    "configs/m6d_redesign_complex_targets.json",
    "configs/m6d_followup_complex_targets.json",
    "configs/m6d_w2_*targets.json",
]
DEFAULT_REGISTRY = "configs/m6d_w2_historical_target_registry.json"


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


def _target_id(row: Dict[str, Any]) -> Optional[str]:
    for key in ("complex_target_id", "target_id", "id", "target"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_id(row: Dict[str, Any], target_id: Optional[str] = None) -> Optional[str]:
    for key in ("rcsb_id", "source_rcsb_id", "source_pdb_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    target_id = target_id or _target_id(row)
    if target_id and "_" in target_id:
        return target_id.split("_", 1)[0].upper()
    return None


def _expand(patterns: Iterable[str]) -> List[str]:
    paths = set()
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.update(matches)
        elif os.path.exists(pattern):
            paths.add(pattern)
    return sorted(paths)


def _manifest_index(paths: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        try:
            manifest = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
        for row in manifest.get("targets", []):
            if not isinstance(row, dict):
                continue
            target_id = _target_id(row)
            if not target_id:
                continue
            item = index.setdefault(target_id, {
                "source_rcsb_ids": set(),
                "manifest_appearances": [],
                "protocols": [],
            })
            source = _source_id(row, target_id)
            if source:
                item["source_rcsb_ids"].add(source)
            item["manifest_appearances"].append(path)
            protocol = {
                "manifest": path,
                "num_seq": row.get("num_seq", defaults.get("num_seq")),
                "temp": row.get("temp", defaults.get("temp")),
                "seed": row.get("seed", defaults.get("seed")),
                "objective": row.get("objective", defaults.get("objective")),
            }
            if protocol not in item["protocols"]:
                item["protocols"].append(protocol)
    return index


def build_registry(report_paths: Sequence[str], manifest_paths: Sequence[str]) -> Dict[str, Any]:
    report_paths = _expand(report_paths)
    manifest_paths = _expand(manifest_paths)
    manifest_index = _manifest_index(manifest_paths)
    evaluated: Dict[str, Dict[str, Any]] = {}
    usable_reports = []
    for path in report_paths:
        try:
            report = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        target_rows = [row for row in report.get("targets", []) if isinstance(row, dict)]
        if not target_rows:
            continue
        usable_reports.append(path)
        for row in target_rows:
            target_id = _target_id(row)
            if not target_id:
                continue
            item = evaluated.setdefault(target_id, {
                "target_id": target_id,
                "source_rcsb_ids": set(),
                "panel_reports": [],
                "observed_statuses": set(),
                "ever_certified": False,
            })
            source = _source_id(row, target_id)
            if source:
                item["source_rcsb_ids"].add(source)
            item["panel_reports"].append(path)
            status = row.get("status")
            if isinstance(status, str) and status:
                item["observed_statuses"].add(status)
            item["ever_certified"] = item["ever_certified"] or row.get("certified") is True

    rows = []
    for target_id in sorted(evaluated):
        item = evaluated[target_id]
        manifest_item = manifest_index.get(target_id, {})
        sources = set(item["source_rcsb_ids"])
        sources.update(manifest_item.get("source_rcsb_ids", set()))
        rows.append({
            "target_id": target_id,
            "source_rcsb_ids": sorted(sources),
            "panel_reports": sorted(set(item["panel_reports"])),
            "observed_statuses": sorted(item["observed_statuses"]),
            "ever_certified": item["ever_certified"],
            "manifest_appearances": sorted(set(manifest_item.get("manifest_appearances", []))),
            "protocols": manifest_item.get("protocols", []),
        })
    source_ids = sorted({source for row in rows for source in row["source_rcsb_ids"]})
    return {
        "artifact": "m6d_w2_historical_target_registry",
        "date": date.today().isoformat(),
        "status": "historical_registry_ready" if rows else "historical_registry_empty",
        "audit_ok": bool(rows),
        "n_evaluated_targets": len(rows),
        "n_evaluated_sources": len(source_ids),
        "evaluated_target_ids": [row["target_id"] for row in rows],
        "evaluated_source_rcsb_ids": source_ids,
        "targets": rows,
        "panel_reports": usable_reports,
        "manifest_sources": manifest_paths,
        "claim_boundary": (
            "Registry membership means the target has already contributed outcome evidence. "
            "It must not be presented as a new confirmatory W2 target under the same protocol."
        ),
    }


def audit_manifest(manifest: Dict[str, Any], registry: Dict[str, Any]) -> Dict[str, Any]:
    historical_targets = set(registry.get("evaluated_target_ids") or [])
    historical_sources = set(registry.get("evaluated_source_rcsb_ids") or [])
    rows = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    overlap_targets = []
    overlap_sources = []
    new_rows = []
    for row in rows:
        target_id = _target_id(row)
        source = _source_id(row, target_id)
        target_overlap = bool(target_id and target_id in historical_targets)
        source_overlap = bool(source and source in historical_sources)
        if target_overlap:
            overlap_targets.append(target_id)
        if source_overlap:
            overlap_sources.append(source)
        if not target_overlap and not source_overlap:
            new_rows.append(row)
    failures = []
    if registry.get("audit_ok") is not True:
        failures.append({"kind": "historical_registry_not_ready"})
    if overlap_targets:
        failures.append({"kind": "historical_target_reuse", "target_ids": sorted(set(overlap_targets))})
    if overlap_sources:
        failures.append({"kind": "historical_source_reuse", "source_rcsb_ids": sorted(set(overlap_sources))})
    return {
        "artifact": "m6d_w2_historical_overlap_audit",
        "status": "historical_overlap_blocked" if failures else "new_target_panel_clear",
        "audit_ok": not failures,
        "n_manifest_targets": len(rows),
        "n_new_targets": len(new_rows),
        "historical_target_overlap": sorted(set(overlap_targets)),
        "historical_source_overlap": sorted(set(overlap_sources)),
        "new_target_ids": sorted(filter(None, (_target_id(row) for row in new_rows))),
        "new_targets": new_rows,
        "failures": failures,
        "claim_boundary": "Any historical target/source overlap blocks a new-target W2 confirmatory claim.",
    }


def new_only_manifest(manifest: Dict[str, Any], audit: Dict[str, Any], source_path: str) -> Dict[str, Any]:
    return {
        "_note": "New-target-only W2 panel; historical evaluated targets and sources were removed fail-closed.",
        "source_manifest": source_path,
        "historical_registry": DEFAULT_REGISTRY,
        "defaults": manifest.get("defaults", {}),
        "representative_target_ids": audit.get("new_target_ids", []),
        "targets": audit.get("new_targets", []),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-glob", action="append", default=[])
    ap.add_argument("--manifest-glob", action="append", default=[])
    ap.add_argument("--registry-out", default=DEFAULT_REGISTRY)
    ap.add_argument("--audit-manifest")
    ap.add_argument("--audit-out")
    ap.add_argument("--emit-new-only-manifest")
    args = ap.parse_args(argv)
    reports = args.report_glob or DEFAULT_REPORT_GLOBS
    manifests = args.manifest_glob or DEFAULT_MANIFEST_GLOBS
    registry = build_registry(reports, manifests)
    _write_json(args.registry_out, registry)
    print(f"registry={registry['status']} targets={registry['n_evaluated_targets']} sources={registry['n_evaluated_sources']}")
    if args.audit_manifest:
        manifest = _load_json(args.audit_manifest)
        audit = audit_manifest(manifest, registry)
        if args.audit_out:
            _write_json(args.audit_out, audit)
        if args.emit_new_only_manifest:
            _write_json(args.emit_new_only_manifest, new_only_manifest(manifest, audit, args.audit_manifest))
        print(f"manifest_audit={audit['status']} new={audit['n_new_targets']} failures={len(audit['failures'])}")
        return 0 if audit["audit_ok"] else 2
    return 0 if registry["audit_ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
