"""M3 generative front-end (consume-side): serve candidate designs produced by a Cayuga
generate job (RFdiffusion / ProteinMPNN / ESM).

Same HPC pattern as predict/structure.py: heavy generation runs on Cayuga/Expanse (GPU) and
writes a candidates JSONL; the local controller consumes it offline via this adapter. The real
generators are GPU jobs (hpc/run_generate.sbatch + hpc/generate_template.py); this is the
local, dependency-free, fully-testable side.

Input JSONL: one record per line, e.g.
    {"id": "...", "representation": "<sequence or backbone ref>", "regime": "monomer", "parent_id": null}
"""

from __future__ import annotations

from typing import List, Optional

from bio_sfm_trust.io_utils import read_jsonl

from ..config import ObjectiveSpec
from ..types import Candidate


def load_candidate_records(path: str) -> List[dict]:
    return read_jsonl(path)


class PrecomputedGenerator:
    """Serve precomputed candidate designs. Single-pass over a fixed Cayuga-produced set:
    round 0 yields up to `n` candidates; later rounds yield [] (the controller then stops)."""

    def __init__(self, candidates_path: str) -> None:
        self._records = load_candidate_records(candidates_path)

    def propose(
        self,
        spec: ObjectiveSpec,
        round: int,
        n: int,
        parents: Optional[List[Candidate]] = None,
    ) -> List[Candidate]:
        if round > 0:
            return []
        out: List[Candidate] = []
        for r in self._records[:n]:
            meta = dict(r.get("meta") or {})
            meta.setdefault("target", spec.target)
            if r.get("regime") is not None:
                meta["regime"] = r["regime"]
            out.append(
                Candidate(
                    id=str(r["id"]),
                    representation=str(r.get("representation", r["id"])),
                    round=round,
                    parent_id=r.get("parent_id"),
                    meta=meta,
                )
            )
        return out
