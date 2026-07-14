"""Tests for the guarded W2c threshold-learning no-submit boundary."""

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
SCRIPT = ROOT / "hpc/run_w2c_fit_learn_guarded.sh"
LOCK = ROOT / "configs/m6d_w2c_fit_learn_input_lock.json"
PACKET = ROOT / "results/m6d_w2c_fit_learn_approval_packet.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class M6DW2CFitLearnGuardedTests(unittest.TestCase):
    @unittest.skipUnless(PACKET.exists(), "requires the ignored local operational packet")
    def test_approval_packet_is_hash_bound_and_no_submit(self):
        packet = json.loads(PACKET.read_text())
        approval = packet["approval"]
        scope = packet["scope"]

        self.assertEqual(
            packet["status"],
            "ready_for_explicit_w2c_fit_learn_approval_not_submitted",
        )
        self.assertTrue(packet["audit_ok"])
        self.assertFalse(packet["packet_preparation_approval"]["record_generation_approved"])
        self.assertFalse(approval["submission_performed"])
        self.assertTrue(approval["explicit_user_approval_required"])
        self.assertEqual(
            approval["required_user_phrase"],
            "approve W2c threshold-learning 480-record generation on H100",
        )
        self.assertEqual(
            approval["environment_value"],
            "approve-w2c-fit-learn-480-h100",
        )
        self.assertEqual(scope["n_targets"], 8)
        self.assertEqual(scope["records_per_target"], 60)
        self.assertEqual(scope["total_records"], 480)
        self.assertEqual(scope["total_slurm_jobs"], 16)
        self.assertFalse(scope["authorizes_record_generation"])
        self.assertFalse(scope["authorizes_independent_screen"])
        self.assertFalse(scope["authorizes_certification"])

        bindings = packet["bound_artifacts"]
        self.assertEqual(len(bindings), 19)
        for name, binding in bindings.items():
            with self.subTest(name=name):
                self.assertEqual(binding["sha256"], _sha256(ROOT / binding["path"]))

    def test_embedded_hashes_match_bound_artifacts(self):
        text = SCRIPT.read_text()
        bindings = {
            "PROTOCOL": "EXPECTED_PROTOCOL_SHA256",
            "SOURCE_MANIFEST": "EXPECTED_SOURCE_MANIFEST_SHA256",
            "STAGE_MANIFEST": "EXPECTED_STAGE_MANIFEST_SHA256",
            "INPUT_LOCK": "EXPECTED_INPUT_LOCK_SHA256",
            "MSA_COMPLETION": "EXPECTED_MSA_COMPLETION_SHA256",
            "SELECTION": "EXPECTED_SELECTION_SHA256",
            "DESIGN_GATE": "EXPECTED_DESIGN_GATE_SHA256",
            "POST_MSA_REPORT": "EXPECTED_POST_MSA_REPORT_SHA256",
            "LOCK_TOOL": "EXPECTED_LOCK_TOOL_SHA256",
            "METADATA_TOOL": "EXPECTED_METADATA_TOOL_SHA256",
            "SUBMIT_BRIDGE": "EXPECTED_SUBMIT_BRIDGE_SHA256",
            "GENERATE_WRAPPER": "EXPECTED_GENERATE_WRAPPER_SHA256",
            "PREDICT_WRAPPER": "EXPECTED_PREDICT_WRAPPER_SHA256",
            "GENERATOR": "EXPECTED_GENERATOR_SHA256",
            "PREDICTOR": "EXPECTED_PREDICTOR_SHA256",
            "MANIFEST_TOOL": "EXPECTED_MANIFEST_TOOL_SHA256",
            "HISTORICAL_AUDIT_TOOL": "EXPECTED_HISTORICAL_AUDIT_TOOL_SHA256",
            "SUBMIT_JOURNAL_TOOL": "EXPECTED_SUBMIT_JOURNAL_TOOL_SHA256",
        }
        for path_var, hash_var in bindings.items():
            with self.subTest(path_var=path_var):
                path_match = re.search(rf'^{path_var}="([^"]+)"$', text, re.MULTILINE)
                hash_match = re.search(rf'^{hash_var}="([0-9a-f]{{64}})"$', text, re.MULTILINE)
                self.assertIsNotNone(path_match)
                self.assertIsNotNone(hash_match)
                self.assertEqual(hash_match.group(1), _sha256(ROOT / path_match.group(1)))
        digest = json.loads(LOCK.read_text())["lock_digest_sha256"]
        self.assertIn(f'EXPECTED_INPUT_LOCK_DIGEST="{digest}"', text)

    def test_shell_syntax_and_scope(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = SCRIPT.read_text()
        self.assertIn("approve-w2c-fit-learn-480-h100", text)
        self.assertIn("would not authorize independent-screen or certification", text)

    def test_dry_run_enumerates_eight_pairs_without_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = pathlib.Path(root) / "receipt.jsonl"
            summary = pathlib.Path(root) / "summary.json"
            env = {
                **os.environ,
                "BIO_SFM_SUBMIT_DRY_RUN": "1",
                "BIO_SFM_PYTHON": "python3",
                "W2C_FIT_LEARN_RECEIPT": str(receipt),
                "W2C_FIT_LEARN_SUMMARY": str(summary),
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
        self.assertEqual(len(re.findall(r"^dry-run [A-Z0-9]+_[A-Z]+:", result.stdout, re.MULTILINE)), 8)
        self.assertIn("480 planned records, zero scheduler jobs submitted", result.stdout)
        self.assertFalse(receipt.exists())
        self.assertFalse(summary.exists())

    def test_non_dry_run_requires_separate_exact_approval(self):
        for approval in (None, "approved", "approve-w2c-fit-learn-480"):
            with self.subTest(approval=approval), tempfile.TemporaryDirectory() as root:
                receipt = pathlib.Path(root) / "receipt.jsonl"
                summary = pathlib.Path(root) / "summary.json"
                env = {
                    **os.environ,
                    "BIO_SFM_PYTHON": sys.executable,
                    "W2C_FIT_LEARN_RECEIPT": str(receipt),
                    "W2C_FIT_LEARN_SUMMARY": str(summary),
                }
                env.pop("BIO_SFM_SUBMIT_DRY_RUN", None)
                env.pop("BIO_SFM_APPROVE_W2C_FIT_LEARN", None)
                if approval is not None:
                    env["BIO_SFM_APPROVE_W2C_FIT_LEARN"] = approval
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("refusing W2c threshold-learning submission", result.stderr)
                self.assertFalse(receipt.exists())
                self.assertFalse(summary.exists())


if __name__ == "__main__":
    unittest.main()
