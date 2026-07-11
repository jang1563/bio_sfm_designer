"""Tests for RCSB seed expansion planning."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_rcsb_seed_expansion import (
    build_query,
    build_seed_expansion,
    main,
)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _response(ids):
    return {
        "total_count": len(ids),
        "result_set": [{"identifier": value} for value in ids],
    }


def _rules():
    return {
        "excluded_source_ids_under_current_protocol": ["EXCL"],
        "excluded_source_rcsb_ids": ["RCSB"],
        "excluded_targets_under_current_protocol": ["TARG_A"],
        "anchors_not_for_immediate_scale": ["ANCH_B"],
        "positive_controls_not_generalization_targets": ["POS_C"],
    }


def _seed_config(ids):
    return {"seeds": [{"rcsb_id": value} for value in ids]}


class M6DW2RcsbSeedExpansionTests(unittest.TestCase):
    def test_build_query_uses_entry_search_contract(self):
        query = build_query(rows=12, min_protein_entities=2, max_resolution=2.5)

        self.assertEqual(query["return_type"], "entry")
        self.assertEqual(query["request_options"]["paginate"]["rows"], 12)
        attrs = [node["parameters"]["attribute"] for node in query["query"]["nodes"]]
        self.assertIn("rcsb_entry_info.polymer_entity_count_protein", attrs)
        self.assertIn("rcsb_entry_info.resolution_combined", attrs)

    def test_seed_expansion_filters_rules_and_previous_seeds(self):
        rep, seed_config = build_seed_expansion(
            _response(["old1", "EXCL", "RCSB", "TARG", "ANCH", "POS", "NEW1", "NEW2", "NEW1", "NEW3"]),
            rules=_rules(),
            previous_seed_configs=[_seed_config(["OLD1"])],
            max_seeds=2,
            date="2026-06-30",
            branch_id="w2_target_family_redesign_v2",
            min_sequence_clusters=4,
            max_largest_cluster_fraction=0.4,
        )

        self.assertEqual(rep["status"], "seed_expansion_ready_for_local_structural_intake")
        self.assertEqual(rep["branch_id"], "w2_target_family_redesign_v2")
        self.assertEqual(rep["selected_seed_ids"], ["NEW1", "NEW2"])
        self.assertEqual([row["rcsb_id"] for row in seed_config["seeds"]], ["NEW1", "NEW2"])
        self.assertEqual(
            seed_config["selection_boundary"]["branch_id"],
            "w2_target_family_redesign_v2",
        )
        self.assertTrue(
            seed_config["selection_boundary"]["sequence_diversity_audit_required_before_msa"]
        )
        self.assertEqual(
            rep["sequence_diversity_preconditions"]["min_sequence_clusters"],
            4,
        )
        self.assertEqual(
            rep["sequence_diversity_preconditions"]["max_largest_cluster_fraction"],
            0.4,
        )
        self.assertFalse(rep["ready_for_target_msa_precompute"])
        self.assertFalse(rep["ready_for_cayuga_submission"])
        self.assertIn("EXCL", rep["excluded_source_ids"])
        self.assertIn("RCSB", rep["excluded_source_ids"])
        self.assertIn("OLD1", rep["already_screened_seed_sources"])

    def test_historical_registry_and_prior_report_sources_are_excluded(self):
        rep, seed_config = build_seed_expansion(
            _response(["HIST", "SCREENED", "NEW"]),
            historical_registry={"evaluated_source_rcsb_ids": ["HIST"]},
            previous_seed_configs=[{"selected_seed_ids": ["SCREENED"]}],
            max_seeds=3,
        )

        self.assertTrue(rep["historical_registry_applied"])
        self.assertEqual(rep["historical_evaluated_source_ids"], ["HIST"])
        self.assertEqual(rep["already_screened_seed_sources"], ["SCREENED"])
        self.assertEqual(rep["selected_seed_ids"], ["NEW"])
        self.assertEqual(seed_config["seeds"], [{"rcsb_id": "NEW"}])

    def test_empty_after_filtering_is_fail_closed(self):
        rep, seed_config = build_seed_expansion(
            _response(["OLD1", "EXCL"]),
            rules=_rules(),
            previous_seed_configs=[_seed_config(["OLD1"])],
            max_seeds=3,
            date="2026-06-30",
        )

        self.assertEqual(rep["status"], "seed_expansion_empty")
        self.assertFalse(rep["ready_for_local_structural_intake"])
        self.assertEqual(seed_config["seeds"], [])

    def test_cli_replays_saved_response(self):
        with tempfile.TemporaryDirectory() as d:
            response = os.path.join(d, "response.json")
            rules = os.path.join(d, "rules.json")
            previous = os.path.join(d, "previous.json")
            out_json = os.path.join(d, "out.json")
            out_md = os.path.join(d, "out.md")
            out_seed = os.path.join(d, "seeds.json")
            out_query = os.path.join(d, "query.json")
            out_response = os.path.join(d, "response_out.json")
            _write_json(response, _response(["OLD1", "NEW1"]))
            _write_json(rules, _rules())
            _write_json(previous, _seed_config(["OLD1"]))

            rc = main([
                "--search-response", response,
                "--candidate-rules", rules,
                "--previous-seed-config", previous,
                "--max-seeds", "5",
                "--date", "2026-06-30",
                "--out-json", out_json,
                "--out-md", out_md,
                "--out-seed-config", out_seed,
                "--out-query", out_query,
                "--out-response", out_response,
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_json))
            self.assertTrue(os.path.exists(out_md))
            self.assertTrue(os.path.exists(out_seed))
            self.assertTrue(os.path.exists(out_query))
            self.assertTrue(os.path.exists(out_response))


if __name__ == "__main__":
    unittest.main()
