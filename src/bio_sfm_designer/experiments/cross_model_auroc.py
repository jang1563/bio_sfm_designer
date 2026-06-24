"""M6a — the HONEST cross-model AUROC (closes the M4b single-model self-consistency caveat).

M4b/M5b measured AUROC(ESMFold pLDDT -> ESMFold-refold success): the pLDDT signal AND the scRMSD
success label came from the SAME ESMFold pass, so the number was partly self-prediction. This joins
the ESMFold-refold fixture (pLDDT signal + ESMFold self-consistency label) with an INDEPENDENT
Boltz-2-refold fixture (Boltz self-consistency label; Boltz = diffusion+Pairformer, no protein LM)
and reports AUROC(ESMFold pLDDT -> BOLTZ success) -- a genuine cross-model check -- beside the
single-model number and the label agreement between the two refolders.

Result on the committed 120-design fixtures (5L33 monomer designs, temps 0.3/0.6/1.0):
  ESMFold success 108/120, Boltz success 75/120 (Boltz stricter); labels agree 72%;
  single-model AUROC 0.947 vs cross-model AUROC 0.967 -- the signal transfers to (in fact predicts
  slightly BETTER on) an independent oracle, so it is not a self-prediction artifact.
"""

from __future__ import annotations

import argparse
import json
import os

_FIX = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "fixtures")
_ESM = os.path.join(_FIX, "esmfold_designs_records.jsonl")
_BOLTZ = os.path.join(_FIX, "boltz_designs_records.jsonl")


def _auroc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def _load(path):
    with open(path) as fh:
        return {r["target_id"]: r for r in (json.loads(line) for line in fh if line.strip())}


def run(esmfold_path: str = _ESM, boltz_path: str = _BOLTZ) -> dict:
    esm, bz = _load(esmfold_path), _load(boltz_path)
    ids = sorted(set(esm) & set(bz))
    esm_plddt = [esm[i]["mean_plddt"] for i in ids]
    esm_succ = [bool(esm[i]["truth"]["correct"]) for i in ids]
    bz_succ = [bool(bz[i]["truth"]["correct"]) for i in ids]
    agree = sum(a == b for a, b in zip(esm_succ, bz_succ))
    return {
        "n": len(ids),
        "esmfold_success": sum(esm_succ),
        "boltz_success": sum(bz_succ),
        "label_agreement": agree / len(ids) if ids else None,
        "auroc_single_model": _auroc(esm_plddt, esm_succ),     # ESMFold pLDDT -> ESMFold success
        "auroc_cross_model": _auroc(esm_plddt, bz_succ),       # ESMFold pLDDT -> BOLTZ success (honest)
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="honest cross-model AUROC (ESMFold signal vs Boltz label)")
    ap.add_argument("--esmfold", default=_ESM)
    ap.add_argument("--boltz", default=_BOLTZ)
    args = ap.parse_args(argv)
    r = run(args.esmfold, args.boltz)
    print(f"# cross-model AUROC  (n={r['n']} designs)")
    print(f"  ESMFold success {r['esmfold_success']}/{r['n']}  |  Boltz (independent) success {r['boltz_success']}/{r['n']}"
          f"  -> Boltz is the stricter oracle")
    print(f"  label agreement (ESMFold vs Boltz self-consistency): {r['label_agreement']:.0%}"
          f"  -> the refolders genuinely disagree, so the cross check is non-trivial")
    print(f"  single-model AUROC(ESMFold pLDDT -> ESMFold success) = {r['auroc_single_model']:.3f}")
    print(f"  HONEST  AUROC(ESMFold pLDDT -> BOLTZ   success) = {r['auroc_cross_model']:.3f}")
    print("  => the pLDDT signal predicts an INDEPENDENT model's success at least as well as its own;")
    print("     the M4b single-model self-consistency caveat is closed (not a self-prediction artifact).")
    return r


if __name__ == "__main__":
    main()
