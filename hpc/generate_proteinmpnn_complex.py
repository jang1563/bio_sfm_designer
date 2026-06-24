"""Cayuga-side ProteinMPNN COMPLEX generate runner (M6c-lite, binder/interface de-risk).

Redesigns ONE chain (the binder) of a fixed two-chain complex backbone against the OTHER chain
(the target: sequence AND structure held fixed) using ProteinMPNN's multichain path, and writes a
candidates JSONL carrying BOTH sequences so Boltz can refold the whole COMPLEX. This is the
interface analog of generate_proteinmpnn.py -- it reuses the shipped tools, NO RFdiffusion.

Flow (ProteinMPNN multichain): strip the PDB to target+binder chains -> parse_multiple_chains.py ->
assign_fixed_chains.py --chain_list "<binder>" (designs the binder, fixes the target) ->
protein_mpnn_run.py. The output FASTA holds ONLY the designed (binder) chain.

Output rows: {"id", "representation"(=designed BINDER seq), "target_seq"(=fixed TARGET seq),
"regime"="complex", "parent_id", "meta"(objective/backbone/chains/score/...)}.

RUNS ON CAYUGA (ProteinMPNN checkout + torch). The parse/assign/run steps are CPU (login-ok).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

_STD_AA = set("ACDEFGHIKLMNPQRSTVWY")


def _parse_fasta(path):
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
    out = {}
    for key in ("score", "global_score", "seq_recovery", "sample", "T"):
        m = re.search(rf"\b{key}=([-\d.]+)", h)
        if m:
            out[key] = float(m.group(1))
    return out


def _strip_chains(src_pdb, chains, dst_pdb):
    keep = set(chains)
    with open(src_pdb) as fh, open(dst_pdb, "w") as out:
        for ln in fh:
            if ln[:4] == "ATOM" and ln[21] in keep:
                out.write(ln)


def main() -> None:
    ap = argparse.ArgumentParser(description="ProteinMPNN complex (binder) design -> candidates.jsonl")
    ap.add_argument("--mpnn-dir", default=os.path.expanduser("~/ProteinMPNN"))
    ap.add_argument("--pdb", required=True, help="complex backbone PDB")
    ap.add_argument("--target-chain", default="A", help="chain held FIXED (the target)")
    ap.add_argument("--design-chain", default="C", help="chain to REDESIGN (the binder)")
    ap.add_argument("--num-seq", type=int, default=8)
    ap.add_argument("--temp", default="0.2", help="ProteinMPNN sampling temperature")
    ap.add_argument("--seed", type=int, default=37)
    ap.add_argument("--objective", default="binder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=sys.executable, help="python that imports torch+numpy")
    args = ap.parse_args()

    pdb_id = os.path.splitext(os.path.basename(args.pdb))[0]
    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    work = os.path.join(outdir, f"_mpnnX_{pdb_id}")
    pdbs = os.path.join(work, "pdbs")
    os.makedirs(pdbs, exist_ok=True)

    stripped = os.path.join(pdbs, f"{pdb_id}_{args.target_chain}{args.design_chain}.pdb")
    _strip_chains(args.pdb, [args.target_chain, args.design_chain], stripped)
    name = os.path.splitext(os.path.basename(stripped))[0]

    hs = os.path.join(args.mpnn_dir, "helper_scripts")
    parsed = os.path.join(work, "parsed.jsonl")
    chainid = os.path.join(work, "chainid.jsonl")
    subprocess.run([args.python, os.path.join(hs, "parse_multiple_chains.py"),
                    f"--input_path={pdbs}", f"--output_path={parsed}"], check=True)
    subprocess.run([args.python, os.path.join(hs, "assign_fixed_chains.py"),
                    f"--input_path={parsed}", f"--output_path={chainid}",
                    "--chain_list", args.design_chain], check=True)
    subprocess.run([args.python, os.path.join(args.mpnn_dir, "protein_mpnn_run.py"),
                    "--jsonl_path", parsed, "--chain_id_jsonl", chainid,
                    "--out_folder", work, "--num_seq_per_target", str(args.num_seq),
                    "--sampling_temp", args.temp, "--seed", str(args.seed), "--batch_size", "1"],
                   check=True, cwd=args.mpnn_dir)

    parsed_row = json.loads(open(parsed).read().splitlines()[0])
    target_seq = parsed_row[f"seq_chain_{args.target_chain}"]
    if set(target_seq) - _STD_AA:
        print(f"WARNING: target chain {args.target_chain} has non-standard residues "
              f"{set(target_seq) - _STD_AA} -- Boltz may reject it", file=sys.stderr)

    fasta = os.path.join(work, "seqs", f"{name}.fa")
    records = list(_parse_fasta(fasta))
    designs = records[1:]  # records[0] is the native binder sequence
    n = 0
    with open(args.out, "w") as out:
        for i, (header, seq) in enumerate(designs):
            if set(seq) - _STD_AA:
                print(f"  skip design {i}: non-standard residues {set(seq) - _STD_AA}", file=sys.stderr)
                continue
            meta = {"objective": args.objective, "backbone": pdb_id, "generator": "proteinmpnn",
                    "target_chain": args.target_chain, "design_chain": args.design_chain,
                    **_meta_from_header(header)}
            row = {"id": f"{args.objective}-mpnnX-{pdb_id}-{i}", "representation": seq,
                   "target_seq": target_seq, "regime": "complex", "parent_id": None, "meta": meta}
            out.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    blen = len(designs[0][1]) if designs else 0
    print(f"wrote {n} complex candidates to {args.out} (backbone {pdb_id} "
          f"{args.target_chain}+{args.design_chain}, target {len(target_seq)}aa, binder {blen}aa)", file=sys.stderr)


if __name__ == "__main__":
    main()
