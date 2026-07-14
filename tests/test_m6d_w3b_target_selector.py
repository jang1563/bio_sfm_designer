"""Tests for label-blind W3b target selection and role assignment."""

import copy
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3b_target_selector import select_targets


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def _representatives(root, n=12):
    rows = []
    for index in range(n):
        target_id = f"T{index:02d}_AB"
        source = f"T{index:02d}X"
        base = os.path.join(root, target_id)
        paths = {
            "source_pdb": os.path.join(base, "source.pdb"),
            "prepared_pdb": os.path.join(base, "prepared.pdb"),
            "prep_report": os.path.join(base, "prepared.report.json"),
            "target_fasta": os.path.join(base, "target.fasta"),
            "target_fasta_report": os.path.join(base, "target.fasta.report.json"),
            "target_msa": os.path.join(base, "target.a3m"),
            "target_msa_report": os.path.join(base, "target.a3m.report.json"),
        }
        for key, path in paths.items():
            if key not in ("target_fasta", "target_msa", "target_msa_report"):
                _write(path)
        _write(paths["target_fasta"], f">{target_id}\nM{'A' * (index + 1)}G\n")
        rows.append({"id": target_id, "rcsb_id": source, **paths})
    return {"defaults": {}, "targets": rows}


def _protocol():
    return {
        "locked_scientific_protocol": {
            "fresh_target_contract": {
                "n_initial_targets": 4,
                "n_fit_targets": 1,
                "n_certification_targets": 2,
                "n_held_out_test_targets": 1,
                "input_reuse_scope": "structural only",
            },
            "fit_design": {"records_per_target": 10},
            "certification_design": {"records_per_target": 20},
            "held_out_test_design": {"records_per_target": 30},
        }
    }


class M6DW3BTargetSelectorTests(unittest.TestCase):
    def test_excludes_prior_surfaces_and_assigns_disjoint_roles(self):
        with tempfile.TemporaryDirectory() as root:
            representatives = _representatives(root)
            historical = {
                "targets": [
                    {"target_id": "T02_AB", "source_rcsb_ids": ["T02X"]},
                    {"target_id": "T03_AB", "source_rcsb_ids": ["T03X"]},
                ]
            }
            w2b = {"targets": copy.deepcopy(representatives["targets"][:2])}
            w2c = {"targets": copy.deepcopy(representatives["targets"][4:6])}
            w3 = {
                "rows": [
                    {"complex_target_id": "T06_AB"},
                    {"complex_target_id": "T07_AB"},
                ]
            }
            output = select_targets(representatives, _protocol(), historical, w2b, w2c, w3)

        report = output["report"]
        manifest = output["manifest"]
        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["n_eligible_after_exclusion"], 4)
        self.assertEqual(report["n_selected"], 4)
        self.assertEqual(report["role_counts"], {"fit": 1, "certification": 2, "held_out_test": 1})
        self.assertEqual({row["id"] for row in manifest["targets"]}, {"T08_AB", "T09_AB", "T10_AB", "T11_AB"})
        self.assertEqual(len(report["missing_target_msa_targets"]), 4)
        self.assertFalse(report["label_data_consumed"])
        self.assertFalse(report["predictor_records_consumed"])
        self.assertFalse(report["ready_for_cayuga_submission"])

    def test_selection_is_order_and_outcome_metadata_invariant(self):
        with tempfile.TemporaryDirectory() as root:
            representatives = _representatives(root, n=14)
            historical = {"targets": []}
            empty = {"targets": []}
            w3 = {"rows": []}
            first = select_targets(representatives, _protocol(), historical, empty, empty, w3)
            reversed_rows = copy.deepcopy(representatives)
            reversed_rows["targets"].reverse()
            historical["irrelevant_outcome"] = "changed"
            second = select_targets(reversed_rows, _protocol(), historical, empty, empty, w3)

        self.assertEqual(first["report"]["selected_target_ids"], second["report"]["selected_target_ids"])
        self.assertEqual(first["report"]["ranking"], second["report"]["ranking"])

    def test_w2c_sequence_overlap_is_excluded_even_under_new_identity(self):
        with tempfile.TemporaryDirectory() as root:
            representatives = _representatives(root, n=8)
            w2c = {"targets": [copy.deepcopy(representatives["targets"][0])]}
            with open(representatives["targets"][1]["target_fasta"], "w") as handle:
                with open(w2c["targets"][0]["target_fasta"]) as source:
                    handle.write(source.read())
            output = select_targets(
                representatives,
                _protocol(),
                {"targets": []},
                {"targets": []},
                w2c,
                {"rows": []},
            )

        excluded = {row["target_id"]: row["reasons"] for row in output["report"]["excluded"]}
        self.assertIn("w2c_sequence_overlap", excluded["T01_AB"])


if __name__ == "__main__":
    unittest.main()
