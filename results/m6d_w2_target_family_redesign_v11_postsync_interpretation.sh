#!/usr/bin/env bash
# Replay W2 v11 post-sync completion, target-wise report, and decision interpretation.
# This script does not submit jobs; it requires postsubmit sync-ready evidence first.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
POSTSUBMIT=results/m6d_w2_target_family_redesign_v11_postsubmit_status.json
JOB_STATES=results/m6d_w2_target_family_redesign_v11_job_state_probe.json
test -s "$POSTSUBMIT"
test -s "$JOB_STATES"
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status --job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json --require-sync-ready
bash results/m6d_w2_target_family_redesign_v11_sync_back.sh
"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_panel_report --records hpc_outputs/m6d_w2_target_family_redesign_v11_records/10XZ_EF/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10YB_GH/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/12NP_AH/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10VB_IJ/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/10ZO_AB/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/1A2Y_BA/records_boltz_complex.jsonl hpc_outputs/m6d_w2_target_family_redesign_v11_records/1A6W_HL/records_boltz_complex.jsonl --target-alpha 0.2 --min-targets 4 --min-records-per-target 20 --out results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_decision_protocol --target-manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json --submit-ready results/m6d_w2_target_family_redesign_v11_manifest_post_msa_require_files.json --approval-packet results/m6d_w2_target_family_redesign_v11_panel_approval_packet.json --completion-report results/m6d_w2_target_family_redesign_v11_panel_completion.json --panel-report results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json --target-alpha 0.2 --min-targets 4 --min-records-per-target 20 --completion-script results/m6d_w2_target_family_redesign_v11_panel_completion.sh --sync-back-script results/m6d_w2_target_family_redesign_v11_sync_back.sh --out-json results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.json --out-md results/m6d_w2_target_family_redesign_v11_panel_decision_protocol.md
"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_postsync_interpretation --out-json results/m6d_w2_target_family_redesign_v11_postsync_interpretation.json --out-md results/m6d_w2_target_family_redesign_v11_postsync_interpretation.md
