#!/usr/bin/env bash
#SBATCH --job-name=biosfm-msa
#SBATCH --output=hpc_outputs/logs/biosfm-msa-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-msa-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

# One-time target-MSA precompute for M6c complex refolds. This runs a tiny Boltz job
# with --use_msa_server, extracts the matching .a3m, and writes it to TARGET_MSA/OUT.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}"
BOLTZ="${BOLTZ:-$HOME/.conda/envs/boltz/bin/boltz}"
FASTA="${FASTA:?Set FASTA to the extracted target FASTA}"
OUT="${OUT:-${TARGET_MSA:-}}"
if [ -z "$OUT" ]; then
  echo "Set OUT or TARGET_MSA to the stable target .a3m path" >&2
  exit 2
fi
REPORT="${REPORT:-$OUT.report.json}"
WORK_DIR="${WORK_DIR:-}"
BOLTZ_CACHE="${BOLTZ_CACHE:-}"
SAMPLING_STEPS="${SAMPLING_STEPS:-1}"
DIFFUSION_SAMPLES="${DIFFUSION_SAMPLES:-1}"
MSA_SERVER_URL="${MSA_SERVER_URL:-}"
FORCE="${FORCE:-0}"
KEEP_WORK="${KEEP_WORK:-0}"

mkdir -p "$(dirname "$OUT")" "$(dirname "$REPORT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"

EXTRA=()
[ -n "$WORK_DIR" ] && EXTRA+=(--work-dir "$WORK_DIR")
[ -n "$BOLTZ_CACHE" ] && EXTRA+=(--cache "$BOLTZ_CACHE")
[ -n "$MSA_SERVER_URL" ] && EXTRA+=(--msa-server-url "$MSA_SERVER_URL")
[ "$FORCE" = "1" ] && EXTRA+=(--force)
[ "$KEEP_WORK" = "1" ] && EXTRA+=(--keep-work)

"$ENV_PY" hpc/precompute_boltz_target_msa.py \
  --fasta "$FASTA" \
  --out "$OUT" \
  --report "$REPORT" \
  --boltz "$BOLTZ" \
  --sampling-steps "$SAMPLING_STEPS" \
  --diffusion-samples "$DIFFUSION_SAMPLES" \
  "${EXTRA[@]}"
echo "target MSA -> $OUT"
