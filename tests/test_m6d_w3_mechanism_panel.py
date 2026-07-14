"""Tests for the preregistered W3 mechanism panel and fail-closed guard."""

import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w3_mechanism_adjudication import adjudicate
from bio_sfm_designer.experiments.m6d_w3_mechanism_guard import verify_bundle, verify_runtime_receipt
from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
    build_panel,
    render_markdown,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hpc/run_w3_mechanism_panel_guarded.sh"
RUNTIME_SCRIPT = ROOT / "hpc/validate_w3_mechanism_runtime.sh"
RUNTIME_RECEIPT_BUILDER = ROOT / "hpc/prepare_w3_mechanism_runtime_receipt.py"
AA = "ACDEFGHIKLMNPQRSTVWY"


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seq(index, length=8):
    chars = []
    for _ in range(length):
        chars.append(AA[index % len(AA)])
        index //= len(AA)
    return "".join(chars)


def _sources():
    target_sequence = "ACDEFG"
    target_msa = ">101\nACDEFG\n>hit\nAC-EFG\n"
    challenge_candidates = []
    challenge_records = []
    challenge_rows = []
    for index in range(18):
        target_id = f"challenge-{index}"
        success = index >= 12
        challenge_candidates.append({
            "id": target_id,
            "target_seq": target_sequence,
            "representation": _seq(1000 + index),
        })
        challenge_records.append({
            "target_id": target_id,
            "complex_target_id": "3PC8_AB",
            "target_chain": "A",
            "binder_chain": "B",
            "pae_interaction": float(index + 1),
            "lrmsd": 2.0 if success else 8.0,
        })
        role = "concordant_success_control" if success else "discordant_boltz_chai_label"
        challenge_rows.append({
            "target_id": target_id,
            "adjudication_role": role,
            "source_labels": {
                "label_a": success,
                "label_b": True,
            },
        })

    target_specs = []
    report_targets = []
    candidates = {}
    records = {}
    msas = {}
    reference_hashes = {}
    for target_index in range(8):
        target_id = f"T{target_index:02d}_AB"
        target_candidates = []
        target_records = []
        for row_index in range(60):
            candidate_id = f"w2c-fit-learn-v1-{target_id}-{row_index}"
            binder = _seq(target_index * 100 + row_index)
            target_candidates.append({
                "id": candidate_id,
                "target_seq": target_sequence,
                "representation": binder,
            })
            if target_index == 0:
                lrmsd = 2.0
            elif target_index in (1, 2):
                lrmsd = 8.0
            else:
                lrmsd = 2.0 if row_index < 28 else 8.0
            target_records.append({
                "target_id": candidate_id,
                "complex_target_id": target_id,
                "representation": binder,
                "pae_interaction": float(row_index + 1),
                "lrmsd": lrmsd,
            })
        candidates[target_id] = target_candidates
        records[target_id] = target_records
        msas[target_id] = target_msa
        reference_hashes[target_id] = _sha(f"reference-{target_id}")
        target_specs.append({
            "id": target_id,
            "target_chain": "A",
            "binder_chain": "B",
            "target_sequence_sha256": _sha(target_sequence),
            "target_msa": f"hpc_outputs/{target_id}.a3m",
            "target_msa_sha256": _sha(target_msa),
            "prepared_pdb": f"hpc_outputs/{target_id}.pdb",
        })
        report_targets.append({
            "target_id": target_id,
            "learning": {
                "mode": "refuse",
                "candidate": False,
                "auroc_pae": None if target_index < 3 else 0.9,
            },
        })

    return {
        "w2c_protocol": {
            "locked_scientific_protocol": {
                "fit_design": {
                    "threshold_learning": {
                        "minimum_accepted": 30,
                        "minimum_auroc": 0.65,
                        "maximum_empirical_false_accept_rate": 0.08,
                    }
                }
            }
        },
        "w2c_target_manifest": {"targets": target_specs},
        "w2c_report": {
            "status": "w2c_threshold_learning_terminal_not_supported",
            "audit_ok": True,
            "terminal_after_threshold_learning": True,
            "n_threshold_candidate_targets": 0,
            "minimum_selective_targets_required": 3,
            "lrmsd_threshold": 4.0,
            "targets": report_targets,
        },
        "challenge": {
            "status": "w3_challenge_manifest_ready_no_submit",
            "audit_ok": True,
            "no_submit": True,
            "rows": challenge_rows,
        },
        "selection": {
            "status": "w3_predictor_selection_card_ready_no_submit",
            "audit_ok": True,
            "selected_predictor_protocol": {
                "predictor_or_protocol_id": "af2_multimer_colabfold_v1"
            },
        },
        "runtime": {
            "status": "w3_runtime_provision_packet_ready_no_submit",
            "audit_ok": True,
            "no_submit": True,
            "runtime_ready": False,
        },
        "challenge_candidates": challenge_candidates,
        "challenge_boltz_records": challenge_records,
        "challenge_target_msa_text": target_msa,
        "challenge_target_msa_sha256": _sha(target_msa),
        "challenge_reference_path": "hpc_outputs/3PC8_AB.pdb",
        "challenge_reference_sha256": _sha("3PC8-reference"),
        "w2c_candidates": candidates,
        "w2c_records": records,
        "w2c_target_msa_texts": msas,
        "w2c_reference_sha256": reference_hashes,
    }


