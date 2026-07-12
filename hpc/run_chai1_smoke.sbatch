#!/usr/bin/env bash
#SBATCH --job-name=biosfm-chai1-smoke
#SBATCH --output=hpc_outputs/logs/biosfm-chai1-smoke-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-chai1-smoke-%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
CHAI_CLI="${CHAI_CLI:-chai-lab}"
RUN_CHAI_FOLD="${RUN_CHAI_FOLD:-0}"
RUN_CHAI_API="${RUN_CHAI_API:-0}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to complex candidate JSONL}"
CANDIDATE_INDEX="${CANDIDATE_INDEX:-0}"
BACKBONE="${BACKBONE:-}"
OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/hpc_outputs/chai1/smoke}"
FASTA="$OUT_DIR/input.fasta"
MANIFEST="$OUT_DIR/input_manifest.json"
MODEL_OUT="$OUT_DIR/model_output"
RECORD_OUT="$OUT_DIR/record.jsonl"

mkdir -p "$OUT_DIR" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/make_chai1_smoke_input.py \
  --candidates "$CANDIDATES" --index "$CANDIDATE_INDEX" --out "$FASTA" --manifest "$MANIFEST"

if [ "$RUN_CHAI_FOLD" != "1" ]; then
  echo "prepared Chai-1 input: $FASTA"
  echo "set RUN_CHAI_FOLD=1 to run the configured Chai-1 runtime"
  exit 0
fi

if [ "$RUN_CHAI_API" = "1" ]; then
  "$ENV_PY" hpc/run_chai1_api_with_metrics.py --fasta "$FASTA" --out-dir "$MODEL_OUT" --overwrite
else
  "$CHAI_CLI" fold "$FASTA" "$MODEL_OUT"
fi
if [ -n "$BACKBONE" ]; then
  "$ENV_PY" hpc/convert_chai1_complex_output.py \
    --manifest "$MANIFEST" --chai-out "$MODEL_OUT" --backbone "$BACKBONE" --out "$RECORD_OUT"
fi
