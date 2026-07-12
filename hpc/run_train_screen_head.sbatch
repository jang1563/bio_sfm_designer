#!/usr/bin/env bash
#SBATCH --job-name=biosfm-train-head
#SBATCH --output=hpc_outputs/logs/biosfm-train-head-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-train-head-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
BASE="${BASE:-microsoft/deberta-v3-base}"
TRAIN="${TRAIN:?Set TRAIN to labeled training JSONL}"
EVAL="${EVAL:?Set EVAL to labeled evaluation JSONL}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/train/screen_head}"
EPOCHS="${EPOCHS:-5}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/train_screen_head.py \
  --base "$BASE" --train "$TRAIN" --eval "$EVAL" --out "$OUT" --epochs "$EPOCHS"
