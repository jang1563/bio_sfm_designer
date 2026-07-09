#!/usr/bin/env bash
# Drive the W2 v11 post-submit ladder after an explicitly approved guarded submit.
# This script never submits jobs; it requires an existing submit receipt.
set -euo pipefail

REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"
REMOTE_PATH="${CAYUGA_BIO_SFM_REMOTE_ROOT:?set CAYUGA_BIO_SFM_REMOTE_ROOT}"
REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:-$REMOTE_HOST:$REMOTE_PATH}"
LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
RECEIPT_MONITOR=results/m6d_w2_target_family_redesign_v11_receipt_monitor.sh
JOB_STATE_QUERY=results/m6d_w2_target_family_redesign_v11_job_state_query.sh
POSTSYNC_REPLAY=results/m6d_w2_target_family_redesign_v11_postsync_interpretation.sh
MANIFEST=configs/m6d_w2_target_family_redesign_v11_representative_targets.json
RECEIPT=results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl
SUMMARY=results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json
POSTSUBMIT=results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
JOB_STATES=results/m6d_w2_target_family_redesign_v11_job_state_probe.json
SACCT_STATES=results/m6d_w2_target_family_redesign_v11_sacct_states.tsv
MAX_POLLS="${M6D_W2_POSTSUBMIT_MAX_POLLS:-120}"
POLL_SECONDS="${M6D_W2_POSTSUBMIT_POLL_SECONDS:-300}"

cd "$LOCAL_ROOT"
test -s "$RECEIPT_MONITOR" || { echo "receipt monitor script is missing: $RECEIPT_MONITOR" >&2; exit 2; }
test -s "$JOB_STATE_QUERY" || { echo "job-state query script is missing: $JOB_STATE_QUERY" >&2; exit 2; }
test -s "$POSTSYNC_REPLAY" || { echo "post-sync replay script is missing: $POSTSYNC_REPLAY" >&2; exit 2; }
test -s "$MANIFEST" || { echo "manifest is missing: $MANIFEST" >&2; exit 2; }

poll=1
while :; do
  echo "W2 v11 postsubmit poll ${poll}/${MAX_POLLS}"
  CAYUGA_BIO_SFM_ROOT="$REMOTE_ROOT" LOCAL_BIO_SFM_ROOT="$LOCAL_ROOT" BIO_SFM_PYTHON="$PYTHON_BIN" bash "$RECEIPT_MONITOR"
  remote_cmd="$(printf 'cd %q && bash %q' "$REMOTE_PATH" "$JOB_STATE_QUERY")"
  ssh "$REMOTE_HOST" "$remote_cmd"
  mkdir -p "$LOCAL_ROOT/$(dirname "$JOB_STATES")" "$LOCAL_ROOT/$(dirname "$SACCT_STATES")"
  rsync -avP "$REMOTE_ROOT/$JOB_STATES" "$LOCAL_ROOT/$JOB_STATES"
  rsync -avP "$REMOTE_ROOT/$SACCT_STATES" "$LOCAL_ROOT/$SACCT_STATES"
  test -s "$LOCAL_ROOT/$JOB_STATES"
  test -s "$LOCAL_ROOT/$SACCT_STATES"
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest "$MANIFEST" --receipt "$RECEIPT" --summary "$SUMMARY" --job-states "$JOB_STATES" --out-json "$POSTSUBMIT"
  sync_ready="$("$PYTHON_BIN" - "$POSTSUBMIT" <<'PY'
import json, sys
with open(sys.argv[1]) as handle:
    rep = json.load(handle)
print('true' if rep.get('sync_ready') is True else 'false')
PY
)"
  if [ "$sync_ready" = "true" ]; then
    break
  fi
  if [ "$poll" -ge "$MAX_POLLS" ]; then
    echo "postsubmit jobs are not sync-ready after ${MAX_POLLS} poll(s); leaving no-submit status for inspection: $POSTSUBMIT" >&2
    exit 2
  fi
  sleep "$POLL_SECONDS"
  poll=$((poll + 1))
done

BIO_SFM_PYTHON="$PYTHON_BIN" PYTHONNOUSERSITE=1 bash "$POSTSYNC_REPLAY"
