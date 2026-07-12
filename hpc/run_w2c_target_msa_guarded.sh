#!/usr/bin/env bash
# Guarded W2c target-MSA-only entrypoint. Never authorizes record generation.
set -euo pipefail

MANIFEST="configs/m6d_w2c_fresh_targets.json"
PROTOCOL="configs/m6d_w2c_one_shot_protocol.json"
SELECTION="results/m6d_w2c_target_selection.json"
DESIGN_GATE="results/m6d_w2c_design_gate.json"
PLAN="results/m6d_w2c_target_msas.sh"
EXPECTED_MANIFEST_SHA256="94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2"
EXPECTED_PROTOCOL_SHA256="d7ae7d23f64f957357a6fb9fe1659beb3c4caeea82d2c87bb3e18c73139dfc96"
EXPECTED_SELECTION_SHA256="0d6e166e8823cf9d62603592b41b3865836a55c9d200e06ca353ccdde420c1c4"
EXPECTED_DESIGN_GATE_SHA256="2fe726335575239baaf6f41a10680750e0277e82e4a9e04d21e0c23aad099667"
EXPECTED_PLAN_SHA256="7d73c4fb250ff4984adb7f876ad7ef0b345e0e422d7682bc7fba72fb648d91eb"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W2C_TARGET_MSA"
APPROVAL_TOKEN="approve-w2c-target-msa-precompute"
RECEIPT="${W2C_TARGET_MSA_RECEIPT:-results/m6d_w2c_target_msa_receipt.jsonl}"
SUMMARY="${W2C_TARGET_MSA_SUMMARY:-results/m6d_w2c_target_msa_receipt_summary.json}"
WORKSTREAM="m6d_w2c_target_msa_input_prep_only"
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
    echo "required W2c target-MSA artifact is missing or empty: $path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W2c target-MSA artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 2
  fi
}

require_sha256 "$MANIFEST" "$EXPECTED_MANIFEST_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$SELECTION" "$EXPECTED_SELECTION_SHA256"
require_sha256 "$DESIGN_GATE" "$EXPECTED_DESIGN_GATE_SHA256"
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

if [ "${BIO_SFM_APPROVE_W2C_TARGET_MSA:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W2c target-MSA submission without explicit approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval covers eight target-MSA jobs only; it does not authorize ProteinMPNN or Boltz" >&2
  exit 2
fi

if [ -e "$RECEIPT" ]; then
  echo "refusing initial W2c target-MSA submission because receipt path already exists: $RECEIPT" >&2
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

MANIFEST="$MANIFEST" PROTOCOL="$PROTOCOL" SELECTION="$SELECTION" DESIGN_GATE="$DESIGN_GATE" PLAN="$PLAN" \
MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" PROTOCOL_SHA256="$EXPECTED_PROTOCOL_SHA256" \
SELECTION_SHA256="$EXPECTED_SELECTION_SHA256" DESIGN_GATE_SHA256="$EXPECTED_DESIGN_GATE_SHA256" \
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
    "artifact": "m6d_w2c_target_msa_receipt_summary",
    "status": "target_msa_jobs_submitted_or_reused",
    "workstream": os.environ["WORKSTREAM"],
    "manifest": os.environ["MANIFEST"],
    "manifest_sha256": os.environ["MANIFEST_SHA256"],
    "protocol": os.environ["PROTOCOL"],
    "protocol_sha256": os.environ["PROTOCOL_SHA256"],
    "selection": os.environ["SELECTION"],
    "selection_sha256": os.environ["SELECTION_SHA256"],
    "design_gate": os.environ["DESIGN_GATE"],
    "design_gate_sha256": os.environ["DESIGN_GATE_SHA256"],
    "plan": os.environ["PLAN"],
    "plan_sha256": os.environ["PLAN_SHA256"],
    "receipt": str(receipt),
    "n_records": len(records),
    "n_targets": len(target_ids),
    "target_ids": target_ids,
    "status_counts": status_counts,
    "claim_boundary": (
        "Target-MSA input-prep provenance only. This is not W2c evidence and does not authorize "
        "ProteinMPNN or Boltz record generation."
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(f"wrote {summary_path}")
PY
