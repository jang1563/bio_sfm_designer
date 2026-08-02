#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3c-b2-af2
#SBATCH --output=hpc_outputs/logs/biosfm-w3c-b2-af2-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3c-b2-af2-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G

# Run exactly one frozen AF2-Multimer native-complex evaluation.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1
export APPTAINERENV_XLA_PYTHON_CLIENT_PREALLOCATE=false

APPROVAL_TOKEN="approve-w3c-b2-native-16-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
HOST_PYTHON="${HOST_PYTHON:?Set HOST_PYTHON}"
COLABFOLD_SIF="${COLABFOLD_SIF:?Set COLABFOLD_SIF}"
AF2_DATA_DIR="${AF2_DATA_DIR:?Set AF2_DATA_DIR}"
APPROVAL_PACKET="${W3C_B2_APPROVAL_PACKET:-results/m6d_w3c_b2_prediction_approval_packet.json}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3c_validity_first_protocol.json}"
NATIVE_MANIFEST="${NATIVE_MANIFEST:-configs/m6d_w3c_b2_native_screen_manifest.json}"
B1_COMPLETION="${B1_COMPLETION:-results/m6d_w3c_b1_target_msa_completion.json}"
W3B_RUNTIME_LOCK="${W3B_RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3c_b2_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
RUNTIME_OBSERVATION="${RUNTIME_OBSERVATION:?Set RUNTIME_OBSERVATION}"
AF2_INPUT_DIR="${AF2_INPUT_DIR:?Set AF2_INPUT_DIR}"
AF2_INPUT_MANIFEST="${AF2_INPUT_MANIFEST:?Set AF2_INPUT_MANIFEST}"
AF2_OUTPUT_DIR="${AF2_OUTPUT_DIR:?Set AF2_OUTPUT_DIR}"

if [ "${BIO_SFM_APPROVE_W3C_B2_NATIVE:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3c-B2 AF2 prediction without exact approval" >&2
  exit 64
fi
test -x "$HOST_PYTHON" || { echo "host Python is unavailable" >&2; exit 2; }
test -s "$COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
for path in "$RUNTIME_OBSERVATION" "$AF2_INPUT_DIR" \
  "$AF2_INPUT_MANIFEST" "$AF2_OUTPUT_DIR"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3c-B2 AF2 artifact: $path" >&2; exit 2; }
done
APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$(dirname "$RUNTIME_OBSERVATION")" "$PROJECT_ROOT/hpc_outputs/logs"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_approval verify \
  --packet "$APPROVAL_PACKET"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_producer \
  --manifest "$NATIVE_MANIFEST" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" target \
  --predictor-id af2_multimer_colabfold_v1
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_producer \
  --manifest "$NATIVE_MANIFEST" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" prepare-af2 \
  --input-dir "$AF2_INPUT_DIR" --out-manifest "$AF2_INPUT_MANIFEST"

COLABFOLD_VERSION="$($APPTAINER_BIN exec --containall --net --network none \
  "$COLABFOLD_SIF" python3 -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-af2 --protocol "$PROTOCOL" --native-manifest "$NATIVE_MANIFEST" \
  --b1-completion "$B1_COMPLETION" --w3b-runtime-lock "$W3B_RUNTIME_LOCK" \
  --runtime-path "$COLABFOLD_SIF" --data-dir "$AF2_DATA_DIR" \
  --colabfold-version "$COLABFOLD_VERSION" --out "$RUNTIME_OBSERVATION"

"$APPTAINER_BIN" exec --nv --containall --net --network none \
  --bind "$PROJECT_ROOT:$PROJECT_ROOT" --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" \
  "$COLABFOLD_SIF" python3 - <<'PY'
import jax

devices = jax.devices()
if not devices or not any(device.platform == "gpu" for device in devices):
    raise SystemExit(f"W3c-B2 AF2 preflight did not expose a GPU: {devices}")
print(f"W3c-B2 AF2 GPU preflight devices: {devices}")
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

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_producer \
  --manifest "$NATIVE_MANIFEST" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" convert-af2 \
  --runtime-observation "$RUNTIME_OBSERVATION" \
  --input-manifest "$AF2_INPUT_MANIFEST" --output-dir "$AF2_OUTPUT_DIR"

echo "W3c-B2 AF2 native evaluation complete: $TARGET_ID"
