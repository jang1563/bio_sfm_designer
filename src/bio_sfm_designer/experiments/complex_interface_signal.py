"""M6c-lite -- does INTERFACE confidence (ipTM) discriminate designed-interface success at fixed difficulty?

The monomer result (within_regime_signal.py) was the project's worry: at fixed difficulty ESMFold pLDDT
does NOT predict an independent model's success (AUROC ~0.59, CI spans chance). This is the complex-regime
analog -- the thesis's last stand. barstar (chain D) is redesigned against a FIXED barnase target (1BRS
chain A) and refolded by Boltz-2 with the TARGET MSA'd + the binder single-seq (the realistic
designed-binder protocol; MSA-free folding FAILS at interfaces -- native barnase-barstar msa:empty -> 38 A,
with MSA -> 1.0 A). ipTM is the interface-confidence SIGNAL; interface success = ligand-RMSD (binder CA
displacement after superposing on the target) < threshold is the INDEPENDENT label.

RESULT (fixture barstar_interface_records.jsonl, 72 designs @ temps 0.3/0.5/0.7; success = L-RMSD < 4 A).
Reported as confound-FREE within-temp STRATIFIED AUROC (only compares success vs fail at the SAME temp;
pooling across temps mildly inflates, as it did for monomers):
  complex pLDDT -> success = 0.88, CI [0.77, 0.96]   <- the real, strong discriminator
  pTM           -> success = 0.87, CI [0.75, 0.96]
  ipTM          -> success = 0.68, CI [0.53, 0.81]   <- WEAK / barely significant
=> Confidence DOES discriminate designed-complex success at fixed difficulty (pLDDT 0.88) -- UNLIKE monomer
   pLDDT (within-regime 0.59, chance). THAT is the thesis-relevant positive: the complex regime has a real
   confidence signal the gate can use.

HONEST CORRECTIONS (a self-review of the first pass, which over-claimed "ipTM discriminates"):
  1. It is FOLD confidence (pLDDT/pTM) that discriminates, NOT interface confidence (ipTM, weak at 0.68).
  2. The label CONFLATES fold + dock: failed designs have mean complex pLDDT 83.5 vs 93.2 for successes,
     i.e. most "interface failures" are the binder MIS-FOLDING entirely, not a subtle interface defect --
     so this tests "confidence predicts complex-design success", not "ipTM predicts interface quality".
  3. SINGLE-MODEL: signal AND label both come from the one Boltz fold (the M4b self-consistency caveat,
     never closed for complexes). n=72, ONE target (barnase-barstar). A promising INDICATION, not a proof.
A proper M6c must: rank on pLDDT (or a blend), not ipTM; design a label that ISOLATES interface quality
(score only well-folded binders); add an INDEPENDENT second predictor; scale targets + designs.
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


def _stratified_auroc(groups, key, threshold):
    """AUROC that only compares success vs fail WITHIN the same temp group -> removes the temp confound."""
    num = den = 0.0
    for sub in groups:
        pos = [r[key] for r in sub if r["lrmsd"] < threshold]
        neg = [r[key] for r in sub if r["lrmsd"] >= threshold]
        for p in pos:
            for n in neg:
                num += (p > n) + 0.5 * (p == n)
                den += 1
    return num / den if den else None


def run(path: str = _BARSTAR, threshold: float = 4.0, n_boot: int = 2000, seed: int = 0) -> dict:
    recs = list(_load(path).values())
    by_t = collections.defaultdict(list)
    for r in recs:
        by_t[_temp(r["target_id"])].append(r)
    groups = list(by_t.values())
    rng = random.Random(seed)

    def stratified_ci(key):
        a = _stratified_auroc(groups, key, threshold)
        boots = []
        for _ in range(n_boot):
            resampled = [[sub[rng.randrange(len(sub))] for _ in range(len(sub))] for sub in groups]
            v = _stratified_auroc(resampled, key, threshold)
            if v is not None:
                boots.append(v)
        boots.sort()
        ci = [round(boots[int(0.025 * len(boots))], 3), round(boots[int(0.975 * len(boots))], 3)] if boots else None
        return {"auroc": round(a, 3) if a is not None else None, "ci": ci}

    # confound-free (within-temp) AUROC for each candidate confidence signal
    signals = {k: stratified_ci(k) for k in ("mean_plddt", "ptm", "iptm")}
    succ = [r for r in recs if r["lrmsd"] < threshold]
    fail = [r for r in recs if r["lrmsd"] >= threshold]
    return {
        "n": len(recs),
        "threshold": threshold,
        "success": len(succ),
        "stratified": signals,    # within-temp, confound-free AUROC(signal -> success) + bootstrap CI
        "mean_plddt_success": round(sum(r["mean_plddt"] for r in succ) / len(succ), 1) if succ else None,
        "mean_plddt_fail": round(sum(r["mean_plddt"] for r in fail) / len(fail), 1) if fail else None,
        "per_temp": {t: {"n": len(s), "success": sum(1 for r in s if r["lrmsd"] < threshold)} for t, s in sorted(by_t.items())},
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="complex-regime: does CONFIDENCE discriminate interface success?")
    ap.add_argument("--records", default=_BARSTAR)
    ap.add_argument("--threshold", type=float, default=4.0)
    args = ap.parse_args(argv)
    r = run(args.records, args.threshold)
    s = r["stratified"]
    print(f"# complex-regime confidence signal  (n={r['n']} barstar redesigns, success = L-RMSD < {r['threshold']} A; "
          f"{r['success']}/{r['n']} succeed)")
    print("  confound-FREE within-temp stratified AUROC(signal -> interface success):")
    print(f"     complex pLDDT (fold conf) = {s['mean_plddt']['auroc']}  CI {s['mean_plddt']['ci']}   <- the real discriminator")
    print(f"     pTM                       = {s['ptm']['auroc']}  CI {s['ptm']['ci']}")
    print(f"     ipTM (interface conf)     = {s['iptm']['auroc']}  CI {s['iptm']['ci']}   <- WEAK / barely significant")
    print(f"  mean complex pLDDT: success={r['mean_plddt_success']} vs fail={r['mean_plddt_fail']} "
          f"=> most failures are binder MIS-FOLDS (label conflates fold + dock), not subtle interface defects")
    print("  => Confidence DOES discriminate designed-complex success at fixed difficulty (pLDDT ~0.88), UNLIKE")
    print("     monomer pLDDT (within-regime ~0.59, chance) -> the complex regime has a real signal the gate can use.")
    print("  CORRECTED: it is FOLD confidence (pLDDT), NOT interface ipTM (0.68, weak). CAVEATS: single-model")
    print("  (signal+label both from one Boltz fold); n=72; ONE target. A promising indication, not a proof.")
    return r


if __name__ == "__main__":
    main()
