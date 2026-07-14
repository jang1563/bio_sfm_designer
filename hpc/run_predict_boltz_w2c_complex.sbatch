#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w2c-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-w2c-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w2c-boltz-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# W2c threshold-learning Boltz stage. The output is namespace-validated in place.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
unset PYTHONHOME
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES}"
BACKBONE="${BACKBONE:?Set BACKBONE}"
TARGET_CHAIN="${TARGET_CHAIN:?Set TARGET_CHAIN}"
BINDER_CHAIN="${BINDER_CHAIN:?Set BINDER_CHAIN}"
COMPLEX_ID="${COMPLEX_ID:?Set COMPLEX_ID}"
TARGET_MSA="${TARGET_MSA:?Set TARGET_MSA}"
W2C_STAGE="${W2C_STAGE:?Set W2C_STAGE}"
W2C_SEED_NAMESPACE="${W2C_SEED_NAMESPACE:?Set W2C_SEED_NAMESPACE}"
EXPECTED_COUNT="${EXPECTED_COUNT:?Set EXPECTED_COUNT}"
THRESHOLD="${THRESHOLD:-4.0}"
SAMPLING_STEPS="${SAMPLING_STEPS:-100}"
OUT="${OUT:?Set OUT}"

[ "$W2C_STAGE" = "threshold_learning" ] || { echo "W2c stage must be threshold_learning" >&2; exit 2; }
[ "$W2C_SEED_NAMESPACE" = "w2c-fit-learn-v1" ] || { echo "unexpected W2c namespace" >&2; exit 2; }
[ "$EXPECTED_COUNT" = "60" ] || { echo "W2c threshold learning requires exactly 60 records" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$ENV_PY" hpc/predict_boltz_complex.py \
  --candidates "$CANDIDATES" --backbone "$BACKBONE" \
  --target-chain "$TARGET_CHAIN" --binder-chain "$BINDER_CHAIN" \
  --complex-id "$COMPLEX_ID" --target-msa "$TARGET_MSA" \
  --out "$OUT" --threshold "$THRESHOLD" --sampling-steps "$SAMPLING_STEPS"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w2c_stage_metadata \
  --kind records --path "$OUT" --candidates "$CANDIDATES" --stage "$W2C_STAGE" \
  --namespace "$W2C_SEED_NAMESPACE" --complex-target-id "$COMPLEX_ID" \
  --expected-count "$EXPECTED_COUNT"
echo "W2c Boltz complex records -> $OUT"
