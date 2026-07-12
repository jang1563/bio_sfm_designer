#!/usr/bin/env bash
#SBATCH --job-name=biosfm-esmfold
#SBATCH --output=hpc_outputs/logs/biosfm-esmfold-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-esmfold-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=40G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to candidate JSONL}"
BACKBONE="${BACKBONE:?Set BACKBONE to the reference structure}"
THRESHOLD="${THRESHOLD:-2.0}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records_esmfold.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/predict_esmfold.py \
  --candidates "$CANDIDATES" --backbone "$BACKBONE" --out "$OUT" --threshold "$THRESHOLD"
