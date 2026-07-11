"""Static and refusal tests for the guarded W2b fit-stage entrypoint."""

import hashlib
import os
import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "hpc" / "run_w2b_fit_guarded.sh"
APPROVAL_PACKET = ROOT / "docs" / "M6D_W2B_FIT_APPROVAL.md"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class W2BFitGuardedTests(unittest.TestCase):
    def test_embedded_hashes_match_current_artifacts(self):
        text = WRAPPER.read_text()
        expected = {
            "MANIFEST": ROOT / "configs" / "m6d_w2b_target_adaptive_fit_targets.json",
            "PROTOCOL": ROOT / "configs" / "m6d_w2b_target_adaptive_exact_ltt_protocol.json",
            "INPUT_LOCK": ROOT / "configs" / "m6d_w2b_target_adaptive_fit_input_lock.json",
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

    def test_scope_and_dry_run_contract_are_explicit(self):
        text = WRAPPER.read_text()
        self.assertIn('APPROVAL_TOKEN="approve-w2b-fit-stage-480"', text)
        self.assertIn("8 targets, 480 records, and 16 Slurm jobs", text)
        self.assertIn('DRY_RUN="${BIO_SFM_SUBMIT_DRY_RUN:-0}"', text)
        self.assertIn("m6d_w2b_input_lock", text)

    def test_approval_packet_binds_guard_and_scope(self):
        text = APPROVAL_PACKET.read_text()
        self.assertIn(_sha256(WRAPPER), text)
        self.assertIn("approve-w2b-fit-stage-480", text)
        self.assertIn("480 total", text)
        self.assertIn("16 total", text)
        self.assertIn("does not extend to this stage", text)

    def test_unapproved_execution_refuses_before_receipt_creation(self):
        env = os.environ.copy()
        env.pop("BIO_SFM_APPROVE_W2B_FIT", None)
        completed = subprocess.run(
            ["bash", str(WRAPPER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("refusing W2b fit-stage submission", completed.stderr)


if __name__ == "__main__":
    unittest.main()
