"""Static, refusal, and dry-run tests for guarded W2b certification."""

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "hpc" / "run_w2b_certification_guarded.sh"
APPROVAL_PACKET = ROOT / "docs" / "M6D_W2B_CERTIFICATION_APPROVAL.md"
INPUT_LOCK = ROOT / "configs" / "m6d_w2b_target_adaptive_certification_input_lock.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locked_target_inputs_available():
    lock = json.loads(INPUT_LOCK.read_text())
    paths = [
        ROOT / artifact["path"]
        for target in lock["binding"]["targets"]
        for artifact in target["artifacts"].values()
    ]
    return all(path.is_file() and path.stat().st_size > 0 for path in paths)


class W2BCertificationGuardedTests(unittest.TestCase):
    def test_embedded_hashes_match_current_artifacts(self):
        text = WRAPPER.read_text()
        expected = {
            "MANIFEST": ROOT / "configs" / "m6d_w2b_target_adaptive_certification_targets.json",
            "PROTOCOL": ROOT / "configs" / "m6d_w2b_target_adaptive_exact_ltt_protocol.json",
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

    def test_approval_packet_binds_current_guard_and_exact_scope(self):
        text = APPROVAL_PACKET.read_text()
        self.assertIn(_sha256(WRAPPER), text)
        self.assertIn("approve-w2b-certification-stage-300-h100", text)
        self.assertIn("300 total", text)
        self.assertIn("10 total", text)
        self.assertIn("does not authorize test-stage compute", text)

    def test_unapproved_execution_refuses_before_receipt_creation(self):
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
            self.assertIn("refusing W2b certification-stage submission", completed.stderr)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())

    def test_dry_run_enumerates_pairs_or_missing_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = pathlib.Path(directory) / "receipt.jsonl"
            summary = pathlib.Path(directory) / "summary.json"
            env = os.environ.copy()
            env.update({
                "BIO_SFM_PYTHON": sys.executable,
                "BIO_SFM_TRUST_CORE_SRC": str(ROOT.parent / "bio-sfm-trust-core" / "src"),
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

            if _locked_target_inputs_available():
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.count("dry-run 1F"), 5)
                self.assertEqual(completed.stdout.count("resources=preempt_gpu/low/gpu:h100:1"), 5)
                self.assertIn("5 frozen rules, no prior outputs", completed.stdout)
            else:
                self.assertEqual(completed.returncode, 2)
                self.assertIn("w2b_stage_input_lock_verification_failed", completed.stdout)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
