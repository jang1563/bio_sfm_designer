"""M1 offline structure gate: the 'gate-before-spend' discipline on real Boltz-2 records.

Runs the deterministic gates from bio_sfm_trust over the 80 post-cutoff PDB targets and
prints the monomer/complex calibration gap + gate decisions. No LLM calls, no GPU. This is
exactly the check that must pass before any LLM/assay spend on the protein substrate.

Run:
    python -m bio_sfm_designer.experiments.offline_structure_gate [--records PATH] [--lam 0.5]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bio_sfm_trust import calibrated_gate, phase2_calibration_gate
from bio_sfm_trust.io_utils import read_jsonl

_DEFAULT_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "phase2_targets_records.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(description="offline structure trust-gate (M1)")
    ap.add_argument("--records", default=str(_DEFAULT_FIXTURE))
    ap.add_argument("--lam", type=float, default=0.5)
    ap.add_argument("--correct-lddt", type=float, default=0.9)
    args = ap.parse_args()

    records = read_jsonl(args.records)
    raw = phase2_calibration_gate(records, lam=args.lam)
    cal = calibrated_gate(records, lam=args.lam, correct_lddt=args.correct_lddt)

    rc = raw["regime_calibration"]
    print("=" * 68)
    print(f"OFFLINE STRUCTURE GATE  ({raw['scope']['n_targets']} targets: "
          f"{raw['scope']['n_monomer']} monomer / {raw['scope']['n_complex']} complex)")
    print("=" * 68)
    print("calibration gap (Pearson pLDDT vs lDDT):")
    print(f"  monomer : {rc['monomer']['pearson_plddt_vs_quality']}")
    print(f"  complex : {rc['complex']['pearson_plddt_vs_quality']}")
    print(f"  gap     : {rc['monomer_minus_complex']}  <- routing stakes; complex is NOT calibrated")
    print()
    print(f"RAW binary gate (truth.correct):      {raw['decision']}")
    print(f"  wrong-risk AUROC: {raw['signal_validity']['wrong_risk_auroc']} "
          f"(Boltz-2 right ~95% -> trust-all ~= oracle; raw signal degenerate)")
    print(f"LOO-isotonic gate (lDDT>={args.correct_lddt}):  {cal['decision']}")
    print(f"  n_wrong: {cal['scope']['n_wrong']} | margin vs trust-all: {cal['margins']['vs_trust_all']} "
          f"| real-minus-shuffled: {cal['margins']['real_minus_shuffled']}")
    print()
    print("interpretation: the binary gate degenerates to trust-all, but the calibrated "
          "(lDDT-0.9) gate fires; calibration is sound for MONOMERS only. Do not claim "
          "interface calibration (see docs/RELATED_WORK.md).")
    print()
    print(json.dumps({"raw_decision": raw["decision"], "calibrated_decision": cal["decision"],
                      "calibration_gap": rc["monomer_minus_complex"]}, indent=2))


if __name__ == "__main__":
    main()
