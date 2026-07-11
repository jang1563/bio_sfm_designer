"""Tests for the append-only, resumable W2 submit journal."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_submit_journal import (
    append_event,
    build_summary,
    load_events,
    target_state,
    write_summary,
)


def _event(stage, *, gen="100", pred=None):
    return {
        "artifact": "submit_record",
        "stage": stage,
        "status": stage,
        "workstream": "w2",
        "target_id": "t0",
        "proteinmpnn_job_id": gen,
        "boltz_job_id": pred,
        "candidates": "out/t0/candidates.jsonl",
        "records": "out/t0/records.jsonl",
        "target_msa": "targets/t0.a3m",
        "prepared_pdb": "targets/t0.pdb",
        "manifest": "targets.json",
    }


class M6DW2SubmitJournalTests(unittest.TestCase):
    def test_submit_script_propagates_w2b_stage_contract(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        script = os.path.join(repo_root, "hpc", "m6d_w2_submit_with_receipt.sh")
        with open(script) as handle:
            text = handle.read()
        self.assertIn("W2B_STAGE", text)
        self.assertIn("W2B_SEED_NAMESPACE", text)
        self.assertIn("ID_PREFIX", text)
        self.assertIn("BIO_SFM_PREDICT_SBATCH_PARTITION", text)
        self.assertIn("submit_predictor_job", text)

    def test_partial_stage_is_immediately_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = os.path.join(directory, "receipt.jsonl")
            append_event(receipt, _event("proteinmpnn_submitted"))
            state = target_state(load_events(receipt), "t0", workstream="w2")

        self.assertEqual(state["stage"], "proteinmpnn_submitted")
        self.assertEqual(state["proteinmpnn_job_id"], "100")
        self.assertIsNone(state["boltz_job_id"])

    def test_pair_completion_reuses_recorded_proteinmpnn_job(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = os.path.join(directory, "receipt.jsonl")
            append_event(receipt, _event("proteinmpnn_submitted"))
            append_event(receipt, _event("pair_submitted", pred="101"))
            state = target_state(load_events(receipt), "t0", workstream="w2")

        self.assertEqual(state["stage"], "pair_submitted")
        self.assertEqual(state["proteinmpnn_job_id"], "100")
        self.assertEqual(state["boltz_job_id"], "101")

    def test_idempotent_append_does_not_duplicate_events(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = os.path.join(directory, "receipt.jsonl")
            append_event(receipt, _event("proteinmpnn_submitted"))
            append_event(receipt, _event("proteinmpnn_submitted"))
            self.assertEqual(len(load_events(receipt)), 1)

    def test_conflicting_resume_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = os.path.join(directory, "receipt.jsonl")
            append_event(receipt, _event("proteinmpnn_submitted"))
            with self.assertRaisesRegex(ValueError, "different ProteinMPNN"):
                append_event(receipt, _event("proteinmpnn_submitted", gen="999"))

    def test_summary_requires_every_target_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "targets.json")
            receipt = os.path.join(directory, "receipt.jsonl")
            with open(manifest, "w") as handle:
                json.dump({
                    "targets": [{
                        "id": "t0",
                        "prepared_pdb": "targets/t0.pdb",
                        "target_msa": "targets/t0.a3m",
                        "out_prefix": "out/t0",
                        "candidates": "out/t0/candidates.jsonl",
                        "records": "out/t0/records.jsonl",
                    }],
                }, handle)
            append_event(receipt, _event("proteinmpnn_submitted"))
            with self.assertRaisesRegex(ValueError, "incomplete targets"):
                build_summary(manifest, receipt, workstream="w2", artifact="summary")

    def test_summary_is_atomic_and_journal_aware(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "targets.json")
            receipt = os.path.join(directory, "receipt.jsonl")
            out = os.path.join(directory, "summary.json")
            with open(manifest, "w") as handle:
                json.dump({
                    "targets": [{
                        "id": "t0",
                        "prepared_pdb": "targets/t0.pdb",
                        "target_msa": "targets/t0.a3m",
                        "out_prefix": "out/t0",
                        "candidates": "out/t0/candidates.jsonl",
                        "records": "out/t0/records.jsonl",
                    }],
                }, handle)
            append_event(receipt, _event("proteinmpnn_submitted"))
            append_event(receipt, _event("pair_submitted", pred="101"))
            summary = build_summary(manifest, receipt, workstream="w2", artifact="summary")
            write_summary(out, summary)
            with open(out) as handle:
                loaded = json.load(handle)

        self.assertEqual(loaded["n_targets"], 1)
        self.assertEqual(loaded["n_records"], 1)
        self.assertEqual(loaded["n_receipt_events"], 2)
        self.assertEqual(loaded["receipt_format"], "append_only_stage_journal_v1")

    def test_submit_script_resumes_after_boltz_submission_failure(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        script = os.path.join(repo_root, "hpc", "m6d_w2_submit_with_receipt.sh")
        with tempfile.TemporaryDirectory() as directory:
            targets = []
            for index in range(4):
                target_id = f"t{index}"
                pdb = os.path.join(directory, f"{target_id}.pdb")
                fasta = os.path.join(directory, f"{target_id}.fasta")
                msa = os.path.join(directory, f"{target_id}.a3m")
                for path, text in (
                    (pdb, "ATOM\n"),
                    (fasta, f">{target_id}\nACDE\n"),
                    (msa, f">{target_id}\nACDE\n"),
                ):
                    with open(path, "w") as handle:
                        handle.write(text)

                def sha(path):
                    with open(path, "rb") as handle:
                        return hashlib.sha256(handle.read()).hexdigest()

                with open(fasta + ".report.json", "w") as handle:
                    json.dump({
                        "pdb": pdb,
                        "pdb_sha256": sha(pdb),
                        "chain": "A",
                        "out": fasta,
                        "out_sha256": sha(fasta),
                        "length": 4,
                        "sequence": "ACDE",
                    }, handle)
                with open(msa + ".report.json", "w") as handle:
                    json.dump({
                        "out": msa,
                        "out_sha256": sha(msa),
                        "fasta": fasta,
                        "fasta_sha256": sha(fasta),
                        "sequence_length": 4,
                        "ok": True,
                    }, handle)
                targets.append({
                    "id": target_id,
                    "prepared_pdb": pdb,
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": fasta,
                    "target_msa": msa,
                    "out_prefix": os.path.join(directory, "outputs", target_id),
                })

            manifest = os.path.join(directory, "targets.json")
            receipt = os.path.join(directory, "receipt.jsonl")
            summary = os.path.join(directory, "summary.json")
            with open(manifest, "w") as handle:
                json.dump({
                    "defaults": {"num_seq": 4, "temp": 0.3, "seed": 7, "objective": "binder"},
                    "targets": targets,
                }, handle)

            counter = os.path.join(directory, "sbatch-count")
            args_log = os.path.join(directory, "sbatch-args.log")
            mock_sbatch = os.path.join(directory, "sbatch")
            with open(mock_sbatch, "w") as handle:
                handle.write(
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"COUNT_FILE={counter!r}\n"
                    f"ARGS_FILE={args_log!r}\n"
                    "printf '%s\\n' \"$*\" >> \"$ARGS_FILE\"\n"
                    "count=0\n"
                    "if [ -s \"$COUNT_FILE\" ]; then count=$(cat \"$COUNT_FILE\"); fi\n"
                    "count=$((count + 1))\n"
                    "printf '%s\\n' \"$count\" > \"$COUNT_FILE\"\n"
                    "if [ \"$count\" -eq 2 ]; then exit 1; fi\n"
                    "printf '%s\\n' \"$((1000 + count))\"\n"
                )
            os.chmod(mock_sbatch, 0o755)
            env = os.environ.copy()
            env.update({
                "BIO_SFM_REPO_ROOT": repo_root,
                "BIO_SFM_PYTHON": sys.executable,
                "SBATCH_BIN": mock_sbatch,
                "MANIFEST": manifest,
                "SUBMIT_RECEIPT": receipt,
                "SUBMIT_SUMMARY": summary,
                "WORKSTREAM": "w2",
                "BIO_SFM_SUBMIT_DRY_RUN": "0",
                "BIO_SFM_PREDICT_SBATCH_PARTITION": "preempt_gpu",
                "BIO_SFM_PREDICT_SBATCH_QOS": "low",
                "BIO_SFM_PREDICT_SBATCH_GRES": "gpu:h100:1",
                "PYTHONPATH": os.pathsep.join([
                    os.path.join(repo_root, "src"),
                    os.path.join(repo_root, "..", "bio-sfm-trust-core", "src"),
                ]),
            })

            first = subprocess.run([script], env=env, text=True, capture_output=True, check=False)
            first_events = load_events(receipt)
            second = subprocess.run([script], env=env, text=True, capture_output=True, check=False)
            final_events = load_events(receipt)
            with open(summary) as handle:
                final_summary = json.load(handle)
            with open(args_log) as handle:
                submitted_args = handle.read().splitlines()

        self.assertNotEqual(first.returncode, 0)
        self.assertEqual(len(first_events), 1)
        self.assertEqual(first_events[0]["stage"], "proteinmpnn_submitted")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("resuming from recorded ProteinMPNN job 1001", second.stdout)
        t0_gen_events = [
            event for event in final_events
            if event["target_id"] == "t0" and event["stage"] == "proteinmpnn_submitted"
        ]
        self.assertEqual(len(t0_gen_events), 1)
        self.assertEqual(final_summary["status"], "submitted_on_cayuga")
        self.assertEqual(final_summary["n_targets"], 4)
        predictor_calls = [line for line in submitted_args if "run_predict_boltz_complex.sbatch" in line]
        generator_calls = [line for line in submitted_args if "run_generate_proteinmpnn_complex.sbatch" in line]
        h100_flags = "--partition=preempt_gpu --qos=low --gres=gpu:h100:1"
        self.assertTrue(predictor_calls)
        self.assertTrue(generator_calls)
        self.assertTrue(all(h100_flags in line for line in predictor_calls))
        self.assertTrue(all(h100_flags not in line for line in generator_calls))


if __name__ == "__main__":
    unittest.main()
