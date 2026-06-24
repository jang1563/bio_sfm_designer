"""Cayuga-side DeBERTa biosafety screen runner.

Reads candidate intents (JSONL: one {"id": ..., "text": ...} per line), scores each with a
constitutional-bioguard DeBERTa, and writes verdicts JSONL: {"id", "flag", "reason", "score"}
for the local safety.PrecomputedScreen to consume offline (the M1 records pattern). Produces a
triage FLAG for human review; never makes the trust-routing decision.

Two modes:
  --model DIR : score with a local sequence-classification model dir directly
                (p_unsafe = softmax[..., -1]). PROVEN on Cayuga with
                models/deberta_bioguard_v8bd (benign ~0.06-0.23, hazardous ~0.99).
  (default)   : constitutional_bioguard DualModeGuard prompt-side intent screen (needs the
                pdual_v3 + v8b model dirs present).

RUNS ON CAYUGA (needs torch + weights). See run_screen_deberta.sbatch for the exact env.
"""

from __future__ import annotations

import argparse
import json
import sys


def _classify_with_model_dir(model_dir, texts, threshold):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
    out = []
    with torch.no_grad():
        for t in texts:
            enc = tok(t, truncation=True, max_length=512, return_tensors="pt")
            p_unsafe = float(torch.softmax(model(**enc).logits, dim=-1)[0][-1])  # last class = unsafe
            out.append((p_unsafe >= threshold, f"deberta p_unsafe={p_unsafe:.3f}", round(p_unsafe, 4)))
    return out


def _load_guard():
    from constitutional_bioguard.dual_mode import DualModeGuard  # Cayuga env only
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
    ap = argparse.ArgumentParser(description="Cayuga DeBERTa screen runner")
    ap.add_argument("--candidates", required=True, help="JSONL: one {id, text} per line")
    ap.add_argument("--out", required=True, help="verdicts JSONL output path")
    ap.add_argument("--model", default=None, help="local sequence-classification model dir (direct mode)")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.candidates) if line.strip()]
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
