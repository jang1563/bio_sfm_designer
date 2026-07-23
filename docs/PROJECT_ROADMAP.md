# Project Roadmap

> **Current statistical boundary (updated 2026-07-15):** positive certificates produced by the former
> same-sample threshold search are legacy exploratory outputs. The canonical 192-design reanalysis under
> `split_ltt_v1` retains the pAE signal but refuses alpha=0.3. The fresh 11-target W2 panel has now
> completed on Cayuga with 1,100 records and is `multi_target_evaluable_not_certified` at alpha=0.2.
> Its target-wise signal is heterogeneous, and the declared split is structurally underpowered:
> 33 certification rows give a best-case Hoeffding UCB of 0.2669; at least 176 total records per target
> are needed merely to make zero-error alpha=0.2 certification possible. This is a post-hoc diagnosis,
> not a recertification. W2 therefore remains negative. The separate W2b target-adaptive exact-LTT fit
> stage is now complete on eight fresh targets with 480 H100 records and strict QC failures=0. Five targets
> are fit-eligible: `1F51_AE` freezes a selective pAE rule at tau 5.7365 with AUROC 0.8421, while four use
> `trust_all`; three targets refuse. Certification then completed on the five eligible targets with 300
> fresh H100 records. Four `trust_all` targets certified, but `1F51_AE`, the sole selective target, failed
> exact certification at 31 accepts, 6 false accepts, UCB 0.4002. The locked requirement of one selective
> certificate is unattainable, so W2b v1 is terminally not supported and test compute was stopped. See
> `docs/STATISTICAL_VALIDITY_RESET_2026-07-10.md`.
> W2c is now declared as a separate selective-pAE-only one-shot successor. Its prospective exact-binomial
> design gate qualifies at 90 certification accepts with conditional power 0.817860 under design risk 0.08,
> the evaluator is implemented, eight label-blind fresh targets are selected, and all eight target-MSA/report
> pairs pass strict validation. The separately approved 8x60 threshold-learning run then completed with
> 480/480 strict-QC Boltz records, 16/16 local/Cayuga file-hash matches, no retries, and 1.0775 H100
> GPU-hours. All eight frozen target decisions refuse, leaving zero selective candidates against the required
> minimum of three. W2c is terminal before independent screening; no screen or certification compute is
> approved. W2c does not alter W2b. Its distinct 58-case W3 AF2-Multimer mechanism panel then completed
> under the frozen protocol. 3PC8 supports Chai (`12/12` discordant labels, `6/6` controls), while W2c
> agreement with Boltz is mixed (`30/40`, with `5/8` targets at least `4/5`). The joint outcome is
> `context_dependent_or_unresolved`, so population-level robustness and W2c rescue remain unsupported.
> W3b now prospectively locks the successor: eight unused source/sequence-unique targets, a label-blind
> 3 fit / 3 certification / 2 held-out-test split, matched Boltz-2/AF2 inputs, and an exact endpoint-power
> gate. The design passes at power 0.824333. Its exact Boltz/AF2 runtime identities are hash-locked. The
> approved target-MSA stage completed 8/8 at 0.216389 A40 GPU-hours. The later initial fit approval was
> consumed once: all three ProteinMPNN and all three Boltz jobs completed, yielding 180 candidates and
> 180 Boltz records. All three AF2 jobs failed before prediction on a container-relative input path, after
> which the separate exact recovery approval was consumed once. Replacements `3085544`-`3085546` completed,
> strict replay assembled 180/180 matched rows, and the frozen evaluator returned
> `w3b_fit_rule_not_found_stop`. No primary or comparator rule qualified. `1FSK_LJ` was wrong for all 60
> rows under both endpoints, making the required 15 accepts alone exceed the 0.08 global risk cap.
> Certification and held-out test are unreachable and unsubmitted; W3b must not be rescued or retuned.
> W3c now freezes the distinct successor as validity-first failure localization. A CPU-only audit of all
> 24 historical representatives found 5 complete author-determined two-chain assemblies and 3 strict
> target-binder systems, with strict branch counts W2b `0/8`, W2c `2/8`, and W3b `1/8`. Historical branches
> remain exact structural-proxy experiments and do not estimate strict target-binder generalization. W3c-A
> then locked eight fresh, source-disjoint complete target-binder dimers. All eight pass the frozen
> structure, semantic, geometry, and exact-overlap gates, with zero MSA or predictor work. The W3c-B1
> target-MSA-only packet is locally prepared and locks eight one-hour A40 queries, but Cayuga no-submit mirror
> validation is still required before exact approval may be requested. No W3c compute is currently authorized.

This is the operating plan for developing `bio_sfm_designer` as a research engine.
It is intentionally not a publication plan. External writing can come later; the
current goal is to make the system stronger, more reproducible, and harder to fool.

## North Star

Build a calibrated, cost-aware, safety-screened DBTL designer where specialist
scientific foundation models propose and evaluate candidates, but an external
trust gate decides when a model output is safe to trust, when to verify, when to
fall back to a baseline, and when to defer.

The project succeeds when a new protein-design regime can be added with:

- explicit allowed-target and safety checks before generation and before synth;
- reproducible heavy-model runs through the HPC JSONL bridge;
- visible prediction evidence, hidden truth labels, and leakage-checked routing;
- a calibrated or conformal risk rule with a stated false-accept target;
- honest stop/go artifacts that can say "refuse", "continue scale", or "certified";
- target-wise and predictor-wise provenance, not pooled-only claims.

## Current Anchor

2026-07-11 W2b certification update: the current evidence frontier is the terminal result summarized in
`docs/M6D_W2B_CERTIFICATION_COMPLETION.md`. Fresh data preserve diagnostic pAE ranking on `1F51_AE`
(AUROC 0.7839), but its frozen threshold fails exact risk certification. Four easy `trust_all` targets
certify; zero selective targets certify. No test rows were generated because they cannot change this result.

