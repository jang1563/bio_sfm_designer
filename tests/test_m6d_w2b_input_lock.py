"""Tests for the W2b byte-level stage input lock."""

import hashlib
import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2b_input_lock import build_lock, verify_lock


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class W2BInputLockTests(unittest.TestCase):
    def _fixture(self, directory):
        source = os.path.join(directory, "source.pdb")
        prepared = os.path.join(directory, "prepared.pdb")
        prep_report = prepared + ".report.json"
        fasta = os.path.join(directory, "target.fasta")
        fasta_report = fasta + ".report.json"
        msa = os.path.join(directory, "target.a3m")
        msa_report = msa + ".report.json"
        _write(source, "ATOM\n")
        _write(prepared, "ATOM\n")
        _write(fasta, ">target\nAAAA\n")
        _write(msa, ">target\nAAAA\n")
        _write(prep_report, json.dumps({
            "target_chain": "A",
            "binder_chain": "B",
            "target_numbering_gaps": [],
            "binder_numbering_gaps": [],
            "ca_interface_contacts": 20,
        }))
        _write(fasta_report, json.dumps({
            "pdb": prepared,
            "pdb_sha256": _sha(prepared),
            "chain": "A",
            "length": 4,
            "sequence": "AAAA",
            "out": fasta,
            "out_sha256": _sha(fasta),
        }))
        _write(msa_report, json.dumps({
            "ok": True,
            "fasta": fasta,
            "fasta_sha256": _sha(fasta),
            "out": msa,
            "out_sha256": _sha(msa),
            "sequence_length": 4,
        }))
        manifest = os.path.join(directory, "manifest.json")
        manifest_value = {
            "defaults": {"num_seq": 2, "seed": 37, "temp": 0.3, "objective": "binder"},
            "protocol_sha256": "science-digest",
            "w2b_stage": "fit",
            "w2b_seed_namespace": "fit-ns",
            "targets": [{
                "id": "toy_AB",
                "source_pdb": source,
                "prepared_pdb": prepared,
                "prep_report": prep_report,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_fasta_report": fasta_report,
                "target_msa": msa,
                "target_msa_report": msa_report,
                "w2b_stage": "fit",
                "w2b_seed_namespace": "fit-ns",
            }],
        }
        _write(manifest, json.dumps(manifest_value))
        protocol = os.path.join(directory, "protocol.json")
        _write(protocol, json.dumps({
            "fresh_target_contract": {"n_initial_targets": 1},
            "generation_stages": {"fit": {"records_per_target": 2, "seed_namespace": "fit-ns"}},
            "current_execution_state": {
                "fit_manifest_sha256": _sha(manifest),
                "locked_scientific_protocol_sha256": "science-digest",
                "stage_proteinmpnn_seeds": {"fit": 37},
            },
        }))
        return protocol, manifest, msa

    def _certification_fixture(self, directory):
        protocol, manifest, msa = self._fixture(directory)
        with open(manifest) as handle:
            manifest_value = json.load(handle)
        target = manifest_value["targets"][0]
        manifest_value.update({
            "w2b_stage": "certification",
            "w2b_seed_namespace": "cert-ns",
            "fit_eligible_target_ids": ["toy_AB"],
            "output_root": os.path.join(directory, "certification-records"),
            "source_fit_manifest_sha256": "fit-manifest",
            "source_fit_report_sha256": "fit-report",
            "source_fit_fixture_sha256": "fit-fixture",
        })
        manifest_value["defaults"].update({"num_seq": 3, "seed": 1037})
        target.update({
            "w2b_stage": "certification",
            "w2b_seed_namespace": "cert-ns",
            "id_prefix": "cert-ns-toy_AB",
            "frozen_fit_rule": {"mode": "selective_pae", "tau": 5.5},
            "out_prefix": os.path.join(directory, "certification-records", "toy_AB"),
            "candidates": os.path.join(
                directory,
                "certification-records",
                "toy_AB",
                "candidates_proteinmpnn_complex.jsonl",
            ),
            "records": os.path.join(
                directory,
                "certification-records",
                "toy_AB",
                "records_boltz_complex.jsonl",
            ),
        })
        _write(manifest, json.dumps(manifest_value))
        with open(protocol) as handle:
            protocol_value = json.load(handle)
        protocol_value["fresh_target_contract"]["n_initial_targets"] = 8
        protocol_value["generation_stages"]["certification"] = {
            "records_per_target": 3,
            "seed_namespace": "cert-ns",
        }
        protocol_value["current_execution_state"].update({
            "certification_manifest_sha256": _sha(manifest),
            "fit_eligible_target_ids": ["toy_AB"],
            "fit_frozen_rules": {
                "toy_AB": {"mode": "selective_pae", "tau": 5.5},
            },
            "fit_manifest_sha256": "fit-manifest",
            "fit_report_sha256": "fit-report",
            "fit_fixture_sha256": "fit-fixture",
        })
        protocol_value["current_execution_state"]["stage_proteinmpnn_seeds"]["certification"] = 1037
        _write(protocol, json.dumps(protocol_value))
        return protocol, manifest, msa

    def test_build_and_verify_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, manifest, _msa = self._fixture(directory)
            lock_path = os.path.join(directory, "lock.json")
            lock = build_lock(protocol, manifest)
            _write(lock_path, json.dumps(lock))

            verification = verify_lock(lock_path, protocol, manifest)

        self.assertTrue(lock["audit_ok"])
        self.assertEqual(lock["n_targets"], 1)
        self.assertEqual(lock["n_artifacts"], 7)
        self.assertTrue(verification["verified"])

    def test_tampered_msa_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, manifest, msa = self._fixture(directory)
            lock_path = os.path.join(directory, "lock.json")
            _write(lock_path, json.dumps(build_lock(protocol, manifest)))
            _write(msa, ">target\nAAAT\n")

            verification = verify_lock(lock_path, protocol, manifest)

        self.assertFalse(verification["verified"])
        self.assertNotEqual(
            verification["expected_lock_digest_sha256"],
            verification["actual_lock_digest_sha256"],
        )

    def test_machine_specific_report_paths_do_not_change_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, manifest, _msa = self._fixture(directory)
            lock_path = os.path.join(directory, "lock.json")
            lock = build_lock(protocol, manifest)
            _write(lock_path, json.dumps(lock))
            manifest_value = json.loads(open(manifest).read())
            target = manifest_value["targets"][0]
            for field, path_keys in (
                ("prep_report", ("source_pdb", "output_pdb")),
                ("target_fasta_report", ("pdb", "out")),
                ("target_msa_report", ("fasta", "out")),
            ):
                path = target[field]
                report = json.loads(open(path).read())
                for key in path_keys:
                    report[key] = f"/different-machine/{key}"
                report["work_dir"] = "/different-machine/work"
                _write(path, json.dumps(report))

            verification = verify_lock(lock_path, protocol, manifest)

        self.assertTrue(verification["verified"])

    def test_certification_lock_binds_fit_rules_and_exact_target_set(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, manifest, _msa = self._certification_fixture(directory)
            lock = build_lock(protocol, manifest)

        self.assertTrue(lock["audit_ok"], lock["failures"])
        self.assertEqual(lock["n_targets"], 1)
        self.assertEqual(
            lock["binding"]["targets"][0]["frozen_fit_rule"],
            {"mode": "selective_pae", "tau": 5.5},
        )
        self.assertEqual(lock["binding"]["fit_evidence"]["fit_report_sha256"], "fit-report")

    def test_certification_lock_rejects_changed_fit_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, manifest, _msa = self._certification_fixture(directory)
            with open(manifest) as handle:
                manifest_value = json.load(handle)
            manifest_value["targets"][0]["frozen_fit_rule"]["tau"] = 6.0
            _write(manifest, json.dumps(manifest_value))
            with open(protocol) as handle:
                protocol_value = json.load(handle)
            protocol_value["current_execution_state"]["certification_manifest_sha256"] = _sha(manifest)
            _write(protocol, json.dumps(protocol_value))

            lock = build_lock(protocol, manifest)

        self.assertFalse(lock["audit_ok"])
        self.assertIn("frozen_fit_rule_mismatch", {row["kind"] for row in lock["failures"]})


if __name__ == "__main__":
    unittest.main()
