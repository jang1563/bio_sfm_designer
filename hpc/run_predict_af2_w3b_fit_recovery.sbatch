#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3b-fit-af2r
#SBATCH --output=hpc_outputs/logs/biosfm-w3b-fit-af2r-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3b-fit-af2r-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=03:59:30
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G

# Recover only a path-failed W3b fit AF2 job. ProteinMPNN and Boltz are out of scope.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
HOST_PYTHON="${HOST_PYTHON:?Set HOST_PYTHON}"
COLABFOLD_SIF="${COLABFOLD_SIF:?Set COLABFOLD_SIF}"
AF2_DATA_DIR="${AF2_DATA_DIR:?Set AF2_DATA_DIR}"
RECOVERY_OBSERVATION="${RECOVERY_OBSERVATION:?Set RECOVERY_OBSERVATION}"
RECOVERY_PACKET="${RECOVERY_PACKET:?Set RECOVERY_PACKET}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES}"
AF2_INPUT_DIR="${AF2_INPUT_DIR:?Set AF2_INPUT_DIR}"
AF2_INPUT_MANIFEST="${AF2_INPUT_MANIFEST:?Set AF2_INPUT_MANIFEST}"
AF2_OUTPUT_DIR="${AF2_OUTPUT_DIR:?Set AF2_OUTPUT_DIR}"
RECORDS="${RECORDS:?Set RECORDS}"
RUNTIME_IDENTITY="${RUNTIME_IDENTITY:?Set RUNTIME_IDENTITY}"
RUNTIME_RECEIPT="${RUNTIME_RECEIPT:?Set RUNTIME_RECEIPT}"

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"

verification="$($HOST_PYTHON -m bio_sfm_designer.experiments.m6d_w3b_fit_af2_recovery \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  verify-target --observation "$RECOVERY_OBSERVATION" --packet "$RECOVERY_PACKET" \
  --target-id "$TARGET_ID")"
expected_token="$($HOST_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["approval_token"])' "$verification")"
if [ "${BIO_SFM_APPROVE_W3B_AF2_RECOVERY:-}" != "$expected_token" ]; then
  echo "refusing W3b AF2 recovery without the packet-bound exact approval" >&2
  exit 64
fi

test -x "$HOST_PYTHON" || { echo "host Python is not executable" >&2; exit 2; }
test -s "$COLABFOLD_SIF" || { echo "ColabFold container is missing" >&2; exit 2; }
test -d "$AF2_DATA_DIR" || { echo "AF2 data directory is missing" >&2; exit 2; }
test -d "$AF2_INPUT_DIR" || { echo "recovery AF2 input directory is missing" >&2; exit 2; }
test -s "$AF2_INPUT_MANIFEST" || { echo "recovery AF2 input manifest is missing" >&2; exit 2; }
test -d "$AF2_OUTPUT_DIR" || { echo "recovery AF2 output directory is missing" >&2; exit 2; }
if [ -n "$(find "$AF2_OUTPUT_DIR" -mindepth 1 -print -quit)" ]; then
  echo "refusing to recover into a non-empty AF2 output directory" >&2
  exit 2
fi
for path in "$RECORDS" "$RUNTIME_RECEIPT"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite terminal AF2 artifact: $path" >&2; exit 2; }
done

APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }
AF2_INPUT_ABS="$($HOST_PYTHON -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$AF2_INPUT_DIR")"
AF2_OUTPUT_ABS="$($HOST_PYTHON -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$AF2_OUTPUT_DIR")"

"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --bind "$PROJECT_ROOT:$PROJECT_ROOT" --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" \
  "$COLABFOLD_SIF" python3 - <<'PY'
import jax

devices = jax.devices()
if not devices or not any(device.platform == "gpu" for device in devices):
    raise SystemExit(f"W3b AF2 recovery preflight did not expose a GPU: {devices}")
print(f"W3b AF2 recovery GPU preflight devices: {devices}")
PY

"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --bind "$PROJECT_ROOT:$PROJECT_ROOT" --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" \
  "$COLABFOLD_SIF" colabfold_batch "$AF2_INPUT_ABS" "$AF2_OUTPUT_ABS" \
  --model-type alphafold2_multimer_v3 \
  --num-models 5 \
  --num-seeds 1 \
  --random-seed 0 \
  --num-recycle 20 \
  --rank multimer \
  --num-relax 0 \
  --msa-mode mmseqs2_uniref_env \
  --pair-mode unpaired_paired \
  --max-seq 508 \
  --max-extra-seq 2048 \
  --data "$AF2_DATA_DIR"

"$HOST_PYTHON" hpc/convert_w3b_af2_outputs.py \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --runtime-identity "$RUNTIME_IDENTITY" --target-id "$TARGET_ID" --stage fit \
  --candidates "$CANDIDATES" --input-manifest "$AF2_INPUT_MANIFEST" \
  --output-dir "$AF2_OUTPUT_DIR" --out "$RECORDS" --threshold 4.0

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --receipt-predictor af2_multimer_colabfold_v1 --receipt-target "$TARGET_ID" \
  --runtime-identity "$RUNTIME_IDENTITY" --out-runtime-receipt "$RUNTIME_RECEIPT"
echo "W3b AF2 fit recovery records -> $RECORDS"