2026-07-14 W2c threshold-learning completion: `docs/M6D_W2C_ONE_SHOT_PROTOCOL.md` and
`results/m6d_w2c_design_gate.{json,md}` define the current forward path. W2c counts only selective-pAE
certificates, separates threshold learning from an independent fit screen, requires prospective exact
power, and forbids adaptive top-up. The fresh manifest locks `1FR2_BA`, `1F80_BC`,
`1EZV_XY`, `1FFG_CD`, `1FFK_HR`, `1FQ9_CA`, `1FYR_CD`, and `1F99_BA`. Target-MSA preparation is complete:
8/8 MSA/report pairs pass strict validation, with 0.144722 A40 GPU-hours consumed. The later exact approval
for `w2c-fit-learn-v1` was consumed: 16/16 receipt-bound jobs completed, 480/480 records passed strict QC,
and all output hashes match Cayuga. The frozen evaluator retained 0/8 threshold candidates. The predeclared
minimum of three is unreachable, so W2c is terminal and later-stage compute is blocked. The authoritative
readout is `docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md`. That terminal result motivated the distinct
W3 predictor-robustness and failure-mechanism experiment summarized below.

2026-07-14 W3 mechanism-panel completion: the public-safe protocol and claim boundary are in
`configs/m6d_w3_mechanism_panel_protocol.json`; the terminal readout is in
`docs/M6D_W3_MECHANISM_PANEL_COMPLETION.md`. The first job was cancelled and invalidated when a wrapper
bug truncated target MSA depth. Corrected, network-isolated job `3084977` preserved the precomputed MSA,
completed 58/58 with exit `0:0`, and passed 58-record conversion and adjudication with zero failures.
The next frontier is not more W2c rescue or W3 retuning. It is a new prospective matched-protocol panel
testing whether predictor-disagreement-aware abstention improves calibratable trust on fresh targets.

2026-07-14 W3b preregistration: `docs/M6D_W3B_DISAGREEMENT_GATE_PROTOCOL.md` and
`configs/m6d_w3b_disagreement_gate_protocol.json` freeze the gate, comparator, matched predictor contract,
target-level split, exact multiplicity correction, held-out decision rule, staged stop conditions, and
24 H100 GPU-hour ceiling. `configs/m6d_w3b_fresh_targets.json` locks the eight label-blind targets and roles.
The evaluator and design auditor are implemented. The historical MSA packet in
`docs/M6D_W3B_TARGET_MSA_APPROVAL.md` was consumed exactly once. Jobs `3085384`-`3085391` completed 8/8
with `0:0`, no retry, and 0.216389 A40 GPU-hours. Strict replay validates all 56 scoped input artifacts,
eight reports, and eight frozen sequences. The public completion and telemetry correction boundary are in
`docs/M6D_W3B_TARGET_MSA_COMPLETION.md`. Candidate and predictor execution remain separately gated.

The lifecycle-derived `m6d_w3b_execution_lock` has now materialized and verified the immutable 870-slot
execution manifest and 56-artifact input lock. `results/m6d_w3b_execution_lock_readiness.{json,md}` is
audit-clean and ready. The W3b evaluator requires its paired predictor MSA hash to equal the target-specific
hash in this execution manifest, closing the previous gap where two predictors could agree on the same
wrong MSA.

The downstream matched-record bridge is now executable without loosening that boundary.
`m6d_w3b_matched_records` verifies exact stage target/candidate counts, candidate and target sequences,
manifest-bound MSAs, per-predictor runtime identities, seed `0`, templates/network off, raw-record hashes,
and predictor-specific pAE/L-RMSD provenance before emitting evaluator input. It also blocks missing pairs
and near-total numeric copies. `results/m6d_w3b_matched_record_contract.{json,md}` is audit-clean with
`assembly_ready=true`; it authorizes no compute by itself.

2026-07-15 W3b runtime lock: `m6d_w3b_runtime_lock` freezes Boltz `2.2.1`, a canonical 116-file
installed-distribution manifest, both required local cache checkpoints, the verified W3 ColabFold 1.6.1
container, all five AF2-Multimer-v3 weight hashes, and exact predictor parameters. The tracked lock is
`configs/m6d_w3b_runtime_lock.json`; `results/m6d_w3b_runtime_lock_readiness.{json,md}` reports
`runtime_identity_ready=true` and `fit_packet_prerequisites_ready=true`. The matched-record path now
requires receipts to bind the exact runtime-lock SHA, lock digest, and predictor identity digest. This
closes runtime substitution. The initial fit and separate AF2-recovery approvals were each consumed once;
neither transfers to any successor experiment.

2026-07-15 W3b fit execution and terminal result: the historical W2b/W2c runners remain untouched. Dedicated W3b
ProteinMPNN validation, Boltz, AF2, runtime re-observation, conversion, guarded submission, and append-only
journal paths are now hash-bound by `m6d_w3b_fit_packet`. Candidate IDs and sequences must both be unique.
The complete synthetic-lock integration test materializes the three-target packet and dry-runs exactly
3 CPU plus 6 H100 jobs, 180 candidates, and 360 matched evaluations with zero scheduler calls or receipt
writes. The exact initial fit approval was then consumed once. ProteinMPNN jobs `3085447`, `3085450`, and
`3085453` and Boltz jobs `3085448`, `3085451`, and `3085454` completed. AF2 jobs `3085449`, `3085452`,
and `3085455` failed before prediction because the container could not resolve a relative `af2_inputs`
path. The separate exact recovery approval was then consumed once for replacements `3085544`-`3085546`.
All three completed `0:0`, yielding 180 AF2 records. Slurm rounded the requested `03:59:30` limits up to
`04:00:00`; all three live jobs were corrected to `03:59:00`, restoring an 86,258-second worst case and
142-second protocol margin. Actual H100 allocation was 16,641 seconds (`4.6225` hours). Strict matched
assembly passed 180/180 rows with local/Cayuga hash parity.

The frozen fit evaluator returned `w3b_fit_rule_not_found_stop`. No primary or comparator rule qualified.
`1FSK_LJ` was wrong on all 60 rows for both predictor endpoints, so the required 15 target accepts imply
a best-case `15/180 = 0.08333` global false-accept rate, already above the 0.08 cap. W3b therefore stops
before certification. No certification or held-out-test job was submitted. See
`docs/M6D_W3B_FIT_COMPLETION.md` and `results/m6d_w3b_fit_completion.json`.

