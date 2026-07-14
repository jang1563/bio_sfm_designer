#!/usr/bin/env bash
set -euo pipefail

ROOT="${BIO_SFM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PACKET="${W3_PACKET:-$ROOT/configs/m6d_w3_mechanism_panel_protocol.json}"
PRIVATE_MANIFEST="${W3_PRIVATE_MANIFEST:-$ROOT/results/m6d_w3_mechanism_panel_inputs.jsonl}"
INPUT_DIR="${W3_INPUT_DIR:-$ROOT/results/m6d_w3_mechanism_panel_inputs/a3m}"
OUTPUT_DIR="${W3_OUTPUT_DIR:-$ROOT/hpc_outputs/m6d_w3_mechanism_panel_af2}"
RUNTIME_RECEIPT="${W3_RUNTIME_RECEIPT:-$ROOT/results/m6d_w3_mechanism_runtime_receipt.json}"
DRY_RUN="${W3_DRY_RUN:-1}"
APPROVAL_TOKEN="approve-w3-mechanism-panel-h100"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

python3 "$ROOT/src/bio_sfm_designer/experiments/m6d_w3_mechanism_guard.py" \
  --packet "$PACKET" \
  --private-manifest "$PRIVATE_MANIFEST" \
  --input-dir "$INPUT_DIR" >/dev/null

if [ "$DRY_RUN" != "0" ]; then
  echo "verified 58-case W3 mechanism bundle; dry-run only, no predictor or scheduler invoked"
  exit 0
fi

if [ "${BIO_SFM_APPROVE_W3_MECHANISM_PANEL:-}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing W3 compute without separate exact approval:" >&2
  echo "  export BIO_SFM_APPROVE_W3_MECHANISM_PANEL=$APPROVAL_TOKEN" >&2
  exit 64
fi

if [ -e "$OUTPUT_DIR" ] && [ -n "$(find "$OUTPUT_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]; then
  echo "refusing to overwrite or resume a non-empty W3 output directory: $OUTPUT_DIR" >&2
  exit 65
fi

if [ -z "${W3_AF2_DATA_DIR:-}" ]; then
  echo "W3_AF2_DATA_DIR is required and must contain pre-staged AF2-Multimer v3 weights" >&2
  exit 66
fi

if [ -n "${W3_COLABFOLD_BIN:-}" ] && [ -n "${W3_COLABFOLD_SIF:-}" ]; then
  echo "set exactly one of W3_COLABFOLD_BIN or W3_COLABFOLD_SIF" >&2
  exit 67
elif [ -n "${W3_COLABFOLD_BIN:-}" ]; then
  RUNTIME_PATH="$W3_COLABFOLD_BIN"
  RUNNER=("$W3_COLABFOLD_BIN")
elif [ -n "${W3_COLABFOLD_SIF:-}" ]; then
  RUNTIME_PATH="$W3_COLABFOLD_SIF"
  APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || true)}"
  if [ -z "$APPTAINER_BIN" ]; then
    echo "apptainer/singularity is required for W3_COLABFOLD_SIF" >&2
    exit 68
  fi
  RUNNER=("$APPTAINER_BIN" exec --nv --containall --net --network none --bind "$ROOT:$ROOT" --bind "$W3_AF2_DATA_DIR:$W3_AF2_DATA_DIR" "$W3_COLABFOLD_SIF" colabfold_batch)
else
  echo "set exactly one existing W3_COLABFOLD_BIN or W3_COLABFOLD_SIF" >&2
  exit 69
fi

python3 "$ROOT/src/bio_sfm_designer/experiments/m6d_w3_mechanism_guard.py" \
  --packet "$PACKET" \
  --private-manifest "$PRIVATE_MANIFEST" \
  --input-dir "$INPUT_DIR" \
  --runtime-receipt "$RUNTIME_RECEIPT" \
  --runtime-path "$RUNTIME_PATH" \
  --data-dir "$W3_AF2_DATA_DIR" >/dev/null

mkdir -p "$OUTPUT_DIR"
# Precomputed A3Ms bypass MMseqs2; a non-single mode preserves the locked target-MSA depth.
"${RUNNER[@]}" "$INPUT_DIR" "$OUTPUT_DIR" \
  --model-type alphafold2_multimer_v3 \
  --num-models 5 \
  --num-seeds 1 \
  --random-seed 0 \
  --num-recycle 20 \
  --rank multimer \
  --num-relax 0 \
  --msa-mode mmseqs2_uniref_env \
  --pair-mode unpaired_paired \
  --max-seq 508 \
  --max-extra-seq 2048 \
  --data "$W3_AF2_DATA_DIR"
