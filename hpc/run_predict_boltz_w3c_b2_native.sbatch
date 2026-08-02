#!/usr/bin/env bash
#SBATCH --job-name=biosfm-w3c-b2-boltz
#SBATCH --output=hpc_outputs/logs/biosfm-w3c-b2-boltz-%j.out
#SBATCH --error=hpc_outputs/logs/biosfm-w3c-b2-boltz-%j.err
#SBATCH --partition=preempt_gpu
#SBATCH --qos=low
#SBATCH --gres=gpu:h100:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G

# Run exactly one frozen Boltz-2 native-complex evaluation.
set -euo pipefail
module load anaconda3/2023.09-3 2>/dev/null || true
unset PYTHONHOME
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

APPROVAL_TOKEN="approve-w3c-b2-native-16-h100"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENV_PY="${ENV_PY:-$HOME/.conda/envs/boltz/bin/python3.11}"
BOLTZ_BIN="${BOLTZ_BIN:-$HOME/.conda/envs/boltz/bin/boltz}"
BOLTZ_CACHE="${BOLTZ_CACHE:-$HOME/.boltz}"
APPROVAL_PACKET="${W3C_B2_APPROVAL_PACKET:-results/m6d_w3c_b2_prediction_approval_packet.json}"
PROTOCOL="${PROTOCOL:-configs/m6d_w3c_validity_first_protocol.json}"
NATIVE_MANIFEST="${NATIVE_MANIFEST:-configs/m6d_w3c_b2_native_screen_manifest.json}"
B1_COMPLETION="${B1_COMPLETION:-results/m6d_w3c_b1_target_msa_completion.json}"
W3B_RUNTIME_LOCK="${W3B_RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3c_b2_runtime_lock.json}"
TARGET_ID="${TARGET_ID:?Set TARGET_ID}"
RUNTIME_OBSERVATION="${RUNTIME_OBSERVATION:?Set RUNTIME_OBSERVATION}"

if [ "${BIO_SFM_APPROVE_W3C_B2_NATIVE:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3c-B2 Boltz prediction without exact approval" >&2
  exit 64
fi
test -x "$ENV_PY" || { echo "Boltz Python is unavailable" >&2; exit 2; }
test -x "$BOLTZ_BIN" || { echo "Boltz executable is unavailable" >&2; exit 2; }
test -d "$BOLTZ_CACHE" || { echo "Boltz cache is unavailable" >&2; exit 2; }
[ ! -e "$RUNTIME_OBSERVATION" ] || {
  echo "refusing to overwrite W3c-B2 Boltz runtime observation" >&2
  exit 2
}

cd "$PROJECT_ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${PROJECT_ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$PROJECT_ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"
export BOLTZ_CACHE
mkdir -p "$(dirname "$RUNTIME_OBSERVATION")" "$PROJECT_ROOT/hpc_outputs/logs"

"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3c_b2_approval verify \
  --packet "$APPROVAL_PACKET"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3c_b2_producer \
  --manifest "$NATIVE_MANIFEST" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" target --predictor-id boltz2_complex
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3c_b2_runtime \
  observe-boltz --protocol "$PROTOCOL" --native-manifest "$NATIVE_MANIFEST" \
  --b1-completion "$B1_COMPLETION" --w3b-runtime-lock "$W3B_RUNTIME_LOCK" \
  --cache-dir "$BOLTZ_CACHE" --boltz-bin "$BOLTZ_BIN" \
  --out "$RUNTIME_OBSERVATION"
"$ENV_PY" -m bio_sfm_designer.experiments.m6d_w3c_b2_producer \
  --manifest "$NATIVE_MANIFEST" --runtime-lock "$RUNTIME_LOCK" \
  --target-id "$TARGET_ID" run-boltz \
  --runtime-observation "$RUNTIME_OBSERVATION" --boltz-bin "$BOLTZ_BIN"

echo "W3c-B2 Boltz native evaluation complete: $TARGET_ID"
