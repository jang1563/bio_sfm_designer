"""Tests for the W2 v9 post-panel decision protocol."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_decision_protocol import (
    build_protocol,
    classify_panel_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _manifest(n=14):
    return {
        "_path": "/tmp/manifest.json",
        "targets": [
            {
                "id": f"t{i}",
                "records": f"hpc_outputs/v9/t{i}/records_boltz_complex.jsonl",
                "out_prefix": f"hpc_outputs/v9/t{i}",
            }
            for i in range(n)
        ],
    }


def _submit_ready(n=14):
    return {
        "_path": "/tmp/submit_ready.json",
        "ok": True,
        "n_targets": n,
        "n_ready_targets": n,
        "target_ids": [f"t{i}" for i in range(n)],
        "failures": [],
    }


def _approval_packet():
    return {
        "_path": "/tmp/panel_approval.json",
        "status": "panel_approval_packet_ready",
        "approval_packet_ready": True,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "submit_receipt": "/tmp/absent_receipt.jsonl",
        "submit_summary": "/tmp/absent_summary.json",
        "panel_approval_env_var": "BIO_SFM_APPROVE_V9_PANEL",
        "panel_approval_env_value": "approve-v9-panel-submit",
        "submit_command_if_approved": "ssh ${CAYUGA_BIO_SFM_HOST} 'BIO_SFM_APPROVE_V9_PANEL=approve-v9-panel-submit bash wrapper.sh'",
        "sync_back_command_after_jobs_finish": "bash results/m6d_w2_target_family_redesign_v9_sync_back.sh",
        "checks": {
            "target_msa_strict_ready": True,
            "panel_preflight_ready": True,
            "panel_dry_run_no_sbatch": True,
            "panel_guard_no_env_refuses": True,
            "submit_receipt_absent": True,
            "submit_summary_absent": True,
        },
    }


def _panel_report(status, *, ok=False, certified_ids=(), not_certified_ids=()):
    targets = [
        {"complex_target_id": target_id, "certified": True}
        for target_id in certified_ids
    ]
    targets.extend(
        {"complex_target_id": target_id, "certified": False}
        for target_id in not_certified_ids
    )
    return {
        "ok": ok,
        "panel_status": status,
        "target_alpha": 0.2,
        "n_targets": len(targets),
        "targets": targets,
        "failures": [] if ok else [{"kind": "target_not_certified", "targets": list(not_certified_ids)}],
    }


class M6DW2PanelDecisionProtocolTests(unittest.TestCase):
    def test_ready_protocol_is_no_submit_and_not_a_claim(self):
        rep = build_protocol(
            target_manifest=_manifest(),
            submit_ready=_submit_ready(),
            approval_packet=_approval_packet(),
        )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["status"], "post_panel_decision_protocol_ready")
        self.assertTrue(rep["no_submit"])
        self.assertTrue(rep["can_submit_panel_if_user_explicitly_approves"])
        self.assertFalse(rep["can_claim_w2_generalization_now"])
        self.assertEqual(rep["panel_contract"]["panel_label"], "predeclared W2 Boltz-2 panel/protocol")
        self.assertEqual(rep["panel_contract"]["n_manifest_targets"], 14)
        self.assertEqual(rep["current_panel_result"]["status"], "not_available_not_submitted")
        self.assertIn("target-wise panel certification", rep["claim_boundary"]["w2_multi_target_generalization"])
        self.assertIn("exact manifest target-set", rep["claim_boundary"]["w2_multi_target_generalization"])
        self.assertIn("duplicate-free target rows", rep["claim_boundary"]["w2_multi_target_generalization"])
        self.assertIn(
            "report target counts match",
            " ".join(rule["if"] for rule in rep["decision_rules"]),
        )
        self.assertIn("submit_guarded_panel", [step["step"] for step in rep["execution_sequence_if_explicitly_approved"]])
        self.assertIn(
            "BIO_SFM_APPROVE_V9_PANEL=approve-v9-panel-submit",
            rep["execution_sequence_if_explicitly_approved"][0]["requires"],
        )
        self.assertIn("pooled diagnostic", render_markdown(rep))

    def test_claim_drift_in_approval_packet_blocks_protocol(self):
        packet = _approval_packet()
        packet["can_claim_w2_generalization"] = True

        rep = build_protocol(
            target_manifest=_manifest(),
            submit_ready=_submit_ready(),
            approval_packet=packet,
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("panel_approval_packet_not_ready_or_claim_drift", kinds)
        self.assertFalse(rep["can_submit_panel_if_user_explicitly_approves"])

    def test_classifies_target_wise_certified_panel_as_w2_supported(self):
        panel = _panel_report(
            "multi_target_certified",
            ok=True,
            certified_ids=[f"t{i}" for i in range(14)],
        )

        result = classify_panel_report(
            panel,
            target_alpha=0.2,
            min_targets=14,
            panel_label="W2 v11 Boltz-2 representative panel/protocol",
        )

        self.assertEqual(result["status"], "w2_generalization_supported_by_target_wise_panel")
        self.assertTrue(result["w2_generalization_supported"])
        self.assertEqual(len(result["certified_targets"]), 14)
        self.assertIn("W2 v11 Boltz-2 representative panel/protocol", result["claim"])

    def test_target_set_mismatch_blocks_w2_support_even_when_certified(self):
        panel = _panel_report(
            "multi_target_certified",
            ok=True,
            certified_ids=["t0", "t_extra"],
        )

        result = classify_panel_report(
            panel,
            target_alpha=0.2,
            min_targets=2,
            expected_target_ids=["t0", "t1"],
        )

        self.assertEqual(result["status"], "panel_report_target_set_mismatch")
        self.assertFalse(result["w2_generalization_supported"])
        self.assertEqual(result["target_set_check"]["missing_target_ids"], ["t1"])
        self.assertEqual(result["target_set_check"]["unexpected_target_ids"], ["t_extra"])
        self.assertIn("targets do not match", result["claim"])

    def test_duplicate_target_rows_block_w2_support_even_when_set_matches(self):
        panel = _panel_report(
            "multi_target_certified",
            ok=True,
            certified_ids=["t0", "t1", "t1"],
        )

        result = classify_panel_report(
            panel,
            target_alpha=0.2,
            min_targets=2,
            expected_target_ids=["t0", "t1"],
        )

        self.assertEqual(result["status"], "panel_report_target_set_mismatch")
        self.assertFalse(result["w2_generalization_supported"])
        self.assertEqual(result["target_set_check"]["duplicate_target_ids"], ["t1"])
        self.assertEqual(result["target_set_check"]["n_observed_rows"], 3)
        self.assertEqual(result["target_set_check"]["n_expected_targets"], 2)
        self.assertFalse(result["target_set_check"]["reported_expected_count_ok"])

    def test_classifies_partial_target_certificates_as_target_specific_only(self):
        panel = _panel_report(
            "multi_target_evaluable_not_certified",
            ok=False,
            certified_ids=["t0"],
            not_certified_ids=["t1", "t2"],
        )

        result = classify_panel_report(panel, target_alpha=0.2, min_targets=3)

        self.assertEqual(result["status"], "w2_generalization_not_supported_target_wise")
        self.assertFalse(result["w2_generalization_supported"])
        self.assertEqual(result["certified_targets"], ["t0"])
        self.assertIn("target-specific only", result["claim"])

    def test_main_writes_protocol_files(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            submit_ready = os.path.join(d, "submit_ready.json")
            packet = os.path.join(d, "packet.json")
            out_json = os.path.join(d, "protocol.json")
            out_md = os.path.join(d, "protocol.md")
            _write_json(manifest, _manifest())
            _write_json(submit_ready, _submit_ready())
            _write_json(packet, _approval_packet())

            rep = main([
                "--target-manifest", manifest,
                "--submit-ready", submit_ready,
                "--approval-packet", packet,
                "--completion-report", os.path.join(d, "missing_completion.json"),
                "--panel-report", os.path.join(d, "missing_panel.json"),
                "--panel-label", "W2 v11 Boltz-2 representative panel/protocol",
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            with open(out_json) as fh:
                saved = json.load(fh)
            with open(out_md) as fh:
                md = fh.read()

        self.assertEqual(rep["status"], "post_panel_decision_protocol_ready")
        self.assertEqual(saved["status"], "post_panel_decision_protocol_ready")
        self.assertEqual(saved["panel_contract"]["panel_label"], "W2 v11 Boltz-2 representative panel/protocol")
        self.assertIn("M6d W2 Panel Decision Protocol", md)
        self.assertIn("W2 v11 Boltz-2 representative panel/protocol", md)


if __name__ == "__main__":
    unittest.main()
