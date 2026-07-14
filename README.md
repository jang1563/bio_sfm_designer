# bio_sfm_designer

> **Continuing this project (new session / Codex)? Start with [HANDOFF.md](HANDOFF.md)** — goal, full
> progress, honest findings, key decisions, and concrete next steps, self-contained.
> For the long project-development plan, use [docs/PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md).
> For long-running Codex goal mode, use [docs/CODEX_GOAL_MODE.md](docs/CODEX_GOAL_MODE.md).
> Before making the repo public, run the no-publish release gate:
> `python -m bio_sfm_designer.experiments.public_release_readiness`.

> **Statistical validity reset (2026-07-10):** historical same-sample RCPS `certified` fields are now
> treated as exploratory. The corrected split learn-then-test reanalysis retains a strong pAE signal
> (AUROC `0.938`) but does **not** certify alpha=0.3. See
> [docs/STATISTICAL_VALIDITY_RESET_2026-07-10.md](docs/STATISTICAL_VALIDITY_RESET_2026-07-10.md).

> **Current W2 result (2026-07-12):** the fresh 11-target representative panel completed on Cayuga
> (22/22 jobs, 1,100/1,100 records). It is target-wise evaluable but not certified at alpha=0.2, with
> success rates from 0% to 100% and defined pAE AUROCs from about 0.24 to 1.00. A post-hoc power audit
> shows that 100 records per target cannot attain the declared Hoeffding/Bonferroni bound: the current
> 33-row certification split has a best-case UCB of 0.2669, while at least 176 total records per target
> are required for zero-error feasibility. This does not recertify the panel. The next W2 protocol must
> be predeclared before more compute. The separate W2b target-adaptive exact-LTT fit stage is now complete:
> eight entirely new targets, 480 H100-generated records, and strict provenance QC failures=0. Five targets
> are fit-eligible. `1F51_AE` freezes the signal-bearing `selective_pae` rule at tau 5.7365 with AUROC
> 0.8421; four targets use `trust_all`, and three refuse. This is fit selection, not certification or W2b
> support. The separately approved five-target certification stage then completed with 300 fresh H100
> records and strict QC failures=0. Four `trust_all` targets certified, but `1F51_AE`, the sole
> `selective_pae` target, failed exact certification: 31 accepts, 6 false accepts, UCB 0.4002. The locked
> panel requires one selective certificate, so W2b v1 is `w2b_certification_terminal_not_supported`.
> Test data cannot change certificates and no test compute was submitted. See
> [docs/M6D_W2B_CERTIFICATION_COMPLETION.md](docs/M6D_W2B_CERTIFICATION_COMPLETION.md).

> **Current W2c result (2026-07-14):** the separately approved `w2c-fit-learn-v1` run completed on
> Cayuga with 8 CPU ProteinMPNN jobs, 8 dependent H100 Boltz jobs, and no retries. All 480 candidate and
> 480 record IDs are unique; strict provenance QC passed 480/480 rows, and all 16 output files have exact
> local-to-Cayuga SHA-256 parity. Under the pre-locked selective-pAE rule, however, all eight targets froze
> to `refuse`: zero threshold candidates remain against the required minimum of three. Some targets retain
> strong pAE ranking AUROC, but none supplies the required >=30-accept region at empirical false-accept
> rate <=0.08; the all-success target has undefined AUROC and cannot count because `trust_all` was excluded
> prospectively. W2c is therefore `w2c_threshold_learning_terminal_not_supported` before independent
> screening. No screen or certification job is approved or submitted. See
> [docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md](docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md) and
> [docs/M6D_W2C_ONE_SHOT_PROTOCOL.md](docs/M6D_W2C_ONE_SHOT_PROTOCOL.md). The next science frontier is a
> distinct W3 predictor-robustness or failure-mechanism experiment, not another W2c rescue iteration.

