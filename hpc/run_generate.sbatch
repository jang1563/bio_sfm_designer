#!/usr/bin/env bash
#SBATCH --job-name=biosfm-generate
#SBATCH --output=hpc_outputs/logs/biosfm-generate-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-generate-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
PYTHON="${PYTHON:-python3}"
SPEC="${SPEC:?Set SPEC to a JSON or YAML objective file}"
N="${N:-32}"
OUT="${OUT:-$PROJECT_ROOT/hpc_outputs/generate/candidates.jsonl}"

mkdir -p "$(dirname "$OUT")" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$PYTHON" hpc/generate_template.py --spec "$SPEC" --n "$N" --out "$OUT"
