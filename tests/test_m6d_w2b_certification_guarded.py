"""Snapshot and retirement tests for the completed W2b certification guard."""

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "hpc" / "run_w2b_certification_guarded.sh"
APPROVAL_PACKET = ROOT / "docs" / "M6D_W2B_CERTIFICATION_APPROVAL.md"
OPERATOR_APPROVAL = ROOT / "results" / "m6d_w2b_target_adaptive_certification_operator_approval.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class W2BCertificationGuardedTests(unittest.TestCase):
    def test_execution_snapshot_matches_operator_approval(self):
        text = WRAPPER.read_text()
        approval = json.loads(OPERATOR_APPROVAL.read_text())
        self.assertEqual(_sha256(WRAPPER), approval["guarded_wrapper_sha256"])
        self.assertEqual(_sha256(APPROVAL_PACKET), approval["approval_packet_sha256"])
        protocol_match = re.search(r'EXPECTED_PROTOCOL_SHA256="([0-9a-f]{64})"', text)
        self.assertIsNotNone(protocol_match)
        self.assertEqual(protocol_match.group(1), approval["protocol_sha256"])
        expected = {
            "MANIFEST": ROOT / "configs" / "m6d_w2b_target_adaptive_certification_targets.json",
            "INPUT_LOCK": ROOT / "configs" / "m6d_w2b_target_adaptive_certification_input_lock.json",
            "FIT_REPORT": ROOT / "results" / "m6d_w2b_target_adaptive_fit_report.json",
            "FIT_FIXTURE": ROOT / "tests" / "fixtures" / "m6d_w2b_target_adaptive_fit_records.jsonl",
            "LOCK_TOOL": ROOT / "src" / "bio_sfm_designer" / "experiments" / "m6d_w2b_input_lock.py",
            "SHARED_SUBMIT": ROOT / "hpc" / "m6d_w2_submit_with_receipt.sh",
            "GENERATE_WRAPPER": ROOT / "hpc" / "run_generate_proteinmpnn_complex.sbatch",
            "PREDICT_WRAPPER": ROOT / "hpc" / "run_predict_boltz_complex.sbatch",
            "GENERATOR": ROOT / "hpc" / "generate_proteinmpnn_complex.py",
            "PREDICTOR": ROOT / "hpc" / "predict_boltz_complex.py",
            "MANIFEST_TOOL": ROOT / "src" / "bio_sfm_designer" / "experiments" / "complex_target_manifest.py",
            "HISTORICAL_AUDIT_TOOL": ROOT / "src" / "bio_sfm_designer" / "experiments" / "m6d_w2_historical_target_registry.py",
            "SUBMIT_JOURNAL_TOOL": ROOT / "src" / "bio_sfm_designer" / "experiments" / "m6d_w2_submit_journal.py",
        }
        for name, path in expected.items():
            match = re.search(rf'EXPECTED_{name}_SHA256="([0-9a-f]{{64}})"', text)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), _sha256(path))

    def test_approval_packet_binds_approved_guard_and_exact_scope(self):
        text = APPROVAL_PACKET.read_text()
        approval = json.loads(OPERATOR_APPROVAL.read_text())
        self.assertIn(approval["guarded_wrapper_sha256"], text)
        self.assertIn("approve-w2b-certification-stage-300-h100", text)
        self.assertIn("300 total", text)
        self.assertIn("10 total", text)
        self.assertIn("does not authorize test-stage compute", text)

    def test_completed_guard_is_retired_before_new_receipt_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = pathlib.Path(directory) / "receipt.jsonl"
            summary = pathlib.Path(directory) / "summary.json"
            env = os.environ.copy()
            env.pop("BIO_SFM_APPROVE_W2B_CERTIFICATION", None)
            env.update({
                "W2B_CERTIFICATION_RECEIPT": str(receipt),
                "W2B_CERTIFICATION_SUMMARY": str(summary),
            })
            completed = subprocess.run(
                ["bash", str(WRAPPER)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("stale W2b certification artifact", completed.stderr)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())

    def test_completed_guard_dry_run_also_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = pathlib.Path(directory) / "receipt.jsonl"
            summary = pathlib.Path(directory) / "summary.json"
            env = os.environ.copy()
            env.update({
                "BIO_SFM_SUBMIT_DRY_RUN": "1",
                "W2B_CERTIFICATION_RECEIPT": str(receipt),
                "W2B_CERTIFICATION_SUMMARY": str(summary),
            })
            completed = subprocess.run(
                ["bash", str(WRAPPER)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("stale W2b certification artifact", completed.stderr)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
