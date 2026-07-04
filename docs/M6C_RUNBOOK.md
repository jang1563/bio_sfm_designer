# M6c Complex/Binder Scale-Up Runbook

This is the execution anchor for moving the current barnase-barstar M6c result from a
fixture-backed certificate to a scale-ready, multi-target complex/binder trust-gate workflow.

## Goal

Produce synchronized complex records that pass QC, tighten the conformal frontier beyond the
current `alpha=0.3` certificate, and make every expensive Cayuga run reproducible from explicit
inputs:

- prepared two-chain PDB
- fixed target FASTA plus `.fasta.report.json`
- cached target `.a3m` plus `.a3m.report.json`
- ProteinMPNN complex candidates JSONL
- Boltz complex records JSONL
- posthoc QC/sweep/plan/decision/report/status bundle

## One Target

Run these from the repo root on the machine where the relevant paths exist.
If the target manifest includes `rcsb_id` and source/prepared paths, the same
fetch -> prep -> FASTA -> target-MSA sequence can also be rendered as one selected-target plan:

```sh
python -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest configs/my_complex_targets.json \
  --target-id 1BRS_AD \
  --emit-msa-plan results/m6c_target_msa_1BRS_AD.sh
```

That plan downloads the RCSB source PDB when `source_pdb` is missing, runs
`hpc/prep_hetdimer.py`, writes the target FASTA/report, and submits the one-time
target `.a3m` job with a matching report. The manual form below is the same sequence spelled out.
For `1BRS_AD`, the template manifest marks the known RCSB chain-D residue-numbering
gap (D64-D65) with `allow_numbering_gaps: true`; do not use that exception for new
targets without manual review.

```sh
# 1) Fetch the source PDB if it is not already present.
mkdir -p hpc_outputs/targets
curl -fsSL https://files.rcsb.org/download/1BRS.pdb \
  -o hpc_outputs/targets/source_1BRS.pdb

# 2) Prepare a clean two-chain target+binder reference.
python hpc/prep_hetdimer.py \
  --pdb hpc_outputs/targets/source_1BRS.pdb \
  --target-chain A --binder-chain D \
  --out hpc_outputs/targets/prepared_1BRS_AD.pdb \
  --report hpc_outputs/targets/prepared_1BRS_AD.report.json \
  --allow-numbering-gaps

# 3) Extract the fixed target sequence that the target MSA must match.
python hpc/extract_chain_fasta.py \
  --pdb hpc_outputs/targets/prepared_1BRS_AD.pdb \
  --chain A --id 1BRS_A \
  --out hpc_outputs/targets/1BRS_A.fasta \
  --report hpc_outputs/targets/1BRS_A.fasta.report.json

# 4) Generate hpc_outputs/targets/1BRS_A.a3m plus report once; reuse it for every designed binder.
FASTA=hpc_outputs/targets/1BRS_A.fasta OUT=hpc_outputs/targets/1BRS_A.a3m \
REPORT=hpc_outputs/targets/1BRS_A.a3m.report.json \
  sbatch hpc/run_precompute_boltz_target_msa.sbatch
#    precompute_boltz_target_msa.py and predict_boltz_complex.py both check that this
#    MSA query matches hpc_outputs/targets/1BRS_A.fasta before inference.

# 5) Generate redesigned binders against the fixed target chain.
PDB=hpc_outputs/targets/prepared_1BRS_AD.pdb \
TARGET_CHAIN=A DESIGN_CHAIN=D NUM_SEQ=260 TEMP=0.3 \
COMPLEX_ID=1BRS_AD \
OUT=hpc_outputs/m6c_targets/1BRS_AD/candidates_proteinmpnn_complex.jsonl \
  sbatch hpc/run_generate_proteinmpnn_complex.sbatch

# 6) Refold candidates as complexes with cached target MSA + binder single-seq.
CANDIDATES=hpc_outputs/m6c_targets/1BRS_AD/candidates_proteinmpnn_complex.jsonl \
BACKBONE=hpc_outputs/targets/prepared_1BRS_AD.pdb \
TARGET_CHAIN=A BINDER_CHAIN=D \
COMPLEX_ID=1BRS_AD \
TARGET_MSA=hpc_outputs/targets/1BRS_A.a3m \
OUT=hpc_outputs/m6c_targets/1BRS_AD/records_boltz_complex.jsonl \
  sbatch hpc/run_predict_boltz_complex.sbatch
```

After syncing the records back locally:

```sh
python -m bio_sfm_designer.experiments.complex_posthoc_bundle \
  --records tests/fixtures/barstar_interface_records.jsonl \
            hpc_outputs/m6c_targets/1BRS_AD/records_boltz_complex.jsonl \
  --alphas 0.3,0.2,0.1 \
  --require-complex-target-id \
  --require-provenance \
  --require-chain-ids \
  --out-dir results/m6c_posthoc
```

If the alpha decision is `continue_scale`, inspect
`results/m6c_posthoc/complex_alpha_decision.json`. Its `next_batch` block rounds the
additional-record estimate into practical ProteinMPNN `NUM_SEQ` settings. The fixture-backed
default for `alpha=0.2` estimates about +260 records; preserving the current three-temperature
distribution rounds that to `NUM_SEQ=100` per temperature, 300 candidates total.

To turn that decision into Cayuga commands without temp-output collisions:

