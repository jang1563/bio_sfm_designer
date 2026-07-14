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
wrapper is `hpc/run_w3b_target_msa_guarded.sh`. The packet and wrapper also bind the four execution
dependencies used by that plan: the target-MSA Slurm script, Boltz MSA helper, heterodimer preparation
helper, and chain-FASTA extractor. Any drift in those files fails closed before dry-run or submission.

## Cayuga no-submit readiness

The exact packet and wrapper are staged at the logical mirror path `$HOME/bio_sfm_smoke`. The live audit
in `results/m6d_w3b_target_msa_remote_readiness.{json,md}` passes 11 exact SHA checks, three shell-syntax
checks, Boltz Python/CLI and `sbatch` checks, receipt absence before and after, and the exact eight-target
dry-run. This proves staging and runtime readiness only; it records no approval and submits no scheduler job.

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

After all jobs finish, sync the eight `.a3m` and report files, validate file and manifest hashes, update
the target manifest lock, and rerun the W3b design audit. Stop again before candidate generation or either
predictor. Those later stages require distinct immutable packets and explicit approvals.
