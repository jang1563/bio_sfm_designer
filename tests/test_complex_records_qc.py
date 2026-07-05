"""QC tests for complex Boltz records before M6c analyses."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_records_qc import run_qc

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


def _valid_record(target_id="cx-0"):
    return {
        "target_id": target_id,
        "complex_target_id": "toy_complex",
        "regime": "complex",
        "predictor_id": "boltz2_complex",
        "signal_source": "boltz2_pae_interaction",
        "label_source": "boltz2_lrmsd_to_reference",
        "target_chain": "A",
        "binder_chain": "D",
        "mean_plddt": 90.0,
        "pae_interaction": 2.5,
        "iptm": 0.8,
        "ptm": 0.9,
        "lrmsd": 2.0,
        "lrmsd_threshold": 4.0,
        "truth": {"correct": True, "quality": 0.8},
        "interface_aligned": True,
        "refolder": "boltz2_complex",
    }


class ComplexRecordsQCTests(unittest.TestCase):
    def test_fixture_passes_qc(self):
        rep = run_qc([FIXTURE])
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["n_unique_target_ids"], 192)
        self.assertEqual(rep["n_failures"], 0)

    def test_fixture_passes_strict_qc_after_schema_backfill(self):
        rep = run_qc([FIXTURE], require_complex_target_id=True, require_provenance=True,
                     require_chain_ids=True)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["n_unique_target_ids"], 192)
        self.assertEqual(rep["n_failures"], 0)
        self.assertTrue(rep["require_complex_target_id"])
        self.assertTrue(rep["require_provenance"])
        self.assertTrue(rep["require_chain_ids"])

    def test_identical_duplicate_is_allowed_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            rec = _valid_record()
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
                fh.write(json.dumps(rec) + "\n")
            rep = run_qc([path])
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["n_unique_target_ids"], 1)
        self.assertEqual(rep["n_unique_record_keys"], 1)
        self.assertEqual(rep["n_exact_duplicates"], 1)

    def test_same_target_id_is_allowed_across_complex_targets(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            rec_a = _valid_record("design-0")
            rec_b = _valid_record("design-0")
            rec_b["complex_target_id"] = "other_complex"
            rec_b["lrmsd"] = 3.0
            rec_b["truth"]["quality"] = 0.7
            with open(path, "w") as fh:
                fh.write(json.dumps(rec_a) + "\n")
                fh.write(json.dumps(rec_b) + "\n")
            rep = run_qc([path], require_complex_target_id=True)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["n_unique_target_ids"], 1)
        self.assertEqual(rep["n_unique_record_keys"], 2)

    def test_strict_qc_accepts_scale_ready_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(_valid_record()) + "\n")
            rep = run_qc([path], require_complex_target_id=True, require_provenance=True,
                         require_chain_ids=True)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["require_complex_target_id"])
        self.assertTrue(rep["require_provenance"])
        self.assertTrue(rep["require_chain_ids"])

    def test_strict_qc_rejects_missing_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            rec = _valid_record()
            rec.pop("complex_target_id")
            rec.pop("signal_source")
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
            rep = run_qc([path], require_complex_target_id=True, require_provenance=True)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["missing_complex_target_id"], 1)
        self.assertEqual(rep["failures_by_kind"]["missing_provenance"], 1)

    def test_second_predictor_contract_accepts_expected_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "chai.jsonl")
            rec = _valid_record()
            rec["predictor_id"] = "chai1_complex"
            rec["signal_source"] = "chai1_pae_interaction"
            rec["label_source"] = "chai1_lrmsd_to_reference"
            rec["refolder"] = "chai1_complex"
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
            rep = run_qc(
                [path],
                require_complex_target_id=True,
                require_provenance=True,
                require_chain_ids=True,
                expect_predictor_id="chai1_complex",
                expect_signal_source="chai1_pae_interaction",
                expect_label_source="chai1_lrmsd_to_reference",
                forbid_predictor_ids=["boltz2_complex"],
            )
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["expect_predictor_id"], "chai1_complex")
        self.assertEqual(rep["forbid_predictor_ids"], ["boltz2_complex"])

    def test_second_predictor_contract_rejects_boltz_copy_and_missing_chain(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.jsonl")
            rec = _valid_record()
            rec.pop("binder_chain")
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
            rep = run_qc(
                [path],
                require_complex_target_id=True,
                require_provenance=True,
                require_chain_ids=True,
                expect_predictor_id="chai1_complex",
                expect_signal_source="chai1_pae_interaction",
                expect_label_source="chai1_lrmsd_to_reference",
                forbid_predictor_ids=["boltz2_complex"],
            )
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["missing_chain_id"], 1)
        self.assertEqual(rep["failures_by_kind"]["unexpected_predictor_id"], 1)
        self.assertEqual(rep["failures_by_kind"]["forbidden_predictor_id"], 1)
        self.assertEqual(rep["failures_by_kind"]["unexpected_signal_source"], 1)
        self.assertEqual(rep["failures_by_kind"]["unexpected_label_source"], 1)

    def test_rejects_conflicting_duplicate_and_missing_pae(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            rec = _valid_record("cx-0")
            conflict = dict(rec)
            conflict["mean_plddt"] = 91.0
            missing = _valid_record("cx-1")
            del missing["pae_interaction"]
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
                fh.write(json.dumps(conflict) + "\n")
                fh.write(json.dumps(missing) + "\n")
            rep = run_qc([path])
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["duplicate_conflict"], 1)
        self.assertEqual(rep["failures_by_kind"]["missing_field"], 1)

    def test_rejects_truth_threshold_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "records.jsonl")
            rec = _valid_record()
            rec["lrmsd"] = 8.0
            rec["truth"]["correct"] = True
            with open(path, "w") as fh:
                fh.write(json.dumps(rec) + "\n")
            rep = run_qc([path])
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["truth_mismatch"], 1)


if __name__ == "__main__":
    unittest.main()
