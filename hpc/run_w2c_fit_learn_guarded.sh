#!/usr/bin/env bash
# Guarded W2c threshold-learning entrypoint. No screen or certification scope is included.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1

PROTOCOL="configs/m6d_w2c_one_shot_protocol.json"
SOURCE_MANIFEST="configs/m6d_w2c_fresh_targets.json"
STAGE_MANIFEST="configs/m6d_w2c_fit_learn_targets.json"
INPUT_LOCK="configs/m6d_w2c_fit_learn_input_lock.json"
MSA_COMPLETION="results/m6d_w2c_target_msa_completion.json"
SELECTION="results/m6d_w2c_target_selection.json"
DESIGN_GATE="results/m6d_w2c_design_gate.json"
POST_MSA_REPORT="results/m6d_w2c_manifest_post_msa.json"
LOCK_TOOL="src/bio_sfm_designer/experiments/m6d_w2c_fit_learn_lock.py"
METADATA_TOOL="src/bio_sfm_designer/experiments/m6d_w2c_stage_metadata.py"
SUBMIT_BRIDGE="hpc/m6d_w2c_fit_learn_submit_with_receipt.sh"
GENERATE_WRAPPER="hpc/run_generate_proteinmpnn_w2c_complex.sbatch"
PREDICT_WRAPPER="hpc/run_predict_boltz_w2c_complex.sbatch"
GENERATOR="hpc/generate_proteinmpnn_complex.py"
PREDICTOR="hpc/predict_boltz_complex.py"
MANIFEST_TOOL="src/bio_sfm_designer/experiments/complex_target_manifest.py"
HISTORICAL_AUDIT_TOOL="src/bio_sfm_designer/experiments/m6d_w2_historical_target_registry.py"
SUBMIT_JOURNAL_TOOL="src/bio_sfm_designer/experiments/m6d_w2_submit_journal.py"

EXPECTED_PROTOCOL_SHA256="d7ae7d23f64f957357a6fb9fe1659beb3c4caeea82d2c87bb3e18c73139dfc96"
EXPECTED_SOURCE_MANIFEST_SHA256="94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2"
EXPECTED_STAGE_MANIFEST_SHA256="c60e1d001f187724bb00a49484158efad0997ca418a0589e5446819fca59daa8"
EXPECTED_INPUT_LOCK_SHA256="904262663513ad243f3dc5ab8160af0b1fb5965939dd5a815066f285cedf9674"
EXPECTED_INPUT_LOCK_DIGEST="8d36af1b46e61d42bdd41532d37845beb06a58a45f87be93e8be97a8fe3bf877"
EXPECTED_MSA_COMPLETION_SHA256="90fee9bba886233e095e9fdcc757fb95cafc7257f2a1f58e0508fee95bc6f344"
EXPECTED_SELECTION_SHA256="0d6e166e8823cf9d62603592b41b3865836a55c9d200e06ca353ccdde420c1c4"
EXPECTED_DESIGN_GATE_SHA256="2fe726335575239baaf6f41a10680750e0277e82e4a9e04d21e0c23aad099667"
EXPECTED_POST_MSA_REPORT_SHA256="6601c2b3b7453025d95b957240d38ef918bf9407cfa190d997bc282da2ecb146"
EXPECTED_LOCK_TOOL_SHA256="0ac1ad7fab5bbb8b9b14fbb84ce7fd06a93777e39be230c0a6f4205345d0d91a"
EXPECTED_METADATA_TOOL_SHA256="ce50c00ec47bf74e9f0de55150b47e1715cbd365f2cbd9796c12a8402af2de25"
EXPECTED_SUBMIT_BRIDGE_SHA256="cb13219248fee89ee15da005e2b99f9c44e95b63839f81b19b68b77f44d56c5d"
EXPECTED_GENERATE_WRAPPER_SHA256="fd35ab794615cf98532d95e6be03d9a680c5d23c08d9b8a31ca0d8355c85401f"
EXPECTED_PREDICT_WRAPPER_SHA256="d8c10ab3bf80379d741f140be4259fdc7f50403629a76fda8c41a90a50d55c49"
EXPECTED_GENERATOR_SHA256="0245801d7a72f927352de3a447640c531e9364d0aa398718a7cea84fd8cfe4db"
EXPECTED_PREDICTOR_SHA256="9203d5acea2b4a9b27747eb1d7be3e218c076c549d5b8228b85d535201de71c8"
EXPECTED_MANIFEST_TOOL_SHA256="1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0"
EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256="82bb6f1cd179de665b5f8aa94b7818a703b8fcf8788a202c26d71c574617fc87"
EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256="6f3c7fe5ca455e58f44375c220b96df06616cad5fe06496dddbc983b92d3d9f8"

