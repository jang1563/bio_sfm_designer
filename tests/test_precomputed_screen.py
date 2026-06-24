import json
import os
import tempfile
import unittest

from bio_sfm_designer.config import ObjectiveSpec
from bio_sfm_designer.safety import PrecomputedScreen
from bio_sfm_designer.types import Candidate

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "phase2_targets_records.jsonl")


def _write_verdicts(tmpdir, rows):
    path = os.path.join(tmpdir, "verdicts.jsonl")
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


class PrecomputedScreenUnitTests(unittest.TestCase):
    def test_flagged_escalates(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_verdicts(d, [{"id": "c1", "flag": True, "reason": "deberta: weaponization intent"}])
            v = PrecomputedScreen(p).screen_candidate(Candidate(id="c1", representation="SEQ"))
            self.assertFalse(v.allowed)
            self.assertEqual(v.decision_class, "escalate")
            self.assertEqual(v.source, "precomputed_deberta")

    def test_unflagged_allows(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_verdicts(d, [{"id": "c1", "flag": False, "reason": ""}])
            self.assertTrue(PrecomputedScreen(p).screen_candidate(Candidate(id="c1", representation="SEQ")).allowed)

    def test_missing_verdict_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_verdicts(d, [{"id": "other", "flag": False}])
            v = PrecomputedScreen(p).screen_candidate(Candidate(id="c1", representation="SEQ"))
            self.assertFalse(v.allowed)                      # missing != cleared
            self.assertEqual(v.decision_class, "route_expert")

    def test_target_policy_still_applies(self):
        with tempfile.TemporaryDirectory() as d:
            screen = PrecomputedScreen(_write_verdicts(d, []))
            self.assertTrue(screen.screen_target(ObjectiveSpec(target="thermostable GFP reporter", objective="stability")).allowed)
            self.assertFalse(screen.screen_target(ObjectiveSpec(target="build a bioweapon", objective="x")).allowed)


class PrecomputedScreenIntegrationTests(unittest.TestCase):
    def test_controller_defers_the_flagged_candidate(self):
        from bio_sfm_designer.loop.controller import DBTLController
        from bio_sfm_designer.predict.structure import (
            PrecomputedStructurePredictor,
            StructureRecordGenerator,
            load_structure_records,
        )

        records = load_structure_records(FIXTURE)
        flagged_id = str(records[0]["target_id"])
        with tempfile.TemporaryDirectory() as d:
            # full verdict coverage (Cayuga would screen every candidate), one flagged
            verdicts = [{"id": str(r["target_id"]), "flag": (str(r["target_id"]) == flagged_id), "reason": "x"}
                        for r in records]
            path = _write_verdicts(d, verdicts)
            spec = ObjectiveSpec(target="protein-structure trust-routing evaluation",
                                 objective="structure_quality", lam=0.5, rounds=1,
                                 candidates_per_round=80, assay_budget=80)
            result = DBTLController(
                generator=StructureRecordGenerator(FIXTURE),
                predictor=PrecomputedStructurePredictor(FIXTURE),
                screen=PrecomputedScreen(path),
            ).run(spec)

            self.assertTrue(result.allowed)
            self.assertEqual(result.screen_backend, "precomputed_deberta")
            flagged_row = next(r for r in result.rows if r["candidate_id"] == flagged_id)
            self.assertEqual(flagged_row["action"], "defer")
            self.assertIn("screen blocked", flagged_row["rationale"])
            # not everything is deferred — unflagged candidates still route via the gate
            self.assertTrue(any(r["action"] != "defer" for r in result.rows))


if __name__ == "__main__":
    unittest.main()
