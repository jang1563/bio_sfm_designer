#!/usr/bin/env bash
# Reobserve AF2 and resolve all sixteen W3d paths without model inference.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
HOST_PYTHON="${HOST_PYTHON:-python3}"
COLABFOLD_SIF="${W3D_COLABFOLD_SIF:?Set W3D_COLABFOLD_SIF}"
AF2_DATA_DIR="${W3D_AF2_DATA_DIR:?Set W3D_AF2_DATA_DIR}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
AF2_INPUT_PATH_PLAN="${AF2_INPUT_PATH_PLAN:?Set AF2_INPUT_PATH_PLAN}"
AF2_RUNTIME_OBSERVATION="${AF2_RUNTIME_OBSERVATION:?Set AF2_RUNTIME_OBSERVATION}"
AF2_PATH_PROBES="${AF2_PATH_PROBES:?Set AF2_PATH_PROBES}"

cd "$PROJECT_ROOT"
if [[ "$HOST_PYTHON" == */* ]]; then
  test -x "$HOST_PYTHON" || { echo "host Python is unavailable" >&2; exit 2; }
else
  HOST_PYTHON="$(command -v "$HOST_PYTHON")" || { echo "host Python is unavailable" >&2; exit 2; }
fi
test -s "$COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
for path in "$AF2_INPUT_PATH_PLAN" "$AF2_RUNTIME_OBSERVATION" "$AF2_PATH_PROBES"; do
  [ ! -e "$path" ] || { echo "refusing to overwrite W3d AF2 validation artifact: $path" >&2; exit 2; }
done
APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$APPTAINER_BIN" ] || { echo "apptainer/singularity is unavailable" >&2; exit 2; }

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export APPTAINERENV_PYTHONNOUSERSITE=1
unset PYTHONHOME

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  verify-inputs --input-manifest "$INPUT_MANIFEST" --project-root "$PROJECT_ROOT"

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
  --colabfold-version "$COLABFOLD_VERSION" --out "$AF2_RUNTIME_OBSERVATION"

"$HOST_PYTHON" -m bio_sfm_designer.experiments.m6d_w3d_input_runtime \
  emit-path-plan --input-manifest "$INPUT_MANIFEST" --project-root "$PROJECT_ROOT" \
  --predictor-id af2_multimer_colabfold_v1 > "$AF2_INPUT_PATH_PLAN"

"$APPTAINER_BIN" exec --containall --net --network none \
  --pwd "$PROJECT_ROOT" --bind "$PROJECT_ROOT:$PROJECT_ROOT" \
  --bind "$AF2_DATA_DIR:$AF2_DATA_DIR" "$COLABFOLD_SIF" python3 -c '
import hashlib
import json
import os
from pathlib import Path
import sys

cwd = os.getcwd()
for raw in sys.stdin:
    row = json.loads(raw)
    input_path = row["input_path"]
    output_path = row["output_path"]
    project_root = row["project_root"]
    digest = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    checks = (
        cwd == project_root,
        os.path.isabs(input_path),
        os.path.isabs(output_path),
        os.path.commonpath((input_path, project_root)) == project_root,
        os.path.commonpath((output_path, project_root)) == project_root,
        digest == row["input_sha256"],
        Path(output_path).parent.is_dir(),
    )
    if not all(checks):
        raise SystemExit("AF2 path probe failed for " + row["cell_id"])
    print(json.dumps({
        "cell_id": row["cell_id"],
        "predictor_id": row["predictor_id"],
        "runtime_surface": "af2_container",
        "input_sha256": digest,
        "input_absolute": True,
        "output_absolute": True,
        "project_root_bound": True,
        "container_working_directory_explicit": True,
        "raw_paths_published": False,
    }, sort_keys=True))
' < "$AF2_INPUT_PATH_PLAN" > "$AF2_PATH_PROBES"

echo "W3d AF2 runtime and sixteen absolute container paths validated without prediction"
