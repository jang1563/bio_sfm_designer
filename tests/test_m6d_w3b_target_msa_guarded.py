"""Tests for the hash-bound W3b target-MSA-only approval boundary."""

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
SCRIPT = ROOT / "hpc/run_w3b_target_msa_guarded.sh"
PACKET = ROOT / "results/m6d_w3b_target_msa_approval_packet.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class M6DW3BTargetMSAGuardedTests(unittest.TestCase):
    def test_approval_packet_is_ready_but_no_submit(self):
        packet = json.loads(PACKET.read_text())

        self.assertEqual(packet["status"], "awaiting_explicit_w3b_target_msa_approval")
        self.assertTrue(packet["approval_packet_ready"])
        self.assertTrue(packet["no_submit"])
        self.assertTrue(packet["explicit_approval_required"])
        self.assertTrue(packet["can_submit_target_msa_if_explicitly_approved"])
        self.assertFalse(packet["can_submit_candidate_generation_or_candidate_level_prediction"])
        self.assertEqual(packet["target_count"], 8)
        self.assertEqual(len(packet["missing_target_msa_targets"]), 8)
        self.assertEqual(packet["maximum_a40_gpu_hours"], 8.0)
        self.assertEqual(packet["failures"], [])

    def test_packet_and_wrapper_hashes_match_all_bound_artifacts(self):
        packet = json.loads(PACKET.read_text())
        text = SCRIPT.read_text()
        for name, binding in packet["bound_artifacts"].items():
            with self.subTest(artifact=name):
                self.assertEqual(binding["sha256"], _sha256(ROOT / binding["path"]))
                marker = re.search(
                    rf'^EXPECTED_{name.upper()}_SHA256="([0-9a-f]{{64}})"$',
                    text,
                    re.MULTILINE,
                )
                self.assertIsNotNone(marker)
                self.assertEqual(marker.group(1), binding["sha256"])
        self.assertEqual(packet["wrapper"]["sha256"], _sha256(SCRIPT))

    def test_shell_syntax_and_scope_are_msa_only(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        text = SCRIPT.read_text()
        self.assertIn("eight target-MSA jobs only", text)
        self.assertIn("candidate-level Boltz/AF2 prediction", text)
        self.assertNotIn("generate_proteinmpnn", text)
        self.assertNotIn("run_predict_boltz", text)
        self.assertNotIn("colabfold_batch", text)

    def test_dry_run_submits_nothing_and_creates_no_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = pathlib.Path(tmp) / "receipt.jsonl"
            summary = pathlib.Path(tmp) / "summary.json"
            env = {
                **os.environ,
                "BIO_SFM_PYTHON": sys.executable,
                "TARGET_MSA_PRECOMPUTE_DRY_RUN": "1",
                "W3B_TARGET_MSA_RECEIPT": str(receipt),
                "W3B_TARGET_MSA_SUMMARY": str(summary),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no scheduler jobs submitted", result.stdout)
            self.assertIn("1FSK_LJ", result.stdout)
            self.assertIn("1F3V_BA", result.stdout)
            self.assertFalse(receipt.exists())
            self.assertFalse(summary.exists())

    def test_non_dry_run_refuses_without_exact_approval(self):
        for approval in (None, "approved", "approve-w3b-target-msa"):
            with self.subTest(approval=approval), tempfile.TemporaryDirectory() as tmp:
                receipt = pathlib.Path(tmp) / "receipt.jsonl"
                summary = pathlib.Path(tmp) / "summary.json"
                env = {
                    **os.environ,
                    "BIO_SFM_PYTHON": sys.executable,
                    "W3B_TARGET_MSA_RECEIPT": str(receipt),
                    "W3B_TARGET_MSA_SUMMARY": str(summary),
                }
                env.pop("TARGET_MSA_PRECOMPUTE_DRY_RUN", None)
                env.pop("BIO_SFM_APPROVE_W3B_TARGET_MSA", None)
                if approval is not None:
                    env["BIO_SFM_APPROVE_W3B_TARGET_MSA"] = approval
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                )

                self.assertEqual(result.returncode, 64)
                self.assertIn("refusing W3b target-MSA submission", result.stderr)
                self.assertFalse(receipt.exists())
                self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
