"""Cayuga-side DeBERTa biosafety screen runner.

Reads candidate intents (JSONL: one {"id": ..., "text": ...} per line), scores each with the
existing constitutional-bioguard DeBERTa (prompt-side intent screen), and writes verdicts
JSONL: {"id": ..., "flag": bool, "reason": str, "score": float|None}.

RUNS ON CAYUGA (needs torch + DeBERTa weights, already installed there) — not locally. The
local SafetyScreen consumes the synced verdicts offline (the same pattern as M1's Boltz-2
records). This produces a triage FLAG for human review; it never makes the trust-routing
decision (the external gate does that).
"""

from __future__ import annotations

import argparse
import json
import sys


def _load_guard():
    from constitutional_bioguard.dual_mode import DualModeGuard  # Cayuga env only
    return DualModeGuard()


def main() -> None:
    ap = argparse.ArgumentParser(description="Cayuga DeBERTa screen runner")
    ap.add_argument("--candidates", required=True, help="JSONL: one {id, text} per line")
    ap.add_argument("--out", required=True, help="verdicts JSONL output path")
    args = ap.parse_args()

    guard = _load_guard()
    rows = [json.loads(line) for line in open(args.candidates) if line.strip()]
    n = 0
    with open(args.out, "w") as fh:
        for r in rows:
            verdict = guard.classify(str(r.get("text", "")))  # prompt-side intent screen
            flag = bool(getattr(verdict, "joint_flag", False) or getattr(verdict, "prompt_flag", False))
            fh.write(json.dumps({
                "id": r.get("id"),
                "flag": flag,
                "reason": str(getattr(verdict, "joint_reason", getattr(verdict, "prompt_reason", ""))),
                "score": getattr(verdict, "response_score", None),
            }, sort_keys=True) + "\n")
            n += 1
    print(f"wrote {n} verdicts to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
