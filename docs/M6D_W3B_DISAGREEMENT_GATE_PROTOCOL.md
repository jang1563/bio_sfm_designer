# M6d W3b predictor-disagreement-aware gate

Frozen preregistration status: `w3b_design_power_qualified_inputs_incomplete_no_submit`.

Date: 2026-07-14.

Operational update, 2026-07-15: the frozen protocol below is unchanged. The separately approved target-MSA
stage completed 8/8, the post-MSA design audit and immutable execution/runtime locks pass, and the fit
approval packet is `w3b_fit_packet_ready_awaiting_explicit_approval`. No W3b candidate, predictor,
certification, held-out-test, or claim output exists. See `docs/M6D_W3B_TARGET_MSA_COMPLETION.md` and
`docs/M6D_W3B_FIT_APPROVAL.md` for the current execution boundary.

## Scientific question

Can a prospectively frozen gate that abstains when Boltz-2 and AF2-Multimer are uncertain or
disagree control worst-predictor structural-proxy false-accept risk on fresh targets, while retaining
useful coverage and improving held-out risk-coverage over a matched Boltz-pAE-only comparator?

This is a new experiment. The completed W2c and W3 records are design diagnostics only and cannot
enter W3b fit, certification, or held-out test.

## Fresh target roles

The selector consumed only target/source identities and local structural inputs. It excluded every
historical, W2b, W2c, and W3 target/source and every W2b/W2c target-sequence hash. Exactly eight
unused source-unique and target-sequence-unique representatives remained. A protocol-digest hash
assigned their target-level roles before any W3b predictor output exists.

| Role | Targets | Rows per target |
|---|---|---:|
| Fit | `1FSK_LJ`, `1FSX_BA`, `1FL7_DC` | 60 |
| Certification | `1F2U_CD`, `1FV1_BA`, `1FN3_DC` | 150 |
| Held-out test | `1FHJ_BA`, `1F3V_BA` | 120 |

The target manifest is `configs/m6d_w3b_fresh_targets.json`, with SHA-256
`0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc`. The locked scientific
protocol digest is `435eadc78fa850d4a67d6eeef463b5a805727cc46e714739d709fec7c28257cb`.

## Matched predictor contract

Each ProteinMPNN candidate is generated once and evaluated by both:

- `boltz2_complex`;
- `af2_multimer_colabfold_v1` using ColabFold 1.6.1 and `alphafold2_multimer_v3`.

The pair must have the same candidate ID, candidate-sequence hash, target-MSA hash, template-off
policy, seed `0`, and prediction-time network prohibition. Both labels use L-RMSD below 4 Angstrom
after target-chain alignment. Pairwise agreement alone is insufficient: the shared target-MSA hash must
also equal the lifecycle-derived hash frozen for that target in the W3b execution manifest. A missing
predictor output, duplicate candidate sequence, manifest-bound MSA mismatch, or any pair mismatch fails QC.

The executable assembler additionally requires one runtime receipt per target and predictor. Each receipt
binds the candidate, MSA, and raw-record files by SHA-256; records bind candidate sequence, target sequence,
target MSA, runtime identity, and model output. The Cayuga Boltz CLI exposes `--seed`; its unseeded default
is not accepted, so W3b receipts and records must both prove seed `0`. Templates and prediction-time network
must both be off. A near-total numeric copy of pAE and L-RMSD across predictors also fails closed.

These are two structural-proxy endpoints, not wet-lab truth.

