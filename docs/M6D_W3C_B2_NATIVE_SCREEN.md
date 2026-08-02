# M6d W3c-B2 Native Dual-Predictor Screen

Date: 2026-08-02

Status: `packet_ready_awaiting_exact_approval`

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
- Current jobs authorized: `0`
- Current H100 GPU-hours authorized: `0`

## No-submit validation

The complete packet passed both local and Cayuga dry-runs. Each replay rederived and verified the bound
execution paths, enumerated all eight target pairs and 16 predictor evaluations, confirmed 77/77 expected
output paths absent, and created no scheduler job, submission receipt, or result. The Cayuga check used the
same staged bytes as the local packet. No API call, ProteinMPNN generation, structure prediction, or GPU
allocation occurred.

## Approval boundary

Readiness does not authorize execution. The guarded submitter rejects a missing or inexact approval token,
preexisting outputs, packet drift, runtime drift, scope drift, and any attempt to exceed the frozen budget.
The only accepted authorization phrase is:

`approve W3c-B2 native dual-predictor screen on H100`

After exact approval, the guarded path may submit only the frozen 16-job native screen. The resulting
records must then be assembled and adjudicated by the preregistered rule. A pass permits preparation of a
new, separately approved generator-yield protocol; it does not authorize ProteinMPNN itself. A fail stops
the branch before generation. At the present boundary, native recoverability remains unknown.

## Key artifacts

- Native-screen manifest: `configs/m6d_w3c_b2_native_screen_manifest.json`
- Runtime lock: `configs/m6d_w3c_b2_runtime_lock.json`
- Runtime readiness: `results/m6d_w3c_b2_runtime_readiness.{json,md}`
- Approval readiness: `results/m6d_w3c_b2_prediction_packet_readiness.{json,md}`
- Approval packet: `results/m6d_w3c_b2_prediction_approval_packet.json`
- Cayuga no-submit evidence: `results/m6d_w3c_b2_cayuga_no_submit_validation.json`
- Guarded submitter: `hpc/m6d_w3c_b2_submit_with_receipt.sh`
- Producer: `bio_sfm_designer.experiments.m6d_w3c_b2_producer`
- Adjudicator: `bio_sfm_designer.experiments.m6d_w3c_b2_native_screen`
