"""Build and audit the W3c-A fresh target representation lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from bio_sfm_designer.experiments.m6d_w2_fresh_discovery_pool import (
    _load_chain_cas,
    _sequence,
)
from bio_sfm_designer.experiments.m6d_w3c_target_validity import (
    _chain_description,
    _deserialize_structure,
    _interface,
    _parse_pdb,
    _serialize_structure,
)


_STATUS = "w3c_a_fresh_target_representation_lock_complete_no_submit"
_OVERLAP_STATUS = "w3c_historical_overlap_registry_locked"
_FIXTURE_STATUS = "public_cpu_replay_fixture"
_CANONICAL_OUTPUTS = (
    "configs/m6d_w3c_fresh_targets.json",
    "results/m6d_w3c_fresh_target_lock.json",
    "results/m6d_w3c_fresh_target_lock.md",
)
_BRANCH_MANIFESTS = {
    "W2b": "configs/m6d_w2b_target_adaptive_fit_targets.json",
    "W2c": "configs/m6d_w2c_fresh_targets.json",
    "W3b": "configs/m6d_w3b_fresh_targets.json",
}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_binding(path: str) -> Dict[str, Any]:
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "sha256": _sha256_file(path),
    }


def _target_rows(payload: Mapping[str, Any], label: str) -> List[Dict[str, Any]]:
    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must contain nonempty object target rows")
    return [dict(row) for row in rows]


def _bound_file_matches(binding: Mapping[str, Any]) -> bool:
    path = binding.get("path")
    return (
        isinstance(path, str)
        and os.path.isfile(path)
        and binding.get("bytes") == os.path.getsize(path)
        and binding.get("sha256") == _sha256_file(path)
    )


def build_historical_overlap_registry(
    source_registry_path: str,
    branch_manifest_paths: Mapping[str, str],
) -> Dict[str, Any]:
    source_registry = _load_json(source_registry_path)
    source_ids = source_registry.get("evaluated_source_rcsb_ids")
    target_ids = source_registry.get("evaluated_target_ids")
    if not isinstance(source_ids, list) or not isinstance(target_ids, list):
        raise ValueError("historical source registry is missing evaluated IDs")

    branch_rows: List[Dict[str, Any]] = []
    manifest_bindings: Dict[str, Dict[str, Any]] = {}
    for branch in ("W2b", "W2c", "W3b"):
        path = branch_manifest_paths.get(branch)
        if not isinstance(path, str):
            raise ValueError(f"missing historical branch manifest: {branch}")
        manifest = _load_json(path)
        manifest_bindings[branch] = _file_binding(path)
        rows = _target_rows(manifest, f"{branch} manifest")
        if len(rows) != 8:
            raise ValueError(f"{branch} manifest must contain exactly eight targets")
        for row in rows:
            target_id = row.get("id")
            rcsb_id = row.get("rcsb_id")
            target_chain = row.get("target_chain")
            if not all(isinstance(value, str) and value for value in (target_id, rcsb_id, target_chain)):
                raise ValueError(f"invalid historical target identity in {branch}")
            sequence_hash = row.get("target_sequence_sha256")
            hash_source = "manifest_field"
            sequence_length = None
            if not _is_sha256(sequence_hash):
                report_path = row.get("target_fasta_report")
                if not isinstance(report_path, str) or not os.path.isfile(report_path):
                    raise ValueError(f"historical target sequence unavailable: {target_id}")
                report = _load_json(report_path)
                sequence = report.get("sequence")
                if not isinstance(sequence, str) or not sequence:
                    raise ValueError(f"historical FASTA report has no sequence: {target_id}")
                sequence_hash = _sha256_text(sequence)
                sequence_length = len(sequence)
                hash_source = "local_target_fasta_report_at_registry_freeze"
            branch_rows.append(
                {
                    "historical_branch": branch,
                    "target_id": target_id,
                    "rcsb_id": rcsb_id.upper(),
                    "target_chain": target_chain,
                    "target_sequence_sha256": sequence_hash,
                    "target_sequence_length": sequence_length,
                    "hash_source": hash_source,
                }
            )

    branch_target_ids = [row["target_id"] for row in branch_rows]
    branch_sources = [row["rcsb_id"] for row in branch_rows]
    branch_hashes = [row["target_sequence_sha256"] for row in branch_rows]
    if len(branch_target_ids) != 24 or len(set(branch_target_ids)) != 24:
        raise ValueError("historical W2b/W2c/W3b target IDs must be 24 unique values")
    if len(set(branch_hashes)) != 24:
        raise ValueError("historical W2b/W2c/W3b target sequence hashes must be unique")

    excluded_target_ids = sorted(set(str(value) for value in target_ids).union(branch_target_ids))
    excluded_sources = sorted(
        set(str(value).upper() for value in source_ids).union(branch_sources)
    )
    return {
        "artifact": "m6d_w3c_historical_overlap_registry",
        "version": 1,
        "status": _OVERLAP_STATUS,
        "date": "2026-07-15",
        "audit_ok": True,
        "inputs": {
            "historical_source_registry": _file_binding(source_registry_path),
            "historical_branch_manifests": manifest_bindings,
        },
        "counts": {
            "historical_evidence_target_ids": len(target_ids),
            "historical_evidence_source_ids": len(source_ids),
            "historical_representative_targets": len(branch_rows),
            "excluded_target_ids": len(excluded_target_ids),
            "excluded_source_rcsb_ids": len(excluded_sources),
            "excluded_target_sequence_hashes": len(set(branch_hashes)),
        },
        "excluded_target_ids": excluded_target_ids,
        "excluded_source_rcsb_ids": excluded_sources,
        "excluded_target_sequence_sha256": sorted(set(branch_hashes)),
        "historical_representative_targets": sorted(
            branch_rows, key=lambda row: (row["historical_branch"], row["target_id"])
        ),
        "predictor_outputs_consumed": False,
        "generated_design_labels_consumed": False,
        "claim_boundary": (
            "Exact target, RCSB source, and target-sequence exclusion registry only; membership and "
            "non-membership carry no binder-quality or predictor-performance label."
        ),
        "no_submit": True,
        "cayuga_submission_allowed": False,
    }


def build_structure_fixture(candidate_config_path: str) -> Dict[str, Any]:
    candidates = _load_json(candidate_config_path)
    rows = []
    for target in _target_rows(candidates, "W3c candidate config"):
        target_id = target.get("id")
        rcsb_id = target.get("rcsb_id")
        source_pdb = target.get("source_pdb")
        target_chain = target.get("target_chain")
        binder_chain = target.get("binder_chain")
        if not all(
            isinstance(value, str) and value
            for value in (target_id, rcsb_id, source_pdb, target_chain, binder_chain)
        ):
            raise ValueError("candidate target identity is incomplete")
        if not os.path.isfile(source_pdb) or os.path.getsize(source_pdb) <= 0:
            raise ValueError(f"candidate source PDB is missing: {source_pdb}")
        parsed = _parse_pdb(source_pdb)
        chain_cas = _load_chain_cas(source_pdb)
        if target_chain not in chain_cas or binder_chain not in chain_cas:
            raise ValueError(f"selected chain missing from source: {target_id}")
        target_sequence = _sequence(chain_cas[target_chain])
        binder_sequence = _sequence(chain_cas[binder_chain])
        rows.append(
            {
                "target_id": target_id,
                "rcsb_id": rcsb_id.upper(),
                "source_pdb": {
                    "path": source_pdb,
                    "bytes": os.path.getsize(source_pdb),
                    "sha256": _sha256_file(source_pdb),
                    "rcsb_download_url": (
                        f"https://files.rcsb.org/download/{rcsb_id.upper()}.pdb"
                    ),
                },
                "selected_sequences": {
                    "target_chain": target_chain,
                    "target_sequence": target_sequence,
                    "target_sequence_sha256": _sha256_text(target_sequence),
                    "binder_chain": binder_chain,
                    "binder_sequence": binder_sequence,
                    "binder_sequence_sha256": _sha256_text(binder_sequence),
                },
                "structure": _serialize_structure(parsed),
            }
        )
    return {
        "artifact": "m6d_w3c_fresh_structure_fixture",
        "version": 1,
        "status": _FIXTURE_STATUS,
        "source": "RCSB PDB legacy-format entries",
        "coordinate_scope": "first-model CA coordinates for all protein chains in each source entry",
        "candidate_config_sha256": _sha256_file(candidate_config_path),
        "targets": rows,
    }


def _fixture_map(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows:
        raise ValueError("fresh structure fixture has no targets")
    output: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("fresh structure fixture rows must be objects")
        target_id = row.get("target_id")
        if not isinstance(target_id, str) or not target_id or target_id in output:
            raise ValueError("invalid or duplicate fresh fixture target ID")
        output[target_id] = dict(row)
    return output


def _overlap_sets(registry: Mapping[str, Any]) -> Tuple[Set[str], Set[str], Set[str]]:
    if (
        registry.get("artifact") != "m6d_w3c_historical_overlap_registry"
        or registry.get("version") != 1
        or registry.get("status") != _OVERLAP_STATUS
        or registry.get("audit_ok") is not True
        or registry.get("predictor_outputs_consumed") is not False
        or registry.get("generated_design_labels_consumed") is not False
    ):
        raise ValueError("invalid W3c historical overlap registry")
    targets = registry.get("excluded_target_ids")
    sources = registry.get("excluded_source_rcsb_ids")
    sequences = registry.get("excluded_target_sequence_sha256")
    if not all(isinstance(values, list) and values for values in (targets, sources, sequences)):
        raise ValueError("W3c overlap registry has incomplete exclusion sets")
    if any(not _is_sha256(value) for value in sequences):
        raise ValueError("W3c overlap registry has an invalid sequence hash")
    return set(targets), set(sources), set(sequences)


def _protocol_gate(protocol: Mapping[str, Any]) -> Dict[str, Any]:
    discovery = protocol.get("target_discovery")
    validity = protocol.get("target_validity_gate")
    stages = protocol.get("stages")
    if not isinstance(discovery, dict) or not isinstance(validity, dict) or not isinstance(stages, list):
        raise ValueError("invalid W3c protocol structure")
    stage_a = next((row for row in stages if row.get("stage") == "W3c-A"), {})
    checks = {
        "protocol_identity": (
            protocol.get("artifact") == "m6d_w3c_validity_first_protocol"
            and protocol.get("version") == 1
            and protocol.get("status") == "preregistered_target_discovery_only_no_submit"
        ),
        "target_count": discovery.get("required_targets") == 8,
        "freshness_scope": (
            discovery.get("fresh_source_required") is True
            and discovery.get("exclude_all_historical_target_ids") is True
            and discovery.get("exclude_all_historical_rcsb_sources") is True
            and discovery.get("exclude_all_historical_target_sequence_hashes") is True
        ),
        "label_blind_selection": (
            discovery.get("selection_may_use_predictor_outputs") is False
            and discovery.get("selection_may_use_generated_design_labels") is False
        ),
        "structural_gate": (
            validity.get("author_determined_biological_unit") == "DIMERIC"
            and validity.get("selected_pair_must_be_complete_protein_assembly") is True
            and validity.get("selected_chains_must_be_distinct_molecule_entities") is True
            and validity.get("manual_target_binder_semantic_verdict") == "pass"
            and validity.get("minimum_ca_residues_per_chain") == 40
            and validity.get("ca_contact_cutoff_angstrom") == 8.0
            and validity.get("minimum_ca_contact_pairs") == 20
            and validity.get("unreviewed_numbering_gaps_allowed") is False
            and validity.get("manual_exceptions_after_predictor_output") is False
        ),
        "stage_a_cpu_only": (
            stage_a.get("compute") == "CPU and metadata only"
            and stage_a.get("proteinmpnn_designs") == 0
            and stage_a.get("predictor_evaluations") == 0
            and stage_a.get("approval_required") is False
        ),
        "no_submit": (
            protocol.get("no_submit") is True
            and protocol.get("cayuga_submission_allowed") is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3c protocol gate failed: {', '.join(failed)}")
    return {"discovery": discovery, "validity": validity, "checks": checks}


def _registry_bindings_match(registry: Mapping[str, Any]) -> bool:
    inputs = registry.get("inputs")
    if not isinstance(inputs, dict):
        return False
    source = inputs.get("historical_source_registry")
    manifests = inputs.get("historical_branch_manifests")
    return (
        isinstance(source, dict)
        and _bound_file_matches(source)
        and isinstance(manifests, dict)
        and set(manifests) == {"W2b", "W2c", "W3b"}
        and all(isinstance(binding, dict) and _bound_file_matches(binding) for binding in manifests.values())
    )


def build_lock(
    candidate_config_path: str,
    overlap_registry_path: str,
    protocol_path: str,
    structure_fixture_path: str,
    *,
    verify_local_sources: bool = False,
) -> Dict[str, Dict[str, Any]]:
    candidates = _load_json(candidate_config_path)
    overlap_registry = _load_json(overlap_registry_path)
    protocol = _load_json(protocol_path)
    fixture = _load_json(structure_fixture_path)
    gate = _protocol_gate(protocol)
    excluded_targets, excluded_sources, excluded_sequences = _overlap_sets(overlap_registry)
    candidate_rows = _target_rows(candidates, "W3c candidate config")
    fixture_rows = _fixture_map(fixture)

    candidate_ids = [row.get("id") for row in candidate_rows]
    candidate_sources = [str(row.get("rcsb_id") or "").upper() for row in candidate_rows]
    checks = {
        "candidate_config_identity": (
            candidates.get("artifact") == "m6d_w3c_fresh_target_candidates"
            and candidates.get("version") == 1
            and candidates.get("status")
            == "prospectively_selected_for_w3c_a_representation_lock_no_submit"
        ),
        "candidate_count_exact": len(candidate_rows) == 8,
        "candidate_ids_unique": len(candidate_ids) == 8 and len(set(candidate_ids)) == 8,
        "candidate_sources_unique": (
            len(candidate_sources) == 8 and len(set(candidate_sources)) == 8
        ),
        "fixture_identity": (
            fixture.get("artifact") == "m6d_w3c_fresh_structure_fixture"
            and fixture.get("version") == 1
            and fixture.get("status") == _FIXTURE_STATUS
        ),
        "fixture_candidate_binding": (
            fixture.get("candidate_config_sha256") == _sha256_file(candidate_config_path)
        ),
        "fixture_targets_exact": set(fixture_rows) == set(candidate_ids),
        "overlap_registry_bindings_exact": _registry_bindings_match(overlap_registry),
        "candidate_selection_label_blind": (
            isinstance(candidates.get("discovery"), dict)
            and candidates["discovery"].get("predictor_outputs_used") is False
            and candidates["discovery"].get("generated_design_labels_used") is False
            and candidates["discovery"].get("post_output_target_replacement_allowed") is False
        ),
        "candidate_no_compute_authority": (
            candidates.get("proteinmpnn_designs") == 0
            and candidates.get("predictor_evaluations") == 0
            and candidates.get("no_submit") is True
            and candidates.get("cayuga_submission_allowed") is False
        ),
    }
    checks.update({f"protocol_{name}": passed for name, passed in gate["checks"].items()})
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3c-A input lock failed: {', '.join(failed)}")

    minimum_residues = gate["validity"]["minimum_ca_residues_per_chain"]
    minimum_contacts = gate["validity"]["minimum_ca_contact_pairs"]
    cutoff = gate["validity"]["ca_contact_cutoff_angstrom"]
    output_rows = []
    local_verified = True
    for target in candidate_rows:
        target_id = target["id"]
        rcsb_id = str(target["rcsb_id"]).upper()
        target_chain = target["target_chain"]
        binder_chain = target["binder_chain"]
        fixture_row = fixture_rows[target_id]
        source = fixture_row.get("source_pdb")
        sequences = fixture_row.get("selected_sequences")
        if not isinstance(source, dict) or not isinstance(sequences, dict):
            raise ValueError(f"invalid fresh fixture provenance: {target_id}")
        if (
            fixture_row.get("rcsb_id") != rcsb_id
            or source.get("path") != target.get("source_pdb")
            or not isinstance(source.get("bytes"), int)
            or source.get("bytes", 0) <= 0
            or not _is_sha256(source.get("sha256"))
        ):
            raise ValueError(f"fresh fixture identity mismatch: {target_id}")
        if verify_local_sources:
            local_verified = local_verified and _bound_file_matches(source)

        parsed = _deserialize_structure(fixture_row.get("structure", {}), target_id)
        assembly = next(
            (
                row
                for row in parsed["assemblies"]
                if str(row.get("assembly_id")) == str(target.get("assembly_id"))
            ),
            None,
        )
        if not isinstance(assembly, dict):
            raise ValueError(f"selected assembly is missing: {target_id}")
        if target_chain not in parsed["chain_cas"] or binder_chain not in parsed["chain_cas"]:
            raise ValueError(f"selected chain is missing: {target_id}")
        target_description = _chain_description(parsed, target_chain)
        binder_description = _chain_description(parsed, binder_chain)
        interface = _interface(
            parsed["chain_cas"][target_chain],
            parsed["chain_cas"][binder_chain],
            cutoff,
        )
        target_sequence = sequences.get("target_sequence")
        binder_sequence = sequences.get("binder_sequence")
        target_hash = sequences.get("target_sequence_sha256")
        binder_hash = sequences.get("binder_sequence_sha256")
        row_checks = {
            "identity_exact": target_id == f"{rcsb_id}_{target_chain}{binder_chain}",
            "fixture_chain_identity": (
                sequences.get("target_chain") == target_chain
                and sequences.get("binder_chain") == binder_chain
            ),
            "sequence_hashes_exact": (
                isinstance(target_sequence, str)
                and isinstance(binder_sequence, str)
                and target_hash == _sha256_text(target_sequence)
                and binder_hash == _sha256_text(binder_sequence)
            ),
            "sequences_canonical": (
                isinstance(target_sequence, str)
                and isinstance(binder_sequence, str)
                and set(target_sequence).issubset(set("ACDEFGHIKLMNPQRSTVWY"))
                and set(binder_sequence).issubset(set("ACDEFGHIKLMNPQRSTVWY"))
            ),
            "author_determined_dimer": assembly.get("author_unit") == "DIMERIC",
            "complete_two_protein_assembly": (
                len(assembly.get("protein_chains", [])) == 2
                and set(assembly.get("protein_chains", [])) == {target_chain, binder_chain}
            ),
            "distinct_molecule_entities": (
                target_description["molecule_id"] is not None
                and binder_description["molecule_id"] is not None
                and target_description["molecule_id"] != binder_description["molecule_id"]
            ),
            "semantic_pass": (
                target.get("semantic_verdict") == "pass"
                and isinstance(target.get("semantic_rationale"), str)
                and bool(target["semantic_rationale"].strip())
                and isinstance(target.get("target_role"), str)
                and isinstance(target.get("binder_role"), str)
            ),
            "minimum_chain_lengths": (
                target_description["ca_residues"] >= minimum_residues
                and binder_description["ca_residues"] >= minimum_residues
            ),
            "no_numbering_gaps": (
                not target_description["has_numbering_gaps"]
                and not binder_description["has_numbering_gaps"]
            ),
            "minimum_interface_contacts": interface["ca_contact_pairs"] >= minimum_contacts,
            "fresh_target_id": target_id not in excluded_targets,
            "fresh_rcsb_source": rcsb_id not in excluded_sources,
            "fresh_target_sequence": target_hash not in excluded_sequences,
        }
        row_failed = [name for name, passed in row_checks.items() if not passed]
        if row_failed:
            raise ValueError(f"W3c-A target failed ({target_id}): {', '.join(row_failed)}")
        output_rows.append(
            {
                "target_id": target_id,
                "rcsb_id": rcsb_id,
                "assembly_id": str(target["assembly_id"]),
                "title": parsed["title"],
                "interaction_class": target["interaction_class"],
                "semantic_verdict": "pass",
                "semantic_rationale": target["semantic_rationale"],
                "target_role": target["target_role"],
                "binder_role": target["binder_role"],
                "target": target_description,
                "binder": binder_description,
                "interface": interface,
                "source_pdb": source,
                "target_sequence_sha256": target_hash,
                "binder_sequence_sha256": binder_hash,
                "checks": row_checks,
            }
        )

    target_hashes = [row["target_sequence_sha256"] for row in output_rows]
    binder_hashes = [row["binder_sequence_sha256"] for row in output_rows]
    panel_checks = {
        "all_eight_targets_pass": len(output_rows) == 8,
        "target_sequence_hashes_unique": len(set(target_hashes)) == 8,
        "binder_sequence_hashes_unique": len(set(binder_hashes)) == 8,
        "all_target_checks_pass": all(
            all(value is True for value in row["checks"].values()) for row in output_rows
        ),
        "local_sources_verified_when_requested": local_verified,
        "zero_proteinmpnn_designs": candidates.get("proteinmpnn_designs") == 0,
        "zero_predictor_evaluations": candidates.get("predictor_evaluations") == 0,
        "no_cayuga_authority": candidates.get("cayuga_submission_allowed") is False,
    }
    panel_failed = [name for name, passed in panel_checks.items() if not passed]
    if panel_failed:
        raise ValueError(f"W3c-A panel lock failed: {', '.join(panel_failed)}")

    manifest_targets = [
        {
            "id": row["target_id"],
            "rcsb_id": row["rcsb_id"],
            "assembly_id": row["assembly_id"],
            "source_pdb": row["source_pdb"]["path"],
            "source_pdb_sha256": row["source_pdb"]["sha256"],
            "source_pdb_url": row["source_pdb"]["rcsb_download_url"],
            "target_chain": row["target"]["chain"],
            "binder_chain": row["binder"]["chain"],
            "target_sequence_sha256": row["target_sequence_sha256"],
            "binder_sequence_sha256": row["binder_sequence_sha256"],
            "interaction_class": row["interaction_class"],
            "semantic_verdict": "pass",
        }
        for row in output_rows
    ]
    manifest = {
        "artifact": "m6d_w3c_fresh_target_manifest",
        "version": 1,
        "status": "representation_locked_awaiting_separate_target_msa_packet_no_submit",
        "target_count": 8,
        "target_ids": [row["id"] for row in manifest_targets],
        "targets": manifest_targets,
        "proteinmpnn_designs": 0,
        "predictor_evaluations": 0,
        "target_msa_queries_authorized": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
    }
    report = {
        "artifact": "m6d_w3c_fresh_target_lock",
        "version": 1,
        "status": _STATUS,
        "date": "2026-07-15",
        "audit_ok": True,
        "inputs": {
            "candidate_config": _file_binding(candidate_config_path),
            "historical_overlap_registry": _file_binding(overlap_registry_path),
            "validity_first_protocol": _file_binding(protocol_path),
            "structure_fixture": _file_binding(structure_fixture_path),
            "local_source_pdbs_verified": verify_local_sources,
        },
        "summary": {
            "required_targets": 8,
            "locked_targets": 8,
            "target_ids": [row["target_id"] for row in output_rows],
            "source_rcsb_ids": [row["rcsb_id"] for row in output_rows],
            "interaction_class_counts": {
                name: sum(row["interaction_class"] == name for row in output_rows)
                for name in sorted({row["interaction_class"] for row in output_rows})
            },
            "minimum_ca_contact_pairs": min(
                row["interface"]["ca_contact_pairs"] for row in output_rows
            ),
        },
        "checks": {**checks, **panel_checks},
        "targets": output_rows,
        "w3c_a_complete": True,
        "w3c_b1_target_msa_packet_prepared": False,
        "w3c_b2_native_screen_packet_prepared": False,
        "proteinmpnn_designs": 0,
        "predictor_evaluations": 0,
        "target_msa_queries_authorized": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_native_recoverability": False,
        "can_claim_generator_yield": False,
        "can_claim_trust_gate": False,
        "can_claim_biological_binder_success": False,
        "next_action": (
            "Prepare a separate hash-bound no-submit W3c-B1 approval packet for at most eight target "
            "MSA queries on Cayuga A40. Do not submit MSA, ProteinMPNN, or predictor work without the "
            "stage-specific approval."
        ),
    }
    return {"report": report, "manifest": manifest}


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# M6d W3c-A fresh target representation lock",
        "",
        f"Status: `{report['status']}`.",
        "",
        "## Summary",
        "",
        f"- locked targets: `{summary['locked_targets']}/{summary['required_targets']}`",
        f"- minimum selected-pair CA contacts: `{summary['minimum_ca_contact_pairs']}`",
        f"- ProteinMPNN designs: `{report['proteinmpnn_designs']}`",
        f"- predictor evaluations: `{report['predictor_evaluations']}`",
        f"- Cayuga submission allowed: `{report['cayuga_submission_allowed']}`",
        "",
        "| Target | Interaction class | Chains | CA residues | CA contacts |",
        "|---|---|---|---:|---:|",
    ]
    for row in report["targets"]:
        lines.append(
            f"| `{row['target_id']}` | {row['interaction_class']} | "
            f"{row['target']['chain']}:{row['binder']['chain']} | "
            f"{row['target']['ca_residues']}:{row['binder']['ca_residues']} | "
            f"{row['interface']['ca_contact_pairs']} |"
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            "This lock establishes representation validity and exact historical non-overlap only. "
            "It contains no native-recoverability, generator, trust-gate, or biological-success evidence.",
            "",
            "## Next action",
            "",
            report["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-config",
        default="configs/m6d_w3c_fresh_target_candidates.json",
    )
    parser.add_argument(
        "--historical-source-registry",
        default="configs/m6d_w2_historical_target_registry.json",
    )
    parser.add_argument(
        "--historical-overlap-registry",
        default="configs/m6d_w3c_historical_overlap_registry.json",
    )
    parser.add_argument(
        "--protocol",
        default="configs/m6d_w3c_validity_first_protocol.json",
    )
    parser.add_argument(
        "--structure-fixture",
        default="tests/fixtures/m6d_w3c_fresh_structure_fixture.json",
    )
    parser.add_argument(
        "--refresh-historical-overlap-registry-from-local-sources",
        action="store_true",
    )
    parser.add_argument(
        "--refresh-structure-fixture-from-local-sources",
        action="store_true",
    )
    parser.add_argument("--verify-local-sources", action="store_true")
    parser.add_argument(
        "--out-manifest",
        default="configs/m6d_w3c_fresh_targets.json",
    )
    parser.add_argument(
        "--out-json",
        default="results/m6d_w3c_fresh_target_lock.json",
    )
    parser.add_argument(
        "--out-md",
        default="results/m6d_w3c_fresh_target_lock.md",
    )
    args = parser.parse_args(argv)

    requested_outputs = {
        os.path.abspath(args.out_manifest),
        os.path.abspath(args.out_json),
        os.path.abspath(args.out_md),
    }
    canonical_outputs = {os.path.abspath(path) for path in _CANONICAL_OUTPUTS}
    if not args.verify_local_sources and requested_outputs & canonical_outputs:
        parser.error(
            "canonical W3c-A outputs require --verify-local-sources; "
            "public CPU replay must use explicit alternate output paths"
        )

    if args.refresh_historical_overlap_registry_from_local_sources:
        registry = build_historical_overlap_registry(
            args.historical_source_registry,
            _BRANCH_MANIFESTS,
        )
        _write_json(args.historical_overlap_registry, registry)
    if args.refresh_structure_fixture_from_local_sources:
        fixture = build_structure_fixture(args.candidate_config)
        _write_json(args.structure_fixture, fixture)

    output = build_lock(
        args.candidate_config,
        args.historical_overlap_registry,
        args.protocol,
        args.structure_fixture,
        verify_local_sources=args.verify_local_sources,
    )
    _write_json(args.out_manifest, output["manifest"])
    output["report"]["inputs"]["locked_manifest"] = _file_binding(args.out_manifest)
    _write_json(args.out_json, output["report"])
    _write_text(args.out_md, render_markdown(output["report"]))
    print(
        f"status={output['report']['status']} "
        f"locked={output['report']['summary']['locked_targets']} "
        "msa_authorized=0 predictor_evaluations=0 cayuga_submission_allowed=false"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
