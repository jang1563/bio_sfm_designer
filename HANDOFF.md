# bio_sfm_designer — Handoff

Self-contained context to continue this project in a fresh session (Codex or otherwise) with **no prior
conversation history**. Read this top to bottom once; it links to the code that matters.

For long-running Codex goal mode, read `docs/CODEX_GOAL_MODE.md` after this handoff and
`docs/PROJECT_ROADMAP.md`.

> One-line status (2026-06-30): the trust-gate thesis is demonstrated **end-to-end on the complex/binder
> regime** — interface confidence (pAE_interaction) discriminates designed-interface success, the gate
> routes on it, and RCPS now has a scoped **t0.3 protocol-branch certificate at α=0.2**. W2 broad-panel
> generalization remains negative; the known W2 pool admitted zero non-anchor pilot targets, and the W2
> fresh-discovery branch has now produced a completed negative unique-source pilot: 3 targets, 300 records,
> `multi_target_evaluable_not_certified` at α=0.2, `trusted=0`, and no τ. The fresh-pilot diagnostic
> classifies all three as target/protocol mismatches with zero transferred low-pAE cutoff accepts, and the
> 12-target known pool still admits zero candidates. The then-next W2 branch was
> `protocol_redesign_plus_success_enriched_discovery_v1`, with candidate rules in
> `configs/m6d_w2_next_branch_candidate_rules.json`. Expanded source-diverse discovery now adds 10
> structurally prepared candidates from 10 unique source PDBs. After the low-concurrency MSA retry and
> sync-back, all 10 target `.a3m`/report files are ready, the combined candidate pool has 25 local inventory
> candidates with 10 admitted for the next W2 branch, and strict preflight passes on
> `configs/m6d_w2_expanded_next_branch_targets.json` with 10/10 ready targets. The expanded panel ran on
> Cayuga through the receipt-preserving wrapper and is now synced back:
> `results/m6d_w2_expanded_next_branch_completion.json` is `ready_for_panel_report` with 10/10 completed
> targets, and `results/m6d_w2_expanded_next_branch_panel_report.json` is
> `multi_target_evaluable_not_certified` at α=0.2 with 10 targets and 1000 records. Boltz job `3056576`
> for `1QFW_BA` failed on a target-MSA/candidate sequence mismatch caused by a terminal atom-only
> residue, but repair job `3056582` completed and generated the synced `1QFW_BA` record. Do not promote
> the pooled diagnostic to W2 evidence: all 10 target-wise certificates are `not_certified`, so W2 still
> needs target replacement/protocol redesign before further scale-up. The redesign diagnostic is
> `results/m6d_w2_expanded_next_branch_redesign_diagnostic.{json,md}`, and the next W2 branch is
> `w2_target_family_redesign_v1` in `results/m6d_w2_expanded_next_branch_next_actions.md`. That branch is
> now materialized as no-spend artifacts: candidate rules admit 0/25 current local inventory targets,
> manifest design is blocked with 0 selected targets, and a filtered 39-seed local source-cache scan
> admitted 0 structural candidates. RCSB seed expansion selected 80 new seeds; local structural discovery
> admitted 132 chain pairs and selected 10 source-diverse targets, but sequence-diversity audit blocks the
> full 10-target panel because 8/10 targets are sequence-identical near duplicates. Only the representative
> subset `10XZ_EF`, `10YB_GH`, and `12NP_AH` moved forward: target-MSA prep completed after a transient
> 10XZ retry, strict preflight passed, and the scoped representative ProteinMPNN/Boltz probe completed with
> receipt capture. `results/m6d_w2_target_family_redesign_v1_rcsb_representative_panel_report.json` is
> `multi_target_evaluable_not_certified` at α=0.2 with 3 targets and 300 records; all three target-wise
> certificates are `not_certified`. The diagnostic recommends replacing/redesigning `12NP_AH` before more W2
> panel GPU and predeclaring a low-pAE acceptance/calibration strategy before scaling `10XZ_EF` or `10YB_GH`.
> `w2_target_family_redesign_v2` carries those constraints into a stricter no-spend rule set and rescreens
> the current local inventory: `results/m6d_w2_target_family_redesign_v2_candidate_pool.json` admits 0/25
> candidates, keeps `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` source-redundancy audit-only, and is not ready for a
> revised manifest or Cayuga submission. The follow-on `w2_target_family_redesign_v2_rcsb` branch now
> expands beyond those excluded sources: saved-response RCSB seed expansion selected 80 seeds, structural
> intake screened 423 chain pairs and selected 20 source-unique targets, sequence-diversity audit passes
> with 12 clusters and largest-cluster fraction 0.25, and Cayuga target-MSA precompute is complete after an
> 11-target low-concurrency retry. Post-sync strict preflight passes 20/20, and
> `results/m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh` passed local and Cayuga dry-runs,
> then submitted 20 receipt-validated ProteinMPNN/Boltz job pairs on Cayuga (`3056715`-`3056754`) with
> records isolated under `hpc_outputs/m6d_w2_target_family_redesign_v2_rcsb_records`. The records are now
> synced back and completed: `results/m6d_w2_target_family_redesign_v2_rcsb_panel_report.json` is
> `multi_target_evaluable_not_certified` at alpha=0.2 with 20 targets and 2000 records. Only `1A3O_BA` and
> `1A9W_EA` certify target-wise; the other 18 targets do not. The pooled diagnostic certifies tau=1.0, but
> pooled-only evidence is not W2 generalization. The follow-on no-spend branch was
> `w2_target_family_redesign_v3`: it preserves those two target-specific positives as controls, selected 80
> new RCSB seeds, screened 753 chain pairs, selected 8 source-diverse and sequence-diverse candidates, and
> submitted target-MSA precompute jobs `3057081`-`3057088` on Cayuga. Six targets are ready remotely; `1AOI_HB`
> and `1AVO_DC` hit the known ColabFold MSA-server invalid tar/gzip response and were resubmitted as
> low-concurrency retry jobs `3057090` and `3057091`; retry recovered 8/8 target MSAs. Strict post-MSA
> preflight passes 8/8, and the v3 panel was submitted on Cayuga through
> `results/m6d_w2_target_family_redesign_v3_submit_with_receipt.sh`: ProteinMPNN/Boltz job pairs are
> `3057094`-`3057109`, with records isolated under `hpc_outputs/m6d_w2_target_family_redesign_v3_records`.
> Those records are synced back and completed. The v3 target-wise panel report
> `results/m6d_w2_target_family_redesign_v3_panel_report.json` is
> `multi_target_evaluable_not_certified` at alpha=0.2 with 8 targets and 800 records. All eight target-wise
> certificates are `not_certified`. The pooled diagnostic certifies tau=0.75, but pooled-only evidence is not
> W2 generalization. The v3 diagnostic recommends replacing or redesigning low-success targets `1AOI_HB` and
> `1APY_CD` before more panel GPU.
> The follow-on v4 branch is now completed negative/evaluable: its 5-target representative panel produced
> 500 records and `results/m6d_w2_target_family_redesign_v4_panel_report.json` is
> `multi_target_evaluable_not_certified` at alpha=0.2. `1AY7_AB` and `1B27_CF` are target-specific certified
> controls, but `1AYY_BA`, `1AZZ_DC`, and `1B2S_BE` are not certified, so v4 is not W2 generalization.
> The v5 branch froze stricter rules, admitted 13 source-diverse next-branch targets after MSA input-prep,
> emitted `configs/m6d_w2_target_family_redesign_v5_targets.json`, passed strict pre-submit preflight 13/13,
> and completed receipt-validated ProteinMPNN/Boltz job pairs `3057168`-`3057193` through
> `results/m6d_w2_target_family_redesign_v5_submit_with_receipt.sh`. The synced v5 panel is fully evaluable
> but negative for W2: `results/m6d_w2_target_family_redesign_v5_panel_report.json` has 13 targets, 1300
> records, and 0/13 target-wise certificates at alpha=0.2. The diagnostic is
> `results/m6d_w2_target_family_redesign_v5_redesign_diagnostic.{json,md}` and recommends redesigning or
> replacing low-success targets before more W2 panel GPU. The follow-on no-spend gate strategy is now
> `results/m6d_w2_target_family_redesign_v5_gate_strategy.{json,md}`: `1BFV_HL` and `1BQH_KI` need an
> explicit label-degeneracy policy before they can be used as gate evidence; `1B2U_CF`, `1B86_DC`, and
> `1BCP_KL` need a low-pAE acceptance strategy; `1B3S_CF` needs target-specific calibration; `1BGS_BF` is
> split-sensitive; and `1BE3_EJ`, `1BGY_EJ`, `1BHH_AB`, `1BMQ_AB`, `1BQL_LY`, and `1BQQ_TM` need target
> replacement or generation/evaluation redesign. The v6 rules in
> `configs/m6d_w2_target_family_redesign_v6_candidate_rules.json` link those preconditions and keep Cayuga
> submission blocked. The current v6 no-spend inventory screen
> `results/m6d_w2_target_family_redesign_v6_candidate_pool.{json,md}` admits 0/25 candidates, with
> `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` audit-only; no revised W2 manifest exists. The blocker policy is
> now resolved fail-closed in `results/m6d_w2_target_family_redesign_v6_gate_strategy_resolution.{json,md}`
> and `configs/m6d_w2_target_family_redesign_v7_protocol.json`: keep label-degenerate all-success targets
> as positive controls only, forbid fixed low-pAE cutoff transfer as a certificate, and continue as
> `w2_target_family_redesign_v7_calibratable_discovery` only after discovery admits at least three
> non-anchor source-diverse targets. V7 has now opened a pre-MSA input-prep branch: seed expansion selected
> 80 new RCSB sources from 5000 response IDs; local structural intake screened 566 chain pairs, admitted 30,
> and selected 13 source-diverse candidates. The full 13-target manifest is sequence-diversity blocked
> (`largest_cluster_fraction=0.307692`), but the representative 10-target subset passes diversity with 10
> clusters and `results/m6d_w2_target_family_redesign_v7_representative_manifest_pre_msa.json` is 10/10 ready.
> Target-MSA input prep completed 10/10 after retry jobs `3057265` and `3057266`, strict post-MSA
> preflight passes 10/10, and the v7 representative panel completed on Cayuga through
> `results/m6d_w2_target_family_redesign_v7_submit_with_receipt.sh`: ProteinMPNN/Boltz job pairs were
> `3057268`-`3057287`, with receipt
> `results/m6d_w2_target_family_redesign_v7_submit_receipt.jsonl`. Records are synced back and
> `results/m6d_w2_target_family_redesign_v7_completion.json` is `ready_for_panel_report` with 10/10
> completed targets. The target-wise panel report
> `results/m6d_w2_target_family_redesign_v7_panel_report.json` is
> `multi_target_evaluable_not_certified` at alpha=0.2 with 10 targets, 1000 records, and 0/10
> target-wise certificates. The diagnostic
> `results/m6d_w2_target_family_redesign_v7_redesign_diagnostic.{json,md}` recommends
> `redesign_or_replace_low_success_targets`: `1BUV_TM`, `1BZQ_BN`, and `1C5F_CE` are target/protocol
> mismatch candidates, while the other seven targets remain low-pAE-acceptance holds. This is a completed
> negative/evaluable science result, not W2 evidence; do not spend more W2 panel GPU until target
> replacement or generation/gate redesign is predeclared. The next no-spend branch is now frozen as
> `w2_target_family_redesign_v8_success_enriched_gate_redesign` in
> `results/m6d_w2_target_family_redesign_v8_followup_contract.{json,md}` and
> `configs/m6d_w2_target_family_redesign_v8_candidate_rules.json`: Cayuga submission remains `false`,
> all 10 v7 target/source IDs are excluded under the current protocol, and unlock requires at least three
> non-anchor targets plus sequence-diversity/preflight and predeclared low-pAE or target-specific calibration.
> The v8 no-spend screen has now produced an input-prep-ready branch: RCSB seed expansion selected
> 100 seeds from 8000 response IDs; local structural intake screened 641 chain pairs, admitted 29
> structurally, and selected 12 source-diverse candidates; sequence diversity passes with 12 targets,
> 8 clusters, and largest-cluster fraction 0.25; and
> `results/m6d_w2_target_family_redesign_v8_manifest_pre_msa.json` is `ok=true` with 12/12 ready targets.
> Target-MSA input prep then completed on Cayuga: initial jobs `3057296`-`3057307` produced 7/12 stable
> MSAs and hit the known transient ColabFold/MMseqs truncated-tar failure on five targets; the serial retry
> bridge `results/m6d_w2_target_family_redesign_v8_target_msa_retry_serial.sh` submitted retry jobs
> `3057334`-`3057338` and recovered all five. After sync-back,
> `results/m6d_w2_target_family_redesign_v8_input_prep_completion_post_sync.json` is `ok=true` with
> 84/84 nonempty artifacts, and
> `results/m6d_w2_target_family_redesign_v8_manifest_post_msa_require_files.json` passes strict
> post-MSA `--require-files` with 12/12 ready targets and zero failures. The separate v8 panel artifacts
> are now generated: `results/m6d_w2_target_family_redesign_v8_submit_ready.json`,
> `results/m6d_w2_target_family_redesign_v8_submit_plan.sh`,
> `results/m6d_w2_target_family_redesign_v8_submit_with_receipt.sh`,
> `results/m6d_w2_target_family_redesign_v8_completion.sh`, and
> `results/m6d_w2_target_family_redesign_v8_sync_back.sh`. Local and Cayuga dry-runs passed, then the
> receipt wrapper submitted 12 ProteinMPNN/Boltz job pairs (`3057340`-`3057363`) and wrote
> `results/m6d_w2_target_family_redesign_v8_submit_receipt_summary.json`. The records are now synced back:
> `results/m6d_w2_target_family_redesign_v8_completion.json` is `ready_for_panel_report` with 12/12
> completed targets, and `results/m6d_w2_target_family_redesign_v8_panel_report.json` is
> `multi_target_evaluable_not_certified` at α=0.2 with 12 targets and 1200 records. Only `1CG5_AB` and
> `1COH_BA` are target-specific certified controls; the other 10 targets are not certified. The pooled
> diagnostic certifies α=0.2, but pooled-only evidence is not W2 generalization. Use
> `results/m6d_w2_target_family_redesign_v8_redesign_diagnostic.{json,md}` before any more W2 panel GPU.
> The follow-up branch is now frozen as
> `w2_target_family_redesign_v9_positive_controls_plus_calibration_redesign` in
> `results/m6d_w2_target_family_redesign_v9_followup_contract.{json,md}` and
> `configs/m6d_w2_target_family_redesign_v9_candidate_rules.json`: Cayuga submission is `false`; `1CG5_AB`
> and `1COH_BA` are retained only as target-specific positive controls; the 10 non-certified v8 targets are
> excluded under the current protocol. Next action is a no-spend replacement-target discovery or gate-redesign
> screen, not more W2 ProteinMPNN/Boltz panel jobs.
> That no-spend v9 replacement-target screen now passes the first local gates:
> `results/m6d_w2_target_family_redesign_v9_seed_expansion.{json,md}` selected 120 new RCSB seeds from
> 10,000 response IDs, `results/m6d_w2_target_family_redesign_v9_discovery_pool.{json,md}` screened
> 988 chain pairs and selected 14 source-diverse targets, and
> `results/m6d_w2_target_family_redesign_v9_sequence_diversity.{json,md}` passes with 14 sequence clusters.
> `results/m6d_w2_target_family_redesign_v9_manifest_pre_msa.json` is `ok=true` with 14/14 ready targets,
> and `results/m6d_w2_target_family_redesign_v9_target_msa_with_receipt.sh` dry-runs cleanly. Strict
> post-MSA `--require-files` intentionally fails on 28 missing target-MSA/MSA-report files, so the only
> open Cayuga action is target-MSA input prep; W2 panel submission is still blocked.
> `results/m6d_w2_target_family_redesign_v9_target_msa_presubmit_preflight.{json,md}` records the Cayuga
> presubmit readback: runtime/helper files are present, dry-run passes, and all 14 source/prepared/FASTA
> inputs are synced. Real target-MSA submission still requires explicit approval, and the wrapper refuses to
> touch the receipt unless `BIO_SFM_APPROVE_V9_TARGET_MSA=approve-v9-target-msa-precompute` is present.
> The postsubmit replay path is also ready:
> `results/m6d_w2_target_family_redesign_v9_pending_input_prep_paths.txt` lists the 28 expected MSA/report
> outputs, `results/m6d_w2_target_family_redesign_v9_msa_sync_back.sh` pulls them plus the receipt/summary
> after jobs finish, and `results/m6d_w2_target_family_redesign_v9_postsubmit_replay_plan.{json,md}`
> records the same approval-env-gated submit command plus the replay boundary.
> `results/m6d_w2_target_family_redesign_v9_target_msa_gate_audit.{json,md}`
> verifies that this expected-blocked state is coherent: 14 targets, 28 pending target-MSA/MSA-report
> paths, 70/98 input-prep artifacts present, `audit_ok=true`, and panel submission still `false`.
> `results/m6c_project_status_w2_followup.json` now takes that gate audit as the current W2 branch state
> (`target_msa_gate_ready_awaiting_explicit_approval`), leaving older negative panel reports as superseded
> evidence instead of the resume point.
> `results/m6d_w2_target_family_redesign_v9_approval_packet.{json,md}` is the no-submit approval packet:
> it checks project status, the gate audit, representative manifest, 28-path pending list, target-MSA
> wrapper, and sync-back replay script agree. It records the exact target-MSA command plus approval env guard
> for a later explicit approval, but still authorizes no ProteinMPNN/Boltz panel work.
> `results/m6d_w2_target_family_redesign_v9_wrapper_guard_audit.{json,md}` is the guard proof for that
> boundary: static audit passes, a no-env wrapper run exits before receipt initialization, and the v9
> target-MSA receipt remains absent on both local and Cayuga.
> `results/m6d_w2_explicit_approval_runbook.{json,md}` is the operator-facing no-submit runbook for a
> later explicit approval: it records the target-MSA-only command order and keeps panel submission blocked
> until sync-back plus strict replay pass.
> `results/m6c_project_status_w2_followup.json` now consumes that packet through `--w2-approval-packet`,
> preserving `approval_packet_ready=true` and `can_submit_proteinmpnn_boltz_panel=false` in the W2 status.
> `results/m6d_w2_target_family_redesign_v9_approval_parity.{json,md}` compares the local and Cayuga
> approval packets and reports `parity_ok=true`; this is a no-submit agreement check and does not create a
> target-MSA receipt. `results/m6c_project_status_w2_followup.json` consumes it through
> `--w2-approval-parity`, preserving `approval_parity_ok=true` in W2 status.
> The guarded v9 ProteinMPNN/Boltz panel was then explicitly submitted on Cayuga, completed, synced back,
> and replayed locally: `results/m6d_w2_target_family_redesign_v9_completion.json` is
> `ready_for_panel_report` with 14/14 completed targets, while
> `results/m6d_w2_target_family_redesign_v9_panel_report.json` is
> `multi_target_evaluable_not_certified` at α=0.2 with 14 targets and 1400 records. The pooled diagnostic
> certifies α=0.2, but pooled-only evidence remains diagnostic; only `1DLF_HL` is target-wise certified
> (`τ=0.333`), and the other 13 targets are not certified. The post-panel diagnostic/strategy artifacts
> `results/m6d_w2_target_family_redesign_v9_redesign_diagnostic.{json,md}` and
> `results/m6d_w2_target_family_redesign_v9_gate_strategy.{json,md}` classify seven low-success
> target/protocol mismatches, five all-success label-degenerate controls, `1D2Z_BA` as a loose-α anchor
> rather than an α=0.2 certificate, and `1DLF_HL` as the single certified control. The next branch is frozen
> as `w2_target_family_redesign_v10_post_v9_decision` in
> `results/m6d_w2_target_family_redesign_v10_followup_contract.{json,md}` and
> `configs/m6d_w2_target_family_redesign_v10_candidate_rules.json`; Cayuga submission is `false` until a
> no-spend replacement-target discovery or predeclared target/family calibration redesign passes its gates.
> The v10 no-spend replacement-target discovery has now advanced locally:
> `results/m6d_w2_target_family_redesign_v10_seed_expansion.{json,md}` selected 160 new RCSB seeds after
> excluding 700 previously screened seeds and the v9 blocked/control sources;
> `results/m6d_w2_target_family_redesign_v10_discovery_pool.{json,md}` screened 1082 chain pairs from
> those seeds, admitted 42 structurally, and selected 16 source-diverse candidates in
> `configs/m6d_w2_target_family_redesign_v10_discovery_targets.json`.
> `results/m6d_w2_target_family_redesign_v10_sequence_diversity.{json,md}` passes with 16 targets,
> 15 sequence clusters, and largest cluster fraction 0.125; the representative manifest
> `configs/m6d_w2_target_family_redesign_v10_representative_targets.json` keeps 15 targets after dropping
> the near-duplicate `1DXV_DC`. Pre-MSA manifest validation was 15/15 ready and emitted
> `results/m6d_w2_target_family_redesign_v10_target_msas.sh`. Cayuga target-MSA precompute submitted
> jobs `3073806`-`3073820`; three transient ColabFold/MSA-server fetch failures were repaired with
> jobs `3073822`-`3073824`. The 30 target-MSA/MSA-report files are synced back locally, and
> `results/m6d_w2_target_family_redesign_v10_manifest_post_msa_require_files.json` is now `ok=true`
> with 15/15 ready targets. V10 panel submission then completed on Cayuga: 15 ProteinMPNN/Boltz
> dependency pairs in `results/m6d_w2_target_family_redesign_v10_submit_receipt.json`, with final
> Boltz jobs `3073855`, `3073857`, and `3073859` all `COMPLETED` with exit code `0:0`.
> The synced 15-target readout is now evaluable but not certified:
> `results/m6d_w2_target_family_redesign_v10_panel_completion.json` is `ready_for_panel_report`,
> while `results/m6d_w2_target_family_redesign_v10_panel_report_alpha02.json` is
> `multi_target_evaluable_not_certified` at α=0.2 with 15 targets and 1500 records. The pooled
> diagnostic certifies α=0.2, but pooled-only evidence remains diagnostic; only `1DXU_DC` is
> target-wise certified at α=0.2. The α=0.3 diagnostic
> (`results/m6d_w2_target_family_redesign_v10_panel_report_alpha03.json`) also remains
> `multi_target_evaluable_not_certified`, with `1DXU_DC`, `1E44_BA`, `1EM8_AB`, and `1EMV_BA`
> target-wise certified controls but 11 targets still not certified. The v10 redesign diagnostic
> (`results/m6d_w2_target_family_redesign_v10_redesign_diagnostic_alpha02.{json,md}`) classifies
> five targets (`13IO_HC`, `1DS6_AB`, `1E50_CA`, `1EER_BA`, `1EQZ_AB`) as low-success
> target/protocol mismatches and keeps one-class all-success targets non-certified under the TrustGate
> one-class policy. The next branch is frozen as `w2_target_family_redesign_v11_post_v10_decision` in
> `results/m6d_w2_target_family_redesign_v11_followup_contract.{json,md}` and
> `configs/m6d_w2_target_family_redesign_v11_candidate_rules.json`; Cayuga submission is blocked until
> a no-spend replacement-target discovery or predeclared gate redesign passes the v11 unlock conditions.
> That no-spend v11 fork has now advanced through input preparation but not panel submission:
> `results/m6d_w2_target_family_redesign_v11_seed_expansion.{json,md}` selected 160 new RCSB seeds,
> `results/m6d_w2_target_family_redesign_v11_discovery_pool.{json,md}` screened 2958 chain pairs and
> selected 20 source-diverse candidates, the full 20-target sequence audit was near-duplicate dominated
> (7 clusters, largest fraction 0.4), and
> `configs/m6d_w2_target_family_redesign_v11_representative_targets.json` keeps 7 cluster representatives
> that pass diversity (`results/m6d_w2_target_family_redesign_v11_representative_sequence_diversity.{json,md}`).
> Target-MSA precompute jobs `3073871`-`3073877` completed on Cayuga with exit code `0:0`, local and
> remote `complex_target_manifest --require-files` both pass 7/7, and
> `results/m6d_w2_target_family_redesign_v11_readiness.json` is `ready`. The raw
> `results/m6d_w2_target_family_redesign_v11_submit_panel.sh` now writes records to
> `hpc_outputs/m6d_w2_target_family_redesign_v11_records/...`; the guarded
> `results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh` delegates through the shared
> receipt-preserving wrapper, refuses real execution without
> `BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit`, and passes local plus Cayuga dry-runs in
> `results/m6d_w2_target_family_redesign_v11_panel_preflight.{json,md}`. The reproducible generator is
> `python -m bio_sfm_designer.experiments.m6d_w2_panel_guarded_preflight --run-local-dry-run`; it has
> been run locally and on Cayuga without creating submit receipts. It also emits the no-submit
> `results/m6d_w2_target_family_redesign_v11_approval_runbook.{json,md}`,
> `results/m6d_w2_target_family_redesign_v11_sync_back.sh`, and
> `results/m6d_w2_target_family_redesign_v11_panel_completion.sh` for the approved-run aftermath, plus
> `results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh` to chain the receipt monitor,
> remote job-state query, polling sync-ready gate, sync-back, completion, and post-sync replay after a future
> explicit approval (`M6D_W2_POSTSUBMIT_MAX_POLLS` / `M6D_W2_POSTSUBMIT_POLL_SECONDS` tune waiting). The
> sync-back script now fail-closes before any record `rsync` unless local submit receipt/summary,
> job-state probe output, and strict `m6d_w2_panel_postsubmit_status` with explicit
> `--manifest/--receipt/--summary/--job-states/--require-sync-ready/--out-json` all pass.
> Project status records this as `panel_postsubmit_sync_ready_gate_ok=true` in the current no-submit state.
> The approval packet/runbook also records the full post-submit bridge: receipt-only monitor,
> one-command no-submit postsubmit driver, read-only job-state query, strict postsubmit status command,
> and post-sync replay. The public approval bundle, completion audit, submission-decision state, and
> local/Cayuga mirror audit now also require the exact driver/replay command pair and tracked
> script-content chain:
> `bash results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh` followed by
> `bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh`; the driver, sync-back,
> completion, and post-sync replay scripts must statically verify as
> `post_approval_workflow.script_chain_static_ok=true`;
> the job-state query script discovers job IDs from the submit receipt at runtime, fail-closes if the
> receipt is absent, and the approval bridge rsyncs the remote job-state probe JSON plus `sacct` TSV back
> locally before postsubmit status. Project status records those invariants as
> `panel_job_state_query_bridge_ok=true` and `panel_postsubmit_bridge_ok=true`.
> The same generator now emits `results/m6d_w2_target_family_redesign_v11_panel_approval_packet.{json,md}`;
> `results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.{json,md}` then records
> `post_panel_decision_protocol_ready`, `no_submit=true`, and `can_claim_w2_generalization_now=false`.
> For public handoff/release surfaces, use
> `results/m6d_w2_target_family_redesign_v11_public_approval_bundle.{json,md}` instead of the raw
> environment-specific runbook; regenerate it with
> `python -m bio_sfm_designer.experiments.m6d_w2_v11_public_approval_bundle`. It preserves the explicit
> approval boundary and post-submit command order with portable placeholders, and it now reads the
> tracked postsubmit driver, sync-back, completion, and post-sync replay scripts; the bundle fails closed
> unless that ordered chain reaches strict postsubmit status, sync-back, completion, target-wise report
> generation, decision refresh, and post-sync interpretation, while keeping `no_submit=true` and
> `can_claim_w2_generalization=false`.
> Full project status now consumes those artifacts plus the remote-readiness audit and reports W2 as
> `panel_approval_packet_ready_awaiting_explicit_approval`; its `resume_execution_ladder` now records the
> post-approval order from guarded submit through receipt monitor, job-state query, sync-ready status,
> sync-back, completion, and post-sync interpretation, and carries the non-approval phrase list used by
> goal-mode resumes. The no-submit Cayuga mirror audit
> (`python -m bio_sfm_designer.experiments.m6d_w2_v11_remote_submission_readiness`) reports
> `remote_submission_readiness_ok` after 25 exact SHA checks, 5 semantic JSON checks, 2
> receipt-absence checks, and 10 shell syntax checks; project status also fail-closes if the stored exact-check local SHA evidence
> no longer matches the current checkout. The final no-submit decision latch
> (`python -m bio_sfm_designer.experiments.m6d_w2_v11_submission_decision_state --check-remote-receipts`)
> writes `results/m6d_w2_target_family_redesign_v11_submission_decision_state.{json,md}` with
> `awaiting_explicit_panel_submission_approval`, `submitted=false`, local/remote receipt absence, and
> `can_claim_w2_generalization=false`; it also requires the completion audit's public approval bundle
> readiness, 9-step post-approval workflow, `script_chain_static_ok=true`, and the 7-target/700-design/14-job
> approval scope before the decision can stay approval-ready. Its `operator_approval_checklist` binds the guarded
> submit entrypoint, postsubmit driver, post-sync replay, local/remote receipt absence, 700 planned designs,
> 14 expected Slurm jobs, and the explicit approval phrase in one operator-facing block. The decision latch
> re-consumes the completion audit's operator-checklist verdict, so a stale or incomplete checklist blocks
> approval-ready status instead of relying only on the raw submission-decision artifact. Tracked result/status artifacts are public-safe and
> use placeholders for host, user, and repo-root values; the executable Cayuga command bridge remains only
> in ignored local artifacts such as `results/m6d_w2_target_family_redesign_v11_approval_runbook.{json,md}`
> and `results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json`. After regenerating tracked
> status/results from private local inputs, run
> `python -m bio_sfm_designer.experiments.public_surface_sanitize --apply` before committing. Its approval-disambiguation block records that continuation phrases
> such as `resume goal`, `go ahead`, and `continue` are not approval. The post-submit status gate
> (`python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status`) currently reports
> `not_submitted`; after explicit approval it validates the submit receipt/summary plus optional Slurm job
> states before allowing sync-back. The no-submit receipt monitor
> (`python -m bio_sfm_designer.experiments.m6d_w2_panel_receipt_monitor`) currently records
> `receipt_absent_not_submitted`; after remote receipt creation it emits a receipt-only sync plan before
> any record sync-back. The companion no-submit job-state probe
> (`python -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe`) currently records
> `receipt_absent_not_submitted`; the emitted read-only `sacct` query plan is receipt-driven at runtime,
> writes postsubmit-compatible `states` JSON, and is synced back locally before record sync-back. The
> post-sync interpretation gate
> (`python -m bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation`) currently records
> `not_synced_not_interpretable`, emits the guarded replay path for sync-back -> completion ->
> `complex_panel_report` -> decision-protocol refresh, explicitly revalidates postsubmit status with the
> manifest, submit receipt/summary, and job-state JSON before sync-back, and keeps
> `can_claim_w2_generalization=false`.
> The panel has not been submitted.
> A separate source-redundancy audit plan exists, but it does not authorize Cayuga submission or W2
> generalization.
> W3 no-MSA Chai scale-up is now a
> negative robustness result: QC/contract pass, but Boltz-vs-Chai label agreement is 0.600 < 0.800. W4 has a
> strict closed-loop DBTL campaign that completed **fail-closed/all-defer**, not as productive build routing.
> `results/m6d_w3_adjudication_audit.{json,md}` now gives the W3 boundary as a standalone no-spend audit:
> 18 adjudication rows, sha/count/role/membership checks passing, and `positive_claim_supported=false`.
> The current goal-mode anchor is `docs/M6D_GOAL_MODE_ANCHOR.md`.

