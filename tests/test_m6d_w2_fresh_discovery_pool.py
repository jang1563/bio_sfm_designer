"""Tests for the fresh M6d W2 discovery-pool intake."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_fresh_discovery_pool import (
    build_discovery_pool,
    main,
    render_markdown,
)


def _ca(serial, resname, chain, resseq, x, y, z):
    return ("ATOM  %5d  CA  %3s %s%4d    %8.3f%8.3f%8.3f  1.00 50.00           C\n"
            % (serial, resname, chain, resseq, x, y, z))


def _write_source(path, *, contacting=True, extra_contacting_chain=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    serial = 1
    for i in range(1, 61):
        lines.append(_ca(serial, "ALA", "A", i, float(i), 0.0, 0.0))
        serial += 1
    offset = 5.0 if contacting else 50.0
    for i in range(1, 56):
        lines.append(_ca(serial, "GLY", "B", i, float(i), offset, 0.0))
        serial += 1
    if extra_contacting_chain:
        for i in range(1, 54):
            lines.append(_ca(serial, "SER", "C", i, float(i), 4.0, 1.0))
            serial += 1
    with open(path, "w") as fh:
        fh.write("".join(lines))
        fh.write("END\n")


class M6DW2FreshDiscoveryPoolTests(unittest.TestCase):
    def test_build_discovery_pool_materializes_structural_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source_TEST.pdb")
            _write_source(source)
            seed = {"seeds": [{"rcsb_id": "TEST", "source_pdb": source}]}

            rep = build_discovery_pool(seed, out_dir=os.path.join(d, "out"), max_candidates=3)

            self.assertEqual(rep["status"], "fresh_structural_candidates_ready_for_msa_precompute")
            self.assertTrue(rep["ready_for_target_msa_precompute"])
            self.assertFalse(rep["ready_for_cayuga_submission"])
            self.assertEqual(rep["n_selected_for_manifest"], 1)
            self.assertEqual(rep["n_unique_selected_rcsb_ids"], 1)
            self.assertIn("one chain-pair per source", rep["selected_source_redundancy_note"])
            self.assertEqual(len(rep["manifest"]["targets"]), 1)
            target = rep["manifest"]["targets"][0]
            self.assertEqual(
                target["out_prefix"],
                os.path.join("hpc_outputs", "m6d_w2_fresh_discovery_records", target["id"]),
            )
            self.assertTrue(os.path.exists(target["prepared_pdb"]))
            self.assertTrue(os.path.exists(target["target_fasta"]))
            self.assertFalse(os.path.exists(target["target_msa"]))
            with open(target["target_fasta_report"]) as fh:
                fasta_report = json.load(fh)
            self.assertEqual(fasta_report["pdb"], target["prepared_pdb"])
            self.assertEqual(fasta_report["out"], target["target_fasta"])
            self.assertTrue(os.path.isabs(fasta_report["pdb_abs"]))
            self.assertTrue(os.path.isabs(fasta_report["out_abs"]))

    def test_non_contacting_source_is_not_selected(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source_TEST.pdb")
            _write_source(source, contacting=False)
            seed = {"seeds": [{"rcsb_id": "TEST", "source_pdb": source}]}

            rep = build_discovery_pool(seed, out_dir=os.path.join(d, "out"))

            self.assertEqual(rep["status"], "no_fresh_structural_candidates_admitted")
            self.assertEqual(rep["n_selected_for_manifest"], 0)

    def test_source_diverse_selection_keeps_one_candidate_per_source(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source_TEST.pdb")
            _write_source(source, extra_contacting_chain=True)
            seed = {"seeds": [{"rcsb_id": "TEST", "source_pdb": source}]}

            rep = build_discovery_pool(
                seed,
                out_dir=os.path.join(d, "out"),
                max_candidates=3,
                source_diverse=True,
            )

            self.assertTrue(rep["source_diverse_selection"])
            self.assertGreater(rep["n_structural_admitted"], 1)
            self.assertEqual(rep["n_selected_for_manifest"], 1)
            self.assertEqual(rep["n_unique_selected_rcsb_ids"], 1)

    def test_historical_registry_excludes_evaluated_target_and_source(self):
        with tempfile.TemporaryDirectory() as d:
            old_source = os.path.join(d, "source_OLD.pdb")
            new_source = os.path.join(d, "source_NEW.pdb")
            _write_source(old_source)
            _write_source(new_source)
            seed = {"seeds": [
                {"rcsb_id": "OLD", "source_pdb": old_source},
                {"rcsb_id": "NEW", "source_pdb": new_source},
            ]}
            registry = {
                "evaluated_target_ids": ["OLD_AB"],
                "evaluated_source_rcsb_ids": ["OLD"],
            }

            rep = build_discovery_pool(
                seed,
                out_dir=os.path.join(d, "out"),
                max_candidates=3,
                source_diverse=True,
                historical_registry=registry,
            )

        self.assertTrue(rep["historical_registry_applied"])
        self.assertGreaterEqual(rep["n_historical_evidence_excluded"], 1)
        self.assertEqual(rep["n_selected_for_manifest"], 1)
        self.assertEqual(rep["manifest"]["targets"][0]["rcsb_id"], "NEW")

    def test_cli_writes_report_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source_TEST.pdb")
            _write_source(source)
            seed_path = os.path.join(d, "seed.json")
            with open(seed_path, "w") as fh:
                json.dump({"seeds": [{"rcsb_id": "TEST", "source_pdb": source}]}, fh)
            out_json = os.path.join(d, "pool.json")
            out_md = os.path.join(d, "pool.md")
            out_manifest = os.path.join(d, "manifest.json")

            rc = main([
                "--seed-config", seed_path,
                "--out-dir", os.path.join(d, "out"),
                "--out-json", out_json,
                "--out-md", out_md,
                "--out-manifest", out_manifest,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_manifest))

    def test_cli_accepts_branch_specific_records_dir(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source_TEST.pdb")
            _write_source(source)
            seed_path = os.path.join(d, "seed.json")
            with open(seed_path, "w") as fh:
                json.dump({"seeds": [{"rcsb_id": "TEST", "source_pdb": source}]}, fh)
            out_manifest = os.path.join(d, "manifest.json")
            records_dir = os.path.join("hpc_outputs", "branch_records")

            rc = main([
                "--seed-config", seed_path,
                "--out-dir", os.path.join(d, "out"),
                "--records-dir", records_dir,
                "--out-json", os.path.join(d, "pool.json"),
                "--out-md", os.path.join(d, "pool.md"),
                "--out-manifest", out_manifest,
            ])

            self.assertEqual(rc, 0)
            with open(out_manifest) as fh:
                manifest = json.load(fh)
            target = manifest["targets"][0]
            self.assertEqual(target["out_prefix"], os.path.join(records_dir, target["id"]))
            self.assertEqual(
                target["records"],
                os.path.join(records_dir, target["id"], "records_boltz_complex.jsonl"),
            )

    def test_markdown_states_pre_msa_boundary(self):
        rep = {
            "date": "2026-06-30",
            "status": "fresh_structural_candidates_ready_for_msa_precompute",
            "ready_for_target_msa_precompute": True,
            "ready_for_cayuga_submission": False,
            "n_seed_pdbs": 1,
            "n_chain_pairs_screened": 1,
            "n_structural_admitted": 1,
            "n_selected_for_manifest": 1,
            "n_unique_selected_rcsb_ids": 1,
            "source_diverse_selection": True,
            "selected_source_redundancy_note": "selected candidates have one chain-pair per source structure",
            "selected_candidates": [{
                "complex_target_id": "TEST_AB",
                "rcsb_id": "TEST",
                "target_chain": "A",
                "binder_chain": "B",
                "target_ca_residues": 60,
                "binder_ca_residues": 55,
                "ca_interface_contacts": 100,
                "chain_sequence_identity": 0.0,
            }],
            "next_action": "precompute MSA",
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Fresh Discovery Pool", md)
        self.assertIn("Ready for Cayuga submission: `false`", md)
        self.assertIn("pre-MSA", md)
        self.assertIn("unique selected source PDBs", md)
        self.assertIn("Source redundancy", md)


if __name__ == "__main__":
    unittest.main()
