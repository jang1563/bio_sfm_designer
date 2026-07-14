#!/usr/bin/env python3
"""Convert locked W3b ColabFold outputs to strict AF2 matched records."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from bio_sfm_designer.experiments.m6d_w3b_producer_contract import (
    load_object,
    load_target_context,
    sequence_sha256,
    sha256_file,
    validate_candidates,
)
from bio_sfm_designer.experiments.m6d_w3b_runtime_lock import (
    canonical_sha256,
    runtime_identity,
)
from bio_sfm_designer.experiments.m6d_w3b_structure_metrics import (
    ca_coords,
    interface_pae,
    lrmsd,
)


def _rank_one_files(output_dir: Path, candidate_id: str) -> Tuple[Path, Path, str]:
    pdbs = sorted(output_dir.glob(f"{candidate_id}_unrelaxed_rank_001_*.pdb"))
    scores = sorted(output_dir.glob(f"{candidate_id}_scores_rank_001_*.json"))
    if len(pdbs) != 1 or len(scores) != 1:
        raise ValueError(
            f"{candidate_id}: expected one rank-001 PDB and score JSON; "
            f"observed pdb={len(pdbs)} scores={len(scores)}"
        )
    pdb_tag = pdbs[0].name.replace(f"{candidate_id}_unrelaxed_", "").replace(".pdb", "")
    score_tag = scores[0].name.replace(f"{candidate_id}_scores_", "").replace(".json", "")
    if pdb_tag != score_tag:
        raise ValueError(f"{candidate_id}: rank-001 PDB and score tags differ")
    return pdbs[0], scores[0], pdb_tag


def _validate_input_manifest(
    manifest: Dict[str, Any],
    manifest_path: str,
    context: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    candidates_path: str,
) -> Dict[str, Dict[str, Any]]:
    target = context["target"]
    if not (
        manifest.get("artifact") == "m6d_w3b_af2_input_manifest"
        and manifest.get("status") == "w3b_af2_inputs_ready_for_locked_prediction"
        and manifest.get("target_id") == target["id"]
        and manifest.get("experimental_role") == context["stage"]
        and manifest.get("seed_namespace") == context["seed_namespace"]
        and manifest.get("n_candidates") == context["expected_count"]
        and manifest.get("candidates") == candidates_path
        and manifest.get("candidates_sha256") == sha256_file(candidates_path)
        and manifest.get("target_msa_sha256") == target["target_msa_sha256"]
        and manifest.get("bindings") == context["bindings"]
    ):
        raise ValueError(f"AF2 input manifest is not bound to the W3b context: {manifest_path}")
    expected_prediction = {
        "model_type": "alphafold2_multimer_v3",
        "models": 5,
        "num_seeds": 1,
        "random_seed": 0,
        "recycles": 20,
        "rank_by": "multimer",
        "relax_models": 0,
        "templates_used": False,
        "prediction_time_network_used": False,
    }
    if manifest.get("prediction_contract") != expected_prediction:
        raise ValueError("AF2 input manifest prediction contract drifted")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != context["expected_count"]:
        raise ValueError("AF2 input manifest row count differs from the W3b lock")
    by_id = {
        str(row.get("candidate_id") or ""): row
        for row in rows
        if isinstance(row, dict)
    }
    candidate_by_id = {str(row["id"]): row for row in candidates}
    if len(by_id) != len(rows) or set(by_id) != set(candidate_by_id):
        raise ValueError("AF2 input manifest candidate identities differ from candidates")
    for candidate_id, row in by_id.items():
        candidate = candidate_by_id[candidate_id]
        a3m_path = row.get("a3m_path")
        if not (
            row.get("complex_target_id") == target["id"]
            and row.get("target_sequence") == candidate["target_seq"]
            and row.get("binder_sequence") == candidate["representation"]
            and row.get("target_sequence_sha256") == sequence_sha256(candidate["target_seq"])
            and row.get("candidate_sequence_sha256") == sequence_sha256(candidate["representation"])
            and row.get("target_msa_sha256") == target["target_msa_sha256"]
            and row.get("reference_backbone") == target["prepared_pdb"]
            and row.get("reference_backbone_sha256") == sha256_file(target["prepared_pdb"])
            and isinstance(a3m_path, str)
            and os.path.isfile(a3m_path)
            and sha256_file(a3m_path) == row.get("a3m_sha256")
        ):
            raise ValueError(f"{candidate_id}: AF2 input manifest row failed provenance validation")
    return by_id


def _build_record(
    candidate: Dict[str, Any],
    input_row: Dict[str, Any],
    target: Dict[str, Any],
    output_dir: Path,
    runtime_digest: str,
    threshold: float,
) -> Dict[str, Any]:
    candidate_id = str(candidate["id"])
    pdb_path, scores_path, model_tag = _rank_one_files(output_dir, candidate_id)
    with open(scores_path) as handle:
        scores = json.load(handle)
    if not isinstance(scores, dict):
        raise ValueError(f"{candidate_id}: score JSON must contain an object")
    pae = np.asarray(scores["pae"], dtype=float)
    plddt = np.asarray(scores["plddt"], dtype=float)
    target_length = len(str(candidate["target_seq"]))
    binder_length = len(str(candidate["representation"]))
    expected_size = target_length + binder_length
    if (
        pae.shape != (expected_size, expected_size)
        or plddt.size != expected_size
        or not np.isfinite(pae).all()
        or not np.isfinite(plddt).all()
    ):
        raise ValueError(f"{candidate_id}: AF2 score arrays differ from locked complex dimensions")
    reference_target = ca_coords(target["prepared_pdb"], target["target_chain"])
    reference_binder = ca_coords(target["prepared_pdb"], target["binder_chain"])
    fold_target = ca_coords(str(pdb_path), "A")
    fold_binder = ca_coords(str(pdb_path), "B")
    observed_lengths = {
        "reference_target": len(reference_target),
        "reference_binder": len(reference_binder),
        "fold_target": len(fold_target),
        "fold_binder": len(fold_binder),
        "locked_target": target_length,
        "locked_binder": binder_length,
    }
    if not (
        len(reference_target) == len(fold_target) == target_length
        and len(reference_binder) == len(fold_binder) == binder_length
        and target_length > 0
        and binder_length > 0
    ):
        raise ValueError(f"{candidate_id}: target/binder CA lengths differ from locks: {observed_lengths}")
    observed_lrmsd = lrmsd(fold_target, fold_binder, reference_target, reference_binder)
    iptm = float(scores["iptm"])
    ptm = float(scores["ptm"])
    if not math.isfinite(iptm) or not math.isfinite(ptm):
        raise ValueError(f"{candidate_id}: AF2 ipTM or pTM is not finite")
    observed_pae = interface_pae(pae, target_length)
    success = observed_lrmsd < threshold
    quality = max(0.0, 1.0 - observed_lrmsd / 10.0)
    return {
        "target_id": candidate_id,
        "complex_target_id": target["id"],
        "representation": candidate["representation"],
        "mean_plddt": round(float(np.mean(plddt)), 3),
        "regime": "complex",
        "predictor_id": "af2_multimer_colabfold_v1",
        "signal_source": "af2_multimer_pae_interaction",
        "label_source": "af2_multimer_lrmsd_to_reference",
        "iptm": round(iptm, 4),
        "ptm": round(ptm, 4),
        "pae_interaction": round(observed_pae, 4),
        "truth": {"correct": success, "quality": round(quality, 4)},
        "lrmsd": observed_lrmsd,
        "lrmsd_threshold": threshold,
        "interface_aligned": True,
        "target_chain": target["target_chain"],
        "binder_chain": target["binder_chain"],
        "fold_target_chain": "A",
        "fold_binder_chain": "B",
        "refolder": "af2_multimer_colabfold_v1",
        "model_tag": model_tag,
        "model_pdb": str(pdb_path),
        "scores_json": str(scores_path),
        "provenance": {
            "candidate_sequence_sha256": sequence_sha256(str(candidate["representation"])),
            "target_sequence_sha256": sequence_sha256(str(candidate["target_seq"])),
            "target_msa_sha256": target["target_msa_sha256"],
            "a3m_sha256": input_row["a3m_sha256"],
            "runtime_identity_sha256": runtime_digest,
            "model_output_sha256": sha256_file(pdb_path),
            "scores_json_sha256": sha256_file(scores_path),
            "reference_backbone_sha256": sha256_file(target["prepared_pdb"]),
            "seed": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
        },
    }


def convert(args: argparse.Namespace) -> List[Dict[str, Any]]:
    context = load_target_context(
        args.protocol,
        args.execution_manifest,
        args.input_lock,
        args.runtime_lock,
        args.target_id,
        args.stage,
    )
    target = context["target"]
    if args.candidates != target["candidates"] or args.out != target["af2_records"]:
        raise ValueError("AF2 candidate/output paths differ from the execution manifest")
    if args.threshold != 4.0:
        raise ValueError("W3b requires the frozen 4.0 Angstrom L-RMSD threshold")
    candidates = validate_candidates(context, args.candidates)
    input_manifest = load_object(args.input_manifest)
    input_rows = _validate_input_manifest(
        input_manifest,
        args.input_manifest,
        context,
        candidates,
        args.candidates,
    )
    observed_identity = load_object(args.runtime_identity)
    expected_identity = runtime_identity(
        context["runtime_lock"],
        "af2_multimer_colabfold_v1",
        args.protocol,
    )
    if observed_identity != expected_identity:
        raise ValueError("observed AF2 runtime identity differs from the W3b lock")
    runtime_digest = canonical_sha256(observed_identity)
    if runtime_digest != context["runtime_lock"]["predictor_runtime_identity_sha256"]["af2_multimer_colabfold_v1"]:
        raise ValueError("observed AF2 runtime identity digest differs from the W3b lock")
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"refusing to overwrite W3b AF2 records: {output}")
    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        raise ValueError("AF2 prediction output directory is missing")
    records = [
        _build_record(
            candidate,
            input_rows[str(candidate["id"])],
            target,
            output_dir,
            runtime_digest,
            args.threshold,
        )
        for candidate in candidates
    ]
    if len(records) != context["expected_count"]:
        raise ValueError("AF2 did not produce the exact locked W3b record count")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with open(temporary, "w") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    os.replace(temporary, output)
    return records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="configs/m6d_w3b_disagreement_gate_protocol.json")
    parser.add_argument("--execution-manifest", default="configs/m6d_w3b_execution_targets.json")
    parser.add_argument("--input-lock", default="configs/m6d_w3b_execution_input_lock.json")
    parser.add_argument("--runtime-lock", default="configs/m6d_w3b_runtime_lock.json")
    parser.add_argument("--runtime-identity", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--stage", choices=("fit", "certification", "held_out_test"), required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--threshold", type=float, default=4.0)
    args = parser.parse_args(argv)
    records = convert(args)
    print(f"target={args.target_id} predictor=af2_multimer_colabfold_v1 records={len(records)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
