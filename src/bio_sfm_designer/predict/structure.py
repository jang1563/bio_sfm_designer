"""M1 predictive front-end: protein structure on precomputed Boltz-2 records.

Reuses the audit's Phase-2 substrate (post-cutoff PDB targets with Boltz-2
pLDDT/ipTM + hidden experimental CA-lDDT truth). No GPU/Boltz needed — records are
precomputed. The SAME DBTL controller can therefore run on real structure data by
swapping in `StructureRecordGenerator` + `PrecomputedStructurePredictor`.

Honest scoping (see docs/RELATED_WORK.md blind spot #2): pLDDT is well-calibrated for
monomers (Pearson ~0.89 vs lDDT) but poorly for complexes/interfaces (~0.16). Only
`monomer` is in the gate's `trusted_regimes`, so complexes are never trusted outright —
they route to verify/defer. There is no model-visible numeric structural baseline per
target (template correctness is a hidden-truth field), so `baseline_value` is None and
`has_baseline` is False (the no-baseline -> verify/defer safety net is therefore live);
the real ipTM is carried through for the complex interface-risk blend.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from bio_sfm_trust.io_utils import read_jsonl

from ..config import ObjectiveSpec
from ..types import Candidate, Prediction


def load_structure_records(path: str) -> List[dict]:
    return read_jsonl(path)


def _prediction_from_record(rec: dict) -> Prediction:
    plddt_unit = float(rec["mean_plddt"]) / 100.0
    truth = rec.get("truth", {})
    iptm = rec.get("iptm")
    return Prediction(
        candidate_id=str(rec["target_id"]),
        value=round(plddt_unit, 6),          # visible proxy (pLDDT); realized lDDT stays hidden
        raw_conf=round(plddt_unit, 6),
        regime=rec.get("regime", "monomer"),
        iptm=float(iptm) if iptm is not None else None,   # real interface confidence (complexes)
        baseline_value=None,                 # no model-visible numeric template baseline per target
        has_baseline=False,                  # no numeric baseline -> no-baseline verify/defer net is live
        truth={
            "sfm_correct": bool(truth.get("correct", False)),
            "baseline_correct": bool(rec.get("template_baseline_correct", False)),
            "quality": truth.get("quality"),
        },
    )


class PrecomputedStructurePredictor:
    """Predictor that serves Boltz-2 records by target_id (candidate.id)."""

    def __init__(self, records_path: str) -> None:
        self._by_id: Dict[str, dict] = {str(r["target_id"]): r for r in load_structure_records(records_path)}

    def predict(self, candidate: Candidate, spec: Optional[ObjectiveSpec] = None) -> Prediction:
        rec = self._by_id.get(candidate.id)
        if rec is None:
            raise KeyError(f"no structure record for candidate {candidate.id!r}")
        return _prediction_from_record(rec)


class StructureRecordGenerator:
    """Generator that yields one Candidate per precomputed target (single-pass eval)."""

    def __init__(self, records_path: str) -> None:
        self._records = load_structure_records(records_path)

    def propose(
        self,
        spec: ObjectiveSpec,
        round: int,
        n: int,
        parents: Optional[List[Candidate]] = None,
    ) -> List[Candidate]:
        if round > 0:
            return []  # fixed target set: nothing new to generate after the first pass
        return [
            Candidate(
                id=str(r["target_id"]),
                representation=str(r["target_id"]),
                round=round,
                meta={"regime": r.get("regime"), "target": spec.target},
            )
            for r in self._records[:n]
        ]
