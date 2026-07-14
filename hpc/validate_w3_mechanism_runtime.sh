#!/usr/bin/env bash
set -euo pipefail

ROOT="${BIO_SFM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RECEIPT="${W3_RUNTIME_RECEIPT:-$ROOT/results/m6d_w3_mechanism_runtime_receipt.json}"
APPROVAL_TOKEN="approve-w3-runtime-validation-only"

if [ "${BIO_SFM_APPROVE_W3_RUNTIME_VALIDATION:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3 runtime validation without explicit no-prediction approval:" >&2
  echo "  export BIO_SFM_APPROVE_W3_RUNTIME_VALIDATION=$APPROVAL_TOKEN" >&2
  exit 64
fi
if [ -z "${W3_AF2_DATA_DIR:-}" ]; then
  echo "W3_AF2_DATA_DIR is required" >&2
  exit 65
fi
if [ -n "${W3_COLABFOLD_BIN:-}" ] && [ -n "${W3_COLABFOLD_SIF:-}" ]; then
  echo "set exactly one of W3_COLABFOLD_BIN or W3_COLABFOLD_SIF" >&2
  exit 66
elif [ -n "${W3_COLABFOLD_BIN:-}" ]; then
  if [ ! -x "$W3_COLABFOLD_BIN" ]; then
    echo "W3_COLABFOLD_BIN is not executable: $W3_COLABFOLD_BIN" >&2
    exit 67
  fi
  COLABFOLD_PYTHON="${W3_COLABFOLD_PYTHON:-$(dirname "$W3_COLABFOLD_BIN")/python}"
  "$W3_COLABFOLD_BIN" --help >/dev/null
  VERSION="$($COLABFOLD_PYTHON -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
  MODE="existing_colabfold_binary"
  RUNTIME_PATH="$W3_COLABFOLD_BIN"
elif [ -n "${W3_COLABFOLD_SIF:-}" ]; then
  if [ ! -f "$W3_COLABFOLD_SIF" ]; then
    echo "W3_COLABFOLD_SIF is not a file: $W3_COLABFOLD_SIF" >&2
    exit 68
  fi
  APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
  if [ -z "$APPTAINER_BIN" ]; then
    echo "apptainer/singularity is unavailable" >&2
    exit 69
  fi
  "$APPTAINER_BIN" exec "$W3_COLABFOLD_SIF" colabfold_batch --help >/dev/null
  VERSION="$($APPTAINER_BIN exec "$W3_COLABFOLD_SIF" python3 -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
  MODE="apptainer_colabfold_image"
  RUNTIME_PATH="$W3_COLABFOLD_SIF"
else
  echo "set exactly one of W3_COLABFOLD_BIN or W3_COLABFOLD_SIF" >&2
  exit 70
fi

python3 "$ROOT/hpc/prepare_w3_mechanism_runtime_receipt.py" \
  --runtime-mode "$MODE" \
  --runtime-path "$RUNTIME_PATH" \
  --data-dir "$W3_AF2_DATA_DIR" \
  --colabfold-version "$VERSION" \
  --out "$RECEIPT"
