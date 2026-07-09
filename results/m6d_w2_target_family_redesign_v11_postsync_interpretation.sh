#!/usr/bin/env bash
# Replay W2 v11 post-sync completion, target-wise report, and decision interpretation.
# This script does not submit jobs; it requires postsubmit sync-ready evidence first.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
MANIFEST=configs/m6d_w2_target_family_redesign_v11_representative_targets.json
RECEIPT=results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl
SUMMARY=results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json
POSTSUBMIT=results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
JOB_STATES=results/m6d_w2_target_family_redesign_v11_job_state_probe.json
COMPLETION_SCRIPT=results/m6d_w2_target_family_redesign_v11_panel_completion.sh
COMPLETION_REPORT=results/m6d_w2_target_family_redesign_v11_panel_completion.json
test -s "$MANIFEST"
test -s "$RECEIPT"
test -s "$SUMMARY"
test -s "$POSTSUBMIT"
test -s "$JOB_STATES"
test -s "$COMPLETION_SCRIPT"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --manifest "$MANIFEST" --receipt "$RECEIPT" --summary "$SUMMARY" --job-states "$JOB_STATES" --require-sync-ready --out-json "$POSTSUBMIT"
bash results/m6d_w2_target_family_redesign_v11_sync_back.sh
BIO_SFM_PYTHON="$PYTHON_BIN" PYTHONNOUSERSITE=1 bash "$COMPLETION_SCRIPT"
test -s "$COMPLETION_REPORT"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_panel_report --records hpc_outputs/m6d_w2_target_family_redesign_v11_records/10XZ_EF/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10YB_GH/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/12NP_AH/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10VB_IJ/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10ZO_AB/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/1A2Y_BA/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/1A6W_HL/records_boltz_complex.jsonl --target-alpha 0.2 --min-targets 4 --min-records-per-target 20 --out results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_decision_protocol --target-manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json --submit-ready results/m6d_w2_target_family_redesign_v11_manifest_post_msa_require_files.json --approval-packet results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json --completion-report results/m6d_w2_target_family_redesign_v11_panel_completion.json --panel-report results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json --target-alpha 0.2 --min-targets 4 --min-records-per-target 20 --panel-label 'W2 v11 Boltz-2 representative panel/protocol' --completion-script results/m6d_w2_target_family_redesign_v11_panel_completion.sh --sync-back-script results/m6d_w2_target_family_redesign_v11_sync_back.sh --out-json results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json --out-md results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.md
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation --panel-label 'W2 v11 Boltz-2 representative panel/protocol' --out-json results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json --out-md results/m6d_w2_target_family_redesign_v11_postsync_interpretation.md