```sh
python -m bio_sfm_designer.experiments.complex_next_batch_plan \
  --manifest configs/my_complex_targets.json \
  --decision results/m6c_posthoc/complex_alpha_decision.json \
  --target-id 1BRS_AD \
  --require-files \
  --previous-records tests/fixtures/barstar_interface_records.jsonl \
  --posthoc-out-dir results/m6c_posthoc_next \
  --out results/m6c_next_batch_1BRS_AD.json \
  --emit-plan results/m6c_next_batch_1BRS_AD.sh
```

The emitted shell plan writes temp-specific candidate/record files such as
`candidates_proteinmpnn_complex_t030.jsonl` and `records_boltz_complex_t030.jsonl`, captures
ProteinMPNN job ids with `sbatch --parsable`, submits matching Boltz jobs with
`--dependency=afterok:<generate-job>`, and passes manifest `SEED`, `OBJECTIVE`, and `COMPLEX_ID` into
the generate stage so candidate ids/metadata keep the target namespace. With `--require-files`, command emission first runs the
selected target through manifest/file/MSA/report preflight; a mismatched target `.a3m` or stale
target-MSA report blocks the plan. The emitted shell plan also replays that selected-target
preflight before any `sbatch`, so stale files are caught if the plan is executed later.
By default, the planner also refuses scale commands if `complex_alpha_decision.json` was not produced
with passing strict QC (`--require-complex-target-id --require-provenance --require-chain-ids`). Use `--no-strict-qc`
only for legacy debugging, not for real scale claims.

After the dependent Boltz jobs finish and the record JSONLs are synced back to the same paths named in
`results/m6c_next_batch_1BRS_AD.json`, run the completion check before posthoc:

```sh
python -m bio_sfm_designer.experiments.complex_scale_completion \
  --plan results/m6c_next_batch_1BRS_AD.json \
  --out results/m6c_scale_completion_1BRS_AD.json \
  --emit-plan results/m6c_scale_completion_1BRS_AD.sh
```

This catches missing, empty, malformed, or target-mismatched JSONL outputs before the expensive analysis
bundle. Use `--new-records-only` when validating just the newly synced Cayuga outputs against a saved
scale plan; the emitted shell plan preserves that flag, `--no-check-target-ids` when used, and the output
path so the completion check is replayable. If it reports `ready_for_posthoc`, run the emitted posthoc
command from the completion report/plan.

To run a single pre-submission readiness audit across the scale plan, target manifest, optional
second-predictor contract, and later W4 batch artifacts:

```sh
python -m bio_sfm_designer.experiments.complex_readiness \
  --decision results/m6c_posthoc/complex_alpha_decision.json \
  --target-manifest configs/my_complex_targets.json \
  --input-prep-completion results/m6c_input_prep_completion.json \
  --scale-target-id 1BRS_AD \
  --previous-records tests/fixtures/barstar_interface_records.jsonl \
  --require-files \
  --out results/m6c_readiness.json \
  --emit-plan results/m6c_readiness.sh \
  --emit-scale-plan results/m6c_next_batch_1BRS_AD.json
```

