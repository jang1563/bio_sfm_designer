import json
import os
import subprocess
import tempfile
import unittest
from argparse import Namespace

from bio_sfm_designer.experiments.run_batch_round import preflight_batch_round, run
from bio_sfm_designer.predict.structure import load_structure_records

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "phase2_targets_records.jsonl")
BARSTAR_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "barstar_interface_records.jsonl")


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
                             out=out, preflight_out=None, strict_complex_records=False,
                             allow_missing_verdicts=False, provider=None)
            result = run(args)

            self.assertTrue(result.allowed)
            self.assertEqual(len(result.rows), 5)
            self.assertTrue(os.path.exists(os.path.join(out, "preflight.json")))
            self.assertTrue(os.path.exists(os.path.join(out, "campaign.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(out, "summary.json")))
            with open(os.path.join(out, "summary.json")) as fh:
                summ = json.load(fh)
            self.assertEqual(summ["status"], "closed_loop_round_complete")
            self.assertEqual(summ["controller_status"], result.status)
            self.assertTrue(summ["allowed"])
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
                             lam=0.5, assay_budget=20, out=os.path.join(d, "r"),
                             preflight_out=None, strict_complex_records=False,
                             allow_missing_verdicts=False, provider=None)
            result = run(args)
            self.assertTrue(result.allowed)
            self.assertEqual(result.screen_backend, "builtin_policy")

    def test_preflight_blocks_missing_prediction_record(self):
        records = load_structure_records(FIXTURE)[:2]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl", [
                {"id": str(records[0]["target_id"]), "representation": "covered"},
                {"id": "missing-prediction", "representation": "not covered"},
            ])
            rep = preflight_batch_round(candidates, FIXTURE)
        self.assertFalse(rep["ok"])
        self.assertIn("missing_prediction_record", {f["kind"] for f in rep["failures"]})

    def test_preflight_blocks_missing_or_empty_batch_artifacts_before_loading(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "missing_candidates.jsonl")
            records = os.path.join(d, "empty_records.jsonl")
            verdicts = os.path.join(d, "missing_verdicts.jsonl")
            prevalidate = os.path.join(d, "missing_prior.jsonl")
            open(records, "w").close()

            rep = preflight_batch_round(
                candidates,
                records,
                verdicts_path=verdicts,
                strict_complex_records=True,
                prevalidate_records_paths=[prevalidate],
                conformal_alpha=0.3,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["n_candidates"], 0)
        self.assertEqual(rep["n_records"], 0)
        self.assertEqual(rep["n_verdicts"], 0)
        self.assertEqual(len(rep["pending_artifacts"]), 4)
        by_artifact = {f["artifact"]: f for f in rep["failures"]}
        self.assertEqual(by_artifact["candidates"]["kind"], "missing_batch_artifact")
        self.assertEqual(by_artifact["records"]["kind"], "empty_batch_artifact")
        self.assertEqual(by_artifact["verdicts"]["status"], "missing")
        self.assertEqual(by_artifact["prevalidate_records"]["status"], "missing")
        self.assertFalse(rep["gate_prevalidation"]["ok"])
        self.assertEqual(rep["gate_prevalidation"]["conformal_alpha"], 0.3)

    def test_run_writes_preflight_when_batch_artifact_missing(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl", [
                {"id": "design-0", "representation": "design-0", "regime": "complex",
                 "meta": {"complex_target_id": "toy"}}
            ])
            out = os.path.join(d, "round0")
            sync_back = os.path.join(d, "w4_sync_back.sh")
            missing_records = "hpc_outputs/__test_missing_batch_round_records__.jsonl"
            self.assertFalse(os.path.exists(missing_records))
            args = Namespace(candidates=candidates, records=missing_records,
                             verdicts=None, target="benign complex DBTL dry run",
                             objective="interface_quality", lam=0.5, assay_budget=20,
                             out=out, preflight_out=None, strict_complex_records=True,
                             allow_missing_verdicts=False, provider=None,
                             prevalidate_records=[], conformal_alpha=None, conformal_delta=0.1,
                             emit_sync_back_plan=sync_back, sync_remote_root=None, sync_local_root=".")

            with self.assertRaises(ValueError):
                run(args)
            with open(os.path.join(out, "preflight.json")) as fh:
                preflight = json.load(fh)
            with open(sync_back) as fh:
                sync_text = fh.read()
            sync_manifest = os.path.splitext(sync_back)[0] + ".manifest.json"
            with open(sync_manifest) as fh:
                manifest = json.load(fh)

        self.assertFalse(preflight["ok"])
        self.assertIn("bio_sfm_designer.experiments.run_batch_round", preflight["self_command"])
        self.assertIn("--emit-sync-back-plan", preflight["self_command"])
        self.assertEqual(preflight["pending_artifacts"][0]["artifact"], "records")
        self.assertEqual(preflight["pending_artifacts"][0]["kind"], "missing_batch_artifact")
        self.assertIn("CAYUGA_BIO_SFM_ROOT", sync_text)
        self.assertEqual(manifest["kind"], "w4_batch_sync_back")
        self.assertEqual(manifest["paths"], [missing_records])
        self.assertEqual(manifest["n_paths"], 1)
        self.assertEqual(manifest["sync_script"], sync_back)
        self.assertIn(f"SYNC_PLAN_MANIFEST={sync_manifest}", sync_text)
        self.assertIn("EXPECTED_SYNC_PLAN_COUNT=1", sync_text)
        self.assertIn("EXPECTED_SYNC_PLAN_SHA256=", sync_text)
        self.assertIn("stale W4 batch sync manifest", sync_text)
        self.assertIn("rsync -avP", sync_text)
        self.assertIn("if ! test -s", sync_text)
        self.assertIn("missing or empty W4 batch artifact after rsync", sync_text)
        self.assertIn("__test_missing_batch_round_records__.jsonl", sync_text)
        self.assertIn("bio_sfm_designer.experiments.run_batch_round", sync_text)
        self.assertIn("--strict-complex-records", sync_text)
        rerun_lines = [
            line for line in sync_text.splitlines()
            if "bio_sfm_designer.experiments.run_batch_round" in line
            and not line.startswith("#")
        ]
        self.assertEqual(len(rerun_lines), 1)
        self.assertNotIn("--emit-sync-back-plan", rerun_lines[0])

    def test_w4_sync_back_plan_fails_if_rsync_leaves_empty_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            bin_dir = os.path.join(d, "bin")
            local_root = os.path.join(d, "local")
            remote_root = os.path.join(d, "remote")
            out = os.path.join(d, "round0")
            sync_back = os.path.join(d, "w4_sync_back.sh")
            os.makedirs(bin_dir, exist_ok=True)
            fake_rsync = os.path.join(bin_dir, "rsync")
            with open(fake_rsync, "w") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(fake_rsync, 0o755)

            candidates = _write(d, "candidates.jsonl", [
                {"id": "design-0", "representation": "design-0", "regime": "complex",
                 "meta": {"complex_target_id": "toy"}}
            ])
            missing_records = "hpc_outputs/__test_missing_w4_empty_guard_records__.jsonl"
            self.assertFalse(os.path.exists(missing_records))
            args = Namespace(candidates=candidates, records=missing_records,
                             verdicts=None, target="benign complex DBTL dry run",
                             objective="interface_quality", lam=0.5, assay_budget=20,
                             out=out, preflight_out=None, strict_complex_records=True,
                             allow_missing_verdicts=False, provider=None,
                             prevalidate_records=[], conformal_alpha=None, conformal_delta=0.1,
                             emit_sync_back_plan=sync_back, sync_remote_root=remote_root,
                             sync_local_root=local_root)

            with self.assertRaises(ValueError):
                run(args)
            with open(sync_back) as fh:
                sync_text = fh.read()
            with open(os.path.join(out, "preflight.json")) as fh:
                preflight_text = fh.read()
            env = os.environ.copy()
            env["PATH"] = os.pathsep.join([bin_dir, env.get("PATH", "")])
            proc = subprocess.run(
                ["bash", sync_back],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing or empty W4 batch artifact after rsync", proc.stderr)
        self.assertIn("--emit-sync-back-plan", preflight_text)
        rerun_lines = [
            line for line in sync_text.splitlines()
            if "bio_sfm_designer.experiments.run_batch_round" in line
            and not line.startswith("#")
        ]
        self.assertEqual(len(rerun_lines), 1)
        self.assertNotIn("--emit-sync-back-plan", rerun_lines[0])
        self.assertNotIn("--sync-remote-root", rerun_lines[0])
        self.assertNotIn("--sync-local-root", rerun_lines[0])

    def test_preflight_blocks_missing_screen_verdict_when_verdicts_provided(self):
        records = load_structure_records(FIXTURE)[:2]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": "x"} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": str(records[0]["target_id"]), "flag": False}])
            rep = preflight_batch_round(candidates, FIXTURE, verdicts_path=verdicts)
        self.assertFalse(rep["ok"])
        self.assertIn("missing_screen_verdict", {f["kind"] for f in rep["failures"]})

    def test_strict_complex_records_round_from_barstar_fixture(self):
        records = load_structure_records(BARSTAR_FIXTURE)[:4]
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            out = os.path.join(d, "complex_round")
            args = Namespace(candidates=candidates, records=BARSTAR_FIXTURE, verdicts=verdicts,
                             target="benign barnase-barstar interface trust-routing evaluation",
                             objective="interface_quality", lam=0.5, assay_budget=20,
                             out=out, preflight_out=None, strict_complex_records=True,
                             allow_missing_verdicts=False, provider=None)
            result = run(args)

            with open(os.path.join(out, "preflight.json")) as fh:
                preflight = json.load(fh)
        self.assertTrue(result.allowed)
        self.assertTrue(preflight["ok"])
        self.assertEqual(preflight["candidate_ids"], ids)
        self.assertTrue(preflight["strict_complex_records"])
        self.assertTrue(preflight["complex_records_qc"]["ok"])

    def test_prevalidate_records_enable_conformal_complex_gate(self):
        records = [dict(r) for r in load_structure_records(BARSTAR_FIXTURE)[:4]]
        for i, rec in enumerate(records):
            rec["target_id"] = f"new-complex-{i}"
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            batch_records = _write(d, "records.jsonl", records)
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            out = os.path.join(d, "complex_round")
            args = Namespace(candidates=candidates, records=batch_records, verdicts=verdicts,
                             target="benign barnase-barstar interface trust-routing evaluation",
                             objective="interface_quality", lam=0.5, assay_budget=20,
                             out=out, preflight_out=None, strict_complex_records=True,
                             allow_missing_verdicts=False,
                             prevalidate_records=[BARSTAR_FIXTURE],
                             conformal_alpha=0.3, conformal_delta=0.1, provider=None)
            result = run(args)

            with open(os.path.join(out, "preflight.json")) as fh:
                preflight = json.load(fh)
            with open(os.path.join(out, "summary.json")) as fh:
                summary = json.load(fh)

        self.assertTrue(result.allowed)
        self.assertTrue(result.gate_calibrated)
        self.assertTrue(summary["gate_calibrated"])
        self.assertTrue(preflight["gate_prevalidation"]["ok"])
        self.assertTrue(preflight["gate_prevalidation"]["regimes"]["complex"]["validated"])
        self.assertIsNotNone(preflight["gate_prevalidation"]["regimes"]["complex"]["tau"])
        self.assertEqual(preflight["gate_prevalidation"]["conformal_alpha"], 0.3)
        contract = preflight["gate_prevalidation"]["batch_contract"]
        self.assertTrue(contract["checked"])
        self.assertTrue(contract["ok"])
        self.assertEqual(
            contract["regimes"]["complex"]["fields"]["predictor_id"]["prevalidation"]["values"],
            ["boltz2_complex"],
        )
        self.assertEqual(
            contract["regimes"]["complex"]["fields"]["signal_source"]["batch"]["values"],
            ["boltz2_pae_interaction"],
        )
        self.assertEqual(
            contract["regimes"]["complex"]["fields"]["lrmsd_threshold"]["batch"]["values"],
            [4.0],
        )
        self.assertEqual(summary["gate_prevalidation"], preflight["gate_prevalidation"])
        self.assertTrue(summary["strict_complex_records"])

    def test_prevalidation_contract_blocks_batch_threshold_drift(self):
        records = [dict(r) for r in load_structure_records(BARSTAR_FIXTURE)[:4]]
        for i, rec in enumerate(records):
            rec["target_id"] = f"new-complex-threshold-{i}"
            rec["lrmsd_threshold"] = 5.0
            rec["truth"] = dict(rec["truth"])
            rec["truth"]["correct"] = float(rec["lrmsd"]) < 5.0
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            batch_records = _write(d, "records.jsonl", records)
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, batch_records, verdicts_path=verdicts,
                                        strict_complex_records=True,
                                        prevalidate_records_paths=[BARSTAR_FIXTURE],
                                        conformal_alpha=0.3)

        self.assertFalse(rep["ok"])
        self.assertIn("gate_prevalidation_blocked", {f["kind"] for f in rep["failures"]})
        gate = rep["gate_prevalidation"]
        self.assertFalse(gate["ok"])
        self.assertIn("prevalidation_batch_contract_mismatch", {f["kind"] for f in gate["failures"]})
        contract = gate["batch_contract"]
        self.assertFalse(contract["ok"])
        threshold = contract["regimes"]["complex"]["fields"]["lrmsd_threshold"]
        self.assertFalse(threshold["single_value_agree"])
        self.assertEqual(threshold["prevalidation"]["values"], [4.0])
        self.assertEqual(threshold["batch"]["values"], [5.0])

    def test_prevalidation_contract_blocks_batch_signal_source_drift(self):
        records = [dict(r) for r in load_structure_records(BARSTAR_FIXTURE)[:4]]
        for i, rec in enumerate(records):
            rec["target_id"] = f"new-complex-signal-{i}"
            rec["signal_source"] = "other_pae_interaction"
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            batch_records = _write(d, "records.jsonl", records)
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, batch_records, verdicts_path=verdicts,
                                        strict_complex_records=True,
                                        prevalidate_records_paths=[BARSTAR_FIXTURE],
                                        conformal_alpha=0.3)

        self.assertFalse(rep["ok"])
        gate = rep["gate_prevalidation"]
        self.assertFalse(gate["ok"])
        contract = gate["batch_contract"]
        self.assertFalse(contract["ok"])
        signal = contract["regimes"]["complex"]["fields"]["signal_source"]
        self.assertFalse(signal["single_value_agree"])
        self.assertEqual(signal["prevalidation"]["values"], ["boltz2_pae_interaction"])
        self.assertEqual(signal["batch"]["values"], ["other_pae_interaction"])

    def test_conformal_alpha_requires_prior_prevalidation_records(self):
        records = load_structure_records(BARSTAR_FIXTURE)[:2]
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, BARSTAR_FIXTURE, verdicts_path=verdicts,
                                        strict_complex_records=True,
                                        conformal_alpha=0.3)

        self.assertFalse(rep["ok"])
        self.assertTrue(rep["gate_prevalidation"]["requested"])
        self.assertFalse(rep["gate_prevalidation"]["ok"])
        self.assertIn("gate_prevalidation_blocked", {f["kind"] for f in rep["failures"]})
        nested = rep["gate_prevalidation"]["failures"]
        self.assertIn("missing_prevalidation_records", {f["kind"] for f in nested})

    def test_strict_complex_preflight_requires_candidate_complex_target_id(self):
        records = load_structure_records(BARSTAR_FIXTURE)[:2]
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": "x",
                                  "regime": "complex"} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, BARSTAR_FIXTURE, verdicts_path=verdicts,
                                        strict_complex_records=True)
        self.assertFalse(rep["ok"])
        self.assertIn("missing_complex_target_id", {f["kind"] for f in rep["failures"]})

    def test_strict_complex_preflight_blocks_candidate_record_complex_target_mismatch(self):
        records = load_structure_records(BARSTAR_FIXTURE)[:2]
        expected_complex_id = str(records[0]["complex_target_id"])
        wrong_records = [dict(r) for r in records]
        wrong_records[0]["complex_target_id"] = "OTHER_COMPLEX"
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": "x",
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            record_path = _write(d, "records.jsonl", wrong_records)
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, record_path, verdicts_path=verdicts,
                                        strict_complex_records=True)

        self.assertFalse(rep["ok"])
        mismatch = [f for f in rep["failures"] if f["kind"] == "complex_target_mismatch"]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0]["candidate_complex_target_ids"], [expected_complex_id])
        self.assertEqual(mismatch[0]["record_complex_target_ids"], ["OTHER_COMPLEX"])

    def test_prevalidation_records_must_not_overlap_current_batch(self):
        records = load_structure_records(BARSTAR_FIXTURE)[:2]
        ids = [str(r["target_id"]) for r in records]
        with tempfile.TemporaryDirectory() as d:
            candidates = _write(d, "candidates.jsonl",
                                [{"id": str(r["target_id"]), "representation": str(r["target_id"]),
                                  "regime": "complex",
                                  "meta": {"complex_target_id": r["complex_target_id"]}} for r in records])
            verdicts = _write(d, "verdicts.jsonl",
                              [{"id": i, "flag": False, "reason": ""} for i in ids])
            rep = preflight_batch_round(candidates, BARSTAR_FIXTURE, verdicts_path=verdicts,
                                        strict_complex_records=True,
                                        prevalidate_records_paths=[BARSTAR_FIXTURE],
                                        conformal_alpha=0.3)

        self.assertFalse(rep["ok"])
        self.assertIn("gate_prevalidation_blocked", {f["kind"] for f in rep["failures"]})
        nested = rep["gate_prevalidation"]["failures"]
        self.assertIn("prevalidation_overlaps_current_batch", {f["kind"] for f in nested})


if __name__ == "__main__":
    unittest.main()
