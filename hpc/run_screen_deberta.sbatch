#!/usr/bin/env bash
#SBATCH --job-name=biosfm-screen
#SBATCH --output=hpc_outputs/logs/biosfm-screen-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-screen-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# DeBERTa biosafety screen on Cayuga (intent-level). Uses the PUBLIC/MIT deberta-v1 head
# (jang1563/constitutional-bioguard-deberta-v1). NOTE: the v8/response head is gated CC-BY-NC and
# judges a RESPONSE (query+response), not an intent -- wrong task for this screen; the prompt head
# is gated too. PROVEN incantation (2026-06-23 smoke): the bioguard conda env's python +
# PYTHONNOUSERSITE=1 (so ~/.local doesn't shadow the env's numpy/scipy). On nodes without HF
# egress, set MODEL_DIR to a local clone. Writes verdicts.jsonl; consume with safety.PrecomputedScreen.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-/home/fs01/jak4013/.conda/envs/bioguard/bin/python}"
MODEL_DIR="${MODEL_DIR:-jang1563/constitutional-bioguard-deberta-v1}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to the input JSONL: one {\"id\":..., \"text\":...} per line}"
VERDICTS_OUT="${VERDICTS_OUT:-$PROJECT_ROOT/hpc_outputs/screen/verdicts.jsonl}"

mkdir -p "$(dirname "$VERDICTS_OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/screen_deberta.py \
  --model "$MODEL_DIR" --candidates "$CANDIDATES" --out "$VERDICTS_OUT"
echo "wrote $VERDICTS_OUT"
