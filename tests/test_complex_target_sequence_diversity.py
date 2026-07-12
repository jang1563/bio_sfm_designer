"""Tests for target-sequence diversity auditing."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.complex_target_sequence_diversity import (
    _coverage_identity,
    audit_sequence_diversity,
    main,
    render_markdown,
    write_representative_manifest,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _write_manifest(root, sequences):
    targets = []
    for target_id, seq in sequences:
        fasta = os.path.join(root, f"{target_id}.fasta")
        _write(fasta, f">{target_id}\n{seq}\n")
        targets.append({
            "id": target_id,
            "rcsb_id": target_id[:4].upper(),
            "prepared_pdb": os.path.join(root, f"{target_id}.pdb"),
            "target_chain": "A",
            "binder_chain": "B",
            "target_fasta": fasta,
            "target_msa": os.path.join(root, f"{target_id}.a3m"),
        })
    manifest = os.path.join(root, "targets.json")
    _write(manifest, json.dumps({"defaults": {"num_seq": 40}, "targets": targets}) + "\n")
    return manifest


class ComplexTargetSequenceDiversityTests(unittest.TestCase):
    def test_global_alignment_recovers_identity_after_terminal_insertion(self):
        metrics = _coverage_identity("ACDEFGHIK", "XACDEFGHIK")
        self.assertEqual(metrics["matches"], 9)
        self.assertEqual(metrics["aligned_length"], 10)
        self.assertEqual(metrics["coverage_identity"], 0.9)
        self.assertEqual(metrics["alignment_identity"], 0.9)

    def test_three_distinct_sequence_clusters_are_ready(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = _write_manifest(d, [
                ("t1", "AAAAAA"),
                ("t2", "CCCCCC"),
                ("t3", "GGGGGG"),
            ])

            rep = audit_sequence_diversity(manifest, min_clusters=3)

            self.assertEqual(rep["status"], "sequence_diversity_ready_for_broad_w2_panel")
            self.assertTrue(rep["ready_for_broad_w2_panel"])
            self.assertEqual(rep["n_sequence_clusters"], 3)
            self.assertEqual(rep["largest_cluster_fraction"], 0.333333)

    def test_dominant_near_duplicate_cluster_blocks_broad_claim(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = _write_manifest(d, [
                ("t1", "AAAAAA"),
                ("t2", "AAAAAA"),
                ("t3", "AAAAAA"),
                ("t4", "CCCCCC"),
                ("t5", "GGGGGG"),
            ])

            rep = audit_sequence_diversity(manifest, min_clusters=3, max_largest_cluster_fraction=0.5)

            self.assertEqual(rep["status"], "sequence_diversity_dominated_by_near_duplicates")
            self.assertFalse(rep["ready_for_broad_w2_panel"])
            self.assertEqual(rep["n_sequence_clusters"], 3)
            self.assertEqual(rep["largest_cluster_size"], 3)
            self.assertEqual(rep["representative_target_ids"], ["t1", "t4", "t5"])

    def test_too_few_clusters_blocks_before_msa_precompute(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = _write_manifest(d, [
                ("t1", "AAAAAA"),
                ("t2", "AAAAAA"),
                ("t3", "CCCCCC"),
            ])

            rep = audit_sequence_diversity(manifest, min_clusters=3)

            self.assertEqual(rep["status"], "sequence_diversity_too_few_clusters")
            self.assertFalse(rep["ready_for_broad_w2_panel"])
            self.assertIn("Expand seed discovery", rep["next_action"])

    def test_representative_manifest_preserves_original_targets(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = _write_manifest(d, [
                ("t1", "AAAAAA"),
                ("t2", "AAAAAA"),
                ("t3", "CCCCCC"),
            ])
            out = os.path.join(d, "representatives.json")

            rep = audit_sequence_diversity(manifest, min_clusters=2)
            write_representative_manifest(manifest, rep["representative_target_ids"], out)

            with open(out) as fh:
                representative = json.load(fh)
            self.assertEqual(representative["defaults"], {"num_seq": 40})
            self.assertEqual([target["id"] for target in representative["targets"]], ["t1", "t3"])
            self.assertIn("does not certify", representative["_note"])

    def test_cli_writes_json_markdown_and_representative_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = _write_manifest(d, [
                ("t1", "AAAAAA"),
                ("t2", "AAAAAA"),
                ("t3", "CCCCCC"),
            ])
            out_json = os.path.join(d, "audit.json")
            out_md = os.path.join(d, "audit.md")
            out_reps = os.path.join(d, "representatives.json")

            rc = main([
                "--manifest", manifest,
                "--min-clusters", "2",
                "--out-json", out_json,
                "--out-md", out_md,
                "--out-representative-manifest", out_reps,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_reps))
            with open(out_json) as fh:
                report = json.load(fh)
            md = render_markdown(report)
            self.assertIn("Complex Target Sequence Diversity Audit", md)
            self.assertIn("Ready for broad W2 panel", md)


if __name__ == "__main__":
    unittest.main()
