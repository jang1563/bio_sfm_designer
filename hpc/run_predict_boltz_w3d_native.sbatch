#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3d-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-w3d-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3d-boltz-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Run exactly one frozen W3d Boltz query-only native-complex evaluation.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

APPROVAL_TOKEN="approve-w3d-native-factorial-24-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python3.11}"
BOLTZ_BIN="${BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
BOLTZ_CACHE="${BOLTZ_CACHE:-$HOME/.boltz}"
APPROVAL_PACKET="${W3D_APPROVAL_PACKET:-results/m6d_w3d_prediction_approval_packet.json}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
RUNTIME_RECEIPT="${W3D_RUNTIME_RECEIPT:-results/m6d_w3d_runtime_validation_receipt.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
REPRESENTATION_ID="${REPRESENTATION_ID:?Set REPRESENTATION_ID}"
INPUT_PATH="${INPUT_PATH:?Set INPUT_PATH}"
OUTPUT_DIR="${OUTPUT_DIR:?Set OUTPUT_DIR}"
RECORD_PATH="${RECORD_PATH:?Set RECORD_PATH}"

if [ "${BIO_SFM_APPROVE_W3D_PANEL:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3d Boltz prediction without exact approval" >&2
  exit 64
fi
test -x "$ENV_PY" || { echo "Boltz Python is unavailable" >&2; exit 2; }
test -x "$BOLTZ_BIN" || { echo "Boltz executable is unavailable" >&2; exit 2; }
test -d "$BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }

cd "$PROJECT_ROOT"
test -f "$INPUT_PATH" || { echo "W3d Boltz input is unavailable" >&2; exit 2; }
[ ! -e "$OUTPUT_DIR" ] || { echo "W3d Boltz output already exists" >&2; exit 2; }
[ ! -e "$RECORD_PATH" ] || { echo "W3d Boltz record already exists" >&2; exit 2; }
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export BOLTZ_CACHE
mkdir -p "$PROJECT_ROOT/hpc_outputs/logs"

WORK_ROOT="$(mktemp -d "${SLURM_TMPDIR:-/tmp}/biosfm-w3d-boltz.XXXXXX")"
cleanup() { rm -rf "$WORK_ROOT"; }
trap cleanup EXIT
RUNTIME_OBSERVATION="$WORK_ROOT/runtime_observation.json"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3d_approval verify \
  --packet "$APPROVAL_PACKET"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" --predictor-id boltz2_complex \
  validate-cell --expected-input-path "$INPUT_PATH" \
  --expected-output-dir "$OUTPUT_DIR" --expected-record-path "$RECORD_PATH"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-boltz --protocol configs/m6d_w3c_validity_first_protocol.json \
  --native-manifest configs/m6d_w3c_b2_native_screen_manifest.json \
  --b1-completion results/m6d_w3c_b1_target_msa_completion.json \
  --w3b-runtime-lock configs/m6d_w3b_runtime_lock.json \
  --cache-dir "$BOLTZ_CACHE" --boltz-bin "$BOLTZ_BIN" \
  --out "$RUNTIME_OBSERVATION"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" --predictor-id boltz2_complex \
  validate-runtime --runtime-observation "$RUNTIME_OBSERVATION"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3d_execution \
  --input-manifest "$INPUT_MANIFEST" --runtime-receipt "$RUNTIME_RECEIPT" \
  --project-root "$PROJECT_ROOT" --target-id "$TARGET_ID" \
  --representation-id "$REPRESENTATION_ID" --predictor-id boltz2_complex \
  run-boltz --runtime-observation "$RUNTIME_OBSERVATION" --boltz-bin "$BOLTZ_BIN"

echo "W3d Boltz evaluation complete: $TARGET_ID $REPRESENTATION_ID"