2026-07-15 W3c validity-first reset: `m6d_w3c_target_validity` parses local RCSB `TITLE`, `COMPND`, and
`REMARK 350` records and checks selected-chain geometry for all 24 historical representatives. The audit
finds 5/24 complete author-determined two-chain assemblies and 3/24 strict target-binder systems. This is
a post-outcome diagnostic design reset, not a historical subgroup claim. The chosen successor asks whether
both frozen predictors can recover native complexes after the benchmark is restricted to prospectively
valid biological target-binder dimers. `configs/m6d_w3c_validity_first_protocol.json` freezes eight fresh
targets, strict representation criteria, a later MSA-only stage, and a later native-only 16-prediction
screen requiring at least 6/8 targets to pass both predictors at L-RMSD below 4.0 A. Each compute stage
requires a separate exact approval. The W3c-B1 packet now exists locally, but Cayuga no-submit validation is
pending and exact approval is not request-ready. See
`docs/M6D_W3C_VALIDITY_FIRST_PROTOCOL.md`, `results/m6d_w3c_target_validity_audit.{json,md}`, and the
public CPU replay fixture `tests/fixtures/m6d_w3c_historical_structure_fixture.json`.

2026-07-15 W3c-A completion: `m6d_w3c_fresh_target_lock` combines the 129-target/128-source historical
evidence registry with the 24 representative inputs, then excludes 153 target IDs, 152 RCSB sources, and
24 exact target-sequence hashes. The locked panel is `1TE1_BA`, `3QB4_AB`, `5E5M_AB`, `5JSB_AB`,
`6KBR_AC`, `6KMQ_AB`, `6SGE_AB`, and `7B5G_AB`. Each pair is a complete author-determined two-protein
dimer with distinct molecule entities, a manual target-binder semantic pass, at least 40 CA residues per
chain, no observed numbering gap, and at least 20 CA contacts. See `docs/M6D_W3C_A_TARGET_LOCK.md`,
`configs/m6d_w3c_fresh_targets.json`, and `results/m6d_w3c_fresh_target_lock.{json,md}`. This is an exact
source/hash and representation lock, not sequence-family disjointness or native-recoverability evidence.
The W3c-B1 packet is locally prepared and audit-clean. It binds the eight source/sequence locks, exact
execution paths, one-hour A40 Slurm resource, eight-query/8-A40-GPU-hour ceiling, and zero downstream
authority. Local dry-run and wrong/missing-approval refusal checks pass. Cayuga no-submit mirror validation,
exact approval, submission, and all target-MSA outputs remain absent.

M6c remains the foundational positive anchor. The complex/binder regime has the first positive
trust-gate result:

- target: barnase-barstar, 1BRS target chain A / binder chain D, with the known RCSB chain-D D64-D65
  numbering gap reviewed and recorded as a narrow manifest exception;
- protocol: target MSA plus binder single sequence;
- signal: `pAE_interaction`, not ipTM and not complex pLDDT;
- fixture: 192 redesign records in `tests/fixtures/barstar_interface_records.jsonl`;
- schema: the fixture is scale-current and passes strict QC with `complex_target_id`,
  `predictor_id`, `signal_source`, and `label_source`;
- gate: RCPS certifies `alpha=0.3` on the held-out split;
- frontier: `alpha<=0.2` is certified only for scoped t0.3 protocol branches so far, not for the full
  0.3/0.5/0.7 mixed-temperature distribution.

2026-06-29 protocol-branch update: after Cayuga round3, the canonical full mixed-temperature
0.3/0.5/0.7 evidence set remains `continue_scale` for `alpha=0.2` at 852 records, but a scoped
t0.3-only production protocol is now `stop_certified` for `alpha=0.2` at 220 records. Keep these
as separate claims: `results/m6c_project_status.json` is the full-mix status, while
`results/m6c_project_status_t030_protocol.json` and `results/m6c_protocol_branch_summary.{json,md}`
are the t0.3 branch certificate. That historical action ledger is superseded; resume from
`results/m6d_goal_state_refresh_report.{json,md}` for the current successor-design action priority.

2026-06-29 W4 update: `results/m6c_w4_round/summary.json` and
`results/m6c_w4_round/campaign.jsonl` now give a project-status-accepted
`closed_loop_round_complete`. It is a fail-closed campaign: the smoke DeBERTa screen produced non-finite
candidate scores, all 50 candidate verdicts escalated to human review, and the DBTL round routed every
candidate to `defer` with zero assay spend. Use
`results/m6c_w4_fail_closed_campaign_status.{json,md}` as the compact claim boundary.

2026-06-30 W3 smoke update: `results/m6c_w3_chai1_smoke_receipt.{json,md}` recorded that the Cayuga Chai-1
environment works, a Python API wrapper now saves pAE/PDE/pLDDT, and one 3PC8 Chai secondary record passed
strict complex-record QC. The one matched Boltz-vs-Chai pair disagrees on the L-RMSD success label, so this
was not W3 completion; it was a scale-up signal. The later M6d goal-mode update below supersedes the
temporary instruction to scale matched Chai records.

2026-06-30 M6d goal-mode update: the Chai scale-up fork has been resolved as a negative robustness result
under the selected no-MSA Chai adjudication protocol. The Chai records pass QC/contract, but matched
Boltz-vs-Chai label agreement is 0.600 against the required 0.800, so W3 independent-predictor robustness
is not supported. That negative interpretation is gated on strict comparison integrity: the only
cross-predictor failure kind is `label_agreement_below_min`, with no target-identity, provenance,
label-threshold, overlap, or numeric-copy blockers. W2 also has a completed known-pool screen with zero
non-anchor admissions. The active W2
branch is now fresh target discovery: `results/m6d_w2_fresh_discovery_pool.{json,md}` screened 10 public
RCSB seeds, selected 6 structural chain-pair candidates from 3 unique source PDBs, and emitted
`configs/m6d_w2_fresh_discovery_complex_targets.json` plus
`results/m6d_w2_fresh_discovery_target_msas.sh`. The six target-MSA jobs completed on Cayuga
(`3056468`-`3056473`), the `.a3m`/report files were synced back, and the full fresh manifest now passes
strict `--require-files`. To avoid source-redundancy drift, the branch tested a 3-target unique-source
pilot in `configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json`, with targets `1FQJ_EB`,
`1AK4_BC`, and `1A2K_CB`. The Cayuga pilot completed
(`3056479`/`3056480`, `3056481`/`3056482`, `3056483`/`3056484` for ProteinMPNN/Boltz) and synced back
300 records. `results/m6d_w2_fresh_discovery_unique_source_pilot_panel_report.json` is
`multi_target_evaluable_not_certified` at alpha=0.2: all three targets are not certified, `trusted=0`, and
no `tau` exists. `results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.{json,md}` classifies all
three as `target_protocol_mismatch_low_success` with zero accepts under the transferred t0.3 low-pAE
cutoff. The regenerated W2 candidate-pool screen now covers 12 known targets and still admits zero pilot
candidates. `results/m6d_w2_next_branch_design.{json,md}` now selects
`protocol_redesign_plus_success_enriched_discovery_v1` and emits
`configs/m6d_w2_next_branch_candidate_rules.json`; the rule config keeps
`spend_gate.cayuga_submission_allowed=false` until at least three non-anchor candidates pass the local
rule set and strict manifest preflight. Applying the rules to the 15-candidate local inventory admits zero
targets and marks `1A2K_DA`, `1A2K_EB`, and `1AK4_AD` as source-redundancy audit-only. This is a completed
negative pilot, not a missing-compute state or a W2 generalization certificate. A separate
`results/m6d_w2_source_redundancy_audit_plan.{json,md}` now exists for those audit-only targets, but it is
not Cayuga submission authority and not W2 generalization evidence; the default W2 path is expanded target
discovery beyond excluded sources.

