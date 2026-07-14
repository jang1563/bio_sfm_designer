#!/usr/bin/env bash
# Submit exactly three W3b fit ProteinMPNN -> matched Boltz/AF2 job triplets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

APPROVAL_TOKEN="approve-w3b-fit-180-matched-h100"
APPROVAL_PACKET="${W3B_FIT_APPROVAL_PACKET:-results/m6d_w3b_fit_approval_packet.json}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
EXECUTION_READINESS="${EXECUTION_READINESS:-results/m6d_w3b_execution_lock_readiness.json}"
RUNTIME_READINESS="${RUNTIME_READINESS:-results/m6d_w3b_runtime_lock_readiness.json}"
MATCHED_READINESS="${MATCHED_READINESS:-results/m6d_w3b_matched_record_contract.json}"
RECEIPT="${W3B_FIT_RECEIPT:-results/m6d_w3b_fit_submit_receipt.jsonl}"
SUMMARY="${W3B_FIT_SUMMARY:-results/m6d_w3b_fit_submit_receipt_summary.json}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
GENERATOR_WRAPPER="hpc/run_generate_proteinmpnn_w3b_fit.sbatch"
BOLTZ_WRAPPER="hpc/run_predict_boltz_w3b_fit.sbatch"
AF2_WRAPPER="hpc/run_predict_af2_w3b_fit.sbatch"
PREDICT_TIME_LIMIT="04:00:00"

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

