#!/usr/bin/env python3
"""Keep scientific protocol state while dropping operator/scheduler metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def write(rel: str, value: dict) -> None:
    (ROOT / rel).write_text(json.dumps(value, indent=2) + "\n")


def sha256_file(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def sanitize_w2b() -> None:
    rel = "configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json"
    protocol = load(rel)
    state = protocol["current_execution_state"]
    protocol["compute_budget"] = {
        "initial_fit_records": protocol["compute_budget"]["initial_fit_records"],
        "maximum_total_records": protocol["compute_budget"]["maximum_total_records"],
        "staged_stop_after_fit": protocol["compute_budget"]["staged_stop_after_fit"],
    }
    protocol["current_execution_state"] = {
        "fit_target_ids": state["fit_target_ids"],
        "fit_records_total": state["fit_records_total"],
        "fit_report_status": state["fit_report_status"],
        "fit_eligible_target_ids": state["fit_eligible_target_ids"],
        "fit_refused_target_ids": state["fit_refused_target_ids"],
        "fit_frozen_rules": state["fit_frozen_rules"],
        "certification_target_ids": state["certification_target_ids"],
        "certification_records_total": state["certification_records_total"],
        "certification_report_status": state["certification_report_status"],
        "certification_certified_target_ids": state["certification_certified_target_ids"],
        "certification_selective_pae_certified_target_ids": state[
            "certification_selective_pae_certified_target_ids"
        ],
        "certification_panel_gate_passed": state["certification_panel_gate_passed"],
        "certification_terminal_after_certification": state[
            "certification_terminal_after_certification"
        ],
        "certification_terminal_reason": state["certification_terminal_reason"],
        "test_status": "not_run_because_test_rows_cannot_change_the_failed_certificate",
    }
    protocol["completed_unlock_conditions"] = [
        "the exact one-sided certification bound is implemented and tested",
        "fit and certification rows use disjoint candidate namespaces",
        "480 fit rows and 300 certification rows pass strict provenance QC",
        "five fit rules were eligible and four trust-all controls certified",
        "the sole selective-pAE rule failed exact certification, so the panel gate failed",
    ]
    protocol["remaining_unlock_conditions"] = []
    write(rel, protocol)


def sanitize_w2c() -> None:
    rel = "configs/m6d_w2c_one_shot_protocol.json"
    protocol = load(rel)
    state = protocol["execution_state"]
    target_manifest = state["target_manifest"]
    protocol["execution_state"] = {
        "target_manifest": target_manifest,
        "target_manifest_sha256": sha256_file(target_manifest),
        "target_ids": state["target_ids"],
        "missing_target_msa_targets": state["missing_target_msa_targets"],
        "evaluator_implemented": state["evaluator_implemented"],
        "command_wrapper_emitted": False,
        "operator_approval_recorded": False,
        "hpc_submission_allowed": False,
        "records_generated": 0,
    }
    protocol["remaining_unlock_conditions"] = [
        "precompute and hash-lock target MSAs for all eight selected targets",
        "pass the locked manifest and provenance checks without changing scientific rules",
        "review any future compute as a separate execution workflow",
    ]
    write(rel, protocol)


def main() -> int:
    sanitize_w2b()
    sanitize_w2c()
    print("sanitized W2b/W2c release protocols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
