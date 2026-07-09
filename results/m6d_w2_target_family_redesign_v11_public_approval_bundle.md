# W2 v11 Public Approval Bundle

Status: `public_approval_bundle_ready_not_submitted`.
Audit ok: `True`.
No submit: `True`.
Can claim W2 generalization: `False`.

## Approval Boundary

- explicit approval required: `True`
- approval must name: `W2 v11 Cayuga ProteinMPNN/Boltz panel submission`
- continuation phrases are approval: `False`
- machine gate: `BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit`

## Portable Commands

### setup_environment

```bash
export CAYUGA_BIO_SFM_HOST=<hpc-login-host>
export CAYUGA_BIO_SFM_REMOTE_ROOT=<remote-repo-root>
export CAYUGA_BIO_SFM_ROOT="$CAYUGA_BIO_SFM_HOST:$CAYUGA_BIO_SFM_REMOTE_ROOT"
export BIO_SFM_PYTHON=<python-with-boltz-and-proteinmpnn-runtime>
```

### submit_if_explicitly_approved

```bash
ssh "$CAYUGA_BIO_SFM_HOST" "cd \"$CAYUGA_BIO_SFM_REMOTE_ROOT\" && BIO_SFM_PYTHON=\"$BIO_SFM_PYTHON\" PYTHONNOUSERSITE=1 BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit bash results/m6d_w2_target_family_redesign_v11_submit_with_receipt.sh"
```

### receipt_monitor_after_submit

```bash
bash results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh
```

### postsubmit_driver_after_submit

```bash
bash results/m6d_w2_target_family_redesign_v11_postsubmit_driver.sh
```

### job_state_query_after_receipt

```bash
ssh "$CAYUGA_BIO_SFM_HOST" "cd \"$CAYUGA_BIO_SFM_REMOTE_ROOT\" && bash results/m6d_w2_target_family_redesign_v11_job_state_query.sh"
```

### sync_job_state_probe_after_query

```bash
mkdir -p results && rsync -avP "$CAYUGA_BIO_SFM_ROOT/results/m6d_w2_target_family_redesign_v11_job_state_probe.json" results/m6d_w2_target_family_redesign_v11_job_state_probe.json && rsync -avP "$CAYUGA_BIO_SFM_ROOT/results/m6d_w2_target_family_redesign_v11_sacct_states.tsv" results/m6d_w2_target_family_redesign_v11_sacct_states.tsv
```

### strict_postsubmit_status_before_sync

```bash
python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json --receipt results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl --summary results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json --job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json --require-sync-ready --out-json results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
```

### sync_back_after_sync_ready

```bash
bash results/m6d_w2_target_family_redesign_v11_sync_back.sh
```

### completion_after_sync

```bash
bash results/m6d_w2_target_family_redesign_v11_panel_completion.sh
```

### postsync_replay

```bash
bash results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh
```

## Post-Approval Workflow

- manual step count: `9`
- all manual commands present: `True`
- sync-ready gate before record sync: `True`
- includes post-sync interpretation: `True`
- driver proceeds only when sync-ready: `True`

- 1. `setup_environment` (command present: `True`)
- 2. `submit_if_explicitly_approved` (command present: `True`)
- 3. `receipt_monitor_after_submit` (command present: `True`)
- 4. `job_state_query_after_receipt` (command present: `True`)
- 5. `sync_job_state_probe_after_query` (command present: `True`)
- 6. `strict_postsubmit_status_before_sync` (command present: `True`)
- 7. `sync_back_after_sync_ready` (command present: `True`)
- 8. `completion_after_sync` (command present: `True`)
- 9. `postsync_replay` (command present: `True`)

## Postsubmit Driver Polling

```text
{"default_max_polls": 120, "default_poll_seconds": 300, "max_polls_env_var": "M6D_W2_POSTSUBMIT_MAX_POLLS", "poll_seconds_env_var": "M6D_W2_POSTSUBMIT_POLL_SECONDS", "proceeds_only_when_sync_ready": true, "sync_ready_gate": "m6d_w2_panel_postsubmit_status.sync_ready"}
```

## Prerequisites

- remote readiness status: `remote_submission_readiness_ok`
- remote exact checks: `25`
- remote shell syntax checks: `10`
- remote shell syntax checks ok: `True`
- remote failures: `0`

## Claim Boundary

not W2 evidence until explicit approval, successful submit receipt, completed jobs, sync-back, completion, target-wise report, and refreshed interpretation

## Failures

- none

## Next Action

await explicit approval before using submit_if_explicitly_approved; otherwise keep no-submit state
