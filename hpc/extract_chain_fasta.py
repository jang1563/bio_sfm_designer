"""Extract a modeled PDB chain sequence as FASTA for target-MSA generation.

The M6c complex workflow reuses one fixed target MSA across many redesigned binders.
This helper makes that first artifact deterministic: read the prepared two-chain
PDB, extract the modeled residues for the fixed target chain, and write the exact
sequence that should be used to generate the target `.a3m`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

_AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    # Common modified residues that still correspond to a standard modeled aa.
    "MSE": "M", "SEC": "C", "PYL": "K", "MLY": "K", "CSO": "C",
    "SEP": "S", "TPO": "T", "PTR": "Y", "HYP": "P", "KCX": "K",
    "LLP": "K", "CME": "C",
}

Residue = Tuple[Tuple[str, str, str], str, str]


def _is_atom(line: str) -> bool:
    return line[:6].strip() in ("ATOM", "HETATM")


def _is_ca(line: str) -> bool:
    return _is_atom(line) and line[12:16].strip() == "CA" and line[16] in (" ", "A")


def _res_uid(line: str) -> Tuple[str, str, str]:
    return (line[21], line[22:26].strip(), line[26].strip())


def extract_chain_sequence(pdb: str, chain: str, *, allow_unknown: bool = False) -> Dict[str, object]:
    residues: List[Residue] = []
    seen = set()
    unknown = []
    with open(pdb) as fh:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            if not _is_ca(line) or line[21] != chain:
                continue
            uid = _res_uid(line)
            if uid in seen:
                continue
            seen.add(uid)
            resname = line[17:20].strip()
            aa = _AA3_TO_1.get(resname)
            if aa is None:
                if not allow_unknown:
                    unknown.append({"resname": resname, "resseq": uid[1], "icode": uid[2]})
                    continue
                aa = "X"
            residues.append((uid, resname, aa))
    if unknown:
        raise ValueError(f"unknown residue(s) in chain {chain}: {unknown[:5]}")
    if not residues:
        raise ValueError(f"chain {chain!r} has no modeled CA residues in {pdb}")
    seq = "".join(aa for _, _, aa in residues)
    return {
        "pdb": os.path.abspath(pdb),
        "pdb_sha256": _sha256_file(pdb),
        "chain": chain,
        "length": len(seq),
        "sequence": seq,
        "first_residue": residues[0][0][1],
        "last_residue": residues[-1][0][1],
        "unknown_allowed": allow_unknown,
    }


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_fasta(path: str, seq_id: str, seq: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f">{seq_id}\n")
        for i in range(0, len(seq), 80):
            fh.write(seq[i:i + 80] + "\n")


def main(argv=None) -> Dict[str, object]:
    ap = argparse.ArgumentParser(description="extract one modeled PDB chain as FASTA")
    ap.add_argument("--pdb", required=True)
    ap.add_argument("--chain", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id", default=None, help="FASTA id; default=<pdb_stem>_<chain>")
    ap.add_argument("--report", default=None, help="optional JSON report")
    ap.add_argument("--expect-seq", default=None, help="optional exact sequence sanity check")
    ap.add_argument("--allow-unknown", action="store_true")
    args = ap.parse_args(argv)

    rep = extract_chain_sequence(args.pdb, args.chain, allow_unknown=args.allow_unknown)
    if args.expect_seq and rep["sequence"] != args.expect_seq:
        raise ValueError(f"extracted sequence length/content does not match --expect-seq "
                         f"({rep['length']} vs {len(args.expect_seq)})")
    seq_id = args.id or f"{os.path.splitext(os.path.basename(args.pdb))[0]}_{args.chain}"
    _write_fasta(args.out, seq_id, str(rep["sequence"]))
    rep = {**rep, "fasta_id": seq_id, "out": os.path.abspath(args.out), "out_sha256": _sha256_file(args.out)}
    text = json.dumps(rep, indent=2, sort_keys=True)
    print(text)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w") as fh:
            fh.write(text + "\n")
    return rep


if __name__ == "__main__":
    main()
