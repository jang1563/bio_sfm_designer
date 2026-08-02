# M6d W3d Native Representation-by-Predictor Diagnostic

Status: `w3d_native_representation_predictor_protocol_locked_no_submit`.

Date locked: 2026-08-02.

## Purpose

W3c-B2 is terminal. Boltz recovered only 2/8 native complexes, which makes the frozen dual-predictor
6/8 pass impossible, while every AF2 job failed before inference on a container-relative input path.
That result is sufficient to close W3c-B2, but it cannot distinguish among:

1. failure caused by the evolutionary-input or complex representation;
2. predictor-specific failure under the same information content;
3. a predictor-by-representation interaction; or
4. general native-recovery difficulty across the tested scope.

W3d is a distinct successor experiment designed to localize that bottleneck before any generated
candidate, trust threshold, or DBTL action is considered.

## Honest Design Boundary

The W3d question was formulated after the W3c-B2 Boltz outcomes were known. W3d is therefore a
**retrospective-baseline/prospective-completion** factorial, not a fully prospective four-cell study.

The control against post-hoc selection is explicit:

- all eight W3c targets are retained in frozen order;
- all eight existing Boltz outcomes are retained, including six failures;
- the completed cell cannot be rerun or selectively replaced;
- the remaining 24 cells and all decision rules are locked before their outcomes;
- no target dropping, threshold tuning, retry, or adaptive top-up is allowed.

## Frozen 2 x 2 Factorial

Every target appears once in each representation-by-predictor cell.

| Evolutionary-information representation | Boltz 2.2.1 | AF2-Multimer v3 |
|---|---:|---:|
| `target_msa_binder_query` | 8 immutable W3c-B2 baseline outcomes | 8 prospective outcomes |
| `query_only_both_chains` | 8 prospective outcomes | 8 prospective outcomes |

Total factorial cells: 32. Completed immutable baseline cells: 8. Prospective cells: 24.

The representation factor is defined by evolutionary information, not byte-identical file format,
because each predictor has a native input grammar:

- `target_msa_binder_query`: the target receives the frozen W3c-B1 homolog MSA, the binder receives no
  homolog MSA, and no non-query paired row is asserted. Boltz encodes this as target A3M plus
  `msa: empty` for the binder. AF2 encodes the same information content as an annotated multimer A3M
  with the paired native query, unpaired target rows, and one unpaired binder query row.
- `query_only_both_chains`: neither chain receives homolog rows. Boltz uses `msa: empty` for both chains;
  AF2 receives an annotated paired native query with no homolog rows.

Predictor chain A is always the target and chain B is always the native binder. Seed 0, templates off,
prediction-time network off, model identity, sampling settings, and endpoint code are held constant.

## Primary Endpoint

A target succeeds in one cell only when:

```text
strict_qc_passed
and interface_pae is finite
and ligand_rmsd_angstrom is finite
and ligand_rmsd_angstrom < 4.0
```

Interface pAE is retained as a continuous QC/diagnostic value. It is not a selection threshold in W3d.
A cell qualifies at 6/8 successful targets.

## Frozen Localization Rules

Each directional comparison is target-paired. A strong directional contrast requires all four:

- favored cell succeeds on at least 6/8 targets;
- unfavored cell succeeds on at most 2/8 targets;
- at least four targets pass only in the favored cell;
- at most one target passes only in the unfavored cell.

The final localization is deterministic:

- `representation_specific_native_recovery_failure`: the same representation strongly dominates within
  both predictors;
- `predictor_specific_native_recovery_failure`: the same predictor strongly dominates within both
  representations;
- `predictor_by_representation_interaction`: strong directional winners reverse across matched
  comparisons;
- `partial_localization_not_replicated_across_orthogonal_factor`: at least one strong contrast exists,
  but it is not repeated across the other factor;
- `mixed_or_unresolved`: no frozen localization rule is met.

These labels are descriptive localization rules for eight targets, not population-level causal estimates.

## Downstream Stop Rule

Candidate generation becomes scientifically reachable only if both predictors qualify at 6/8 or better
under the **same** representation. A one-predictor pass does not unlock generation. Even a successful W3d
native-validity result authorizes no ProteinMPNN or predictor compute; it would require a separate
generator protocol and explicit approval.

## Baseline Replay

The immutable `target_msa_binder_query` Boltz cell contains two successes:

| Target | interface pAE | L-RMSD (A) | Success |
|---|---:|---:|:---:|
| `1TE1_BA` | 11.4271 | 30.981252 | false |
| `3QB4_AB` | 18.0891 | 58.449146 | false |
| `5E5M_AB` | 4.4283 | 2.426855 | true |
| `5JSB_AB` | 3.2575 | 0.644485 | true |
| `6KBR_AC` | 9.2236 | 17.343068 | false |
| `6KMQ_AB` | 4.1455 | 7.910633 | false |
| `6SGE_AB` | 11.0180 | 7.319867 | false |
| `7B5G_AB` | 8.4088 | 39.582202 | false |

The protocol binds the W3c-B2 manifest, runtime lock, terminal report, baseline JSONL, AF2 failure
evidence, both historical wrappers, and producer by exact SHA-256. The CPU replay does not require the
original ignored HPC model-output files.

## Runtime Correction Boundary

The failed W3c-B2 AF2 jobs are not recoverable under W3d. A new AF2 wrapper must:

- use absolute container-visible input and output paths;
- set an explicit container working directory;
- preserve ColabFold 1.6.1, AF2-Multimer v3, all five weight hashes, seed 0, 20 recycles, no templates,
  no relaxation, and no prediction-time network;
- pass a new no-prediction runtime and input-resolution validation before an approval packet exists.

Boltz must retain the exact 2.2.1 runtime identity and the same model/sampling settings. Both predictors
require new wrapper/input validation because W3d adds the query-only representation.

## Authority and Budget

Current authority is exactly zero:

- predictor evaluations authorized: 0;
- H100 GPU-hours authorized: 0;
- target-MSA queries authorized: 0;
- ProteinMPNN designs authorized: 0;
- API calls authorized: 0;
- retries and adaptive top-ups authorized: 0.

If separately validated and approved later, the frozen proposal contains 24 new one-hour H100 evaluation
slots: eight Boltz and sixteen AF2, with a maximum 24 H100 GPU-hour allocation. This is a proposed ceiling,
not current authority.

## Reproduce the No-Submit Lock

```sh
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_native_diagnostic

PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m pytest -q \
  tests/test_m6d_w3d_native_diagnostic.py
```

Authoritative artifacts:

- `configs/m6d_w3d_native_diagnostic_protocol.json`
- `configs/m6d_w3d_native_diagnostic_manifest.json`
- `results/m6d_w3d_native_diagnostic_readiness.{json,md}`
- `src/bio_sfm_designer/experiments/m6d_w3d_native_diagnostic.py`

Next action: implement and validate the CPU-only input producer and corrected no-prediction runtime
wrappers for all 24 prospective cells, then stop before any compute approval packet.