---

## 1. What this project is (goal + thesis)

A **calibrated, cost-aware, safety-screened Design–Build–Test–Learn (DBTL) designer** for proteins.
Claude is the **orchestrator** (not an oracle) over specialist scientific foundation models (SFMs —
ProteinMPNN, ESMFold, Boltz-2). The intellectual core is an **external, engineered trust gate** that
decides, per candidate,

```
trust_sfm | verify_assay | default_baseline | defer      scored by  net = benefit − λ·assays
```

plus a second gate, a **biosafety screen**, before propose and before synth.

**Why the gate is external/engineered (the founding result, from the sibling `bio-sfm-trust-audit`):** an
LLM placed above specialist models allocates verification at ≈ chance, stronger models over-verify, and
trust tracks name-familiarity. So trust is **not delegated to the orchestrator** — it is keyed on a
**calibrated scalar risk**, with three hard constraints baked into `trust/gate.py`:
1. the gate is external — never "ask the LLM if it's confident";
2. the competence signal is **disagreement with a cheap baseline** where one exists (Bayes-optimal
   deferral); where none exists, `trust_sfm` is **restricted to calibration-validated regimes**;
3. confidence is consumed only as a **scalar calibrated risk**, never a raw latent.

**Goal of the current phase:** prove the thesis *dynamically on real protein data* — turn "the gate helps"
from assumed into measured — and harden it with conformal (distribution-free) risk control.