> **Current W3 result (2026-07-14):** the preregistered 58-case AF2-Multimer mechanism panel completed
> on Cayuga. The first job was cancelled and excluded before adjudication after a wrapper bug reduced
> target-MSA depth to one; the corrected network-isolated full-MSA job completed 58/58 with exit `0:0`.
> Frozen adjudication supports Chai on the 3PC8 challenge (`12/12` discordant labels, `6/6` controls),
> while W2c agreement with Boltz is mixed (`30/40` globally, `5/8` targets at least `4/5`). The joint
> outcome is `context_dependent_or_unresolved`. This supports a bounded predictor/target-dependence
> conclusion, not population-level robustness or W2c rescue. See
> [docs/M6D_W3_MECHANISM_PANEL_COMPLETION.md](docs/M6D_W3_MECHANISM_PANEL_COMPLETION.md),
> [docs/M6D_W3_MECHANISM_PANEL.md](docs/M6D_W3_MECHANISM_PANEL.md), and
> [configs/m6d_w3_mechanism_panel_protocol.json](configs/m6d_w3_mechanism_panel_protocol.json).

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

## Status (2026-07-14)

Past the stub milestone — the loop is closed on CPU and runs on a real, license-clean backend.

**Current local source verified** (`936` designer tests and `53` subtests on 2026-07-14).
The pinned public `bio-sfm-trust-core` v0.1.0 tag remains install-compatible through a tested split-LTT
fallback until the coordinated trust-core release is published:
- DBTL loop closed on CPU (heritable feedback, pluggable acquisition, causal orchestration).
- Real HPC backend: **ProteinMPNN** (design) → **ESMFold** (refold / pLDDT signal) → **Boltz-2**
  (architecturally independent refold = the success label). HPC job → JSONL → local `Precomputed*` adapters.
