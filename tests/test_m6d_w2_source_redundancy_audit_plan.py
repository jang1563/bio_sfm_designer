"""Tests for the W2 source-redundancy audit plan."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_source_redundancy_audit_plan import (
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


class M6DW2SourceRedundancyAuditPlanTests(unittest.TestCase):
    def test_groups_audit_only_targets_with_failed_source_target(self):
        pool = {
            "screened_targets": [
                {
                    "target": "SRC_A",
                    "rcsb_id": "SRC",
                    "verdict": "excluded_current_protocol",
                    "source_redundancy_audit_only": False,
                },
                {
                    "target": "SRC_B",
                    "rcsb_id": "SRC",
                    "verdict": "source_redundancy_audit_only",
                    "source_redundancy_audit_only": True,
                    "structural_preflight": {"ca_interface_contacts": 25, "min_ca_distance": 4.0},
                    "reasons": ["source-redundant chain pair"],
                },
            ]
        }
        diagnostic = {
            "targets": [{
                "complex_target_id": "SRC_A",
                "classification": "target_protocol_mismatch_low_success",
                "success_rate": 0.0,
                "protocol_cutoff_accepts": 0,
            }]
        }

        rep = build_report(pool, diagnostic)

        self.assertEqual(rep["status"], "source_redundancy_audit_plan_ready_no_submit")
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertFalse(rep["ready_for_w2_generalization_claim"])
        self.assertEqual(rep["audit_targets"], ["SRC_B"])
        group = rep["source_groups"][0]
        self.assertEqual(group["source"], "SRC")
        self.assertEqual(group["failed_current_protocol_targets"][0]["success_rate"], 0.0)
        self.assertEqual(group["audit_only_targets"][0]["target"], "SRC_B")

    def test_no_audit_targets_is_non_submit_state(self):
        rep = build_report({"screened_targets": []}, {"targets": []})

        self.assertEqual(rep["status"], "no_source_redundancy_audit_targets")
        self.assertEqual(rep["n_audit_targets"], 0)
        self.assertFalse(rep["ready_for_cayuga_submission"])

    def test_markdown_states_not_generalization(self):
        rep = {
            "date": "2026-06-30",
            "status": "source_redundancy_audit_plan_ready_no_submit",
            "ready_for_cayuga_submission": False,
            "ready_for_w2_generalization_claim": False,
            "source_groups": [{
                "source": "SRC",
                "failed_current_protocol_targets": [{"target": "SRC_A"}],
                "audit_only_targets": [{"target": "SRC_B"}],
                "audit_question": "question",
            }],
            "promotion_rules": ["write a separate audit manifest"],
            "next_action": "expand discovery",
        }

        md = render_markdown(rep)

        self.assertIn("Source-Redundancy Audit Plan", md)
        self.assertIn("not independent multi-target evidence", md)
        self.assertIn("does not authorize Cayuga submission", md)

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            pool = os.path.join(d, "pool.json")
            diag = os.path.join(d, "diag.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            _write_json(pool, {
                "screened_targets": [{
                    "target": "SRC_B",
                    "rcsb_id": "SRC",
                    "verdict": "source_redundancy_audit_only",
                    "source_redundancy_audit_only": True,
                    "structural_preflight": {"ca_interface_contacts": 25},
                }]
            })
            _write_json(diag, {"targets": []})

            rc = main([
                "--candidate-pool", pool,
                "--fresh-diagnostic", diag,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
