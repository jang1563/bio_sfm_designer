"""Tests for label-blind W2c target selection."""

import copy
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2c_target_selector import select_targets


def _protocol(n_targets=4):
    return {
        "locked_scientific_protocol": {
            "fresh_target_contract": {"n_initial_targets": n_targets},
            "fit_design": {"threshold_learning": {"records_per_target": 60}},
            "other_locked_field": "stable",
        }
    }


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def _manifest(root, n=12):
    rows = []
    for index in range(n):
        target_id = f"T{index:02d}_AB"
        source = f"T{index:02d}X"
        base = os.path.join(root, target_id)
        source_pdb = os.path.join(base, "source.pdb")
        prepared_pdb = os.path.join(base, "prepared.pdb")
        prep_report = os.path.join(base, "prepared.report.json")
        fasta = os.path.join(base, "target.fasta")
        fasta_report = os.path.join(base, "target.fasta.report.json")
        for path in (source_pdb, prepared_pdb, prep_report, fasta_report):
            _write(path)
        _write(fasta, f">{target_id}\nM{'A' * (index + 1)}G\n")
        rows.append({
            "id": target_id,
            "rcsb_id": source,
            "source_pdb": source_pdb,
            "prepared_pdb": prepared_pdb,
            "prep_report": prep_report,
            "target_fasta": fasta,
            "target_fasta_report": fasta_report,
            "target_msa": os.path.join(base, "target.a3m"),
            "target_msa_report": os.path.join(base, "target.a3m.report.json"),
        })
    return {"defaults": {"num_seq": 100}, "targets": rows}


def _predecessor(manifest):
    return {"targets": copy.deepcopy(manifest["targets"][:2])}


def _registry(manifest):
    return {
        "targets": [
            {
                "target_id": manifest["targets"][2]["id"],
                "source_rcsb_ids": [manifest["targets"][2]["rcsb_id"]],
                "ever_certified": True,
            },
            {
                "target_id": "unrelated",
                "source_rcsb_ids": [manifest["targets"][3]["rcsb_id"]],
                "observed_statuses": ["not_certified"],
            },
        ]
    }


class M6DW2CTargetSelectorTests(unittest.TestCase):
    def test_selects_label_blind_fresh_targets_and_requires_msa(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = _manifest(root)
            output = select_targets(manifest, _protocol(), _registry(manifest), _predecessor(manifest))

        report = output["report"]
        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["status"], "w2c_fresh_targets_selected_awaiting_msa_no_submit")
        self.assertEqual(report["n_eligible_after_exclusion"], 8)
        self.assertEqual(report["n_selected"], 4)
        self.assertFalse(report["label_data_consumed"])
        self.assertFalse(report["predictor_records_consumed"])
        self.assertFalse(report["ready_for_cayuga_submission"])
        self.assertEqual(len(report["missing_target_msa_targets"]), 4)
        self.assertTrue(all(target not in report["selected_target_ids"] for target in ("T00_AB", "T01_AB", "T02_AB", "T03_AB")))
        self.assertEqual(output["manifest"]["defaults"]["num_seq"], 60)
        self.assertFalse(output["manifest"]["cayuga_submission_allowed"])

    def test_selection_is_order_and_outcome_field_invariant(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = _manifest(root, n=14)
            registry = _registry(manifest)
            first = select_targets(manifest, _protocol(), registry, _predecessor(manifest))
            reversed_manifest = copy.deepcopy(manifest)
            reversed_manifest["targets"].reverse()
            changed_registry = copy.deepcopy(registry)
            changed_registry["targets"][0]["ever_certified"] = False
            changed_registry["targets"][0]["observed_statuses"] = ["changed"]
            second = select_targets(
                reversed_manifest,
                _protocol(),
                changed_registry,
                _predecessor(manifest),
            )

        self.assertEqual(first["report"]["selected_target_ids"], second["report"]["selected_target_ids"])
        self.assertEqual(first["report"]["locked_scientific_digest"], second["report"]["locked_scientific_digest"])

    def test_w2b_sequence_overlap_is_excluded_even_with_new_id(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = _manifest(root, n=10)
            predecessor = _predecessor(manifest)
            with open(manifest["targets"][4]["target_fasta"], "w") as handle:
                with open(predecessor["targets"][0]["target_fasta"]) as source:
                    handle.write(source.read())
            output = select_targets(manifest, _protocol(), {"targets": []}, predecessor)

        excluded = {row["target_id"]: row["reasons"] for row in output["report"]["excluded"]}
        self.assertIn("w2b_sequence_overlap", excluded["T04_AB"])

    def test_insufficient_fresh_pool_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = _manifest(root, n=6)
            with self.assertRaisesRegex(ValueError, "only .*W2c-eligible"):
                select_targets(manifest, _protocol(n_targets=4), _registry(manifest), _predecessor(manifest))


if __name__ == "__main__":
    unittest.main()
