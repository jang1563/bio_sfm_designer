"""Tests for W2 gate-strategy blocker resolution."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_gate_strategy_resolution import (
    build_protocol_config,
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _gate_strategy():
    return {
        "branch_id": "v6",
        "spend_gate": {
            "blockers": [
                "label_degenerate_gate_validation_policy_missing",
                "low_pae_acceptance_strategy_missing",
                "cutoff_transfer_failure",
                "low_success_target_protocol_mismatch",
            ],
            "cayuga_submission_allowed": False,
        },
        "gate_strategy_groups": {
            "label_degeneracy_policy_required_before_gate_claim": ["all_success"],
            "low_pae_acceptance_strategy_required": ["low_pae"],
            "target_specific_calibration_required": ["cutoff_fail"],
            "target_alpha_split_sensitive_scale_or_recalibration_candidate": ["split"],
            "replace_target_or_redesign_generation_protocol": ["weak"],
        },
    }


def _candidate_pool(admitted=0, ready=False):
    return {
        "status": "no_admitted_candidates_source_redundancy_audit_only",
        "n_candidates": 25,
        "n_admitted_for_next_branch": admitted,
        "n_source_redundancy_audit_only": 3,
        "source_redundancy_audit_targets": ["audit_a", "audit_b"],
        "ready_for_revised_manifest": ready,
        "ready_for_cayuga_submission": False,
    }


def _rules(min_candidates=3):
    return {
        "artifact": "rules",
        "candidate_requirements": {
            "min_non_anchor_candidates_for_revised_manifest": min_candidates,
        },
    }


class M6DW2GateStrategyResolutionTests(unittest.TestCase):
    def test_build_report_resolves_label_degeneracy_fail_closed(self):
        rep = build_report(_gate_strategy(), _candidate_pool(), _rules())

        self.assertEqual(rep["status"], "gate_strategy_resolved_discovery_required")
        self.assertFalse(rep["ready_for_cayuga_submission"])
        label_policy = rep["selected_policies"]["label_degeneracy"]
        self.assertEqual(label_policy["policy"], "fail_closed_positive_controls_only")
        self.assertIn("all_success", label_policy["targets"])
        self.assertIn("actual TrustGate tau must exist", label_policy["requirements_to_reopen"][2])
        resolutions = {row["blocker"]: row for row in rep["blocker_resolution"]}
        self.assertFalse(
            resolutions["label_degenerate_gate_validation_policy_missing"]["unlocks_cayuga_submission"]
        )

    def test_candidate_pool_zero_admissions_blocks_manifest_and_target_msa(self):
        rep = build_report(_gate_strategy(), _candidate_pool(admitted=0, ready=False), _rules())

        self.assertFalse(rep["ready_for_revised_manifest"])
        self.assertFalse(rep["ready_for_target_msa_precompute"])
        self.assertEqual(rep["candidate_pool_readout"]["n_admitted_for_next_branch"], 0)
        self.assertIn("Do not submit", rep["next_actions"][0])

    def test_markdown_and_protocol_config_render_boundaries(self):
        rep = build_report(_gate_strategy(), _candidate_pool(), _rules())
        md = render_markdown(rep)
        cfg = build_protocol_config(rep)

        self.assertIn("Do not relax one-class TrustGate behavior", md)
        self.assertIn("no_fixed_cutoff_transfer", md)
        self.assertFalse(cfg["ready_for_cayuga_submission"])
        self.assertEqual(cfg["protocol_id"], rep["branch_id"])

    def test_cli_writes_json_markdown_and_protocol_config(self):
        with tempfile.TemporaryDirectory() as d:
            gate = os.path.join(d, "gate.json")
            pool = os.path.join(d, "pool.json")
            rules = os.path.join(d, "rules.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            out_cfg = os.path.join(d, "cfg.json")
            _write_json(gate, _gate_strategy())
            _write_json(pool, _candidate_pool())
            _write_json(rules, _rules())

            rc = main([
                "--gate-strategy", gate,
                "--candidate-pool", pool,
                "--candidate-rules", rules,
                "--out-json", out_json,
                "--out-md", out_md,
                "--out-protocol-config", out_cfg,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_cfg))
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertFalse(saved["ready_for_cayuga_submission"])


if __name__ == "__main__":
    unittest.main()
