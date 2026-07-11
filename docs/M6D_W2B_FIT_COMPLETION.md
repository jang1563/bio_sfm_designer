# M6d W2b Fit Completion

Status: `fit_complete_5_eligible_awaiting_explicit_certification_approval`.

The fit-only stage completed on 2026-07-11. It freezes target-specific modes and one pAE threshold. It does
not certify any target and does not authorize certification or test compute.

## Execution

- initial targets: 8;
- ProteinMPNN candidates: 60 per target, 480 total, all exact binder sequences unique;
- Boltz records: 60 per target, 480 total;
- strict record QC: 480 unique IDs, 0 exact duplicates, 0 failures;
- original Boltz jobs: `3079709`, `3079711`, `3079713`, `3079715`, `3079717`, `3079719`, `3079721`,
  `3079723`;
- approved hardware migration: all eight still-pending jobs moved together from A40 `scu-gpu/normal` to
  H100 `preempt_gpu/low`, with no A40 result records produced;
- H100 node: `g0004`; all jobs completed with exit code `0:0` in 3:20 to 4:54.

The original submission journal was not modified. Hardware approval, before/after resources, job states,
elapsed times, output counts, and QC hashes are recorded separately in
`results/m6d_w2b_target_adaptive_fit_h100_migration_receipt.jsonl`.

## Frozen Fit Result

Success is `L-RMSD < 4.0 A`. Lower `pAE_interaction` is the predeclared favorable direction.

| target | raw success | fit mode | tau | accepted | false accepts | fit risk | pAE AUROC |
|---|---:|---|---:|---:|---:|---:|---:|
| `1F51_AE` | 38/60 | `selective_pae` | 5.7365 | 40 | 8 | 0.20 | 0.8421 |
| `1F66_AB` | 29/60 | `refuse` | - | 0 | 0 | - | 0.5217 |
| `1F93_DC` | 60/60 | `trust_all` | - | 60 | 0 | 0.00 | - |
| `1FDH_GA` | 54/60 | `trust_all` | - | 60 | 6 | 0.10 | 0.9444 |
| `1FJG_FR` | 0/60 | `refuse` | - | 0 | 0 | - | - |
| `1FLT_WV` | 60/60 | `trust_all` | - | 60 | 0 | 0.00 | - |
| `1FVC_DC` | 60/60 | `trust_all` | - | 60 | 0 | 0.00 | - |
| `1FXK_CA` | 1/60 | `refuse` | - | 0 | 0 | - | 0.7119 |

Fit-eligible targets are `1F51_AE`, `1F93_DC`, `1FDH_GA`, `1FLT_WV`, and `1FVC_DC`. Refused targets
remain in the eight-target denominator.

## Interpretation

The fit result is scientifically useful but not yet positive W2b evidence:

- `1F51_AE` is the required signal-bearing branch: pAE ranks interface success well enough to select and
  freeze a target-specific threshold;
- `1F93_DC`, `1FLT_WV`, and `1FVC_DC` are easy fit targets whose predeclared mode is `trust_all`; they may
  support risk control if fresh certification rows remain stable, but they do not establish a pAE signal;
- `1FDH_GA` also selects `trust_all` because mode order is locked, despite strong diagnostic pAE ranking;
- `1F66_AB` has near-chance pAE ranking, `1FJG_FR` has no fit successes, and `1FXK_CA` has too few
  successes to support the minimum accepted set, so all three correctly refuse.

The panel success rule remains reachable because five targets are eligible and one uses `selective_pae`.
The selective branch is also the main risk. At per-target delta 0.0125, the exact one-sided
Clopper-Pearson rule permits only the following false accepts:

| certification accepts | maximum false accepts for UCB <= 0.2 |
|---:|---:|
| 22 | 0 |
| 30 | 1 |
| 40 | 2 |
| 50 | 3 |
| 60 | 5 |

`1F51_AE` had 8 false accepts among 40 fit accepts, so its frozen rule has real ranking signal but is not
already close to an exact certificate. Fresh certification data, not fit optimism, must decide the claim.

## Reproducibility

- CPU-replay fixture: `tests/fixtures/m6d_w2b_target_adaptive_fit_records.jsonl`
  (`3187ba56a3eb39e4820d17c42e6a8ffd8ce28add05d858645a1e92427c6d4dbe`);
- strict fixture QC: `results/m6d_w2b_target_adaptive_fit_fixture_qc.json`
  (`8f7b86e0bc7dcd63b9bbb87b722e541afff464b1efdc0dc9e01433eabd32595d`);
- fit report: `results/m6d_w2b_target_adaptive_fit_report.json`
  (`6aac81be46805ad983e770af49f15e38cac140d469e4541e40788a21129ef3c1`);
- output manifest: `results/m6d_w2b_target_adaptive_fit_output_manifest.json`
  (`6f71eab1dc123d292e779763e2c03897d44a30a297245c39a942ba0000c271b9`);
- H100 migration receipt: `results/m6d_w2b_target_adaptive_fit_h100_migration_receipt.jsonl`
  (`53a5c0e51d2d29e4c0bff423faf36649b0c6d6777ba23ca2091c9ed15165321f`).

## Next Approval Gate

The next evidence-bearing stage is certification only for the five fit-eligible targets:

- 60 fresh records per target, 300 total;
- ProteinMPNN seed `1037`;
- namespace `w2b-cert-v1`;
- the five frozen rules above, including `1F51_AE` tau 5.7365;
- no test-stage generation or folding.

The certification manifest, fresh input lock, and guarded H100 command are now prepared and have passed
local plus Cayuga dry-runs without submission. Exact scope is in `docs/M6D_W2B_CERTIFICATION_APPROVAL.md`;
separate explicit execution approval is still required. Test-stage compute remains separately unauthorized.
