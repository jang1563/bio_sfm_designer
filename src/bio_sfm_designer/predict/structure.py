"""M1 predictive front-end: protein structure on precomputed Boltz-2 records.

Reuses the audit's Phase-2 substrate (post-cutoff PDB targets with Boltz-2
pLDDT/ipTM/pAE + hidden experimental CA-lDDT truth). No GPU/Boltz needed — records are
precomputed. The SAME DBTL controller can therefore run on real structure data by
swapping in `StructureRecordGenerator` + `PrecomputedStructurePredictor`.

Honest scoping (see docs/RELATED_WORK.md blind spot #2): pLDDT is well-calibrated for
monomers (Pearson ~0.89 vs lDDT) but poorly for complexes/interfaces (~0.16). monomer is
assume-validated in the gate; complexes start UNvalidated, so they verify/defer (never
trust the raw signal) until the complex regime is calibration-validated — either via the
offline `TrustGate.prevalidate(...)` pass or by accumulating verified complexes online —
at which point complexes route calibrated-selective (trust the low-risk, verify the rest).
There is no model-visible numeric structural baseline per target (template correctness is
a hidden-truth field), so `baseline_value` is None and `has_baseline` is False (the
no-baseline -> verify/defer net is live); the real ipTM and pAE_interaction are carried through
for complex interface-risk routing.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from bio_sfm_trust.io_utils import read_jsonl

from ..config import ObjectiveSpec
from ..types import Candidate, Prediction


def load_structure_records(path: str) -> List[dict]:
    return read_jsonl(path)


def _complex_target_id_from_record(rec: dict) -> Optional[str]:
    value = rec.get("complex_target_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _complex_target_id_from_candidate(candidate: Candidate) -> Optional[str]:
    value = candidate.meta.get("complex_target_id") if isinstance(candidate.meta, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _prediction_from_record(rec: dict) -> Prediction:
    plddt_unit = float(rec["mean_plddt"]) / 100.0
    truth = rec.get("truth", {})
    iptm = rec.get("iptm")
    pae_interaction = rec.get("pae_interaction")
    return Prediction(
        candidate_id=str(rec["target_id"]),
        value=round(plddt_unit, 6),          # visible proxy (pLDDT); realized lDDT stays hidden
        raw_conf=round(plddt_unit, 6),
        regime=rec.get("regime", "monomer"),
        iptm=float(iptm) if iptm is not None else None,   # real interface confidence (complexes)
        pae_interaction=float(pae_interaction) if pae_interaction is not None else None,
        baseline_value=None,                 # no model-visible numeric template baseline per target
        has_baseline=False,                  # no numeric baseline -> no-baseline verify/defer net is live
        truth={
            "sfm_correct": bool(truth.get("correct", False)),
            "baseline_correct": bool(rec.get("template_baseline_correct", False)),
            "quality": truth.get("quality"),
        },
    )


class PrecomputedStructurePredictor:
    """Predictor that serves Boltz-2 records by target_id, namespaced by complex_target_id when present."""

    def __init__(self, records_path: str) -> None:
        self._by_id: Dict[str, dict] = {}
        self._by_complex_id: Dict[Tuple[str, str], dict] = {}
        self._ambiguous_ids = set()
        for rec in load_structure_records(records_path):
            target_id = str(rec["target_id"])
            complex_id = _complex_target_id_from_record(rec)
            if complex_id:
                self._by_complex_id[(complex_id, target_id)] = rec
            if target_id in self._by_id and self._by_id[target_id] != rec:
                self._ambiguous_ids.add(target_id)
            else:
                self._by_id[target_id] = rec

    def predict(self, candidate: Candidate, spec: Optional[ObjectiveSpec] = None) -> Prediction:
        complex_id = _complex_target_id_from_candidate(candidate)
        if complex_id:
            rec = self._by_complex_id.get((complex_id, candidate.id))
            if rec is None:
                raise KeyError(f"no structure record for candidate {candidate.id!r} in complex {complex_id!r}")
            return _prediction_from_record(rec)
        if candidate.id in self._ambiguous_ids:
            raise KeyError(
                f"ambiguous structure records for candidate {candidate.id!r}; "
                "provide candidate.meta['complex_target_id']"
            )
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