Expanded source-diverse discovery has now moved that path through manifest preflight:
`results/m6d_w2_expanded_discovery_pool.{json,md}` screened 49 seed PDBs, scanned 248 chain pairs, admitted
17 structural candidates, and selected 10 candidates from 10 unique source PDBs. The first target-MSA
batch produced three ready targets and seven ColabFold MSA-server failures; the low-concurrency retry
completed the remaining targets. After sync-back, `results/m6d_w2_next_branch_candidate_pool.{json,md}`
covers 25 local inventory candidates with 10 admitted, 0 target-MSA-precompute-blocked, and three
source-redundancy audit-only leftovers. `results/m6d_w2_next_branch_manifest_design.{json,md}` freezes
the 10 admitted targets into `configs/m6d_w2_expanded_next_branch_targets.json`, and
`results/m6d_w2_expanded_next_branch_manifest.json` passes strict `--require-files` with 10/10 ready
targets and no failures. The expanded panel has now been submitted on Cayuga with job-id receipt capture:
ProteinMPNN/Boltz jobs are `3056559`-`3056578`, and receipt/summary are
`results/m6d_w2_expanded_next_branch_submit_receipt.jsonl` and
`results/m6d_w2_expanded_next_branch_submit_receipt_summary.json`, with status in
`results/m6d_w2_expanded_next_branch_submission_status.json`. Original Boltz job `3056576` for
`1QFW_BA` failed on a target-MSA/candidate sequence mismatch caused by a terminal atom-only residue; repair
job `3056582` completed and the repaired record is synced back. The expanded next-branch panel report is
`multi_target_evaluable_not_certified` at alpha=0.2 with 10 targets and 1000 records. This is completed
negative W2 evidence, not a generalization certificate, because all 10 target-wise certificates are
`not_certified`.

The known open limits are also part of the anchor:

- one completed-evidence target only;
- W2 now has the original 300-record panel (`1BRS_AD`, `2SIC_EI`, `1CGI_EI`), the completed
  400-record replacement panel (`1BRS_AD`, `3PC8_AB`, `1S1Q_CD`, `1SYX_AB`), and the completed
  500-record follow-up panel (`1BRS_AD`, `3PC8_AB`, `1MEL_MB`, `1GCQ_CB`, `2IDO_CD`), plus the completed
  300-record fresh-discovery unique-source pilot (`1FQJ_EB`, `1AK4_BC`, `1A2K_CB`), all
  `multi_target_evaluable_not_certified` at alpha=0.2; the 12-target known pool admits zero candidates for
  another current-protocol pilot; the latest 3PC8 mini-scale certifies
  `3PC8_AB` as a target-specific alpha=0.2 result, not a W2 generalization result;
- one production-scale complex predictor/label source only;
- W3 has completed no-MSA Chai scale-up records that pass QC/contract, but the cross-predictor audit fails
  the predeclared label-agreement requirement, so independent-predictor robustness remains unsupported;
- W4 closed-loop plumbing is complete only as a fail-closed/all-defer screen result, not as productive
  build/no-build routing;
- no RFdiffusion de-novo backbone generation yet;
- no live provider run until credential hygiene is clean;
- monomer pLDDT is not a fine per-design trust signal at fixed difficulty.

## Operating Principles

1. Measurement first. Negative results, refusals, and corrected claims are real
   progress.
2. The gate, not the orchestrator, owns trust. Claude may plan and interpret,
   but it does not decide whether a model is confident enough.
3. Expensive compute must be replayable from explicit inputs. Every model batch
   should reduce to input files, an sbatch command, JSONL outputs, and local
   posthoc checks.
4. Generalization requires per-target evidence. Pooled results are diagnostics,
   not proof.
5. The single-model caveat stays open until signal and label behavior survive
   an independent complex predictor.
6. Safety screening is a human-triage aid, not autonomous clearance.

## Workstreams

| Workstream | Purpose | Entry | Exit |
|---|---|---|---|
| W1: M6c scale-up | Tighten barnase-barstar from `alpha=0.3` toward `alpha<=0.2`. | Current fixture plus Cayuga records; cached target FASTA/MSA paths plus reports; Cayuga Boltz env. | Either a scoped protocol branch such as t0.3-only says `stop_certified` for target alpha after QC passes, or the canonical full-mix status remains `continue_scale`; bootstrap `complex_scale_projection.json` remains planning-only (`certifies_target_alpha=false`). |
| W2: Multi-target panel | Test whether the interface trust signal survives beyond barnase-barstar. | At least three clean heterodimer manifests with target FASTA/MSA reports and output paths. | `complex_panel_report.py` passes with per-target, single-predictor records and certificates under one matching L-RMSD threshold; pooled-only, mixed-predictor, or mixed-threshold evidence is insufficient. |
| W3: Independent predictor | Close or quantify the Boltz-only caveat. | A filled `configs/template_second_predictor_contract.json` copy plus matched records from a second complex predictor with stable `complex_target_id` + `target_id` keys and explicit signal/label sources. | `complex_predictor_contract.py --require-files --run-record-qc` passes with disjoint primary/secondary record paths, positive `min_overlap`, valid `min_label_agreement`, and strict disjoint record-file checking, then `complex_cross_predictor.py` passes labeled-overlap, same-threshold label agreement, target-identity, distinct-provenance, non-copied numeric-output, and per-JSONL predictor-membership checks; `complex_project_status.py` refuses older/non-strict cross reports without that audit. |
| W4: Closed-loop DBTL | Feed the complex evidence back into route/verify/learn decisions. | Synchronized candidates, records, verdicts, prior verified prevalidation records, and calibrated/conformal gate settings. | One async batch round runs through `run_batch_round.py --strict-complex-records --prevalidate-records ... --conformal-alpha ...` or a complex-specific successor, records complex-regime `tau`, proves prevalidation/current-batch predictor-source-label contract compatibility, and writes `preflight.json`, campaign artifacts, and route/verify/net summaries that project status accepts as calibrated W4 evidence. |
| W5: De-novo binders | Move beyond fixed-backbone ProteinMPNN interface redesign. | RFdiffusion or equivalent generator selected with license and HPC constraints checked. | Candidate JSONL uses the same bridge and can be evaluated by the complex posthoc/gate stack. |
| W6: Live orchestration | Let Claude plan/interprete between verified batch rounds. | P0 key rotation complete; provider seam configured; safety and label-integrity checks on. | Live provider run is reproducible, logged, and never bypasses the external trust/safety gates. |

