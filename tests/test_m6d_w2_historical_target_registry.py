import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_historical_target_registry import (
    audit_manifest,
    build_registry,
    new_only_manifest,
)


def _write(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh)


class M6DW2HistoricalTargetRegistryTests(unittest.TestCase):
    def test_registry_uses_reports_as_evaluation_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "report.json")
            _write(manifest, {
                "defaults": {"seed": 37, "temp": 0.3, "num_seq": 100},
                "targets": [{"id": "OLD_AB", "rcsb_id": "OLD"}, {"id": "UNRUN_CD", "rcsb_id": "UNRUN"}],
            })
            _write(report, {"targets": [{"complex_target_id": "OLD_AB", "certified": False, "status": "not_certified"}]})
            registry = build_registry([report], [manifest])

        self.assertTrue(registry["audit_ok"])
        self.assertEqual(registry["evaluated_target_ids"], ["OLD_AB"])
        self.assertEqual(registry["evaluated_source_rcsb_ids"], ["OLD"])
        self.assertEqual(registry["targets"][0]["protocols"][0]["seed"], 37)

    def test_overlap_blocks_target_and_source_reuse(self):
        registry = {
            "audit_ok": True,
            "evaluated_target_ids": ["OLD_AB"],
            "evaluated_source_rcsb_ids": ["OLD"],
        }
        manifest = {
            "defaults": {"seed": 37},
            "targets": [
                {"id": "OLD_AB", "rcsb_id": "OLD"},
                {"id": "OLD_CD", "rcsb_id": "OLD"},
                {"id": "NEW_EF", "rcsb_id": "NEW"},
            ],
        }
        audit = audit_manifest(manifest, registry)
        subset = new_only_manifest(manifest, audit, "manifest.json")

        self.assertFalse(audit["audit_ok"])
        self.assertEqual(audit["historical_target_overlap"], ["OLD_AB"])
        self.assertEqual(audit["historical_source_overlap"], ["OLD"])
        self.assertEqual(audit["new_target_ids"], ["NEW_EF"])
        self.assertEqual([row["id"] for row in subset["targets"]], ["NEW_EF"])

    def test_empty_registry_fails_closed(self):
        audit = audit_manifest({"targets": [{"id": "NEW_AB", "rcsb_id": "NEW"}]}, {"audit_ok": False})
        self.assertFalse(audit["audit_ok"])
        self.assertEqual(audit["failures"][0]["kind"], "historical_registry_not_ready")


if __name__ == "__main__":
    unittest.main()
