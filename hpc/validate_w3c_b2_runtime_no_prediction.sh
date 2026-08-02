#!/usr/bin/env bash
# Reobserve the exact W3c-B2 predictor runtimes without scheduler or prediction.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

HOST_PYTHON="${BIO_SFM_PYTHON:-python3}"
BOLTZ_PYTHON="${W3C_B2_BOLTZ_PYTHON:-$HOME/.conda/envs/boltz/bin/python}"
BOLTZ_BIN="${W3C_B2_BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
BOLTZ_CACHE="${W3C_B2_BOLTZ_CACHE:-$HOME/.boltz}"
COLABFOLD_SIF="${W3C_B2_COLABFOLD_SIF:?Set W3C_B2_COLABFOLD_SIF}"
AF2_DATA_DIR="${W3C_B2_AF2_DATA_DIR:?Set W3C_B2_AF2_DATA_DIR}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3c_validity_first_protocol.json}"
NATIVE_MANIFEST="${NATIVE_MANIFEST:-configs/m6d_w3c_b2_native_screen_manifest.json}"
B1_COMPLETION="${B1_COMPLETION:-results/m6d_w3c_b1_target_msa_completion.json}"
W3B_RUNTIME_LOCK="${W3B_RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
BOLTZ_OBSERVATION="${BOLTZ_OBSERVATION:-results/m6d_w3c_b2_boltz_runtime_observation.json}"
AF2_OBSERVATION="${AF2_OBSERVATION:-results/m6d_w3c_b2_af2_runtime_observation.json}"
RUNTIME_READINESS="${RUNTIME_READINESS:-results/m6d_w3c_b2_runtime_readiness.json}"
RUNTIME_READINESS_MD="${RUNTIME_READINESS_MD:-results/m6d_w3c_b2_runtime_readiness.md}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3c_b2_runtime_lock.json}"

if [[ "$HOST_PYTHON" == */* ]]; then
  test -x "$HOST_PYTHON" || { echo "host Python is not executable: $HOST_PYTHON" >&2; exit 2; }
else
  HOST_PYTHON="$(command -v "$HOST_PYTHON")" || { echo "host Python is unavailable" >&2; exit 2; }
fi
test -x "$BOLTZ_PYTHON" || { echo "Boltz Python is unavailable" >&2; exit 2; }
test -x "$BOLTZ_BIN" || { echo "Boltz executable is unavailable" >&2; exit 2; }
test -d "$BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
test -s "$COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }

for path in "$BOLTZ_OBSERVATION" "$AF2_OBSERVATION" "$RUNTIME_LOCK"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3c-B2 runtime artifact: $path" >&2; exit 2; }
done

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

"$BOLTZ_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-boltz --protocol "$PROTOCOL" --native-manifest "$NATIVE_MANIFEST" \
  --b1-completion "$B1_COMPLETION" --w3b-runtime-lock "$W3B_RUNTIME_LOCK" \
  --cache-dir "$BOLTZ_CACHE" --boltz-bin "$BOLTZ_BIN" --out "$BOLTZ_OBSERVATION"

APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }
COLABFOLD_VERSION="$($APPTAINER_BIN exec --containall --net --network none \
  "$COLABFOLD_SIF" python3 -c 'import importlib.metadata; print(importlib.metadata.version("colabfold"))')"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-af2 --protocol "$PROTOCOL" --native-manifest "$NATIVE_MANIFEST" \
  --b1-completion "$B1_COMPLETION" --w3b-runtime-lock "$W3B_RUNTIME_LOCK" \
  --runtime-path "$COLABFOLD_SIF" --data-dir "$AF2_DATA_DIR" \
  --colabfold-version "$COLABFOLD_VERSION" --out "$AF2_OBSERVATION"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  packet --protocol "$PROTOCOL" --native-manifest "$NATIVE_MANIFEST" \
  --b1-completion "$B1_COMPLETION" --w3b-runtime-lock "$W3B_RUNTIME_LOCK" \
  --boltz-observation "$BOLTZ_OBSERVATION" --af2-observation "$AF2_OBSERVATION" \
  --out-readiness "$RUNTIME_READINESS" --out-readiness-md "$RUNTIME_READINESS_MD" \
  --out-runtime-lock "$RUNTIME_LOCK"

echo "W3c-B2 runtime reobservation complete: no scheduler, GPU, network fetch, or prediction"
