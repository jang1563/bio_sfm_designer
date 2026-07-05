"""M6c-lite -- does INTERFACE confidence discriminate designed-interface success at fixed difficulty?

The monomer result (within_regime_signal.py) was the project's worry: at fixed difficulty ESMFold pLDDT
does NOT predict an independent model's success (AUROC ~0.59, CI spans chance). This is the complex-regime
analog -- the thesis's last stand. barstar (chain D) is redesigned against a FIXED barnase target (1BRS
chain A) and refolded by Boltz-2 with the TARGET MSA'd + the binder single-seq (the realistic designed-binder
protocol; MSA-free folding FAILS at interfaces -- native barnase-barstar msa:empty -> 38 A, with MSA -> 1.0 A).
Interface success = ligand-RMSD (binder CA displacement after superposing on the target) < threshold.

RESULT (fixture barstar_interface_records.jsonl, 192 designs @ temps 0.3/0.5/0.7; success = L-RMSD < 4 A).
Reported as confound-FREE within-temp STRATIFIED AUROC (only compares success vs fail at the SAME temp):
  -pAE_interaction -> success = 0.93   <- the metric binder-design actually uses; the REAL interface signal
  complex pLDDT    -> success = 0.92   (fold confidence -- but that is FOLDABILITY, see below)
  pTM              -> success = 0.91
  ipTM             -> success = 0.76   <- weakest
The decisive control -- among WELL-FOLDED binders only (complex pLDDT >= 85, n=122, foldability held ~const):
  AUROC(-pAE_interaction -> docking) = 0.88, but AUROC(ipTM -> docking) = 0.59 (weak). So pAE_interaction
  is a genuine INTERFACE-QUALITY signal (separates good vs bad docking even among well-folded binders),
  whereas ipTM mostly co-varies with "did the binder fold".

HONEST verdict: UNLIKE monomer pLDDT (within-regime 0.59, chance), the complex/binder regime HAS an
informative, optimistically-miscalibrated interface-confidence signal -- pAE_interaction -- that survives
BOTH the temperature confound and the foldability control. That is exactly the regime where calibration +
selective deferral earn their keep -> a proper M6c is justified, routing on pAE_interaction (NOT ipTM, which
is the wrong/weak metric here). CAVEATS: single-model (pAE_interaction AND the L-RMSD label both come from
the one Boltz fold -- the M4b self-consistency caveat, not closed for complexes); n=192; ONE target
(barnase-barstar). A promising INDICATION that justifies a proper M6c, not a proof.
"""

from __future__ import annotations

import argparse
import collections
import os
import random

from .cross_model_auroc import _auroc, _load

_FIX = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "fixtures")
_BARSTAR = os.path.join(_FIX, "barstar_interface_records.jsonl")

# (record key, sign so that higher = more confident, label). pAE is lower=better -> sign -1.
_SIGNALS = [("pae_interaction", -1, "pAE_interaction (interface)"),
            ("mean_plddt", 1, "complex pLDDT (fold)"),
            ("ptm", 1, "pTM"),
            ("iptm", 1, "ipTM (interface)")]


def _temp(target_id):
    return target_id.split("-")[0]    # binder_t03 / binder_t05 / binder_t07


def _stratified_auroc(groups, key, sign, threshold):
    """AUROC comparing success vs fail only WITHIN the same temp group (removes the temp confound)."""
    num = den = 0.0
    for sub in groups:
        pos = [sign * r[key] for r in sub if r["lrmsd"] < threshold]
        neg = [sign * r[key] for r in sub if r["lrmsd"] >= threshold]
        for p in pos:
            for n in neg:
                num += (p > n) + 0.5 * (p == n)
                den += 1
    return num / den if den else None


def load_records(path: str) -> list[dict]:
    return [r for r in _load(path).values() if "pae_interaction" in r]


