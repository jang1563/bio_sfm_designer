"""Build a no-submit W2 panel Slurm job-state probe from a submit receipt.

This helper never submits jobs. It reads the guarded panel submit receipt,
extracts ProteinMPNN/Boltz job IDs, optionally parses sacct output, and writes a
JSON state map that can be passed directly to
``m6d_w2_panel_postsubmit_status --job-states``.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
from typing import Any, Dict, Iterable, List, Optional, Tuple


_DEFAULT_RECEIPT = "results/m6d_w2_target_family_redesign_v11_submit_receipt.jsonl"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_job_state_probe.md"
_DEFAULT_QUERY_PLAN = "results/m6d_w2_target_family_redesign_v11_job_state_query.sh"
_DEFAULT_EXPECTED_WORKSTREAM = "m6d_w2_target_family_redesign_v11"


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str, *, executable: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if executable:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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


def _add_failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row = {"kind": kind, "message": message}
    row.update({key: value for key, value in extra.items() if value is not None})
    failures.append(row)


def _job_id_ok(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and not any(ch.isspace() for ch in text)


def _normalize_state(value: Any) -> str:
    text = str(value or "").strip().upper()
    if " " in text:
        text = text.split(" ", 1)[0]
    return text


def _base_job_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(".", 1)[0].split("_", 1)[0]


def _receipt_jobs(rows: Iterable[Dict[str, Any]],
                  *,
                  expected_workstream: Optional[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    jobs: List[Dict[str, str]] = []
    failures: List[Dict[str, Any]] = []
    seen_job_ids = set()
    for row in rows:
        target_id = str(row.get("target_id") or "")
        if not target_id:
            _add_failure(failures, "receipt_missing_target_id", "receipt row has no target_id")
        if row.get("status") != "submitted":
            _add_failure(
                failures,
                "receipt_row_status_not_submitted",
                "receipt row status must be submitted",
                target_id=target_id,
                observed=row.get("status"),
            )
        if expected_workstream is not None and row.get("workstream") != expected_workstream:
            _add_failure(
                failures,
                "receipt_row_workstream_mismatch",
                "receipt row workstream mismatch",
                target_id=target_id,
                expected=expected_workstream,
                observed=row.get("workstream"),
            )
        for role, field in (("proteinmpnn", "proteinmpnn_job_id"), ("boltz", "boltz_job_id")):
            job_id = str(row.get(field) or "").strip()
            if not _job_id_ok(job_id):
                _add_failure(
                    failures,
                    "receipt_bad_job_id",
                    f"invalid {field}",
                    target_id=target_id,
                    observed=row.get(field),
                )
                continue
            if job_id in seen_job_ids:
                _add_failure(failures, "receipt_duplicate_job_id", "duplicate job id in receipt", job_id=job_id)
            seen_job_ids.add(job_id)
            jobs.append({"target_id": target_id, "role": role, "job_id": job_id})
    return jobs, failures


def _parse_sacct_output(text: str) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    header: Optional[List[str]] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|") if "|" in line else line.split()
        if not parts:
            continue
        lowered = [part.lower() for part in parts]
        if "state" in lowered and any(part in lowered for part in ("jobid", "jobidraw")):
            header = lowered
            continue
        if header:
            values = {header[index]: parts[index] for index in range(min(len(header), len(parts)))}
            job_id = values.get("jobidraw") or values.get("jobid") or parts[0]
            state = values.get("state") or (parts[1] if len(parts) > 1 else "")
            exit_code = values.get("exitcode") or values.get("exit_code") or ""
        else:
            job_id = parts[0]
            state = parts[1] if len(parts) > 1 else ""
            exit_code = parts[2] if len(parts) > 2 else ""
        base = _base_job_id(job_id)
        if not base:
            continue
        current = rows.get(base)
        if current and "." not in current.get("raw_job_id", "") and "." in str(job_id):
            continue
        rows[base] = {
            "raw_job_id": str(job_id),
            "state": _normalize_state(state),
            "exit_code": str(exit_code),
        }
    return rows


def _sacct_command(job_ids: List[str]) -> str:
    joined = ",".join(job_ids)
    return f"sacct -P -j {joined} --format=JobIDRaw,State,ExitCode,Elapsed,NodeList"


def render_query_plan(job_ids: List[str],
                      *,
                      out_tsv: str,
                      receipt_path: str = _DEFAULT_RECEIPT,
                      out_json: str = _DEFAULT_OUT_JSON,
                      out_md: str = _DEFAULT_OUT_MD) -> str:
    preview = ",".join(job_ids)
    return "\n".join([
        "#!/usr/bin/env bash",
        "# Query W2 v11 panel Slurm states after guarded submission.",
        "# This is read-only and does not submit jobs. It discovers job IDs from the submit receipt at runtime.",
        f"# Last rendered job-id preview: {preview or 'receipt not available yet'}",
        "set -euo pipefail",
        'PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"',
        'export PYTHONPATH="${PYTHONPATH:-src}"',
        'export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"',
        f"RECEIPT={shlex.quote(receipt_path)}",
        f"OUT=${{1:-{out_tsv}}}",
        f"OUT_JSON={shlex.quote(out_json)}",
        f"OUT_MD={shlex.quote(out_md)}",
        'test -s "$RECEIPT" || { echo "submit receipt is missing; run receipt monitor after guarded submit first: $RECEIPT" >&2; exit 2; }',
        "mkdir -p \"$(dirname \"$OUT\")\"",
        'mkdir -p "$(dirname "$OUT_JSON")" "$(dirname "$OUT_MD")"',
        (
            '"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe '
            '--receipt "$RECEIPT" --emit-query-plan "" --out-json "$OUT_JSON" --out-md "$OUT_MD"'
        ),
        'job_ids="$("$PYTHON_BIN" - "$OUT_JSON" <<\'PY\'',
        "import json",
        "import sys",
        "with open(sys.argv[1]) as handle:",
        "    rep = json.load(handle)",
        "ids = [str(job_id) for job_id in rep.get('job_ids', []) if str(job_id)]",
        "if not ids:",
        "    raise SystemExit('job-state query has no job IDs in the submit receipt')",
        "print(','.join(ids))",
        "PY",
        ')"',
        'sacct -P -j "$job_ids" --format=JobIDRaw,State,ExitCode,Elapsed,NodeList > "$OUT"',
        "test -s \"$OUT\"",
        (
            '"$PYTHON_BIN" -m bio_sfm_designer.experiments.m6d_w2_panel_job_state_probe '
            '--receipt "$RECEIPT" --sacct-output "$OUT" --sacct-output-path "$OUT" '
            '--emit-query-plan "" --out-json "$OUT_JSON" --out-md "$OUT_MD"'
        ),
        "",
    ])


def build_probe(*,
                receipt_path: str = _DEFAULT_RECEIPT,
                expected_workstream: Optional[str] = _DEFAULT_EXPECTED_WORKSTREAM,
                sacct_output: Optional[str] = None,
                query_plan_path: Optional[str] = _DEFAULT_QUERY_PLAN,
                sacct_output_path: str = "results/m6d_w2_target_family_redesign_v11_sacct_states.tsv") -> Dict[str, Any]:
    receipt_exists = os.path.exists(receipt_path)
    if not receipt_exists:
        return {
            "artifact": "m6d_w2_panel_job_state_probe",
            "status": "receipt_absent_not_submitted",
            "audit_ok": True,
            "no_submit": True,
            "submitted": False,
            "receipt": receipt_path,
            "receipt_exists": False,
            "n_receipt_rows": 0,
            "n_jobs": 0,
            "n_states": 0,
            "n_missing_states": 0,
            "job_ids": [],
            "states": {},
            "jobs": [],
            "query_plan": query_plan_path,
            "sacct_query_command": "",
            "postsubmit_status_command": "",
            "failures": [],
            "claim_boundary": "job-state probe only; no W2 evidence and no sync readiness without submit receipt states",
            "next_action": "await explicit approval and guarded panel submission before querying Slurm job states",
        }

    rows = _load_jsonl(receipt_path)
    jobs, failures = _receipt_jobs(rows, expected_workstream=expected_workstream)
    job_ids = [job["job_id"] for job in jobs]
    sacct_rows = _parse_sacct_output(sacct_output or "") if sacct_output is not None else {}
    states: Dict[str, str] = {}
    enriched_jobs: List[Dict[str, Any]] = []
    for job in jobs:
        job_id = job["job_id"]
        state_row = sacct_rows.get(_base_job_id(job_id), {})
        state = state_row.get("state", "")
        if state:
            states[job_id] = state
        enriched = dict(job)
        enriched.update({
            "state": state,
            "raw_job_id": state_row.get("raw_job_id", ""),
            "exit_code": state_row.get("exit_code", ""),
        })
        enriched_jobs.append(enriched)

    n_states = len(states)
    n_missing_states = len(job_ids) - n_states
    if failures:
        status = "job_state_probe_blocked"
    elif sacct_output is None:
        status = "receipt_ready_for_state_query"
    elif n_missing_states:
        status = "job_states_partial"
    else:
        status = "job_states_collected"
    audit_ok = not failures
    command = _sacct_command(job_ids) if job_ids else ""
    return {
        "artifact": "m6d_w2_panel_job_state_probe",
        "status": status,
        "audit_ok": audit_ok,
        "no_submit": True,
        "submitted": bool(rows),
        "receipt": receipt_path,
        "receipt_exists": True,
        "n_receipt_rows": len(rows),
        "n_jobs": len(job_ids),
        "n_states": n_states,
        "n_missing_states": n_missing_states,
        "job_ids": job_ids,
        "states": states,
        "jobs": enriched_jobs,
        "query_plan": query_plan_path,
        "sacct_query_command": command,
        "postsubmit_status_command": (
            "python -m bio_sfm_designer.experiments.m6d_w2_panel_postsubmit_status "
            "--job-states results/m6d_w2_target_family_redesign_v11_job_state_probe.json"
        ),
        "sacct_output_path": sacct_output_path,
        "failures": failures,
        "claim_boundary": "job-state probe only; sync readiness still requires m6d_w2_panel_postsubmit_status",
        "next_action": (
            "run postsubmit status with this job-state JSON"
            if audit_ok and n_states else
            "run the emitted sacct query plan after guarded submission writes the receipt"
            if audit_ok else
            "repair receipt/job-state probe blockers before monitoring or sync-back"
        ),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 Panel Job-State Probe",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        "",
        f"- receipt: `{rep.get('receipt')}` exists=`{rep.get('receipt_exists')}`",
        f"- receipt rows: `{rep.get('n_receipt_rows', 0)}`",
        f"- jobs: `{rep.get('n_jobs', 0)}`",
        f"- states collected: `{rep.get('n_states', 0)}`",
        f"- missing states: `{rep.get('n_missing_states', 0)}`",
        f"- query plan: `{rep.get('query_plan')}`",
        "",
    ]
    command = rep.get("sacct_query_command")
    if command:
        lines.extend(["## Sacct Query", "", f"`{command}`", ""])
    postsubmit = rep.get("postsubmit_status_command")
    if postsubmit:
        lines.extend(["## Postsubmit Replay", "", f"`{postsubmit}`", ""])
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
    ap.add_argument("--receipt", default=_DEFAULT_RECEIPT)
    ap.add_argument("--expected-workstream", default=_DEFAULT_EXPECTED_WORKSTREAM)
    ap.add_argument("--sacct-output", default=None, help="Optional sacct -P output to parse")
    ap.add_argument("--sacct-output-path", default="results/m6d_w2_target_family_redesign_v11_sacct_states.tsv")
    ap.add_argument("--emit-query-plan", default=_DEFAULT_QUERY_PLAN)
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    sacct_text = None
    if args.sacct_output:
        with open(args.sacct_output) as fh:
            sacct_text = fh.read()
    rep = build_probe(
        receipt_path=args.receipt,
        expected_workstream=args.expected_workstream,
        sacct_output=sacct_text,
        query_plan_path=args.emit_query_plan,
        sacct_output_path=args.sacct_output_path,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    if args.emit_query_plan:
        _write_text(
            args.emit_query_plan,
            render_query_plan(
                rep.get("job_ids") or [],
                out_tsv=args.sacct_output_path,
                receipt_path=args.receipt,
                out_json=args.out_json,
                out_md=args.out_md,
            ),
            executable=True,
        )
    print(
        "status={status} audit_ok={ok} receipt_exists={receipt} jobs={jobs} states={states}".format(
            status=rep["status"],
            ok=rep["audit_ok"],
            receipt=rep["receipt_exists"],
            jobs=rep.get("n_jobs", 0),
            states=rep.get("n_states", 0),
        )
    )
    return 0 if rep.get("audit_ok") else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
