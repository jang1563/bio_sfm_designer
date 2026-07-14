#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3b-fit-mpnn
#SBATCH --output=hpc_outputs/logs/biosfm-w3b-fit-mpnn-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3b-fit-mpnn-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# Dedicated W3b fit candidate producer. It authorizes no predictor or later stage.
set -euo pipefail
unset PYTHONNOUSERSITE

APPROVAL_TOKEN="approve-w3b-fit-180-matched-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/bioguard/bin/python}"
MPNN_DIR="${MPNN_DIR:-$HOME/ProteinMPNN}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
STAGE="${STAGE:?Set STAGE}"
PREPARED_PDB="${PREPARED_PDB:?Set PREPARED_PDB}"
TARGET_CHAIN="${TARGET_CHAIN:?Set TARGET_CHAIN}"
BINDER_CHAIN="${BINDER_CHAIN:?Set BINDER_CHAIN}"
NUM_SEQ="${NUM_SEQ:?Set NUM_SEQ}"
TEMP="${TEMP:?Set TEMP}"
SEED="${SEED:?Set SEED}"
OBJECTIVE="${OBJECTIVE:-binder}"
SEED_NAMESPACE="${SEED_NAMESPACE:?Set SEED_NAMESPACE}"
ID_PREFIX="${ID_PREFIX:?Set ID_PREFIX}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES}"

if [ "${BIO_SFM_APPROVE_W3B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b fit candidate generation without exact fit-stage approval" >&2
  exit 64
fi
[ "$STAGE" = "fit" ] || { echo "W3b fit producer requires STAGE=fit" >&2; exit 2; }
[ "$NUM_SEQ" = "60" ] || { echo "W3b fit requires exactly 60 candidates per target" >&2; exit 2; }
[ "$SEED_NAMESPACE" = "w3b-fit-v1" ] || { echo "W3b fit seed namespace mismatch" >&2; exit 2; }
[ "$ID_PREFIX" = "${SEED_NAMESPACE}-${TARGET_ID}" ] || { echo "W3b fit ID prefix mismatch" >&2; exit 2; }
[ ! -e "$CANDIDATES" ] || { echo "refusing to overwrite W3b candidates: $CANDIDATES" >&2; exit 2; }

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$(dirname "$CANDIDATES")" "$PROJECT_ROOT/hpc_outputs/logs"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract target \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" \
  --prepared-pdb "$PREPARED_PDB" --target-chain "$TARGET_CHAIN" \
  --binder-chain "$BINDER_CHAIN" --candidates "$CANDIDATES"

"$ENV_PY" hpc/generate_proteinmpnn_complex.py \
  --mpnn-dir "$MPNN_DIR" --pdb "$PREPARED_PDB" \
  --target-chain "$TARGET_CHAIN" --design-chain "$BINDER_CHAIN" \
  --num-seq "$NUM_SEQ" --temp "$TEMP" --seed "$SEED" \
  --objective "$OBJECTIVE" --complex-id "$TARGET_ID" --id-prefix "$ID_PREFIX" \
  --out "$CANDIDATES" --python "$ENV_PY"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract candidates \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" --candidates "$CANDIDATES"
echo "W3b fit candidates -> $CANDIDATES"
