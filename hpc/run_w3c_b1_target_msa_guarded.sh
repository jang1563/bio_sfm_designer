#!/usr/bin/env bash
# Guarded W3c-B1 target-MSA-only entrypoint. It never authorizes downstream prediction.
set -euo pipefail

LOCKED_MANIFEST="configs/m6d_w3c_fresh_targets.json"
FRESH_TARGET_LOCK="results/m6d_w3c_fresh_target_lock.json"
PROTOCOL="configs/m6d_w3c_validity_first_protocol.json"
EXECUTION_MANIFEST="configs/m6d_w3c_b1_target_msa_manifest.json"
STRUCTURE_FIXTURE="tests/fixtures/m6d_w3c_fresh_structure_fixture.json"
HISTORICAL_OVERLAP_REGISTRY="configs/m6d_w3c_historical_overlap_registry.json"
PLAN="results/m6d_w3c_b1_target_msas.sh"
PREFLIGHT="src/bio_sfm_designer/experiments/m6d_w3c_b1_target_msa_preflight.py"
PRECOMPUTE_SBATCH="hpc/run_precompute_boltz_target_msa.sbatch"
PRECOMPUTE_PYTHON="hpc/precompute_boltz_target_msa.py"
PREP_HETERODIMER="hpc/prep_hetdimer.py"
EXTRACT_CHAIN_FASTA="hpc/extract_chain_fasta.py"

EXPECTED_LOCKED_MANIFEST_SHA256="c3689aee385fef7db89bb7e81b638c1274a957f9465f73464bf42987cda8893d"
EXPECTED_FRESH_TARGET_LOCK_SHA256="1713155ffd24019a003b1366d27816bd5f3b9e1d98b6e2c576b94a00e5936137"
EXPECTED_PROTOCOL_SHA256="ca4c9984a1fb8fa16d71e01a536417fc320857356af5f9ad721b5a11dda06be3"
EXPECTED_EXECUTION_MANIFEST_SHA256="d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda"
EXPECTED_STRUCTURE_FIXTURE_SHA256="b8d523ddc58d6f043001f88a41b7486fd4648f4b299c199bbf62db20c0bff7e0"
EXPECTED_HISTORICAL_OVERLAP_REGISTRY_SHA256="84a837b092ebca73078582f14d8998eb711071a985290e7b57d70b7443bc1df0"
EXPECTED_PLAN_SHA256="a0233c371abba51d8ede2ee848b7c12abbc99226492c90199ebc0babb72b2e10"
EXPECTED_PREFLIGHT_SHA256="d7648ede6d781ad6079ed3b093297d877ae74bc6f4917e3874fbfba048e75f40"
EXPECTED_PRECOMPUTE_SBATCH_SHA256="14080cbbb791a1db2fe1bcd4ca8bcba36d5f4d47ba9ae22f6f27042c59e2f82f"
EXPECTED_PRECOMPUTE_PYTHON_SHA256="c1acecd1a67c9253df17a02e16f402296056892e1fe3b878d172f72dd8e369ff"
EXPECTED_PREP_HETERODIMER_SHA256="ca9c6ebb7156bcd401a7c4de981f89985123fe8bbcf0c55b344b58d0cf1b7356"
EXPECTED_EXTRACT_CHAIN_FASTA_SHA256="d5441f6c1fb35fa60be89e67562b2449ce599bcf700ac96c0f8a314f19bd1c2b"

APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W3C_B1_TARGET_MSA"
APPROVAL_TOKEN="approve-w3c-b1-target-msa-precompute"
RECEIPT="${W3C_B1_TARGET_MSA_RECEIPT:-results/m6d_w3c_b1_target_msa_receipt.jsonl}"
SUMMARY="${W3C_B1_TARGET_MSA_SUMMARY:-results/m6d_w3c_b1_target_msa_receipt_summary.json}"
PREFLIGHT_REPORT="${W3C_B1_TARGET_MSA_PREFLIGHT:-results/m6d_w3c_b1_target_msa_input_preflight.json}"
WORKSTREAM="m6d_w3c_b1_target_msa_input_prep_only"
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
    echo "required W3c-B1 target-MSA artifact is missing or empty: $path" >&2
    exit 65
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W3c-B1 target-MSA artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 65
  fi
}

require_sha256 "$LOCKED_MANIFEST" "$EXPECTED_LOCKED_MANIFEST_SHA256"
require_sha256 "$FRESH_TARGET_LOCK" "$EXPECTED_FRESH_TARGET_LOCK_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$EXECUTION_MANIFEST" "$EXPECTED_EXECUTION_MANIFEST_SHA256"
require_sha256 "$STRUCTURE_FIXTURE" "$EXPECTED_STRUCTURE_FIXTURE_SHA256"
require_sha256 "$HISTORICAL_OVERLAP_REGISTRY" "$EXPECTED_HISTORICAL_OVERLAP_REGISTRY_SHA256"
require_sha256 "$PLAN" "$EXPECTED_PLAN_SHA256"
require_sha256 "$PREFLIGHT" "$EXPECTED_PREFLIGHT_SHA256"
require_sha256 "$PRECOMPUTE_SBATCH" "$EXPECTED_PRECOMPUTE_SBATCH_SHA256"
require_sha256 "$PRECOMPUTE_PYTHON" "$EXPECTED_PRECOMPUTE_PYTHON_SHA256"
require_sha256 "$PREP_HETERODIMER" "$EXPECTED_PREP_HETERODIMER_SHA256"
require_sha256 "$EXTRACT_CHAIN_FASTA" "$EXPECTED_EXTRACT_CHAIN_FASTA_SHA256"
bash -n "$PLAN"

