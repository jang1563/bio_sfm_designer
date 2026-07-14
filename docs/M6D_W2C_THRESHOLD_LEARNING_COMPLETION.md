# M6d W2c Threshold-Learning Completion

Status: `w2c_threshold_learning_terminal_not_supported`.

Date: 2026-07-14.

## Decision

The approved `w2c-fit-learn-v1` stage completed exactly as locked: eight fresh targets,
60 ProteinMPNN designs per target, and 480 Boltz-2 complex records. Strict provenance QC
passed all 480 rows with zero failures. The learning-only evaluator then froze a refusal
for all eight targets. The protocol requires at least three selective-pAE threshold
candidates before independent screening; the observed count is zero.

W2c is therefore terminal before independent-screen or certification compute. This result
does not support W2c selective target-adaptive viability or universal W2 generalization.

## Execution Evidence

- 8 CPU ProteinMPNN jobs and 8 dependent H100 Boltz jobs completed with exit code `0:0`;
- 480/480 candidate IDs and 480/480 record IDs are unique and stage-isolated;
- all 16 candidate/record files have exact local-to-Cayuga SHA-256 parity;
- predictor provenance is `boltz2_complex` / `boltz2_pae_interaction` /
  `boltz2_lrmsd_to_reference`;
- no retry or resubmission was required;
- the eight H100 jobs consumed 3,879 allocation-seconds, or 1.0775 H100 GPU-hours.

The detailed operational record is intentionally local and ignored:
`results/m6d_w2c_fit_learn_completion.json`. The learning report is
`results/m6d_w2c_threshold_learning_report.json` with SHA-256
`d22d04750c408113bcba2b96507efc3637d47e6db692d3aec1045b94e75c3c9e`.

## Frozen Target Decisions

The pre-locked rule required AUROC at least 0.65 and a deterministic pAE acceptance
region containing at least 30 rows with empirical false-accept rate at most 0.08.

| Target | L-RMSD successes | pAE AUROC | Best FAR at n>=30 | Frozen decision |
|---|---:|---:|---:|---|
| `1FR2_BA` | 24/60 | 0.9248 | 9/30 = 0.3000 | refuse |
| `1F80_BC` | 15/60 | 0.3363 | 43/58 = 0.7414 | refuse |
| `1EZV_XY` | 60/60 | undefined | 0/30 = 0.0000 | refuse |
| `1FFG_CD` | 39/60 | 0.7998 | 3/31 = 0.0968 | refuse |
| `1FFK_HR` | 0/60 | undefined | 30/30 = 1.0000 | refuse |
| `1FQ9_CA` | 2/60 | 0.9655 | 28/30 = 0.9333 | refuse |
| `1FYR_CD` | 0/60 | undefined | 30/30 = 1.0000 | refuse |
| `1F99_BA` | 14/60 | 0.8261 | 18/30 = 0.6000 | refuse |

`Best FAR at n>=30` is a transparent diagnostic over the frozen learning rows, not a new
selection rule. `1EZV_XY` has all-success rows, so discrimination AUROC is undefined;
because W2c was declared selective-pAE-only and `trust_all` cannot count, it must refuse.
`1FFG_CD` is the closest selective case but still exceeds the locked 0.08 cap. Several
other targets have high ranking AUROC but insufficient absolute success capacity, showing
that ranking signal alone does not create a useful low-risk acceptance region.

## Claim Boundary

- W1 target-specific evidence remains preserved.
- W2 universal multi-target generalization remains unsupported.
- W2b target-adaptive v1 remains terminally unsupported.
- W2c selective target-adaptive viability is now terminally unsupported under its locked
  prospective threshold-learning rule.
- Independent-screen and certification generation are not approved and were not submitted.

No threshold, sample count, AUROC floor, false-accept cap, or `trust_all` exclusion may be
changed to rescue this run. The next scientific step is a distinct W3 experiment focused
on predictor robustness or an explicit analysis of why ranking quality and usable selective
coverage diverge across targets.
