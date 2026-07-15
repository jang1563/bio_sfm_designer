"""Audit whether historical two-chain inputs represent valid target-binder systems."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

Coord = Tuple[float, float, float]
ResidueKey = Tuple[str, str]

_MODIFIED_AA = {
    "CME",
    "CSO",
    "HYP",
    "KCX",
    "LLP",
    "MLY",
    "MSE",
    "PTR",
    "PYL",
    "SEC",
    "SEP",
    "TPO",
}
_SEMANTIC_VERDICTS = {"pass", "needs_reformulation", "out_of_scope"}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _is_supported_ca(line: str) -> bool:
    record = line[:6].strip()
    if record not in {"ATOM", "HETATM"} or line[12:16].strip() != "CA":
        return False
    if record == "HETATM" and line[17:20].strip() not in _MODIFIED_AA:
        return False
    return line[16] in {" ", "A"}


def _split_chains(value: str) -> List[str]:
    return [part.strip().strip(",") for part in value.split(",") if part.strip().strip(",")]


def _parse_compnd(lines: Sequence[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    clauses = [part.strip() for part in " ".join(lines).split(";") if part.strip()]
    molecules: Dict[str, Dict[str, Any]] = {}
    chain_to_molecule: Dict[str, str] = {}
    current: Optional[str] = None
    for clause in clauses:
        if ":" not in clause:
            continue
        key, value = (part.strip() for part in clause.split(":", 1))
        if key == "MOL_ID":
            current = value
            molecules.setdefault(current, {"molecule_id": current, "name": None, "chains": []})
        elif current is not None and key == "MOLECULE":
            molecules[current]["name"] = value
        elif current is not None and key == "CHAIN":
            chains = _split_chains(value)
            molecules[current]["chains"].extend(chains)
            for chain in chains:
                chain_to_molecule[chain] = current
    return molecules, chain_to_molecule


def _parse_pdb(path: str) -> Dict[str, Any]:
    title_parts: List[str] = []
    compnd_parts: List[str] = []
    chain_cas: Dict[str, Dict[ResidueKey, Coord]] = defaultdict(dict)
    assemblies: Dict[str, Dict[str, Any]] = {}
    current_assemblies: List[str] = []

    with open(path) as handle:
        for line in handle:
            if line.startswith("ENDMDL"):
                break
            if line.startswith("TITLE "):
                title_parts.append(line[10:].strip())
            elif line.startswith("COMPND"):
                compnd_parts.append(line[10:].strip())
            elif line.startswith("REMARK 350 BIOMOLECULE:"):
                current_assemblies = _split_chains(line.split(":", 1)[1])
                for assembly_id in current_assemblies:
                    assemblies.setdefault(
                        assembly_id,
                        {"assembly_id": assembly_id, "author_unit": None, "chains": set()},
                    )
            elif line.startswith("REMARK 350 AUTHOR DETERMINED BIOLOGICAL UNIT:"):
                unit = line.split(":", 1)[1].strip()
                for assembly_id in current_assemblies:
                    assemblies[assembly_id]["author_unit"] = unit
            elif line.startswith("REMARK 350 APPLY THE FOLLOWING TO CHAINS:"):
                chains = _split_chains(line.split(":", 1)[1])
                for assembly_id in current_assemblies:
                    assemblies[assembly_id]["chains"].update(chains)
            elif line.startswith("REMARK 350                    AND CHAINS:"):
                chains = _split_chains(line.split(":", 1)[1])
                for assembly_id in current_assemblies:
                    assemblies[assembly_id]["chains"].update(chains)

            if not _is_supported_ca(line):
                continue
            chain = line[21]
            residue = (line[22:26].strip(), line[26].strip())
            chain_cas[chain].setdefault(
                residue,
                (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                ),
            )

    molecules, chain_to_molecule = _parse_compnd(compnd_parts)
    assembly_rows = []
    for assembly_id, assembly in assemblies.items():
        chains = sorted(assembly["chains"])
        protein_chains = sorted(chain for chain in chains if chain_cas.get(chain))
        assembly_rows.append(
            {
                "assembly_id": assembly_id,
                "author_unit": assembly["author_unit"],
                "chains": chains,
                "protein_chains": protein_chains,
            }
        )
    assembly_rows.sort(key=lambda row: _natural_key(row["assembly_id"]))
    return {
        "title": " ".join(title_parts),
        "molecules": molecules,
        "chain_to_molecule": chain_to_molecule,
        "chain_cas": dict(chain_cas),
        "assemblies": assembly_rows,
    }


def _serialize_structure(parsed: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "title": parsed["title"],
        "molecules": parsed["molecules"],
        "chain_to_molecule": parsed["chain_to_molecule"],
        "assemblies": parsed["assemblies"],
        "chain_cas": {
            chain: [
                [number, insertion, coordinate[0], coordinate[1], coordinate[2]]
                for (number, insertion), coordinate in residues.items()
            ]
            for chain, residues in sorted(parsed["chain_cas"].items())
        },
    }


def _deserialize_structure(payload: Mapping[str, Any], target_id: str) -> Dict[str, Any]:
    chain_rows = payload.get("chain_cas")
    if not isinstance(chain_rows, dict) or not chain_rows:
        raise ValueError(f"structure fixture has no CA coordinates: {target_id}")
    chain_cas: Dict[str, Dict[ResidueKey, Coord]] = {}
    for chain, rows in chain_rows.items():
        if not isinstance(chain, str) or not chain or not isinstance(rows, list):
            raise ValueError(f"invalid fixture chain rows: {target_id}")
        residues: Dict[ResidueKey, Coord] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) != 5:
                raise ValueError(f"invalid fixture CA row: {target_id}/{chain}")
            number, insertion, x, y, z = row
            if not isinstance(number, str) or not isinstance(insertion, str):
                raise ValueError(f"invalid fixture residue key: {target_id}/{chain}")
            if not all(isinstance(value, (int, float)) for value in (x, y, z)):
                raise ValueError(f"invalid fixture coordinate: {target_id}/{chain}")
            key = (number, insertion)
            if key in residues:
                raise ValueError(f"duplicate fixture residue: {target_id}/{chain}/{key}")
            residues[key] = (float(x), float(y), float(z))
        chain_cas[chain] = residues
    required_objects = ("molecules", "chain_to_molecule")
    if any(not isinstance(payload.get(name), dict) for name in required_objects):
        raise ValueError(f"invalid fixture molecule metadata: {target_id}")
    if not isinstance(payload.get("assemblies"), list):
        raise ValueError(f"invalid fixture assembly metadata: {target_id}")
    return {
        "title": str(payload.get("title", "")),
        "molecules": payload["molecules"],
        "chain_to_molecule": payload["chain_to_molecule"],
        "chain_cas": chain_cas,
        "assemblies": payload["assemblies"],
    }


def build_structure_fixture(pool_manifest_path: str) -> Dict[str, Any]:
    pool = _load_json(pool_manifest_path)
    pool_ids = _target_ids(pool, "representative pool")
    targets_by_id = {target["id"]: target for target in pool["targets"]}
    rows = []
    for target_id in pool_ids:
        target = targets_by_id[target_id]
        source_pdb = str(target.get("source_pdb", ""))
        rcsb_id = target.get("rcsb_id")
        if not isinstance(rcsb_id, str) or not rcsb_id:
            raise ValueError(f"target lacks RCSB id: {target_id}")
        if not os.path.isfile(source_pdb) or os.path.getsize(source_pdb) == 0:
            raise ValueError(f"target source PDB is missing or empty: {source_pdb}")
        rows.append(
            {
                "target_id": target_id,
                "rcsb_id": rcsb_id,
                "source_pdb": {
                    "bytes": os.path.getsize(source_pdb),
                    "sha256": _sha256_file(source_pdb),
                    "rcsb_download_url": f"https://files.rcsb.org/download/{rcsb_id}.pdb",
                },
                "structure": _serialize_structure(_parse_pdb(source_pdb)),
            }
        )
    return {
        "artifact": "m6d_w3c_historical_structure_fixture",
        "version": 1,
        "status": "public_cpu_replay_fixture",
        "source": "RCSB PDB legacy-format entries",
        "coordinate_scope": "first-model CA coordinates for all protein chains in each source entry",
        "pool_manifest_sha256": _sha256_file(pool_manifest_path),
        "targets": rows,
    }


def _natural_key(value: str) -> Tuple[int, str]:
    try:
        return (int(value), value)
    except ValueError:
        return (10**9, value)


def _numbering_gaps(residues: Mapping[ResidueKey, Coord]) -> List[Dict[str, int]]:
    numbers = sorted({int(number) for number, _ in residues if number.lstrip("-").isdigit()})
    return [
        {"after": first, "before": second, "missing_residues": second - first - 1}
        for first, second in zip(numbers, numbers[1:])
        if second - first > 1
    ]


def _chain_description(parsed: Mapping[str, Any], chain: str) -> Dict[str, Any]:
    molecule_id = parsed["chain_to_molecule"].get(chain)
    molecule = parsed["molecules"].get(molecule_id, {})
    residues = parsed["chain_cas"].get(chain, {})
    numbering_gaps = _numbering_gaps(residues)
    return {
        "chain": chain,
        "molecule_id": molecule_id,
        "molecule_name": molecule.get("name"),
        "ca_residues": len(residues),
        "numbering_gaps": numbering_gaps,
        "has_numbering_gaps": bool(numbering_gaps),
    }


def _interface(
    first: Mapping[ResidueKey, Coord],
    second: Mapping[ResidueKey, Coord],
    cutoff: float,
) -> Dict[str, Any]:
    pairs = 0
    first_residues: Set[ResidueKey] = set()
    second_residues: Set[ResidueKey] = set()
    min_distance: Optional[float] = None
    for first_key, first_coord in first.items():
        for second_key, second_coord in second.items():
            distance = math.dist(first_coord, second_coord)
            min_distance = distance if min_distance is None else min(min_distance, distance)
            if distance <= cutoff:
                pairs += 1
                first_residues.add(first_key)
                second_residues.add(second_key)
    return {
        "ca_contact_pairs": pairs,
        "first_interface_residues": len(first_residues),
        "second_interface_residues": len(second_residues),
        "first_interface_residue_ids": [
            f"{number}{insertion}" for number, insertion in sorted(first_residues)
        ],
        "minimum_ca_distance": None if min_distance is None else round(min_distance, 3),
    }


def _target_ids(manifest: Mapping[str, Any], label: str) -> List[str]:
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError(f"{label} has no targets")
    if any(not isinstance(target, dict) for target in targets):
        raise ValueError(f"{label} target rows must be objects")
    ids = [target.get("id") for target in targets]
    if any(not isinstance(target_id, str) or not target_id for target_id in ids):
        raise ValueError(f"{label} contains a target without an id")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} target ids are not unique")
    return ids


def _structure_fixture_map(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows:
        raise ValueError("structure fixture has no targets")
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("structure fixture target rows must be objects")
        target_id = row.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("structure fixture row lacks target id")
        if target_id in out:
            raise ValueError(f"duplicate structure fixture target: {target_id}")
        source = row.get("source_pdb")
        if (
            not isinstance(row.get("rcsb_id"), str)
            or not isinstance(source, dict)
            or not isinstance(source.get("bytes"), int)
            or source.get("bytes", 0) <= 0
            or not _is_sha256(source.get("sha256"))
            or not isinstance(row.get("structure"), dict)
        ):
            raise ValueError(f"invalid structure fixture provenance: {target_id}")
        out[target_id] = dict(row)
    return out


def _annotation_map(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("semantic annotation file has no targets")
    out: Dict[str, Dict[str, Any]] = {}
    for row in targets:
        if not isinstance(row, dict):
            raise ValueError("semantic annotation rows must be objects")
        target_id = row.get("id")
        verdict = row.get("semantic_verdict")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("semantic annotation row lacks id")
        if target_id in out:
            raise ValueError(f"duplicate semantic annotation: {target_id}")
        if verdict not in _SEMANTIC_VERDICTS:
            raise ValueError(f"invalid semantic verdict for {target_id}: {verdict}")
        if not isinstance(row.get("semantic_context"), str) or not row["semantic_context"]:
            raise ValueError(f"semantic annotation lacks context: {target_id}")
        if not isinstance(row.get("rationale"), str) or not row["rationale"]:
            raise ValueError(f"semantic annotation lacks rationale: {target_id}")
        out[target_id] = dict(row)
    return out


def _audit_target(
    target: Mapping[str, Any],
    annotation: Mapping[str, Any],
    branch: str,
    fixture_row: Mapping[str, Any],
    *,
    contact_cutoff: float,
) -> Dict[str, Any]:
    required = ("id", "rcsb_id", "target_chain", "binder_chain")
    missing = [field for field in required if not target.get(field)]
    if missing:
        raise ValueError(f"target lacks required fields {missing}: {target}")
    if fixture_row.get("target_id") != target["id"] or fixture_row.get("rcsb_id") != target["rcsb_id"]:
        raise ValueError(f"structure fixture identity mismatch: {target['id']}")
    parsed = _deserialize_structure(fixture_row["structure"], str(target["id"]))
    target_chain = str(target["target_chain"])
    binder_chain = str(target["binder_chain"])
    pair = {target_chain, binder_chain}
    for chain in pair:
        if not parsed["chain_cas"].get(chain):
            raise ValueError(f"target {target['id']} selected chain has no CA residues: {chain}")

    relevant = [
        assembly
        for assembly in parsed["assemblies"]
        if assembly.get("author_unit") is not None
        and pair.issubset(set(assembly.get("protein_chains", [])))
    ]
    relevant.sort(
        key=lambda row: (
            len(row.get("protein_chains", [])),
            _natural_key(str(row.get("assembly_id", ""))),
        )
    )
    selected_assembly = relevant[0] if relevant else None
    selected_protein_chains = (
        list(selected_assembly.get("protein_chains", [])) if selected_assembly else []
    )
    omitted_chains = sorted(set(selected_protein_chains) - pair)
    structural_complete = bool(
        selected_assembly
        and selected_assembly.get("author_unit") == "DIMERIC"
        and set(selected_protein_chains) == pair
    )

    selected_interface = _interface(
        parsed["chain_cas"][binder_chain],
        parsed["chain_cas"][target_chain],
        contact_cutoff,
    )
    target_description = _chain_description(parsed, target_chain)
    binder_description = _chain_description(parsed, binder_chain)
    selected_chains_share_molecule_entity = (
        parsed["chain_to_molecule"].get(target_chain) is not None
        and parsed["chain_to_molecule"].get(target_chain)
        == parsed["chain_to_molecule"].get(binder_chain)
    )
    omitted_interfaces = []
    selected_binder_residues = set(selected_interface["first_interface_residue_ids"])
    omitted_binder_residues: Set[str] = set()
    for chain in omitted_chains:
        interface = _interface(
            parsed["chain_cas"][binder_chain],
            parsed["chain_cas"][chain],
            contact_cutoff,
        )
        omitted_binder_residues.update(interface["first_interface_residue_ids"])
        omitted_interfaces.append(
            {
                "chain": chain,
                "molecule": _chain_description(parsed, chain),
                **interface,
            }
        )

    all_binder_interface_residues = selected_binder_residues | omitted_binder_residues
    selected_fraction = (
        len(selected_binder_residues) / len(all_binder_interface_residues)
        if all_binder_interface_residues
        else None
    )
    strict_eligible = bool(
        structural_complete
        and annotation["semantic_verdict"] == "pass"
        and not selected_chains_share_molecule_entity
        and target_description["ca_residues"] >= 40
        and binder_description["ca_residues"] >= 40
        and selected_interface["ca_contact_pairs"] >= 20
        and not target_description["has_numbering_gaps"]
        and not binder_description["has_numbering_gaps"]
    )
    return {
        "target_id": target["id"],
        "historical_branch": branch,
        "historical_role": target.get("experimental_role", "fit"),
        "source": fixture_row["source_pdb"],
        "rcsb_id": target.get("rcsb_id"),
        "title": parsed["title"],
        "target": target_description,
        "binder": binder_description,
        "selected_chains_share_molecule_entity": selected_chains_share_molecule_entity,
        "author_assemblies_containing_pair": relevant,
        "selected_author_assembly": selected_assembly,
        "omitted_protein_chains": omitted_chains,
        "selected_pair_interface": selected_interface,
        "omitted_chain_interfaces": omitted_interfaces,
        "selected_binder_interface_fraction_within_assembly": (
            None if selected_fraction is None else round(selected_fraction, 6)
        ),
        "structural_pair_complete": structural_complete,
        "semantic_context": annotation["semantic_context"],
        "semantic_verdict": annotation["semantic_verdict"],
        "semantic_rationale": annotation["rationale"],
        "strict_target_binder_eligible": strict_eligible,
    }


def _branch_summary(rows: Sequence[Mapping[str, Any]], branch: str) -> Dict[str, Any]:
    scoped = [row for row in rows if row["historical_branch"] == branch]
    structurally_complete = [row["target_id"] for row in scoped if row["structural_pair_complete"]]
    semantic_pass = [row["target_id"] for row in scoped if row["semantic_verdict"] == "pass"]
    strict = [row["target_id"] for row in scoped if row["strict_target_binder_eligible"]]
    return {
        "n_targets": len(scoped),
        "n_structurally_complete_two_chain": len(structurally_complete),
        "structurally_complete_target_ids": structurally_complete,
        "n_semantic_pass": len(semantic_pass),
        "semantic_pass_target_ids": semantic_pass,
        "n_strict_target_binder_eligible": len(strict),
        "strict_target_binder_eligible_ids": strict,
        "strict_target_binder_eligible_fraction": len(strict) / len(scoped) if scoped else 0.0,
    }


def _protocol_checks(protocol: Mapping[str, Any], expected_targets: int) -> Dict[str, bool]:
    stages = protocol.get("stages") if isinstance(protocol.get("stages"), list) else []
    stages_by_name = {
        stage.get("stage"): stage for stage in stages if isinstance(stage, dict)
    }
    target_discovery = (
        protocol.get("target_discovery")
        if isinstance(protocol.get("target_discovery"), dict)
        else {}
    )
    validity = (
        protocol.get("target_validity_gate")
        if isinstance(protocol.get("target_validity_gate"), dict)
        else {}
    )
    native = stages_by_name.get("W3c-B2", {})
    msa = stages_by_name.get("W3c-B1", {})
    discovery = stages_by_name.get("W3c-A", {})
    post_native = (
        protocol.get("post_native_boundary")
        if isinstance(protocol.get("post_native_boundary"), dict)
        else {}
    )
    runtime = (
        protocol.get("runtime_boundary")
        if isinstance(protocol.get("runtime_boundary"), dict)
        else {}
    )
    claim = (
        protocol.get("claim_boundary")
        if isinstance(protocol.get("claim_boundary"), dict)
        else {}
    )
    return {
        "protocol_identity_exact": (
            protocol.get("artifact") == "m6d_w3c_validity_first_protocol"
            and protocol.get("version") == 1
            and protocol.get("status") == "preregistered_target_discovery_only_no_submit"
        ),
        "protocol_target_scope_exact": (
            target_discovery.get("required_targets") == expected_targets
            and target_discovery.get("fresh_source_required") is True
            and target_discovery.get("exclude_all_historical_target_ids") is True
            and target_discovery.get("exclude_all_historical_rcsb_sources") is True
            and target_discovery.get("exclude_all_historical_target_sequence_hashes") is True
            and target_discovery.get("selection_may_use_predictor_outputs") is False
            and target_discovery.get("selection_may_use_generated_design_labels") is False
        ),
        "protocol_validity_gate_exact": (
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
        "protocol_stages_exact": (
            len(stages) == 3
            and len(stages_by_name) == 3
            and set(stages_by_name) == {"W3c-A", "W3c-B1", "W3c-B2"}
        ),
        "protocol_discovery_scope_exact": (
            discovery.get("proteinmpnn_designs") == 0
            and discovery.get("predictor_evaluations") == 0
            and discovery.get("approval_required") is False
        ),
        "protocol_msa_scope_exact": (
            msa.get("maximum_target_msa_queries") == expected_targets
            and msa.get("proteinmpnn_designs") == 0
            and msa.get("predictor_evaluations") == 0
            and msa.get("approval_required") is True
            and msa.get("approval_status") == "not_prepared"
        ),
        "protocol_native_scope_exact": (
            native.get("targets") == expected_targets
            and native.get("native_sequences_per_target") == 1
            and native.get("predictors")
            == ["boltz2_complex", "af2_multimer_colabfold_v1"]
            and native.get("maximum_predictor_evaluations") == 2 * expected_targets
            and native.get("proteinmpnn_designs") == 0
            and native.get("lrmsd_success_threshold_angstrom") == 4.0
            and native.get("minimum_targets_passing") == 6
            and native.get("approval_required") is True
            and native.get("approval_status") == "not_prepared"
        ),
        "protocol_no_submit_exact": (
            protocol.get("no_submit") is True
            and protocol.get("cayuga_submission_allowed") is False
        ),
        "protocol_post_native_boundary_exact": (
            post_native.get("generator_protocol_prepared") is False
            and post_native.get("trust_gate_protocol_prepared") is False
            and post_native.get("certification_protocol_prepared") is False
            and post_native.get("native_screen_may_select_gate_thresholds") is False
            and post_native.get("native_screen_may_select_generator_settings") is False
            and post_native.get("next_protocol_requires_separate_preregistration") is True
            and post_native.get("next_compute_requires_separate_exact_approval") is True
        ),
        "protocol_runtime_boundary_exact": (
            runtime.get("w3b_runtime_may_transfer_only_by_exact_hash_match") is True
            and runtime.get("new_runtime_observation_required") is True
            and runtime.get("new_budget_lock_required_before_approval") is True
            and runtime.get("prediction_time_network_allowed") is False
            and runtime.get("templates_allowed") is False
            and runtime.get("seed") == 0
        ),
        "protocol_claim_boundary_exact": (
            claim.get("target_discovery_supports_binder_design_claim") is False
            and claim.get("native_screen_supports_generator_claim") is False
            and claim.get("native_screen_supports_trust_gate_claim") is False
            and claim.get("native_screen_supports_biological_binder_success_claim") is False
        ),
    }


def build_audit(
    pool_manifest_path: str,
    semantic_annotations_path: str,
    w2b_manifest_path: str,
    w2c_manifest_path: str,
    w3b_manifest_path: str,
    *,
    protocol_path: str,
    structure_fixture_path: str,
    verify_local_sources: bool = False,
    contact_cutoff: float = 8.0,
) -> Dict[str, Any]:
    pool = _load_json(pool_manifest_path)
    annotations_payload = _load_json(semantic_annotations_path)
    branch_payloads = {
        "W2b": _load_json(w2b_manifest_path),
        "W2c": _load_json(w2c_manifest_path),
        "W3b": _load_json(w3b_manifest_path),
    }
    structure_fixture = _load_json(structure_fixture_path)
    fixture_by_id = _structure_fixture_map(structure_fixture)
    pool_ids = _target_ids(pool, "representative pool")
    annotations = _annotation_map(annotations_payload)
    branch_ids = {
        branch: _target_ids(payload, f"{branch} manifest")
        for branch, payload in branch_payloads.items()
    }
    policy = annotations_payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("semantic annotation file lacks policy")
    expected_pool_targets = policy.get("expected_representative_pool_targets")
    expected_targets_per_branch = policy.get("expected_targets_per_historical_branch")
    expected_successor_targets = policy.get("expected_successor_targets")
    if not isinstance(expected_pool_targets, int) or expected_pool_targets <= 0:
        raise ValueError("invalid expected representative pool target count")
    if not isinstance(expected_targets_per_branch, int) or expected_targets_per_branch <= 0:
        raise ValueError("invalid expected historical branch target count")
    if not isinstance(expected_successor_targets, int) or expected_successor_targets <= 0:
        raise ValueError("invalid expected successor target count")
    protocol = _load_json(protocol_path)
    all_branch_ids = [target_id for ids in branch_ids.values() for target_id in ids]
    targets_by_id = {target["id"]: target for target in pool["targets"]}
    fixture_ids = [row.get("target_id") for row in structure_fixture.get("targets", [])]
    checks = {
        "pool_size_exact": len(pool_ids) == expected_pool_targets,
        "semantic_annotations_exact": set(annotations) == set(pool_ids),
        "historical_branch_sizes_exact": all(
            len(ids) == expected_targets_per_branch for ids in branch_ids.values()
        ),
        "historical_branches_are_disjoint": len(all_branch_ids) == len(set(all_branch_ids)),
        "historical_branches_partition_pool": set(all_branch_ids) == set(pool_ids),
        "annotation_policy_no_historical_labels": (
            annotations_payload.get("historical_predictor_labels_used") is False
        ),
        "annotation_post_outcome_timing_disclosed": (
            annotations_payload.get("created_after_historical_outcomes_observed") is True
        ),
        "annotation_public_replay_fixture_bound": (
            isinstance(annotations_payload.get("public_replay_structure_fixture"), str)
            and os.path.abspath(annotations_payload["public_replay_structure_fixture"])
            == os.path.abspath(structure_fixture_path)
        ),
        "annotation_strict_policy_exact": (
            policy.get("strict_eligibility_requires_semantic_pass") is True
            and policy.get("strict_eligibility_also_requires_complete_author_determined_dimer") is True
            and policy.get("historical_targets_are_diagnostic_only") is True
            and policy.get("successor_targets_must_be_screened_prospectively") is True
        ),
        "structure_fixture_identity_exact": (
            structure_fixture.get("artifact") == "m6d_w3c_historical_structure_fixture"
            and structure_fixture.get("version") == 1
            and structure_fixture.get("status") == "public_cpu_replay_fixture"
        ),
        "structure_fixture_pool_binding_exact": (
            structure_fixture.get("pool_manifest_sha256") == _sha256_file(pool_manifest_path)
        ),
        "structure_fixture_targets_exact": fixture_ids == pool_ids,
        "structure_fixture_rcsb_ids_exact": all(
            isinstance(fixture_by_id.get(target_id), dict)
            and fixture_by_id[target_id].get("rcsb_id")
            == targets_by_id[target_id].get("rcsb_id")
            for target_id in pool_ids
        ),
        "no_compute_authority": annotations_payload.get("cayuga_submission_allowed") is False,
        "contact_cutoff_matches_protocol": contact_cutoff == 8.0,
    }
    if verify_local_sources:
        checks["local_source_pdbs_match_fixture"] = all(
            isinstance(fixture_by_id.get(target_id), dict)
            and os.path.isfile(str(targets_by_id[target_id].get("source_pdb", "")))
            and os.path.getsize(str(targets_by_id[target_id]["source_pdb"]))
            == fixture_by_id[target_id]["source_pdb"]["bytes"]
            and _sha256_file(str(targets_by_id[target_id]["source_pdb"]))
            == fixture_by_id[target_id]["source_pdb"]["sha256"]
            for target_id in pool_ids
        )
    checks.update(_protocol_checks(protocol, expected_successor_targets))
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3c target-validity input checks failed: {', '.join(failed)}")

    branch_by_id = {
        target_id: branch for branch, ids in branch_ids.items() for target_id in ids
    }
    rows = [
        _audit_target(
            targets_by_id[target_id],
            annotations[target_id],
            branch_by_id[target_id],
            fixture_by_id[target_id],
            contact_cutoff=contact_cutoff,
        )
        for target_id in pool_ids
    ]
    structural_ids = [row["target_id"] for row in rows if row["structural_pair_complete"]]
    strict_ids = [row["target_id"] for row in rows if row["strict_target_binder_eligible"]]
    relevant_assembly_complete = all(row["selected_author_assembly"] is not None for row in rows)
    selected_interfaces_present = all(
        row["selected_pair_interface"]["ca_contact_pairs"] > 0 for row in rows
    )
    checks.update(
        {
            "all_selected_pairs_map_to_author_assemblies": relevant_assembly_complete,
            "all_selected_pairs_have_ca_contacts": selected_interfaces_present,
            "strict_eligibility_is_policy_derived": all(
                row["strict_target_binder_eligible"]
                == (
                    row["structural_pair_complete"]
                    and row["semantic_verdict"] == "pass"
                    and not row["selected_chains_share_molecule_entity"]
                    and row["target"]["ca_residues"] >= 40
                    and row["binder"]["ca_residues"] >= 40
                    and row["selected_pair_interface"]["ca_contact_pairs"] >= 20
                    and not row["target"]["has_numbering_gaps"]
                    and not row["binder"]["has_numbering_gaps"]
                )
                for row in rows
            ),
        }
    )
    audit_ok = all(checks.values())
    branch_summary = {
        branch: _branch_summary(rows, branch) for branch in ("W2b", "W2c", "W3b")
    }
    return {
        "artifact": "m6d_w3c_target_validity_audit",
        "version": 1,
        "status": "w3c_target_validity_reset_complete_fresh_target_discovery_required",
        "audit_ok": audit_ok,
        "contact_cutoff_angstrom": contact_cutoff,
        "inputs": {
            "pool_manifest": _file_binding(pool_manifest_path),
            "semantic_annotations": _file_binding(semantic_annotations_path),
            "successor_protocol": _file_binding(protocol_path),
            "structure_fixture": _file_binding(structure_fixture_path),
            "local_source_pdbs_verified": verify_local_sources,
            "historical_branch_manifests": {
                "W2b": _file_binding(w2b_manifest_path),
                "W2c": _file_binding(w2c_manifest_path),
                "W3b": _file_binding(w3b_manifest_path),
            },
        },
        "checks": checks,
        "summary": {
            "n_targets": len(rows),
            "n_structurally_complete_two_chain": len(structural_ids),
            "structurally_complete_target_ids": structural_ids,
            "n_strict_target_binder_eligible": len(strict_ids),
            "strict_target_binder_eligible_ids": strict_ids,
            "strict_target_binder_eligible_fraction": len(strict_ids) / len(rows),
            "semantic_verdict_counts": {
                verdict: sum(row["semantic_verdict"] == verdict for row in rows)
                for verdict in sorted(_SEMANTIC_VERDICTS)
            },
        },
        "historical_branch_summary": branch_summary,
        "targets": rows,
        "historical_claim_reset": (
            "W2b, W2c, and W3b remain valid for their exact prepared two-chain structural-proxy "
            "inputs. Because the representative pool did not prospectively require a complete "
            "author-determined dimer plus target-binder semantics, those branches do not estimate "
            "generalization to strict biological target-binder systems."
        ),
        "successor_policy": {
            "require_fresh_sources_outside_historical_24": True,
            "require_author_determined_dimer": True,
            "require_selected_pair_is_complete_protein_assembly": True,
            "require_selected_chains_are_distinct_molecule_entities": True,
            "require_manual_target_binder_semantic_pass": True,
            "minimum_ca_residues_per_chain": 40,
            "minimum_ca_contact_pairs": 20,
            "require_no_unreviewed_numbering_gaps": True,
            "require_native_dual_predictor_screen_before_generation": True,
        },
        "next_action": (
            "Discover and preregister eight fresh, source-disjoint targets that pass the frozen "
            "structural and semantic validity gate. Prepare no ProteinMPNN designs. A separately "
            "approved native-sequence screen must show that both frozen predictors can recover each "
            "target before any generator or trust-gate experiment."
        ),
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_claim_target_binder_generalization": False,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# M6d W3c target-validity audit",
        "",
        f"Status: `{report['status']}`.",
        f"Audit ok: `{report['audit_ok']}`.",
        "",
        "## Result",
        "",
        f"- representative targets: `{summary['n_targets']}`",
        f"- complete author-determined two-chain assemblies: `{summary['n_structurally_complete_two_chain']}`",
        f"- strict target-binder eligible: `{summary['n_strict_target_binder_eligible']}`",
        f"- strict eligible IDs: `{', '.join(summary['strict_target_binder_eligible_ids'])}`",
        "",
        "## Historical Branches",
        "",
        "| branch | targets | complete two-chain | strict target-binder |",
        "|---|---:|---:|---:|",
    ]
    for branch in ("W2b", "W2c", "W3b"):
        row = report["historical_branch_summary"][branch]
        lines.append(
            f"| {branch} | {row['n_targets']} | {row['n_structurally_complete_two_chain']} | "
            f"{row['n_strict_target_binder_eligible']} |"
        )
    lines.extend(
        [
            "",
            "## Targets",
            "",
            "| target | branch | selected molecules | author assembly | omitted protein chains | structural | semantic | strict |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["targets"]:
        assembly = row["selected_author_assembly"] or {}
        molecules = f"{row['target']['molecule_name']} / {row['binder']['molecule_name']}"
        assembly_text = f"{assembly.get('author_unit', 'none')}:{','.join(assembly.get('protein_chains', []))}"
        omitted = ",".join(row["omitted_protein_chains"]) or "none"
        lines.append(
            f"| `{row['target_id']}` | {row['historical_branch']} | {molecules} | {assembly_text} | "
            f"{omitted} | `{row['structural_pair_complete']}` | `{row['semantic_verdict']}` | "
            f"`{row['strict_target_binder_eligible']}` |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- public structure fixture: `{report['inputs']['structure_fixture']['path']}`",
            f"- fixture SHA-256: `{report['inputs']['structure_fixture']['sha256']}`",
            f"- local source PDBs verified against fixture: `{report['inputs']['local_source_pdbs_verified']}`",
            "",
            "## Claim Boundary",
            "",
            report["historical_claim_reset"],
            "",
            "## Next Action",
            "",
            report["next_action"],
            "",
            "No compute or Cayuga submission is authorized by this audit.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(
    path: str,
    payload: Mapping[str, Any],
    *,
    compact: bool = False,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as handle:
        if compact:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-manifest",
        default="configs/m6d_w2b_target_adaptive_cluster_representatives.json",
    )
    parser.add_argument(
        "--semantic-annotations",
        default="configs/m6d_w3c_target_semantic_annotations.json",
    )
    parser.add_argument(
        "--w2b-manifest",
        default="configs/m6d_w2b_target_adaptive_fit_targets.json",
    )
    parser.add_argument("--w2c-manifest", default="configs/m6d_w2c_fresh_targets.json")
    parser.add_argument("--w3b-manifest", default="configs/m6d_w3b_fresh_targets.json")
    parser.add_argument(
        "--protocol",
        default="configs/m6d_w3c_validity_first_protocol.json",
    )
    parser.add_argument(
        "--structure-fixture",
        default="tests/fixtures/m6d_w3c_historical_structure_fixture.json",
    )
    parser.add_argument(
        "--refresh-structure-fixture-from-local-sources",
        action="store_true",
    )
    parser.add_argument("--verify-local-sources", action="store_true")
    parser.add_argument("--contact-cutoff", type=float, default=8.0)
    parser.add_argument("--out-json", default="results/m6d_w3c_target_validity_audit.json")
    parser.add_argument("--out-md", default="results/m6d_w3c_target_validity_audit.md")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.refresh_structure_fixture_from_local_sources:
        _write_json(
            args.structure_fixture,
            build_structure_fixture(args.pool_manifest),
            compact=True,
        )
    report = build_audit(
        args.pool_manifest,
        args.semantic_annotations,
        args.w2b_manifest,
        args.w2c_manifest,
        args.w3b_manifest,
        protocol_path=args.protocol,
        structure_fixture_path=args.structure_fixture,
        verify_local_sources=(
            args.verify_local_sources or args.refresh_structure_fixture_from_local_sources
        ),
        contact_cutoff=args.contact_cutoff,
    )
    _write_json(args.out_json, report)
    _write_text(args.out_md, render_markdown(report))
    print(
        f"status={report['status']} structural="
        f"{report['summary']['n_structurally_complete_two_chain']}/"
        f"{report['summary']['n_targets']} strict="
        f"{report['summary']['n_strict_target_binder_eligible']}/"
        f"{report['summary']['n_targets']} no_submit=True"
    )
    return 0 if report["audit_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