Use the emitted readiness shell plan as the review artifact before `sbatch`. Planned downstream
`target_fasta_report` and `target_msa_report` paths are checked when declared in the manifest; when
omitted, the validator requires the defaults `<target_fasta>.report.json` and
`<target_msa>.report.json`. The FASTA report must carry `pdb`, `pdb_sha256`, `chain`, `out`,
`out_sha256`, integer `length`, and `sequence` matching the current prepared PDB/FASTA. The MSA report
must carry `ok=true`, `fasta`, `out`, integer `sequence_length`, `fasta_sha256`, and `out_sha256`
matching the current manifest FASTA/MSA. A copied or later-mutated FASTA/MSA without its matching report
stays in `waiting_on_input_prep` until the input-prep artifact pair is complete.
Planned downstream `records` paths in a target manifest are treated as outputs, not required inputs; use
`complex_target_manifest.py --require-records` only when validating already-synced outputs.
When an input-prep completion report exists, pass `--input-prep-completion` so readiness and its embedded
roadmap status preserve `pending_artifacts`, `blocked_targets`, and the manifest rerun command.
The JSON readiness report also includes `ordered_steps`, and `--emit-scale-plan` writes the saved
next-batch JSON to pass later to `complex_scale_completion.py --plan`. If scale submission is not ready,
it writes an `ok=false`, `action=unavailable` sentinel at that path instead of leaving a stale runnable
plan behind; `complex_scale_completion.py` blocks on the sentinel. Together, these make the intended
sequence explicit:
fetch source PDBs when `rcsb_id` is present, prepare heterodimers, extract target FASTAs, precompute
target MSAs when needed, submit scale or panel jobs, run posthoc/status refresh after records are synced
and `complex_scale_completion.py` passes, then run second-predictor checks only when those independent
records exist. When the second-predictor contract is ready, readiness orders the cross-predictor report
command before the project-status refresh. For W4, add synced `--batch-candidates`,
`--batch-records`, optional `--batch-verdicts`, and `--batch-target`; readiness runs strict complex
batch preflight and emits the `run_batch_round.py --strict-complex-records` command only when candidate,
prediction, verdict, and candidate-record `complex_target_id` agreement passes.
If those batch or prevalidation JSONLs are missing or empty, `run_batch_round.py` still writes
`preflight.json` with `pending_artifacts` before stopping. Add
`--emit-sync-back-plan results/m6c_w4_sync_back.sh` to turn those blockers into explicit `rsync -avP`
pulls from `CAYUGA_BIO_SFM_ROOT` plus a rerun of the same W4 batch command.
When routing W4 through readiness first, pass `--batch-sync-back-plan results/m6c_w4_sync_back.sh`
so the readiness JSON/shell plan preserves that path and prints `bash <script>` in the blocked-check section.
When refreshing project status, pass the same path as `--batch-sync-back-plan` so the top-level roadmap
JSON/text and post-sync replay command retain the W4 sync/rerun pointer.
For W3, pass `--predictor-sync-back-plan results/m6c_second_predictor_sync_back.sh` when the
second-predictor contract is blocked on missing secondary records so the same roadmap artifacts retain
that sync/rerun pointer. The generated W3 and W4 direct sync scripts validate their own
`<script>.manifest.json` sidecars before rsync, require each pulled JSONL to be non-empty afterward,
and avoid regenerating their own running script during direct replay, so workstream-level replay also
fails closed on stale pending-path manifests or empty pulls.
Add `--emit-pending-external-paths results/m6c_project_pending_external_paths.txt` to write the combined
W1/W2 input-prep, W3 second-predictor, and W4 batch artifact checklist.
The status JSON preserves that checklist as `pending_external_summary`, grouped by workstream, category,
target, artifact, and field, and `pending_external_followups` maps the same pre-remote checklist to
W1-W4 repair actions before the remote-check report exists.
Add `--emit-external-remote-check-plan results/m6c_project_remote_check.sh` to write a lightweight
`ssh test -s` preflight for that checklist before artifact rsync, so missing/unfinished Cayuga jobs are
distinguished from local sync problems. The script writes `results/m6c_project_remote_check.json` with
per-path present/missing status plus missing-by-workstream/category/target metadata, and status JSON
exposes that report path in `generated_scripts`.
When the target-MSA precompute receipt path is known, the same remote-check bridge first attempts to rsync
`results/m6c_project_target_msa_precompute_receipt.jsonl` back from Cayuga and records the outcome as
`target_msa_precompute_receipt_sync` in the remote-check report, including the synced local receipt SHA-256
and byte size when the pull succeeds. The remote-check bridge verifies the pending external path-list
fingerprint before that receipt sync, so stale generated scripts fail before touching local receipt state.
Pass `--external-remote-check-report results/m6c_project_remote_check.json` on status refresh; only a
fresh `ok=true` report for the current pending-path SHA advances `recommended_next_script` from the
remote check to the external sync-back bridge, and only when its `path_manifest` provenance matches the
current pending-path manifest, its status/counters/per-path records prove every current path is present, and
any required target-MSA precompute receipt is satisfied. A fresh all-present
report without target-MSA receipt-sync evidence is treated as `target_msa_receipt_sync_missing`; rerun the
remote-check bridge before any target-MSA re-submit. If the report shows that receipt sync was requested but
did not produce a synced local receipt, status is `target_msa_receipt_sync_failed`; inspect or repair the
Cayuga receipt, then rerun the remote-check bridge. A `synced=true` receipt report without SHA-256 and byte
size is also treated as stale repair-required evidence. External sync scripts also pin the satisfied local
target-MSA receipt SHA from status generation and recheck it before any rsync. When a target-MSA
precompute plan is emitted and W1/W2 target MSAs are still pending, status routes that deduplicated submit
plan before the remote check; same target ids are de-duplicated only when FASTA/MSA/report material matches,
and conflicting duplicate target ids fail closed as a local plan conflict. Without that pending target-MSA submit step, a fresh missing report keeps the
next action on the remote check and adds fresh-report-derived `remote_missing_followups` so each missing
remote artifact points back to the relevant readiness/workstream repair action.
The precompute plan writes `results/m6c_project_target_msa_precompute_receipt.jsonl`; after that JSONL
records exactly one accepted row per planned target as `submitted` or `validated_existing`, has no
unexpected target rows, has a non-empty, whitespace-free `sbatch --parsable` job id for each `submitted` row, and has FASTA/MSA/report paths plus manifest path/hash/workstream provenance matching the
current raw manifests, status treats
the precompute step as `satisfied` and advances the next bridge to remote-check instead of risking
duplicate submits. If the receipt was written only on Cayuga, run the remote-check bridge; it will try to
pull the receipt before checking the pending external artifacts.
If a non-empty local receipt is incomplete or invalid, status blocks blind resubmission and the generated
target-MSA bridge exits before truncating it. Inspect or archive that receipt first; set
`TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1` only after confirming recorded jobs will not be duplicated.
The generated target-MSA precompute bridge checks each raw manifest hash and `sbatch` before initializing
that receipt, so stale rendered commands or a mistaken local run fail before clobbering resume evidence. It
also exits before recording a `submitted` receipt row if `sbatch --parsable` returns an empty,
whitespace-only, or whitespace-containing job id. Before exiting, each rendered section self-validates
that its expected target subset has exactly one accepted receipt row with exact FASTA/MSA/report path plus
manifest/workstream provenance, and the project-level bridge runs a strict aggregate target-set/provenance
check so unexpected or stale rows are caught before remote-check. Set
`TARGET_MSA_PRECOMPUTE_DRY_RUN=1` before the bridge command to validate manifest freshness and print the
planned target set plus current receipt state without submitting jobs or creating/truncating the receipt; if
that receipt is non-empty, the dry-run also previews recorded, missing, duplicate, and unexpected target ids
plus strict accepted-status, job-id, manifest/workstream, and FASTA/MSA/report provenance validity, so
partial-submit recovery can be inspected before any overwrite. Set
`TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH=1` only for intentional local diagnostics. The dry-run also reports
the required helper file SHA-256s, whether each planned source target FASTA is already present or can be
regenerated by the same bridge from its prepared/source PDB or `rcsb_id` metadata, and whether the Boltz
runtime pointed to by `ENV_PY` and `BOLTZ` is executable when new target-MSA outputs are still missing. On
Cayuga, leave `ENV_PY` at the Boltz conda Python or set `BIO_SFM_PYTHON` explicitly; the generated bridge
defaults its helper Python to `ENV_PY` before falling back to `python`, avoiding the system Python 3.6
login-node trap. The real submit path verifies every helper file still matches the generated bridge hash,
every planned source target FASTA is present or regenerable, and the required Boltz runtime exists before
creating or truncating the receipt, so stale helper code, an ungrounded missing FASTA, or a bad Cayuga
Boltz environment fails closed before any resume evidence is touched. If Boltz writes a matching `.a3m`
and then fails during the unnecessary structure-prediction tail of this MSA-only job, the helper recovers
that `.a3m` and writes the report instead of throwing away usable MSA output; use `KEEP_WORK=1` only when
intentionally recovering from an existing work directory. The helper preserves the caller-declared
`fasta` and `out` strings in the report and writes machine-specific absolute paths only as `fasta_abs` and
`out_abs`, so reports generated on Cayuga still validate after sync-back against repo-relative manifests.
Add `--emit-external-sync-back-plan results/m6c_project_external_sync_back.sh` to turn that checklist into
one external pull bridge that records the W3/W4 direct sync scripts as provenance comments, then hands
local W1-W4 reruns and project-status refresh to `results/m6c_project_post_sync.sh`.
When `--emit-external-remote-check-plan` is also present, that external sync bridge fail-closes before
`rsync` unless the matching remote-check report proves the same pending-path manifest is all-present and
any required target-MSA receipt is locally satisfied.
The pending-path sidecar manifests record path-count and SHA-256 fingerprints, and generated input-prep
and external sync scripts check the current checklist before rsync so stale pull/replay scripts fail closed.
Each generated sync step also verifies that the local pulled file is non-empty immediately after `rsync`.
Bridge scripts derive the repo root from their own path, default local pulls to that root unless
`LOCAL_BIO_SFM_ROOT` or `--sync-local-root` overrides it, and post-sync replay bootstraps
`BIO_SFM_PYTHON`, `PYTHONNOUSERSITE=1`, and local `PYTHONPATH` for fresh-shell reruns. Sync and
remote-check bridge Python snippets also honor `BIO_SFM_PYTHON`.
Generated bridge/status artifacts are written by atomic replace, so a post-sync status refresh can update
bridge files without truncating a currently running shell script.
The input-prep and external bridges failure-collect each per-path `rsync` plus the post-sync call, so one
missing remote artifact does not prevent later pulls or local status replay; each script still exits
nonzero if any pull/replay step failed.
The post-sync plan replays W1/W2 completion/readiness checks and, when available, reruns W3/W4 from the
`self_command` stored in the current predictor-contract report and W4 preflight artifact. It
failure-collects those local steps so a partial sync still reaches later checks and final status refresh,
then exits nonzero if any replay step failed. For W3, that post-sync self-command regenerates the contract
report, command plan, and sync-back plan; the direct W3 sync script checks that each pulled
secondary-record JSONL is non-empty after `rsync` and intentionally avoids rewriting itself while it is
running.
The generated status JSON/text records `generated_scripts` plus `recommended_next_script`; sync script
entries include compact manifest summaries (`n_paths`, SHA-256, source/sidecar). Use
`operator_preflight_command` first when present, then `recommended_next_script` as the first executable
bridge when resuming from a fresh Codex session, after
confirming `sync_manifest_audit.ok=true`; currently that first bridge is the target-MSA precompute plan when
W1/W2 target MSAs are pending, then the remote existence check, then a project-status refresh that consumes
`results/m6c_project_remote_check.json`, then the external sync-back script only after refreshed status
recommends it. A complete target-MSA precompute receipt marks that first step satisfied. A failed audit blocks the recommended script until the stale manifest/script is regenerated.
Also inspect `resume_bridge_preflight`: `ready_to_execute` means the bridge can be run immediately,
`waiting_on_env` means the files and manifests are fresh but `CAYUGA_BIO_SFM_ROOT` must be exported first,
`waiting_on_cayuga_session` means the next script is a Cayuga-only submit step, and `blocked` means
regenerate or repair the bridge before
running it. For runnable/external-waiting bridges, preflight `next_action` carries the same downstream
remote-check/status-refresh continuation as the operator resume instruction. `resume_execution_ladder` orders the bridge sequence, including the non-shell
`project_status_refresh` pseudo-step: remote check -> status refresh with `--external-remote-check-report` ->
external sync-back -> post-sync replay. Later steps stay blocked until their predecessor succeeds. Inspect
`script_bash_syntax_ok` in `resume_bridge_preflight`; generated bridges are checked with non-executing
`bash -n`, and syntax failures are `bash_syntax_error` blockers. Also inspect
`generated_script_syntax_audit` to catch syntax failures in later generated bridge scripts before the ladder
reaches them; failures also appear in `goal_progress_audit.local_blockers`.
`pending_artifact_local_audit` alongside it: `all_missing` means the files still need
the external pull, while `all_present_nonempty` means a previous/manual sync likely happened and the local
completion/readiness/W3/W4 replay checks should run before another rsync.
`goal_progress_audit` is the Codex goal-mode guard in the same status JSON: use its W1-W4 requirement list,
first action, local/external blocker split, and `can_mark_goal_complete` flag before deciding whether a
resumed goal is complete, externally waiting, or locally actionable. It requires each workstream's canonical
terminal status, parseable non-empty evidence artifact whose content supports that terminal claim, W4
preflight/summary/campaign supporting artifacts when closed-loop completion is claimed, and clear local/external
blocker audit, not just a raw `complete=true`, before it can mark the overall goal complete.
Top-level `goal_progress`, `remaining`, `remaining_requirements`, `can_mark_goal_complete`, and
`goal_completion_note` mirror that compact completion/resume state for lightweight checks.
Top-level `operator_next_action`, `operator_next_command`, and `operator_next_role` mirror that resume
instruction; `operator_next_action` also includes the downstream remote-check/status-refresh continuation
when the ladder requires it. Top-level `next_action` remains the scientific workstream action and may be less operational
than the recommended bridge.
For calibrated W4 routing, also add prior verified `--batch-prevalidate-records` and
`--batch-conformal-alpha`; readiness forwards those as `run_batch_round.py --prevalidate-records` and
`--conformal-alpha`. The prevalidation records must be prior evidence only: any overlap with the current
batch candidate identities is blocked as hidden-truth leakage. Supplying `--conformal-alpha` without
prior prevalidation records is also blocked, because no complex-regime `tau` can be established. The
preflight also records a `batch_contract` audit and blocks calibrated routing if the prior records and
current batch records disagree on `predictor_id`, `signal_source`, `label_source`, or `lrmsd_threshold`
within any routed regime.
When `--scale-target-id` is set, the readiness target-MSA precompute section is scoped to that one target
instead of every manifest entry, so placeholder panel targets are not submitted during W1 scale-up.
If `--require-files` finds only repairable missing/empty source/prep/FASTA/MSA/report inputs and an input-prep
plan is available, readiness reports `waiting_on_input_prep`: run the emitted `target_msa_precompute`
section, then rerun readiness with `--require-files`. A missing `source_pdb` without `rcsb_id`, a missing
prepared PDB with no source path, MSA/FASTA mismatches, bad prep reports, malformed manifests, or missing
second-predictor records stay `blocked`.
The readiness JSON and shell plan include a canonical `self_command` / `# rerun_readiness_after_prep`;
after the target-MSA sbatch finishes, rerun that command so `--emit-scale-plan` is refreshed from the
current filesystem state without carrying unrelated default W4 batch options.
The terminal summary and emitted readiness shell plan list the exact missing or mismatched files, and the
same entries are preserved under `scale_next_batch.details.failures` or
`multi_target_manifest.details.failures` in the JSON readiness report for machine-readable triage.