def run_rows(rows: list[dict], threshold: float = 4.0, plddt_cut: float = 85.0,
             n_boot: int = 2000, seed: int = 0) -> dict:
    recs = [r for r in rows if "pae_interaction" in r]
    by_t = collections.defaultdict(list)
    for r in recs:
        by_t[_temp(r["target_id"])].append(r)
    groups = list(by_t.values())
    rng = random.Random(seed)

    def stratified_ci(key, sign):
        a = _stratified_auroc(groups, key, sign, threshold)
        boots = []
        for _ in range(n_boot):
            resampled = [[sub[rng.randrange(len(sub))] for _ in range(len(sub))] for sub in groups]
            v = _stratified_auroc(resampled, key, sign, threshold)
            if v is not None:
                boots.append(v)
        boots.sort()
        ci = [round(boots[int(0.025 * len(boots))], 3), round(boots[int(0.975 * len(boots))], 3)] if boots else None
        return {"auroc": round(a, 3) if a is not None else None, "ci": ci}

    stratified = {key: stratified_ci(key, sign) for key, sign, _ in _SIGNALS}

    # foldability control: among well-folded binders, does the INTERFACE signal still separate docking?
    wf = [r for r in recs if r["mean_plddt"] >= plddt_cut]
    wf_succ = [r["lrmsd"] < threshold for r in wf]
    well_folded = {
        "plddt_cut": plddt_cut, "n": len(wf), "dock_success": sum(wf_succ),
        "auroc_pae": _auroc([-r["pae_interaction"] for r in wf], wf_succ),
        "auroc_iptm": _auroc([r["iptm"] for r in wf], wf_succ),
    }

    succ = [r for r in recs if r["lrmsd"] < threshold]
    fail = [r for r in recs if r["lrmsd"] >= threshold]
    return {
        "n": len(recs),
        "threshold": threshold,
        "success": len(succ),
        "stratified": stratified,
        "well_folded": well_folded,
        "mean_plddt_success": round(sum(r["mean_plddt"] for r in succ) / len(succ), 1) if succ else None,
        "mean_plddt_fail": round(sum(r["mean_plddt"] for r in fail) / len(fail), 1) if fail else None,
    }


def run(path: str = _BARSTAR, threshold: float = 4.0, plddt_cut: float = 85.0,
        n_boot: int = 2000, seed: int = 0) -> dict:
    return run_rows(load_records(path), threshold=threshold, plddt_cut=plddt_cut,
                    n_boot=n_boot, seed=seed)


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="complex-regime: does INTERFACE confidence discriminate success?")
    ap.add_argument("--records", default=_BARSTAR)
    ap.add_argument("--threshold", type=float, default=4.0)
    args = ap.parse_args(argv)
    r = run(args.records, args.threshold)
    s = r["stratified"]
    print(f"# complex-regime interface signal  (n={r['n']} barstar redesigns; success = L-RMSD < {r['threshold']} A; "
          f"{r['success']}/{r['n']} succeed)")
    print("  confound-FREE within-temp stratified AUROC(signal -> interface success):")
    for key, _, label in _SIGNALS:
        print(f"     {label:28s} = {s[key]['auroc']}  CI {s[key]['ci']}")
    wf = r["well_folded"]
    print(f"  foldability control (well-folded, complex pLDDT >= {wf['plddt_cut']:.0f}; n={wf['n']}, dock {wf['dock_success']}/{wf['n']}):")
    print(f"     AUROC(-pAE_interaction -> dock) = {wf['auroc_pae']:.2f}   vs   AUROC(ipTM -> dock) = {wf['auroc_iptm']:.2f}")
    print("  => pAE_interaction discriminates interface quality EVEN among well-folded binders (where ipTM is")
    print("     chance) -> a genuine interface signal, UNLIKE monomer pLDDT (within-regime ~0.59, chance).")
    print(f"  (fold conflated with dock: mean complex pLDDT success {r['mean_plddt_success']} vs fail {r['mean_plddt_fail']}.")
    print(f"   CAVEATS: single-model -- pAE + label both from one Boltz fold; n={r['n']}; ONE target. Indication, not proof.)")
    return r


if __name__ == "__main__":
    main()
