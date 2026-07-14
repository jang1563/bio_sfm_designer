#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3b-fit-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-w3b-fit-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3b-fit-boltz-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Dedicated W3b fit Boltz producer with runtime re-observation and strict receipts.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

APPROVAL_TOKEN="approve-w3b-fit-180-matched-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}"
BOLTZ_BIN="${BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
BOLTZ_CACHE="${BOLTZ_CACHE:-$HOME/.boltz}"
export BOLTZ_CACHE
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
STAGE="${STAGE:?Set STAGE}"
PREPARED_PDB="${PREPARED_PDB:?Set PREPARED_PDB}"
TARGET_CHAIN="${TARGET_CHAIN:?Set TARGET_CHAIN}"
BINDER_CHAIN="${BINDER_CHAIN:?Set BINDER_CHAIN}"
TARGET_MSA="${TARGET_MSA:?Set TARGET_MSA}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES}"
RECORDS="${RECORDS:?Set RECORDS}"
RUNTIME_IDENTITY="${RUNTIME_IDENTITY:?Set RUNTIME_IDENTITY}"
RUNTIME_RECEIPT="${RUNTIME_RECEIPT:?Set RUNTIME_RECEIPT}"

if [ "${BIO_SFM_APPROVE_W3B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b Boltz fit prediction without exact fit-stage approval" >&2
  exit 64
fi
[ "$STAGE" = "fit" ] || { echo "W3b Boltz fit producer requires STAGE=fit" >&2; exit 2; }
for path in "$RECORDS" "$RUNTIME_IDENTITY" "$RUNTIME_RECEIPT"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3b Boltz artifact: $path" >&2; exit 2; }
done
test -x "$ENV_PY" || { echo "Boltz Python is not executable: $ENV_PY" >&2; exit 2; }
test -x "$BOLTZ_BIN" || { echo "Boltz executable is unavailable: $BOLTZ_BIN" >&2; exit 2; }

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$(dirname "$RECORDS")" "$PROJECT_ROOT/hpc_outputs/logs"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract target \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" \
  --prepared-pdb "$PREPARED_PDB" --target-msa "$TARGET_MSA" \
  --target-chain "$TARGET_CHAIN" --binder-chain "$BINDER_CHAIN" \
  --candidates "$CANDIDATES" --boltz-records "$RECORDS"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract candidates \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" --candidates "$CANDIDATES"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_runtime_observation \
  --protocol "$PROTOCOL" --runtime-lock "$RUNTIME_LOCK" \
  boltz2_complex --cache-dir "$BOLTZ_CACHE" --boltz-bin "$BOLTZ_BIN" \
  --out "$RUNTIME_IDENTITY"

"$ENV_PY" hpc/predict_boltz_w3b_complex.py \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --runtime-identity "$RUNTIME_IDENTITY" --target-id "$TARGET_ID" --stage "$STAGE" \
  --candidates "$CANDIDATES" --out "$RECORDS" --threshold 4.0 --boltz "$BOLTZ_BIN"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --receipt-predictor boltz2_complex --receipt-target "$TARGET_ID" \
  --runtime-identity "$RUNTIME_IDENTITY" --out-runtime-receipt "$RUNTIME_RECEIPT"
echo "W3b Boltz fit records -> $RECORDS"