To summarize the roadmap state after writing posthoc, panel, or cross-predictor artifacts:

```sh
python -m bio_sfm_designer.experiments.complex_project_status \
  --posthoc-manifest results/m6c_posthoc/manifest.json \
  --scale-completion results/m6c_scale_completion_1BRS_AD.json \
  --scale-input-prep-completion results/m6c_input_prep_completion.json \
  --scale-target-manifest configs/template_complex_targets.json \
  --scale-readiness-report results/m6c_readiness.json \
  --target-manifest-report results/m6d_candidate_targets_manifest.json \
  --panel-input-prep-completion results/m6d_candidate_input_prep_completion.json \
  --panel-target-manifest configs/m6d_candidate_complex_targets.json \
  --panel-readiness-report results/m6d_candidate_readiness.json \
  --panel-completion results/m6c_panel_completion.json \
  --panel-report results/m6c_panel_report.json \
  --predictor-contract-report results/m6c_second_predictor_contract.json \
  --predictor-sync-back-plan results/m6c_second_predictor_sync_back.sh \
  --cross-predictor-report results/m6c_cross_predictor.json \
  --batch-preflight results/round_0/preflight.json \
  --batch-summary results/round_0/summary.json \
  --batch-campaign results/round_0/campaign.jsonl \
  --batch-sync-back-plan results/m6c_w4_sync_back.sh \
  --out results/m6c_project_status.json \
  --emit-pending-input-prep-paths results/m6c_project_pending_input_prep_paths.txt \
  --emit-pending-external-paths results/m6c_project_pending_external_paths.txt \
  --emit-sync-back-plan results/m6c_project_sync_back.sh \
  --emit-external-sync-back-plan results/m6c_project_external_sync_back.sh \
  --emit-external-remote-check-plan results/m6c_project_remote_check.sh \
  --external-remote-check-report results/m6c_project_remote_check.json \
  --emit-target-msa-precompute-plan results/m6c_project_target_msa_precompute.sh \
  --emit-post-sync-plan results/m6c_project_post_sync.sh
```

