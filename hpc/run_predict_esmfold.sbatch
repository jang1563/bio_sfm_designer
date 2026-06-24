#!/usr/bin/env bash
#SBATCH --job-name=biosfm-esmfold
#SBATCH --output=hpc_outputs/logs/biosfm-esmfold-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-esmfold-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=40G

# ESMFold predict stage (M4): refold ProteinMPNN designs and compute self-consistency scRMSD to the
# intended backbone -> records.jsonl for predict.PrecomputedStructurePredictor. ESMFold (MIT) runs via
# transformers in the bioguard conda env; set PYTHONNOUSERSITE=1 (conda torch+transformers, same as
# the DeBERTa screen). Pre-cache the weights ONCE on the login node (compute nodes may lack egress):
#   PYTHONNOUSERSITE=1 $ENV_PY -c "from huggingface_hub import snapshot_download as s; s('facebook/esmfold_v1')"
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-/home/fs01/jak4013/.conda/envs/bioguard/bin/python}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to a designs candidates.jsonl (from generate_proteinmpnn.py)}"
BACKBONE="${BACKBONE:?Set BACKBONE to the intended backbone PDB the designs were made for}"
THRESHOLD="${THRESHOLD:-2.0}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

env PYTHONNOUSERSITE=1 "$ENV_PY" hpc/predict_esmfold.py \
  --candidates "$CANDIDATES" --backbone "$BACKBONE" --out "$OUT" --threshold "$THRESHOLD"
echo "records -> $OUT"
