#!/usr/bin/env bash
# Query W2 v11 panel Slurm states after guarded submission.
# This is read-only and does not submit jobs. It discovers job IDs from the submit receipt at runtime.
# Last rendered job-id preview: receipt not available yet
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
RECEIPT=results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl
OUT=${1:-results/m6d_w2_target_family_redesign_v11_sacct_states.tsv}
OUT_JSON=results/m6d_w2_target_family_redesign_v11_job_state_probe.json
OUT_MD=results/m6d_w2_target_family_redesign_v11_job_state_probe.md
test -s "$RECEIPT" || { echo "submit receipt is missing; run receipt monitor after guarded submit first: $RECEIPT" >&2; exit 2; }
mkdir -p "$(dirname "$OUT")"
mkdir -p "$(dirname "$OUT_JSON")" "$(dirname "$OUT_MD")"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe --receipt "$RECEIPT" --emit-query-plan "" --out-json "$OUT_JSON" --out-md "$OUT_MD"
job_ids="$("$PYTHON_BIN" - "$OUT_JSON" <<'PY'
import json
import sys
with open(sys.argv[1]) as handle:
    rep = json.load(handle)
ids = [str(job_id) for job_id in rep.get('job_ids', []) if str(job_id)]
if not ids:
    raise SystemExit('job-state query has no job IDs in the submit receipt')
print(','.join(ids))
PY
)"
sacct -P -j "$job_ids" --format=JobIDRaw,State,ExitCode,Elapsed,NodeList > "$OUT"
test -s "$OUT"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe --receipt "$RECEIPT" --sacct-output "$OUT" --sacct-output-path "$OUT" --emit-query-plan "" --out-json "$OUT_JSON" --out-md "$OUT_MD"
