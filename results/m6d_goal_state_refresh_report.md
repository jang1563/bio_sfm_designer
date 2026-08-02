# M6d Goal-State Refresh

Status: `goal_state_refreshed_w3c_b2_jobs_submitted_awaiting_results`.
Audit ok: `True`.
Runtime goal active: `False`.
W2b: `w2b_certification_terminal_not_supported`.
W2c current: `w2c_threshold_learning_terminal_not_supported`.
W2c design-gate snapshot: `w2c_design_power_qualified_no_submit`.
W2c target-MSA packet: `ready_for_explicit_target_msa_approval_not_submitted (historical; superseded by completion)`.
W2c target-MSA completion: `target_msa_precompute_complete_8_of_8`.
W2c fit-learn packet: `ready_for_explicit_w2c_fit_learn_approval_not_submitted`.
W2c fit-learn submission: `submitted_on_cayuga`.
W2c threshold-learning result: `w2c_threshold_learning_terminal_not_supported`.
W3 preregistration packet: `w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit (historical; superseded by completed adjudication)`.
W3 cases: `58`.
W3 preregistration runtime-ready field: `False`.
W3 preregistration execution-ready field: `False`.
W3 completion: `w3_mechanism_panel_adjudicated_context_dependent_or_unresolved`.
W3 joint outcome: `context_dependent_or_unresolved`.
W3b: `w3b_fit_complete_rule_not_found_terminal_stop`.
W3b initial fit approval recorded: `True`.
W3b initial fit jobs submitted: `9`.
W3b ProteinMPNN completed: `3`.
W3b Boltz completed: `3`.
W3b AF2 failed before prediction: `3`.
W3b AF2 recovery: `w3b_fit_af2_recovery_completed`.
W3b AF2 recovery approval recorded: `True`.
W3b AF2 recovery jobs submitted: `3`.
W3b fit completion: `w3b_fit_complete_rule_not_found_terminal_stop`.
W3b certification reachable: `False`.
W3c target validity: `w3c_target_validity_reset_complete_fresh_target_discovery_required`.
W3c historical complete dimers: `5`.
W3c historical strict target-binders: `3`.
W3c-A fresh target lock: `w3c_a_fresh_target_representation_lock_complete_no_submit`.
W3c-A fresh targets locked: `8`.
W3c-B1 target-MSA packet: `w3c_b1_packet_cayuga_validated_ready_for_exact_approval (historical; approval consumed; superseded by completion)`.
W3c-B1 approval recorded: `True`.
W3c-B1 queries authorized: `8`.
W3c-B1 completion: `target_msa_precompute_complete_8_of_8`.
W3c-B1 target MSAs complete: `8`.
W3c-B1 A40 GPU-hours: `1.1511111111111112`.
W3c-B2: `w3c_b2_all_sixteen_prediction_jobs_submitted`.
W3c-B2 runtime ready: `True`.
W3c-B2 Cayuga no-submit validation: `True`.
W3c-B2 approval recorded: `True`.
W3c-B2 predictor jobs submitted: `16`.
Cayuga submission allowed: `False`.

## Updated Artifacts

- `results/m6d_goal_mode_current_anchor.json`
- `results/m6d_goal_completion_audit.json`
- `results/m6d_goal_completion_audit.md`
- `results/m6d_goal_drift_audit.json`
- `results/m6d_goal_drift_audit.md`
- `results/m6d_followup_next_science_actions.json`
- `results/m6d_followup_next_science_actions.md`
- `results/m6d_goal_mode_local_harness_status.json`
- `results/m6d_goal_mode_local_harness_status.md`
- `configs/m6d_w3c_target_semantic_annotations.json`
- `configs/m6d_w3c_validity_first_protocol.json`
- `docs/M6D_W3C_VALIDITY_FIRST_PROTOCOL.md`
- `tests/fixtures/m6d_w3c_historical_structure_fixture.json`
- `results/m6d_w3c_target_validity_audit.json`
- `results/m6d_w3c_target_validity_audit.md`
- `configs/m6d_w3c_fresh_target_candidates.json`
- `configs/m6d_w3c_historical_overlap_registry.json`
- `configs/m6d_w3c_fresh_targets.json`
- `tests/fixtures/m6d_w3c_fresh_structure_fixture.json`
- `results/m6d_w3c_fresh_target_lock.json`
- `results/m6d_w3c_fresh_target_lock.md`
- `configs/m6d_w3c_b1_target_msa_manifest.json`
- `results/m6d_w3c_b1_target_manifest_pre_msa.json`
- `results/m6d_w3c_b1_target_msas.sh`
- `hpc/run_w3c_b1_target_msa_guarded.sh`
- `results/m6d_w3c_b1_target_msa_approval_packet.json`
- `results/m6d_w3c_b1_target_msa_approval_packet.md`
- `results/m6d_w3c_b1_cayuga_no_submit_validation.json`
- `results/m6d_w3c_b1_target_msa_completion.json`
- `results/m6d_w3c_b1_target_msa_completion.md`
- `configs/m6d_w3c_b2_native_screen_manifest.json`
- `configs/m6d_w3c_b2_runtime_lock.json`
- `results/m6d_w3c_b2_runtime_readiness.json`
- `results/m6d_w3c_b2_prediction_packet_readiness.json`
- `results/m6d_w3c_b2_prediction_approval_packet.json`
- `results/m6d_w3c_b2_cayuga_no_submit_validation.json`
- `docs/M6D_W3C_B2_NATIVE_SCREEN.md`
- `results/m6d_w3c_b2_submit_receipt.jsonl`
- `results/m6d_w3c_b2_submit_receipt_summary.json`

## Next Action

Wait for only the sixteen receipt-bound Slurm jobs to reach terminal states, without retry or adaptive top-up. Then preserve Slurm accounting, sync the exact bound outputs, assemble all sixteen strict-QC records, and apply the frozen both-predictors and at-least-6-of-8 rule.
