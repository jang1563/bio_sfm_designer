"""external HPC-side generative SFM runner TEMPLATE.

Plug in your generator (RFdiffusion / ProteinMPNN / ESM) where marked and write one candidate
record per line:
    {"id": "<unique>", "representation": "<amino-acid sequence or backbone ref>", "regime": "monomer"}

RUNS ON EXTERNAL HPC (GPU) inside the generator's conda env. The local PrecomputedGenerator
(src/bio_sfm_designer/generate/precomputed.py) consumes the output offline — same pattern as
predict/structure.py's Boltz-2 records. Designs are NOT trusted/synthesized here: the local
trust gate routes them and the safety screen (PrecomputedScreen) gates them before synth.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterator


def generate(spec_path: str, n: int) -> Iterator[dict]:
    """TODO: load `spec_path` and call the generative SFM on this node, yielding `n` candidate
    dicts of the shape documented above. This stub is intentionally unimplemented because the
    invocation is generator- and env-specific (RFdiffusion vs ProteinMPNN vs ESM)."""
    raise NotImplementedError(
        "Plug in the generative SFM (RFdiffusion/ProteinMPNN/ESM) here and yield candidate dicts."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="external HPC generative-SFM runner (template)")
    ap.add_argument("--spec", required=True, help="objective/spec file (JSON or YAML)")
    ap.add_argument("--n", type=int, default=32, help="number of candidates to generate")
    ap.add_argument("--out", required=True, help="candidates JSONL output path")
    args = ap.parse_args()

    n = 0
    with open(args.out, "w") as fh:
        for cand in generate(args.spec, args.n):
            fh.write(json.dumps(cand, sort_keys=True) + "\n")
            n += 1
    print(f"wrote {n} candidates to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
