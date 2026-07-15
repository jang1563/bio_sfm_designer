# M6d W3b matched-predictor fit completion

Status: `w3b_fit_complete_rule_not_found_terminal_stop`.

Date: 2026-07-15.

## Completion

The exact W3b fit approval and the separate AF2 path-recovery approval were each consumed once. The
initial stage produced 180 unique ProteinMPNN candidates and 180 Boltz records. Initial AF2 jobs
`3085449`, `3085452`, and `3085455` failed before prediction on a relative container path after 38
combined H100 GPU-seconds. Their separately approved replacements completed without retry:

| Target | Failed AF2 job | Recovery job | State | Elapsed seconds |
|---|---:|---:|---|---:|
| `1FL7_DC` | `3085455` | `3085544` | `COMPLETED/0:0` | 4,121 |
| `1FSK_LJ` | `3085449` | `3085545` | `COMPLETED/0:0` | 9,805 |
| `1FSX_BA` | `3085452` | `3085546` | `COMPLETED/0:0` | 1,753 |

Each replacement used one H100, `--no-requeue`, the frozen ColabFold/AF2-Multimer runtime, the same 60
precomputed A3Ms, and no prediction-time network. Each produced exactly 60 AF2 records, 300 ranked score
JSON files, 300 ranked unrelaxed PDBs, 60 completion markers, and one provenance-bound runtime receipt.

The packet requested `03:59:30`, which Slurm initially rounded up to an effective `04:00:00`. That
rounding would have raised the protocol worst case to 86,438 GPU-seconds, 38 seconds above the 86,400
ceiling. All three live jobs were therefore immediately reduced with `scontrol` to `03:59:00`. The
public-safe, field-minimized post-correction snapshot proves `JobState=RUNNING`, `Requeue=0`,
`TimeLimit=03:59:00`, and `gres/gpu:h100:1` for all three without publishing user, host, or home-path
metadata. The complete raw scheduler response remains outside the public repository.
The corrected worst case is 86,258 seconds, leaving 142 seconds of margin. Actual H100 allocation across
the three original Boltz jobs, three failed AF2 allocations, and three replacements was 16,641 seconds
(`4.6225` H100 GPU-hours).

## Matched-record QC

The strict assembler produced 180/180 matched rows, 60 per fit target, with zero failures. Every pair
matches candidate ID and sequence hash, lifecycle-derived target-MSA hash, runtime-lock identity, seed
`0`, template-off and network-off settings, and model-output hashes. The numeric-copy guard passed. The
synced compact records and receipts have exact local/Cayuga SHA-256 parity.

Key artifacts:

- public scheduler evidence: `results/m6d_w3b_fit_af2_recovery_sacct.tsv` and
  `results/m6d_w3b_fit_af2_recovery_scontrol_post_correction.txt`;
- recovery completion: `results/m6d_w3b_fit_af2_recovery_completion.json`;
- matched rows: `results/m6d_w3b_fit_matched_records.jsonl`;
- assembly report: `results/m6d_w3b_fit_matched_record_assembly.json`;
- frozen fit decision: `results/m6d_w3b_fit_gate_report.json`;
- descriptive diagnostics: `results/m6d_w3b_fit_diagnostics.json`;
- integrated completion: `results/m6d_w3b_fit_completion.json`.

## Frozen fit result

The preregistered evaluator returned `w3b_fit_rule_not_found_stop`. Neither gate froze a rule:

- primary `max_pAE + pAE_gap`: zero qualifying rules;
- Boltz-pAE-only comparator: zero qualifying rules.

The fit contract required at least 90 accepted rows in total, at least 15 per target, and empirical
false-accept risk at most 0.08 against both predictor-defined L-RMSD endpoints.

| Target | Boltz wrong / 60 | AF2 wrong / 60 | Predictor-label disagreements |
|---|---:|---:|---:|
| `1FL7_DC` | 24 | 48 | 36 |
| `1FSK_LJ` | 60 | 60 | 0 |
| `1FSX_BA` | 1 | 1 | 2 |

`1FSK_LJ` makes the frozen fit mathematically impossible, independent of threshold search. Any valid
rule must accept at least 15 rows from that target, and every such row is wrong for both endpoints. Even
if all 180 fit rows were accepted, the global false-accept lower bound would be `15/180 = 0.08333`, above
the frozen 0.08 cap.

Exhaustive descriptive enumeration agrees:

- the best primary rule satisfying frozen coverage accepts 90 rows but has worst-predictor risk
  `0.24444`;
- the best primary rule satisfying the 0.08 risk cap accepts 73 rows and zero from `1FSK_LJ`, so it fails
  both total and per-target coverage;
- the best comparator satisfying frozen coverage has worst-predictor risk `0.47761`;
- the best comparator satisfying the risk cap accepts 59 rows and zero from `1FSK_LJ`.

These are post-fit diagnostics, not alternate rules. No threshold, target, endpoint, or stop condition was
changed after observing labels.

## Decision

W3b stops at fit. Certification and held-out test are scientifically unreachable and have zero submitted
jobs. No retry, target removal, adaptive top-up, threshold retuning, or W3b rescue is allowed.

The result is useful negative evidence: target heterogeneity dominates, one target is uniformly
unsuccessful under both predictors, and another shows large endpoint disagreement. A successor may study
generator failure, target-family heterogeneity, or a different trust signal, but it must be a distinct
prospectively preregistered experiment.

The chosen successor is now W3c validity-first failure localization. The follow-up historical-pool audit
found that the 24-target representative set did not prospectively require complete biological dimers or
strict target-binder semantics. This narrows the scope of W3b without changing its terminal fit decision:
W3b remains valid for its exact prepared structural-proxy inputs, while W3c starts from fresh targets and
tests representation validity and native predictor recoverability before any new generator or gate study.
See `docs/M6D_W3C_VALIDITY_FIRST_PROTOCOL.md`.

## Claim boundary

This result supports only a terminal negative conclusion for the preregistered matched-predictor
structural-proxy fit. It is not a certificate, wet-lab binder result, universal predictor comparison, or
population-level robustness claim.
