"""Cayuga-side ESMFold predict runner (M4, predict stage).

Refolds each ProteinMPNN design with ESMFold (single-sequence; the standard self-consistency
tool) and writes a structure records JSONL for the local PrecomputedStructurePredictor to consume.

Per design it records:
  - mean_plddt  : ESMFold per-residue CA pLDDT (0-100) -- the SFM's self-confidence, the VISIBLE
                  signal the trust gate calibrates and routes on.
  - iptm        : ESMFold pTM (global confidence; carried in the iptm field).
  - truth.correct = scRMSD-to-intended-backbone < threshold (default 2.0 A): the self-consistency
                  SUCCESS proxy -- HIDDEN from the gate, revealed only by a verify-assay / the scorer.
                  (Without wet-lab data, self-consistency is the standard in-silico success label.)
  - truth.quality, scrmsd, proteinmpnn_score (a cheaper, fold-free signal) for offline analysis.

CAVEAT -- single-model self-consistency: pLDDT and scRMSD both come from the SAME ESMFold pass, so
"pLDDT predicts scRMSD<thr" is inflated by self-consistency of ONE model and is NOT comparable to the
standard protocol (refold with an INDEPENDENT predictor, e.g. AF2, or compare to the experimental
structure). It measures "does ESMFold confidence predict ESMFold self-consistency" -- a weaker claim
than de-novo design success, and on small n the CI is wide. Read the AUROC accordingly.
M6a measured this with an INDEPENDENT Boltz-2 refold (experiments/cross_model_auroc.py): the signal
TRANSFERS -- AUROC(ESMFold pLDDT -> BOLTZ success) = 0.943, labels agree 72% -- so it is not pure
self-prediction. But honestly (a self-review): it is NOT significantly above the single-model 0.947
(the difference's 95% CI spans 0), and the AUROC is inflated by a TEMPERATURE confound (failures
concentrate at sampling temp 1.0; Boltz 4/40 success there), plus Boltz ran msa:empty (a weak
single-seq refolder). So the caveat is ADDRESSED, not cleanly closed -- a tighter test needs
within-stratum analysis + a validated refolder (Boltz+MSA or AF2).
M6b RAN that within-stratum test (experiments/within_regime_signal.py: 160 designs at a FIXED temp
0.7, Boltz mix 120/160): AUROC(ESMFold pLDDT -> Boltz success) = 0.59, CI [0.48, 0.70] -- WEAK, not
significantly above chance; non-monotone by pLDDT tertile. So the pooled 0.943 was a TEMPERATURE batch
effect; at fixed difficulty ESMFold pLDDT barely predicts an independent model's per-design success.
Honest read: monomer pLDDT-risk is a COARSE difficulty filter, NOT a fine per-design trust oracle.
(Numbers are the CLEAN re-fold after a Boltz work-dir caching bug was fixed 2026-06-24.)
RUNS ON CAYUGA (GPU; ESMFold). See run_predict_esmfold.sbatch.
"""

from __future__ import annotations

import argparse
import json
import sys


# modified residues whose CA is written as HETATM but which ARE part of the chain (ProteinMPNN
# and ESMFold treat them as standard residues, so the backbone CA list must include them).
_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}


def _ca_coords_from_pdb(path, chain=None):
    """CA coordinates [(x,y,z), ...] in residue order for ONE chain of a PDB (first model). Three
    correspondence hazards are handled so scRMSD stays a true 1:1 comparison:
      - altLoc: take ' '/'A' only, one CA per (chain,resSeq,iCode). Without this, altloc duplicates
        inflate the count and frame-shift the alignment (e.g. 5L33: 109 CA records / 106 residues).
      - modified residues: read CAs from HETATM too when the resName is a known modified AA (e.g.
        MSE selenomethionine), which crystal structures use in place of MET; ProteinMPNN reads them
        as standard residues, so dropping them would shorten the backbone and mismatch the design.
      - chains: restrict to ONE chain (default: the first seen). ESMFold folds a single sequence, so
        mixing chains would break the design<->backbone correspondence.
    Pure-Python (no numpy) so this is locally testable."""
    coords, seen, target_chain = [], set(), chain
    with open(path) as fh:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            rec = line[:6].strip()
            if rec not in ("ATOM", "HETATM") or line[12:16].strip() != "CA":
                continue
            if rec == "HETATM" and line[17:20].strip() not in _MODIFIED_AA:
                continue                                # skip ligand/water CAs; keep modified AAs
            if line[16] not in (" ", "A"):              # skip alternate conformations B/C/...
                continue
            ch = line[21]
            if target_chain is None:
                target_chain = ch                       # lock onto the first chain seen
            if ch != target_chain:
                continue
            reskey = (ch, line[22:27])                  # chain + resSeq(+iCode)
            if reskey in seen:
                continue
            seen.add(reskey)
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coords


