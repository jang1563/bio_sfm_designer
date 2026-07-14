"""M5b — the conformal trust gate on REAL designed proteins.

Loads the committed fixture of real ProteinMPNN->ESMFold designs (tests/fixtures/
esmfold_designs_records.jsonl: 120 designs for the 5L33 backbone across sampling temperatures;
ESMFold mean pLDDT is the visible signal, self-consistency scRMSD<2A the hidden success label),
splits it into a calibration set and a held-out test set, certifies a conformal trust threshold
tau on the calibration set via TrustGate(conformal_alpha=...), routes the held-out designs, and
reports the trusted set's ACTUAL false-accept rate vs the target alpha -- the calibrated, guaranteed
trust decision shown on real designs, next to the trust-all baseline.

CAVEATS (honest):
- Inherited from M4b: pLDDT and scRMSD come from the SAME ESMFold pass, so the success label is
  single-model self-consistency, not an independent oracle. The guarantee is "controls the
  self-consistency false-accept rate"; an independent refolder (Boltz-2/AF2, M6) removes the caveat.
- n is small (~120): the Hoeffding bound (RCPS) needs hundreds of points to certify a tight alpha,
  so it certifies a loose-but-real alpha and otherwise REFUSES (returns no tau) rather than
  over-promise. The RCPS machinery itself is proven in bio-sfm-trust tests/test_conformal.py.
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

_REGIME = "monomer"   # assume_validated is empty, so this experiment must still earn trust + certify tau
_DEFAULT_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "tests", "fixtures", "esmfold_designs_records.jsonl")


def _auroc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def _raw_risk(rec):
    return confidence_to_risk({"regime": _REGIME, "mean_plddt": rec["mean_plddt"]})


def _wrong(rec):
    return 0 if rec["truth"]["correct"] else 1


def run(records_path: str = _DEFAULT_FIXTURE, alpha: float = 0.2, delta: float = 0.1,
        n_cal: int = 80, seed: int = 0) -> Dict[str, Any]:
    with open(records_path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)
    cal = [rows[i] for i in idx[:n_cal]]
    test = [rows[i] for i in idx[n_cal:]]

    gate = TrustGate(lam=0.5, conformal_alpha=alpha, conformal_delta=delta,
                     assume_validated=frozenset())
    gate.prevalidate(_REGIME, [_raw_risk(r) for r in cal], [_wrong(r) for r in cal])
    state = gate._regimes[_REGIME]
    tau = state.tau

    def pred(rec):
        return Prediction(candidate_id=rec["target_id"], value=rec["mean_plddt"] / 100.0,
                          raw_conf=rec["mean_plddt"] / 100.0, regime=_REGIME, has_baseline=False)

    actions = Counter()
    trusted = trusted_wrong = 0
    for r in test:
        action = gate.route(pred(r)).action
        actions[action] += 1
        if action == "trust_sfm":
            trusted += 1
            trusted_wrong += _wrong(r)

    test_wrong = sum(_wrong(r) for r in test)
    return {
        "certification_schema": "split_ltt_v1",
        "n_cal": len(cal), "n_fit": len(cal) // 2,
        "n_certification": len(cal) - len(cal) // 2,
        "n_test": len(test), "alpha": alpha, "delta": delta,
        "auroc_plddt": _auroc([r["mean_plddt"] for r in rows], [r["truth"]["correct"] for r in rows]),
        "tau": tau,
        "certificate": state.certificate,
        "conformal": {"trusted": trusted, "false_accepts": trusted_wrong,
                      "false_accept_rate": (trusted_wrong / trusted) if trusted else None,
                      "actions": dict(actions)},
        "trust_all": {"trusted": len(test), "false_accepts": test_wrong,
                      "false_accept_rate": test_wrong / len(test) if test else None},
    }


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="conformal trust gate on real ProteinMPNN->ESMFold designs")
    ap.add_argument("--records", default=_DEFAULT_FIXTURE)
    ap.add_argument("--alpha", type=float, default=0.2, help="target false-accept rate for the trusted set")
    ap.add_argument("--delta", type=float, default=0.1, help="1-delta is the confidence of the bound")
    ap.add_argument("--ncal", type=int, default=80)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    rep = run(args.records, args.alpha, args.delta, args.ncal, args.seed)

    print(f"# conformal trust gate on REAL designs  (n_cal={rep['n_cal']}, n_test={rep['n_test']}, "
          f"alpha={rep['alpha']}, delta={rep['delta']})")
    print(f"  signal: AUROC(ESMFold pLDDT -> self-consistency success) = {rep['auroc_plddt']:.3f}")
    if rep["tau"] is None:
        print(f"  SPLIT-LTT REFUSED to certify a tau at alpha={rep['alpha']} (signal/n insufficient) -> trust nothing.")
        return rep
    c, ta = rep["conformal"], rep["trust_all"]
    far = c["false_accept_rate"]
    far_s = f"{far:.3f}" if far is not None else "n/a (trusted 0)"
    print(f"  certified tau = {rep['tau']:.3f}")
    print(f"  conformal gate (held-out): trusts {c['trusted']}/{rep['n_test']}, "
          f"false-accepts {c['false_accepts']} -> rate {far_s}  (target <= {rep['alpha']})")
    print(f"  trust-all   (held-out): trusts {ta['trusted']}/{rep['n_test']}, "
          f"false-accepts {ta['false_accepts']} -> rate {ta['false_accept_rate']:.3f}")
    print(f"  actions: {c['actions']}")
    print("  honest: success label = single-model self-consistency (M4b caveat); n small -> loose alpha.")
    return rep


if __name__ == "__main__":
    main()
