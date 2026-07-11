# M6d W2b Certification Completion

Status: `w2b_certification_terminal_not_supported`.

The certification-only stage completed on 2026-07-11. Four `trust_all` targets passed exact risk
certification, but the sole `selective_pae` target failed. The locked panel requires at least one selective
certificate, and test data cannot change certificates. W2b v1 therefore stops here without test compute.

## Execution

- targets: `1F51_AE`, `1F93_DC`, `1FDH_GA`, `1FLT_WV`, `1FVC_DC`;
- ProteinMPNN candidates: 60 per target, 300 total;
- Boltz records: 60 per target, 300 total;
- candidate QC: 300 unique IDs, 300 unique sequences, fit-sequence overlap 0;
- strict record QC: 300 unique keys, exact duplicates 0, failures 0;
- ProteinMPNN jobs: `3079899`, `3079901`, `3079903`, `3079905`, `3079907`;
- H100 Boltz jobs: `3079900`, `3079902`, `3079904`, `3079906`, `3079908`;
- hardware: Cayuga `g0004`, NVIDIA H100 NVL, `preempt_gpu/low/gpu:h100:1`;
- all ten jobs: `COMPLETED`, exit code `0:0`;
- Boltz elapsed range: 3:22 to 4:54.

The append-only submission receipt remained unchanged after submission. Exact target/job mapping, elapsed
times, output hashes, and execution-time packet hashes are in
`results/m6d_w2b_target_adaptive_certification_output_manifest.json`.

## Exact Result

Success is `L-RMSD < 4.0 A`. Certification uses the frozen fit rule, target alpha 0.2, per-target delta
0.0125, at least 22 accepts, and the one-sided exact Clopper-Pearson upper bound.

| target | frozen mode | accepted | false accepts | empirical risk | exact UCB | certified |
|---|---|---:|---:|---:|---:|---|
| `1F51_AE` | `selective_pae`, tau 5.7365 | 31 | 6 | 0.1935 | 0.4002 | no |
| `1F93_DC` | `trust_all` | 60 | 0 | 0.0000 | 0.0704 | yes |
| `1FDH_GA` | `trust_all` | 60 | 2 | 0.0333 | 0.1286 | yes |
| `1FLT_WV` | `trust_all` | 60 | 0 | 0.0000 | 0.0704 | yes |
| `1FVC_DC` | `trust_all` | 60 | 0 | 0.0000 | 0.0704 | yes |

The panel certifies 4 targets, exceeding the minimum of 3, but certifies 0 selective-pAE targets instead of
the required 1. The panel certification gate therefore fails.

## Scientific Interpretation

The result separates signal transfer from risk certification:

- `1F51_AE` pAE ranking transfers to fresh data: fit AUROC was 0.8421 and certification diagnostic AUROC is
  0.7839;
- the diagnostic AUROC is reporting-only and does not affect the certificate;
- the frozen threshold reduces raw certification failures from 26/60 to 6/31 among accepted rows, but this
  is not enough for the declared confidence level;
- with 31 accepts, at most 1 false accept is compatible with exact UCB at most 0.2; the observed count is 6;
- the four `trust_all` certificates establish that those target distributions are easy under the current
  generator/predictor pair, not that pAE provides selective gating.

The main design lesson is that selecting a fit threshold at empirical risk equal to alpha leaves almost no
margin for exact certification. `1F51_AE` fit risk was exactly 8/40 = 0.2; fresh empirical risk remained near
that boundary at 6/31 = 0.1935, so finite-sample uncertainty made the exact UCB much larger than alpha.

## Terminal Stop

The locked panel decision requires at least one certified `selective_pae` target. `1F51_AE` is the only such
target and its certification result is fixed. The protocol explicitly states that the test split does not
affect certificates. Consequently:

- no possible test result can make W2b v1 pass;
- test-stage generation and folding would be non-decisive compute;
- no test job was submitted;
- `can_claim_w2b_target_adaptive_viability` remains false;
- universal or zero-shot W2 generalization remains unsupported.

## Reproducibility

- certification fixture: `tests/fixtures/m6d_w2b_target_adaptive_certification_records.jsonl`
  (`4ebc9156f839eea1fefaaa274310cb28b73ffcfdb898b7b0a8dbc5d4aeebaa70`);
- fixture QC: `results/m6d_w2b_target_adaptive_certification_fixture_qc.json`
  (`ed846c877ce531516417942d2cc8c4945afd8052fd4fb1923ed7b5fbcd53bf37`);
- certification report: `results/m6d_w2b_target_adaptive_certification_report.json`
  (`87760fadffb46848bb027bc214710286ec5d057ec8ecb83030b0f361c2639d36`);
- output manifest: `results/m6d_w2b_target_adaptive_certification_output_manifest.json`
  (`9f2dd8fefc72b67e8217af8f04a51654162eef09c7f569b8a8948ded6d1b38e4`);
- submission receipt: `results/m6d_w2b_target_adaptive_certification_submit_receipt.jsonl`
  (`e3a365135dadbf4a9d561ed8112ce58921f6d349a5f7ce84191e20069c9476c6`).

The approved protocol and guard remain preserved as execution-time snapshots. The protocol's locked
scientific digest remains `19bad978cdbccfeb5cfe3ec0f7c7455bb8d2f7e10697091c15ec6b40c7341b0b`;
only mutable execution state was updated after completion.

## Recommended Next Research Direction

Do not extend W2b v1 with more certification or test rows. A successor protocol should be declared as a new
experiment and should build statistical slack into selective threshold fitting, for example by targeting a
fit risk materially below certification alpha or by using an inner confidence-aware calibration rule. It
must use fresh stage namespaces and data and must preserve this terminal result rather than reinterpreting
certification rows as fit data.
