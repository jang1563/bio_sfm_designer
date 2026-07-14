#!/usr/bin/env python3
"""Dedicated provenance-locked Boltz-2 producer for W3b matched records."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


def _msa_query(path: str) -> str:
    sequence: List[str] = []
    in_first_record = False
    with open(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if in_first_record:
                    break
                in_first_record = True
                continue
            if in_first_record:
                sequence.append(line)
    return "".join(
        character
        for character in "".join(sequence)
        if character.isupper() and character != "-"
    )


def _rank_zero_files(output_dir: Path, name: str) -> Dict[str, Path]:
    prediction_roots = list(output_dir.glob(f"boltz_results_*/predictions/{name}"))
    if len(prediction_roots) != 1:
        raise ValueError(f"{name}: expected one Boltz prediction directory; observed {len(prediction_roots)}")
    root = prediction_roots[0]
    expected = {
        "pdb": list(root.glob(f"{name}_model_0.pdb")),
        "confidence": list(root.glob(f"confidence_{name}_model_0.json")),
        "pae": list(root.glob(f"pae_{name}_model_0.npz")),
    }
    if any(len(paths) != 1 for paths in expected.values()):
        counts = {key: len(paths) for key, paths in expected.items()}
        raise ValueError(f"{name}: incomplete or ambiguous Boltz rank-zero outputs: {counts}")
    return {key: paths[0] for key, paths in expected.items()}


def _build_record(
    candidate: Dict[str, Any],
    target: Dict[str, Any],
    files: Dict[str, Path],
    runtime_digest: str,
    threshold: float,
) -> Dict[str, Any]:
    reference_target = ca_coords(target["prepared_pdb"], target["target_chain"])
    reference_binder = ca_coords(target["prepared_pdb"], target["binder_chain"])
    fold_target = ca_coords(str(files["pdb"]), "A")
    fold_binder = ca_coords(str(files["pdb"]), "B")
    target_length = len(str(candidate["target_seq"]))
    binder_length = len(str(candidate["representation"]))
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
        raise ValueError(f"{candidate['id']}: target/binder CA lengths differ from locks: {observed_lengths}")
    observed_lrmsd = lrmsd(fold_target, fold_binder, reference_target, reference_binder)
    with open(files["confidence"]) as handle:
        confidence = json.load(handle)
    with np.load(files["pae"]) as archive:
        if len(archive.files) != 1:
            raise ValueError(f"{candidate['id']}: expected one pAE array")
        pae = np.asarray(archive[archive.files[0]], dtype=float)
    expected_size = target_length + binder_length
    if pae.shape != (expected_size, expected_size):
        raise ValueError(f"{candidate['id']}: pAE shape differs from locked complex length")
    plddt = float(confidence["complex_plddt"])
    ptm = float(confidence["ptm"])
    iptm = float(confidence["iptm"])
    if not all(math.isfinite(value) for value in (plddt, ptm, iptm)):
        raise ValueError(f"{candidate['id']}: Boltz confidence contains non-finite values")
    observed_pae = interface_pae(pae, target_length)
    success = observed_lrmsd < threshold
    quality = max(0.0, 1.0 - observed_lrmsd / 10.0)
    return {
        "target_id": candidate["id"],
        "complex_target_id": target["id"],
        "representation": candidate["representation"],
        "mean_plddt": round(100.0 * plddt, 3),
        "regime": "complex",
        "predictor_id": "boltz2_complex",
        "signal_source": "boltz2_pae_interaction",
        "label_source": "boltz2_lrmsd_to_reference",
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
        "refolder": "boltz2_complex",
        "model_pdb": str(files["pdb"]),
        "confidence_json": str(files["confidence"]),
        "pae_npz": str(files["pae"]),
        "provenance": {
            "candidate_sequence_sha256": sequence_sha256(str(candidate["representation"])),
            "target_sequence_sha256": sequence_sha256(str(candidate["target_seq"])),
            "target_msa_sha256": target["target_msa_sha256"],
            "runtime_identity_sha256": runtime_digest,
            "model_output_sha256": sha256_file(files["pdb"]),
            "confidence_json_sha256": sha256_file(files["confidence"]),
            "pae_npz_sha256": sha256_file(files["pae"]),
            "reference_backbone_sha256": sha256_file(target["prepared_pdb"]),
            "seed": 0,
            "templates_used": False,
            "prediction_time_network_used": False,
        },
    }


def run(args: argparse.Namespace) -> List[Dict[str, Any]]:
    context = load_target_context(
        args.protocol,
        args.execution_manifest,
        args.input_lock,
        args.runtime_lock,
        args.target_id,
        args.stage,
    )
    target = context["target"]
    if args.candidates != target["candidates"] or args.out != target["boltz_records"]:
        raise ValueError("Boltz candidate/output paths differ from the execution manifest")
    candidates = validate_candidates(context, args.candidates)
    if args.threshold != 4.0:
        raise ValueError("W3b requires the frozen 4.0 Angstrom L-RMSD threshold")
    if _msa_query(target["target_msa"]) != candidates[0]["target_seq"]:
        raise ValueError("target-MSA query differs from the locked target sequence")
    observed_identity = load_object(args.runtime_identity)
    expected_identity = runtime_identity(
        context["runtime_lock"],
        "boltz2_complex",
        args.protocol,
    )
    if observed_identity != expected_identity:
        raise ValueError("observed Boltz runtime identity differs from the W3b lock")
    runtime_digest = canonical_sha256(observed_identity)
    if runtime_digest != context["runtime_lock"]["predictor_runtime_identity_sha256"]["boltz2_complex"]:
        raise ValueError("observed Boltz runtime identity digest differs from the W3b lock")

    output = Path(args.out)
    if output.exists():
        raise ValueError(f"refusing to overwrite W3b Boltz records: {output}")
    work = output.parent / ("_w3b_boltz_work_" + output.stem)
    if work.exists():
        raise ValueError(f"refusing to reuse W3b Boltz work directory: {work}")
    yaml_dir = work / "yamls"
    prediction_dir = work / "out"
    yaml_dir.mkdir(parents=True)
    names: List[tuple[str, Dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        name = f"w3b{index:03d}"
        names.append((name, candidate))
        payload = (
            "version: 1\n"
            "sequences:\n"
            "  - protein:\n"
            "      id: A\n"
            f"      sequence: {candidate['target_seq']}\n"
            f"      msa: {json.dumps(os.path.abspath(target['target_msa']))}\n"
            "  - protein:\n"
            "      id: B\n"
            f"      sequence: {candidate['representation']}\n"
            "      msa: empty\n"
            "templates: []\n"
        )
        (yaml_dir / f"{name}.yaml").write_text(payload)

    command = [
        args.boltz,
        "predict",
        str(yaml_dir),
        "--out_dir",
        str(prediction_dir),
        "--no_kernels",
        "--output_format",
        "pdb",
        "--accelerator",
        "gpu",
        "--devices",
        "1",
        "--model",
        "boltz2",
        "--seed",
        "0",
        "--recycling_steps",
        "3",
        "--diffusion_samples",
        "1",
        "--sampling_steps",
        "100",
        "--write_full_pae",
    ]
    subprocess.run(command, check=True)
    records = [
        _build_record(
            candidate,
            target,
            _rank_zero_files(prediction_dir, name),
            runtime_digest,
            args.threshold,
        )
        for name, candidate in names
    ]
    if len(records) != context["expected_count"]:
        raise ValueError("Boltz did not produce the exact locked W3b record count")
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
    parser.add_argument("--out", required=True)
    parser.add_argument("--threshold", type=float, default=4.0)
    parser.add_argument("--boltz", default=os.path.expanduser("~/.conda/envs/boltz/bin/boltz"))
    args = parser.parse_args(argv)
    records = run(args)
    print(f"target={args.target_id} predictor=boltz2_complex records={len(records)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