## 2. Repos, setup, how to run

Two local git repos (both pushed to **public** GitHub under `jang1563`):

| repo | path | GitHub | role |
|---|---|---|---|
| `bio-sfm-trust-core` | `…/Claude/bio-sfm-trust-core` | `jang1563/bio-sfm-trust-core` | **engine** (pure stdlib): TrustGate calibration, isotonic, RCPS conformal, metrics |
| `bio_sfm_designer` | `…/Claude/bio_sfm_designer` | `jang1563/bio_sfm_designer` | **application**: DBTL loop, ProteinMPNN/ESMFold/Boltz HPC bridges, biosafety screen |

Dependency is one-way: `designer → trust-core`. (There is also a third sibling, `bio-sfm-trust-audit`,
the measurement project the engine was extracted from — referenced, not required here.)

```bash
# fresh venv (NOTE: /tmp is ephemeral — recreate when gone; needs modern pip for PEP 660 editable installs)
python3 -m venv /tmp/bio_sfm_venv && /tmp/bio_sfm_venv/bin/pip install -U pip
/tmp/bio_sfm_venv/bin/pip install -e ".[dev]"                         # includes pytest + numpy for CI parity
/tmp/bio_sfm_venv/bin/python -m pytest -q                             # public clone smoke: 118 passed, 4 skipped
```

For local engine development, override the pinned public dependency with the sibling checkout,
then run both suites:

```bash
/tmp/bio_sfm_venv/bin/pip install -e ../bio-sfm-trust-core -e ".[dev]"
/tmp/bio_sfm_venv/bin/python -m pytest -q
/tmp/bio_sfm_venv/bin/python -m unittest discover -s ../bio-sfm-trust-core/tests
```

The honest results live in committed experiments + fixtures (no GPU needed to re-run the analyses):

