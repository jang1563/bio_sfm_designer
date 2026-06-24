#!/usr/bin/env bash
#SBATCH --job-name=biosfm-screen
#SBATCH --output=hpc_outputs/logs/biosfm-screen-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-screen-%j.err
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
## DeBERTa is small — CPU is fine. For a GPU node, uncomment:
## SBATCH --gres=gpu:1

# DeBERTa biosafety screen on Cayuga (intent-level). Reuses the existing constitutional-bioguard
# install where DeBERTa is already set up. Writes verdicts JSONL; sync back and let the local
# SafetyScreen consume it offline. Expanse: submit with --account/--partition.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
# The constitutional_bioguard checkout on Cayuga (where DeBERTa + weights already live):
BIOGUARD_DIR="${BIOGUARD_DIR:?Set BIOGUARD_DIR to the constitutional_bioguard checkout on Cayuga}"
CONDA_ENV="${CONDA_ENV:-bioguard}"                 # existing Cayuga env with torch + transformers
CANDIDATES="${CANDIDATES:?Set CANDIDATES to the input JSONL: one {\"id\":..., \"text\":...} per line}"
VERDICTS_OUT="${VERDICTS_OUT:-$PROJECT_ROOT/hpc_outputs/screen/verdicts.jsonl}"

mkdir -p "$(dirname "$VERDICTS_OUT")" "$PROJECT_ROOT/hpc_outputs/logs"

if command -v conda >/dev/null 2>&1; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
fi

cd "$PROJECT_ROOT"
PYTHONPATH="$BIOGUARD_DIR:${PYTHONPATH:-}" python hpc/screen_deberta.py \
  --candidates "$CANDIDATES" --out "$VERDICTS_OUT"
echo "wrote $VERDICTS_OUT"
