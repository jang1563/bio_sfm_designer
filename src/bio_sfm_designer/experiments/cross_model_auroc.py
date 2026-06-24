"""M6a — the HONEST cross-model AUROC (closes the M4b single-model self-consistency caveat).

M4b/M5b measured AUROC(ESMFold pLDDT -> ESMFold-refold success): the pLDDT signal AND the scRMSD
success label came from the SAME ESMFold pass, so the number was partly self-prediction. This joins
the ESMFold-refold fixture (pLDDT signal + ESMFold self-consistency label) with an INDEPENDENT
Boltz-2-refold fixture (Boltz self-consistency label; Boltz = diffusion+Pairformer, no protein LM)
and reports AUROC(ESMFold pLDDT -> BOLTZ success) -- a genuine cross-model check -- beside the
single-model number and the label agreement between the two refolders.

Result on the committed 120-design fixtures (5L33 monomer designs, temps 0.3/0.6/1.0):
  ESMFold success 108/120, Boltz success 75/120; labels agree 72%; single-model AUROC 0.947 vs
  cross-model AUROC 0.967. The pLDDT signal DOES transfer to an independent oracle (so it is not a
  pure self-prediction artifact) -- but read the AUROC with three honest caveats (a self-review of
  this very result; see `run()`'s per-temp / within-temp / bootstrap fields):
   1. TEMPERATURE CONFOUND: failures concentrate at sampling temp 1.0 (Boltz 1/40 success there,
      mean scRMSD 10.3 A) and pLDDT tracks temperature, so most of the AUROC is separating easy
      (low-temp) from hard (high-temp) BATCHES, not a fine-grained per-design signal. Within temp
      1.0 the cross-model AUROC is degenerate (1 positive).
   2. NOT SIGNIFICANTLY HIGHER: the (cross - single) 95% bootstrap CI contains 0 -- 0.967 vs 0.947
      are statistically indistinguishable at n=120. Do NOT claim cross-model "predicts better".
   3. BOLTZ-msa:empty CONFOUND: Boltz single-sequence is "not recommended" (reduced accuracy); its
      higher failure rate may be a weak single-seq refold (10 A at temp 1.0), not designs being bad
      -- so "Boltz is stricter" is confounded. A cleaner test needs within-stratum analysis and a
      better-validated independent refolder (Boltz WITH MSA, or AF2).
"""

from __future__ import annotations

import argparse
import json
import os
import random

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


def _temp(target_id):
    return target_id.split("-")[0]    # design_t03 / design_t06 / design_t10


def run(esmfold_path: str = _ESM, boltz_path: str = _BOLTZ, n_boot: int = 2000, seed: int = 0) -> dict:
    esm, bz = _load(esmfold_path), _load(boltz_path)
    ids = sorted(set(esm) & set(bz))
    pl = [esm[i]["mean_plddt"] for i in ids]
    es = [bool(esm[i]["truth"]["correct"]) for i in ids]
    bs = [bool(bz[i]["truth"]["correct"]) for i in ids]
    agree = sum(a == b for a, b in zip(es, bs))

    # per-temperature breakdown -- failures concentrate at high temp, a confound for the pooled AUROC
    per_temp = {}
    for t in sorted(set(_temp(i) for i in ids)):
        sub = [k for k, i in enumerate(ids) if _temp(i) == t]
        per_temp[t] = {
            "n": len(sub),
            "esmfold_success": sum(es[k] for k in sub),
            "boltz_success": sum(bs[k] for k in sub),
            "auroc_cross_within": _auroc([pl[k] for k in sub], [bs[k] for k in sub]),  # degenerate if 1 class
        }

    # bootstrap: cross-model AUROC CI, and whether cross - single differs from 0
    rng = random.Random(seed)
    n = len(ids)
    cross_bs, diff_bs = [], []
    for _ in range(n_boot):
        samp = [rng.randrange(n) for _ in range(n)]
        ac = _auroc([pl[k] for k in samp], [bs[k] for k in samp])
        asg = _auroc([pl[k] for k in samp], [es[k] for k in samp])
        if ac is not None and asg is not None:
            cross_bs.append(ac)
            diff_bs.append(ac - asg)
    cross_bs.sort()
    diff_bs.sort()

    def _ci(v):
        return [round(v[int(0.025 * len(v))], 3), round(v[int(0.975 * len(v))], 3)] if v else None

    return {
        "n": n,
        "esmfold_success": sum(es),
        "boltz_success": sum(bs),
        "label_agreement": agree / n if n else None,
        "auroc_single_model": _auroc(pl, es),                  # ESMFold pLDDT -> ESMFold success
        "auroc_cross_model": _auroc(pl, bs),                   # ESMFold pLDDT -> BOLTZ success
        "auroc_cross_ci": _ci(cross_bs),
        "auroc_cross_minus_single_ci": _ci(diff_bs),           # contains 0 => not distinguishable
        "per_temp": per_temp,
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="honest cross-model AUROC (ESMFold signal vs Boltz label)")
    ap.add_argument("--esmfold", default=_ESM)
    ap.add_argument("--boltz", default=_BOLTZ)
    args = ap.parse_args(argv)
    r = run(args.esmfold, args.boltz)
    print(f"# cross-model AUROC  (n={r['n']} designs)")
    print(f"  ESMFold success {r['esmfold_success']}/{r['n']} | Boltz success {r['boltz_success']}/{r['n']}"
          f" | labels agree {r['label_agreement']:.0%} (genuinely different oracles)")
    print(f"  single-model AUROC(ESMFold pLDDT -> ESMFold success) = {r['auroc_single_model']:.3f}")
    print(f"  cross-model  AUROC(ESMFold pLDDT -> BOLTZ   success) = {r['auroc_cross_model']:.3f}  CI {r['auroc_cross_ci']}")
    print("  => the signal TRANSFERS to an independent oracle (not pure self-prediction). Read honestly:")
    print(f"     - (cross - single) 95% CI {r['auroc_cross_minus_single_ci']} CONTAINS 0 -> not 'better', indistinguishable.")
    print("     - per-temperature confound (failures concentrate at high temp; pLDDT tracks temp):")
    for t, d in r["per_temp"].items():
        aw = d["auroc_cross_within"]
        aw_s = f"{aw:.3f}" if aw is not None else "n/a (1 class)"
        print(f"         {t}: n={d['n']} esm_succ={d['esmfold_success']} boltz_succ={d['boltz_success']}"
              f"  within-temp cross-AUROC={aw_s}")
    print("       so the pooled AUROC mostly separates easy(low-temp) vs hard(high-temp) BATCHES; within the")
    print("       hardest temp Boltz success is ~degenerate, and Boltz ran msa:empty (a weak single-seq refolder).")
    print("  HONEST verdict: caveat ADDRESSED (independent signal transfers), NOT a clean 'closed' -- a tighter")
    print("  test needs within-stratum analysis + a validated independent refolder (Boltz+MSA / AF2).")
    return r


if __name__ == "__main__":
    main()
