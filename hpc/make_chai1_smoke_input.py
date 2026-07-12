#!/usr/bin/env python3
"""Prepare a minimal Chai-1 heterodimer FASTA from a complex candidate JSONL."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any, Dict, Iterable, Optional, Tuple


_VALID_AA = set("ACDEFGHIKLMNPQRSTVWYX")


def _read_jsonl(path: pathlib.Path) -> Iterable[Tuple[int, Dict[str, Any]]]:
    with path.open() as handle:
        for i, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"line {i + 1} is not a JSON object")
            yield i, payload


def _select_candidate(
    path: pathlib.Path,
    *,
    candidate_id: Optional[str],
    index: int,
) -> Tuple[int, Dict[str, Any]]:
    if candidate_id:
        for i, row in _read_jsonl(path):
            if row.get("id") == candidate_id:
                return i, row
        raise ValueError(f"candidate id not found: {candidate_id}")
    for i, row in _read_jsonl(path):
        if i == index:
            return i, row
    raise ValueError(f"candidate index out of range: {index}")


def _require_sequence(row: Dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate is missing non-empty {key!r}")
    seq = "".join(value.split()).upper()
    invalid = sorted(set(seq) - _VALID_AA)
    if invalid:
        raise ValueError(f"{key} contains unsupported residue symbols: {''.join(invalid)}")
    return seq


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    safe = safe.strip("._-")
    return safe or "candidate"


def _wrap(seq: str, width: int = 80) -> str:
    return "\n".join(seq[i : i + width] for i in range(0, len(seq), width))


def build_fasta(candidate: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("candidate is missing non-empty 'id'")
    meta = candidate.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    target_seq = _require_sequence(candidate, "target_seq")
    binder_seq = _require_sequence(candidate, "representation")
    target_chain = str(meta.get("target_chain") or "target")
    binder_chain = str(meta.get("design_chain") or meta.get("binder_chain") or "binder")
    complex_target_id = str(meta.get("complex_target_id") or "")
    safe_id = _safe_name(candidate_id)
    target_name = _safe_name(f"{safe_id}_{target_chain}")
    binder_name = _safe_name(f"{safe_id}_{binder_chain}")
    fasta = (
        f">protein|name={target_name}\n{_wrap(target_seq)}\n"
        f">protein|name={binder_name}\n{_wrap(binder_seq)}\n"
    )
    manifest = {
        "candidate_id": candidate_id,
        "complex_target_id": complex_target_id,
        "target_chain": target_chain,
        "binder_chain": binder_chain,
        "target_fasta_name": target_name,
        "binder_fasta_name": binder_name,
        "target_sequence_length": len(target_seq),
        "binder_sequence_length": len(binder_seq),
        "predictor_id": "chai1_complex",
        "signal_source": "chai1_pae_interaction",
        "label_source": "chai1_lrmsd_to_reference",
        "claim_status": "no_claim_smoke_input",
    }
    return fasta, manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="write a minimal Chai-1 smoke-test FASTA and manifest from complex candidates JSONL"
    )
    parser.add_argument("--candidates", required=True, help="complex candidates JSONL")
    parser.add_argument("--candidate-id", default=None, help="candidate id to select")
    parser.add_argument("--index", type=int, default=0, help="0-based candidate index if --candidate-id is omitted")
    parser.add_argument("--out", required=True, help="output FASTA path")
    parser.add_argument("--manifest", required=True, help="output manifest JSON path")
    args = parser.parse_args()

    candidates_path = pathlib.Path(args.candidates)
    out_path = pathlib.Path(args.out)
    manifest_path = pathlib.Path(args.manifest)
    selected_index, candidate = _select_candidate(candidates_path, candidate_id=args.candidate_id, index=args.index)
    fasta, manifest = build_fasta(candidate)
    manifest.update(
        {
            "source_candidates": str(candidates_path),
            "selected_index": selected_index,
            "fasta": str(out_path),
            "manifest": str(manifest_path),
        }
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(fasta)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}")
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
