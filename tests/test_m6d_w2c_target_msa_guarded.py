"""Tests for the guarded W2c target-MSA-only boundary."""

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
SCRIPT = ROOT / "hpc/run_w2c_target_msa_guarded.sh"
APPROVAL_PACKET = ROOT / "results/m6d_w2c_target_msa_approval_packet.json"
PRE_MSA_REPORT = ROOT / "results/m6d_w2c_manifest_pre_msa.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class M6DW2CTargetMSAGuardedTests(unittest.TestCase):
    def test_public_pre_msa_report_uses_portable_manifest_path(self):
        report = json.loads(PRE_MSA_REPORT.read_text())

        self.assertEqual(report["manifest"], "configs/m6d_w2c_fresh_targets.json")
        self.assertFalse(pathlib.Path(report["manifest"]).is_absolute())

    def test_approval_packet_hashes_match_every_bound_artifact(self):
        packet = json.loads(APPROVAL_PACKET.read_text())

        for name, binding in packet["bound_artifacts"].items():
            with self.subTest(artifact=name):
                self.assertEqual(binding["sha256"], _sha256(ROOT / binding["path"]))

    def test_embedded_hashes_match_current_artifacts(self):
        text = SCRIPT.read_text()
        bindings = {
            "MANIFEST": "EXPECTED_MANIFEST_SHA256",
            "PROTOCOL": "EXPECTED_PROTOCOL_SHA256",
            "SELECTION": "EXPECTED_SELECTION_SHA256",
            "DESIGN_GATE": "EXPECTED_DESIGN_GATE_SHA256",
            "PLAN": "EXPECTED_PLAN_SHA256",
        }
        for path_var, hash_var in bindings.items():
            path_match = re.search(rf'^{path_var}="([^"]+)"$', text, re.MULTILINE)
            hash_match = re.search(rf'^{hash_var}="([0-9a-f]{{64}})"$', text, re.MULTILINE)
            self.assertIsNotNone(path_match, path_var)
            self.assertIsNotNone(hash_match, hash_var)
            self.assertEqual(hash_match.group(1), _sha256(ROOT / path_match.group(1)))

    def test_shell_syntax_and_scope_are_target_msa_only(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = SCRIPT.read_text()
        self.assertNotIn("run_proteinmpnn", text)
        self.assertNotIn("run_boltz", text)
        self.assertIn("does not authorize ProteinMPNN or Boltz", text)

    def test_dry_run_submits_nothing_and_touches_no_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = pathlib.Path(tmp) / "receipt.jsonl"
            summary = pathlib.Path(tmp) / "summary.json"
            env = {
                **os.environ,
                "TARGET_MSA_PRECOMPUTE_DRY_RUN": "1",
                "BIO_SFM_PYTHON": sys.executable,
                "W2C_TARGET_MSA_RECEIPT": str(receipt),
                "W2C_TARGET_MSA_SUMMARY": str(summary),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no scheduler jobs submitted", result.stdout)
        self.assertIn("1FR2_BA", result.stdout)
        self.assertFalse(receipt.exists())
        self.assertFalse(summary.exists())

    def test_non_dry_run_requires_exact_explicit_approval(self):
        for approval in (None, "approved", "approve-w2c-target-msa"):
            with self.subTest(approval=approval), tempfile.TemporaryDirectory() as tmp:
                receipt = pathlib.Path(tmp) / "receipt.jsonl"
                summary = pathlib.Path(tmp) / "summary.json"
                env = {
                    **os.environ,
                    "BIO_SFM_PYTHON": sys.executable,
                    "W2C_TARGET_MSA_RECEIPT": str(receipt),
                    "W2C_TARGET_MSA_SUMMARY": str(summary),
                }
                env.pop("TARGET_MSA_PRECOMPUTE_DRY_RUN", None)
                env.pop("BIO_SFM_APPROVE_W2C_TARGET_MSA", None)
                if approval is not None:
                    env["BIO_SFM_APPROVE_W2C_TARGET_MSA"] = approval
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("refusing W2c target-MSA submission", result.stderr)
                self.assertFalse(receipt.exists())
                self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