if [[ "$PYTHON_BIN" == */* ]]; then
  test -x "$PYTHON_BIN" || { echo "BIO_SFM_PYTHON is not executable: $PYTHON_BIN" >&2; exit 2; }
else
  PYTHON_BIN="$(command -v "$PYTHON_BIN")" || { echo "BIO_SFM_PYTHON is unavailable" >&2; exit 2; }
fi

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_packet \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --execution-readiness "$EXECUTION_READINESS" --runtime-readiness "$RUNTIME_READINESS" \
  --matched-readiness "$MATCHED_READINESS" \
  --verify-approval-packet "$APPROVAL_PACKET"

if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W3B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b fit submission without exact approval" >&2
  exit 64
fi
if [ "$DRY_RUN" != "1" ] && { [ -e "$RECEIPT" ] || [ -e "$SUMMARY" ]; }; then
  echo "refusing initial W3b fit submission because receipt or summary already exists" >&2
  echo "use a separately audited recovery path; do not rerun the initial bridge" >&2
  exit 2
fi

bash -n "$GENERATOR_WRAPPER" "$BOLTZ_WRAPPER" "$AF2_WRAPPER"
"$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY'
import json
import os
import sys

packet = json.load(open(sys.argv[1]))
contract = packet.get("approval_contract", {})
targets = packet.get("fit_targets", [])
if not (
    packet.get("status") == "w3b_fit_approval_packet_ready_no_submit"
    and contract.get("stage") == "fit"
    and contract.get("target_count") == 3
    and contract.get("candidate_designs") == 180
    and contract.get("matched_predictor_evaluations") == 360
    and len(targets) == 3
    and all(row.get("records_planned") == 60 for row in targets)
):
    raise SystemExit("W3b fit approval packet scope is invalid")
paths = []
for row in targets:
    root = row["out_prefix"]
    paths.extend([
        row["candidates"], row["boltz_records"], row["af2_records"],
        os.path.join(root, "boltz2_observed_runtime_identity.json"),
        os.path.join(root, "boltz2_runtime_receipt.json"),
        os.path.join(root, "af2_inputs"),
        os.path.join(root, "af2_input_manifest.json"),
        os.path.join(root, "af2_predictions"),
        os.path.join(root, "af2_observed_runtime_identity.json"),
        os.path.join(root, "af2_multimer_runtime_receipt.json"),
    ])
existing = [path for path in paths if os.path.exists(path)]
if existing:
    raise SystemExit("initial W3b fit outputs already exist: " + ",".join(existing))
print(f"initial output absence check clear: {len(paths)}/{len(paths)} paths absent")
PY

if [ "$DRY_RUN" = "1" ]; then
  echo "## W3b fit dry run: no sbatch calls and no receipt writes"
else
  command -v "$SBATCH_BIN" >/dev/null 2>&1 || { echo "Slurm sbatch is required" >&2; exit 2; }
  W3B_MPNN_PYTHON="${W3B_MPNN_PYTHON:-$HOME/.conda/envs/bioguard/bin/python}"
  W3B_MPNN_DIR="${W3B_MPNN_DIR:-$HOME/ProteinMPNN}"
  W3B_BOLTZ_PYTHON="${W3B_BOLTZ_PYTHON:-$HOME/.conda/envs/boltz/bin/python}"
  W3B_BOLTZ_BIN="${W3B_BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
  W3B_BOLTZ_CACHE="${W3B_BOLTZ_CACHE:-$HOME/.boltz}"
  W3B_HOST_PYTHON="${W3B_HOST_PYTHON:-$PYTHON_BIN}"
  W3B_COLABFOLD_SIF="${W3B_COLABFOLD_SIF:?Set W3B_COLABFOLD_SIF}"
  W3B_AF2_DATA_DIR="${W3B_AF2_DATA_DIR:?Set W3B_AF2_DATA_DIR}"
  for path in "$W3B_MPNN_PYTHON" "$W3B_BOLTZ_PYTHON" "$W3B_BOLTZ_BIN" "$W3B_HOST_PYTHON"; do
    test -x "$path" || { echo "required W3b executable is unavailable: $path" >&2; exit 2; }
  done
  test -d "$W3B_MPNN_DIR" || { echo "ProteinMPNN checkout is unavailable" >&2; exit 2; }
  test -d "$W3B_BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
  test -s "$W3B_COLABFOLD_SIF" || { echo "ColabFold container is unavailable" >&2; exit 2; }
  test -d "$W3B_AF2_DATA_DIR" || { echo "AF2 data directory is unavailable" >&2; exit 2; }
  mkdir -p "$(dirname "$RECEIPT")" "$(dirname "$SUMMARY")" hpc_outputs/logs
fi

require_job_id() {
  local stage="$1" target_id="$2" job_id="$3"
  if [ -z "${job_id//[[:space:]]/}" ] || [[ "$job_id" =~ [[:space:]] ]]; then
    echo "${stage} sbatch returned an invalid job id for ${target_id}: ${job_id}" >&2
    exit 2
  fi
}

journal_append() {
  local stage="$1" target_id="$2" gen_job="$3" boltz_job="$4" af2_job="$5"
  local candidates="$6" boltz_records="$7" af2_records="$8"
  local args=(
    -m bio_sfm_designer.experiments.m6d_w3b_fit_submit_journal append
    --receipt "$RECEIPT" --stage "$stage" --target-id "$target_id"
    --approval-packet "$APPROVAL_PACKET" --proteinmpnn-job-id "$gen_job"
    --candidates "$candidates" --boltz-records "$boltz_records" --af2-records "$af2_records"
  )
  if [ -n "$boltz_job" ]; then args+=(--boltz-job-id "$boltz_job"); fi
  if [ -n "$af2_job" ]; then args+=(--af2-job-id "$af2_job"); fi
  "$PYTHON_BIN" "${args[@]}"
}

submit_target() {
  local target_id="$1" prepared_pdb="$2" target_chain="$3" binder_chain="$4"
  local target_msa="$5" candidates="$6" boltz_records="$7" af2_records="$8"
  local out_prefix="$9" num_seq="${10}" temp="${11}" seed="${12}"
  local objective="${13}" namespace="${14}" id_prefix="${15}"
  local boltz_identity="${out_prefix}/boltz2_observed_runtime_identity.json"
  local boltz_receipt="${out_prefix}/boltz2_runtime_receipt.json"
  local af2_input_dir="${out_prefix}/af2_inputs"
  local af2_input_manifest="${out_prefix}/af2_input_manifest.json"
  local af2_output_dir="${out_prefix}/af2_predictions"
  local af2_identity="${out_prefix}/af2_observed_runtime_identity.json"
  local af2_receipt="${out_prefix}/af2_multimer_runtime_receipt.json"

  [ "$num_seq" = "60" ] || { echo "unexpected W3b fit count for $target_id" >&2; exit 2; }
  [ "$namespace" = "w3b-fit-v1" ] || { echo "unexpected W3b namespace for $target_id" >&2; exit 2; }
  [ "$id_prefix" = "${namespace}-${target_id}" ] || { echo "unexpected W3b ID prefix for $target_id" >&2; exit 2; }
  if [ "$DRY_RUN" = "1" ]; then
    echo "dry-run ${target_id}: 60 ProteinMPNN -> matched H100 Boltz + AF2 (120 predictor evaluations)"
    return 0
  fi

  local gen_job boltz_job af2_job
  gen_job=$(BIO_SFM_APPROVE_W3B_FIT="$APPROVAL_TOKEN" PROJECT_ROOT="$REPO_ROOT" \
    ENV_PY="$W3B_MPNN_PYTHON" MPNN_DIR="$W3B_MPNN_DIR" \
    PROTOCOL="$PROTOCOL" EXECUTION_MANIFEST="$EXECUTION_MANIFEST" \
    INPUT_LOCK="$INPUT_LOCK" RUNTIME_LOCK="$RUNTIME_LOCK" \
    TARGET_ID="$target_id" STAGE=fit PREPARED_PDB="$prepared_pdb" \
    TARGET_CHAIN="$target_chain" BINDER_CHAIN="$binder_chain" NUM_SEQ="$num_seq" \
    TEMP="$temp" SEED="$seed" OBJECTIVE="$objective" SEED_NAMESPACE="$namespace" \
    ID_PREFIX="$id_prefix" CANDIDATES="$candidates" \
    "$SBATCH_BIN" --parsable "$GENERATOR_WRAPPER")
  require_job_id ProteinMPNN "$target_id" "$gen_job"
  journal_append proteinmpnn_submitted "$target_id" "$gen_job" "" "" \
    "$candidates" "$boltz_records" "$af2_records"

  boltz_job=$(BIO_SFM_APPROVE_W3B_FIT="$APPROVAL_TOKEN" PROJECT_ROOT="$REPO_ROOT" \
    ENV_PY="$W3B_BOLTZ_PYTHON" BOLTZ_BIN="$W3B_BOLTZ_BIN" BOLTZ_CACHE="$W3B_BOLTZ_CACHE" \
    PROTOCOL="$PROTOCOL" EXECUTION_MANIFEST="$EXECUTION_MANIFEST" \
    INPUT_LOCK="$INPUT_LOCK" RUNTIME_LOCK="$RUNTIME_LOCK" \
    TARGET_ID="$target_id" STAGE=fit PREPARED_PDB="$prepared_pdb" \
    TARGET_CHAIN="$target_chain" BINDER_CHAIN="$binder_chain" TARGET_MSA="$target_msa" \
    CANDIDATES="$candidates" RECORDS="$boltz_records" \
    RUNTIME_IDENTITY="$boltz_identity" RUNTIME_RECEIPT="$boltz_receipt" \
    "$SBATCH_BIN" --no-requeue --time="$PREDICT_TIME_LIMIT" --dependency="afterok:${gen_job}" \
      --parsable "$BOLTZ_WRAPPER")
  require_job_id Boltz "$target_id" "$boltz_job"
  journal_append boltz_submitted "$target_id" "$gen_job" "$boltz_job" "" \
    "$candidates" "$boltz_records" "$af2_records"

  af2_job=$(BIO_SFM_APPROVE_W3B_FIT="$APPROVAL_TOKEN" PROJECT_ROOT="$REPO_ROOT" \
    HOST_PYTHON="$W3B_HOST_PYTHON" COLABFOLD_SIF="$W3B_COLABFOLD_SIF" \
    AF2_DATA_DIR="$W3B_AF2_DATA_DIR" PROTOCOL="$PROTOCOL" \
    EXECUTION_MANIFEST="$EXECUTION_MANIFEST" INPUT_LOCK="$INPUT_LOCK" \
    RUNTIME_LOCK="$RUNTIME_LOCK" TARGET_ID="$target_id" STAGE=fit \
    PREPARED_PDB="$prepared_pdb" TARGET_CHAIN="$target_chain" BINDER_CHAIN="$binder_chain" \
    TARGET_MSA="$target_msa" CANDIDATES="$candidates" AF2_INPUT_DIR="$af2_input_dir" \
    AF2_INPUT_MANIFEST="$af2_input_manifest" AF2_OUTPUT_DIR="$af2_output_dir" \
    RECORDS="$af2_records" RUNTIME_IDENTITY="$af2_identity" RUNTIME_RECEIPT="$af2_receipt" \
    "$SBATCH_BIN" --no-requeue --time="$PREDICT_TIME_LIMIT" --dependency="afterok:${gen_job}" \
      --parsable "$AF2_WRAPPER")
  require_job_id AF2 "$target_id" "$af2_job"
  journal_append af2_submitted "$target_id" "$gen_job" "$boltz_job" "$af2_job" \
    "$candidates" "$boltz_records" "$af2_records"
  echo "${target_id}: ProteinMPNN ${gen_job} -> Boltz ${boltz_job} + AF2 ${af2_job}"
}

"$PYTHON_BIN" - "$APPROVAL_PACKET" <<'PY' | while IFS=$'\t' read -r target_id prepared_pdb target_chain binder_chain target_msa candidates boltz_records af2_records out_prefix num_seq temp seed objective namespace id_prefix; do
import json
import sys

packet = json.load(open(sys.argv[1]))
targets = packet["fit_targets"]
if len(targets) != 3:
    raise SystemExit("W3b fit packet must contain exactly three targets")
for target in targets:
    print("\t".join(str(target[key]) for key in (
        "target_id", "prepared_pdb", "target_chain", "binder_chain", "target_msa",
        "candidates", "boltz_records", "af2_records", "out_prefix", "records_planned",
        "proteinmpnn_temperature", "proteinmpnn_seed", "proteinmpnn_objective",
        "seed_namespace", "id_prefix",
    )))
PY
  submit_target "$target_id" "$prepared_pdb" "$target_chain" "$binder_chain" \
    "$target_msa" "$candidates" "$boltz_records" "$af2_records" "$out_prefix" \
    "$num_seq" "$temp" "$seed" "$objective" "$namespace" "$id_prefix"
done

if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run complete: 3 fit targets, 180 candidates, 360 predictor evaluations, zero scheduler jobs"
  exit 0
fi

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_submit_journal summary \
  --approval-packet "$APPROVAL_PACKET" --receipt "$RECEIPT" --out "$SUMMARY"
echo "W3b fit submit receipt: $RECEIPT"
echo "W3b fit submit summary: $SUMMARY"
