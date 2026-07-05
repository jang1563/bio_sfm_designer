"""Cayuga-side Boltz-2 COMPLEX refold runner (M6c-lite, binder/interface de-risk).

Refolds each designed COMPLEX (fixed target chain + redesigned binder chain) with Boltz-2. Interfaces
need a target MSA; the validated protocol is target-MSA + binder single-seq for designed binders.
It scores the INTERFACE two ways:
  - SIGNAL  : pAE_interaction -- mean target<->binder PAE, the validated complex signal for routing.
              ipTM is still recorded as a secondary diagnostic, but it is weak after foldability control.
  - LABEL   : ligand-RMSD (L-RMSD) -- superpose the refold onto the TARGET chain (Kabsch), then measure
              the BINDER chain CA-RMSD to the reference complex. Success = the binder docks in the right
              place (L-RMSD < threshold). This is an INDEPENDENT interface-success label (Boltz refold
              vs the intended backbone), the complex analog of monomer scRMSD.

Writes records.jsonl (PrecomputedStructurePredictor schema; regime "complex", pAE_interaction + ipTM
carried) for the within-regime complex analysis. All designs fold in ONE model load (Boltz predicts a
dir of YAMLs).

RUNS ON CAYUGA (GPU). `boltz` conda env + PYTHONNOUSERSITE=1 + `--no_kernels`. See run_predict_boltz_complex.sbatch.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys

_MODIFIED_AA = {"MSE", "SEC", "PYL", "MLY", "CSO", "SEP", "TPO", "PTR", "HYP", "KCX", "LLP", "CME"}


def _read_first_fasta_sequence(path):
    seq = []
    in_record = False
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if in_record:
                    break
                in_record = True
                continue
            if in_record:
                seq.append(line)
    if not seq:
        return None
    # A3M lower-case insertions and alignment gaps are not part of the query sequence Boltz should match.
    return "".join(c for c in "".join(seq) if c.isupper() and c != "-")


def _count_nul_bytes(path):
    with open(path, "rb") as fh:
        return fh.read().count(b"\x00")


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


def _kabsch_transform(P, Q):
    """Rotation R + centroids so that (P - Pm) @ R.T + Qm best fits Q. Apply to OTHER points to get L-RMSD."""
    import numpy as np
    P = np.asarray(P, dtype=float)
    Q = np.asarray(Q, dtype=float)
    Pm, Qm = P.mean(0), Q.mean(0)
    H = (P - Pm).T @ (Q - Qm)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, Pm, Qm


def _lrmsd(fold_target, fold_binder, ref_target, ref_binder):
    """Ligand-RMSD: superpose on the target, measure the binder displacement (DockQ's L-RMSD)."""
    import numpy as np
    R, Pm, Qm = _kabsch_transform(fold_target, ref_target)   # align refold target onto reference target
    fb = (np.asarray(fold_binder, float) - Pm) @ R.T + Qm     # move the binder by the SAME transform
    rb = np.asarray(ref_binder, float)
    return float(np.sqrt(((fb - rb) ** 2).sum() / len(rb)))


def _interface_pae(npz_path, n_target):
    """Mean predicted aligned error across the target<->binder interface (the binder-design metric;
    LOWER = more confident). PAE matrix is ordered [target residues, binder residues]. This is the
    interface signal that actually discriminates docking quality (ipTM alone does not -- M6c-lite)."""
    import numpy as np
    m = np.load(npz_path)
    m = m[m.files[0]]
    if m.ndim != 2 or m.shape[0] <= n_target:
        return None
    return float((m[:n_target, n_target:].mean() + m[n_target:, :n_target].mean()) / 2.0)


def _complex_id(args, cand):
    if args.complex_id:
        return args.complex_id
    meta = cand.get("meta") if isinstance(cand.get("meta"), dict) else {}
    for key in ("complex_target_id", "target_id", "backbone"):
        value = meta.get(key)
        if value:
            return str(value)
    return os.path.splitext(os.path.basename(args.backbone))[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Boltz-2 complex refold + interface L-RMSD -> structure records")
    ap.add_argument("--candidates", required=True, help="complex candidates.jsonl (representation=binder, target_seq=target)")
    ap.add_argument("--backbone", required=True, help="reference complex PDB")
    ap.add_argument("--target-chain", default="A", help="reference chain for the (fixed) target")
    ap.add_argument("--binder-chain", default="C", help="reference chain for the (designed) binder")
    ap.add_argument("--complex-id", default=None,
                    help="heterodimer target id to carry into each output record")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=4.0, help="L-RMSD (A) below which the interface 'succeeds'")
    ap.add_argument("--boltz", default=os.path.expanduser("~/.conda/envs/boltz/bin/boltz"))
    ap.add_argument("--sampling-steps", type=int, default=100)
    # interfaces need coevolution: msa:empty folds monomers fine but FAILS at complexes (verified:
    # native barnase-barstar msa:empty -> 38 A, cplx_plddt 43). --use-msa-server gives the TARGET an MSA
    # (the binder stays single-seq = the realistic designed-binder protocol, since designs have no homologs).
    ap.add_argument("--target-msa", default=None,
                    help="precomputed target MSA (.a3m); avoids repeated identical MSA-server queries")
    ap.add_argument("--use-msa-server", action="store_true",
                    help="generate MSAs via the ColabFold server (needs compute-node internet)")
    ap.add_argument("--binder-uses-msa", action="store_true",
                    help="also MSA the binder (NATURAL binders / WT controls; default: binder single-seq)")
    args = ap.parse_args()
    if args.target_msa and args.use_msa_server:
        ap.error("--target-msa and --use-msa-server are mutually exclusive")
    if args.target_msa and not os.path.exists(args.target_msa):
        ap.error(f"--target-msa file not found: {args.target_msa}")
    if args.target_msa:
        n_nul = _count_nul_bytes(args.target_msa)
        if n_nul:
            ap.error(f"--target-msa contains {n_nul} NUL byte(s); rerun/sanitize target-MSA precompute")

    ref_target = _ca_coords_from_pdb(args.backbone, args.target_chain)
    ref_binder = _ca_coords_from_pdb(args.backbone, args.binder_chain)
    with open(args.candidates) as fh:
        cands = [json.loads(line) for line in fh if line.strip()]
    if args.target_msa:
        msa_seq = _read_first_fasta_sequence(args.target_msa)
        if not msa_seq:
            ap.error(f"--target-msa has no FASTA/A3M query sequence: {args.target_msa}")
        bad = [c.get("id", f"candidate_{i}") for i, c in enumerate(cands)
               if str(c.get("target_seq", "")) != msa_seq]
        if bad:
            ap.error(f"--target-msa query sequence does not match target_seq for {len(bad)} "
                     f"candidate(s); first mismatch={bad[0]}")

    # UNIQUE per output AND wiped on start -- Boltz skips predictions whose output already exists, so a
    # shared/stale work dir silently reuses a previous run's structures (a real contamination bug).
    work = os.path.join(os.path.dirname(os.path.abspath(args.out)) or ".",
                        "_boltzX_work_" + os.path.splitext(os.path.basename(args.out))[0])
    shutil.rmtree(work, ignore_errors=True)
    yamls = os.path.join(work, "yamls")
    outdir = os.path.join(work, "out")
    os.makedirs(yamls, exist_ok=True)
    names = []
    for i, c in enumerate(cands):
        name = f"c{i}"
        names.append((name, c))
        if args.target_msa:
            target_msa = f"      msa: {json.dumps(os.path.abspath(args.target_msa))}\n"
        else:
            target_msa = "" if args.use_msa_server else "      msa: empty\n"
        binder_msa = "" if (args.use_msa_server and args.binder_uses_msa) else "      msa: empty\n"
        with open(os.path.join(yamls, name + ".yaml"), "w") as fh:
            fh.write(
                "version: 1\nsequences:\n"
                "  - protein:\n      id: A\n      sequence: %s\n%s"
                "  - protein:\n      id: B\n      sequence: %s\n%s"
                % (str(c["target_seq"]), target_msa, str(c["representation"]), binder_msa)
            )

    cmd = [args.boltz, "predict", yamls, "--out_dir", outdir, "--no_kernels", "--output_format", "pdb",
           "--accelerator", "gpu", "--devices", "1", "--diffusion_samples", "1",
           "--sampling_steps", str(args.sampling_steps)]
    if args.use_msa_server:
        cmd += ["--use_msa_server"]
    subprocess.run(cmd, check=True)

    n_ok = 0
    with open(args.out, "w") as out:
        for name, c in names:
            pdbs = glob.glob(os.path.join(outdir, "boltz_results_*", "predictions", name, name + "_model_0.pdb"))
            confs = glob.glob(os.path.join(outdir, "boltz_results_*", "predictions", name, "confidence_" + name + "_model_0.json"))
            if not pdbs or not confs:
                print(f"  WARNING {c['id']}: no Boltz output found", file=sys.stderr)
                continue
            fold_target = _ca_coords_from_pdb(pdbs[0], "A")     # YAML id A = target
            fold_binder = _ca_coords_from_pdb(pdbs[0], "B")     # YAML id B = binder
            with open(confs[0]) as cf:
                conf = json.load(cf)
            plddt = float(conf.get("complex_plddt", 0.0))
            ptm = float(conf.get("ptm", 0.0))
            iptm = float(conf.get("iptm", 0.0))
            paes = glob.glob(os.path.join(outdir, "boltz_results_*", "predictions", name, "pae_" + name + "_model_0.npz"))
            pae_interaction = _interface_pae(paes[0], len(fold_target)) if paes else None
            aligned = (len(fold_target) == len(ref_target) and len(fold_binder) == len(ref_binder))
            if not aligned:
                print(f"  WARNING {c['id']}: CA counts target {len(fold_target)}/{len(ref_target)} "
                      f"binder {len(fold_binder)}/{len(ref_binder)} -- L-RMSD unreliable", file=sys.stderr)
            lrmsd = _lrmsd(fold_target, fold_binder, ref_target, ref_binder) if aligned else float("nan")
            success = bool(aligned and math.isfinite(lrmsd) and lrmsd < args.threshold)
            quality = round(max(0.0, 1.0 - lrmsd / 10.0), 4) if (aligned and math.isfinite(lrmsd)) else 0.0
            rec = {
                "target_id": c["id"],
                "complex_target_id": _complex_id(args, c),
                "mean_plddt": round(100.0 * plddt, 3),          # complex pLDDT
                "regime": "complex",
                "predictor_id": "boltz2_complex",
                "signal_source": "boltz2_pae_interaction",
                "label_source": "boltz2_lrmsd_to_reference",
                "iptm": round(iptm, 4),                          # global interface pTM (weak discriminator here)
                "ptm": round(ptm, 4),
                "pae_interaction": round(pae_interaction, 4) if pae_interaction is not None else None,  # the real interface signal

                "truth": {"correct": success, "quality": quality},  # INDEPENDENT interface-success label
                "lrmsd": round(lrmsd, 4) if math.isfinite(lrmsd) else None,
                "lrmsd_threshold": args.threshold,
                "interface_aligned": aligned,
                "target_chain": args.target_chain,
                "binder_chain": args.binder_chain,
                "refolder": "boltz2_complex",
            }
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            n_ok += 1
            pae_msg = "n/a" if pae_interaction is None else f"{pae_interaction:.2f}"
            print(f"  {c['id']}: pAE_interaction={pae_msg} iptm={iptm:.3f} "
                  f"cplx_plddt={100*plddt:.1f} L-RMSD={lrmsd:.2f} success={success}", file=sys.stderr)
    print(f"wrote {n_ok} Boltz complex records to {args.out}", file=sys.stderr)
    if cands and n_ok == 0:
        raise RuntimeError("Boltz complex prediction produced zero records; inspect Boltz logs and MSA inputs")


if __name__ == "__main__":
    main()
