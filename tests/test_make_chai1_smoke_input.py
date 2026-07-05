import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load():
    path = os.path.join(_HPC, "make_chai1_smoke_input.py")
    spec = importlib.util.spec_from_file_location("make_chai1_smoke_input_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_candidate(path, **updates):
    row = {
        "id": "binder mpnn/0",
        "meta": {
            "complex_target_id": "3PC8_AB",
            "target_chain": "A",
            "design_chain": "B",
        },
        "representation": "GGHHII",
        "target_seq": "AACCDD",
    }
    row.update(updates)
    with open(path, "a") as handle:
        handle.write(json.dumps(row) + "\n")
    return row


class MakeChai1SmokeInputTests(unittest.TestCase):
    def test_chai_smoke_sbatch_is_syntax_valid_and_fold_guarded(self):
        script = os.path.join(_HPC, "run_chai1_smoke.sbatch")
        subprocess.run(["bash", "-n", script], check=True)
        with open(script) as handle:
            text = handle.read()
        self.assertIn('RUN_CHAI_FOLD="${RUN_CHAI_FOLD:-0}"', text)
        self.assertIn('RUN_CHAI_API="${RUN_CHAI_API:-0}"', text)
        self.assertIn('if [ "$RUN_CHAI_FOLD" != "1" ]; then', text)
        self.assertIn("set RUN_CHAI_FOLD=1", text)
        self.assertIn("run_chai1_api_with_metrics.py", text)
        batch_script = os.path.join(_HPC, "run_chai1_batch_array.sbatch")
        subprocess.run(["bash", "-n", batch_script], check=True)
        with open(batch_script) as handle:
            batch_text = handle.read()
        self.assertIn('CANDIDATE_INDEX="${CANDIDATE_INDEX:-${SLURM_ARRAY_TASK_ID:-0}}"', batch_text)
        self.assertIn('RUN_CHAI_API="${RUN_CHAI_API:-1}"', batch_text)
        self.assertIn("convert_chai1_complex_output.py", batch_text)

    def test_writes_chai_fasta_and_manifest_from_first_candidate(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            out = os.path.join(d, "smoke", "input.fasta")
            manifest = os.path.join(d, "smoke", "input_manifest.json")
            _write_candidate(candidates)

            argv = sys.argv
            sys.argv = [
                "make_chai1_smoke_input.py",
                "--candidates",
                candidates,
                "--out",
                out,
                "--manifest",
                manifest,
            ]
            try:
                rc = mod.main()
            finally:
                sys.argv = argv

            self.assertEqual(rc, 0)
            with open(out) as handle:
                fasta = handle.read()
            self.assertIn(">protein|name=binder_mpnn_0_A", fasta)
            self.assertIn(">protein|name=binder_mpnn_0_B", fasta)
            self.assertIn("AACCDD", fasta)
            self.assertIn("GGHHII", fasta)
            with open(manifest) as handle:
                saved = json.load(handle)
            self.assertEqual(saved["candidate_id"], "binder mpnn/0")
            self.assertEqual(saved["complex_target_id"], "3PC8_AB")
            self.assertEqual(saved["target_chain"], "A")
            self.assertEqual(saved["binder_chain"], "B")
            self.assertEqual(saved["predictor_id"], "chai1_complex")
            self.assertEqual(saved["signal_source"], "chai1_pae_interaction")
            self.assertEqual(saved["label_source"], "chai1_lrmsd_to_reference")
            self.assertEqual(saved["claim_status"], "no_claim_smoke_input")
            self.assertEqual(saved["target_sequence_length"], 6)
            self.assertEqual(saved["binder_sequence_length"], 6)

    def test_selects_candidate_by_id(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            out = os.path.join(d, "input.fasta")
            manifest = os.path.join(d, "manifest.json")
            _write_candidate(candidates, id="first", representation="AAAA")
            _write_candidate(candidates, id="second", representation="CCCC")

            argv = sys.argv
            sys.argv = [
                "make_chai1_smoke_input.py",
                "--candidates",
                candidates,
                "--candidate-id",
                "second",
                "--out",
                out,
                "--manifest",
                manifest,
            ]
            try:
                mod.main()
            finally:
                sys.argv = argv

            with open(manifest) as handle:
                saved = json.load(handle)
            self.assertEqual(saved["candidate_id"], "second")
            self.assertEqual(saved["selected_index"], 1)
            with open(out) as handle:
                self.assertIn("CCCC", handle.read())

    def test_rejects_unsupported_sequence_symbols(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            _write_candidate(candidates, representation="ACD*")
            with self.assertRaisesRegex(ValueError, "unsupported residue"):
                _, row = mod._select_candidate(pathlib.Path(candidates), candidate_id=None, index=0)
                mod.build_fasta(row)


if __name__ == "__main__":
    unittest.main()
