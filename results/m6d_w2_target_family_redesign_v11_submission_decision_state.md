# M6d W2 v11 Submission Decision State

Status: `awaiting_explicit_panel_submission_approval`.
Decision: `awaiting_explicit_approval`.
Audit ok: `True`.
No submit: `True`.
Submitted: `False`.
Explicit approval required: `True`.
Can submit if explicitly approved: `True`.
Can claim W2 generalization: `False`.

## Prerequisites

| prerequisite | ok | status |
|---|---:|---|
| approval_packet | True | panel_approval_packet_ready |
| panel_decision_protocol | True | post_panel_decision_protocol_ready |
| remote_submission_readiness | True | remote_submission_readiness_ok |
| project_status | True | m6_complex_in_progress |
| goal_completion_audit | True | goal_active_w2_remaining |
| goal_drift_audit | True | no_major_direction_drift_w2_blocked |

## Receipt Absence

- local `results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl` exists: `False`
- local `results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json` exists: `False`
- remote checked: `<hpc-login-host>:/home/fs01/<user>/bio_sfm_smoke`
- remote `results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl` exists: `False`
- remote `results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json` exists: `False`

## Approval Boundary

- required env: `BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit`
- submit command if explicitly approved:

```bash
ssh <hpc-login-host> 'cd /home/fs01/<user>/bio_sfm_smoke && BIO_SFM_PYTHON=/home/fs01/<user>/.conda/envs/boltz/bin/python PYTHONNOUSERSITE=1 BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit bash results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh'
```

Postsubmit sync-ready gate before record sync-back:

```bash
python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json --receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl --summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json --job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json --require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
```

This artifact does not submit jobs and does not create W2 evidence.

## Approval Disambiguation

- continuation phrases are approval: `False`
- approval must explicitly name: `W2 v11 Cayuga ProteinMPNN/Boltz panel submission`
- machine gate: `BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit`
- non-approval continuation phrases: `resume goal`, `resume goal mode`, `goal mode resume`, `go ahead`, `continue`, `continue working toward the active thread goal`, `keep going`, `이어서`, `계속`

## Next Action

await explicit user approval before running submit_command_if_approved
