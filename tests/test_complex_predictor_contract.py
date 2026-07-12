"""Tests for second-predictor contract validation."""

import json
import os
import subprocess
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_predictor_contract import (
    main,
    render_sync_back_plan,
    validate_contract,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _record(i, predictor="chai1_complex", signal="chai1_pae_interaction",
            label="chai1_lrmsd_to_reference"):
    return {
        "target_id": f"design-{i}",
        "complex_target_id": "toy",
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


def _write_missing_secondary_contract(path, secondary_records=None):
    secondary_records = secondary_records or [
        "hpc_outputs/m6c_second_predictor/test_missing_chai_complex_records.jsonl"
    ]
    _write_json(path, {
        "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
        "secondary_records": secondary_records,
        "secondary_predictor": {
            "predictor_id": "chai1_complex",
            "signal_source": "chai1_pae_interaction",
            "label_source": "chai1_lrmsd_to_reference",
            "forbid_predictor_ids": ["boltz2_complex"],
        },
    })
    return secondary_records


class ComplexPredictorContractTests(unittest.TestCase):
    def test_template_shape_emits_reproducible_commands_without_files(self):
        rep = validate_contract("configs/template_second_predictor_contract.json")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["secondary_predictor"]["predictor_id"], "chai1_complex")
        self.assertIn("--expect-predictor-id chai1_complex", rep["commands"]["secondary_qc"])
        self.assertIn("--forbid-predictor-id boltz2_complex", rep["commands"]["secondary_qc"])
        self.assertIn("complex_cross_predictor", rep["commands"]["cross_predictor"])
        self.assertEqual(rep["cross_predictor"]["copy_tolerance"], 1e-6)
        self.assertEqual(rep["cross_predictor"]["copy_fraction_threshold"], 0.95)
        self.assertEqual(rep["cross_predictor"]["label_threshold_tolerance"], 1e-9)
        self.assertEqual(rep["cross_predictor"]["min_overlap"], 20)
        self.assertEqual(rep["cross_predictor"]["min_label_agreement"], 0.8)
        self.assertTrue(rep["cross_predictor"]["require_disjoint_record_files"])
        self.assertIn("--min-overlap 20", rep["commands"]["cross_predictor"])
        self.assertIn("--min-label-agreement 0.8", rep["commands"]["cross_predictor"])
        self.assertIn("--copy-tolerance 1e-06", rep["commands"]["cross_predictor"])
        self.assertIn("--copy-fraction-threshold 0.95", rep["commands"]["cross_predictor"])
        self.assertIn("--label-threshold-tolerance 1e-09", rep["commands"]["cross_predictor"])
        self.assertIn("--require-disjoint-record-files", rep["commands"]["cross_predictor"])
        self.assertIn("set -euo pipefail", rep["plan_text"])
        self.assertIn("complex_predictor_contract --contract", rep["plan_text"])
        self.assertNotIn("# blockers", rep["plan_text"])

    def test_require_files_and_record_qc_accept_expected_second_predictor(self):
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "boltz.jsonl")
            secondary = os.path.join(d, "chai.jsonl")
            contract = os.path.join(d, "contract.json")
            with open(primary, "w") as fh:
                fh.write(json.dumps(_record(0, predictor="boltz2_complex",
                                            signal="boltz2_pae_interaction",
                                            label="boltz2_lrmsd_to_reference")) + "\n")
            with open(secondary, "w") as fh:
                fh.write(json.dumps(_record(0)) + "\n")
            _write_json(contract, {
                "primary_records": [primary],
                "secondary_records": [secondary],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                    "forbid_predictor_ids": ["boltz2_complex"],
                },
                "cross_predictor": {"min_overlap": 1, "min_label_agreement": 0.8,
                                    "copy_tolerance": 1e-5,
                                    "copy_fraction_threshold": 0.9,
                                    "label_threshold_tolerance": 1e-8},
            })

            rep = validate_contract(contract, require_files=True, run_record_qc=True)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["secondary_records_qc"]["ok"])
        self.assertEqual(rep["secondary_records_qc"]["expect_predictor_id"], "chai1_complex")
        self.assertIn("--require-files", rep["plan_text"])
        self.assertIn("--run-record-qc", rep["plan_text"])
        self.assertIn("complex_records_qc", rep["plan_text"])
        self.assertIn("complex_cross_predictor", rep["plan_text"])
        self.assertIn("--copy-tolerance 1e-05", rep["commands"]["cross_predictor"])
        self.assertIn("--copy-fraction-threshold 0.9", rep["commands"]["cross_predictor"])
        self.assertIn("--label-threshold-tolerance 1e-08", rep["commands"]["cross_predictor"])
        self.assertIn("--require-disjoint-record-files", rep["commands"]["cross_predictor"])

    def test_bad_min_overlap_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"min_overlap": 0},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("min_overlap", rep["plan_text"])
        self.assertIn("min_overlap", {f["field"] for f in rep["failures"]})
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_bad_require_disjoint_record_files_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"require_disjoint_record_files": "yes"},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("require_disjoint_record_files", rep["plan_text"])
        self.assertIn("require_disjoint_record_files", {f["field"] for f in rep["failures"]})

    def test_bad_min_label_agreement_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"min_label_agreement": 1.2},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("min_label_agreement", rep["plan_text"])
        self.assertIn("min_label_agreement", {f["field"] for f in rep["failures"]})
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_bad_copy_tolerance_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"copy_tolerance": -1.0},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("copy_tolerance", rep["plan_text"])
        self.assertEqual(rep["failures"][0]["field"], "copy_tolerance")
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_bad_copy_fraction_threshold_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"copy_fraction_threshold": 1.1},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("copy_fraction_threshold", rep["plan_text"])
        self.assertIn("copy_fraction_threshold", {f["field"] for f in rep["failures"]})
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_bad_label_threshold_tolerance_blocks_contract(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
                "cross_predictor": {"label_threshold_tolerance": -1.0},
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertIn("label_threshold_tolerance", rep["plan_text"])
        self.assertIn("label_threshold_tolerance", {f["field"] for f in rep["failures"]})
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_record_qc_rejects_second_predictor_boltz_copy(self):
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "boltz.jsonl")
            secondary = os.path.join(d, "bad_second.jsonl")
            contract = os.path.join(d, "contract.json")
            with open(primary, "w") as fh:
                fh.write(json.dumps(_record(0, predictor="boltz2_complex",
                                            signal="boltz2_pae_interaction",
                                            label="boltz2_lrmsd_to_reference")) + "\n")
            with open(secondary, "w") as fh:
                fh.write(json.dumps(_record(0, predictor="boltz2_complex",
                                            signal="boltz2_pae_interaction",
                                            label="boltz2_lrmsd_to_reference")) + "\n")
            _write_json(contract, {
                "primary_records": [primary],
                "secondary_records": [secondary],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                    "forbid_predictor_ids": ["boltz2_complex"],
                },
            })

            rep = validate_contract(contract, require_files=True, run_record_qc=True)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures"][0]["kind"], "secondary_records_qc_failed")
        kinds = rep["secondary_records_qc"]["failures_by_kind"]
        self.assertEqual(kinds["forbidden_predictor_id"], 1)
        self.assertEqual(kinds["unexpected_predictor_id"], 1)

    def test_declared_secondary_predictor_cannot_be_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": ["tests/fixtures/barstar_interface_records.jsonl"],
                "secondary_records": ["placeholder.jsonl"],
                "secondary_predictor": {
                    "predictor_id": "boltz2_complex",
                    "signal_source": "boltz2_pae_interaction",
                    "label_source": "boltz2_lrmsd_to_reference",
                    "forbid_predictor_ids": ["boltz2_complex"],
                },
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures"][0]["kind"], "forbidden_secondary_predictor_id")
        self.assertIn("secondary_predictor.predictor_id", rep["plan_text"])
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_primary_and_secondary_record_paths_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            record_path = os.path.join(d, "records.jsonl")
            with open(record_path, "w") as fh:
                fh.write(json.dumps(_record(0)) + "\n")
            contract = os.path.join(d, "contract.json")
            _write_json(contract, {
                "primary_records": [record_path],
                "secondary_records": [record_path],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["record_path_overlaps"][0]["primary_record"], record_path)
        self.assertEqual(rep["record_path_overlaps"][0]["secondary_record"], record_path)
        self.assertIn("overlapping_primary_secondary_records", {f["kind"] for f in rep["failures"]})
        self.assertIn("secondary_records", {f["field"] for f in rep["failures"]})
        self.assertIn("# Downstream commands are commented", rep["plan_text"])

    def test_primary_secondary_overlap_uses_normalized_absolute_paths(self):
        with tempfile.TemporaryDirectory() as d:
            record_path = os.path.join(d, "records.jsonl")
            with open(record_path, "w") as fh:
                fh.write(json.dumps(_record(0)) + "\n")
            contract = os.path.join(d, "contract.json")
            primary = os.path.join(d, ".", "records.jsonl")
            _write_json(contract, {
                "primary_records": [primary],
                "secondary_records": [record_path],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
            })

            rep = validate_contract(contract)

        self.assertFalse(rep["ok"])
        self.assertEqual(len(rep["record_path_overlaps"]), 1)
        self.assertEqual(rep["record_path_overlaps"][0]["secondary_record"], record_path)

    def test_require_files_reports_missing_records(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract with spaces.json")
            _write_json(contract, {
                "primary_records": [os.path.join(d, "missing_primary.jsonl")],
                "secondary_records": [os.path.join(d, "missing_secondary.jsonl")],
                "secondary_predictor": {
                    "predictor_id": "chai1_complex",
                    "signal_source": "chai1_pae_interaction",
                    "label_source": "chai1_lrmsd_to_reference",
                },
            })

            rep = validate_contract(contract, require_files=True)
        self.assertFalse(rep["ok"])
        self.assertEqual({f["field"] for f in rep["failures"]}, {"primary_records", "secondary_records"})
        self.assertIn("contract with spaces.json'", rep["plan_text"])
        self.assertIn("# blockers", rep["plan_text"])
        self.assertIn("missing_file field=primary_records", rep["plan_text"])
        self.assertIn("missing_file field=secondary_records", rep["plan_text"])
        self.assertIn("--require-files", rep["plan_text"])
        self.assertIn("# Downstream commands are commented", rep["plan_text"])
        self.assertIn("# python -m bio_sfm_designer.experiments.complex_records_qc", rep["plan_text"])
        self.assertIn("# python -m bio_sfm_designer.experiments.complex_cross_predictor", rep["plan_text"])

    def test_sync_back_plan_pulls_pending_secondary_records(self):
        with tempfile.TemporaryDirectory() as d:
            contract = os.path.join(d, "contract.json")
            secondary_records = _write_missing_secondary_contract(contract)
            rep = validate_contract(contract, require_files=True, run_record_qc=True)
            plan = render_sync_back_plan(
                rep,
                out="results/m6c_second_predictor_contract.json",
                emit_plan="results/m6c_second_predictor_commands.sh",
                sync_script="results/m6c_second_predictor_sync_back.sh",
                sync_manifest_path="results/m6c_second_predictor_sync_back.manifest.json",
            )

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["pending_secondary_records"][0]["path"], secondary_records[0])
        self.assertIn("REMOTE_BIO_SFM_ROOT", plan)
        self.assertIn("SYNC_PLAN_MANIFEST=results/m6c_second_predictor_sync_back.manifest.json", plan)
        self.assertIn("EXPECTED_SYNC_PLAN_COUNT=1", plan)
        self.assertIn("EXPECTED_SYNC_PLAN_SHA256=", plan)
        self.assertIn("stale second-predictor sync manifest", plan)
        self.assertIn("rsync -avP", plan)
        self.assertIn(f'"${{REMOTE_ROOT%/}}"/{secondary_records[0]}', plan)
        self.assertIn(f'if ! test -s "${{LOCAL_ROOT%/}}"/{secondary_records[0]}', plan)
        self.assertIn("--out results/m6c_second_predictor_contract.json", plan)
        self.assertIn("--emit-plan results/m6c_second_predictor_commands.sh", plan)
        self.assertIn("bash results/m6c_second_predictor_commands.sh", plan)

    def test_sync_back_plan_fails_if_rsync_leaves_empty_secondary_record(self):
        with tempfile.TemporaryDirectory() as d:
            bin_dir = os.path.join(d, "bin")
            local_root = os.path.join(d, "local")
            remote_root = os.path.join(d, "remote")
            out = os.path.join(d, "contract.json")
            plan = os.path.join(d, "commands.sh")
            sync_back = os.path.join(d, "sync_back.sh")
            contract = os.path.join(d, "missing_contract.json")
            os.makedirs(bin_dir, exist_ok=True)
            fake_rsync = os.path.join(bin_dir, "rsync")
            with open(fake_rsync, "w") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(fake_rsync, 0o755)
            _write_missing_secondary_contract(contract)

            with self.assertRaises(SystemExit) as cm:
                main([
                    "--contract", contract,
                    "--require-files",
                    "--run-record-qc",
                    "--out", out,
                    "--emit-plan", plan,
                    "--emit-sync-back-plan", sync_back,
                    "--sync-remote-root", remote_root,
                    "--sync-local-root", local_root,
                ])
            self.assertEqual(cm.exception.code, 2)

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
        self.assertIn("missing or empty secondary-predictor record after rsync", proc.stderr)

    def test_cli_report_records_self_command(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "contract.json")
            plan = os.path.join(d, "commands.sh")
            sync_back = os.path.join(d, "sync_back.sh")
            contract = os.path.join(d, "missing_contract.json")
            _write_missing_secondary_contract(contract)

            with self.assertRaises(SystemExit) as cm:
                main([
                    "--contract", contract,
                    "--require-files",
                    "--run-record-qc",
                    "--out", out,
                    "--emit-plan", plan,
                    "--emit-sync-back-plan", sync_back,
                    "--sync-remote-root", "runner@<hpc-login-host>:/scratch/<user>/bio_sfm_designer",
                    "--sync-local-root", "/tmp/local-bio-sfm",
                ])
            self.assertEqual(cm.exception.code, 2)
            with open(out) as fh:
                saved = json.load(fh)
            with open(sync_back) as fh:
                sync_text = fh.read()

        self.assertIn("self_command", saved)
        self.assertIn("complex_predictor_contract", saved["self_command"])
        self.assertIn("--require-files", saved["self_command"])
        self.assertIn("--run-record-qc", saved["self_command"])
        self.assertIn(f"--out {out}", saved["self_command"])
        self.assertIn(f"--emit-plan {plan}", saved["self_command"])
        self.assertIn(f"--emit-sync-back-plan {sync_back}", saved["self_command"])
        self.assertIn("--sync-remote-root 'runner@<hpc-login-host>:/scratch/<user>/bio_sfm_designer'", saved["self_command"])
        self.assertIn("--sync-local-root /tmp/local-bio-sfm", saved["self_command"])
        refresh_line = [
            line for line in sync_text.splitlines()
            if "bio_sfm_designer.experiments.complex_predictor_contract" in line
            and not line.startswith("#")
        ][0]
        self.assertIn(f"--out {out}", refresh_line)
        self.assertIn(f"--emit-plan {plan}", refresh_line)
        self.assertNotIn("--emit-sync-back-plan", refresh_line)


if __name__ == "__main__":
    unittest.main()
