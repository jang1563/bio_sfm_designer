#!/usr/bin/env bash
# Guarded W2b fit-stage entrypoint. This authorizes no certification or test jobs.
set -euo pipefail

MANIFEST="configs/m6d_w2b_target_adaptive_fit_targets.json"
PROTOCOL="configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json"
INPUT_LOCK="configs/m6d_w2b_target_adaptive_fit_input_lock.json"
LOCK_TOOL="src/bio_sfm_designer/experiments/m6d_w2b_input_lock.py"
SHARED_SUBMIT="hpc/m6d_w2_submit_with_receipt.sh"
GENERATE_WRAPPER="hpc/run_generate_proteinmpnn_complex.sbatch"
PREDICT_WRAPPER="hpc/run_predict_boltz_complex.sbatch"
GENERATOR="hpc/generate_proteinmpnn_complex.py"
PREDICTOR="hpc/predict_boltz_complex.py"
MANIFEST_TOOL="src/bio_sfm_designer/experiments/complex_target_manifest.py"
HISTORICAL_AUDIT_TOOL="src/bio_sfm_designer/experiments/m6d_w2_historical_target_registry.py"
SUBMIT_JOURNAL_TOOL="src/bio_sfm_designer/experiments/m6d_w2_submit_journal.py"
EXPECTED_MANIFEST_SHA256="1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14"
EXPECTED_PROTOCOL_SHA256="3747ae72ac1f271ed808db98894139520d6d4fb2b44b93ac5abd814cfda54c99"
EXPECTED_INPUT_LOCK_SHA256="938003752b3ab8fb62dcd5114678738b0373ec399dafb64fab9c6fe389d94ec4"
EXPECTED_INPUT_LOCK_DIGEST="a97423644fef1ddbbb88471a759e42ea21c9097bcf6aa314e4f608e11773064b"
EXPECTED_LOCK_TOOL_SHA256="ea5f2e6fe3a62c32a3436e3e43e6649a88a3d201364ce9e642edac092a195631"
EXPECTED_SHARED_SUBMIT_SHA256="61fb4b92d935e5708c35f3d90380b06ed0a8c6b4f7cfc5affb137d16b4332a92"
EXPECTED_GENERATE_WRAPPER_SHA256="6b010e2cd45a2c148161e7dffe021165af199f9e64d21be06b2c1b706e7b0aa6"
EXPECTED_PREDICT_WRAPPER_SHA256="254e7c985fdd92d388261f8af01a319344a428a16e5bb0ecfbbc1c5bc2ca53d9"
EXPECTED_GENERATOR_SHA256="0245801d7a72f927352de3a447640c531e9364d0aa398718a7cea84fd8cfe4db"
EXPECTED_PREDICTOR_SHA256="9203d5acea2b4a9b27747eb1d7be3e218c076c549d5b8228b85d535201de71c8"
EXPECTED_MANIFEST_TOOL_SHA256="1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0"
EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256="82bb6f1cd179de665b5f8aa94b7818a703b8fcf8788a202c26d71c574617fc87"
EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256="6f3c7fe5ca455e58f44375c220b96df06616cad5fe06496dddbc983b92d3d9f8"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W2B_FIT"
APPROVAL_TOKEN="approve-w2b-fit-stage-480"
RECEIPT="${W2B_FIT_RECEIPT:-results/m6d_w2b_target_adaptive_fit_submit_receipt.jsonl}"
SUMMARY="${W2B_FIT_SUMMARY:-results/m6d_w2b_target_adaptive_fit_submit_receipt_summary.json}"
WORKSTREAM="m6d_w2b_target_adaptive_fit"
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"

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
    echo "required W2b fit artifact is missing or empty: $path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W2b fit artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 2
  fi
}

require_sha256 "$MANIFEST" "$EXPECTED_MANIFEST_SHA256"
require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$INPUT_LOCK" "$EXPECTED_INPUT_LOCK_SHA256"
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

if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W2B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W2b fit-stage submission without explicit approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval would cover fit only: 8 targets, 480 records, and 16 Slurm jobs" >&2
  echo "it does not authorize certification or test-stage compute" >&2
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
  echo "W2b fit input-lock digest mismatch" >&2
  exit 2
fi

if [ "$DRY_RUN" != "1" ] && [ -e "$RECEIPT" ]; then
  echo "refusing initial W2b fit submission because receipt path already exists: $RECEIPT" >&2
  echo "audit the receipt and use a scope-bound recovery path instead of rerunning this wrapper" >&2
  exit 2
fi

MANIFEST="$MANIFEST" \
SUBMIT_RECEIPT="$RECEIPT" \
SUBMIT_SUMMARY="$SUMMARY" \
WORKSTREAM="$WORKSTREAM" \
SUBMIT_RECORD_ARTIFACT="m6d_w2b_fit_submit_record" \
SUBMIT_SUMMARY_ARTIFACT="m6d_w2b_fit_submit_receipt_summary" \
BIO_SFM_SUBMIT_DRY_RUN="$DRY_RUN" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
PYTHONNOUSERSITE=1 \
  bash "$SHARED_SUBMIT"
