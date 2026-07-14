#!/usr/bin/env bash
# Pull only W3b target input-prep artifacts and replay strict CPU validation.
# This script never submits jobs and never pulls candidate-level predictor output.
set -euo pipefail
REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:?set CAYUGA_BIO_SFM_HOST}"
REMOTE_ROOT="${CAYUGA_BIO_SFM_ROOT:-bio_sfm_smoke}"
LOCAL_ROOT="${LOCAL_BIO_SFM_ROOT:-$(pwd)}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
MANIFEST=configs/m6d_w3b_fresh_targets.json
PACKET=results/m6d_w3b_target_msa_approval_packet.json
RECEIPT=results/m6d_w3b_target_msa_receipt.jsonl
SUMMARY=results/m6d_w3b_target_msa_receipt_summary.json
SACCT=results/m6d_w3b_target_msa_sacct.tsv
QUERY=results/m6d_w3b_target_msa_job_state_query.sh
OUT_JSON=results/m6d_w3b_target_msa_lifecycle.json
OUT_MD=results/m6d_w3b_target_msa_lifecycle.md
cd "$LOCAL_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$LOCAL_ROOT/../bio-sfm-trust-core/src}"
if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then
  export PYTHONPATH="$LOCAL_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$LOCAL_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
printf -v remote_command 'cd %q && BIO_SFM_PYTHON=$HOME/.conda/envs/boltz/bin/python PYTHONNOUSERSITE=1 bash %q' "$REMOTE_ROOT" "$QUERY"
ssh "$REMOTE_HOST" "$remote_command"
for relpath in "$RECEIPT" "$SUMMARY" "$SACCT" "$OUT_JSON"; do
  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"
  rsync -avP "$REMOTE_HOST:$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"
  test -s "$LOCAL_ROOT/$relpath"
done
jobs_ready="$("$PYTHON_BIN" - "$OUT_JSON" <<'PY'
import json
import sys
with open(sys.argv[1]) as handle:
    report = json.load(handle)
print('1' if report.get('jobs_terminal_success') else '0')
PY
)"
test "$jobs_ready" = 1 || { echo "W3b target-MSA jobs are not all terminal-success; do not sync inputs yet" >&2; exit 2; }
artifact_paths="$("$PYTHON_BIN" - "$MANIFEST" <<'PY'
import json
import sys
with open(sys.argv[1]) as handle:
    manifest = json.load(handle)
fields = ('source_pdb', 'prepared_pdb', 'prep_report', 'target_fasta', 'target_fasta_report', 'target_msa', 'target_msa_report')
seen = set()
for target in manifest.get('targets', []):
    for field in fields:
        value = target.get(field)
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            print(value)
PY
)"
while IFS= read -r relpath; do
  [ -n "$relpath" ] || continue
  mkdir -p "$LOCAL_ROOT/$(dirname "$relpath")"
  rsync -avP "$REMOTE_HOST:$REMOTE_ROOT/$relpath" "$LOCAL_ROOT/$relpath"
  test -s "$LOCAL_ROOT/$relpath"
done <<< "$artifact_paths"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_target_msa_lifecycle --manifest "$MANIFEST" --approval-packet "$PACKET" --receipt "$RECEIPT" --summary "$SUMMARY" --sacct "$SACCT" --out-json "$OUT_JSON" --out-md "$OUT_MD" --emit-query "" --emit-sync ""
completion_ok="$("$PYTHON_BIN" - "$OUT_JSON" <<'PY'
import json
import sys
with open(sys.argv[1]) as handle:
    report = json.load(handle)
print('1' if report.get('completion_ok') else '0')
PY
)"
test "$completion_ok" = 1 || { echo "W3b target-MSA completion validation failed" >&2; exit 2; }
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_disagreement_design_gate --out-json results/m6d_w3b_disagreement_design_gate_post_msa.json --out-md results/m6d_w3b_disagreement_design_gate_post_msa.md
echo 'W3b target-MSA inputs validated; stop before candidate generation or candidate-level prediction.'
