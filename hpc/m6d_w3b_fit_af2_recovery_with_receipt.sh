#!/usr/bin/env bash
# Submit exactly three path-only W3b fit AF2 recovery jobs after separate approval.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

RECOVERY_OBSERVATION="${W3B_AF2_RECOVERY_OBSERVATION:-results/m6d_w3b_fit_initial_execution_observation.json}"
RECOVERY_PACKET="${W3B_AF2_RECOVERY_PACKET:-results/m6d_w3b_fit_af2_recovery_approval_packet.json}"
RECEIPT="${W3B_AF2_RECOVERY_RECEIPT:-results/m6d_w3b_fit_af2_recovery_submit_receipt.jsonl}"
SUMMARY="${W3B_AF2_RECOVERY_SUMMARY:-results/m6d_w3b_fit_af2_recovery_submit_summary.json}"
WRAPPER="hpc/run_predict_af2_w3b_fit_recovery.sbatch"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery \
  verify-packet --observation "$RECOVERY_OBSERVATION" --packet "$RECOVERY_PACKET"
IFS=$'\t' read -r expected_token time_limit < <("$PYTHON_BIN" - "$RECOVERY_PACKET" <<'PY'
import json
import sys

packet = json.load(open(sys.argv[1]))
contract = packet["approval_contract"]
print(contract["environment_value"] + "\t" + contract["recovery_time_limit"])
PY
)
if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W3B_AF2_RECOVERY:-}" != "$expected_token" ]; then
  echo "refusing W3b AF2 recovery without exact packet-bound approval" >&2
  exit 64
fi
if [ "$DRY_RUN" != "1" ] && { [ -e "$RECEIPT" ] || [ -e "$SUMMARY" ]; }; then
  echo "refusing W3b AF2 recovery because its receipt or summary already exists" >&2
  exit 2
fi
bash -n "$WRAPPER"

if [ "$DRY_RUN" = "1" ]; then
  echo "## W3b AF2 recovery dry run: no sbatch calls and no receipt writes"
else
  command -v "$SBATCH_BIN" >/dev/null 2>&1 || { echo "Slurm sbatch is required" >&2; exit 2; }
  W3B_HOST_PYTHON="${W3B_HOST_PYTHON:-$PYTHON_BIN}"
  W3B_COLABFOLD_SIF="${W3B_COLABFOLD_SIF:?Set W3B_COLABFOLD_SIF}"
  W3B_AF2_DATA_DIR="${W3B_AF2_DATA_DIR:?Set W3B_AF2_DATA_DIR}"
  test -x "$W3B_HOST_PYTHON" || { echo "W3b host Python is unavailable" >&2; exit 2; }
  test -s "$W3B_COLABFOLD_SIF" || { echo "W3b ColabFold container is unavailable" >&2; exit 2; }
  test -d "$W3B_AF2_DATA_DIR" || { echo "W3b AF2 data directory is unavailable" >&2; exit 2; }
  mkdir -p "$(dirname "$RECEIPT")" "$(dirname "$SUMMARY")" hpc_outputs/logs
fi

while IFS=$'\t' read -r target_id failed_job candidates input_manifest input_dir output_dir records runtime_identity runtime_receipt; do
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery \
    --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
    --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
    verify-target --observation "$RECOVERY_OBSERVATION" --packet "$RECOVERY_PACKET" \
    --target-id "$target_id" >/dev/null
  if [ "$DRY_RUN" = "1" ]; then
    echo "dry-run ${target_id}: inputs verified; replace failed AF2 ${failed_job} only; no ProteinMPNN or Boltz job"
    continue
  fi
  recovery_job=$(BIO_SFM_APPROVE_W3B_AF2_RECOVERY="$expected_token" \
    PROJECT_ROOT="$REPO_ROOT" HOST_PYTHON="$W3B_HOST_PYTHON" \
    COLABFOLD_SIF="$W3B_COLABFOLD_SIF" AF2_DATA_DIR="$W3B_AF2_DATA_DIR" \
    RECOVERY_OBSERVATION="$RECOVERY_OBSERVATION" RECOVERY_PACKET="$RECOVERY_PACKET" \
    PROTOCOL="$PROTOCOL" EXECUTION_MANIFEST="$EXECUTION_MANIFEST" \
    INPUT_LOCK="$INPUT_LOCK" RUNTIME_LOCK="$RUNTIME_LOCK" TARGET_ID="$target_id" \
    CANDIDATES="$candidates" AF2_INPUT_DIR="$input_dir" \
    AF2_INPUT_MANIFEST="$input_manifest" AF2_OUTPUT_DIR="$output_dir" \
    RECORDS="$records" RUNTIME_IDENTITY="$runtime_identity" \
    RUNTIME_RECEIPT="$runtime_receipt" \
    "$SBATCH_BIN" --parsable --no-requeue --time="$time_limit" "$WRAPPER")
  if [ -z "${recovery_job//[[:space:]]/}" ] || [[ "$recovery_job" =~ [[:space:]] ]]; then
    echo "invalid AF2 recovery job id for $target_id: $recovery_job" >&2
    exit 2
  fi
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery append \
    --packet "$RECOVERY_PACKET" --receipt "$RECEIPT" \
    --target-id "$target_id" --job-id "$recovery_job"
  echo "${target_id}: failed AF2 ${failed_job} -> recovery AF2 ${recovery_job}"
done < <("$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery \
  emit-targets --packet "$RECOVERY_PACKET")

if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run complete: exactly 3 AF2 recovery jobs, zero ProteinMPNN/Boltz jobs"
  exit 0
fi
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery summary \
  --packet "$RECOVERY_PACKET" --receipt "$RECEIPT" --out "$SUMMARY"
echo "W3b AF2 recovery receipt: $RECEIPT"
echo "W3b AF2 recovery summary: $SUMMARY"
