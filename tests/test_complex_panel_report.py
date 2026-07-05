"""Panel-report tests for multi-target M6c validation."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_panel_report import run_panel

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


def _record(complex_target_id, i, *, predictor="boltz2_complex",
            signal_source="boltz2_pae_interaction",
            label_source="boltz2_lrmsd_to_reference"):
    return {
        "target_id": f"{complex_target_id}-design-{i}",
        "complex_target_id": complex_target_id,
        "predictor_id": predictor,
        "signal_source": signal_source,
        "label_source": label_source,
        "regime": "complex",
        "mean_plddt": 95.0,
        "pae_interaction": 1.0 + i / 100.0,
        "iptm": 0.9,
        "ptm": 0.9,
        "lrmsd": 1.0,
        "lrmsd_threshold": 4.0,
        "truth": {"correct": True, "quality": 0.9},
        "interface_aligned": True,
        "target_chain": "A",
        "binder_chain": "B",
        "refolder": predictor,
    }


class ComplexPanelReportTests(unittest.TestCase):
    def test_fixture_single_target_is_not_multitarget_evidence(self):
        rep = run_panel([FIXTURE], min_targets=3, min_records_per_target=5, target_alpha=0.2)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["panel_status"], "not_multi_target_proof")
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("too_few_targets", kinds)
        self.assertIn("target_not_certified", kinds)
        self.assertEqual(rep["missing_complex_target_id"], 0)
        self.assertEqual(rep["n_targets"], 1)

    def test_three_target_synthetic_panel_is_evaluable_but_not_a_pooled_claim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "panel.jsonl")
            with open(path, "w") as fh:
                for tid in ("t0", "t1", "t2"):
                    for i in range(5):
                        fh.write(json.dumps(_record(tid, i)) + "\n")
            rep = run_panel([path], min_targets=3, min_records_per_target=5, target_alpha=0.99)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["panel_status"], "multi_target_evaluable_not_certified")
        self.assertEqual(rep["n_targets"], 3)
        self.assertEqual(rep["missing_complex_target_id"], 0)
        self.assertEqual(rep["predictors"], ["boltz2_complex"])
        self.assertEqual(rep["signal_sources"], ["boltz2_pae_interaction"])
        self.assertEqual(rep["label_sources"], ["boltz2_lrmsd_to_reference"])
        self.assertEqual(rep["failures"], [{"kind": "target_not_certified",
                                             "targets": ["t0", "t1", "t2"]}])

    def test_too_few_records_per_target_blocks_claim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "panel.jsonl")
            with open(path, "w") as fh:
                for tid in ("t0", "t1", "t2"):
                    fh.write(json.dumps(_record(tid, 0)) + "\n")
            rep = run_panel([path], min_targets=3, min_records_per_target=5, target_alpha=0.99)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures"][0]["kind"], "too_few_records_per_target")

    def test_mixed_predictors_are_not_panel_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "panel.jsonl")
            with open(path, "w") as fh:
                for tid in ("t0", "t1", "t2"):
                    for i in range(5):
                        predictor = "boltz2_complex" if i % 2 == 0 else "chai1_complex"
                        fh.write(json.dumps(_record(
                            tid,
                            i,
                            predictor=predictor,
                            signal_source=f"{predictor}_interface_signal",
                            label_source=f"{predictor}_lrmsd_to_reference",
                        )) + "\n")
            rep = run_panel([path], min_targets=3, min_records_per_target=5, target_alpha=0.99)
        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("mixed_or_missing_predictor_id", kinds)
        self.assertIn("mixed_or_missing_signal_source", kinds)
        self.assertIn("mixed_or_missing_label_source", kinds)

    def test_missing_signal_or_label_source_blocks_panel_claim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "panel.jsonl")
            with open(path, "w") as fh:
                for tid in ("t0", "t1", "t2"):
                    for i in range(5):
                        rec = _record(tid, i)
                        rec.pop("signal_source")
                        rec.pop("label_source")
                        fh.write(json.dumps(rec) + "\n")
            rep = run_panel([path], min_targets=3, min_records_per_target=5, target_alpha=0.99)
        self.assertFalse(rep["ok"])
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("mixed_or_missing_signal_source", kinds)
        self.assertIn("mixed_or_missing_label_source", kinds)

    def test_label_threshold_mismatch_blocks_panel_claim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "panel.jsonl")
            with open(path, "w") as fh:
                for tid in ("t0", "t1", "t2"):
                    for i in range(5):
                        rec = _record(tid, i)
                        if tid == "t1":
                            rec["lrmsd_threshold"] = 5.0
                        fh.write(json.dumps(rec) + "\n")
            rep = run_panel([path], min_targets=3, min_records_per_target=5,
                            target_alpha=0.99, threshold=4.0)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["panel_status"], "not_multi_target_proof")
        self.assertFalse(rep["label_threshold_audit"]["ok"])
        self.assertEqual(rep["label_threshold_audit"]["expected_threshold"], 4.0)
        self.assertEqual(rep["label_threshold_audit"]["record_thresholds"], [4.0, 5.0])
        self.assertEqual(rep["pooled_diagnostic"]["status"], "skipped_label_threshold_mismatch")
        kinds = {f["kind"] for f in rep["failures"]}
        self.assertIn("label_threshold_mismatch", kinds)


if __name__ == "__main__":
    unittest.main()
