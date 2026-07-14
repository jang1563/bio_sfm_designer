#!/usr/bin/env bash
# Guarded W3b target-MSA-only entrypoint. It never authorizes candidate-level predictor execution.
set -euo pipefail

MANIFEST="configs/m6d_w3b_fresh_targets.json"
PROTOCOL="configs/m6d_w3b_disagreement_gate_protocol.json"
SELECTION="results/m6d_w3b_target_selection.json"
DESIGN_GATE="results/m6d_w3b_disagreement_design_gate.json"
PLAN="results/m6d_w3b_target_msas.sh"
PRECOMPUTE_SBATCH="hpc/run_precompute_boltz_target_msa.sbatch"
PRECOMPUTE_PYTHON="hpc/precompute_boltz_target_msa.py"
PREP_HETERODIMER="hpc/prep_hetdimer.py"
EXTRACT_CHAIN_FASTA="hpc/extract_chain_fasta.py"
LIFECYCLE="src/bio_sfm_designer/experiments/m6d_w3b_target_msa_lifecycle.py"
MANIFEST_VALIDATOR="src/bio_sfm_designer/experiments/complex_target_manifest.py"
JOB_STATE_QUERY="results/m6d_w3b_target_msa_job_state_query.sh"
SYNC_BACK="results/m6d_w3b_target_msa_sync_back.sh"
EXPECTED_MANIFEST_SHA256="0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc"
EXPECTED_PROTOCOL_SHA256="8dae842c4ec2573e46df6bbd17dfc0a8600e0579289483e98cc551d67cfd5b96"
EXPECTED_SELECTION_SHA256="9349357a35986982bc05867e81e4a345040f444c1685c2e7059f96d4d8e47902"
EXPECTED_DESIGN_GATE_SHA256="bf6361b80575ec4f6d108356f70f09a18fc61fd3dd0e462b4d282e6d095f3aea"
EXPECTED_PLAN_SHA256="ecb815347161d7b1f4ed0f9e7889749a9eb086c590eae6c9fc13137f9f075ca1"
EXPECTED_PRECOMPUTE_SBATCH_SHA256="14080cbbb791a1db2fe1bcd4ca8bcba36d5f4d47ba9ae22f6f27042c59e2f82f"
EXPECTED_PRECOMPUTE_PYTHON_SHA256="c1acecd1a67c9253df17a02e16f402296056892e1fe3b878d172f72dd8e369ff"
EXPECTED_PREP_HETERODIMER_SHA256="ca9c6ebb7156bcd401a7c4de981f89985123fe8bbcf0c55b344b58d0cf1b7356"
EXPECTED_EXTRACT_CHAIN_FASTA_SHA256="d5441f6c1fb35fa60be89e67562b2449ce599bcf700ac96c0f8a314f19bd1c2b"
EXPECTED_LIFECYCLE_SHA256="9c3ecf8ba3d63194d6927c2307e6251e736234496e44d555ba8ba74cbf79db40"
EXPECTED_MANIFEST_VALIDATOR_SHA256="1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0"
EXPECTED_JOB_STATE_QUERY_SHA256="bb941cb48639ce4b3663c90d552a78bf47de9e929c7fa279a6f0db9c402c8da5"
EXPECTED_SYNC_BACK_SHA256="9db801ac3746b368c15542565ee5a51f0d33a1a7d29ed8f6b736520b5f07c393"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W3B_TARGET_MSA"
APPROVAL_TOKEN="approve-w3b-target-msa-precompute"
RECEIPT="${W3B_TARGET_MSA_RECEIPT:-results/m6d_w3b_target_msa_receipt.jsonl}"
SUMMARY="${W3B_TARGET_MSA_SUMMARY:-results/m6d_w3b_target_msa_receipt_summary.json}"
WORKSTREAM="m6d_w3b_target_msa_input_prep_only"
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
    echo "required W3b target-MSA artifact is missing or empty: $path" >&2
    exit 65
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W3b target-MSA artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 65
  fi
}

require_sha256 "$MANIFEST" "$EXPECTED_MANIFEST_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$SELECTION" "$EXPECTED_SELECTION_SHA256"
require_sha256 "$DESIGN_GATE" "$EXPECTED_DESIGN_GATE_SHA256"
require_sha256 "$PLAN" "$EXPECTED_PLAN_SHA256"
require_sha256 "$PRECOMPUTE_SBATCH" "$EXPECTED_PRECOMPUTE_SBATCH_SHA256"
require_sha256 "$PRECOMPUTE_PYTHON" "$EXPECTED_PRECOMPUTE_PYTHON_SHA256"
require_sha256 "$PREP_HETERODIMER" "$EXPECTED_PREP_HETERODIMER_SHA256"
require_sha256 "$EXTRACT_CHAIN_FASTA" "$EXPECTED_EXTRACT_CHAIN_FASTA_SHA256"
require_sha256 "$LIFECYCLE" "$EXPECTED_LIFECYCLE_SHA256"
require_sha256 "$MANIFEST_VALIDATOR" "$EXPECTED_MANIFEST_VALIDATOR_SHA256"
require_sha256 "$JOB_STATE_QUERY" "$EXPECTED_JOB_STATE_QUERY_SHA256"
require_sha256 "$SYNC_BACK" "$EXPECTED_SYNC_BACK_SHA256"
bash -n "$PLAN"
bash -n "$JOB_STATE_QUERY"
bash -n "$SYNC_BACK"

if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then
  TARGET_MSA_PRECOMPUTE_DRY_RUN=1 \
  TARGET_MSA_PRECOMPUTE_RECEIPT="$RECEIPT" \
  TARGET_MSA_PRECOMPUTE_WORKSTREAM="$WORKSTREAM" \
  BIO_SFM_PYTHON="$PYTHON_BIN" \
  PYTHONNOUSERSITE=1 \
    bash "$PLAN"
  exit 0
fi

if [ "${BIO_SFM_APPROVE_W3B_TARGET_MSA:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b target-MSA submission without exact approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval covers eight target-MSA jobs only; it does not authorize ProteinMPNN or candidate-level Boltz/AF2 prediction" >&2
  exit 64
fi

if [ -e "$RECEIPT" ]; then
  echo "refusing initial W3b target-MSA submission because receipt path already exists: $RECEIPT" >&2
  echo "audit the existing receipt and use an explicit recovery plan instead of rerunning this wrapper" >&2
  exit 66
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
    "artifact": "m6d_w3b_target_msa_receipt_summary",
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
        "Target-MSA input-prep provenance only. This does not authorize candidate generation, "
        "candidate-level Boltz/AF2 prediction, or a W3b scientific claim."
    ),
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(f"wrote {summary_path}")
PY
