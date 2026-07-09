#!/usr/bin/env bash
# Replay the v11 panel completion gate after records are synced back.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"
export PYTHONPATH="${PYTHONPATH:-src}"
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"

"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_panel_completion --manifest configs/m6d_w2_target_family_redesign_v11_representative_targets.json --min-targets 4 --min-records-per-target 20 --target-alpha 0.2 --panel-out results/m6d_w2_target_family_redesign_v11_panel_report_alpha02.json --out results/m6d_w2_target_family_redesign_v11_panel_completion.json