APPROVAL_ENV_VAR="BIO_SFM_APPROVE_W2C_FIT_LEARN"
APPROVAL_TOKEN="approve-w2c-fit-learn-480-h100"
RECEIPT="${W2C_FIT_LEARN_RECEIPT:-results/m6d_w2c_fit_learn_submit_receipt.jsonl}"
SUMMARY="${W2C_FIT_LEARN_SUMMARY:-results/m6d_w2c_fit_learn_submit_receipt_summary.json}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
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
    echo "required W2c fit-learn artifact is missing or empty: $path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "stale W2c fit-learn artifact: $path expected_sha256=$expected actual_sha256=$actual" >&2
    exit 2
  fi
}

require_sha256 "$PROTOCOL" "$EXPECTED_PROTOCOL_SHA256"
require_sha256 "$SOURCE_MANIFEST" "$EXPECTED_SOURCE_MANIFEST_SHA256"
require_sha256 "$STAGE_MANIFEST" "$EXPECTED_STAGE_MANIFEST_SHA256"
require_sha256 "$INPUT_LOCK" "$EXPECTED_INPUT_LOCK_SHA256"
require_sha256 "$MSA_COMPLETION" "$EXPECTED_MSA_COMPLETION_SHA256"
require_sha256 "$SELECTION" "$EXPECTED_SELECTION_SHA256"
require_sha256 "$DESIGN_GATE" "$EXPECTED_DESIGN_GATE_SHA256"
require_sha256 "$POST_MSA_REPORT" "$EXPECTED_POST_MSA_REPORT_SHA256"
require_sha256 "$LOCK_TOOL" "$EXPECTED_LOCK_TOOL_SHA256"
require_sha256 "$METADATA_TOOL" "$EXPECTED_METADATA_TOOL_SHA256"
require_sha256 "$SUBMIT_BRIDGE" "$EXPECTED_SUBMIT_BRIDGE_SHA256"
require_sha256 "$GENERATE_WRAPPER" "$EXPECTED_GENERATE_WRAPPER_SHA256"
require_sha256 "$PREDICT_WRAPPER" "$EXPECTED_PREDICT_WRAPPER_SHA256"
require_sha256 "$GENERATOR" "$EXPECTED_GENERATOR_SHA256"
require_sha256 "$PREDICTOR" "$EXPECTED_PREDICTOR_SHA256"
require_sha256 "$MANIFEST_TOOL" "$EXPECTED_MANIFEST_TOOL_SHA256"
require_sha256 "$HISTORICAL_AUDIT_TOOL" "$EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256"
require_sha256 "$SUBMIT_JOURNAL_TOOL" "$EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256"
bash -n "$SUBMIT_BRIDGE" "$GENERATE_WRAPPER" "$PREDICT_WRAPPER"

PYTHONPATH="src:${BIO_SFM_TRUST_CORE_SRC:-../bio-sfm-trust-core/src}${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2c_fit_learn_lock \
  --protocol "$PROTOCOL" --source-manifest "$SOURCE_MANIFEST" --completion "$MSA_COMPLETION" \
  --stage-manifest "$STAGE_MANIFEST" --verify-lock "$INPUT_LOCK"

actual_lock_digest="$("$PYTHON_BIN" - "$INPUT_LOCK" <<'PY'
import json, sys
with open(sys.argv[1]) as handle:
    print(json.load(handle)["lock_digest_sha256"])
PY
)"
if [ "$actual_lock_digest" != "$EXPECTED_INPUT_LOCK_DIGEST" ]; then
  echo "W2c fit-learn input-lock digest mismatch" >&2
  exit 2
fi

if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W2C_FIT_LEARN:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W2c threshold-learning submission without explicit approval:" >&2
  echo "  export ${APPROVAL_ENV_VAR}=${APPROVAL_TOKEN}" >&2
  echo "this approval would cover exactly 8 targets, 480 records, 8 CPU jobs, and 8 H100 jobs" >&2
  echo "it would not authorize independent-screen or certification compute" >&2
  exit 2
fi

if [ "$DRY_RUN" != "1" ] && { [ -e "$RECEIPT" ] || [ -e "$SUMMARY" ]; }; then
  echo "refusing initial W2c threshold-learning submission because receipt or summary exists" >&2
  exit 2
fi

MANIFEST="$STAGE_MANIFEST" \
SUBMIT_RECEIPT="$RECEIPT" \
SUBMIT_SUMMARY="$SUMMARY" \
BIO_SFM_SUBMIT_DRY_RUN="$DRY_RUN" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
PYTHONNOUSERSITE=1 \
  bash "$SUBMIT_BRIDGE"
