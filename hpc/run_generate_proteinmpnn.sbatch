#!/usr/bin/env bash
#SBATCH --job-name=biosfm-mpnn
#SBATCH --output=hpc_outputs/logs/biosfm-mpnn-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-mpnn-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# ProteinMPNN generate stage (M4): design sequences for a FIXED backbone PDB -> candidates.jsonl,
# consumed locally by generate.PrecomputedGenerator. ProteinMPNN is MIT + CPU-capable; its weights
# ship in the repo (~/ProteinMPNN), so nothing gated is downloaded. torch+numpy come from the
# bioguard env / ~/.local -- do NOT set PYTHONNOUSERSITE here (unlike the DeBERTa screen): ProteinMPNN
# wants the ~/.local torch build. Sync candidates.jsonl back and feed PrecomputedGenerator.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/bioguard/bin/python}"
MPNN_DIR="${MPNN_DIR:-$HOME/ProteinMPNN}"
PDB="${PDB:?Set PDB to a backbone PDB to design on (e.g. $MPNN_DIR/inputs/PDB_monomers/pdbs/5L33.pdb)}"
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
echo "candidates -> $OUT"
