#!/usr/bin/env bash
#SBATCH --job-name=biosfm-boltz-complex
#SBATCH --output=hpc_outputs/logs/biosfm-boltz-complex-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-boltz-complex-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to complex candidate JSONL}"
BACKBONE="${BACKBONE:?Set BACKBONE to the reference complex}"
TARGET_CHAIN="${TARGET_CHAIN:-A}"
BINDER_CHAIN="${BINDER_CHAIN:-B}"
COMPLEX_ID="${COMPLEX_ID:-}"
THRESHOLD="${THRESHOLD:-4.0}"
SAMPLING_STEPS="${SAMPLING_STEPS:-100}"
TARGET_MSA="${TARGET_MSA:-}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records_boltz_complex.jsonl}"

EXTRA=()
[ -n "$TARGET_MSA" ] && EXTRA+=(--target-msa "$TARGET_MSA")
[ -n "$COMPLEX_ID" ] && EXTRA+=(--complex-id "$COMPLEX_ID")
mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/predict_boltz_complex.py --candidates "$CANDIDATES" --backbone "$BACKBONE" \
  --target-chain "$TARGET_CHAIN" --binder-chain "$BINDER_CHAIN" \
  --out "$OUT" --threshold "$THRESHOLD" --sampling-steps "$SAMPLING_STEPS" "${EXTRA[@]}"
