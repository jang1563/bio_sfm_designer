#!/usr/bin/env bash
# Resumable W2 ProteinMPNN -> Boltz panel submission with an append-only receipt journal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BIO_SFM_REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "$REPO_ROOT"

MANIFEST="${MANIFEST:?set MANIFEST to the W2 target manifest}"
SUBMIT_RECEIPT="${SUBMIT_RECEIPT:?set SUBMIT_RECEIPT}"
SUBMIT_SUMMARY="${SUBMIT_SUMMARY:?set SUBMIT_SUMMARY}"
WORKSTREAM="${WORKSTREAM:?set WORKSTREAM}"
DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"
SUBMIT_RECORD_ARTIFACT="${SUBMIT_RECORD_ARTIFACT:-${WORKSTREAM}_submit_record}"
SUBMIT_SUMMARY_ARTIFACT="${SUBMIT_SUMMARY_ARTIFACT:-${WORKSTREAM}_submit_receipt_summary}"
PYTHON_BIN="${BIO_SFM_PYTHON:-${SUBMIT_PYTHON:-python3}}"
SBATCH_BIN="${SBATCH_BIN:-sbatch}"
HISTORICAL_REGISTRY="${HISTORICAL_REGISTRY:-configs/m6d_w2_historical_target_registry.json}"

BIO_SFM_TRUST_CORE_SRC="${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}"
BIO_SFM_PYTHONPATH="${REPO_ROOT%/}/src"
if [ -d "$BIO_SFM_TRUST_CORE_SRC" ]; then
  BIO_SFM_PYTHONPATH="${BIO_SFM_PYTHONPATH}:${BIO_SFM_TRUST_CORE_SRC}"
fi
export PYTHONPATH="${BIO_SFM_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"

test -x "$PYTHON_BIN" || { echo "BIO_SFM_PYTHON is not executable: $PYTHON_BIN" >&2; exit 2; }

echo "## W2 strict submit preflight: $WORKSTREAM"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest "$MANIFEST" --require-files --min-targets 4 --min-contacts 20 --max-failures 100
test -s "$HISTORICAL_REGISTRY" || {
  echo "historical target registry is missing: $HISTORICAL_REGISTRY" >&2
  exit 2
}
"$PYTHON_BIN" - "$MANIFEST" "$HISTORICAL_REGISTRY" <<'PY'
import json, sys
from bio_sfm_designer.experiments.m6d_w2_historical_target_registry import audit_manifest

with open(sys.argv[1]) as handle:
    manifest = json.load(handle)
with open(sys.argv[2]) as handle:
    registry = json.load(handle)
report = audit_manifest(manifest, registry)
if not report.get("audit_ok"):
    overlaps = ",".join(report.get("historical_target_overlap") or [])
    raise SystemExit(f"historical target/source overlap blocks submission: {overlaps}")
print(f"historical registry audit clear: {report.get('n_new_targets')} new targets")
PY

if [ "$DRY_RUN" = "1" ]; then
  echo "## Dry run: no sbatch calls and no receipt writes"
else
  command -v "$SBATCH_BIN" >/dev/null 2>&1 || {
    echo "submit requires SLURM sbatch; run from the staged Cayuga repository" >&2
    exit 2
  }
  mkdir -p "$(dirname "$SUBMIT_RECEIPT")" "$(dirname "$SUBMIT_SUMMARY")" hpc_outputs/logs
  touch "$SUBMIT_RECEIPT"
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
    --receipt "$SUBMIT_RECEIPT" --stage "$stage" --artifact "$SUBMIT_RECORD_ARTIFACT"
    --workstream "$WORKSTREAM" --target-id "$target_id"
    --proteinmpnn-job-id "$gen_job" --candidates "$candidates" --records "$records"
    --target-msa "$target_msa" --prepared-pdb "$prepared_pdb" --manifest "$MANIFEST"
  )
  if [ -n "$pred_job" ]; then
    args+=(--boltz-job-id "$pred_job")
  fi
  "$PYTHON_BIN" "${args[@]}"
}

