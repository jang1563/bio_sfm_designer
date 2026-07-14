"""Tests for fail-closed W2c candidate and record metadata attachment."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2c_stage_metadata import (
    annotate_candidates,
    annotate_records,
)


_STAGE = "threshold_learning"
_NAMESPACE = "w2c-fit-learn-v1"
_TARGET = "1FR2_BA"


def _write_jsonl(path, rows):
    with open(path, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class M6DW2CStageMetadataTests(unittest.TestCase):
    def test_candidates_and_records_receive_locked_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            candidates_path = os.path.join(root, "candidates.jsonl")
            records_path = os.path.join(root, "records.jsonl")
            identifiers = [f"{_NAMESPACE}-{_TARGET}-{index}" for index in range(60)]
            _write_jsonl(candidates_path, [
                {"id": identifier, "meta": {"complex_target_id": _TARGET}}
                for identifier in identifiers
            ])
            annotate_candidates(
                candidates_path,
                stage=_STAGE,
                namespace=_NAMESPACE,
                complex_target_id=_TARGET,
                expected_count=60,
            )
            _write_jsonl(records_path, [
                {"target_id": identifier, "complex_target_id": _TARGET}
                for identifier in reversed(identifiers)
            ])
            annotate_records(
                records_path,
                candidates_path,
                stage=_STAGE,
                namespace=_NAMESPACE,
                complex_target_id=_TARGET,
                expected_count=60,
            )
            candidates = [json.loads(line) for line in open(candidates_path)]
            records = [json.loads(line) for line in open(records_path)]

        self.assertTrue(all(row["w2c_stage"] == _STAGE for row in candidates + records))
        self.assertTrue(all(row["w2c_seed_namespace"] == _NAMESPACE for row in candidates + records))
        self.assertTrue(all(row["meta"]["w2c_stage"] == _STAGE for row in candidates))

    def test_wrong_count_is_rejected_without_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "candidates.jsonl")
            _write_jsonl(path, [{"id": f"{_NAMESPACE}-{_TARGET}-0", "meta": {"complex_target_id": _TARGET}}])
            before = open(path, "rb").read()
            with self.assertRaisesRegex(ValueError, "expected 60 rows"):
                annotate_candidates(
                    path,
                    stage=_STAGE,
                    namespace=_NAMESPACE,
                    complex_target_id=_TARGET,
                    expected_count=60,
                )
            after = open(path, "rb").read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
