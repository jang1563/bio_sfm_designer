#!/usr/bin/env bash
#SBATCH --job-name=biosfm-screen
#SBATCH --output=hpc_outputs/logs/biosfm-screen-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-screen-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# DeBERTa biosafety screen on Cayuga (intent-level). PROVEN incantation (2026-06-23 smoke):
# the bioguard conda env's python + PYTHONNOUSERSITE=1 (so ~/.local doesn't shadow the env's
# numpy/scipy) + the local v8bd model dir. Writes verdicts.jsonl; sync back and consume with
# safety.PrecomputedScreen. Expanse: submit with --account/--partition.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-/home/fs01/jak4013/.conda/envs/bioguard/bin/python}"
MODEL_DIR="${MODEL_DIR:-/home/fs01/jak4013/constitutional-bioguard/models/deberta_bioguard_v8bd}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to the input JSONL: one {\"id\":..., \"text\":...} per line}"
VERDICTS_OUT="${VERDICTS_OUT:-$PROJECT_ROOT/hpc_outputs/screen/verdicts.jsonl}"

mkdir -p "$(dirname "$VERDICTS_OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/screen_deberta.py \
  --model "$MODEL_DIR" --candidates "$CANDIDATES" --out "$VERDICTS_OUT"
echo "wrote $VERDICTS_OUT"
