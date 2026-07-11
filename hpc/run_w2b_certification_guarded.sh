#!/usr/bin/env bash
# Guarded W2b certification-only entrypoint. This authorizes no test-stage jobs.
set -euo pipefail

MANIFEST="configs/m6d_w2b_target_adaptive_certification_targets.json"
PROTOCOL="configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json"
INPUT_LOCK="configs/m6d_w2b_target_adaptive_certification_input_lock.json"
FIT_REPORT="results/m6d_w2b_target_adaptive_fit_report.json"
FIT_FIXTURE="tests/fixtures/m6d_w2b_target_adaptive_fit_records.jsonl"
LOCK_TOOL="src/bio_sfm_designer/experiments/m6d_w2b_input_lock.py"
SHARED_SUBMIT="hpc/m6d_w2_submit_with_receipt.sh"
GENERATE_WRAPPER="hpc/run_generate_proteinmpnn_complex.sbatch"
PREDICT_WRAPPER="hpc/run_predict_boltz_complex.sbatch"
GENERATOR="hpc/generate_proteinmpnn_complex.py"
PREDICTOR="hpc/predict_boltz_complex.py"
MANIFEST_TOOL="src/bio_sfm_designer/experiments/complex_target_manifest.py"
HISTORICAL_AUDIT_TOOL="src/bio_sfm_designer/experiments/m6d_w2_historical_target_registry.py"
SUBMIT_JOURNAL_TOOL="src/bio_sfm_designer/experiments/m6d_w2_submit_journal.py"
EXPECTED_MANIFEST_SHA256="502b2d91e29c9f9c1199e79b075051c83b0a634277283a6c97ee4b6d83ae8d99"
EXPECTED_PROTOCOL_SHA256="dcef5d1b080791b54bafb485f815e08b536bcd68a44ee4ab458b34ebb3d5567c"
EXPECTED_INPUT_LOCK_SHA256="41279f144bcbe09fe61aedd838e413900200a814b73f64b2616a64430fdcdd23"
EXPECTED_INPUT_LOCK_DIGEST="2153bf715745813730e2f41b340329adb21dc7415f293980cf8519320b5deaae"
EXPECTED_FIT_REPORT_SHA256="6aac81be46805ad983e770af49f15e38cac140d469e4541e40788a21129ef3c1"
EXPECTED_FIT_FIXTURE_SHA256="3187ba56a3eb39e4820d17c42e6a8ffd8ce28add05d858645a1e92427c6d4dbe"
EXPECTED_LOCK_TOOL_SHA256="ea5f2e6fe3a62c32a3436e3e43e6649a88a3d201364ce9e642edac092a195631"
EXPECTED_SHARED_SUBMIT_SHA256="61fb4b92d935e5708c35f3d90380b06ed0a8c6b4f7cfc5affb137d16b4332a92"
EXPECTED_GENERATE_WRAPPER_SHA256="6b010e2cd45a2c148161e7dffe021165af199f9e64d21be06b2c1b706e7b0aa6"
EXPECTED_PREDICT_WRAPPER_SHA256="254e7c985fdd92d388261f8af01a319344a428a16e5bb0ecfbbc1c5bc2ca53d9"
EXPECTED_GENERATOR_SHA256="0245801d7a72f927352de3a447640c531e9364d0aa398718a7cea84fd8cfe4db"
EXPECTED_PREDICTOR_SHA256="9203d5acea2b4a9b27747eb1d7be3e218c076c549d5b8228b85d535201de71c8"
EXPECTED_MANIFEST_TOOL_SHA256="1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0"
EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256="82bb6f1cd179de665b5f8aa94b7818a703b8fcf8788a202c26d71c574617fc87"
EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256="6f3c7fe5ca455e58f44375c220b96df06616cad5fe06496dddbc983b92d3d9f8"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W2B_CERTIFICATION"
APPROVAL_TOKEN="approve-w2b-certification-stage-300-h100"
RECEIPT="${W2B_CERTIFICATION_RECEIPT:-results/m6d_w2b_target_adaptive_certification_submit_receipt.jsonl}"
SUMMARY="${W2B_CERTIFICATION_SUMMARY:-results/m6d_w2b_target_adaptive_certification_submit_receipt_summary.json}"
WORKSTREAM="m6d_w2b_target_adaptive_certification"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
PREDICT_PARTITION="preempt_gpu"
PREDICT_QOS="low"
PREDICT_GRES="gpu:h100:1"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

require_sha256() {
  local path="$1" expected="$2"
  if [ ! -s "$path" ]; then
    echo "required W2b certification artifact is missing or empty: $path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W2b certification artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 2
  fi
}

