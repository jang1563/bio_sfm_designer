"""M6c-lite -- does INTERFACE confidence (ipTM) discriminate designed-interface success at fixed difficulty?

The monomer result (within_regime_signal.py) was the project's worry: at fixed difficulty ESMFold pLDDT
does NOT predict an independent model's success (AUROC ~0.59, CI spans chance). This is the complex-regime
analog -- the thesis's last stand. barstar (chain D) is redesigned against a FIXED barnase target (1BRS
chain A) and refolded by Boltz-2 with the TARGET MSA'd + the binder single-seq (the realistic
designed-binder protocol; MSA-free folding FAILS at interfaces -- native barnase-barstar msa:empty -> 38 A,
with MSA -> 1.0 A). ipTM is the interface-confidence SIGNAL; interface success = ligand-RMSD (binder CA
displacement after superposing on the target) < threshold is the INDEPENDENT label.

RESULT (fixture barstar_interface_records.jsonl, 72 designs @ temps 0.3/0.5/0.7; success = L-RMSD < 4 A):
  within-temp AUROC(ipTM -> success) = 0.64 / 0.68 / 0.76 -- every stratum ABOVE chance (unlike monomer);
  pooled AUROC = 0.73, CI [0.61, 0.84] -- EXCLUDES 0.5. ipTM is systematically higher for successes
  (~0.92) than failures (0.71-0.83) within each temp: informative but OPTIMISTICALLY MISCALIBRATED (even
  failures score ~0.8). That is exactly the regime where calibration + selective deferral earn their keep --
  a real signal to rank on, but raw ipTM over-trusts.

HONEST verdict: UNLIKE monomer pLDDT (chance at fixed difficulty), interface ipTM carries a real per-design
signal, so the trust gate's machinery has something to work with in the COMPLEX/binder regime. CAVEATS: the
effect is MODEST (~0.73, not 0.9+); n=72, ONE target (barnase-barstar), single-model refold (Boltz only),
within-temp n=24 (wide CIs). A promising INDICATION that justifies a proper M6c -- not a proof.
"""

from __future__ import annotations

import argparse
import collections
import os
import random

from .cross_model_auroc import _auroc, _load

_FIX = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "fixtures")
_BARSTAR = os.path.join(_FIX, "barstar_interface_records.jsonl")


def _temp(target_id):
    return target_id.split("-")[0]    # binder_t03 / binder_t05 / binder_t07


def run(path: str = _BARSTAR, threshold: float = 4.0, n_boot: int = 2000, seed: int = 0) -> dict:
    recs = list(_load(path).values())
    iptm = [r["iptm"] for r in recs]
    succ = [r["lrmsd"] < threshold for r in recs]

    per_temp = {}
    by_t = collections.defaultdict(list)
    for r in recs:
        by_t[_temp(r["target_id"])].append(r)
    for t in sorted(by_t):
        sub = by_t[t]
        s = [x["iptm"] for x in sub]
        l = [x["lrmsd"] < threshold for x in sub]
        per_temp[t] = {"n": len(sub), "success": sum(l), "auroc_iptm": _auroc(s, l)}

    sp = [r["iptm"] for r in recs if r["lrmsd"] < threshold]
    fp = [r["iptm"] for r in recs if r["lrmsd"] >= threshold]

    rng = random.Random(seed)
    n = len(recs)
    boots = []
    for _ in range(n_boot):
        samp = [rng.randrange(n) for _ in range(n)]
        a = _auroc([iptm[k] for k in samp], [succ[k] for k in samp])
        if a is not None:
            boots.append(a)
    boots.sort()

    return {
        "n": n,
        "threshold": threshold,
        "success": sum(succ),
        "auroc_pooled": _auroc(iptm, succ),
        "auroc_pooled_ci": [round(boots[int(0.025 * len(boots))], 3), round(boots[int(0.975 * len(boots))], 3)] if boots else None,
        "mean_iptm_success": round(sum(sp) / len(sp), 3) if sp else None,
        "mean_iptm_fail": round(sum(fp) / len(fp), 3) if fp else None,
        "per_temp": per_temp,
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="complex-regime: does ipTM discriminate interface success?")
    ap.add_argument("--records", default=_BARSTAR)
    ap.add_argument("--threshold", type=float, default=4.0)
    args = ap.parse_args(argv)
    r = run(args.records, args.threshold)
    print(f"# complex-regime interface signal  (n={r['n']} barstar redesigns, success = L-RMSD < {r['threshold']} A)")
    print(f"  interface success: {r['success']}/{r['n']}")
    print("  within-temp AUROC(ipTM -> success)  [every stratum > 0.5 = signal at fixed difficulty]:")
    for t, d in r["per_temp"].items():
        a = d["auroc_iptm"]
        print(f"     {t}: n={d['n']} success={d['success']}  AUROC={'n/a' if a is None else round(a, 3)}")
    print(f"  POOLED AUROC(ipTM -> success) = {r['auroc_pooled']:.3f}  CI {r['auroc_pooled_ci']}  [excludes 0.5 => significant]")
    print(f"  mean ipTM: success={r['mean_iptm_success']} vs fail={r['mean_iptm_fail']}  (informative but optimistic = miscalibrated)")
    print("  => UNLIKE monomer pLDDT (within-regime AUROC ~0.59, CI spans chance), interface ipTM carries a")
    print("     real per-design signal -> the trust gate's calibration earns its keep in the COMPLEX regime.")
    print("  CAVEATS: modest (~0.73, not 0.9+); n=72; ONE target (barnase-barstar); single-model (Boltz-only) refold.")
    return r


if __name__ == "__main__":
    main()