When W1 and W2 share the same missing target-MSA file, the emitted
`results/m6c_project_pending_input_prep_paths.txt` de-duplicates it into a single copy/sync path while
`results/m6c_project_status.json` preserves the workstream and target provenance.
When raw W1/W2 manifests are supplied, `results/m6c_project_target_msa_precompute.sh` also de-duplicates
the upstream precompute work itself when duplicated target ids point to the same FASTA/MSA/report material,
so the shared `1BRS_AD` target is prepared once before the remote-check bridge. If the duplicated id points
to different material, status reports a plan conflict and the generated bridge exits before submit or receipt
initialization.
The emitted `results/m6c_project_sync_back.sh` turns that list into explicit `rsync -avP` pulls from
`CAYUGA_BIO_SFM_ROOT` and then calls the post-sync replay script.
The emitted `results/m6c_project_post_sync.sh` then replays W1/W2 input-prep completion, W1/W2
readiness, and the project-status refresh after those paths are synced back.

The posthoc bundle writes `project_status.json` and `project_status.txt` automatically for W1;
missing panel or cross-predictor artifacts are reported as missing workstreams, not as completed evidence.
When scale/panel completion reports are supplied, project status reports the intermediate post-Cayuga
state explicitly, e.g. `scale_records_ready_for_posthoc`, `scale_completion_blocked`,
`panel_records_ready_for_report`, or `panel_completion_blocked`.
For W2, a current non-ready target manifest supersedes stale panel-completion artifacts so missing
target-MSA/report prep is reported before downstream record-sync failures.
When a predictor-contract report is supplied before the final cross-predictor report, W3 reports
`second_predictor_contract_ready` or `second_predictor_contract_blocked`; blocked W3 status keeps
`commands_available=false` and does not re-expose runnable downstream commands.
When batch preflight and summary are supplied, W4 reports `batch_preflight_blocked`,
`batch_gate_prevalidation_missing`, `batch_gate_prevalidation_blocked`, `batch_preflight_ready`,
or `closed_loop_round_complete`; the complete
W4 state also requires prior conformal gate prevalidation with a recorded complex-regime `tau`,
compatible prevalidation/current-batch `batch_contract`, `summary.json gate_calibrated=true`, and a
readable `campaign.jsonl` whose row count matches the summary routed-candidate count, whose rows have
non-empty unique `candidate_id` values plus known DBTL routing actions, whose action mix matches any
summary aggregate action rates, whose optional summary `per_round` counts agree with the aggregate,
whose reported `assays_used` matches the campaign `verify_assay` count,
whose reported summary `best` matches the highest-quality advancing campaign row,
and whose candidate-id set matches preflight when preflight recorded it, next to the summary unless
`--batch-campaign` is supplied explicitly.
For W1/W2, alpha-bearing artifacts must match the requested `--target-alpha`; mismatched alpha decisions,
scale completions, panel completions, or panel reports are reported as alpha-mismatch states rather than
completed evidence.

