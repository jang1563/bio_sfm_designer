"""Fail-closed no-submit audit for W2 v11 panel approval messages.

This module never submits jobs. It checks whether an operator message is
specific enough to be considered explicit approval for the guarded W2 v11
Cayuga ProteinMPNN/Boltz panel submission path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


_DEFAULT_DECISION_STATE = "results/m6d_w2_target_family_redesign_v11_submission_decision_state.json"
_DEFAULT_OUT_JSON = "results/m6d_w2_target_family_redesign_v11_approval_intent_audit.json"
_DEFAULT_OUT_MD = "results/m6d_w2_target_family_redesign_v11_approval_intent_audit.md"
_REQUIRED_APPROVAL_PHRASE = "W2 v11 Cayuga ProteinMPNN/Boltz panel submission"
_REQUIRED_MACHINE_GATE = "BIO_SFM_APPROVE_V11_PANEL=approve-v11-panel-submit"
_NON_APPROVAL_CONTINUATIONS = [
    "resume goal",
    "resume goal mode",
    "goal mode resume",
    "go ahead",
    "continue",
    "continue working toward the active thread goal",
    "keep going",
    "이어서",
    "계속",
]
_APPROVAL_TERM_RE = re.compile(r"\b(approve|approved|approval|authorize|authorized|authorization)\b")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def _contains(text: str, needle: str) -> bool:
    return _norm(needle) in _norm(text)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _failure(failures: List[Dict[str, Any]], kind: str, message: str, **extra: Any) -> None:
    row: Dict[str, Any] = {"kind": kind, "message": message}
    row.update({key: value for key, value in extra.items() if value is not None})
    failures.append(row)


def _decision_ready(decision_state: Dict[str, Any]) -> bool:
    return (
        decision_state.get("status") == "awaiting_explicit_panel_submission_approval"
        and decision_state.get("audit_ok") is True
        and decision_state.get("decision") == "awaiting_explicit_approval"
        and decision_state.get("no_submit") is True
        and decision_state.get("submitted") is False
        and decision_state.get("can_submit_panel_if_user_explicitly_approves") is True
        and decision_state.get("can_claim_w2_generalization") is False
    )


def _acknowledgement_checks(message: str, machine_gate: str) -> Dict[str, bool]:
    text = _norm(message)
    text_without_gate = text.replace(_norm(machine_gate), " ")
    return {
        "approval_term_present": bool(_APPROVAL_TERM_RE.search(text_without_gate)) or "승인" in text_without_gate,
        "guarded_submit_acknowledged": (
            ("guarded" in text and "submit" in text)
            or _contains(message, machine_gate)
        ),
        "receipt_and_jobs_acknowledged": (
            "receipt" in text and ("slurm" in text or "job" in text or "jobs" in text)
        ),
        "compute_spend_acknowledged": any(term in text for term in ["gpu", "compute", "spend", "cost", "비용", "컴퓨트"]),
        "sync_back_and_certification_acknowledged": (
            ("sync-back" in text or "sync back" in text)
            and ("target-wise" in text or "certification" in text or "certify" in text)
        ),
    }


def audit_approval_intent(
    *,
    message: str,
    decision_state: Optional[Dict[str, Any]] = None,
    decision_state_path: Optional[str] = None,
) -> Dict[str, Any]:
    decision_state = decision_state or {}
    checklist = (
        decision_state.get("operator_approval_checklist")
        if isinstance(decision_state.get("operator_approval_checklist"), dict)
        else {}
    )
    disambiguation = (
        decision_state.get("approval_disambiguation")
        if isinstance(decision_state.get("approval_disambiguation"), dict)
        else {}
    )
    required_phrase = (
        disambiguation.get("approval_must_explicitly_name")
        or checklist.get("approval_phrase_required")
        or _REQUIRED_APPROVAL_PHRASE
    )
    machine_gate = disambiguation.get("machine_gate") or checklist.get("machine_gate") or _REQUIRED_MACHINE_GATE
    non_approval = disambiguation.get("non_approval_continuation_phrases") or _NON_APPROVAL_CONTINUATIONS
    ack_checks = _acknowledgement_checks(message, machine_gate)
    failures: List[Dict[str, Any]] = []
    message_norm = _norm(message)
    exact_non_approval_matches = [phrase for phrase in non_approval if message_norm == _norm(phrase)]

    if decision_state:
        if not _decision_ready(decision_state):
            _failure(
                failures,
                "decision_state_not_ready",
                "submission-decision state is not ready for explicit approval",
                observed={
                    "status": decision_state.get("status"),
                    "audit_ok": decision_state.get("audit_ok"),
                    "decision": decision_state.get("decision"),
                    "no_submit": decision_state.get("no_submit"),
                    "submitted": decision_state.get("submitted"),
                },
            )
    else:
        _failure(
            failures,
            "decision_state_missing",
            "approval intent must be checked against the current submission-decision state",
            path=decision_state_path,
        )

    if not message.strip():
        _failure(failures, "message_empty", "operator approval message is empty")
    if exact_non_approval_matches:
        _failure(
            failures,
            "non_approval_continuation_phrase",
            "message is an explicit non-approval continuation phrase",
            observed=exact_non_approval_matches,
        )
    if not _contains(message, required_phrase):
        _failure(
            failures,
            "approval_phrase_missing",
            "message must explicitly name the W2 v11 Cayuga ProteinMPNN/Boltz panel submission",
            expected=required_phrase,
        )
    for key, ok in ack_checks.items():
        if not ok:
            _failure(failures, key + "_missing", "message does not satisfy required approval acknowledgement")

    accepted = not failures
    return {
        "artifact": "m6d_w2_v11_approval_intent_audit",
        "date": date.today().isoformat(),
        "status": "approval_intent_accepted" if accepted else "approval_intent_rejected",
        "audit_ok": accepted,
        "approval_intent_accepted": accepted,
        "does_not_submit": True,
        "no_submit": True,
        "submitted": False,
        "decision_state_path": decision_state_path or "",
        "decision_state_status": decision_state.get("status"),
        "required_approval_phrase": required_phrase,
        "required_machine_gate": machine_gate,
        "approval_phrase_present": _contains(message, required_phrase),
        "non_approval_continuation_phrase_matched": exact_non_approval_matches,
        "acknowledgement_checks": ack_checks,
        "message_sha256": __import__("hashlib").sha256(message.encode("utf-8")).hexdigest(),
        "message_preview": message[:240],
        "claim_boundary": {
            "intent_audit": "classifies an operator message only; it never submits jobs",
            "panel_submission": "still requires running the guarded submit command after accepted approval intent",
            "w2_generalization": "not supported until synced records pass target-wise certification",
        },
        "next_action": (
            "approval intent accepted; run only the separately guarded submit command if the operator proceeds"
            if accepted
            else "keep waiting for an explicit approval message before any guarded W2 panel submission"
        ),
        "failures": failures,
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# M6d W2 v11 Approval Intent Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Approval intent accepted: `{rep.get('approval_intent_accepted')}`.",
        f"No submit: `{rep.get('no_submit')}`.",
        f"Submitted: `{rep.get('submitted')}`.",
        f"Required approval phrase: `{rep.get('required_approval_phrase')}`.",
        f"Required machine gate: `{rep.get('required_machine_gate')}`.",
        f"Message SHA256: `{rep.get('message_sha256')}`.",
        "",
        "## Acknowledgement Checks",
        "",
    ]
    checks = rep.get("acknowledgement_checks") if isinstance(rep.get("acknowledgement_checks"), dict) else {}
    for key, ok in checks.items():
        lines.append(f"- {key}: `{ok}`")
    failures = rep.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('kind')}`: {failure.get('message')}")
    lines.extend(["", "## Next Action", "", str(rep.get("next_action") or ""), ""])
    return "\n".join(lines)


def _read_message(args: argparse.Namespace) -> str:
    if args.message_file:
        with open(args.message_file) as fh:
            return fh.read()
    if args.message is not None:
        return args.message
    return sys.stdin.read()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--message", default=None)
    ap.add_argument("--message-file", default=None)
    ap.add_argument("--decision-state", default=_DEFAULT_DECISION_STATE)
    ap.add_argument("--skip-decision-state", action="store_true")
    ap.add_argument("--require-accepted", action="store_true")
    ap.add_argument("--out-json", default=_DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=_DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    message = _read_message(args)
    decision_state = None
    if not args.skip_decision_state:
        decision_state = _load_json(args.decision_state)
    rep = audit_approval_intent(
        message=message,
        decision_state=decision_state,
        decision_state_path=None if args.skip_decision_state else args.decision_state,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(
        "status={status} audit_ok={audit_ok} approval_intent_accepted={accepted} no_submit={no_submit} submitted={submitted}".format(
            status=rep.get("status"),
            audit_ok=rep.get("audit_ok"),
            accepted=rep.get("approval_intent_accepted"),
            no_submit=rep.get("no_submit"),
            submitted=rep.get("submitted"),
        )
    )
    if args.require_accepted and not rep.get("approval_intent_accepted"):
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
