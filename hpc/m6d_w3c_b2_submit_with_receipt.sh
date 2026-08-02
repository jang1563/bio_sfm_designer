#!/usr/bin/env bash
# Submit exactly eight Boltz and eight AF2 native-complex evaluations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

APPROVAL_TOKEN="approve-w3c-b2-native-16-h100"
APPROVAL_PACKET="${W3C_B2_APPROVAL_PACKET:-results/m6d_w3c_b2_prediction_approval_packet.json}"
NATIVE_MANIFEST="${NATIVE_MANIFEST:-configs/m6d_w3c_b2_native_screen_manifest.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3c_b2_runtime_lock.json}"
RECEIPT="${W3C_B2_RECEIPT:-results/m6d_w3c_b2_submit_receipt.jsonl}"
SUMMARY="${W3C_B2_SUBMIT_SUMMARY:-results/m6d_w3c_b2_submit_receipt_summary.json}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
BOLTZ_WRAPPER="hpc/run_predict_boltz_w3c_b2_native.sbatch"
AF2_WRAPPER="hpc/run_predict_af2_w3c_b2_native.sbatch"
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

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3c_b2_approval verify \
  --packet "$APPROVAL_PACKET"

if [ "$DRY_RUN" != "1" ] && \
  [ "${BIO_SFM_APPROVE_W3C_B2_NATIVE:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3c-B2 prediction submission without exact approval" >&2
  exit 64
fi
if [ -e "$RECEIPT" ] || [ -e "$SUMMARY" ]; then
  echo "refusing initial W3c-B2 submission because receipt evidence exists" >&2
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
    raise SystemExit("W3c-B2 approval packet contains duplicate output paths")
existing = [path for path in paths if os.path.exists(path)]
if existing:
    raise SystemExit("initial W3c-B2 outputs already exist: " + ",".join(existing))
print(f"initial output absence check clear: {len(paths)}/{len(paths)} paths absent")
PY

if [ "$DRY_RUN" = "1" ]; then
  "$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY'
import json
import sys

packet = json.load(open(sys.argv[1]))
for row in packet["execution_targets"]:
    print(
        f"dry-run {row['target_id']}: one Boltz H100 + one AF2 H100; "
        "no scheduler command"
    )
print("dry-run complete: 8 targets, 16 evaluations, zero scheduler jobs")
PY
  exit 0
fi

command -v "$SBATCH_BIN" >/dev/null 2>&1 || { echo "Slurm sbatch is required" >&2; exit 2; }
W3C_B2_BOLTZ_PYTHON="${W3C_B2_BOLTZ_PYTHON:-$HOME/.conda/envs/boltz/bin/python3.11}"
W3C_B2_BOLTZ_BIN="${W3C_B2_BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
W3C_B2_BOLTZ_CACHE="${W3C_B2_BOLTZ_CACHE:-$HOME/.boltz}"
W3C_B2_HOST_PYTHON="${W3C_B2_HOST_PYTHON:-$PYTHON_BIN}"
W3C_B2_COLABFOLD_SIF="${W3C_B2_COLABFOLD_SIF:?Set W3C_B2_COLABFOLD_SIF}"
W3C_B2_AF2_DATA_DIR="${W3C_B2_AF2_DATA_DIR:?Set W3C_B2_AF2_DATA_DIR}"
for path in "$W3C_B2_BOLTZ_PYTHON" "$W3C_B2_BOLTZ_BIN" \
  "$W3C_B2_HOST_PYTHON"; do
  test -x "$path" || { echo "required executable is unavailable: $path" >&2; exit 2; }
done
test -d "$W3C_B2_BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
test -s "$W3C_B2_COLABFOLD_SIF" || { echo "ColabFold image is unavailable" >&2; exit 2; }
test -d "$W3C_B2_AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
mkdir -p "$(dirname "$RECEIPT")" "$(dirname "$SUMMARY")" hpc_outputs/logs

require_job_id() {
  local predictor="$1" target_id="$2" job_id="$3"
  if [[ ! "$job_id" =~ ^[0-9]+(_[0-9]+)?$ ]]; then
    echo "${predictor} sbatch returned an invalid job id for ${target_id}: ${job_id}" >&2
    exit 2
  fi
}

journal_append() {
  local target_id="$1" predictor_id="$2" job_id="$3"
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3c_b2_submit_journal append \
    --packet "$APPROVAL_PACKET" --receipt "$RECEIPT" \
    --target-id "$target_id" --predictor-id "$predictor_id" --job-id "$job_id"
}

submit_target() {
  local target_id="$1" boltz_observation="$2" af2_observation="$3"
  local af2_input_dir="$4" af2_input_manifest="$5" af2_output_dir="$6"
  local boltz_job af2_job
  boltz_job=$(BIO_SFM_APPROVE_W3C_B2_NATIVE="$APPROVAL_TOKEN" \
    PROJECT_ROOT="$REPO_ROOT" ENV_PY="$W3C_B2_BOLTZ_PYTHON" \
    BOLTZ_BIN="$W3C_B2_BOLTZ_BIN" BOLTZ_CACHE="$W3C_B2_BOLTZ_CACHE" \
    W3C_B2_APPROVAL_PACKET="$APPROVAL_PACKET" NATIVE_MANIFEST="$NATIVE_MANIFEST" \
    RUNTIME_LOCK="$RUNTIME_LOCK" TARGET_ID="$target_id" \
    RUNTIME_OBSERVATION="$boltz_observation" \
    "$SBATCH_BIN" --parsable --no-requeue --time="$PREDICT_TIME_LIMIT" \
      "$BOLTZ_WRAPPER")
  require_job_id boltz2_complex "$target_id" "$boltz_job"
  journal_append "$target_id" boltz2_complex "$boltz_job"

  af2_job=$(BIO_SFM_APPROVE_W3C_B2_NATIVE="$APPROVAL_TOKEN" \
    PROJECT_ROOT="$REPO_ROOT" HOST_PYTHON="$W3C_B2_HOST_PYTHON" \
    COLABFOLD_SIF="$W3C_B2_COLABFOLD_SIF" AF2_DATA_DIR="$W3C_B2_AF2_DATA_DIR" \
    W3C_B2_APPROVAL_PACKET="$APPROVAL_PACKET" NATIVE_MANIFEST="$NATIVE_MANIFEST" \
    RUNTIME_LOCK="$RUNTIME_LOCK" TARGET_ID="$target_id" \
    RUNTIME_OBSERVATION="$af2_observation" AF2_INPUT_DIR="$af2_input_dir" \
    AF2_INPUT_MANIFEST="$af2_input_manifest" AF2_OUTPUT_DIR="$af2_output_dir" \
    "$SBATCH_BIN" --parsable --no-requeue --time="$PREDICT_TIME_LIMIT" \
      "$AF2_WRAPPER")
  require_job_id af2_multimer_colabfold_v1 "$target_id" "$af2_job"
  journal_append "$target_id" af2_multimer_colabfold_v1 "$af2_job"
  echo "$target_id: Boltz $boltz_job + AF2 $af2_job"
}

"$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY' | while IFS=$'\t' read -r target_id boltz_observation af2_observation af2_input_dir af2_input_manifest af2_output_dir; do
import json
import sys

packet = json.load(open(sys.argv[1]))
for row in packet["execution_targets"]:
    print("\t".join(str(row[key]) for key in (
        "target_id",
        "boltz_runtime_observation",
        "af2_runtime_observation",
        "af2_input_dir",
        "af2_input_manifest",
        "af2_output_dir",
    )))
PY
  submit_target "$target_id" "$boltz_observation" "$af2_observation" \
    "$af2_input_dir" "$af2_input_manifest" "$af2_output_dir"
done

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3c_b2_submit_journal summary \
  --packet "$APPROVAL_PACKET" --receipt "$RECEIPT" --out "$SUMMARY"
echo "W3c-B2 submission receipt: $RECEIPT"
echo "W3c-B2 submission summary: $SUMMARY"
