# M6d W3c-B1 target-MSA approval packet

Status: `w3c_b1_packet_cayuga_validated_ready_for_exact_approval` (immutable pre-execution packet).

Lifecycle: historical and consumed once; see the completion update below.

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
- Cayuga no-submit evidence: `results/m6d_w3c_b1_cayuga_no_submit_validation.json`
- approval packet: `results/m6d_w3c_b1_target_msa_approval_packet.{json,md}`

## Current validation state

Local packet generation, hash audit, shell syntax validation, source/sequence fixture replay, dry-run, and
missing/wrong-approval refusal tests pass. The local dry-run prints exactly the eight locked target IDs,
submits no scheduler job, and creates no receipt, summary, preflight report, MSA, ProteinMPNN output, or
predictor output.

Cayuga mirror validation ran in a private project mirror using Python 3.11.15. Public evidence redacts
the login node and account-specific absolute paths. All 13 packet-bound artifacts matched local SHA-256
values. The guarded wrapper exited `0`, printed the same eight target IDs, reported zero scheduler
submissions, and left receipt, summary, input-preflight, and A3M outputs absent. The checksum-mode rsync
replay reported zero differences.

The machine-readable evidence passed the packet validator. This paragraph describes the immutable
pre-execution boundary; the exact approval was later consumed once as recorded below.

## Next exact-approval action

The following exact user phrase may now be requested:

`approve W3c-B1 target-MSA precompute`

The matching machine guard is:

`BIO_SFM_APPROVE_W3C_B1_TARGET_MSA=approve-w3c-b1-target-msa-precompute`

Even after exact approval, the scope remains target-MSA input preparation only. ProteinMPNN, Boltz/AF2
structure prediction, W3c-B2, and all scientific claims remain separately blocked.

## Completion update

On 2026-08-02, the exact approval was consumed once through the guarded wrapper. Jobs
`3118725`-`3118732` completed 8/8 with top-level state `COMPLETED` and exit `0:0`, consuming
`1.151111` A40 GPU-hours. All eight A3M/report pairs pass the frozen sequence, query identity, depth,
hash, sanitization, and no-truncation checks. See
[M6D_W3C_B1_TARGET_MSA_COMPLETION.md](M6D_W3C_B1_TARGET_MSA_COMPLETION.md).

The packet remains historical and cannot be reused. W3c-B1 completion permits preparation of a separate
W3c-B2 no-submit packet only; it does not authorize native prediction or ProteinMPNN work.