The runtime itself is frozen before any W3b predictor output. Boltz is `2.2.1`, bound to a canonical
116-file installed-distribution manifest and the SHA-256/byte counts of `boltz2_conf.ckpt` and the locally
required `boltz2_aff.ckpt` cache file. Structure prediction explicitly uses model `boltz2`, seed `0`,
100 sampling steps, 3 recycles, 1 diffusion sample, `--no_kernels`, local target MSA, binder single sequence,
and no prediction-time network. AF2 reuses the W3-verified ColabFold 1.6.1 container SHA, all five
Multimer-v3 parameter hashes, seed `0`, 5 models, 20 recycles, no relaxation, no templates, and no network.
The machine lock is `configs/m6d_w3b_runtime_lock.json`; its no-submit readiness report is
`results/m6d_w3b_runtime_lock_readiness.{json,md}`. A receipt must match the lock file SHA, lock digest,
and predictor-specific canonical identity digest. A different but internally self-consistent runtime fails.

## Frozen gate

The primary gate uses only predictor-visible interface uncertainty:

```text
max_pAE = max(Boltz pAE_interaction, AF2 pAE_interaction)
pAE_gap = abs(Boltz pAE_interaction - AF2 pAE_interaction)
accept iff max_pAE <= tau_max_pAE and pAE_gap <= tau_pAE_gap
```

The comparator accepts when `Boltz pAE_interaction <= tau_boltz`. Threshold candidates are the
sorted unique fit values. Both rules must accept at least 90 fit rows, at least 15 from every fit
target, and have empirical false-accept risk at most 0.08 against each predictor endpoint. The
deterministic tie order maximizes coverage and target breadth, then minimizes worst-predictor risk
and threshold values. All thresholds freeze before certification.

## Exact certification

Certification requires at least 100 accepted rows on a target. For each of the three certification
targets, Boltz and AF2 false-accept risks are certified separately with one-sided exact
Clopper-Pearson bounds at `alpha=0.2`. Panel delta `0.05` is Bonferroni-corrected over all
`3 targets x 2 predictors`, giving per-endpoint delta `0.008333333333333333`. Failed targets remain
in the denominator, and at least two of three targets must pass both endpoints.

At 100 accepts, at most 10 false accepts can certify. Under design risk 0.08, conditional
certification power is `0.824333`, above the frozen 0.8 floor.

## Held-out test

Held-out test cannot create, alter, or rescue a certificate. The primary gate must:

- accept at least 48 rows on each test target;
- activate the disagreement abstention channel on each target;
- have worst-predictor empirical risk no worse than the comparator on each target;
- retain at least 70% of comparator coverage when pooled;
- improve pooled worst-predictor empirical risk by at least 0.05.

The terminal outcomes distinguish `not certified`, `certified but test not supported`, and
`certified and test supported`. Only the last permits the bounded W3b viability statement.

## Compute and approval boundary

The maximum design is 870 candidate sequences and 1,740 matched predictor evaluations, with a
24 H100 GPU-hour ceiling. Fit failure stops before certification; certification failure stops before
held-out test; adaptive top-up is forbidden.

The existing shared `hpc/predict_boltz_complex.py` and its Slurm wrapper remain hash-bound historical
inputs to consumed W2b/W2c approval packets and are not W3b execution authority. Dedicated W3b producer,
runtime-observation, Boltz, AF2, converter, guarded-submit, and append-only journal paths are now implemented
and hash-bound by `m6d_w3b_fit_packet`. They pass every explicit runtime-lock parameter, including Boltz
seed `0`, and reject duplicate candidate sequences. Six H100 fit jobs receive four-hour hard limits and
`--no-requeue`, so fit cannot allocate more than the protocol-wide 24 H100 GPU-hour ceiling. Historical
approval snapshots were not rewritten.

At preregistration, target-MSA readiness was 0/8 and the MSA-only packet authorized nothing. That historical
packet was later consumed exactly once: all eight jobs completed, strict replay passed, and the
target-MSA-derived execution lock was materialized. Those later operational facts do not modify this frozen
scientific protocol. The downstream fit producer contract and current no-submit approval packet are in
`docs/M6D_W3B_FIT_APPROVAL.md`; fit compute still requires its separate exact approval and cannot authorize
certification, held-out test, adaptive top-up, or claims.

## Reproducibility

