#!/usr/bin/env bash
#SBATCH --job-name=biosfm-generate
#SBATCH --output=hpc_outputs/logs/biosfm-generate-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-generate-%j.err
#SBATCH --time=02:00:00
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

# Generative SFM job (RFdiffusion / ProteinMPNN / ESM) on Cayuga/Expanse. Each generator has
# its OWN conda env — build it once like the audit's hpc/build_phase2_boltz_env.sh. Writes a
# candidates.jsonl that the local PrecomputedGenerator consumes. Expanse: add --account/--partition.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
CONDA_ENV="${CONDA_ENV:?Set CONDA_ENV to the generator env (e.g. proteinmpnn / rfdiffusion / esm)}"
SPEC="${SPEC:?Set SPEC to the objective/spec file (JSON or YAML)}"
N="${N:-32}"
CANDIDATES_OUT="${CANDIDATES_OUT:-$PROJECT_ROOT/hpc_outputs/generate/candidates.jsonl}"

mkdir -p "$(dirname "$CANDIDATES_OUT")" "$PROJECT_ROOT/hpc_outputs/logs"

if command -v conda >/dev/null 2>&1; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
fi

cd "$PROJECT_ROOT"
python hpc/generate_template.py --spec "$SPEC" --n "$N" --out "$CANDIDATES_OUT"
echo "wrote $CANDIDATES_OUT"
