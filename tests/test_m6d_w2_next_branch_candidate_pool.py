"""Tests for the M6d W2 next-branch candidate-pool artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_next_branch_candidate_pool import (
    DEFAULT_INVENTORY_MANIFESTS,
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x\n")


def _prep(path, contacts=25):
    _write_json(path, {
        "ca_interface_contacts": contacts,
        "target_ca_residues": 120,
        "binder_ca_residues": 80,
        "target_numbering_gaps": [],
        "binder_numbering_gaps": [],
        "min_ca_distance": 4.1,
    })


def _target(base, target_id, rcsb_id):
    prep = os.path.join(base, f"{target_id}.prep.json")
    _prep(prep)
    fields = {
        "source_pdb": os.path.join(base, f"{target_id}.source.pdb"),
        "prepared_pdb": os.path.join(base, f"{target_id}.prepared.pdb"),
        "target_fasta": os.path.join(base, f"{target_id}.fasta"),
        "target_fasta_report": os.path.join(base, f"{target_id}.fasta.report.json"),
        "target_msa": os.path.join(base, f"{target_id}.a3m"),
        "target_msa_report": os.path.join(base, f"{target_id}.a3m.report.json"),
    }
    for path in fields.values():
        _touch(path)
    return {"id": target_id, "rcsb_id": rcsb_id, "prep_report": prep, **fields}


def _target_without_msa(base, target_id, rcsb_id):
    target = _target(base, target_id, rcsb_id)
    os.remove(target["target_msa"])
    os.remove(target["target_msa_report"])
    return target


def _rules(**overrides):
    rules = {
        "protocol_id": "test_protocol",
        "selected_design": "test_design",
        "excluded_targets_under_current_protocol": ["bad_A"],
        "positive_controls_not_generalization_targets": [],
        "anchors_not_for_immediate_scale": [],
        "candidate_requirements": {
            "min_non_anchor_candidates_for_revised_manifest": 3,
            "min_ca_interface_contacts": 20,
            "require_source_pdb_deduplication": True,
            "require_prepared_pdb": True,
            "require_prep_report": True,
            "require_target_fasta": True,
            "require_target_fasta_report": True,
            "require_target_msa": True,
            "require_target_msa_report": True,
        },
    }
    rules.update(overrides)
    return rules


class M6DW2NextBranchCandidatePoolTests(unittest.TestCase):
    def test_source_redundant_candidate_is_audit_only(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [
                _target(d, "bad_A", "SRC1"),
                _target(d, "sibling_B", "SRC1"),
            ]})

            rep = build_report(_rules(), [manifest])

        by_target = {row["target"]: row for row in rep["screened_targets"]}
        self.assertEqual(by_target["bad_A"]["verdict"], "excluded_current_protocol")
        self.assertEqual(by_target["sibling_B"]["verdict"], "source_redundancy_audit_only")
        self.assertTrue(by_target["sibling_B"]["source_redundancy_audit_only"])
        self.assertEqual(rep["n_admitted_for_next_branch"], 0)
        self.assertEqual(rep["n_source_redundancy_audit_only"], 1)
        self.assertFalse(rep["ready_for_revised_manifest"])

    def test_explicit_excluded_source_ids_are_audit_only(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [_target(d, "sibling_B", "SRC1")]})

            rep = build_report(
                _rules(
                    excluded_targets_under_current_protocol=[],
                    excluded_source_ids_under_current_protocol=["SRC1"],
                ),
                [manifest],
            )

        by_target = {row["target"]: row for row in rep["screened_targets"]}
        self.assertEqual(by_target["sibling_B"]["verdict"], "source_redundancy_audit_only")
        self.assertEqual(rep["excluded_sources_from_current_protocol"], ["SRC1"])
        self.assertEqual(rep["n_admitted_for_next_branch"], 0)

    def test_existing_audit_plan_updates_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [
                _target(d, "bad_A", "SRC1"),
                _target(d, "sibling_B", "SRC1"),
            ]})

            rep = build_report(
                _rules(),
                [manifest],
                source_audit_plan={"status": "source_redundancy_audit_plan_ready_no_submit"},
            )

        self.assertEqual(
            rep["source_redundancy_audit_plan_status"],
            "source_redundancy_audit_plan_ready_no_submit",
        )
        self.assertIn("already exists", rep["next_action"])
        self.assertNotIn("or write", rep["next_action"])

    def test_novel_structurally_valid_candidates_can_unlock_manifest_design(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [
                _target(d, "new_A", "SRC1"),
                _target(d, "new_B", "SRC2"),
            ]})
            rules = _rules(
                excluded_targets_under_current_protocol=[],
                candidate_requirements={
                    **_rules()["candidate_requirements"],
                    "min_non_anchor_candidates_for_revised_manifest": 2,
                },
            )

            rep = build_report(rules, [manifest])

        self.assertEqual(rep["status"], "next_branch_candidates_ready_for_manifest_design")
        self.assertEqual(rep["n_admitted_for_next_branch"], 2)
        self.assertTrue(rep["ready_for_revised_manifest"])
        self.assertFalse(rep["ready_for_cayuga_submission"])

    def test_novel_same_source_candidates_do_not_unlock_manifest_design(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [
                _target(d, "new_A", "SRC1"),
                _target(d, "new_B", "SRC1"),
                _target(d, "new_C", "SRC1"),
            ]})

            rep = build_report(_rules(excluded_targets_under_current_protocol=[]), [manifest])

        self.assertEqual(rep["n_admitted_for_next_branch"], 1)
        self.assertEqual(rep["n_source_redundancy_audit_only"], 2)
        self.assertFalse(rep["ready_for_revised_manifest"])
        by_target = {row["target"]: row for row in rep["screened_targets"]}
        self.assertEqual(by_target["new_A"]["verdict"], "admitted_for_next_branch_candidate_pool")
        self.assertEqual(by_target["new_B"]["verdict"], "source_redundancy_audit_only")
        self.assertEqual(by_target["new_C"]["verdict"], "source_redundancy_audit_only")

    def test_some_admitted_but_below_minimum_is_not_named_no_admitted(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [_target(d, "new_A", "SRC1")]})
            rules = _rules(
                excluded_targets_under_current_protocol=[],
                candidate_requirements={
                    **_rules()["candidate_requirements"],
                    "min_non_anchor_candidates_for_revised_manifest": 3,
                },
            )

            rep = build_report(rules, [manifest])

        self.assertEqual(rep["n_admitted_for_next_branch"], 1)
        self.assertEqual(rep["status"], "insufficient_admitted_candidates_expand_discovery")
        self.assertIn("at least 3", rep["next_action"])
        self.assertFalse(rep["ready_for_revised_manifest"])

    def test_missing_required_inputs_blocks_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            prep = os.path.join(d, "prep.json")
            _prep(prep)
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [{
                "id": "missing",
                "rcsb_id": "SRC1",
                "prep_report": prep,
                "source_pdb": os.path.join(d, "missing.pdb"),
            }]})

            rep = build_report(_rules(excluded_targets_under_current_protocol=[]), [manifest])

        self.assertEqual(
            rep["screened_targets"][0]["verdict"],
            "structural_or_input_preflight_blocked",
        )
        self.assertIn("missing_prepared_pdb", rep["screened_targets"][0]["reasons"])

    def test_missing_only_target_msa_points_to_precompute_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [_target_without_msa(d, "new_A", "SRC1")]})

            rep = build_report(_rules(excluded_targets_under_current_protocol=[]), [manifest])

        self.assertEqual(rep["status"], "target_msa_precompute_required_for_expanded_candidates")
        self.assertEqual(rep["n_target_msa_precompute_blocked"], 1)
        self.assertEqual(rep["target_msa_precompute_blocked_targets"], ["new_A"])
        self.assertIn("precompute target MSAs", rep["next_action"])
        self.assertFalse(rep["ready_for_revised_manifest"])
        self.assertFalse(rep["ready_for_cayuga_submission"])

    def test_defaults_include_full_fresh_inventory(self):
        self.assertIn(
            "configs/m6d_w2_fresh_discovery_complex_targets.json",
            DEFAULT_INVENTORY_MANIFESTS,
        )
        self.assertIn(
            "configs/m6d_w2_expanded_discovery_complex_targets.json",
            DEFAULT_INVENTORY_MANIFESTS,
        )

    def test_markdown_marks_source_redundancy_as_audit_only(self):
        rep = {
            "date": "2026-06-30",
            "status": "no_admitted_candidates_source_redundancy_audit_only",
            "ready_for_revised_manifest": False,
            "ready_for_cayuga_submission": False,
            "n_candidates": 1,
            "n_admitted_for_next_branch": 0,
            "n_source_redundancy_audit_only": 1,
            "excluded_sources_from_current_protocol": ["SRC1"],
            "screened_targets": [{
                "target": "sibling",
                "rcsb_id": "SRC1",
                "verdict": "source_redundancy_audit_only",
                "admitted_for_next_branch": False,
                "source_redundancy_audit_only": True,
                "structural_preflight": {"ok": True, "ca_interface_contacts": 20},
            }],
            "next_action": "expand",
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Next-Branch Candidate Pool", md)
        self.assertIn("source_redundancy_audit_only", md)
        self.assertIn("does not authorize Cayuga submission", md)

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [_target(d, "new_A", "SRC1")]})
            rules = os.path.join(d, "rules.json")
            design = os.path.join(d, "design.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            _write_json(rules, _rules(excluded_targets_under_current_protocol=[]))
            _write_json(design, {"status": "design"})

            rc = main([
                "--candidate-rules", rules,
                "--source-design", design,
                "--inventory-manifest", manifest,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
