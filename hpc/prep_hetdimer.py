"""Prepare and validate a two-chain heterodimer backbone for the M6c complex workflow.

This is a cheap local preflight before spending ProteinMPNN/Boltz compute cycles:
strip a source PDB down to target+binder chains, then reject obvious bad targets such as
missing chains, chain gaps, or chains that do not form a CA-contacting interface.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Dict, Iterable, List, Optional, Tuple

_MODIFIED_AA_TO_STANDARD = {
    "MSE": "MET", "SEC": "CYS", "PYL": "LYS", "MLY": "LYS",
    "CSO": "CYS", "SEP": "SER", "TPO": "THR", "PTR": "TYR",
    "HYP": "PRO", "KCX": "LYS", "LLP": "LYS", "CME": "CYS",
}
ResidueCA = Tuple[Tuple[str, str, str], Tuple[float, float, float]]


def _is_atom(line: str) -> bool:
    return line[:6].strip() in ("ATOM", "HETATM")


def _is_supported_ca(line: str) -> bool:
    if not _is_atom(line) or line[12:16].strip() != "CA":
        return False
    if line[:6].strip() == "HETATM" and line[17:20].strip() not in _MODIFIED_AA_TO_STANDARD:
        return False
    return line[16] in (" ", "A")


def _chain(line: str) -> str:
    return line[21]


def _res_uid(line: str) -> Tuple[str, str, str]:
    return (_chain(line), line[22:26].strip(), line[26].strip())


def _coord(line: str) -> Tuple[float, float, float]:
    return (float(line[30:38]), float(line[38:46]), float(line[46:54]))


def _load_chain_cas(path: str, chains: Iterable[str]) -> Dict[str, List[ResidueCA]]:
    keep = set(chains)
    out: Dict[str, List[ResidueCA]] = {c: [] for c in keep}
    seen = set()
    with open(path) as fh:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            if not _is_supported_ca(line) or _chain(line) not in keep:
                continue
            uid = _res_uid(line)
            if uid in seen:
                continue
            seen.add(uid)
            out[_chain(line)].append((uid, _coord(line)))
    return out


def _numbering_gaps(residues: List[ResidueCA]) -> List[Dict[str, int]]:
    gaps = []
    prev: Optional[int] = None
    for uid, _ in residues:
        try:
            cur = int(uid[1])
        except ValueError:
            prev = None
            continue
        if prev is not None and cur > prev + 1:
            gaps.append({"after": prev, "before": cur, "missing": cur - prev - 1})
        prev = cur
    return gaps


def _dist(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _interface(cas_a: List[ResidueCA],
               cas_b: List[ResidueCA],
               cutoff: float) -> Tuple[int, Optional[float]]:
    contacts = 0
    min_dist: Optional[float] = None
    for _, ca in cas_a:
        for _, cb in cas_b:
            d = _dist(ca, cb)
            min_dist = d if min_dist is None else min(min_dist, d)
            if d <= cutoff:
                contacts += 1
    return contacts, min_dist


def _normalized_protein_atom(line: str) -> Tuple[Optional[str], bool]:
    record = line[:6].strip()
    if record == "ATOM":
        return line, False
    if record != "HETATM":
        return None, False
    resname = line[17:20].strip()
    standard = _MODIFIED_AA_TO_STANDARD.get(resname)
    if standard is None:
        return None, False
    normalized = "ATOM  " + line[6:17] + f"{standard:>3}" + line[20:]
    if resname == "MSE" and normalized[12:16].strip() == "SE":
        normalized = normalized[:12] + f"{'SD':>4}" + normalized[16:]
        if len(normalized) >= 78:
            normalized = normalized[:76] + " S" + normalized[78:]
    return normalized, True


def _write_selected_atoms(src_pdb: str, dst_pdb: str,
                          chains: Iterable[str]) -> Tuple[int, int]:
    keep = set(chains)
    n = 0
    normalized_modified = 0
    with open(src_pdb) as fh, open(dst_pdb, "w") as out:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            if not _is_atom(line) or _chain(line) not in keep:
                continue
            selected, was_modified = _normalized_protein_atom(line)
            if selected is None:
                continue
            out.write(selected)
            n += 1
            normalized_modified += int(was_modified)
        out.write("END\n")
    return n, normalized_modified


def prepare_hetdimer(src_pdb: str, target_chain: str, binder_chain: str, out_pdb: str,
                     contact_cutoff: float = 8.0, min_contacts: int = 1,
                     min_residues: int = 20, allow_numbering_gaps: bool = False) -> Dict[str, object]:
    if target_chain == binder_chain:
        raise ValueError("target_chain and binder_chain must be different")
    if os.path.abspath(src_pdb) == os.path.abspath(out_pdb):
        raise ValueError("out_pdb must be different from src_pdb")

    cas = _load_chain_cas(src_pdb, [target_chain, binder_chain])
    target = cas[target_chain]
    binder = cas[binder_chain]
    if not target:
        raise ValueError(f"target chain {target_chain!r} has no CA residues")
    if not binder:
        raise ValueError(f"binder chain {binder_chain!r} has no CA residues")
    if len(target) < min_residues:
        raise ValueError(f"target chain {target_chain!r} has only {len(target)} CA residues (< {min_residues})")
    if len(binder) < min_residues:
        raise ValueError(f"binder chain {binder_chain!r} has only {len(binder)} CA residues (< {min_residues})")

    target_gaps = _numbering_gaps(target)
    binder_gaps = _numbering_gaps(binder)
    if not allow_numbering_gaps and (target_gaps or binder_gaps):
        raise ValueError(f"residue-numbering gaps detected: target={target_gaps}, binder={binder_gaps}")

    contacts, min_dist = _interface(target, binder, contact_cutoff)
    if contacts < min_contacts:
        md = "n/a" if min_dist is None else f"{min_dist:.2f}"
        raise ValueError(f"interface contacts below threshold: {contacts} < {min_contacts} "
                         f"(cutoff={contact_cutoff}, min_ca_distance={md})")

    os.makedirs(os.path.dirname(os.path.abspath(out_pdb)) or ".", exist_ok=True)
    atom_records, modified_records = _write_selected_atoms(
        src_pdb, out_pdb, [target_chain, binder_chain]
    )
    return {
        "source_pdb": os.path.abspath(src_pdb),
        "output_pdb": os.path.abspath(out_pdb),
        "target_chain": target_chain,
        "binder_chain": binder_chain,
        "target_ca_residues": len(target),
        "binder_ca_residues": len(binder),
        "target_numbering_gaps": target_gaps,
        "binder_numbering_gaps": binder_gaps,
        "contact_cutoff": contact_cutoff,
        "min_contacts_required": min_contacts,
        "ca_interface_contacts": contacts,
        "min_ca_distance": None if min_dist is None else round(min_dist, 3),
        "atom_records_written": atom_records,
        "modified_atom_records_normalized": modified_records,
    }


def main(argv=None) -> Dict[str, object]:
    ap = argparse.ArgumentParser(description="strip and validate a two-chain heterodimer PDB")
    ap.add_argument("--pdb", required=True, help="source PDB")
    ap.add_argument("--target-chain", required=True, help="fixed target chain")
    ap.add_argument("--binder-chain", required=True, help="binder/design chain")
    ap.add_argument("--out", required=True, help="prepared two-chain PDB")
    ap.add_argument("--report", default=None, help="optional JSON validation report")
    ap.add_argument("--contact-cutoff", type=float, default=8.0)
    ap.add_argument("--min-contacts", type=int, default=1)
    ap.add_argument("--min-residues", type=int, default=20)
    ap.add_argument("--allow-numbering-gaps", action="store_true",
                    help="allow residue-numbering gaps; use only after manual inspection")
    args = ap.parse_args(argv)

    rep = prepare_hetdimer(args.pdb, args.target_chain, args.binder_chain, args.out,
                           contact_cutoff=args.contact_cutoff, min_contacts=args.min_contacts,
                           min_residues=args.min_residues,
                           allow_numbering_gaps=args.allow_numbering_gaps)
    text = json.dumps(rep, indent=2, sort_keys=True)
    print(text)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w") as fh:
            fh.write(text + "\n")
    return rep


if __name__ == "__main__":
    main()
