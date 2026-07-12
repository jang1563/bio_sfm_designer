import json
import os
import tempfile
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.generate import PrecomputedGenerator
from bio_sfm_designer.loop.controller import DBTLController
from bio_sfm_designer.predict.structure import PrecomputedStructurePredictor, load_structure_records
from bio_sfm_designer.safety import PrecomputedScreen

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "phase2_targets_records.jsonl")


def _write(tmpdir, name, rows):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


class PrecomputedGeneratorUnitTests(unittest.TestCase):
    def test_round0_yields_candidates_then_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "candidates.jsonl", [
                {"id": "a", "representation": "ACDE", "regime": "monomer"},
                {"id": "b", "representation": "FGHI", "regime": "complex", "parent_id": "a"},
            ])
            gen = PrecomputedGenerator(p)
            spec = ObjectiveSpec(target="t", objective="o")
            r0 = gen.propose(spec, 0, 10)
            self.assertEqual([c.id for c in r0], ["a", "b"])
            self.assertEqual(r0[1].parent_id, "a")
            self.assertEqual(r0[0].meta["regime"], "monomer")
            self.assertEqual(gen.propose(spec, 1, 10), [])  # fixed set -> no later rounds

    def test_n_limits(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "c.jsonl", [{"id": str(i), "representation": "X"} for i in range(5)])
            self.assertEqual(len(PrecomputedGenerator(p).propose(ObjectiveSpec(target="t"), 0, 3)), 3)


class FullPrecomputedPipelineTests(unittest.TestCase):
    """generate + predict + screen, all consuming external HPC-style JSONL, run offline locally."""

    def test_generate_predict_screen_all_precomputed(self):
        records = load_structure_records(FIXTURE)[:5]
        ids = [str(r["target_id"]) for r in records]
        flagged_id = ids[0]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": r["regime"]} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": (i == flagged_id), "reason": "x"} for i in ids])

            spec = ObjectiveSpec(target="protein-structure trust-routing evaluation",
                                 objective="structure_quality", lam=0.5, rounds=1,
                                 candidates_per_round=5, assay_budget=20)
            result = DBTLController(
                generator=PrecomputedGenerator(candidates),
                predictor=PrecomputedStructurePredictor(FIXTURE),
                screen=PrecomputedScreen(verdicts),
            ).run(spec)

            self.assertTrue(result.allowed)
            self.assertEqual(len(result.rows), 5)
            self.assertEqual({r["candidate_id"] for r in result.rows}, set(ids))
            flagged_row = next(r for r in result.rows if r["candidate_id"] == flagged_id)
            self.assertEqual(flagged_row["action"], "defer")
            self.assertIn("screen blocked", flagged_row["rationale"])


if __name__ == "__main__":
    unittest.main()
