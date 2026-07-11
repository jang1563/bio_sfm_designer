"""Append-only, resumable submit journal for W2 ProteinMPNN -> Boltz job pairs."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_PROTEINMPNN_STAGE = "proteinmpnn_submitted"
_PAIR_STAGES = {"pair_submitted", "submitted"}


def _job_id(value: Any, field: str) -> str:
    text = str(value or "")
    if not text.strip() or any(ch.isspace() for ch in text):
        raise ValueError(f"invalid {field}: {value!r}")
    return text


def load_events(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    events: List[Dict[str, Any]] = []
    with open(path) as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"{path}:{line_no}: event must be an object")
            events.append(event)
    return events


def target_state(
    events: Iterable[Dict[str, Any]],
    target_id: str,
    *,
    workstream: Optional[str] = None,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "stage": "not_submitted",
        "target_id": str(target_id),
        "proteinmpnn_job_id": None,
        "boltz_job_id": None,
    }
    for event in events:
        if str(event.get("target_id") or "") != str(target_id):
            continue
        if workstream is not None and event.get("workstream") != workstream:
            raise ValueError(f"target_id={target_id} has a conflicting workstream")
        stage = str(event.get("stage") or event.get("status") or "")
        if stage == _PROTEINMPNN_STAGE:
            gen_job = _job_id(event.get("proteinmpnn_job_id"), "proteinmpnn_job_id")
            previous = state.get("proteinmpnn_job_id")
            if previous is not None and previous != gen_job:
                raise ValueError(f"target_id={target_id} has conflicting ProteinMPNN job ids")
            if state["stage"] == "pair_submitted":
                raise ValueError(f"target_id={target_id} has a ProteinMPNN event after pair completion")
            state.update(stage=_PROTEINMPNN_STAGE, proteinmpnn_job_id=gen_job)
        elif stage in _PAIR_STAGES:
            gen_job = _job_id(event.get("proteinmpnn_job_id"), "proteinmpnn_job_id")
            pred_job = _job_id(event.get("boltz_job_id"), "boltz_job_id")
            previous_gen = state.get("proteinmpnn_job_id")
            previous_pred = state.get("boltz_job_id")
            if previous_gen is not None and previous_gen != gen_job:
                raise ValueError(f"target_id={target_id} pair has a conflicting ProteinMPNN job id")
            if previous_pred is not None and previous_pred != pred_job:
                raise ValueError(f"target_id={target_id} has conflicting Boltz job ids")
            state.update(
                stage="pair_submitted",
                proteinmpnn_job_id=gen_job,
                boltz_job_id=pred_job,
                event=event,
            )
        else:
            raise ValueError(f"target_id={target_id} has unsupported journal stage {stage!r}")
    return state


def append_event(path: str, event: Dict[str, Any]) -> Dict[str, Any]:
    target_id = str(event.get("target_id") or "")
    workstream = str(event.get("workstream") or "")
    stage = str(event.get("stage") or "")
    if not target_id or not workstream:
        raise ValueError("journal event requires target_id and workstream")
    if stage not in {_PROTEINMPNN_STAGE, "pair_submitted"}:
        raise ValueError(f"unsupported journal stage {stage!r}")
    _job_id(event.get("proteinmpnn_job_id"), "proteinmpnn_job_id")
    if stage == "pair_submitted":
        _job_id(event.get("boltz_job_id"), "boltz_job_id")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    record = dict(event)
    record["timestamp_unix"] = int(record.get("timestamp_unix") or time.time())
    with open(path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = [json.loads(line) for line in handle if line.strip()]
        before = target_state(existing, target_id, workstream=workstream)
        if before["stage"] == "pair_submitted":
            if (
                before["proteinmpnn_job_id"] == str(record["proteinmpnn_job_id"])
                and before["boltz_job_id"] == str(record.get("boltz_job_id"))
            ):
                return before
            raise ValueError(f"target_id={target_id} is already pair_submitted")
        if stage == _PROTEINMPNN_STAGE and before["stage"] == _PROTEINMPNN_STAGE:
            if before["proteinmpnn_job_id"] == str(record["proteinmpnn_job_id"]):
                return before
            raise ValueError(f"target_id={target_id} already has a different ProteinMPNN job")
        if stage == "pair_submitted" and before["proteinmpnn_job_id"] not in (
            None,
            str(record["proteinmpnn_job_id"]),
        ):
            raise ValueError(f"target_id={target_id} pair conflicts with the recorded ProteinMPNN job")
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target_state(load_events(path), target_id, workstream=workstream)


def _manifest_specs(manifest: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    specs: Dict[str, Dict[str, str]] = {}
    for target in manifest.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_id = str(target["id"])
        out_prefix = str(target.get("out_prefix") or f"hpc_outputs/{target_id}")
        specs[target_id] = {
            "candidates": str(
                target.get("candidates")
                or f"{out_prefix}/candidates_proteinmpnn_complex.jsonl"
            ),
            "records": str(
                target.get("records") or f"{out_prefix}/records_boltz_complex.jsonl"
            ),
            "target_msa": str(target["target_msa"]),
            "prepared_pdb": str(target["prepared_pdb"]),
        }
    return specs


def build_summary(
    manifest_path: str,
    receipt_path: str,
    *,
    workstream: str,
    artifact: str,
) -> Dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text())
    specs = _manifest_specs(manifest)
    events = load_events(receipt_path)
    states = {
        target_id: target_state(events, target_id, workstream=workstream)
        for target_id in specs
    }
    incomplete = [target_id for target_id, state in states.items() if state["stage"] != "pair_submitted"]
    if incomplete:
        raise ValueError("submit journal has incomplete targets: " + ",".join(sorted(incomplete)))
    unexpected = sorted(
        {str(event.get("target_id") or "") for event in events}
        - set(specs)
        - {""}
    )
    if unexpected:
        raise ValueError("submit journal has unexpected targets: " + ",".join(unexpected))
    for target_id, spec in specs.items():
        event = states[target_id].get("event") or {}
        for field, expected in spec.items():
            if str(event.get(field) or "") != expected:
                raise ValueError(
                    f"target_id={target_id} {field} mismatch: "
                    f"expected={expected!r} actual={event.get(field)!r}"
                )
    return {
        "artifact": artifact,
        "status": "submitted_on_cayuga",
        "manifest": manifest_path,
        "receipt": receipt_path,
        "receipt_format": "append_only_stage_journal_v1",
        "workstream": workstream,
        "n_targets": len(specs),
        "n_records": len(specs),
        "n_receipt_events": len(events),
        "targets": [
            {
                "target_id": target_id,
                "proteinmpnn_job_id": states[target_id]["proteinmpnn_job_id"],
                "boltz_job_id": states[target_id]["boltz_job_id"],
                "records": specs[target_id]["records"],
            }
            for target_id in sorted(specs)
        ],
        "next_action": "wait for jobs, sync records, then run completion and panel reports",
        "claim_boundary": "job submission is not W2 evidence",
    }


def write_summary(path: str, summary: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".submit-summary-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _event_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "artifact": args.artifact,
        "stage": args.stage,
        "status": args.stage,
        "workstream": args.workstream,
        "target_id": args.target_id,
        "proteinmpnn_job_id": args.proteinmpnn_job_id,
        "boltz_job_id": args.boltz_job_id,
        "candidates": args.candidates,
        "records": args.records,
        "target_msa": args.target_msa,
        "prepared_pdb": args.prepared_pdb,
        "manifest": args.manifest,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    state_parser = sub.add_parser("state")
    state_parser.add_argument("--receipt", required=True)
    state_parser.add_argument("--target-id", required=True)
    state_parser.add_argument("--workstream", required=True)

    append_parser = sub.add_parser("append")
    append_parser.add_argument("--receipt", required=True)
    append_parser.add_argument("--stage", choices=[_PROTEINMPNN_STAGE, "pair_submitted"], required=True)
    append_parser.add_argument("--artifact", required=True)
    append_parser.add_argument("--workstream", required=True)
    append_parser.add_argument("--target-id", required=True)
    append_parser.add_argument("--proteinmpnn-job-id", required=True)
    append_parser.add_argument("--boltz-job-id")
    append_parser.add_argument("--candidates", required=True)
    append_parser.add_argument("--records", required=True)
    append_parser.add_argument("--target-msa", required=True)
    append_parser.add_argument("--prepared-pdb", required=True)
    append_parser.add_argument("--manifest", required=True)

    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("--manifest", required=True)
    summary_parser.add_argument("--receipt", required=True)
    summary_parser.add_argument("--out", required=True)
    summary_parser.add_argument("--workstream", required=True)
    summary_parser.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)

    if args.command == "state":
        state = target_state(load_events(args.receipt), args.target_id, workstream=args.workstream)
        print("\t".join(str(state.get(key) or "") for key in (
            "stage", "proteinmpnn_job_id", "boltz_job_id"
        )))
    elif args.command == "append":
        append_event(args.receipt, _event_from_args(args))
    else:
        summary = build_summary(
            args.manifest,
            args.receipt,
            workstream=args.workstream,
            artifact=args.artifact,
        )
        write_summary(args.out, summary)
        print(f"submit journal validated: {args.receipt} ({summary['n_targets']} targets)")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    main()