```bash
python -m bio_sfm_designer.experiments.within_regime_signal      # monomer: signal is CHANCE at fixed difficulty
python -m bio_sfm_designer.experiments.cross_model_auroc         # monomer: cross-model AUROC + the temp confound
python -m bio_sfm_designer.experiments.complex_interface_signal  # complex: pAE_interaction discriminates (the win)
python -m bio_sfm_designer.experiments.conformal_complex_gate    # complex: RCPS certifies α=0.3, gate vs trust-all
python -m bio_sfm_designer.experiments.complex_records_qc --records tests/fixtures/barstar_interface_records.jsonl --require-complex-target-id --require-provenance --require-chain-ids
python -m bio_sfm_designer.experiments.complex_gate_sweep --records tests/fixtures/barstar_interface_records.jsonl --alphas 0.3,0.2,0.1
python -m bio_sfm_designer.experiments.complex_alpha_plan --records tests/fixtures/barstar_interface_records.jsonl --alphas 0.3,0.2,0.1
python -m bio_sfm_designer.experiments.complex_alpha_decision --records tests/fixtures/barstar_interface_records.jsonl --target-alpha 0.2 --require-complex-target-id --require-provenance --require-chain-ids
python -m bio_sfm_designer.experiments.complex_design_regime_audit --records tests/fixtures/barstar_interface_records.jsonl
python -m bio_sfm_designer.experiments.complex_scale_projection --records tests/fixtures/barstar_interface_records.jsonl --target-alpha 0.2 --n-new 300 --seeds 0:20
python -m bio_sfm_designer.experiments.m6c_report --out-md results/m6c_report.md --out-json results/m6c_report.json
python -m bio_sfm_designer.experiments.complex_posthoc_bundle --records tests/fixtures/barstar_interface_records.jsonl --out-dir results/m6c_posthoc --require-complex-target-id --require-provenance --require-chain-ids
python -m bio_sfm_designer.experiments.complex_next_batch_plan --manifest configs/template_complex_targets.json --decision results/m6c_posthoc/complex_alpha_decision.json --target-id 1BRS_AD --require-files --min-contacts 1 --previous-records tests/fixtures/barstar_interface_records.jsonl --out results/m6c_next_batch_1BRS_AD.json
python -m bio_sfm_designer.experiments.complex_scale_completion --plan results/m6c_next_batch_1BRS_AD.json --out results/m6c_scale_completion_1BRS_AD.json
python -m bio_sfm_designer.experiments.complex_project_status --posthoc-manifest results/m6c_posthoc/manifest.json --scale-completion results/m6c_scale_completion_1BRS_AD.json --scale-input-prep-completion results/m6c_input_prep_completion.json --scale-target-manifest configs/template_complex_targets.json --scale-readiness-report results/m6c_readiness.json --target-manifest-report results/m6d_candidate_targets_manifest.json --panel-input-prep-completion results/m6d_candidate_input_prep_completion.json --panel-target-manifest configs/m6d_candidate_complex_targets.json --panel-readiness-report results/m6d_candidate_readiness.json --panel-completion results/m6c_panel_completion.json --predictor-contract-report results/m6c_second_predictor_contract.json --predictor-sync-back-plan results/m6c_second_predictor_sync_back.sh --batch-preflight results/m6c_w4_round/preflight.json --batch-summary results/m6c_w4_round/summary.json --batch-campaign results/m6c_w4_round/campaign.jsonl --batch-sync-back-plan results/m6c_w4_sync_back.sh --out results/m6c_project_status.json --emit-pending-input-prep-paths results/m6c_project_pending_input_prep_paths.txt --emit-pending-external-paths results/m6c_project_pending_external_paths.txt --emit-sync-back-plan results/m6c_project_sync_back.sh --emit-external-sync-back-plan results/m6c_project_external_sync_back.sh --emit-external-remote-check-plan results/m6c_project_remote_check.sh --external-remote-check-report results/m6c_project_remote_check.json --emit-target-msa-precompute-plan results/m6c_project_target_msa_precompute.sh --emit-post-sync-plan results/m6c_project_post_sync.sh
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/template_complex_targets.json --target-id 1BRS_AD --emit-msa-plan results/m6c_target_msa_1BRS_AD.sh
python -m bio_sfm_designer.experiments.complex_input_prep_completion --report results/m6c_target_manifest_1BRS_AD.json --out results/m6c_input_prep_completion.json --emit-pending-paths results/m6c_pending_input_prep_paths.txt
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/template_complex_targets.json --min-targets 3
python -m bio_sfm_designer.experiments.complex_panel_completion --manifest configs/template_complex_targets.json --out results/m6c_panel_completion.json --panel-out results/m6c_panel_report.json
python -m bio_sfm_designer.experiments.complex_panel_report --records tests/fixtures/barstar_interface_records.jsonl --min-targets 3
python -m bio_sfm_designer.experiments.complex_cross_predictor --records tests/fixtures/barstar_interface_records.jsonl --min-overlap 20 --copy-tolerance 1e-6 --label-threshold-tolerance 1e-9 --emit-matches results/m6c_cross_predictor_matches.jsonl
python -m bio_sfm_designer.experiments.complex_predictor_contract --contract configs/template_second_predictor_contract.json --require-files --run-record-qc --out results/m6c_second_predictor_contract.json --emit-plan results/m6c_second_predictor_commands.sh --emit-sync-back-plan results/m6c_second_predictor_sync_back.sh
python -m bio_sfm_designer.experiments.run_batch_round --candidates hpc_outputs/m6c_w4/candidates.jsonl --records hpc_outputs/m6c_w4/records.jsonl --verdicts hpc_outputs/m6c_w4/verdicts.jsonl --target "benign complex/binder DBTL routing" --objective interface_quality --out results/m6c_w4_round --strict-complex-records --prevalidate-records tests/fixtures/barstar_interface_records.jsonl --conformal-alpha 0.3 --emit-sync-back-plan results/m6c_w4_sync_back.sh
python -m bio_sfm_designer.experiments.complex_readiness --batch-candidates hpc_outputs/m6c_w4/candidates.jsonl --batch-records hpc_outputs/m6c_w4/records.jsonl --batch-verdicts hpc_outputs/m6c_w4/verdicts.jsonl --batch-target "benign complex/binder DBTL routing" --batch-objective interface_quality --batch-out results/m6c_w4_round --batch-prevalidate-records tests/fixtures/barstar_interface_records.jsonl --batch-conformal-alpha 0.3 --batch-sync-back-plan results/m6c_w4_sync_back.sh --target-alpha 0.2 --out results/m6c_w4_readiness.json --emit-plan results/m6c_w4_readiness.sh
python -m bio_sfm_designer.experiments.complex_readiness --decision results/m6c_posthoc/complex_alpha_decision.json --posthoc-manifest results/m6c_posthoc/manifest.json --target-manifest configs/template_complex_targets.json --input-prep-completion results/m6c_input_prep_completion.json --scale-target-id 1BRS_AD --previous-records tests/fixtures/barstar_interface_records.jsonl --posthoc-out-dir results/m6c_posthoc_next --require-files --min-contacts 1 --panel-min-targets 3 --target-alpha 0.2 --out results/m6c_readiness.json --emit-plan results/m6c_readiness.sh --emit-scale-plan results/m6c_next_batch_1BRS_AD.json
python -m bio_sfm_designer.experiments.complex_readiness --target-manifest configs/m6d_candidate_complex_targets.json --input-prep-completion results/m6d_candidate_input_prep_completion.json --require-files --panel-min-targets 3 --target-alpha 0.2 --out results/m6d_candidate_readiness.json --emit-plan results/m6d_candidate_readiness.sh
python -m bio_sfm_designer.experiments.m6d_w2_fresh_discovery_pool --fetch
python -m bio_sfm_designer.experiments.m6d_w2_fresh_discovery_pool --fetch --source-diverse --seed-config configs/m6d_w2_expanded_discovery_seed_rcsb_ids.json --source-dir hpc_outputs/m6d_w2_expanded_discovery_sources --out-dir hpc_outputs/m6d_w2_expanded_discovery_targets --max-candidates 12 --out-json results/m6d_w2_expanded_discovery_pool.json --out-md results/m6d_w2_expanded_discovery_pool.md --out-manifest configs/m6d_w2_expanded_discovery_complex_targets.json
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2_fresh_discovery_complex_targets.json --min-targets 3 --min-contacts 20 --require-files --out results/m6d_w2_fresh_discovery_targets_manifest.json --emit-msa-plan results/m6d_w2_fresh_discovery_target_msas.sh --max-failures 100
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2_expanded_discovery_complex_targets.json --min-targets 3 --min-contacts 20 --out results/m6d_w2_expanded_discovery_targets_manifest_pre_msa.json --emit-msa-plan results/m6d_w2_expanded_discovery_target_msas.sh --max-failures 100
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2_expanded_discovery_complex_targets.json --min-targets 3 --min-contacts 20 --require-files --out results/m6d_w2_expanded_discovery_targets_manifest_strict_pre_msa.json --max-failures 100
python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json --min-targets 3 --min-contacts 20 --require-files --out results/m6d_w2_fresh_discovery_unique_source_pilot_manifest.json --emit-plan results/m6d_w2_fresh_discovery_unique_source_pilot_submit.sh --max-failures 100
```

