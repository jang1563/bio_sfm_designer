"""Tests for rendering next-batch Cayuga commands from alpha decisions."""

import io
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from bio_sfm_designer.experiments.complex_next_batch_plan import (
    TargetPreflightError,
    build_next_batch_plan,
    main,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


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


class ComplexNextBatchPlanTests(unittest.TestCase):
    def test_renders_temp_specific_generate_and_predict_commands(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "defaults": {"seed": 99, "objective": "scale"},
                "targets": [{
                    "id": "1BRS_AD",
                    "prepared_pdb": "hpc_outputs/targets/prepared_1BRS_AD.pdb",
                    "target_chain": "A",
                    "binder_chain": "D",
                    "target_fasta": "hpc_outputs/targets/1BRS_A.fasta",
                    "target_msa": "hpc_outputs/targets/1BRS_A.a3m",
                    "out_prefix": "hpc_outputs/m6c_targets/1BRS_AD",
                }]
            })
            _write_json(decision, {
                "decision": "continue_scale",
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3, 0.5, 0.7],
                    "num_seq_per_temperature": 100,
                    "recommended_total_candidates": 300,
                },
            })

            plan = build_next_batch_plan(
                manifest_path=manifest,
                decision_path=decision,
                target_id="1BRS_AD",
                previous_records=["tests/fixtures/barstar_interface_records.jsonl"],
                posthoc_out_dir="results/m6c_posthoc_next",
            )

            self.assertEqual(plan["action"], "run_scale_batch")
            self.assertEqual(len(plan["commands"]), 3)
            self.assertEqual(len(set(plan["new_records"])), 3)
            self.assertEqual(plan["seed"], "99")
            self.assertEqual(plan["objective"], "scale")
            self.assertIn("COMPLEX_ID=1BRS_AD", plan["commands"][0]["generate_command"])
            self.assertEqual(plan["batch_namespace"], "1BRS_AD")
            self.assertEqual(plan["commands"][0]["id_prefix"], "scale-mpnnX-1BRS_AD-1BRS_AD-t030")
            self.assertIn("ID_PREFIX=scale-mpnnX-1BRS_AD-1BRS_AD-t030", plan["commands"][0]["generate_command"])
            self.assertIn("SEED=99", plan["commands"][0]["generate_command"])
            self.assertIn("OBJECTIVE=scale", plan["commands"][0]["generate_command"])
            self.assertIn("COMPLEX_ID=1BRS_AD", plan["commands"][0]["predict_command"])
            text = plan["plan_text"]
            self.assertIn("GEN_T030=$(", text)
            self.assertIn("TEMP=0.3", text)
            self.assertIn("ID_PREFIX=scale-mpnnX-1BRS_AD-1BRS_AD-t030", text)
            self.assertIn("NUM_SEQ=100", text)
            self.assertIn("candidates_proteinmpnn_complex_t030.jsonl", text)
            self.assertIn("records_boltz_complex_t070.jsonl", text)
            self.assertIn("sbatch --dependency=afterok:${GEN_T030}", text)
            self.assertIn("COMPLEX_ID=1BRS_AD", text)
            self.assertIn("TARGET_MSA=hpc_outputs/targets/1BRS_A.a3m", text)
            self.assertIn("complex_posthoc_bundle", text)
            self.assertIn("--require-complex-target-id --require-provenance --require-chain-ids", text)
            self.assertIn("tests/fixtures/barstar_interface_records.jsonl", text)
            self.assertIn("results/m6c_posthoc_next", text)
            self.assertIn("# python -m bio_sfm_designer.experiments.complex_posthoc_bundle", text)
            self.assertNotIn("\npython -m bio_sfm_designer.experiments.complex_posthoc_bundle", text)
            self.assertTrue(plan["strict_qc"])

    def test_require_files_runs_selected_target_preflight(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "good.pdb")
            fasta = os.path.join(d, "good.fasta")
            msa = os.path.join(d, "good.a3m")
            with open(pdb, "w") as fh:
                fh.write("ATOM\n")
            with open(fasta, "w") as fh:
                fh.write(">target\nAAAA\n")
            with open(msa, "w") as fh:
                fh.write(">target\nAAAA\n")
            _write_target_fasta_report(pdb, fasta)
            _write_target_msa_report(msa, fasta)
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "targets": [
                    {
                        "id": "good",
                        "prepared_pdb": pdb,
                        "target_chain": "A",
                        "binder_chain": "B",
                        "target_fasta": fasta,
                        "target_msa": msa,
                        "out_prefix": os.path.join(d, "out"),
                    },
                    {
                        "id": "bad_placeholder",
                        "prepared_pdb": "missing.pdb",
                        "target_chain": "A",
                        "binder_chain": "B",
                        "target_fasta": "missing.fasta",
                        "target_msa": "missing.a3m",
                    },
                ]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            plan = build_next_batch_plan(
                manifest_path=manifest,
                decision_path=decision,
                target_id="good",
                require_files=True,
            )
            self.assertTrue(plan["preflight"]["ok"])
            self.assertEqual(plan["preflight"]["ready_targets"], ["good"])
            self.assertIn("selected-target preflight ok=True require_files=True", plan["plan_text"])
            self.assertIn("complex_target_manifest --manifest", plan["plan_text"])
            self.assertIn("--target-id good", plan["plan_text"])
            self.assertIn("--require-files", plan["plan_text"])
            self.assertIn("--min-contacts 1", plan["plan_text"])
            self.assertIn("records_boltz_complex_t030.jsonl", plan["plan_text"])

    def test_require_files_blocks_bad_target_msa(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "good.pdb")
            fasta = os.path.join(d, "good.fasta")
            msa = os.path.join(d, "bad.a3m")
            with open(pdb, "w") as fh:
                fh.write("ATOM\n")
            with open(fasta, "w") as fh:
                fh.write(">target\nAAAA\n")
            with open(msa, "w") as fh:
                fh.write(">target\nAAAT\n")
            _write_target_fasta_report(pdb, fasta)
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
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            with self.assertRaisesRegex(TargetPreflightError, "target_msa_mismatch") as ctx:
                build_next_batch_plan(
                    manifest_path=manifest,
                    decision_path=decision,
                    target_id="bad_msa",
                    require_files=True,
                )
            self.assertEqual(ctx.exception.target_id, "bad_msa")
            self.assertEqual(ctx.exception.preflight_report["failures_by_kind"]["target_msa_mismatch"], 1)

    def test_quotes_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "targets": [{
                    "id": "spacey",
                    "prepared_pdb": "/tmp/prepared target.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "/tmp/target fasta.fa",
                    "target_msa": "/tmp/target msa.a3m",
                    "out_prefix": "/tmp/out prefix",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            text = build_next_batch_plan(
                manifest_path=manifest,
                decision_path=decision,
                target_id="spacey",
            )["plan_text"]
            self.assertIn("PDB='/tmp/prepared target.pdb'", text)
            self.assertIn("TARGET_MSA='/tmp/target msa.a3m'", text)
            self.assertIn("COMPLEX_ID=spacey", text)
            self.assertIn("mkdir -p '/tmp/out prefix'", text)
            self.assertIn("--require-complex-target-id --require-provenance --require-chain-ids", text)

    def test_scale_plan_requires_strict_decision_qc_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "targets": [{
                    "id": "legacy",
                    "prepared_pdb": "prepared.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "target.fa",
                    "target_msa": "target.a3m",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            with self.assertRaisesRegex(ValueError, "missing qc"):
                build_next_batch_plan(
                    manifest_path=manifest,
                    decision_path=decision,
                    target_id="legacy",
                )

    def test_no_strict_qc_allows_legacy_decision_explicitly(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "targets": [{
                    "id": "legacy",
                    "prepared_pdb": "prepared.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "target.fa",
                    "target_msa": "target.a3m",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            plan = build_next_batch_plan(
                manifest_path=manifest,
                decision_path=decision,
                target_id="legacy",
                strict_qc=False,
            )
            self.assertFalse(plan["strict_qc"])
            self.assertNotIn("--require-complex-target-id", plan["posthoc_command"])

    def test_cli_refuses_to_save_runnable_plan_without_file_preflight(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            out = os.path.join(d, "next_batch.json")
            _write_json(out, {"ok": True, "action": "run_scale_batch", "target_id": "keep_me"})
            _write_json(manifest, {
                "targets": [{
                    "id": "1BRS_AD",
                    "prepared_pdb": "prepared.pdb",
                    "target_chain": "A",
                    "binder_chain": "D",
                    "target_fasta": "target.fa",
                    "target_msa": "target.a3m",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([
                        "--manifest", manifest,
                        "--decision", decision,
                        "--target-id", "1BRS_AD",
                        "--out", out,
                    ])
            with open(out) as fh:
                saved = json.load(fh)

        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(saved["target_id"], "keep_me")

    def test_cli_allow_unchecked_files_marks_saved_plan_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            out = os.path.join(d, "next_batch.json")
            shell_plan = os.path.join(d, "next_batch.sh")
            _write_json(manifest, {
                "targets": [{
                    "id": "1BRS_AD",
                    "prepared_pdb": "prepared.pdb",
                    "target_chain": "A",
                    "binder_chain": "D",
                    "target_fasta": "target.fa",
                    "target_msa": "target.a3m",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.2,
                "qc": _strict_qc(),
                "next_batch": {
                    "action": "run_scale_batch",
                    "temperatures": [0.3],
                    "num_seq_per_temperature": 20,
                    "recommended_total_candidates": 20,
                },
            })

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                main([
                    "--manifest", manifest,
                    "--decision", decision,
                    "--target-id", "1BRS_AD",
                    "--allow-unchecked-files",
                    "--out", out,
                    "--emit-plan", shell_plan,
                ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(shell_plan) as fh:
                text = fh.read()

        self.assertTrue(saved["diagnostic_only"])
        self.assertTrue(saved["unchecked_files_allowed"])
        self.assertIn("without --require-files", saved["diagnostic_reason"])
        self.assertIn("diagnostic only", text)

    def test_non_scale_decision_emits_no_commands(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            decision = os.path.join(d, "decision.json")
            _write_json(manifest, {
                "targets": [{
                    "id": "1BRS_AD",
                    "prepared_pdb": "prepared.pdb",
                    "target_chain": "A",
                    "binder_chain": "D",
                    "target_fasta": "target.fa",
                    "target_msa": "target.a3m",
                }]
            })
            _write_json(decision, {
                "target_alpha": 0.3,
                "next_batch": {"action": "none", "recommended_total_candidates": 0},
            })

            plan = build_next_batch_plan(
                manifest_path=manifest,
                decision_path=decision,
                target_id="1BRS_AD",
            )
            self.assertEqual(plan["action"], "none")
            self.assertEqual(plan["commands"], [])
            self.assertIn("no scale batch emitted", plan["plan_text"])


if __name__ == "__main__":
    unittest.main()
