"""Tests for the M6d W2 next-branch manifest-design artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_next_branch_manifest_design import (
    build_manifest_design,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _target(target_id, source):
    return {
        "id": target_id,
        "rcsb_id": source,
        "source_pdb": f"hpc_outputs/source_{source}.pdb",
        "prepared_pdb": f"hpc_outputs/{target_id}/prepared.pdb",
        "prep_report": f"hpc_outputs/{target_id}/prepared.report.json",
        "target_chain": "A",
        "binder_chain": "B",
        "target_fasta": f"hpc_outputs/{target_id}/target.fasta",
        "target_fasta_report": f"hpc_outputs/{target_id}/target.fasta.report.json",
        "target_msa": f"hpc_outputs/{target_id}/target.a3m",
        "target_msa_report": f"hpc_outputs/{target_id}/target.a3m.report.json",
        "records": f"hpc_outputs/{target_id}/records.jsonl",
    }


def _candidate_pool(admitted):
    return {
        "status": "next_branch_candidates_ready_for_manifest_design",
        "ready_for_revised_manifest": True,
        "ready_for_cayuga_submission": False,
        "min_non_anchor_candidates_for_revised_manifest": 2,
        "admitted_targets": admitted,
    }


class M6DW2NextBranchManifestDesignTests(unittest.TestCase):
    def test_build_manifest_design_selects_admitted_source_diverse_targets(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "inventory.json")
            _write_json(manifest, {
                "defaults": {"num_seq": 100, "temp": 0.3, "seed": 37, "objective": "binder"},
                "targets": [
                    _target("A_AB", "SRC1"),
                    _target("B_AB", "SRC2"),
                    _target("held_AB", "SRC3"),
                ],
            })

            rep, out_manifest = build_manifest_design(
                _candidate_pool(["A_AB", "B_AB"]),
                [manifest],
                out_manifest="configs/out.json",
            )

        self.assertEqual(rep["status"], "next_branch_manifest_ready_for_strict_preflight")
        self.assertTrue(rep["ready_for_strict_preflight"])
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertEqual(rep["selected_targets"], ["A_AB", "B_AB"])
        self.assertEqual(rep["n_unique_selected_sources"], 2)
        self.assertEqual([row["id"] for row in out_manifest["targets"]], ["A_AB", "B_AB"])
        self.assertEqual(out_manifest["targets"][0]["_next_branch_admission"]["source_manifest"], manifest)

    def test_duplicate_source_blocks_preflight_ready(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "inventory.json")
            _write_json(manifest, {
                "targets": [
                    _target("A_AB", "SRC1"),
                    _target("A_AC", "SRC1"),
                ],
            })

            rep, _out_manifest = build_manifest_design(
                _candidate_pool(["A_AB", "A_AC"]),
                [manifest],
                out_manifest="configs/out.json",
            )

        self.assertEqual(rep["status"], "next_branch_manifest_design_blocked")
        self.assertFalse(rep["ready_for_strict_preflight"])
        self.assertEqual(rep["duplicate_sources"], ["SRC1"])
        self.assertEqual(rep["failures"][0]["kind"], "duplicate_source_pdb")

    def test_not_ready_candidate_pool_blocks_manifest_design(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "inventory.json")
            _write_json(manifest, {"targets": [_target("A_AB", "SRC1")]})
            pool = _candidate_pool(["A_AB"])
            pool["ready_for_revised_manifest"] = False

            rep, _out_manifest = build_manifest_design(pool, [manifest], out_manifest="configs/out.json")

        self.assertEqual(rep["status"], "next_branch_manifest_design_blocked")
        self.assertIn("candidate_pool_not_ready", [failure["kind"] for failure in rep["failures"]])

    def test_markdown_names_claim_boundary(self):
        rep = {
            "date": "2026-06-30",
            "status": "next_branch_manifest_ready_for_strict_preflight",
            "ready_for_strict_preflight": True,
            "ready_for_cayuga_submission": False,
            "target_manifest": "configs/out.json",
            "n_admitted_targets": 2,
            "n_selected_targets": 2,
            "n_unique_selected_sources": 2,
            "duplicate_sources": [],
            "selected_targets": ["A_AB"],
            "selected_sources": ["A"],
            "failures": [],
            "next_action": "run strict preflight",
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Next-Branch Manifest Design", md)
        self.assertIn("Ready for Cayuga submission: `false`", md)
        self.assertIn("does not certify W2", md)

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            inventory = os.path.join(d, "inventory.json")
            pool = os.path.join(d, "pool.json")
            out_manifest = os.path.join(d, "out_manifest.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            _write_json(inventory, {
                "targets": [_target("A_AB", "SRC1"), _target("B_AB", "SRC2")],
            })
            _write_json(pool, _candidate_pool(["A_AB", "B_AB"]))

            rc = main([
                "--candidate-pool", pool,
                "--inventory-manifest", inventory,
                "--out-manifest", out_manifest,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_manifest))
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
