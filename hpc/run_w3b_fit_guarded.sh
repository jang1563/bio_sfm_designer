#!/usr/bin/env bash
# Guarded W3b fit entrypoint. It authorizes no certification or held-out-test stage.
set -euo pipefail
unset PYTHONHOME
export PYTHONNOUSERSITE=1

ROOT="${BIO_SFM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APPROVAL_TOKEN="approve-w3b-fit-180-matched-h100"
APPROVAL_PACKET="${W3B_FIT_APPROVAL_PACKET:-results/m6d_w3b_fit_approval_packet.json}"
SUBMIT_BRIDGE="hpc/m6d_w3b_fit_submit_with_receipt.sh"
PROTOCOL="${PROTOCOL:-configs/m6d_w3b_disagreement_gate_protocol.json}"
EXECUTION_MANIFEST="${EXECUTION_MANIFEST:-configs/m6d_w3b_execution_targets.json}"
INPUT_LOCK="${INPUT_LOCK:-configs/m6d_w3b_execution_input_lock.json}"
RUNTIME_LOCK="${RUNTIME_LOCK:-configs/m6d_w3b_runtime_lock.json}"
EXECUTION_READINESS="${EXECUTION_READINESS:-results/m6d_w3b_execution_lock_readiness.json}"
RUNTIME_READINESS="${RUNTIME_READINESS:-results/m6d_w3b_runtime_lock_readiness.json}"
MATCHED_READINESS="${MATCHED_READINESS:-results/m6d_w3b_matched_record_contract.json}"
PYTHON_BIN="${BIO_SFM_PYTHON:-python3}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"

cd "$ROOT"
BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${ROOT%/}/../bio-sfm-trust-core/src}"
export PYTHONPATH="$ROOT/src:$BIO_SFM_TRUST_CORE_SRC${PYTHONPATH:+:$PYTHONPATH}"

test -s "$APPROVAL_PACKET" || {
  echo "W3b fit approval packet is absent; complete target-MSA and execution-lock readiness first" >&2
  exit 2
}
test -s "$SUBMIT_BRIDGE" || { echo "W3b fit submit bridge is missing" >&2; exit 2; }
bash -n "$SUBMIT_BRIDGE"

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w3b_fit_packet \
  --protocol "$PROTOCOL" --execution-manifest "$EXECUTION_MANIFEST" \
  --input-lock "$INPUT_LOCK" --runtime-lock "$RUNTIME_LOCK" \
  --execution-readiness "$EXECUTION_READINESS" --runtime-readiness "$RUNTIME_READINESS" \
  --matched-readiness "$MATCHED_READINESS" \
  --verify-approval-packet "$APPROVAL_PACKET"

if [ "$DRY_RUN" != "1" ] && [ "${BIO_SFM_APPROVE_W3B_FIT:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3b fit submission without exact approval:" >&2
  echo "  export BIO_SFM_APPROVE_W3B_FIT=$APPROVAL_TOKEN" >&2
  echo "scope: exactly 3 fit targets, 180 candidates, 3 CPU jobs, and 6 H100 jobs" >&2
  echo "certification, held-out test, adaptive top-up, and scientific claims remain unauthorized" >&2
  exit 64
fi

BIO_SFM_REPO_ROOT="$ROOT" \
W3B_FIT_APPROVAL_PACKET="$APPROVAL_PACKET" \
BIO_SFM_SUBMIT_DRY_RUN="$DRY_RUN" \
BIO_SFM_PYTHON="$PYTHON_BIN" \
BIO_SFM_APPROVE_W3B_FIT="${BIO_SFM_APPROVE_W3B_FIT:-}" \
PROTOCOL="$PROTOCOL" EXECUTION_MANIFEST="$EXECUTION_MANIFEST" \
INPUT_LOCK="$INPUT_LOCK" RUNTIME_LOCK="$RUNTIME_LOCK" \
EXECUTION_READINESS="$EXECUTION_READINESS" RUNTIME_READINESS="$RUNTIME_READINESS" \
MATCHED_READINESS="$MATCHED_READINESS" \
  bash "$SUBMIT_BRIDGE"
