"""external HPC-side DeBERTa biosafety screen runner.

Reads candidate intents (JSONL: one {"id": ..., "text": ...} per line), scores each with a
constitutional-bioguard DeBERTa, and writes verdicts JSONL: {"id", "flag", "reason", "score"}
for the local safety.PrecomputedScreen to consume offline (the M1 records pattern). Produces a
triage FLAG for human review; never makes the trust-routing decision.

Two modes:
  --model DIR : score with a local sequence-classification model dir directly
                (p_unsafe = softmax[..., -1]). PROVEN on external HPC with
                models/deberta_bioguard_v8bd (benign ~0.06-0.23, hazardous ~0.99).
  (default)   : constitutional_bioguard DualModeGuard prompt-side intent screen (needs the
                pdual_v3 + v8b model dirs present).

RUNS ON EXTERNAL HPC (needs torch + weights). See run_screen_deberta.sbatch for a generic wrapper.
"""

from __future__ import annotations

import argparse
import json
import sys


def _classify_with_model_dir(model_dir, texts, threshold):
    import math

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
    out = []
    n_nonfinite = 0
    with torch.no_grad():
        for t in texts:
            enc = tok(t, truncation=True, max_length=512, return_tensors="pt")
            p_unsafe = float(torch.softmax(model(**enc).logits, dim=-1)[0][-1])  # last class = unsafe
            if not math.isfinite(p_unsafe):
                n_nonfinite += 1
                # fail-closed: NaN/inf -> flag for human review, valid JSON (no bare NaN)
                out.append((True, "deberta returned non-finite score -> human review", None))
            else:
                out.append((p_unsafe >= threshold, f"deberta p_unsafe={p_unsafe:.3f}", round(p_unsafe, 4)))
    if n_nonfinite:
        print(f"WARNING: {n_nonfinite}/{len(texts)} predictions were non-finite — head is likely "
              f"under-trained or mis-initialized; treating those as flagged for human review.",
              file=__import__("sys").stderr)
    return out


def _load_guard():
    from constitutional_bioguard.dual_mode import DualModeGuard  # external HPC env only
    return DualModeGuard()


def _classify_with_dualmode(texts):
    guard = _load_guard()
    out = []
    for t in texts:
        v = guard.classify(t)  # prompt-side intent screen
        flag = bool(getattr(v, "joint_flag", False) or getattr(v, "prompt_flag", False))
        out.append((flag, str(getattr(v, "joint_reason", getattr(v, "prompt_reason", ""))),
                    getattr(v, "response_score", None)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="external HPC DeBERTa screen runner")
    ap.add_argument("--candidates", required=True, help="JSONL: one {id, text} per line")
    ap.add_argument("--out", required=True, help="verdicts JSONL output path")
    ap.add_argument("--model", default=None, help="local sequence-classification model dir (direct mode)")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    with open(args.candidates) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    texts = [str(r.get("text", "")) for r in rows]
    results = (_classify_with_model_dir(args.model, texts, args.threshold)
               if args.model else _classify_with_dualmode(texts))

    with open(args.out, "w") as fh:
        for r, (flag, reason, score) in zip(rows, results):
            fh.write(json.dumps({"id": r.get("id"), "flag": bool(flag), "reason": reason, "score": score},
                                sort_keys=True) + "\n")
    print(f"wrote {len(rows)} verdicts to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
