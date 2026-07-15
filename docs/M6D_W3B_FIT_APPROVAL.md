# M6d W3b fit-stage execution boundary

Status: `initial_fit_approval_consumed_af2_recovery_approval_wait`.

Date: 2026-07-15.

## Current state

The exact W3b fit approval was consumed once for the packet-bound 180-design matched Boltz-AF2 fit
stage. The guarded Cayuga bridge submitted exactly three CPU ProteinMPNN jobs, three H100 Boltz jobs,
and three H100 AF2 jobs. No certification, held-out test, adaptive top-up, threshold retuning, or claim
authority was included.

The initial nine jobs are terminal:

| Target | ProteinMPNN | Boltz | AF2 |
| --- | --- | --- | --- |
| `1FSK_LJ` | `3085447` completed | `3085448` completed | `3085449` failed before prediction |
| `1FSX_BA` | `3085450` completed | `3085451` completed | `3085452` failed before prediction |
| `1FL7_DC` | `3085453` completed | `3085454` completed | `3085455` failed before prediction |

ProteinMPNN produced exactly 180 candidates. Boltz produced exactly 180 fit records. The three AF2
jobs allocated 38 GPU-seconds in total and all failed before prediction because the container received a
relative `af2_inputs` path that it could not resolve. GPU preflight and runtime-identity checks passed
before that path error. The 180 precomputed A3Ms, candidate files, input manifests, and observed AF2
runtime identities remain intact; all three AF2 output directories are empty, and no AF2 record or
runtime-receipt file exists.

This is an operationally incomplete fit stage. It is not a W3b result and cannot support a gate,
certification, held-out test, predictor comparison, or biological-success claim.

## Consumed initial scope

The historical approval phrase was
`approve W3b fit-stage 180-design matched Boltz-AF2 generation on H100`. It authorized exactly:

- fit targets `1FSK_LJ`, `1FSX_BA`, and `1FL7_DC`;
- 60 unique ProteinMPNN candidates per target and 180 total;
- matched Boltz-2 and AF2-Multimer prediction for every candidate;
- 360 planned predictor evaluations;
- 3 CPU ProteinMPNN, 3 H100 Boltz, and 3 H100 AF2 jobs;
- no certification, held-out test, adaptive top-up, retuning, or claim.

That approval is consumed and cannot authorize an AF2 retry.

## Separate AF2 recovery gate

The path-only recovery is frozen in
`results/m6d_w3b_fit_af2_recovery_approval_packet.json` and documented in
`docs/M6D_W3B_AF2_RECOVERY_APPROVAL.md`. It permits only three replacement AF2 jobs for failed jobs
`3085449`, `3085452`, and `3085455`. It permits zero ProteinMPNN jobs and zero Boltz jobs.

The recovery runner uses absolute container input/output paths, revalidates the packet and all 180 A3M
files before any scheduler call, revalidates again inside each job, sets `--no-requeue`, and limits each
replacement to `03:59:30`. Including the initial 38 failed AF2 GPU-seconds and the maximum original Boltz
allocation, the worst-case protocol allocation is 86,348 seconds, below the frozen 86,400-second ceiling.

Local and Cayuga dry-runs both pass with exactly three AF2 replacements enumerated, zero ProteinMPNN or
Boltz jobs, zero `sbatch` calls, and zero receipt writes. No recovery approval is recorded and no recovery
job has been submitted.

The only valid next compute authorization is the exact phrase:

```text
approve W3b AF2 fit recovery for failed jobs 3085449,3085452,3085455 on H100
```

Its packet-bound environment token is
`approve-w3b-af2-fit-recovery-3085449-3085452-3085455-h100` in
`BIO_SFM_APPROVE_W3B_AF2_RECOVERY`. Generic continuation, goal-mode resume, and the consumed initial fit
approval do not transfer.

## Evidence

- initial immutable packet: `results/m6d_w3b_fit_approval_packet.json`;
- scheduler journal and summary: `results/m6d_w3b_fit_submit_receipt.jsonl` and
  `results/m6d_w3b_fit_submit_receipt_summary.json`;
- terminal initial observation: `results/m6d_w3b_fit_initial_execution_observation.json`;
- separate no-submit recovery packet: `results/m6d_w3b_fit_af2_recovery_approval_packet.json`;
- recovery audit/runner: `m6d_w3b_fit_af2_recovery`,
  `hpc/m6d_w3b_fit_af2_recovery_with_receipt.sh`, and
  `hpc/run_predict_af2_w3b_fit_recovery.sbatch`.

After a separately approved recovery completes, sync only receipt-bound AF2 outputs, enforce exact hash
parity and matched-record QC, and then assemble the 180 paired rows. The frozen fit evaluator determines
whether W3b stops or a separate certification packet may be prepared. Recovery completion alone is not
fit evidence.