def _build(private_manifest="results/test_w3_inputs.jsonl", input_dir="results/test_w3_inputs/a3m"):
    return build_panel(
        **_sources(),
        private_manifest_path=private_manifest,
        input_dir=input_dir,
        report_date="2026-07-14",
    )


def _materialize(root, packet, private_rows, payloads):
    packet_path = root / "configs/m6d_w3_mechanism_panel_protocol.json"
    manifest = root / "results/test_w3_inputs.jsonl"
    input_dir = root / "results/test_w3_inputs/a3m"
    packet_path.parent.mkdir(parents=True)
    input_dir.mkdir(parents=True)
    packet_path.write_text(json.dumps(packet) + "\n")
    manifest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in private_rows))
    for case_id, payload in payloads.items():
        (input_dir / f"{case_id}.a3m").write_text(payload)
    return packet_path, manifest, input_dir


class M6DW3MechanismPanelTests(unittest.TestCase):
    def test_builds_hash_only_58_case_preregistration(self):
        packet, private_rows, payloads = _build()

        self.assertTrue(packet["audit_ok"])
        self.assertEqual(packet["status"], "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit")
        self.assertEqual(len(packet["rows"]), 58)
        self.assertEqual(len(private_rows), 58)
        self.assertEqual(len(payloads), 58)
        self.assertFalse(packet["execution_packet"]["execution_ready"])
        self.assertFalse(packet["can_claim_independent_predictor_robustness_now"])
        public_text = json.dumps(packet)
        self.assertNotIn('"target_sequence":', public_text)
        self.assertNotIn('"binder_sequence":', public_text)
        self.assertNotIn("/Users/", public_text)

        w2c_rows = [row for row in private_rows if row["panel_block"] == "w2c_pae_order_statistics"]
        by_target = {}
        for row in w2c_rows:
            by_target.setdefault(row["complex_target_id"], []).append(row["pae_order_rank"])
        self.assertEqual(set(by_target), {f"T{i:02d}_AB" for i in range(8)})
        self.assertTrue(all(ranks == [1, 15, 30, 45, 60] for ranks in by_target.values()))
        self.assertEqual(packet["w2c_characterization"]["failure_kinds"]["auroc_undefined_all_success"], 1)

    def test_annotated_a3m_has_paired_query_and_unpaired_binder(self):
        text = build_annotated_multimer_a3m(
            ">101\nACDE\n>hit\nAC-E\n", "ACDE", "FGHI"
        )
        lines = text.splitlines()
        self.assertEqual(lines[:3], ["#4,4\t1,1", ">101\t102", "ACDEFGHI"])
        self.assertIn("----FGHI", lines)

    def test_blocks_source_status_drift(self):
        sources = _sources()
        sources["w2c_report"]["n_threshold_candidate_targets"] = 1
        packet, _, _ = build_panel(
            **sources,
            private_manifest_path="results/test.jsonl",
            input_dir="results/test/a3m",
        )
        self.assertFalse(packet["audit_ok"])
        self.assertIn("w2c_candidates_not_zero", {row["kind"] for row in packet["failures"]})

    def test_markdown_freezes_scope_and_no_submit_boundary(self):
        packet, _, _ = _build()
        text = render_markdown(packet)
        self.assertIn("58 distinct AF2-Multimer inputs", text)
        self.assertIn("This is a no-submit packet", text)
        self.assertIn("32/40", text)

    def test_bundle_verifier_detects_a3m_tamper(self):
        packet, private_rows, payloads = _build()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            packet_path, manifest, input_dir = _materialize(root, packet, private_rows, payloads)
            report = verify_bundle(
                packet,
                packet_path=str(packet_path),
                private_manifest_path=str(manifest),
                input_dir=str(input_dir),
            )
            self.assertTrue(report["ok"])
            (input_dir / "w3m-001.a3m").write_text("tampered\n")
            report = verify_bundle(
                packet,
                packet_path=str(packet_path),
                private_manifest_path=str(manifest),
                input_dir=str(input_dir),
            )
            self.assertFalse(report["ok"])
            self.assertIn("a3m_sha_mismatch", {row["kind"] for row in report["failures"]})

    def test_shell_guard_dry_run_and_approval_refusal(self):
        packet, private_rows, payloads = _build()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            packet_path, manifest, input_dir = _materialize(root, packet, private_rows, payloads)
            env = os.environ.copy()
            env.update({
                "W3_PACKET": str(packet_path),
                "W3_PRIVATE_MANIFEST": str(manifest),
                "W3_INPUT_DIR": str(input_dir),
            })
            dry = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("dry-run only", dry.stdout)
            env["W3_DRY_RUN"] = "0"
            refused = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
            self.assertEqual(refused.returncode, 64)
            self.assertIn("separate exact approval", refused.stderr)

    def test_adjudicator_supports_boltz_mechanism_only_at_frozen_thresholds(self):
        packet, _, _ = _build()
        records = []
        for row in packet["rows"]:
            label = row["source_boltz2_label"]
            records.append({
                "case_id": row["case_id"],
                "target_id": row["source_target_id"],
                "complex_target_id": row["complex_target_id"],
                "predictor_id": "af2_multimer_colabfold_v1",
                "signal_source": "af2_multimer_pae_interaction",
                "label_source": "af2_multimer_lrmsd_to_reference",
                "lrmsd_threshold": 4.0,
                "interface_aligned": True,
                "lrmsd": 2.0 if label else 8.0,
                "pae_interaction": 5.0,
                "mean_plddt": 90.0,
                "truth": {"correct": label},
                "provenance": {
                    "panel_block": row["panel_block"],
                    "panel_role": row["panel_role"],
                    "a3m_sha256": row["a3m_sha256"],
                    "reference_backbone_sha256": row["reference_backbone_sha256"],
                    "target_sequence_sha256": row["target_sequence_sha256"],
                    "binder_sequence_sha256": row["binder_sequence_sha256"],
                },
            })
        report = adjudicate(packet, records)
        self.assertTrue(report["audit_ok"])
        self.assertEqual(report["three_pc8"]["outcome"], "boltz_supported_on_challenge_panel")
        self.assertEqual(report["w2c"]["outcome"], "boltz_supported_on_w2c_mechanism_panel")
        self.assertEqual(report["joint_outcome"], "boltz_supported_target_or_coverage_mechanism")
        self.assertFalse(report["can_claim_population_level_independent_predictor_robustness"])

        records[0]["truth"]["correct"] = not records[0]["truth"]["correct"]
        blocked = adjudicate(packet, records)
        self.assertFalse(blocked["audit_ok"])
        self.assertIn(
            "result_label_lrmsd_mismatch",
            {row["kind"] for row in blocked["failures"]},
        )

    def test_guard_enforces_network_and_api_locks(self):
        packet, private_rows, payloads = _build()
        packet["execution_packet"]["no_network_fetch"] = False
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            packet_path, manifest, input_dir = _materialize(
                root, packet, private_rows, payloads
            )
            report = verify_bundle(
                packet,
                packet_path=str(packet_path),
                private_manifest_path=str(manifest),
                input_dir=str(input_dir),
            )
        self.assertFalse(report["ok"])
        self.assertIn(
            "packet_network_boundary_invalid",
            {row["kind"] for row in report["failures"]},
        )

    def test_adjudicator_blocks_missing_result(self):
        packet, _, _ = _build()
        report = adjudicate(packet, [])
        self.assertFalse(report["audit_ok"])
        self.assertEqual(report["joint_outcome"], "contract_blocked")

    def test_guard_script_has_valid_shell_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_runtime_receipt_locks_binary_and_local_weights(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("w3_runtime_receipt_under_test", RUNTIME_RECEIPT_BUILDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            runtime = root / "colabfold_batch"
            runtime.write_text("runtime-1.6.1\n")
            params = root / "data/params"
            params.mkdir(parents=True)
            (params / "download_complexes_multimer_v3_finished.txt").write_text("done\n")
            for index in range(1, 6):
                (params / f"params_model_{index}_multimer_v3.npz").write_bytes(f"weight-{index}".encode())
            receipt = module.build_receipt(
                runtime_mode="existing_colabfold_binary",
                runtime_path=runtime,
                data_dir=root / "data",
                colabfold_version="1.6.1",
            )
            verified = verify_runtime_receipt(
                receipt,
                data_dir=str(root / "data"),
                runtime_path=str(runtime),
            )
        self.assertTrue(verified["ok"])
        self.assertFalse(receipt["prediction_executed"])

    def test_runtime_validator_is_no_submit_and_no_fetch(self):
        subprocess.run(["bash", "-n", str(RUNTIME_SCRIPT)], check=True)
        text = RUNTIME_SCRIPT.read_text()
        for forbidden in ("sbatch ", "srun ", "curl ", "wget ", "pip install"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