W6 engineering update (2026-07-23): the provider seam is now executable in
default-shadow mode with an exact recommendation schema, bounded Anthropic and
OpenAI adapters, prompt/response audit logs, one-batch post-stop consultation,
and an offline one-call invariant smoke. JK then attested P0 credential hygiene
and authorized one Anthropic `claude-opus-4-8` shadow call. Transport,
structural JSON, routing equivalence, and no-effect checks passed, but semantic
authority failed because the model recommended changing the trust threshold.
Contract v2 rejects that response offline. This does not complete W6 or M7:
the hardened contract has not had a newly authorized live rerun, and productive
W4 scientific evidence remains separate from this orchestration plumbing.

W6-v2 offline-panel update (2026-07-23): 16 aggregate W2-W4 states are now
frozen by source-artifact SHA-256 and assertion, with balanced stop/continue and
explore/exploit labels, allowed evidence scopes, a human-review rubric, and
predeclared pass thresholds. The provider-free replay accepts the valid
synthetic fixture 16/16 with zero authority violations and rejects the
adversarial fixture with eight violations. API calls, provider calls, compute
submissions, and applied recommendations are all zero. This completes the
offline panel harness only; a live shadow panel still requires separate exact
approval and does not by itself complete M7. See
`docs/W6_V2_FROZEN_SHADOW_PANEL.md`.

## Milestone Ladder

| Milestone | Definition of done | Primary artifacts |
|---|---|---|
| M6c+ | Barnase-barstar scale-up certifies a tighter alpha target or gives a quantified next-n refusal. | `complex_posthoc_bundle.py`, `complex_alpha_decision.json`, merged records JSONL. |
| M6d | At least three heterodimer targets are prepared, run, and evaluated target-wise. | target manifest, prepared PDBs, target FASTAs/MSAs/reports, `complex_panel_report.json`. |
| M6e | Independent predictor comparison is available for matched complex candidates. | second-predictor records JSONL, `complex_cross_predictor` output. |
| M6f | Complex records are consumed by a DBTL campaign loop rather than only posthoc scripts. | campaign JSONL, summary JSON, route/verify/net comparison, W4 claim-boundary status artifact. |
| M7 | Live orchestrator participates in a gated batch campaign without owning trust decisions. | provider logs, safety verdicts, campaign artifacts, gate certificate. |
| M8 | New generator regime is added without changing the trust-gate contract. | RFdiffusion or equivalent candidate JSONL plus existing posthoc/gate outputs. |

## Stop/Go After Each Batch

Run these checks before spending the next GPU batch:

- QC: do all records pass schema, pAE, L-RMSD, target-id, provenance, duplicate, and interface checks?
- Strict QC: for any scale, panel, or second-predictor claim, do
  `complex_records_qc.py`, `complex_alpha_decision.py`, or `complex_posthoc_bundle.py` pass with
  `--require-complex-target-id --require-provenance --require-chain-ids`?
- Label threshold: do row-level `lrmsd_threshold` values match the posthoc/report `--threshold` before
  any tool recomputes `truth.correct`?
- Inputs: do target FASTA/MSA/report files exist, including declared/default `<target_fasta>.report.json`
  with `pdb`, `pdb_sha256`, `chain`, `out`, `out_sha256`, integer `length`, and `sequence`, plus
  declared/default `<target_msa>.report.json` with `ok=true`, `fasta`, `out`, integer
  `sequence_length`, `fasta_sha256`, and `out_sha256`, and does each MSA query match its explicit
  target FASTA?
- Risk: is the target alpha certified by RCPS, refused, or underpowered?
- Utility: does selective trust beat trust-all and verify-all on false accepts and assay cost?
- Provenance: can every row be tied to a target, predictor, signal source, label source, and input batch?
- Identity: do complex candidates and records preserve `complex_target_id`, with candidate ids unique within
  any DBTL round so controller dictionaries, screen verdicts, and prediction records cannot shadow each other?
- Generality: is the evidence target-wise, or only pooled?
- Panel provenance: is the panel a single predictor/signal/label source, with cross-predictor mixtures kept
  for `complex_cross_predictor.py`?
- Independence: are signal and label still from one predictor?
- Cross-predictor integrity: do matched predictor records have enough labeled overlap, same-threshold label
  agreement, and distinct `signal_source`/`label_source` provenance?
- Cross-predictor triage: did `complex_cross_predictor.py --emit-matches` write a matched-overlap JSONL
  so disagreements can be inspected target by target?
- Closed-loop preflight: before W4, does `run_batch_round.py` write an `ok=true` `preflight.json` proving
  candidate ids are covered by prediction records and provided screen verdicts, with strict complex-record
  QC enabled for complex/binder evidence, candidate-side `complex_target_id` present, and candidate-record
  target identity agreement checked? If calibrated routing is requested, are the prevalidation records
  prior evidence with no overlap against the current batch, is `--conformal-alpha` blocked unless
  those prior records are supplied, and does `batch_contract` show matching `predictor_id`,
  `signal_source`, `label_source`, and `lrmsd_threshold` by routed regime?