- protocol: `configs/m6d_w3b_disagreement_gate_protocol.json`;
- target selector: `bio_sfm_designer.experiments.m6d_w3b_target_selector`;
- design/power auditor: `bio_sfm_designer.experiments.m6d_w3b_disagreement_design_gate`;
- lifecycle-derived execution manifest/input lock:
  `bio_sfm_designer.experiments.m6d_w3b_execution_lock`;
- provenance-bound matched-record assembler:
  `bio_sfm_designer.experiments.m6d_w3b_matched_records`;
- exact dual-predictor runtime lock:
  `bio_sfm_designer.experiments.m6d_w3b_runtime_lock`;
- W3b-only producer, runtime-observation, and fit-packet contracts:
  `bio_sfm_designer.experiments.m6d_w3b_producer_contract`,
  `bio_sfm_designer.experiments.m6d_w3b_runtime_observation`, and
  `bio_sfm_designer.experiments.m6d_w3b_fit_packet`;
- append-only fit scheduler journal:
  `bio_sfm_designer.experiments.m6d_w3b_fit_submit_journal`;
- frozen evaluator: `bio_sfm_designer.experiments.m6d_w3b_disagreement_gate`;
- focused tests: `tests/test_m6d_w3b_target_selector.py` and
  `tests/test_m6d_w3b_disagreement_gate.py`; execution-lock tests are in
  `tests/test_m6d_w3b_execution_lock.py`, and assembler tests are in
  `tests/test_m6d_w3b_matched_records.py`. Producer/fit-packet tests are in
  `tests/test_m6d_w3b_producer_contract.py`, `tests/test_m6d_w3b_runtime_observation.py`,
  `tests/test_m6d_w3b_fit_packet.py`, and `tests/test_m6d_w3b_fit_submit_journal.py`.

The current no-submit execution-lock readiness report is
`results/m6d_w3b_execution_lock_readiness.{json,md}`. It is audit-clean but cannot materialize the
execution manifest until the separately approved target-MSA lifecycle reaches strict 8/8 completion.
The assembler contract is `results/m6d_w3b_matched_record_contract.{json,md}`. It is audit-clean but
correctly reports `assembly_ready=false` until that execution manifest and input lock exist.
The dedicated fit packet report is `results/m6d_w3b_fit_packet_readiness.{json,md}`. It currently reports
`fit_packet_ready=false` solely because the same execution lock is absent; it records no approval and has
no authority to submit work.

After a separately approved predictor stage completes, create each target/predictor receipt from the
captured runtime identity, then assemble the stage and run the frozen evaluator:

```bash
python -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --receipt-predictor boltz2_complex --receipt-target <target-id> \
  --runtime-lock configs/m6d_w3b_runtime_lock.json \
  --runtime-identity <captured-boltz-runtime-identity.json>
python -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --receipt-predictor af2_multimer_colabfold_v1 --receipt-target <target-id> \
  --runtime-lock configs/m6d_w3b_runtime_lock.json \
  --runtime-identity <captured-af2-runtime-identity.json>
python -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --stage fit --out-records results/m6d_w3b_fit_matched_records.jsonl \
  --out-report results/m6d_w3b_fit_matched_record_assembly.json
python -m bio_sfm_designer.experiments.m6d_w3b_disagreement_gate \
  --records results/m6d_w3b_fit_matched_records.jsonl \
  --out results/m6d_w3b_fit_gate_report.json
```

These are post-run CPU replay commands, not submission authority. Certification or held-out-test replay
must use its own separately approved stage and cannot bypass the frozen stop rules.

The previous `m6d_w2_w3_decision_protocol` remains a historical artifact for the pre-AF2 fork; it
must not override this current W3b boundary.

## Claim boundary

Even a successful W3b result supports only bounded matched-predictor structural-proxy gate viability
under these targets and runtimes. It cannot establish wet-lab binder success, a universal complex
gate, population-level predictor robustness, or W2c rescue.
