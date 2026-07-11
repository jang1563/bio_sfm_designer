"""Tests for the W2b target-MSA guarded entrypoint."""

import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "hpc" / "run_w2b_target_msa_guarded.sh"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class W2BTargetMsaGuardedTests(unittest.TestCase):
    def test_embedded_hashes_match_current_artifacts(self):
        text = WRAPPER.read_text()
        expected = {
            "MANIFEST": ROOT / "configs" / "m6d_w2b_target_adaptive_fit_targets.json",
            "PROTOCOL": ROOT / "configs" / "m6d_w2b_target_adaptive_exact_ltt_protocol.json",
            "PLAN": ROOT / "results" / "m6d_w2b_target_adaptive_fit_target_msas.sh",
        }
        for name, path in expected.items():
            match = re.search(rf'EXPECTED_{name}_SHA256="([0-9a-f]{{64}})"', text)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), _sha256(path))

    def test_dry_run_touches_no_receipt_or_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = pathlib.Path(tmp) / "receipt.jsonl"
            summary = pathlib.Path(tmp) / "summary.json"
            env = {
                **os.environ,
                "TARGET_MSA_PRECOMPUTE_DRY_RUN": "1",
                "W2B_TARGET_MSA_RECEIPT": str(receipt),
                "W2B_TARGET_MSA_SUMMARY": str(summary),
                "BIO_SFM_PYTHON": sys.executable,
            }
            completed = subprocess.run(
                ["bash", str(WRAPPER)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("no scheduler jobs submitted", completed.stdout)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())

    def test_unapproved_execution_refuses_before_receipt_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = pathlib.Path(tmp) / "receipt.jsonl"
            summary = pathlib.Path(tmp) / "summary.json"
            env = {
                **os.environ,
                "W2B_TARGET_MSA_RECEIPT": str(receipt),
                "W2B_TARGET_MSA_SUMMARY": str(summary),
                "BIO_SFM_PYTHON": sys.executable,
            }
            env.pop("BIO_SFM_APPROVE_W2B_TARGET_MSA", None)
            completed = subprocess.run(
                ["bash", str(WRAPPER)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("refusing W2b target-MSA submission", completed.stderr)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
