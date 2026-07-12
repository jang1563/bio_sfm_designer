# M6d W2c Target-MSA Approval Packet

Status: `ready_for_explicit_target_msa_approval_not_submitted`.

This packet is readiness evidence, not approval. No Slurm job, receipt, or summary was
created. It covers target-MSA input preparation only and cannot authorize ProteinMPNN or
Boltz record generation.

## Scope

- targets: `1FR2_BA`, `1F80_BC`, `1EZV_XY`, `1FFG_CD`, `1FFK_HR`, `1FQ9_CA`,
  `1FYR_CD`, and `1F99_BA`;
- expected jobs: 8;
- resource per job: Cayuga `scu-gpu`, one A40, up to one hour;
- maximum authorized budget if approved: 8 A40 GPU-hours;
- output: target `.a3m` and validation report only.

## Verified Boundary

- the manifest, W2c protocol, label-blind selection report, design gate, pre-MSA audit,
  MSA plan, and guard are SHA-bound in
  `results/m6d_w2c_target_msa_approval_packet.json`;
- the local manifest has eight schema-ready targets;
- all 40 required source/prepared/FASTA inputs are present on Cayuga and match local
  SHA-256 values (`40/40`, mismatches 0);
- local and Cayuga guarded dry-runs pass;
- Cayuga Slurm count remained `0 -> 0`;
- Cayuga receipt and summary paths remain absent;
- non-dry execution without the exact approval token refuses before receipt creation.

## Approval Contract

Explicit user wording must name this scope: `approve W2c target-MSA precompute`.

The machine gate is:

```text
BIO_SFM_APPROVE_W2C_TARGET_MSA=approve-w2c-target-msa-precompute
```

Generic continuation, goal-mode resume, or approval of later W2c record generation does
not satisfy this boundary. After target MSAs complete, outputs must be synced back and
hash-locked before any separate fit-record packet can be prepared.

## Claim Boundary

No W2c record exists, no W2c certificate exists, and W2 generalization remains
unsupported.
