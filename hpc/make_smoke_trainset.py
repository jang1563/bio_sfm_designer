"""Write a tiny labeled JSONL pair (train + eval) for a MECHANICAL training smoke.

This proves the train->screen plumbing on external HPC -- it does NOT produce a useful screen head.
Real heads need real labeled data (e.g. WildGuardMix + FalseReject + domain-specific intents).

Labels: 1 = hazardous-intent placeholder, 0 = benign research/biology.
The hazardous rows here are abstract placeholders, not real hazard content (the smoke just
needs two linearly-separable classes to verify the trainer end-to-end).
"""

from __future__ import annotations

import argparse
import json
import os

_BENIGN = [
    "Design a thermostable variant of GFP.",
    "Improve the solubility of a benign industrial enzyme.",
    "Engineer a more efficient cellulase for biofuel production.",
    "Optimize a beta-lactamase variant for diagnostic assays.",
    "Design a fluorescent calcium sensor for live-cell imaging.",
    "Stabilize a human serum albumin variant for drug delivery.",
    "Engineer a heat-tolerant lipase for laundry detergent.",
    "Improve the catalytic rate of carbonic anhydrase for CO2 capture.",
    "Design a binder for a benign reporter protein.",
    "Engineer a more soluble form of GFP for fluorescence microscopy.",
    "Optimize streptavidin for affinity chromatography.",
    "Design an enzyme that degrades PET plastic at room temperature.",
]

# Abstract placeholders: "PLACEHOLDER_HAZARD_INTENT_<n>" — not real hazard text.
# The trainer only needs two separable classes to verify the pipeline mechanically.
_HAZARD = [f"PLACEHOLDER_HAZARD_INTENT_{i}" for i in range(1, 13)]


def _write(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="write a tiny labeled smoke trainset")
    ap.add_argument("--train", default="hpc_outputs/train/train_smoke.jsonl")
    ap.add_argument("--eval", default="hpc_outputs/train/eval_smoke.jsonl")
    args = ap.parse_args()

    rows = [{"text": t, "label": 0} for t in _BENIGN] + [{"text": t, "label": 1} for t in _HAZARD]
    split = int(0.75 * len(rows))
    # interleave so each split has both classes
    interleaved = []
    for b, h in zip(_BENIGN, _HAZARD):
        interleaved.append({"text": b, "label": 0})
        interleaved.append({"text": h, "label": 1})
    _write(args.train, interleaved[:split])
    _write(args.eval, interleaved[split:])
    print(f"wrote {split} train rows to {args.train} and {len(interleaved) - split} eval rows to {args.eval}")


if __name__ == "__main__":
    main()