- **Split learn-then-test risk control**: calibrator/threshold learning and independent Hoeffding
  certification are separated; the current canonical fixture refuses certification and trusts nothing.
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
  The v10 no-spend replacement-target discovery has now advanced locally:
  `results/m6d_w2_target_family_redesign_v10_seed_expansion.{json,md}` selected 160 new RCSB seeds after
  excluding 700 previously screened seeds and the v9 blocked/control sources;
  `results/m6d_w2_target_family_redesign_v10_discovery_pool.{json,md}` screened 1082 chain pairs from
  those seeds, admitted 42 structurally, and selected 16 source-diverse candidates in
  `configs/m6d_w2_target_family_redesign_v10_discovery_targets.json`.
  `results/m6d_w2_target_family_redesign_v10_sequence_diversity.{json,md}` passes with 16 targets,
  15 sequence clusters, and largest cluster fraction 0.125; the representative manifest
  `configs/m6d_w2_target_family_redesign_v10_representative_targets.json` keeps 15 targets after dropping
  the near-duplicate `1DXV_DC`. Pre-MSA manifest validation was 15/15 ready and emitted
  `results/m6d_w2_target_family_redesign_v10_target_msas.sh`. Cayuga target-MSA precompute submitted
  jobs `3073806`-`3073820`; three transient ColabFold/MSA-server fetch failures were repaired with
  jobs `3073822`-`3073824`. The 30 target-MSA/MSA-report files are synced back locally, and
  `results/m6d_w2_target_family_redesign_v10_manifest_post_msa_require_files.json` is now `ok=true`
  with 15/15 ready targets. V10 panel submission then completed on Cayuga: 15 ProteinMPNN/Boltz
  dependency pairs in `results/m6d_w2_target_family_redesign_v10_submit_receipt.json`, with final
  Boltz jobs `3073855`, `3073857`, and `3073859` all `COMPLETED` with exit code `0:0`.
  The synced 15-target readout is now evaluable but not certified:
  `results/m6d_w2_target_family_redesign_v10_panel_completion.json` is `ready_for_panel_report`,
  while `results/m6d_w2_target_family_redesign_v10_panel_report_alpha02.json` is
  `multi_target_evaluable_not_certified` at α=0.2 with 15 targets and 1500 records. The pooled
  diagnostic certifies α=0.2, but pooled-only evidence remains diagnostic; only `1DXU_DC` is
  target-wise certified at α=0.2. The α=0.3 diagnostic
  (`results/m6d_w2_target_family_redesign_v10_panel_report_alpha03.json`) also remains
  `multi_target_evaluable_not_certified`, with `1DXU_DC`, `1E44_BA`, `1EM8_AB`, and `1EMV_BA`
  target-wise certified controls but 11 targets still not certified. The v10 redesign diagnostic
  (`results/m6d_w2_target_family_redesign_v10_redesign_diagnostic_alpha02.{json,md}`) classifies
  five targets (`13IO_HC`, `1DS6_AB`, `1E50_CA`, `1EER_BA`, `1EQZ_AB`) as low-success
  target/protocol mismatches and keeps one-class all-success targets non-certified under the TrustGate
  one-class policy. The next branch is frozen as `w2_target_family_redesign_v11_post_v10_decision` in
  `results/m6d_w2_target_family_redesign_v11_followup_contract.{json,md}` and
  `configs/m6d_w2_target_family_redesign_v11_candidate_rules.json`; Cayuga submission is blocked until
  a no-spend replacement-target discovery or predeclared gate redesign passes the v11 unlock conditions.
  Historical pre-submit trace, superseded by the 2026-07-11 W2 result above: at that stage, the no-spend
  v11 fork had advanced through input preparation but not panel submission:
  `results/m6d_w2_target_family_redesign_v11_seed_expansion.{json,md}` selected 160 new RCSB seeds,
  `results/m6d_w2_target_family_redesign_v11_discovery_pool.{json,md}` screened 2958 chain pairs and
  selected 20 source-diverse candidates, the full 20-target sequence audit was near-duplicate dominated
  (7 clusters, largest fraction 0.4), and
  `configs/m6d_w2_target_family_redesign_v11_representative_targets.json` keeps 7 cluster representatives
  that pass diversity (`results/m6d_w2_target_family_redesign_v11_representative_sequence_diversity.{json,md}`).
  Target-MSA precompute jobs `3073871`-`3073877` completed on Cayuga with exit code `0:0`, local and
  remote `complex_target_manifest --require-files` both pass 7/7, and
  `results/m6d_w2_target_family_redesign_v11_readiness.json` is `ready`. The raw
  `results/m6d_w2_target_family_redesign_v11_submit_panel.sh` now writes records to
  `hpc_outputs/m6d_w2_target_family_redesign_v11_records/...`; the guarded
  `results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh` delegates through the shared
  receipt-preserving wrapper, refuses real execution without
  `BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit`, and passes local plus Cayuga dry-runs in
  `results/m6d_w2_target_family_redesign_v11_panel_preflight.{json,md}`. The reproducible generator is
  `python -m bio_sfm_designer.experiments.m6d_w2_panel_guarded_preflight --run-local-dry-run`; it has
  been run locally and on Cayuga without creating submit receipts. It also emits the no-submit
  `results/m6d_w2_target_family_redesign_v11_approval_runbook.{json,md}`,
  `results/m6d_w2_target_family_redesign_v11_sync_back.sh`, and
  `results/m6d_w2_target_family_redesign_v11_panel_completion.sh` for the approved-run aftermath, plus
  `results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh` to chain the receipt monitor,
  remote job-state query, polling sync-ready gate, sync-back, completion, and post-sync replay after a future
  explicit approval (`M6D_W2_POSTSUBMIT_MAX_POLLS` / `M6D_W2_POSTSUBMIT_POLL_SECONDS` tune waiting). The
  sync-back script now fail-closes before any record `rsync` unless local submit receipt/summary,
  job-state probe output, and strict `m6d_w2_panel_postsubmit_status` with explicit
  `--manifest/--receipt/--summary/--job-states/--require-sync-ready/--out-json` all pass.
  Project status records this as `panel_postsubmit_sync_ready_gate_ok=true` in the current no-submit state.
  The approval packet/runbook also records the full post-submit bridge: receipt-only monitor,
  one-command no-submit postsubmit driver, read-only job-state query, strict postsubmit status command,
  and post-sync replay. The public approval bundle, completion audit, submission-decision state, and
  local/Cayuga mirror audit now also require the exact driver/replay command pair and the tracked
  script-content chain:
  `bash results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh` followed by
  `bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh`; the driver, sync-back,
  completion, and post-sync replay scripts must statically verify as
  `post_approval_workflow.script_chain_static_ok=true`;
  the job-state query script discovers job IDs from the submit receipt at runtime, fail-closes if the
  receipt is absent, and the approval bridge rsyncs the remote job-state probe JSON plus `sacct` TSV back
  locally before postsubmit status. Project status records those invariants as
  `panel_job_state_query_bridge_ok=true` and `panel_postsubmit_bridge_ok=true`.
  The same generator now emits `results/m6d_w2_target_family_redesign_v11_panel_approval_packet.{json,md}`;
  its approval scope binds the future explicit approval to exactly 7 representative targets,
  100 planned ProteinMPNN designs per target, 700 planned design records total, 7
  ProteinMPNN-to-Boltz job pairs, and 14 expected dependent Slurm jobs at target α=0.2.
  `results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.{json,md}` then records
  `post_panel_decision_protocol_ready`, `no_submit=true`, and `can_claim_w2_generalization_now=false`.
  Its post-panel claim boundary is stricter than `multi_target_certified` alone: a W2 generalization claim
  also requires the panel report target set to exactly match the 7-target manifest, duplicate-free target
  rows, matching reported target counts, and target-wise certificates for every target.
  For public handoff/release surfaces, use
  `results/m6d_w2_target_family_redesign_v11_public_approval_bundle.{json,md}` instead of the raw
  environment-specific runbook; regenerate it with
  `python -m bio_sfm_designer.experiments.m6d_w2_v11_public_approval_bundle`. It preserves the explicit
  approval boundary, post-submit command order, and structured post-approval workflow with portable
  placeholders; it also reads the tracked postsubmit driver, sync-back, completion, and post-sync replay
	  scripts and fails closed unless their ordered chain reaches strict postsubmit status, sync-back,
	  completion, target-wise report generation, decision refresh, and post-sync interpretation, while keeping
	  `no_submit=true` and `can_claim_w2_generalization=false`. The public bundle also requires the
	  no-submit pre-submit approval-intent audit command from the submission-decision checklist, so approval
	  text is classified before the guarded submit entrypoint can be used. Tracked result/status artifacts are
  intentionally public-safe and may use `<hpc-login-host>`, `/home/fs01/<user>`, and `<repo-root>`
  placeholders; the executable Cayuga command bridge remains only in ignored local artifacts such as
  `results/m6d_w2_target_family_redesign_v11_approval_runbook.{json,md}` and
  `results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json`. After regenerating tracked
  status/results from private local inputs, run
  `python -m bio_sfm_designer.experiments.public_surface_sanitize --apply` before committing.
  Full project status now consumes those artifacts plus the remote-readiness audit and reports W2 as
  `panel_approval_packet_ready_awaiting_explicit_approval`; its `resume_execution_ladder` now records the
  post-approval order from guarded submit through receipt monitor, job-state query, sync-ready status,
  sync-back, completion, and post-sync interpretation, and carries the non-approval phrase list used by
  goal-mode resumes. The no-submit Cayuga mirror audit
  (`python -m bio_sfm_designer.experiments.m6d_w2_v11_remote_submission_readiness`) reports
  `remote_submission_readiness_ok` after 26 exact SHA checks, 7 semantic JSON checks, 2
  receipt-absence checks, and 10 shell-syntax checks; project status also fail-closes if the stored exact-check local SHA evidence
  no longer matches the current checkout. The final no-submit decision latch
  (`python -m bio_sfm_designer.experiments.m6d_w2_v11_submission_decision_state --check-remote-receipts`)
  writes `results/m6d_w2_target_family_redesign_v11_submission_decision_state.{json,md}` with
  `awaiting_explicit_panel_submission_approval`, `submitted=false`, local/remote receipt absence, and
  `can_claim_w2_generalization=false`; it also requires the completion audit's public approval bundle
  readiness, 9-step post-approval workflow, `script_chain_static_ok=true`, and matching
  7-target/700-design/14-job approval scope
  before the decision can stay approval-ready. Its `operator_approval_checklist` binds the guarded submit
  entrypoint, postsubmit driver, post-sync replay, script-chain static sub-gates, local/remote receipt
  absence, 700 planned designs, 14 expected Slurm jobs, and the explicit approval phrase in one
  operator-facing block. The decision latch now re-consumes the completion audit's operator-checklist and
  operator script-chain verdicts, so a stale or incomplete checklist blocks approval-ready status instead
  of relying only on the raw submission-decision artifact.
  Before any future real submit command, operator text can be fail-closed audited with
  `python -m bio_sfm_designer.experiments.m6d_w2_v11_approval_intent_audit --message-file <approval-message.txt> --require-accepted`;
  that audit only classifies the message and never submits jobs.
  Its approval-disambiguation block records that continuation phrases such as `resume goal`, `go ahead`,
  and `continue` are not approval. The post-submit status gate
  (`python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status`) currently reports
  `not_submitted`; after explicit approval it validates the submit receipt/summary plus optional Slurm job
  states before allowing sync-back. The no-submit receipt monitor
  (`python -m bio_sfm_designer.experiments.m6d_w2_panel_receipt_monitor`) currently records
  `receipt_absent_not_submitted`; after remote receipt creation it emits a receipt-only sync plan before
  any record sync-back. The companion no-submit job-state probe
  (`python -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe`) currently records
  `receipt_absent_not_submitted`; the emitted read-only `sacct` query plan is receipt-driven at runtime,
  writes postsubmit-compatible `states` JSON, and is synced back locally before record sync-back. The
  post-sync interpretation gate
  (`python -m bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation`) currently records
  `not_synced_not_interpretable`, emits the guarded replay path for sync-back -> completion ->
  `complex_panel_report` -> decision-protocol refresh, explicitly revalidates postsubmit status with the
  manifest, submit receipt/summary, and job-state JSON before sync-back, fail-closes on panel-report
  target-set drift, duplicate target rows, or target-count mismatch, and keeps `can_claim_w2_generalization=false`.
  At the time captured by this historical trace, the panel had not yet been submitted.
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
  `goal_completion_note` mirror the compact completion/resume state. The standalone no-submit completion
  audit, `results/m6d_goal_completion_audit.{json,md}`, should pass with `audit_ok=true` and
  `can_mark_goal_complete=false` until the W2 v11 panel is explicitly approved, submitted, synced back,
  completed, and target-wise certified. It now records `panel_public_approval_bundle_ready=true`,
  `panel_public_approval_bundle_workflow_script_chain_static_ok=true`, and
  `panel_submission_decision_operator_script_chain_static_ok=true` when the public-safe v11 approval bundle
  and operator-facing checklist preserve the same no-submit script-chain gate. The no-submit local/Cayuga
  mirror audit, `results/m6d_local_cayuga_mirror_audit.{json,md}`, currently reports
  `local_cayuga_mirror_agree` with 32 exact checks and 16 semantic checks. The no-submit goal-boundary drift
  audit, `results/m6d_goal_drift_audit.{json,md}`, currently reports
  `no_major_direction_drift_w2_blocked`, `audit_ok=true`, `major_direction_drift=false`, and execution
  `panel_postsync_interpretation_predeclared_not_synced`; it also records
  `current_state.W2_panel_submission_decision.operator_checklist_ok=true`,
  `current_state.W2_panel_submission_decision.operator_script_chain_static_ok=true`, and
  `current_state.completion_audit.panel_public_approval_bundle_workflow_script_chain_static_ok=true`, and
  fails closed if either the operator checklist or script-chain gate drifts. The next action remains
  limited to explicit W2 v11 panel approval followed by sync-back, completion, target-wise reporting, and
  refreshed post-sync interpretation,
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
