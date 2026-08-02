# M6d W3c-B2 Native Dual-Predictor Screen

Date: 2026-08-02

Status: `sixteen_jobs_submitted_awaiting_terminal_outputs`

## Purpose

W3c-B2 asks a single validity question before any generator work: can both frozen structure predictors
recover the native geometry of the eight representation-locked strict target-binder complexes? This stage
localizes predictor/protocol failure. It does not learn a threshold, evaluate generated binders, certify a
trust gate, or support a biological-success claim.

## Frozen scope

- Targets: `1TE1_BA`, `3QB4_AB`, `5E5M_AB`, `5JSB_AB`, `6KBR_AC`, `6KMQ_AB`, `6SGE_AB`, `7B5G_AB`
- Predictors: `boltz2_complex` and `af2_multimer_colabfold_v1`
- Evaluations: exactly one native-sequence evaluation per target and predictor, 16 maximum
- Compute ceiling: 16 one-hour H100 jobs, 16 H100 GPU-hours maximum
- Seed: `0`
- Templates: disabled
- Prediction-time network: disabled
- Retry or adaptive top-up: disabled
- ProteinMPNN designs: `0`

Each predictor record must pass strict provenance and structural QC with finite interface pAE and native-
complex L-RMSD. A target passes only if both predictors have L-RMSD below `4.0 A`. W3c-B2 passes only if at
least six of eight targets pass. Failure stops W3c before candidate generation and requires a separately
preregistered revision of representation or predictor scope.

## Input and runtime readiness

W3c-A locked the eight native complexes, and W3c-B1 completed all eight frozen target MSAs. The W3c-B2
manifest binds those prepared structures, sequences, MSAs, and expected output contracts. The runtime lock
binds freshly reobserved Cayuga identities for both predictors without executing a prediction.

- Runtime lock SHA-256: `d25f609473c03137283f3cd5f293a090ffb71b8fc7a81a81ba954fd7dc13198d`
- Approval packet SHA-256: `8ab2beb9145ab0fed44e172b127ba8cb137a8ef31a99725b33da02fa26c157dd`
- Exact one-shot approval consumed: `true`
- Predictor jobs submitted: `16/16`
- Additional jobs authorized: `0`
- Terminal H100 accounting: pending

## No-submit validation

The complete packet passed both local and Cayuga dry-runs. Each replay rederived and verified the bound
execution paths, enumerated all eight target pairs and 16 predictor evaluations, confirmed 77/77 expected
output paths absent, and created no scheduler job, submission receipt, or result. The Cayuga check used the
same staged bytes as the local packet. No API call, ProteinMPNN generation, structure prediction, or GPU
allocation occurred.

## Submission state

The exact approval phrase was received and consumed once on 2026-08-02. The guarded bridge reverified the
packet and all 77 output paths immediately before submission, then recorded exactly 16 jobs: `3171272`
through `3171287`, one Boltz and one AF2 evaluation for each frozen target. The append-only summary passes
at `16/16`, with retry jobs `0` and adaptive top-up jobs `0`. The jobs are waiting in Cayuga's shared H100
queue; terminal outputs and Slurm accounting do not yet exist. Submission is operational evidence only and
does not establish native recoverability.

## Approval boundary

Readiness alone did not authorize execution. The guarded submitter rejected a missing or inexact approval
token, preexisting outputs, packet drift, runtime drift, scope drift, and any attempt to exceed the frozen
budget. The accepted one-shot authorization phrase was:

`approve W3c-B2 native dual-predictor screen on H100`

That approval is now consumed and cannot authorize a retry, top-up, or replacement job. The resulting
records must be assembled and adjudicated by the preregistered rule. A pass permits preparation of a new,
separately approved generator-yield protocol; it does not authorize ProteinMPNN itself. A fail stops the
branch before generation. At the present boundary, native recoverability remains unknown.

## Key artifacts

- Native-screen manifest: `configs/m6d_w3c_b2_native_screen_manifest.json`
- Runtime lock: `configs/m6d_w3c_b2_runtime_lock.json`
- Runtime readiness: `results/m6d_w3c_b2_runtime_readiness.{json,md}`
- Approval readiness: `results/m6d_w3c_b2_prediction_packet_readiness.{json,md}`
- Approval packet: `results/m6d_w3c_b2_prediction_approval_packet.json`
- Cayuga no-submit evidence: `results/m6d_w3c_b2_cayuga_no_submit_validation.json`
- Submission receipt: `results/m6d_w3c_b2_submit_receipt.jsonl`
- Submission summary: `results/m6d_w3c_b2_submit_receipt_summary.json`
- Guarded submitter: `hpc/m6d_w3c_b2_submit_with_receipt.sh`
- Producer: `bio_sfm_designer.experiments.m6d_w3c_b2_producer`
- Adjudicator: `bio_sfm_designer.experiments.m6d_w3c_b2_native_screen`
