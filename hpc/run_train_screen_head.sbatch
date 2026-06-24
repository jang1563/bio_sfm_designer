#!/usr/bin/env bash
#SBATCH --job-name=biosfm-train-head
#SBATCH --output=hpc_outputs/logs/biosfm-train-head-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-train-head-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

# Fine-tune a bio-harm INTENT classification head FROM microsoft/deberta-v3-base (the base
# encoder; it has no head of its own). Produces a model dir that hpc/screen_deberta.py --model
# consumes. BYO labeled data: JSONL {text,label}, label 1 = harmful intent. Env = the bioguard
# conda env (torch+transformers); PYTHONNOUSERSITE=1 so ~/.local doesn't shadow it. preempt_gpu is
# a cheaper partition. (For a quick plumbing check, scu-cpu works on a tiny set.)
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-/home/fs01/jak4013/.conda/envs/bioguard/bin/python}"
BASE="${BASE:-microsoft/deberta-v3-base}"
TRAIN="${TRAIN:-}"
EVAL="${EVAL:-}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/train/screen_head}"
EPOCHS="${EPOCHS:-5}"
if [ -z "$TRAIN" ] || [ -z "$EVAL" ]; then
  echo "ERROR: set TRAIN and EVAL to labeled JSONL paths (label 1 = harmful intent)" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/train_screen_head.py \
  --base "$BASE" --train "$TRAIN" --eval "$EVAL" --out "$OUT" --epochs "$EPOCHS"
echo "trained head -> $OUT"
