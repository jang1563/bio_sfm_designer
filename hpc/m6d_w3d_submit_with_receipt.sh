#!/usr/bin/env bash
# Submit exactly eight Boltz and sixteen AF2 W3d native diagnostic evaluations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd -P)"
cd "$REPO_ROOT"

APPROVAL_TOKEN="approve-w3d-native-factorial-24-h100"
APPROVAL_PACKET="${W3D_APPROVAL_PACKET:-results/m6d_w3d_prediction_approval_packet.json}"
INPUT_MANIFEST="${W3D_INPUT_MANIFEST:-configs/m6d_w3d_prospective_input_manifest.json}"
RUNTIME_RECEIPT="${W3D_RUNTIME_RECEIPT:-results/m6d_w3d_runtime_validation_receipt.json}"
SUBMIT_RECEIPT="${W3D_SUBMIT_RECEIPT:-results/m6d_w3d_submit_receipt.jsonl}"
SUMMARY="${W3D_SUBMIT_SUMMARY:-results/m6d_w3d_submit_receipt_summary.json}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
BOLTZ_WRAPPER="hpc/run_predict_boltz_w3d_native.sbatch"
AF2_WRAPPER="hpc/run_predict_af2_w3d_native.sbatch"
PREDICT_TIME_LIMIT="01:00:00"

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

