# M6d W3b AF2 fit recovery approval boundary

Status: `recovery_packet_ready_awaiting_explicit_approval`.

Date: 2026-07-15.

> **Historical consumed snapshot:** this file preserves the immutable pre-submit approval boundary below.
> The exact approval was later consumed once. Replacement jobs `3085544`-`3085546` completed `0:0` with
> exactly 60 AF2 records per target. Slurm rounded the requested `03:59:30` to `04:00:00`; all three live
> limits were corrected to `03:59:00`, restoring an 86,258-second worst case and 142-second margin. Strict
> replay assembled 180/180 matched fit rows, after which the frozen evaluator returned
> `w3b_fit_rule_not_found_stop`. See `docs/M6D_W3B_FIT_COMPLETION.md`. The original status, scope, and phrase
> below are retained as historical evidence and are not reusable authority.

## Why recovery is needed

The approved initial W3b fit submission completed all three ProteinMPNN jobs and all three Boltz jobs.
AF2 jobs `3085449`, `3085452`, and `3085455` failed before prediction after successful GPU and runtime
preflight because the network-isolated container could not resolve a relative input-directory path.
Their combined H100 allocation was 38 seconds. No AF2 prediction, record, or runtime receipt was written.

The original candidates, 180 precomputed A3Ms, A3M manifests, and observed runtime identities pass strict
hash validation. All three output directories remain empty. Recovery therefore changes only the host-to-
container path representation from relative to absolute; it does not regenerate or alter scientific input.

## Frozen recovery scope

The hash-bound packet at `results/m6d_w3b_fit_af2_recovery_approval_packet.json` authorizes, after exact
approval, only:

- one replacement AF2 H100 job for each of the three failed jobs;
- the same 180 fit candidates and precomputed A3Ms;
- the same ColabFold 1.6.1 / AF2-Multimer-v3 runtime and frozen predictor settings;
- absolute container input and output paths;
- `--no-requeue` and a `03:59:30` limit per job.

It authorizes zero ProteinMPNN jobs, zero Boltz jobs, zero certification jobs, zero held-out-test jobs,
zero adaptive top-up, zero retuning, and zero claims. The maximum protocol H100 allocation after recovery
is 86,348 seconds, below the 86,400-second ceiling.

## Guard sequence

Before any scheduler call, the bridge:

1. re-derives and verifies the recovery packet against its bound code and evidence;
2. validates candidate, input-manifest, and runtime-identity hashes;
3. re-hashes all 60 A3Ms per target and rejects missing, changed, or extra files;
4. requires empty AF2 output directories and absent terminal records/receipts;
5. requires the exact packet token and rejects any existing recovery journal or summary;
6. enumerates exactly three AF2 jobs and no ProteinMPNN or Boltz jobs.

Each Slurm job repeats the target verification before invoking ColabFold. Local and Cayuga dry-runs pass
this full sequence with zero scheduler calls and zero receipt writes. The Cayuga user queue is empty.

## Approval boundary

No recovery approval is currently recorded, and no recovery job has been submitted. The exact phrase is:

```text
approve W3b AF2 fit recovery for failed jobs 3085449,3085452,3085455 on H100
```

The matching environment value is:

```text
BIO_SFM_APPROVE_W3B_AF2_RECOVERY=approve-w3b-af2-fit-recovery-3085449-3085452-3085455-h100
```

Generic continuation, goal-mode resume, and the consumed initial fit approval are insufficient. After any
approved recovery, scheduler provenance and terminal success must be audited before AF2 outputs are synced
or the paired fit assembler is run.
