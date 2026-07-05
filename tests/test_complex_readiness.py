"""Tests for the project-level M6c readiness preflight."""

import io
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from bio_sfm_designer.experiments.complex_readiness import main, render_text, run_readiness
from bio_sfm_designer.experiments.complex_scale_completion import run_completion


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _write_json(path, obj):
    _write(path, json.dumps(obj) + "\n")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_target_msa_report(msa, fasta, sequence_length=4):
    _write_json(msa + ".report.json", {
        "ok": True,
        "fasta": fasta,
        "fasta_sha256": _sha256_file(fasta),
        "out": msa,
        "out_sha256": _sha256_file(msa),
        "sequence_length": sequence_length,
    })


def _write_target_fasta_report(pdb, fasta, chain="A", sequence="AAAA"):
    _write_json(fasta + ".report.json", {
        "pdb": os.path.abspath(pdb),
        "pdb_sha256": _sha256_file(pdb),
        "chain": chain,
        "length": len(sequence),
        "sequence": sequence,
        "fasta_id": f"target_{chain}",
        "out": os.path.abspath(fasta),
        "out_sha256": _sha256_file(fasta),
        "unknown_allowed": False,
    })


def _strict_qc():
    return {"ok": True, "require_complex_target_id": True,
            "require_provenance": True, "require_chain_ids": True}


def _complex_record(i, *, predictor="chai1_complex", signal="chai1_pae_interaction",
                    label="chai1_lrmsd_to_reference"):
    return {
        "target_id": f"design-{i}",
        "complex_target_id": "1BRS_AD",
        "predictor_id": predictor,
        "signal_source": signal,
        "label_source": label,
        "target_chain": "A",
        "binder_chain": "D",
        "regime": "complex",
        "mean_plddt": 88.0,
        "pae_interaction": 2.0 + i,
        "lrmsd": 1.5,
        "lrmsd_threshold": 4.0,
        "truth": {"correct": True, "quality": 0.8},
        "interface_aligned": True,
    }


