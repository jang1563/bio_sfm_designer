"""Tests for the deterministic W2c threshold-learning manifest and input lock."""

import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from bio_sfm_designer.experiments.m6d_w2c_fit_learn_lock import (
    build_lock,
    build_stage_manifest,
    deterministic_seed,
)


def _sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "w"
    with open(path, mode) as handle:
        if isinstance(content, dict):
            json.dump(content, handle)
            handle.write("\n")
        else:
            handle.write(content)


class M6DW2CFitLearnLockTests(unittest.TestCase):
    def _fixture(self, root):
        target_ids = [f"fresh-{index}" for index in range(8)]
        source_targets = []
        completion_targets = []
        for index, target_id in enumerate(target_ids):
            target_root = os.path.join(root, "inputs", target_id)
            paths = {
                "source_pdb": os.path.join(target_root, "source.pdb"),
                "prepared_pdb": os.path.join(target_root, "prepared.pdb"),
                "prep_report": os.path.join(target_root, "prepared.report.json"),
                "target_fasta": os.path.join(target_root, "target.fasta"),
                "target_fasta_report": os.path.join(target_root, "target.fasta.report.json"),
                "target_msa": os.path.join(target_root, "target.a3m"),
                "target_msa_report": os.path.join(target_root, "target.a3m.report.json"),
            }
            _write(paths["source_pdb"], "ATOM\n")
            _write(paths["prepared_pdb"], "ATOM\n")
            _write(paths["prep_report"], {"ok": True})
            _write(paths["target_fasta"], ">target\nAAAA\n")
            _write(paths["target_fasta_report"], {"sequence": "AAAA"})
            _write(paths["target_msa"], ">target\nAAAA\n")
            _write(paths["target_msa_report"], {"ok": True})
            source_targets.append({
                "id": target_id,
                "rcsb_id": f"T{index:03d}",
                **paths,
                "target_chain": "A",
                "binder_chain": "B",
                "target_sequence_sha256": "a" * 64,
                "selection_input_origin": "test",
                "out_prefix": os.path.join(root, "historical", target_id),
                "records": os.path.join(root, "historical", target_id, "records.jsonl"),
            })
            completion_targets.append({
                "target_id": target_id,
                "report_ok": True,
                "target_msa_sha256": _sha256(paths["target_msa"]),
                "target_msa_report_sha256": _sha256(paths["target_msa_report"]),
            })
        source = {
            "artifact": "source",
            "locked_scientific_digest": "b" * 64,
            "defaults": {"num_seq": 60, "temp": 0.3, "objective": "binder"},
            "targets": source_targets,
        }
        source_path = os.path.join(root, "source.json")
        _write(source_path, source)
        protocol = {
            "locked_scientific_protocol": {
                "fit_design": {
                    "threshold_learning": {
                        "records_per_target": 60,
                        "seed_namespace": "w2c-fit-learn-v1",
                    }
                }
            },
            "execution_state": {
                "target_ids": target_ids,
                "target_manifest_sha256": _sha256(source_path),
            },
        }
        protocol_path = os.path.join(root, "protocol.json")
        _write(protocol_path, protocol)
        completion = {
            "status": "target_msa_precompute_complete_8_of_8",
            "audit_ok": True,
            "n_targets": 8,
            "n_target_msas": 8,
            "n_target_msa_reports": 8,
            "strict_manifest_ready_targets": 8,
            "within_approved_gpu_hour_ceiling": True,
            "targets": completion_targets,
        }
        completion_path = os.path.join(root, "completion.json")
        _write(completion_path, completion)
        return protocol_path, source_path, completion_path, target_ids

    def test_manifest_is_isolated_and_deterministic(self):
        with tempfile.TemporaryDirectory() as root:
            protocol, source, completion, target_ids = self._fixture(root)
            first = build_stage_manifest(protocol, source, completion)
            second = build_stage_manifest(protocol, source, completion)

        self.assertEqual(first, second)
        self.assertEqual(first["total_records"], 480)
        self.assertFalse(first["cayuga_submission_allowed"])
        self.assertEqual([row["id"] for row in first["targets"]], target_ids)
        self.assertEqual(len({row["seed"] for row in first["targets"]}), 8)
        for row in first["targets"]:
            self.assertEqual(row["seed"], deterministic_seed("w2c-fit-learn-v1", row["id"]))
            self.assertTrue(row["records"].startswith("hpc_outputs/m6d_w2c_fit_learn_records/"))
            self.assertTrue(row["id_prefix"].startswith("w2c-fit-learn-v1-"))

    def test_lock_covers_56_artifacts_and_rejects_output_collision(self):
        with tempfile.TemporaryDirectory() as root:
            protocol, source, completion, _ = self._fixture(root)
            manifest = build_stage_manifest(protocol, source, completion)
            manifest_path = os.path.join(root, "stage.json")
            _write(manifest_path, manifest)
            with patch(
                "bio_sfm_designer.experiments.m6d_w2c_fit_learn_lock.validate_manifest",
                return_value={"ok": True, "failures": []},
            ):
                report = build_lock(protocol, source, completion, manifest_path)
            self.assertTrue(report["audit_ok"])
            self.assertEqual(report["n_artifacts"], 56)

            source_value = json.load(open(source))
            manifest["targets"][0]["records"] = source_value["targets"][0]["records"]
            _write(manifest_path, manifest)
            with patch(
                "bio_sfm_designer.experiments.m6d_w2c_fit_learn_lock.validate_manifest",
                return_value={"ok": True, "failures": []},
            ):
                blocked = build_lock(protocol, source, completion, manifest_path)
        self.assertFalse(blocked["audit_ok"])
        self.assertIn("historical_output_path_collision", {row["kind"] for row in blocked["failures"]})


if __name__ == "__main__":
    unittest.main()
