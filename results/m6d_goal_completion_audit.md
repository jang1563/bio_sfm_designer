# M6d Goal Completion Audit

Status: `goal_active_w3b_fit_terminal_successor_preregistration_required`.
Audit ok: `True`.
Can mark goal complete: `False`.

## Current Boundary

- W2b: `w2b_certification_terminal_not_supported`
- W2c current: `w2c_threshold_learning_terminal_not_supported`
- W2c design-gate snapshot: `w2c_design_power_qualified_no_submit`
- W2c execution ready: `False`
- W2c Cayuga submission allowed: `False`
- W2c target-MSA packet: `ready_for_explicit_target_msa_approval_not_submitted (historical; superseded by completion)`
- W2c target-MSA completion: `target_msa_precompute_complete_8_of_8`
- W2c fit-learn packet: `ready_for_explicit_w2c_fit_learn_approval_not_submitted`
- W2c fit-learn submission: `submitted_on_cayuga`
- W2c threshold-learning result: `w2c_threshold_learning_terminal_not_supported`
- W3 preregistration packet: `w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit (historical; superseded by completed adjudication)`
- W3 preregistration runtime-ready field: `False`
- W3 preregistration execution-ready field: `False`
- W3 completion: `w3_mechanism_panel_adjudicated_context_dependent_or_unresolved`
- W3 joint outcome: `context_dependent_or_unresolved`
- W3b: `w3b_fit_complete_rule_not_found_terminal_stop`
- W3b initial fit approval recorded: `True`
- W3b initial fit jobs submitted: `9`
- W3b ProteinMPNN completed: `3`
- W3b Boltz completed: `3`
- W3b AF2 failed before prediction: `3`
- W3b AF2 recovery: `w3b_fit_af2_recovery_completed`
- W3b AF2 recovery approval recorded: `True`
- W3b AF2 recovery jobs submitted: `3`
- W3b fit completion: `w3b_fit_complete_rule_not_found_terminal_stop`
- W3b certification reachable: `False`
- remaining requirement: `W3b_successor_scientific_question_and_preregistration`

Historical W2 v9/v11 panel fields retained in the JSON are superseded and are not current routes.

## Next Action

Preserve W3b as a terminal negative fit result and submit no certification or held-out-test compute. Use the target-level failure pattern only to choose and preregister a distinct successor question; do not retune the frozen W3b thresholds or rescue this experiment.
