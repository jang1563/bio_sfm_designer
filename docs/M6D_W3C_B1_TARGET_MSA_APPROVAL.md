# M6d W3c-B1 target-MSA approval packet

Status: `w3c_b1_packet_prepared_cayuga_no_submit_validation_required`.

## Purpose

W3c-B1 prepares one reusable target MSA for each of the eight prospectively locked W3c targets. This
eliminates per-design target-MSA queries before any native recoverability or generator experiment.

This document and its packet are a no-submit input and budget lock. They do not record approval and do not
authorize compute by themselves.

## Locked scope

- targets: `1TE1_BA`, `3QB4_AB`, `5E5M_AB`, `5JSB_AB`, `6KBR_AC`, `6KMQ_AB`, `6SGE_AB`, `7B5G_AB`
- maximum target-MSA queries after all gates pass: `8`
- scheduler resource per query: one Cayuga A40 for `01:00:00`
- maximum allocation: `8 A40 GPU-hours`
- ProteinMPNN designs: `0`
- structure-predictor evaluations: `0`
- W3c-B2 authority: `false`
- scientific-claim authority: `false`

The derived execution manifest binds every source PDB SHA-256, target-chain sequence SHA-256, chain role,
FASTA path, A3M path, and report path back to the completed W3c-A representation lock. The guarded wrapper
also binds the frozen protocol, public structure fixture, historical overlap registry, MSA plan, source and
FASTA preflight, Slurm script, and all input-preparation tools.

## Artifacts

- W3c-A manifest: `configs/m6d_w3c_fresh_targets.json`
- W3c-B1 execution manifest: `configs/m6d_w3c_b1_target_msa_manifest.json`
- pre-MSA manifest audit: `results/m6d_w3c_b1_target_manifest_pre_msa.json`
- target-MSA plan: `results/m6d_w3c_b1_target_msas.sh`
- input preflight: `src/bio_sfm_designer/experiments/m6d_w3c_b1_target_msa_preflight.py`
- guarded wrapper: `hpc/run_w3c_b1_target_msa_guarded.sh`
- approval packet: `results/m6d_w3c_b1_target_msa_approval_packet.{json,md}`

## Current validation state

Local packet generation, hash audit, shell syntax validation, source/sequence fixture replay, dry-run, and
missing/wrong-approval refusal tests pass. The local dry-run prints exactly the eight locked target IDs,
submits no scheduler job, and creates no receipt, summary, preflight report, MSA, ProteinMPNN output, or
predictor output.

Cayuga mirror validation has not been run. Therefore the exact approval must not be requested or treated as
active yet.

## Next no-submit action

Mirror all packet-bound artifacts to the Cayuga checkout and run:

```bash
TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \
BIO_SFM_PYTHON="$HOME/.conda/envs/boltz/bin/python" \
PYTHONNOUSERSITE=1 \
bash hpc/run_w3c_b1_target_msa_guarded.sh
```

The Cayuga validation must confirm exact local/remote hashes, the same eight dry-run IDs, exit `0`, zero
scheduler submissions, and absent receipt, summary, and materialization-report files.

Only after that validation passes may the following exact user phrase be requested:

`approve W3c-B1 target-MSA precompute`

The matching machine guard is:

`BIO_SFM_APPROVE_W3C_B1_TARGET_MSA=approve-w3c-b1-target-msa-precompute`

Even after exact approval, the scope remains target-MSA input preparation only. ProteinMPNN, Boltz/AF2
structure prediction, W3c-B2, and all scientific claims remain separately blocked.
