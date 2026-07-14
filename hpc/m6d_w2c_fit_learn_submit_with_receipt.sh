#!/usr/bin/env bash
# Submit exactly eight W2c threshold-learning ProteinMPNN -> H100 Boltz pairs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

MANIFEST="${MANIFEST:-configs/m6d_w2c_fit_learn_targets.json}"
INPUT_LOCK="configs/m6d_w2c_fit_learn_input_lock.json"
SUBMIT_RECEIPT="${SUBMIT_RECEIPT:-results/m6d_w2c_fit_learn_submit_receipt.jsonl}"
SUBMIT_SUMMARY="${SUBMIT_SUMMARY:-results/m6d_w2c_fit_learn_submit_receipt_summary.json}"
WORKSTREAM="m6d_w2c_fit_learn"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
HISTORICAL_REGISTRY="configs/m6d_w2_historical_target_registry.json"
GENERATE_WRAPPER="hpc/run_generate_proteinmpnn_w2c_complex.sbatch"
PREDICT_WRAPPER="hpc/run_predict_boltz_w2c_complex.sbatch"
APPROVAL_TOKEN="approve-w2c-fit-learn-480-h100"
PREDICT_PARTITION="preempt_gpu"
PREDICT_QOS="low"
PREDICT_GRES="gpu:h100:1"
EXPECTED_MANIFEST_SHA256="c60e1d001f187724bb00a49484158efad0997ca418a0589e5446819fca59daa8"
EXPECTED_INPUT_LOCK_SHA256="904262663513ad243f3dc5ab8160af0b1fb5965939dd5a815066f285cedf9674"

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME

