# M6d W3 mechanism-panel completion

Status: `w3_mechanism_panel_adjudicated_context_dependent_or_unresolved`.

Date: 2026-07-14.

## Scope

This is the terminal readout of the preregistered 58-case AF2-Multimer mechanism panel in
`configs/m6d_w3_mechanism_panel_protocol.json`. The immutable public protocol SHA-256 is
`16251403d47e7956415a4d3a748aa700997bdacfe19bb299b6befff5a1d0b1a3`; the private input-manifest
SHA-256 is `c3389487220cf1d53adb66ace486ba61f93a40a8d800fb03ade296e09d937107`.

The panel asks whether the W2c result is better explained by reproducible target/coverage
heterogeneity or by predictor/protocol label instability. It cannot certify population-level
independent-predictor robustness and cannot reopen or rescue W2c.

## Execution integrity

| Job | State | Validity | Evidence |
|---|---|---|---|
| `3084976` | cancelled at 23/58 | invalidated; never adjudicated | `single_sequence` forced ColabFold to `max_seq=1`, `max_extra_seq=1`, contrary to the locked target-MSA reuse policy |
| `3084977` | completed 58/58, exit `0:0` | valid | precomputed target MSA retained, `max_seq=508`, `max_extra_seq=2048`, `pair_mode=unpaired_paired`, network namespace `none` |

The correction changed only the faulty execution wrapper. It did not change panel membership,
sequences, hashes, labels, thresholds, or decision rules. A no-prediction feature probe on `w3m-001`
observed an AF2 input MSA shape of `512 x 193`, proving that the target MSA reached model features.

The valid job used ColabFold 1.6.1, five AlphaFold2-Multimer v3 models, one seed, at most 20
recycles, no templates, no relaxation, and one H100 on Cayuga. It completed in `01:04:39`
(`1.0775` H100 GPU-hours). The runtime image SHA-256 was
`e26689bc357e8aaf5210ed43499e565d2a440ea6efde5a8a42cbdc4f6a83e566`.

Raw-output checks passed: 58 done markers, 290 PDBs, 290 score JSON files, 58 rank-1 PDBs,
and 58 rank-1 score files. Conversion produced 58/58 records with zero failures.

## Frozen result

| Block | Frozen readout | Outcome |
|---|---|---|
| 3PC8 discordant cases | Boltz alignment `0/12`; Chai alignment `12/12` | Chai supported |
| 3PC8 controls | `6/6` successful | control requirement passed |
| W2c global agreement with Boltz | `30/40` (`0.75`) | below `32/40` support, above `24/40` instability |
| W2c target breadth | `5/8` targets at least `4/5` | below `6/8` support, above `3/8` instability |
| Joint | valid but neither joint mechanism rule passed | `context_dependent_or_unresolved` |

The adjudication audit passed with `failures=[]`. The W2c enum is
`mixed_or_contract_blocked`; because `audit_ok=true`, this instance means mixed, not contract-blocked.

## Descriptive readout

These values were computed only after frozen adjudication and do not alter its outcome.

| Target | AF2 successes | Boltz successes | Agreement | Median LRMSD | Median interface pAE |
|---|---:|---:|---:|---:|---:|
| 3PC8_AB | 18/18 | 6/18 | 6/18 | 2.2079 | 4.9055 |
| 1EZV_XY | 4/5 | 5/5 | 4/5 | 1.6543 | 6.5886 |
| 1F80_BC | 4/5 | 1/5 | 2/5 | 3.0541 | 11.0366 |
| 1F99_BA | 0/5 | 3/5 | 2/5 | 13.8117 | 10.3148 |
| 1FFG_CD | 2/5 | 3/5 | 4/5 | 4.7741 | 5.6196 |
| 1FFK_HR | 0/5 | 0/5 | 5/5 | 12.9327 | 11.3789 |
| 1FQ9_CA | 0/5 | 0/5 | 5/5 | 23.2366 | 24.7009 |
| 1FR2_BA | 3/5 | 1/5 | 3/5 | 2.3412 | 6.0034 |
| 1FYR_CD | 0/5 | 0/5 | 5/5 | 39.9820 | 11.3822 |

AF2 labeled 31/58 cases successful: 18/18 in the 3PC8 block and 13/40 in the W2c block.
The result is not one universal predictor correction. It shows strong Boltz-versus-AF2/Chai
instability on 3PC8 and target-dependent agreement or disagreement across W2c.

## Scientific interpretation

The strongest supported conclusion is that structural-design labels are conditional on target and
predictor protocol. A single refolder cannot be treated as stable ground truth across these regimes.
The external trust gate therefore needs an explicit predictor-disagreement uncertainty channel and
must be able to abstain when label stability is unsupported.

This result does not support a universal complex-design gate, population-level independent-predictor
robustness, W2c rescue, or post-hoc threshold tuning.

## CPU replay

The public sequence-free replay fixture is
`tests/fixtures/m6d_w3_mechanism_panel_af2_records.jsonl` with SHA-256
`830a31bd7ad849fb55be0aec760e40b1cd587872f11ee5dd6e4810702003bef2`.

```bash
PYTHONPATH="$PWD/src:$PWD/../bio-sfm-trust-core/src" \
  python3 -m pytest -q tests/test_m6d_w3_mechanism_panel.py
```

Local replay reproduces every label, rounded metric, and adjudication field. Unrounded LRMSD differs
across the Cayuga and local NumPy stacks by at most `1.78e-14` Angstrom, far below any decision scale.

## Next frontier

Freeze W3 as a bounded, terminal mechanism result. The next high-impact experiment should be a new,
prospectively locked predictor-disagreement-aware gate on fresh source-diverse targets with matched
target-MSA, template, seed, and label protocols across predictors. It must define fit, certification,
and held-out test roles before labels are observed. That successor is now preregistered in
`docs/M6D_W3B_DISAGREEMENT_GATE_PROTOCOL.md`; no new predictor compute is authorized.
