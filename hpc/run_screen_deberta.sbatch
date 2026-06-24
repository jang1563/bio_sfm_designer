#!/usr/bin/env bash
#SBATCH --job-name=biosfm-screen
#SBATCH --output=hpc_outputs/logs/biosfm-screen-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-screen-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# DeBERTa biosafety screen on Cayuga (intent-level). BRING YOUR OWN trained classification head:
# microsoft/deberta-v3-base (MIT, arxiv:2111.09543) is the BASE encoder these heads fine-tune from
# -- it has NO classification head, so it cannot screen on its own (a raw load gives a random head).
# Set MODEL_DIR to a TRAINED bio-harm head: a local dir, or an HF id you fine-tuned from
# deberta-v3-base. The repo pins no model; the model-free default is the built-in lexicon
# (safety.SafetyScreen). NOTE: bioguard's v8/response head judges a RESPONSE (query+response), not
# an intent -- wrong task here; both bioguard heads are gated. PROVEN incantation (2026-06-23
# smoke, with a trained head): the bioguard conda env's python + PYTHONNOUSERSITE=1 (so ~/.local
# doesn't shadow the env's numpy/scipy). Writes verdicts.jsonl; consume with safety.PrecomputedScreen.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-/home/fs01/jak4013/.conda/envs/bioguard/bin/python}"
MODEL_DIR="${MODEL_DIR:?Set MODEL_DIR to a TRAINED bio-harm classification head (local dir or HF id fine-tuned from microsoft/deberta-v3-base). The base encoder alone cannot screen.}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to the input JSONL: one {\"id\":..., \"text\":...} per line}"
VERDICTS_OUT="${VERDICTS_OUT:-$PROJECT_ROOT/hpc_outputs/screen/verdicts.jsonl}"

mkdir -p "$(dirname "$VERDICTS_OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/screen_deberta.py \
  --model "$MODEL_DIR" --candidates "$CANDIDATES" --out "$VERDICTS_OUT"
echo "wrote $VERDICTS_OUT"
