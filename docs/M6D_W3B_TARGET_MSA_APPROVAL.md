# M6d W3b target-MSA approval boundary

Status: `awaiting_explicit_w3b_target_msa_approval`.

Date: 2026-07-14.

The W3b scientific protocol, label-blind 3/3/2 target roles, exact-power design audit, and eight-target
MSA plan are complete and hash-bound. This packet does not record approval and does not submit work.

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
wrapper is `hpc/run_w3b_target_msa_guarded.sh`. The packet and wrapper also bind all eight execution and
replay dependencies: the target-MSA Slurm script, Boltz MSA helper, heterodimer preparation helper,
chain-FASTA extractor, strict manifest validator, lifecycle auditor, read-only Slurm query, and scoped
sync-back replay. Any drift in those files fails closed before dry-run or submission.

## Cayuga no-submit readiness

The exact packet and wrapper are staged at the logical mirror path `$HOME/bio_sfm_smoke`. The live audit
in `results/m6d_w3b_target_msa_remote_readiness.{json,md}` passes 15 exact SHA checks, five shell-syntax
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

## Approval gate

A real MSA submission requires the exact, separate approval token:

```bash
BIO_SFM_APPROVE_W3B_TARGET_MSA=approve-w3b-target-msa-precompute \
bash hpc/run_w3b_target_msa_guarded.sh
```

Generic continuation language and shorter token variants are not approval. The wrapper refuses them
before creating a receipt.

## After completion

After an approved submission, run `results/m6d_w3b_target_msa_job_state_query.sh` on Cayuga. It reads the
receipt, queries `sacct`, and updates the lifecycle report without submitting work. Only after all eight
jobs are terminal-success, run `results/m6d_w3b_target_msa_sync_back.sh` locally. It pulls only the receipt,
job state, and target input-prep artifacts; then it replays strict manifest, sequence, report-hash, frozen-
sequence, allocation, and 8/8 completion checks and reruns the design gate. Stop again before candidate
generation or either predictor. Those later stages require distinct immutable packets and explicit approvals.
