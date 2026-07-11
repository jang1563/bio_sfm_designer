#!/usr/bin/env bash
# Guarded W2b target-MSA input-prep entrypoint. This never authorizes design/folding jobs.
set -euo pipefail

MANIFEST="configs/m6d_w2b_target_adaptive_fit_targets.json"
PROTOCOL="configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json"
PLAN="results/m6d_w2b_target_adaptive_fit_target_msas.sh"
EXPECTED_MANIFEST_SHA256="1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14"
EXPECTED_PROTOCOL_SHA256="21271eeed9bf4baca5eb55614f1649c1cb329e9b933a7d7cc06d15f674495c88"
EXPECTED_PLAN_SHA256="34f44d18ab784a321a948bcf1d0c3c0b4cb0c7e5d5bd3f77d3fa247a20a9ff5d"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W2B_TARGET_MSA"
APPROVAL_TOKEN="approve-w2b-target-msa-precompute"
RECEIPT="${W2B_TARGET_MSA_RECEIPT:-results/m6d_w2b_target_adaptive_fit_target_msa_receipt.jsonl}"
SUMMARY="${W2B_TARGET_MSA_SUMMARY:-results/m6d_w2b_target_adaptive_fit_target_msa_receipt_summary.json}"
WORKSTREAM="m6d_w2b_target_msa_input_prep"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

require_sha256() {
  local path="$1"
  local expected="$2"
  if [ ! -s "$path" ]; then
    echo "required W2b target-MSA artifact is missing or empty: $path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W2b target-MSA artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 2
  fi
}

require_sha256 "$MANIFEST" "$EXPECTED_MANIFEST_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$PLAN" "$EXPECTED_PLAN_SHA256"
bash -n "$PLAN"

if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then
  TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \
  TARGET_MSA_PRECOMPUTE_RECEIPT="$RECEIPT" \
  TARGET_MSA_PRECOMPUTE_WORKSTREAM="$WORKSTREAM" \
  BIO_SFM_PYTHON="$PYTHON_BIN" \
  PYTHONNOUSERSITE=1 \
    bash "$PLAN"
  exit 0
fi

if [ "${BIO_SFM_APPROVE_W2B_TARGET_MSA:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W2b target-MSA submission without explicit approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval covers eight target-MSA jobs only; it does not authorize ProteinMPNN or Boltz" >&2
  exit 2
fi

if [ -e "$RECEIPT" ]; then
  echo "refusing initial W2b target-MSA submission because receipt path already exists: $RECEIPT" >&2
  echo "audit the existing receipt and use an explicit recovery plan instead of rerunning this wrapper" >&2
  exit 2
fi

mkdir -p "$(dirname "$RECEIPT")" "$(dirname "$SUMMARY")"
: > "$RECEIPT"
TARGET_MSA_PRECOMPUTE_RECEIPT="$RECEIPT" \
TARGET_MSA_PRECOMPUTE_WORKSTREAM="$WORKSTREAM" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
PYTHONNOUSERSITE=1 \
  bash "$PLAN"

MANIFEST="$MANIFEST" PROTOCOL="$PROTOCOL" PLAN="$PLAN" \
MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" PROTOCOL_SHA256="$EXPECTED_PROTOCOL_SHA256" \
PLAN_SHA256="$EXPECTED_PLAN_SHA256" WORKSTREAM="$WORKSTREAM" \
  "$PYTHON_BIN" - "$RECEIPT" "$SUMMARY" <<'PY'
import json
import os
import pathlib
import sys

receipt = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
records = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
target_ids = sorted({str(row.get("target_id")) for row in records if row.get("target_id")})
status_counts = {}
for row in records:
    status = str(row.get("status"))
    status_counts[status] = status_counts.get(status, 0) + 1
summary = {
    "artifact": "m6d_w2b_target_msa_receipt_summary",
    "status": "target_msa_jobs_submitted_or_reused",
    "workstream": os.environ["WORKSTREAM"],
    "manifest": os.environ["MANIFEST"],
    "manifest_sha256": os.environ["MANIFEST_SHA256"],
    "protocol": os.environ["PROTOCOL"],
    "protocol_sha256": os.environ["PROTOCOL_SHA256"],
    "plan": os.environ["PLAN"],
    "plan_sha256": os.environ["PLAN_SHA256"],
    "receipt": str(receipt),
    "n_records": len(records),
    "n_targets": len(target_ids),
    "target_ids": target_ids,
    "status_counts": status_counts,
    "claim_boundary": (
        "Target-MSA input-prep provenance only. This is not W2b evidence and does not authorize "
        "ProteinMPNN or Boltz execution."
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(f"wrote {summary_path}")
PY
