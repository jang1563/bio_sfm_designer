"""Tests for the no-spend W3 challenge manifest."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_challenge_manifest import (
    build_manifest,
    main,
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


def _sha256_file(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows():
    return [
        {
            "adjudication_rank": 1,
            "adjudication_role": "discordant_boltz_chai_label",
            "adjudication_selection_reason": "label_a != label_b",
            "target_id": "d0",
            "complex_target_id_a": "3PC8_AB",
            "complex_target_id_b": "3PC8_AB",
            "complex_target_id_agrees": True,
            "label_a": False,
            "label_b": True,
            "label_agrees": False,
            "predictor_a": "boltz2_complex",
            "predictor_b": "chai1_complex",
            "signal_source_a": "boltz2_pae_interaction",
            "signal_source_b": "chai1_pae_interaction",
            "label_source_a": "boltz2_lrmsd_to_reference",
            "label_source_b": "chai1_lrmsd_to_reference",
            "lrmsd_threshold_a": 4.0,
            "lrmsd_threshold_b": 4.0,
            "label_threshold_agrees": True,
            "pae_interaction_a": 17.0,
            "pae_interaction_b": 4.0,
            "lrmsd_a": 55.0,
            "lrmsd_b": 1.5,
        },
        {
            "adjudication_rank": 2,
            "adjudication_role": "concordant_success_control",
            "adjudication_selection_reason": "first 1 sorted concordant-success ids",
            "target_id": "c0",
            "complex_target_id_a": "3PC8_AB",
            "complex_target_id_b": "3PC8_AB",
            "complex_target_id_agrees": True,
            "label_a": True,
            "label_b": True,
            "label_agrees": True,
            "predictor_a": "boltz2_complex",
            "predictor_b": "chai1_complex",
            "signal_source_a": "boltz2_pae_interaction",
            "signal_source_b": "chai1_pae_interaction",
            "label_source_a": "boltz2_lrmsd_to_reference",
            "label_source_b": "chai1_lrmsd_to_reference",
            "lrmsd_threshold_a": 4.0,
            "lrmsd_threshold_b": 4.0,
            "label_threshold_agrees": True,
            "pae_interaction_a": 4.0,
            "pae_interaction_b": 4.2,
            "lrmsd_a": 2.0,
            "lrmsd_b": 1.8,
        },
    ]


def _next_protocol(adjudication_jsonl, sha, *, claim=False):
    return {
        "_path": "/tmp/w3_next.json",
        "status": "w3_next_protocol_ready_no_spend",
        "audit_ok": True,
        "no_submit": True,
        "no_api_spend": True,
        "no_gpu_spend": True,
        "can_claim_independent_predictor_robustness_now": claim,
        "positive_claim_supported": False,
        "adjudication_set_contract": {
            "jsonl": adjudication_jsonl,
            "jsonl_sha256": sha,
            "n_rows": 2,
            "counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
            "required_counts_by_role": {
                "discordant_boltz_chai_label": 1,
                "concordant_success_control": 1,
            },
        },
        "recommended_next_routes": [
            {"rank": 1, "route": "third_independent_predictor_or_protocol"},
            {"rank": 2, "route": "stronger_chai_msa_template_protocol"},
        ],
        "decision_contract": {
            "stage": "challenge_panel_adjudication_before_full_w3_claim",
            "discordant_alignment_threshold": 1,
            "control_consistency_threshold": 1,
            "future_result_schema": ["target_id", "predictor_or_protocol_id", "label"],
            "outcomes": [],
        },
    }


class M6DW3ChallengeManifestTests(unittest.TestCase):
    def test_build_manifest_materializes_no_spend_challenge_panel(self):
        with tempfile.TemporaryDirectory() as d:
            adjudication = os.path.join(d, "adjudication.jsonl")
            source_a = os.path.join(d, "boltz.jsonl")
            source_b = os.path.join(d, "chai.jsonl")
            _write_jsonl(adjudication, _rows())
            _write_jsonl(source_a, [{"target_id": "d0", "predictor_id": "boltz2_complex"},
                                    {"target_id": "c0", "predictor_id": "boltz2_complex"}])
            _write_jsonl(source_b, [{"target_id": "d0", "predictor_id": "chai1_complex"},
                                    {"target_id": "c0", "predictor_id": "chai1_complex"}])

            rep = build_manifest(
                _next_protocol(adjudication, _sha256_file(adjudication)),
                _rows(),
                adjudication_jsonl=adjudication,
                source_records=[source_a, source_b],
                report_date="2026-07-05",
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "w3_challenge_manifest_ready_no_submit")
        self.assertFalse(rep["execution_ready"])
        self.assertFalse(rep["can_claim_independent_predictor_robustness_now"])
        self.assertEqual(rep["challenge_panel"]["counts_by_role"]["discordant_boltz_chai_label"], 1)
        self.assertEqual(rep["source_record_audit"][0]["selected_seen"], 2)
        self.assertEqual(rep["rows"][0]["source_labels"]["label_a"], False)
        self.assertIn("explicit approval", rep["execution_blockers"][-1])

    def test_blocks_next_protocol_claim_leak(self):
        with tempfile.TemporaryDirectory() as d:
            adjudication = os.path.join(d, "adjudication.jsonl")
            source = os.path.join(d, "records.jsonl")
            _write_jsonl(adjudication, _rows())
            _write_jsonl(source, [{"target_id": "d0"}, {"target_id": "c0"}])

            rep = build_manifest(
                _next_protocol(adjudication, _sha256_file(adjudication), claim=True),
                _rows(),
                adjudication_jsonl=adjudication,
                source_records=[source],
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_next_protocol_claim_leak", kinds)

    def test_blocks_missing_source_target_ids(self):
        with tempfile.TemporaryDirectory() as d:
            adjudication = os.path.join(d, "adjudication.jsonl")
            source = os.path.join(d, "records.jsonl")
            _write_jsonl(adjudication, _rows())
            _write_jsonl(source, [{"target_id": "d0"}])

            rep = build_manifest(
                _next_protocol(adjudication, _sha256_file(adjudication)),
                _rows(),
                adjudication_jsonl=adjudication,
                source_records=[source],
            )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("w3_challenge_source_record_target_ids_missing", kinds)

    def test_render_markdown_names_no_submit_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            adjudication = os.path.join(d, "adjudication.jsonl")
            source = os.path.join(d, "records.jsonl")
            _write_jsonl(adjudication, _rows())
            _write_jsonl(source, [{"target_id": "d0"}, {"target_id": "c0"}])
            rep = build_manifest(
                _next_protocol(adjudication, _sha256_file(adjudication)),
                _rows(),
                adjudication_jsonl=adjudication,
                source_records=[source],
            )

        md = render_markdown(rep)

        self.assertIn("M6d W3 Challenge Manifest", md)
        self.assertIn("no-submit, no-API, no-GPU", md)
        self.assertIn("not a positive W3 robustness claim", md)

    def test_cli_writes_manifest_files(self):
        with tempfile.TemporaryDirectory() as d:
            adjudication = os.path.join(d, "adjudication.jsonl")
            source_a = os.path.join(d, "boltz.jsonl")
            source_b = os.path.join(d, "chai.jsonl")
            next_protocol = os.path.join(d, "w3_next.json")
            out_json = os.path.join(d, "manifest.json")
            out_md = os.path.join(d, "manifest.md")
            _write_jsonl(adjudication, _rows())
            _write_jsonl(source_a, [{"target_id": "d0", "predictor_id": "boltz2_complex"},
                                    {"target_id": "c0", "predictor_id": "boltz2_complex"}])
            _write_jsonl(source_b, [{"target_id": "d0", "predictor_id": "chai1_complex"},
                                    {"target_id": "c0", "predictor_id": "chai1_complex"}])
            _write_json(next_protocol, _next_protocol(adjudication, _sha256_file(adjudication)))

            rc = main([
                "--w3-next-protocol", next_protocol,
                "--adjudication-jsonl", adjudication,
                "--source-records", source_a,
                "--source-records", source_b,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["status"], "w3_challenge_manifest_ready_no_submit")
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
