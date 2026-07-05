#!/usr/bin/env bash
#SBATCH --job-name=biosfm-chai1-smoke
#SBATCH --output=hpc_outputs/logs/biosfm-chai1-smoke-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-chai1-smoke-%j.err
#SBATCH --partition=scu-gpu
#SBATCH --gres=gpu:a40:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Chai-1 W3 no-claim smoke path. This prepares one heterodimer FASTA from a
# complex candidate JSONL, verifies a dedicated Chai env/CLI, and only folds
# when RUN_CHAI_FOLD=1 is set explicitly.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
export PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
CHAI_ENV_PREFIX="${CHAI_ENV_PREFIX:-$HOME/.conda/envs/chai1}"
ENV_PY="${ENV_PY:-$CHAI_ENV_PREFIX/bin/python}"
CHAI_CLI="${CHAI_CLI:-$CHAI_ENV_PREFIX/bin/chai-lab}"
CHAI_VERSION="${CHAI_VERSION:-0.6.1}"
CREATE_ENV="${CREATE_ENV:-0}"
RUN_CHAI_FOLD="${RUN_CHAI_FOLD:-0}"
RUN_CHAI_API="${RUN_CHAI_API:-0}"
USE_MSA_SERVER="${USE_MSA_SERVER:-0}"
USE_TEMPLATES_SERVER="${USE_TEMPLATES_SERVER:-0}"
NUM_TRUNK_RECYCLES="${NUM_TRUNK_RECYCLES:-3}"
NUM_DIFFN_TIMESTEPS="${NUM_DIFFN_TIMESTEPS:-200}"
NUM_DIFFN_SAMPLES="${NUM_DIFFN_SAMPLES:-5}"
NUM_TRUNK_SAMPLES="${NUM_TRUNK_SAMPLES:-1}"
CHAI_SEED="${CHAI_SEED:-}"
CHAI_DOWNLOADS_DIR="${CHAI_DOWNLOADS_DIR:-$PROJECT_ROOT/hpc_outputs/chai1/downloads}"
CANDIDATES="${CANDIDATES:-$PROJECT_ROOT/hpc_outputs/m6d_followup_3PC8_AB_scale_t030/candidates_proteinmpnn_complex_t030.jsonl}"
CANDIDATE_ID="${CANDIDATE_ID:-}"
CANDIDATE_INDEX="${CANDIDATE_INDEX:-0}"
SMOKE_DIR="${SMOKE_DIR:-$PROJECT_ROOT/hpc_outputs/m6c_second_predictor/chai1_smoke}"
SMOKE_FASTA="${SMOKE_FASTA:-$SMOKE_DIR/input.fasta}"
SMOKE_MANIFEST="${SMOKE_MANIFEST:-$SMOKE_DIR/input_manifest.json}"
CHAI_OUT="${CHAI_OUT:-$SMOKE_DIR/chai_output}"

mkdir -p "$PROJECT_ROOT/hpc_outputs/logs" "$SMOKE_DIR" "$CHAI_DOWNLOADS_DIR"
cd "$PROJECT_ROOT"

if [ ! -x "$ENV_PY" ]; then
  if [ "$CREATE_ENV" != "1" ]; then
    echo "missing Chai python: $ENV_PY" >&2
    echo "rerun with CREATE_ENV=1 to create $CHAI_ENV_PREFIX, or set ENV_PY/CHAI_CLI to an existing install" >&2
    exit 2
  fi
  conda create -y -p "$CHAI_ENV_PREFIX" python=3.11
fi

if ! "$ENV_PY" - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("chai_lab") else 1)
PY
then
  if [ "$CREATE_ENV" != "1" ]; then
    echo "chai_lab is not importable in $ENV_PY" >&2
    echo "rerun with CREATE_ENV=1 to install chai_lab==$CHAI_VERSION, or set ENV_PY/CHAI_CLI to an existing install" >&2
    exit 2
  fi
  "$ENV_PY" -m pip install --upgrade pip
  "$ENV_PY" -m pip install "chai_lab==$CHAI_VERSION"
fi

if [ ! -x "$CHAI_CLI" ]; then
  echo "missing Chai CLI: $CHAI_CLI" >&2
  exit 2
fi

MAKE_INPUT=( "$ENV_PY" hpc/make_chai1_smoke_input.py
  --candidates "$CANDIDATES"
  --index "$CANDIDATE_INDEX"
  --out "$SMOKE_FASTA"
  --manifest "$SMOKE_MANIFEST"
)
if [ -n "$CANDIDATE_ID" ]; then
  MAKE_INPUT=( "$ENV_PY" hpc/make_chai1_smoke_input.py
    --candidates "$CANDIDATES"
    --candidate-id "$CANDIDATE_ID"
    --out "$SMOKE_FASTA"
    --manifest "$SMOKE_MANIFEST"
  )
fi
"${MAKE_INPUT[@]}"

env PYTHONNOUSERSITE=1 "$ENV_PY" - <<'PY'
import importlib.metadata
import importlib.util
import json
import shutil
import sys

payload = {
    "python": sys.executable,
    "python_version": sys.version.split()[0],
    "chai_lab_importable": bool(importlib.util.find_spec("chai_lab")),
    "chai_lab_version": None,
    "chai_lab_cli": shutil.which("chai-lab"),
}
try:
    payload["chai_lab_version"] = importlib.metadata.version("chai_lab")
except importlib.metadata.PackageNotFoundError:
    pass
print(json.dumps(payload, sort_keys=True))
PY

if [ "$RUN_CHAI_FOLD" != "1" ]; then
  echo "prepared Chai smoke input:"
  echo "  FASTA: $SMOKE_FASTA"
  echo "  manifest: $SMOKE_MANIFEST"
  echo "set RUN_CHAI_FOLD=1 to run: $CHAI_CLI fold $SMOKE_FASTA $CHAI_OUT"
  echo "set RUN_CHAI_FOLD=1,RUN_CHAI_API=1 to save pAE/PDE/pLDDT arrays via the Chai Python API"
  exit 0
fi

if [ -e "$CHAI_OUT" ]; then
  echo "removing existing Chai smoke output: $CHAI_OUT"
  rm -rf "$CHAI_OUT"
fi
mkdir -p "$CHAI_OUT"

EXTRA=()
[ "$USE_MSA_SERVER" = "1" ] && EXTRA+=(--use-msa-server)
[ "$USE_TEMPLATES_SERVER" = "1" ] && EXTRA+=(--use-templates-server)

export CHAI_DOWNLOADS_DIR
if [ "$RUN_CHAI_API" = "1" ]; then
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
else
  "$CHAI_CLI" fold "${EXTRA[@]}" "$SMOKE_FASTA" "$CHAI_OUT"
fi
echo "Chai smoke output -> $CHAI_OUT"
