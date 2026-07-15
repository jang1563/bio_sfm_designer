# M6d W3b target-MSA completion

Status: `target_msa_precompute_complete_8_of_8`.

Date: 2026-07-15.

## Approved execution

The exact approval `approve W3b target-MSA precompute` was consumed for the frozen eight-target
MSA-only packet. The guarded wrapper submitted jobs `3085384` through `3085391`, one for each locked
target. All eight jobs reached `COMPLETED/0:0`; no retry, ProteinMPNN generation, candidate-level Boltz
prediction, AF2-Multimer prediction, certification, or held-out test was submitted.

The eight jobs allocated 779 one-GPU seconds, or `0.216389 A40 GPU-hours`, against the approved
8 A40 GPU-hour ceiling.

## Strict replay

The scoped sync copied exactly the 56 manifest-declared input-prep artifacts: source PDB, prepared PDB,
preparation report, target FASTA, FASTA report, target A3M, and A3M report for each target. Strict replay
passes with:

- targets: `8/8`;
- terminal scheduler records: `8/8 COMPLETED/0:0`;
- target A3M/report pairs: `8/8`;
- A3M reports with `ok=true`: `8/8`;
- frozen target-sequence hashes: `8/8`;
- lifecycle failures: `0`;
- design power: `0.824333`;
- claim status: no W3b gate or biological-success claim.

## Slurm telemetry reconciliation

Cayuga's raw `sacct AllocTRES` retained `gres/gpu=1` but omitted the GPU subtype. The original frozen
lifecycle therefore failed closed with exactly eight `job_gpu_allocation_invalid` records even though the
jobs and outputs succeeded. Raw accounting was not edited.

The versioned no-submit reconciliation in
`bio_sfm_designer.experiments.m6d_w3b_target_msa_allocation_reconcile` restores `a40` in memory only after
all of the following independent checks pass:

- the consumed packet still binds the exact sbatch containing `--gres=gpu:a40:1`;
- submit-time `scontrol` records cover all eight receipt job IDs and report
  `TresPerNode=gres/gpu:a40:1`;
- terminal raw `sacct` reports exactly one GPU and `COMPLETED/0:0` for every job;
- the terminal node inventory reports `Gres=gpu:a40:4`;
- the raw lifecycle failures contain no failure other than the eight omitted-subtype failures.

The adapter has no path for suppressing scientific, manifest, sequence, report, job-state, budget, or
scope failures. Raw evidence remains ignored operational data; the tracked lifecycle stores its hashes,
the extracted audit result, and the exact normalization scope.

## Execution lock and next boundary

The completed lifecycle materialized and verified:

- `configs/m6d_w3b_execution_targets.json`;
- `configs/m6d_w3b_execution_input_lock.json`;
- `results/m6d_w3b_execution_lock_readiness.{json,md}`.

These artifacts bind all eight MSA hashes and 870 preregistered stage-assigned design slots. Runtime and
matched-record readiness are audit-clean. The separate fit approval packet is now emitted and its guarded
dry-run enumerates exactly three fit targets, 180 candidates, 360 matched predictor evaluations, 3 CPU
jobs, and 6 H100 jobs with zero `sbatch` calls and zero receipt writes.

No fit compute is approved. The next exact approval phrase is
`approve W3b fit-stage 180-design matched Boltz-AF2 generation on H100`.