Use `complex_project_status.py` to summarize W1/W2/W3/W4 from JSON artifacts after each analysis pass.
It accepts post-Cayuga completion reports as intermediate evidence, so synced scale records can move W1
to `scale_records_ready_for_posthoc`; an unavailable/sentinel scale plan can move W1 to
`scale_waiting_on_input_prep`; target manifests missing only target-MSA/report artifacts can move W2 to
`panel_waiting_on_input_prep`; `complex_input_prep_completion.py` reports can refine W1/W2 to
`scale_input_prep_completion_blocked`, `scale_input_prep_ready_for_manifest`,
`panel_input_prep_completion_blocked`, or `panel_input_prep_ready_for_manifest`; and synced panel records
can move W2 to `panel_records_ready_for_report` before final posthoc/panel artifacts exist.
When W1 and W2 input-prep completion reports are both supplied, `--emit-pending-input-prep-paths` writes
a de-duplicated project-level copy list while the JSON status keeps the workstream and target provenance.
`--emit-sync-back-plan` turns that copy list into an explicit `rsync` pull script from
`CAYUGA_BIO_SFM_ROOT`. With W1/W2 readiness reports supplied, `--emit-post-sync-plan` also writes the
ordered local replay after sync-back: input-prep completion, readiness refresh, then project-status refresh.
For the combined W1/W2/W3/W4 external-artifact checklist, `--emit-external-remote-check-plan` writes a
lightweight `ssh test -s` preflight before the external sync-back script, so unfinished Cayuga jobs are
distinguished from local sync problems. The preflight writes a JSON report of per-path remote
present/missing status plus missing-by-workstream/category/target summaries, keeping failed bridge runs
auditable across Codex sessions. Status consumes that
report only when its path-count and SHA match the current pending checklist; only a fresh `ok=true` report
can advance the recommended bridge to external sync-back, and only when its `path_manifest` provenance
matches the current pending-path manifest, its status/counters/per-path records prove every current path is
present, and any required target-MSA precompute receipt is satisfied. Fresh
reports with missing remote artifacts keep the remote-check bridge recommended and add
fresh-report-derived `remote_missing_followups` for the upstream W1-W4 repair action. The remote-check
bridge also tries to sync the target-MSA precompute receipt back from Cayuga and records that handoff in
`target_msa_precompute_receipt_sync`, including local SHA-256 and byte size when the pull succeeds; if a
fresh all-present report lacks that receipt-sync evidence, status keeps the remote-check bridge recommended
before any target-MSA re-submit, while an attempted-but-unsynced receipt is surfaced as
`target_msa_receipt_sync_failed` for Cayuga receipt repair. A digest-free `synced=true` receipt report is
also stale repair-required evidence. The remote-check script checks the pending external path-list
fingerprint before receipt sync, so stale scripts fail before local side effects.
When a remote-check plan is emitted, the external sync bridge independently enforces the same proof before
`rsync`: the matching report must prove the current pending manifest is all-present, and any required
target-MSA receipt must already be satisfied in local status with the same receipt SHA that was validated
during status generation.
Before that report exists, `pending_external_summary` exposes the same pending checklist grouped by
workstream, category, target, artifact, and field, while `pending_external_followups` maps the checklist
to pre-remote W1-W4 repair actions.
When supplied with the raw W1/W2 manifests, status can also emit
`results/m6c_project_target_msa_precompute.sh`, a deduplicated target-MSA precompute bridge that renders
shared targets once before remote-check only when duplicated target ids share the same FASTA/MSA/report
material. Conflicting duplicate target ids fail closed as a local plan conflict before submit or receipt
initialization.
Named optional artifact paths that have not been generated yet are surfaced as explicit missing statuses
instead of crashing the roadmap audit, so the same status command can be run before, during, and after
Cayuga sync.
If a current W2 target manifest is not ready, that upstream input-prep or manifest blocker supersedes stale
panel-completion artifacts so status points to the earliest actionable fix.
It also accepts the second-predictor contract report as W3 intermediate evidence, so W3 can report
`second_predictor_contract_ready` or `second_predictor_contract_blocked` before a final cross-predictor
report exists. Blocked W3 status keeps `commands_available=false` and does not re-expose runnable
downstream commands from the blocked contract report.
For W4, it reads `run_batch_round.py` `preflight.json`, `summary.json`, and `campaign.jsonl`; W4 is complete
only when strict complex-record preflight passed, gate prevalidation has a compatible `batch_contract`, the
routed count matches the preflight candidate count, and the campaign JSONL is present, readable, and has the
same row count as the summary routed-candidate count, with non-empty unique `candidate_id` values that match
preflight candidate ids when recorded, known DBTL routing actions, and an action mix that matches any summary
aggregate action rates.
W1/W2 status is target-alpha scoped: alpha decisions, scale completions, panel completions, and panel
reports with a different `target_alpha` are mismatch states, not completed evidence for the requested alpha.

Allowed decisions:

- `stop_certified`: freeze that target/alpha condition and move to panel or predictor validation.
- `continue_scale`: run the next planned batch size from `complex_alpha_plan.py`.
- `run_scale_batch`: use `complex_alpha_decision.py`/`complex_posthoc_bundle.py` `next_batch`
  output to set per-temperature ProteinMPNN `NUM_SEQ`.
- `emit_scale_plan`: run `complex_next_batch_plan.py` so temp-specific candidate/record paths
  and generate-to-predict dependencies are explicit before submitting; use `--require-files`
  for real Cayuga submission so selected-target FASTA/MSA/report/prep preflight runs first and is
  replayed by the emitted shell plan before any `sbatch`. The planner refuses `run_scale_batch`
  decisions that were not produced with strict QC unless explicitly run with `--no-strict-qc` for
  legacy debugging; saved runnable scale plans also require `--require-files` unless
  `--allow-unchecked-files` is explicitly used for diagnostics.
- `complete_scale_batch`: after Cayuga jobs finish and records are synced back, run
  `complex_scale_completion.py --plan <next_batch_plan.json>` before posthoc so missing, empty, or
  target-mismatched JSONL outputs are caught as sync/completion failures instead of analysis surprises.
  Use `--new-records-only` for W1 synced-output checks when previous records are already trusted locally;
  the emitted shell plan preserves replay flags and target-id checking choices.
- `complete_input_prep`: after the target-MSA/input-prep plan runs on Cayuga and files are synced back,
  run `complex_input_prep_completion.py --report <target_manifest_report.json>` before rerunning
  `complex_target_manifest.py --require-files` or `complex_readiness.py --require-files`. This catches
  missing or empty source/prepared PDB, FASTA/MSA, and report files as sync failures before semantic
  manifest validation checks sequence and report hashes. Use its `pending_artifacts`, `blocked_targets`,
  and `artifacts_by_target` fields as the machine-readable sync checklist, or add `--emit-pending-paths`
  to write a one-path-per-line copy list for simple sync scripts.
