#!/usr/bin/env bash
#SBATCH --job-name=biosfm-mpnnX
#SBATCH --output=hpc_outputs/logs/biosfm-mpnnX-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-mpnnX-%j.err
#SBATCH --partition=scu-cpu
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

# ProteinMPNN complex generate stage (M6c): redesign one binder chain against a fixed target chain
# in a two-chain complex PDB -> complex candidates.jsonl for hpc/predict_boltz_complex.py.
# ProteinMPNN is CPU-capable; torch+numpy come from the bioguard env / ~/.local, so do NOT set
# PYTHONNOUSERSITE here (unlike Boltz/DeBERTa).
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/bioguard/bin/python}"
MPNN_DIR="${MPNN_DIR:-$HOME/ProteinMPNN}"
PDB="${PDB:?Set PDB to a two-chain complex backbone PDB, e.g. prepared 1BRS A+D}"
TARGET_CHAIN="${TARGET_CHAIN:-A}"
DESIGN_CHAIN="${DESIGN_CHAIN:-D}"
NUM_SEQ="${NUM_SEQ:-40}"
TEMP="${TEMP:-0.3}"
SEED="${SEED:-37}"
OBJECTIVE="${OBJECTIVE:-binder}"
COMPLEX_ID="${COMPLEX_ID:-}"
ID_PREFIX="${ID_PREFIX:-}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/generate/candidates_proteinmpnn_complex.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

EXTRA=()
[ -n "$COMPLEX_ID" ] && EXTRA+=(--complex-id "$COMPLEX_ID")
[ -n "$ID_PREFIX" ] && EXTRA+=(--id-prefix "$ID_PREFIX")

"$ENV_PY" hpc/generate_proteinmpnn_complex.py \
  --mpnn-dir "$MPNN_DIR" --pdb "$PDB" \
  --target-chain "$TARGET_CHAIN" --design-chain "$DESIGN_CHAIN" \
  --num-seq "$NUM_SEQ" --temp "$TEMP" --seed "$SEED" \
  --objective "$OBJECTIVE" --out "$OUT" --python "$ENV_PY" \
  "${EXTRA[@]}"
echo "complex candidates -> $OUT"
