#!/usr/bin/env bash
#SBATCH --job-name=biosfm-mpnn-complex
#SBATCH --output=hpc_outputs/logs/biosfm-mpnn-complex-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-mpnn-complex-%j.err
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail
unset PYTHONNOUSERSITE
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
MPNN_DIR="${MPNN_DIR:?Set MPNN_DIR to a ProteinMPNN checkout}"
PDB="${PDB:?Set PDB to a two-chain complex structure}"
TARGET_CHAIN="${TARGET_CHAIN:-A}"
DESIGN_CHAIN="${DESIGN_CHAIN:-B}"
NUM_SEQ="${NUM_SEQ:-40}"
TEMP="${TEMP:-0.3}"
SEED="${SEED:-37}"
OBJECTIVE="${OBJECTIVE:-binder}"
COMPLEX_ID="${COMPLEX_ID:-}"
ID_PREFIX="${ID_PREFIX:-}"
W2B_STAGE="${W2B_STAGE:-}"
W2B_SEED_NAMESPACE="${W2B_SEED_NAMESPACE:-}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/generate/candidates_proteinmpnn_complex.jsonl}"

EXTRA=()
[ -n "$COMPLEX_ID" ] && EXTRA+=(--complex-id "$COMPLEX_ID")
[ -n "$ID_PREFIX" ] && EXTRA+=(--id-prefix "$ID_PREFIX")
if [ -n "$W2B_STAGE" ] || [ -n "$W2B_SEED_NAMESPACE" ]; then
  [ -n "$W2B_STAGE" ] && [ -n "$W2B_SEED_NAMESPACE" ] && [ -n "$ID_PREFIX" ] || {
    echo "W2B_STAGE, W2B_SEED_NAMESPACE, and ID_PREFIX must be set together" >&2
    exit 2
  }
  EXTRA+=(--w2b-stage "$W2B_STAGE" --w2b-seed-namespace "$W2B_SEED_NAMESPACE")
fi

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/generate_proteinmpnn_complex.py \
  --mpnn-dir "$MPNN_DIR" --pdb "$PDB" \
  --target-chain "$TARGET_CHAIN" --design-chain "$DESIGN_CHAIN" \
  --num-seq "$NUM_SEQ" --temp "$TEMP" --seed "$SEED" \
  --objective "$OBJECTIVE" --out "$OUT" --python "$ENV_PY" "${EXTRA[@]}"
