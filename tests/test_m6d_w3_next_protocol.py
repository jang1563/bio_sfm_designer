"""Tests for the no-spend M6d W3 next-protocol contract."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_next_protocol import (
    build_protocol,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _w3_audit():
    return {
        "_path": "/tmp/w3_audit.json",
        "audit_ok": True,
        "status": "negative_robustness_result_adjudicated",
        "positive_claim_supported": False,
        "claim_boundary": "independent_predictor_robustness_not_supported",
        "current_protocol_verdict": "negative_robustness_result_for_no_msa_chai",
        "selected_protocol": "adjudicated_disagreement_protocol_v1",
        "label_agreement": 0.6,
        "min_label_agreement": 0.8,
        "matched_overlap": 30,
        "adjudication_set_artifact_audit": {
            "ok": True,
            "n_rows": 18,
            "actual_sha256": "a" * 64,
            "counts_by_role": {
                "discordant_boltz_chai_label": 12,
                "concordant_success_control": 6,
            },
            "path": "/tmp/adjudication.jsonl",
        },
    }


def _summary():
    return {
        "_path": "/tmp/w3_summary.json",
        "artifact": "m6d_w3_adjudication_set",
        "claim_boundary": "not a positive robustness claim; input set for future W3 adjudication only",
        "counts_by_role": {
            "discordant_boltz_chai_label": 12,
            "concordant_success_control": 6,
        },
        "n_rows": 18,
        "out_jsonl": "results/m6d_w3_adjudication_set.jsonl",
        "out_jsonl_sha256": "a" * 64,
        "selected_protocol": "adjudicated_disagreement_protocol_v1",
    }


class M6DW3NextProtocolTests(unittest.TestCase):
    def test_build_protocol_selects_third_predictor_first_without_claim(self):
        rep = build_protocol(_w3_audit(), _summary(), report_date="2026-07-05")

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_next_protocol_ready_no_spend")
        self.assertTrue(rep["no_submit"])
        self.assertTrue(rep["no_api_spend"])
        self.assertTrue(rep["no_gpu_spend"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(
            rep["recommended_next_routes"][0]["route"],
            "third_independent_predictor_or_protocol",
        )
        self.assertEqual(rep["decision_contract"]["discordant_alignment_threshold"], 10)
        self.assertEqual(rep["decision_contract"]["control_consistency_threshold"], 5)
        self.assertIn("full matched cross-predictor panel", rep["recommended_next_routes"][0]["claim_after_stage"])

    def test_blocks_positive_claim_leak(self):
        audit = _w3_audit()
        audit["positive_claim_supported"] = True

        rep = build_protocol(audit, _summary())

        self.assertFalse(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_next_protocol_blocked")
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_positive_claim_leak", kinds)

    def test_blocks_count_and_sha_drift(self):
        audit = _w3_audit()
        summary = _summary()
        summary["counts_by_role"]["discordant_boltz_chai_label"] = 11
        summary["n_rows"] = 17
        summary["out_jsonl_sha256"] = "b" * 64

        rep = build_protocol(audit, summary)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_adjudication_summary_count_mismatch", kinds)
        self.assertIn("w3_adjudication_summary_row_count_mismatch", kinds)
        self.assertIn("w3_adjudication_sha_mismatch", kinds)

    def test_render_markdown_contains_next_route_and_guards(self):
        md = render_markdown(build_protocol(_w3_audit(), _summary()))

        self.assertIn("M6d W3 Next Protocol", md)
        self.assertIn("third_independent_predictor_or_protocol", md)
        self.assertIn("no-submit, no-API, no-GPU", md)
        self.assertIn("do not rerun the same no-MSA Chai protocol", md)

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            audit = os.path.join(d, "audit.json")
            summary = os.path.join(d, "summary.json")
            out_json = os.path.join(d, "next.json")
            out_md = os.path.join(d, "next.md")
            _write_json(audit, _w3_audit())
            _write_json(summary, _summary())

            rc = main([
                "--w3-adjudication-audit", audit,
                "--w3-adjudication-summary", summary,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_next_protocol_ready_no_spend")
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
