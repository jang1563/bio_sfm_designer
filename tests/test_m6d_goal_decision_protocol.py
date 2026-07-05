"""Tests for the M6d W2/W3 goal-mode decision protocol."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_decision_protocol import (
    build_report,
    main,
    materialize_w3_adjudication_set,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class M6DGoalDecisionProtocolTests(unittest.TestCase):
    def test_build_report_selects_negative_chai_disagreement_protocol(self):
        goal = {
            "objective": "continue",
            "current_status": {
                "w1": "certified",
                "w2": "evaluable_not_certified",
                "w3": "single_model_caveat_open",
                "w4": "closed_loop_round_complete",
            },
        }
        actions = {
            "target_triage": [
                {
                    "target": "3PC8_AB",
                    "alpha_0_2_seed_sensitivity": "4/100 split seeds certified",
                    "alpha_0_3_seed_sensitivity": "100/100 split seeds certified",
                    "estimated_additional_records_for_alpha_0_2": {"median": 22},
                    "action": "freeze target-specific certificate",
                },
                {
                    "target": "weak",
                    "alpha_0_2_seed_sensitivity": "0/100 split seeds certified",
                    "alpha_0_3_seed_sensitivity": "0/100 split seeds certified",
                    "estimated_additional_records_for_alpha_0_2": {"median": 1000},
                    "action": "replace",
                },
            ]
        }
        diagnostic = {
            "targets": [
                {
                    "complex_target_id": "3PC8_AB",
                    "classification": "underpowered_low_pae_acceptance",
                    "success_rate": 0.53,
                    "recommended_action": "do_not_pool",
                },
                {
                    "complex_target_id": "weak",
                    "classification": "target_protocol_mismatch_low_success",
                    "success_rate": 0.1,
                    "recommended_action": "replace_target",
                },
            ]
        }
        cross = {
            "ok": False,
            "min_label_agreement": 0.8,
            "failures": [{"kind": "label_agreement_below_min"}],
            "pairs": [{
                "label_agreement": 0.6,
                "min_label_agreement": 0.8,
                "n_overlap": 30,
                "meets_min_overlap": True,
                "meets_min_labeled_overlap": True,
                "complex_target_id_complete": True,
                "complex_target_id_agree": True,
                "label_threshold_complete": True,
                "label_threshold_agree": True,
                "provenance_complete": True,
                "distinct_signal_sources": True,
                "distinct_label_sources": True,
                "copied_numeric_values": False,
                "both_success": 18,
                "both_failure": 0,
                "predictor_b_only_success": 12,
                "numeric_copy_fraction": 0.0,
            }],
        }
        matches = [
            {"target_id": "d0", "label_a": False, "label_b": True},
            {"target_id": "d1", "label_a": True, "label_b": True},
        ]

        rep = build_report(goal, actions, diagnostic, cross, matches, controls=1)

        self.assertFalse(rep["can_mark_goal_complete"])
        self.assertEqual(
            rep["w3"]["current_protocol_verdict"],
            "negative_robustness_result_for_no_msa_chai",
        )
        self.assertEqual(rep["w3"]["selected_protocol"], "adjudicated_disagreement_protocol_v1")
        self.assertTrue(rep["w3"]["strict_adjudication_integrity"])
        self.assertIn("d0", rep["w3"]["adjudication_set"]["discordant_target_ids"])
        by_target = {row["target"]: row for row in rep["w2"]["targets"]}
        self.assertEqual(by_target["3PC8_AB"]["role"], "freeze_target_specific_certificate")
        self.assertEqual(by_target["weak"]["role"], "drop_or_replace")

    def test_build_report_does_not_adjudicate_when_integrity_fails(self):
        goal = {"objective": "continue", "current_status": {}}
        cross = {
            "ok": False,
            "min_label_agreement": 0.8,
            "failures": [
                {"kind": "label_agreement_below_min"},
                {"kind": "weak_target_identity"},
            ],
            "pairs": [{
                "label_agreement": 0.6,
                "min_label_agreement": 0.8,
                "n_overlap": 30,
                "meets_min_overlap": True,
                "meets_min_labeled_overlap": True,
                "complex_target_id_complete": False,
                "complex_target_id_agree": False,
                "label_threshold_complete": True,
                "label_threshold_agree": True,
                "provenance_complete": True,
                "distinct_signal_sources": True,
                "distinct_label_sources": True,
                "copied_numeric_values": False,
            }],
        }

        rep = build_report(goal, {"target_triage": []}, {"targets": []}, cross, [], controls=1)

        self.assertEqual(
            rep["w3"]["current_protocol_verdict"],
            "unresolved_contract_or_overlap_blocker",
        )
        self.assertEqual(rep["w3"]["selected_protocol"], "repair_contract_before_science_claim")
        self.assertFalse(rep["w3"]["strict_adjudication_integrity"])
        self.assertIn(
            "cross_predictor_has_non_agreement_failures",
            rep["w3"]["strict_adjudication_integrity_blockers"],
        )

    def test_render_markdown_contains_protocol_boundaries(self):
        rep = {
            "date": "2026-06-30",
            "overall_status": "w2_w3_decision_protocol_selected_goal_still_active",
            "completion_boundary": "not complete",
            "w2": {
                "status": "redesign_required_before_more_broad_panel_gpu",
                "targets": [],
                "target_rules": ["do not pool"],
            },
            "w3": {
                "status": "protocol_selected",
                "current_protocol_verdict": "negative_robustness_result_for_no_msa_chai",
                "selected_protocol": "adjudicated_disagreement_protocol_v1",
                "label_agreement": 0.6,
                "min_label_agreement": 0.8,
                "matched_overlap": 30,
                "both_success": 18,
                "chai_only_success": 12,
                "numeric_copy_fraction": 0.0,
                "cross_predictor_failure_kinds": ["label_agreement_below_min"],
                "strict_adjudication_integrity": True,
                "strict_adjudication_integrity_blockers": [],
                "next_spend_gate": "do not rerun no-MSA Chai",
                "adjudication_set": {
                    "discordant_target_ids": ["d0"],
                    "concordant_success_control_ids": ["d1"],
                },
                "protocol_rules": ["predeclare"],
            },
            "next_actions": ["refresh status"],
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2/W3 Decision Protocol", md)
        self.assertIn("negative_robustness_result_for_no_msa_chai", md)
        self.assertIn("do not rerun no-MSA Chai", md)
        self.assertIn("strict adjudication integrity", md)

    def test_materialize_w3_adjudication_set_writes_full_rows(self):
        with tempfile.TemporaryDirectory() as d:
            out_jsonl = os.path.join(d, "adjudication.jsonl")
            out_summary = os.path.join(d, "adjudication_summary.json")
            matches = [
                {
                    "target_id": "d0",
                    "complex_target_id_a": "3PC8_AB",
                    "label_a": False,
                    "label_b": True,
                    "pae_interaction_a": 17.2,
                    "pae_interaction_b": 4.8,
                },
                {
                    "target_id": "c0",
                    "complex_target_id_a": "3PC8_AB",
                    "label_a": True,
                    "label_b": True,
                    "pae_interaction_a": 4.1,
                    "pae_interaction_b": 4.8,
                },
                {
                    "target_id": "c1",
                    "complex_target_id_a": "3PC8_AB",
                    "label_a": True,
                    "label_b": True,
                    "pae_interaction_a": 5.1,
                    "pae_interaction_b": 4.9,
                },
            ]

            summary = materialize_w3_adjudication_set(
                matches,
                controls=1,
                source_matches="matches.jsonl",
                out_jsonl=out_jsonl,
                out_summary=out_summary,
            )

            with open(out_jsonl) as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            with open(out_summary) as fh:
                summary_from_disk = json.load(fh)

            self.assertEqual(summary["n_rows"], 2)
            self.assertEqual(summary_from_disk["n_rows"], 2)
            self.assertEqual(
                summary["counts_by_role"],
                {"discordant_boltz_chai_label": 1, "concordant_success_control": 1},
            )
            self.assertEqual(rows[0]["target_id"], "d0")
            self.assertEqual(rows[0]["adjudication_role"], "discordant_boltz_chai_label")
            self.assertEqual(rows[1]["target_id"], "c0")
            self.assertEqual(rows[1]["adjudication_role"], "concordant_success_control")
            self.assertIn("out_jsonl_sha256", summary)

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            goal = os.path.join(d, "goal.json")
            actions = os.path.join(d, "actions.json")
            diagnostic = os.path.join(d, "diagnostic.json")
            cross = os.path.join(d, "cross.json")
            matches = os.path.join(d, "matches.jsonl")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            out_adj = os.path.join(d, "w3_adjudication.jsonl")
            out_adj_summary = os.path.join(d, "w3_adjudication_summary.json")
            _write_json(goal, {"objective": "x", "current_status": {}})
            _write_json(actions, {"target_triage": []})
            _write_json(diagnostic, {"targets": []})
            _write_json(cross, {"ok": True, "pairs": [{"label_agreement": 1.0, "n_overlap": 5}]})
            _write_jsonl(matches, [
                {"target_id": "d0", "label_a": False, "label_b": True},
                {"target_id": "c0", "label_a": True, "label_b": True},
            ])

            rc = main([
                "--goal-anchor", goal,
                "--science-actions", actions,
                "--w2-panel-diagnostic", diagnostic,
                "--w3-cross-predictor", cross,
                "--w3-matches", matches,
                "--controls", "1",
                "--emit-w3-adjudication-set-jsonl", out_adj,
                "--emit-w3-adjudication-summary", out_adj_summary,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_adj))
            self.assertTrue(os.path.exists(out_adj_summary))
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["w3"]["adjudication_set_artifact"]["n_rows"], 2)
            self.assertEqual(rep["w3"]["adjudication_set_artifact"]["out_jsonl"], out_adj)


if __name__ == "__main__":
    unittest.main()
