#!/usr/bin/env bash
#SBATCH --job-name=biosfm-chai1-batch
#SBATCH --output=hpc_outputs/logs/biosfm-chai1-batch-%A_%a.out
#SBATCH --error=hpc_outputs/logs/biosfm-chai1-batch-%A_%a.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Chai-1 W3 scale path. Each Slurm array task folds one matched 3PC8
# candidate, saves pAE/PDE/pLDDT via the Chai Python API, and converts the
# result into the strict complex-record schema.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
CHAI_ENV_PREFIX="${CHAI_ENV_PREFIX:-$HOME/.conda/envs/chai1}"
ENV_PY="${ENV_PY:-$CHAI_ENV_PREFIX/bin/python}"
RUN_CHAI_API="${RUN_CHAI_API:-1}"
USE_MSA_SERVER="${USE_MSA_SERVER:-0}"
USE_TEMPLATES_SERVER="${USE_TEMPLATES_SERVER:-0}"
NUM_TRUNK_RECYCLES="${NUM_TRUNK_RECYCLES:-3}"
NUM_DIFFN_TIMESTEPS="${NUM_DIFFN_TIMESTEPS:-200}"
NUM_DIFFN_SAMPLES="${NUM_DIFFN_SAMPLES:-5}"
NUM_TRUNK_SAMPLES="${NUM_TRUNK_SAMPLES:-1}"
CHAI_SEED="${CHAI_SEED:-37}"
CHAI_DOWNLOADS_DIR="${CHAI_DOWNLOADS_DIR:-$PROJECT_ROOT/hpc_outputs/chai1/downloads}"
CANDIDATES="${CANDIDATES:-$PROJECT_ROOT/hpc_outputs/m6d_followup_3PC8_AB_scale_t030/candidates_proteinmpnn_complex_t030.jsonl}"
BACKBONE="${BACKBONE:-$PROJECT_ROOT/hpc_outputs/targets/prepared_3PC8_AB.pdb}"
THRESHOLD="${THRESHOLD:-4.0}"
OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/hpc_outputs/m6c_second_predictor/chai1_batch}"
CANDIDATE_INDEX="${CANDIDATE_INDEX:-${SLURM_ARRAY_TASK_ID:-0}}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"

CANDIDATE_DIR="$OUT_DIR/index_${CANDIDATE_INDEX}"
SMOKE_FASTA="$CANDIDATE_DIR/input.fasta"
SMOKE_MANIFEST="$CANDIDATE_DIR/input_manifest.json"
CHAI_OUT="$CANDIDATE_DIR/chai_output_api"
RECORD_OUT="$CANDIDATE_DIR/record.jsonl"

mkdir -p "$PROJECT_ROOT/hpc_outputs/logs" "$CANDIDATE_DIR" "$CHAI_DOWNLOADS_DIR"
cd "$PROJECT_ROOT"

if [ "$RUN_CHAI_API" != "1" ]; then
  echo "RUN_CHAI_API must be 1 for W3 Chai scale records because pAE arrays are required" >&2
  exit 2
fi

if [ "$SKIP_EXISTING" = "1" ] && [ -s "$RECORD_OUT" ]; then
  echo "existing record found; skipping candidate index $CANDIDATE_INDEX: $RECORD_OUT"
  exit 0
fi

if [ ! -x "$ENV_PY" ]; then
  echo "missing Chai python: $ENV_PY" >&2
  echo "create the Chai env first with hpc/run_chai1_smoke.sbatch or set ENV_PY" >&2
  exit 2
fi

if ! env PYTHONNOUSERSITE=1 "$ENV_PY" - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("chai_lab") else 1)
PY
then
  echo "chai_lab is not importable in $ENV_PY" >&2
  exit 2
fi

"$ENV_PY" hpc/make_chai1_smoke_input.py \
  --candidates "$CANDIDATES" \
  --index "$CANDIDATE_INDEX" \
  --out "$SMOKE_FASTA" \
  --manifest "$SMOKE_MANIFEST"

export CHAI_DOWNLOADS_DIR
API_ARGS=( "$ENV_PY" hpc/run_chai1_api_with_metrics.py
  --fasta "$SMOKE_FASTA"
  --out-dir "$CHAI_OUT"
  --overwrite
  --num-trunk-recycles "$NUM_TRUNK_RECYCLES"
  --num-diffn-timesteps "$NUM_DIFFN_TIMESTEPS"
  --num-diffn-samples "$NUM_DIFFN_SAMPLES"
  --num-trunk-samples "$NUM_TRUNK_SAMPLES"
)
[ "$USE_MSA_SERVER" = "1" ] && API_ARGS+=(--use-msa-server)
[ "$USE_TEMPLATES_SERVER" = "1" ] && API_ARGS+=(--use-templates-server)
[ -n "$CHAI_SEED" ] && API_ARGS+=(--seed "$CHAI_SEED")
"${API_ARGS[@]}"

"$ENV_PY" hpc/convert_chai1_complex_output.py \
  --manifest "$SMOKE_MANIFEST" \
  --chai-out "$CHAI_OUT" \
  --backbone "$BACKBONE" \
  --out "$RECORD_OUT" \
  --threshold "$THRESHOLD"

echo "Chai batch record -> $RECORD_OUT"
