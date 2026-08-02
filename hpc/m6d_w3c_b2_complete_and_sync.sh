#!/usr/bin/env bash
# Read Slurm accounting, unlock exact retrieval, and replay W3c-B2 locally.
set -euo pipefail

REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"
REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT}"
LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
PACKET="results/m6d_w3c_b2_prediction_approval_packet.json"
RECEIPT="results/m6d_w3c_b2_submit_receipt.jsonl"
SUMMARY="results/m6d_w3c_b2_submit_receipt_summary.json"
SACCT="results/m6d_w3c_b2_sacct.tsv"
ACCOUNTING="results/m6d_w3c_b2_completion_accounting.json"
ACCOUNTING_MD="results/m6d_w3c_b2_completion_accounting.md"
MODULE="bio_sfm_designer.experiments.m6d_w3c_b2_completion"

cd "$LOCAL_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$LOCAL_ROOT/../bio-sfm-trust-core/src}"
if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then
  export PYTHONPATH="$LOCAL_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$LOCAL_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"

job_ids="$("$PYTHON_BIN" -m "$MODULE" job-ids \
  --packet "$PACKET" --receipt "$RECEIPT")"
case "$job_ids" in
  (*[!0-9,_]*) echo "invalid W3c-B2 job-id list" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$SACCT")"
sacct_tmp="$SACCT.tmp"
remote_query="sacct -P -j '$job_ids' --format=JobIDRaw,JobName,State,ExitCode,ElapsedRaw,ReqTRES,AllocTRES,NodeList,Start,End"
ssh "$REMOTE_HOST" "$remote_query" > "$sacct_tmp"
test -s "$sacct_tmp"
mv "$sacct_tmp" "$SACCT"

"$PYTHON_BIN" -m "$MODULE" account \
  --packet "$PACKET" --receipt "$RECEIPT" --summary "$SUMMARY" \
  --sacct "$SACCT" --out-json "$ACCOUNTING" --out-md "$ACCOUNTING_MD" \
  --require-sync-ready

sync_roots="$("$PYTHON_BIN" -m "$MODULE" sync-roots --packet "$PACKET")"
while IFS= read -r target_root; do
  [ -n "$target_root" ] || continue
  mkdir -p "$LOCAL_ROOT/$target_root"
  rsync -aP \
    "$REMOTE_HOST:$REMOTE_ROOT/$target_root/" \
    "$LOCAL_ROOT/$target_root/"
done <<< "$sync_roots"

"$PYTHON_BIN" -m "$MODULE" finalize --accounting "$ACCOUNTING"
echo "W3c-B2 exact outputs synced and the frozen native-recoverability rule replayed."
