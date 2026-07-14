#!/usr/bin/env bash
# Read-only W3b target-MSA Slurm query. This script never calls sbatch.
set -euo pipefail
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$PWD}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-$REPO_ROOT/../bio-sfm-trust-core/src}"
if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then
  export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
fi
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
RECEIPT=results/m6d_w3b_target_msa_receipt.jsonl
SUMMARY=results/m6d_w3b_target_msa_receipt_summary.json
SACCT=results/m6d_w3b_target_msa_sacct.tsv
test -s "$RECEIPT" || { echo "W3b target-MSA receipt is absent; no approved submission to query" >&2; exit 2; }
test -s "$SUMMARY" || { echo "W3b target-MSA receipt summary is absent" >&2; exit 2; }
job_ids="$("$PYTHON_BIN" - "$RECEIPT" <<'PY'
import json
import sys
ids = []
with open(sys.argv[1]) as handle:
    for line in handle:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('status') == 'submitted':
            ids.append(str(row.get('job_id') or '').strip())
if any(not value or any(ch.isspace() for ch in value) for value in ids):
    raise SystemExit('receipt contains a non-parsable submitted job id')
print(','.join(ids))
PY
)"
mkdir -p "$(dirname "$SACCT")"
if [ -n "$job_ids" ]; then
  sacct -P -j "$job_ids" --format=JobIDRaw,State,ExitCode,ElapsedRaw,AllocTRES,NodeList > "$SACCT"
else
  printf 'JobIDRaw|State|ExitCode|ElapsedRaw|AllocTRES|NodeList|\n' > "$SACCT"
fi
test -s "$SACCT"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_target_msa_lifecycle --manifest configs/m6d_w3b_fresh_targets.json --approval-packet results/m6d_w3b_target_msa_approval_packet.json --receipt "$RECEIPT" --summary "$SUMMARY" --sacct "$SACCT" --out-json results/m6d_w3b_target_msa_lifecycle.json --out-md results/m6d_w3b_target_msa_lifecycle.md --emit-query "" --emit-sync ""