require_sha256 "$MANIFEST" "$EXPECTED_MANIFEST_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$INPUT_LOCK" "$EXPECTED_INPUT_LOCK_SHA256"
require_sha256 "$FIT_REPORT" "$EXPECTED_FIT_REPORT_SHA256"
require_sha256 "$FIT_FIXTURE" "$EXPECTED_FIT_FIXTURE_SHA256"
require_sha256 "$LOCK_TOOL" "$EXPECTED_LOCK_TOOL_SHA256"
require_sha256 "$SHARED_SUBMIT" "$EXPECTED_SHARED_SUBMIT_SHA256"
require_sha256 "$GENERATE_WRAPPER" "$EXPECTED_GENERATE_WRAPPER_SHA256"
require_sha256 "$PREDICT_WRAPPER" "$EXPECTED_PREDICT_WRAPPER_SHA256"
require_sha256 "$GENERATOR" "$EXPECTED_GENERATOR_SHA256"
require_sha256 "$PREDICTOR" "$EXPECTED_PREDICTOR_SHA256"
require_sha256 "$MANIFEST_TOOL" "$EXPECTED_MANIFEST_TOOL_SHA256"
require_sha256 "$HISTORICAL_AUDIT_TOOL" "$EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256"
require_sha256 "$SUBMIT_JOURNAL_TOOL" "$EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256"
bash -n "$SHARED_SUBMIT" "$GENERATE_WRAPPER" "$PREDICT_WRAPPER"

if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W2B_CERTIFICATION:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W2b certification-stage submission without explicit approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval would cover certification only: 5 targets, 300 records, and 10 Slurm jobs" >&2
  echo "Boltz resources: ${PREDICT_PARTITION}/${PREDICT_QOS}/${PREDICT_GRES}; maximum 30 H100 GPU-hours" >&2
  echo "it does not authorize test-stage compute" >&2
  exit 2
fi

PYTHONPATH="src:${BIO_SFM_TRUST_CORE_SRC:-../bio-sfm-trust-core/src}${PYTHONPATH:+:${PYTHONPATH}}" \
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2b_input_lock \
  --protocol "$PROTOCOL" --manifest "$MANIFEST" --verify-lock "$INPUT_LOCK"

actual_lock_digest="$($PYTHON_BIN - "$INPUT_LOCK" <<'PY'
import json, sys
with open(sys.argv[1]) as handle:
    print(json.load(handle)["lock_digest_sha256"])
PY
)"
if [ "$actual_lock_digest" != "$EXPECTED_INPUT_LOCK_DIGEST" ]; then
  echo "W2b certification input-lock digest mismatch" >&2
  exit 2
fi

"$PYTHON_BIN" - "$PROTOCOL" "$MANIFEST" "$FIT_REPORT" <<'PY'
import json
import os
import sys

with open(sys.argv[1]) as handle:
    protocol = json.load(handle)
with open(sys.argv[2]) as handle:
    manifest = json.load(handle)
with open(sys.argv[3]) as handle:
    fit_report = json.load(handle)

state = protocol["current_execution_state"]
target_ids = [target["id"] for target in manifest["targets"]]
report_ids = fit_report.get("fit_eligible_targets")
if not fit_report.get("audit_ok") or fit_report.get("status") != "w2b_fit_complete_awaiting_certification":
    raise SystemExit("fit report is not an audited fit-only completion")
if fit_report.get("certified_targets") or fit_report.get("selective_pae_certified_targets"):
    raise SystemExit("fit report unexpectedly contains certification claims")
if target_ids != report_ids or target_ids != state.get("fit_eligible_target_ids"):
    raise SystemExit("certification target IDs do not match the frozen fit-eligible set")
report_rules = {
    row["target_id"]: {"mode": row["fit"]["mode"], "tau": row["fit"]["tau"]}
    for row in fit_report["targets"]
    if row["target_id"] in target_ids
}
manifest_rules = {target["id"]: target["frozen_fit_rule"] for target in manifest["targets"]}
if report_rules != manifest_rules or report_rules != state.get("fit_frozen_rules"):
    raise SystemExit("certification rules do not match the frozen fit report")
if manifest.get("w2b_stage") != "certification" or manifest.get("w2b_seed_namespace") != "w2b-cert-v1":
    raise SystemExit("certification stage or namespace mismatch")
defaults = manifest.get("defaults") or {}
if defaults.get("seed") != 1037 or defaults.get("num_seq") != 60:
    raise SystemExit("certification seed or record budget mismatch")
for target in manifest["targets"]:
    for field in ("candidates", "records"):
        path = target[field]
        if os.path.exists(path):
            raise SystemExit(f"refusing pre-existing certification output: {path}")
print("certification fit binding verified: 5 frozen rules, no prior outputs")
PY

if [ "$DRY_RUN" != "1" ] && [ -e "$RECEIPT" ]; then
  echo "refusing initial W2b certification submission because receipt path already exists: $RECEIPT" >&2
  echo "audit the receipt and use a scope-bound recovery path instead of rerunning this wrapper" >&2
  exit 2
fi

MANIFEST="$MANIFEST" \
SUBMIT_RECEIPT="$RECEIPT" \
SUBMIT_SUMMARY="$SUMMARY" \
WORKSTREAM="$WORKSTREAM" \
SUBMIT_RECORD_ARTIFACT="m6d_w2b_certification_submit_record" \
SUBMIT_SUMMARY_ARTIFACT="m6d_w2b_certification_submit_receipt_summary" \
BIO_SFM_SUBMIT_DRY_RUN="$DRY_RUN" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
BIO_SFM_PREDICT_SBATCH_PARTITION="$PREDICT_PARTITION" \
BIO_SFM_PREDICT_SBATCH_QOS="$PREDICT_QOS" \
BIO_SFM_PREDICT_SBATCH_GRES="$PREDICT_GRES" \
PYTHONNOUSERSITE=1 \
  bash "$SHARED_SUBMIT"
