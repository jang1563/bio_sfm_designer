#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w2c-mpnn
#SBATCH --output=hpc_outputs/logs/biosfm-w2c-mpnn-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w2c-mpnn-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# W2c threshold-learning ProteinMPNN stage. The output is namespace-validated in place.
set -euo pipefail
unset PYTHONNOUSERSITE

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/bioguard/bin/python}"
MPNN_DIR="${MPNN_DIR:-$HOME/ProteinMPNN}"
PDB="${PDB:?Set PDB to the locked two-chain complex backbone}"
TARGET_CHAIN="${TARGET_CHAIN:?Set TARGET_CHAIN}"
DESIGN_CHAIN="${DESIGN_CHAIN:?Set DESIGN_CHAIN}"
NUM_SEQ="${NUM_SEQ:?Set NUM_SEQ}"
TEMP="${TEMP:?Set TEMP}"
SEED="${SEED:?Set SEED}"
OBJECTIVE="${OBJECTIVE:-binder}"
COMPLEX_ID="${COMPLEX_ID:?Set COMPLEX_ID}"
ID_PREFIX="${ID_PREFIX:?Set ID_PREFIX}"
W2C_STAGE="${W2C_STAGE:?Set W2C_STAGE}"
W2C_SEED_NAMESPACE="${W2C_SEED_NAMESPACE:?Set W2C_SEED_NAMESPACE}"
OUT="${OUT:?Set OUT}"

[ "$W2C_STAGE" = "threshold_learning" ] || { echo "W2c stage must be threshold_learning" >&2; exit 2; }
[ "$W2C_SEED_NAMESPACE" = "w2c-fit-learn-v1" ] || { echo "unexpected W2c namespace" >&2; exit 2; }
[ "$NUM_SEQ" = "60" ] || { echo "W2c threshold learning requires exactly 60 sequences" >&2; exit 2; }
[ "$ID_PREFIX" = "${W2C_SEED_NAMESPACE}-${COMPLEX_ID}" ] || { echo "W2c ID prefix mismatch" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$ENV_PY" hpc/generate_proteinmpnn_complex.py \
  --mpnn-dir "$MPNN_DIR" --pdb "$PDB" \
  --target-chain "$TARGET_CHAIN" --design-chain "$DESIGN_CHAIN" \
  --num-seq "$NUM_SEQ" --temp "$TEMP" --seed "$SEED" \
  --objective "$OBJECTIVE" --complex-id "$COMPLEX_ID" --id-prefix "$ID_PREFIX" \
  --out "$OUT" --python "$ENV_PY"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w2c_stage_metadata \
  --kind candidates --path "$OUT" --stage "$W2C_STAGE" \
  --namespace "$W2C_SEED_NAMESPACE" --complex-target-id "$COMPLEX_ID" \
  --expected-count "$NUM_SEQ"
echo "W2c complex candidates -> $OUT"