## Multi-Target Panel

For a fresh panel, copy `configs/template_complex_targets.json` and replace the placeholder paths.
The current W2 candidate panel is already staged in `configs/m6d_candidate_complex_targets.json`;
see `docs/M6D_CANDIDATE_PANEL.md` for prep evidence and remaining MSA/report blockers. Then run:

```sh
# If target .a3m/report files do not exist yet, render and submit the one-time MSA jobs first.
# For targets with `rcsb_id`, this same plan also fetches source PDBs, prepares heterodimers,
# and extracts target FASTAs before target-MSA submission.
python -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest configs/my_complex_targets.json \
  --require-files --min-targets 3 \
  --out results/m6c_targets_manifest.json \
  --emit-plan results/m6c_targets_submit.sh \
  --emit-msa-plan results/m6c_target_msas.sh
```

For W1 single-target prep or staged panel bring-up, add one or more `--target-id <id>` arguments to
validate and emit only that subset while leaving placeholder targets in the manifest.
The emitted MSA plan includes an `# expected_input_prep_files` checklist, and the JSON report written by
`--out` carries the same paths as `input_prep_artifacts`; if the plan runs on Cayuga,
sync those listed paths back before rerunning local validation. After sync-back, first run the lightweight
completion check:

```sh
python -m bio_sfm_designer.experiments.complex_input_prep_completion \
  --report results/m6c_target_manifest_1BRS_AD.json \
  --out results/m6c_input_prep_completion.json \
  --emit-plan results/m6c_input_prep_completion.sh \
  --emit-pending-paths results/m6c_pending_input_prep_paths.txt
```

If it reports `ready_for_require_files`, run the emitted `manifest_command`, or the original
`# rerun_manifest_after_msa` command embedded at the bottom of the MSA plan when you also need to refresh
the submission plan. If it blocks, sync/fix the listed source/prepared PDB, FASTA/MSA, or report paths
before rerunning manifest validation; the JSON report exposes `pending_artifacts`, `blocked_targets`, and
`artifacts_by_target`, while `--emit-pending-paths` writes a one-path-per-line sync-back list.
If a target `.a3m` already exists but its report is missing or stale, the plan validates the existing MSA
against the FASTA and refreshes the report locally instead of submitting another GPU MSA job.

