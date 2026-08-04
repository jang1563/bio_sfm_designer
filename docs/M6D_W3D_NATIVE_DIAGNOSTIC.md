# M6d W3d Native Representation-by-Predictor Diagnostic

Terminal status: `w3d_terminal_partial_result_native_validity_impossibility_stop`.

Historical protocol status: `w3d_native_representation_predictor_protocol_locked_no_submit`.

Date locked: 2026-08-02.

Operational preparation status (2026-08-03):
`w3d_input_and_runtime_validation_complete_no_submit`.

Approval-packet status (2026-08-03):
`w3d_prediction_approval_packet_ready_no_submit`.

Terminal adjudication date: 2026-08-04.

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
  the intended AF2 representation contains the paired native query plus only the runtime-required unpaired
  native query rows, with no homolog rows. The packet-bound producer omitted those unpaired rows; that
  implementation defect is part of the terminal result below.

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
- pass a new no-prediction runtime and input-resolution validation before inclusion in any approval packet.

Boltz must retain the exact 2.2.1 runtime identity and the same model/sampling settings. Both predictors
require new wrapper/input validation because W3d adds the query-only representation.

## CPU Input and Wrapper Completion

The deterministic producer in `m6d_w3d_input_runtime.py` now materializes all and only the 24 prospective
cells under the ignored `hpc_outputs/m6d_w3d_native_diagnostic/` tree:

| Predictor-native input | Representation | Files |
|---|---|---:|
| Boltz YAML | query-only both chains | 8 |
| AF2 annotated multimer A3M | target MSA + binder query | 8 |
| AF2 annotated multimer A3M | query-only both chains | 8 |

Pre-execution validation passed for 24/24 file hashes and its then-declared representation semantics. In
particular:

- every query-only AF2 file contains exactly one paired native query and no homolog row, but the validator
  failed to require ColabFold's unpaired monomer query rows; all eight such files later failed during
  feature generation;
- every target-MSA AF2 file round-trips the exact frozen target A3M hash, has no non-query paired row,
  and adds only the unpaired native binder query;
- every prospective Boltz YAML uses `msa: empty` for both chains and `templates: []`;
- every cell retains its frozen sequence hashes, seed, model settings, output path, record path, and
  runtime-identity digest;
- the producer cannot rebuild the eight retrospective Boltz baseline cells.

The tracked `configs/m6d_w3d_prospective_input_manifest.json` contains portable relative paths and hashes,
not local absolute paths. The raw 11.2 MB input bundle remains ignored. A public clone can replay the
tracked manifest, wrapper hashes, and tests; full file-semantic revalidation requires materializing the
hash-locked inputs from the local W3c source cache.

Three execution-incapable validation wrappers are now present:

- `hpc/validate_w3d_boltz_runtime_no_prediction.sh`;
- `hpc/validate_w3d_af2_runtime_no_prediction.sh`;
- `hpc/validate_w3d_runtime_no_prediction.sh`.

They contain no predictor invocation, accelerator exposure, scheduler command, or download path. The AF2
probe resolves all 16 input/output pairs to absolute project-bound paths inside the container, binds the
same absolute project root, sets `--pwd` to that root, and disables container networking. The Boltz probe
does the corresponding host-path checks for eight cells. Both reobserve the exact locked runtime identity.

Static validation and exact execution of these no-prediction probes on Cayuga are complete. Both locked
runtime identities match, 8/8 Boltz host paths and 16/16 AF2 container paths pass, and all 16 AF2 probes
confirm the explicit container working directory. The redacted receipt contains no Cayuga path and records
zero prediction, GPU, scheduler, or network-fetch execution. Runtime validation itself granted no compute
authority. The immutable packet still records its creation-time `approval_recorded=false` state, while the
later one-shot approval and scheduler submission are recorded separately in the append-only receipt and
the integrated goal state.

## Hash-Bound Approval Packet

The no-submit packet now binds the complete prospective execution surface:

- 24 prospective cells: 8 Boltz query-only and 16 AF2 cells;
- exactly 24 scheduler jobs, each `h100:1` for at most one hour, under one separately recorded approval;
- a total ceiling of 24 H100 GPU-hours;
- all protocol, factorial, input, runtime, producer, converter, journal, wrapper, and submit-bridge hashes;
- 53 paths that must all be absent before first submission;
- seed 0, templates off, prediction-time network off, zero target-MSA queries, and zero ProteinMPNN designs;
- zero retries, adaptive top-ups, target dropping, partial-panel adjudication, or predecessor reruns.

The guarded wrappers revalidate the packet, cell input, runtime observation, and output absence before
prediction. The append-only scheduler journal rejects duplicate or out-of-scope cells and can summarize
only the exact 8-Boltz plus 16-AF2 set. The local submit dry run enumerates all 24 cells and creates zero
scheduler jobs. Packet digest:
`6a2cde2d90fc054298bef33e7ccf0c6c984a939de0f9cd1a5a543c44a855c36a`.

Packet preparation was not execution approval. After the exact approval was recorded on 2026-08-03, the
guarded bridge consumed it once and submitted jobs `3171691`-`3171714`: 8 Boltz and 16 AF2 cells, with
24/24 unique packet cells and scheduler IDs. The receipt records zero retries and zero adaptive top-ups.
Submission is execution provenance, not scientific evidence; no prospective outcome is claimable until
all terminal records are reconciled and the frozen complete-case adjudicator runs.

## Terminal Execution and Bounded Result

