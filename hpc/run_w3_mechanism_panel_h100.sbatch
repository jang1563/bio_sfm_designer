#!/usr/bin/env bash
#SBATCH --job-name=w3-af2-mechanism
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=12:00:00

set -euo pipefail

ROOT="${W3_RUN_ROOT:?W3_RUN_ROOT is required}"
HOST_PYTHON="${W3_HOST_PYTHON_BIN:?W3_HOST_PYTHON_BIN is required}"
COLABFOLD_SIF="${W3_COLABFOLD_SIF:?W3_COLABFOLD_SIF is required}"
AF2_DATA_DIR="${W3_AF2_DATA_DIR:?W3_AF2_DATA_DIR is required}"
RUNTIME_RECEIPT="${W3_RUNTIME_RECEIPT:?W3_RUNTIME_RECEIPT is required}"
APPROVAL_TOKEN="approve-w3-mechanism-panel-h100"

if [ "${BIO_SFM_APPROVE_W3_MECHANISM_PANEL:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3 H100 execution without exact approval" >&2
  exit 64
fi
if [ ! -x "$HOST_PYTHON" ]; then
  echo "W3 host Python is not executable: $HOST_PYTHON" >&2
  exit 65
fi

APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
if [ -z "$APPTAINER_BIN" ]; then
  echo "apptainer/singularity is unavailable" >&2
  exit 66
fi

export PATH="$(dirname "$HOST_PYTHON"):$PATH"
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1
cd "$ROOT"

"$APPTAINER_BIN" exec --nv --net --network none "$COLABFOLD_SIF" python3 - <<'PY'
import jax

devices = jax.devices()
if not devices or not any(device.platform == "gpu" for device in devices):
    raise SystemExit(f"W3 H100 preflight did not expose a GPU: {devices}")
print(f"W3 GPU preflight devices: {devices}")
PY

BIO_SFM_ROOT="$ROOT" \
BIO_SFM_APPROVE_W3_MECHANISM_PANEL="$APPROVAL_TOKEN" \
W3_DRY_RUN=0 \
W3_COLABFOLD_SIF="$COLABFOLD_SIF" \
W3_AF2_DATA_DIR="$AF2_DATA_DIR" \
W3_RUNTIME_RECEIPT="$RUNTIME_RECEIPT" \
APPTAINER_BIN="$APPTAINER_BIN" \
  "$ROOT/hpc/run_w3_mechanism_panel_guarded.sh"

printf 'W3 mechanism panel completed under Slurm job %s\n' "${SLURM_JOB_ID:-unknown}"