The emitted submit plan replays manifest file/report preflight before any `sbatch`, extracts each
target FASTA with its report, verifies that each target MSA exists, then
submits the complex ProteinMPNN and Boltz jobs for ready targets. It captures each ProteinMPNN
job id with `sbatch --parsable`, submits the matching Boltz job with `--dependency=afterok`,
and makes `NUM_SEQ`, `TEMP`, `SEED`, and `OBJECTIVE` explicit from manifest `defaults` or
per-target overrides. With `--require-files`, the manifest validator also checks that each
target MSA query sequence matches the explicit target FASTA and that declared/default FASTA and
target-MSA reports match before a target is considered ready.
It does not require planned downstream `records` paths to exist before jobs run unless
`--require-records` is explicitly supplied.

After the panel jobs finish and the per-target records JSONLs are synced back to the manifest paths:

```sh
python -m bio_sfm_designer.experiments.complex_panel_completion \
  --manifest configs/my_complex_targets.json \
  --min-targets 3 \
  --min-records-per-target 20 \
  --out results/m6c_panel_completion.json \
  --panel-out results/m6c_panel_report.json \
  --emit-plan results/m6c_panel_completion.sh
```

For staged panel debugging, add repeated `--target-id <id>` arguments and set `--min-targets` to the
selected subset size. The emitted shell plan preserves `--target-id`, `--min-targets`,
`--min-records-per-target`, `--target-alpha`, `--panel-out`, and `--out` so the completion check is
replayable from the saved artifact.

This checks that every completed target records file is present, non-empty, readable JSONL, and carries
the manifest target id as `complex_target_id`. If it reports `ready_for_panel_report`, run the emitted
panel-report command.

## Second Predictor

Copy `configs/template_second_predictor_contract.json`, replace the placeholder second-predictor
records path and provenance fields, then run:

```sh
python -m bio_sfm_designer.experiments.complex_predictor_contract \
  --contract configs/my_second_predictor_contract.json \
  --require-files --run-record-qc \
  --out results/m6c_second_predictor_contract.json \
  --emit-plan results/m6c_second_predictor_commands.sh \
  --emit-sync-back-plan results/m6c_second_predictor_sync_back.sh
```

The contract validator writes the exact strict-QC command for the second-predictor JSONL and the
matched `complex_cross_predictor.py --emit-matches` command for Boltz-vs-second-predictor comparison.
The template pins `cross_predictor.min_overlap=20`, `cross_predictor.min_label_agreement=0.8`,
`cross_predictor.copy_tolerance=1e-6`, `cross_predictor.copy_fraction_threshold=0.95`,
`cross_predictor.label_threshold_tolerance=1e-9`, and
`cross_predictor.require_disjoint_record_files=true`; invalid overlap/agreement settings block at the
contract stage, primary/secondary record paths must be disjoint, and the emitted comparison command passes
these options explicitly so overlap, label-agreement, exact/mostly-near-exact numeric-copy blocking,
label-threshold agreement, and one-predictor-per-record-file checking are reproducible. Project status
also refuses to mark W3 complete from older/non-strict cross-predictor reports that lack the record-file audit.
If secondary records are missing or empty, the emitted `results/m6c_second_predictor_sync_back.sh`
pulls those JSONLs from `CAYUGA_BIO_SFM_ROOT`, verifies each pulled local JSONL is non-empty, refreshes
the contract report/command plan, and then runs the refreshed plan.
It blocks immediately if the declared secondary `predictor_id` appears in `forbid_predictor_ids`, even
before records files exist.
Cross-predictor overlap is counted only when both `complex_target_id` and `target_id` match, so reused
candidate ids across different panel targets do not silently become false overlap.
If `--require-files` or `--run-record-qc` blocks, the emitted shell plan lists blockers and comments out
the downstream QC/cross-predictor commands until the contract validates.
This is the W3 gate before treating an independent predictor as evidence against the single-model caveat.

## Guards

- `prep_hetdimer.py` rejects missing chains, residue-numbering gaps, non-contacting chains, and
  source-overwrite mistakes before model spend. A manifest target may opt into `allow_numbering_gaps: true`
  only after a reviewed source-PDB exception, as with the 1BRS_AD chain-D D64-D65 numbering gap.
- `extract_chain_fasta.py` makes the fixed target sequence explicit before MSA generation.
- `complex_target_manifest.py --emit-msa-plan` can render the full cheap input-prep sequence:
  RCSB source PDB fetch from `rcsb_id`, heterodimer prep, target FASTA extraction, and target-MSA
  precompute.
- `complex_target_manifest.py --require-files` checks target FASTA/MSA presence, target-MSA report
  provenance when declared, and FASTA/MSA sequence agreement before emitting a ready target in the
  multi-target plan; emitted plans chain each Boltz job to its matching ProteinMPNN job and preserve
  explicit batch settings.
- `complex_input_prep_completion.py` checks that the manifest-listed source/prepared PDB, FASTA/MSA, and
  report files are synced back and non-empty before the stricter manifest `--require-files` gate is rerun.
- `complex_panel_completion.py` checks synced per-target records before `complex_panel_report.py`,
  including row-level `complex_target_id` alignment with the manifest target id.
- `predict_boltz_complex.py --target-msa` checks the MSA query sequence against every candidate
  `target_seq`; wrong target MSAs fail before GPU inference.
