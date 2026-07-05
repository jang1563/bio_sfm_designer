"""Cross-predictor bridge tests for closing the M6c single-model caveat."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_cross_predictor import run_cross_predictor, write_match_rows

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


def _rec(i, predictor, correct=True, pae=2.0, lrmsd=1.0, threshold=4.0, provenance=True,
         complex_target_id="toy", target_id=None):
    signal_source = predictor if provenance else None
    label_source = predictor if provenance else None
    return {
        "target_id": target_id or f"design-{i}",
        "complex_target_id": complex_target_id,
        "predictor_id": predictor,
        "signal_source": signal_source,
        "label_source": label_source,
        "regime": "complex",
        "mean_plddt": 90.0,
        "pae_interaction": pae,
        "lrmsd": lrmsd,
        "lrmsd_threshold": threshold,
        "truth": {"correct": correct, "quality": 0.8 if correct else 0.2},
        "interface_aligned": True,
        "refolder": predictor,
    }


class ComplexCrossPredictorTests(unittest.TestCase):
    def test_fixture_alone_keeps_single_model_caveat_open(self):
        rep = run_cross_predictor([FIXTURE], min_overlap=5)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "single_model_caveat_open")
        self.assertEqual(rep["failures"][0]["kind"], "too_few_predictors")

    def test_bad_min_overlap_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "min_overlap"):
            run_cross_predictor([FIXTURE], min_overlap=0)

    def test_two_predictor_overlap_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.jsonl")
            b = os.path.join(d, "b.jsonl")
            with open(a, "w") as fa, open(b, "w") as fb:
                for i in range(6):
                    correct = i % 3 != 0
                    fa.write(json.dumps(_rec(i, "boltz2_complex", correct=correct,
                                             pae=2.0 + i, lrmsd=1.0 if correct else 8.0)) + "\n")
                    fb.write(json.dumps(_rec(i, "chai1_complex", correct=correct,
                                             pae=2.2 + i, lrmsd=1.2 if correct else 7.5)) + "\n")
            rep = run_cross_predictor([a, b], min_overlap=5, match_preview=2)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["status"], "cross_predictor_ready")
        self.assertEqual(rep["pairs"][0]["n_overlap"], 6)
        self.assertEqual(rep["n_match_rows"], 6)
        self.assertEqual(len(rep["match_preview"]), 2)
        self.assertEqual(rep["match_preview"][0]["predictor_a"], "boltz2_complex")
        self.assertEqual(rep["match_preview"][0]["predictor_b"], "chai1_complex")
        self.assertTrue(rep["match_preview"][0]["label_agrees"])
        self.assertEqual(rep["pairs"][0]["n_labeled_overlap"], 6)
        self.assertEqual(rep["pairs"][0]["label_agreement"], 1.0)
        self.assertTrue(rep["pairs"][0]["provenance_complete"])
        self.assertTrue(rep["pairs"][0]["complex_target_id_complete"])
        self.assertTrue(rep["pairs"][0]["complex_target_id_agree"])
        self.assertTrue(rep["pairs"][0]["label_threshold_complete"])
        self.assertTrue(rep["pairs"][0]["label_threshold_agree"])
        self.assertEqual(rep["pairs"][0]["label_threshold_values"], [4.0])
        self.assertTrue(rep["pairs"][0]["distinct_signal_sources"])
        self.assertTrue(rep["pairs"][0]["distinct_label_sources"])
        self.assertGreater(rep["pairs"][0]["pae_interaction_pearson"], 0.99)
        self.assertEqual(rep["record_files"][0]["predictors"], ["boltz2_complex"])
        self.assertEqual(rep["record_files"][1]["predictors"], ["chai1_complex"])

    def test_mixed_record_file_is_reported_but_not_blocked_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mixed.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    correct = i % 3 != 0
                    fh.write(json.dumps(_rec(i, "boltz2_complex", correct=correct,
                                             pae=2.0 + i, lrmsd=1.0 if correct else 8.0)) + "\n")
                    fh.write(json.dumps(_rec(i, "chai1_complex", correct=correct,
                                             pae=2.2 + i, lrmsd=1.2 if correct else 7.5)) + "\n")
            rep = run_cross_predictor([path], min_overlap=5)

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["record_files"][0]["path"], path)
        self.assertEqual(rep["record_files"][0]["predictors"], ["boltz2_complex", "chai1_complex"])
        self.assertEqual(rep["record_files"][0]["records_by_predictor"]["boltz2_complex"], 6)
        self.assertEqual(rep["record_files"][0]["records_by_predictor"]["chai1_complex"], 6)

    def test_require_disjoint_record_files_blocks_mixed_predictor_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mixed.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    correct = i % 3 != 0
                    fh.write(json.dumps(_rec(i, "boltz2_complex", correct=correct,
                                             pae=2.0 + i, lrmsd=1.0 if correct else 8.0)) + "\n")
                    fh.write(json.dumps(_rec(i, "chai1_complex", correct=correct,
                                             pae=2.2 + i, lrmsd=1.2 if correct else 7.5)) + "\n")
            rep = run_cross_predictor([path], min_overlap=5, require_disjoint_record_files=True)

        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("mixed_predictor_record_file", kinds)
        self.assertEqual(rep["record_files"][0]["predictors"], ["boltz2_complex", "chai1_complex"])

    def test_label_threshold_mismatch_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "threshold_mismatch.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    fh.write(json.dumps(_rec(i, "boltz2_complex", correct=True,
                                             lrmsd=1.0, threshold=4.0)) + "\n")
                    fh.write(json.dumps(_rec(i, "chai1_complex", correct=True,
                                             lrmsd=1.0, threshold=5.0)) + "\n")
            rep = run_cross_predictor([path], min_overlap=5, match_preview=1)

        self.assertFalse(rep["ok"])
        self.assertIn("label_threshold_mismatch", {f["kind"] for f in rep["failures"]})
        self.assertEqual(rep["pairs"][0]["label_agreement"], 1.0)
        self.assertTrue(rep["pairs"][0]["label_threshold_complete"])
        self.assertFalse(rep["pairs"][0]["label_threshold_agree"])
        self.assertEqual(rep["pairs"][0]["label_threshold_values"], [4.0, 5.0])
        self.assertEqual(rep["match_preview"][0]["lrmsd_threshold_a"], 4.0)
        self.assertEqual(rep["match_preview"][0]["lrmsd_threshold_b"], 5.0)
        self.assertFalse(rep["match_preview"][0]["label_threshold_agrees"])

    def test_same_design_id_can_repeat_across_complex_targets(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "multi_target.jsonl")
            with open(path, "w") as fh:
                for complex_target_id in ("target_a", "target_b"):
                    fh.write(json.dumps(_rec(0, "boltz2_complex",
                                             complex_target_id=complex_target_id,
                                             target_id="design-0")) + "\n")
                    fh.write(json.dumps(_rec(0, "chai1_complex", pae=2.5, lrmsd=1.2,
                                             complex_target_id=complex_target_id,
                                             target_id="design-0")) + "\n")
            rep = run_cross_predictor([path], min_overlap=2)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["pairs"][0]["n_overlap"], 2)
        self.assertEqual(rep["n_match_rows"], 2)

    def test_missing_complex_target_id_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "missing_complex_id.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    a = _rec(i, "boltz2_complex")
                    b = _rec(i, "chai1_complex")
                    a.pop("complex_target_id")
                    b.pop("complex_target_id")
                    fh.write(json.dumps(a) + "\n")
                    fh.write(json.dumps(b) + "\n")
            rep = run_cross_predictor([path], min_overlap=5)
        self.assertFalse(rep["ok"])
        self.assertIn("weak_target_identity", {f["kind"] for f in rep["failures"]})
        self.assertFalse(rep["pairs"][0]["complex_target_id_complete"])

    def test_label_disagreement_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.jsonl")
            b = os.path.join(d, "b.jsonl")
            with open(a, "w") as fa, open(b, "w") as fb:
                for i in range(6):
                    fa.write(json.dumps(_rec(i, "boltz2_complex", correct=True)) + "\n")
                    fb.write(json.dumps(_rec(i, "chai1_complex", correct=(i == 0))) + "\n")
            rep = run_cross_predictor([a, b], min_overlap=5, min_label_agreement=0.8)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "single_model_caveat_open")
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("label_agreement_below_min", kinds)
        self.assertLess(rep["pairs"][0]["label_agreement"], 0.8)

    def test_missing_or_copied_provenance_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "missing.jsonl")
            copied = os.path.join(d, "copied.jsonl")
            with open(missing, "w") as fh:
                for i in range(6):
                    fh.write(json.dumps(_rec(i, "boltz2_complex", provenance=False)) + "\n")
                    fh.write(json.dumps(_rec(i, "chai1_complex", provenance=False)) + "\n")
            rep_missing = run_cross_predictor([missing], min_overlap=5)
            self.assertFalse(rep_missing["ok"])
            self.assertIn("weak_predictor_provenance", {f["kind"] for f in rep_missing["failures"]})

            with open(copied, "w") as fh:
                for i in range(6):
                    a = _rec(i, "boltz2_complex")
                    b = _rec(i, "chai1_complex")
                    b["label_source"] = "boltz2_complex"
                    fh.write(json.dumps(a) + "\n")
                    fh.write(json.dumps(b) + "\n")
            rep_copied = run_cross_predictor([copied], min_overlap=5)
        self.assertFalse(rep_copied["ok"])
        self.assertIn("weak_predictor_provenance", {f["kind"] for f in rep_copied["failures"]})
        self.assertFalse(rep_copied["pairs"][0]["distinct_label_sources"])

    def test_exact_numeric_copy_under_new_predictor_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "numeric_copy.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    correct = i % 2 == 0
                    primary = _rec(i, "boltz2_complex", correct=correct,
                                   pae=2.0 + i, lrmsd=1.0 if correct else 8.0)
                    copied = dict(primary)
                    copied["predictor_id"] = "chai1_complex"
                    copied["refolder"] = "chai1_complex"
                    copied["signal_source"] = "chai1_pae_interaction"
                    copied["label_source"] = "chai1_lrmsd_to_reference"
                    fh.write(json.dumps(primary) + "\n")
                    fh.write(json.dumps(copied) + "\n")
            rep = run_cross_predictor([path], min_overlap=5)

        self.assertFalse(rep["ok"])
        self.assertIn("copied_predictor_values", {f["kind"] for f in rep["failures"]})
        self.assertTrue(rep["pairs"][0]["distinct_signal_sources"])
        self.assertTrue(rep["pairs"][0]["distinct_label_sources"])
        self.assertTrue(rep["pairs"][0]["pae_interaction_exact_match"])
        self.assertTrue(rep["pairs"][0]["lrmsd_exact_match"])
        self.assertTrue(rep["pairs"][0]["copied_numeric_values"])

    def test_near_numeric_copy_under_new_predictor_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "near_numeric_copy.jsonl")
            with open(path, "w") as fh:
                for i in range(6):
                    correct = i % 2 == 0
                    pae = 2.0 + i
                    lrmsd = 1.0 if correct else 8.0
                    primary = _rec(i, "boltz2_complex", correct=correct,
                                   pae=pae, lrmsd=lrmsd)
                    copied = dict(primary)
                    copied["predictor_id"] = "chai1_complex"
                    copied["refolder"] = "chai1_complex"
                    copied["signal_source"] = "chai1_pae_interaction"
                    copied["label_source"] = "chai1_lrmsd_to_reference"
                    copied["pae_interaction"] = pae + 1e-7
                    copied["lrmsd"] = lrmsd - 1e-7
                    fh.write(json.dumps(primary) + "\n")
                    fh.write(json.dumps(copied) + "\n")
            rep = run_cross_predictor([path], min_overlap=5, copy_tolerance=1e-6)

        self.assertFalse(rep["ok"])
        self.assertIn("copied_predictor_values", {f["kind"] for f in rep["failures"]})
        self.assertFalse(rep["pairs"][0]["pae_interaction_exact_match"])
        self.assertFalse(rep["pairs"][0]["lrmsd_exact_match"])
        self.assertTrue(rep["pairs"][0]["pae_interaction_near_match"])
        self.assertTrue(rep["pairs"][0]["lrmsd_near_match"])
        self.assertTrue(rep["pairs"][0]["copied_numeric_values"])

    def test_mostly_near_numeric_copy_keeps_caveat_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mostly_near_numeric_copy.jsonl")
            with open(path, "w") as fh:
                for i in range(20):
                    correct = i % 2 == 0
                    pae = 2.0 + i
                    lrmsd = 1.0 if correct else 8.0
                    primary = _rec(i, "boltz2_complex", correct=correct,
                                   pae=pae, lrmsd=lrmsd)
                    copied = dict(primary)
                    copied["predictor_id"] = "chai1_complex"
                    copied["refolder"] = "chai1_complex"
                    copied["signal_source"] = "chai1_pae_interaction"
                    copied["label_source"] = "chai1_lrmsd_to_reference"
                    if i == 19:
                        copied["pae_interaction"] = pae + 0.5
                        copied["lrmsd"] = lrmsd + 0.5
                    else:
                        copied["pae_interaction"] = pae + 1e-7
                        copied["lrmsd"] = lrmsd - 1e-7
                    fh.write(json.dumps(primary) + "\n")
                    fh.write(json.dumps(copied) + "\n")
            rep = run_cross_predictor([path], min_overlap=20, copy_tolerance=1e-6,
                                      copy_fraction_threshold=0.95)

        self.assertFalse(rep["ok"])
        self.assertIn("copied_predictor_values", {f["kind"] for f in rep["failures"]})
        self.assertFalse(rep["pairs"][0]["pae_interaction_near_match"])
        self.assertFalse(rep["pairs"][0]["lrmsd_near_match"])
        self.assertEqual(rep["pairs"][0]["n_numeric_copy_pairs"], 19)
        self.assertEqual(rep["pairs"][0]["numeric_copy_fraction"], 0.95)
        self.assertTrue(rep["pairs"][0]["copied_numeric_values"])

    def test_match_rows_can_be_written_for_mismatch_triage(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.jsonl")
            b = os.path.join(d, "b.jsonl")
            out = os.path.join(d, "matches.jsonl")
            with open(a, "w") as fa, open(b, "w") as fb:
                for i in range(3):
                    fa.write(json.dumps(_rec(i, "boltz2_complex", correct=True,
                                             pae=1.0 + i, lrmsd=1.0)) + "\n")
                    fb.write(json.dumps(_rec(i, "chai1_complex", correct=(i != 1),
                                             pae=2.0 + i, lrmsd=1.2 if i != 1 else 8.0)) + "\n")
            rep = run_cross_predictor([a, b], min_overlap=3, min_label_agreement=0.5,
                                      match_preview=10)
            write_match_rows(out, rep["match_preview"])

            with open(out) as fh:
                rows = [json.loads(line) for line in fh]
        self.assertEqual(len(rows), 3)
        disagree = [row for row in rows if row["label_agrees"] is False]
        self.assertEqual(len(disagree), 1)
        self.assertEqual(disagree[0]["target_id"], "design-1")
        self.assertEqual(disagree[0]["label_source_a"], "boltz2_complex")
        self.assertEqual(disagree[0]["label_source_b"], "chai1_complex")
        self.assertEqual(disagree[0]["lrmsd_threshold_a"], 4.0)
        self.assertEqual(disagree[0]["lrmsd_threshold_b"], 4.0)
        self.assertTrue(disagree[0]["label_threshold_agrees"])

    def test_same_target_duplicate_for_one_predictor_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dup.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(_rec(0, "boltz2_complex")) + "\n")
                fh.write(json.dumps(_rec(0, "boltz2_complex")) + "\n")
            rep = run_cross_predictor([path], min_overlap=1)
        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("duplicate_predictor_target", kinds)


if __name__ == "__main__":
    unittest.main()
