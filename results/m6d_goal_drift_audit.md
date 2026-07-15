# M6d Goal Drift Audit

Status: `no_major_direction_drift_w3b_af2_path_recovery_approval_wait`.
Audit ok: `True`.
Major direction drift: `False`.

## Assessment

- mission: `no_drift_external_calibrated_trust_gate_north_star_preserved`
- protocol: `no_drift_initial_failure_preserved_path_only_recovery_separately_gated`
- claims: `no_drift_fit_incomplete_no_w3b_claim`
- execution: `initial_9_jobs_terminal_af2_recovery_packet_ready_not_approved_no_submit`
- operational status: `current_surfaces_reconciled_to_af2_recovery_approval_gate`

## Active Risks

- `w3b_initial_approval_reuse` (managed): the consumed nine-job approval cannot authorize the three recovery jobs
- `w3b_successful_producer_rerun` (managed): the recovery packet authorizes zero ProteinMPNN and zero Boltz jobs
- `w3b_gpu_budget_drift` (managed): 38 failed AF2 GPU-seconds are retained and recovery walltime keeps the worst case below 24 H100 hours
- `w3b_partial_output_overwrite` (managed): candidate, A3M, manifest, runtime, and empty-output hashes are packet-bound and fail closed on drift

## Next Action

Wait for exact user approval: approve W3b AF2 fit recovery for failed jobs 3085449,3085452,3085455 on H100. Generic continuation and the consumed initial fit approval do not authorize recovery; no ProteinMPNN, Boltz, certification, held-out-test, adaptive-top-up, or claim authority is included.