All receipt-bound jobs are terminal. Exact Slurm replay gives:

| Outcome class | Jobs | Scientific interpretation |
|---|---:|---|
| completed with replayed strict-QC record | 16 | observed predictor outcomes |
| failed query-only AF2 before model inference | 8 | input-encoding defect, not scientific negatives |
| unresolved | 0 | none |

The eight failures are jobs `3171693`, `3171696`, `3171699`, `3171702`, `3171705`, `3171708`,
`3171711`, and `3171714`. ColabFold reached feature generation and rejected MSA 0 because the packet-bound
query-only A3M had one paired query but zero unpaired monomer query rows. No recycle, model inference,
ranking, PDB, confidence, or strict-QC record was produced for those cells. The packet-bound producer and
approved inputs remain immutable; a corrected encoding is successor work, not a W3d retry.

Available frozen cell counts are:

| Representation | Boltz 2.2.1 | AF2-Multimer v3 |
|---|---:|---:|
| `target_msa_binder_query` | 2/8 success | 2/8 success |
| `query_only_both_chains` | 1/8 success | unavailable, 0/8 observed |

The missing cell prevents complete-case `2 x 2` localization. No representation-specific,
predictor-specific, or interaction label is assigned. It also prevents a complete native-recoverability
estimate. This incompleteness does not leave the frozen downstream decision open: target-MSA has both
predictors fully observed at 2/8, and query-only has Boltz fully observed at 1/8. Thus neither
representation can have both predictors reach 6/8, even if every missing query-only AF2 outcome were a
success. The maximum possible number of recovered representations is zero.

W3d therefore closes at `w3d_terminal_partial_result_native_validity_impossibility_stop` with
`stage_pass=false`. Candidate generation is scientifically unreachable. There is no retry, replacement,
adaptive top-up, target drop, ProteinMPNN, generator, or gate authority.

## Authority and Budget

The approved envelope was fully consumed by the 24 receipt-bound submissions. Current *additional*
authority is exactly zero:

- additional predictor evaluations authorized: 0;
- additional H100 GPU-hours authorized: 0;
- target-MSA queries authorized: 0;
- ProteinMPNN designs authorized: 0;
- API calls authorized: 0;
- retries and adaptive top-ups authorized: 0.

The consumed envelope contained 24 one-hour H100 evaluation slots: eight Boltz and sixteen AF2, with a
maximum 24 H100 GPU-hour allocation. Terminal accounting records 6,206 one-H100 GPU-seconds
(`1.723889` hours). Failed cells may not be replaced or topped up.

## Reproduce the No-Submit Lock

```sh
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_native_diagnostic

PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m pytest -q \
  tests/test_m6d_w3d_native_diagnostic.py \
  tests/test_m6d_w3d_input_runtime.py

# Requires the local hash-locked W3c source cache; performs CPU input work only.
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_input_runtime prepare

# Rebuild and verify the no-submit packet; neither command submits work.
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_approval prepare
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_approval verify

BIO_SFM_SUBMIT_DRY_RUN=1 bash hpc/m6d_w3d_submit_with_receipt.sh

# Requires the exact synced packet-bound outputs and logs; performs CPU replay only.
PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m \
  bio_sfm_designer.experiments.m6d_w3d_terminal_stop

PYTHONPATH=src:../bio-sfm-trust-core/src python3 -m pytest -q \
  tests/test_m6d_w3d_terminal_stop.py
```

Authoritative artifacts:

- `configs/m6d_w3d_native_diagnostic_protocol.json`
- `configs/m6d_w3d_native_diagnostic_manifest.json`
- `configs/m6d_w3d_prospective_input_manifest.json`
- `results/m6d_w3d_native_diagnostic_readiness.{json,md}`
- `results/m6d_w3d_input_runtime_readiness.{json,md}`
- `results/m6d_w3d_runtime_validation_receipt.json`
- `results/m6d_w3d_prediction_packet_readiness.{json,md}`
- `results/m6d_w3d_prediction_approval_packet.json`
- `results/m6d_w3d_submit_receipt.jsonl`
- `results/m6d_w3d_submit_receipt_summary.json`
- `results/m6d_w3d_sacct.tsv`
- `results/m6d_w3d_h100_node_snapshot.txt`
- `results/m6d_w3d_terminal_accounting.{json,md}`
- `results/m6d_w3d_available_records.jsonl`
- `results/m6d_w3d_query_only_af2_failure_evidence.jsonl`
- `results/m6d_w3d_terminal_stop.{json,md}`
- `src/bio_sfm_designer/experiments/m6d_w3d_native_diagnostic.py`
- `src/bio_sfm_designer/experiments/m6d_w3d_input_runtime.py`
- `src/bio_sfm_designer/experiments/m6d_w3d_approval.py`
- `src/bio_sfm_designer/experiments/m6d_w3d_execution.py`
- `src/bio_sfm_designer/experiments/m6d_w3d_submit_journal.py`
- `src/bio_sfm_designer/experiments/m6d_w3d_terminal_stop.py`
- `hpc/run_predict_boltz_w3d_native.sbatch`
- `hpc/run_predict_af2_w3d_native.sbatch`
- `hpc/m6d_w3d_submit_with_receipt.sh`

Next action: preserve W3d as closed. If the missing localization is worth resolving, preregister a separate
successor whose query-only AF2 A3M includes runtime-required unpaired native query rows and validate that
grammar before requesting any new compute. Do not retry W3d or begin ProteinMPNN, generator, gate, or
biological-claim work.
