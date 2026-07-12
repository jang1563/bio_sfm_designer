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

    try:
        records = read_jsonl(args.records)
    except FileNotFoundError:
        raise SystemExit(
            f"records file not found: {args.records}\n"
            "Pass --records PATH. The default fixture ships only in a source checkout "
            "(tests/fixtures/phase2_targets_records.jsonl), not in an installed wheel."
        )

    mono = [r for r in records if r.get("regime") == "monomer"]
    cplx = [r for r in records if r.get("regime") == "complex"]
    raw = phase2_calibration_gate(records, lam=args.lam)
    rc = raw["regime_calibration"]

    def _cal(rs):
        return calibrated_gate(rs, lam=args.lam, correct_lddt=args.correct_lddt) if rs else None

    def _auroc(g):
        return None if g is None else g["signal_validity"]["wrong_risk_auroc"]

    cal_mono, cal_cplx, cal_all = _cal(mono), _cal(cplx), _cal(records)

    print("=" * 72)
    print(f"OFFLINE STRUCTURE GATE  ({raw['scope']['n_targets']} targets: "
          f"{len(mono)} monomer / {len(cplx)} complex)")
    print("=" * 72)
    print("calibration gap (Pearson pLDDT vs lDDT):")
    print(f"  monomer : {rc['monomer']['pearson_plddt_vs_quality']}")
    print(f"  complex : {rc['complex']['pearson_plddt_vs_quality']}")
    print(f"  gap     : {rc['monomer_minus_complex']}   <- complex pLDDT is NOT calibrated")
    print()
    print(f"RAW binary gate (truth.correct):  {raw['decision']}")
    print("  (Boltz-2 right ~95% -> trust-all ~= oracle; the raw binary signal is degenerate)")
    print()
    print(f"LOO-isotonic gate (lDDT>={args.correct_lddt}), reported PER REGIME:")
    print(f"  monomer-only : {cal_mono['decision']:<36}  wrong-risk AUROC={_auroc(cal_mono)}")
    print(f"  complex-only : {cal_cplx['decision']:<36}  wrong-risk AUROC={_auroc(cal_cplx)}")
    print(f"  pooled       : {cal_all['decision']:<36}  wrong-risk AUROC={_auroc(cal_all)}")
    print()
    print("interpretation: the calibrated wrong-risk signal is STRONG for monomers and WEAK for")
    print("complexes. The pooled 'interface_pilot' verdict only reaches its per-regime power floor")
    print("because complexes are counted — it is NOT an interface-calibration claim. Trust is scoped")
    print("to monomers; complexes verify/defer (see docs/RELATED_WORK.md blind spot #2).")
    print()
    print(json.dumps({
        "raw_decision": raw["decision"],
        "calibrated_decision_monomer": cal_mono["decision"],
        "calibrated_decision_complex": cal_cplx["decision"],
        "calibration_gap": rc["monomer_minus_complex"],
        "auroc_monomer": _auroc(cal_mono),
        "auroc_complex": _auroc(cal_cplx),
    }, indent=2))


if __name__ == "__main__":
    main()
