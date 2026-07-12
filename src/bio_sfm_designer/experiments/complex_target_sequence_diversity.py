"""Audit target-sequence diversity before broad multi-target claims.

This is a cheap, pre-MSA guardrail. It reads target FASTA files from a complex
target manifest, clusters near-duplicate target sequences, and reports whether
the panel is diverse enough to support a broad W2 target-family claim before
submitting expensive external HPC jobs.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


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


def _read_fasta_sequence(path: str) -> str:
    seq: List[str] = []
    with open(path) as fh:
        for line in fh:
            text = line.strip()
            if not text or text.startswith(">"):
                continue
            seq.append(text)
    return "".join(ch.upper() for ch in "".join(seq) if ch.isalpha())


def _target_id(target: Dict[str, Any], index: int) -> str:
    value = target.get("id")
    if value is None or not str(value).strip():
        return f"target_{index}"
    return str(value)


def _coverage_identity(a: str, b: str) -> Dict[str, Any]:
    """Global-alignment identity with coverage normalized by the longer sequence."""
    min_len = min(len(a), len(b))
    max_len = max(len(a), len(b))
    if min_len == 0 or max_len == 0:
        return {
            "matches": 0,
            "min_len": min_len,
            "max_len": max_len,
            "aligned_length": max_len,
            "alignment_identity": 0.0,
            "overlap_identity": 0.0,
            "length_ratio": 0.0,
            "coverage_identity": 0.0,
        }

    # Each cell stores (alignment score, matches, aligned length). Ties prefer more
    # matches and then the shorter alignment, making the result deterministic.
    gap = -1
    previous = [(j * gap, 0, j) for j in range(len(b) + 1)]
    for i, residue_a in enumerate(a, 1):
        current = [(i * gap, 0, i)]
        for j, residue_b in enumerate(b, 1):
            diagonal = (
                previous[j - 1][0] + (1 if residue_a == residue_b else -1),
                previous[j - 1][1] + (1 if residue_a == residue_b else 0),
                previous[j - 1][2] + 1,
            )
            delete = (previous[j][0] + gap, previous[j][1], previous[j][2] + 1)
            insert = (current[j - 1][0] + gap, current[j - 1][1], current[j - 1][2] + 1)
            current.append(max((diagonal, delete, insert), key=lambda item: (item[0], item[1], -item[2])))
        previous = current
    _, matches, aligned_length = previous[-1]
    return {
        "matches": matches,
        "min_len": min_len,
        "max_len": max_len,
        "aligned_length": aligned_length,
        "alignment_identity": round(matches / aligned_length, 6),
        "overlap_identity": round(matches / min_len, 6),
        "length_ratio": round(min_len / max_len, 6),
        "coverage_identity": round(matches / max_len, 6),
    }


def _connected_components(nodes: Iterable[str], edges: Dict[str, Set[str]]) -> List[List[str]]:
    unseen = set(nodes)
    components: List[List[str]] = []
    while unseen:
        seed = sorted(unseen)[0]
        stack = [seed]
        component: Set[str] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            for neighbor in edges.get(node, set()):
                if neighbor not in component:
                    stack.append(neighbor)
        components.append(sorted(component))
        unseen -= component
    components.sort(key=lambda xs: (-len(xs), xs[0] if xs else ""))
    return components


def _representative_target_ids(clusters: List[List[str]], sequence_lengths: Dict[str, int]) -> List[str]:
    reps = []
    for cluster in clusters:
        reps.append(sorted(cluster, key=lambda target_id: (-sequence_lengths[target_id], target_id))[0])
    return reps


def write_representative_manifest(source_manifest_path: str, target_ids: Iterable[str], out: str) -> None:
    manifest = _load_json(source_manifest_path)
    keep = {str(target_id) for target_id in target_ids}
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise ValueError("manifest targets must be a list")
    representative_targets = [
        target for target in targets
        if isinstance(target, dict) and str(target.get("id")) in keep
    ]
    out_manifest = {
        "_note": (
            "Representative target subset emitted by complex_target_sequence_diversity. "
            "Use for scoped MSA precompute only; it does not certify broad W2 generalization."
        ),
        "source_manifest": source_manifest_path,
        "representative_target_ids": sorted(keep),
        "defaults": manifest.get("defaults", {}),
        "targets": representative_targets,
    }
    _write_json(out, out_manifest)


def audit_sequence_diversity(
    manifest_path: str,
    *,
    identity_threshold: float = 0.9,
    min_clusters: int = 3,
    max_largest_cluster_fraction: float = 0.5,
) -> Dict[str, Any]:
    manifest = _load_json(manifest_path)
    targets = manifest.get("targets")
    failures = []
    if not isinstance(targets, list):
        return {
            "artifact": "complex_target_sequence_diversity",
            "status": "bad_manifest",
            "manifest": os.path.abspath(manifest_path),
            "ok": False,
            "failures": [{"kind": "bad_manifest", "message": "targets must be a list"}],
            "ready_for_broad_w2_panel": False,
        }

    sequences: Dict[str, str] = {}
    target_rows: List[Dict[str, Any]] = []
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            failures.append({"kind": "bad_target", "target_id": None, "message": f"targets[{index}] is not an object"})
            continue
        tid = _target_id(target, index)
        fasta = target.get("target_fasta")
        if not isinstance(fasta, str) or not fasta.strip():
            failures.append({"kind": "missing_target_fasta", "target_id": tid, "message": "target_fasta is missing"})
            continue
        if not os.path.exists(fasta):
            failures.append({"kind": "missing_target_fasta", "target_id": tid, "message": f"target_fasta does not exist: {fasta}"})
            continue
        try:
            seq = _read_fasta_sequence(fasta)
        except OSError as exc:
            failures.append({"kind": "bad_target_fasta", "target_id": tid, "message": str(exc)})
            continue
        if not seq:
            failures.append({"kind": "empty_target_sequence", "target_id": tid, "message": f"target_fasta has no sequence: {fasta}"})
            continue
        sequences[tid] = seq
        target_rows.append({
            "target_id": tid,
            "rcsb_id": target.get("rcsb_id"),
            "source_pdb": target.get("source_pdb"),
            "target_fasta": fasta,
            "sequence_length": len(seq),
        })

    pairwise: List[Dict[str, Any]] = []
    edges: Dict[str, Set[str]] = {tid: set() for tid in sequences}
    ids = sorted(sequences)
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            metrics = _coverage_identity(sequences[left], sequences[right])
            row = {
                "target_id_a": left,
                "target_id_b": right,
                **metrics,
                "near_duplicate": metrics["coverage_identity"] >= identity_threshold,
            }
            pairwise.append(row)
            if row["near_duplicate"]:
                edges[left].add(right)
                edges[right].add(left)

    clusters = _connected_components(ids, edges)
    sequence_lengths = {tid: len(seq) for tid, seq in sequences.items()}
    representative_ids = _representative_target_ids(clusters, sequence_lengths)
    largest_cluster_size = max((len(cluster) for cluster in clusters), default=0)
    n_targets = len(target_rows)
    largest_cluster_fraction = round(largest_cluster_size / n_targets, 6) if n_targets else 0.0
    n_clusters = len(clusters)
    ready = (
        not failures
        and n_targets > 0
        and n_clusters >= min_clusters
        and largest_cluster_fraction <= max_largest_cluster_fraction
    )
    if failures:
        status = "sequence_diversity_audit_failed"
        next_action = "Fix missing or unreadable target FASTA files before W2 target-family decisions."
    elif ready:
        status = "sequence_diversity_ready_for_broad_w2_panel"
        next_action = "Proceed to target-MSA precompute for the full manifest, then rerun strict require-files preflight."
    elif n_clusters >= min_clusters:
        status = "sequence_diversity_dominated_by_near_duplicates"
        next_action = (
            "Use representative targets for scoped MSA precompute or expand seed discovery; "
            "do not claim broad W2 target-family diversity from the full panel."
        )
    else:
        status = "sequence_diversity_too_few_clusters"
        next_action = (
            "Expand seed discovery before external HPC MSA precompute; current panel has too few "
            "target-sequence clusters for a broad W2 claim."
        )

    return {
        "artifact": "complex_target_sequence_diversity",
        "status": status,
        "manifest": os.path.abspath(manifest_path),
        "ok": not failures,
        "ready_for_broad_w2_panel": ready,
        "identity_metric": "Needleman-Wunsch global-alignment matches / max(sequence lengths)",
        "identity_threshold": identity_threshold,
        "min_clusters": min_clusters,
        "max_largest_cluster_fraction": max_largest_cluster_fraction,
        "n_targets": n_targets,
        "n_sequence_clusters": n_clusters,
        "largest_cluster_size": largest_cluster_size,
        "largest_cluster_fraction": largest_cluster_fraction,
        "representative_target_ids": representative_ids,
        "target_sequences": target_rows,
        "clusters": [
            {
                "cluster_id": index + 1,
                "size": len(cluster),
                "representative_target_id": representative_ids[index],
                "target_ids": cluster,
            }
            for index, cluster in enumerate(clusters)
        ],
        "pairwise": pairwise,
        "failures": failures,
        "claim_boundary": (
            "This audit only checks target FASTA sequence diversity. It does not certify W2, "
            "does not evaluate binder quality, and does not replace target MSA or Boltz/Chai evidence."
        ),
        "next_action": next_action,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Complex Target Sequence Diversity Audit",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Ready for broad W2 panel: `{str(report.get('ready_for_broad_w2_panel')).lower()}`",
        f"- Targets: `{report.get('n_targets')}`",
        f"- Sequence clusters: `{report.get('n_sequence_clusters')}`",
        f"- Largest cluster size: `{report.get('largest_cluster_size')}`",
        f"- Largest cluster fraction: `{report.get('largest_cluster_fraction')}`",
        f"- Identity threshold: `{report.get('identity_threshold')}` using `{report.get('identity_metric')}`",
        f"- Minimum clusters: `{report.get('min_clusters')}`",
        f"- Maximum largest-cluster fraction: `{report.get('max_largest_cluster_fraction')}`",
        "",
        "## Claim Boundary",
        "",
        str(report.get("claim_boundary", "")),
        "",
        "## Clusters",
        "",
    ]
    for cluster in report.get("clusters", []):
        lines.append(
            f"- Cluster {cluster.get('cluster_id')}: size `{cluster.get('size')}`, "
            f"representative `{cluster.get('representative_target_id')}`, "
            f"targets `{', '.join(cluster.get('target_ids', []))}`"
        )
    if not report.get("clusters"):
        lines.append("- None")
    lines.extend(["", "## Highest Pairwise Similarities", ""])
    pairwise = sorted(
        report.get("pairwise", []),
        key=lambda row: (row.get("coverage_identity", 0.0), row.get("overlap_identity", 0.0)),
        reverse=True,
    )
    for row in pairwise[:20]:
        lines.append(
            f"- `{row.get('target_id_a')}` vs `{row.get('target_id_b')}`: "
            f"coverage_identity `{row.get('coverage_identity')}`, "
            f"overlap_identity `{row.get('overlap_identity')}`, "
            f"length_ratio `{row.get('length_ratio')}`, "
            f"near_duplicate `{str(row.get('near_duplicate')).lower()}`"
        )
    if not pairwise:
        lines.append("- None")
    lines.extend(["", "## Next Action", "", str(report.get("next_action", "")), ""])
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--identity-threshold", type=float, default=0.9)
    parser.add_argument("--min-clusters", type=int, default=3)
    parser.add_argument("--max-largest-cluster-fraction", type=float, default=0.5)
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    parser.add_argument("--out-representative-manifest")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = audit_sequence_diversity(
        args.manifest,
        identity_threshold=args.identity_threshold,
        min_clusters=args.min_clusters,
        max_largest_cluster_fraction=args.max_largest_cluster_fraction,
    )
    if args.out_json:
        _write_json(args.out_json, report)
    if args.out_md:
        _write_text(args.out_md, render_markdown(report))
    if args.out_representative_manifest:
        write_representative_manifest(args.manifest, report.get("representative_target_ids", []), args.out_representative_manifest)
    print(
        f"status={report['status']} targets={report['n_targets']} "
        f"clusters={report['n_sequence_clusters']} ready={report['ready_for_broad_w2_panel']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