if [[ "$PYTHON_BIN" == */* ]]; then
  test -x "$PYTHON_BIN" || { echo "BIO_SFM_PYTHON is not executable: $PYTHON_BIN" >&2; exit 2; }
else
  PYTHON_BIN="$(command -v "$PYTHON_BIN")" || {
    echo "BIO_SFM_PYTHON is not available on PATH" >&2
    exit 2
  }
fi
bash -n "$GENERATE_WRAPPER" "$PREDICT_WRAPPER"

"$PYTHON_BIN" - "$MANIFEST" "$INPUT_LOCK" \
  "$EXPECTED_MANIFEST_SHA256" "$EXPECTED_INPUT_LOCK_SHA256" <<'PY'
import hashlib, os, sys

for path, expected in ((sys.argv[1], sys.argv[3]), (sys.argv[2], sys.argv[4])):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise SystemExit(f"missing or empty W2c fit-learn bound artifact: {path}")
    with open(path, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if actual != expected:
        raise SystemExit(
            f"stale W2c fit-learn bound artifact: {path} "
            f"expected_sha256={expected} actual_sha256={actual}"
        )
PY
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2c_fit_learn_lock \
  --stage-manifest "$MANIFEST" --verify-lock "$INPUT_LOCK"

"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest "$MANIFEST" --require-files --min-targets 8 --min-contacts 1 --max-failures 100
test -s "$HISTORICAL_REGISTRY" || { echo "historical target registry is missing" >&2; exit 2; }
"$PYTHON_BIN" - "$MANIFEST" "$HISTORICAL_REGISTRY" <<'PY'
import json, sys
from bio_sfm_designer.experiments.m6d_w2_historical_target_registry import audit_manifest

with open(sys.argv[1]) as handle:
    manifest = json.load(handle)
with open(sys.argv[2]) as handle:
    registry = json.load(handle)
report = audit_manifest(manifest, registry)
if not report.get("audit_ok"):
    raise SystemExit("historical target/source overlap blocks W2c threshold learning")
print(f"historical registry audit clear: {report.get('n_new_targets')} new targets")
PY

"$PYTHON_BIN" - "$MANIFEST" <<'PY'
import json, os, sys

with open(sys.argv[1]) as handle:
    manifest = json.load(handle)
existing = []
for target in manifest.get("targets", []):
    for field in ("candidates", "records"):
        path = target.get(field)
        if isinstance(path, str) and os.path.exists(path):
            existing.append(path)
if existing:
    raise SystemExit("initial W2c threshold-learning outputs already exist: " + ",".join(existing))
print("initial output absence check clear: 16/16 candidate and record paths absent")
PY

if [ "$DRY_RUN" = "1" ]; then
  echo "## W2c fit-learn dry run: no sbatch calls and no receipt writes"
else
  if [ "${BIO_SFM_APPROVE_W2C_FIT_LEARN:-}" != "$APPROVAL_TOKEN" ]; then
    echo "refusing W2c threshold-learning submission without exact explicit approval" >&2
    exit 2
  fi
  if [ -e "$SUBMIT_RECEIPT" ] || [ -e "$SUBMIT_SUMMARY" ]; then
    echo "refusing W2c threshold-learning submission because receipt or summary already exists" >&2
    echo "use a separately audited recovery path; do not rerun the initial bridge" >&2
    exit 2
  fi
  command -v "$SBATCH_BIN" >/dev/null 2>&1 || { echo "Slurm sbatch is required" >&2; exit 2; }
  mkdir -p "$(dirname "$SUBMIT_RECEIPT")" "$(dirname "$SUBMIT_SUMMARY")" hpc_outputs/logs
  : > "$SUBMIT_RECEIPT"
fi

require_job_id() {
  local stage="$1" target_id="$2" job_id="$3"
  if [ -z "${job_id//[[:space:]]/}" ] || [[ "$job_id" =~ [[:space:]] ]]; then
    echo "${stage} sbatch returned an invalid job id for ${target_id}: ${job_id}" >&2
    exit 2
  fi
}

journal_append() {
  local stage="$1" target_id="$2" gen_job="$3" pred_job="$4"
  local candidates="$5" records="$6" target_msa="$7" prepared_pdb="$8"
  local args=(
    -m bio_sfm_designer.experiments.m6d_w2_submit_journal append
    --receipt "$SUBMIT_RECEIPT" --stage "$stage" --artifact m6d_w2c_fit_learn_submit_record
    --workstream "$WORKSTREAM" --target-id "$target_id"
    --proteinmpnn-job-id "$gen_job" --candidates "$candidates" --records "$records"
    --target-msa "$target_msa" --prepared-pdb "$prepared_pdb" --manifest "$MANIFEST"
  )
  if [ -n "$pred_job" ]; then args+=(--boltz-job-id "$pred_job"); fi
  "$PYTHON_BIN" "${args[@]}"
}

submit_pair() {
  local target_id="$1" prepared_pdb="$2" target_chain="$3" binder_chain="$4"
  local target_msa="$5" candidates="$6" records="$7" num_seq="$8" temp="$9"
  local seed="${10}" objective="${11}" stage="${12}" namespace="${13}" id_prefix="${14}"

  test -s "$prepared_pdb" || { echo "missing prepared PDB for ${target_id}" >&2; exit 2; }
  test -s "$target_msa" || { echo "missing target MSA for ${target_id}" >&2; exit 2; }
  [ "$stage" = "threshold_learning" ] || { echo "unexpected W2c stage for ${target_id}" >&2; exit 2; }
  [ "$namespace" = "w2c-fit-learn-v1" ] || { echo "unexpected W2c namespace for ${target_id}" >&2; exit 2; }
  [ "$num_seq" = "60" ] || { echo "unexpected W2c record count for ${target_id}" >&2; exit 2; }
  [ "$id_prefix" = "${namespace}-${target_id}" ] || { echo "unexpected W2c ID prefix for ${target_id}" >&2; exit 2; }

  if [ "$DRY_RUN" = "1" ]; then
    echo "dry-run ${target_id}: 60 ProteinMPNN -> ${candidates}; H100 Boltz ${PREDICT_PARTITION}/${PREDICT_QOS}/${PREDICT_GRES} -> ${records}"
    return 0
  fi

  mkdir -p "$(dirname "$candidates")" "$(dirname "$records")"
  local gen_job pred_job
  gen_job=$(PROJECT_ROOT="$REPO_ROOT" PDB="$prepared_pdb" TARGET_CHAIN="$target_chain" \
    DESIGN_CHAIN="$binder_chain" NUM_SEQ="$num_seq" TEMP="$temp" SEED="$seed" \
    OBJECTIVE="$objective" COMPLEX_ID="$target_id" ID_PREFIX="$id_prefix" \
    W2C_STAGE="$stage" W2C_SEED_NAMESPACE="$namespace" OUT="$candidates" \
    "$SBATCH_BIN" --parsable "$GENERATE_WRAPPER")
  require_job_id "ProteinMPNN" "$target_id" "$gen_job"
  journal_append proteinmpnn_submitted "$target_id" "$gen_job" "" \
    "$candidates" "$records" "$target_msa" "$prepared_pdb"

  pred_job=$(PROJECT_ROOT="$REPO_ROOT" CANDIDATES="$candidates" BACKBONE="$prepared_pdb" \
    TARGET_CHAIN="$target_chain" BINDER_CHAIN="$binder_chain" COMPLEX_ID="$target_id" \
    TARGET_MSA="$target_msa" W2C_STAGE="$stage" W2C_SEED_NAMESPACE="$namespace" \
    EXPECTED_COUNT="$num_seq" OUT="$records" \
    "$SBATCH_BIN" --partition="$PREDICT_PARTITION" --qos="$PREDICT_QOS" \
      --gres="$PREDICT_GRES" --dependency="afterok:${gen_job}" --parsable "$PREDICT_WRAPPER")
  require_job_id "Boltz" "$target_id" "$pred_job"
  journal_append pair_submitted "$target_id" "$gen_job" "$pred_job" \
    "$candidates" "$records" "$target_msa" "$prepared_pdb"
  echo "${target_id}: ProteinMPNN ${gen_job} -> H100 Boltz ${pred_job}"
}

"$PYTHON_BIN" - "$MANIFEST" <<'PY' | while IFS=$'\t' read -r target_id prepared_pdb target_chain binder_chain target_msa candidates records num_seq temp seed objective stage namespace id_prefix; do
import json, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
targets = manifest.get("targets")
if not isinstance(targets, list) or len(targets) != 8:
    raise SystemExit("W2c fit-learn manifest must contain exactly eight targets")
for target in targets:
    print("\t".join(str(target[key]) for key in (
        "id", "prepared_pdb", "target_chain", "binder_chain", "target_msa",
        "candidates", "records", "num_seq", "temp", "seed", "objective",
        "w2c_stage", "w2c_seed_namespace", "id_prefix",
    )))
PY
  submit_pair "$target_id" "$prepared_pdb" "$target_chain" "$binder_chain" "$target_msa" \
    "$candidates" "$records" "$num_seq" "$temp" "$seed" "$objective" \
    "$stage" "$namespace" "$id_prefix"
done

if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run complete: eight target pairs, 480 planned records, zero scheduler jobs submitted"
  exit 0
fi

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_submit_journal summary \
  --manifest "$MANIFEST" --receipt "$SUBMIT_RECEIPT" --out "$SUBMIT_SUMMARY" \
  --workstream "$WORKSTREAM" --artifact m6d_w2c_fit_learn_submit_receipt_summary
echo "submit receipt: $SUBMIT_RECEIPT"
echo "submit summary: $SUBMIT_SUMMARY"
