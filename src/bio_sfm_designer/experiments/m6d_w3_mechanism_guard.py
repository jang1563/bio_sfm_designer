"""Fail-closed validation for the no-submit W3 mechanism-panel bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


_STATUS = "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            rows.append(value)
    return rows


def _add(failures: List[Dict[str, Any]], kind: str, message: str,
         observed: Any = None) -> None:
    item: Dict[str, Any] = {"kind": kind, "message": message}
    if observed is not None:
        item["observed"] = observed
    failures.append(item)


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def verify_bundle(packet: Mapping[str, Any], *, packet_path: str,
                  private_manifest_path: str, input_dir: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    execution = packet.get("execution_packet")
    if not isinstance(execution, dict):
        execution = {}
        _add(failures, "execution_packet_missing", "public packet lacks execution_packet")
    checks = [
        (packet.get("status") == _STATUS, "packet_status_invalid", packet.get("status")),
        (packet.get("audit_ok") is True, "packet_audit_not_ok", packet.get("audit_ok")),
        (execution.get("no_submit") is True, "packet_not_no_submit", execution.get("no_submit")),
        (execution.get("no_gpu_compute") is True, "packet_gpu_boundary_invalid", execution.get("no_gpu_compute")),
        (execution.get("no_api_spend") is True, "packet_api_boundary_invalid", execution.get("no_api_spend")),
        (execution.get("no_network_fetch") is True, "packet_network_boundary_invalid", execution.get("no_network_fetch")),
        (execution.get("inputs_emitted") is True, "packet_inputs_not_emitted", execution.get("inputs_emitted")),
        (execution.get("approval_recorded") is False, "packet_approval_already_recorded", execution.get("approval_recorded")),
        (execution.get("approval_consumed") is False, "packet_approval_already_consumed", execution.get("approval_consumed")),
        (execution.get("execution_ready") is False, "packet_execution_ready_leak", execution.get("execution_ready")),
        (execution.get("n_inputs") == 58, "packet_input_count_invalid", execution.get("n_inputs")),
    ]
    for ok, kind, observed in checks:
        if not ok:
            _add(failures, kind, "public packet violates the no-submit bundle contract", observed)

    if not os.path.isfile(private_manifest_path):
        _add(failures, "private_manifest_missing", "private sequence-bearing manifest is missing",
             private_manifest_path)
        rows: List[Dict[str, Any]] = []
    else:
        observed_sha = _sha256_file(private_manifest_path)
        if observed_sha != execution.get("private_manifest_sha256"):
            _add(failures, "private_manifest_sha_mismatch", "private manifest hash differs from public lock",
                 observed_sha)
        rows = _load_jsonl(private_manifest_path)
    if len(rows) != 58:
        _add(failures, "private_manifest_count_invalid", "private manifest must have 58 rows", len(rows))

    public_rows = packet.get("rows")
    if not isinstance(public_rows, list):
        public_rows = []
        _add(failures, "public_rows_missing", "public packet rows are missing")
    public_by_id = {
        str(row.get("case_id")): row for row in public_rows if isinstance(row, dict)
    }
    private_ids = [str(row.get("case_id")) for row in rows]
    if len(public_by_id) != 58 or sorted(public_by_id) != sorted(private_ids):
        _add(failures, "public_private_case_identity_mismatch",
             "public and private case identities must match exactly")

    project_root = Path(packet_path).resolve().parent.parent
    root = Path(input_dir)
    if not root.is_absolute():
        root = project_root / root
    for row in rows:
        case_id = str(row.get("case_id"))
        public = public_by_id.get(case_id) or {}
        target = row.get("target_sequence")
        binder = row.get("binder_sequence")
        if not isinstance(target, str) or _sha256_text(target) != public.get("target_sequence_sha256"):
            _add(failures, "target_sequence_sha_mismatch", "target sequence hash mismatch", case_id)
        if not isinstance(binder, str) or _sha256_text(binder) != public.get("binder_sequence_sha256"):
            _add(failures, "binder_sequence_sha_mismatch", "binder sequence hash mismatch", case_id)
        a3m_path = Path(str(row.get("a3m_path") or ""))
        if not a3m_path.is_absolute():
            a3m_path = project_root / a3m_path
        if not _under(a3m_path, root):
            _add(failures, "a3m_path_escape", "A3M path escapes the locked input directory", case_id)
            continue
        if not a3m_path.is_file():
            _add(failures, "a3m_missing", "locked A3M input is missing", os.fspath(a3m_path))
            continue
        observed = _sha256_file(os.fspath(a3m_path))
        if observed != public.get("a3m_sha256") or observed != row.get("a3m_sha256"):
            _add(failures, "a3m_sha_mismatch", "A3M hash differs from public/private locks", case_id)
        with open(a3m_path) as handle:
            first = handle.readline().rstrip("\n")
            second = handle.readline().rstrip("\n")
            query = handle.readline().rstrip("\n")
        expected_header = f"#{len(target or '')},{len(binder or '')}\t1,1"
        if first != expected_header or not second.startswith(">") or query != f"{target or ''}{binder or ''}":
            _add(failures, "a3m_annotation_invalid", "annotated complex A3M header/query is invalid", case_id)

    report = {
        "artifact": "m6d_w3_mechanism_bundle_verification",
        "status": "verified_no_submit" if not failures else "verification_failed",
        "ok": not failures,
        "packet": packet_path,
        "private_manifest": private_manifest_path,
        "input_dir": input_dir,
        "n_rows": len(rows),
        "failures": failures,
        "prediction_executed": False,
        "submitted_jobs": 0,
    }
    return report


def verify_runtime_receipt(receipt: Mapping[str, Any], *, data_dir: str,
                           runtime_path: str) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    required = {
        "artifact": "m6d_w3_mechanism_runtime_receipt",
        "status": "w3_mechanism_runtime_ready_no_prediction",
        "colabfold_version": "1.6.1",
        "model_type": "alphafold2_multimer_v3",
        "prediction_executed": False,
        "submitted_jobs": 0,
        "network_fetch_executed": False,
    }
    for field, expected in required.items():
        if receipt.get(field) != expected:
            _add(failures, f"runtime_receipt_{field}_invalid", "runtime receipt field mismatch",
                 {"expected": expected, "observed": receipt.get(field)})
    if receipt.get("runtime_mode") not in (
        "existing_colabfold_binary",
        "apptainer_colabfold_image",
    ):
        _add(failures, "runtime_receipt_mode_invalid", "runtime mode is not supported")
    if os.path.abspath(str(receipt.get("runtime_path") or "")) != os.path.abspath(runtime_path):
        _add(failures, "runtime_receipt_path_mismatch", "runtime path differs from receipt")
    if os.path.abspath(str(receipt.get("data_dir") or "")) != os.path.abspath(data_dir):
        _add(failures, "runtime_receipt_data_dir_mismatch", "weights path differs from receipt")
    marker = Path(data_dir) / "params" / "download_complexes_multimer_v3_finished.txt"
    weights = sorted((Path(data_dir) / "params").glob("params_model_*_multimer_v3.npz"))
    if not marker.is_file() or len(weights) != 5:
        _add(failures, "runtime_weights_incomplete",
             "local AF2-Multimer v3 success marker and exactly five model files are required",
             {"marker": marker.is_file(), "weight_files": len(weights)})
    observed_manifest = hashlib.sha256()
    for path in weights:
        observed_manifest.update(path.name.encode("utf-8"))
        observed_manifest.update(_sha256_file(os.fspath(path)).encode("ascii"))
    if observed_manifest.hexdigest() != receipt.get("weights_manifest_sha256"):
        _add(failures, "runtime_weights_manifest_mismatch", "weights manifest hash differs from receipt")
    if not os.path.isfile(runtime_path) or _sha256_file(runtime_path) != receipt.get("runtime_sha256"):
        _add(failures, "runtime_binary_or_image_sha_mismatch", "runtime hash differs from receipt")
    return {"ok": not failures, "failures": failures}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the W3 no-submit mechanism bundle")
    parser.add_argument("--packet", default="configs/m6d_w3_mechanism_panel_protocol.json")
    parser.add_argument("--private-manifest", default="results/m6d_w3_mechanism_panel_inputs.jsonl")
    parser.add_argument("--input-dir", default="results/m6d_w3_mechanism_panel_inputs/a3m")
    parser.add_argument("--out", default=None)
    parser.add_argument("--runtime-receipt", default=None)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    packet = _load_json(args.packet)
    report = verify_bundle(
        packet,
        packet_path=args.packet,
        private_manifest_path=args.private_manifest,
        input_dir=args.input_dir,
    )
    if args.runtime_receipt or args.runtime_path or args.data_dir:
        if not all((args.runtime_receipt, args.runtime_path, args.data_dir)):
            _add(report["failures"], "runtime_arguments_incomplete",
                 "runtime receipt, runtime path, and data dir must be supplied together")
            report["ok"] = False
            report["status"] = "verification_failed"
        else:
            runtime = verify_runtime_receipt(
                _load_json(args.runtime_receipt),
                data_dir=args.data_dir,
                runtime_path=args.runtime_path,
            )
            report["runtime"] = runtime
            if not runtime["ok"]:
                report["failures"].extend(runtime["failures"])
                report["ok"] = False
                report["status"] = "verification_failed"
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as handle:
            handle.write(text)
    print(text, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
