#!/usr/bin/env bash
#SBATCH --job-name=biosfm-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-boltz-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to candidate JSONL}"
BACKBONE="${BACKBONE:?Set BACKBONE to the reference structure}"
THRESHOLD="${THRESHOLD:-2.0}"
SAMPLING_STEPS="${SAMPLING_STEPS:-200}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records_boltz.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/predict_boltz.py --candidates "$CANDIDATES" --backbone "$BACKBONE" \
  --out "$OUT" --threshold "$THRESHOLD" --sampling-steps "$SAMPLING_STEPS"