- `preflight_readiness`: run `complex_readiness.py` to aggregate scale-plan, panel-manifest,
  second-predictor contract, and W4 closed-loop batch checks into one JSON/shell artifact before Cayuga
  or local DBTL spend; use
  `--emit-scale-plan` during W1 so the exact next-batch JSON used for submission is saved for
  `complex_scale_completion.py --plan`. If readiness is not scale-ready, that path is overwritten with an
  `ok=false`, `action=unavailable` sentinel so stale plans cannot be replayed. If readiness is scale-ready
  and would write a runnable saved plan, it requires `--require-files` unless `--allow-unchecked-files`
  is explicitly used for diagnostics; unchecked saved plans are marked `diagnostic_only` and completion
  reports surface that warning. Pass `--input-prep-completion` when that artifact exists so readiness carries target-wise sync-back
  blockers into its embedded roadmap status. When summarizing W1 and W2 together, pass separate
  `--scale-input-prep-completion` and `--panel-input-prep-completion` reports to
  `complex_project_status.py` so scale and panel sync blockers do not overwrite each other. Inspect
  `ordered_steps` so
  source PDB fetch/prep, target-MSA precompute, scale/panel submission, posthoc refresh,
  second-predictor follow-up, cross-predictor reporting, strict W4 batch routing, and status refresh stay
  in the intended order. For W4, pass synced `--batch-candidates`, `--batch-records`, optional
  `--batch-verdicts`, and `--batch-target`; readiness runs strict complex batch preflight and emits the
  `run_batch_round.py --strict-complex-records` command only when that preflight passes. Missing or empty
  batch/prevalidation JSONLs remain machine-readable in `preflight.json`, and
  calibrated W4 preflight also blocks predictor/source/threshold drift between prior prevalidation evidence
  and current batch records. `run_batch_round.py --emit-sync-back-plan` can turn missing artifacts into an
  `rsync` pull/retry script. When W4 is
  planned through readiness, pass `--batch-sync-back-plan` so that script path remains in the readiness
  JSON and shell plan. When refreshing the top-level dashboard, pass the same
  `--batch-sync-back-plan` to `complex_project_status.py` so status JSON/text and post-sync replay preserve
  the W4 sync/rerun pointer.
  For W3, pass `--predictor-sync-back-plan` to `complex_project_status.py` so missing second-predictor
  record blockers preserve their sync/rerun pointer in the same dashboard. Post-sync reruns W3 from the
  contract report's `self_command`, which regenerates the contract report, command plan, and sync-back
  plan; the direct W3 sync script keeps its own refresh command from rewriting the running script.
  W3/W4 direct sync scripts validate their own `<script>.manifest.json` sidecars before rsync so
  workstream-level replay fails closed if its pending-path manifest drifts, both direct scripts verify
  each pulled JSONL is non-empty before refreshing or rerunning the workstream, and neither direct script
  regenerates its own running shell file.
  Use `--emit-pending-external-paths` to keep one combined W1/W2/W3/W4 missing-artifact checklist for
  sync/replay audits, and `--emit-external-sync-back-plan` to turn that checklist into a one-command
  external pull bridge that delegates local W1-W4 reruns to the post-sync plan. Pending-path sidecar
  manifests carry path-count and SHA-256 fingerprints, and generated input-prep/external sync scripts
  check the current checklist before rsync.
  Generated sync steps also verify that each local pulled file is non-empty immediately after `rsync`.
  Bridge scripts derive the repo root from their own path, and post-sync replay bootstraps
  `BIO_SFM_PYTHON`, `PYTHONNOUSERSITE=1`, and local `PYTHONPATH` for fresh-shell reruns.
  Generated bridge/status artifacts are written by atomic replace, so replay can refresh bridge files
  without truncating a currently running parent shell script.
  The input-prep and external bridges failure-collect per-path `rsync` and post-sync steps so one missing
  remote artifact does not prevent later pulls or final status replay; stale checklist fingerprints still
  fail closed before any rsync.
  The post-sync plan failure-collects local replay steps so a partial sync still reaches later checks and
  final status refresh, then exits nonzero if any replay step failed. Treat
  `recommended_next_script` as the current first executable bridge; use `generated_scripts[*].manifest`
  plus `sync_manifest_audit` for a compact script freshness audit. With pending W1/W2 target MSAs, the first
  bridge is the deduplicated target-MSA precompute plan; after that, run the remote existence check, refresh
  project status with `results/m6c_project_remote_check.json`, and run the external sync-back bridge only
  after refreshed status recommends it. A complete `target_msa_precompute_receipt` marks the
  submit step satisfied only when it has exactly one accepted row per planned target, no unexpected target
  rows, a non-empty, whitespace-free `sbatch --parsable` job id for each `submitted` row, and FASTA/MSA/report paths plus manifest path/hash/workstream provenance matching the current raw manifests,
  then moves resumed sessions to
  remote-check; the remote-check bridge can pull that receipt back from Cayuga. The
  generated target-MSA bridge checks raw manifest hashes and `sbatch` before initializing that receipt, so
  stale rendered commands or accidental local execution fail before clobbering resume evidence, and it refuses to record a `submitted` row if
  `sbatch --parsable` returns an empty, whitespace-only, or whitespace-containing job id; a non-empty incomplete/invalid receipt blocks blind
  resubmission unless `TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1` is set after duplicate-job review;
  each rendered section self-validates its expected receipt subset, exact FASTA/MSA/report paths, and
  manifest/workstream provenance before exiting, and the project-level bridge runs a strict aggregate
  target-set/provenance receipt check before remote-check; conflicting duplicate target ids also block the
  recommended bridge before submit or receipt initialization. A failed audit blocks the recommended script before
  external replay. Use `resume_bridge_preflight` to distinguish a fresh bridge that is only `waiting_on_env`
  or `waiting_on_cayuga_session` from a structurally `blocked` bridge; it also records a non-executing
  `bash -n` syntax audit, with generated-script syntax failures surfaced as `bash_syntax_error`.
  For runnable/external-waiting bridges, preflight and the first ladder step carry the downstream
  remote-check/status-refresh continuation when required.
  `generated_script_syntax_audit` extends that check across every generated bridge, including later ladder
  steps that are not recommended yet; failures feed `goal_progress_audit.local_blockers`.
  Use `resume_execution_ladder` to follow the generated bridge sequence without rereading shell scripts; it
  marks remote-check, the non-shell `project_status_refresh` pseudo-step, external sync, and post-sync replay
  as satisfied, waiting, or blocked by a predecessor, and the status-refresh step names the exact
  `--external-remote-check-report` argument when the report path is known.
  `goal_progress_audit` is the goal-mode completion guard: it summarizes W1-W4 requirements, the first
  action, local/external blockers, and `can_mark_goal_complete`, so continuation does not confuse a fresh
  bridge blocker with project completion. It requires each workstream's canonical terminal status, not just
  a raw `complete=true`, plus a parseable non-empty evidence artifact whose content supports that terminal
  claim, W4 preflight/summary/campaign supporting artifacts when closed-loop completion is claimed, and a
  clear local/external blocker audit before the overall goal can complete. Top-level `goal_progress`, `remaining`, `remaining_requirements`,
  `can_mark_goal_complete`, and `goal_completion_note` mirror that compact resume state.
  Use top-level `operator_next_action`, `operator_next_command`, and `operator_next_role` as the resume
  instruction; `operator_next_action` also carries the downstream remote-check/status-refresh continuation
  when the ladder requires it. Top-level `next_action` is still the scientific workstream-level next action.
  For W1 with `--scale-target-id`, the target-MSA precompute section is selected-target scoped.
  If repairable missing/empty source/prep/FASTA/MSA/report files are the only W1/W2 issue, readiness reports
  `waiting_on_input_prep`; run the emitted `target_msa_precompute` section, then rerun readiness with
  `--require-files`. Missing source PDBs without `rcsb_id` or missing prepared PDBs with no source path
  stay `blocked`. If readiness reports `blocked`, use the terminal/shell-plan blocker lines and the
  structured `details.failures` entries rather than only the summary count to fix the hard failure.
  Prefer the project-level `results/m6c_project_target_msa_precompute.sh` when both W1 and W2 are waiting
  on target MSAs; it de-duplicates shared targets before the remote-check bridge only when their
  FASTA/MSA/report material matches.
  Readiness artifacts include a canonical `self_command` / `# rerun_readiness_after_prep` command; use it
  after input prep completes so stale arguments and stale scale-plan sentinels are replaced without carrying
  unrelated default W4 batch options.