- `COMPLEX_ID`/`--complex-id` is carried into ProteinMPNN candidate metadata/ids and then into Boltz records
  as `complex_target_id`; multi-target candidates or records without that field are not acceptable evidence
  for generalization or strict W4 DBTL rounds.
- Boltz complex records also carry `predictor_id`, `signal_source`, and `label_source`; second-predictor
  records should preserve the same `complex_target_id` + `target_id` keys and use explicit source fields so
  `complex_cross_predictor.py` can match and compare them. The cross-predictor check requires enough labeled
  overlap, label agreement under the same `lrmsd_threshold` definition, complete target identity, distinct
  signal/label sources, and non-copied pAE/L-RMSD numeric values before the single-model caveat can close;
  exact or mostly near-exact numeric copies under a new predictor id remain blocked. The second-predictor
  contract template records `min_overlap`, `min_label_agreement`, `copy_tolerance`,
  `copy_fraction_threshold`, `label_threshold_tolerance`, and strict disjoint-record-file checking used for
  this check and emits them on the command line. Use
  `--emit-matches results/m6c_cross_predictor_matches.jsonl` to write
  target-wise matched rows for disagreement/provenance triage.
- Before running `complex_cross_predictor.py`, preflight second-predictor records through
  `complex_predictor_contract.py --require-files --run-record-qc`; it emits the strict
  `complex_records_qc.py` command with expected predictor/source fields and forbidden Boltz-copy ids.
- For real scale-up claims, run `complex_records_qc.py`, `complex_alpha_decision.py`, and
  `complex_posthoc_bundle.py` with `--require-complex-target-id --require-provenance --require-chain-ids`. The committed
  192-record fixture is schema-current and passes this strict mode. Posthoc alpha/report tools also
  require row-level `lrmsd_threshold` metadata to match the analysis `--threshold` before accepting
  recomputed `truth.correct` labels.
- `TARGET_MSA` and `USE_MSA_SERVER=1` are mutually exclusive. Use `TARGET_MSA` for scale-up.
- Boltz runs with `PYTHONNOUSERSITE=1` and `--no_kernels`; the script wipes its work directory
  per output file to avoid stale-output contamination.
- `complex_records_qc.py` fails on missing pAE, bad L-RMSD labels, duplicate conflicts, and
  unaligned interfaces before any alpha claims are made.

## Completion Criteria

For a scale-up batch to count as usable evidence:

- Strict QC passes on every records file, including `complex_target_id`, `target_chain`,
  `binder_chain`, `predictor_id`, `signal_source`, and `label_source`.
- Every record's `lrmsd_threshold` metadata matches the posthoc/report analysis threshold.
- The posthoc bundle writes QC, alpha sweep, alpha plan, Markdown report, JSON report, and manifest.
- The posthoc bundle writes `project_status.json`/`.txt` so W1 status is recorded with the exact
  evidence set.
- The posthoc bundle writes `complex_alpha_decision.json`; for the current target alpha it must say
  `stop_certified` before scaling can stop, otherwise `continue_scale` gives the next-record estimate.
- When `continue_scale`, the decision artifact's `next_batch` block gives the next practical
  ProteinMPNN `NUM_SEQ` per temperature; use that instead of choosing batch size by inspection.
- `complex_next_batch_plan.py` expands that `next_batch` block into temp-specific sbatch commands
  with distinct output JSONL paths and generate->predict dependencies, and it requires a strict-QC
  decision artifact before emitting real scale commands.
- `complex_scale_completion.py` passes on the saved next-batch JSON plan after records are synced back,
  proving that every expected posthoc input exists, is non-empty, and is readable JSONL.
- `complex_project_status.py` reports W1/W2/W3/W4 status from the written JSON artifacts and keeps
  missing evidence explicit; W4 completion requires strict preflight, compatible gate-prevalidation
  `batch_contract`, a matching summary, and readable
  `campaign.jsonl`. Pass `--batch-sync-back-plan` while W4 batch artifacts are missing so status output
  keeps the sync/rerun script visible; pass `--predictor-sync-back-plan` while W3 secondary records are
  missing for the same reason. `pending_external_artifacts` is the combined W1/W2/W3/W4 missing-artifact
  checklist; `--emit-pending-external-paths` writes it as one path per line, and
  `--emit-external-remote-check-plan` turns it into a one-command remote existence preflight before rsync,
  while `--emit-external-sync-back-plan` turns it into an external pull bridge whose post-sync plan owns
  local W1/W2/W3/W4 reruns. The `recommended_next_script` field points to the first script to execute.
- The alpha sweep reports whether `alpha=0.2` is certified rather than inferred by eye.
- Multi-target claims require `complex_panel_report.py` to pass; the pooled diagnostic alone is not enough.
- Before `complex_panel_report.py`, `complex_panel_completion.py` passes on the manifest after records are
  synced back, proving that each expected target records file exists, is non-empty, is readable JSONL, and
  carries the expected `complex_target_id`.
- `complex_panel_report.py` treats a panel certificate as predictor-specific; do not mix Boltz and a second
  predictor in one panel report. Use `complex_cross_predictor.py` for predictor comparisons.
- Closing the single-model caveat requires `complex_cross_predictor.py` to pass on matched records from
  at least two predictor ids; keep the `--emit-matches` JSONL with the report so mismatches are auditable.
- The report still states the single-model and one-target caveats unless the batch actually closes them.
