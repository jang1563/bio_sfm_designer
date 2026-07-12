#!/usr/bin/env bash
#SBATCH --job-name=biosfm-chai1-batch
#SBATCH --output=hpc_outputs/logs/biosfm-chai1-batch-%A_%a.out
#SBATCH --error=hpc_outputs/logs/biosfm-chai1-batch-%A_%a.err
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-python3}"
RUN_CHAI_API="${RUN_CHAI_API:-1}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES to complex candidate JSONL}"
BACKBONE="${BACKBONE:?Set BACKBONE to the reference complex}"
OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/hpc_outputs/chai1/batch}"
CANDIDATE_INDEX="${CANDIDATE_INDEX:-${SLURM_ARRAY_TASK_ID:-0}}"
TASK_DIR="$OUT_DIR/index_$CANDIDATE_INDEX"
FASTA="$TASK_DIR/input.fasta"
MANIFEST="$TASK_DIR/input_manifest.json"
MODEL_OUT="$TASK_DIR/model_output"
RECORD_OUT="$TASK_DIR/record.jsonl"

[ "$RUN_CHAI_API" = "1" ] || { echo "RUN_CHAI_API must be 1 for batch records" >&2; exit 2; }
mkdir -p "$TASK_DIR" "$PROJECT_ROOT/hpc_outputs/logs"
cd "$PROJECT_ROOT"
"$ENV_PY" hpc/make_chai1_smoke_input.py \
  --candidates "$CANDIDATES" --index "$CANDIDATE_INDEX" --out "$FASTA" --manifest "$MANIFEST"
"$ENV_PY" hpc/run_chai1_api_with_metrics.py --fasta "$FASTA" --out-dir "$MODEL_OUT" --overwrite
"$ENV_PY" hpc/convert_chai1_complex_output.py \
  --manifest "$MANIFEST" --chai-out "$MODEL_OUT" --backbone "$BACKBONE" --out "$RECORD_OUT"