"$PYTHON_BIN" "$PREFLIGHT" --manifest "$EXECUTION_MANIFEST"

if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then
  TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \
  TARGET_MSA_PRECOMPUTE_RECEIPT="$RECEIPT" \
  TARGET_MSA_PRECOMPUTE_WORKSTREAM="$WORKSTREAM" \
  BIO_SFM_PYTHON="$PYTHON_BIN" \
  PYTHONNOUSERSITE=1 \
    bash "$PLAN"
  exit 0
fi

if [ "${BIO_SFM_APPROVE_W3C_B1_TARGET_MSA:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3c-B1 target-MSA submission without exact approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval covers exactly eight one-hour A40 target-MSA jobs only" >&2
  echo "it does not authorize ProteinMPNN, Boltz/AF2 structure prediction, W3c-B2, or a scientific claim" >&2
  exit 64
fi

for path in "$RECEIPT" "$SUMMARY" "$PREFLIGHT_REPORT"; do
  if [ -e "$path" ]; then
    echo "refusing initial W3c-B1 target-MSA submission because provenance path exists: $path" >&2
    echo "audit the existing artifact and prepare an explicit recovery packet instead of rerunning" >&2
    exit 66
  fi
done

mkdir -p "$(dirname "$RECEIPT")" "$(dirname "$SUMMARY")" "$(dirname "$PREFLIGHT_REPORT")"
"$PYTHON_BIN" "$PREFLIGHT" \
  --manifest "$EXECUTION_MANIFEST" \
  --materialize \
  --python-bin "$PYTHON_BIN" \
  --out "$PREFLIGHT_REPORT"

: > "$RECEIPT"
TARGET_MSA_PRECOMPUTE_RECEIPT="$RECEIPT" \
TARGET_MSA_PRECOMPUTE_WORKSTREAM="$WORKSTREAM" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
PYTHONNOUSERSITE=1 \
  bash "$PLAN"

LOCKED_MANIFEST="$LOCKED_MANIFEST" FRESH_TARGET_LOCK="$FRESH_TARGET_LOCK" \
PROTOCOL="$PROTOCOL" EXECUTION_MANIFEST="$EXECUTION_MANIFEST" PLAN="$PLAN" \
PREFLIGHT_REPORT="$PREFLIGHT_REPORT" WORKSTREAM="$WORKSTREAM" \
LOCKED_MANIFEST_SHA256="$EXPECTED_LOCKED_MANIFEST_SHA256" \
FRESH_TARGET_LOCK_SHA256="$EXPECTED_FRESH_TARGET_LOCK_SHA256" \
PROTOCOL_SHA256="$EXPECTED_PROTOCOL_SHA256" \
EXECUTION_MANIFEST_SHA256="$EXPECTED_EXECUTION_MANIFEST_SHA256" \
PLAN_SHA256="$EXPECTED_PLAN_SHA256" \
  "$PYTHON_BIN" - "$RECEIPT" "$SUMMARY" <<'PY'
import hashlib
import json
import os
import pathlib
import sys

receipt = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
records = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
expected = ["1TE1_BA", "3QB4_AB", "5E5M_AB", "5JSB_AB", "6KBR_AC", "6KMQ_AB", "6SGE_AB", "7B5G_AB"]
target_ids = [str(row.get("target_id") or "") for row in records]
if len(records) != 8 or sorted(target_ids) != sorted(expected) or len(set(target_ids)) != 8:
    raise SystemExit("W3c-B1 receipt does not contain exactly one record for each locked target")
status_counts = {}
for row in records:
    status = str(row.get("status"))
    status_counts[status] = status_counts.get(status, 0) + 1
preflight_path = pathlib.Path(os.environ["PREFLIGHT_REPORT"])
preflight_sha256 = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
summary = {
    "artifact": "m6d_w3c_b1_target_msa_receipt_summary",
    "version": 1,
    "status": "w3c_b1_target_msa_jobs_submitted_or_reused",
    "workstream": os.environ["WORKSTREAM"],
    "locked_manifest": os.environ["LOCKED_MANIFEST"],
    "locked_manifest_sha256": os.environ["LOCKED_MANIFEST_SHA256"],
    "fresh_target_lock": os.environ["FRESH_TARGET_LOCK"],
    "fresh_target_lock_sha256": os.environ["FRESH_TARGET_LOCK_SHA256"],
    "protocol": os.environ["PROTOCOL"],
    "protocol_sha256": os.environ["PROTOCOL_SHA256"],
    "execution_manifest": os.environ["EXECUTION_MANIFEST"],
    "execution_manifest_sha256": os.environ["EXECUTION_MANIFEST_SHA256"],
    "plan": os.environ["PLAN"],
    "plan_sha256": os.environ["PLAN_SHA256"],
    "input_preflight": os.environ["PREFLIGHT_REPORT"],
    "input_preflight_sha256": preflight_sha256,
    "receipt": str(receipt),
    "n_records": len(records),
    "n_targets": len(set(target_ids)),
    "target_ids": expected,
    "status_counts": status_counts,
    "proteinmpnn_designs": 0,
    "predictor_evaluations": 0,
    "claim_boundary": (
        "Target-MSA input-prep provenance only. This does not authorize ProteinMPNN, "
        "structure prediction, W3c-B2, or a scientific claim."
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(f"wrote {summary_path}")
PY
