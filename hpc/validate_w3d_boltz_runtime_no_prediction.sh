#!/usr/bin/env bash
# Reobserve Boltz and resolve all eight W3d paths without model inference.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
HOST_PYTHON="${HOST_PYTHON:-python3}"
BOLTZ_PYTHON="${W3D_BOLTZ_PYTHON:-$HOME/.conda/envs/boltz/bin/python}"
BOLTZ_BIN="${W3D_BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
BOLTZ_CACHE="${W3D_BOLTZ_CACHE:-$HOME/.boltz}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
BOLTZ_INPUT_PATH_PLAN="${BOLTZ_INPUT_PATH_PLAN:?Set BOLTZ_INPUT_PATH_PLAN}"
BOLTZ_RUNTIME_OBSERVATION="${BOLTZ_RUNTIME_OBSERVATION:?Set BOLTZ_RUNTIME_OBSERVATION}"
BOLTZ_PATH_PROBES="${BOLTZ_PATH_PROBES:?Set BOLTZ_PATH_PROBES}"

cd "$PROJECT_ROOT"
if [[ "$HOST_PYTHON" == */* ]]; then
  test -x "$HOST_PYTHON" || { echo "host Python is unavailable" >&2; exit 2; }
else
  HOST_PYTHON="$(command -v "$HOST_PYTHON")" || { echo "host Python is unavailable" >&2; exit 2; }
fi
test -x "$BOLTZ_PYTHON" || { echo "Boltz Python is unavailable" >&2; exit 2; }
test -x "$BOLTZ_BIN" || { echo "Boltz executable is unavailable" >&2; exit 2; }
test -d "$BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
for path in "$BOLTZ_INPUT_PATH_PLAN" "$BOLTZ_RUNTIME_OBSERVATION" "$BOLTZ_PATH_PROBES"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3d Boltz validation artifact: $path" >&2; exit 2; }
done

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
unset PYTHONHOME

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  verify-inputs --input-manifest "$INPUT_MANIFEST" --project-root "$PROJECT_ROOT"

"$BOLTZ_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-boltz --protocol configs/m6d_w3c_validity_first_protocol.json \
  --native-manifest configs/m6d_w3c_b2_native_screen_manifest.json \
  --b1-completion results/m6d_w3c_b1_target_msa_completion.json \
  --w3b-runtime-lock configs/m6d_w3b_runtime_lock.json \
  --cache-dir "$BOLTZ_CACHE" --boltz-bin "$BOLTZ_BIN" \
  --out "$BOLTZ_RUNTIME_OBSERVATION"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  emit-path-plan --input-manifest "$INPUT_MANIFEST" --project-root "$PROJECT_ROOT" \
  --predictor-id boltz2_complex > "$BOLTZ_INPUT_PATH_PLAN"
"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  probe-host-paths --path-plan "$BOLTZ_INPUT_PATH_PLAN" --out "$BOLTZ_PATH_PROBES"

echo "W3d Boltz runtime and eight absolute input paths validated without prediction"
