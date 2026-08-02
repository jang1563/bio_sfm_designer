"""Materialize and validate the frozen W3d prospective inputs without prediction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from bio_sfm_designer.experiments import m6d_w3d_native_diagnostic as diagnostic
from bio_sfm_designer.experiments.m6d_w3_mechanism_panel import (
    build_annotated_multimer_a3m,
)
from bio_sfm_designer.experiments.m6d_w3c_b2_producer import load_context
from bio_sfm_designer.experiments.m6d_w3c_b2_runtime import validate_observation


INPUT_MANIFEST_PATH = "configs/m6d_w3d_prospective_input_manifest.json"
READINESS_PATH = "results/m6d_w3d_input_runtime_readiness.json"
READINESS_MD_PATH = "results/m6d_w3d_input_runtime_readiness.md"
RUNTIME_RECEIPT_PATH = "results/m6d_w3d_runtime_validation_receipt.json"

NATIVE_MANIFEST_PATH = "configs/m6d_w3c_b2_native_screen_manifest.json"
RUNTIME_LOCK_PATH = "configs/m6d_w3c_b2_runtime_lock.json"
B1_COMPLETION_PATH = "results/m6d_w3c_b1_target_msa_completion.json"
W3B_RUNTIME_LOCK_PATH = "configs/m6d_w3b_runtime_lock.json"
W3C_PROTOCOL_PATH = "configs/m6d_w3c_validity_first_protocol.json"

PRODUCER_PATH = (
    "src/bio_sfm_designer/experiments/m6d_w3d_input_runtime.py"
)
WRAPPER_PATHS = {
    "orchestrator": "hpc/validate_w3d_runtime_no_prediction.sh",
    "boltz2_complex": "hpc/validate_w3d_boltz_runtime_no_prediction.sh",
    "af2_multimer_colabfold_v1": (
        "hpc/validate_w3d_af2_runtime_no_prediction.sh"
    ),
}

INPUT_STATUS = "w3d_24_prospective_inputs_materialized_no_prediction"
READINESS_PENDING_STATUS = (
    "w3d_inputs_materialized_runtime_validation_pending_no_submit"
)
READINESS_COMPLETE_STATUS = (
    "w3d_input_and_runtime_validation_complete_no_submit"
)
RECEIPT_STATUS = "w3d_exact_runtime_and_path_validation_complete_no_prediction"

AF2_SETTINGS = {
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
BOLTZ_SETTINGS = {
    "accelerator": "gpu",
    "devices": 1,
    "diffusion_samples": 1,
    "model": "boltz2",
    "no_kernels": True,
    "output_format": "pdb",
    "prediction_time_network_used": False,
    "recycling_steps": 3,
    "sampling_steps": 100,
    "seed": 0,
    "templates_used": False,
    "write_full_pae": True,
}


PathLike = Union[os.PathLike, str]


def sha256_file(path: PathLike) -> str:
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_object(path: PathLike) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _binding(path: str) -> Dict[str, Any]:
    source = Path(path)
    _require(source.is_file() and source.stat().st_size > 0, f"missing artifact: {path}")
    return {
        "path": path,
        "bytes": source.stat().st_size,
        "sha256": sha256_file(source),
    }


def _redacted_binding(path: str) -> Dict[str, Any]:
    binding = _binding(path)
    return {
        "bytes": binding["bytes"],
        "sha256": binding["sha256"],
        "path_published": False,
    }


def _write_text_idempotent(path: PathLike, value: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_text() != value:
            raise ValueError(f"refusing to overwrite divergent W3d artifact: {path}")
        os.chmod(destination, 0o644)
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=str(destination.parent)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o644)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_idempotent(
    path: PathLike, value: Mapping[str, Any]
) -> None:
    _write_text_idempotent(
        path, json.dumps(value, indent=2, sort_keys=True) + "\n"
    )


def _safe_relative_path(value: Any, *, prefix: Optional[str] = None) -> str:
    _require(isinstance(value, str) and bool(value), "W3d path must be a string")
    path = Path(value)
    _require(not path.is_absolute() and ".." not in path.parts, f"unsafe W3d path: {value}")
    normalized = path.as_posix()
    if prefix is not None:
        _require(
            normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"),
            f"W3d path is outside {prefix}: {value}",
        )
    return normalized


def build_query_only_a3m(target_sequence: str, binder_sequence: str) -> str:
    """Encode one paired query and no homolog rows for ColabFold multimer."""

    return (
        f"#{len(target_sequence)},{len(binder_sequence)}\t1,1\n"
        ">101\t102\n"
        f"{target_sequence}{binder_sequence}\n"
    )


def build_boltz_yaml(
    target_sequence: str,
    binder_sequence: str,
    representation_id: str,
    *,
    target_msa_path: Optional[str] = None,
) -> str:
    """Render a deterministic predictor-native Boltz complex input."""

    _require(
        representation_id in diagnostic.REPRESENTATION_IDS,
        f"unsupported W3d representation: {representation_id}",
    )
    if representation_id == "target_msa_binder_query":
        _require(
            isinstance(target_msa_path, str) and os.path.isabs(target_msa_path),
            "target-MSA Boltz input requires an absolute MSA path",
        )
        target_msa = json.dumps(target_msa_path)
    else:
        _require(target_msa_path is None, "query-only Boltz input cannot reference an MSA")
        target_msa = "empty"
    return (
        "version: 1\n"
        "sequences:\n"
        "  - protein:\n"
        "      id: A\n"
        f"      sequence: {target_sequence}\n"
        f"      msa: {target_msa}\n"
        "  - protein:\n"
        "      id: B\n"
        f"      sequence: {binder_sequence}\n"
        "      msa: empty\n"
        "templates: []\n"
    )


def _parse_a3m_records(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    lines = text.splitlines()
    _require(bool(lines) and lines[0].startswith("#"), "annotated A3M header is missing")
    records: List[Tuple[str, str]] = []
    header: Optional[str] = None
    sequence: List[str] = []
    for line in lines[1:]:
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence)))
            header = line
            sequence = []
        else:
            _require(header is not None, "A3M sequence precedes its record header")
            sequence.append(line.strip())
    if header is not None:
        records.append((header, "".join(sequence)))
    _require(bool(records), "annotated A3M has no records")
    return lines[0], records


def _validate_af2_payload(cell: Mapping[str, Any], text: str) -> None:
    target_length = int(cell["target_sequence_length"])
    binder_length = int(cell["binder_sequence_length"])
    annotated_header, records = _parse_a3m_records(text)
    _require(
        annotated_header == f"#{target_length},{binder_length}\t1,1",
        f"{cell['cell_id']}: annotated A3M dimensions drifted",
    )
    query_header, query = records[0]
    _require(query_header == ">101\t102", f"{cell['cell_id']}: paired query header drifted")
    _require(
        len(query) == target_length + binder_length,
        f"{cell['cell_id']}: paired query length drifted",
    )
    target_sequence = query[:target_length]
    binder_sequence = query[target_length:]
    _require(
        _sha256_text(target_sequence) == cell["target_sequence_sha256"]
        and _sha256_text(binder_sequence) == cell["binder_sequence_sha256"],
        f"{cell['cell_id']}: paired native sequence binding drifted",
    )
    representation_id = cell["representation_id"]
    if representation_id == "query_only_both_chains":
        _require(
            len(records) == 1
            and cell["target_msa_records_in_input"] == 0
            and cell["external_msa_references"] == 0,
            f"{cell['cell_id']}: query-only AF2 input contains homolog rows",
        )
        return

    target_record_count = int(cell["target_msa_records_in_input"])
    _require(
        len(records) == target_record_count + 2,
        f"{cell['cell_id']}: target-MSA AF2 record count drifted",
    )
    binder_gap = "-" * binder_length
    reconstructed: List[str] = []
    for header, sequence in records[1:-1]:
        _require(
            sequence.endswith(binder_gap),
            f"{cell['cell_id']}: unpaired target row has binder content",
        )
        reconstructed.extend((header, sequence[:-binder_length]))
    binder_header, binder_row = records[-1]
    _require(
        binder_header == ">w3_designed_binder_query"
        and binder_row == "-" * target_length + binder_sequence,
        f"{cell['cell_id']}: unpaired binder query drifted",
    )
    reconstructed_text = "\n".join(reconstructed) + "\n"
    _require(
        _sha256_text(reconstructed_text) == cell["target_msa_sha256"]
        and cell["external_msa_references"] == 0,
        f"{cell['cell_id']}: embedded target MSA drifted",
    )


def _parse_boltz_yaml(text: str) -> Tuple[str, str, str, str]:
    lines = text.splitlines()
    expected_prefixes = (
        (4, "      sequence: "),
        (5, "      msa: "),
        (8, "      sequence: "),
        (9, "      msa: "),
    )
    _require(
        len(lines) == 11
        and lines[0] == "version: 1"
        and lines[1] == "sequences:"
        and lines[2] == "  - protein:"
        and lines[3] == "      id: A"
        and lines[6] == "  - protein:"
        and lines[7] == "      id: B"
        and lines[10] == "templates: []",
        "Boltz YAML structure drifted",
    )
    values: List[str] = []
    for index, prefix in expected_prefixes:
        _require(lines[index].startswith(prefix), "Boltz YAML field order drifted")
        values.append(lines[index][len(prefix):])
    return values[0], values[1], values[2], values[3]


def _validate_boltz_payload(cell: Mapping[str, Any], text: str) -> None:
    target_sequence, target_msa, binder_sequence, binder_msa = _parse_boltz_yaml(text)
    _require(
        len(target_sequence) == cell["target_sequence_length"]
        and len(binder_sequence) == cell["binder_sequence_length"]
        and _sha256_text(target_sequence) == cell["target_sequence_sha256"]
        and _sha256_text(binder_sequence) == cell["binder_sequence_sha256"],
        f"{cell['cell_id']}: Boltz native sequence binding drifted",
    )
    _require(binder_msa == "empty", f"{cell['cell_id']}: binder MSA must be empty")
    if cell["representation_id"] == "query_only_both_chains":
        _require(
            target_msa == "empty" and cell["external_msa_references"] == 0,
            f"{cell['cell_id']}: query-only Boltz input references an MSA",
        )
    else:
        _require(
            target_msa.startswith('"/') and target_msa.endswith('"'),
            f"{cell['cell_id']}: target-MSA Boltz path is not absolute",
        )


def _validate_locked_sources(
    protocol: Mapping[str, Any],
    factorial_manifest: Mapping[str, Any],
    *,
    protocol_path: str,
    factorial_manifest_path: str,
) -> None:
    diagnostic.validate_protocol(protocol)
    _require(
        factorial_manifest.get("artifact")
        == "m6d_w3d_native_diagnostic_manifest"
        and factorial_manifest.get("status") == diagnostic.STATUS
        and factorial_manifest.get("audit_ok") is True
        and factorial_manifest.get("target_ids") == diagnostic.TARGET_IDS
        and factorial_manifest.get("predictor_ids") == diagnostic.PREDICTOR_IDS
        and factorial_manifest.get("representation_ids")
        == diagnostic.REPRESENTATION_IDS
        and factorial_manifest.get("prospective_cells")
        == diagnostic.PROSPECTIVE_CELLS
        and factorial_manifest.get("predictor_evaluations_authorized") == 0
        and factorial_manifest.get("h100_gpu_hours_authorized") == 0.0
        and factorial_manifest.get("no_submit") is True
        and factorial_manifest.get("cayuga_submission_allowed") is False,
        "W3d factorial manifest boundary drifted",
    )
    _require(
        factorial_manifest.get("protocol_binding") == _binding(protocol_path),
        "W3d protocol/manifest binding drifted",
    )
    _require(
        sha256_file(factorial_manifest_path)
        == _binding(factorial_manifest_path)["sha256"],
        "W3d factorial manifest is unreadable",
    )


def _expected_prospective_cells(
    factorial_manifest: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    cells = [
        row
        for row in factorial_manifest.get("cells", [])
        if isinstance(row, dict)
        and row.get("cell_status") == "prospective_not_authorized"
    ]
    _require(
        len(cells) == diagnostic.PROSPECTIVE_CELLS
        and all(
            row.get("new_prediction_required") is True
            and row.get("prospective_after_protocol_lock") is True
            and row.get("prediction_authorized") is False
            for row in cells
        ),
        "W3d prospective cell scope drifted",
    )
    return cells


def _cell_input_path(cell: Mapping[str, Any]) -> str:
    output_root = _safe_relative_path(
        cell.get("planned_output_root"),
        prefix="hpc_outputs/m6d_w3d_native_diagnostic",
    )
    if cell["predictor_id"] == "boltz2_complex":
        filename = "w3d.yaml"
    else:
        filename = f"{cell['cell_id']}.a3m"
    return (Path(output_root) / "input" / filename).as_posix()


def _context_map() -> Dict[str, Mapping[str, Any]]:
    return {
        target_id: load_context(
            NATIVE_MANIFEST_PATH,
            RUNTIME_LOCK_PATH,
            target_id,
            "boltz2_complex",
        )
        for target_id in diagnostic.TARGET_IDS
    }


def build_input_manifest(
    protocol: Mapping[str, Any],
    factorial_manifest: Mapping[str, Any],
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    protocol_path: str = diagnostic.PROTOCOL_PATH,
    factorial_manifest_path: str = diagnostic.MANIFEST_PATH,
    project_root: PathLike = ".",
    materialize: bool = True,
) -> Dict[str, Any]:
    """Build all and only the 24 prospective predictor-native inputs."""

    _validate_locked_sources(
        protocol,
        factorial_manifest,
        protocol_path=protocol_path,
        factorial_manifest_path=factorial_manifest_path,
    )
    root = Path(project_root).resolve()
    _require(set(contexts) == set(diagnostic.TARGET_IDS), "W3d context scope drifted")
    runtime_lock = _load_object(RUNTIME_LOCK_PATH)
    runtime_ids = runtime_lock.get("predictor_runtime_identity_sha256")
    _require(
        runtime_ids
        == protocol["runtime_contract"]["predictor_runtime_identity_sha256"],
        "W3d runtime identity transfer drifted",
    )
    targets = {
        row["target_id"]: row
        for row in factorial_manifest.get("targets", [])
        if isinstance(row, dict) and isinstance(row.get("target_id"), str)
    }
    _require(list(targets) == diagnostic.TARGET_IDS, "W3d target metadata order drifted")

    rows: List[Dict[str, Any]] = []
    for cell in _expected_prospective_cells(factorial_manifest):
        target_id = str(cell["target_id"])
        predictor_id = str(cell["predictor_id"])
        representation_id = str(cell["representation_id"])
        context = contexts[target_id]
        target = targets[target_id]
        target_sequence = str(context["target_sequence"])
        binder_sequence = str(context["binder_sequence"])
        _require(
            len(target_sequence) == target["target_sequence_length"]
            and len(binder_sequence) == target["binder_sequence_length"]
            and _sha256_text(target_sequence) == target["target_sequence_sha256"]
            and _sha256_text(binder_sequence) == target["binder_sequence_sha256"],
            f"{target_id}: W3d native sequence source drifted",
        )
        input_path = _cell_input_path(cell)
        if predictor_id == "af2_multimer_colabfold_v1":
            if representation_id == "target_msa_binder_query":
                target_msa_text = Path(str(context["target"]["target_msa"])).read_text()
                payload = build_annotated_multimer_a3m(
                    target_msa_text, target_sequence, binder_sequence
                )
                target_msa_records = int(target["target_msa_records"])
                target_msa_sha256: Optional[str] = str(target["target_msa_sha256"])
            else:
                payload = build_query_only_a3m(target_sequence, binder_sequence)
                target_msa_records = 0
                target_msa_sha256 = None
            input_kind = "af2_annotated_multimer_a3m"
            settings = AF2_SETTINGS
        else:
            _require(
                representation_id == "query_only_both_chains",
                "the locked Boltz target-MSA cell is retrospective and cannot be rebuilt",
            )
            payload = build_boltz_yaml(
                target_sequence, binder_sequence, representation_id
            )
            input_kind = "boltz_yaml"
            settings = BOLTZ_SETTINGS
            target_msa_records = 0
            target_msa_sha256 = None
        destination = root / input_path
        if materialize:
            _write_text_idempotent(destination, payload)
        row = {
            "cell_id": cell["cell_id"],
            "target_id": target_id,
            "representation_id": representation_id,
            "predictor_id": predictor_id,
            "input_kind": input_kind,
            "input_path": input_path,
            "input_bytes": len(payload.encode("utf-8")),
            "input_sha256": _sha256_text(payload),
            "target_sequence_length": len(target_sequence),
            "target_sequence_sha256": target["target_sequence_sha256"],
            "binder_sequence_length": len(binder_sequence),
            "binder_sequence_sha256": target["binder_sequence_sha256"],
            "target_msa_records_in_input": target_msa_records,
            "target_msa_sha256": target_msa_sha256,
            "paired_query_rows": 1,
            "nonquery_paired_rows": 0,
            "binder_homolog_rows": 0,
            "external_msa_references": 0,
            "planned_output_dir": (
                Path(str(cell["planned_output_root"])) / "prediction"
            ).as_posix(),
            "planned_record": cell["planned_record"],
            "runtime_identity_sha256": runtime_ids[predictor_id],
            "prediction_settings": dict(settings),
            "container_path_policy": {
                "declared_paths_are_repo_relative": True,
                "runtime_input_and_output_must_be_absolute": True,
                "project_root_bind_must_preserve_absolute_path": True,
                "container_working_directory_must_equal_project_root": (
                    predictor_id == "af2_multimer_colabfold_v1"
                ),
            },
            "prediction_authorized": False,
        }
        if materialize:
            _require(
                destination.stat().st_size == row["input_bytes"]
                and sha256_file(destination) == row["input_sha256"],
                f"{cell['cell_id']}: materialized input hash drifted",
            )
        rows.append(row)

    _require(
        len(rows) == 24
        and sum(row["predictor_id"] == "boltz2_complex" for row in rows) == 8
        and sum(
            row["predictor_id"] == "af2_multimer_colabfold_v1" for row in rows
        )
        == 16,
        "W3d producer did not build the exact 24-cell scope",
    )
    return {
        "artifact": "m6d_w3d_prospective_input_manifest",
        "version": 1,
        "status": INPUT_STATUS,
        "audit_ok": True,
        "protocol_binding": _binding(protocol_path),
        "factorial_manifest_binding": _binding(factorial_manifest_path),
        "native_manifest_binding": _binding(NATIVE_MANIFEST_PATH),
        "runtime_lock_binding": _binding(RUNTIME_LOCK_PATH),
        "producer_binding": _binding(PRODUCER_PATH),
        "target_ids": diagnostic.TARGET_IDS,
        "predictor_ids": diagnostic.PREDICTOR_IDS,
        "representation_ids": diagnostic.REPRESENTATION_IDS,
        "prospective_cells": 24,
        "prospective_boltz_cells": 8,
        "prospective_af2_cells": 16,
        "materialized_input_files": 24,
        "runtime_identity_sha256": runtime_ids,
        "cells": rows,
        "absolute_host_paths_published": False,
        "raw_input_files_tracked": False,
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "scheduler_command_executed": False,
        "network_fetch_executed": False,
        "predictor_evaluations_authorized": 0,
        "h100_gpu_hours_authorized": 0.0,
        "approval_packet_prepared": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "claim_boundary": (
            "This manifest binds CPU-generated inputs for 24 prospective W3d cells. "
            "It records no runtime validation, prediction, approval, or scientific outcome."
        ),
    }


def validate_input_manifest(
    input_manifest: Mapping[str, Any],
    *,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
    protocol_path: str = diagnostic.PROTOCOL_PATH,
    factorial_manifest_path: str = diagnostic.MANIFEST_PATH,
    project_root: PathLike = ".",
    require_files: bool = True,
) -> None:
    protocol = _load_object(protocol_path)
    factorial_manifest = _load_object(factorial_manifest_path)
    _validate_locked_sources(
        protocol,
        factorial_manifest,
        protocol_path=protocol_path,
        factorial_manifest_path=factorial_manifest_path,
    )
    cells = input_manifest.get("cells")
    expected = _expected_prospective_cells(factorial_manifest)
    _require(
        input_manifest.get("artifact") == "m6d_w3d_prospective_input_manifest"
        and input_manifest.get("version") == 1
        and input_manifest.get("status") == INPUT_STATUS
        and input_manifest.get("audit_ok") is True
        and input_manifest.get("protocol_binding") == _binding(protocol_path)
        and input_manifest.get("factorial_manifest_binding")
        == _binding(factorial_manifest_path)
        and input_manifest.get("native_manifest_binding")
        == _binding(NATIVE_MANIFEST_PATH)
        and input_manifest.get("runtime_lock_binding") == _binding(RUNTIME_LOCK_PATH)
        and input_manifest.get("producer_binding") == _binding(PRODUCER_PATH)
        and input_manifest.get("target_ids") == diagnostic.TARGET_IDS
        and input_manifest.get("predictor_ids") == diagnostic.PREDICTOR_IDS
        and input_manifest.get("representation_ids") == diagnostic.REPRESENTATION_IDS
        and input_manifest.get("prospective_cells") == 24
        and input_manifest.get("prospective_boltz_cells") == 8
        and input_manifest.get("prospective_af2_cells") == 16
        and input_manifest.get("materialized_input_files") == 24
        and isinstance(cells, list)
        and len(cells) == 24,
        "W3d input manifest identity or scope drifted",
    )
    runtime_ids = _load_object(RUNTIME_LOCK_PATH)[
        "predictor_runtime_identity_sha256"
    ]
    _require(
        input_manifest.get("runtime_identity_sha256") == runtime_ids,
        "W3d input runtime identity binding drifted",
    )
    root = Path(project_root).resolve()
    for source, row in zip(expected, cells):
        _require(isinstance(row, dict), "W3d input cell must be an object")
        predictor_id = source["predictor_id"]
        representation_id = source["representation_id"]
        input_path = _safe_relative_path(
            row.get("input_path"), prefix="hpc_outputs/m6d_w3d_native_diagnostic"
        )
        _require(
            row.get("cell_id") == source["cell_id"]
            and row.get("target_id") == source["target_id"]
            and row.get("representation_id") == representation_id
            and row.get("predictor_id") == predictor_id
            and input_path == _cell_input_path(source)
            and row.get("planned_record") == source["planned_record"]
            and row.get("planned_output_dir")
            == (Path(str(source["planned_output_root"])) / "prediction").as_posix()
            and row.get("runtime_identity_sha256") == runtime_ids[predictor_id]
            and row.get("paired_query_rows") == 1
            and row.get("nonquery_paired_rows") == 0
            and row.get("binder_homolog_rows") == 0
            and row.get("external_msa_references") == 0
            and row.get("prediction_authorized") is False
            and isinstance(row.get("input_bytes"), int)
            and row["input_bytes"] > 0
            and _is_sha256(row.get("input_sha256")),
            f"{source['cell_id']}: W3d input-cell contract drifted",
        )
        if predictor_id == "af2_multimer_colabfold_v1":
            _require(
                row.get("input_kind") == "af2_annotated_multimer_a3m"
                and row.get("prediction_settings") == AF2_SETTINGS,
                f"{source['cell_id']}: AF2 settings drifted",
            )
        else:
            _require(
                representation_id == "query_only_both_chains"
                and row.get("input_kind") == "boltz_yaml"
                and row.get("prediction_settings") == BOLTZ_SETTINGS,
                f"{source['cell_id']}: Boltz settings drifted",
            )
        if not require_files:
            continue
        path = root / input_path
        _require(
            path.is_file()
            and path.stat().st_size == row["input_bytes"]
            and sha256_file(path) == row["input_sha256"],
            f"{source['cell_id']}: W3d materialized input is missing or drifted",
        )
        text = path.read_text()
        if predictor_id == "af2_multimer_colabfold_v1":
            _validate_af2_payload(row, text)
        else:
            _validate_boltz_payload(row, text)
    _require(
        input_manifest.get("absolute_host_paths_published") is False
        and input_manifest.get("prediction_executed") is False
        and input_manifest.get("gpu_compute_executed") is False
        and input_manifest.get("scheduler_command_executed") is False
        and input_manifest.get("network_fetch_executed") is False
        and input_manifest.get("predictor_evaluations_authorized") == 0
        and input_manifest.get("h100_gpu_hours_authorized") == 0.0
        and input_manifest.get("approval_packet_prepared") is False
        and input_manifest.get("no_submit") is True
        and input_manifest.get("cayuga_submission_allowed") is False,
        "W3d input manifest authority drifted",
    )
    if Path(input_manifest_path).is_file():
        _require(
            _load_object(input_manifest_path) == dict(input_manifest),
            "serialized W3d input manifest differs from the validated object",
        )


def _validate_wrapper_contracts() -> Dict[str, Dict[str, Any]]:
    bindings = {name: _binding(path) for name, path in WRAPPER_PATHS.items()}
    combined = "\n".join(Path(path).read_text() for path in WRAPPER_PATHS.values())
    for forbidden in (
        "sbatch",
        "srun",
        "--nv",
        "boltz predict",
        "colabfold_batch",
        "curl ",
        "wget ",
    ):
        _require(forbidden not in combined, f"W3d no-prediction wrapper contains {forbidden}")
    af2 = Path(WRAPPER_PATHS["af2_multimer_colabfold_v1"]).read_text()
    boltz = Path(WRAPPER_PATHS["boltz2_complex"]).read_text()
    orchestrator = Path(WRAPPER_PATHS["orchestrator"]).read_text()
    _require(
        '--pwd "$PROJECT_ROOT"' in af2
        and '--bind "$PROJECT_ROOT:$PROJECT_ROOT"' in af2
        and "--network none" in af2
        and "APPTAINER_BIN" in af2
        and "AF2_INPUT_PATH_PLAN" in af2
        and "PYTHONNOUSERSITE=1" in af2,
        "W3d AF2 absolute container path contract is incomplete",
    )
    _require(
        "BOLTZ_INPUT_PATH_PLAN" in boltz
        and "PYTHONNOUSERSITE=1" in boltz
        and "m6d_w3c_b2_runtime" in boltz,
        "W3d Boltz no-prediction runtime contract is incomplete",
    )
    _require(
        "validate_w3d_boltz_runtime_no_prediction.sh" in orchestrator
        and "validate_w3d_af2_runtime_no_prediction.sh" in orchestrator
        and "runtime-receipt" in orchestrator,
        "W3d runtime validation orchestrator is incomplete",
    )
    return bindings


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"{path}:{line_number}: expected object")
        rows.append(value)
    return rows


def emit_path_plan(
    input_manifest: Mapping[str, Any],
    predictor_id: str,
    *,
    project_root: PathLike = ".",
) -> List[Dict[str, Any]]:
    validate_input_manifest(input_manifest, project_root=project_root, require_files=True)
    _require(
        predictor_id in diagnostic.PREDICTOR_IDS,
        f"unsupported W3d predictor: {predictor_id}",
    )
    root = Path(project_root).resolve()
    rows: List[Dict[str, Any]] = []
    for cell in input_manifest["cells"]:
        if cell["predictor_id"] != predictor_id:
            continue
        input_path = (root / cell["input_path"]).resolve()
        output_path = (root / cell["planned_output_dir"]).resolve()
        _require(
            os.path.commonpath((str(input_path), str(root))) == str(root)
            and os.path.commonpath((str(output_path), str(root))) == str(root)
            and input_path.is_absolute()
            and output_path.is_absolute()
            and input_path.is_file()
            and output_path.parent.is_dir(),
            f"{cell['cell_id']}: runtime path is not project-bound and absolute",
        )
        rows.append({
            "cell_id": cell["cell_id"],
            "predictor_id": predictor_id,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "input_sha256": cell["input_sha256"],
            "project_root": str(root),
        })
    expected = 8 if predictor_id == "boltz2_complex" else 16
    _require(len(rows) == expected, f"W3d path plan expected {expected} cells")
    return rows


def probe_host_paths(path_plan: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    probes: List[Dict[str, Any]] = []
    for row in path_plan:
        input_path = str(row["input_path"])
        output_path = str(row["output_path"])
        project_root = str(row["project_root"])
        _require(
            os.path.isabs(input_path)
            and os.path.isabs(output_path)
            and os.path.commonpath((input_path, project_root)) == project_root
            and os.path.commonpath((output_path, project_root)) == project_root
            and sha256_file(input_path) == row["input_sha256"]
            and Path(output_path).parent.is_dir(),
            f"{row['cell_id']}: host runtime path probe failed",
        )
        probes.append({
            "cell_id": row["cell_id"],
            "predictor_id": row["predictor_id"],
            "runtime_surface": "host_boltz",
            "input_sha256": row["input_sha256"],
            "input_absolute": True,
            "output_absolute": True,
            "project_root_bound": True,
            "container_working_directory_explicit": False,
            "raw_paths_published": False,
        })
    return probes


def _validate_probe_rows(
    rows: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
    predictor_id: str,
) -> None:
    expected_cells = [
        row for row in input_manifest["cells"] if row["predictor_id"] == predictor_id
    ]
    expected = {row["cell_id"]: row for row in expected_cells}
    _require(
        len(rows) == len(expected)
        and [row.get("cell_id") for row in rows] == list(expected),
        f"W3d {predictor_id} path probe scope drifted",
    )
    for row in rows:
        cell = expected[str(row["cell_id"])]
        expected_surface = (
            "host_boltz"
            if predictor_id == "boltz2_complex"
            else "af2_container"
        )
        _require(
            row.get("predictor_id") == predictor_id
            and row.get("runtime_surface") == expected_surface
            and row.get("input_sha256") == cell["input_sha256"]
            and row.get("input_absolute") is True
            and row.get("output_absolute") is True
            and row.get("project_root_bound") is True
            and row.get("raw_paths_published") is False
            and row.get("container_working_directory_explicit")
            is (predictor_id == "af2_multimer_colabfold_v1"),
            f"{row.get('cell_id')}: W3d path probe evidence drifted",
        )


def _validate_runtime_observation(
    observation: Mapping[str, Any], predictor_id: str
) -> None:
    failures = validate_observation(
        observation,
        predictor_id,
        protocol_path=W3C_PROTOCOL_PATH,
        native_manifest_path=NATIVE_MANIFEST_PATH,
        b1_completion_path=B1_COMPLETION_PATH,
        w3b_runtime_lock_path=W3B_RUNTIME_LOCK_PATH,
    )
    runtime_lock = _load_object(RUNTIME_LOCK_PATH)
    _require(
        not failures
        and observation.get("runtime_identity")
        == runtime_lock["predictor_runtime_identities"][predictor_id]
        and observation.get("runtime_identity_sha256")
        == runtime_lock["predictor_runtime_identity_sha256"][predictor_id],
        f"W3d {predictor_id} exact runtime reobservation drifted: {failures}",
    )


def build_runtime_receipt(
    input_manifest: Mapping[str, Any],
    *,
    boltz_observation_path: str,
    af2_observation_path: str,
    boltz_probe_path: str,
    af2_probe_path: str,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
    project_root: PathLike = ".",
) -> Dict[str, Any]:
    validate_input_manifest(
        input_manifest,
        input_manifest_path=input_manifest_path,
        project_root=project_root,
        require_files=True,
    )
    observations = {
        "boltz2_complex": _load_object(boltz_observation_path),
        "af2_multimer_colabfold_v1": _load_object(af2_observation_path),
    }
    for predictor_id, observation in observations.items():
        _validate_runtime_observation(observation, predictor_id)
    probes = {
        "boltz2_complex": _load_jsonl(boltz_probe_path),
        "af2_multimer_colabfold_v1": _load_jsonl(af2_probe_path),
    }
    for predictor_id, rows in probes.items():
        _validate_probe_rows(rows, input_manifest, predictor_id)
    runtime_lock = _load_object(RUNTIME_LOCK_PATH)
    return {
        "artifact": "m6d_w3d_runtime_validation_receipt",
        "version": 1,
        "status": RECEIPT_STATUS,
        "audit_ok": True,
        "input_manifest_binding": _binding(input_manifest_path),
        "runtime_lock_binding": _binding(RUNTIME_LOCK_PATH),
        "wrapper_bindings": _validate_wrapper_contracts(),
        "runtime_observation_bindings": {
            "boltz2_complex": _redacted_binding(boltz_observation_path),
            "af2_multimer_colabfold_v1": _redacted_binding(af2_observation_path),
        },
        "path_probe_evidence": probes,
        "predictor_runtime_identity_sha256": runtime_lock[
            "predictor_runtime_identity_sha256"
        ],
        "runtime_observations_complete": 2,
        "prospective_input_hashes_verified": 24,
        "absolute_path_probes_complete": 24,
        "boltz_host_path_probes_complete": 8,
        "af2_container_path_probes_complete": 16,
        "af2_explicit_container_working_directory_probes": 16,
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "scheduler_command_executed": False,
        "network_fetch_executed": False,
        "raw_host_paths_published": False,
        "predictor_evaluations_authorized": 0,
        "h100_gpu_hours_authorized": 0.0,
        "approval_packet_prepared": False,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "can_run_predictors": False,
        "claim_boundary": (
            "Exact runtime identity and absolute-path resolution were validated without "
            "model inference, accelerator use, scheduler action, network fetch, or compute authority."
        ),
    }


def validate_runtime_receipt(
    receipt: Mapping[str, Any],
    *,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
) -> None:
    runtime_lock = _load_object(RUNTIME_LOCK_PATH)
    observations = receipt.get("runtime_observation_bindings")
    probe_evidence = receipt.get("path_probe_evidence")
    _require(
        receipt.get("artifact") == "m6d_w3d_runtime_validation_receipt"
        and receipt.get("version") == 1
        and receipt.get("status") == RECEIPT_STATUS
        and receipt.get("audit_ok") is True
        and receipt.get("input_manifest_binding") == _binding(input_manifest_path)
        and receipt.get("runtime_lock_binding") == _binding(RUNTIME_LOCK_PATH)
        and receipt.get("wrapper_bindings") == _validate_wrapper_contracts()
        and receipt.get("predictor_runtime_identity_sha256")
        == runtime_lock["predictor_runtime_identity_sha256"]
        and isinstance(observations, dict)
        and set(observations) == set(diagnostic.PREDICTOR_IDS)
        and all(
            isinstance(observations[predictor_id], dict)
            and observations[predictor_id].get("bytes", 0) > 0
            and _is_sha256(observations[predictor_id].get("sha256"))
            and observations[predictor_id].get("path_published") is False
            and "path" not in observations[predictor_id]
            for predictor_id in diagnostic.PREDICTOR_IDS
        )
        and receipt.get("runtime_observations_complete") == 2
        and receipt.get("prospective_input_hashes_verified") == 24
        and receipt.get("absolute_path_probes_complete") == 24
        and receipt.get("boltz_host_path_probes_complete") == 8
        and receipt.get("af2_container_path_probes_complete") == 16
        and receipt.get("af2_explicit_container_working_directory_probes") == 16
        and receipt.get("prediction_executed") is False
        and receipt.get("gpu_compute_executed") is False
        and receipt.get("scheduler_command_executed") is False
        and receipt.get("network_fetch_executed") is False
        and receipt.get("raw_host_paths_published") is False
        and receipt.get("predictor_evaluations_authorized") == 0
        and receipt.get("h100_gpu_hours_authorized") == 0.0
        and receipt.get("approval_packet_prepared") is False
        and receipt.get("no_submit") is True
        and receipt.get("cayuga_submission_allowed") is False
        and receipt.get("can_run_predictors") is False,
        "W3d no-prediction runtime receipt drifted",
    )
    _require(
        isinstance(probe_evidence, dict)
        and set(probe_evidence) == set(diagnostic.PREDICTOR_IDS),
        "W3d runtime receipt path-probe evidence is missing",
    )
    input_manifest = _load_object(input_manifest_path)
    validate_input_manifest(
        input_manifest,
        input_manifest_path=input_manifest_path,
        require_files=False,
    )
    for predictor_id in diagnostic.PREDICTOR_IDS:
        rows = probe_evidence[predictor_id]
        _require(
            isinstance(rows, list),
            f"W3d {predictor_id} receipt probe evidence must be a list",
        )
        _validate_probe_rows(rows, input_manifest, predictor_id)


def build_readiness(
    input_manifest: Mapping[str, Any],
    *,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
    runtime_receipt_path: str = RUNTIME_RECEIPT_PATH,
    project_root: PathLike = ".",
) -> Dict[str, Any]:
    validate_input_manifest(
        input_manifest,
        input_manifest_path=input_manifest_path,
        project_root=project_root,
        require_files=True,
    )
    wrapper_bindings = _validate_wrapper_contracts()
    receipt_binding: Optional[Dict[str, Any]] = None
    runtime_complete = False
    if Path(runtime_receipt_path).is_file():
        receipt = _load_object(runtime_receipt_path)
        validate_runtime_receipt(receipt, input_manifest_path=input_manifest_path)
        receipt_binding = _binding(runtime_receipt_path)
        runtime_complete = True
    status = (
        READINESS_COMPLETE_STATUS if runtime_complete else READINESS_PENDING_STATUS
    )
    next_action = (
        "Prepare a separate hash-bound W3d compute approval packet for exactly 24 "
        "prospective evaluations; do not submit prediction work yet."
        if runtime_complete
        else "Run hpc/validate_w3d_runtime_no_prediction.sh on Cayuga with the exact "
        "Boltz 2.2.1 and ColabFold 1.6.1 runtimes, sync the redacted receipt, and "
        "stop before any compute approval packet."
    )
    return {
        "artifact": "m6d_w3d_input_runtime_readiness",
        "version": 1,
        "status": status,
        "audit_ok": True,
        "input_manifest_binding": _binding(input_manifest_path),
        "wrapper_bindings": wrapper_bindings,
        "runtime_receipt_binding": receipt_binding,
        "input_producer_implemented": True,
        "materialized_input_files": 24,
        "materialized_input_hashes_verified": 24,
        "representation_semantics_verified": 24,
        "prospective_boltz_cells": 8,
        "prospective_af2_cells": 16,
        "new_runtime_wrappers_implemented": True,
        "wrapper_static_no_prediction_validation_complete": True,
        "af2_absolute_path_contract_implemented": True,
        "af2_explicit_container_working_directory_implemented": True,
        "exact_cayuga_runtime_validation_complete": runtime_complete,
        "no_prediction_runtime_validation_complete": runtime_complete,
        "approval_packet_prepared": False,
        "execution_ready": False,
        "prediction_executed": False,
        "gpu_compute_executed": False,
        "scheduler_command_executed": False,
        "network_fetch_executed": False,
        "predictor_evaluations_authorized": 0,
        "h100_gpu_hours_authorized": 0.0,
        "target_msa_queries_authorized": 0,
        "proteinmpnn_designs": 0,
        "api_calls": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
        "repo_only_replay": (
            "Tracked manifests, wrapper hashes, and readiness replay without ignored raw "
            "inputs. Re-running semantic file validation requires the materialized input bundle."
        ),
        "claim_boundary": (
            "All 24 prospective inputs and no-prediction wrapper contracts are locally "
            "validated. No structure prediction, compute approval, or scientific outcome is recorded."
            if not runtime_complete
            else "All 24 prospective inputs and exact no-prediction runtime/path contracts are "
            "validated. No structure prediction, compute approval, or scientific outcome is recorded."
        ),
        "next_action": next_action,
    }


def validate_public_readiness(
    readiness: Mapping[str, Any],
    *,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
) -> None:
    runtime_complete = readiness.get("no_prediction_runtime_validation_complete")
    expected_status = (
        READINESS_COMPLETE_STATUS if runtime_complete else READINESS_PENDING_STATUS
    )
    receipt_binding = readiness.get("runtime_receipt_binding")
    _require(
        readiness.get("artifact") == "m6d_w3d_input_runtime_readiness"
        and readiness.get("version") == 1
        and readiness.get("status") == expected_status
        and readiness.get("audit_ok") is True
        and readiness.get("input_manifest_binding") == _binding(input_manifest_path)
        and readiness.get("wrapper_bindings") == _validate_wrapper_contracts()
        and readiness.get("input_producer_implemented") is True
        and readiness.get("materialized_input_files") == 24
        and readiness.get("materialized_input_hashes_verified") == 24
        and readiness.get("representation_semantics_verified") == 24
        and readiness.get("prospective_boltz_cells") == 8
        and readiness.get("prospective_af2_cells") == 16
        and readiness.get("new_runtime_wrappers_implemented") is True
        and readiness.get("wrapper_static_no_prediction_validation_complete") is True
        and readiness.get("af2_absolute_path_contract_implemented") is True
        and readiness.get("af2_explicit_container_working_directory_implemented")
        is True
        and readiness.get("exact_cayuga_runtime_validation_complete")
        is runtime_complete
        and readiness.get("approval_packet_prepared") is False
        and readiness.get("execution_ready") is False
        and readiness.get("prediction_executed") is False
        and readiness.get("gpu_compute_executed") is False
        and readiness.get("scheduler_command_executed") is False
        and readiness.get("network_fetch_executed") is False
        and readiness.get("predictor_evaluations_authorized") == 0
        and readiness.get("h100_gpu_hours_authorized") == 0.0
        and readiness.get("no_submit") is True
        and readiness.get("cayuga_submission_allowed") is False,
        "W3d public input/runtime readiness drifted",
    )
    if runtime_complete:
        _require(
            isinstance(receipt_binding, dict)
            and receipt_binding.get("path") == RUNTIME_RECEIPT_PATH
            and receipt_binding == _binding(RUNTIME_RECEIPT_PATH),
            "W3d runtime receipt binding is missing or drifted",
        )
        validate_runtime_receipt(
            _load_object(RUNTIME_RECEIPT_PATH),
            input_manifest_path=input_manifest_path,
        )
    else:
        _require(receipt_binding is None, "W3d pending readiness binds a runtime receipt")


def render_readiness_markdown(readiness: Mapping[str, Any]) -> str:
    return "\n".join([
        "# M6d W3d Input and Runtime Readiness",
        "",
        f"Status: `{readiness['status']}`.",
        "",
        f"Materialized inputs verified: `{readiness['materialized_input_hashes_verified']}/24`.",
        f"Representation semantics verified: `{readiness['representation_semantics_verified']}/24`.",
        f"Runtime wrappers implemented: `{readiness['new_runtime_wrappers_implemented']}`.",
        f"Static no-prediction validation: `{readiness['wrapper_static_no_prediction_validation_complete']}`.",
        f"Exact Cayuga runtime validation: `{readiness['exact_cayuga_runtime_validation_complete']}`.",
        f"Execution ready: `{readiness['execution_ready']}`.",
        f"Predictor evaluations authorized: `{readiness['predictor_evaluations_authorized']}`.",
        f"H100 GPU-hours authorized: `{readiness['h100_gpu_hours_authorized']}`.",
        f"Prediction executed: `{readiness['prediction_executed']}`.",
        "",
        f"Claim boundary: {readiness['claim_boundary']}",
        "",
        f"Next action: {readiness['next_action']}",
        "",
    ])


def prepare(
    *,
    protocol_path: str = diagnostic.PROTOCOL_PATH,
    factorial_manifest_path: str = diagnostic.MANIFEST_PATH,
    input_manifest_path: str = INPUT_MANIFEST_PATH,
    readiness_path: str = READINESS_PATH,
    readiness_md_path: str = READINESS_MD_PATH,
    runtime_receipt_path: str = RUNTIME_RECEIPT_PATH,
    project_root: PathLike = ".",
) -> Dict[str, Any]:
    protocol = _load_object(protocol_path)
    factorial_manifest = _load_object(factorial_manifest_path)
    input_manifest = build_input_manifest(
        protocol,
        factorial_manifest,
        _context_map(),
        protocol_path=protocol_path,
        factorial_manifest_path=factorial_manifest_path,
        project_root=project_root,
        materialize=True,
    )
    _write_json_idempotent(input_manifest_path, input_manifest)
    validate_input_manifest(
        input_manifest,
        input_manifest_path=input_manifest_path,
        protocol_path=protocol_path,
        factorial_manifest_path=factorial_manifest_path,
        project_root=project_root,
        require_files=True,
    )
    readiness = build_readiness(
        input_manifest,
        input_manifest_path=input_manifest_path,
        runtime_receipt_path=runtime_receipt_path,
        project_root=project_root,
    )
    _write_json_idempotent(readiness_path, readiness)
    _write_text_idempotent(readiness_md_path, render_readiness_markdown(readiness))
    return readiness


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--protocol", default=diagnostic.PROTOCOL_PATH)
    prepare_parser.add_argument("--factorial-manifest", default=diagnostic.MANIFEST_PATH)
    prepare_parser.add_argument("--input-manifest", default=INPUT_MANIFEST_PATH)
    prepare_parser.add_argument("--readiness", default=READINESS_PATH)
    prepare_parser.add_argument("--readiness-md", default=READINESS_MD_PATH)
    prepare_parser.add_argument("--runtime-receipt", default=RUNTIME_RECEIPT_PATH)
    prepare_parser.add_argument("--project-root", default=".")

    verify_parser = subparsers.add_parser("verify-inputs")
    verify_parser.add_argument("--input-manifest", default=INPUT_MANIFEST_PATH)
    verify_parser.add_argument("--project-root", default=".")

    emit_parser = subparsers.add_parser("emit-path-plan")
    emit_parser.add_argument("--input-manifest", default=INPUT_MANIFEST_PATH)
    emit_parser.add_argument("--project-root", default=".")
    emit_parser.add_argument("--predictor-id", choices=diagnostic.PREDICTOR_IDS, required=True)

    probe_parser = subparsers.add_parser("probe-host-paths")
    probe_parser.add_argument("--path-plan", required=True)
    probe_parser.add_argument("--out", required=True)

    receipt_parser = subparsers.add_parser("runtime-receipt")
    receipt_parser.add_argument("--input-manifest", default=INPUT_MANIFEST_PATH)
    receipt_parser.add_argument("--project-root", default=".")
    receipt_parser.add_argument("--boltz-observation", required=True)
    receipt_parser.add_argument("--af2-observation", required=True)
    receipt_parser.add_argument("--boltz-probes", required=True)
    receipt_parser.add_argument("--af2-probes", required=True)
    receipt_parser.add_argument("--out", default=RUNTIME_RECEIPT_PATH)

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "prepare":
        readiness = prepare(
            protocol_path=args.protocol,
            factorial_manifest_path=args.factorial_manifest,
            input_manifest_path=args.input_manifest,
            readiness_path=args.readiness,
            readiness_md_path=args.readiness_md,
            runtime_receipt_path=args.runtime_receipt,
            project_root=args.project_root,
        )
        print(json.dumps({
            "status": readiness["status"],
            "materialized_input_files": readiness["materialized_input_files"],
            "prediction_executed": readiness["prediction_executed"],
            "execution_ready": readiness["execution_ready"],
        }, sort_keys=True))
        return 0
    if args.command == "probe-host-paths":
        probes = probe_host_paths(_load_jsonl(args.path_plan))
        _write_text_idempotent(
            args.out,
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in probes),
        )
        print(f"W3d host path probes complete: {len(probes)}")
        return 0
    input_manifest = _load_object(args.input_manifest)
    if args.command == "verify-inputs":
        validate_input_manifest(
            input_manifest,
            input_manifest_path=args.input_manifest,
            project_root=args.project_root,
            require_files=True,
        )
        print("W3d prospective inputs verified: 24/24; no prediction")
        return 0
    if args.command == "emit-path-plan":
        for row in emit_path_plan(
            input_manifest,
            args.predictor_id,
            project_root=args.project_root,
        ):
            print(json.dumps(row, sort_keys=True))
        return 0
    receipt = build_runtime_receipt(
        input_manifest,
        boltz_observation_path=args.boltz_observation,
        af2_observation_path=args.af2_observation,
        boltz_probe_path=args.boltz_probes,
        af2_probe_path=args.af2_probes,
        input_manifest_path=args.input_manifest,
        project_root=args.project_root,
    )
    _write_json_idempotent(args.out, receipt)
    print("W3d exact runtime and absolute-path validation complete: no prediction")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
