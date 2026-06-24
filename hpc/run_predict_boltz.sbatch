#!/usr/bin/env bash
#SBATCH --job-name=biosfm-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-boltz-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G

# Boltz-2 INDEPENDENT refold (M6a): refold designs (msa: empty) -> records.jsonl for the gate, giving
# a success LABEL from a different model than the ESMFold pLDDT signal (closes the M4b caveat). Uses the
# `boltz` conda env + PYTHONNOUSERSITE=1 (so ~/.local doesn't shadow the env's torch) + --no_kernels (no
# cuequivariance dep). First predict downloads Boltz-2 weights to ~/.boltz. Boltz diffusion is SLOW with
# --no_kernels -- budget hours for ~100s of designs; lower SAMPLING_STEPS (e.g. 50) to trade accuracy for speed.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to a designs candidates.jsonl}"
BACKBONE="${BACKBONE:?Set BACKBONE to the intended backbone PDB}"
THRESHOLD="${THRESHOLD:-2.0}"
SAMPLING_STEPS="${SAMPLING_STEPS:-200}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/predict/records_boltz.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/predict_boltz.py --candidates "$CANDIDATES" --backbone "$BACKBONE" \
  --out "$OUT" --threshold "$THRESHOLD" --sampling-steps "$SAMPLING_STEPS"
echo "boltz records -> $OUT"
