"""external HPC-side ProteinMPNN generate runner (M4, generate stage).

Designs sequences for a FIXED backbone PDB with ProteinMPNN (inverse folding) and writes a
candidates JSONL in the designer's schema for the local PrecomputedGenerator to consume offline
(the M1 records pattern, generate side). ProteinMPNN is MIT and CPU-capable; its weights ship in
the repo, so there is nothing gated to download.

Output rows: {"id", "representation"(=designed sequence), "regime", "parent_id", "meta"} where
meta carries the backbone id and ProteinMPNN's own score / seq_recovery / sampling temperature.

RUNS ON EXTERNAL HPC (needs the ProteinMPNN checkout + torch). See run_generate_proteinmpnn.sbatch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


def _parse_fasta(path):
    """Yield (header, sequence). ProteinMPNN writes the native sequence first, then the designs."""
    header, seq = None, []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(seq)
                header, seq = line[1:], []
            elif line:
                seq.append(line)
    if header is not None:
        yield header, "".join(seq)


def _meta_from_header(h):
    """Pull score / global_score / seq_recovery / sample / T from a ProteinMPNN design header."""
    out = {}
    for key in ("score", "global_score", "seq_recovery", "sample", "T"):
        m = re.search(rf"\b{key}=([-\d.]+)", h)
        if m:
            out[key] = float(m.group(1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="ProteinMPNN -> candidates.jsonl for the designer")
    ap.add_argument("--mpnn-dir", default=os.path.expanduser("~/ProteinMPNN"))
    ap.add_argument("--pdb", required=True, help="backbone PDB to design on")
    ap.add_argument("--chains", default="A", help="chain(s) to design, space-separated (e.g. 'A' or 'A B')")
    ap.add_argument("--num-seq", type=int, default=8)
    ap.add_argument("--temp", default="0.2", help="ProteinMPNN sampling temperature")
    ap.add_argument("--seed", type=int, default=37)
    ap.add_argument("--objective", default="stability")
    ap.add_argument("--target", default="")
    ap.add_argument("--out", required=True, help="candidates.jsonl output path")
    ap.add_argument("--python", default=sys.executable, help="python that imports torch+numpy")
    args = ap.parse_args()

    pdb_id = os.path.splitext(os.path.basename(args.pdb))[0]
    regime = "monomer" if len(args.chains.split()) <= 1 else "complex"
    work = os.path.join(os.path.dirname(os.path.abspath(args.out)) or ".", f"_mpnn_{pdb_id}")
    os.makedirs(work, exist_ok=True)

    cmd = [args.python, os.path.join(args.mpnn_dir, "protein_mpnn_run.py"),
           "--pdb_path", args.pdb, "--pdb_path_chains", args.chains,
           "--out_folder", work, "--num_seq_per_target", str(args.num_seq),
           "--sampling_temp", args.temp, "--seed", str(args.seed), "--batch_size", "1"]
    subprocess.run(cmd, check=True, cwd=args.mpnn_dir)

    fasta = os.path.join(work, "seqs", f"{pdb_id}.fa")
    records = list(_parse_fasta(fasta))
    designs = records[1:]  # records[0] is the native input sequence; the rest are designs
    n = 0
    with open(args.out, "w") as out:
        for i, (header, seq) in enumerate(designs):
            meta = {"objective": args.objective, "target": args.target,
                    "backbone": pdb_id, "generator": "proteinmpnn", **_meta_from_header(header)}
            row = {"id": f"{args.objective}-mpnn-{pdb_id}-{i}", "representation": seq,
                   "regime": regime, "parent_id": None, "meta": meta}
            out.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    native_len = len(records[0][1]) if records else 0
    print(f"wrote {n} candidates to {args.out} (backbone {pdb_id}, {regime}, {native_len} aa)", file=sys.stderr)


if __name__ == "__main__":
    main()