class ComplexReadinessTests(unittest.TestCase):
    def test_no_inputs_is_blocked_with_next_action(self):
        rep = run_readiness()
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertIn("readiness_inputs", {c["name"] for c in rep["checks"]})
        self.assertIn("provide at least one", rep["next_action"])
        self.assertIn("complex readiness", render_text(rep))

    def test_input_prep_completion_is_first_class_readiness_check(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input_prep_completion.json")
            _write_json(completion, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 7,
                "n_present": 5,
                "n_nonempty": 5,
                "n_missing": 2,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["1BRS_AD"],
                "pending_artifacts": [
                    {"target_id": "1BRS_AD", "field": "target_msa", "path": "1BRS_A.a3m", "error": "missing_file"},
                ],
                "artifacts_by_target": {
                    "1BRS_AD": {
                        "n_artifacts": 7,
                        "n_present": 5,
                        "n_nonempty": 5,
                        "n_missing": 2,
                        "n_empty": 0,
                        "pending_fields": ["target_msa", "target_msa_report"],
                        "ready": False,
                    },
                },
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })

            rep = run_readiness(input_prep_completion_path=completion)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["input_prep_completion"]["status"], "blocked")
        self.assertEqual(checks["input_prep_completion"]["details"]["blocked_targets"], ["1BRS_AD"])
        self.assertEqual(
            checks["input_prep_completion"]["details"]["pending_artifacts"][0]["field"],
            "target_msa",
        )
        w2 = rep["roadmap_status"]["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_input_prep_completion_blocked")
        self.assertIn("input_prep_completion: blocked", rep["plan_text"])

    def test_input_prep_completion_ready_is_readiness_ready_to_rerun_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input_prep_completion.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_require_files",
                "n_artifacts": 7,
                "n_present": 7,
                "n_nonempty": 7,
                "n_missing": 0,
                "n_empty": 0,
                "ready_targets": ["1BRS_AD"],
                "blocked_targets": [],
                "pending_artifacts": [],
                "artifacts_by_target": {"1BRS_AD": {"ready": True}},
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })

            rep = run_readiness(input_prep_completion_path=completion)

        self.assertTrue(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["input_prep_completion"]["status"], "ready")
        self.assertIn("manifest_command", checks["input_prep_completion"]["next_action"])
        w2 = rep["roadmap_status"]["workstreams"]["W2_multi_target_panel"]
        self.assertEqual(w2["status"], "panel_input_prep_ready_for_manifest")
        self.assertEqual(w2["ready_targets"], ["1BRS_AD"])

    def test_readiness_preserves_posthoc_science_claims_from_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input_prep_completion.json")
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_require_files",
                "n_artifacts": 7,
                "n_present": 7,
                "n_nonempty": 7,
                "n_missing": 0,
                "n_empty": 0,
                "ready_targets": ["1BRS_AD"],
                "blocked_targets": [],
                "pending_artifacts": [],
                "artifacts_by_target": {"1BRS_AD": {"ready": True}},
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "science_claims_supported": ["complex_pae_interaction_signal"],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_readiness(
                posthoc_manifest_path=manifest,
                input_prep_completion_path=completion,
            )

        self.assertTrue(rep["posthoc_science_claims_audit"]["ok"])
        self.assertEqual(rep["posthoc_science_claims_audit"]["status"], "ok")
        self.assertEqual(rep["posthoc_science_claims"]["supported"], [
            "complex_pae_interaction_signal",
        ])
        self.assertEqual(rep["posthoc_science_claims"]["not_yet_supported"], [
            "target_alpha_0_2_certificate",
        ])
        self.assertIn("posthoc_science_claims:", render_text(rep))
        self.assertIn("target_alpha_0_2_certificate", rep["plan_text"])

    def test_readiness_blocks_posthoc_science_claim_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input_prep_completion.json")
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            report = os.path.join(d, "m6c_report.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_require_files",
                "n_artifacts": 7,
                "n_present": 7,
                "n_nonempty": 7,
                "n_missing": 0,
                "n_empty": 0,
                "ready_targets": ["1BRS_AD"],
                "blocked_targets": [],
                "pending_artifacts": [],
                "artifacts_by_target": {"1BRS_AD": {"ready": True}},
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
            })
            _write_json(report, {
                "dataset": {"n": 192},
                "target_alpha": 0.2,
                "science_claims": {
                    "supported": [{"id": "complex_pae_interaction_signal"}],
                    "not_yet_supported": [{"id": "target_alpha_0_2_certificate"}],
                    "planning_diagnostics": [{"id": "scale_projection_alpha_0_2"}],
                    "decisive_next_experiments": [{"id": "scale_barnase_barstar_alpha_0_2"}],
                },
            })
            _write_json(manifest, {
                "paths": {"decision": decision, "report_json": report},
                "summary": {
                    "science_claims_supported": [
                        "complex_pae_interaction_signal",
                        "alpha_0_3_rcps_certificate",
                    ],
                    "science_claims_not_yet_supported": ["target_alpha_0_2_certificate"],
                    "science_claims_planning_diagnostics": ["scale_projection_alpha_0_2"],
                    "science_claims_decisive_next": ["scale_barnase_barstar_alpha_0_2"],
                },
            })

            rep = run_readiness(
                posthoc_manifest_path=manifest,
                input_prep_completion_path=completion,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        self.assertEqual(rep["posthoc_science_claims_audit"]["status"], "claim_summary_mismatch")
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["posthoc_science_claims"]["status"], "claim_summary_mismatch")
        self.assertIn("manifest claim summaries", checks["posthoc_science_claims"]["next_action"])

    def test_readiness_blocks_when_roadmap_status_refresh_fails(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input_prep_completion.json")
            decision = os.path.join(d, "decision.json")
            manifest = os.path.join(d, "manifest.json")
            _write_json(completion, {
                "ok": True,
                "status": "ready_for_require_files",
                "n_artifacts": 7,
                "n_present": 7,
                "n_nonempty": 7,
                "n_missing": 0,
                "n_empty": 0,
                "ready_targets": ["1BRS_AD"],
                "blocked_targets": [],
                "pending_artifacts": [],
                "artifacts_by_target": {"1BRS_AD": {"ready": True}},
                "manifest_command": "python -m bio_sfm_designer.experiments.complex_target_manifest --manifest targets.json --require-files",
            })
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "n_records": 192,
                "certified_alphas": [0.3],
            })
            _write(manifest, "{not-json\n")

            rep = run_readiness(
                decision_path=decision,
                posthoc_manifest_path=manifest,
                input_prep_completion_path=completion,
            )

        self.assertFalse(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["roadmap_status"]["status"], "roadmap_status_failed")
        self.assertIn("fix roadmap status inputs", checks["roadmap_status"]["next_action"])
        self.assertIn("roadmap status refresh failed", checks["roadmap_status"]["message"])

    def test_single_target_scale_plan_does_not_require_panel(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "prepared_pdb": "hpc_outputs/targets/prepared_1BRS_AD.pdb",
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": "hpc_outputs/targets/1BRS_A.fasta",
                "target_msa": "hpc_outputs/targets/1BRS_A.a3m",
                "out_prefix": "hpc_outputs/m6c_targets/1BRS_AD",
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3, 0.5],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 200,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="1BRS_AD",
                previous_records=["tests/fixtures/barstar_interface_records.jsonl"],
            )

        self.assertTrue(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["scale_next_batch"]["status"], "ready")
        self.assertEqual(checks["multi_target_manifest"]["status"], "not_requested")
        self.assertIn("scale_next_batch", rep["plans"])
        scale_json = rep["plans"]["scale_next_batch"]["plan_json"]
        self.assertEqual(scale_json["action"], "run_scale_batch")
        self.assertEqual(scale_json["target_id"], "1BRS_AD")
        self.assertNotIn("plan_text", scale_json)
        self.assertIn("GEN_T030=$(", rep["plan_text"])
        self.assertIn("complex_posthoc_bundle", rep["plan_text"])
        ordered = [step["id"] for step in rep["ordered_steps"]]
        self.assertIn("target_msa_precompute", ordered)
        self.assertIn("scale_next_batch", ordered)
        self.assertIn("scale_posthoc", ordered)
        self.assertIn("project_status_refresh", ordered)
        self.assertIn("ordered_steps", render_text(rep))

    def test_cli_can_emit_saved_scale_plan_for_completion_check(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "prepared.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            _write(msa, ">target\nAAAA\n")
            _write_target_fasta_report(pdb, fasta, chain="A")
            _write_target_msa_report(msa, fasta)
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": fasta,
                "target_msa": msa,
                "out_prefix": os.path.join(d, "planned", "1BRS_AD"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 100,
                },
            })

            with redirect_stdout(io.StringIO()):
                main([
                    "--decision", decision,
                    "--target-manifest", manifest,
                    "--scale-target-id", "1BRS_AD",
                    "--previous-records", "tests/fixtures/barstar_interface_records.jsonl",
                    "--require-files",
                    "--emit-scale-plan", scale_plan,
                ])

            with open(scale_plan) as fh:
                plan = json.load(fh)

        self.assertEqual(plan["action"], "run_scale_batch")
        self.assertEqual(plan["target_id"], "1BRS_AD")
        self.assertEqual(plan["target_alpha"], 0.2)
        self.assertIn("new_records", plan)
        self.assertIn("posthoc_command", plan)
        self.assertNotIn("plan_text", plan)

    def test_emit_scale_plan_requires_file_preflight_for_runnable_plan(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            readiness_json = os.path.join(d, "readiness.json")
            readiness_plan = os.path.join(d, "readiness.sh")
            _write_json(scale_plan, {
                "ok": True,
                "action": "run_scale_batch",
                "target_id": "keep_me",
            })
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "prepared_pdb": "prepared.pdb",
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": "target.fasta",
                "target_msa": "target.a3m",
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 100,
                },
            })

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--decision", decision,
                        "--target-manifest", manifest,
                        "--scale-target-id", "1BRS_AD",
                        "--out", readiness_json,
                        "--emit-plan", readiness_plan,
                        "--emit-scale-plan", scale_plan,
                    ])
            with open(scale_plan) as fh:
                plan = json.load(fh)

        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(plan["target_id"], "keep_me")
        self.assertFalse(os.path.exists(readiness_json))
        self.assertFalse(os.path.exists(readiness_plan))

    def test_allow_unchecked_files_marks_readiness_scale_plan_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            readiness_json = os.path.join(d, "readiness.json")
            readiness_plan = os.path.join(d, "readiness.sh")
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "prepared_pdb": "prepared.pdb",
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": "target.fasta",
                "target_msa": "target.a3m",
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 100,
                },
            })

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                main([
                    "--decision", decision,
                    "--target-manifest", manifest,
                    "--scale-target-id", "1BRS_AD",
                    "--allow-unchecked-files",
                    "--out", readiness_json,
                    "--emit-plan", readiness_plan,
                    "--emit-scale-plan", scale_plan,
                ])
            with open(scale_plan) as fh:
                saved_scale = json.load(fh)
            with open(readiness_json) as fh:
                saved_readiness = json.load(fh)
            with open(readiness_plan) as fh:
                readiness_text = fh.read()

        embedded = saved_readiness["plans"]["scale_next_batch"]["plan_json"]
        self.assertTrue(saved_scale["diagnostic_only"])
        self.assertTrue(embedded["diagnostic_only"])
        self.assertIn("without --require-files", saved_scale["diagnostic_reason"])
        self.assertIn("--allow-unchecked-files", saved_readiness["self_command"])
        self.assertIn("diagnostic only", readiness_text)

    def test_cli_overwrites_stale_scale_plan_with_unavailable_sentinel(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            readiness_json = os.path.join(d, "readiness.json")
            readiness_plan = os.path.join(d, "readiness.sh")
            _write_json(scale_plan, {
                "ok": True,
                "action": "run_scale_batch",
                "target_id": "stale",
                "records": ["stale.jsonl"],
                "new_records": ["stale.jsonl"],
                "posthoc_command": "python stale",
            })
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "rcsb_id": "1BRS",
                "source_pdb": os.path.join(d, "source_1BRS.pdb"),
                "prepared_pdb": os.path.join(d, "prepared_1BRS_AD.pdb"),
                "prep_report": os.path.join(d, "prepared_1BRS_AD.report.json"),
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": os.path.join(d, "1BRS_A.fasta"),
                "target_msa": os.path.join(d, "1BRS_A.a3m"),
                "out_prefix": os.path.join(d, "planned", "1BRS_AD"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 100,
                },
            })

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--decision", decision,
                        "--target-manifest", manifest,
                        "--scale-target-id", "1BRS_AD",
                        "--require-files",
                        "--out", readiness_json,
                        "--emit-plan", readiness_plan,
                        "--emit-scale-plan", scale_plan,
                    ])
            with open(scale_plan) as fh:
                plan = json.load(fh)
            with open(readiness_json) as fh:
                readiness = json.load(fh)
            with open(readiness_plan) as fh:
                plan_text = fh.read()

        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["action"], "unavailable")
        self.assertEqual(plan["status"], "waiting_on_input_prep")
        self.assertEqual(plan["target_id"], "1BRS_AD")
        self.assertEqual(plan["records"], [])
        self.assertEqual(plan["new_records"], [])
        self.assertNotIn("stale", json.dumps(plan))
        self.assertIn("readiness_command", plan)
        self.assertIn("--emit-scale-plan", plan["readiness_command"])
        self.assertIn("self_command", readiness)
        self.assertIn("--require-files", readiness["self_command"])
        self.assertNotIn("--batch-objective", readiness["self_command"])
        self.assertNotIn("--batch-lam", readiness["self_command"])
        self.assertNotIn("--batch-out", readiness["self_command"])
        self.assertNotIn("--batch-objective", plan["readiness_command"])
        self.assertIn("# rerun_readiness_after_prep", plan_text)
        self.assertIn(readiness["self_command"], plan_text)

    def test_emit_scale_plan_without_scale_check_does_not_clobber_existing_plan(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            _write_json(scale_plan, {
                "ok": True,
                "action": "run_scale_batch",
                "target_id": "keep_me",
            })
            _write_json(manifest, {"targets": [
                {
                    "id": "panel_a",
                    "prepared_pdb": "a.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "a.fasta",
                    "target_msa": "a.a3m",
                },
                {
                    "id": "panel_b",
                    "prepared_pdb": "b.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "b.fasta",
                    "target_msa": "b.a3m",
                },
                {
                    "id": "panel_c",
                    "prepared_pdb": "c.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "c.fasta",
                    "target_msa": "c.a3m",
                },
            ]})

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--target-manifest", manifest,
                        "--emit-scale-plan", scale_plan,
                    ])
            with open(scale_plan) as fh:
                plan = json.load(fh)

        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(plan["target_id"], "keep_me")
        self.assertEqual(plan["action"], "run_scale_batch")

    def test_scale_readiness_scopes_msa_plan_to_selected_target(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [
                {
                    "id": "1BRS_AD",
                    "prepared_pdb": "hpc_outputs/targets/prepared_1BRS_AD.pdb",
                    "target_chain": "A",
                    "binder_chain": "D",
                    "target_fasta": "hpc_outputs/targets/1BRS_A.fasta",
                    "target_msa": "hpc_outputs/targets/1BRS_A.a3m",
                    "out_prefix": "hpc_outputs/m6c_targets/1BRS_AD",
                },
                {
                    "id": "TARGET2_AB",
                    "prepared_pdb": "hpc_outputs/targets/prepared_TARGET2_AB.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "hpc_outputs/targets/TARGET2_A.fasta",
                    "target_msa": "hpc_outputs/targets/TARGET2_A.a3m",
                    "out_prefix": "hpc_outputs/m6c_targets/TARGET2_AB",
                },
            ]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 100,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="1BRS_AD",
            )

        msa_plan = rep["plans"]["target_msa_precompute"]["plan_text"]
        self.assertIn("# 1BRS_AD", msa_plan)
        self.assertIn("MSA_00_T_1BRS_AD=$(", msa_plan)
        self.assertNotIn("TARGET2_AB", msa_plan)
        self.assertNotIn("TARGET2_A", msa_plan)

    def test_emitted_scale_plan_feeds_scale_completion(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "prepared.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            scale_plan = os.path.join(d, "scale_plan.json")
            previous = os.path.join(d, "previous.jsonl")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            _write(msa, ">target\nAAAA\n")
            _write_target_fasta_report(pdb, fasta, chain="A")
            _write_target_msa_report(msa, fasta)
            _write(previous, json.dumps({
                "design_id": "old-1",
                "complex_target_id": "1BRS_AD",
            }) + "\n")
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": fasta,
                "target_msa": msa,
                "out_prefix": os.path.join(d, "planned", "1BRS_AD"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3, 0.5],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 200,
                },
            })

            with redirect_stdout(io.StringIO()):
                main([
                    "--decision", decision,
                    "--target-manifest", manifest,
                    "--scale-target-id", "1BRS_AD",
                    "--previous-records", previous,
                    "--require-files",
                    "--emit-scale-plan", scale_plan,
                ])
            with open(scale_plan) as fh:
                plan = json.load(fh)
            for i, record_path in enumerate(plan["new_records"]):
                _write(record_path, json.dumps({
                    "design_id": f"new-{i}",
                    "complex_target_id": "1BRS_AD",
                }) + "\n")

            completion = run_completion(scale_plan, out_path=os.path.join(d, "completion.json"))

        self.assertTrue(completion["ok"])
        self.assertEqual(completion["status"], "ready_for_posthoc")
        self.assertEqual(completion["target_id"], "1BRS_AD")
        self.assertEqual(len(completion["expected_new_records"]), 2)
        self.assertIn("target-id aligned", completion["shell_plan"])

    def test_scale_plan_blocks_on_bad_target_msa_when_files_required(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "target.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            _write(msa, ">target\nAAAT\n")
            _write_target_fasta_report(pdb, fasta, chain="A")
            _write_target_msa_report(msa, fasta)
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [{
                "id": "bad_msa",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="bad_msa",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["status"], "blocked")
        self.assertIn("target_msa_mismatch", scale["message"])
        self.assertEqual(scale["details"]["target_id"], "bad_msa")
        self.assertEqual(scale["details"]["failures_by_kind"]["target_msa_mismatch"], 1)
        self.assertEqual(scale["details"]["failures"][0]["kind"], "target_msa_mismatch")
        text = render_text(rep)
        self.assertIn("failures:", text)
        self.assertIn("target_msa_mismatch target=bad_msa", text)
        self.assertIn("target_msa query sequence does not match", text)
        self.assertIn("# blockers", rep["plan_text"])
        self.assertIn("# - target_msa_mismatch target=bad_msa", rep["plan_text"])

    def test_scale_plan_waits_on_generated_input_prep_plan(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [{
                "id": "1BRS_AD",
                "rcsb_id": "1BRS",
                "source_pdb": os.path.join(d, "source_1BRS.pdb"),
                "prepared_pdb": os.path.join(d, "prepared_1BRS_AD.pdb"),
                "prep_report": os.path.join(d, "prepared_1BRS_AD.report.json"),
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": os.path.join(d, "1BRS_A.fasta"),
                "target_msa": os.path.join(d, "1BRS_A.a3m"),
                "out_prefix": os.path.join(d, "out"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="1BRS_AD",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "waiting_on_input_prep")
        self.assertIn("target_msa_precompute", rep["next_action"])
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["status"], "waiting_on_input_prep")
        self.assertTrue(scale["details"]["input_prep_plan_available"])
        self.assertEqual(scale["details"]["failures"][0]["field"], "source_pdb")
        self.assertIn("curl -fsSL https://files.rcsb.org/download/1BRS.pdb", rep["plan_text"])
        self.assertIn("prep_hetdimer.py", rep["plan_text"])
        self.assertIn("scale_next_batch status=waiting_on_input_prep", rep["plan_text"])

    def test_missing_target_msa_report_is_repairable_input_prep(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "target.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            msa_report = os.path.join(d, "target.a3m.report.json")
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            _write(msa, ">target\nAAAA\n")
            _write_target_fasta_report(pdb, fasta, chain="A")
            _write_json(manifest, {"targets": [{
                "id": "needs_msa_report",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "target_msa_report": msa_report,
                "out_prefix": os.path.join(d, "out"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="needs_msa_report",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "waiting_on_input_prep")
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["details"]["failures"][0]["field"], "target_msa_report")
        plan_text = rep["plans"]["target_msa_precompute"]["plan_text"]
        self.assertIn("REPORT=", plan_text)
        self.assertIn(f"if [ -s {msa} ]; then", plan_text)
        self.assertIn("target MSA exists; validating and refreshing report", plan_text)
        self.assertIn(
            f"\"$PYTHON_BIN\" hpc/precompute_boltz_target_msa.py --fasta {fasta} --out {msa} --report {msa_report}",
            plan_text,
        )
        self.assertIn("sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch", plan_text)

    def test_stale_target_fasta_report_is_repairable_input_prep(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "target.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            _write_json(fasta + ".report.json", {
                "pdb": os.path.abspath(pdb),
                "chain": "A",
                "length": 4,
                "sequence": "AAAA",
                "out": os.path.abspath(fasta),
            })
            _write_json(manifest, {"targets": [{
                "id": "needs_fasta_report_refresh",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "out_prefix": os.path.join(d, "out"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="needs_fasta_report_refresh",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "waiting_on_input_prep")
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["status"], "waiting_on_input_prep")
        self.assertTrue(scale["details"]["input_prep_plan_available"])
        self.assertEqual(scale["details"]["failures_by_kind"]["target_fasta_report_missing_field"], 2)
        self.assertIn({"target_id": "needs_fasta_report_refresh", "field": "target_msa_report",
                       "path": msa + ".report.json"}, scale["details"]["input_prep_artifacts"])
        plan_text = rep["plans"]["target_msa_precompute"]["plan_text"]
        self.assertIn("extract_chain_fasta.py", plan_text)
        self.assertIn(f"--report {fasta}.report.json", plan_text)

    def test_missing_source_without_rcsb_id_is_hard_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [{
                "id": "manual_source",
                "source_pdb": os.path.join(d, "source_manual.pdb"),
                "prepared_pdb": os.path.join(d, "prepared_manual.pdb"),
                "prep_report": os.path.join(d, "prepared_manual.report.json"),
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": os.path.join(d, "manual_A.fasta"),
                "target_msa": os.path.join(d, "manual_A.a3m"),
                "out_prefix": os.path.join(d, "out"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="manual_source",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "blocked")
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["status"], "blocked")
        self.assertFalse(scale["details"]["input_prep_plan_available"])
        self.assertIn("Missing source PDB", rep["plan_text"])
        self.assertNotIn("scale_next_batch status=waiting_on_input_prep", rep["plan_text"])

    def test_missing_prepared_without_source_path_is_hard_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            fasta = os.path.join(d, "target.fasta")
            _write(fasta, ">target\nAAAA\n")
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {"targets": [{
                "id": "no_source",
                "prepared_pdb": os.path.join(d, "prepared_missing.pdb"),
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": os.path.join(d, "target.a3m"),
                "out_prefix": os.path.join(d, "out"),
            }]})
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            rep = run_readiness(
                decision_path=decision,
                target_manifest_path=manifest,
                scale_target_id="no_source",
                require_files=True,
            )

        self.assertFalse(rep["ok"])
        scale = [c for c in rep["checks"] if c["name"] == "scale_next_batch"][0]
        self.assertEqual(scale["status"], "blocked")
        self.assertFalse(scale["details"]["input_prep_plan_available"])
        self.assertEqual(scale["details"]["failures"][0]["field"], "prepared_pdb")

    def test_panel_preflight_allows_planned_records_paths_before_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for i in range(3):
                tid = f"panel_{i}"
                pdb = os.path.join(d, f"{tid}.pdb")
                fasta = os.path.join(d, f"{tid}.fasta")
                msa = os.path.join(d, f"{tid}.a3m")
                _write(pdb, "ATOM\n")
                _write(fasta, ">target\nAAAA\n")
                _write(msa, ">target\nAAAA\n")
                _write_target_fasta_report(pdb, fasta, chain="A")
                _write_target_msa_report(msa, fasta)
                targets.append({
                    "id": tid,
                    "prepared_pdb": pdb,
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": fasta,
                    "target_msa": msa,
                    "records": os.path.join(d, "planned", tid, "records.jsonl"),
                    "out_prefix": os.path.join(d, "planned", tid),
                })
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": targets})

            rep = run_readiness(target_manifest_path=manifest, require_files=True)

        self.assertTrue(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["multi_target_manifest"]["status"], "ready")
        self.assertIn("multi_target_panel", rep["plans"])
        self.assertIn("run_generate_proteinmpnn_complex.sbatch", rep["plan_text"])
        ordered = [step["id"] for step in rep["ordered_steps"]]
        self.assertIn("panel_completion", ordered)
        panel_completion = [step for step in rep["ordered_steps"] if step["id"] == "panel_completion"][0]
        self.assertEqual(panel_completion["depends_on"], ["multi_target_panel"])

    def test_missing_target_msa_waits_on_precompute_plan(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "target.pdb")
            fasta = os.path.join(d, "target.fasta")
            msa = os.path.join(d, "target.a3m")
            _write(pdb, "ATOM\n")
            _write(fasta, ">target\nAAAA\n")
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": [{
                "id": "needs_msa",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "out_prefix": os.path.join(d, "out"),
            }]})

            rep = run_readiness(
                target_manifest_path=manifest,
                require_files=True,
                panel_min_targets=1,
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["status"], "waiting_on_input_prep")
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["multi_target_manifest"]["status"], "waiting_on_input_prep")
        self.assertIn("target_msa_precompute", rep["plans"])
        self.assertIn("run_precompute_boltz_target_msa.sbatch", rep["plan_text"])
        self.assertIn("OUT=", rep["plan_text"])
        self.assertEqual(rep["ordered_steps"][0]["id"], "target_msa_precompute")
        panel_steps = [s for s in rep["ordered_steps"] if s["id"] == "multi_target_panel"]
        self.assertEqual(panel_steps[0]["status"], "waiting_on_input_prep")
        self.assertEqual(panel_steps[0]["depends_on"], ["target_msa_precompute"])
        text = render_text(rep)
        self.assertIn("missing_file target=needs_msa", text)
        self.assertIn("target_msa does not exist", text)
        self.assertIn("# - missing_file target=needs_msa", rep["plan_text"])

    def test_second_predictor_contract_blocks_when_required_files_missing(self):
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "boltz.jsonl")
            secondary = os.path.join(d, "missing_chai.jsonl")
            contract_path = os.path.join(d, "contract.json")
            _write(primary, json.dumps(_complex_record(
                0,
                predictor="boltz2_complex",
                signal="boltz2_pae_interaction",
                label="boltz2_lrmsd_to_reference",
            )) + "\n")
            _write_json(contract_path, {
                "primary_records": [primary],
                "secondary_records": [secondary],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                    "forbid_predictor_ids": ["boltz2_complex"],
                },
                "qc": {
                    "require_complex_target_id": True,
                    "require_provenance": True,
                    "require_chain_ids": True,
                },
                "cross_predictor": {
                    "min_overlap": 20,
                    "min_label_agreement": 0.8,
                    "require_disjoint_record_files": True,
                },
            })

            rep = run_readiness(
                second_predictor_contract_path=contract_path,
                require_files=True,
                run_second_record_qc=True,
            )
        self.assertFalse(rep["ok"])
        contract = [c for c in rep["checks"] if c["name"] == "second_predictor_contract"][0]
        self.assertEqual(contract["status"], "blocked")
        self.assertIn("missing_file", contract["message"])
        text = render_text(rep)
        self.assertIn("missing_file field=secondary_records", text)
        self.assertIn("# - missing_file field=secondary_records", rep["plan_text"])
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_second_predictor_ready_orders_cross_predictor_and_status_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "boltz.jsonl")
            secondary = os.path.join(d, "chai.jsonl")
            contract = os.path.join(d, "contract.json")
            _write(primary, json.dumps(_complex_record(
                0,
                predictor="boltz2_complex",
                signal="boltz2_pae_interaction",
                label="boltz2_lrmsd_to_reference",
            )) + "\n")
            _write(secondary, json.dumps(_complex_record(0)) + "\n")
            _write_json(contract, {
                "primary_records": [primary],
                "secondary_records": [secondary],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                    "forbid_predictor_ids": ["boltz2_complex"],
                },
                "cross_predictor": {
                    "min_overlap": 1,
                    "min_label_agreement": 0.8,
                    "out": os.path.join(d, "cross.json"),
                    "emit_matches": os.path.join(d, "matches.jsonl"),
                },
            })

            rep = run_readiness(
                second_predictor_contract_path=contract,
                require_files=True,
                run_second_record_qc=True,
            )

        self.assertTrue(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["second_predictor_contract"]["status"], "ready")
        steps = {step["id"]: step for step in rep["ordered_steps"]}
        self.assertEqual(steps["second_predictor_contract"]["status"], "ready")
        self.assertEqual(steps["cross_predictor_report"]["status"], "after_contract")
        self.assertEqual(steps["cross_predictor_report"]["depends_on"], ["second_predictor_contract"])
        self.assertIn("project_status_refresh", steps)
        self.assertEqual(steps["project_status_refresh"]["depends_on"], ["cross_predictor_report"])
        self.assertIn("complex_cross_predictor", rep["plan_text"])
        self.assertNotIn("# Downstream commands are commented", rep["plan_text"])

    def test_closed_loop_batch_ready_orders_batch_and_status_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            records = os.path.join(d, "records.jsonl")
            verdicts = os.path.join(d, "verdicts.jsonl")
            out = os.path.join(d, "round_0")
            sync_back = os.path.join(d, "w4_sync_back.sh")
            rows = [
                _complex_record(
                    i,
                    predictor="boltz2_complex",
                    signal="boltz2_pae_interaction",
                    label="boltz2_lrmsd_to_reference",
                )
                for i in range(2)
            ]
            _write(candidates, "".join(
                json.dumps({
                    "id": row["target_id"],
                    "representation": row["target_id"],
                    "regime": "complex",
                    "meta": {"complex_target_id": row["complex_target_id"]},
                }) + "\n"
                for row in rows
            ))
            _write(records, "".join(json.dumps(row) + "\n" for row in rows))
            _write(verdicts, "".join(
                json.dumps({"id": row["target_id"], "flag": False, "reason": ""}) + "\n"
                for row in rows
            ))

            rep = run_readiness(
                batch_candidates_path=candidates,
                batch_records_path=records,
                batch_verdicts_path=verdicts,
                batch_target="benign barnase-barstar interface trust-routing evaluation",
                batch_objective="interface_quality",
                batch_out_dir=out,
                batch_prevalidate_records=["tests/fixtures/barstar_interface_records.jsonl"],
                batch_conformal_alpha=0.3,
                batch_sync_back_plan=sync_back,
            )

        self.assertTrue(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["closed_loop_batch"]["status"], "ready")
        self.assertEqual(checks["closed_loop_batch"]["details"]["n_candidates"], 2)
        self.assertTrue(checks["closed_loop_batch"]["details"]["gate_prevalidation"]["ok"])
        self.assertTrue(
            checks["closed_loop_batch"]["details"]["gate_prevalidation"]["batch_contract"]["ok"]
        )
        self.assertEqual(checks["closed_loop_batch"]["details"]["sync_back_plan"], sync_back)
        steps = {step["id"]: step for step in rep["ordered_steps"]}
        self.assertEqual(steps["closed_loop_batch"]["status"], "ready")
        self.assertEqual(steps["closed_loop_batch"]["depends_on"], [])
        self.assertEqual(steps["project_status_refresh"]["depends_on"], ["closed_loop_batch"])
        self.assertIn("run_batch_round", rep["plan_text"])
        self.assertIn("--strict-complex-records", rep["plan_text"])
        self.assertIn("--prevalidate-records", rep["plan_text"])
        self.assertIn("--conformal-alpha 0.3", rep["plan_text"])
        self.assertIn("--emit-sync-back-plan", rep["plan_text"])
        self.assertIn(sync_back, rep["plan_text"])

    def test_closed_loop_batch_blocks_conformal_alpha_without_prevalidation_records(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            records = os.path.join(d, "records.jsonl")
            verdicts = os.path.join(d, "verdicts.jsonl")
            rows = [_complex_record(i) for i in range(2)]
            _write(candidates, "".join(
                json.dumps({
                    "id": row["target_id"],
                    "representation": row["target_id"],
                    "regime": "complex",
                    "meta": {"complex_target_id": row["complex_target_id"]},
                }) + "\n"
                for row in rows
            ))
            _write(records, "".join(json.dumps(row) + "\n" for row in rows))
            _write(verdicts, "".join(
                json.dumps({"id": row["target_id"], "flag": False, "reason": ""}) + "\n"
                for row in rows
            ))

            rep = run_readiness(
                batch_candidates_path=candidates,
                batch_records_path=records,
                batch_verdicts_path=verdicts,
                batch_target="benign barnase-barstar interface trust-routing evaluation",
                batch_objective="interface_quality",
                batch_conformal_alpha=0.3,
            )

        self.assertFalse(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["closed_loop_batch"]["status"], "blocked")
        failures = checks["closed_loop_batch"]["details"]["failures"]
        self.assertIn("gate_prevalidation_blocked", {f["kind"] for f in failures})
        nested = failures[0]["failures"]
        self.assertIn("missing_prevalidation_records", {f["kind"] for f in nested})

    def test_closed_loop_batch_missing_jsonl_preserves_pending_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = "hpc_outputs/__test_missing_w4_candidates__.jsonl"
            records = "hpc_outputs/__test_missing_w4_records__.jsonl"
            sync_back = os.path.join(d, "w4_sync_back.sh")
            self.assertFalse(os.path.exists(candidates))
            self.assertFalse(os.path.exists(records))

            rep = run_readiness(
                batch_candidates_path=candidates,
                batch_records_path=records,
                batch_target="benign barnase-barstar interface trust-routing evaluation",
                batch_sync_back_plan=sync_back,
            )

        self.assertFalse(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        batch = checks["closed_loop_batch"]
        self.assertEqual(batch["status"], "blocked")
        self.assertEqual(batch["details"]["sync_back_plan"], sync_back)
        self.assertEqual(
            {a["path"] for a in batch["details"]["pending_artifacts"]},
            {candidates, records},
        )
        self.assertNotIn("run_batch_round", rep["plan_text"])
        self.assertIn("missing_batch_artifact", rep["plan_text"])
        self.assertIn(f"# sync_back: bash {sync_back}", rep["plan_text"])

    def test_closed_loop_batch_blocks_when_candidate_complex_target_missing(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = os.path.join(d, "candidates.jsonl")
            records = os.path.join(d, "records.jsonl")
            verdicts = os.path.join(d, "verdicts.jsonl")
            rows = [_complex_record(i) for i in range(2)]
            _write(candidates, "".join(
                json.dumps({
                    "id": row["target_id"],
                    "representation": row["target_id"],
                    "regime": "complex",
                }) + "\n"
                for row in rows
            ))
            _write(records, "".join(json.dumps(row) + "\n" for row in rows))
            _write(verdicts, "".join(
                json.dumps({"id": row["target_id"], "flag": False, "reason": ""}) + "\n"
                for row in rows
            ))

            rep = run_readiness(
                batch_candidates_path=candidates,
                batch_records_path=records,
                batch_verdicts_path=verdicts,
                batch_target="benign barnase-barstar interface trust-routing evaluation",
            )

        self.assertFalse(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["closed_loop_batch"]["status"], "blocked")
        failures = checks["closed_loop_batch"]["details"]["failures"]
        self.assertIn("missing_complex_target_id", {f["kind"] for f in failures})
        steps = {step["id"]: step for step in rep["ordered_steps"]}
        self.assertNotIn("project_status_refresh", steps)
        self.assertNotIn("run_batch_round", rep["plan_text"])
        self.assertIn("# - missing_complex_target_id", rep["plan_text"])

    def test_existing_batch_preflight_artifact_is_reflected_in_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            _write_json(preflight, {
                "ok": False,
                "n_candidates": 2,
                "strict_complex_records": True,
                "failures": [{"kind": "missing_screen_verdict", "ids": ["design-1"]}],
            })

            rep = run_readiness(batch_preflight_path=preflight)

        self.assertFalse(rep["ok"])
        checks = {c["name"]: c for c in rep["checks"]}
        self.assertEqual(checks["closed_loop_artifacts"]["status"], "batch_preflight_blocked")
        self.assertIn("missing_screen_verdict",
                      {f["kind"] for f in checks["closed_loop_artifacts"]["details"]["failures"]})
        self.assertIn("missing_screen_verdict", rep["plan_text"])

    def test_self_command_preserves_batch_defaults_only_with_batch_context(self):
        with tempfile.TemporaryDirectory() as d:
            preflight = os.path.join(d, "preflight.json")
            readiness_json = os.path.join(d, "readiness.json")
            readiness_plan = os.path.join(d, "readiness.sh")
            _write_json(preflight, {
                "ok": False,
                "n_candidates": 2,
                "strict_complex_records": True,
                "failures": [{"kind": "missing_screen_verdict", "ids": ["design-1"]}],
            })

            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--batch-preflight", preflight,
                        "--out", readiness_json,
                        "--emit-plan", readiness_plan,
                    ])
            with open(readiness_json) as fh:
                readiness = json.load(fh)
            with open(readiness_plan) as fh:
                plan_text = fh.read()

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--batch-preflight", readiness["self_command"])
        self.assertIn("--batch-objective interface_quality", readiness["self_command"])
        self.assertIn("--batch-lam 0.5", readiness["self_command"])
        self.assertIn("--batch-out results/round_0", readiness["self_command"])
        self.assertIn(readiness["self_command"], plan_text)

    def test_cli_self_command_preserves_input_prep_completion(self):
        with tempfile.TemporaryDirectory() as d:
            completion = os.path.join(d, "input prep completion.json")
            readiness_json = os.path.join(d, "readiness.json")
            readiness_plan = os.path.join(d, "readiness.sh")
            _write_json(completion, {
                "ok": False,
                "status": "blocked",
                "n_artifacts": 1,
                "n_present": 0,
                "n_nonempty": 0,
                "n_missing": 1,
                "n_empty": 0,
                "ready_targets": [],
                "blocked_targets": ["t0"],
                "pending_artifacts": [
                    {"target_id": "t0", "field": "target_msa", "path": "target.a3m", "error": "missing_file"},
                ],
                "artifacts_by_target": {"t0": {"ready": False}},
            })

            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--input-prep-completion", completion,
                        "--out", readiness_json,
                        "--emit-plan", readiness_plan,
                    ])
            with open(readiness_json) as fh:
                readiness = json.load(fh)
            with open(readiness_plan) as fh:
                plan_text = fh.read()

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--input-prep-completion", readiness["self_command"])
        self.assertIn("input prep completion.json'", readiness["self_command"])
        self.assertIn(readiness["self_command"], plan_text)


if __name__ == "__main__":
    unittest.main()
