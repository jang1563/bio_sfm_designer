"""Simulate the external HPC DeBERTa producer locally to prove the producer->consumer JSONL
contract WITHOUT torch/bioguard/the cluster. We import hpc/screen_deberta.py, swap its
DeBERTa loader for a keyword fake, run it on tiny candidate intents, then feed the resulting
verdicts.jsonl into the real local PrecomputedScreen. If the field names ever drift between
hpc/screen_deberta.py and safety.PrecomputedScreen, this test fails."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

from bio_sfm_designer.safety import PrecomputedScreen
from bio_sfm_designer.types import Candidate

_HPC_DIR = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load_screen_module():
    path = os.path.join(_HPC_DIR, "screen_deberta.py")
    spec = importlib.util.spec_from_file_location("screen_deberta_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeVerdict:
    def __init__(self, flag, reason):
        self.joint_flag = flag
        self.prompt_flag = flag
        self.joint_reason = reason
        self.response_score = 1.0 if flag else 0.0


class _FakeGuard:
    """Stand-in for constitutional-bioguard's DualModeGuard (no torch)."""
    def classify(self, text):
        flag = any(w in text.lower() for w in ("weaponize", "bioweapon", "enhance lethality"))
        return _FakeVerdict(flag, "fake-deberta: hazard term" if flag else "")


class ScreenContractTests(unittest.TestCase):
    def test_sbatch_candidates_guard_does_not_corrupt_set_value(self):
        script = os.path.join(_HPC_DIR, "run_screen_deberta.sbatch")
        with open(script) as fh:
            text = fh.read()
        match = re.search(r'^CANDIDATES="([^"]+)"$', text, flags=re.MULTILINE)
        self.assertIsNotNone(match)
        assignment = match.group(0)
        proc = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", f"CANDIDATES=example.jsonl\n{assignment}\nprintf '%s' \"$CANDIDATES\""],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.stdout, "example.jsonl")

    def test_producer_output_feeds_consumer(self):
        mod = _load_screen_module()
        mod._load_guard = lambda: _FakeGuard()  # swap the external HPC DeBERTa loader

        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cands = os.path.join(d, "candidates.jsonl")
            verdicts = os.path.join(d, "verdicts.jsonl")
            with open(cands, "w") as fh:
                fh.write(json.dumps({"id": "c-benign", "text": "thermostable GFP reporter"}) + "\n")
                fh.write(json.dumps({"id": "c-haz", "text": "weaponize a pathogen to enhance lethality"}) + "\n")

            # run the external HPC producer (with the fake guard) exactly as the sbatch would
            argv = sys.argv
            sys.argv = ["screen_deberta.py", "--candidates", cands, "--out", verdicts]
            try:
                mod.main()
            finally:
                sys.argv = argv

            # producer wrote the contract fields
            with open(verdicts) as vf:
                rows = {r["id"]: r for r in (json.loads(l) for l in vf if l.strip())}
            self.assertEqual(set(rows), {"c-benign", "c-haz"})
            self.assertTrue(rows["c-haz"]["flag"])
            self.assertFalse(rows["c-benign"]["flag"])

            # the real local consumer reads them — benign id with an opaque (benign) representation
            # so the verdict (not the builtin lexicon) is what drives the decision
            screen = PrecomputedScreen(verdicts)
            haz = screen.screen_candidate(Candidate(id="c-haz", representation="ACDEFGHIK"))
            benign = screen.screen_candidate(Candidate(id="c-benign", representation="ACDEFGHIK"))
            self.assertFalse(haz.allowed)
            self.assertEqual(haz.decision_class, "escalate")
            self.assertTrue(benign.allowed)


if __name__ == "__main__":
    unittest.main()