Project roadmap: `docs/PROJECT_ROADMAP.md` is the current long-term development plan: M6c scale-up,
multi-target validation, second-predictor validation, closed-loop DBTL integration, de-novo binders, and
live orchestration, with entry/exit criteria and stop/go decisions.
`complex_readiness.py` now writes `ordered_steps` in JSON/text/shell output so input prep,
target-MSA precompute, scale or panel submission, posthoc/status refresh, second-predictor follow-up,
cross-predictor report generation, strict W4 batch routing, and status refresh are explicitly sequenced.
For W4 closed-loop DBTL, `run_batch_round.py` now writes a `preflight.json` artifact before routing; it
blocks unsynchronized candidates, prediction records, or provided screen verdicts, with missing/empty
batch or prevalidation JSONLs preserved as structured `pending_artifacts`; `--emit-sync-back-plan`
writes `results/m6c_w4_sync_back.sh` to pull those JSONLs and rerun the same batch command;
`complex_readiness.py --batch-sync-back-plan` preserves that script path in
`results/m6c_w4_readiness.json/.sh`; `complex_project_status.py --batch-sync-back-plan`
preserves it in the top-level roadmap status and post-sync replay command; and
`--strict-complex-records` requires candidate-side `complex_target_id` plus strict complex-record QC before
complex/binder evidence enters the DBTL loop. Strict W4 preflight also blocks a candidate whose
`complex_target_id` disagrees with the matching prediction record for the same id. Readiness can now preflight synced W4
`--batch-candidates`/`--batch-records`/`--batch-verdicts`, emit the strict `run_batch_round.py` command
only when that preflight passes, and order the final project-status refresh after the batch artifacts.
For calibrated W4 routing, pass prior verified `--prevalidate-records` and `--conformal-alpha`; the batch
preflight blocks any overlap between those prevalidation records and the current batch so hidden truth from
the live candidates cannot calibrate the gate, and it blocks `--conformal-alpha` without prior records
because no complex-regime `tau` can be established. It also writes a `batch_contract` audit and blocks
routing unless prevalidation records and current batch records share one `predictor_id`, `signal_source`,
`label_source`, and `lrmsd_threshold` per routed regime.
Current W4 status is captured in `results/m6c_w4_fail_closed_campaign_status.{json,md}`: 50 candidates
passed strict preflight into the DBTL loop, but the smoke DeBERTa head returned non-finite scores for every
candidate verdict, so all 50 routes deferred with zero assay spend. This proves fail-closed closed-loop
plumbing, not production safety clearance or productive synth/build selection.
`run_generate_proteinmpnn_complex.sbatch` passes `COMPLEX_ID`
into candidate metadata and generated candidate ids, so W2/W4 do not rely on implicit PDB basenames for
target identity.
When preparing W1, pass `--emit-scale-plan results/m6c_next_batch_1BRS_AD.json` so the exact next-batch
JSON used for submission is also the later `complex_scale_completion.py --plan` input.
If readiness is not scale-ready yet, `--emit-scale-plan` overwrites that path with an `ok=false`
`action=unavailable` sentinel instead of leaving a stale runnable plan behind; `complex_scale_completion.py`
blocks on that sentinel.
If readiness is scale-ready and would save a runnable scale plan, `--require-files` is required unless
the diagnostic `--allow-unchecked-files` escape hatch is explicitly used; unchecked saved plans are marked
`diagnostic_only` in JSON and warned in shell plans.
For W1 single-target scale-up, readiness scopes the target-MSA precompute plan to `--scale-target-id`, so
placeholder panel targets in the template are not submitted by accident.
With `--require-files`, readiness preserves the selected-target preflight failure list in JSON so Cayuga
blockers are actionable, not just summarized as counts; the same failure lines now appear in the terminal
summary and emitted readiness shell plan. If the remaining W1/W2 failures are only missing/empty
source/prep/FASTA/MSA/report inputs and a prep plan is available, readiness reports `waiting_on_input_prep`:
run the emitted `target_msa_precompute` section, then rerun readiness with `--require-files`.
This state is only used for repairable prep gaps; a missing `source_pdb` without `rcsb_id`, a missing
prepared PDB with no source path, MSA/FASTA mismatch, bad prep report, or malformed manifest stays `blocked`.
Readiness artifacts include a canonical `self_command` / `# rerun_readiness_after_prep`; after the MSA
sbatch finishes, `results/m6c_project_sync_back.sh` can pull the de-duplicated `.a3m` plus
`.a3m.report.json` paths from `CAYUGA_BIO_SFM_ROOT` and then run `results/m6c_project_post_sync.sh`.
If syncing manually, run `complex_input_prep_completion.py --report <manifest_report.json>` first to prove the listed
source/prepared PDB, FASTA/MSA, and report paths are present and non-empty; use its `pending_artifacts`,
`blocked_targets`, and `artifacts_by_target` fields, or the `--emit-pending-paths` text output, as the
machine-readable sync-back checklist, then
rerun that command so readiness and
`--emit-scale-plan` are refreshed from current files without carrying unrelated default W4 batch options.
After scale jobs finish and records are synced back, `complex_scale_completion.py` reads the saved
next-batch JSON plan and blocks posthoc if any expected record JSONL is missing, empty, malformed, or
carries the wrong `complex_target_id`; emitted shell plans preserve `--new-records-only` and target-id
checking choices, and explicitly label the target-id escape hatch when used.
After panel jobs finish, `complex_panel_completion.py` reads the target manifest and blocks panel report if
any target records JSONL is missing, empty, malformed, or carries the wrong `complex_target_id`; repeated
`--target-id` arguments allow staged-panel subset completion checks without editing the manifest, and the
emitted shell plan preserves the completion arguments.
`complex_project_status.py` now understands scale, input-prep, and panel completion artifacts, so W1/W2
can explicitly report `scale_records_ready_for_posthoc`, `scale_waiting_on_input_prep`,
`scale_input_prep_completion_blocked`, `scale_input_prep_ready_for_manifest`,
`scale_completion_blocked`, `panel_waiting_on_input_prep`, `panel_input_prep_completion_blocked`,
`panel_input_prep_ready_for_manifest`, `panel_records_ready_for_report`, or `panel_completion_blocked`
between prep/HPC completion and final posthoc/panel reports.
Named optional artifact paths that have not been generated yet are treated as explicit missing statuses
instead of tracebacks, so the canonical status command can be run throughout the prep/HPC/sync lifecycle.
For W2, a current non-ready target manifest supersedes stale or missing panel-completion artifacts so
target-MSA/report prep blockers are not hidden behind downstream record-sync failures.
Its input-prep sync plan failure-collects per-path `rsync` steps and the post-sync replay call, so one
missing remote prep artifact no longer blocks later pulls or local replay; it still exits nonzero if any
pull or replay step failed.
It also writes top-level `pending_external_artifacts` and optional
`results/m6c_project_pending_external_paths.txt`, which combine W1/W2 input-prep blockers, W3 secondary
predictor records, and W4 batch JSONLs into one machine-readable HPC bridge checklist;
`pending_external_summary` groups that checklist by workstream, category, target, artifact, and field
before any remote-check report exists, and `pending_external_followups` turns that pre-remote checklist
into W1-W4 repair actions;
`--scale-target-manifest`, `--panel-target-manifest`, and `--emit-target-msa-precompute-plan` write
`results/m6c_project_target_msa_precompute.sh`, a deduplicated W1/W2 target-MSA precompute bridge;
currently it covers `1BRS_AD`, `1CGI_EI`, and `2SIC_EI`, with shared `1BRS_AD` rendered once before
remote-check only when the duplicated target FASTA/MSA/report material matches. Conflicting duplicate
target ids fail closed as a local plan conflict before any submit or receipt write.
`--emit-external-remote-check-plan` writes `results/m6c_project_remote_check.sh`, a lightweight
`ssh test -s` preflight over the combined list. It first attempts to sync
`results/m6c_project_target_msa_precompute_receipt.jsonl` back from Cayuga, then writes a
machine-readable `results/m6c_project_remote_check.json` report with
missing-by-workstream/category/target metadata.
It verifies the pending external path-list fingerprint before attempting receipt sync or remote artifact
checks, so stale remote-check scripts fail before local side effects.
Status consumes that metadata into `remote_missing_followups`, which points failed remote preflights back
to the relevant readiness/workstream action, and exposes the report path in `generated_scripts`.
Passing that report back via `--external-remote-check-report` makes project status skip the remote-check
step and recommend external sync only when the report is fresh for the current pending-path SHA, `ok=true`,
its `path_manifest` provenance matches the current pending-path manifest, its status, path counters, and
per-path records prove every current path is present, and any required target-MSA precompute receipt is
satisfied. If a fresh all-present report lacks target-MSA receipt-sync evidence,
status reports `target_msa_receipt_sync_missing` and recommends rerunning the remote-check bridge before
any re-submit; if receipt sync was attempted but did not sync the receipt, status reports
`target_msa_receipt_sync_failed` so the Cayuga receipt can be inspected or repaired before another bridge step.
Receipt sync counts only when the remote-check report includes the local receipt SHA-256 and byte size; older
`synced=true` reports without digest evidence are treated as repair-required stale bridge evidence.
`resume_execution_ladder` orders the generated bridge sequence, including the non-shell
`project_status_refresh` pseudo-step: remote-check -> status refresh with `--external-remote-check-report` ->
external sync-back -> post-sync replay. The status-refresh step names the report path when known. Later steps stay blocked until their predecessor succeeds.
`--emit-external-sync-back-plan` writes
`results/m6c_project_external_sync_back.sh`, which pulls that combined list with per-path failure
collection, records the W3/W4 workstream sync scripts as provenance comments, and delegates local W1-W4
reruns plus project status refresh to `results/m6c_project_post_sync.sh`.
When the remote-check plan is part of the emitted bridge set, this external sync bridge refuses to begin
`rsync` unless the matching remote-check report proves the same pending manifest is all-present and any
required target-MSA receipt is locally satisfied with the same SHA validated during status generation.
One missing remote artifact no longer blocks later pulls or post-sync replay, but the script exits nonzero
if any pull or replay step failed. The post-sync replay script also runs each local step in a
failure-collecting wrapper so partial sync still reaches later W1-W4 checks and the final status refresh,
then exits nonzero if any replay failed. Pending-path sidecar
manifests record line counts and SHA-256 hashes; generated input-prep and external sync scripts check
the current checklist fingerprint before rsync so stale bridges fail closed, and each sync step verifies
that the local pulled file is non-empty immediately after `rsync`. Bridge scripts derive the repo root from
their own path, route bridge Python snippets through `BIO_SFM_PYTHON` when set, and default local pulls to
that root unless `LOCAL_BIO_SFM_ROOT` or `--sync-local-root` overrides it. Post-sync replay bootstraps
`BIO_SFM_PYTHON` (falling back to `python3`), `PYTHONNOUSERSITE=1`, and local `PYTHONPATH`
so fresh-shell reruns use the intended interpreter and in-repo modules, and checks its generated dependency
manifest before replay. Generated bridge/status artifacts
are written by atomic replace, so a post-sync refresh can regenerate bridge scripts without truncating a
currently running shell file. The canonical
`results/m6c_project_status.json` now includes `generated_scripts` and `recommended_next_script`, and sync
script entries carry compact manifest summaries (`n_paths`, SHA-256, sidecar/source), including post-sync
replay dependency provenance. `sync_manifest_audit`
checks those summaries against the current pending blockers and blocks the recommended sync script if the
audit fails; with the current blockers, the first executable bridge is
`bash results/m6c_project_target_msa_precompute.sh` from the Cayuga repo checkout, then
`bash results/m6c_project_remote_check.sh`, then rerun the project-status refresh with
`--external-remote-check-report results/m6c_project_remote_check.json`; run
`bash results/m6c_project_external_sync_back.sh` only after that refreshed status recommends it. The target-MSA plan writes
`results/m6c_project_target_msa_precompute_receipt.jsonl`; when that receipt covers every planned target,
has exactly one accepted row per planned target, has no unexpected target rows, records `submitted` or
`validated_existing` (with a non-empty, whitespace-free `sbatch --parsable` job id for `submitted` rows), and matches the current manifest FASTA/MSA/report paths plus manifest
path/hash/workstream provenance, status marks the submit
step `satisfied` and recommends the remote-check bridge instead of re-submitting.
An existing non-empty incomplete/invalid receipt blocks blind resubmission until it is inspected or
explicitly overwritten with `TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1` after confirming recorded jobs will
not be duplicated.
The remote-check report includes `target_msa_precompute_receipt_sync` so resumed local status can tell
whether that receipt was pulled successfully, is still remote-missing, or needs repair.
Successful receipt-sync evidence includes the synced local receipt SHA-256 and byte size; digest-free
`synced=true` reports should be regenerated with the current remote-check bridge.
The generated target-MSA bridge now checks the raw manifest hash and `sbatch` before initializing that
receipt, so stale rendered commands or accidental local execution fail before clobbering resume evidence,
and it refuses to record a `submitted` receipt row when `sbatch --parsable` returns an empty,
whitespace-only, or whitespace-containing job id. Before the bridge exits, each rendered section
self-validates its expected receipt subset, exact FASTA/MSA/report paths, and manifest/workstream
provenance, and the project-level wrapper runs a strict aggregate target-set/provenance receipt check before
remote-check; use `TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH=1` only for explicit diagnostics.
Use `TARGET_MSA_PRECOMPUTE_DRY_RUN=1 bash results/m6c_project_target_msa_precompute.sh` before the real
Cayuga submit to validate manifest freshness and print the planned target set plus current receipt state
without submitting jobs or creating/truncating the receipt; for a non-empty receipt it also previews
recorded, missing, duplicate, and unexpected target ids plus strict accepted-status, job-id,
manifest/workstream, and FASTA/MSA/report provenance validity before any overwrite decision.
The dry-run also reports the required helper file SHA-256s, whether each planned source target FASTA is
already present or can be regenerated by the same bridge from its prepared/source PDB or `rcsb_id`
metadata, and whether the Boltz runtime pointed to by `ENV_PY` and `BOLTZ` is executable when new target-MSA
outputs are still missing. The real submit path verifies every helper file still matches the generated
bridge hash, every planned source target FASTA is present or regenerable, and the required Boltz runtime
exists before creating or truncating the receipt, so stale helper code, an ungrounded missing FASTA, or a bad
Cayuga Boltz environment fails before resume evidence is touched.
Project status also records `target_msa_precompute_script_validation_audit`, which checks the emitted
bridge still contains those section, aggregate receipt, helper/source, and runtime guards; audit failure
becomes a local goal-mode blocker before Cayuga submission.
`resume_bridge_preflight` also checks that this bridge
exists locally, its pending-path/manifest files are present when applicable, and the sync-manifest audit is
fresh. It now also records a non-executing `bash -n` syntax audit, with syntax errors surfaced as structural
blockers. For runnable/external-waiting bridges, preflight and the first ladder step carry the same
downstream remote-check/status-refresh continuation as the top-level operator action. The top-level
`generated_script_syntax_audit` does the same for every generated bridge, including
later ladder steps that are not recommended yet, and syntax failures are surfaced in
`goal_progress_audit.local_blockers`; the current local state is structurally ready but
`waiting_on_cayuga_session` until the target-MSA
precompute submit step is run on Cayuga.
Use top-level `operator_next_action`, `operator_next_command`, and `operator_next_role` for resuming a
goal; when `operator_preflight_command` is present, run it before `operator_next_command`.
`operator_next_action` also carries the downstream remote-check/status-refresh continuation when
the ladder requires it. Top-level `next_action` remains the scientific workstream action.
`pending_artifact_local_audit` records whether those pending W1-W4 files are already present, empty, or
missing locally; currently all 10 pending external artifacts are local-missing, so sync is genuinely still needed.
The same status JSON now carries `self_command`, which is the exact command to refresh the dashboard and
regenerate the pending-path/sync-script artifacts from the current arguments, plus `goal_progress_audit`,
which maps the long-lived Codex goal onto W1-W4 requirement states, current first action, local/external
blockers, and an explicit `can_mark_goal_complete` guard that requires each workstream's canonical terminal
status, parseable non-empty evidence artifact whose content supports that terminal claim, W4
preflight/summary/campaign supporting artifacts when closed-loop completion is claimed, and clear
local/external blocker audit, not just a raw `complete=true`.
The same compact state is mirrored at top level
as `goal_progress`, `remaining`, `remaining_requirements`, `can_mark_goal_complete`, and
`goal_completion_note` for lightweight resume checks.
`results/m6d_goal_completion_audit.{json,md}` is the standalone no-submit completion-boundary audit:
the current honest state is `audit_ok=true`, `can_mark_goal_complete=false`, and remaining requirement
`W2_multi_target_panel`; W2 remains incomplete until the v11 panel is explicitly approved, submitted,
synced back, completed, and target-wise certified. It now also records
`panel_public_approval_bundle_ready=true` and
`panel_public_approval_bundle_workflow_script_chain_static_ok=true` when the public-safe v11 approval
bundle preserves no-submit, claim-boundary, and tracked postsubmit script-chain checks.
`results/m6d_local_cayuga_mirror_audit.{json,md}` is the standalone no-submit mirror audit: current local
and Cayuga artifacts agree across 30 exact SHA checks plus 16 semantic JSON checks, including the v11
panel approval, remote-readiness, submission-decision, receipt monitor, post-submit status, job-state
probe, and post-sync interpretation artifacts; the next action stays limited to explicit panel submission
approval, sync-back, completion, and target-wise certification.
`results/m6d_goal_drift_audit.{json,md}` is the standalone no-submit goal-boundary drift audit: current
status is `no_major_direction_drift_w2_blocked`, `audit_ok=true`, `major_direction_drift=false`, and
execution is `panel_postsync_interpretation_predeclared_not_synced`; it also records
`current_state.W2_panel_submission_decision.operator_checklist_ok=true` and
`current_state.completion_audit.panel_public_approval_bundle_workflow_script_chain_static_ok=true`;
it fails closed if either the operator checklist or script-chain gate drifts. It keeps the next action limited to
explicit W2 v11 panel approval followed by sync-back, completion, target-wise reporting, and refreshed
post-sync interpretation.
It also understands the second-predictor contract report, so W3 can report
`second_predictor_contract_ready` or `second_predictor_contract_blocked` before the final
cross-predictor report exists; blocked W3 status does not re-expose runnable downstream commands
(`commands_available=false`, `commands={}`). `--predictor-sync-back-plan` preserves the W3
second-predictor sync/rerun script path in top-level roadmap status and generated script provenance;
`--w3-decision-protocol` supersedes the raw cross-predictor caveat only for the strict
negative robustness result, reporting `negative_robustness_result_adjudicated` while keeping
`positive_claim_supported=false`;
post-sync reruns W3 from the contract report's captured `self_command` when present, including
contract, command-plan, and sync-back-plan regeneration; the generated W3 sync script validates its own
`<script>.manifest.json` sidecar before rsync, verifies each pulled secondary-record JSONL is non-empty,
and does not rewrite itself while running.
It now also reads W4 `run_batch_round.py` artifacts: `preflight.json`, `summary.json`, and
`campaign.jsonl`; W4 reports `closed_loop_round_complete` only when strict complex preflight passed, the
prior conformal gate prevalidation records a complex-regime `tau`, the prevalidation/current-batch
`batch_contract` is compatible, `summary.json` proves the round used a calibrated gate, the summary routed
count matches the preflight candidate count, and the campaign JSONL is readable with the same row count as
the summary routed-candidate count, any summary `per_round` counts agree with the aggregate, plus non-empty
unique `candidate_id` values that match preflight candidate ids when recorded, known DBTL routing actions,
an action mix matching any summary aggregate action rates, and `assays_used` matching the `verify_assay`
count plus summary `best` matching the highest-quality advancing campaign row when reported.
Post-sync reruns W4 from the preflight's captured `self_command` when present, and the generated W4 sync
script validates its `<script>.manifest.json` sidecar before pulling batch JSONLs and requires each pulled
JSONL to be non-empty before rerun; the direct W4 rerun command omits `--emit-sync-back-plan` so it does
not rewrite the running sync script.
W1/W2 status is target-alpha scoped: a decision/completion/panel artifact generated for alpha=0.3 is not
accepted as completed evidence for `--target-alpha 0.2`.

