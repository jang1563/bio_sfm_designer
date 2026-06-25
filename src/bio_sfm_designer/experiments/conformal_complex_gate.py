"""M6c — the conformal trust gate on the COMPLEX/binder regime (the regime where confidence is real).

M6c-lite established that the complex regime has a genuine interface-confidence signal: pAE_interaction
discriminates designed-interface success at fixed difficulty (within-temp stratified AUROC 0.91; 0.88 even
among well-folded binders, where ipTM is chance). This routes the barstar redesigns through TrustGate on the
calibrated pAE_interaction risk: split cal/test, certify a conformal tau (false-accept <= alpha) on cal,
route the held-out designs, and report the trusted set's ACTUAL false-accept rate vs the trust-all baseline.
This is the gate's reason to exist -- selective deferral with a distribution-free bound -- demonstrated on
the protein regime where the signal is informative (unlike monomer, where it was chance).

Routing signal: confidence_to_risk now prefers pae_interaction for complexes (not the weak ipTM), and the
gate re-calibrates it per regime (isotonic) before certifying tau.

RESULT (192 barstar redesigns, target-MSA): signal AUROC(-pAE -> interface success) ~0.94; RCPS CERTIFIES
alpha=0.3 -- the gate trusts 25/64 held-out at 12% false-accept (bound <= 30%) vs trust-all 60%. Scaling the
set 72 -> 192 moved this from "refuse to certify" to "certify alpha=0.3"; tighter alpha (0.1/0.2) still
refuses (the Hoeffding n<->alpha tradeoff -> more designs).

CAVEATS: single-model (pae_interaction AND the L-RMSD label both come from the one Boltz fold -- the M4b
self-consistency caveat, not closed for complexes); ONE target (barnase-barstar). An indication on one
target with a loose certified alpha, not a multi-target proof.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter
from typing import Any, Dict

from bio_sfm_trust import confidence_to_risk

from ..trust import TrustGate
from ..types import Prediction

_REGIME = "complex"   # not assume-validated -> the gate must earn trust + certify tau
_DEFAULT_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "tests", "fixtures", "barstar_interface_records.jsonl")


def _auroc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def _raw_risk(rec):
    return confidence_to_risk({"regime": _REGIME, "mean_plddt": rec["mean_plddt"],
                               "iptm": rec.get("iptm"), "pae_interaction": rec.get("pae_interaction")})


def _wrong(rec, threshold):
    return 0 if rec["lrmsd"] < threshold else 1


def run(records_path: str = _DEFAULT_FIXTURE, alpha: float = 0.3, delta: float = 0.1,
        threshold: float = 4.0, n_cal: int = 128, seed: int = 0) -> Dict[str, Any]:
    rows = [r for r in (json.loads(line) for line in open(records_path) if line.strip())
            if r.get("pae_interaction") is not None]
    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)
    cal = [rows[i] for i in idx[:n_cal]]
    test = [rows[i] for i in idx[n_cal:]]

    gate = TrustGate(lam=0.5, conformal_alpha=alpha, conformal_delta=delta, assume_validated=frozenset())
    gate.prevalidate(_REGIME, [_raw_risk(r) for r in cal], [_wrong(r, threshold) for r in cal])
    tau = gate._regimes[_REGIME].tau

    def pred(rec):
        return Prediction(candidate_id=rec["target_id"], value=rec["mean_plddt"] / 100.0,
                          raw_conf=rec["mean_plddt"] / 100.0, regime=_REGIME,
                          iptm=rec.get("iptm"), pae_interaction=rec.get("pae_interaction"), has_baseline=False)

    actions = Counter()
    trusted = trusted_wrong = 0
    for r in test:
        action = gate.route(pred(r)).action
        actions[action] += 1
        if action == "trust_sfm":
            trusted += 1
            trusted_wrong += _wrong(r, threshold)

    test_wrong = sum(_wrong(r, threshold) for r in test)
    # selective-risk curve, illustrative of the SIGNAL's gating power independent of the (small-n) conformal
    # certificate: sort by pae_interaction (ascending = most confident) and trust the lowest-pae fraction.
    srt = sorted(rows, key=lambda r: r["pae_interaction"])
    selective = []
    for frac in (0.25, 0.5, 0.75):
        k = max(1, int(len(srt) * frac))
        fa = sum(_wrong(r, threshold) for r in srt[:k])
        selective.append({"frac": frac, "trusted": k, "false_accept_rate": round(fa / k, 3)})
    return {
        "n_cal": len(cal), "n_test": len(test), "alpha": alpha, "delta": delta, "threshold": threshold,
        # signal quality on the full set: -pAE_interaction vs interface success (higher score = lower pae)
        "auroc_pae": _auroc([-r["pae_interaction"] for r in rows], [r["lrmsd"] < threshold for r in rows]),
        "base_rate_fail": round(sum(_wrong(r, threshold) for r in rows) / len(rows), 3),
        "tau": tau,
        "conformal": {"trusted": trusted, "false_accepts": trusted_wrong,
                      "false_accept_rate": (trusted_wrong / trusted) if trusted else None,
                      "actions": dict(actions)},
        "trust_all": {"trusted": len(test), "false_accepts": test_wrong,
                      "false_accept_rate": test_wrong / len(test) if test else None},
        "selective": selective,
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="conformal trust gate on the complex/binder regime (pAE signal)")
    ap.add_argument("--records", default=_DEFAULT_FIXTURE)
    ap.add_argument("--alpha", type=float, default=0.3)
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--ncal", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    rep = run(args.records, args.alpha, args.delta, args.threshold, args.ncal, args.seed)

    print(f"# conformal trust gate on the COMPLEX regime  (n_cal={rep['n_cal']}, n_test={rep['n_test']}, "
          f"alpha={rep['alpha']}, delta={rep['delta']})")
    print(f"  signal: AUROC(-pAE_interaction -> interface success) = {rep['auroc_pae']:.3f}  "
          f"(base-rate failure {rep['base_rate_fail']:.0%})")
    print("  selective-risk -- trust the lowest-pAE fraction (illustrative of the signal, in-sample):")
    for s in rep["selective"]:
        print(f"     trust lowest {s['frac']:.0%} ({s['trusted']}): false-accept {s['false_accept_rate']:.0%}"
              f"   vs trust-all {rep['base_rate_fail']:.0%}")
    c = rep["conformal"]
    if rep["tau"] is None:
        print(f"  CONFORMAL: RCPS refused a tau at alpha={rep['alpha']} (n_cal={rep['n_cal']} too small for the "
              f"Hoeffding bound) -> trust nothing rather than over-promise.")
        print("  => the SIGNAL gates well (selective curve), but a distribution-free certificate needs ~hundreds")
        print("     of designs -- that scale-up is the proper-M6c step, not a limitation of the signal.")
    else:
        far = c["false_accept_rate"]
        far_s = f"{far:.3f}" if far is not None else "n/a (trusted 0)"
        print(f"  CONFORMAL: certified tau={rep['tau']:.3f}; held-out trusts {c['trusted']}/{rep['n_test']}, "
              f"false-accept {far_s} (target <= {rep['alpha']})")
    print("  honest: single-model (pAE + label both from one Boltz fold); ONE target (barnase-barstar).")
    return rep


if __name__ == "__main__":
    main()
