# M6d W3c-B2 Native Dual-Predictor Screen

Date: 2026-08-02

Status: `w3c_b2_terminal_partial_result_impossibility_stop`

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
- Scheduler jobs terminal: `16/16`
- Strict predictor records recovered: `8/16` (all Boltz)
- Additional jobs authorized: `0`
- Terminal H100 accounting: `1,357` GPU-seconds (`0.376944` H100 GPU-hours)

## No-submit validation

The complete packet passed both local and Cayuga dry-runs. Each replay rederived and verified the bound
execution paths, enumerated all eight target pairs and 16 predictor evaluations, confirmed 77/77 expected
output paths absent, and created no scheduler job, submission receipt, or result. The Cayuga check used the
same staged bytes as the local packet. No API call, ProteinMPNN generation, structure prediction, or GPU
allocation occurred.

## Terminal execution state

The exact approval phrase was received and consumed once on 2026-08-02. The guarded bridge reverified the
packet and all 77 output paths immediately before submission, then recorded exactly 16 jobs: `3171272`
through `3171287`, one Boltz and one AF2 evaluation for each frozen target. The append-only summary passes
at `16/16`, with retry jobs `0` and adaptive top-up jobs `0`.

All 16 jobs are now terminal. Boltz jobs `3171272`, `3171274`, `3171276`, `3171278`, `3171280`, `3171282`,
`3171284`, and `3171286` completed with exit `0:0`. AF2 jobs `3171273`, `3171275`, `3171277`, `3171279`,
`3171281`, `3171283`, `3171285`, and `3171287` failed with exit `1:0`. Exact Slurm accounting observes
`1,357` H100 GPU-seconds, well below the `57,600`-second ceiling. No retry or top-up is authorized.

Every AF2 job passed approval verification, target-context validation, input preparation, runtime
reobservation, and CUDA preflight. ColabFold `1.6.1` then stopped in `get_queries` because its container
could not resolve the packet-relative `af2_inputs` path. Each stderr ends with the target-specific
`OSError: hpc_outputs/m6d_w3c_b2_native/<TARGET>/af2_inputs could not be found`. No AF2 model output or
strict record exists. This is classified narrowly as a pre-inference container path-resolution failure,
not as an AF2 scientific failure.

## CPU replay and frozen decision

All eight Boltz strict records pass frozen identity, runtime, sequence, reference, output-path, and
SHA-256 checks. Interface pAE and native-complex L-RMSD were recomputed from each bound model and pAE
array rather than trusted from the records.

| Target | interface pAE | L-RMSD (A) | Boltz success |
|---|---:|---:|:---:|
| `1TE1_BA` | 11.4271 | 30.981252 | false |
| `3QB4_AB` | 18.0891 | 58.449146 | false |
| `5E5M_AB` | 4.4283 | 2.426855 | true |
| `5JSB_AB` | 3.2575 | 0.644485 | true |
| `6KBR_AC` | 9.2236 | 17.343068 | false |
| `6KMQ_AB` | 4.1455 | 7.910633 | false |
| `6SGE_AB` | 11.0180 | 7.319867 | false |
| `7B5G_AB` | 8.4088 | 39.582202 | false |

Boltz succeeds on only `2/8` targets. Because a frozen target pass requires both predictors, no possible
assignment of the missing AF2 outcomes can produce more than `2/8` dual-predictor target passes. The stage
requires at least `6/8`; therefore stage pass is mathematically impossible. The stage decision is complete
and negative even though full dual-predictor native recoverability is not evaluable.

## Terminal completion bridge

`hpc/m6d_w3c_b2_complete_and_sync.sh` was the fail-closed full-completion path. It correctly kept full
retrieval and 16-record adjudication locked because eight receipt-bound jobs ended in terminal failure.
The script can neither submit nor retry work, and its failure is preserved as the one-shot outcome.

The separate CPU-only `m6d_w3c_b2_terminal_stop` adjudicator accepts no submission authority. It replays the
terminal accounting, all available Boltz output hashes and metrics, and all AF2 input/runtime/log evidence.
It reports `audit_ok=true` because the partial evidence is coherent and sufficient for the monotonic
impossibility proof; the source accounting remains `audit_ok=false` because eight scheduler jobs failed.

## Approval boundary

Readiness alone did not authorize execution. The guarded submitter rejected a missing or inexact approval
token, preexisting outputs, packet drift, runtime drift, scope drift, and any attempt to exceed the frozen
budget. The accepted one-shot authorization phrase was:

`approve W3c-B2 native dual-predictor screen on H100`

That approval is consumed and cannot authorize a retry, top-up, AF2 recovery, or replacement job. W3c-B2
now stops before candidate generation. Any representation/predictor successor, including any scientifically
motivated AF2 recovery, requires a separate preregistered and explicitly approved protocol.

The supported claim is only that the frozen W3c-B2 `>=6/8` pass criterion is unreachable. This is not a
complete dual-predictor native-recoverability estimate, generator-yield evidence, trust-gate evidence, or
biological binder-success evidence.

## Key artifacts

- Native-screen manifest: `configs/m6d_w3c_b2_native_screen_manifest.json`
- Runtime lock: `configs/m6d_w3c_b2_runtime_lock.json`
- Runtime readiness: `results/m6d_w3c_b2_runtime_readiness.{json,md}`
- Approval readiness: `results/m6d_w3c_b2_prediction_packet_readiness.{json,md}`
- Approval packet: `results/m6d_w3c_b2_prediction_approval_packet.json`
- Cayuga no-submit evidence: `results/m6d_w3c_b2_cayuga_no_submit_validation.json`
- Submission receipt: `results/m6d_w3c_b2_submit_receipt.jsonl`
- Submission summary: `results/m6d_w3c_b2_submit_receipt_summary.json`
- Slurm accounting snapshot: `results/m6d_w3c_b2_sacct.tsv`
- Terminal accounting: `results/m6d_w3c_b2_completion_accounting.{json,md}`
- Replayed Boltz records: `results/m6d_w3c_b2_boltz_native_records.jsonl`
- AF2 failure evidence: `results/m6d_w3c_b2_af2_failure_evidence.jsonl`
- Terminal partial-result report: `results/m6d_w3c_b2_terminal_stop.{json,md}`
- Guarded submitter: `hpc/m6d_w3c_b2_submit_with_receipt.sh`
- Fail-closed completion bridge: `hpc/m6d_w3c_b2_complete_and_sync.sh`
- Producer: `bio_sfm_designer.experiments.m6d_w3c_b2_producer`
- Adjudicator: `bio_sfm_designer.experiments.m6d_w3c_b2_native_screen`
- Accounting and completion: `bio_sfm_designer.experiments.m6d_w3c_b2_completion`
- Terminal-stop adjudicator: `bio_sfm_designer.experiments.m6d_w3c_b2_terminal_stop`