HPC scale-up anchor: `docs/M6C_RUNBOOK.md` is the current end-to-end Cayuga path. It makes
source PDB fetch/prep, target FASTA extraction, and one-time target MSA + report generation explicit, and
`complex_target_manifest.py --require-files` checks target FASTA/MSA agreement plus declared or default
`<target_fasta>.report.json` and `<target_msa>.report.json` reports before plan emission. Target FASTA
reports must carry `pdb`, `pdb_sha256`, `chain`, `out`, `out_sha256`, integer `length`, and `sequence`
matching the current prepared PDB/FASTA. Target-MSA reports must carry `ok=true`, `fasta`, `out`,
integer `sequence_length`, `fasta_sha256`, and `out_sha256` matching the current manifest FASTA/MSA,
with optional repeated `--target-id` subset selection for W1 or staged-panel bring-up,
while `predict_boltz_complex.py --target-msa` checks that the MSA query sequence matches every
candidate `target_seq` before launching Boltz.
When a target entry includes `rcsb_id`, `complex_target_manifest.py --emit-msa-plan` now renders the
cheap input-prep sequence first: fetch RCSB source PDB, run `hpc/prep_hetdimer.py`, extract target FASTA,
then submit the target-MSA precompute job.
For real scale-up claims, run the QC/decision/posthoc path with
`--require-complex-target-id --require-provenance --require-chain-ids`; the committed M6c fixture already passes that
schema-current strict mode. `complex_next_batch_plan.py` now refuses to emit scale commands from a
non-strict decision artifact unless the legacy `--no-strict-qc` escape hatch is explicitly used, and it
refuses to save a runnable scale plan without `--require-files` unless the diagnostic
`--allow-unchecked-files` escape hatch is explicitly used. `complex_readiness.py --emit-scale-plan`
applies the same guard before writing a runnable saved plan, and diagnostic unchecked plans carry
`diagnostic_only`/`unchecked_files_allowed` metadata for downstream completion checks.

## 3. Architecture

- `loop/` — DBTL controller + planner + acquisition + interpreter (Claude = orchestrator; live provider seam exists, mockable).
- `generate/` — Generator protocol + stub + `PrecomputedGenerator` (consumes HPC JSONL).
- `predict/` — Predictor protocol + stub + `PrecomputedStructurePredictor`.
- `trust/` — the external calibrated `TrustGate` (per-regime calibration-validated trust; conformal mode).
- `safety/` — tiered biosafety screen (lexicon → bioguard lexicon → DeBERTa head); **a human-triage aid, NOT an autonomous gate** ("absence of a flag is not a clearance"); fail-closed.
- `scoring/` — `net = benefit − λ·assays`, delegated to `bio_sfm_trust`.
- `hpc/` — Cayuga-side runners; **HPC bridge pattern = SLURM job → JSONL → local `Precomputed*` adapter** (heavy compute on the cluster, local = orchestration + gate + tests).

## 4. Roadmap & status

| milestone | status | what |
|---|---|---|
| M0–M2 | ✅ | scaffold, offline gate on real PDBs, per-regime calibration, live-Claude seam, **biosafety screen** (+HPC head training) |
| M3 | ✅ | DBTL loop **closed on CPU** (heritable feedback, pluggable acquisition, causal orchestration) |
| M4 | ✅ | first real backend: **ProteinMPNN → ESMFold** refold; pLDDT→self-consistency AUROC (single-model caveat) |
| M5a/M5b | ✅ | **conformal risk control** (RCPS/Hoeffding) + the conformal gate on real designs |
| M6a | ✅ | independent **Boltz-2** refold → honest cross-model AUROC (monomer) |
| M6b | ✅ | **clean within-regime test** → monomer pLDDT signal is **chance** at fixed difficulty |
| M6c-lite | ✅ | **complex/binder de-risk** → **pAE_interaction discriminates** (the regime where the gate works) |
| **M6c (live frontier)** | 🔨 | gate on the complex regime: **RCPS certifies α=0.3 at n=192**. Remaining = §8 |
| M6d/M6e/M6f | ⬜ | RFdiffusion de-novo binders · live Claude (blocked on P0 key) · DX one-command campaign |

Current milestone detail and definitions of done are in `docs/PROJECT_ROADMAP.md`; the older local
Claude plan (`~/.claude/plans/velvety-greeting-dijkstra.md`) is historical context only.

## 5. The honest findings (the heart of the project)

This is **measurement-first** tooling — negative and corrected results are the deliverable. The defining
pattern: every headline number was adversarially re-reviewed, and several were corrected.

1. **The distinctive signal (cheap-baseline disagreement) is DEAD on de-novo protein design.** ProteinMPNN
   self-consistency score ≈ 0.57 (chance); `has_baseline=False`. It is validated only in the *perturbation*
   regime (CausalAtlas 0.88 AUROC) — **cite that, do not imply it was validated on protein design.**
2. **Monomer confidence is a coarse difficulty filter, not a fine trust signal.** A pooled cross-temperature
   AUROC looks strong (~0.95) but is a **temperature batch effect**; at *fixed* difficulty the within-regime
   AUROC is **~0.59 (chance)**, CI spans 0.5. (`within_regime_signal.py`.)
3. **The complex/binder regime DOES have a real interface signal — and it's `pAE_interaction`, not ipTM.**
   At fixed difficulty: pAE stratified AUROC **0.93**; and **0.88 even among well-folded binders** (foldability
   controlled), where **ipTM is weak (~0.59)** and complex-pLDDT is just foldability. (`complex_interface_signal.py`.)
   pAE is informative-but-optimistically-miscalibrated → exactly what calibration + selective deferral are for.
4. **The gate works on the complex regime, with a guarantee.** Routing on calibrated pAE, RCPS **certifies
   α=0.3** at n=192: trusts 25/64 held-out at **12% false-accept vs 52% held-out trust-all**
   (60% full-set base-rate). (`conformal_complex_gate.py`.)

**Net thesis status:** the calibrated trust gate adds value **in the complex/binder regime** (broken-but-
informative confidence) — *not* on monomers (well-calibrated but uninformative-at-fixed-difficulty) and *not*
via the disagreement route on protein design. This is a coherent, defensible, honestly-bounded position.

## 6. Key decision points (forks + why)

- **Drifted into the safety screen, then re-centered on the design engine** (the screen is one of two gates,
  was over-invested; now done). The thesis is the *gate + generative loop*, not the screen.
- **Monomer → complex pivot.** After M6b showed monomers carry no fine signal, the thesis's "last stand" was
  the complex regime (where confidence is genuinely broken-but-informative). JK chose to **de-risk it cheaply**
  before committing to a heavy full M6c.
- **Target choice for the complex de-risk:** 4YOW (homotrimer) was **abandoned** — isolating 2 chains breaks
  the geometry (native L-RMSD 33–47 Å) and C3 symmetry makes per-chain L-RMSD ambiguous. Switched to
  **barnase–barstar (1BRS, chain A target / D binder)** — a clean obligate heterodimer. The downloaded RCSB
  chain D has a reviewed residue-numbering gap (D64-D65); the template manifest records this explicitly with
  `allow_numbering_gaps: true` for `1BRS_AD` only.
- **MSA is mandatory for interfaces.** MSA-free (`msa:empty`) folds monomers fine but **fails at complexes**
  (native barnase–barstar `msa:empty` → 38 Å; **with MSA → 1.0 Å**). Protocol = **target gets an MSA, binder
  stays single-sequence** (designs have no homologs). Preferred scale-up path:
  `predict_boltz_complex.py --target-msa target.a3m`; `--use-msa-server` remains a one-off fallback.
