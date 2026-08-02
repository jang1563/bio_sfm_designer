#!/usr/bin/env bash
# Validate both exact W3d runtimes and all 24 paths without accelerator use.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
HOST_PYTHON="${HOST_PYTHON:-python3}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
RUNTIME_RECEIPT="${W3D_RUNTIME_RECEIPT:-results/m6d_w3d_runtime_validation_receipt.json}"
WORK_ROOT="${W3D_RUNTIME_VALIDATION_WORK_ROOT:-$PROJECT_ROOT/hpc_outputs/m6d_w3d_runtime_validation_tmp}"

cd "$PROJECT_ROOT"
test -s "$INPUT_MANIFEST" || { echo "W3d input manifest is unavailable" >&2; exit 2; }
[ ! -e "$RUNTIME_RECEIPT" ] || { echo "refusing to overwrite W3d runtime receipt" >&2; exit 2; }
[ ! -e "$WORK_ROOT" ] || { echo "refusing to reuse W3d runtime validation workspace" >&2; exit 2; }
mkdir -p "$WORK_ROOT"
cleanup() { rm -rf "$WORK_ROOT"; }
trap cleanup EXIT

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

PROJECT_ROOT="$PROJECT_ROOT" HOST_PYTHON="$HOST_PYTHON" \
  W3D_INPUT_MANIFEST="$INPUT_MANIFEST" \
  BOLTZ_INPUT_PATH_PLAN="$WORK_ROOT/boltz_path_plan.jsonl" \
  BOLTZ_RUNTIME_OBSERVATION="$WORK_ROOT/boltz_runtime_observation.json" \
  BOLTZ_PATH_PROBES="$WORK_ROOT/boltz_path_probes.jsonl" \
  bash "$SCRIPT_DIR/validate_w3d_boltz_runtime_no_prediction.sh"

PROJECT_ROOT="$PROJECT_ROOT" HOST_PYTHON="$HOST_PYTHON" \
  W3D_INPUT_MANIFEST="$INPUT_MANIFEST" \
  AF2_INPUT_PATH_PLAN="$WORK_ROOT/af2_path_plan.jsonl" \
  AF2_RUNTIME_OBSERVATION="$WORK_ROOT/af2_runtime_observation.json" \
  AF2_PATH_PROBES="$WORK_ROOT/af2_path_probes.jsonl" \
  bash "$SCRIPT_DIR/validate_w3d_af2_runtime_no_prediction.sh"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  runtime-receipt --input-manifest "$INPUT_MANIFEST" --project-root "$PROJECT_ROOT" \
  --boltz-observation "$WORK_ROOT/boltz_runtime_observation.json" \
  --af2-observation "$WORK_ROOT/af2_runtime_observation.json" \
  --boltz-probes "$WORK_ROOT/boltz_path_probes.jsonl" \
  --af2-probes "$WORK_ROOT/af2_path_probes.jsonl" --out "$RUNTIME_RECEIPT"

echo "W3d no-prediction runtime validation complete: 24/24 absolute paths, zero compute authority"