if [[ "$PYTHON_BIN" == */* ]]; then
  test -x "$PYTHON_BIN" || { echo "BIO_SFM_PYTHON is not executable" >&2; exit 2; }
else
  PYTHON_BIN="$(command -v "$PYTHON_BIN")" || { echo "BIO_SFM_PYTHON is unavailable" >&2; exit 2; }
fi

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3d_approval verify \
  --packet "$APPROVAL_PACKET"
if [ "$DRY_RUN" != "1" ] && \
  [ "${BIO_SFM_APPROVE_W3D_PANEL:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3d prediction submission without exact approval" >&2
  exit 64
fi
if [ -e "$SUBMIT_RECEIPT" ] || [ -e "$SUMMARY" ]; then
  echo "refusing initial W3d submission because receipt evidence exists" >&2
  echo "use a separately audited recovery path; do not rerun this bridge" >&2
  exit 2
fi

bash -n "$BOLTZ_WRAPPER" "$AF2_WRAPPER"
"$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY'
import json
import os
import sys

packet = json.load(open(sys.argv[1]))
paths = packet.get("initial_output_paths", [])
if len(paths) != len(set(paths)):
    raise SystemExit("W3d approval packet contains duplicate output paths")
existing = [path for path in paths if os.path.exists(path)]
if existing:
    raise SystemExit("initial W3d outputs already exist: " + ",".join(existing))
print(f"initial output absence check clear: {len(paths)}/{len(paths)} paths absent")
PY

if [ "$DRY_RUN" = "1" ]; then
  "$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY'
import collections
import json
import sys

packet = json.load(open(sys.argv[1]))
counts = collections.Counter(row["predictor_id"] for row in packet["execution_cells"])
for row in packet["execution_cells"]:
    print(
        f"dry-run {row['cell_id']}: one {row['predictor_id']} H100; "
        "no scheduler command"
    )
if counts != {"boltz2_complex": 8, "af2_multimer_colabfold_v1": 16}:
    raise SystemExit(f"unexpected W3d predictor counts: {dict(counts)}")
print("dry-run complete: 8 Boltz + 16 AF2 = 24 evaluations, zero scheduler jobs")
PY
  exit 0
fi

command -v "$SBATCH_BIN" >/dev/null 2>&1 || { echo "Slurm sbatch is required" >&2; exit 2; }
W3D_BOLTZ_PYTHON="${W3D_BOLTZ_PYTHON:-$HOME/.conda/envs/boltz/bin/python3.11}"
W3D_BOLTZ_BIN="${W3D_BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
W3D_BOLTZ_CACHE="${W3D_BOLTZ_CACHE:-$HOME/.boltz}"
W3D_HOST_PYTHON="${W3D_HOST_PYTHON:-$PYTHON_BIN}"
W3D_COLABFOLD_SIF="${W3D_COLABFOLD_SIF:?Set W3D_COLABFOLD_SIF}"
W3D_AF2_DATA_DIR="${W3D_AF2_DATA_DIR:?Set W3D_AF2_DATA_DIR}"
for path in "$W3D_BOLTZ_PYTHON" "$W3D_BOLTZ_BIN" "$W3D_HOST_PYTHON"; do
  test -x "$path" || { echo "required executable is unavailable: $path" >&2; exit 2; }
done
test -d "$W3D_BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
test -s "$W3D_COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$W3D_AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
mkdir -p "$(dirname "$SUBMIT_RECEIPT")" "$(dirname "$SUMMARY")" hpc_outputs/logs

require_job_id() {
  local cell_id="$1" job_id="$2"
  if [[ ! "$job_id" =~ ^[0-9]+(_[0-9]+)?$ ]]; then
    echo "sbatch returned an invalid job id for ${cell_id}: ${job_id}" >&2
    exit 2
  fi
}

journal_append() {
  local cell_id="$1" job_id="$2"
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3d_submit_journal append \
    --packet "$APPROVAL_PACKET" --receipt "$SUBMIT_RECEIPT" \
    --cell-id "$cell_id" --job-id "$job_id"
}

submit_cell() {
  local cell_id="$1" target_id="$2" representation_id="$3" predictor_id="$4"
  local input_path="$5" output_dir="$6" record_path="$7" job_id
  if [ "$predictor_id" = "boltz2_complex" ]; then
    job_id=$(BIO_SFM_APPROVE_W3D_PANEL="$APPROVAL_TOKEN" \
      PROJECT_ROOT="$REPO_ROOT" ENV_PY="$W3D_BOLTZ_PYTHON" \
      BOLTZ_BIN="$W3D_BOLTZ_BIN" BOLTZ_CACHE="$W3D_BOLTZ_CACHE" \
      W3D_APPROVAL_PACKET="$APPROVAL_PACKET" W3D_INPUT_MANIFEST="$INPUT_MANIFEST" \
      W3D_RUNTIME_RECEIPT="$RUNTIME_RECEIPT" TARGET_ID="$target_id" \
      REPRESENTATION_ID="$representation_id" INPUT_PATH="$input_path" \
      OUTPUT_DIR="$output_dir" RECORD_PATH="$record_path" \
      "$SBATCH_BIN" --parsable --no-requeue --time="$PREDICT_TIME_LIMIT" \
        "$BOLTZ_WRAPPER")
  elif [ "$predictor_id" = "af2_multimer_colabfold_v1" ]; then
    job_id=$(BIO_SFM_APPROVE_W3D_PANEL="$APPROVAL_TOKEN" \
      PROJECT_ROOT="$REPO_ROOT" HOST_PYTHON="$W3D_HOST_PYTHON" \
      COLABFOLD_SIF="$W3D_COLABFOLD_SIF" AF2_DATA_DIR="$W3D_AF2_DATA_DIR" \
      W3D_APPROVAL_PACKET="$APPROVAL_PACKET" W3D_INPUT_MANIFEST="$INPUT_MANIFEST" \
      W3D_RUNTIME_RECEIPT="$RUNTIME_RECEIPT" TARGET_ID="$target_id" \
      REPRESENTATION_ID="$representation_id" INPUT_PATH="$input_path" \
      OUTPUT_DIR="$output_dir" RECORD_PATH="$record_path" \
      "$SBATCH_BIN" --parsable --no-requeue --time="$PREDICT_TIME_LIMIT" \
        "$AF2_WRAPPER")
  else
    echo "unsupported W3d predictor: $predictor_id" >&2
    exit 2
  fi
  require_job_id "$cell_id" "$job_id"
  journal_append "$cell_id" "$job_id"
  echo "$cell_id: $job_id"
}

"$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY' | while IFS=$'\t' read -r cell_id target_id representation_id predictor_id input_path output_dir record_path; do
import json
import sys

packet = json.load(open(sys.argv[1]))
for row in packet["execution_cells"]:
    print("\t".join(str(row[key]) for key in (
        "cell_id",
        "target_id",
        "representation_id",
        "predictor_id",
        "input_path",
        "output_dir",
        "record_path",
    )))
PY
  submit_cell "$cell_id" "$target_id" "$representation_id" "$predictor_id" \
    "$input_path" "$output_dir" "$record_path"
done

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3d_submit_journal summary \
  --packet "$APPROVAL_PACKET" --receipt "$SUBMIT_RECEIPT" --out "$SUMMARY"
echo "W3d submission receipt: $SUBMIT_RECEIPT"
echo "W3d submission summary: $SUMMARY"
