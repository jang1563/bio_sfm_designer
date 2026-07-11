"""Tests for label-blind W2b target selection."""

import copy
import unittest

from bio_sfm_designer.experiments.m6d_w2b_target_selector import select_targets


def _protocol():
    return {
        "objective": "test",
        "claim_scope": {},
        "fresh_target_contract": {"n_initial_targets": 3},
        "generation_stages": {
            "fit": {"records_per_target": 60, "seed_namespace": "w2b-fit-v1"},
        },
        "fit_stage_rule": {},
        "certification_rule": {},
        "panel_decision_rule": {},
        "compute_budget": {},
        "post_hoc_changes_forbidden": [],
    }


def _manifest():
    return {
        "defaults": {"num_seq": 100, "temp": 0.3},
        "targets": [
            {"id": f"T{index}_AB", "rcsb_id": f"T{index}", "records": f"t{index}.jsonl"}
            for index in range(6)
        ],
    }


class W2BTargetSelectorTests(unittest.TestCase):
    def test_selection_is_label_blind_fixed_size_and_stage_bound(self):
        output = select_targets(_manifest(), _protocol())

        self.assertTrue(output["report"]["audit_ok"])
        self.assertEqual(output["report"]["n_selected"], 3)
        self.assertFalse(output["report"]["label_data_consumed"])
        self.assertFalse(output["report"]["ready_for_cayuga_submission"])
        self.assertEqual(output["manifest"]["defaults"]["num_seq"], 60)
        self.assertTrue(all(row["w2b_stage"] == "fit" for row in output["manifest"]["targets"]))

    def test_selection_does_not_depend_on_input_order(self):
        first = select_targets(_manifest(), _protocol())
        reversed_manifest = copy.deepcopy(_manifest())
        reversed_manifest["targets"].reverse()
        second = select_targets(reversed_manifest, _protocol())

        self.assertEqual(
            first["report"]["selected_target_ids"],
            second["report"]["selected_target_ids"],
        )

    def test_selection_does_not_change_with_mutable_execution_state(self):
        first = select_targets(_manifest(), _protocol())
        updated = copy.deepcopy(_protocol())
        updated["status"] = "later_status"
        updated["current_execution_state"] = {"mutable": True}
        second = select_targets(_manifest(), updated)

        self.assertEqual(first["report"]["protocol_sha256"], second["report"]["protocol_sha256"])
        self.assertEqual(first["report"]["selected_target_ids"], second["report"]["selected_target_ids"])

    def test_duplicate_source_fails_closed(self):
        manifest = _manifest()
        manifest["targets"][1]["rcsb_id"] = manifest["targets"][0]["rcsb_id"]
        with self.assertRaisesRegex(ValueError, "source RCSB ids"):
            select_targets(manifest, _protocol())


if __name__ == "__main__":
    unittest.main()
