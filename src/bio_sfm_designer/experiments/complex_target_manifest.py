"""Validate a multi-target heterodimer manifest for M6c scale-up.

The manifest is deliberately small JSON: a list of target entries that point to
prepared two-chain PDBs, target MSAs, and optional downstream records. This gives
multi-target validation a reproducible bookkeeping layer before any expensive
ProteinMPNN/Boltz work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from typing import Any, Dict, Iterable, List, Optional


_REQUIRED_TARGET_FIELDS = ("id", "prepared_pdb", "target_chain", "binder_chain", "target_fasta", "target_msa")


def _failure(target_id: Optional[str], kind: str, message: str, *,
             field: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"target_id": target_id, "kind": kind, "message": message}
    if field is not None:
        out["field"] = field
    return out


def _bad_manifest(path: str, kind: str, message: str) -> Dict[str, Any]:
    failure = _failure(None, kind, message)
    return {"ok": False, "manifest": os.path.abspath(path), "n_targets": 0, "n_ready_targets": 0,
            "ready_targets": [], "failures": [failure], "failures_by_kind": {kind: 1}}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _allow_numbering_gaps(target: Dict[str, Any]) -> bool:
    return target.get("allow_numbering_gaps") is True


def _check_file(path: str, target_id: str, field: str, require_files: bool) -> List[Dict[str, Any]]:
    if not require_files:
        return []
    if not os.path.exists(path):
        return [_failure(target_id, "missing_file", f"{field} does not exist: {path}", field=field)]
    if os.path.isfile(path) and os.path.getsize(path) == 0:
        return [_failure(target_id, "empty_file", f"{field} is empty: {path}", field=field)]
    return []


def _read_first_sequence(path: str, *, a3m: bool = False) -> str:
    seq: List[str] = []
    in_record = False
    with open(path) as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            if text.startswith(">"):
                if in_record:
                    break
                in_record = True
                continue
            if not in_record and not seq:
                in_record = True
            if in_record:
                seq.append(text)
    joined = "".join(seq)
    if a3m:
        return "".join(ch for ch in joined if ch.isupper() and ch != "-")
    return "".join(ch.upper() for ch in joined if ch.isalpha())


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _path_matches_or_verified_by_sha(report_path: Any, artifact_path: Any, report_sha256: Any) -> bool:
    if not _is_nonempty_str(report_path) or not _is_nonempty_str(artifact_path):
        return False
    if os.path.abspath(str(report_path)) == os.path.abspath(str(artifact_path)):
        return True
    if not _is_nonempty_str(report_sha256) or not os.path.exists(str(artifact_path)):
        return False
    try:
        return str(report_sha256) == _sha256_file(str(artifact_path))
    except OSError:
        return False


def _check_target_sequence_files(target: dict, require_files: bool) -> List[Dict[str, Any]]:
    if not require_files:
        return []
    target_id = str(target.get("id"))
    fasta = target.get("target_fasta")
    msa = target.get("target_msa")
    if not _is_nonempty_str(fasta) or not _is_nonempty_str(msa):
        return []
    if not os.path.exists(fasta) or not os.path.exists(msa):
        return []

    try:
        fasta_seq = _read_first_sequence(fasta)
        msa_query = _read_first_sequence(msa, a3m=True)
    except OSError as exc:
        return [_failure(target_id, "bad_sequence_file", f"cannot read target FASTA/MSA: {exc}")]
    if not fasta_seq:
        return [_failure(target_id, "empty_sequence", f"target_fasta has no sequence: {fasta}")]
    if not msa_query:
        return [_failure(target_id, "empty_sequence", f"target_msa has no query sequence: {msa}")]
    if fasta_seq != msa_query:
        return [_failure(
            target_id,
            "target_msa_mismatch",
            f"target_msa query sequence does not match target_fasta ({len(msa_query)} aa vs {len(fasta_seq)} aa)",
        )]
    return []


def _check_target_msa_report(path: str, target: dict, require_files: bool) -> List[Dict[str, Any]]:
    if not path:
        return []
    target_id = str(target.get("id"))
    if not os.path.exists(path):
        return [_failure(
            target_id,
            "missing_file",
            f"target_msa_report does not exist: {path}",
            field="target_msa_report",
        )] if require_files else []
    try:
        with open(path) as fh:
            rep = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [_failure(target_id, "bad_target_msa_report",
                         f"cannot read target_msa_report {path}: {exc}",
                         field="target_msa_report")]
    if not isinstance(rep, dict):
        return [_failure(target_id, "bad_target_msa_report",
                         "target_msa_report must be a JSON object",
                         field="target_msa_report")]
    failures = []
    if rep.get("ok") is not True:
        failures.append(_failure(target_id, "target_msa_report_not_ok",
                                 f"target_msa_report ok={rep.get('ok')!r}",
                                 field="target_msa_report"))
    target_msa = target.get("target_msa")
    if _is_nonempty_str(target_msa):
        if not _is_nonempty_str(rep.get("out")):
            failures.append(_failure(target_id, "target_msa_report_missing_field",
                                     "target_msa_report missing non-empty out",
                                     field="target_msa_report"))
        elif not _path_matches_or_verified_by_sha(rep["out"], target_msa, rep.get("out_sha256")):
            failures.append(_failure(target_id, "target_msa_report_mismatch",
                                     "target_msa_report out differs from target_msa",
                                     field="target_msa_report"))
        if not _is_nonempty_str(rep.get("out_sha256")):
            failures.append(_failure(target_id, "target_msa_report_missing_field",
                                     "target_msa_report missing non-empty out_sha256",
                                     field="target_msa_report"))
        elif os.path.exists(str(target_msa)):
            try:
                actual = _sha256_file(str(target_msa))
            except OSError as exc:
                return [_failure(target_id, "bad_sequence_file", f"cannot hash target MSA: {exc}")]
            if str(rep["out_sha256"]) != actual:
                failures.append(_failure(target_id, "target_msa_report_mismatch",
                                         "target_msa_report out_sha256 differs from target_msa",
                                         field="target_msa_report"))
    target_fasta = target.get("target_fasta")
    if _is_nonempty_str(target_fasta):
        if not _is_nonempty_str(rep.get("fasta")):
            failures.append(_failure(target_id, "target_msa_report_missing_field",
                                     "target_msa_report missing non-empty fasta",
                                     field="target_msa_report"))
        elif not _path_matches_or_verified_by_sha(rep["fasta"], target_fasta, rep.get("fasta_sha256")):
            failures.append(_failure(target_id, "target_msa_report_mismatch",
                                     "target_msa_report fasta differs from target_fasta",
                                     field="target_msa_report"))
        if not _is_nonempty_str(rep.get("fasta_sha256")):
            failures.append(_failure(target_id, "target_msa_report_missing_field",
                                     "target_msa_report missing non-empty fasta_sha256",
                                     field="target_msa_report"))
        elif os.path.exists(str(target_fasta)):
            try:
                actual = _sha256_file(str(target_fasta))
            except OSError as exc:
                return [_failure(target_id, "bad_sequence_file", f"cannot hash target FASTA: {exc}")]
            if str(rep["fasta_sha256"]) != actual:
                failures.append(_failure(target_id, "target_msa_report_mismatch",
                                         "target_msa_report fasta_sha256 differs from target_fasta",
                                         field="target_msa_report"))
    if _is_nonempty_str(target_fasta) and os.path.exists(str(target_fasta)):
        try:
            fasta_seq = _read_first_sequence(str(target_fasta))
        except OSError as exc:
            return [_failure(target_id, "bad_sequence_file", f"cannot read target FASTA: {exc}")]
        if not isinstance(rep.get("sequence_length"), int):
            failures.append(_failure(target_id, "target_msa_report_missing_field",
                                     "target_msa_report missing integer sequence_length",
                                     field="target_msa_report"))
        elif rep["sequence_length"] != len(fasta_seq):
            failures.append(_failure(
                target_id,
                "target_msa_report_mismatch",
                f"target_msa_report sequence_length={rep['sequence_length']} differs from target_fasta length={len(fasta_seq)}",
                field="target_msa_report",
            ))
    return failures


def _check_target_fasta_report(path: str, target: dict, require_files: bool) -> List[Dict[str, Any]]:
    if not path:
        return []
    target_id = str(target.get("id"))
    field = "target_fasta_report"
    if not os.path.exists(path):
        return [_failure(
            target_id,
            "missing_file",
            f"{field} does not exist: {path}",
            field=field,
        )] if require_files else []
    try:
        with open(path) as fh:
            rep = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [_failure(target_id, "bad_target_fasta_report",
                         f"cannot read {field} {path}: {exc}",
                         field=field)]
    if not isinstance(rep, dict):
        return [_failure(target_id, "bad_target_fasta_report",
                         "target_fasta_report must be a JSON object",
                         field=field)]
    failures = []
    prepared_pdb = target.get("prepared_pdb")
    if _is_nonempty_str(prepared_pdb):
        if not _is_nonempty_str(rep.get("pdb")):
            failures.append(_failure(target_id, "target_fasta_report_missing_field",
                                     "target_fasta_report missing non-empty pdb",
                                     field=field))
        elif not _path_matches_or_verified_by_sha(rep["pdb"], prepared_pdb, rep.get("pdb_sha256")):
            failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                     "target_fasta_report pdb differs from prepared_pdb",
                                     field=field))
        if not _is_nonempty_str(rep.get("pdb_sha256")):
            failures.append(_failure(target_id, "target_fasta_report_missing_field",
                                     "target_fasta_report missing non-empty pdb_sha256",
                                     field=field))
        elif os.path.exists(str(prepared_pdb)):
            try:
                actual = _sha256_file(str(prepared_pdb))
            except OSError as exc:
                return [_failure(target_id, "bad_sequence_file", f"cannot hash prepared_pdb: {exc}")]
            if str(rep["pdb_sha256"]) != actual:
                failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                         "target_fasta_report pdb_sha256 differs from prepared_pdb",
                                         field=field))
    target_chain = target.get("target_chain")
    if _is_nonempty_str(target_chain):
        if rep.get("chain") != target_chain:
            failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                     "target_fasta_report chain differs from target_chain",
                                     field=field))
    target_fasta = target.get("target_fasta")
    fasta_seq: Optional[str] = None
    if _is_nonempty_str(target_fasta):
        if not _is_nonempty_str(rep.get("out")):
            failures.append(_failure(target_id, "target_fasta_report_missing_field",
                                     "target_fasta_report missing non-empty out",
                                     field=field))
        elif not _path_matches_or_verified_by_sha(rep["out"], target_fasta, rep.get("out_sha256")):
            failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                     "target_fasta_report out differs from target_fasta",
                                     field=field))
        if not _is_nonempty_str(rep.get("out_sha256")):
            failures.append(_failure(target_id, "target_fasta_report_missing_field",
                                     "target_fasta_report missing non-empty out_sha256",
                                     field=field))
        elif os.path.exists(str(target_fasta)):
            try:
                actual = _sha256_file(str(target_fasta))
            except OSError as exc:
                return [_failure(target_id, "bad_sequence_file", f"cannot hash target_fasta: {exc}")]
            if str(rep["out_sha256"]) != actual:
                failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                         "target_fasta_report out_sha256 differs from target_fasta",
                                         field=field))
        if os.path.exists(str(target_fasta)):
            try:
                fasta_seq = _read_first_sequence(str(target_fasta))
            except OSError as exc:
                return [_failure(target_id, "bad_sequence_file", f"cannot read target FASTA: {exc}")]
    if fasta_seq is not None:
        if not isinstance(rep.get("length"), int):
            failures.append(_failure(target_id, "target_fasta_report_missing_field",
                                     "target_fasta_report missing integer length",
                                     field=field))
        elif rep["length"] != len(fasta_seq):
            failures.append(_failure(
                target_id,
                "target_fasta_report_mismatch",
                f"target_fasta_report length={rep['length']} differs from target_fasta length={len(fasta_seq)}",
                field=field,
            ))
        if rep.get("sequence") != fasta_seq:
            failures.append(_failure(target_id, "target_fasta_report_mismatch",
                                     "target_fasta_report sequence differs from target_fasta",
                                     field=field))
    return failures


def _target_fasta_report_path(target: Dict[str, Any], require_files: bool) -> Optional[str]:
    declared = target.get("target_fasta_report")
    if _is_nonempty_str(declared):
        return str(declared)
    target_fasta = target.get("target_fasta")
    if require_files and _is_nonempty_str(target_fasta):
        return str(target_fasta) + ".report.json"
    return None


def _target_msa_report_path(target: Dict[str, Any], require_files: bool) -> Optional[str]:
    declared = target.get("target_msa_report")
    if _is_nonempty_str(declared):
        return str(declared)
    target_msa = target.get("target_msa")
    if require_files and _is_nonempty_str(target_msa):
        return str(target_msa) + ".report.json"
    return None


def _check_prep_report(path: str, target: dict, require_files: bool,
                       min_contacts: int) -> List[Dict[str, Any]]:
    target_id = str(target.get("id"))
    if not path:
        return []
    if not os.path.exists(path):
        return [_failure(
            target_id,
            "missing_file",
            f"prep_report does not exist: {path}",
            field="prep_report",
        )] if require_files else []
    try:
        with open(path) as fh:
            rep = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [_failure(target_id, "bad_prep_report", f"cannot read prep_report {path}: {exc}")]
    if not isinstance(rep, dict):
        return [_failure(target_id, "bad_prep_report", "prep_report must be a JSON object")]
    failures = []
    if rep.get("target_chain") != target.get("target_chain"):
        failures.append(_failure(target_id, "prep_report_mismatch", "target_chain differs from prep report"))
    if rep.get("binder_chain") != target.get("binder_chain"):
        failures.append(_failure(target_id, "prep_report_mismatch", "binder_chain differs from prep report"))
    allow_numbering_gaps = _allow_numbering_gaps(target)
    if rep.get("target_numbering_gaps") and not allow_numbering_gaps:
        failures.append(_failure(target_id, "prep_report_gap", "target_numbering_gaps is non-empty"))
    if rep.get("binder_numbering_gaps") and not allow_numbering_gaps:
        failures.append(_failure(target_id, "prep_report_gap", "binder_numbering_gaps is non-empty"))
    contacts = rep.get("ca_interface_contacts")
    if not isinstance(contacts, int) or contacts < min_contacts:
        failures.append(_failure(target_id, "prep_report_contacts",
                                 f"ca_interface_contacts={contacts!r} below {min_contacts}"))
    return failures


def _env_assign(**values: str) -> str:
    return " ".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def _shell_token(text: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(text).upper()).strip("_")
    if not token:
        token = "TARGET"
    if token[0].isdigit():
        token = f"T_{token}"
    return token


def _target_setting(manifest: Dict[str, Any], target: Dict[str, Any],
                    field: str, default: Any) -> str:
    defaults = manifest.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    value = target.get(field, defaults.get(field, default))
    return str(value)


def _rcsb_id(target: Dict[str, Any]) -> Optional[str]:
    value = target.get("rcsb_id")
    if not _is_nonempty_str(value):
        return None
    token = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", token):
        return None
    return token


def _mkdir_line(paths: Iterable[str]) -> str:
    dirs = []
    seen = set()
    for path in paths:
        if not _is_nonempty_str(path):
            continue
        d = os.path.dirname(str(path)) or "."
        if d not in seen:
            dirs.append(d)
            seen.add(d)
    if not dirs:
        dirs = ["."]
    return "mkdir -p " + " ".join(shlex.quote(d) for d in dirs)


def _input_prep_artifacts(target: Dict[str, Any]) -> List[Dict[str, str]]:
    artifacts: List[Dict[str, str]] = []
    target_id = str(target.get("id", "target"))

    def add(field: str, value: Any) -> None:
        if _is_nonempty_str(value):
            artifacts.append({"target_id": target_id, "field": field, "path": str(value)})

    add("source_pdb", target.get("source_pdb"))
    prepared_pdb = target.get("prepared_pdb")
    add("prepared_pdb", prepared_pdb)
    if _is_nonempty_str(prepared_pdb):
        add("prep_report", target.get("prep_report", str(prepared_pdb) + ".report.json"))
    target_fasta = target.get("target_fasta")
    add("target_fasta", target_fasta)
    if _is_nonempty_str(target_fasta):
        add("target_fasta_report", target.get("target_fasta_report", str(target_fasta) + ".report.json"))
    target_msa = target.get("target_msa")
    add("target_msa", target_msa)
    if _is_nonempty_str(target_msa):
        add("target_msa_report", target.get("target_msa_report", str(target_msa) + ".report.json"))
    return artifacts


def validate_manifest(path: str, *, require_files: bool = False, min_targets: int = 1,
                      min_contacts: int = 1,
                      target_ids: Optional[Iterable[str]] = None,
                      require_records: bool = False) -> Dict[str, Any]:
    try:
        with open(path) as fh:
            manifest = json.load(fh)
    except OSError as exc:
        return _bad_manifest(path, "missing_manifest", str(exc))
    except json.JSONDecodeError as exc:
        return _bad_manifest(path, "bad_manifest_json", str(exc))
    failures: List[Dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return _bad_manifest(path, "bad_manifest", "manifest must be a JSON object")
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        return _bad_manifest(path, "bad_manifest", "targets must be a list")
    selected_ids = set(str(t) for t in target_ids) if target_ids is not None else None
    if selected_ids is not None:
        targets = [t for t in targets if isinstance(t, dict) and str(t.get("id")) in selected_ids]
        missing_selected = selected_ids - {str(t.get("id")) for t in targets}
    else:
        missing_selected = set()
    if len(targets) < min_targets:
        failures.append(_failure(None, "too_few_targets", f"{len(targets)} targets < required {min_targets}"))
    for missing in sorted(missing_selected):
        failures.append(_failure(missing, "missing_target", "requested target id is not present in manifest"))

    seen = set()
    ready = []
    input_prep_artifacts: List[Dict[str, str]] = []
    for i, target in enumerate(targets):
        if not isinstance(target, dict):
            failures.append(_failure(None, "bad_target", f"targets[{i}] must be an object"))
            continue
        target_id = str(target.get("id")) if target.get("id") is not None else None
        if not _is_nonempty_str(target_id):
            failures.append(_failure(None, "missing_field", f"targets[{i}] missing id"))
            continue
        if target_id in seen:
            failures.append(_failure(target_id, "duplicate_target", "duplicate target id"))
        seen.add(target_id)
        input_prep_artifacts.extend(_input_prep_artifacts(target))

        for field in _REQUIRED_TARGET_FIELDS:
            if not _is_nonempty_str(target.get(field)):
                failures.append(_failure(target_id, "missing_field", f"missing {field}"))
        if target.get("target_chain") == target.get("binder_chain"):
            failures.append(_failure(target_id, "bad_chains", "target_chain and binder_chain must differ"))
        if _is_nonempty_str(target.get("rcsb_id")) and _rcsb_id(target) is None:
            failures.append(_failure(target_id, "bad_rcsb_id", "rcsb_id must be a 4-character RCSB/PDB id"))
        if "allow_numbering_gaps" in target and not isinstance(target.get("allow_numbering_gaps"), bool):
            failures.append(_failure(target_id, "bad_allow_numbering_gaps",
                                     "allow_numbering_gaps must be boolean when present"))

        for field in ("source_pdb", "prepared_pdb", "target_fasta", "target_msa"):
            value = target.get(field)
            if _is_nonempty_str(value):
                failures.extend(_check_file(value, target_id, field, require_files))
        if require_records:
            value = target.get("records")
            if _is_nonempty_str(value):
                failures.extend(_check_file(value, target_id, "records", require_files))
        failures.extend(_check_target_sequence_files(target, require_files))
        target_fasta_report = _target_fasta_report_path(target, require_files)
        if target_fasta_report is not None:
            failures.extend(_check_target_fasta_report(target_fasta_report, target, require_files))
        prep_report = target.get("prep_report")
        if _is_nonempty_str(prep_report):
            failures.extend(_check_prep_report(prep_report, target, require_files, min_contacts))
        target_msa_report = _target_msa_report_path(target, require_files)
        if target_msa_report is not None:
            failures.extend(_check_target_msa_report(target_msa_report, target, require_files))

        if not any(f["target_id"] == target_id for f in failures):
            ready.append(target_id)

    by_kind: Dict[str, int] = {}
    for f in failures:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {
        "ok": not failures,
        "manifest": os.path.abspath(path),
        "n_targets": len(targets),
        "n_ready_targets": len(ready),
        "ready_targets": ready,
        "min_targets": min_targets,
        "min_contacts": min_contacts,
        "require_files": require_files,
        "require_records": require_records,
        "target_ids": sorted(selected_ids) if selected_ids is not None else None,
        "input_prep_artifacts": input_prep_artifacts,
        "failures_by_kind": by_kind,
        "failures": failures,
    }


def render_hpc_plan(report: Dict[str, Any], manifest_path: str, *,
                    msa_plan_path: Optional[str] = None) -> str:
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    lines = [
        "# M6c multi-target command plan",
        "# Review paths, MSA files, and SLURM resources before submitting.",
        "# After records sync back, run complex_panel_completion before complex_panel_report.",
        "set -euo pipefail",
        "PYTHON_BIN=\"${BIO_SFM_PYTHON:-${ENV_PY:-python3}}\"",
        "",
    ]
    if report.get("require_files"):
        preflight_args = [
            "-m",
            "bio_sfm_designer.experiments.complex_target_manifest",
            "--manifest", manifest_path,
            "--require-files",
            "--min-targets", str(report.get("min_targets", 1)),
            "--min-contacts", str(report.get("min_contacts", 1)),
        ]
        if report.get("require_records"):
            preflight_args.append("--require-records")
        target_ids = report.get("target_ids")
        if isinstance(target_ids, list):
            for target_id in target_ids:
                preflight_args.extend(["--target-id", str(target_id)])
        lines.extend([
            "# Re-run manifest file/report preflight at execution time before any sbatch.",
            "\"$PYTHON_BIN\" " + shlex.join(preflight_args),
            "",
        ])
    if not report.get("ok") or not report.get("ready_targets"):
        lines.extend([
            "# submission blocked: manifest preflight is not ready.",
            "# no sbatch submission commands emitted from this plan.",
        ])
        failures = report.get("failures")
        if isinstance(failures, list) and failures:
            fields = {f.get("field") for f in failures if isinstance(f, dict)}
            if fields & {"target_fasta_report", "target_msa", "target_msa_report"}:
                msa_plan_hint = (
                    f"# expected MSA plan: {shlex.quote(str(msa_plan_path))}"
                    if msa_plan_path else
                    "# generate one with: --emit-msa-plan <target_msa_plan.sh>"
                )
                lines.extend([
                    "# input prep: run the emitted target_msa_precompute plan first,",
                    "# then rerun this manifest with --require-files to emit sbatch commands.",
                    msa_plan_hint,
                ])
            lines.append("# blockers:")
            for failure in failures[:20]:
                if not isinstance(failure, dict):
                    continue
                field = f" field={failure['field']}" if failure.get("field") is not None else ""
                lines.append(
                    f"# - {failure.get('kind')} target={failure.get('target_id')}{field} -- "
                    f"{failure.get('message')}"
                )
        lines.append("")
    for index, target in enumerate(manifest.get("targets", [])):
        target_id = target.get("id", "target")
        if target_id not in set(report.get("ready_targets", [])):
            continue
        out_prefix = target.get("out_prefix", f"hpc_outputs/{target_id}")
        target_fasta = target.get("target_fasta", f"{out_prefix}/target_{target['target_chain']}.fasta")
        target_fasta_report = target.get("target_fasta_report", str(target_fasta) + ".report.json")
        candidates = target.get("candidates", f"{out_prefix}/candidates_proteinmpnn_complex.jsonl")
        records = target.get("records", f"{out_prefix}/records_boltz_complex.jsonl")
        generate_job_var = f"GEN_{index:02d}_{_shell_token(target_id)}"
        predict_job_var = f"PRED_{index:02d}_{_shell_token(target_id)}"
        num_seq = _target_setting(manifest, target, "num_seq", 40)
        temp = _target_setting(manifest, target, "temp", 0.3)
        seed = _target_setting(manifest, target, "seed", 37)
        objective = _target_setting(manifest, target, "objective", "binder")
        missing_msa_msg = (
            f"Missing target MSA: {target['target_msa']} "
            f"(generate once: FASTA={target_fasta} OUT={target['target_msa']} "
            "sbatch hpc/run_precompute_boltz_target_msa.sbatch)"
        )
        lines.extend([
            f"# {target_id}",
            f"mkdir -p {shlex.quote(out_prefix)}",
            f"\"$PYTHON_BIN\" hpc/extract_chain_fasta.py --pdb {shlex.quote(target['prepared_pdb'])} "
            f"--chain {shlex.quote(target['target_chain'])} --id {shlex.quote(str(target_id) + '_' + target['target_chain'])} "
            f"--out {shlex.quote(target_fasta)} --report {shlex.quote(str(target_fasta_report))}",
            f"test -s {shlex.quote(target['target_msa'])} || "
            f"{{ echo {shlex.quote(missing_msa_msg)} >&2; exit 2; }}",
            f"{generate_job_var}=$("
            + _env_assign(
                PDB=target["prepared_pdb"],
                TARGET_CHAIN=target["target_chain"],
                DESIGN_CHAIN=target["binder_chain"],
                NUM_SEQ=num_seq,
                TEMP=temp,
                SEED=seed,
                OBJECTIVE=objective,
                COMPLEX_ID=str(target_id),
                OUT=candidates,
            )
            + " sbatch --parsable hpc/run_generate_proteinmpnn_complex.sbatch)",
            f"echo {shlex.quote('submitted ProteinMPNN job for ' + str(target_id) + ': ')}\"${{{generate_job_var}}}\"",
            f"{predict_job_var}=$("
            + _env_assign(
                CANDIDATES=candidates,
                BACKBONE=target["prepared_pdb"],
                TARGET_CHAIN=target["target_chain"],
                BINDER_CHAIN=target["binder_chain"],
                COMPLEX_ID=str(target_id),
                TARGET_MSA=target["target_msa"],
                OUT=records,
            )
            + f" sbatch --dependency=afterok:${{{generate_job_var}}} "
            + "--parsable hpc/run_predict_boltz_complex.sbatch)",
            f"echo {shlex.quote('submitted Boltz job for ' + str(target_id) + ': ')}\"${{{predict_job_var}}}\"",
            "",
        ])
    return "\n".join(lines)


def render_target_msa_plan(manifest_path: str, *,
                           target_ids: Optional[Iterable[str]] = None,
                           rerun_command: Optional[str] = None,
                           workstream: Optional[str] = None) -> str:
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    manifest_sha256 = _sha256_file(manifest_path)
    selected_ids = set(str(t) for t in target_ids) if target_ids is not None else None
    dry_run_target_ids = [
        str(target.get("id", f"target_{index}"))
        for index, target in enumerate(manifest.get("targets", []))
        if isinstance(target, dict)
        and (selected_ids is None or str(target.get("id", f"target_{index}")) in selected_ids)
        and all(_is_nonempty_str(target.get(field)) for field in ("prepared_pdb", "target_chain", "target_fasta", "target_msa"))
    ]
    lines = [
        "# M6c target-MSA precompute plan",
        "# Run this before --require-files panel/scale readiness when target .a3m/report files are missing or stale.",
        "set -euo pipefail",
        "PYTHON_BIN=\"${BIO_SFM_PYTHON:-${ENV_PY:-python3}}\"",
        "",
        "# Optional: set TARGET_MSA_PRECOMPUTE_RECEIPT to append submitted/reused targets as JSONL.",
        "if [ -n \"${TARGET_MSA_PRECOMPUTE_RECEIPT:-}\" ]; then",
        "  mkdir -p \"$(dirname \"$TARGET_MSA_PRECOMPUTE_RECEIPT\")\"",
        "fi",
        f"TARGET_MSA_PRECOMPUTE_MANIFEST={shlex.quote(str(manifest_path))}",
        "export TARGET_MSA_PRECOMPUTE_MANIFEST",
        f"TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED={shlex.quote(manifest_sha256)}",
        "export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED",
        "if [ ! -f \"$TARGET_MSA_PRECOMPUTE_MANIFEST\" ]; then",
        "  echo \"target-MSA precompute manifest is missing: $TARGET_MSA_PRECOMPUTE_MANIFEST\" >&2",
        "  exit 2",
        "fi",
        "TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL=$(\"$PYTHON_BIN\" - <<'PY'",
        "import hashlib, os, pathlib",
        "path = pathlib.Path(os.environ[\"TARGET_MSA_PRECOMPUTE_MANIFEST\"])",
        "print(hashlib.sha256(path.read_bytes()).hexdigest())",
        "PY",
        ")",
        "if [ \"$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL\" != \"$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED\" ]; then",
        "  echo \"target-MSA precompute manifest is stale: $TARGET_MSA_PRECOMPUTE_MANIFEST expected_sha256=$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED actual_sha256=$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL\" >&2",
        "  exit 2",
        "fi",
        "TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256=\"$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED\"",
        "export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256",
        f"TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS={shlex.quote(json.dumps(dry_run_target_ids, sort_keys=True))}",
        "export TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS",
        "if [ \"${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}\" = \"1\" ]; then",
        "  echo \"target-MSA precompute dry-run: manifest fresh; no scheduler jobs submitted; receipt untouched.\"",
        "  \"$PYTHON_BIN\" - <<'PY'",
        "import json, os",
        "targets = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS') or '[]')",
        "print('target-MSA precompute dry-run targets: ' + ','.join(targets))",
        "PY",
        "  exit 0",
        "fi",
        "record_target_msa_precompute() {",
        "  local target_id=\"$1\"",
        "  local status=\"$2\"",
        "  local job_id=\"$3\"",
        "  local fasta=\"$4\"",
        "  local out=\"$5\"",
        "  local report=\"$6\"",
        "  if [ -z \"${TARGET_MSA_PRECOMPUTE_RECEIPT:-}\" ]; then",
        "    return 0",
        "  fi",
        "  TARGET_ID=\"$target_id\" STATUS=\"$status\" JOB_ID=\"$job_id\" FASTA=\"$fasta\" OUT=\"$out\" REPORT=\"$report\" WORKSTREAM=\"${TARGET_MSA_PRECOMPUTE_WORKSTREAM:-}\" MANIFEST=\"${TARGET_MSA_PRECOMPUTE_MANIFEST:-}\" MANIFEST_SHA256=\"${TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256:-}\" \"$PYTHON_BIN\" - <<'PY'",
        "import json, os, time",
        "record = {",
        "    \"target_id\": os.environ[\"TARGET_ID\"],",
        "    \"status\": os.environ[\"STATUS\"],",
        "    \"job_id\": os.environ.get(\"JOB_ID\") or None,",
        "    \"target_fasta\": os.environ[\"FASTA\"],",
        "    \"target_msa\": os.environ[\"OUT\"],",
        "    \"target_msa_report\": os.environ[\"REPORT\"],",
        "    \"manifest\": os.environ.get(\"MANIFEST\") or None,",
        "    \"manifest_sha256\": os.environ.get(\"MANIFEST_SHA256\") or None,",
        "    \"workstream\": os.environ.get(\"WORKSTREAM\") or None,",
        "    \"timestamp_unix\": int(time.time()),",
        "}",
        "with open(os.environ[\"TARGET_MSA_PRECOMPUTE_RECEIPT\"], \"a\") as fh:",
        "    fh.write(json.dumps(record, sort_keys=True) + \"\\n\")",
        "PY",
        "}",
        "require_target_msa_job_id() {",
        "  local target_id=\"$1\"",
        "  local job_id=\"$2\"",
        "  if [ -z \"${job_id//[[:space:]]/}\" ]; then",
        "    echo \"target-MSA precompute sbatch returned an empty or whitespace-only job id for ${target_id}; not recording submitted receipt\" >&2",
        "    exit 2",
        "  fi",
        "  if [[ \"$job_id\" =~ [[:space:]] ]]; then",
        "    echo \"target-MSA precompute sbatch returned a non-parsable job id with whitespace for ${target_id}: ${job_id}\" >&2",
        "    exit 2",
        "  fi",
        "}",
        "validate_target_msa_precompute_receipt() {",
        "  if [ -z \"${TARGET_MSA_PRECOMPUTE_RECEIPT:-}\" ]; then",
        "    return 0",
        "  fi",
        "  local expected_json=\"{}\"",
        "  if [ \"${1:-}\" = \"--expect-json\" ]; then",
        "    if [ \"$#\" -lt 2 ]; then",
        "      echo \"validate_target_msa_precompute_receipt missing JSON after --expect-json\" >&2",
        "      exit 2",
        "    fi",
        "    expected_json=\"$2\"",
        "    shift 2",
        "  fi",
        "  TARGET_MSA_PRECOMPUTE_EXPECTED_JSON=\"$expected_json\" \"$PYTHON_BIN\" - \"$TARGET_MSA_PRECOMPUTE_RECEIPT\" \"$@\" <<'PY'",
        "import json, os, pathlib, sys",
        "receipt = pathlib.Path(sys.argv[1])",
        "expected = [str(target_id) for target_id in sys.argv[2:]]",
        "if not expected:",
        "    raise SystemExit(0)",
        "bad = []",
        "try:",
        "    expected_specs = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_EXPECTED_JSON') or '{}')",
        "except json.JSONDecodeError as exc:",
        "    expected_specs = {}",
        "    bad.append(f'invalid expected receipt JSON: {exc}')",
        "if not isinstance(expected_specs, dict):",
        "    expected_specs = {}",
        "    bad.append('expected receipt JSON must be an object')",
        "if not receipt.exists() or receipt.stat().st_size <= 0:",
        "    bad.append(f'receipt is missing or empty: {receipt}')",
        "records = []",
        "if receipt.exists():",
        "    with receipt.open() as fh:",
        "        for lineno, line in enumerate(fh, 1):",
        "            text = line.strip()",
        "            if not text:",
        "                continue",
        "            try:",
        "                record = json.loads(text)",
        "            except json.JSONDecodeError as exc:",
        "                bad.append(f'line {lineno}: invalid JSON: {exc}')",
        "                continue",
        "            if not isinstance(record, dict):",
        "                bad.append(f'line {lineno}: receipt record is not an object')",
        "                continue",
        "            records.append((lineno, record))",
        "expected_set = set(expected)",
        "by_expected = {target_id: [] for target_id in expected}",
        "seen_unexpected = set()",
        "accepted_statuses = {'submitted', 'validated_existing'}",
        "for lineno, record in records:",
        "    target_id = str(record.get('target_id') or '')",
        "    if target_id in expected_set:",
        "        by_expected[target_id].append((lineno, record))",
        "    elif target_id:",
        "        seen_unexpected.add(target_id)",
        "for target_id in expected:",
        "    rows = by_expected[target_id]",
        "    if not rows:",
        "        bad.append(f'missing expected target_id={target_id}')",
        "        continue",
        "    if len(rows) > 1:",
        "        lines = ','.join(str(lineno) for lineno, _record in rows)",
        "        bad.append(f'duplicate expected target_id={target_id} lines={lines}')",
        "    for lineno, record in rows:",
        "        status = record.get('status')",
        "        if status not in accepted_statuses:",
        "            bad.append(f'line {lineno}: target_id={target_id} unexpected status={status!r}')",
        "        if status == 'submitted':",
        "            job_id = str(record.get('job_id') or '')",
        "            if not job_id.strip() or any(ch.isspace() for ch in job_id):",
        "                bad.append(f'line {lineno}: target_id={target_id} has non-parsable submitted job_id={job_id!r}')",
        "        for field in ('target_fasta', 'target_msa', 'target_msa_report'):",
        "            value = record.get(field)",
        "            if not isinstance(value, str) or not value.strip():",
        "                bad.append(f'line {lineno}: target_id={target_id} missing non-empty {field}')",
        "        spec = expected_specs.get(target_id)",
        "        if spec is not None and not isinstance(spec, dict):",
        "            bad.append(f'target_id={target_id} expected receipt spec is not an object')",
        "            continue",
        "        for field in ('target_fasta', 'target_msa', 'target_msa_report', 'manifest', 'manifest_sha256', 'workstream'):",
        "            if not spec or field not in spec:",
        "                continue",
        "            expected_value = str(spec[field])",
        "            actual_value = record.get(field)",
        "            if actual_value is None or str(actual_value) != expected_value:",
        "                bad.append(",
        "                    f'line {lineno}: target_id={target_id} {field} mismatch '",
        "                    f'expected={expected_value!r} actual={actual_value!r}'",
        "                )",
        "if os.environ.get('TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET') == '1' and seen_unexpected:",
        "    bad.append('unexpected target ids in receipt: ' + ','.join(sorted(seen_unexpected)))",
        "if bad:",
        "    print('target-MSA precompute receipt validation failed:', file=sys.stderr)",
        "    for item in bad:",
        "        print(f'  - {item}', file=sys.stderr)",
        "    raise SystemExit(2)",
        "print(f'target-MSA precompute receipt validated for {len(expected)} expected target(s): {receipt}')",
        "PY",
        "}",
        "",
    ]
    input_prep_artifacts: List[Dict[str, str]] = []
    expected_receipt_target_ids: List[str] = []
    receipt_expectations: Dict[str, Dict[str, str]] = {}
    for index, target in enumerate(manifest.get("targets", [])):
        if not isinstance(target, dict):
            lines.extend([f"# targets[{index}] is not an object; skipped", ""])
            continue
        target_id = target.get("id", f"target_{index}")
        if selected_ids is not None and str(target_id) not in selected_ids:
            continue
        missing = [field for field in ("prepared_pdb", "target_chain", "target_fasta", "target_msa")
                   if not _is_nonempty_str(target.get(field))]
        if missing:
            lines.extend([f"# {target_id}: missing {', '.join(missing)}; skipped", ""])
            continue
        expected_receipt_target_ids.append(str(target_id))
        input_prep_artifacts.extend(_input_prep_artifacts(target))
        msa_job_var = f"MSA_{index:02d}_{_shell_token(target_id)}"
        target_fasta = str(target["target_fasta"])
        target_msa = str(target["target_msa"])
        target_msa_report = target.get("target_msa_report", target_msa + ".report.json")
        receipt_expectation = {
            "target_fasta": target_fasta,
            "target_msa": target_msa,
            "target_msa_report": str(target_msa_report),
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_sha256,
        }
        if workstream:
            receipt_expectation["workstream"] = str(workstream)
        receipt_expectations[str(target_id)] = receipt_expectation
        source_pdb = str(target["source_pdb"]) if _is_nonempty_str(target.get("source_pdb")) else None
        prepared_pdb = str(target["prepared_pdb"])
        prep_report = str(target.get("prep_report", prepared_pdb + ".report.json"))
        fasta_report = str(target.get("target_fasta_report", target_fasta + ".report.json"))
        rcsb_id = _rcsb_id(target)
        prep_gap_arg = " --allow-numbering-gaps" if _allow_numbering_gaps(target) else ""
        prep_ready_msg = f"prepared PDB already exists: {prepared_pdb}"
        lines.extend([
            f"# {target_id}",
            _mkdir_line([source_pdb or "", prepared_pdb, prep_report, target_fasta, fasta_report,
                         target_msa, str(target_msa_report)]),
        ])
        if source_pdb:
            if rcsb_id:
                source_exists_msg = f"source PDB already exists: {source_pdb}"
                source_url = f"https://files.rcsb.org/download/{rcsb_id}.pdb"
                lines.extend([
                    f"if [ -s {shlex.quote(source_pdb)} ]; then",
                    f"  echo {shlex.quote(source_exists_msg)}",
                    "else",
                    f"  curl -fsSL {shlex.quote(source_url)} -o {shlex.quote(source_pdb)}",
                    "fi",
                ])
            else:
                missing_source_msg = f"Missing source PDB: {source_pdb} (set rcsb_id to auto-fetch or copy it here)"
                lines.append(
                    f"test -s {shlex.quote(source_pdb)} || "
                    f"{{ echo {shlex.quote(missing_source_msg)} >&2; exit 2; }}"
                )
            if _is_nonempty_str(target.get("binder_chain")):
                lines.extend([
                    f"if [ -s {shlex.quote(prepared_pdb)} ] && [ -s {shlex.quote(prep_report)} ]; then",
                    f"  echo {shlex.quote(prep_ready_msg)}",
                    "else",
                    f"  \"$PYTHON_BIN\" hpc/prep_hetdimer.py --pdb {shlex.quote(source_pdb)} "
                    f"--target-chain {shlex.quote(str(target['target_chain']))} "
                    f"--binder-chain {shlex.quote(str(target['binder_chain']))} "
                    f"--out {shlex.quote(prepared_pdb)} --report {shlex.quote(prep_report)}"
                    f"{prep_gap_arg}",
                    "fi",
                ])
        lines.extend([
            f"\"$PYTHON_BIN\" hpc/extract_chain_fasta.py --pdb {shlex.quote(prepared_pdb)} "
            f"--chain {shlex.quote(str(target['target_chain']))} "
            f"--id {shlex.quote(str(target_id) + '_' + str(target['target_chain']))} "
            f"--out {shlex.quote(target_fasta)} --report {shlex.quote(fasta_report)}",
            f"if [ -s {shlex.quote(target_msa)} ]; then",
            f"  echo {shlex.quote('target MSA exists; validating and refreshing report: ' + target_msa)}",
            f"  \"$PYTHON_BIN\" hpc/precompute_boltz_target_msa.py --fasta {shlex.quote(target_fasta)} "
            f"--out {shlex.quote(target_msa)} --report {shlex.quote(str(target_msa_report))}",
            f"  record_target_msa_precompute {shlex.quote(str(target_id))} validated_existing '' "
            f"{shlex.quote(target_fasta)} {shlex.quote(target_msa)} {shlex.quote(str(target_msa_report))}",
            "else",
            f"  {msa_job_var}=$("
            + _env_assign(
                FASTA=target_fasta,
                OUT=target_msa,
                REPORT=str(target_msa_report),
            )
            + " sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)",
            f"  require_target_msa_job_id {shlex.quote(str(target_id))} \"${{{msa_job_var}}}\"",
            f"  echo {shlex.quote('submitted target MSA job for ' + str(target_id) + ': ')}\"${{{msa_job_var}}}\"",
            f"  record_target_msa_precompute {shlex.quote(str(target_id))} submitted \"${{{msa_job_var}}}\" "
            f"{shlex.quote(target_fasta)} {shlex.quote(target_msa)} {shlex.quote(str(target_msa_report))}",
            "fi",
            "",
        ])
    if expected_receipt_target_ids:
        quoted_expected = " ".join(shlex.quote(target_id) for target_id in expected_receipt_target_ids)
        expected_json = json.dumps(receipt_expectations, sort_keys=True, separators=(",", ":"))
        lines.extend([
            f"validate_target_msa_precompute_receipt --expect-json {shlex.quote(expected_json)} {quoted_expected}",
            "",
        ])
    if input_prep_artifacts:
        lines.extend([
            "# expected_input_prep_files",
            "# If this plan runs on Cayuga, sync these paths back before rerunning --require-files.",
        ])
        for artifact in input_prep_artifacts:
            lines.append(
                f"# {artifact['target_id']} {artifact['field']}: {artifact['path']}"
            )
        lines.append("")
    if rerun_command:
        lines.extend([
            "# rerun_manifest_after_msa",
            f"# {rerun_command}",
            "",
        ])
    return "\n".join(lines)


def _rerun_manifest_after_msa_command(args: argparse.Namespace) -> str:
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.complex_target_manifest",
        "--manifest",
        args.manifest,
    ]
    for target_id in args.target_ids or []:
        parts.extend(["--target-id", str(target_id)])
    parts.extend([
        "--require-files",
        "--min-targets",
        str(args.min_targets),
        "--min-contacts",
        str(args.min_contacts),
    ])
    if args.require_records:
        parts.append("--require-records")
    if args.out:
        parts.extend(["--out", args.out])
    if args.emit_plan:
        parts.extend(["--emit-plan", args.emit_plan])
    return shlex.join(parts)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="validate an M6c multi-target heterodimer manifest")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--target-id", action="append", dest="target_ids", default=None,
                    help="optional target id to validate/emit; repeat for a selected subset")
    ap.add_argument("--require-files", action="store_true")
    ap.add_argument("--min-targets", type=int, default=1)
    ap.add_argument("--min-contacts", type=int, default=1)
    ap.add_argument("--require-records", action="store_true",
                    help="with --require-files, also require planned downstream records to already exist")
    ap.add_argument("--out", default=None, help="optional JSON validation report")
    ap.add_argument("--emit-plan", default=None, help="optional shell command plan for ready targets")
    ap.add_argument("--emit-msa-plan", default=None,
                    help="optional shell command plan to precompute missing target MSAs")
    ap.add_argument("--max-failures", type=int, default=20)
    args = ap.parse_args(argv)

    rep = validate_manifest(args.manifest, require_files=args.require_files,
                            min_targets=args.min_targets, min_contacts=args.min_contacts,
                            target_ids=args.target_ids,
                            require_records=args.require_records)
    print(f"# complex target manifest  targets={rep['n_targets']} ready={rep['n_ready_targets']} ok={rep['ok']}")
    if rep["failures_by_kind"]:
        print("  failures_by_kind:", json.dumps(rep["failures_by_kind"], sort_keys=True))
        for f in rep["failures"][:args.max_failures]:
            field = f" field={f['field']}" if f.get("field") is not None else ""
            print(f"  {f['kind']} target={f['target_id']}{field} -- {f['message']}")
    else:
        print("  ok")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {args.out}")
    if args.emit_plan:
        plan = render_hpc_plan(rep, args.manifest, msa_plan_path=args.emit_msa_plan)
        with open(args.emit_plan, "w") as fh:
            fh.write(plan)
        print(f"wrote {args.emit_plan}")
    if args.emit_msa_plan:
        plan = render_target_msa_plan(
            args.manifest,
            target_ids=args.target_ids,
            rerun_command=_rerun_manifest_after_msa_command(args),
        )
        with open(args.emit_msa_plan, "w") as fh:
            fh.write(plan)
        print(f"wrote {args.emit_msa_plan}")
    if not rep["ok"]:
        sys.exit(2)
    return rep


if __name__ == "__main__":
    main()