submit_pair() {
  local target_id="$1" prepared_pdb="$2" target_chain="$3" binder_chain="$4"
  local target_msa="$5" candidates="$6" records="$7" num_seq="$8" temp="$9"
  local seed="${10}" objective="${11}" w2b_stage="${12}" w2b_namespace="${13}"
  local id_prefix="${14}"

  if [ "$w2b_stage" = "__BIO_SFM_EMPTY__" ]; then w2b_stage=""; fi
  if [ "$w2b_namespace" = "__BIO_SFM_EMPTY__" ]; then w2b_namespace=""; fi
  if [ "$id_prefix" = "__BIO_SFM_EMPTY__" ]; then id_prefix=""; fi
  if [ -n "$w2b_stage" ] || [ -n "$w2b_namespace" ]; then
    [ -n "$w2b_stage" ] && [ -n "$w2b_namespace" ] && [ -n "$id_prefix" ] || {
      echo "incomplete W2b stage metadata for ${target_id}" >&2
      exit 2
    }
  fi

  test -s "$prepared_pdb" || { echo "missing prepared PDB for ${target_id}: $prepared_pdb" >&2; exit 2; }
  test -s "$target_msa" || { echo "missing target MSA for ${target_id}: $target_msa" >&2; exit 2; }
  mkdir -p "$(dirname "$candidates")" "$(dirname "$records")"
  if [ "$DRY_RUN" = "1" ]; then
    echo "dry-run ${target_id}: ProteinMPNN -> ${candidates}; Boltz -> ${records}"
    return 0
  fi

  local state gen_job pred_job
  IFS=$'\t' read -r state gen_job pred_job < <(
    "$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_submit_journal state \
      --receipt "$SUBMIT_RECEIPT" --target-id "$target_id" --workstream "$WORKSTREAM"
  )
  if [ "$state" = "pair_submitted" ]; then
    echo "${target_id}: already submitted ProteinMPNN ${gen_job} -> Boltz ${pred_job}; skipping"
    return 0
  fi

  if [ "$state" != "proteinmpnn_submitted" ]; then
    gen_job=$(PROJECT_ROOT="$REPO_ROOT" PDB="$prepared_pdb" TARGET_CHAIN="$target_chain" \
      DESIGN_CHAIN="$binder_chain" NUM_SEQ="$num_seq" TEMP="$temp" SEED="$seed" \
      OBJECTIVE="$objective" COMPLEX_ID="$target_id" ID_PREFIX="$id_prefix" \
      W2B_STAGE="$w2b_stage" W2B_SEED_NAMESPACE="$w2b_namespace" OUT="$candidates" \
      "$SBATCH_BIN" --parsable hpc/run_generate_proteinmpnn_complex.sbatch)
    require_job_id "ProteinMPNN" "$target_id" "$gen_job"
    journal_append proteinmpnn_submitted "$target_id" "$gen_job" "" \
      "$candidates" "$records" "$target_msa" "$prepared_pdb"
  else
    echo "${target_id}: resuming from recorded ProteinMPNN job ${gen_job}"
  fi

  pred_job=$(PROJECT_ROOT="$REPO_ROOT" CANDIDATES="$candidates" BACKBONE="$prepared_pdb" \
    TARGET_CHAIN="$target_chain" BINDER_CHAIN="$binder_chain" COMPLEX_ID="$target_id" \
    TARGET_MSA="$target_msa" OUT="$records" \
    "$SBATCH_BIN" --dependency="afterok:${gen_job}" --parsable hpc/run_predict_boltz_complex.sbatch)
  require_job_id "Boltz" "$target_id" "$pred_job"
  journal_append pair_submitted "$target_id" "$gen_job" "$pred_job" \
    "$candidates" "$records" "$target_msa" "$prepared_pdb"
  echo "${target_id}: ProteinMPNN ${gen_job} -> Boltz ${pred_job}"
}

"$PYTHON_BIN" - "$MANIFEST" <<'PY' | while IFS=$'\t' read -r target_id prepared_pdb target_chain binder_chain target_msa candidates records num_seq temp seed objective w2b_stage w2b_namespace id_prefix; do
import json, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
for target in manifest.get("targets", []):
    if not isinstance(target, dict):
        continue
    target_id = str(target["id"])
    out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
    w2b_stage = str(target.get("w2b_stage") or manifest.get("w2b_stage") or "")
    w2b_namespace = str(target.get("w2b_seed_namespace") or manifest.get("w2b_seed_namespace") or "")
    if bool(w2b_stage) != bool(w2b_namespace):
        raise SystemExit(f"incomplete W2b stage metadata for {target_id}")
    id_prefix = str(target.get("id_prefix") or (f"{w2b_namespace}-{target_id}" if w2b_namespace else ""))
    empty = "__BIO_SFM_EMPTY__"
    print("\t".join([
        target_id,
        str(target["prepared_pdb"]),
        str(target["target_chain"]),
        str(target["binder_chain"]),
        str(target["target_msa"]),
        str(target.get("candidates") or f"{out_prefix}/candidates_proteinmpnn_complex.jsonl"),
        str(target.get("records") or f"{out_prefix}/records_boltz_complex.jsonl"),
        str(target.get("num_seq", defaults.get("num_seq", 40))),
        str(target.get("temp", defaults.get("temp", 0.3))),
        str(target.get("seed", defaults.get("seed", 37))),
        str(target.get("objective", defaults.get("objective", "binder"))),
        w2b_stage or empty,
        w2b_namespace or empty,
        id_prefix or empty,
    ]))
PY
  submit_pair "$target_id" "$prepared_pdb" "$target_chain" "$binder_chain" "$target_msa" \
    "$candidates" "$records" "$num_seq" "$temp" "$seed" "$objective" \
    "$w2b_stage" "$w2b_namespace" "$id_prefix"
done

if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run complete: $MANIFEST"
  exit 0
fi

"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_submit_journal summary \
  --manifest "$MANIFEST" --receipt "$SUBMIT_RECEIPT" --out "$SUBMIT_SUMMARY" \
  --workstream "$WORKSTREAM" --artifact "$SUBMIT_SUMMARY_ARTIFACT"
echo "submit receipt: $SUBMIT_RECEIPT"
echo "submit summary: $SUBMIT_SUMMARY"
