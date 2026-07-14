# M6d W3b fit-stage approval boundary

Status: `producer_and_submit_contract_ready_awaiting_target_msa_execution_lock_no_submit`.

Date: 2026-07-15.

## Current state

The W3b fit execution surface is implemented, but the fit approval packet is intentionally not emitted.
The eight target MSAs remain 0/8 and the lifecycle-derived execution manifest/input lock therefore do not
exist. `results/m6d_w3b_fit_packet_readiness.{json,md}` is audit-clean and reports
`w3b_fit_packet_awaiting_target_msa_and_execution_lock`.

This state submits no job, records no approval, generates no candidate, runs no predictor, and supports no
W3b or biological-success claim. The earlier W3 mechanism-panel approval does not authorize W3b.

## Frozen fit scope

A future fit approval can cover exactly:

- targets: `1FSK_LJ`, `1FSX_BA`, and `1FL7_DC`;
- one ProteinMPNN candidate set per target, 60 unique sequences each;
- 180 candidate designs total;
- matched Boltz-2 and AF2-Multimer prediction for every candidate;
- 360 predictor evaluations total;
- 3 CPU ProteinMPNN jobs, 3 H100 Boltz jobs, and 3 H100 AF2 jobs;
- no certification, held-out test, adaptive top-up, threshold retuning, or scientific claim.

Each H100 job is submitted with a hard four-hour wall-time and `--no-requeue`. The six H100 jobs therefore
cannot allocate more than the protocol-wide 24 H100 GPU-hour ceiling during fit. Actual Slurm GPU accounting
must be reconciled before any later-stage packet; unused budget is not inferred from wall-time requests.

## Dedicated producers

Historical W2b/W2c helpers remain unchanged. W3b uses dedicated, packet-bound execution authority:

- `hpc/run_generate_proteinmpnn_w3b_fit.sbatch` validates the target/input locks, invokes the frozen shared
  ProteinMPNN generator, and rejects an incomplete, duplicate-ID, or duplicate-sequence 60-row output;
- `hpc/run_predict_boltz_w3b_fit.sbatch` re-hashes the installed Boltz 2.2.1 distribution and both cache
  checkpoints before running explicit model `boltz2`, seed `0`, 100 sampling steps, 3 recycles, one diffusion
  sample, local target MSA, binder single sequence, no templates, full pAE, and no MSA server;
- `hpc/run_predict_af2_w3b_fit.sbatch` re-hashes the ColabFold container and all five Multimer-v3 weights,
  then runs seed `0`, five models, 20 recycles, no relaxation, no templates, and an isolated network namespace;
- both converters require complete model outputs, target-aligned L-RMSD, interface pAE, and candidate/MSA/
  runtime/model-output SHA-256 provenance before writing records;
- `hpc/m6d_w3b_fit_submit_with_receipt.sh` limits submission to the three locked fit targets and writes an
  append-only nine-event journal through `m6d_w3b_fit_submit_journal`;
- `hpc/run_w3b_fit_guarded.sh` re-derives and verifies the approval packet before any `sbatch` call.

## Future unlock sequence

1. Obtain the separate target-MSA approval, complete all 8/8 jobs, sync back, and materialize the execution
   manifest/input lock.
2. Rebuild all W3b runtime and matched-record readiness artifacts.
3. Emit `results/m6d_w3b_fit_approval_packet.json` with:

   ```bash
   python -m bio_sfm_designer.experiments.m6d_w3b_fit_packet \
     --emit-approval-packet results/m6d_w3b_fit_approval_packet.json
   ```

4. Run the guarded bridge with `BIO_SFM_SUBMIT_DRY_RUN=1`; it must enumerate exactly three target triplets,
   180 candidates, 360 predictor evaluations, zero `sbatch` calls, and zero receipt writes.
5. Stop and request a separate exact fit approval. The future approval phrase is
   `approve W3b fit-stage 180-design matched Boltz-AF2 generation on H100`; its machine token is
   `approve-w3b-fit-180-matched-h100` in `BIO_SFM_APPROVE_W3B_FIT`.

The current user approval history does not contain that W3b fit phrase or token.

## Post-submit boundary

Submission creates `results/m6d_w3b_fit_submit_receipt.jsonl` and its summary. Those artifacts prove scheduler
scope only. All nine jobs must reach terminal success, cumulative H100 usage must remain within the frozen
budget, every output must sync with exact hash parity, and both per-target predictor receipts must validate
before the CPU assembler can produce 180 matched rows. Fit results then either freeze a qualifying primary
rule and comparator or stop W3b before certification. Submission or job completion alone is never evidence.
