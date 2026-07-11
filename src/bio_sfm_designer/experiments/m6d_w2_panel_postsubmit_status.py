"""Audit W2 panel submit receipts before sync-back.

This helper never submits jobs. It validates the receipt/summary emitted by the
guarded panel submit wrapper and, when Slurm job states are supplied, decides
whether sync-back is allowed to start.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple


_DEFAULT_MANIFEST = "configs/m6d_w2_target_family_redesign_v11_representative_targets.json"
_DEFAULT_RECEIPT = "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl"
_DEFAULT_SUMMARY = "results/m6d_w2_target_family_redesign_v11_submit_receipt_summary.json"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_postsubmit_status.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_postsubmit_status.md"
_COMPLETE_STATES = {"COMPLETED", "COMPLETE", "CD"}
_ACTIVE_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED", "PD", "R", "CF", "CG", "S"}
_FAILED_STATES = {
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
    "F",
    "CA",
    "TO",
    "OOM",
    "NF",
    "PR",
    "BF",
    "DL",
}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: JSONL row must be an object")
            rows.append(obj)
    return rows


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _records_path(target: Dict[str, Any]) -> str:
    target_id = str(target.get("id", "target"))
    out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
    return str(target.get("records") or os.path.join(out_prefix, "records_boltz_complex.jsonl"))


def _manifest_specs(manifest: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    specs: Dict[str, Dict[str, str]] = {}
    for index, target in enumerate(manifest.get("targets", [])):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or f"target_{index}")
        specs[target_id] = {
            "records": _records_path(target),
            "target_msa": str(target.get("target_msa") or ""),
            "prepared_pdb": str(target.get("prepared_pdb") or ""),
        }
    return specs


def _job_id_ok(value: Any) -> bool:
    text = str(value or "")
    return bool(text.strip()) and not any(ch.isspace() for ch in text)


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update({k: v for k, v in extra.items() if v is not None})
    failures.append(row)


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().upper()


def _coerce_job_states(obj: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(obj, dict):
        return {}
    if isinstance(obj.get("states"), dict):
        return {str(job_id): _normalize_state(state) for job_id, state in obj["states"].items()}
    rows = obj.get("jobs")
    if not isinstance(rows, list):
        rows = obj.get("job_states")
    if not isinstance(rows, list):
        rows = []
    states: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        job_id = row.get("job_id") or row.get("JobID") or row.get("jobid")
        state = row.get("state") or row.get("State") or row.get("job_state")
        if job_id is not None:
            states[str(job_id)] = _normalize_state(state)
    return states


def _receipt_rows_by_target(rows: Iterable[Dict[str, Any]],
                            specs: Dict[str, Dict[str, str]],
                            *,
                            expected_workstream: Optional[str]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    failures: List[Dict[str, Any]] = []
    by_target: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        target_id = str(row.get("target_id") or "")
        if not target_id:
            _add_failure(failures, "receipt_missing_target_id", "receipt row has no target_id")
            continue
        stage = str(row.get("stage") or row.get("status") or "")
        if stage not in {"proteinmpnn_submitted", "pair_submitted", "submitted"}:
            _add_failure(failures, "receipt_row_stage_invalid", "receipt row has an unsupported stage",
                         target_id=target_id, observed=stage)
            continue
        if expected_workstream is not None and row.get("workstream") != expected_workstream:
            _add_failure(failures, "receipt_row_workstream_mismatch", "receipt row workstream mismatch",
                         target_id=target_id, expected=expected_workstream, observed=row.get("workstream"))
        required_job_fields = (
            ("proteinmpnn_job_id",)
            if stage == "proteinmpnn_submitted"
            else ("proteinmpnn_job_id", "boltz_job_id")
        )
        for field in required_job_fields:
            if not _job_id_ok(row.get(field)):
                _add_failure(failures, "receipt_bad_job_id", f"invalid {field}", target_id=target_id, field=field,
                             observed=row.get(field))
        spec = specs.get(target_id)
        if spec is None:
            _add_failure(failures, "receipt_unexpected_target", "receipt target is not in manifest", target_id=target_id)
            continue
        for field, expected in spec.items():
            if expected and str(row.get(field) or "") != expected:
                _add_failure(failures, "receipt_manifest_field_mismatch", "receipt field differs from manifest",
                             target_id=target_id, field=field, expected=expected, observed=row.get(field))
        if stage in {"pair_submitted", "submitted"}:
            previous = by_target.get(target_id)
            if previous is not None and (
                previous.get("proteinmpnn_job_id") != row.get("proteinmpnn_job_id")
                or previous.get("boltz_job_id") != row.get("boltz_job_id")
            ):
                _add_failure(failures, "receipt_conflicting_pair", "target has conflicting submitted pairs",
                             target_id=target_id)
            by_target[target_id] = row
    missing = sorted(set(specs) - set(by_target))
    if missing:
        _add_failure(failures, "receipt_missing_targets", "receipt does not cover all manifest targets", targets=missing)
    return by_target, failures


def _summary_failures(summary: Dict[str, Any],
                      receipt_path: str,
                      specs: Dict[str, Dict[str, str]],
                      by_target: Dict[str, Dict[str, Any]],
                      *,
                      expected_workstream: Optional[str]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if summary.get("status") != "submitted_on_cayuga":
        _add_failure(failures, "summary_status_not_submitted", "summary status must be submitted_on_cayuga",
                     observed=summary.get("status"))
    if expected_workstream is not None and summary.get("workstream") != expected_workstream:
        _add_failure(failures, "summary_workstream_mismatch", "summary workstream mismatch",
                     expected=expected_workstream, observed=summary.get("workstream"))
    if str(summary.get("receipt") or "") != receipt_path:
        _add_failure(failures, "summary_receipt_path_mismatch", "summary receipt path mismatch",
                     expected=receipt_path, observed=summary.get("receipt"))
    if summary.get("n_targets") != len(specs):
        _add_failure(failures, "summary_target_count_mismatch", "summary n_targets mismatch",
                     expected=len(specs), observed=summary.get("n_targets"))
    if summary.get("n_records") != len(by_target):
        _add_failure(failures, "summary_record_count_mismatch", "summary n_records mismatch",
                     expected=len(by_target), observed=summary.get("n_records"))
    return failures


def _job_state_report(by_target: Dict[str, Dict[str, Any]], job_states: Dict[str, str]) -> Dict[str, Any]:
    jobs = []
    counts = {"complete": 0, "active": 0, "failed": 0, "unknown": 0}
    for target_id in sorted(by_target):
        row = by_target[target_id]
        for role, field in (("proteinmpnn", "proteinmpnn_job_id"), ("boltz", "boltz_job_id")):
            job_id = str(row.get(field) or "")
            state = job_states.get(job_id, "")
            state_class = (
                "complete" if state in _COMPLETE_STATES else
                "active" if state in _ACTIVE_STATES else
                "failed" if state in _FAILED_STATES else
                "unknown"
            )
            counts[state_class] += 1
            jobs.append({
                "target_id": target_id,
                "role": role,
                "job_id": job_id,
                "state": state,
                "state_class": state_class,
            })
    return {"jobs": jobs, "counts": counts}


def build_status(manifest: Dict[str, Any],
                 *,
                 receipt_path: str = _DEFAULT_RECEIPT,
                 summary_path: str = _DEFAULT_SUMMARY,
                 job_states: Optional[Dict[str, Any]] = None,
                 expected_workstream: Optional[str] = "m6d_w2_target_family_redesign_v11") -> Dict[str, Any]:
    specs = _manifest_specs(manifest)
    receipt_exists = os.path.exists(receipt_path)
    summary_exists = os.path.exists(summary_path)
    if not receipt_exists and not summary_exists:
        return {
            "artifact": "m6d_w2_panel_postsubmit_status",
            "status": "not_submitted",
            "audit_ok": True,
            "no_submit": True,
            "submitted": False,
            "sync_ready": False,
            "can_claim_w2_generalization": False,
            "manifest_targets": len(specs),
            "receipt": receipt_path,
            "summary": summary_path,
            "receipt_exists": False,
            "summary_exists": False,
            "failures": [],
            "claim_boundary": "no-submit postsubmit status; no W2 evidence until synced records pass completion and panel report",
            "next_action": "await explicit approval and guarded panel submission before monitoring receipt job states",
        }

    failures: List[Dict[str, Any]] = []
    if not receipt_exists:
        _add_failure(failures, "receipt_missing", "submit receipt is missing", path=receipt_path)
        rows: List[Dict[str, Any]] = []
    else:
        rows = _load_jsonl(receipt_path)
    if not summary_exists:
        _add_failure(failures, "summary_missing", "submit receipt summary is missing", path=summary_path)
        summary: Dict[str, Any] = {}
    else:
        summary = _load_json(summary_path)

    by_target, receipt_failures = _receipt_rows_by_target(
        rows, specs, expected_workstream=expected_workstream
    )
    failures.extend(receipt_failures)
    if summary_exists:
        failures.extend(_summary_failures(
            summary,
            receipt_path,
            specs,
            by_target,
            expected_workstream=expected_workstream,
        ))

    states = _coerce_job_states(job_states)
    state_report = _job_state_report(by_target, states) if states else {"jobs": [], "counts": {}}
    sync_ready = False
    status = "submitted_jobs_unverified"
    if states:
        counts = state_report["counts"]
        if counts.get("failed", 0):
            status = "submitted_jobs_failed"
            _add_failure(failures, "submitted_job_failed", "one or more submitted jobs failed",
                         count=counts.get("failed", 0))
        elif counts.get("unknown", 0):
            status = "submitted_jobs_unknown"
        elif counts.get("active", 0):
            status = "submitted_jobs_active_wait"
        else:
            status = "submitted_jobs_complete_ready_for_sync"
            sync_ready = True
    if failures:
        status = "postsubmit_status_blocked"
        sync_ready = False

    audit_ok = not failures
    return {
        "artifact": "m6d_w2_panel_postsubmit_status",
        "status": status,
        "audit_ok": audit_ok,
        "no_submit": True,
        "submitted": bool(receipt_exists and rows),
        "sync_ready": sync_ready,
        "can_claim_w2_generalization": False,
        "manifest_targets": len(specs),
        "receipt": receipt_path,
        "summary": summary_path,
        "receipt_exists": receipt_exists,
        "summary_exists": summary_exists,
        "n_receipt_rows": len(rows),
        "n_targets_in_receipt": len(by_target),
        "target_ids": sorted(by_target),
        "job_state_report": state_report,
        "failures": failures,
        "claim_boundary": "postsubmit status only; sync-ready is not W2 evidence",
        "next_action": (
            "run sync-back script, then completion and target-wise panel report"
            if sync_ready else
            "wait for all submitted jobs to complete, or provide fresh Slurm job states"
            if audit_ok and receipt_exists else
            "repair postsubmit receipt/status blockers before sync-back"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Postsubmit Status",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        f"Sync ready: `{rep.get('sync_ready')}`.",
        f"Can claim W2 generalization: `{rep.get('can_claim_w2_generalization')}`.",
        "",
        f"- manifest targets: `{rep.get('manifest_targets')}`",
        f"- receipt rows: `{rep.get('n_receipt_rows', 0)}`",
        f"- receipt: `{rep.get('receipt')}` exists=`{rep.get('receipt_exists')}`",
        f"- summary: `{rep.get('summary')}` exists=`{rep.get('summary_exists')}`",
        "",
    ]
    counts = (rep.get("job_state_report") or {}).get("counts") or {}
    if counts:
        lines.extend([
            "## Job States",
            "",
            f"- complete: `{counts.get('complete', 0)}`",
            f"- active: `{counts.get('active', 0)}`",
            f"- failed: `{counts.get('failed', 0)}`",
            f"- unknown: `{counts.get('unknown', 0)}`",
            "",
        ])
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
        lines.append("")
    lines.extend([
        "## Claim Boundary",
        "",
        str(rep.get("claim_boundary") or ""),
        "",
        "## Next Action",
        "",
        str(rep.get("next_action") or ""),
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=_DEFAULT_MANIFEST)
    ap.add_argument("--receipt", default=_DEFAULT_RECEIPT)
    ap.add_argument("--summary", default=_DEFAULT_SUMMARY)
    ap.add_argument("--job-states", default=None, help="Optional JSON with states map or jobs rows")
    ap.add_argument("--expected-workstream", default="m6d_w2_target_family_redesign_v11")
    ap.add_argument("--require-sync-ready", action="store_true")
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    job_states = _load_json(args.job_states) if args.job_states else None
    rep = build_status(
        _load_json(args.manifest),
        receipt_path=args.receipt,
        summary_path=args.summary,
        job_states=job_states,
        expected_workstream=args.expected_workstream,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={ok} submitted={submitted} sync_ready={sync_ready}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            submitted=rep["submitted"],
            sync_ready=rep["sync_ready"],
        )
    )
    if args.require_sync_ready and not rep.get("sync_ready"):
        return 2
    return 0 if rep.get("audit_ok") else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
