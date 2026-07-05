"""Tests for the W2 v9 staged target-MSA planning artifact."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_v9_staged_msa_plan import (
    build_plan,
    main,
    render_markdown,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _discovery_pool():
    return {
        "selected_candidates": [
            {
                "complex_target_id": "strong",
                "rcsb_id": "1AAA",
                "ca_interface_contacts": 180,
                "target_ca_residues": 100,
                "binder_ca_residues": 80,
                "chain_sequence_identity": 0.05,
                "min_ca_distance": 4.0,
            },
            {
                "complex_target_id": "large",
                "rcsb_id": "1BBB",
                "ca_interface_contacts": 140,
                "target_ca_residues": 220,
                "binder_ca_residues": 190,
                "chain_sequence_identity": 0.05,
                "min_ca_distance": 4.0,
            },
            {
                "complex_target_id": "prior",
                "rcsb_id": "1CCC",
                "ca_interface_contacts": 150,
                "target_ca_residues": 100,
                "binder_ca_residues": 80,
                "chain_sequence_identity": 0.05,
                "min_ca_distance": 4.0,
            },
            {
                "complex_target_id": "weak",
                "rcsb_id": "1DDD",
                "ca_interface_contacts": 24,
                "target_ca_residues": 100,
                "binder_ca_residues": 80,
                "chain_sequence_identity": 0.05,
                "min_ca_distance": 4.0,
            },
        ]
    }


def _sequence_diversity():
    return {
        "ok": True,
        "clusters": [
            {"cluster_id": 1, "target_ids": ["strong"]},
            {"cluster_id": 2, "target_ids": ["large"]},
            {"cluster_id": 3, "target_ids": ["prior"]},
            {"cluster_id": 4, "target_ids": ["weak"]},
        ],
    }


def _contract():
    return {"ready_for_cayuga_submission": False}


def _approval_packet(n=4):
    return {
        "target_count": n,
        "pending_path_count": n * 2,
        "can_submit_proteinmpnn_boltz_panel": False,
    }


def _manifest():
    return {
        "defaults": {"num_seq": 100},
        "targets": [
            {"id": "strong", "rcsb_id": "1AAA"},
            {"id": "large", "rcsb_id": "1BBB"},
            {"id": "prior", "rcsb_id": "1CCC"},
            {"id": "weak", "rcsb_id": "1DDD"},
        ],
    }


class M6DW2V9StagedMsaPlanTests(unittest.TestCase):
    def test_build_plan_ranks_and_writes_pilot_manifest_without_submit(self):
        with tempfile.TemporaryDirectory() as d:
            prior_report = os.path.join(d, "prior.json")
            pilot_manifest = os.path.join(d, "pilot.json")
            _write_json(prior_report, {
                "targets": [{"complex_target_id": "prior", "certified": False}]
            })

            rep = build_plan(
                _discovery_pool(),
                _sequence_diversity(),
                _contract(),
                _approval_packet(),
                _manifest(),
                prior_negative_panel_reports=[prior_report],
                pilot_size=3,
                expansion_size=1,
                pilot_manifest_path=pilot_manifest,
            )

            self.assertTrue(rep["audit_ok"])
            self.assertEqual(rep["status"], "staged_target_msa_plan_ready_no_submit")
            self.assertEqual(rep["stages"]["pilot_target_msa_targets"][0], "strong")
            self.assertIn("prior", rep["prior_negative_targets"])
            self.assertTrue(os.path.exists(pilot_manifest))
            with open(pilot_manifest) as fh:
                saved = json.load(fh)
            self.assertEqual(len(saved["targets"]), 3)
            self.assertEqual(
                rep["claim_boundary"]["proteinmpnn_boltz_panel_submission"],
                "blocked",
            )

    def test_blocks_packet_target_count_drift(self):
        rep = build_plan(
            _discovery_pool(),
            _sequence_diversity(),
            _contract(),
            _approval_packet(n=3),
            _manifest(),
            prior_negative_panel_reports=[],
        )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("approval_packet_target_count_mismatch", {f["kind"] for f in rep["failures"]})

    def test_cli_writes_plan_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {
                "pool": os.path.join(d, "pool.json"),
                "seq": os.path.join(d, "seq.json"),
                "contract": os.path.join(d, "contract.json"),
                "packet": os.path.join(d, "packet.json"),
                "manifest": os.path.join(d, "manifest.json"),
                "out": os.path.join(d, "plan.json"),
                "md": os.path.join(d, "plan.md"),
                "pilot": os.path.join(d, "pilot.json"),
            }
            _write_json(paths["pool"], _discovery_pool())
            _write_json(paths["seq"], _sequence_diversity())
            _write_json(paths["contract"], _contract())
            _write_json(paths["packet"], _approval_packet())
            _write_json(paths["manifest"], _manifest())

            rc = main([
                "--discovery-pool", paths["pool"],
                "--sequence-diversity", paths["seq"],
                "--followup-contract", paths["contract"],
                "--approval-packet", paths["packet"],
                "--target-manifest", paths["manifest"],
                "--prior-negative-panel-report", os.path.join(d, "absent.json"),
                "--out-json", paths["out"],
                "--out-md", paths["md"],
                "--pilot-manifest", paths["pilot"],
            ])

            self.assertEqual(rc, 0)
            with open(paths["out"]) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["audit_ok"])
            self.assertIn("Staged Target-MSA Plan", render_markdown(rep))


if __name__ == "__main__":
    unittest.main()
