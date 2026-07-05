"""Precompute one target MSA for repeated Boltz complex refolds.

The M6c complex workflow should not ask the public MSA server once per designed
binder. This helper runs one tiny Boltz job with `--use_msa_server`, searches
the Boltz processed output for a matching `.a3m`, and copies it to the stable
target MSA path used later by `predict_boltz_complex.py --target-msa`.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional


def _read_first_sequence(path: str, *, a3m: bool = False) -> Optional[str]:
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
    if not seq:
        return None
    joined = "".join(seq)
    if a3m:
        return "".join(ch for ch in joined if ch.isupper() and ch != "-")
    return "".join(ch.upper() for ch in joined if ch.isalpha())


def _read_first_header(path: str) -> str:
    with open(path) as fh:
        for line in fh:
            if line.startswith(">"):
                return line[1:].strip() or "target"
    return "target"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize_a3m_file(path: str) -> int:
    """Remove NUL bytes that Boltz cannot parse; return the number removed."""
    with open(path, "rb") as fh:
        data = fh.read()
    n_nul = data.count(b"\x00")
    if n_nul:
        with open(path, "wb") as fh:
            fh.write(data.replace(b"\x00", b""))
    return n_nul


def _write_yaml(path: str, sequence: str) -> None:
    with open(path, "w") as fh:
        fh.write(
            "version: 1\nsequences:\n"
            "  - protein:\n"
            "      id: A\n"
            f"      sequence: {sequence}\n"
        )


def _find_matching_a3m(root: str, sequence: str) -> Dict[str, object]:
    paths = sorted(glob.glob(os.path.join(root, "**", "*.a3m"), recursive=True))
    paths.extend(sorted(glob.glob(os.path.join(root, "**", "*.A3M"), recursive=True)))
    mismatches = []
    for path in paths:
        try:
            query = _read_first_sequence(path, a3m=True)
        except OSError as exc:
            mismatches.append({"path": path, "error": str(exc)})
            continue
        if query == sequence:
            return {"path": path, "n_candidates": len(paths), "mismatches": mismatches}
        mismatches.append({
            "path": path,
            "query_length": len(query or ""),
            "expected_length": len(sequence),
        })
    return {"path": None, "n_candidates": len(paths), "mismatches": mismatches}


def _copy_matching_a3m(*, work: str, sequence: str, out_abs: str) -> Dict[str, object]:
    match = _find_matching_a3m(work, sequence)
    if not match["path"]:
        return match
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    shutil.copyfile(str(match["path"]), out_abs)
    match["out_sanitized_nul_bytes"] = _sanitize_a3m_file(out_abs)
    copied = _read_first_sequence(out_abs, a3m=True)
    if copied != sequence:
        raise ValueError("copied MSA failed post-copy FASTA query check")
    return match


def precompute_target_msa(*, fasta: str, out: str, report: Optional[str] = None,
                          work_dir: Optional[str] = None,
                          boltz: str = os.path.expanduser("~/.conda/envs/boltz/bin/boltz"),
                          cache: Optional[str] = None,
                          sampling_steps: int = 1,
                          diffusion_samples: int = 1,
                          accelerator: str = "gpu",
                          devices: str = "1",
                          output_format: str = "pdb",
                          msa_server_url: Optional[str] = None,
                          force: bool = False,
                          keep_work: bool = False) -> Dict[str, object]:
    if not os.path.exists(fasta):
        raise ValueError(f"target FASTA not found: {fasta}")
    sequence = _read_first_sequence(fasta, a3m=False)
    if not sequence:
        raise ValueError(f"target FASTA has no sequence: {fasta}")
    fasta_id = _read_first_header(fasta)

    out_abs = os.path.abspath(out)
    if os.path.exists(out_abs) and not force:
        sanitized_nul_bytes = _sanitize_a3m_file(out_abs)
        existing = _read_first_sequence(out_abs, a3m=True)
        if existing == sequence:
            rep = {
                "ok": True,
                "reused_existing": True,
                "fasta": fasta,
                "fasta_abs": os.path.abspath(fasta),
                "fasta_id": fasta_id,
                "fasta_sha256": _sha256_file(fasta),
                "out": out,
                "out_abs": out_abs,
                "out_sha256": _sha256_file(out_abs),
                "out_sanitized_nul_bytes": sanitized_nul_bytes,
                "sequence_length": len(sequence),
                "message": "existing target MSA matches FASTA; no Boltz run needed",
            }
            if report:
                _write_report(report, rep)
            return rep
        raise ValueError(f"existing target MSA query does not match FASTA: {out_abs}")

    work = work_dir or os.path.join(
        os.path.dirname(out_abs) or ".",
        "_target_msa_work_" + os.path.splitext(os.path.basename(out_abs))[0],
    )
    work = os.path.abspath(work)
    if os.path.exists(work) and not keep_work:
        shutil.rmtree(work)
    os.makedirs(work, exist_ok=True)
    yaml_dir = os.path.join(work, "yaml")
    boltz_out = os.path.join(work, "boltz_out")
    os.makedirs(yaml_dir, exist_ok=True)
    yaml_path = os.path.join(yaml_dir, "target.yaml")
    _write_yaml(yaml_path, sequence)

    cmd = [
        boltz,
        "predict",
        yaml_path,
        "--out_dir",
        boltz_out,
        "--use_msa_server",
        "--no_kernels",
        "--override",
        "--output_format",
        output_format,
        "--accelerator",
        accelerator,
        "--devices",
        str(devices),
        "--diffusion_samples",
        str(diffusion_samples),
        "--sampling_steps",
        str(sampling_steps),
    ]
    if cache:
        cmd.extend(["--cache", cache])
    if msa_server_url:
        cmd.extend(["--msa_server_url", msa_server_url])

    recovered_existing_work = False
    recovered_after_boltz_failure = False
    boltz_returncode = None
    match = {"path": None, "n_candidates": 0, "mismatches": []}
    if keep_work:
        match = _copy_matching_a3m(work=work, sequence=sequence, out_abs=out_abs)
        recovered_existing_work = bool(match["path"])
    if not match["path"]:
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            boltz_returncode = exc.returncode
            match = _copy_matching_a3m(work=work, sequence=sequence, out_abs=out_abs)
            recovered_after_boltz_failure = bool(match["path"])
            if not match["path"]:
                raise
        else:
            match = _copy_matching_a3m(work=work, sequence=sequence, out_abs=out_abs)
    if not match["path"]:
        raise ValueError(
            "Boltz run finished, but no matching .a3m was found under "
            f"{work}; found {match['n_candidates']} candidate .a3m file(s)"
        )
    rep = {
        "ok": True,
        "reused_existing": False,
        "recovered_existing_work": recovered_existing_work,
        "recovered_after_boltz_failure": recovered_after_boltz_failure,
        "fasta": fasta,
        "fasta_abs": os.path.abspath(fasta),
        "fasta_id": fasta_id,
        "fasta_sha256": _sha256_file(fasta),
        "out": out,
        "out_abs": out_abs,
        "out_sha256": _sha256_file(out_abs),
        "out_sanitized_nul_bytes": int(match.get("out_sanitized_nul_bytes") or 0),
        "work_dir": work,
        "source_msa": os.path.abspath(str(match["path"])),
        "sequence_length": len(sequence),
        "n_a3m_candidates": match["n_candidates"],
        "command": cmd,
    }
    if boltz_returncode is not None:
        rep["boltz_returncode"] = boltz_returncode
    if report:
        _write_report(report, rep)
    return rep


def _write_report(path: str, rep: Dict[str, object]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(rep, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv=None) -> Dict[str, object]:
    ap = argparse.ArgumentParser(description="precompute and validate one Boltz target .a3m")
    ap.add_argument("--fasta", required=True, help="target FASTA extracted from the prepared PDB")
    ap.add_argument("--out", required=True, help="stable output .a3m path")
    ap.add_argument("--report", default=None, help="optional JSON report")
    ap.add_argument("--work-dir", default=None, help="temporary Boltz work directory")
    ap.add_argument("--boltz", default=os.path.expanduser("~/.conda/envs/boltz/bin/boltz"))
    ap.add_argument("--cache", default=None, help="optional Boltz cache directory")
    ap.add_argument("--sampling-steps", type=int, default=1)
    ap.add_argument("--diffusion-samples", type=int, default=1)
    ap.add_argument("--accelerator", default="gpu")
    ap.add_argument("--devices", default="1")
    ap.add_argument("--output-format", default="pdb")
    ap.add_argument("--msa-server-url", default=None)
    ap.add_argument("--force", action="store_true", help="overwrite an existing output MSA")
    ap.add_argument("--keep-work", action="store_true", help="do not wipe the work directory before running")
    args = ap.parse_args(argv)

    try:
        rep = precompute_target_msa(
            fasta=args.fasta,
            out=args.out,
            report=args.report,
            work_dir=args.work_dir,
            boltz=args.boltz,
            cache=args.cache,
            sampling_steps=args.sampling_steps,
            diffusion_samples=args.diffusion_samples,
            accelerator=args.accelerator,
            devices=args.devices,
            output_format=args.output_format,
            msa_server_url=args.msa_server_url,
            force=args.force,
            keep_work=args.keep_work,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"target MSA precompute failed: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"# target MSA precompute ok={rep['ok']} reused_existing={rep['reused_existing']}")
    print(f"  fasta: {rep['fasta']}")
    print(f"  out: {rep['out']}")
    if rep.get("source_msa"):
        print(f"  source_msa: {rep['source_msa']}")
    if args.report:
        print(f"wrote {args.report}")
    return rep


if __name__ == "__main__":
    main()
