#!/usr/bin/env bash
#SBATCH --job-name=biosfm-mpnn
#SBATCH --output=hpc_outputs/logs/biosfm-mpnn-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-mpnn-%j.err
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
MPNN_DIR="${MPNN_DIR:?Set MPNN_DIR to a ProteinMPNN checkout}"
PDB="${PDB:?Set PDB to a backbone structure}"
CHAINS="${CHAINS:-A}"
NUM_SEQ="${NUM_SEQ:-16}"
OBJECTIVE="${OBJECTIVE:-stability}"
TARGET="${TARGET:-}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/generate/candidates.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/generate_proteinmpnn.py \
  --mpnn-dir "$MPNN_DIR" --pdb "$PDB" --chains "$CHAINS" --num-seq "$NUM_SEQ" \
  --objective "$OBJECTIVE" --target "$TARGET" --out "$OUT" --python "$ENV_PY"
