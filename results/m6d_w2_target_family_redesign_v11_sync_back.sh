#!/usr/bin/env bash
# Sync completed W2 panel records back from Cayuga, then replay the local completion gate.
# Run only after the submitted Boltz jobs in the submit receipt have finished.
set -euo pipefail

REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}"
LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
MANIFEST=configs/m6d_w2_target_family_redesign_v11_representative_targets.json
COMPLETION=results/m6d_w2_target_family_redesign_v11_panel_completion.sh
RECEIPT=results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl
SUMMARY=results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json
POSTSUBMIT=results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
JOB_STATES=results/m6d_w2_target_family_redesign_v11_job_state_probe.json
SACCT_STATES=results/m6d_w2_target_family_redesign_v11_sacct_states.tsv
export MANIFEST

test -s "$MANIFEST" || { echo "manifest is missing or empty: $MANIFEST" >&2; exit 2; }
test -s "$COMPLETION" || { echo "completion script is missing or empty: $COMPLETION" >&2; exit 2; }
test -s "$RECEIPT" || { echo "submit receipt is missing locally; run receipt monitor first: $RECEIPT" >&2; exit 2; }
test -s "$SUMMARY" || { echo "submit summary is missing locally; run receipt monitor first: $SUMMARY" >&2; exit 2; }
mkdir -p "$LOCAL_ROOT/$(dirname "$JOB_STATES")"
rsync -avP "$REMOTE_ROOT/$JOB_STATES" "$LOCAL_ROOT/$JOB_STATES" || { echo "remote job-state probe is missing; run the job-state query bridge first: $JOB_STATES" >&2; exit 2; }
mkdir -p "$LOCAL_ROOT/$(dirname "$SACCT_STATES")"
rsync -avP "$REMOTE_ROOT/$SACCT_STATES" "$LOCAL_ROOT/$SACCT_STATES" || true
test -s "$JOB_STATES" || { echo "job-state probe is missing locally; run the job-state query/probe before sync-back: $JOB_STATES" >&2; exit 2; }

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest "$MANIFEST" --receipt "$RECEIPT" --summary "$SUMMARY" --job-states "$JOB_STATES" --require-sync-ready --out-json "$POSTSUBMIT"

record_paths="$("$PYTHON_BIN" - <<'PY'
import json, os
with open(os.environ["MANIFEST"]) as handle:
    manifest = json.load(handle)
for target in manifest.get("targets", []):
    if not isinstance(target, dict):
        continue
    target_id = str(target.get("id", "target"))
    out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
    records = str(target.get("records") or f"{out_prefix}/records_boltz_complex.jsonl")
    if records:
        print(records)
PY
)"

if [ -z "$record_paths" ]; then
  echo "manifest has no record paths: $MANIFEST" >&2
  exit 2
fi

while IFS= read -r relpath; do
  if [ -z "$relpath" ]; then
    continue
  fi
  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"
  rsync -avP "$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"
  test -s "$LOCAL_ROOT/$relpath"
done <<< "$record_paths"

mkdir -p "$LOCAL_ROOT/results"
rsync -avP "$REMOTE_ROOT/$RECEIPT" "$REMOTE_ROOT/$SUMMARY" "$LOCAL_ROOT/results/"
test -s "$LOCAL_ROOT/$RECEIPT"
test -s "$LOCAL_ROOT/$SUMMARY"

BIO_SFM_PYTHON="$PYTHON_BIN" PYTHONNOUSERSITE=1 bash "$COMPLETION"
