# M6d W3b target-MSA approval boundary

Status: `consumed_and_completed_8_of_8`.

Date: 2026-07-14.

The W3b scientific protocol, label-blind 3/3/2 target roles, exact-power design audit, and eight-target
MSA plan were completed and hash-bound before execution. The exact approval was later consumed, jobs
`3085384`-`3085391` completed `8/8` with exit `0:0`, and strict replay passed at `0.216389 A40 GPU-hours`.
This document and its machine packet are now immutable historical approval evidence. The authoritative
completion record is `docs/M6D_W3B_TARGET_MSA_COMPLETION.md`.

## Exact scope

- eight target-MSA precomputations only;
- targets: `1FSK_LJ`, `1FSX_BA`, `1FL7_DC`, `1F2U_CD`, `1FV1_BA`, `1FN3_DC`,
  `1FHJ_BA`, and `1F3V_BA`;
- maximum allocation: 8 A40 GPU-hours;
- no ProteinMPNN candidate generation;
- no Boltz candidate prediction;
- no AF2-Multimer prediction;
- no W3b scientific claim.

The machine-readable packet is `results/m6d_w3b_target_msa_approval_packet.json`. It binds the protocol,
target manifest, target-selection report, design audit, and generated MSA plan by SHA-256. The guarded
wrapper is `hpc/run_w3b_target_msa_guarded.sh`. The packet and wrapper also bind all nine execution and
replay dependencies: the target-MSA Slurm script, Boltz MSA helper, heterodimer preparation helper,
chain-FASTA extractor, strict manifest validator, lifecycle auditor, read-only Slurm query, and scoped
sync-back replay, plus the lifecycle-derived W3b execution-lock builder. Any drift in those files fails
closed before dry-run or submission.

## Cayuga no-submit readiness

The exact packet and wrapper are staged at the logical mirror path `$HOME/bio_sfm_smoke`. The live audit
in `results/m6d_w3b_target_msa_remote_readiness.{json,md}` passes 16 exact SHA checks, five shell-syntax
checks, Boltz Python/CLI and `sbatch` checks, lifecycle import, receipt absence before and after, the
expected receiptless-query refusal, and the exact eight-target dry-run. This proves staging and runtime
readiness only; it records no approval and submits no scheduler job.

## Safe dry-run

```bash
TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \
BIO_SFM_PYTHON=python3 \
bash hpc/run_w3b_target_msa_guarded.sh
```

The verified dry-run enumerates exactly eight targets, submits no scheduler jobs, and leaves receipt
and summary paths untouched.

## Historical approval gate

The completed MSA submission required the exact, separate approval token:

```bash
BIO_SFM_APPROVE_W3B_TARGET_MSA=approve-w3b-target-msa-precompute \
bash hpc/run_w3b_target_msa_guarded.sh
```

Generic continuation language and shorter token variants were not approval. The wrapper refused them
before creating a receipt. Do not reuse this consumed token.

## Completed replay

The read-only query, scoped sync, strict manifest/sequence/report replay, and lifecycle-derived execution
lock are complete. `configs/m6d_w3b_execution_targets.json` and
`configs/m6d_w3b_execution_input_lock.json` freeze all 870 stage-assigned design slots and bind every
target to its validated MSA hash. They authorize no candidate generation or predictor work. The project
has stopped at the distinct fit-stage approval boundary in `docs/M6D_W3B_FIT_APPROVAL.md`.
