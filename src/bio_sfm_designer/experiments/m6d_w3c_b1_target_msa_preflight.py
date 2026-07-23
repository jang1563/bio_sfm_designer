"""Validate or materialize W3c-B1 source and target-FASTA inputs without submitting jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from typing import Any, Dict, Iterable, List, Mapping, Optional

TARGET_IDS = [
    "1TE1_BA",
    "3QB4_AB",
    "5E5M_AB",
    "5JSB_AB",
    "6KBR_AC",
    "6KMQ_AB",
    "6SGE_AB",
    "7B5G_AB",
]


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


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_fasta(path: str) -> str:
    sequence: List[str] = []
    with open(path) as handle:
        for line in handle:
            text = line.strip()
            if text and not text.startswith(">"):
                sequence.append(text)
    value = "".join(sequence).upper()
    if not value or not set(value).issubset(set("ACDEFGHIKLMNPQRSTVWY")):
        raise ValueError(f"target FASTA is empty or noncanonical: {path}")
    return value


def _target_rows(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = manifest.get("targets")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("W3c-B1 manifest must contain object target rows")
    return [dict(row) for row in rows]


def validate_manifest(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = _target_rows(manifest)
    target_ids = [str(row.get("id") or "") for row in rows]
    checks = {
        "identity": (
            manifest.get("artifact") == "m6d_w3c_b1_target_msa_manifest"
            and manifest.get("version") == 1
            and manifest.get("status") == "inputs_locked_awaiting_exact_approval_no_submit"
        ),
        "target_panel": target_ids == TARGET_IDS and len(set(target_ids)) == 8,
        "budget": (
            manifest.get("compute_resource") == "Cayuga A40"
            and manifest.get("slurm_time_per_query") == "01:00:00"
            and manifest.get("maximum_target_msa_queries") == 8
            and float(manifest.get("maximum_a40_gpu_hours") or 0.0) == 8.0
        ),
        "authority": (
            manifest.get("target_msa_queries_authorized") == 0
            and manifest.get("proteinmpnn_designs_authorized") == 0
            and manifest.get("predictor_evaluations_authorized") == 0
            and manifest.get("approval_recorded") is False
            and manifest.get("submission_performed") is False
            and manifest.get("no_submit") is True
            and manifest.get("cayuga_submission_allowed") is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"W3c-B1 manifest preflight failed: {', '.join(failed)}")

    required = (
        "id",
        "rcsb_id",
        "source_pdb",
        "source_pdb_sha256",
        "source_pdb_url",
        "prepared_pdb",
        "prep_report",
        "target_chain",
        "binder_chain",
        "target_sequence_sha256",
        "target_fasta",
        "target_fasta_report",
        "target_msa",
        "target_msa_report",
    )
    for row in rows:
        target_id = str(row["id"])
        missing = [name for name in required if not isinstance(row.get(name), str) or not row[name]]
        if missing:
            raise ValueError(f"{target_id} is missing required fields: {', '.join(missing)}")
        for name in ("source_pdb_sha256", "target_sequence_sha256"):
            value = str(row[name])
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{target_id} has invalid {name}")
        if row["target_chain"] == row["binder_chain"]:
            raise ValueError(f"{target_id} target and binder chains are identical")
        if row.get("semantic_verdict") != "pass":
            raise ValueError(f"{target_id} lacks the frozen semantic pass")
    return rows


def _materialize_source(row: Mapping[str, Any]) -> str:
    source_path = str(row["source_pdb"])
    expected = str(row["source_pdb_sha256"])
    if os.path.isfile(source_path) and os.path.getsize(source_path) > 0:
        actual = _sha256_file(source_path)
        if actual != expected:
            raise ValueError(
                f"source PDB hash mismatch for {row['id']}: expected={expected} actual={actual}"
            )
        return "verified_existing"

    os.makedirs(os.path.dirname(source_path) or ".", exist_ok=True)
    temporary = source_path + ".download"
    if os.path.exists(temporary):
        os.remove(temporary)
    try:
        urllib.request.urlretrieve(str(row["source_pdb_url"]), temporary)
        actual = _sha256_file(temporary)
        if actual != expected:
            raise ValueError(
                f"downloaded source PDB hash mismatch for {row['id']}: "
                f"expected={expected} actual={actual}"
            )
        os.replace(temporary, source_path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return "downloaded_and_verified"


def _run_checked(command: List[str], *, cwd: str) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ValueError(f"input materialization command failed: {detail}")


def run_preflight(
    manifest: Mapping[str, Any],
    *,
    materialize: bool,
    project_root: str,
    python_bin: str,
) -> Dict[str, Any]:
    rows = validate_manifest(manifest)
    target_reports: List[Dict[str, Any]] = []
    for row in rows:
        target_id = str(row["id"])
        source_path = str(row["source_pdb"])
        source_exists = os.path.isfile(source_path) and os.path.getsize(source_path) > 0
        source_verified = source_exists and _sha256_file(source_path) == row["source_pdb_sha256"]
        if source_exists and not source_verified:
            raise ValueError(f"source PDB hash mismatch during config preflight: {target_id}")

        target_report: Dict[str, Any] = {
            "target_id": target_id,
            "source_pdb": source_path,
            "source_pdb_sha256": row["source_pdb_sha256"],
            "source_present": source_exists,
            "source_hash_verified": source_verified,
            "target_sequence_sha256": row["target_sequence_sha256"],
            "target_fasta": row["target_fasta"],
            "target_msa": row["target_msa"],
            "target_msa_present": os.path.exists(str(row["target_msa"])),
        }
        if materialize:
            if target_report["target_msa_present"]:
                raise ValueError(
                    f"refusing initial W3c-B1 materialization because target MSA exists: {row['target_msa']}"
                )
            source_status = _materialize_source(row)
            prep_command = [
                python_bin,
                "hpc/prep_hetdimer.py",
                "--pdb",
                source_path,
                "--target-chain",
                str(row["target_chain"]),
                "--binder-chain",
                str(row["binder_chain"]),
                "--out",
                str(row["prepared_pdb"]),
                "--report",
                str(row["prep_report"]),
                "--contact-cutoff",
                "8.0",
                "--min-contacts",
                "20",
                "--min-residues",
                "40",
            ]
            _run_checked(prep_command, cwd=project_root)
            fasta_command = [
                python_bin,
                "hpc/extract_chain_fasta.py",
                "--pdb",
                str(row["prepared_pdb"]),
                "--chain",
                str(row["target_chain"]),
                "--id",
                f"{target_id}_{row['target_chain']}",
                "--out",
                str(row["target_fasta"]),
                "--report",
                str(row["target_fasta_report"]),
            ]
            _run_checked(fasta_command, cwd=project_root)
            sequence = _read_fasta(str(row["target_fasta"]))
            actual_sequence_hash = _sha256_text(sequence)
            if actual_sequence_hash != row["target_sequence_sha256"]:
                raise ValueError(
                    f"target sequence hash mismatch for {target_id}: "
                    f"expected={row['target_sequence_sha256']} actual={actual_sequence_hash}"
                )
            target_report.update(
                {
                    "source_status": source_status,
                    "source_present": True,
                    "source_hash_verified": True,
                    "prepared_pdb": row["prepared_pdb"],
                    "prep_report": row["prep_report"],
                    "target_fasta_report": row["target_fasta_report"],
                    "target_sequence_length": len(sequence),
                    "target_sequence_hash_verified": True,
                }
            )
        target_reports.append(target_report)

    return {
        "artifact": "m6d_w3c_b1_target_msa_input_preflight",
        "version": 1,
        "status": (
            "w3c_b1_inputs_materialized_ready_for_approved_msa_submission"
            if materialize
            else "w3c_b1_input_configuration_valid_no_submit"
        ),
        "audit_ok": True,
        "mode": "materialize" if materialize else "config_only",
        "target_count": 8,
        "target_ids": TARGET_IDS,
        "targets": target_reports,
        "source_pdbs_verified": sum(row["source_hash_verified"] for row in target_reports),
        "target_fastas_verified": (
            sum(bool(row.get("target_sequence_hash_verified")) for row in target_reports)
        ),
        "scheduler_jobs_submitted": 0,
        "target_msa_queries_submitted": 0,
        "proteinmpnn_designs": 0,
        "predictor_evaluations": 0,
        "no_submit": True,
        "cayuga_submission_allowed": False,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="configs/m6d_w3c_b1_target_msa_manifest.json")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    report = run_preflight(
        _load_json(args.manifest),
        materialize=args.materialize,
        project_root=args.project_root,
        python_bin=args.python_bin,
    )
    if args.out:
        _write_json(args.out, report)
        print(f"wrote {args.out}")
    print(
        f"status={report['status']} targets={report['target_count']} "
        f"jobs_submitted={report['scheduler_jobs_submitted']} no_submit={report['no_submit']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
