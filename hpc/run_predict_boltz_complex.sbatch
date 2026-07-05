#!/usr/bin/env bash
#SBATCH --job-name=biosfm-boltzX
#SBATCH --output=hpc_outputs/logs/biosfm-boltzX-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-boltzX-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Boltz-2 COMPLEX refold (M6c): refold designed complexes (target-MSA + redesigned binder single-seq)
# -> records.jsonl carrying pAE_interaction (validated interface signal), ipTM diagnostics, and interface
# L-RMSD success. `boltz` env + PYTHONNOUSERSITE=1 + --no_kernels. Complexes are LARGER than monomers
# (here ~454 aa) so folding is much slower -- budget accordingly; lower SAMPLING_STEPS to trade speed.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to a complex candidates.jsonl}"
BACKBONE="${BACKBONE:?Set BACKBONE to the reference complex PDB}"
TARGET_CHAIN="${TARGET_CHAIN:-A}"
BINDER_CHAIN="${BINDER_CHAIN:-C}"
COMPLEX_ID="${COMPLEX_ID:-}"
THRESHOLD="${THRESHOLD:-4.0}"
SAMPLING_STEPS="${SAMPLING_STEPS:-100}"
USE_MSA_SERVER="${USE_MSA_SERVER:-0}"     # 1 -> target gets a ColabFold-server MSA (interfaces need it)
TARGET_MSA="${TARGET_MSA:-}"             # precomputed target .a3m; preferred for scale-up
BINDER_USES_MSA="${BINDER_USES_MSA:-0}"   # 1 -> binder also MSA'd (natural/WT; default binder single-seq)
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records_boltz_complex.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
EXTRA=()
if [ -n "$TARGET_MSA" ] && [ "$USE_MSA_SERVER" = "1" ]; then
  echo "Set either TARGET_MSA or USE_MSA_SERVER=1, not both" >&2
  exit 2
fi
[ -n "$TARGET_MSA" ] && EXTRA+=(--target-msa "$TARGET_MSA")
[ -n "$COMPLEX_ID" ] && EXTRA+=(--complex-id "$COMPLEX_ID")
[ "$USE_MSA_SERVER" = "1" ] && EXTRA+=(--use-msa-server)
[ "$BINDER_USES_MSA" = "1" ] && EXTRA+=(--binder-uses-msa)
"$ENV_PY" hpc/predict_boltz_complex.py --candidates "$CANDIDATES" --backbone "$BACKBONE" \
  --target-chain "$TARGET_CHAIN" --binder-chain "$BINDER_CHAIN" \
  --out "$OUT" --threshold "$THRESHOLD" --sampling-steps "$SAMPLING_STEPS" "${EXTRA[@]}"
echo "boltz complex records -> $OUT"
