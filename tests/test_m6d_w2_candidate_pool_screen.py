"""Tests for the M6d W2 candidate-pool screen."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_candidate_pool_screen import (
    DEFAULT_DIAGNOSTICS,
    DEFAULT_MANIFESTS,
    build_report,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _prep(path, contacts=25, gaps=False):
    _write_json(path, {
        "target_chain": "A",
        "binder_chain": "B",
        "target_ca_residues": 100,
        "binder_ca_residues": 80,
        "target_numbering_gaps": [{"after": 1, "before": 3, "missing": 1}] if gaps else [],
        "binder_numbering_gaps": [],
        "ca_interface_contacts": contacts,
        "min_ca_distance": 4.2,
    })


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x\n")


def _manifest(path, target_id, prep_report):
    base = os.path.dirname(path)
    files = {
        "source_pdb": os.path.join(base, f"{target_id}.source.pdb"),
        "prepared_pdb": os.path.join(base, f"{target_id}.prepared.pdb"),
        "target_fasta": os.path.join(base, f"{target_id}.fasta"),
        "target_msa": os.path.join(base, f"{target_id}.a3m"),
        "target_msa_report": os.path.join(base, f"{target_id}.a3m.report.json"),
    }
    for file_path in files.values():
        _touch(file_path)
    _write_json(path, {
        "targets": [{
            "id": target_id,
            "prep_report": prep_report,
            "target_chain": "A",
            "binder_chain": "B",
            **files,
        }]
    })


class M6DW2CandidatePoolScreenTests(unittest.TestCase):
    def test_unknown_structurally_valid_candidate_is_admitted_for_pilot(self):
        with tempfile.TemporaryDirectory() as d:
            prep = os.path.join(d, "prep.json")
            _prep(prep)
            manifest = os.path.join(d, "manifest.json")
            _manifest(manifest, "new_target", prep)
            branch = {"target_decisions": []}

            rep = build_report([manifest], [], branch)

            self.assertEqual(rep["status"], "pilot_candidates_admitted")
            self.assertEqual(rep["n_admitted_for_pilot"], 1)
            self.assertTrue(rep["ready_for_revised_manifest"])
            self.assertFalse(rep["ready_for_cayuga_submission"])

    def test_known_negative_candidate_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as d:
            prep = os.path.join(d, "prep.json")
            _prep(prep)
            manifest = os.path.join(d, "manifest.json")
            _manifest(manifest, "weak", prep)
            diagnostic = os.path.join(d, "diag.json")
            _write_json(diagnostic, {
                "targets": [{
                    "complex_target_id": "weak",
                    "classification": "target_protocol_mismatch_low_success",
                    "success_rate": 0.1,
                    "protocol_cutoff_accepts": 0,
                }]
            })
            branch = {"target_decisions": []}

            rep = build_report([manifest], [diagnostic], branch)

            self.assertEqual(rep["status"], "no_current_non_anchor_admissions")
            self.assertEqual(rep["screened_targets"][0]["verdict"], "reject_for_current_w2_branch")

    def test_branch_freeze_blocks_positive_control_from_admission(self):
        with tempfile.TemporaryDirectory() as d:
            prep = os.path.join(d, "prep.json")
            _prep(prep)
            manifest = os.path.join(d, "manifest.json")
            _manifest(manifest, "3PC8_AB", prep)
            branch = {
                "target_decisions": [{
                    "target": "3PC8_AB",
                    "branch_decision": "freeze_as_target_specific_positive_control",
                }]
            }

            rep = build_report([manifest], [], branch)

            self.assertFalse(rep["screened_targets"][0]["admitted_for_pilot"])
            self.assertEqual(
                rep["screened_targets"][0]["verdict"],
                "frozen_positive_control_not_admitted",
            )

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            prep = os.path.join(d, "prep.json")
            _prep(prep)
            manifest = os.path.join(d, "manifest.json")
            _manifest(manifest, "new_target", prep)
            branch = os.path.join(d, "branch.json")
            _write_json(branch, {"target_decisions": []})
            out_json = os.path.join(d, "screen.json")
            out_md = os.path.join(d, "screen.md")

            rc = main([
                "--candidate-manifest", manifest,
                "--revised-branch", branch,
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))

    def test_markdown_marks_not_submission_authority(self):
        rep = {
            "date": "2026-06-30",
            "status": "no_current_non_anchor_admissions",
            "ready_for_revised_manifest": False,
            "ready_for_cayuga_submission": False,
            "screened_targets": [],
            "next_action": "discover targets",
        }

        md = render_markdown(rep)

        self.assertIn("M6d W2 Candidate-Pool Screen", md)
        self.assertIn("Ready for Cayuga submission: `false`", md)
        self.assertIn("does not authorize Cayuga submission", md)

    def test_defaults_include_fresh_unique_source_pilot(self):
        self.assertIn(
            "configs/m6d_w2_fresh_discovery_unique_source_pilot_targets.json",
            DEFAULT_MANIFESTS,
        )
        self.assertIn(
            "results/m6d_w2_fresh_discovery_unique_source_pilot_diagnostic.json",
            DEFAULT_DIAGNOSTICS,
        )


if __name__ == "__main__":
    unittest.main()