def _kabsch_rmsd(P, Q):
    """Minimal CA-RMSD after optimal superposition (Kabsch). P, Q: (N,3) array-likes, 1:1."""
    import numpy as np
    P = np.asarray(P, dtype=float)
    Q = np.asarray(Q, dtype=float)
    Pc = P - P.mean(0)
    Qc = Q - Q.mean(0)
    H = Pc.T @ Qc
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    Pr = Pc @ R.T
    return float(np.sqrt(((Pr - Qc) ** 2).sum() / len(P)))


def main() -> None:
    ap = argparse.ArgumentParser(description="ESMFold refold + scRMSD -> structure records for the designer")
    ap.add_argument("--candidates", required=True, help="candidates.jsonl (ProteinMPNN designs)")
    ap.add_argument("--backbone", required=True, help="intended backbone PDB (the design target)")
    ap.add_argument("--chain", default=None, help="backbone chain to align to (default: first chain seen)")
    ap.add_argument("--out", required=True, help="records.jsonl output")
    ap.add_argument("--threshold", type=float, default=2.0, help="scRMSD (A) below which a design 'succeeds'")
    ap.add_argument("--model", default="facebook/esmfold_v1")
    args = ap.parse_args()

    import numpy as np
    import torch
    from transformers import EsmForProteinFolding

    target_ca = _ca_coords_from_pdb(args.backbone, args.chain)
    with open(args.candidates) as fh:
        cands = [json.loads(line) for line in fh if line.strip()]

    model = EsmForProteinFolding.from_pretrained(args.model).cuda().eval()

    n_ok = 0
    with open(args.out, "w") as out:
        for c in cands:
            seq = str(c["representation"])
            with torch.no_grad():
                o = model.infer([seq])
            pos = o["positions"]                              # ESMFold: (blocks, batch, L, atoms, 3)
            pos = pos[-1, 0] if pos.dim() == 5 else (pos[0] if pos.dim() == 4 else pos)
            assert pos.dim() == 3, f"unexpected ESMFold positions ndim={pos.dim()}"        # (L, atoms, 3)
            design_ca = pos[:, 1, :].detach().cpu().numpy()                                # CA = atom index 1
            plddt = o["plddt"]
            plddt_ca = plddt[0, :, 1] if plddt.dim() == 3 else plddt[0]                    # per-residue CA pLDDT
            mean_plddt_unit = float(plddt_ca.float().mean())                               # 0..1
            ptm = float(o["ptm"]) if "ptm" in o else None

            aligned = len(design_ca) == len(target_ca)
            if not aligned:
                print(f"  WARNING {c['id']}: design has {len(design_ca)} CA but backbone has "
                      f"{len(target_ca)} -- correspondence is not 1:1, scRMSD is unreliable", file=sys.stderr)
            L = min(len(design_ca), len(target_ca))
            scrmsd = _kabsch_rmsd(design_ca[:L], target_ca[:L]) if L >= 3 else float("nan")
            success = bool(aligned and np.isfinite(scrmsd) and scrmsd < args.threshold)
            # quality is gated on `aligned`: a frame-shifted (non-1:1) design must not report a
            # plausible continuous quality from a truncated-prefix RMSD.
            quality = round(max(0.0, 1.0 - scrmsd / 5.0), 4) if (aligned and np.isfinite(scrmsd)) else 0.0

            rec = {
                "target_id": c["id"],
                "mean_plddt": round(100.0 * mean_plddt_unit, 3),     # VISIBLE: SFM self-confidence
                "regime": c.get("regime", "monomer"),
                "iptm": round(ptm, 4) if ptm is not None else None,
                "truth": {"correct": success, "quality": quality},   # HIDDEN: self-consistency success
                "scrmsd": round(scrmsd, 4) if np.isfinite(scrmsd) else None,
                "scrmsd_threshold": args.threshold,
                "ca_aligned": aligned,
                "proteinmpnn_score": (c.get("meta") or {}).get("score"),  # cheaper fold-free signal
            }
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            n_ok += 1
            print(f"  {c['id']}: plddt={100*mean_plddt_unit:.1f} ptm={ptm} scRMSD={scrmsd:.2f} "
                  f"success={success}", file=sys.stderr)

    print(f"wrote {n_ok} records to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
