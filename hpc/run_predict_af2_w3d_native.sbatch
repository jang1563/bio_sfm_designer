#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3d-af2
#SBATCH --output=hpc_outputs/logs/biosfm-w3d-af2-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3d-af2-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G

# Run exactly one frozen W3d AF2-Multimer native-complex evaluation.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1
export APPTAINERENV_XLA_PYTHON_CLIENT_PREALLOCATE=false

APPROVAL_TOKEN="approve-w3d-native-factorial-24-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
HOST_PYTHON="${HOST_PYTHON:?Set HOST_PYTHON}"
COLABFOLD_SIF="${COLABFOLD_SIF:?Set COLABFOLD_SIF}"
AF2_DATA_DIR="${AF2_DATA_DIR:?Set AF2_DATA_DIR}"
APPROVAL_PACKET="${W3D_APPROVAL_PACKET:-results/m6d_w3d_prediction_approval_packet.json}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
RUNTIME_RECEIPT="${W3D_RUNTIME_RECEIPT:-results/m6d_w3d_runtime_validation_receipt.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
REPRESENTATION_ID="${REPRESENTATION_ID:?Set REPRESENTATION_ID}"
INPUT_PATH="${INPUT_PATH:?Set INPUT_PATH}"
OUTPUT_DIR="${OUTPUT_DIR:?Set OUTPUT_DIR}"
RECORD_PATH="${RECORD_PATH:?Set RECORD_PATH}"

if [ "${BIO_SFM_APPROVE_W3D_PANEL:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3d AF2 prediction without exact approval" >&2
  exit 64
fi
test -x "$HOST_PYTHON" || { echo "host Python is unavailable" >&2; exit 2; }
test -s "$COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }

cd "$PROJECT_ROOT"
test -f "$INPUT_PATH" || { echo "W3d AF2 input is unavailable" >&2; exit 2; }
[ ! -e "$OUTPUT_DIR" ] || { echo "W3d AF2 output already exists" >&2; exit 2; }
[ ! -e "$RECORD_PATH" ] || { echo "W3d AF2 record already exists" >&2; exit 2; }
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$PROJECT_ROOT/hpc_outputs/logs"

WORK_ROOT="$(mktemp -d "${SLURM_TMPDIR:-/tmp}/biosfm-w3d-af2.XXXXXX")"
cleanup() { rm -rf "$WORK_ROOT"; }
trap cleanup EXIT
RUNTIME_OBSERVATION="$WORK_ROOT/runtime_observation.json"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_approval verify \
  --packet "$APPROVAL_PACKET"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" \
  --predictor-id af2_multimer_colabfold_v1 validate-cell \
  --expected-input-path "$INPUT_PATH" --expected-output-dir "$OUTPUT_DIR" \
  --expected-record-path "$RECORD_PATH"

COLABFOLD_VERSION="$($APPTAINER_BIN exec --containall --net --network none \
  --pwd "$PROJECT_ROOT" --bind "$PROJECT_ROOT:$PROJECT_ROOT" \
  --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" "$COLABFOLD_SIF" \
  python3 -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-af2 --protocol configs/m6d_w3c_validity_first_protocol.json \
  --native-manifest configs/m6d_w3c_b2_native_screen_manifest.json \
  --b1-completion results/m6d_w3c_b1_target_msa_completion.json \
  --w3b-runtime-lock configs/m6d_w3b_runtime_lock.json \
  --runtime-path "$COLABFOLD_SIF" --data-dir "$AF2_DATA_DIR" \
  --colabfold-version "$COLABFOLD_VERSION" --out "$RUNTIME_OBSERVATION"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" \
  --predictor-id af2_multimer_colabfold_v1 validate-runtime \
  --runtime-observation "$RUNTIME_OBSERVATION"

"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --pwd "$PROJECT_ROOT" --bind "$PROJECT_ROOT:$PROJECT_ROOT" \
  --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" "$COLABFOLD_SIF" python3 - <<'PY'
import jax

devices = jax.devices()
if not devices or not any(device.platform == "gpu" for device in devices):
    raise SystemExit(f"W3d AF2 preflight did not expose a GPU: {devices}")
print(f"W3d AF2 GPU preflight devices: {devices}")
PY

INPUT_ABS="$PROJECT_ROOT/$INPUT_PATH"
OUTPUT_ABS="$PROJECT_ROOT/$OUTPUT_DIR"
mkdir -p "$OUTPUT_ABS"
"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --pwd "$PROJECT_ROOT" --bind "$PROJECT_ROOT:$PROJECT_ROOT" \
  --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" "$COLABFOLD_SIF" \
  colabfold_batch "$INPUT_ABS" "$OUTPUT_ABS" \
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

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" \
  --predictor-id af2_multimer_colabfold_v1 convert-af2 \
  --runtime-observation "$RUNTIME_OBSERVATION"

echo "W3d AF2 evaluation complete: $TARGET_ID $REPRESENTATION_ID"
