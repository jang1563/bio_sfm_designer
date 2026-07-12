#!/usr/bin/env bash
#SBATCH --job-name=biosfm-screen
#SBATCH --output=hpc_outputs/logs/biosfm-screen-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-screen-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
MODEL_DIR="${MODEL_DIR:?Set MODEL_DIR to a trained classification head}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to input JSONL}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/screen/verdicts.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/screen_deberta.py \
  --model "$MODEL_DIR" --candidates "$CANDIDATES" --out "$OUT"
