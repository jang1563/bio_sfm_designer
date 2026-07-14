#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3b-fit-af2
#SBATCH --output=hpc_outputs/logs/biosfm-w3b-fit-af2-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3b-fit-af2-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G

# Dedicated W3b fit AF2 producer with network isolation and strict receipts.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1

APPROVAL_TOKEN="approve-w3b-fit-180-matched-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
HOST_PYTHON="${HOST_PYTHON:?Set HOST_PYTHON to the repository Python}"
COLABFOLD_SIF="${COLABFOLD_SIF:?Set COLABFOLD_SIF}"
AF2_DATA_DIR="${AF2_DATA_DIR:?Set AF2_DATA_DIR}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
STAGE="${STAGE:?Set STAGE}"
PREPARED_PDB="${PREPARED_PDB:?Set PREPARED_PDB}"
TARGET_CHAIN="${TARGET_CHAIN:?Set TARGET_CHAIN}"
BINDER_CHAIN="${BINDER_CHAIN:?Set BINDER_CHAIN}"
TARGET_MSA="${TARGET_MSA:?Set TARGET_MSA}"
CANDIDATES="${CANDIDATES:?Set CANDIDATES}"
AF2_INPUT_DIR="${AF2_INPUT_DIR:?Set AF2_INPUT_DIR}"
AF2_INPUT_MANIFEST="${AF2_INPUT_MANIFEST:?Set AF2_INPUT_MANIFEST}"
AF2_OUTPUT_DIR="${AF2_OUTPUT_DIR:?Set AF2_OUTPUT_DIR}"
RECORDS="${RECORDS:?Set RECORDS}"
RUNTIME_IDENTITY="${RUNTIME_IDENTITY:?Set RUNTIME_IDENTITY}"
RUNTIME_RECEIPT="${RUNTIME_RECEIPT:?Set RUNTIME_RECEIPT}"

if [ "${BIO_SFM_APPROVE_W3B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b AF2 fit prediction without exact fit-stage approval" >&2
  exit 64
fi
[ "$STAGE" = "fit" ] || { echo "W3b AF2 fit producer requires STAGE=fit" >&2; exit 2; }
test -x "$HOST_PYTHON" || { echo "host Python is not executable: $HOST_PYTHON" >&2; exit 2; }
test -s "$COLABFOLD_SIF" || { echo "ColabFold container is missing: $COLABFOLD_SIF" >&2; exit 2; }
for path in "$AF2_INPUT_DIR" "$AF2_INPUT_MANIFEST" "$AF2_OUTPUT_DIR" \
  "$RECORDS" "$RUNTIME_IDENTITY" "$RUNTIME_RECEIPT"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3b AF2 artifact: $path" >&2; exit 2; }
done

APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$(dirname "$RECORDS")" "$PROJECT_ROOT/hpc_outputs/logs"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract target \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" \
  --prepared-pdb "$PREPARED_PDB" --target-msa "$TARGET_MSA" \
  --target-chain "$TARGET_CHAIN" --binder-chain "$BINDER_CHAIN" \
  --candidates "$CANDIDATES" --af2-records "$RECORDS"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3b_producer_contract prepare-af2 \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" --stage "$STAGE" --candidates "$CANDIDATES" \
  --input-dir "$AF2_INPUT_DIR" --out-manifest "$AF2_INPUT_MANIFEST"

COLABFOLD_VERSION="$($APPTAINER_BIN exec --containall --net --network none \
  "$COLABFOLD_SIF" python3 -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3b_runtime_observation \
  --protocol "$PROTOCOL" --runtime-lock "$RUNTIME_LOCK" \
  af2_multimer_colabfold_v1 --runtime-path "$COLABFOLD_SIF" \
  --data-dir "$AF2_DATA_DIR" --colabfold-version "$COLABFOLD_VERSION" \
  --out "$RUNTIME_IDENTITY"

"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --bind "$PROJECT_ROOT:$PROJECT_ROOT" --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" \
  "$COLABFOLD_SIF" python3 - <<'PY'
import jax

devices = jax.devices()
if not devices or not any(device.platform == "gpu" for device in devices):
    raise SystemExit(f"W3b AF2 preflight did not expose a GPU: {devices}")
print(f"W3b AF2 GPU preflight devices: {devices}")
PY

mkdir -p "$AF2_OUTPUT_DIR"
"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --bind "$PROJECT_ROOT:$PROJECT_ROOT" --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" \
  "$COLABFOLD_SIF" colabfold_batch "$AF2_INPUT_DIR" "$AF2_OUTPUT_DIR" \
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
  --runtime-identity "$RUNTIME_IDENTITY" --target-id "$TARGET_ID" --stage "$STAGE" \
  --candidates "$CANDIDATES" --input-manifest "$AF2_INPUT_MANIFEST" \
  --output-dir "$AF2_OUTPUT_DIR" --out "$RECORDS" --threshold 4.0

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3b_matched_records \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --receipt-predictor af2_multimer_colabfold_v1 --receipt-target "$TARGET_ID" \
  --runtime-identity "$RUNTIME_IDENTITY" --out-runtime-receipt "$RUNTIME_RECEIPT"
echo "W3b AF2 fit records -> $RECORDS"
