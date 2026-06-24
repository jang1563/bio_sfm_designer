"""Cayuga-side Boltz-2 INDEPENDENT refold runner (M6a).

Refolds each ProteinMPNN design with Boltz-2 in single-sequence mode (`msa: empty`) and computes
scRMSD to the intended backbone. Boltz-2 (diffusion + Pairformer, no protein language model) is
ARCHITECTURALLY INDEPENDENT of ESMFold (ESM-2 LM-based) — so the success LABEL here comes from a
different model than the ESMFold pLDDT SIGNAL used elsewhere, closing the M4b single-model
self-consistency caveat (the AUROC becomes a genuine cross-model check, not self-prediction).

Writes records.jsonl in the PrecomputedStructurePredictor schema, with Boltz mean pLDDT and
scRMSD<threshold success. All designs fold in ONE model load (Boltz predicts a directory of YAMLs).

RUNS ON CAYUGA (GPU). Needs the `boltz` conda env + PYTHONNOUSERSITE=1 (so ~/.local doesn't shadow the
env's torch) + `--no_kernels` (no cuequivariance dependency). See run_predict_boltz.sbatch.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys

# modified residues whose CA is a HETATM but which are part of the chain (mirror predict_esmfold.py)
_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}


def _ca_coords_from_pdb(path, chain=None):
    """CA coords [(x,y,z), ...] for ONE chain; dedupes altLoc, reads modified-residue HETATM CAs."""
    coords, seen, target_chain = [], set(), chain
    with open(path) as fh:
        for line in fh:
            if line.startswith("ENDMDL"):
                break
            rec = line[:6].strip()
            if rec not in ("ATOM", "HETATM") or line[12:16].strip() != "CA":
                continue
            if rec == "HETATM" and line[17:20].strip() not in _MODIFIED_AA:
                continue
            if line[16] not in (" ", "A"):
                continue
            ch = line[21]
            if target_chain is None:
                target_chain = ch
            if ch != target_chain:
                continue
            reskey = (ch, line[22:27])
            if reskey in seen:
                continue
            seen.add(reskey)
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coords


def _kabsch_rmsd(P, Q):
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
    ap = argparse.ArgumentParser(description="Boltz-2 independent refold + scRMSD -> structure records")
    ap.add_argument("--candidates", required=True, help="candidates.jsonl (designs)")
    ap.add_argument("--backbone", required=True, help="intended backbone PDB")
    ap.add_argument("--chain", default=None, help="backbone chain (default: first seen)")
    ap.add_argument("--out", required=True, help="records.jsonl output")
    ap.add_argument("--threshold", type=float, default=2.0)
    ap.add_argument("--boltz", default=os.path.expanduser("~/.conda/envs/boltz/bin/boltz"))
    ap.add_argument("--sampling-steps", type=int, default=200)
    args = ap.parse_args()

    target_ca = _ca_coords_from_pdb(args.backbone, args.chain)
    with open(args.candidates) as fh:
        cands = [json.loads(line) for line in fh if line.strip()]

    work = os.path.join(os.path.dirname(os.path.abspath(args.out)) or ".", "_boltz_work")
    yamls = os.path.join(work, "yamls")
    outdir = os.path.join(work, "out")
    os.makedirs(yamls, exist_ok=True)
    names = []
    for i, c in enumerate(cands):
        name = f"d{i}"                      # stable, filesystem-safe stem; map back to the candidate
        names.append((name, c))
        with open(os.path.join(yamls, name + ".yaml"), "w") as fh:
            fh.write("version: 1\nsequences:\n  - protein:\n      id: A\n      sequence: %s\n      msa: empty\n"
                     % str(c["representation"]))

    cmd = [args.boltz, "predict", yamls, "--out_dir", outdir, "--no_kernels", "--output_format", "pdb",
           "--accelerator", "gpu", "--devices", "1", "--diffusion_samples", "1",
           "--sampling_steps", str(args.sampling_steps)]
    subprocess.run(cmd, check=True)

    n_ok = 0
    with open(args.out, "w") as out:
        for name, c in names:
            pdbs = glob.glob(os.path.join(outdir, "boltz_results_*", "predictions", name, name + "_model_0.pdb"))
            confs = glob.glob(os.path.join(outdir, "boltz_results_*", "predictions", name, "confidence_" + name + "_model_0.json"))
            if not pdbs or not confs:
                print(f"  WARNING {c['id']}: no Boltz output found", file=sys.stderr)
                continue
            design_ca = _ca_coords_from_pdb(pdbs[0])
            with open(confs[0]) as cf:
                conf = json.load(cf)
            plddt = float(conf.get("complex_plddt", 0.0))          # 0..1
            ptm = float(conf.get("ptm", 0.0))
            iptm = float(conf.get("iptm", 0.0))
            aligned = len(design_ca) == len(target_ca)
            if not aligned:
                print(f"  WARNING {c['id']}: {len(design_ca)} CA vs backbone {len(target_ca)} — scRMSD unreliable",
                      file=sys.stderr)
            L = min(len(design_ca), len(target_ca))
            scrmsd = _kabsch_rmsd(design_ca[:L], target_ca[:L]) if L >= 3 else float("nan")
            success = bool(aligned and math.isfinite(scrmsd) and scrmsd < args.threshold)
            quality = round(max(0.0, 1.0 - scrmsd / 5.0), 4) if (aligned and math.isfinite(scrmsd)) else 0.0
            rec = {
                "target_id": c["id"],
                "mean_plddt": round(100.0 * plddt, 3),             # Boltz mean pLDDT (independent signal)
                "regime": c.get("regime", "monomer"),
                "iptm": round(iptm if iptm > 0 else ptm, 4),
                "truth": {"correct": success, "quality": quality}, # INDEPENDENT self-consistency label
                "scrmsd": round(scrmsd, 4) if math.isfinite(scrmsd) else None,
                "scrmsd_threshold": args.threshold,
                "ca_aligned": aligned,
                "refolder": "boltz2",
            }
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            n_ok += 1
            print(f"  {c['id']}: boltz_plddt={100*plddt:.1f} ptm={ptm:.3f} scRMSD={scrmsd:.2f} success={success}",
                  file=sys.stderr)
    print(f"wrote {n_ok} Boltz records to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
