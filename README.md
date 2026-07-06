# bio_sfm_designer

> **Continuing this project (new session / Codex)? Start with [HANDOFF.md](HANDOFF.md)** — goal, full
> progress, honest findings, key decisions, and concrete next steps, self-contained.
> For the long project-development plan, use [docs/PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md).
> For long-running Codex goal mode, use [docs/CODEX_GOAL_MODE.md](docs/CODEX_GOAL_MODE.md).
> Before making the repo public, run the no-publish release gate:
> `python -m bio_sfm_designer.experiments.public_release_readiness`.

A **calibrated, cost-aware, safety-screened** Design–Build–Test–Learn (DBTL) designer
for biology. Claude orchestrates specialist scientific foundation models (SFMs —
protein/genome/single-cell); an **external calibrated trust gate** decides, per
candidate, whether to

`trust_sfm | verify_assay | default_baseline | defer`,  scored by `net = benefit − λ·assays`,

and a **biosafety screen** runs before propose and before synth.

**Built on [bio-sfm-trust-core](https://github.com/jang1563/bio-sfm-trust-core)** — the reusable,
domain-agnostic trust engine (gate · calibration · conformal, pure stdlib). This repo is the biology
*application*; that repo is the *engine*. The dependency is one-way: `designer → trust-core`.

## Why it isn't just another generative designer

Proto/EvoDesign-class systems orchestrate many specialists but **trust their confidence
unconditionally**. The sibling project [bio-sfm-trust-audit] *measured* why that's unsafe:
an LLM placed above specialist models allocates verification at ≈ chance, stronger models
over-verify, and trust tracks name-familiarity rather than reliability. So here the trust
decision is **external and engineered**, not delegated to the orchestrator. See
[`docs/BACKGROUND.md`](docs/BACKGROUND.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Three constraints are baked into the gate ([`trust/gate.py`](src/bio_sfm_designer/trust/gate.py)):
1. the gate is external — never "ask the LLM if it's confident";
2. where a cheap structural baseline exists, the competence signal is **disagreement with it**
   (not the SFM's own confidence); where none exists (e.g. protein structure), `trust_sfm` is
   **restricted to calibration-validated regimes** — monomer pLDDT is assumed-validated, every
   other regime must **earn** trust via a validated calibrator (offline `prevalidate` or online),
   else it verifies/defers (complexes, whose raw pLDDT is uncalibrated, are never blindly trusted);
3. confidence is consumed as a **scalar calibrated risk**, never a raw latent.

## Status (2026-07-04)

Past the stub milestone — the loop is closed on CPU and runs on a real, license-clean backend.

**Public clone verified** (`118 passed, 4 skipped`; the pinned public `bio-sfm-trust-core` release tag
engine installs from GitHub):
- DBTL loop closed on CPU (heritable feedback, pluggable acquisition, causal orchestration).
- Real HPC backend: **ProteinMPNN** (design) → **ESMFold** (refold / pLDDT signal) → **Boltz-2**
  (architecturally independent refold = the success label). HPC job → JSONL → local `Precomputed*` adapters.
- **Conformal risk control** (RCPS / Hoeffding) so a `trust` carries a stated false-accept bound.
- CPU alpha scale planner (`python -m bio_sfm_designer.experiments.complex_alpha_plan`) to turn the current
  alpha<=0.2 frontier into an explicit next-n estimate before HPC spend.
- Alpha decision artifact (`python -m bio_sfm_designer.experiments.complex_alpha_decision`) to mark each
  post-HPC batch as `stop_certified`, `continue_scale`, or QC-blocked for the target alpha, with a
  `next_batch` recommendation for the next ProteinMPNN scale-up when more records are justified.
- Next-batch command planner (`python -m bio_sfm_designer.experiments.complex_next_batch_plan`) to expand
  `next_batch` into temp-specific ProteinMPNN/Boltz sbatch commands without JSONL output collisions; by
  default it refuses scale plans from decision artifacts that were not produced under strict QC, and it
  refuses to save runnable scale plans without selected-target `--require-files` preflight unless an
  explicit diagnostic escape hatch is used; unchecked diagnostic plans are marked in JSON/shell output. It
  carries manifest `SEED`, `OBJECTIVE`, and `COMPLEX_ID` into the generate command.
- Scale-completion checker (`python -m bio_sfm_designer.experiments.complex_scale_completion`) to verify
  that planned post-Cayuga record JSONLs were synced back, structurally readable, and aligned to the
  planned `complex_target_id` before the synchronized posthoc bundle runs; emitted shell plans preserve
  `--new-records-only` and target-id checking choices for replay.
- Complex records QC (`python -m bio_sfm_designer.experiments.complex_records_qc`) to fail fast on partial,
  conflicting, or schema-broken Boltz JSONL before alpha/report analyses; strict mode requires
  `complex_target_id`, chain ids, `predictor_id`, `signal_source`, and `label_source` before
  scale/panel/predictor claims.
- One-command M6c posthoc bundle (`python -m bio_sfm_designer.experiments.complex_posthoc_bundle`) for
  QC + sweep + alpha plan + alpha decision + seed/design-regime/scale-projection audits + report +
  project status from one synchronized records list; alpha/report paths now block mixed row-level
  `lrmsd_threshold` metadata before recomputing `truth.correct`.
- Multi-target manifest validator (`python -m bio_sfm_designer.experiments.complex_target_manifest`) for
  >=3 heterodimer panels before generalization claims, with emitted submit plans that chain each Boltz
  job to its matching ProteinMPNN job and replay manifest file/report preflight before any `sbatch`. A
  separate `--emit-msa-plan` path can fetch an RCSB source PDB from `rcsb_id`, prepare the heterodimer,
  extract target FASTA, and precompute missing target `.a3m` + report files; repeated `--target-id`
  arguments restrict validation and emitted plans to a selected W1 or staged-panel subset. Historical
  W2 panels are summarized in `docs/M6D_CANDIDATE_PANEL.md`; an earlier W2 branch is fresh discovery via
  `results/m6d_w2_fresh_discovery_pool.{json,md}` and
  `configs/m6d_w2_fresh_discovery_complex_targets.json`. Target-MSA precompute is complete for the selected
  candidates; the strict-ready 3-target unique-source pilot in
  `configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json` has now completed on Cayuga and is
  `multi_target_evaluable_not_certified` at alpha=0.2. Its redesign diagnostic classifies all three pilot
  targets as current-protocol target/protocol mismatches, and the 12-target known pool still admits zero
  candidates for another W2 pilot. The then-next branch was
  `protocol_redesign_plus_success_enriched_discovery_v1`, with no-spend rules in
  `configs/m6d_w2_next_branch_candidate_rules.json`. Expanded source-diverse discovery now adds 10
  structurally prepared candidates from 10 unique source PDBs. After the low-concurrency MSA retry and
  sync-back, all 10 target `.a3m`/report files are ready, the 25-candidate combined pool admits those 10
  for the next W2 branch, and strict preflight passes on
  `configs/m6d_w2_expanded_next_branch_targets.json` with 10/10 ready targets. The expanded panel ran on
  Cayuga through the receipt-preserving wrapper and is now synced back: `results/m6d_w2_expanded_next_branch_completion.json`
  is `ready_for_panel_report` with 10/10 completed targets, and
  `results/m6d_w2_expanded_next_branch_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2 with 10 targets and 1000 records. Boltz job
  `3056576` for `1QFW_BA` failed on a target-MSA/candidate sequence mismatch caused by a terminal
  atom-only residue, but repair job `3056582` completed and generated the synced `1QFW_BA` record. Do
  not use the pooled diagnostic as W2 evidence: all 10 target-wise certificates are `not_certified`, so
  W2 still needs target replacement/protocol redesign before further scale-up. The current redesign
  diagnostic is `results/m6d_w2_expanded_next_branch_redesign_diagnostic.{json,md}` and the next branch
  anchor is `results/m6d_w2_expanded_next_branch_next_actions.md`: continue as
  `w2_target_family_redesign_v1`, excluding or redesigning the six low-success targets before any more
  W2 GPU spend. The target-family redesign rules are now materialized in
  `configs/m6d_w2_target_family_redesign_v1_candidate_rules.json`; the current local inventory screen
  admits 0/25 candidates, the manifest design is blocked with 0 selected targets, and a filtered 39-seed
  local source-cache scan admitted 0 structural candidates. RCSB seed expansion then selected 80 new seeds,
  local structural discovery admitted 132 chain pairs and selected 10 source-diverse targets, but sequence
  diversity audit blocks the full 10-target panel because 8/10 targets are sequence-identical near duplicates.
  The representative subset `10XZ_EF`, `10YB_GH`, and `12NP_AH` completed target-MSA prep after a transient
  10XZ retry, passed strict preflight, and completed a scoped representative ProteinMPNN/Boltz probe with
  receipt capture. `results/m6d_w2_target_family_redesign_v1_rcsb_representative_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2 with 3 targets and 300 records; all three target-wise
  certificates are `not_certified`. The diagnostic recommends replacing/redesigning `12NP_AH` before more W2
  panel GPU and predeclaring a low-pAE acceptance/calibration strategy before scaling `10XZ_EF` or `10YB_GH`.
  `w2_target_family_redesign_v2` carries those constraints into a stricter no-spend rule set and rescreens
  the current local inventory: `results/m6d_w2_target_family_redesign_v2_candidate_pool.json` admits 0/25
  candidates, keeps `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` source-redundancy audit-only, and is not ready for a
  revised manifest or Cayuga submission. The follow-on `w2_target_family_redesign_v2_rcsb` branch now
  expands beyond those excluded sources: saved-response RCSB seed expansion selected 80 seeds, structural
  intake screened 423 chain pairs and selected 20 source-unique targets, sequence-diversity audit passes
  with 12 clusters and largest-cluster fraction 0.25, and Cayuga target-MSA precompute is complete after an
  11-target low-concurrency retry. Post-sync strict preflight passes 20/20, and
  `results/m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh` passed local and Cayuga dry-runs,
  then submitted 20 receipt-validated ProteinMPNN/Boltz job pairs on Cayuga (`3056715`-`3056754`) with
  records isolated under `hpc_outputs/m6d_w2_target_family_redesign_v2_rcsb_records`. The records are now
  synced back and completed: `results/m6d_w2_target_family_redesign_v2_rcsb_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2 with 20 targets and 2000 records. Only `1A3O_BA` and
  `1A9W_EA` certify target-wise; the remaining 18 targets do not. The pooled diagnostic certifies tau=1.0,
  but pooled-only evidence is not W2 generalization. The follow-on no-spend branch
  `w2_target_family_redesign_v3` preserves those two target-specific positives as controls, selected 80 new
  RCSB seeds, screened 753 chain pairs, selected 8 source-diverse and sequence-diverse candidates, and
  submitted target-MSA precompute jobs `3057081`-`3057088` on Cayuga. Six targets are ready remotely; `1AOI_HB`
  and `1AVO_DC` hit the known ColabFold MSA-server invalid tar/gzip response and were resubmitted as
  low-concurrency retry jobs `3057090` and `3057091`; retry recovered 8/8 target MSAs. Strict post-MSA
  preflight passes 8/8, and the v3 panel was submitted on Cayuga through
  `results/m6d_w2_target_family_redesign_v3_submit_with_receipt.sh`: ProteinMPNN/Boltz job pairs are
  `3057094`-`3057109`, with records isolated under `hpc_outputs/m6d_w2_target_family_redesign_v3_records`.
  Those records are synced back and completed. The v3 target-wise panel report
  `results/m6d_w2_target_family_redesign_v3_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2 with 8 targets and 800 records. All eight target-wise
  certificates are `not_certified`. The pooled diagnostic certifies tau=0.75, but pooled-only evidence is not
  W2 generalization. The v3 diagnostic recommends replacing or redesigning low-success targets `1AOI_HB` and
  `1APY_CD` before more panel GPU.
  The follow-on v4 branch is now completed negative/evaluable: its 5-target representative panel
  (`1AY7_AB`, `1B27_CF`, `1B2S_BE`, `1AZZ_DC`, `1AYY_BA`) produced 500 records and
  `results/m6d_w2_target_family_redesign_v4_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2. `1AY7_AB` and `1B27_CF` are target-specific
  certified controls, but `1AYY_BA`, `1AZZ_DC`, and `1B2S_BE` are not certified, so v4 is not W2
  generalization. The v5 branch then froze stricter rules, admitted 13 source-diverse next-branch targets
  after MSA input-prep, emitted `configs/m6d_w2_target_family_redesign_v5_targets.json`, passed strict
  pre-submit preflight 13/13, and completed receipt-validated ProteinMPNN/Boltz job pairs `3057168`-`3057193`
  through `results/m6d_w2_target_family_redesign_v5_submit_with_receipt.sh`. The synced v5 panel is fully
  evaluable but not certified: `results/m6d_w2_target_family_redesign_v5_panel_report.json` has 13 targets,
  1300 records, and 0/13 target-wise certificates at alpha=0.2. The diagnostic
  `results/m6d_w2_target_family_redesign_v5_redesign_diagnostic.{json,md}` recommends redesigning or
  replacing low-success targets and treating high-success/no-trust targets as calibration/split-sensitivity
  diagnostics before any more W2 panel GPU. The follow-on no-spend gate strategy is now explicit in
  `results/m6d_w2_target_family_redesign_v5_gate_strategy.{json,md}`: label-degenerate all-success targets
  `1BFV_HL` and `1BQH_KI` need a gate-validation policy, `1B2U_CF`, `1B86_DC`, and `1BCP_KL` need a
  low-pAE acceptance strategy, `1B3S_CF` needs target-specific calibration, `1BGS_BF` is split-sensitive,
  and the six low-success targets require replacement or protocol redesign. The v6 no-spend rule set in
  `configs/m6d_w2_target_family_redesign_v6_candidate_rules.json` links that strategy and keeps Cayuga
  submission blocked; the current v6 local inventory screen
  `results/m6d_w2_target_family_redesign_v6_candidate_pool.{json,md}` admits 0/25 candidates, with only
  `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` audit-only. The blocker policy is now resolved fail-closed in
  `results/m6d_w2_target_family_redesign_v6_gate_strategy_resolution.{json,md}` and
  `configs/m6d_w2_target_family_redesign_v7_protocol.json`: label-degenerate all-success targets remain
  positive controls only, fixed low-pAE cutoff transfer is forbidden as a certificate, and the next W2
  branch is `w2_target_family_redesign_v7_calibratable_discovery`. Do not submit another W2 panel until
  discovery admits at least three non-anchor source-diverse targets and a new manifest/preflight exists. The
  v7 discovery pass screened 5000 RCSB response IDs, selected 80 new seeds, fetched 80 seeds, screened
  566 chain pairs, admitted 30 structurally, and selected 13 source-diverse candidates. The full
  13-target manifest is blocked for broad W2 by sequence diversity (`largest_cluster_fraction=0.307692`),
  but the representative 10-target subset in
  `configs/m6d_w2_target_family_redesign_v7_representative_targets.json` passes sequence diversity with
  10 clusters. Target-MSA input prep completed 10/10 after two low-concurrency retry jobs (`3057265`,
  `3057266`), strict post-MSA preflight passes 10/10, and the representative ProteinMPNN/Boltz panel
  completed on Cayuga with job pairs `3057268`-`3057287`. The synced completion artifact
  `results/m6d_w2_target_family_redesign_v7_completion.json` is `ready_for_panel_report` with 10/10
  completed targets. The target-wise report
  `results/m6d_w2_target_family_redesign_v7_panel_report.json` is
  `multi_target_evaluable_not_certified` at alpha=0.2 with 10 targets, 1000 records, and 0/10 target-wise
  certificates. The diagnostic `results/m6d_w2_target_family_redesign_v7_redesign_diagnostic.{json,md}`
  recommends `redesign_or_replace_low_success_targets`: `1BUV_TM`, `1BZQ_BN`, and `1C5F_CE` are
  target/protocol mismatch candidates, while the other seven targets remain low-pAE-acceptance holds.
  V7 is a completed negative/evaluable science result, not W2 generalization evidence; do not spend more
  W2 panel GPU until target replacement or generation/gate redesign is predeclared. That next no-spend
  branch is now frozen as `w2_target_family_redesign_v8_success_enriched_gate_redesign` in
  `results/m6d_w2_target_family_redesign_v8_followup_contract.{json,md}` and
  `configs/m6d_w2_target_family_redesign_v8_candidate_rules.json`: Cayuga submission remains `false`,
  all 10 v7 target/source IDs are excluded under the current protocol, and unlock requires at least three
  non-anchor targets, sequence-diversity/preflight, and predeclared low-pAE or target-specific calibration.
  The v8 no-spend screen has now produced an input-prep-ready branch: RCSB seed expansion selected
  100 seeds from 8000 response IDs; local structural intake screened 641 chain pairs, admitted 29
  structurally, and selected 12 source-diverse candidates; sequence diversity passes with 12 targets,
  8 clusters, and largest-cluster fraction 0.25; and
  `results/m6d_w2_target_family_redesign_v8_manifest_pre_msa.json` is `ok=true` with 12/12 ready targets.
  Target-MSA input prep then completed on Cayuga: initial jobs `3057296`-`3057307` produced 7/12 stable
  MSAs and hit the known transient ColabFold/MMseqs truncated-tar failure on five targets; the serial retry
  bridge `results/m6d_w2_target_family_redesign_v8_target_msa_retry_serial.sh` submitted retry jobs
  `3057334`-`3057338` and recovered all five. After sync-back,
  `results/m6d_w2_target_family_redesign_v8_input_prep_completion_post_sync.json` is `ok=true` with
  84/84 nonempty artifacts, and
  `results/m6d_w2_target_family_redesign_v8_manifest_post_msa_require_files.json` passes strict
  post-MSA `--require-files` with 12/12 ready targets and zero failures. The separate v8 panel artifacts
  are now generated: `results/m6d_w2_target_family_redesign_v8_submit_ready.json`,
  `results/m6d_w2_target_family_redesign_v8_submit_plan.sh`,
  `results/m6d_w2_target_family_redesign_v8_submit_with_receipt.sh`,
  `results/m6d_w2_target_family_redesign_v8_completion.sh`, and
  `results/m6d_w2_target_family_redesign_v8_sync_back.sh`. Local and Cayuga dry-runs passed, then the
  receipt wrapper submitted 12 ProteinMPNN/Boltz job pairs (`3057340`-`3057363`) and wrote
  `results/m6d_w2_target_family_redesign_v8_submit_receipt_summary.json`. The records are now synced back:
  `results/m6d_w2_target_family_redesign_v8_completion.json` is `ready_for_panel_report` with 12/12
  completed targets, and `results/m6d_w2_target_family_redesign_v8_panel_report.json` is
  `multi_target_evaluable_not_certified` at α=0.2 with 12 targets and 1200 records. Only `1CG5_AB` and
  `1COH_BA` are target-specific certified controls; the other 10 targets are not certified. The pooled
  diagnostic certifies α=0.2, but pooled-only evidence is not W2 generalization. Use
  `results/m6d_w2_target_family_redesign_v8_redesign_diagnostic.{json,md}` before any more W2 panel GPU.
  The follow-up branch is now frozen as
  `w2_target_family_redesign_v9_positive_controls_plus_calibration_redesign` in
  `results/m6d_w2_target_family_redesign_v9_followup_contract.{json,md}` and
  `configs/m6d_w2_target_family_redesign_v9_candidate_rules.json`: Cayuga submission is `false`; `1CG5_AB`
  and `1COH_BA` are retained only as target-specific positive controls; the 10 non-certified v8 targets are
  excluded under the current protocol. Next action is a no-spend replacement-target discovery or gate-redesign
  screen, not more W2 ProteinMPNN/Boltz panel jobs.
  That no-spend v9 replacement-target screen now passes the first local gates:
  `results/m6d_w2_target_family_redesign_v9_seed_expansion.{json,md}` selected 120 new RCSB seeds from
  10,000 response IDs, `results/m6d_w2_target_family_redesign_v9_discovery_pool.{json,md}` screened
  988 chain pairs and selected 14 source-diverse targets, and
  `results/m6d_w2_target_family_redesign_v9_sequence_diversity.{json,md}` passes with 14 sequence clusters.
  `results/m6d_w2_target_family_redesign_v9_manifest_pre_msa.json` is `ok=true` with 14/14 ready targets,
  and `results/m6d_w2_target_family_redesign_v9_target_msa_with_receipt.sh` dry-runs cleanly. Strict
  post-MSA `--require-files` intentionally fails on 28 missing target-MSA/MSA-report files, so the only
  open Cayuga action is target-MSA input prep; W2 panel submission is still blocked.
  `results/m6d_w2_target_family_redesign_v9_target_msa_presubmit_preflight.{json,md}` records the Cayuga
  presubmit readback: runtime/helper files are present, dry-run passes, and all 14 source/prepared/FASTA
  inputs are synced. Real target-MSA submission still requires explicit approval, and the wrapper refuses to
  touch the receipt unless `BIO_SFM_APPROVE_V9_TARGET_MSA=approve-v9-target-msa-precompute` is present.
  The postsubmit replay path is also ready:
  `results/m6d_w2_target_family_redesign_v9_pending_input_prep_paths.txt` lists the 28 expected MSA/report
  outputs, `results/m6d_w2_target_family_redesign_v9_msa_sync_back.sh` pulls them plus the receipt/summary
  after jobs finish, and `results/m6d_w2_target_family_redesign_v9_postsubmit_replay_plan.{json,md}`
  records the same approval-env-gated submit command plus the replay boundary.
  `results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.{json,md}`
  now verifies that this expected-blocked state is internally consistent: 14 targets, 28 pending
  target-MSA/MSA-report paths, 70/98 input-prep artifacts present, `audit_ok=true`, and panel submission
  still `false`. `results/m6c_project_status_w2_followup.json` now accepts that gate audit as the current
  W2 branch state (`target_msa_gate_ready_awaiting_explicit_approval`) so older negative panel reports stay
  as superseded evidence rather than hijacking the resume point.
  `results/m6d_w2_target_family_redesign_v9_approval_packet.{json,md}` is the no-submit approval packet:
  it verifies the project status, gate audit, representative manifest, 28-path pending list, target-MSA
  wrapper, and sync-back replay script agree, while keeping ProteinMPNN/Boltz panel submission blocked. The
  packet also records the approval env guard required by the wrapper.
  `results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.{json,md}` is the no-submit guard proof:
  static audit passes, a no-env wrapper run exits before receipt initialization, and the v9 target-MSA
  receipt remains absent on both local and Cayuga.
  `results/m6d_w2_explicit_approval_runbook.{json,md}` is the operator-facing no-submit runbook for later
  explicit approval: it records the target-MSA-only command order, keeps panel submission blocked, and
  requires sync-back plus strict replay before any panel plan can be considered.
  Project status now consumes this packet through `--w2-approval-packet`, so the machine resume state
  records `approval_packet_ready=true` and `can_submit_proteinmpnn_boltz_panel=false`.
  `results/m6d_w2_target_family_redesign_v9_approval_parity.{json,md}` compares the local and Cayuga
  packets and reports `parity_ok=true` without creating a target-MSA receipt. Project status consumes
  this report through `--w2-approval-parity`, so W2 also records `approval_parity_ok=true`.
  The guarded v9 ProteinMPNN/Boltz panel was then explicitly submitted on Cayuga, completed, synced back,
  and replayed locally: `results/m6d_w2_target_family_redesign_v9_completion.json` is
  `ready_for_panel_report` with 14/14 completed targets, while
  `results/m6d_w2_target_family_redesign_v9_panel_report.json` is
  `multi_target_evaluable_not_certified` at α=0.2 with 14 targets and 1400 records. The pooled diagnostic
  certifies α=0.2, but pooled-only evidence remains diagnostic; only `1DLF_HL` is target-wise certified
  (`τ=0.333`), and the other 13 targets are not certified. The post-panel diagnostic/strategy artifacts
  `results/m6d_w2_target_family_redesign_v9_redesign_diagnostic.{json,md}` and
  `results/m6d_w2_target_family_redesign_v9_gate_strategy.{json,md}` classify seven low-success
  target/protocol mismatches, five all-success label-degenerate controls, `1D2Z_BA` as a loose-α anchor
  rather than an α=0.2 certificate, and `1DLF_HL` as the single certified control. The next branch is frozen
  as `w2_target_family_redesign_v10_post_v9_decision` in
  `results/m6d_w2_target_family_redesign_v10_followup_contract.{json,md}` and
  `configs/m6d_w2_target_family_redesign_v10_candidate_rules.json`; Cayuga submission is `false` until a
  no-spend replacement-target discovery or predeclared target/family calibration redesign passes its gates.
- Input-prep completion checker (`python -m bio_sfm_designer.experiments.complex_input_prep_completion`)
  to verify that the manifest-listed source/prepared PDB, target FASTA/MSA, and companion report files
  are synced back and non-empty before rerunning the stricter `complex_target_manifest --require-files`
  gate; emitted shell plans preserve selected `--target-id` filters, optional pending-path outputs, and
  the manifest rerun command, while `--emit-pending-paths` writes a one-path-per-line list for sync-back scripts.
- Multi-target panel report (`python -m bio_sfm_designer.experiments.complex_panel_report`) to require
  explicit `complex_target_id` provenance, single-predictor/single-source panel evidence, and per-target
  certificates, not pooled-only or mixed-predictor evidence. It also blocks panel claims when row-level
  `lrmsd_threshold` metadata does not match the report `--threshold`, so a multi-target certificate cannot
  silently mix different success definitions.
- Multi-target panel completion checker (`python -m bio_sfm_designer.experiments.complex_panel_completion`)
  to verify that each manifest target's post-Cayuga records JSONL is synced, readable, and target-id
  aligned before `complex_panel_report.py` runs; repeated `--target-id` arguments support staged-panel
  subset completion checks and the emitted shell plan preserves the completion arguments.
- Cross-predictor bridge (`python -m bio_sfm_designer.experiments.complex_cross_predictor`) to check
  matched complex records across independent predictors before closing the single-model caveat; overlap is
  matched on `complex_target_id` + `target_id`, requires label agreement under the same
  `lrmsd_threshold` definition plus distinct `signal_source`/`label_source` provenance, rejects exact or
  mostly near-exact pAE/L-RMSD numeric copies under a new predictor id, and can emit a matched-overlap
  JSONL for disagreement triage. It also reports per-JSONL predictor membership, and the W3 contract emits
  comparisons with strict one-predictor-per-record-file checking; project status refuses to close W3 from
  older/non-strict cross-predictor reports that lack this audit.
- W3 decision protocol (`results/m6d_w2_w3_decision_protocol.{json,md}`) to keep the Boltz-vs-Chai
  disagreement as an adjudicated negative robustness result, not a positive independent-predictor claim;
  the protocol now materializes `results/m6d_w3_adjudication_set.jsonl` plus
  `results/m6d_w3_adjudication_set.json` with 12 discordant Boltz/Chai labels and 6 concordant-success
  controls for any future predeclared third-predictor or stronger-Chai adjudication run;
  `complex_project_status --w3-decision-protocol ...` now verifies the materialized JSONL sha256/count/roles
  and reports this as `negative_robustness_result_adjudicated` when strict integrity has no blockers.
  `results/m6d_w3_adjudication_audit.{json,md}` is the standalone no-spend audit for the same boundary:
  it confirms label agreement 0.600 < 0.800, the sole failure kind `label_agreement_below_min`, 18
  materialized adjudication rows, and `positive_claim_supported=false`.
- Second-predictor contract validator (`python -m bio_sfm_designer.experiments.complex_predictor_contract`)
  to turn a proposed Chai-1/other complex-predictor JSONL into strict QC and matched cross-predictor commands
  before claiming independent validation; blocked contracts emit blocker comments, `--emit-sync-back-plan`
  can turn missing secondary-record JSONLs into an `rsync` pull script, emitted cross-predictor commands pin
  positive `--min-overlap`, valid `--min-label-agreement`, `--copy-tolerance`, `--copy-fraction-threshold`,
  `--label-threshold-tolerance`, and `--require-disjoint-record-files`, primary/secondary record paths are
  required to be disjoint, and downstream commands stay commented until the contract validates.
- M6c scale-up runbook (`docs/M6C_RUNBOOK.md`) plus manifest-driven source PDB fetch/prep,
  deterministic target FASTA extraction, one-time Boltz target-MSA precompute, target FASTA/MSA
  report checks, and target-MSA sequence checks during manifest preflight and before Boltz complex
  inference. Under `--require-files`, a target FASTA needs its declared report or default
  `<target_fasta>.report.json`; that report must carry `pdb`, `pdb_sha256`, `chain`, `out`,
  `out_sha256`, integer `length`, and `sequence` matching the current prepared PDB/FASTA. A target
  `.a3m` also needs its declared report or default `<target_msa>.report.json`; that report must carry
  `ok=true`, `fasta`, `out`, integer `sequence_length`, `fasta_sha256`, and `out_sha256`. Bare or
  stale-report target FASTA/MSA files are not scale-ready evidence.
- Project roadmap (`docs/PROJECT_ROADMAP.md`) for milestone entry/exit criteria, stop/go decisions,
  and Codex execution cadence.
- Project status auditor (`python -m bio_sfm_designer.experiments.complex_project_status`) to summarize
  W1/W2/W3/W4 roadmap state from posthoc, scale-completion, W1/W2 input-prep-completion,
  panel-completion, panel-report, predictor-contract/cross-predictor/W3-decision-protocol, and batch
  preflight/summary/campaign artifacts, with target-alpha mismatch guards for W1/W2 evidence and no
  runnable W3 commands re-exposed from blocked predictor contracts; unavailable scale-plan sentinels
  surface as `scale_waiting_on_input_prep`, split scale/panel input-prep reports refine W1/W2 to
  blocked-vs-ready manifest rerun states, `--emit-pending-input-prep-paths` writes a de-duplicated
  project-level W1/W2 sync checklist, `--emit-sync-back-plan` turns it into an `rsync` pull script
  whose per-path `rsync` steps and post-sync call are failure-collected so one missing remote prep
  artifact does not block later pulls or replay,
  `--emit-post-sync-plan` writes the ordered completion/readiness/status replay after sync-back, runs each
  replay step in a failure-collecting wrapper so later W1-W4 checks and final status refresh are still
  attempted, then exits nonzero if any replay step failed,
  `pending_external_artifacts` and `--emit-pending-external-paths` combine W1/W2 input-prep blockers,
  W3 second-predictor records, and W4 batch JSONLs into one machine-readable HPC bridge checklist,
  with `pending_external_summary` grouping the same checklist by workstream, category, target, artifact,
  and field before any remote-check report exists, plus `pending_external_followups` translating that
  pre-remote checklist into W1-W4 repair actions,
  `--scale-target-manifest`, `--panel-target-manifest`, and `--emit-target-msa-precompute-plan` write a
  deduplicated W1/W2 target-MSA precompute script so shared targets such as `1BRS_AD` are prepared once
  before the remote-check bridge when their FASTA/MSA/report material matches; conflicting duplicate
  target ids fail closed as a local plan conflict before any submit or receipt write. The generated script
  verifies each raw manifest hash before receipt initialization, then exits before touching its receipt if
  `sbatch` is unavailable, unless `TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH=1` is explicitly set for local diagnostics,
  `--emit-external-remote-check-plan` writes a lightweight `ssh test -s` preflight for that checklist
  so unfinished Cayuga jobs are separated from local sync problems before artifact `rsync`, opportunistically
  syncs the target-MSA precompute receipt back to the local checkout, emits a
  machine-readable remote-check report next to the script with missing-by-workstream/category/target
  metadata, status-derived `remote_missing_followups` that point back to the relevant readiness/workstream
  action, and exposes that report path in
  `generated_scripts`; `--external-remote-check-report` consumes that report and advances the recommended
  bridge to external sync only when the report is fresh for the current pending-path SHA, `ok=true`, its
  `path_manifest` provenance matches the current pending-path manifest, its status, path counters, and
  per-path records prove every current path is present, and any required target-MSA precompute receipt is
  satisfied; fresh all-present reports that lack target-MSA receipt-sync evidence are
  routed back to the remote-check bridge before any re-submit,
  `resume_execution_ladder` orders the generated bridge sequence and marks later steps blocked until the
  current remote-check or sync-back predecessor succeeds,
  `--emit-external-sync-back-plan` writes a unified external pull bridge for that full checklist and
  failure-collects per-path `rsync` steps so one missing remote artifact does not block later pulls or
  post-sync replay; when a remote-check plan is emitted, the external sync bridge also refuses to start
  `rsync` unless the matching remote-check report proves the same pending manifest is all-present and any
  required target-MSA receipt is locally satisfied; W3/W4 direct workstream sync scripts are retained as
  provenance comments in the unified bridge rather than executed twice,
  pending-path sidecar manifests record line counts and SHA-256 hashes so input-prep and external sync
  scripts fail before rsync when their checklists are stale,
  each generated sync step verifies that the local pulled file is non-empty immediately after `rsync`,
  bridge scripts derive the repo root from their own path, route bridge Python snippets through
  `BIO_SFM_PYTHON` when set, and default local pulls to that root unless
  `LOCAL_BIO_SFM_ROOT` or `--sync-local-root` overrides it,
  post-sync replay bootstraps `BIO_SFM_PYTHON` (falling back to `python3`), `PYTHONNOUSERSITE=1`, and local
  `PYTHONPATH` so fresh-shell reruns use the intended interpreter and in-repo modules, and writes/checks a
  post-sync dependency manifest before replay,
  generated bridge scripts are written by atomic replace so post-sync status refreshes can update bridge
  files without truncating a currently running shell script,
  `generated_scripts` and `recommended_next_script` make the next executable bridge explicit in JSON/text
  (currently the deduplicated target-MSA precompute plan first when W1/W2 target MSAs are pending,
  then remote existence preflight, then external sync-back after it passes; a complete
  `target_msa_precompute_receipt` advances resumed sessions past the submit step only when it has exactly
  one accepted row per planned target, no unexpected target rows, a non-empty, whitespace-free `sbatch --parsable` job id
  for each `submitted` row, and FASTA/MSA/report paths plus
  manifest path/hash/workstream provenance matching the current raw manifests, and remote-check reports include
  `target_msa_precompute_receipt_sync` for that handoff, including explicit
  `target_msa_receipt_sync_missing` and `target_msa_receipt_sync_failed` states; an existing non-empty incomplete/invalid receipt
  blocks blind resubmission until it is inspected or explicitly overwritten with
  `TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1` after duplicate-job risk is checked; run
  `TARGET_MSA_PRECOMPUTE_DRY_RUN=1 bash results/m6c_project_target_msa_precompute.sh` before real Cayuga
  submission to validate manifest freshness and print the planned target set plus receipt state without
  touching the receipt, including recorded/missing/duplicate/unexpected target-id preview and strict
	  accepted-status/job-id/provenance validity for any non-empty receipt; the dry-run also previews helper
	  hashes, source FASTA regenerability, and Boltz runtime readiness from `ENV_PY`/`BOLTZ` when new target
	  MSAs are missing; the bridge defaults helper Python to `ENV_PY` before falling back to `python`, and
	  the MSA helper recovers matching `.a3m` output if Boltz fails after MSA generation; target-MSA reports
	  preserve declared `fasta`/`out` paths for sync-back portability and store absolute paths separately;
	  real submit checks every helper file hash still matches the generated bridge, every planned source
	  target FASTA is present or regenerable from prepared/source PDB or `rcsb_id` metadata, and the required
	  Boltz runtime exists before creating/truncating the receipt),
  `operator_preflight_command` exposes the receipt-safe dry-run when available, while
  `operator_next_action`, `operator_next_command`, and `operator_next_role` expose the resume instruction
  separately from the scientific workstream `next_action`,
  with compact manifest summaries (`n_paths`, SHA-256, sidecar/source) attached to sync script entries,
  including the post-sync replay dependency manifest, and `sync_manifest_audit` verifies those summaries still
  match the current pending blockers; failed
  audits mark the recommended sync script as blocked until manifests are regenerated, while
  `resume_bridge_preflight` records whether that recommended bridge exists locally, has any required
  pending-path/manifest files, passes the sync-manifest audit and a non-executing `bash -n` syntax check,
  and is waiting only on local env setup or a Cayuga-session-only submit step before execution;
  `generated_script_syntax_audit` records the same non-executing syntax check across every generated
  bridge script, including later ladder steps that are not recommended yet, and syntax failures appear in
  `goal_progress_audit.local_blockers`; and
  `pending_artifact_local_audit` records whether the
  pending W1-W4 files are already present,
  empty, or missing locally before another sync/replay attempt; the status JSON also carries `self_command`
  and `goal_progress_audit`, which maps the full Codex goal onto W1-W4 requirement states, first action,
  local/external blockers, and an explicit `can_mark_goal_complete` guard that requires each workstream's
  canonical terminal status, parseable non-empty evidence artifact whose content supports that terminal claim,
  W4 preflight/summary/campaign supporting artifacts when closed-loop completion is claimed, and clear
  local/external blocker audit, not just a raw `complete=true`; top-level
  `goal_progress`, `remaining`, `remaining_requirements`, `can_mark_goal_complete`, and
  `goal_completion_note` mirror the compact completion/resume state,
  while `results/m6d_goal_completion_audit.{json,md}` is the standalone no-submit completion-boundary audit:
  it should pass with `audit_ok=true` and `can_mark_goal_complete=false` until W2 target-MSA execution,
  sync-back, and strict replay finish,
	  and `results/m6d_local_cayuga_mirror_audit.{json,md}` is the no-submit local/Cayuga mirror audit:
	  exact SHA checks cover handoff/source artifacts and semantic JSON checks cover path-bearing generated
	  audits, so stale remote artifacts are caught without false-failing on local-vs-Cayuga absolute paths,
	  `results/m6d_goal_drift_audit.{json,md}` is the no-submit goal-boundary drift audit: current status is
	  `no_major_direction_drift_w2_blocked`, `audit_ok=true`, and `major_direction_drift=false`, keeping the
	  next action limited to explicit W2 v9 target-MSA input-prep approval only,
	  so the same dashboard refresh can be replayed exactly,
	  `--predictor-sync-back-plan` preserves the W3 second-predictor sync/rerun script in status and replay artifacts,
  `--batch-sync-back-plan` preserves the W4 missing-batch sync/rerun script in status and replay artifacts,
  post-sync replays W3/W4 from the `self_command` captured in their current report/preflight artifacts
  so W3 can regenerate its contract, command plan, and sync-back plan after a unified pull,
  and those W3/W4 direct sync scripts also validate their own `<script>.manifest.json` sidecars before
  pulling files,
  not-yet-created optional artifact paths become explicit missing statuses instead of
  tracebacks, W2 target-manifest input blockers supersede stale/missing panel-completion artifacts, and
  W4 only completes when strict preflight, summary, and campaign JSONL agree, including campaign row count
  matching the summary routed-candidate count, optional `per_round` counts agreeing with the aggregate,
  non-empty unique campaign `candidate_id` values, and known
  DBTL routing actions whose mix matches summary aggregate action rates, with `assays_used` matching the
  `verify_assay` count and summary `best` matching the highest-quality advancing campaign row when reported; calibrated W4 routing
  requires prior `--prevalidate-records`, so `--conformal-alpha` without prior evidence fails closed,
  and the preflight records a `batch_contract` proving the prior gate evidence and current batch share
  one `predictor_id`, `signal_source`, `label_source`, and `lrmsd_threshold` per routed regime.
- M6c readiness preflight (`python -m bio_sfm_designer.experiments.complex_readiness`) to aggregate
  next-batch, panel-manifest, second-predictor contract, and W4 closed-loop batch checks into one
  reviewable Cayuga/local plan before spending GPU time, with ordered JSON steps for input prep,
  target-MSA precompute, scale/panel submission, posthoc refresh, second-predictor follow-up,
  cross-predictor report generation, strict W4 batch routing, and status refresh; `--batch-sync-back-plan`
  preserves the W4 missing-batch sync/rerun script path in readiness artifacts; `--emit-scale-plan`
  writes the exact next-batch JSON later consumed by
  `complex_scale_completion.py --plan`, or an `ok=false` unavailable sentinel when scale submission is not
  ready yet so stale plans are overwritten. Saving a runnable scale plan through readiness requires
  `--require-files`, with an explicit diagnostic escape hatch for unchecked files; those artifacts are
  marked as diagnostic-only. For W1 single-target scale-up, the input-prep/target-MSA plan is
  scoped to `--scale-target-id` so placeholder panel targets are not submitted by accident, and
  `--require-files` reports missing source/prep/FASTA/MSA/report artifacts as `waiting_on_input_prep` when the
  emitted prep plan can repair them before rerunning readiness; missing source PDBs without `rcsb_id` stay
  hard-blocked because they require a manual file or manifest fix. The readiness JSON/shell artifacts include
  a canonical `self_command` / `# rerun_readiness_after_prep` command to rerun the same effective check
  after target-MSA prep finishes, and `--input-prep-completion` carries target-wise sync-back blockers into
  readiness; project status can take separate `--scale-input-prep-completion` and
  `--panel-input-prep-completion` reports when W1 and W2 are being tracked together.
- Reproducible M6c status generator (`python -m bio_sfm_designer.experiments.m6c_report`) for Markdown/JSON
  headline, science claim ledger, caveats, alpha-frontier, seed-sensitivity, design-regime, and scale-projection artifacts. The
  scale-projection JSON is explicitly `planning_diagnostic` evidence with `certifies_target_alpha=false`;
  it can justify the next Cayuga batch but cannot stop W1. The report includes the same row-level
  `lrmsd_threshold` audit used by the posthoc alpha tools.
- Batch DBTL round consumer (`python -m bio_sfm_designer.experiments.run_batch_round`) now writes a
  `preflight.json` artifact before routing and blocks unsynchronized candidates, prediction records, or
  provided screen verdicts; missing or empty batch/prevalidation JSONLs become structured
  `pending_artifacts` instead of raw loader errors, and `--emit-sync-back-plan` turns them into an
  `rsync` pull script plus rerun command. `--strict-complex-records` requires candidate-side
  `complex_target_id` plus strict
  complex-record QC, and verifies that each candidate's `complex_target_id` agrees with the matching
  prediction record before W4 uses complex/binder evidence in the loop. W4 can also pass prior verified
  `--prevalidate-records` plus `--conformal-alpha` to install the calibrated/RCPS gate before routing;
  prevalidation records that overlap the current batch are blocked as truth leakage, the certified complex
  `tau` is recorded, prevalidation/current-batch predictor-source-label contracts must match by regime,
  and `summary.json` preserves the gate-prevalidation metadata used for status audits.
  The complex ProteinMPNN generator carries `COMPLEX_ID` into candidate metadata and namespaces generated candidate ids.
- Tiered **biosafety screen** (lexicon → bioguard → DeBERTa), fail-closed, human-triage.

**Honest findings** (this is measurement-first tooling — negatives are results):
- The *distinctive* signal — disagreement with a cheap baseline — is **dead on de-novo protein design**
  (ProteinMPNN self-consistency ≈ 0.57, chance); it is validated only in the perturbation regime
  (cited, not claimed here).
- Monomer pLDDT tracks fold *difficulty*: a pooled cross-temperature cross-model AUROC looks strong (0.94)
  but is largely a batch effect. At **fixed difficulty** the within-regime AUROC is only **0.59** (CI
  [0.48, 0.70], not significantly above chance) — monomer pLDDT is a **coarse difficulty filter, not a fine
  per-design trust oracle**.

**In progress:**
- A Boltz output-caching bug (a shared work dir silently reused stale predictions) was found **and fixed**
  2026-06-24 (unique per-output work dir + wipe-on-start); M6a/M6b were re-folded clean and the numbers
  above are post-fix. The find→fix is preserved in git history.
- Complex/binder de-risk **(done — positive)**: barnase–barstar (1BRS), **target MSA + binder single-seq**
  (MSA-free folding fails at interfaces — native complex `msa:empty` → 38 Å, with MSA → 1.0 Å). The interface
  metric **pAE_interaction discriminates** designed-interface success at fixed difficulty (confound-free
  within-temp AUROC **0.93**, n=192) **and even among well-folded binders (0.88, where ipTM is weak ~0.59** and
  foldability is controlled) — so it's a genuine *interface-quality* signal, **unlike monomer pLDDT (chance
  ~0.59)**. (Review caught two wrong metrics first — ipTM, then pLDDT/foldability — before landing on
  pAE_interaction, the metric binder-design actually uses.) **Routing the gate on calibrated pAE (n=192): RCPS
  certifies α=0.3** — trusts 25/64 held-out at **12% false-accept vs 52% held-out trust-all**
  (60% full-set base-rate; most-confident quartile → ~8%). So the complex regime carries the informative, miscalibrated signal the gate is built for, *with a
  distribution-free guarantee*. Caveats: single-model (Boltz-only), one target; tighter α (≤0.2) + more targets
  are the next scale steps. The committed fixture is now schema-current for scale-up: each row carries
  `complex_target_id`, chain ids, predictor/source provenance, and passes strict QC.

## Install & run (stub loop — no GPU/weights/network)

```bash
pip install -e ".[dev]"                  # pulls the pinned public bio-sfm-trust-core release tag
python -m pytest -q
python -m bio_sfm_designer.experiments.dry_run_stub_designer --out results/dry_run
```

The dry-run runs the whole loop on stub generators/predictors, then shows a hazardous
objective being refused at the screen.

## Layout

| Path | Role |
|---|---|
| `loop/` | DBTL controller + planner + interpreter (Claude = orchestrator) |
| `generate/` | Generator protocol + stub + `Precomputed` adapter; real **ProteinMPNN** via `hpc/` |
| `predict/` | Predictor protocol + stub + `Precomputed` adapter; real **ESMFold + Boltz-2** via `hpc/` |
| `trust/` | the external calibrated gate + predictor→evidence adapter |
| `safety/` | screening gate (built-in lexicon now; constitutional-bioguard via `[safety]`) |
| `scoring/` | `net = benefit − λ·assays`, delegated to `bio_sfm_trust` |

## Scope & Safety

This is **defensive, measurement-first** research tooling. The designer operates only on
explicitly allowed targets; objectives are screened before any candidate is generated and
again before any candidate advances. The screen is a **triage aid that produces candidates
for human decision — not an autonomous gate** ("absence of a flag is not a clearance"). It
keys on content/meaning rather than surface tokens, and treats stored annotations,
accessions, and tool names as untrusted input. The stub milestone (M0) generates no real
biological designs. Real generative/predictive SFMs are gated behind these checks and added
only in later milestones. See [`docs/BACKGROUND.md`](docs/BACKGROUND.md) for the dual-use
posture inherited from the FRT and constitutional-bioguard work.

## License

MIT.

[bio-sfm-trust-audit]: https://github.com/jang1563/bio-sfm-trust-audit
