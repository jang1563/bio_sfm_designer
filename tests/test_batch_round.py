import json
import os
import tempfile
import unittest
from argparse import Namespace

from bio_sfm_designer.experiments.run_batch_round import run
from bio_sfm_designer.predict.structure import load_structure_records

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "phase2_targets_records.jsonl")


def _write(tmpdir, name, rows):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


class BatchRoundCLITests(unittest.TestCase):
    def test_round_from_synced_artifacts(self):
        records = load_structure_records(FIXTURE)[:5]
        ids = [str(r["target_id"]) for r in records]
        flagged = ids[0]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": r["regime"]} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": (i == flagged), "reason": "x"} for i in ids])
            out = os.path.join(d, "round0")
            args = Namespace(candidates=candidates, records=FIXTURE, verdicts=verdicts,
                             target="protein-structure trust-routing evaluation",
                             objective="structure_quality", lam=0.5, assay_budget=20,
                             out=out, provider=None)
            result = run(args)

            self.assertTrue(result.allowed)
            self.assertEqual(len(result.rows), 5)
            self.assertTrue(os.path.exists(os.path.join(out, "campaign.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(out, "summary.json")))
            with open(os.path.join(out, "summary.json")) as fh:
                summ = json.load(fh)
            self.assertEqual(summ["screen_backend"], "precomputed_deberta")
            flagged_row = next(r for r in result.rows if r["candidate_id"] == flagged)
            self.assertEqual(flagged_row["action"], "defer")

    def test_omitting_verdicts_uses_builtin_screen(self):
        records = load_structure_records(FIXTURE)[:3]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": r["regime"]} for r in records])
            args = Namespace(candidates=candidates, records=FIXTURE, verdicts=None,
                             target="thermostable GFP reporter", objective="stability",
                             lam=0.5, assay_budget=20, out=os.path.join(d, "r"), provider=None)
            result = run(args)
            self.assertTrue(result.allowed)
            self.assertEqual(result.screen_backend, "builtin_policy")


if __name__ == "__main__":
    unittest.main()
