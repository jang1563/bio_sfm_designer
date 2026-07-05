"""Tests for the standalone M6d W3 adjudication audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_goal_decision_protocol import (
    materialize_w3_adjudication_set,
)
from bio_sfm_designer.experiments.m6d_w3_adjudication_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _matches():
    return [
        {
            "target_id": "d0",
            "label_a": False,
            "label_b": True,
            "pae_interaction_a": 18.0,
            "pae_interaction_b": 4.0,
        },
        {
            "target_id": "c0",
            "label_a": True,
            "label_b": True,
            "pae_interaction_a": 4.5,
            "pae_interaction_b": 4.2,
        },
    ]


def _cross_predictor():
    return {
        "_path": "/tmp/cross.json",
        "ok": False,
        "min_label_agreement": 0.8,
        "failures": [{"kind": "label_agreement_below_min"}],
        "pairs": [{
            "label_agreement": 0.5,
            "min_label_agreement": 0.8,
            "n_overlap": 2,
        }],
    }


def _decision_protocol(artifact):
    return {
        "_path": "/tmp/decision.json",
        "artifact": "m6d_w2_w3_decision_protocol",
        "w3": {
            "status": "protocol_selected",
            "current_protocol_verdict": "negative_robustness_result_for_no_msa_chai",
            "selected_protocol": "adjudicated_disagreement_protocol_v1",
            "claim_boundary": "independent_predictor_robustness_not_supported",
            "label_agreement": 0.5,
            "min_label_agreement": 0.8,
            "matched_overlap": 2,
            "cross_predictor_failure_kinds": ["label_agreement_below_min"],
            "strict_adjudication_integrity": True,
            "strict_adjudication_integrity_blockers": [],
            "adjudication_set": {
                "discordant_target_ids": ["d0"],
                "concordant_success_control_ids": ["c0"],
            },
            "adjudication_set_artifact": artifact,
        },
    }


class M6DW3AdjudicationAuditTests(unittest.TestCase):
    def test_build_audit_accepts_negative_robustness_adjudication(self):
        with tempfile.TemporaryDirectory() as d:
            out_jsonl = os.path.join(d, "adjudication.jsonl")
            out_summary = os.path.join(d, "adjudication.json")
            artifact = materialize_w3_adjudication_set(
                _matches(),
                controls=1,
                source_matches="matches.jsonl",
                out_jsonl=out_jsonl,
                out_summary=out_summary,
            )

            rep = build_audit(_decision_protocol(artifact), _cross_predictor())

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "negative_robustness_result_adjudicated")
        self.assertFalse(rep["positive_claim_supported"])
        self.assertTrue(rep["adjudication_set_artifact_audit"]["ok"])
        self.assertEqual(rep["adjudication_set_artifact_audit"]["n_rows"], 2)
        self.assertIn("no-spend audit", render_markdown(rep))

    def test_build_audit_blocks_stale_adjudication_sha(self):
        with tempfile.TemporaryDirectory() as d:
            out_jsonl = os.path.join(d, "adjudication.jsonl")
            out_summary = os.path.join(d, "adjudication.json")
            artifact = materialize_w3_adjudication_set(
                _matches(),
                controls=1,
                source_matches="matches.jsonl",
                out_jsonl=out_jsonl,
                out_summary=out_summary,
            )
            artifact["out_jsonl_sha256"] = "0" * 64

            rep = build_audit(_decision_protocol(artifact), _cross_predictor())

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_adjudication_set_jsonl_sha256_mismatch", kinds)

    def test_build_audit_blocks_cross_predictor_drift(self):
        with tempfile.TemporaryDirectory() as d:
            out_jsonl = os.path.join(d, "adjudication.jsonl")
            out_summary = os.path.join(d, "adjudication.json")
            artifact = materialize_w3_adjudication_set(
                _matches(),
                controls=1,
                source_matches="matches.jsonl",
                out_jsonl=out_jsonl,
                out_summary=out_summary,
            )
            cross = _cross_predictor()
            cross["pairs"][0]["label_agreement"] = 1.0
            cross["ok"] = True
            cross["failures"] = []

            rep = build_audit(_decision_protocol(artifact), cross)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_cross_predictor_not_negative", kinds)
        self.assertIn("w3_cross_predictor_failure_kind_mismatch", kinds)
        self.assertIn("w3_cross_predictor_label_agreement_mismatch", kinds)

    def test_cli_writes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            out_jsonl = os.path.join(d, "adjudication.jsonl")
            out_summary = os.path.join(d, "adjudication.json")
            artifact = materialize_w3_adjudication_set(
                _matches(),
                controls=1,
                source_matches="matches.jsonl",
                out_jsonl=out_jsonl,
                out_summary=out_summary,
            )
            decision = os.path.join(d, "decision.json")
            cross = os.path.join(d, "cross.json")
            out_json = os.path.join(d, "audit.json")
            out_md = os.path.join(d, "audit.md")
            _write_json(decision, _decision_protocol(artifact))
            _write_json(cross, _cross_predictor())

            rc = main([
                "--decision-protocol", decision,
                "--cross-predictor", cross,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["audit_ok"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
