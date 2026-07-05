"""Build a fresh local W2 target-discovery candidate pool.

This is a no-GPU, pre-MSA intake step. It fetches or reads source PDBs, scans
chain pairs, writes prepared heterodimer PDB/FASTA artifacts for structurally
admitted candidates, and emits a manifest that can later be passed to the
target-MSA precompute flow. It does not certify W2 and does not authorize a
Cayuga ProteinMPNN/Boltz submission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

_AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "C", "PYL": "K", "MLY": "K", "CSO": "C",
    "SEP": "S", "TPO": "T", "PTR": "Y", "HYP": "P", "KCX": "K",
    "LLP": "K", "CME": "C",
}

ResidueCA = Tuple[Tuple[str, str, str], str, str, Tuple[float, float, float]]


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return obj


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_atom(line: str) -> bool:
    return line[:6].strip() in ("ATOM", "HETATM")


def _is_supported_ca(line: str) -> bool:
    if not _is_atom(line) or line[12:16].strip() != "CA":
        return False
    if line[16] not in (" ", "A"):
        return False
    resname = line[17:20].strip()
    return line[:6].strip() == "ATOM" or resname in _AA3_TO_1


def _chain(line: str) -> str:
    return line[21]


def _res_uid(line: str) -> Tuple[str, str, str]:
    return (_chain(line), line[22:26].strip(), line[26].strip())


def _coord(line: str) -> Tuple[float, float, float]:
    return (float(line[30:38]), float(line[38:46]), float(line[46:54]))


def _load_chain_cas(path: str) -> Dict[str, List[ResidueCA]]:
    out: Dict[str, List[ResidueCA]] = {}
    seen = set()
    with open(path) as fh:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            if not _is_supported_ca(line):
                continue
            uid = _res_uid(line)
            if uid in seen:
                continue
            seen.add(uid)
            resname = line[17:20].strip()
            aa = _AA3_TO_1.get(resname, "X")
            out.setdefault(uid[0], []).append((uid, resname, aa, _coord(line)))
    return out


def _numbering_gaps(residues: List[ResidueCA]) -> List[Dict[str, int]]:
    gaps = []
    prev: Optional[int] = None
    for uid, _resname, _aa, _coord_value in residues:
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


def _interface(a: List[ResidueCA], b: List[ResidueCA], cutoff: float) -> Tuple[int, Optional[float]]:
    contacts = 0
    min_dist: Optional[float] = None
    for _uida, _res_a, _aa_a, ca in a:
        for _uidb, _res_b, _aa_b, cb in b:
            d = _dist(ca, cb)
            min_dist = d if min_dist is None else min(min_dist, d)
            if d <= cutoff:
                contacts += 1
    return contacts, min_dist


def _sequence(residues: List[ResidueCA]) -> str:
    return "".join(aa for _uid, _resname, aa, _coord_value in residues)


def _identity(a: str, b: str) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    return sum(1 for i in range(n) if a[i] == b[i]) / n


def _write_selected_atoms(src_pdb: str, dst_pdb: str, chains: Iterable[str]) -> int:
    keep = set(chains)
    n = 0
    with open(src_pdb) as fh, open(dst_pdb, "w") as out:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            if line.startswith("ATOM") and _chain(line) in keep:
                out.write(line)
                n += 1
        out.write("END\n")
    return n


def _write_fasta(path: str, fasta_id: str, seq: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f">{fasta_id}\n")
        for i in range(0, len(seq), 80):
            fh.write(seq[i:i + 80] + "\n")


def _fetch_pdb(rcsb_id: str, out: str) -> None:
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    url = f"https://files.rcsb.org/download/{rcsb_id.upper()}.pdb"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    if not data:
        raise ValueError(f"empty PDB response for {rcsb_id}")
    with open(out, "wb") as fh:
        fh.write(data)


def _seed_rows(seed_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    seeds = seed_config.get("seeds")
    if not isinstance(seeds, list):
        raise ValueError("seed config must contain a seeds list")
    rows = []
    for seed in seeds:
        if isinstance(seed, str):
            rows.append({"rcsb_id": seed})
        elif isinstance(seed, dict) and isinstance(seed.get("rcsb_id"), str):
            rows.append(dict(seed))
        else:
            raise ValueError(f"invalid seed entry: {seed!r}")
    return rows


def _screen_pdb_pairs(source_pdb: str, rcsb_id: str, *,
                      min_contacts: int,
                      min_chain_residues: int,
                      max_target_residues: int,
                      max_binder_residues: int,
                      max_sequence_identity: float,
                      contact_cutoff: float) -> List[Dict[str, Any]]:
    chains = _load_chain_cas(source_pdb)
    candidates = []
    for chain_a in sorted(chains):
        for chain_b in sorted(chains):
            if chain_a >= chain_b:
                continue
            residues_a = chains[chain_a]
            residues_b = chains[chain_b]
            if len(residues_a) >= len(residues_b):
                target_chain, binder_chain = chain_a, chain_b
                target, binder = residues_a, residues_b
            else:
                target_chain, binder_chain = chain_b, chain_a
                target, binder = residues_b, residues_a
            contacts, min_dist = _interface(target, binder, contact_cutoff)
            target_seq = _sequence(target)
            binder_seq = _sequence(binder)
            target_gaps = _numbering_gaps(target)
            binder_gaps = _numbering_gaps(binder)
            seq_ident = _identity(target_seq, binder_seq)
            failures = []
            if len(target) < min_chain_residues:
                failures.append("target_too_short")
            if len(binder) < min_chain_residues:
                failures.append("binder_too_short")
            if len(target) > max_target_residues:
                failures.append("target_too_long")
            if len(binder) > max_binder_residues:
                failures.append("binder_too_long")
            if target_gaps:
                failures.append("target_numbering_gaps")
            if binder_gaps:
                failures.append("binder_numbering_gaps")
            if contacts < min_contacts:
                failures.append("insufficient_interface_contacts")
            if seq_ident > max_sequence_identity:
                failures.append("high_chain_sequence_identity")
            candidate_id = f"{rcsb_id.upper()}_{target_chain}{binder_chain}"
            candidates.append({
                "complex_target_id": candidate_id,
                "rcsb_id": rcsb_id.upper(),
                "source_pdb": source_pdb,
                "target_chain": target_chain,
                "binder_chain": binder_chain,
                "target_ca_residues": len(target),
                "binder_ca_residues": len(binder),
                "target_numbering_gaps": target_gaps,
                "binder_numbering_gaps": binder_gaps,
                "ca_interface_contacts": contacts,
                "min_ca_distance": None if min_dist is None else round(min_dist, 3),
                "chain_sequence_identity": round(seq_ident, 3),
                "admitted_structural_candidate": not failures,
                "screen_failures": failures,
                "_target_sequence": target_seq,
            })
    return candidates


def _materialize_candidate(candidate: Dict[str, Any], *, out_dir: str,
                           records_dir: str) -> Dict[str, Any]:
    target_id = str(candidate["complex_target_id"])
    target_dir = os.path.join(out_dir, target_id)
    os.makedirs(target_dir, exist_ok=True)
    prepared_pdb = os.path.join(target_dir, f"prepared_{target_id}.pdb")
    prep_report = os.path.join(target_dir, f"prepared_{target_id}.report.json")
    fasta = os.path.join(target_dir, f"{target_id}_{candidate['target_chain']}.fasta")
    fasta_report = fasta + ".report.json"
    target_msa = os.path.join(target_dir, f"{target_id}_{candidate['target_chain']}.a3m")
    target_msa_report = target_msa + ".report.json"
    atoms = _write_selected_atoms(
        str(candidate["source_pdb"]),
        prepared_pdb,
        [str(candidate["target_chain"]), str(candidate["binder_chain"])],
    )
    prep = {
        "source_pdb": os.path.abspath(str(candidate["source_pdb"])),
        "output_pdb": os.path.abspath(prepared_pdb),
        "target_chain": candidate["target_chain"],
        "binder_chain": candidate["binder_chain"],
        "target_ca_residues": candidate["target_ca_residues"],
        "binder_ca_residues": candidate["binder_ca_residues"],
        "target_numbering_gaps": candidate["target_numbering_gaps"],
        "binder_numbering_gaps": candidate["binder_numbering_gaps"],
        "contact_cutoff": 8.0,
        "min_contacts_required": 20,
        "ca_interface_contacts": candidate["ca_interface_contacts"],
        "min_ca_distance": candidate["min_ca_distance"],
        "atom_records_written": atoms,
    }
    _write_json(prep_report, prep)
    fasta_id = f"{target_id}_{candidate['target_chain']}"
    _write_fasta(fasta, fasta_id, str(candidate["_target_sequence"]))
    fasta_rep = {
        "pdb": prepared_pdb,
        "pdb_abs": os.path.abspath(prepared_pdb),
        "pdb_sha256": _sha256_file(prepared_pdb),
        "chain": candidate["target_chain"],
        "length": len(str(candidate["_target_sequence"])),
        "sequence": candidate["_target_sequence"],
        "fasta_id": fasta_id,
        "out": fasta,
        "out_abs": os.path.abspath(fasta),
        "out_sha256": _sha256_file(fasta),
        "unknown_allowed": True,
    }
    _write_json(fasta_report, fasta_rep)
    out = dict(candidate)
    out.pop("_target_sequence", None)
    out_prefix = os.path.join(records_dir, target_id)
    out.update({
        "prepared_pdb": prepared_pdb,
        "prep_report": prep_report,
        "target_fasta": fasta,
        "target_fasta_report": fasta_report,
        "target_msa": target_msa,
        "target_msa_report": target_msa_report,
        "records": os.path.join(out_prefix, "records_boltz_complex.jsonl"),
        "out_prefix": out_prefix,
    })
    return out


def build_discovery_pool(seed_config: Dict[str, Any], *,
                         fetch: bool = False,
                         source_dir: str = "hpc_outputs/m6d_w2_fresh_discovery_sources",
                         out_dir: str = "hpc_outputs/m6d_w2_fresh_discovery_targets",
                         records_dir: str = "hpc_outputs/m6d_w2_fresh_discovery_records",
                         max_candidates: int = 6,
                         min_contacts: int = 20,
                         min_chain_residues: int = 50,
                         max_target_residues: int = 220,
                         max_binder_residues: int = 180,
                         max_sequence_identity: float = 0.25,
                         source_diverse: bool = False) -> Dict[str, Any]:
    seeds = _seed_rows(seed_config)
    fetch_failures = []
    all_pairs = []
    for seed in seeds:
        rcsb_id = str(seed["rcsb_id"]).upper()
        source_pdb = str(seed.get("source_pdb") or os.path.join(source_dir, f"source_{rcsb_id}.pdb"))
        if fetch and (not os.path.exists(source_pdb) or os.path.getsize(source_pdb) == 0):
            try:
                _fetch_pdb(rcsb_id, source_pdb)
            except Exception as exc:  # noqa: BLE001 - recorded as data, not hidden
                fetch_failures.append({"rcsb_id": rcsb_id, "source_pdb": source_pdb, "message": str(exc)})
                continue
        if not os.path.exists(source_pdb) or os.path.getsize(source_pdb) == 0:
            fetch_failures.append({"rcsb_id": rcsb_id, "source_pdb": source_pdb, "message": "missing source PDB"})
            continue
        all_pairs.extend(_screen_pdb_pairs(
            source_pdb,
            rcsb_id,
            min_contacts=min_contacts,
            min_chain_residues=min_chain_residues,
            max_target_residues=max_target_residues,
            max_binder_residues=max_binder_residues,
            max_sequence_identity=max_sequence_identity,
            contact_cutoff=8.0,
        ))

    admitted = [row for row in all_pairs if row["admitted_structural_candidate"]]
    admitted.sort(key=lambda row: (
        abs(float(row["target_ca_residues"]) - 100.0),
        -int(row["ca_interface_contacts"]),
        row["complex_target_id"],
    ))
    selection_pool = admitted
    if source_diverse:
        seen_sources = set()
        selection_pool = []
        for row in admitted:
            source_id = str(row["rcsb_id"])
            if source_id in seen_sources:
                continue
            seen_sources.add(source_id)
            selection_pool.append(row)
    selected = [
        _materialize_candidate(row, out_dir=out_dir, records_dir=records_dir)
        for row in selection_pool[:max_candidates]
    ]
    selected_source_ids = sorted({str(row["rcsb_id"]) for row in selected})
    source_redundancy_note = (
        "selected candidates include multiple chain-pairs from the same source structures; "
        "review source redundancy before treating this as a multi-target generalization panel"
    ) if len(selected_source_ids) < len(selected) else "selected candidates have one chain-pair per source structure"
    manifest = {
        "_note": (
            "Fresh M6d W2 discovery candidates. This manifest is pre-MSA and not a Cayuga submit plan. "
            "Review source redundancy before treating selected chain-pairs as independent targets."
        ),
        "defaults": {"num_seq": 100, "temp": 0.3, "seed": 37, "objective": "binder"},
        "targets": [
            {
                "id": row["complex_target_id"],
                "rcsb_id": row["rcsb_id"],
                "source_pdb": row["source_pdb"],
                "prepared_pdb": row["prepared_pdb"],
                "prep_report": row["prep_report"],
                "target_chain": row["target_chain"],
                "binder_chain": row["binder_chain"],
                "target_fasta": row["target_fasta"],
                "target_fasta_report": row["target_fasta_report"],
                "target_msa": row["target_msa"],
                "target_msa_report": row["target_msa_report"],
                "records": row["records"],
                "out_prefix": row["out_prefix"],
            }
            for row in selected
        ],
    }
    return {
        "artifact": "m6d_w2_fresh_discovery_pool",
        "date": "2026-06-30",
        "status": "fresh_structural_candidates_ready_for_msa_precompute" if selected else "no_fresh_structural_candidates_admitted",
        "ready_for_target_msa_precompute": bool(selected),
        "ready_for_cayuga_submission": False,
        "n_seed_pdbs": len(seeds),
        "n_fetch_failures": len(fetch_failures),
        "n_chain_pairs_screened": len(all_pairs),
        "n_structural_admitted": len(admitted),
        "n_selected_for_manifest": len(selected),
        "n_unique_selected_rcsb_ids": len(selected_source_ids),
        "unique_selected_rcsb_ids": selected_source_ids,
        "source_diverse_selection": source_diverse,
        "selected_source_redundancy_note": source_redundancy_note,
        "fetch_failures": fetch_failures,
        "screen_parameters": {
            "min_contacts": min_contacts,
            "min_chain_residues": min_chain_residues,
            "max_target_residues": max_target_residues,
            "max_binder_residues": max_binder_residues,
            "max_sequence_identity": max_sequence_identity,
        },
        "selected_candidates": selected,
        "rejected_preview": [row for row in all_pairs if not row["admitted_structural_candidate"]][:20],
        "manifest": manifest,
        "claim_boundary": {
            "fresh_discovery": "local_structure_intake_only",
            "w2_multi_target_generalization": "not_supported",
            "selected_candidate_independence": "source_redundancy_requires_review_before_generalization_claim",
            "target_msa_precompute": "next_step_only_if_manifest_nonempty",
            "cayuga_submission": "not_ready_until_msa_and_manifest_require_files_pass",
        },
        "next_action": (
            "run complex_target_manifest --emit-msa-plan on the emitted manifest, then target-MSA "
            "precompute; do not submit ProteinMPNN/Boltz until --require-files and panel completion pass"
        ) if selected else "revise seed list or relax structural intake thresholds before target-MSA work",
        "can_mark_goal_complete": False,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Fresh Discovery Pool",
        "",
        f"Date: {rep.get('date')}",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Ready for target-MSA precompute: `{str(rep.get('ready_for_target_msa_precompute')).lower()}`.",
        f"Ready for Cayuga submission: `{str(rep.get('ready_for_cayuga_submission')).lower()}`.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| seed PDBs | {rep.get('n_seed_pdbs')} |",
        f"| chain pairs screened | {rep.get('n_chain_pairs_screened')} |",
        f"| structural admitted | {rep.get('n_structural_admitted')} |",
        f"| selected for manifest | {rep.get('n_selected_for_manifest')} |",
        f"| unique selected source PDBs | {rep.get('n_unique_selected_rcsb_ids')} |",
        f"| source-diverse selection | {str(rep.get('source_diverse_selection', False)).lower()} |",
        "",
        "## Selected Candidates",
        "",
        "| target | source | chains | target CA | binder CA | contacts | seq identity |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rep.get("selected_candidates", []):
        lines.append(
            "| {target} | {rcsb} | {tc}/{bc} | {tca} | {bca} | {contacts} | {ident:.3f} |".format(
                target=row["complex_target_id"],
                rcsb=row["rcsb_id"],
                tc=row["target_chain"],
                bc=row["binder_chain"],
                tca=row["target_ca_residues"],
                bca=row["binder_ca_residues"],
                contacts=row["ca_interface_contacts"],
                ident=float(row["chain_sequence_identity"]),
            )
        )
    lines.extend([
        "",
        "## Claim Boundary",
        "",
        "- This is local structural intake, not W2 evidence.",
        "- The emitted manifest is pre-MSA and is not a ProteinMPNN/Boltz submit plan.",
        f"- Source redundancy: {rep.get('selected_source_redundancy_note')}.",
        "- Cayuga submission remains blocked until target MSA/report files exist and strict manifest checks pass.",
        "",
        "## Next Action",
        "",
        rep.get("next_action", ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed-config", default="configs/m6d_w2_fresh_discovery_seed_rcsb_ids.json")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--source-dir", default="hpc_outputs/m6d_w2_fresh_discovery_sources")
    ap.add_argument("--out-dir", default="hpc_outputs/m6d_w2_fresh_discovery_targets")
    ap.add_argument("--records-dir", default="hpc_outputs/m6d_w2_fresh_discovery_records")
    ap.add_argument("--max-candidates", type=int, default=6)
    ap.add_argument("--source-diverse", action="store_true",
                    help="select at most one structurally admitted chain-pair per source PDB")
    ap.add_argument("--out-json", default="results/m6d_w2_fresh_discovery_pool.json")
    ap.add_argument("--out-md", default="results/m6d_w2_fresh_discovery_pool.md")
    ap.add_argument("--out-manifest", default="configs/m6d_w2_fresh_discovery_complex_targets.json")
    args = ap.parse_args(argv)

    rep = build_discovery_pool(
        _load_json(args.seed_config),
        fetch=args.fetch,
        source_dir=args.source_dir,
        out_dir=args.out_dir,
        records_dir=args.records_dir,
        max_candidates=args.max_candidates,
        source_diverse=args.source_diverse,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    _write_json(args.out_manifest, rep["manifest"])
    print(f"wrote {args.out_json}, {args.out_md}, and {args.out_manifest}")
    print(
        "status={status} seeds={seeds} screened={screened} selected={selected} ready_msa={ready}".format(
            status=rep["status"],
            seeds=rep["n_seed_pdbs"],
            screened=rep["n_chain_pairs_screened"],
            selected=rep["n_selected_for_manifest"],
            ready=rep["ready_for_target_msa_precompute"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
