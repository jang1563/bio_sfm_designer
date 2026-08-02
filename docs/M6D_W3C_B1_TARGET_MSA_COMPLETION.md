# M6d W3c-B1 target-MSA completion

Status: `target_msa_precompute_complete_8_of_8`.

Date: 2026-08-02.

## Result

The exact W3c-B1 approval was consumed once through the hash-bound guarded wrapper. Exactly eight
one-hour A40 jobs were submitted, one for each prospectively locked W3c target. All eight top-level Slurm
jobs completed with state `COMPLETED` and exit code `0:0`:

| Target | Job | Elapsed seconds | A3M records |
|---|---:|---:|---:|
| `1TE1_BA` | `3118725` | 682 | 2442 |
| `3QB4_AB` | `3118726` | 851 | 1909 |
| `5E5M_AB` | `3118727` | 677 | 96 |
| `5JSB_AB` | `3118728` | 655 | 287 |
| `6KBR_AC` | `3118729` | 610 | 7447 |
| `6KMQ_AB` | `3118730` | 429 | 3195 |
| `6SGE_AB` | `3118731` | 174 | 8845 |
| `7B5G_AB` | `3118732` | 66 | 7594 |

The total allocation was 4,144 A40 GPU-seconds, or `1.151111` A40 GPU-hours, below the approved
8 A40 GPU-hour ceiling. The observed A3M depth ranges from 96 to 8,845 records. Every target remains in
the frozen panel; no target was removed or selected after observing MSA depth.

## Integrity checks

All eight A3M/report pairs pass the frozen sequence, query identity, no-truncation, nontrivial-depth,
NUL-sanitization, path, and SHA-256 checks. Strict execution-manifest replay is ready for all eight
targets. The completion adjudicator ignores child Slurm steps and requires the exact top-level job rows,
which prevents an unrelated diagnostic step from changing the batch-job verdict.

The public-safe completion record is
`results/m6d_w3c_b1_target_msa_completion.{json,md}`. Raw A3Ms, operational receipts, and scheduler
accounting remain ignored local evidence.

## Transport observation

The packet-bound helper used `boltz predict --use_msa_server` as the MSA transport. In every target, the
MSA artifact was retrieved before Boltz's downstream target-only inference returned nonzero. The helper
recovered and sanitized each A3M. This is recorded as eight MSA transport invocations, eight recovered
post-MSA inference failures, zero consumed structure-prediction outputs, zero candidate-level predictor
evaluations, and zero ProteinMPNN designs.

This is target-MSA input preparation success, not Boltz structure-prediction success.

## Claim and authority boundary

W3c-B1 supplies no evidence for native recoverability, generator yield, trust-gate calibration, or
biological binder success. It authorizes no W3c-B2 compute and no ProteinMPNN work.

The next allowed action is to prepare a separate hash-bound, no-submit W3c-B2 packet for exactly eight
native complexes evaluated by two frozen predictors. H100 runtime re-observation and packet validation
must occur without prediction. Any 16-evaluation native screen requires a new exact approval.
