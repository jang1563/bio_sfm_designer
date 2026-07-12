# Results and Claim Boundaries

## Release-level summary

| Result | Evidence | Interpretation |
|---|---|---|
| CPU DBTL loop | Public unit/integration tests | The orchestration, gate, safety, scoring, and feedback path is runnable without model APIs or GPUs. |
| Interface-confidence signal | Canonical 192-design reanalysis: AUROC 0.9381 | Lower pAE ranks successful interfaces on this substrate, but ranking alone is not a risk certificate. |
| Split-LTT alpha 0.3 check | 29 certification accepts, 9 false accepts, UCB 0.5096 | The former positive threshold does not survive independent certification; the gate trusts 0/64 test rows. |
| W2b exact-LTT panel | 4 certified `trust_all` controls, 0 selective certificates | The panel success rule fails because it requires at least one selective certificate. |
| W2c design power | Conditional power 0.817860 at 90 accepts | The prospective design is powered under its assumptions, but no W2c model records exist. |

## W2b terminal result

The checked report is
`results/m6d_w2b_target_adaptive_certification_report.json`.

- status: `w2b_certification_terminal_not_supported`;
- initial targets: 8;
- fit-eligible targets: 5;
- exact target alpha: 0.2;
- certified `trust_all` targets: 4;
- certified `selective_pae` targets: 0;
- panel gate: failed.

The decisive selective target, `1F51_AE`, accepted 31 certification rows with
6 false accepts. Its exact one-sided upper bound was 0.4002, above alpha 0.2.
Its diagnostic pAE AUROC of 0.7839 remains scientifically informative but does
not affect the certificate.

This result is not W2 generalization evidence. The four `trust_all` controls do
not answer whether a selective gate transfers across targets, and pooled-only
evidence is not proof of target-wise control.

## W2c prospective boundary

`configs/m6d_w2c_one_shot_protocol.json` defines a fresh selective-only
experiment. Eight new targets were selected without model-label use. The
release records zero generated W2c rows and stops before target-MSA execution.
No W2c or W2 generalization claim is supported.

## W3 boundary

Independent-predictor robustness is not supported. W3 remains a future
predeclared evaluation question rather than a positive result.

## Reproducibility

The W2b report is replayed from the checked protocol and two public fixtures:

- `tests/fixtures/m6d_w2b_target_adaptive_fit_records.jsonl` (480 rows);
- `tests/fixtures/m6d_w2b_target_adaptive_certification_records.jsonl` (300 rows).

The public manifest records their SHA-256 digests. Raw scheduler logs, model
state, and operator receipts are not release evidence.
