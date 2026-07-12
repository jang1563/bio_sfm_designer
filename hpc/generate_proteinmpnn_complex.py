"""external HPC-side ProteinMPNN COMPLEX generate runner (M6c-lite, binder/interface de-risk).

Redesigns ONE chain (the binder) of a fixed two-chain complex backbone against the OTHER chain
(the target: sequence AND structure held fixed) using ProteinMPNN's multichain path, and writes a
candidates JSONL carrying BOTH sequences so Boltz can refold the whole COMPLEX. This is the
interface analog of generate_proteinmpnn.py -- it reuses the shipped tools, NO RFdiffusion.

Flow (ProteinMPNN multichain): strip the PDB to target+binder chains -> parse_multiple_chains.py ->
assign_fixed_chains.py --chain_list "<binder>" (designs the binder, fixes the target) ->
protein_mpnn_run.py. The output FASTA holds ONLY the designed (binder) chain.

Output rows: {"id", "representation"(=designed BINDER seq), "target_seq"(=fixed TARGET seq),
"regime"="complex", "parent_id", "meta"(objective/backbone/complex_target_id/chains/score/...)}.

RUNS ON EXTERNAL HPC (ProteinMPNN checkout + torch). The parse/assign/run steps are CPU (login-ok).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

_STD_AA = set("ACDEFGHIKLMNPQRSTVWY")
_AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "C", "PYL": "K", "MLY": "K", "CSO": "C",
    "SEP": "S", "TPO": "T", "PTR": "Y", "HYP": "P", "KCX": "K",
    "LLP": "K", "CME": "C",
}
_MODIFIED_AA_TO_STANDARD = {
    "MSE": "MET", "SEC": "CYS", "PYL": "LYS", "MLY": "LYS",
    "CSO": "CYS", "SEP": "SER", "TPO": "THR", "PTR": "TYR",
    "HYP": "PRO", "KCX": "LYS", "LLP": "LYS", "CME": "CYS",
}


def _safe_token(text):
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("._")
    return token or "run"


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
            if ln[:6].strip() == "ATOM" and ln[21] in keep:
                out.write(ln)
                continue
            if (ln[:6].strip() == "HETATM" and ln[21] in keep
                    and ln[17:20].strip() in _MODIFIED_AA_TO_STANDARD):
                resname = ln[17:20].strip()
                standard = _MODIFIED_AA_TO_STANDARD[resname]
                normalized = "ATOM  " + ln[6:17] + f"{standard:>3}" + ln[20:]
                if resname == "MSE" and normalized[12:16].strip() == "SE":
                    normalized = normalized[:12] + f"{'SD':>4}" + normalized[16:]
                    if len(normalized) >= 78:
                        normalized = normalized[:76] + " S" + normalized[78:]
                out.write(normalized)


def _target_ca_sequence(pdb, chain):
    residues, seen = [], set()
    with open(pdb) as fh:
        for ln in fh:
            record = ln[:6].strip()
            if record not in ("ATOM", "HETATM"):
                continue
            if record == "HETATM" and ln[17:20].strip() not in _MODIFIED_AA_TO_STANDARD:
                continue
            if ln[21] != chain or ln[12:16].strip() != "CA" or ln[16] not in (" ", "A"):
                continue
            uid = (ln[21], ln[22:26].strip(), ln[26].strip())
            if uid in seen:
                continue
            seen.add(uid)
            resname = ln[17:20].strip()
            aa = _AA3_TO_1.get(resname)
            if aa is None:
                raise ValueError(f"unsupported target residue {resname!r} at {chain}{uid[1]}{uid[2]}")
            residues.append(aa)
    if not residues:
        raise ValueError(f"target chain {chain!r} has no modeled CA residues in {pdb}")
    return "".join(residues)


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
    ap.add_argument("--complex-id", default=None,
                    help="heterodimer target id to carry through candidate metadata")
    ap.add_argument("--id-prefix", default=None,
                    help="optional candidate-id prefix; use temp/batch-specific values for scale batches")
    ap.add_argument("--w2b-stage", choices=("fit", "certification", "test"), default=None)
    ap.add_argument("--w2b-seed-namespace", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=sys.executable, help="python that imports torch+numpy")
    args = ap.parse_args()
    if bool(args.w2b_stage) != bool(args.w2b_seed_namespace):
        ap.error("--w2b-stage and --w2b-seed-namespace must be provided together")
    if args.w2b_stage and not args.id_prefix:
        ap.error("W2b generation requires --id-prefix to keep candidate IDs disjoint across stages")

    pdb_id = os.path.splitext(os.path.basename(args.pdb))[0]
    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    out_stem = os.path.splitext(os.path.basename(args.out))[0]
    work = os.path.join(outdir, f"_mpnnX_{pdb_id}_{_safe_token(out_stem)}")
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

    with open(parsed) as fh:
        parsed_row = json.loads(fh.read().splitlines()[0])
    raw_target = parsed_row[f"seq_chain_{args.target_chain}"]
    parsed_target = "".join(c for c in raw_target if c in _STD_AA)
    # ProteinMPNN's parser can include terminal atom-only residues that have no CA backbone (observed in
    # 1QFW_BA). The Boltz label aligns against CA coordinates, so the folded target sequence must be the
    # CA-modeled sequence, matching hpc/extract_chain_fasta.py and the target-MSA query.
    target_seq = _target_ca_sequence(stripped, args.target_chain)
    if target_seq != parsed_target:
        print(f"NOTE: target chain {args.target_chain}: using CA-modeled target sequence "
              f"({len(target_seq)} aa) instead of ProteinMPNN parsed sequence ({len(parsed_target)} aa)",
              file=sys.stderr)

    fasta = os.path.join(work, "seqs", f"{name}.fa")
    records = list(_parse_fasta(fasta))
    designs = records[1:]  # records[0] is the native binder sequence
    n = 0
    id_token = args.complex_id or pdb_id
    with open(args.out, "w") as out:
        for i, (header, seq) in enumerate(designs):
            clean = "".join(c for c in seq if c in _STD_AA)   # drop unmodeled positions (same gap as native)
            meta = {"objective": args.objective, "backbone": pdb_id, "generator": "proteinmpnn",
                    "target_chain": args.target_chain, "design_chain": args.design_chain,
                    **_meta_from_header(header)}
            if args.complex_id:
                meta["complex_target_id"] = args.complex_id
            if args.id_prefix:
                meta["id_prefix"] = args.id_prefix
            row_id = f"{args.id_prefix}-{i}" if args.id_prefix else f"{args.objective}-mpnnX-{id_token}-{i}"
            row = {"id": row_id, "representation": clean,
                   "target_seq": target_seq, "regime": "complex", "parent_id": None, "meta": meta}
            if args.w2b_stage:
                row["w2b_stage"] = args.w2b_stage
                row["w2b_seed_namespace"] = args.w2b_seed_namespace
                meta["w2b_stage"] = args.w2b_stage
                meta["w2b_seed_namespace"] = args.w2b_seed_namespace
            out.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    blen = len(designs[0][1]) if designs else 0
    print(f"wrote {n} complex candidates to {args.out} (backbone {pdb_id} "
          f"{args.target_chain}+{args.design_chain}, target {len(target_seq)}aa, binder {blen}aa)", file=sys.stderr)


if __name__ == "__main__":
    main()
