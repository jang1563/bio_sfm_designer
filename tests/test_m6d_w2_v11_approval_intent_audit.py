"""Tests for W2 v11 approval intent auditing."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v11_approval_intent_audit import (
    audit_approval_intent,
    main,
    render_markdown,
)
from bio_sfm_designer.experiments.m6d_w2_approval_scope import bind_scope


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _ready_decision_state():
    state = {
        "status": "awaiting_explicit_panel_submission_approval",
        "audit_ok": True,
        "decision": "awaiting_explicit_approval",
        "no_submit": True,
        "submitted": False,
        "can_submit_panel_if_user_explicitly_approves": True,
        "can_claim_w2_generalization": False,
        "approval_disambiguation": {
            "continuation_phrases_are_approval": False,
            "non_approval_continuation_phrases": [
                "resume goal",
                "go ahead",
                "continue working toward the active thread goal",
            ],
            "approval_must_explicitly_name": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "machine_gate": "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
        },
        "operator_approval_checklist": {
            "approval_phrase_required": "W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            "machine_gate": "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
        },
    }
    state["approval_scope"] = bind_scope({
        "manifest": "configs/v11.json",
        "manifest_sha256": "a" * 64,
        "target_ids": ["t0", "t1"],
        "n_ready_targets": 2,
        "planned_design_records": 200,
    })
    return state


def _accepted_message():
    return (
        "I explicitly approve W2 v11 Cayuga ProteinMPNN/Boltz panel submission. "
        "I acknowledge this will run the guarded Cayuga panel submit command with "
        "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit, create a submit receipt "
        "and Slurm jobs, spend GPU/compute before sync-back and target-wise certification."
    )


class M6DW2V11ApprovalIntentAuditTests(unittest.TestCase):
    def test_explicit_message_with_required_acknowledgements_is_accepted(self):
        rep = audit_approval_intent(
            message=_accepted_message(),
            decision_state=_ready_decision_state(),
            decision_state_path="decision.json",
        )

        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["approval_intent_accepted"])
        self.assertTrue(rep["does_not_submit"])
        self.assertTrue(rep["no_submit"])
        self.assertFalse(rep["submitted"])
        self.assertEqual(rep["failures"], [])
        self.assertEqual(rep["approval_scope_sha256"], rep["approval_scope"]["scope_sha256"])
        self.assertEqual(rep["manifest_sha256"], "a" * 64)
        self.assertIn("Approval intent accepted: `True`", render_markdown(rep))

    def test_continuation_phrase_is_rejected(self):
        rep = audit_approval_intent(
            message="go ahead",
            decision_state=_ready_decision_state(),
            decision_state_path="decision.json",
        )

        self.assertFalse(rep["audit_ok"])
        self.assertFalse(rep["approval_intent_accepted"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("non_approval_continuation_phrase", kinds)
        self.assertIn("approval_phrase_missing", kinds)

    def test_required_phrase_without_acknowledgements_is_rejected(self):
        rep = audit_approval_intent(
            message="Please do W2 v11 Cayuga ProteinMPNN/Boltz panel submission.",
            decision_state=_ready_decision_state(),
            decision_state_path="decision.json",
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_term_present_missing", kinds)
        self.assertIn("receipt_and_jobs_acknowledged_missing", kinds)
        self.assertIn("compute_spend_acknowledged_missing", kinds)

    def test_machine_gate_alone_is_not_approval(self):
        rep = audit_approval_intent(
            message="BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit",
            decision_state=_ready_decision_state(),
            decision_state_path="decision.json",
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_phrase_missing", kinds)
        self.assertIn("approval_term_present_missing", kinds)

    def test_not_ready_decision_state_blocks_even_explicit_message(self):
        decision = _ready_decision_state()
        decision["status"] = "submission_decision_blocked"
        decision["audit_ok"] = False

        rep = audit_approval_intent(
            message=_accepted_message(),
            decision_state=decision,
            decision_state_path="decision.json",
        )

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("decision_state_not_ready", kinds)

    def test_main_writes_artifacts_and_require_accepted_controls_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            decision = os.path.join(d, "decision.json")
            out_json = os.path.join(d, "intent.json")
            out_md = os.path.join(d, "intent.md")
            _write_json(decision, _ready_decision_state())

            ok = main([
                "--message",
                _accepted_message(),
                "--decision-state",
                decision,
                "--out-json",
                out_json,
                "--out-md",
                out_md,
                "--require-accepted",
            ])
            self.assertEqual(ok, 0)
            with open(out_json) as fh:
                saved = json.load(fh)
            self.assertTrue(saved["approval_intent_accepted"])

            blocked = main([
                "--message",
                "continue working toward the active thread goal",
                "--decision-state",
                decision,
                "--out-json",
                out_json,
                "--out-md",
                out_md,
                "--require-accepted",
            ])
            self.assertEqual(blocked, 2)


if __name__ == "__main__":
    unittest.main()
