"""M6b — the CLEAN within-regime cross-model signal (removes the temperature confound that inflated M6a).

M6a's pooled AUROC(ESMFold pLDDT -> Boltz success) = 0.967 was measured across sampling temps 0.3/0.6/1.0.
Since failures concentrate at high temp and pLDDT tracks temp, that number mostly separated easy(low-temp)
from hard(high-temp) BATCHES, not designs within a regime. This re-measures at a SINGLE temperature
(0.7, 160 designs) so difficulty is fixed and the AUROC reflects per-design discrimination only.

RESULT (fixtures esmfold_t07_records.jsonl + boltz_t07_records.jsonl, 160 designs @ temp 0.7):
  Boltz success 101/160 (a genuine mix, NOT saturated); ESMFold self-label 158/160 (near-degenerate);
  labels agree 63%. AUROC(ESMFold pLDDT -> Boltz success) = 0.55, CI ~[0.45, 0.65] -- indistinguishable
  from chance (0.5). Boltz success by pLDDT tertile is non-monotone (53% / 74% / 63%); mean pLDDT is 89.4
  for Boltz-success vs 88.4 for Boltz-fail (a ~1-point gap).

HONEST CONCLUSION: at fixed difficulty, ESMFold pLDDT does NOT predict an independent model's per-design
success -- the strong pooled signal was a temperature/difficulty BATCH effect, not per-design quality. The
monomer pLDDT-risk the trust gate routes on is a COARSE difficulty filter (it rejects clearly-bad designs),
NOT a fine per-design trust oracle. This sharpens the project's honest positioning: monomer confidence
alone is not a fine trust signal; calibration earns its keep in the COMPLEX/binder regime (broken
confidence -> selective deferral), and the cheap-baseline-disagreement signal is validated only in the
perturbation regime -- not on monomer design here.

CAVEATS (why this reads "weak / chance-level", not "provably zero"): (1) restriction of range -- at one
moderate temp pLDDT is compressed (77-94), so the very-low-pLDDT designs that only appear at higher temp
aren't sampled; the coarse signal lives at that extreme (confounded with temp). (2) Both refolders are
single-sequence (ESMFold + Boltz msa:empty, the correct mode for homolog-free designs), so the
disagreement is partly two noisy single-seq models. (3) n=160; the CI admits a very weak ~0.6 but rules
out the >=0.8 the pooled number implied.
"""

from __future__ import annotations

import argparse
import random

from .cross_model_auroc import _FIX, _auroc, _load
import os

_ESM_T07 = os.path.join(_FIX, "esmfold_t07_records.jsonl")
_BOLTZ_T07 = os.path.join(_FIX, "boltz_t07_records.jsonl")


def run(esmfold_path: str = _ESM_T07, boltz_path: str = _BOLTZ_T07, n_boot: int = 2000, seed: int = 0) -> dict:
    esm, bz = _load(esmfold_path), _load(boltz_path)
    ids = sorted(set(esm) & set(bz))
    pl = [esm[i]["mean_plddt"] for i in ids]
    es = [bool(esm[i]["truth"]["correct"]) for i in ids]
    bs = [bool(bz[i]["truth"]["correct"]) for i in ids]
    agree = sum(a == b for a, b in zip(es, bs))

    # Boltz success rate by ESMFold-pLDDT tertile (a monotone rise would mean pLDDT carries signal)
    z = sorted(zip(pl, bs))
    t = len(z) // 3
    tertiles = []
    for chunk in (z[:t], z[t:2 * t], z[2 * t:]):
        rate = sum(b for _, b in chunk) / len(chunk)
        tertiles.append({"plddt_lo": chunk[0][0], "plddt_hi": chunk[-1][0], "boltz_success_rate": round(rate, 3)})

    sp = [p for p, b in zip(pl, bs) if b]
    fp = [p for p, b in zip(pl, bs) if not b]

    rng = random.Random(seed)
    n = len(ids)
    boots = []
    for _ in range(n_boot):
        samp = [rng.randrange(n) for _ in range(n)]
        a = _auroc([pl[k] for k in samp], [bs[k] for k in samp])
        if a is not None:
            boots.append(a)
    boots.sort()

    return {
        "n": n,
        "boltz_success": sum(bs),
        "esmfold_success": sum(es),
        "label_agreement": round(agree / n, 3) if n else None,
        "auroc_cross": _auroc(pl, bs),
        "auroc_cross_ci": [round(boots[int(0.025 * len(boots))], 3), round(boots[int(0.975 * len(boots))], 3)] if boots else None,
        "mean_plddt_boltz_success": round(sum(sp) / len(sp), 1) if sp else None,
        "mean_plddt_boltz_fail": round(sum(fp) / len(fp), 1) if fp else None,
        "tertiles": tertiles,
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="clean within-regime (fixed-temp) cross-model signal")
    ap.add_argument("--esmfold", default=_ESM_T07)
    ap.add_argument("--boltz", default=_BOLTZ_T07)
    args = ap.parse_args(argv)
    r = run(args.esmfold, args.boltz)
    print(f"# within-regime cross-model signal  (n={r['n']} designs, FIXED temp 0.7)")
    print(f"  Boltz success {r['boltz_success']}/{r['n']} (genuine mix) | ESMFold self-label "
          f"{r['esmfold_success']}/{r['n']} (near-degenerate) | labels agree {r['label_agreement']:.0%}")
    print(f"  AUROC(ESMFold pLDDT -> BOLTZ success) = {r['auroc_cross']:.3f}  CI {r['auroc_cross_ci']}"
          f"  <- chance is 0.5")
    print(f"  mean pLDDT: Boltz-success={r['mean_plddt_boltz_success']} vs Boltz-fail={r['mean_plddt_boltz_fail']}"
          f"  (negligible gap)")
    print("  Boltz success by pLDDT tertile (a rise would mean signal):")
    for d in r["tertiles"]:
        print(f"     pLDDT {d['plddt_lo']:.0f}-{d['plddt_hi']:.0f}: {d['boltz_success_rate']:.0%}")
    print("  => at FIXED difficulty the cross-model signal is ~chance; the pooled 0.967 (M6a) was a")
    print("     temperature BATCH effect. Monomer pLDDT-risk is a COARSE difficulty filter, not a fine")
    print("     per-design trust oracle. Calibration earns its keep in the complex/binder regime, not here.")
    return r


if __name__ == "__main__":
    main()