- **The metric is `pAE_interaction`, corrected twice.** First pass wrongly headlined ipTM (temp-inflated +
  weak); review showed pLDDT works but is foldability; the real interface-quality signal is **pAE_interaction**
  (which the first runs hadn't even captured). Lesson: use the metric the binder-design field uses, and control
  for foldability.

## 7. Where M6c stands now (live frontier)

- Fixture: `tests/fixtures/barstar_interface_records.jsonl` — **192 barstar redesigns** (1BRS A+D, temps
  0.3/0.5/0.7, target-MSA + binder single-seq), each with `iptm`, `ptm`, `mean_plddt`, `pae_interaction`,
  `lrmsd`, `truth.correct` (= L-RMSD < 4 Å), `complex_target_id`, chain ids, and predictor/source
  provenance (`predictor_id`, `signal_source`, `label_source`).
- `confidence_to_risk` (trust-core) now **prefers `pae_interaction` for complexes** (risk = pae/30), falling
  back to the old pLDDT+ipTM blend then pLDDT. `Prediction` carries `pae_interaction`.
- `conformal_complex_gate.py` (defaults α=0.3, n_cal=128): **certifies τ=0.071**, gate trusts 25/64 held-out
  at 12% false-accept (≤ α) vs 52% held-out trust-all (60% full-set base-rate). α≤0.2 still *refuses*
  (Hoeffding n↔α tradeoff).
- `complex_alpha_seed_sensitivity.py`: target alpha=0.2 certifies **0/20** split seeds; baseline alpha=0.3
  certifies **17/20**. So the alpha=0.2 refusal is not a one-split accident.
- `complex_design_regime_audit.py`: pAE remains informative inside every temperature stratum
  (pAE AUROC 0.948/0.885/0.917 for temps 0.3/0.5/0.7), while success drops 44/64 → 23/64 → 9/64.
  This supports keeping the next scale batch balanced across 0.3/0.5/0.7 rather than overfitting to one
  easy or hard regime.
- `complex_scale_projection.py`: under empirical resampling of a balanced **+300** batch
  (100 per temperature), alpha=0.2 certifies **15/20** split/sample seeds. This is planning evidence that
  the 300-candidate Cayuga scale-up is plausible, not a completed certificate. The JSON now carries
  `evidence_level=planning_diagnostic` and `certifies_target_alpha=false` so this cannot be confused with
  the W1 stop condition.
- 2026-06-29 Cayuga round3 update: the real balanced/full-mix evidence set now has **852 records** and
  still says `continue_scale` for alpha=0.2 (`results/m6c_posthoc_next3/complex_alpha_decision.json`;
  certified alphas = `[0.3]`). However, the scoped **t0.3-only production protocol** has **220 records**
  and says `stop_certified` for alpha=0.2 (`results/m6c_posthoc_t030_protocol/complex_alpha_decision.json`;
  tau=0.1053, trusted=32/74, false-accept=0.0938, trust-all false-accept=0.4459). Treat this as a
  protocol-branch certificate, not as a full 0.3/0.5/0.7 mixed-temperature certificate. The compact claim
  boundary is in `results/m6c_protocol_branch_summary.{json,md}` and the next-action table is
  `results/m6c_next_science_actions.{json,md}`.
- 2026-06-29 W4 update: `results/m6c_w4_round/summary.json` and
  `results/m6c_w4_round/campaign.jsonl` are accepted by
  `results/m6c_project_status_w2_followup.json` as `closed_loop_round_complete`. The campaign is
  intentionally conservative: the precomputed DeBERTa screen produced non-finite scores for all 50
  candidate verdicts, so every candidate was routed to `defer` (`defer_rate=1.0`, `assays_used=0`,
  `best=null`). The compact claim boundary is in
  `results/m6c_w4_fail_closed_campaign_status.{json,md}`.

## 8. Next steps (concrete, prioritized)

1. **Freeze the t0.3 protocol branch, then broaden.** The strongest W1 result is now the scoped
   t0.3-only alpha=0.2 certificate. Do not launch another balanced W1 round only by inertia; run more
   full-mix scale only if the explicit question is full 0.3/0.5/0.7 certification. The more valuable next
   science steps are target-wise t0.3 validation in W2 and independent-predictor evidence in W3.
2. **FIRST use cached target MSA, then scale.** `predict_boltz_complex.py` now supports `--target-msa`
   (and `run_predict_boltz_complex.sbatch` supports `TARGET_MSA=/path/to/target.a3m`) so the barnase target
   MSA can be precomputed once and referenced in every YAML. Use `docs/M6C_RUNBOOK.md`: prepare the
   heterodimer, extract the fixed target FASTA plus `.fasta.report.json` with `hpc/extract_chain_fasta.py`,
   generate the target `.a3m` and `.a3m.report.json` once with
   `hpc/run_precompute_boltz_target_msa.sbatch`, then refold with `TARGET_MSA`.
   This replaces the old `--use_msa_server` per-design target query
   waste (~90 min/120 redundant identical queries). Generate hundreds more barstar
   designs with `run_generate_proteinmpnn_complex.sbatch`, refold with `TARGET_MSA`, then run
   `complex_posthoc_bundle.py --require-complex-target-id --require-provenance --require-chain-ids` on the merged old+new
   JSONL inputs. It emits QC, alpha sweep, scale plan,
   alpha decision, row-level `lrmsd_threshold` audit, Markdown/JSON report, and project-status artifacts
   from one synchronized records list. Then try to certify
   **α≤0.2**. The decision artifact should move from `continue_scale` to `stop_certified` before stopping.
   Historical fixture-era scale planner:
   `complex_alpha_plan.py` estimated alpha=0.2 needed about **n≈452 total** from the 192-record fixture
   (about +260 records) and recommended **NUM_SEQ=100 per temperature** (300 candidates total). The real
   Cayuga round3 full-mix follow-up reached **852 records** and still did not certify alpha=0.2; the latest
   full-mix `next_batch` now estimates **+458 records** and recommends **NUM_SEQ=160 per temperature**
   (480 candidates total). Run that only if the explicit question is full 0.3/0.5/0.7 certification;
   otherwise prefer the scoped t0.3 certificate plus W2/W3 broadening.
   Use `complex_next_batch_plan.py --require-files` to preflight the selected target
   and emit temp-specific candidate/record paths plus generate→predict sbatch dependencies before submitting;
   generated ProteinMPNN commands carry manifest `SEED`, `OBJECTIVE`, and `COMPLEX_ID=<target id>` so
   candidate ids/metadata stay target-namespaced;
   the emitted shell plan replays selected-target FASTA/MSA/report/prep preflight before any `sbatch`,
   so stale copied files are caught even if the plan is run later;
   by default this requires the decision JSON to include passing strict QC provenance and chain ids. Save the
   plan with `--out`, then after records sync back run `complex_scale_completion.py --plan <plan.json>`
   before the posthoc bundle so missing/empty/malformed outputs are caught as completion failures.
   Alpha=0.1 is far larger (~7.9k).
3. **More targets (≥3 clean heterodimers)** → show the result generalizes beyond barnase–barstar. The W2
   current resume branch is fresh discovery, not another run of the historical panels below. The known local
   W2 pool admitted zero non-anchor pilot targets. `results/m6d_w2_fresh_discovery_pool.{json,md}` screened
   10 public RCSB seeds, selected 6 structural chain-pair candidates from 3 source PDBs
   (`1A2K`, `1AK4`, `1FQJ`), and wrote
   `configs/m6d_w2_fresh_discovery_complex_targets.json`. Target-MSA precompute completed on Cayuga for all
   6 selected chain-pairs (`3056468`-`3056473`), the `.a3m`/report files were synced back, and
   `results/m6d_w2_fresh_discovery_targets_manifest.json` now passes strict `--require-files` with
   `n_ready_targets=6`. To avoid source-redundancy drift, the branch tested the 3-target unique-source
   pilot (`1FQJ_EB`, `1AK4_BC`, `1A2K_CB`) in
   `configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json`; its strict report is
   `results/m6d_w2_fresh_discovery_unique_source_pilot_manifest.json` and submit plan is
   `results/m6d_w2_fresh_discovery_unique_source_pilot_submit.sh`. It was submitted on Cayuga:
   `1FQJ_EB` ProteinMPNN/Boltz `3056479`/`3056480`, `1AK4_BC` `3056481`/`3056482`, and `1A2K_CB`
   `3056483`/`3056484`. Use
   `results/m6d_w2_fresh_discovery_unique_source_pilot_submit_receipt.json` as the local receipt. All three
   records JSONLs synced back with 100 records each; completion is
   `results/m6d_w2_fresh_discovery_unique_source_pilot_completion.json` (`ok=true`), and the panel report is
   `results/m6d_w2_fresh_discovery_unique_source_pilot_panel_report.json`
   (`panel_status=multi_target_evaluable_not_certified`, `ok=false`). All three pilot targets are
   `not_certified`; only `1AK4_BC` had any successes (2/100). The diagnostic
   `results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.{json,md}` classifies all three as
   `target_protocol_mismatch_low_success` with zero accepts under the transferred t0.3 low-pAE cutoff.
   The regenerated revised branch now has 12 known target decisions, and the regenerated candidate-pool
   screen still has `n_admitted_for_pilot=0`. Next action is W2 target/protocol redesign, not rerunning this
   same pilot or emitting a submit manifest from the current known pool. The current W2 design anchor is
   `results/m6d_w2_next_branch_design.{json,md}`; it emits
   `configs/m6d_w2_next_branch_candidate_rules.json`, where `spend_gate.cayuga_submission_allowed=false`.
   `results/m6d_w2_expanded_discovery_pool.{json,md}` now expands beyond excluded sources: it screened
   49 seed PDBs, scanned 248 chain pairs, admitted 17 structural candidates, and selected 10
   source-diverse candidates from 10 unique source PDBs (`1BVK`, `1CHO`, `1EER`, `1HE1`, `1KAC`, `1KLU`,
   `1MLC`, `1NMB`, `1QFW`, `2MTA`). The first target-MSA batch had seven ColabFold MSA-server failures,
   but the low-concurrency retry completed the remaining targets. After sync-back,
   `results/m6d_w2_expanded_discovery_target_msa_combined_audit.{json,md}` is
   `target_msa_precompute_complete_after_retry`, `results/m6d_w2_expanded_discovery_targets_manifest.json`
   passes strict `--require-files` with 10/10 ready targets, and
   `results/m6d_w2_next_branch_candidate_pool.{json,md}` admits all 10 source-diverse targets while keeping
   `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` audit-only. The separate audit plan is
   `results/m6d_w2_source_redundancy_audit_plan.{json,md}`; it is a within-source failure-mode plan only,
   with `ready_for_cayuga_submission=false` and `ready_for_w2_generalization_claim=false`.
   `results/m6d_w2_next_branch_manifest_design.{json,md}` freezes the admitted targets into
   `configs/m6d_w2_expanded_next_branch_targets.json`; strict preflight
   `results/m6d_w2_expanded_next_branch_manifest.json` has `ok=true`, `n_ready_targets=10`, and no failures.
   The expanded next-branch run is now complete and synced back: completion has 10/10 completed targets,
   while `results/m6d_w2_expanded_next_branch_panel_report.json` is
   `multi_target_evaluable_not_certified` at alpha=0.2. The diagnostic
   `results/m6d_w2_expanded_next_branch_redesign_diagnostic.{json,md}` recommends
   `redesign_or_replace_low_success_targets`: six targets are drop/redesign, `1BVK_ED` and `1NMB_HL`
   are retain/retest candidates, and `1KLU_BA`/`1QFW_BA` are held until the low-pAE signal strategy is
   clarified. This produced `w2_target_family_redesign_v1`; do not repeat that same panel. The v1
   no-spend replay had 0 admitted candidates from the 25-target local inventory and 0 structural
   candidates from the filtered 39-seed source cache. RCSB seed expansion then selected 80 new seeds,
   structural discovery selected 10 source-diverse targets, and sequence-diversity audit blocked the full
   10-target panel because 8/10 targets are sequence-identical near duplicates. The representative targets
   `10XZ_EF`, `10YB_GH`, and `12NP_AH` completed target-MSA prep after retry, passed strict preflight, and
   completed a scoped ProteinMPNN/Boltz probe with receipt capture. The representative report is
   `multi_target_evaluable_not_certified` at alpha=0.2 with 3 targets and 300 records. The diagnostic
   recommends replacing/redesigning `12NP_AH` before more W2 panel GPU and predeclaring a low-pAE
   acceptance/calibration strategy before scaling `10XZ_EF` or `10YB_GH`. `w2_target_family_redesign_v2`
   now carries the current resume branch forward: the v2 no-spend local inventory screen admits 0/25 candidates,
   keeps `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` source-redundancy audit-only, and is not ready for a revised
   manifest or Cayuga submission. The follow-on `w2_target_family_redesign_v2_rcsb` branch is now completed
   negative W2 evidence: seed expansion selected 80 seeds, structural intake selected
   20 source-unique targets, sequence-diversity audit passes with 12 clusters and largest-cluster fraction
   0.25, target-MSA precompute is complete after 11 retry jobs, post-sync strict preflight passes 20/20,
   and the receipt-preserving wrapper submitted 20 ProteinMPNN/Boltz job pairs (`3056715`-`3056754`).
   Those records are now synced back and the panel report is `multi_target_evaluable_not_certified` at
   alpha=0.2 with 20 targets and 2000 records. Only `1A3O_BA` and `1A9W_EA` certify target-wise; the other
   18 targets do not. The pooled diagnostic certifies tau=1.0, but pooled-only evidence is not W2
   generalization. The follow-on branch `w2_target_family_redesign_v3` selected 8 source-diverse and
   sequence-diverse candidates, completed target-MSA prep after two low-concurrency retry jobs (`3057090`,
   `3057091`), passed strict post-MSA preflight 8/8, submitted 8 receipt-validated ProteinMPNN/Boltz job
   pairs (`3057094`-`3057109`), synced back 8/8 records, and completed target-wise panel reporting. The
   v3 panel is `multi_target_evaluable_not_certified` at alpha=0.2 with 8 targets and 800 records. All eight
   target-wise certificates are `not_certified`; the pooled diagnostic tau=0.75 is diagnostic only. Next W2
   action moved to `w2_target_family_redesign_v4`: rules were frozen, the local inventory screen found 0/56
   admitted candidates, new RCSB seed expansion selected 80 seeds, structural intake selected 7 candidates,
   sequence-diversity audit passed with 5 clusters, a 5-target representative manifest completed target-MSA
   precompute after two retry jobs (`3057130`, `3057131`), strict post-MSA preflight passed 5/5, and the
   representative panel completed as `multi_target_evaluable_not_certified` at alpha=0.2 with 5 targets and
   500 records. `1AY7_AB` and `1B27_CF` are target-specific certified controls only. The v5 branch admitted
   13 source-diverse targets, passed strict pre-submit preflight 13/13, completed receipt-validated
   ProteinMPNN/Boltz jobs `3057168`-`3057193`, and synced back 13/13 records. The v5 panel is
   `multi_target_evaluable_not_certified` at alpha=0.2 with 13 targets and 1300 records; all 13 target-wise
   certificates are `not_certified`, so this is completed negative W2 evidence, not generalization.
   Historical W2 candidate manifest: `configs/m6d_candidate_complex_targets.json` with `1BRS_AD`, `2SIC_EI`, and
   `1CGI_EI`; evidence and caveats are in `docs/M6D_CANDIDATE_PANEL.md`. `2SIC_EI` and `1CGI_EI` passed
   strict `hpc/prep_hetdimer.py` locally with no numbering gaps and 60+ CA contacts. Next run
   `complex_target_manifest.py --manifest configs/m6d_candidate_complex_targets.json --emit-msa-plan results/m6d_candidate_target_msas.sh`
   before target `.a3m`/report files exist; entries with `rcsb_id` get source PDB fetch and heterodimer prep
   commands in that same plan. If a target `.a3m` already exists but its report is missing or stale, the
   plan validates the existing MSA against the FASTA and refreshes the report locally instead of resubmitting
   a GPU MSA job. After `.a3m`/report files sync back, run the embedded `# rerun_manifest_after_msa`
   command to rerun `--require-files --min-targets 3` and emit the W2 submit plan.
   2026-06-29 update: the current W2 panel has already produced 300 Boltz records and is evaluable but
   not certified (`results/m6c_panel_report.json`, `panel_status=multi_target_evaluable_not_certified`).
   Because the manifest default is temp=0.3, this is a negative t0.3 generalization check for the current
   1CGI/2SIC target choices, not merely missing panel execution.
   W2 redesign diagnostic is in `results/m6c_w2_redesign_diagnostic.{json,md}` and recommends
   `redesign_or_replace_low_success_targets`: 1CGI_EI and 2SIC_EI are low-success target/protocol
   mismatches, while 1BRS_AD is underpowered or split-sensitive. The explicit GPU spend gate is: do not
   rerun the same 1CGI_EI/2SIC_EI panel as though it were an untested target-MSA or sync problem.
   A replacement M6d panel (`configs/m6d_redesign_complex_targets.json`) has now also completed on Cayuga:
   `1BRS_AD`, `3PC8_AB`, `1S1Q_CD`, and `1SYX_AB` each have 100 ProteinMPNN candidates and 100 Boltz
   complex records. `results/m6d_redesign_panel_report.json` is still
   `multi_target_evaluable_not_certified` at alpha=0.2, so do not claim multi-target generalization.
   The replacement diagnostic (`results/m6d_redesign_panel_diagnostic.{json,md}`) says `1SYX_AB` is a
   low-success target/protocol mismatch, while `1BRS_AD`, `3PC8_AB`, and `1S1Q_CD` are underpowered.
   Planning-only relaxed-alpha reports show `3PC8_AB` certifies at alpha=0.3 and `1BRS_AD` plus
   `3PC8_AB` certify at alpha=0.4; the target alpha=0.2 claim remains negative. Seed sensitivity makes
   `3PC8_AB` the best near scale candidate (`results/m6d_3pc8_seed_sensitivity.json`, alpha=0.2
   certified in 4/100 split seeds; estimated extra records median 22), but a 3PC8 scale-up would be a
   target-specific test, not a W2 generalization claim. A follow-up panel
   (`configs/m6d_followup_complex_targets.json`) reused `1BRS_AD`/`3PC8_AB`, added
   `1MEL_MB`, `1GCQ_CB`, and `2IDO_CD`, and completed 500 records total. It is still
   `multi_target_evaluable_not_certified` at alpha=0.2. Seed sensitivity makes only
   `3PC8_AB` near alpha=0.2: alpha=0.3 certifies in 100/100 split seeds, alpha=0.2 in
   4/100 split seeds, with estimated extra records median 22. The current next-action
   artifact is `results/m6d_followup_next_science_actions.{json,md}`. A target-specific
   `3PC8_AB` t0.3 mini-scale from `results/m6d_followup_3PC8_AB_next_batch.{json,sh}`
   completed on Cayuga (jobs 3056320/3056321), wrote 50 new records to
   `hpc_outputs/m6d_followup_3PC8_AB_scale_t030`, and
   `results/m6d_followup_3PC8_AB_posthoc_scale_t030/complex_alpha_decision.json` is
   `decision=stop_certified` for alpha=0.2 with 150 total 3PC8 records. This tightens
   3PC8 only and must not be promoted to W2 multi-target generalization.
   The emitted plan captures ProteinMPNN job ids, chains each Boltz job with `afterok`, and passes
   `COMPLEX_ID=<target id>`, which is written as `complex_target_id`.
   After panel records sync back, run `complex_panel_completion.py --manifest <targets.json>` before
   `complex_panel_report.py` so missing or target-mismatched per-target JSONLs are caught before claims.
   Before submitting, run `complex_readiness.py --target-manifest ... --require-files --emit-plan ...`
   to aggregate target-manifest, scale-plan, second-predictor, and later W4 batch preflight results in one artifact.
   Before making a generalization claim, run `complex_panel_report.py`; it refuses pooled-only evidence and
   requires per-target records/certificates. Panel certificates are predictor-specific: mixed predictors,
   mixed signal sources, or mixed label sources are blocked and should be analyzed with
   `complex_cross_predictor.py` instead. Row-level `lrmsd_threshold` metadata must match the panel
   report `--threshold`, so target panels cannot mix incompatible success definitions.
4. **Independent 2nd complex predictor** (e.g. Chai-1; AF2/AF3 only if license permits — see landmines) to
   close the **single-model caveat** (pAE + the L-RMSD label currently both come from the one Boltz fold), as
   M6a did for monomers. Future second-predictor records should carry `predictor_id`, `signal_source`,
   `label_source`, `target_id`, and `complex_target_id`; cross-predictor overlap is matched on
   `complex_target_id` + `target_id`, then checked by `complex_cross_predictor.py` against the Boltz records
   before dropping the caveat. Copy `configs/template_second_predictor_contract.json`, fill in
   the real second-predictor paths/sources, then run `complex_predictor_contract.py --require-files
   --run-record-qc --emit-plan ...`. The validator emits both the strict second-record QC command and the
   matched cross-predictor command; if the contract is blocked, the emitted plan lists blockers and comments
   downstream commands until validation passes. The checker requires enough labeled overlap, label agreement
   (default ≥0.8) under the same `lrmsd_threshold` definition, distinct signal/label provenance, and
   non-copied numeric outputs; copied Boltz labels, mixed-threshold labels, or exact/mostly near-exact
   pAE/L-RMSD values under a new predictor id do **not** close the caveat.
   The contract template pins `cross_predictor.min_overlap=20`, `cross_predictor.min_label_agreement=0.8`,
   `cross_predictor.copy_tolerance=1e-6`, `cross_predictor.copy_fraction_threshold=0.95`,
   `cross_predictor.label_threshold_tolerance=1e-9`, and
   `cross_predictor.require_disjoint_record_files=true`; invalid overlap/agreement settings block at the
   contract stage, primary/secondary record paths must be disjoint, and emitted commands pass these options explicitly so the independence,
   label-definition, and one-predictor-per-record-file guards are reproducible. Project status also refuses to
   mark W3 complete from older/non-strict cross-predictor reports that lack the record-file audit.
   Use `--emit-matches results/m6c_cross_predictor_matches.jsonl` to inspect target-wise
   label disagreements and source provenance before trusting the aggregate status.
   2026-06-30 current W3 update: the Chai path progressed beyond the initial smoke record. The no-MSA Chai
   scale-up now passes QC/contract, but `results/m6c_cross_predictor.json` reports matched label agreement
   0.600 against the required 0.800. Under the selected
   `adjudicated_disagreement_protocol_v1`, this is a negative robustness result for the no-MSA Chai protocol,
   not a reason to rerun the same no-MSA scale-up. The decision protocol now requires strict adjudication
   integrity before making that interpretation: the only cross-predictor failure kind is
   `label_agreement_below_min`, with no target-identity, provenance, label-threshold, overlap, or
   numeric-copy blockers. The same protocol now materializes
   `results/m6d_w3_adjudication_set.jsonl` and `results/m6d_w3_adjudication_set.json` as the concrete
   future W3 adjudication input set: 12 discordant Boltz/Chai labels plus 6 concordant-success controls.
   `complex_project_status.py` verifies the materialized JSONL sha256, row count, role counts, and target-id
   membership before preserving `negative_robustness_result_adjudicated`.
   If W3 is pursued further, choose a third predictor/protocol or a stronger Chai MSA/template variant
   with a predeclared agreement rule and use that materialized set.
5. **Replace or train the W4 screen head before nontrivial routing.** W4 campaign plumbing now works under
   strict preflight and calibrated gate checks, but the current smoke DeBERTa head returned non-finite
   candidate scores and therefore failed closed. Keep this as useful safety behavior, not as a route-to-build
   policy, until a trained screen head produces finite, audited verdicts.
6. Optional: **RFdiffusion** de-novo binder backbones (vs ProteinMPNN interface redesign on a fixed backbone).
7. **P0 (blocks live Claude / M6e):** complete credential hygiene before any live-Claude run.
   This repo should not contain provider keys or key material. JK owns any out-of-band rotation/revocation.

## 9. HPC (Cayuga) specifics + gotchas / landmines

- Access: set `CAYUGA_BIO_SFM_HOST` to the login host. Working dir
  `${CAYUGA_BIO_SFM_ROOT:-$HOME/bio_sfm_smoke}` (mirrors `hpc/`, holds `hpc_outputs/`).
  ProteinMPNN checkout at `~/ProteinMPNN`. Login node **has internet** (curl/MSA server); so do compute nodes.
- Conda envs (`module load anaconda3/2023.09-3` first): **`bioguard`** (ProteinMPNN + ESMFold via transformers,
  torch 2.6), **`boltz`** (Boltz-2 2.2.1 checked on Cayuga, torch 2.12), and separate **`chai1`**
  (`chai_lab`/`chai-lab` 0.6.1 checked on Cayuga for the completed no-MSA W3 comparator). Partition
  `scu-gpu` (a40/a100/h100); submit with the `hpc/run_*.sbatch` files.
- **Always `export PYTHONNOUSERSITE=1`** before Boltz — else `~/.local` shadows the env's torch (and pip will
  silently skip installing torch into the env). Boltz needs **`--no_kernels`** (no cuequivariance on the cluster).
