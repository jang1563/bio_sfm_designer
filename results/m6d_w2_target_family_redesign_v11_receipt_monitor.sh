#!/usr/bin/env bash
# Pull only W2 v11 submit receipt/summary before record sync-back.
# This is read-only with respect to Cayuga jobs and does not submit work.
set -euo pipefail
REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT to user@host:/path}"
LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
RECEIPT=results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl
SUMMARY=results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json
mkdir -p "$LOCAL_ROOT/results"
for relpath in "$RECEIPT" "$SUMMARY"; do
  rsync -avP "$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"
  test -s "$LOCAL_ROOT/$relpath"
done
cd "$LOCAL_ROOT"
export PYTHONPATH="${PYTHONPATH:-src}"
PYTHONNOUSERSITE=1 "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe
