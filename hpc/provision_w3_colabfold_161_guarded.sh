#!/usr/bin/env bash
set -euo pipefail

ROOT="${BIO_SFM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APPROVAL_TOKEN="approve-w3-runtime-provision"
EXPECTED_IMAGE_URI="docker://ghcr.io/sokrypton/colabfold:1.6.1-cuda12"
IMAGE_URI="${W3_COLABFOLD_IMAGE_URI:-$EXPECTED_IMAGE_URI}"
PROVISION_ROOT="${W3_PROVISION_ROOT:-}"
PRIOR_FETCH_OCCURRED="${W3_PROVISION_PRIOR_FETCH_OCCURRED:-false}"

if [ "${BIO_SFM_APPROVE_W3_RUNTIME_PROVISION:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3 runtime provisioning without explicit approval:" >&2
  echo "  export BIO_SFM_APPROVE_W3_RUNTIME_PROVISION=$APPROVAL_TOKEN" >&2
  exit 64
fi
if [ -z "$PROVISION_ROOT" ] || [[ "$PROVISION_ROOT" != /* ]]; then
  echo "W3_PROVISION_ROOT must be an absolute path" >&2
  exit 65
fi
if [ "$IMAGE_URI" != "$EXPECTED_IMAGE_URI" ]; then
  echo "W3 provisioning requires the pinned image: $EXPECTED_IMAGE_URI" >&2
  exit 66
fi
if [ "$PRIOR_FETCH_OCCURRED" != "false" ] && [ "$PRIOR_FETCH_OCCURRED" != "true" ]; then
  echo "W3_PROVISION_PRIOR_FETCH_OCCURRED must be true or false" >&2
  exit 67
fi

APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
if [ -z "$APPTAINER_BIN" ]; then
  echo "apptainer/singularity is unavailable" >&2
  exit 68
fi

RUNTIME_DIR="$PROVISION_ROOT/runtime"
DATA_DIR="$PROVISION_ROOT/af2_data"
CACHE_DIR="$PROVISION_ROOT/apptainer_cache"
TMP_DIR="$PROVISION_ROOT/apptainer_tmp"
RECEIPT_DIR="$PROVISION_ROOT/receipts"
IMAGE="$RUNTIME_DIR/colabfold-1.6.1-cuda12.sif"
VALIDATION_RECEIPT="${W3_RUNTIME_RECEIPT:-$RECEIPT_DIR/m6d_w3_mechanism_runtime_receipt.json}"
PROVISION_RECEIPT="${W3_PROVISION_RECEIPT:-$RECEIPT_DIR/m6d_w3_runtime_provision_receipt.json}"

mkdir -p "$RUNTIME_DIR" "$DATA_DIR" "$CACHE_DIR" "$TMP_DIR" "$RECEIPT_DIR"

image_pulled=false
if [ ! -f "$IMAGE" ]; then
  partial_image="$IMAGE.partial.$$"
  cleanup() {
    rm -f "$partial_image"
  }
  trap cleanup EXIT
  APPTAINER_CACHEDIR="$CACHE_DIR" APPTAINER_TMPDIR="$TMP_DIR" \
    "$APPTAINER_BIN" pull --disable-cache "$partial_image" "$IMAGE_URI"
  mv "$partial_image" "$IMAGE"
  trap - EXIT
  image_pulled=true
fi

export APPTAINERENV_PYTHONNOUSERSITE=1
version="$("$APPTAINER_BIN" exec "$IMAGE" python3 -c \
  'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"
if [ "$version" != "1.6.1" ]; then
  echo "ColabFold 1.6.1 is required; observed $version" >&2
  exit 69
fi
"$APPTAINER_BIN" exec "$IMAGE" colabfold_batch --help >/dev/null

marker="$DATA_DIR/params/download_complexes_multimer_v3_finished.txt"
weights_download_invoked=false
mkdir -p "$DATA_DIR/params"
weight_count="$(find "$DATA_DIR/params" -maxdepth 1 -type f \
  -name 'params_model_*_multimer_v3.npz' 2>/dev/null | wc -l | tr -d ' ')"
if [ ! -f "$marker" ] || [ "$weight_count" != "5" ]; then
  "$APPTAINER_BIN" exec --containall --bind "$PROVISION_ROOT:$PROVISION_ROOT" \
    "$IMAGE" python3 - "$DATA_DIR" <<'PY'
from pathlib import Path
from sys import argv

from colabfold.download import download_alphafold_params

download_alphafold_params("alphafold2_multimer_v3", Path(argv[1]))
PY
  weights_download_invoked=true
fi

BIO_SFM_APPROVE_W3_RUNTIME_VALIDATION=approve-w3-runtime-validation-only \
BIO_SFM_ROOT="$ROOT" \
W3_AF2_DATA_DIR="$DATA_DIR" \
W3_COLABFOLD_SIF="$IMAGE" \
W3_RUNTIME_RECEIPT="$VALIDATION_RECEIPT" \
APPTAINER_BIN="$APPTAINER_BIN" \
  "$ROOT/hpc/validate_w3_mechanism_runtime.sh"

python3 - \
  "$PROVISION_RECEIPT" \
  "$VALIDATION_RECEIPT" \
  "$IMAGE_URI" \
  "$IMAGE" \
  "$DATA_DIR" \
  "$image_pulled" \
  "$weights_download_invoked" \
  "$PRIOR_FETCH_OCCURRED" <<'PY'
import hashlib
import json
import os
from pathlib import Path
from sys import argv

(
    receipt_path,
    validation_receipt_path,
    image_uri,
    image_path,
    data_dir,
    image_pulled,
    weights_download_invoked,
    prior_fetch_occurred,
) = argv[1:]
validation_path = Path(validation_receipt_path)
validation = json.loads(validation_path.read_text())
validation_sha256 = hashlib.sha256(validation_path.read_bytes()).hexdigest()
payload = {
    "artifact": "m6d_w3_runtime_provision_receipt",
    "status": "w3_runtime_provisioned_and_validated_no_prediction",
    "image_uri": image_uri,
    "image_path": os.path.abspath(image_path),
    "image_pulled_this_invocation": image_pulled == "true",
    "data_dir": os.path.abspath(data_dir),
    "weights_download_invoked_this_invocation": weights_download_invoked == "true",
    "prior_fetch_occurred": prior_fetch_occurred == "true",
    "network_fetch_executed": any(
        value == "true"
        for value in (image_pulled, weights_download_invoked, prior_fetch_occurred)
    ),
    "validation_receipt": os.path.abspath(validation_receipt_path),
    "validation_receipt_sha256": validation_sha256,
    "runtime_sha256": validation["runtime_sha256"],
    "weights_manifest_sha256": validation["weights_manifest_sha256"],
    "colabfold_version": validation["colabfold_version"],
    "model_type": validation["model_type"],
    "prediction_executed": False,
    "submitted_jobs": 0,
    "gpu_used": False,
    "claim_boundary": "runtime provisioning and local-weight identity only; no prediction or scheduler action",
}
out = Path(receipt_path)
out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_name(f".{out.name}.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(tmp, out)
print(f"wrote W3 provisioning receipt to {out}")
PY

printf 'W3_COLABFOLD_SIF=%s\n' "$IMAGE"
printf 'W3_AF2_DATA_DIR=%s\n' "$DATA_DIR"
printf 'W3_RUNTIME_RECEIPT=%s\n' "$VALIDATION_RECEIPT"
printf 'W3_PROVISION_RECEIPT=%s\n' "$PROVISION_RECEIPT"