- `emit_panel_plan`: run `complex_target_manifest.py --require-files --emit-plan` so each ready
  target gets explicit batch settings, the emitted shell plan replays manifest preflight before
  `sbatch`, and each Boltz job depends on its matching ProteinMPNN job.
  Use repeated `--target-id` arguments for W1 or staged-panel subset preflight without editing the manifest.
- `complete_panel_batch`: after panel jobs finish and records are synced back, run
  `complex_panel_completion.py --manifest <targets.json>` before `complex_panel_report.py` so missing,
  malformed, or target-id-mismatched per-target records are caught before panel claims. Use repeated
  `--target-id` arguments plus a matching `--min-targets` value for staged-panel completion checks; the
  emitted shell plan preserves the replay arguments.
- `change_axis`: switch from more records to more targets or a second predictor.
- `revise_metric`: if pAE stops discriminating after QC, inspect confounding before scaling.
- `abandon_regime`: if within-regime signal collapses and RCPS keeps refusing, preserve it as a negative result.

## Immediate Codex Cadence

1. Use `docs/M6D_W3C_VALIDITY_FIRST_PROTOCOL.md`, `docs/M6D_GOAL_MODE_ANCHOR.md`, and the refreshed goal-state
   artifacts as the current resume surface.
2. Preserve W2/W2b/W2c as completed negative evidence, W3 as `context_dependent_or_unresolved`, and W3b as
   `w3b_fit_complete_rule_not_found_terminal_stop`; do not rescue or retune any branch.
3. Submit no W3b certification, held-out-test, retry, or adaptive-top-up compute. The frozen fit stop makes
   those stages unreachable.
4. Preserve the 24-target validity audit as a diagnostic claim reset: only 5 pairs are complete dimers and
   only 3 are strict target-binder systems; do not turn those post-outcome annotations into subgroup claims.
5. Preserve the completed W3c-A eight-target representation lock; do not replace a target after predictor
   output or reinterpret exact hash exclusion as sequence-family disjointness.
6. Preserve the locally completed hash-bound W3c-B1 packet and run Cayuga no-submit mirror validation next.
   Request exact approval only after local/remote hash parity, dry-run exit `0`, zero submissions, and absent
   provenance outputs are confirmed. ProteinMPNN, native prediction, generator, gate, and certification work
   remain at zero.
7. Keep W1 as bounded target-specific evidence and W4 as fail-closed/all-defer plumbing evidence. Do not
   claim productive DBTL or universal robustness from the current negative sequence.

## File Map

- Context: `HANDOFF.md`
- Architecture: `docs/ARCHITECTURE.md`
- HPC bridge: `docs/HPC.md`, `hpc/README.md`
- M6c execution: `docs/M6C_RUNBOOK.md`
- Target panel template: `configs/template_complex_targets.json`
- W2 candidate panel: `configs/m6d_candidate_complex_targets.json`, `docs/M6D_CANDIDATE_PANEL.md`
- Posthoc bundle: `src/bio_sfm_designer/experiments/complex_posthoc_bundle.py`
- Alpha frontier: `src/bio_sfm_designer/experiments/complex_alpha_plan.py`,
  `src/bio_sfm_designer/experiments/complex_alpha_decision.py`
- Next scale batch: `src/bio_sfm_designer/experiments/complex_next_batch_plan.py`
- Scale completion: `src/bio_sfm_designer/experiments/complex_scale_completion.py`
- Project status: `src/bio_sfm_designer/experiments/complex_project_status.py`
- Readiness preflight: `src/bio_sfm_designer/experiments/complex_readiness.py`
- Panel validation: `src/bio_sfm_designer/experiments/complex_target_manifest.py`,
  `src/bio_sfm_designer/experiments/complex_panel_completion.py`,
  `src/bio_sfm_designer/experiments/complex_panel_report.py`
- Predictor validation: `configs/template_second_predictor_contract.json`,
  `src/bio_sfm_designer/experiments/complex_predictor_contract.py`,
  `src/bio_sfm_designer/experiments/complex_cross_predictor.py`
