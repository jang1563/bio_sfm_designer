#!/usr/bin/env bash
#SBATCH --job-name=biosfm-msa
#SBATCH --output=hpc_outputs/logs/biosfm-msa-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-msa-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
BOLTZ="${BOLTZ:?Set BOLTZ to the Boltz executable}"
FASTA="${FASTA:?Set FASTA to the target FASTA}"
OUT="${OUT:-${TARGET_MSA:-}}"
[ -n "$OUT" ] || { echo "Set OUT or TARGET_MSA" >&2; exit 2; }
REPORT="${REPORT:-$OUT.report.json}"

mkdir -p "$(dirname "$OUT")" "$(dirname "$REPORT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/precompute_boltz_target_msa.py \
  --fasta "$FASTA" --out "$OUT" --report "$REPORT" --boltz "$BOLTZ"