- For the generated target-MSA bridge, keep `ENV_PY=$HOME/.conda/envs/boltz/bin/python` or set
  `BIO_SFM_PYTHON` explicitly. Cayuga's system Python can be too old for the helpers, so the bridge now
  prefers the Boltz env Python before falling back to `python`.
- Target-MSA precompute is MSA-only even though Boltz continues into a tiny structure-prediction tail. If
  that tail fails after writing a matching `.a3m`, `precompute_boltz_target_msa.py` recovers the `.a3m`
  and writes the report; `KEEP_WORK=1` can recover from an existing work directory after interrupted runs.
- Target-MSA reports preserve the caller-declared `fasta`/`out` path strings and keep machine-specific
  absolute paths in `fasta_abs`/`out_abs`, so Cayuga-generated reports remain manifest-compatible after
  local sync-back.
- **Boltz output caching bug (FIXED — do not regress):** Boltz **skips** any prediction whose output already
  exists. Two runs sharing one work dir → silent reuse of stale structures (this corrupted an early M6b run).
  Fix in `predict_boltz.py` / `predict_boltz_complex.py`: the work dir is **unique per output file AND wiped on
  start**. Keep distinct `OUT` per run.
- **Crystal gaps:** unmodeled residues come through ProteinMPNN as `X`; `generate_proteinmpnn_complex.py`
  **drops them** to get the continuous modeled sequence (a 2-residue barstar gap once voided every design).
- **Quoting:** zsh/ssh eat backticks and `(`/`)` inside `bash -lc "…"`; use quoted heredocs and avoid parens in
  `echo`. Git commit messages with backticks → `git commit -F - <<'MSG'`.
- The `/tmp/bio_sfm_venv` is **ephemeral** (cleared periodically); recreate per §2. Analyses are pure-stdlib
  (no numpy) except the Kabsch/PAE bits.

## 10. Key file map

- Engine: `bio-sfm-trust-core/src/bio_sfm_trust/{gate.py (confidence_to_risk, TrustGate helpers), calibration.py, conformal.py (rcps_threshold), metrics.py}`
- Project plan: `docs/PROJECT_ROADMAP.md` (workstreams, milestone definitions, stop/go rules)
- Gate: `src/bio_sfm_designer/trust/gate.py` (per-regime conformal τ routing); `types.py` (`Prediction.pae_interaction`)
- HPC runners: `hpc/{prep_hetdimer.py, extract_chain_fasta.py, precompute_boltz_target_msa.py, generate_proteinmpnn.py, predict_esmfold.py, predict_boltz.py, generate_proteinmpnn_complex.py, predict_boltz_complex.py}` + matching `run_*.sbatch`
- Experiments (each has a contract/result test in `tests/`): `experiments/{within_regime_signal, cross_model_auroc, complex_interface_signal, conformal_complex_gate, complex_records_qc, complex_gate_sweep, complex_alpha_plan, complex_alpha_decision, complex_alpha_seed_sensitivity, complex_design_regime_audit, complex_scale_projection, complex_next_batch_plan, complex_scale_completion, complex_project_status, complex_readiness, complex_panel_completion, complex_panel_report, complex_cross_predictor, complex_predictor_contract, complex_input_prep_completion, m6c_report, complex_posthoc_bundle, complex_target_manifest, run_batch_round, conformal_design_gate, closed_loop_campaign}.py`
- Fixtures: `tests/fixtures/{esmfold_designs_records, boltz_designs_records, esmfold_t07_records, boltz_t07_records, barstar_interface_records}.jsonl`

## 11. The meta-lesson (please preserve)

This project's value is **honest measurement**, not a win. In one stretch it caught — by adversarial
re-review — a temperature confound, a single-model-self-consistency inflation, a data-integrity caching bug,
two wrong interface metrics, and a degenerate target choice. **Default to reviewing your own headline number
before trusting it:** check the temperature/difficulty confound (analyze *within* a fixed regime), the
single-model circularity (signal and label from the same model), the small-n CIs, and whether the "signal" is
really the thing you claim or a proxy (foldability vs interface quality). Report caveats plainly; let RCPS
refuse rather than over-promise. Guarantees over vibes.
