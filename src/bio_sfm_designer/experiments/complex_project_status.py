"""Project-level status audit for the M6 complex/binder roadmap.

The individual tools answer narrow questions: did QC pass, is alpha certified,
is the target panel valid, can the single-model caveat close, did a closed-loop
round consume synchronized artifacts? This module reads their JSON artifacts and
maps them onto the W1/W2/W3/W4 roadmap gates so the next Codex/Cayuga action is
explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from .complex_target_manifest import render_target_msa_plan


_W2_PANEL_APPROVAL_READY_STATUS = "panel_approval_packet_ready"
_W2_PANEL_DECISION_PROTOCOL_READY_STATUS = "post_panel_decision_protocol_ready"
_W2_REMOTE_SUBMISSION_READY_STATUS = "remote_submission_readiness_ok"
_W2_PANEL_SUBMISSION_DECISION_READY_STATUS = "awaiting_explicit_panel_submission_approval"


def _write_text_atomic(path: str, text: str) -> None:
    """Replace an output file without truncating a script that may be running."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    mode = 0o644
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        pass
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _write_json_atomic(path: str, obj: Dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _missing_artifact(path: str, role: str) -> Dict[str, Any]:
    return {
        "_path": os.path.abspath(path),
        "_missing_artifact": True,
        "artifact_role": role,
        "ok": False,
        "status": "missing_artifact",
        "message": f"{role} artifact does not exist: {path}",
    }


def _is_missing_artifact(obj: Optional[Dict[str, Any]]) -> bool:
    return isinstance(obj, dict) and obj.get("_missing_artifact") is True


def _load_json(path: Optional[str], *, role: str = "artifact",
               missing_ok: bool = True) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    if not os.path.exists(path):
        if missing_ok:
            return _missing_artifact(path, role)
        raise FileNotFoundError(path)
    with open(path) as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must contain a JSON object")
    obj["_path"] = os.path.abspath(path)
    return obj


def _load_jsonl_records(path: str) -> list:
    records = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: bad JSONL: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: JSONL record is not an object")
            records.append(record)
    return records


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _target_msa_precompute_receipt_path(script_path: Optional[str]) -> Optional[str]:
    if not script_path:
        return None
    root, _ext = os.path.splitext(script_path)
    return f"{root}_receipt.jsonl"


def _target_msa_precompute_dry_run_command(script_path: Optional[str]) -> Optional[str]:
    if not isinstance(script_path, str) or not script_path.strip():
        return None
    return f"TARGET_MSA_PRECOMPUTE_DRY_RUN=1 bash {script_path}"


_TARGET_MSA_RECEIPT_REVIEW_BLOCKER = "target_msa_receipt_requires_review"
_TARGET_MSA_RECEIPT_VALIDATION_AUDIT_BLOCKER = "target_msa_receipt_validation_audit_failed"
_TARGET_MSA_RECEIPT_REVIEW_ACTION = (
    "inspect or archive the existing target-MSA precompute receipt before resubmitting; "
    "set TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1 only after confirming recorded jobs will not be duplicated"
)


def _target_msa_receipt_requires_review(receipt: Any) -> bool:
    if not isinstance(receipt, dict):
        return False
    if receipt.get("ok") is True:
        return False
    if receipt.get("status") in {"missing_receipt", "plan_conflict"}:
        return False
    try:
        size_bytes = int(receipt.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size_bytes = 0
    return receipt.get("exists") is True and size_bytes > 0


def _existing_nonempty_file(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _target_msa_outputs_satisfied(plan: Any) -> bool:
    if not isinstance(plan, dict):
        return False
    expected = plan.get("expected_receipt_targets")
    if not isinstance(expected, dict) or not expected:
        return False
    for target in expected.values():
        if not isinstance(target, dict):
            return False
        if not _existing_nonempty_file(target.get("target_msa")):
            return False
        if not _existing_nonempty_file(target.get("target_msa_report")):
            return False
    return True


def _submitted_job_id_error(job_id: Any) -> Optional[str]:
    if job_id is None:
        return "missing_job_id"
    text = str(job_id)
    if not text.strip():
        return "missing_job_id"
    if any(ch.isspace() for ch in text):
        return "invalid_job_id"
    return None


def _decision_from_manifest(manifest: Optional[Dict[str, Any]]) -> Optional[str]:
    if not manifest or _is_missing_artifact(manifest):
        return None
    paths = manifest.get("paths")
    if isinstance(paths, dict):
        decision_path = paths.get("decision")
        if isinstance(decision_path, str) and os.path.exists(decision_path):
            return decision_path
    return None


def _target_alpha_value(obj: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(obj, dict):
        return None
    value = obj.get("target_alpha")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _alpha_mismatch(obj: Optional[Dict[str, Any]], target_alpha: float) -> Optional[float]:
    artifact_alpha = _target_alpha_value(obj)
    if artifact_alpha is None:
        return None
    if abs(artifact_alpha - float(target_alpha)) > 1e-12:
        return artifact_alpha
    return None


def _absolute_path_set(paths: Any) -> set:
    if not isinstance(paths, list):
        return set()
    return {
        os.path.abspath(str(path))
        for path in paths
        if isinstance(path, str) and path.strip()
    }


def _decision_consumes_scale_completion(decision: Optional[Dict[str, Any]],
                                        scale_completion: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(decision, dict) or not isinstance(scale_completion, dict):
        return False
    expected_records = _absolute_path_set(scale_completion.get("expected_records"))
    if not expected_records:
        return False
    decision_records = _absolute_path_set(decision.get("records"))
    if not decision_records:
        return False
    return expected_records.issubset(decision_records)


def _alpha_mismatch_status(*, workstream: str, status: str, artifact_alpha: float,
                           target_alpha: float, evidence: Optional[str],
                           next_action: str) -> Dict[str, Any]:
    return {
        "workstream": workstream,
        "status": status,
        "complete": False,
        "target_alpha": artifact_alpha,
        "requested_target_alpha": target_alpha,
        "message": (
            f"artifact target_alpha={artifact_alpha} does not match "
            f"requested target_alpha={target_alpha}"
        ),
        "next_action": next_action,
        "evidence": evidence,
    }


def _finite_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _float_close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance


def _w1_alpha_decision_audit_failures(decision: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if decision.get("ok") is not True:
        failures.append({"kind": "alpha_decision_not_ok", "field": "ok"})
    if decision.get("decision") != "stop_certified":
        failures.append({
            "kind": "alpha_decision_not_terminal",
            "field": "decision",
            "actual": decision.get("decision"),
        })

    reported_failures = decision.get("failures")
    if reported_failures is not None:
        if not isinstance(reported_failures, list):
            failures.append({"kind": "alpha_decision_failures_not_list", "field": "failures"})
        elif reported_failures:
            failures.append({
                "kind": "alpha_decision_reported_failures",
                "field": "failures",
                "n_failures": len(reported_failures),
            })

    target_alpha = _finite_float(decision.get("target_alpha"))
    if target_alpha is None or target_alpha <= 0.0 or target_alpha > 1.0:
        failures.append({
            "kind": "alpha_decision_target_alpha_invalid",
            "field": "target_alpha",
            "actual": decision.get("target_alpha"),
        })

    certified_alphas_raw = decision.get("certified_alphas")
    certified_alphas: List[float] = []
    if not isinstance(certified_alphas_raw, list) or not certified_alphas_raw:
        failures.append({"kind": "alpha_decision_certified_alphas_invalid", "field": "certified_alphas"})
    else:
        for value in certified_alphas_raw:
            alpha = _finite_float(value)
            if alpha is None or alpha <= 0.0 or alpha > 1.0:
                failures.append({
                    "kind": "alpha_decision_certified_alpha_invalid",
                    "field": "certified_alphas",
                    "actual": value,
                })
            else:
                certified_alphas.append(alpha)
        if target_alpha is not None and not any(_float_close(alpha, target_alpha) for alpha in certified_alphas):
            failures.append({
                "kind": "alpha_decision_target_alpha_not_certified",
                "field": "certified_alphas",
                "target_alpha": target_alpha,
            })

    n_records = _positive_int(decision.get("n_records"))
    n_cal = _positive_int(decision.get("n_cal"))
    n_test = _positive_int(decision.get("n_test"))
    if n_records is None:
        failures.append({"kind": "alpha_decision_n_records_invalid", "field": "n_records"})
    if n_cal is None:
        failures.append({"kind": "alpha_decision_n_cal_invalid", "field": "n_cal"})
    if n_test is None:
        failures.append({"kind": "alpha_decision_n_test_invalid", "field": "n_test"})
    if n_records is not None and n_cal is not None and n_test is not None and n_records != n_cal + n_test:
        failures.append({
            "kind": "alpha_decision_split_count_mismatch",
            "field": "n_records",
            "n_records": n_records,
            "n_cal": n_cal,
            "n_test": n_test,
        })

    delta = _finite_float(decision.get("delta"))
    if delta is None or delta <= 0.0 or delta > 1.0:
        failures.append({"kind": "alpha_decision_delta_invalid", "field": "delta"})
    threshold = _finite_float(decision.get("threshold"))
    if threshold is None or threshold <= 0.0:
        failures.append({"kind": "alpha_decision_threshold_invalid", "field": "threshold"})

    qc = decision.get("qc")
    if not isinstance(qc, dict) or qc.get("ok") is not True:
        failures.append({"kind": "alpha_decision_qc_invalid", "field": "qc"})
    else:
        qc_failures = _nonnegative_int(qc.get("n_failures"))
        if qc_failures is None or qc_failures != 0:
            failures.append({
                "kind": "alpha_decision_qc_failures_present",
                "field": "qc.n_failures",
                "actual": qc.get("n_failures"),
            })

    label_audit = decision.get("label_threshold_audit")
    if not isinstance(label_audit, dict) or label_audit.get("ok") is not True:
        failures.append({
            "kind": "alpha_decision_label_threshold_audit_invalid",
            "field": "label_threshold_audit",
        })
    else:
        audit_threshold = _finite_float(label_audit.get("expected_threshold"))
        if threshold is not None and audit_threshold is not None and not _float_close(audit_threshold, threshold):
            failures.append({
                "kind": "alpha_decision_label_threshold_mismatch",
                "field": "label_threshold_audit.expected_threshold",
                "actual": audit_threshold,
                "expected": threshold,
            })
        record_thresholds = label_audit.get("record_thresholds")
        if not isinstance(record_thresholds, list) or not record_thresholds:
            failures.append({
                "kind": "alpha_decision_record_thresholds_invalid",
                "field": "label_threshold_audit.record_thresholds",
            })
        else:
            for value in record_thresholds:
                record_threshold = _finite_float(value)
                if record_threshold is None or audit_threshold is None or not _float_close(record_threshold, audit_threshold):
                    failures.append({
                        "kind": "alpha_decision_record_threshold_mismatch",
                        "field": "label_threshold_audit.record_thresholds",
                        "actual": value,
                        "expected": audit_threshold,
                    })
                    break
        audit_records = _positive_int(label_audit.get("n_records"))
        if audit_records is None:
            failures.append({
                "kind": "alpha_decision_label_audit_n_records_invalid",
                "field": "label_threshold_audit.n_records",
            })
        elif n_records is not None and audit_records != n_records:
            failures.append({
                "kind": "alpha_decision_label_audit_n_records_mismatch",
                "field": "label_threshold_audit.n_records",
                "actual": audit_records,
                "expected": n_records,
            })
        n_mismatches = _nonnegative_int(label_audit.get("n_mismatches"))
        if n_mismatches is None or n_mismatches != 0:
            failures.append({
                "kind": "alpha_decision_label_threshold_mismatches_present",
                "field": "label_threshold_audit.n_mismatches",
                "actual": label_audit.get("n_mismatches"),
            })

    target_sweep = decision.get("target_sweep")
    if not isinstance(target_sweep, dict):
        failures.append({"kind": "alpha_decision_target_sweep_missing", "field": "target_sweep"})
    else:
        sweep_alpha = _finite_float(target_sweep.get("alpha"))
        if target_alpha is not None and (sweep_alpha is None or not _float_close(sweep_alpha, target_alpha)):
            failures.append({
                "kind": "alpha_decision_target_sweep_alpha_mismatch",
                "field": "target_sweep.alpha",
                "actual": target_sweep.get("alpha"),
                "expected": target_alpha,
            })
        if target_sweep.get("certified") is not True:
            failures.append({"kind": "alpha_decision_target_sweep_not_certified", "field": "target_sweep.certified"})
        if _finite_float(target_sweep.get("tau")) is None:
            failures.append({"kind": "alpha_decision_target_sweep_tau_invalid", "field": "target_sweep.tau"})
        trusted = _positive_int(target_sweep.get("trusted"))
        if trusted is None:
            failures.append({"kind": "alpha_decision_target_sweep_trusted_invalid", "field": "target_sweep.trusted"})
        sweep_n_test = _positive_int(target_sweep.get("n_test"))
        if sweep_n_test is None:
            failures.append({"kind": "alpha_decision_target_sweep_n_test_invalid", "field": "target_sweep.n_test"})
        elif n_test is not None and sweep_n_test != n_test:
            failures.append({
                "kind": "alpha_decision_target_sweep_n_test_mismatch",
                "field": "target_sweep.n_test",
                "actual": sweep_n_test,
                "expected": n_test,
            })
        false_accept_rate = _finite_float(target_sweep.get("false_accept_rate"))
        if false_accept_rate is None or false_accept_rate < 0.0:
            failures.append({
                "kind": "alpha_decision_target_sweep_false_accept_invalid",
                "field": "target_sweep.false_accept_rate",
            })
        elif target_alpha is not None and false_accept_rate > target_alpha + 1e-12:
            failures.append({
                "kind": "alpha_decision_target_sweep_false_accept_above_alpha",
                "field": "target_sweep.false_accept_rate",
                "actual": false_accept_rate,
                "target_alpha": target_alpha,
            })

    target_plan = decision.get("target_plan")
    if not isinstance(target_plan, dict):
        failures.append({"kind": "alpha_decision_target_plan_missing", "field": "target_plan"})
    else:
        plan_alpha = _finite_float(target_plan.get("alpha"))
        if target_alpha is not None and (plan_alpha is None or not _float_close(plan_alpha, target_alpha)):
            failures.append({
                "kind": "alpha_decision_target_plan_alpha_mismatch",
                "field": "target_plan.alpha",
                "actual": target_plan.get("alpha"),
                "expected": target_alpha,
            })
        if target_plan.get("certified") is not True:
            failures.append({"kind": "alpha_decision_target_plan_not_certified", "field": "target_plan.certified"})
        plan_additional = _nonnegative_int(target_plan.get("estimated_additional_records"))
        if plan_additional is None or plan_additional != 0:
            failures.append({
                "kind": "alpha_decision_target_plan_not_terminal",
                "field": "target_plan.estimated_additional_records",
                "actual": target_plan.get("estimated_additional_records"),
            })

    additional = _nonnegative_int(decision.get("estimated_additional_records"))
    if additional is None or additional != 0:
        failures.append({
            "kind": "alpha_decision_additional_records_not_terminal",
            "field": "estimated_additional_records",
            "actual": decision.get("estimated_additional_records"),
        })

    next_batch = decision.get("next_batch")
    if not isinstance(next_batch, dict):
        failures.append({"kind": "alpha_decision_next_batch_missing", "field": "next_batch"})
    else:
        if next_batch.get("action") != "none":
            failures.append({
                "kind": "alpha_decision_next_batch_not_terminal",
                "field": "next_batch.action",
                "actual": next_batch.get("action"),
            })
        batch_alpha = _finite_float(next_batch.get("target_alpha"))
        if target_alpha is not None and (batch_alpha is None or not _float_close(batch_alpha, target_alpha)):
            failures.append({
                "kind": "alpha_decision_next_batch_alpha_mismatch",
                "field": "next_batch.target_alpha",
                "actual": next_batch.get("target_alpha"),
                "expected": target_alpha,
            })
        recommended = _nonnegative_int(next_batch.get("recommended_total_candidates"))
        if recommended is None or recommended != 0:
            failures.append({
                "kind": "alpha_decision_next_batch_recommends_more_work",
                "field": "next_batch.recommended_total_candidates",
                "actual": next_batch.get("recommended_total_candidates"),
            })

    return failures


def _target_manifest_waiting_on_msa_artifacts(target_manifest: Dict[str, Any]) -> bool:
    failures = target_manifest.get("failures")
    if not isinstance(failures, list) or not failures:
        return False
    allowed_fields = {"target_fasta_report", "target_msa", "target_msa_report"}
    allowed_kinds = {
        "missing_file",
        "empty_file",
        "bad_target_fasta_report",
        "target_fasta_report_missing_field",
        "target_fasta_report_mismatch",
        "bad_target_msa_report",
        "target_msa_report_not_ok",
        "target_msa_report_missing_field",
        "target_msa_report_mismatch",
    }
    for failure in failures:
        if not isinstance(failure, dict):
            return False
        if failure.get("kind") not in allowed_kinds:
            return False
        if failure.get("field") not in allowed_fields:
            return False
    return True


def _input_prep_completion_status(input_prep_completion: Dict[str, Any], *,
                                  workstream: str, status_prefix: str,
                                  ready_next_action: str) -> Dict[str, Any]:
    if _is_missing_artifact(input_prep_completion):
        return {
            "workstream": workstream,
            "status": f"{status_prefix}_input_prep_completion_missing",
            "complete": False,
            "message": input_prep_completion.get("message", ""),
            "next_action": "run complex_input_prep_completion.py after target input-prep artifacts are synced",
            "evidence": input_prep_completion.get("_path"),
        }
    ready = (
        input_prep_completion.get("ok") is True
        and input_prep_completion.get("status") == "ready_for_require_files"
    )
    status = (
        f"{status_prefix}_input_prep_ready_for_manifest" if ready
        else f"{status_prefix}_input_prep_completion_blocked"
    )
    next_action = ready_next_action if ready else input_prep_completion.get(
        "next_action",
        "sync/fix missing or empty input-prep artifacts before rerunning --require-files",
    )
    return {
        "workstream": workstream,
        "status": status,
        "complete": False,
        "n_artifacts": input_prep_completion.get("n_artifacts"),
        "n_present": input_prep_completion.get("n_present"),
        "n_nonempty": input_prep_completion.get("n_nonempty"),
        "n_missing": input_prep_completion.get("n_missing"),
        "n_empty": input_prep_completion.get("n_empty"),
        "ready_targets": input_prep_completion.get("ready_targets", []),
        "blocked_targets": input_prep_completion.get("blocked_targets", []),
        "artifacts_by_target": input_prep_completion.get("artifacts_by_target", {}),
        "pending_artifacts": input_prep_completion.get("pending_artifacts", []),
        "failures": input_prep_completion.get("failures", []),
        "manifest_command": input_prep_completion.get("manifest_command"),
        "message": input_prep_completion.get("next_action", ""),
        "next_action": next_action,
        "evidence": input_prep_completion.get("_path"),
    }


def _w1_completion_status(scale_completion: Dict[str, Any], *,
                          target_alpha: float,
                          input_prep_completion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if _is_missing_artifact(scale_completion):
        return {
            "workstream": "W1_M6c_scale_up",
            "status": "scale_completion_missing",
            "complete": False,
            "target_alpha": target_alpha,
            "message": scale_completion.get("message", ""),
            "next_action": "run complex_scale_completion.py after the saved scale plan exists and Cayuga records are synced",
            "evidence": scale_completion.get("_path"),
        }
    mismatch = _alpha_mismatch(scale_completion, target_alpha)
    if mismatch is not None:
        return _alpha_mismatch_status(
            workstream="W1_M6c_scale_up",
            status="scale_completion_alpha_mismatch",
            artifact_alpha=mismatch,
            target_alpha=target_alpha,
            evidence=scale_completion.get("_path"),
            next_action="rerun status with the matching --target-alpha or regenerate the scale plan/completion for the requested alpha",
        )
    if scale_completion.get("ok") and scale_completion.get("status") == "ready_for_posthoc":
        status = "scale_records_ready_for_posthoc"
        next_action = "run posthoc command from scale completion report"
    elif scale_completion.get("status") == "scale_plan_unavailable":
        source_status = scale_completion.get("source_status")
        if source_status == "waiting_on_input_prep" and input_prep_completion is not None:
            status = _input_prep_completion_status(
                input_prep_completion,
                workstream="W1_M6c_scale_up",
                status_prefix="scale",
                ready_next_action="run manifest_command, then rerun complex_readiness.py --require-files to regenerate the scale plan",
            )
            status["source_status"] = source_status
            status["readiness_status"] = scale_completion.get("readiness_status")
            status["superseded_scale_completion"] = scale_completion.get("_path")
            status["superseded_scale_completion_status"] = scale_completion.get("status")
            return status
        status = "scale_waiting_on_input_prep" if source_status == "waiting_on_input_prep" else "scale_plan_unavailable"
        next_action = scale_completion.get(
            "next_action",
            "rerun readiness after fixing the scale-plan blocker",
        )
    else:
        status = "scale_completion_blocked"
        next_action = scale_completion.get(
            "next_action",
            "sync or fix missing/invalid scale records before posthoc",
        )
    return {
        "workstream": "W1_M6c_scale_up",
        "status": status,
        "complete": False,
        "target_alpha": scale_completion.get("target_alpha", target_alpha),
        "target_id": scale_completion.get("target_id"),
        "failures": scale_completion.get("failures", []),
        "records": scale_completion.get("records", []),
        "expected_records": scale_completion.get("expected_records", []),
        "expected_new_records": scale_completion.get("expected_new_records", []),
        "posthoc_command": scale_completion.get("posthoc_command"),
        "source_status": scale_completion.get("source_status"),
        "readiness_status": scale_completion.get("readiness_status"),
        "message": scale_completion.get("next_action", ""),
        "next_action": next_action,
        "evidence": scale_completion.get("_path"),
    }


def _w1_status(decision: Optional[Dict[str, Any]], posthoc_manifest: Optional[Dict[str, Any]],
               scale_completion: Optional[Dict[str, Any]], target_alpha: float,
               input_prep_completion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if _is_missing_artifact(decision):
        return {
            "workstream": "W1_M6c_scale_up",
            "status": "alpha_decision_missing",
            "complete": False,
            "target_alpha": target_alpha,
            "message": decision.get("message", ""),
            "next_action": "run complex_posthoc_bundle.py or pass a current alpha decision artifact",
            "evidence": decision.get("_path"),
        }
    dec = decision.get("decision") if isinstance(decision, dict) else None
    if decision is not None:
        mismatch = _alpha_mismatch(decision, target_alpha)
        if mismatch is not None:
            return _alpha_mismatch_status(
                workstream="W1_M6c_scale_up",
                status="alpha_decision_alpha_mismatch",
                artifact_alpha=mismatch,
                target_alpha=target_alpha,
                evidence=decision.get("_path"),
                next_action="rerun status with the matching --target-alpha or regenerate the alpha decision for the requested alpha",
            )
    if (
        scale_completion is not None
        and dec != "stop_certified"
        and not _decision_consumes_scale_completion(decision, scale_completion)
    ):
        return _w1_completion_status(
            scale_completion,
            target_alpha=target_alpha,
            input_prep_completion=input_prep_completion,
        )
    if decision is None:
        return {
            "workstream": "W1_M6c_scale_up",
            "status": "missing",
            "complete": False,
            "message": "No alpha decision artifact provided.",
            "next_action": "run complex_posthoc_bundle.py on synchronized records",
        }
    next_batch = decision.get("next_batch") if isinstance(decision.get("next_batch"), dict) else {}
    summary = posthoc_manifest.get("summary", {}) if isinstance(posthoc_manifest, dict) else {}
    if dec == "stop_certified":
        audit_failures = _w1_alpha_decision_audit_failures(decision)
        if audit_failures:
            status = "alpha_decision_audit_failed"
            complete = False
            next_action = "rerun complex_alpha_decision.py or complex_posthoc_bundle.py with strict W1 terminal evidence"
        else:
            status = "certified"
            complete = True
            next_action = "freeze this target/alpha and broaden to multi-target or second-predictor validation"
    elif dec == "continue_scale":
        audit_failures = []
        status = "continue_scale"
        complete = False
        next_action = "emit/run next scale batch from next_batch"
    elif dec == "qc_failed":
        audit_failures = []
        status = "qc_failed"
        complete = False
        next_action = "fix records QC before alpha claims"
    elif dec == "label_threshold_mismatch":
        audit_failures = []
        status = "label_threshold_mismatch"
        complete = False
        next_action = "regenerate records or rerun W1 analysis with a matching L-RMSD threshold"
    elif dec == "no_feasible_threshold":
        audit_failures = []
        status = "change_axis_or_metric"
        complete = False
        next_action = "add targets/predictors or revisit metric; more same-target scale is not justified"
    else:
        audit_failures = []
        status = "unknown"
        complete = False
        next_action = "inspect alpha decision artifact"
    return {
        "workstream": "W1_M6c_scale_up",
        "status": status,
        "complete": complete,
        "target_alpha": decision.get("target_alpha", target_alpha),
        "n_records": decision.get("n_records") or summary.get("n_records"),
        "certified_alphas": decision.get("certified_alphas") or summary.get("certified_alphas"),
        "estimated_additional_records": decision.get("estimated_additional_records")
        if "estimated_additional_records" in decision else summary.get("estimated_additional_records"),
        "next_batch": next_batch,
        "label_threshold_audit": decision.get("label_threshold_audit"),
        "audit_failures": audit_failures,
        "failures": audit_failures,
        "message": decision.get("message", ""),
        "next_action": next_action,
        "evidence": decision.get("_path"),
    }


def _summary_id_list(summary: Dict[str, Any], key: str) -> List[str]:
    values = summary.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value.strip()]


def _posthoc_science_claims(posthoc_manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(posthoc_manifest, dict):
        return {}
    summary = posthoc_manifest.get("summary")
    if not isinstance(summary, dict):
        return {}
    claims = {
        "supported": _summary_id_list(summary, "science_claims_supported"),
        "not_yet_supported": _summary_id_list(summary, "science_claims_not_yet_supported"),
        "planning_diagnostics": _summary_id_list(summary, "science_claims_planning_diagnostics"),
        "decisive_next": _summary_id_list(summary, "science_claims_decisive_next"),
    }
    if not any(claims.values()):
        return {}
    claims["source"] = "posthoc_manifest"
    report = posthoc_manifest.get("paths", {}).get("report_json")
    if isinstance(report, str) and report.strip():
        claims["report_json"] = report
    return claims


def _science_claim_ids_from_report(report: Dict[str, Any]) -> Dict[str, List[str]]:
    claims = report.get("science_claims")
    if not isinstance(claims, dict):
        return {}
    def ids(section: str) -> List[str]:
        items = claims.get(section)
        if not isinstance(items, list):
            return []
        return [
            item["id"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        ]
    return {
        "supported": ids("supported"),
        "not_yet_supported": ids("not_yet_supported"),
        "planning_diagnostics": ids("planning_diagnostics"),
        "decisive_next": ids("decisive_next_experiments"),
    }


def _resolve_existing_portable_path(path: str) -> str:
    if os.path.exists(path):
        return os.path.realpath(path)
    for marker in ("/results/", "/configs/", "/tests/", "/hpc_outputs/"):
        idx = path.find(marker)
        if idx >= 0:
            candidate = os.path.abspath(path[idx + 1:])
            if os.path.exists(candidate):
                return os.path.realpath(candidate)
    return path


def _resolve_manifest_path(posthoc_manifest: Dict[str, Any], path: str) -> str:
    if os.path.isabs(path):
        return _resolve_existing_portable_path(path)
    manifest_path = posthoc_manifest.get("_path")
    if isinstance(manifest_path, str) and manifest_path:
        return os.path.abspath(os.path.join(os.path.dirname(manifest_path), path))
    return os.path.abspath(path)


def _manifest_record_paths(posthoc_manifest: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(posthoc_manifest, dict):
        return []
    records = posthoc_manifest.get("records")
    if not isinstance(records, list):
        return []
    return [
        _resolve_manifest_path(posthoc_manifest, path)
        for path in records
        if isinstance(path, str) and path.strip()
    ]


def _report_record_paths(report: Dict[str, Any], report_path: str) -> List[str]:
    records = report.get("records_paths")
    if not isinstance(records, list):
        return []
    base_dir = os.path.dirname(os.path.abspath(report_path))
    paths = []
    for path in records:
        if not isinstance(path, str) or not path.strip():
            continue
        paths.append(
            _resolve_existing_portable_path(path)
            if os.path.isabs(path)
            else os.path.abspath(os.path.join(base_dir, path))
        )
    return paths


def _posthoc_science_claims_audit(posthoc_manifest: Optional[Dict[str, Any]],
                                  claims: Dict[str, Any],
                                  *,
                                  target_alpha: Optional[float] = None) -> Dict[str, Any]:
    if not claims:
        return {"ok": True, "status": "not_applicable"}
    report_path = claims.get("report_json")
    if not isinstance(report_path, str) or not report_path.strip():
        return {
            "ok": False,
            "status": "missing_report_path",
            "next_action": "regenerate the posthoc bundle so manifest paths.report_json points to the source M6c report",
        }
    report_path = _resolve_manifest_path(posthoc_manifest or {}, report_path)
    if not os.path.exists(report_path):
        return {
            "ok": False,
            "status": "missing_report_json",
            "report_json": report_path,
            "next_action": "regenerate the posthoc bundle so the source M6c report exists",
        }
    try:
        with open(report_path) as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "report_json_parse_error",
            "report_json": report_path,
            "error": str(exc),
            "next_action": "regenerate the M6c report JSON before trusting posthoc claim summaries",
        }
    if not isinstance(report, dict):
        return {
            "ok": False,
            "status": "report_json_not_object",
            "report_json": report_path,
            "next_action": "regenerate the M6c report JSON before trusting posthoc claim summaries",
        }
    if target_alpha is not None:
        report_alpha = _target_alpha_value(report)
        if report_alpha is None:
            return {
                "ok": False,
                "status": "report_target_alpha_missing",
                "report_json": report_path,
                "target_alpha": target_alpha,
                "next_action": "regenerate the M6c report JSON with the requested target_alpha before trusting claim summaries",
            }
        if not _float_close(report_alpha, target_alpha, tolerance=1e-12):
            return {
                "ok": False,
                "status": "report_target_alpha_mismatch",
                "report_json": report_path,
                "target_alpha": target_alpha,
                "report_target_alpha": report_alpha,
                "next_action": "regenerate the M6c report and posthoc bundle for the requested target_alpha",
            }
    summary = posthoc_manifest.get("summary") if isinstance(posthoc_manifest, dict) else None
    manifest_n_records = (
        _nonnegative_int(summary.get("n_records"))
        if isinstance(summary, dict)
        else None
    )
    report_dataset = report.get("dataset")
    report_n_records = (
        _nonnegative_int(report_dataset.get("n"))
        if isinstance(report_dataset, dict)
        else None
    )
    if manifest_n_records is not None:
        if report_n_records is None:
            return {
                "ok": False,
                "status": "report_n_records_missing",
                "report_json": report_path,
                "manifest_n_records": manifest_n_records,
                "next_action": "regenerate the M6c report JSON so dataset.n matches the posthoc manifest",
            }
        if report_n_records != manifest_n_records:
            return {
                "ok": False,
                "status": "report_n_records_mismatch",
                "report_json": report_path,
                "manifest_n_records": manifest_n_records,
                "report_n_records": report_n_records,
                "next_action": "regenerate the M6c report and posthoc bundle from the same records",
            }
    manifest_records = _manifest_record_paths(posthoc_manifest)
    if manifest_records:
        report_records = _report_record_paths(report, report_path)
        if not report_records:
            return {
                "ok": False,
                "status": "report_records_paths_missing",
                "report_json": report_path,
                "manifest_records": manifest_records,
                "next_action": "regenerate the M6c report JSON so records_paths matches the posthoc manifest",
            }
        if report_records != manifest_records:
            return {
                "ok": False,
                "status": "report_records_paths_mismatch",
                "report_json": report_path,
                "manifest_records": manifest_records,
                "report_records_paths": report_records,
                "next_action": "regenerate the M6c report and posthoc bundle from the same record paths",
            }
    source_claims = _science_claim_ids_from_report(report)
    mismatches = []
    for key in ("supported", "not_yet_supported", "planning_diagnostics", "decisive_next"):
        expected = claims.get(key) or []
        actual = source_claims.get(key) or []
        if expected != actual:
            mismatches.append({"field": key, "manifest": expected, "report": actual})
    if mismatches:
        return {
            "ok": False,
            "status": "claim_summary_mismatch",
            "report_json": report_path,
            "mismatches": mismatches,
            "next_action": "regenerate the posthoc bundle so manifest claim summaries match m6c_report.json",
        }
    return {
        "ok": True,
        "status": "ok",
        "report_json": report_path,
        "checked_fields": [
            "n_records",
            "records_paths",
            "supported",
            "not_yet_supported",
            "planning_diagnostics",
            "decisive_next",
        ],
    }


_POSTHOC_SCIENCE_CLAIM_SECTIONS = (
    "supported",
    "not_yet_supported",
    "planning_diagnostics",
    "decisive_next",
)


def _missing_posthoc_science_claim_sections(claims: Any) -> List[str]:
    missing = []
    if not isinstance(claims, dict):
        return list(_POSTHOC_SCIENCE_CLAIM_SECTIONS)
    for key in _POSTHOC_SCIENCE_CLAIM_SECTIONS:
        values = claims.get(key)
        if not (
            isinstance(values, list)
            and any(isinstance(value, str) and value.strip() for value in values)
        ):
            missing.append(key)
    return missing


def _has_complete_posthoc_science_claim_sections(claims: Any) -> bool:
    return not _missing_posthoc_science_claim_sections(claims)


def _w2_panel_report_audit_failures(panel_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if panel_report.get("ok") is not True:
        failures.append({"kind": "panel_report_not_ok", "field": "ok"})
    if panel_report.get("panel_status") != "multi_target_certified":
        failures.append({
            "kind": "panel_report_status_not_certified",
            "field": "panel_status",
            "panel_status": panel_report.get("panel_status"),
        })
    reported_failures = panel_report.get("failures", [])
    if not isinstance(reported_failures, list):
        failures.append({"kind": "panel_report_failures_field_invalid", "field": "failures"})
    elif reported_failures:
        failures.append({
            "kind": "panel_report_has_failures",
            "field": "failures",
            "n_failures": len(reported_failures),
        })

    min_targets = panel_report.get("min_targets")
    if not isinstance(min_targets, int) or isinstance(min_targets, bool) or min_targets < 3:
        failures.append({
            "kind": "panel_report_min_targets_invalid",
            "field": "min_targets",
            "min_targets": min_targets,
        })
        min_targets = None
    min_records = panel_report.get("min_records_per_target")
    if not isinstance(min_records, int) or isinstance(min_records, bool) or min_records <= 0:
        failures.append({
            "kind": "panel_report_min_records_per_target_invalid",
            "field": "min_records_per_target",
            "min_records_per_target": min_records,
        })
        min_records = None
    n_targets = panel_report.get("n_targets")
    if (
        not isinstance(n_targets, int)
        or isinstance(n_targets, bool)
        or n_targets <= 0
        or (min_targets is not None and n_targets < min_targets)
    ):
        failures.append({
            "kind": "panel_report_too_few_targets",
            "field": "n_targets",
            "n_targets": n_targets,
            "required": min_targets,
        })
    n_records = panel_report.get("n_records")
    if (
        not isinstance(n_records, int)
        or isinstance(n_records, bool)
        or n_records <= 0
        or (
            isinstance(n_targets, int)
            and not isinstance(n_targets, bool)
            and min_records is not None
            and n_records < n_targets * min_records
        )
    ):
        failures.append({
            "kind": "panel_report_record_count_invalid",
            "field": "n_records",
            "n_records": n_records,
        })

    target_alpha = panel_report.get("target_alpha")
    if (
        not isinstance(target_alpha, (int, float))
        or isinstance(target_alpha, bool)
        or not 0.0 < float(target_alpha) <= 1.0
    ):
        failures.append({
            "kind": "panel_report_target_alpha_invalid",
            "field": "target_alpha",
            "target_alpha": target_alpha,
        })
    threshold = panel_report.get("threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or float(threshold) <= 0.0
    ):
        failures.append({
            "kind": "panel_report_threshold_invalid",
            "field": "threshold",
            "threshold": threshold,
        })

    for field, kind in (
        ("predictors", "panel_report_predictor_provenance_invalid"),
        ("signal_sources", "panel_report_signal_provenance_invalid"),
        ("label_sources", "panel_report_label_provenance_invalid"),
    ):
        values = panel_report.get(field)
        if not (
            isinstance(values, list)
            and len(values) == 1
            and isinstance(values[0], str)
            and values[0].strip()
            and values[0] != "unknown"
        ):
            failures.append({"kind": kind, "field": field, "values": values})

    label_threshold_audit = panel_report.get("label_threshold_audit")
    if not isinstance(label_threshold_audit, dict) or label_threshold_audit.get("ok") is not True:
        failures.append({
            "kind": "panel_report_label_threshold_audit_invalid",
            "field": "label_threshold_audit",
        })

    targets = panel_report.get("targets")
    if not isinstance(targets, list) or not targets:
        failures.append({"kind": "panel_report_targets_missing", "field": "targets"})
        return failures
    if isinstance(n_targets, int) and not isinstance(n_targets, bool) and len(targets) != n_targets:
        failures.append({
            "kind": "panel_report_target_count_mismatch",
            "field": "targets",
            "expected": n_targets,
            "actual": len(targets),
        })
    seen_target_ids = set()
    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            failures.append({"kind": "panel_report_target_invalid", "field": "targets", "index": idx})
            continue
        target_id = target.get("complex_target_id")
        if not isinstance(target_id, str) or not target_id.strip():
            failures.append({
                "kind": "panel_report_target_id_invalid",
                "field": "targets.complex_target_id",
                "index": idx,
                "complex_target_id": target_id,
            })
        elif target_id in seen_target_ids:
            failures.append({
                "kind": "panel_report_target_id_duplicate",
                "field": "targets.complex_target_id",
                "index": idx,
                "complex_target_id": target_id,
            })
        else:
            seen_target_ids.add(target_id)
        target_records = target.get("n_records")
        if (
            not isinstance(target_records, int)
            or isinstance(target_records, bool)
            or target_records <= 0
            or (min_records is not None and target_records < min_records)
        ):
            failures.append({
                "kind": "panel_report_target_too_few_records",
                "field": "targets.n_records",
                "index": idx,
                "complex_target_id": target_id,
                "n_records": target_records,
                "required": min_records,
            })
        if target.get("status") != "certified" or target.get("certified") is not True:
            failures.append({
                "kind": "panel_report_target_not_certified",
                "field": "targets.certified",
                "index": idx,
                "complex_target_id": target_id,
                "status": target.get("status"),
                "certified": target.get("certified"),
            })
        if target.get("tau") is None:
            failures.append({
                "kind": "panel_report_target_tau_missing",
                "field": "targets.tau",
                "index": idx,
                "complex_target_id": target_id,
            })
    return failures


def _w2_completion_status(panel_completion: Dict[str, Any], *, target_alpha: float) -> Dict[str, Any]:
    if _is_missing_artifact(panel_completion):
        return {
            "workstream": "W2_multi_target_panel",
            "status": "panel_completion_missing",
            "complete": False,
            "message": panel_completion.get("message", ""),
            "next_action": "run complex_panel_completion.py after panel records are generated and synced",
            "evidence": panel_completion.get("_path"),
        }
    mismatch = _alpha_mismatch(panel_completion, target_alpha)
    if mismatch is not None:
        return _alpha_mismatch_status(
            workstream="W2_multi_target_panel",
            status="panel_completion_alpha_mismatch",
            artifact_alpha=mismatch,
            target_alpha=target_alpha,
            evidence=panel_completion.get("_path"),
            next_action="rerun status with the matching --target-alpha or regenerate panel completion for the requested alpha",
        )
    if panel_completion.get("ok") and panel_completion.get("status") == "ready_for_panel_report":
        status = "panel_records_ready_for_report"
        next_action = "run panel_report_command from panel completion report"
    else:
        status = "panel_completion_blocked"
        next_action = panel_completion.get(
            "next_action",
            "sync/fix target records before panel report",
        )
    return {
        "workstream": "W2_multi_target_panel",
        "status": status,
        "complete": False,
        "n_targets": panel_completion.get("n_manifest_targets"),
        "n_completed_targets": panel_completion.get("n_completed_targets"),
        "expected_records": panel_completion.get("expected_records", []),
        "failures": panel_completion.get("failures", []),
        "records": panel_completion.get("records", []),
        "panel_report_command": panel_completion.get("panel_report_command"),
        "message": panel_completion.get("next_action", ""),
        "next_action": next_action,
        "evidence": panel_completion.get("_path"),
    }


def _w2_target_manifest_status(target_manifest: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(target_manifest):
        return {
            "workstream": "W2_multi_target_panel",
            "status": "target_manifest_report_missing",
            "complete": False,
            "message": target_manifest.get("message", ""),
            "next_action": "run complex_target_manifest.py --require-files to refresh the W2 target manifest report",
            "evidence": target_manifest.get("_path"),
        }
    if target_manifest.get("ok"):
        status = "targets_ready_no_panel"
        next_action = "run Cayuga jobs for ready targets, then complex_panel_completion.py"
    elif _target_manifest_waiting_on_msa_artifacts(target_manifest):
        status = "panel_waiting_on_input_prep"
        next_action = "run the emitted target_msa_precompute plan, sync target MSA/report files, then rerun target manifest with --require-files"
    else:
        status = "target_manifest_failed"
        next_action = "fix target manifest/prep/MSA failures before model spend"
    return {
        "workstream": "W2_multi_target_panel",
        "status": status,
        "complete": False,
        "n_targets": target_manifest.get("n_targets"),
        "n_ready_targets": target_manifest.get("n_ready_targets"),
        "failures": target_manifest.get("failures", []),
        "input_prep_artifacts": target_manifest.get("input_prep_artifacts", []),
        "next_action": next_action,
        "evidence": target_manifest.get("_path"),
    }


def _w2_target_msa_gate_status(target_msa_gate_audit: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(target_msa_gate_audit):
        return {
            "workstream": "W2_multi_target_panel",
            "status": "target_msa_gate_audit_missing",
            "complete": False,
            "message": target_msa_gate_audit.get("message", ""),
            "next_action": "rerun m6d_w2_target_msa_gate_audit.py before target-MSA or panel submission",
            "evidence": target_msa_gate_audit.get("_path"),
        }

    audit_ok = target_msa_gate_audit.get("audit_ok") is True
    if audit_ok:
        status = "target_msa_gate_ready_awaiting_explicit_approval"
        next_action = target_msa_gate_audit.get(
            "next_action",
            "await explicit approval before submitting target-MSA jobs",
        )
    else:
        status = "target_msa_gate_audit_failed"
        next_action = target_msa_gate_audit.get(
            "next_action",
            "repair the target-MSA gate audit before any W2 model spend",
        )

    return {
        "workstream": "W2_multi_target_panel",
        "status": status,
        "complete": False,
        "audit_ok": audit_ok,
        "target_count": target_msa_gate_audit.get("target_count"),
        "pending_path_count": target_msa_gate_audit.get("pending_path_count"),
        "completion_counts": target_msa_gate_audit.get("completion_counts", {}),
        "manifest_counts": target_msa_gate_audit.get("manifest_counts", {}),
        "ready_for_panel_submission": target_msa_gate_audit.get("ready_for_panel_submission"),
        "ready_for_target_msa_submission_if_explicitly_approved": target_msa_gate_audit.get(
            "ready_for_target_msa_submission_if_explicitly_approved"
        ),
        "explicit_submit_approval_required": target_msa_gate_audit.get("explicit_submit_approval_required"),
        "submit_command_if_approved": target_msa_gate_audit.get("submit_command_if_approved"),
        "postsubmit_sync_back_command": target_msa_gate_audit.get("postsubmit_sync_back_command"),
        "pending_paths": target_msa_gate_audit.get("pending_paths"),
        "failures": target_msa_gate_audit.get("failures", []),
        "message": target_msa_gate_audit.get("status", ""),
        "next_action": next_action,
        "evidence": target_msa_gate_audit.get("_path"),
    }


def _attach_w2_approval_packet(status: Dict[str, Any],
                               approval_packet: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(approval_packet):
        status.update({
            "status": "target_msa_approval_packet_missing",
            "approval_packet_ready": False,
            "approval_packet": approval_packet.get("_path"),
            "complete": False,
            "message": approval_packet.get("message", ""),
            "next_action": "rerun m6d_w2_target_msa_approval_packet.py before target-MSA approval or submission",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    packet_failures = approval_packet.get("failures") if isinstance(approval_packet.get("failures"), list) else []
    consistency_failures = []
    if approval_packet.get("target_count") != status.get("target_count"):
        consistency_failures.append({
            "kind": "approval_packet_target_count_mismatch",
            "expected": status.get("target_count"),
            "observed": approval_packet.get("target_count"),
        })
    if approval_packet.get("pending_path_count") != status.get("pending_path_count"):
        consistency_failures.append({
            "kind": "approval_packet_pending_path_count_mismatch",
            "expected": status.get("pending_path_count"),
            "observed": approval_packet.get("pending_path_count"),
        })
    if approval_packet.get("submit_command_if_approved") != status.get("submit_command_if_approved"):
        consistency_failures.append({
            "kind": "approval_packet_submit_command_mismatch",
            "expected": status.get("submit_command_if_approved"),
            "observed": approval_packet.get("submit_command_if_approved"),
        })
    if approval_packet.get("postsubmit_sync_back_command") != status.get("postsubmit_sync_back_command"):
        consistency_failures.append({
            "kind": "approval_packet_sync_command_mismatch",
            "expected": status.get("postsubmit_sync_back_command"),
            "observed": approval_packet.get("postsubmit_sync_back_command"),
        })
    if approval_packet.get("can_submit_proteinmpnn_boltz_panel") is not False:
        consistency_failures.append({
            "kind": "approval_packet_panel_submission_not_blocked",
            "observed": approval_packet.get("can_submit_proteinmpnn_boltz_panel"),
        })

    packet_ready = (
        approval_packet.get("approval_packet_ready") is True
        and approval_packet.get("can_submit_target_msa_if_user_explicitly_approves") is True
        and approval_packet.get("can_submit_proteinmpnn_boltz_panel") is False
        and not packet_failures
        and not consistency_failures
    )
    status.update({
        "approval_packet": approval_packet.get("_path"),
        "approval_packet_ready": packet_ready,
        "approval_packet_status": approval_packet.get("status"),
        "can_submit_target_msa_if_user_explicitly_approves": approval_packet.get(
            "can_submit_target_msa_if_user_explicitly_approves"
        ),
        "can_submit_proteinmpnn_boltz_panel": approval_packet.get("can_submit_proteinmpnn_boltz_panel"),
        "target_msa_approval_env_var": approval_packet.get("target_msa_approval_env_var"),
        "target_msa_approval_env_value": approval_packet.get("target_msa_approval_env_value"),
        "wrapper_guard_audit": approval_packet.get("wrapper_guard_audit"),
        "wrapper_guard_audit_ok": approval_packet.get("wrapper_guard_audit_ok"),
        "wrapper_guard_static_ok": approval_packet.get("wrapper_guard_static_ok"),
        "wrapper_guard_no_env_run_ok": approval_packet.get("wrapper_guard_no_env_run_ok"),
        "wrapper_guard_script_sha256": approval_packet.get("wrapper_guard_script_sha256"),
        "approval_packet_failures": packet_failures + consistency_failures,
    })
    if not packet_ready:
        status.update({
            "status": "target_msa_approval_packet_blocked",
            "complete": False,
            "failures": failures + packet_failures + consistency_failures,
            "next_action": approval_packet.get(
                "next_action",
                "fix approval packet before target-MSA approval or submission",
            ),
        })
    return status


def _attach_w2_approval_parity(status: Dict[str, Any],
                               approval_parity: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(approval_parity):
        status.update({
            "status": "target_msa_approval_parity_missing",
            "approval_parity_ok": False,
            "approval_parity": approval_parity.get("_path"),
            "complete": False,
            "message": approval_parity.get("message", ""),
            "next_action": "rerun m6d_w2_target_msa_approval_parity.py before target-MSA approval or submission",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    parity_failures = []
    mismatches = approval_parity.get("mismatches") if isinstance(approval_parity.get("mismatches"), list) else []
    if approval_parity.get("parity_ok") is not True:
        parity_failures.append({
            "kind": "approval_parity_not_ok",
            "status": approval_parity.get("status"),
            "mismatches": mismatches,
        })
    if approval_parity.get("approval_packet_ready") is not True:
        parity_failures.append({
            "kind": "approval_parity_packet_not_ready_on_both_sides",
            "observed": approval_parity.get("approval_packet_ready"),
        })
    if approval_parity.get("panel_submission_blocked") is not True:
        parity_failures.append({
            "kind": "approval_parity_panel_not_blocked_on_both_sides",
            "observed": approval_parity.get("panel_submission_blocked"),
        })
    if approval_parity.get("target_count") != status.get("target_count"):
        parity_failures.append({
            "kind": "approval_parity_target_count_mismatch",
            "expected": status.get("target_count"),
            "observed": approval_parity.get("target_count"),
        })
    if approval_parity.get("pending_path_count") != status.get("pending_path_count"):
        parity_failures.append({
            "kind": "approval_parity_pending_path_count_mismatch",
            "expected": status.get("pending_path_count"),
            "observed": approval_parity.get("pending_path_count"),
        })

    parity_ok = not parity_failures
    status.update({
        "approval_parity": approval_parity.get("_path"),
        "approval_parity_ok": parity_ok,
        "approval_parity_status": approval_parity.get("status"),
        "local_cayuga_approval_packet_agree": approval_parity.get("parity_ok"),
        "approval_parity_failures": parity_failures,
    })
    if not parity_ok:
        status.update({
            "status": "target_msa_approval_parity_blocked",
            "complete": False,
            "failures": failures + parity_failures,
            "next_action": approval_parity.get(
                "next_action",
                "fix local/Cayuga approval packet parity before target-MSA approval or submission",
            ),
        })
    return status


def _attach_w2_panel_approval_packet(status: Dict[str, Any],
                                     panel_approval_packet: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(panel_approval_packet):
        status.update({
            "status": "panel_approval_packet_missing",
            "panel_approval_packet_ready": False,
            "panel_approval_packet": panel_approval_packet.get("_path"),
            "complete": False,
            "message": panel_approval_packet.get("message", ""),
            "next_action": "rerun m6d_w2_panel_approval_packet.py before panel approval or submission",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    packet_failures = (
        panel_approval_packet.get("failures")
        if isinstance(panel_approval_packet.get("failures"), list)
        else []
    )
    checks = (
        panel_approval_packet.get("checks")
        if isinstance(panel_approval_packet.get("checks"), dict)
        else {}
    )
    consistency_failures = []
    if panel_approval_packet.get("status") != _W2_PANEL_APPROVAL_READY_STATUS:
        consistency_failures.append({
            "kind": "panel_approval_packet_status_not_ready",
            "observed": panel_approval_packet.get("status"),
        })
    if panel_approval_packet.get("approval_packet_ready") is not True:
        consistency_failures.append({
            "kind": "panel_approval_packet_not_ready",
            "observed": panel_approval_packet.get("approval_packet_ready"),
        })
    if panel_approval_packet.get("can_submit_panel_if_user_explicitly_approves") is not True:
        consistency_failures.append({
            "kind": "panel_approval_packet_submit_not_allowed_after_explicit_approval",
            "observed": panel_approval_packet.get("can_submit_panel_if_user_explicitly_approves"),
        })
    if panel_approval_packet.get("can_claim_w2_generalization") is not False:
        consistency_failures.append({
            "kind": "panel_approval_packet_claim_boundary_drift",
            "observed": panel_approval_packet.get("can_claim_w2_generalization"),
        })
    for key in (
        "target_msa_strict_ready",
        "panel_preflight_ready",
        "panel_dry_run_no_sbatch",
        "panel_guard_no_env_refuses",
        "submit_receipt_absent",
        "submit_summary_absent",
    ):
        if checks.get(key) is not True:
            consistency_failures.append({
                "kind": "panel_approval_packet_check_failed",
                "check": key,
                "observed": checks.get(key),
            })
    def _strict_postsubmit_command_ok(command: Any) -> bool:
        text = str(command or "")
        required_flags = (
            "--manifest",
            "--receipt",
            "--summary",
            "--job-states",
            "--require-sync-ready",
            "--out-json",
        )
        required_paths = (
            panel_approval_packet.get("manifest"),
            panel_approval_packet.get("submit_receipt"),
            panel_approval_packet.get("submit_summary"),
            panel_approval_packet.get("postsubmit_status_before_sync"),
            panel_approval_packet.get("job_state_probe_before_sync"),
        )
        return (
            "m6d_w2_panel_postsubmit_status" in text
            and all(flag in text for flag in required_flags)
            and all(str(path) in text for path in required_paths if path)
        )

    v11_panel_sync = "v11" in str(panel_approval_packet.get("sync_back_command_after_jobs_finish") or "")
    postsubmit_sync_ready_gate_ok = (
        bool(panel_approval_packet.get("postsubmit_status_before_sync"))
        and bool(panel_approval_packet.get("job_state_probe_before_sync"))
        and _strict_postsubmit_command_ok(panel_approval_packet.get("postsubmit_sync_ready_gate"))
    )
    job_state_sync = str(panel_approval_packet.get("job_state_probe_sync_after_query") or "")
    job_state_query_bridge_ok = (
        bool(panel_approval_packet.get("job_state_query_after_receipt"))
        and bool(job_state_sync)
        and "rsync" in job_state_sync
        and str(panel_approval_packet.get("job_state_probe_before_sync") or "") in job_state_sync
    )
    postsubmit_bridge_ok = (
        postsubmit_sync_ready_gate_ok
        and bool(panel_approval_packet.get("receipt_monitor_after_submit"))
        and bool(panel_approval_packet.get("postsubmit_driver_after_submit"))
        and job_state_query_bridge_ok
        and bool(panel_approval_packet.get("postsubmit_status_command_before_sync"))
        and _strict_postsubmit_command_ok(panel_approval_packet.get("postsubmit_status_command_before_sync"))
        and bool(panel_approval_packet.get("postsync_replay_after_sync"))
    )
    if v11_panel_sync and not postsubmit_sync_ready_gate_ok:
        consistency_failures.append({
            "kind": "panel_approval_packet_postsubmit_sync_ready_gate_missing",
            "observed": {
                "postsubmit_status_before_sync": panel_approval_packet.get("postsubmit_status_before_sync"),
                "job_state_probe_before_sync": panel_approval_packet.get("job_state_probe_before_sync"),
                "postsubmit_sync_ready_gate": panel_approval_packet.get("postsubmit_sync_ready_gate"),
            },
        })
    if v11_panel_sync and not postsubmit_bridge_ok:
        consistency_failures.append({
            "kind": "panel_approval_packet_postsubmit_bridge_missing",
            "observed": {
                "receipt_monitor_after_submit": panel_approval_packet.get("receipt_monitor_after_submit"),
                "postsubmit_driver_after_submit": panel_approval_packet.get("postsubmit_driver_after_submit"),
                "job_state_query_after_receipt": panel_approval_packet.get("job_state_query_after_receipt"),
                "job_state_probe_sync_after_query": panel_approval_packet.get("job_state_probe_sync_after_query"),
                "postsubmit_status_command_before_sync": panel_approval_packet.get(
                    "postsubmit_status_command_before_sync"
                ),
                "postsync_replay_after_sync": panel_approval_packet.get("postsync_replay_after_sync"),
            },
        })

    packet_ready = not packet_failures and not consistency_failures
    status.update({
        "panel_approval_packet": panel_approval_packet.get("_path"),
        "panel_approval_packet_ready": packet_ready,
        "panel_approval_packet_status": panel_approval_packet.get("status"),
        "can_submit_panel_if_user_explicitly_approves": panel_approval_packet.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "can_claim_w2_generalization": panel_approval_packet.get("can_claim_w2_generalization"),
        "panel_approval_env_var": panel_approval_packet.get("panel_approval_env_var"),
        "panel_approval_env_value": panel_approval_packet.get("panel_approval_env_value"),
        "panel_submit_command_if_approved": panel_approval_packet.get("submit_command_if_approved"),
        "panel_sync_back_command_after_jobs_finish": panel_approval_packet.get(
            "sync_back_command_after_jobs_finish"
        ),
        "panel_completion_command_after_sync": panel_approval_packet.get("completion_command_after_sync"),
        "panel_postsubmit_status_before_sync": panel_approval_packet.get("postsubmit_status_before_sync"),
        "panel_job_state_probe_before_sync": panel_approval_packet.get("job_state_probe_before_sync"),
        "panel_receipt_monitor_after_submit": panel_approval_packet.get("receipt_monitor_after_submit"),
        "panel_postsubmit_driver_after_submit": panel_approval_packet.get("postsubmit_driver_after_submit"),
        "panel_postsubmit_driver_script": panel_approval_packet.get("postsubmit_driver_script"),
        "panel_postsubmit_driver_polling": panel_approval_packet.get("postsubmit_driver_polling"),
        "panel_job_state_query_after_receipt": panel_approval_packet.get("job_state_query_after_receipt"),
        "panel_job_state_probe_sync_after_query": panel_approval_packet.get("job_state_probe_sync_after_query"),
        "panel_job_state_query_bridge_ok": job_state_query_bridge_ok,
        "panel_postsubmit_sync_ready_gate": panel_approval_packet.get("postsubmit_sync_ready_gate"),
        "panel_postsubmit_status_command_before_sync": panel_approval_packet.get(
            "postsubmit_status_command_before_sync"
        ),
        "panel_postsync_replay_after_sync": panel_approval_packet.get("postsync_replay_after_sync"),
        "panel_postsubmit_sync_ready_gate_ok": postsubmit_sync_ready_gate_ok,
        "panel_postsubmit_bridge_ok": postsubmit_bridge_ok,
        "panel_approval_checks": checks,
        "panel_approval_packet_failures": packet_failures + consistency_failures,
    })
    if packet_ready:
        status.update({
            "status": "panel_approval_packet_ready_awaiting_explicit_approval",
            "complete": False,
            "ready_for_panel_submission_if_explicitly_approved": True,
            "next_action": (
                "await explicit user approval before guarded W2 panel submission; "
                "then sync back, run completion, and certify target-wise panel report"
            ),
        })
    else:
        status.update({
            "status": "panel_approval_packet_blocked",
            "complete": False,
            "failures": failures + packet_failures + consistency_failures,
            "next_action": panel_approval_packet.get(
                "next_action",
                "fix panel approval packet before panel approval or submission",
            ),
        })
    return status


def _attach_w2_panel_decision_protocol(status: Dict[str, Any],
                                       panel_decision_protocol: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(panel_decision_protocol):
        status.update({
            "status": "panel_decision_protocol_missing",
            "panel_decision_protocol_ready": False,
            "panel_decision_protocol": panel_decision_protocol.get("_path"),
            "complete": False,
            "message": panel_decision_protocol.get("message", ""),
            "next_action": "rerun m6d_w2_panel_decision_protocol.py before panel approval or interpretation",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    protocol_failures = (
        panel_decision_protocol.get("failures")
        if isinstance(panel_decision_protocol.get("failures"), list)
        else []
    )
    current_panel_result = (
        panel_decision_protocol.get("current_panel_result")
        if isinstance(panel_decision_protocol.get("current_panel_result"), dict)
        else {}
    )
    consistency_failures = []
    if panel_decision_protocol.get("status") != _W2_PANEL_DECISION_PROTOCOL_READY_STATUS:
        consistency_failures.append({
            "kind": "panel_decision_protocol_status_not_ready",
            "observed": panel_decision_protocol.get("status"),
        })
    if panel_decision_protocol.get("audit_ok") is not True:
        consistency_failures.append({
            "kind": "panel_decision_protocol_audit_not_ok",
            "observed": panel_decision_protocol.get("audit_ok"),
        })
    if panel_decision_protocol.get("no_submit") is not True:
        consistency_failures.append({
            "kind": "panel_decision_protocol_not_no_submit",
            "observed": panel_decision_protocol.get("no_submit"),
        })
    if panel_decision_protocol.get("can_claim_w2_generalization_now") is not False:
        consistency_failures.append({
            "kind": "panel_decision_protocol_claim_boundary_drift",
            "observed": panel_decision_protocol.get("can_claim_w2_generalization_now"),
        })
    if current_panel_result.get("w2_generalization_supported") is not False:
        consistency_failures.append({
            "kind": "panel_decision_protocol_current_result_claim_drift",
            "observed": current_panel_result.get("w2_generalization_supported"),
        })

    ready = not protocol_failures and not consistency_failures
    status.update({
        "panel_decision_protocol": panel_decision_protocol.get("_path"),
        "panel_decision_protocol_ready": ready,
        "panel_decision_protocol_status": panel_decision_protocol.get("status"),
        "panel_decision_no_submit": panel_decision_protocol.get("no_submit"),
        "panel_decision_can_claim_w2_now": panel_decision_protocol.get("can_claim_w2_generalization_now"),
        "panel_decision_current_result_status": current_panel_result.get("status"),
        "panel_decision_current_result_claim": current_panel_result.get("claim"),
        "panel_decision_protocol_failures": protocol_failures + consistency_failures,
    })
    if ready:
        status.update({
            "complete": False,
            "next_action": (
                "await explicit user approval before guarded W2 panel submission; "
                "post-panel decision protocol is predeclared for sync-back, completion, and target-wise certification"
            ),
        })
    else:
        status.update({
            "status": "panel_decision_protocol_blocked",
            "complete": False,
            "failures": failures + protocol_failures + consistency_failures,
            "next_action": "repair panel decision protocol before panel approval or interpretation",
        })
    return status


def _attach_w2_panel_remote_readiness(status: Dict[str, Any],
                                      panel_remote_readiness: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(panel_remote_readiness):
        status.update({
            "status": "panel_remote_submission_readiness_missing",
            "panel_remote_submission_readiness_ok": False,
            "panel_remote_submission_readiness": panel_remote_readiness.get("_path"),
            "complete": False,
            "message": panel_remote_readiness.get("message", ""),
            "next_action": "rerun m6d_w2_v11_remote_submission_readiness.py before panel approval or submission",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    readiness_failures = (
        panel_remote_readiness.get("failures")
        if isinstance(panel_remote_readiness.get("failures"), list)
        else []
    )
    consistency_failures = []
    if panel_remote_readiness.get("status") != _W2_REMOTE_SUBMISSION_READY_STATUS:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_status_not_ok",
            "observed": panel_remote_readiness.get("status"),
        })
    if panel_remote_readiness.get("audit_ok") is not True:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_audit_not_ok",
            "observed": panel_remote_readiness.get("audit_ok"),
        })
    if panel_remote_readiness.get("no_submit") is not True:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_submit_drift",
            "observed": panel_remote_readiness.get("no_submit"),
        })
    if panel_remote_readiness.get("can_submit_panel_if_user_explicitly_approves") is not True:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_not_explicit_approval_ready",
            "observed": panel_remote_readiness.get("can_submit_panel_if_user_explicitly_approves"),
        })
    if panel_remote_readiness.get("can_claim_w2_generalization") is not False:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_claim_boundary_drift",
            "observed": panel_remote_readiness.get("can_claim_w2_generalization"),
        })
    if panel_remote_readiness.get("n_failures") != 0:
        consistency_failures.append({
            "kind": "panel_remote_submission_readiness_failures_present",
            "observed": panel_remote_readiness.get("n_failures"),
        })
    exact_checks = (
        panel_remote_readiness.get("exact_checks")
        if isinstance(panel_remote_readiness.get("exact_checks"), list)
        else []
    )
    local_root = panel_remote_readiness.get("local_root")
    local_exact_failures = _w2_remote_readiness_local_exact_failures(
        exact_checks,
        local_root=local_root if isinstance(local_root, str) else None,
    )

    ready = not readiness_failures and not consistency_failures and not local_exact_failures
    status.update({
        "panel_remote_submission_readiness": panel_remote_readiness.get("_path"),
        "panel_remote_submission_readiness_ok": ready,
        "panel_remote_submission_readiness_status": panel_remote_readiness.get("status"),
        "panel_remote_no_submit": panel_remote_readiness.get("no_submit"),
        "panel_remote_can_submit_if_explicitly_approved": panel_remote_readiness.get(
            "can_submit_panel_if_user_explicitly_approves"
        ),
        "panel_remote_can_claim_w2_generalization": panel_remote_readiness.get("can_claim_w2_generalization"),
        "panel_remote_exact_checks": panel_remote_readiness.get("n_exact_checks"),
        "panel_remote_semantic_checks": panel_remote_readiness.get("n_semantic_checks"),
        "panel_remote_absence_checks": panel_remote_readiness.get("n_absence_checks"),
        "panel_remote_local_exact_fresh": not local_exact_failures,
        "panel_remote_local_exact_stale_count": len(local_exact_failures),
        "panel_remote_submission_readiness_failures": (
            readiness_failures + consistency_failures + local_exact_failures
        ),
    })
    if ready:
        status.update({
            "complete": False,
            "next_action": (
                "remote mirror is ready; await explicit user approval before guarded W2 panel submission; "
                "then sync back, run completion, and certify target-wise panel report"
            ),
        })
    else:
        status.update({
            "status": "panel_remote_submission_readiness_blocked",
            "complete": False,
            "failures": failures + readiness_failures + consistency_failures + local_exact_failures,
            "next_action": "repair remote submission readiness before panel approval or submission",
        })
    return status


def _resolve_w2_exact_check_path(path: str, *, local_root: Optional[str]) -> str:
    if os.path.isabs(path):
        return path
    cwd_path = os.path.abspath(path)
    if os.path.exists(cwd_path):
        return cwd_path
    if local_root:
        return os.path.join(local_root, path)
    return cwd_path


def _w2_remote_readiness_local_exact_failures(exact_checks: Any,
                                             *,
                                             local_root: Optional[str]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if not isinstance(exact_checks, list):
        return failures
    for row in exact_checks:
        if not isinstance(row, dict):
            failures.append({
                "kind": "panel_remote_submission_readiness_local_exact_invalid",
                "observed": row,
            })
            continue
        rel_path = row.get("path")
        expected_sha = row.get("local_sha256")
        expected_bytes = row.get("local_bytes")
        if not isinstance(rel_path, str) or not rel_path:
            failures.append({
                "kind": "panel_remote_submission_readiness_local_exact_missing_path",
                "observed": rel_path,
            })
            continue
        local_path = _resolve_w2_exact_check_path(rel_path, local_root=local_root)
        if not os.path.exists(local_path):
            failures.append({
                "kind": "panel_remote_submission_readiness_local_exact_missing",
                "path": rel_path,
                "local_path": local_path,
            })
            continue
        actual_sha = _sha256_file(local_path)
        actual_bytes = os.path.getsize(local_path)
        if actual_sha != expected_sha or (
            isinstance(expected_bytes, int) and actual_bytes != expected_bytes
        ):
            failures.append({
                "kind": "panel_remote_submission_readiness_local_exact_stale",
                "path": rel_path,
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes,
            })
    return failures


def _receipt_absence_rows_ok(rows: Any) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    return all(isinstance(row, dict) and row.get("exists") is False for row in rows)


def _attach_w2_panel_submission_decision_state(status: Dict[str, Any],
                                               panel_submission_decision_state: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(panel_submission_decision_state):
        status.update({
            "status": "panel_submission_decision_state_missing",
            "panel_submission_decision_ready": False,
            "panel_submission_decision_state": panel_submission_decision_state.get("_path"),
            "complete": False,
            "message": panel_submission_decision_state.get("message", ""),
            "next_action": "rerun m6d_w2_v11_submission_decision_state.py before panel approval or submission",
        })
        return status

    failures = list(status.get("failures", [])) if isinstance(status.get("failures", []), list) else []
    decision_failures = (
        panel_submission_decision_state.get("failures")
        if isinstance(panel_submission_decision_state.get("failures"), list)
        else []
    )
    receipt_absence = (
        panel_submission_decision_state.get("receipt_absence")
        if isinstance(panel_submission_decision_state.get("receipt_absence"), dict)
        else {}
    )
    remote_checked = receipt_absence.get("remote_checked") is True
    local_absence_ok = _receipt_absence_rows_ok(receipt_absence.get("local"))
    remote_absence_ok = remote_checked and _receipt_absence_rows_ok(receipt_absence.get("remote"))
    consistency_failures = []
    if panel_submission_decision_state.get("status") != _W2_PANEL_SUBMISSION_DECISION_READY_STATUS:
        consistency_failures.append({
            "kind": "panel_submission_decision_status_not_ready",
            "observed": panel_submission_decision_state.get("status"),
        })
    if panel_submission_decision_state.get("decision") != "awaiting_explicit_approval":
        consistency_failures.append({
            "kind": "panel_submission_decision_not_awaiting_explicit_approval",
            "observed": panel_submission_decision_state.get("decision"),
        })
    if panel_submission_decision_state.get("audit_ok") is not True:
        consistency_failures.append({
            "kind": "panel_submission_decision_audit_not_ok",
            "observed": panel_submission_decision_state.get("audit_ok"),
        })
    if panel_submission_decision_state.get("no_submit") is not True:
        consistency_failures.append({
            "kind": "panel_submission_decision_submit_drift",
            "observed": panel_submission_decision_state.get("no_submit"),
        })
    if panel_submission_decision_state.get("submitted") is not False:
        consistency_failures.append({
            "kind": "panel_submission_decision_already_submitted",
            "observed": panel_submission_decision_state.get("submitted"),
        })
    if panel_submission_decision_state.get("explicit_approval_required") is not True:
        consistency_failures.append({
            "kind": "panel_submission_decision_approval_not_required",
            "observed": panel_submission_decision_state.get("explicit_approval_required"),
        })
    approval_disambiguation = (
        panel_submission_decision_state.get("approval_disambiguation")
        if isinstance(panel_submission_decision_state.get("approval_disambiguation"), dict)
        else {}
    )
    non_approval_continuations = approval_disambiguation.get("non_approval_continuation_phrases")
    if not isinstance(non_approval_continuations, list):
        non_approval_continuations = []
    if approval_disambiguation.get("continuation_phrases_are_approval") is not False:
        consistency_failures.append({
            "kind": "panel_submission_decision_approval_disambiguation_missing",
            "observed": approval_disambiguation,
        })
    if "continue working toward the active thread goal" not in non_approval_continuations:
        consistency_failures.append({
            "kind": "panel_submission_decision_goal_continuation_boundary_missing",
            "observed": approval_disambiguation,
        })
    if panel_submission_decision_state.get("can_submit_if_explicitly_approved") is not True:
        consistency_failures.append({
            "kind": "panel_submission_decision_not_explicit_approval_ready",
            "observed": panel_submission_decision_state.get("can_submit_if_explicitly_approved"),
        })
    if panel_submission_decision_state.get("can_claim_w2_generalization") is not False:
        consistency_failures.append({
            "kind": "panel_submission_decision_claim_boundary_drift",
            "observed": panel_submission_decision_state.get("can_claim_w2_generalization"),
        })
    if not local_absence_ok:
        consistency_failures.append({
            "kind": "panel_submission_decision_local_receipt_absence_not_verified",
            "observed": receipt_absence.get("local"),
        })
    if not remote_absence_ok:
        consistency_failures.append({
            "kind": "panel_submission_decision_remote_receipt_absence_not_verified",
            "observed": {
                "remote_checked": receipt_absence.get("remote_checked"),
                "remote": receipt_absence.get("remote"),
            },
        })

    ready = not decision_failures and not consistency_failures
    status.update({
        "panel_submission_decision_state": panel_submission_decision_state.get("_path"),
        "panel_submission_decision_ready": ready,
        "panel_submission_decision_status": panel_submission_decision_state.get("status"),
        "panel_submission_decision": panel_submission_decision_state.get("decision"),
        "panel_submission_decision_no_submit": panel_submission_decision_state.get("no_submit"),
        "panel_submission_decision_submitted": panel_submission_decision_state.get("submitted"),
        "panel_submission_decision_explicit_approval_required": panel_submission_decision_state.get(
            "explicit_approval_required"
        ),
        "panel_submission_decision_continuation_phrases_are_approval": approval_disambiguation.get(
            "continuation_phrases_are_approval"
        ),
        "panel_submission_decision_non_approval_continuation_phrases": non_approval_continuations,
        "panel_submission_decision_approval_must_explicitly_name": approval_disambiguation.get(
            "approval_must_explicitly_name"
        ),
        "panel_submission_decision_machine_gate": approval_disambiguation.get("machine_gate"),
        "panel_submission_decision_can_submit_if_explicitly_approved": panel_submission_decision_state.get(
            "can_submit_if_explicitly_approved"
        ),
        "panel_submission_decision_can_claim_w2_generalization": panel_submission_decision_state.get(
            "can_claim_w2_generalization"
        ),
        "panel_submission_decision_remote_checked": remote_checked,
        "panel_submission_decision_local_receipt_absence_ok": local_absence_ok,
        "panel_submission_decision_remote_receipt_absence_ok": remote_absence_ok,
        "panel_submission_decision_failures": decision_failures + consistency_failures,
    })
    if ready:
        status.update({
            "complete": False,
            "next_action": (
                "submission decision is recorded; await explicit user approval before guarded W2 panel submission; "
                "then sync back, run completion, and certify target-wise panel report"
            ),
        })
    else:
        status.update({
            "status": "panel_submission_decision_state_blocked",
            "complete": False,
            "failures": failures + decision_failures + consistency_failures,
            "next_action": "repair panel submission-decision state before panel approval or submission",
        })
    return status


def _attach_w2_panel_postsync_interpretation(status: Dict[str, Any],
                                             panel_postsync_interpretation: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(panel_postsync_interpretation):
        status.update({
            "status": "panel_postsync_interpretation_missing",
            "panel_postsync_interpretation_ready": False,
            "panel_postsync_interpretation": panel_postsync_interpretation.get("_path"),
            "message": panel_postsync_interpretation.get("message", ""),
            "next_action": "rerun m6d_w2_panel_postsync_interpretation.py before post-sync W2 interpretation",
        })
        return status

    failures = (
        panel_postsync_interpretation.get("failures")
        if isinstance(panel_postsync_interpretation.get("failures"), list)
        else []
    )
    consistency_failures: List[Dict[str, Any]] = []
    allowed_statuses = {
        "not_synced_not_interpretable",
        "ready_for_target_wise_panel_report",
        "w2_generalization_supported_by_target_wise_panel",
        "w2_generalization_not_supported_target_wise",
        "panel_report_not_multi_target_proof",
    }
    current_result = (
        panel_postsync_interpretation.get("current_panel_result")
        if isinstance(panel_postsync_interpretation.get("current_panel_result"), dict)
        else {}
    )
    ready = True
    if panel_postsync_interpretation.get("status") not in allowed_statuses:
        consistency_failures.append({
            "kind": "panel_postsync_interpretation_status_unknown",
            "observed": panel_postsync_interpretation.get("status"),
        })
    if panel_postsync_interpretation.get("audit_ok") is not True:
        consistency_failures.append({
            "kind": "panel_postsync_interpretation_audit_not_ok",
            "observed": panel_postsync_interpretation.get("audit_ok"),
        })
    if panel_postsync_interpretation.get("no_submit") is not True:
        consistency_failures.append({
            "kind": "panel_postsync_interpretation_submit_drift",
            "observed": panel_postsync_interpretation.get("no_submit"),
        })
    if (
        panel_postsync_interpretation.get("can_claim_w2_generalization") is True
        and current_result.get("status") != "w2_generalization_supported_by_target_wise_panel"
    ):
        consistency_failures.append({
            "kind": "panel_postsync_interpretation_claim_without_supported_panel",
            "observed": {
                "can_claim_w2_generalization": panel_postsync_interpretation.get("can_claim_w2_generalization"),
                "current_panel_result.status": current_result.get("status"),
            },
        })
    if consistency_failures or failures:
        ready = False

    status.update({
        "panel_postsync_interpretation": panel_postsync_interpretation.get("_path"),
        "panel_postsync_interpretation_ready": ready,
        "panel_postsync_status": panel_postsync_interpretation.get("status"),
        "panel_postsync_no_submit": panel_postsync_interpretation.get("no_submit"),
        "panel_postsync_submitted": panel_postsync_interpretation.get("submitted"),
        "panel_postsync_sync_ready": panel_postsync_interpretation.get("sync_ready"),
        "panel_postsync_can_claim_w2_generalization": panel_postsync_interpretation.get(
            "can_claim_w2_generalization"
        ),
        "panel_postsync_target_alpha": panel_postsync_interpretation.get("target_alpha"),
        "panel_postsync_min_targets": panel_postsync_interpretation.get("min_targets"),
        "panel_postsync_min_records_per_target": panel_postsync_interpretation.get("min_records_per_target"),
        "panel_postsync_current_result_status": current_result.get("status"),
        "panel_postsync_interpretation_failures": failures + consistency_failures,
    })
    if not ready:
        status.update({
            "status": "panel_postsync_interpretation_blocked",
            "complete": False,
            "failures": failures + consistency_failures,
            "next_action": "repair post-sync interpretation before W2 panel claim or goal completion",
        })
    return status


def _w2_status(target_manifest: Optional[Dict[str, Any]], panel_completion: Optional[Dict[str, Any]],
               panel_report: Optional[Dict[str, Any]], target_alpha: float,
               input_prep_completion: Optional[Dict[str, Any]] = None,
               target_msa_gate_audit: Optional[Dict[str, Any]] = None,
               target_msa_approval_packet: Optional[Dict[str, Any]] = None,
               target_msa_approval_parity: Optional[Dict[str, Any]] = None,
               panel_approval_packet: Optional[Dict[str, Any]] = None,
               panel_decision_protocol: Optional[Dict[str, Any]] = None,
               panel_remote_readiness: Optional[Dict[str, Any]] = None,
               panel_submission_decision_state: Optional[Dict[str, Any]] = None,
               panel_postsync_interpretation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    missing_panel_report = panel_report if _is_missing_artifact(panel_report) else None
    if missing_panel_report is not None:
        panel_report = None
    if target_msa_gate_audit is not None:
        status = _w2_target_msa_gate_status(target_msa_gate_audit)
        if target_manifest is not None:
            status["superseded_target_manifest"] = target_manifest.get("_path")
            status["superseded_target_manifest_status"] = target_manifest.get("status")
        if panel_completion is not None:
            status["superseded_panel_completion"] = panel_completion.get("_path")
            status["superseded_panel_completion_status"] = panel_completion.get("status")
            status["superseded_panel_completion_records"] = panel_completion.get("records", [])
            status["superseded_panel_completion_failures"] = panel_completion.get("failures", [])
        if panel_report is not None:
            status["superseded_panel_report"] = panel_report.get("_path")
            status["superseded_panel_report_status"] = panel_report.get("panel_status") or panel_report.get("status")
        if missing_panel_report is not None:
            status["superseded_panel_report"] = missing_panel_report.get("_path")
            status["superseded_panel_report_status"] = missing_panel_report.get("status")
        if target_msa_approval_packet is not None:
            status = _attach_w2_approval_packet(status, target_msa_approval_packet)
        if target_msa_approval_parity is not None:
            status = _attach_w2_approval_parity(status, target_msa_approval_parity)
        if panel_approval_packet is not None:
            status = _attach_w2_panel_approval_packet(status, panel_approval_packet)
        if panel_decision_protocol is not None:
            status = _attach_w2_panel_decision_protocol(status, panel_decision_protocol)
        if panel_remote_readiness is not None:
            status = _attach_w2_panel_remote_readiness(status, panel_remote_readiness)
        if panel_submission_decision_state is not None:
            status = _attach_w2_panel_submission_decision_state(status, panel_submission_decision_state)
        if panel_postsync_interpretation is not None:
            status = _attach_w2_panel_postsync_interpretation(status, panel_postsync_interpretation)
        return status
    if panel_report is not None:
        mismatch = _alpha_mismatch(panel_report, target_alpha)
        if mismatch is not None:
            return _alpha_mismatch_status(
                workstream="W2_multi_target_panel",
                status="panel_report_alpha_mismatch",
                artifact_alpha=mismatch,
                target_alpha=target_alpha,
                evidence=panel_report.get("_path"),
                next_action="rerun status with the matching --target-alpha or regenerate panel report for the requested alpha",
            )
        panel_status = panel_report.get("panel_status")
        audit_failures = _w2_panel_report_audit_failures(panel_report)
        if panel_report.get("ok") and panel_status == "multi_target_certified" and not audit_failures:
            status = "multi_target_certified"
            complete = True
            next_action = "use panel evidence; continue to second-predictor validation if still open"
        elif panel_status == "multi_target_evaluable_not_certified":
            status = "evaluable_not_certified"
            complete = False
            next_action = "continue per-target scale or inspect target-specific failures"
        elif panel_status == "qc_failed":
            status = "qc_failed"
            complete = False
            next_action = "fix panel records QC"
        else:
            status = "not_multi_target_proof"
            complete = False
            next_action = "fix panel failures before making a multi-target claim"
        return {
            "workstream": "W2_multi_target_panel",
            "status": status,
            "complete": complete,
            "n_targets": panel_report.get("n_targets"),
            "n_records": panel_report.get("n_records"),
            "failures": list(panel_report.get("failures", [])) + audit_failures,
            "audit_failures": audit_failures,
            "message": panel_report.get("message", ""),
            "next_action": next_action,
            "evidence": panel_report.get("_path"),
        }

    if target_manifest is not None and not target_manifest.get("ok"):
        status = _w2_target_manifest_status(target_manifest)
        if status["status"] == "panel_waiting_on_input_prep" and input_prep_completion is not None:
            status = _input_prep_completion_status(
                input_prep_completion,
                workstream="W2_multi_target_panel",
                status_prefix="panel",
                ready_next_action="run manifest_command to refresh the target manifest and emit the panel submission plan",
            )
            status["superseded_target_manifest"] = target_manifest.get("_path")
            status["superseded_target_manifest_status"] = "panel_waiting_on_input_prep"
        if panel_completion is not None:
            status["superseded_panel_completion"] = panel_completion.get("_path")
            status["superseded_panel_completion_status"] = panel_completion.get("status")
            status["superseded_panel_completion_records"] = panel_completion.get("records", [])
            status["superseded_panel_completion_failures"] = panel_completion.get("failures", [])
        if missing_panel_report is not None:
            status["superseded_panel_report"] = missing_panel_report.get("_path")
            status["superseded_panel_report_status"] = missing_panel_report.get("status")
        return status

    if panel_completion is not None:
        return _w2_completion_status(panel_completion, target_alpha=target_alpha)

    if target_manifest is not None:
        status = _w2_target_manifest_status(target_manifest)
        if panel_approval_packet is not None:
            status = _attach_w2_panel_approval_packet(status, panel_approval_packet)
        if panel_decision_protocol is not None:
            status = _attach_w2_panel_decision_protocol(status, panel_decision_protocol)
        if panel_remote_readiness is not None:
            status = _attach_w2_panel_remote_readiness(status, panel_remote_readiness)
        if panel_submission_decision_state is not None:
            status = _attach_w2_panel_submission_decision_state(status, panel_submission_decision_state)
        if panel_postsync_interpretation is not None:
            status = _attach_w2_panel_postsync_interpretation(status, panel_postsync_interpretation)
        return status

    if input_prep_completion is not None:
        return _input_prep_completion_status(
            input_prep_completion,
            workstream="W2_multi_target_panel",
            status_prefix="panel",
            ready_next_action="run manifest_command to refresh the target manifest and emit the panel submission plan",
        )

    if missing_panel_report is not None:
        return {
            "workstream": "W2_multi_target_panel",
            "status": "panel_report_missing",
            "complete": False,
            "message": missing_panel_report.get("message", ""),
            "next_action": "generate panel records and run complex_panel_report.py before making a multi-target claim",
            "evidence": missing_panel_report.get("_path"),
        }

    return {
        "workstream": "W2_multi_target_panel",
        "status": "missing",
        "complete": False,
        "message": "No target manifest or panel report artifact provided.",
        "next_action": "prepare/validate >=3 heterodimer targets",
    }


def _w3_contract_status(predictor_contract: Dict[str, Any]) -> Dict[str, Any]:
    if _is_missing_artifact(predictor_contract):
        return {
            "workstream": "W3_independent_predictor",
            "status": "second_predictor_contract_missing",
            "complete": False,
            "commands": {},
            "commands_available": False,
            "blocked_command_keys": [],
            "failures": [],
            "message": predictor_contract.get("message", ""),
            "next_action": "copy and fill a second-predictor contract, then run complex_predictor_contract.py",
            "evidence": predictor_contract.get("_path"),
        }
    predictor = predictor_contract.get("secondary_predictor")
    if not isinstance(predictor, dict):
        predictor = {}
    commands = predictor_contract.get("commands")
    if not isinstance(commands, dict):
        commands = {}
    if predictor_contract.get("ok"):
        status = "second_predictor_contract_ready"
        next_action = "run cross-predictor command from predictor contract report"
        commands_out = commands
        commands_available = True
    else:
        status = "second_predictor_contract_blocked"
        next_action = "fix second-predictor contract or records before cross-predictor claims"
        commands_out = {}
        commands_available = False
    return {
        "workstream": "W3_independent_predictor",
        "status": status,
        "complete": False,
        "secondary_predictor": predictor,
        "primary_records": predictor_contract.get("primary_records", []),
        "secondary_records": predictor_contract.get("secondary_records", []),
        "pending_secondary_records": predictor_contract.get("pending_secondary_records", []),
        "commands": commands_out,
        "commands_available": commands_available,
        "blocked_command_keys": [] if commands_available else sorted(commands),
        "failures": predictor_contract.get("failures", []),
        "next_action": next_action,
        "evidence": predictor_contract.get("_path"),
    }


def _w3_cross_predictor_audit_failures(cross_predictor: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    declared_predictors: Optional[List[str]] = None
    min_overlap = cross_predictor.get("min_overlap")
    min_label_agreement = cross_predictor.get("min_label_agreement")
    predictors = cross_predictor.get("predictors")
    if not (
        isinstance(predictors, list)
        and predictors
        and all(isinstance(pred, str) and pred.strip() for pred in predictors)
    ):
        failures.append({
            "kind": "cross_predictor_predictors_invalid",
            "field": "predictors",
            "message": "cross-predictor report must list non-empty predictor ids",
        })
    else:
        declared_predictors = sorted(pred.strip() for pred in predictors)
        if len(set(declared_predictors)) != len(declared_predictors):
            failures.append({
                "kind": "cross_predictor_predictors_duplicate",
                "field": "predictors",
                "predictors": declared_predictors,
                "message": "cross-predictor report must not duplicate predictor ids",
            })

    if not isinstance(min_overlap, int) or isinstance(min_overlap, bool) or min_overlap <= 0:
        failures.append({
            "kind": "cross_predictor_min_overlap_invalid",
            "field": "min_overlap",
            "min_overlap": min_overlap,
            "message": "cross-predictor report must include a positive integer min_overlap",
        })
        min_overlap = None
    if (
        not isinstance(min_label_agreement, (int, float))
        or isinstance(min_label_agreement, bool)
        or not 0.0 <= float(min_label_agreement) <= 1.0
    ):
        failures.append({
            "kind": "cross_predictor_min_label_agreement_invalid",
            "field": "min_label_agreement",
            "min_label_agreement": min_label_agreement,
            "message": "cross-predictor report must include min_label_agreement in [0, 1]",
        })
        min_label_agreement = None
    else:
        min_label_agreement = float(min_label_agreement)

    declared_counts: Optional[Dict[str, int]] = None
    records_by_predictor = cross_predictor.get("records_by_predictor")
    if not isinstance(records_by_predictor, dict) or not records_by_predictor:
        failures.append({
            "kind": "cross_predictor_records_by_predictor_invalid",
            "field": "records_by_predictor",
            "message": "cross-predictor report must include non-empty records_by_predictor counts",
        })
    else:
        declared_counts = {}
        for pred, count in records_by_predictor.items():
            if (
                not isinstance(pred, str)
                or not pred.strip()
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ):
                declared_counts = None
                failures.append({
                    "kind": "cross_predictor_records_by_predictor_invalid",
                    "field": "records_by_predictor",
                    "predictor": pred,
                    "count": count,
                    "message": "records_by_predictor keys must be non-empty strings with positive integer counts",
                })
                break
            declared_counts[pred.strip()] = count

    reported_failures = cross_predictor.get("failures", [])
    if not isinstance(reported_failures, list):
        failures.append({
            "kind": "cross_predictor_failures_field_invalid",
            "field": "failures",
            "message": "cross-predictor failures field must be a list",
        })
    elif reported_failures:
        failures.append({
            "kind": "cross_predictor_report_has_failures",
            "field": "failures",
            "n_failures": len(reported_failures),
            "message": "cross-predictor terminal evidence must not contain reported failures",
        })
    if cross_predictor.get("require_disjoint_record_files") is not True:
        failures.append({
            "kind": "cross_predictor_disjoint_record_files_not_required",
            "field": "require_disjoint_record_files",
            "message": "cross-predictor report must be generated with --require-disjoint-record-files",
        })
    record_files = cross_predictor.get("record_files")
    if not isinstance(record_files, list) or not record_files:
        failures.append({
            "kind": "cross_predictor_record_file_audit_missing",
            "field": "record_files",
            "message": "cross-predictor report must include per-JSONL predictor membership",
        })
        return failures
    file_predictors: List[str] = []
    file_counts: Dict[str, int] = {}
    seen_paths = set()
    for entry in record_files:
        if not isinstance(entry, dict):
            failures.append({
                "kind": "cross_predictor_record_file_audit_invalid",
                "field": "record_files",
                "message": "record_files entries must be objects",
            })
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            failures.append({
                "kind": "cross_predictor_record_file_path_invalid",
                "field": "record_files",
                "path": path,
                "message": "each record file audit entry must include a non-empty path",
            })
        elif path in seen_paths:
            failures.append({
                "kind": "cross_predictor_record_file_duplicate_path",
                "field": "record_files",
                "path": path,
                "message": "cross-predictor record file audit must not list the same path twice",
            })
        else:
            seen_paths.add(path)

        predictors = entry.get("predictors")
        if not isinstance(predictors, list) or not predictors:
            failures.append({
                "kind": "cross_predictor_record_file_predictors_missing",
                "field": "record_files",
                "path": entry.get("path"),
                "message": "each record file audit entry must list predictor membership",
            })
            file_predictor = None
        elif not all(isinstance(pred, str) and pred.strip() for pred in predictors):
            failures.append({
                "kind": "cross_predictor_record_file_predictors_invalid",
                "field": "record_files",
                "path": entry.get("path"),
                "predictors": predictors,
                "message": "record file predictor membership must use non-empty strings",
            })
            file_predictor = None
        elif len(predictors) > 1:
            failures.append({
                "kind": "mixed_predictor_record_file",
                "field": "record_files",
                "path": entry.get("path"),
                "predictors": predictors,
                "message": "each W3 input JSONL must contain records from only one predictor",
            })
            file_predictor = None
        else:
            file_predictor = predictors[0].strip()
            file_predictors.append(file_predictor)

        n_records = entry.get("n_records")
        if not isinstance(n_records, int) or isinstance(n_records, bool) or n_records <= 0:
            failures.append({
                "kind": "cross_predictor_record_file_count_invalid",
                "field": "record_files.n_records",
                "path": entry.get("path"),
                "n_records": n_records,
                "message": "each record file audit entry must include a positive integer n_records",
            })
            n_records = None

        file_records_by_predictor = entry.get("records_by_predictor")
        if not isinstance(file_records_by_predictor, dict) or not file_records_by_predictor:
            failures.append({
                "kind": "cross_predictor_record_file_records_by_predictor_invalid",
                "field": "record_files.records_by_predictor",
                "path": entry.get("path"),
                "message": "each record file audit entry must include per-predictor counts",
            })
            continue
        if file_predictor is None or n_records is None:
            continue
        if set(file_records_by_predictor) != {file_predictor}:
            failures.append({
                "kind": "cross_predictor_record_file_predictor_count_mismatch",
                "field": "record_files.records_by_predictor",
                "path": entry.get("path"),
                "predictors": predictors,
                "records_by_predictor": file_records_by_predictor,
                "message": "record file predictor counts must match the file's sole predictor",
            })
            continue
        file_count = file_records_by_predictor.get(file_predictor)
        if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count != n_records:
            failures.append({
                "kind": "cross_predictor_record_file_count_mismatch",
                "field": "record_files",
                "path": entry.get("path"),
                "predictor": file_predictor,
                "n_records": n_records,
                "records_by_predictor": file_records_by_predictor,
                "message": "record file n_records must match its records_by_predictor count",
            })
            continue
        file_counts[file_predictor] = file_counts.get(file_predictor, 0) + file_count

    unique_file_predictors = sorted(set(file_predictors))
    if len(unique_file_predictors) < 2:
        failures.append({
            "kind": "cross_predictor_record_file_too_few_predictors",
            "field": "record_files",
            "predictors": unique_file_predictors,
            "message": "strict W3 evidence requires record files from at least two predictors",
        })
    if declared_predictors is not None and unique_file_predictors != declared_predictors:
        failures.append({
            "kind": "cross_predictor_record_file_predictor_mismatch",
            "field": "record_files",
            "expected": declared_predictors,
            "actual": unique_file_predictors,
            "message": "record file predictor membership must match top-level predictors",
        })
    if declared_counts is not None and file_counts and file_counts != declared_counts:
        failures.append({
            "kind": "cross_predictor_record_file_count_mismatch",
            "field": "record_files",
            "expected": declared_counts,
            "actual": file_counts,
            "message": "summed record file counts must match top-level records_by_predictor",
        })

    pairs = cross_predictor.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        failures.append({
            "kind": "cross_predictor_pair_audit_missing",
            "field": "pairs",
            "message": "strict W3 evidence requires pair-level cross-predictor audit records",
        })
        return failures

    observed_pair_keys = set()
    for idx, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            failures.append({
                "kind": "cross_predictor_pair_audit_invalid",
                "field": "pairs",
                "index": idx,
                "message": "pair audit entries must be objects",
            })
            continue
        a = pair.get("predictor_a")
        b = pair.get("predictor_b")
        if not isinstance(a, str) or not a.strip() or not isinstance(b, str) or not b.strip() or a == b:
            failures.append({
                "kind": "cross_predictor_pair_predictor_invalid",
                "field": "pairs",
                "index": idx,
                "predictor_a": a,
                "predictor_b": b,
                "message": "each pair audit entry must name two distinct predictors",
            })
            continue
        pair_key = tuple(sorted((a.strip(), b.strip())))
        if pair_key in observed_pair_keys:
            failures.append({
                "kind": "cross_predictor_pair_duplicate",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "message": "pair audit entries must not duplicate predictor pairs",
            })
        observed_pair_keys.add(pair_key)
        if declared_predictors is not None and any(pred not in set(declared_predictors) for pred in pair_key):
            failures.append({
                "kind": "cross_predictor_pair_predictor_mismatch",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "predictors": declared_predictors,
                "message": "pair audit predictors must be listed in the top-level predictors field",
            })

        n_overlap = pair.get("n_overlap")
        n_labeled = pair.get("n_labeled_overlap")
        label_agreement = pair.get("label_agreement")
        if (
            min_overlap is not None
            and (
                not isinstance(n_overlap, int)
                or isinstance(n_overlap, bool)
                or n_overlap < min_overlap
                or pair.get("meets_min_overlap") is not True
            )
        ):
            failures.append({
                "kind": "cross_predictor_pair_overlap_below_min",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "n_overlap": n_overlap,
                "required": min_overlap,
                "message": "pair audit overlap must meet min_overlap",
            })
        if (
            min_overlap is not None
            and (
                not isinstance(n_labeled, int)
                or isinstance(n_labeled, bool)
                or n_labeled < min_overlap
                or pair.get("meets_min_labeled_overlap") is not True
            )
        ):
            failures.append({
                "kind": "cross_predictor_pair_labeled_overlap_below_min",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "n_labeled_overlap": n_labeled,
                "required": min_overlap,
                "message": "pair audit labeled overlap must meet min_overlap",
            })
        if (
            min_label_agreement is not None
            and (
                not isinstance(label_agreement, (int, float))
                or isinstance(label_agreement, bool)
                or float(label_agreement) < min_label_agreement
                or pair.get("meets_min_label_agreement") is not True
            )
        ):
            failures.append({
                "kind": "cross_predictor_pair_label_agreement_below_min",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "label_agreement": label_agreement,
                "required": min_label_agreement,
                "message": "pair audit label agreement must meet min_label_agreement",
            })
        if not (
            pair.get("provenance_complete") is True
            and pair.get("distinct_signal_sources") is True
            and pair.get("distinct_label_sources") is True
        ):
            failures.append({
                "kind": "cross_predictor_pair_provenance_weak",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "message": "pair audit must show complete distinct signal and label provenance",
            })
        if not (
            pair.get("complex_target_id_complete") is True
            and pair.get("complex_target_id_agree") is True
        ):
            failures.append({
                "kind": "cross_predictor_pair_target_identity_weak",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "message": "pair audit must show complete matching complex_target_id",
            })
        if not (
            pair.get("label_threshold_complete") is True
            and pair.get("label_threshold_agree") is True
        ):
            failures.append({
                "kind": "cross_predictor_pair_label_threshold_mismatch",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "message": "pair audit must show matched lrmsd_threshold definitions",
            })
        if pair.get("copied_numeric_values") is not False:
            failures.append({
                "kind": "cross_predictor_pair_copied_numeric_values",
                "field": "pairs",
                "index": idx,
                "pair": list(pair_key),
                "message": "pair audit must not indicate copied pAE/L-RMSD values",
            })

    if declared_predictors is not None:
        expected_pair_keys = {
            (declared_predictors[i], declared_predictors[j])
            for i in range(len(declared_predictors))
            for j in range(i + 1, len(declared_predictors))
        }
        if observed_pair_keys != expected_pair_keys:
            failures.append({
                "kind": "cross_predictor_pair_set_mismatch",
                "field": "pairs",
                "expected": [list(pair) for pair in sorted(expected_pair_keys)],
                "actual": [list(pair) for pair in sorted(observed_pair_keys)],
                "message": "pair audit set must match every top-level predictor pair",
            })
    return failures


_W3_NEGATIVE_ROBUSTNESS_STATUS = "negative_robustness_result_adjudicated"
_W3_NEXT_PROTOCOL_READY_STATUS = "w3_next_protocol_ready_no_spend"
_W3_CHALLENGE_MANIFEST_READY_STATUS = "w3_challenge_manifest_ready_no_submit"
_W3_THIRD_PREDICTOR_CONTRACT_READY_STATUS = "w3_third_predictor_contract_ready_no_submit"
_W3_PREDICTOR_SELECTION_CARD_READY_STATUS = "w3_predictor_selection_card_ready_no_submit"
_W3_RUNTIME_PROBE_PLAN_READY_STATUS = "w3_runtime_probe_plan_ready_no_submit"
_W3_RUNTIME_PROBE_REPORT_RECORDED_STATUS = "w3_runtime_probe_report_recorded_runtime_not_ready_no_submit"
_W3_RUNTIME_PROBE_REPORT_READY_STATUS = "w3_runtime_probe_report_runtime_ready_no_submit"
_W3_RUNTIME_REPAIR_PLAN_READY_STATUS = "w3_runtime_repair_plan_ready_no_submit"
_W3_RUNTIME_PROVISION_PACKET_READY_STATUS = "w3_runtime_provision_packet_ready_no_submit"
_W3_NEXT_PRIMARY_ROUTE = "third_independent_predictor_or_protocol"
_W3_NEXT_SECONDARY_ROUTE = "stronger_chai_msa_template_protocol"


def _resolve_existing_artifact_path(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not path.strip():
        return None
    return path if os.path.isabs(path) else os.path.abspath(path)


def _w3_adjudication_set_artifact_audit(w3: Dict[str, Any]) -> Dict[str, Any]:
    artifact = w3.get("adjudication_set_artifact")
    failures: List[Dict[str, Any]] = []
    if not isinstance(artifact, dict):
        return {
            "ok": False,
            "failures": [{
                "kind": "w3_adjudication_set_artifact_missing",
                "message": "W3 negative robustness status requires a materialized adjudication set artifact",
            }],
        }

    out_jsonl = _resolve_existing_artifact_path(artifact.get("out_jsonl"))
    expected_sha = artifact.get("out_jsonl_sha256")
    if out_jsonl is None:
        failures.append({
            "kind": "w3_adjudication_set_jsonl_path_missing",
            "message": "adjudication_set_artifact.out_jsonl must be a non-empty path",
        })
    elif not os.path.exists(out_jsonl):
        failures.append({
            "kind": "w3_adjudication_set_jsonl_missing",
            "path": out_jsonl,
        })
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        failures.append({
            "kind": "w3_adjudication_set_jsonl_sha256_missing",
            "message": "adjudication_set_artifact.out_jsonl_sha256 must be a 64-character sha256",
            "actual": expected_sha,
        })

    rows: List[Dict[str, Any]] = []
    actual_sha = None
    if out_jsonl is not None and os.path.exists(out_jsonl):
        actual_sha = _sha256_file(out_jsonl)
        if isinstance(expected_sha, str) and expected_sha != actual_sha:
            failures.append({
                "kind": "w3_adjudication_set_jsonl_sha256_mismatch",
                "path": out_jsonl,
                "expected": expected_sha,
                "actual": actual_sha,
            })
        try:
            rows = _load_jsonl_records(out_jsonl)
        except Exception as exc:
            failures.append({
                "kind": "w3_adjudication_set_jsonl_parse_failed",
                "path": out_jsonl,
                "error": str(exc),
            })

    expected_n_rows = artifact.get("n_rows")
    if not isinstance(expected_n_rows, int) or expected_n_rows <= 0:
        failures.append({
            "kind": "w3_adjudication_set_n_rows_invalid",
            "actual": expected_n_rows,
        })
    elif rows and len(rows) != expected_n_rows:
        failures.append({
            "kind": "w3_adjudication_set_n_rows_mismatch",
            "expected": expected_n_rows,
            "actual": len(rows),
        })

    counts: Dict[str, int] = {}
    target_ids_by_role: Dict[str, List[str]] = {}
    allowed_roles = {"discordant_boltz_chai_label", "concordant_success_control"}
    for row in rows:
        role = row.get("adjudication_role")
        target_id = row.get("target_id")
        if role not in allowed_roles:
            failures.append({
                "kind": "w3_adjudication_set_role_invalid",
                "target_id": target_id,
                "role": role,
            })
            continue
        if not isinstance(target_id, str) or not target_id:
            failures.append({
                "kind": "w3_adjudication_set_target_id_missing",
                "role": role,
            })
            continue
        counts[role] = counts.get(role, 0) + 1
        target_ids_by_role.setdefault(role, []).append(target_id)

    expected_counts = artifact.get("counts_by_role")
    if isinstance(expected_counts, dict) and rows:
        normalized_counts = {
            str(role): int(count)
            for role, count in expected_counts.items()
            if isinstance(count, int)
        }
        if normalized_counts != counts:
            failures.append({
                "kind": "w3_adjudication_set_role_counts_mismatch",
                "expected": normalized_counts,
                "actual": counts,
            })

    expected_ids_by_role = artifact.get("target_ids_by_role")
    if isinstance(expected_ids_by_role, dict) and rows:
        normalized_expected_ids = {
            str(role): sorted(ids)
            for role, ids in expected_ids_by_role.items()
            if isinstance(ids, list)
        }
        normalized_actual_ids = {
            role: sorted(ids)
            for role, ids in target_ids_by_role.items()
        }
        if normalized_expected_ids != normalized_actual_ids:
            failures.append({
                "kind": "w3_adjudication_set_target_ids_by_role_mismatch",
                "expected": normalized_expected_ids,
                "actual": normalized_actual_ids,
            })

    adjudication_set = w3.get("adjudication_set") if isinstance(w3.get("adjudication_set"), dict) else {}
    expected_discordant = sorted(adjudication_set.get("discordant_target_ids", []))
    expected_controls = sorted(adjudication_set.get("concordant_success_control_ids", []))
    actual_discordant = sorted(target_ids_by_role.get("discordant_boltz_chai_label", []))
    actual_controls = sorted(target_ids_by_role.get("concordant_success_control", []))
    if rows and expected_discordant != actual_discordant:
        failures.append({
            "kind": "w3_adjudication_set_discordant_ids_mismatch",
            "expected": expected_discordant,
            "actual": actual_discordant,
        })
    if rows and expected_controls != actual_controls:
        failures.append({
            "kind": "w3_adjudication_set_control_ids_mismatch",
            "expected": expected_controls,
            "actual": actual_controls,
        })

    return {
        "ok": not failures,
        "path": out_jsonl,
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "n_rows": len(rows),
        "counts_by_role": counts,
        "failures": failures,
    }


def _w3_decision_protocol_failures(decision_protocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    w3 = decision_protocol.get("w3")
    if not isinstance(w3, dict):
        return [{
            "kind": "w3_decision_protocol_missing_w3_section",
            "message": "W3 decision protocol must contain a w3 object",
        }]
    if w3.get("status") != "protocol_selected":
        failures.append({
            "kind": "w3_decision_protocol_status_invalid",
            "expected": "protocol_selected",
            "actual": w3.get("status"),
        })
    if w3.get("current_protocol_verdict") != "negative_robustness_result_for_no_msa_chai":
        failures.append({
            "kind": "w3_decision_protocol_verdict_invalid",
            "expected": "negative_robustness_result_for_no_msa_chai",
            "actual": w3.get("current_protocol_verdict"),
        })
    if w3.get("claim_boundary") != "independent_predictor_robustness_not_supported":
        failures.append({
            "kind": "w3_decision_protocol_claim_boundary_invalid",
            "expected": "independent_predictor_robustness_not_supported",
            "actual": w3.get("claim_boundary"),
        })
    if not isinstance(w3.get("selected_protocol"), str) or not w3.get("selected_protocol", "").strip():
        failures.append({
            "kind": "w3_decision_protocol_selected_protocol_missing",
            "message": "W3 decision protocol must name the selected adjudication protocol",
        })
    if w3.get("strict_adjudication_integrity") is not True:
        failures.append({
            "kind": "w3_decision_protocol_integrity_not_strict",
            "message": "W3 negative robustness status requires strict adjudication integrity",
        })
    blockers = w3.get("strict_adjudication_integrity_blockers")
    if blockers not in (None, []) and blockers:
        failures.append({
            "kind": "w3_decision_protocol_integrity_blockers_present",
            "blockers": blockers,
        })
    failure_kinds = w3.get("cross_predictor_failure_kinds")
    if not isinstance(failure_kinds, list) or "label_agreement_below_min" not in failure_kinds:
        failures.append({
            "kind": "w3_decision_protocol_negative_signal_missing",
            "message": "negative robustness status requires the predeclared label-agreement failure kind",
        })
    adjudication_set = w3.get("adjudication_set")
    discordant_ids = (
        adjudication_set.get("discordant_target_ids")
        if isinstance(adjudication_set, dict)
        else None
    )
    control_ids = (
        adjudication_set.get("concordant_success_control_ids")
        if isinstance(adjudication_set, dict)
        else None
    )
    if not isinstance(discordant_ids, list) or not discordant_ids:
        failures.append({
            "kind": "w3_decision_protocol_adjudication_discordants_missing",
            "message": "negative robustness status requires a non-empty discordant adjudication set",
        })
    if not isinstance(control_ids, list) or not control_ids:
        failures.append({
            "kind": "w3_decision_protocol_adjudication_controls_missing",
            "message": "negative robustness status requires non-empty concordant-success controls",
        })
    artifact_audit = _w3_adjudication_set_artifact_audit(w3)
    if artifact_audit.get("ok") is not True:
        failures.extend(artifact_audit.get("failures", []))
    return failures


def _w3_decision_protocol_status(decision_protocol: Dict[str, Any],
                                 cross_predictor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if _is_missing_artifact(decision_protocol):
        return {
            "workstream": "W3_independent_predictor",
            "status": "w3_decision_protocol_missing",
            "complete": False,
            "message": decision_protocol.get("message", ""),
            "next_action": "regenerate the W3 decision protocol before treating predictor disagreement as resolved",
            "evidence": decision_protocol.get("_path"),
        }
    failures = _w3_decision_protocol_failures(decision_protocol)
    w3 = decision_protocol.get("w3") if isinstance(decision_protocol.get("w3"), dict) else {}
    if failures:
        return {
            "workstream": "W3_independent_predictor",
            "status": "w3_decision_protocol_blocked",
            "complete": False,
            "failures": failures,
            "message": "W3 decision protocol does not pass strict negative-result integrity checks",
            "next_action": "fix W3 decision protocol integrity blockers before treating predictor disagreement as resolved",
            "evidence": decision_protocol.get("_path"),
        }
    cross_predictor_path = (
        cross_predictor.get("_path")
        if isinstance(cross_predictor, dict) and not _is_missing_artifact(cross_predictor)
        else None
    )
    return {
        "workstream": "W3_independent_predictor",
        "status": _W3_NEGATIVE_ROBUSTNESS_STATUS,
        "complete": True,
        "positive_claim_supported": False,
        "claim_boundary": w3.get("claim_boundary"),
        "current_protocol_verdict": w3.get("current_protocol_verdict"),
        "selected_protocol": w3.get("selected_protocol"),
        "strict_adjudication_integrity": w3.get("strict_adjudication_integrity"),
        "strict_adjudication_integrity_blockers": w3.get("strict_adjudication_integrity_blockers", []),
        "cross_predictor_failure_kinds": w3.get("cross_predictor_failure_kinds", []),
        "label_agreement": w3.get("label_agreement"),
        "min_label_agreement": w3.get("min_label_agreement"),
        "matched_overlap": w3.get("matched_overlap"),
        "adjudication_set": w3.get("adjudication_set", {}),
        "adjudication_set_artifact": w3.get("adjudication_set_artifact"),
        "adjudication_set_artifact_audit": _w3_adjudication_set_artifact_audit(w3),
        "protocol_rules": w3.get("protocol_rules", []),
        "next_action": w3.get(
            "next_spend_gate",
            "do not make a positive W3 claim; use the adjudication set before any future W3 spend",
        ),
        "evidence": decision_protocol.get("_path"),
        "cross_predictor_evidence": cross_predictor_path,
    }


def _int_counts(obj: Any) -> Dict[str, int]:
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, int] = {}
    for key, value in obj.items():
        if isinstance(key, str) and isinstance(value, int):
            out[key] = value
    return out


def _w3_next_expected_counts(w3_status: Dict[str, Any]) -> Dict[str, int]:
    artifact_audit = w3_status.get("adjudication_set_artifact_audit")
    if not isinstance(artifact_audit, dict):
        return {}
    return _int_counts(artifact_audit.get("counts_by_role"))


def _w3_next_expected_rows(w3_status: Dict[str, Any]) -> Optional[int]:
    artifact_audit = w3_status.get("adjudication_set_artifact_audit")
    if not isinstance(artifact_audit, dict):
        return None
    rows = artifact_audit.get("n_rows")
    return rows if isinstance(rows, int) else None


def _w3_next_expected_sha(w3_status: Dict[str, Any]) -> Optional[str]:
    artifact_audit = w3_status.get("adjudication_set_artifact_audit")
    if not isinstance(artifact_audit, dict):
        return None
    sha = artifact_audit.get("actual_sha256")
    return sha if isinstance(sha, str) and sha else None


def _w3_next_expected_jsonl(w3_status: Dict[str, Any]) -> Optional[str]:
    artifact_audit = w3_status.get("adjudication_set_artifact_audit")
    if not isinstance(artifact_audit, dict):
        return None
    return _resolve_existing_artifact_path(artifact_audit.get("path"))


def _w3_next_protocol_failures(next_protocol: Dict[str, Any],
                               w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if next_protocol.get("status") != _W3_NEXT_PROTOCOL_READY_STATUS:
        failures.append({
            "kind": "w3_next_protocol_status_invalid",
            "expected": _W3_NEXT_PROTOCOL_READY_STATUS,
            "actual": next_protocol.get("status"),
        })
    if next_protocol.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_next_protocol_audit_not_ok",
            "expected": True,
            "actual": next_protocol.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if next_protocol.get(field) is not True:
            failures.append({
                "kind": f"w3_next_protocol_{field}_not_true",
                "expected": True,
                "actual": next_protocol.get(field),
            })
    if next_protocol.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_next_protocol_claim_leak",
            "expected": False,
            "actual": next_protocol.get("can_claim_independent_predictor_robustness_now"),
        })
    if next_protocol.get("positive_claim_supported") is not False:
        failures.append({
            "kind": "w3_next_protocol_positive_claim_leak",
            "expected": False,
            "actual": next_protocol.get("positive_claim_supported"),
        })

    current = next_protocol.get("current_w3_result")
    if not isinstance(current, dict):
        failures.append({
            "kind": "w3_next_protocol_current_result_missing",
            "message": "W3 next protocol must record the W3 result it is extending",
        })
        current = {}
    expected_current = {
        "status": w3_status.get("status"),
        "verdict": w3_status.get("current_protocol_verdict"),
        "claim_boundary": w3_status.get("claim_boundary"),
    }
    for field, expected in expected_current.items():
        if expected is not None and current.get(field) != expected:
            failures.append({
                "kind": f"w3_next_protocol_current_{field}_mismatch",
                "expected": expected,
                "actual": current.get(field),
            })
    label_agreement = current.get("label_agreement")
    min_label_agreement = current.get("min_label_agreement")
    if not (
        isinstance(label_agreement, (int, float))
        and isinstance(min_label_agreement, (int, float))
        and label_agreement < min_label_agreement
    ):
        failures.append({
            "kind": "w3_next_protocol_negative_signal_missing",
            "expected": "label_agreement < min_label_agreement",
            "actual": {
                "label_agreement": label_agreement,
                "min_label_agreement": min_label_agreement,
            },
        })

    contract = next_protocol.get("adjudication_set_contract")
    if not isinstance(contract, dict):
        failures.append({
            "kind": "w3_next_protocol_adjudication_contract_missing",
            "message": "W3 next protocol must contain an adjudication_set_contract object",
        })
        contract = {}
    expected_counts = _w3_next_expected_counts(w3_status)
    expected_rows = _w3_next_expected_rows(w3_status)
    expected_sha = _w3_next_expected_sha(w3_status)
    expected_jsonl = _w3_next_expected_jsonl(w3_status)
    for field in ("counts_by_role", "required_counts_by_role"):
        counts = _int_counts(contract.get(field))
        if expected_counts and counts != expected_counts:
            failures.append({
                "kind": f"w3_next_protocol_{field}_mismatch",
                "expected": expected_counts,
                "actual": counts,
            })
    if expected_rows is not None and contract.get("n_rows") != expected_rows:
        failures.append({
            "kind": "w3_next_protocol_row_count_mismatch",
            "expected": expected_rows,
            "actual": contract.get("n_rows"),
        })
    if expected_sha is not None and contract.get("jsonl_sha256") != expected_sha:
        failures.append({
            "kind": "w3_next_protocol_sha_mismatch",
            "expected": expected_sha,
            "actual": contract.get("jsonl_sha256"),
        })
    contract_jsonl = _resolve_existing_artifact_path(contract.get("jsonl"))
    if expected_jsonl is not None and contract_jsonl != expected_jsonl:
        failures.append({
            "kind": "w3_next_protocol_jsonl_path_mismatch",
            "expected": expected_jsonl,
            "actual": contract_jsonl,
        })

    routes = next_protocol.get("recommended_next_routes")
    route_names = [
        route.get("route")
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("route"), str)
    ] if isinstance(routes, list) else []
    if route_names[:2] != [_W3_NEXT_PRIMARY_ROUTE, _W3_NEXT_SECONDARY_ROUTE]:
        failures.append({
            "kind": "w3_next_protocol_route_order_mismatch",
            "expected": [_W3_NEXT_PRIMARY_ROUTE, _W3_NEXT_SECONDARY_ROUTE],
            "actual": route_names[:2],
        })

    decision = next_protocol.get("decision_contract")
    if not isinstance(decision, dict):
        failures.append({
            "kind": "w3_next_protocol_decision_contract_missing",
            "message": "W3 next protocol must predeclare the challenge-panel decision contract",
        })
        decision = {}
    discordant = expected_counts.get("discordant_boltz_chai_label")
    controls = expected_counts.get("concordant_success_control")
    if isinstance(discordant, int):
        expected_threshold = int(math.ceil(discordant * 0.80))
        if decision.get("discordant_alignment_threshold") != expected_threshold:
            failures.append({
                "kind": "w3_next_protocol_discordant_threshold_mismatch",
                "expected": expected_threshold,
                "actual": decision.get("discordant_alignment_threshold"),
            })
    if isinstance(controls, int):
        expected_threshold = int(math.ceil(controls * 0.80))
        if decision.get("control_consistency_threshold") != expected_threshold:
            failures.append({
                "kind": "w3_next_protocol_control_threshold_mismatch",
                "expected": expected_threshold,
                "actual": decision.get("control_consistency_threshold"),
            })
    return failures


def _attach_w3_next_protocol(w3_status: Dict[str, Any],
                             next_protocol: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if next_protocol is None:
        return w3_status
    if _is_missing_artifact(next_protocol):
        failures = [{
            "kind": "w3_next_protocol_missing",
            "message": next_protocol.get("message", "W3 next protocol artifact is missing"),
            "path": next_protocol.get("_path"),
        }]
    else:
        failures = _w3_next_protocol_failures(next_protocol, w3_status)
    ready = not failures
    decision = (
        next_protocol.get("decision_contract")
        if isinstance(next_protocol, dict) and isinstance(next_protocol.get("decision_contract"), dict)
        else {}
    )
    routes = (
        next_protocol.get("recommended_next_routes")
        if isinstance(next_protocol, dict) and isinstance(next_protocol.get("recommended_next_routes"), list)
        else []
    )
    w3_status["w3_next_protocol"] = {
        "path": next_protocol.get("_path") if isinstance(next_protocol, dict) else None,
        "status": next_protocol.get("status") if isinstance(next_protocol, dict) else None,
        "ready": ready,
        "audit_ok": next_protocol.get("audit_ok") if isinstance(next_protocol, dict) else None,
        "no_submit": next_protocol.get("no_submit") if isinstance(next_protocol, dict) else None,
        "no_api_spend": next_protocol.get("no_api_spend") if isinstance(next_protocol, dict) else None,
        "no_gpu_spend": next_protocol.get("no_gpu_spend") if isinstance(next_protocol, dict) else None,
        "can_claim_independent_predictor_robustness_now": False,
        "recommended_routes": [
            route.get("route")
            for route in routes
            if isinstance(route, dict) and isinstance(route.get("route"), str)
        ],
        "decision_contract": decision,
        "failures": failures,
    }
    w3_status["w3_next_protocol_ready"] = ready
    w3_status["future_w3_spend_requires_explicit_approval"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_next_protocol_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 next-protocol contract before any future W3 spend; "
            "preserve the negative robustness boundary meanwhile"
        )
    else:
        w3_status["recommended_next_routes"] = w3_status["w3_next_protocol"]["recommended_routes"]
        w3_status["w3_next_decision_contract"] = decision
        recommended = next_protocol.get("recommended_next_action") if isinstance(next_protocol, dict) else None
        if isinstance(recommended, str) and recommended.strip():
            w3_status["next_action"] = recommended
    return w3_status


def _w3_challenge_manifest_failures(challenge_manifest: Dict[str, Any],
                                    w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if challenge_manifest.get("status") != _W3_CHALLENGE_MANIFEST_READY_STATUS:
        failures.append({
            "kind": "w3_challenge_manifest_status_invalid",
            "expected": _W3_CHALLENGE_MANIFEST_READY_STATUS,
            "actual": challenge_manifest.get("status"),
        })
    if challenge_manifest.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_challenge_manifest_audit_not_ok",
            "expected": True,
            "actual": challenge_manifest.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if challenge_manifest.get(field) is not True:
            failures.append({
                "kind": f"w3_challenge_manifest_{field}_not_true",
                "expected": True,
                "actual": challenge_manifest.get(field),
            })
    if challenge_manifest.get("execution_ready") is not False:
        failures.append({
            "kind": "w3_challenge_manifest_execution_ready_drift",
            "expected": False,
            "actual": challenge_manifest.get("execution_ready"),
        })
    if challenge_manifest.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_challenge_manifest_claim_leak",
            "expected": False,
            "actual": challenge_manifest.get("can_claim_independent_predictor_robustness_now"),
        })

    expected_rows = _w3_next_expected_rows(w3_status)
    expected_counts = _w3_next_expected_counts(w3_status)
    expected_sha = _w3_next_expected_sha(w3_status)
    expected_jsonl = _w3_next_expected_jsonl(w3_status)
    panel = challenge_manifest.get("challenge_panel")
    if not isinstance(panel, dict):
        failures.append({
            "kind": "w3_challenge_manifest_panel_missing",
            "message": "challenge manifest must contain a challenge_panel object",
        })
        panel = {}
    if expected_rows is not None and panel.get("n_rows") != expected_rows:
        failures.append({
            "kind": "w3_challenge_manifest_row_count_mismatch",
            "expected": expected_rows,
            "actual": panel.get("n_rows"),
        })
    panel_counts = _int_counts(panel.get("counts_by_role"))
    if expected_counts and panel_counts != expected_counts:
        failures.append({
            "kind": "w3_challenge_manifest_role_count_mismatch",
            "expected": expected_counts,
            "actual": panel_counts,
        })
    if expected_sha is not None and challenge_manifest.get("source_adjudication_sha256") != expected_sha:
        failures.append({
            "kind": "w3_challenge_manifest_sha_mismatch",
            "expected": expected_sha,
            "actual": challenge_manifest.get("source_adjudication_sha256"),
        })
    manifest_jsonl = _resolve_existing_artifact_path(challenge_manifest.get("source_adjudication_jsonl"))
    if expected_jsonl is not None and manifest_jsonl != expected_jsonl:
        failures.append({
            "kind": "w3_challenge_manifest_jsonl_path_mismatch",
            "expected": expected_jsonl,
            "actual": manifest_jsonl,
        })

    target_ids = panel.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids:
        failures.append({
            "kind": "w3_challenge_manifest_target_ids_missing",
            "message": "challenge manifest must list selected target IDs",
        })
        target_ids = []
    elif expected_rows is not None and len(target_ids) != expected_rows:
        failures.append({
            "kind": "w3_challenge_manifest_target_id_count_mismatch",
            "expected": expected_rows,
            "actual": len(target_ids),
        })
    source_audit = challenge_manifest.get("source_record_audit")
    if not isinstance(source_audit, list) or not source_audit:
        failures.append({
            "kind": "w3_challenge_manifest_source_audit_missing",
            "message": "challenge manifest must audit source record coverage",
        })
        source_audit = []
    for item in source_audit:
        if not isinstance(item, dict):
            failures.append({
                "kind": "w3_challenge_manifest_source_audit_invalid",
                "actual": item,
            })
            continue
        if item.get("exists") is not True:
            failures.append({
                "kind": "w3_challenge_manifest_source_record_missing",
                "path": item.get("path"),
            })
        if expected_rows is not None and item.get("selected_seen") != expected_rows:
            failures.append({
                "kind": "w3_challenge_manifest_source_coverage_incomplete",
                "expected": expected_rows,
                "actual": item.get("selected_seen"),
                "path": item.get("path"),
            })
        missing = item.get("missing_selected_target_ids")
        if isinstance(missing, list) and missing:
            failures.append({
                "kind": "w3_challenge_manifest_source_missing_target_ids",
                "path": item.get("path"),
                "missing": missing,
            })

    if challenge_manifest.get("recommended_next_route") != _W3_NEXT_PRIMARY_ROUTE:
        failures.append({
            "kind": "w3_challenge_manifest_primary_route_mismatch",
            "expected": _W3_NEXT_PRIMARY_ROUTE,
            "actual": challenge_manifest.get("recommended_next_route"),
        })
    blockers = challenge_manifest.get("execution_blockers")
    if not isinstance(blockers, list) or not blockers:
        failures.append({
            "kind": "w3_challenge_manifest_execution_blockers_missing",
            "message": "challenge manifest must preserve explicit execution blockers",
        })
    return failures


def _attach_w3_challenge_manifest(w3_status: Dict[str, Any],
                                  challenge_manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if challenge_manifest is None:
        return w3_status
    if _is_missing_artifact(challenge_manifest):
        failures = [{
            "kind": "w3_challenge_manifest_missing",
            "message": challenge_manifest.get("message", "W3 challenge manifest artifact is missing"),
            "path": challenge_manifest.get("_path"),
        }]
    else:
        failures = _w3_challenge_manifest_failures(challenge_manifest, w3_status)
    ready = not failures
    panel = (
        challenge_manifest.get("challenge_panel")
        if isinstance(challenge_manifest, dict) and isinstance(challenge_manifest.get("challenge_panel"), dict)
        else {}
    )
    source_audit = (
        challenge_manifest.get("source_record_audit")
        if isinstance(challenge_manifest, dict) and isinstance(challenge_manifest.get("source_record_audit"), list)
        else []
    )
    w3_status["w3_challenge_manifest"] = {
        "path": challenge_manifest.get("_path") if isinstance(challenge_manifest, dict) else None,
        "status": challenge_manifest.get("status") if isinstance(challenge_manifest, dict) else None,
        "ready": ready,
        "audit_ok": challenge_manifest.get("audit_ok") if isinstance(challenge_manifest, dict) else None,
        "no_submit": challenge_manifest.get("no_submit") if isinstance(challenge_manifest, dict) else None,
        "no_api_spend": challenge_manifest.get("no_api_spend") if isinstance(challenge_manifest, dict) else None,
        "no_gpu_spend": challenge_manifest.get("no_gpu_spend") if isinstance(challenge_manifest, dict) else None,
        "execution_ready": False,
        "can_claim_independent_predictor_robustness_now": False,
        "n_rows": panel.get("n_rows"),
        "counts_by_role": panel.get("counts_by_role"),
        "target_ids": panel.get("target_ids"),
        "source_record_audit": source_audit,
        "failures": failures,
    }
    w3_status["w3_challenge_manifest_ready"] = ready
    w3_status["w3_challenge_execution_ready"] = False
    w3_status["future_w3_execution_requires_new_contract"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_challenge_manifest_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 challenge manifest before designing any third-predictor execution wrapper; "
            "preserve the negative robustness boundary meanwhile"
        )
    return w3_status


def _w3_challenge_expected_target_ids(w3_status: Dict[str, Any]) -> List[str]:
    challenge = w3_status.get("w3_challenge_manifest")
    if not isinstance(challenge, dict):
        return []
    ids = challenge.get("target_ids")
    if isinstance(ids, list):
        return [target_id for target_id in ids if isinstance(target_id, str)]
    return []


def _w3_third_predictor_contract_failures(third_predictor_contract: Dict[str, Any],
                                          w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if third_predictor_contract.get("status") != _W3_THIRD_PREDICTOR_CONTRACT_READY_STATUS:
        failures.append({
            "kind": "w3_third_predictor_contract_status_invalid",
            "expected": _W3_THIRD_PREDICTOR_CONTRACT_READY_STATUS,
            "actual": third_predictor_contract.get("status"),
        })
    if third_predictor_contract.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_third_predictor_contract_audit_not_ok",
            "expected": True,
            "actual": third_predictor_contract.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if third_predictor_contract.get(field) is not True:
            failures.append({
                "kind": f"w3_third_predictor_contract_{field}_not_true",
                "expected": True,
                "actual": third_predictor_contract.get(field),
            })
    if third_predictor_contract.get("execution_ready") is not False:
        failures.append({
            "kind": "w3_third_predictor_contract_execution_ready_drift",
            "expected": False,
            "actual": third_predictor_contract.get("execution_ready"),
        })
    if third_predictor_contract.get("command_wrapper_emitted") is not False:
        failures.append({
            "kind": "w3_third_predictor_contract_wrapper_emitted_drift",
            "expected": False,
            "actual": third_predictor_contract.get("command_wrapper_emitted"),
        })
    if third_predictor_contract.get("approval_token_emitted") is not False:
        failures.append({
            "kind": "w3_third_predictor_contract_approval_token_drift",
            "expected": False,
            "actual": third_predictor_contract.get("approval_token_emitted"),
        })
    if third_predictor_contract.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_third_predictor_contract_claim_leak",
            "expected": False,
            "actual": third_predictor_contract.get("can_claim_independent_predictor_robustness_now"),
        })

    if w3_status.get("w3_challenge_manifest_ready") is not True:
        failures.append({
            "kind": "w3_third_predictor_contract_challenge_manifest_not_ready",
            "message": "third-predictor contract requires the W3 challenge manifest to be consumed and ready",
        })
    challenge = w3_status.get("w3_challenge_manifest")
    if not isinstance(challenge, dict):
        challenge = {}
    contract_panel = (
        third_predictor_contract.get("challenge_panel_contract")
        if isinstance(third_predictor_contract.get("challenge_panel_contract"), dict)
        else {}
    )
    expected_rows = challenge.get("n_rows")
    if isinstance(expected_rows, int) and contract_panel.get("n_rows") != expected_rows:
        failures.append({
            "kind": "w3_third_predictor_contract_row_count_mismatch",
            "expected": expected_rows,
            "actual": contract_panel.get("n_rows"),
        })
    expected_counts = _int_counts(challenge.get("counts_by_role"))
    observed_counts = _int_counts(contract_panel.get("counts_by_role"))
    if expected_counts and observed_counts != expected_counts:
        failures.append({
            "kind": "w3_third_predictor_contract_role_count_mismatch",
            "expected": expected_counts,
            "actual": observed_counts,
        })
    expected_ids = _w3_challenge_expected_target_ids(w3_status)
    observed_ids_raw = contract_panel.get("target_ids")
    observed_ids = [
        target_id for target_id in observed_ids_raw
        if isinstance(target_id, str)
    ] if isinstance(observed_ids_raw, list) else []
    if expected_ids and observed_ids != expected_ids:
        failures.append({
            "kind": "w3_third_predictor_contract_target_ids_mismatch",
            "expected": expected_ids,
            "actual": observed_ids,
        })

    challenge_path = challenge.get("path")
    expected_challenge_path = _resolve_existing_artifact_path(challenge_path)
    contract_challenge_path = _resolve_existing_artifact_path(
        third_predictor_contract.get("source_challenge_manifest"),
    )
    if expected_challenge_path and contract_challenge_path != expected_challenge_path:
        failures.append({
            "kind": "w3_third_predictor_contract_challenge_path_mismatch",
            "expected": expected_challenge_path,
            "actual": contract_challenge_path,
        })
    if expected_challenge_path and os.path.exists(expected_challenge_path):
        expected_sha = _sha256_file(expected_challenge_path)
        if third_predictor_contract.get("source_challenge_manifest_sha256") != expected_sha:
            failures.append({
                "kind": "w3_third_predictor_contract_challenge_sha_mismatch",
                "expected": expected_sha,
                "actual": third_predictor_contract.get("source_challenge_manifest_sha256"),
            })

    selection = (
        third_predictor_contract.get("predictor_selection_contract")
        if isinstance(third_predictor_contract.get("predictor_selection_contract"), dict)
        else {}
    )
    if selection.get("route") != _W3_NEXT_PRIMARY_ROUTE:
        failures.append({
            "kind": "w3_third_predictor_contract_route_mismatch",
            "expected": _W3_NEXT_PRIMARY_ROUTE,
            "actual": selection.get("route"),
        })
    required_fields = selection.get("required_selection_fields")
    if not isinstance(required_fields, list) or "approval_gate" not in required_fields:
        failures.append({
            "kind": "w3_third_predictor_contract_approval_gate_missing",
            "message": "third-predictor selection contract must require an approval_gate field",
        })

    output = (
        third_predictor_contract.get("output_contract")
        if isinstance(third_predictor_contract.get("output_contract"), dict)
        else {}
    )
    if isinstance(expected_rows, int) and output.get("required_n_rows") != expected_rows:
        failures.append({
            "kind": "w3_third_predictor_contract_output_row_count_mismatch",
            "expected": expected_rows,
            "actual": output.get("required_n_rows"),
        })
    output_ids_raw = output.get("required_target_ids")
    output_ids = [
        target_id for target_id in output_ids_raw
        if isinstance(target_id, str)
    ] if isinstance(output_ids_raw, list) else []
    if expected_ids and output_ids != expected_ids:
        failures.append({
            "kind": "w3_third_predictor_contract_output_target_ids_mismatch",
            "expected": expected_ids,
            "actual": output_ids,
        })
    required_schema = output.get("required_result_schema")
    if not isinstance(required_schema, list) or "target_id" not in required_schema or "provenance" not in required_schema:
        failures.append({
            "kind": "w3_third_predictor_contract_result_schema_incomplete",
            "message": "third-predictor output contract must require target_id and provenance",
        })
    future_artifacts = third_predictor_contract.get("future_artifacts_required")
    if not isinstance(future_artifacts, list) or "approval_gated_command_wrapper" not in future_artifacts:
        failures.append({
            "kind": "w3_third_predictor_contract_future_wrapper_requirement_missing",
            "message": "third-predictor contract must require a future approval-gated command wrapper",
        })
    blockers = third_predictor_contract.get("execution_blockers")
    if not isinstance(blockers, list) or not blockers:
        failures.append({
            "kind": "w3_third_predictor_contract_execution_blockers_missing",
            "message": "third-predictor contract must preserve explicit execution blockers",
        })
    return failures


def _attach_w3_third_predictor_contract(
    w3_status: Dict[str, Any],
    third_predictor_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if third_predictor_contract is None:
        return w3_status
    if _is_missing_artifact(third_predictor_contract):
        failures = [{
            "kind": "w3_third_predictor_contract_missing",
            "message": third_predictor_contract.get("message", "W3 third-predictor contract artifact is missing"),
            "path": third_predictor_contract.get("_path"),
        }]
    else:
        failures = _w3_third_predictor_contract_failures(third_predictor_contract, w3_status)
    ready = not failures
    panel = (
        third_predictor_contract.get("challenge_panel_contract")
        if isinstance(third_predictor_contract, dict)
        and isinstance(third_predictor_contract.get("challenge_panel_contract"), dict)
        else {}
    )
    output = (
        third_predictor_contract.get("output_contract")
        if isinstance(third_predictor_contract, dict)
        and isinstance(third_predictor_contract.get("output_contract"), dict)
        else {}
    )
    w3_status["w3_third_predictor_contract"] = {
        "path": third_predictor_contract.get("_path") if isinstance(third_predictor_contract, dict) else None,
        "status": third_predictor_contract.get("status") if isinstance(third_predictor_contract, dict) else None,
        "ready": ready,
        "audit_ok": third_predictor_contract.get("audit_ok") if isinstance(third_predictor_contract, dict) else None,
        "no_submit": third_predictor_contract.get("no_submit") if isinstance(third_predictor_contract, dict) else None,
        "no_api_spend": third_predictor_contract.get("no_api_spend") if isinstance(third_predictor_contract, dict) else None,
        "no_gpu_spend": third_predictor_contract.get("no_gpu_spend") if isinstance(third_predictor_contract, dict) else None,
        "execution_ready": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "n_rows": panel.get("n_rows"),
        "counts_by_role": panel.get("counts_by_role"),
        "planned_result_jsonl": output.get("planned_jsonl"),
        "required_result_schema": output.get("required_result_schema"),
        "future_artifacts_required": third_predictor_contract.get("future_artifacts_required")
        if isinstance(third_predictor_contract, dict) else None,
        "failures": failures,
    }
    w3_status["w3_third_predictor_contract_ready"] = ready
    w3_status["w3_third_predictor_execution_ready"] = False
    w3_status["future_w3_execution_requires_explicit_approval"] = True
    w3_status["future_w3_execution_requires_approval_gated_wrapper"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_third_predictor_contract_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 third-predictor execution contract before selecting or wrapping a future predictor; "
            "preserve the negative robustness boundary meanwhile"
        )
    return w3_status


def _w3_predictor_selection_card_failures(selection_card: Dict[str, Any],
                                          w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if selection_card.get("status") != _W3_PREDICTOR_SELECTION_CARD_READY_STATUS:
        failures.append({
            "kind": "w3_predictor_selection_card_status_invalid",
            "expected": _W3_PREDICTOR_SELECTION_CARD_READY_STATUS,
            "actual": selection_card.get("status"),
        })
    if selection_card.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_predictor_selection_card_audit_not_ok",
            "expected": True,
            "actual": selection_card.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if selection_card.get(field) is not True:
            failures.append({
                "kind": f"w3_predictor_selection_card_{field}_not_true",
                "expected": True,
                "actual": selection_card.get(field),
            })
    for field in ("execution_ready", "runtime_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted"):
        if selection_card.get(field) is not False:
            failures.append({
                "kind": f"w3_predictor_selection_card_{field}_drift",
                "expected": False,
                "actual": selection_card.get(field),
            })
    if selection_card.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_predictor_selection_card_claim_leak",
            "expected": False,
            "actual": selection_card.get("can_claim_independent_predictor_robustness_now"),
        })
    if w3_status.get("w3_third_predictor_contract_ready") is not True:
        failures.append({
            "kind": "w3_predictor_selection_card_third_contract_not_ready",
            "message": "predictor selection card requires the W3 third-predictor contract to be consumed and ready",
        })

    third_contract = (
        w3_status.get("w3_third_predictor_contract")
        if isinstance(w3_status.get("w3_third_predictor_contract"), dict)
        else {}
    )
    expected_contract_path = _resolve_existing_artifact_path(third_contract.get("path"))
    observed_contract_path = _resolve_existing_artifact_path(selection_card.get("source_third_predictor_contract"))
    if expected_contract_path and observed_contract_path != expected_contract_path:
        failures.append({
            "kind": "w3_predictor_selection_card_contract_path_mismatch",
            "expected": expected_contract_path,
            "actual": observed_contract_path,
        })
    if expected_contract_path and os.path.exists(expected_contract_path):
        expected_sha = _sha256_file(expected_contract_path)
        if selection_card.get("source_third_predictor_contract_sha256") != expected_sha:
            failures.append({
                "kind": "w3_predictor_selection_card_contract_sha_mismatch",
                "expected": expected_sha,
                "actual": selection_card.get("source_third_predictor_contract_sha256"),
            })

    selected = (
        selection_card.get("selected_predictor_protocol")
        if isinstance(selection_card.get("selected_predictor_protocol"), dict)
        else {}
    )
    selected_id = selected.get("predictor_or_protocol_id")
    if not isinstance(selected_id, str) or not selected_id.strip():
        failures.append({
            "kind": "w3_predictor_selection_card_selected_id_missing",
            "message": "selection card must name the selected predictor_or_protocol_id",
        })
    if selected_id in {"boltz2_complex", "chai1_complex", "same_no_msa_chai1_protocol"}:
        failures.append({
            "kind": "w3_predictor_selection_card_source_predictor_reselected",
            "actual": selected_id,
        })
    if selected.get("route") != _W3_NEXT_PRIMARY_ROUTE:
        failures.append({
            "kind": "w3_predictor_selection_card_route_mismatch",
            "expected": _W3_NEXT_PRIMARY_ROUTE,
            "actual": selected.get("route"),
        })
    if selected.get("selection_status") != "selected_pending_runtime_probe":
        failures.append({
            "kind": "w3_predictor_selection_card_selection_status_invalid",
            "expected": "selected_pending_runtime_probe",
            "actual": selected.get("selection_status"),
        })
    required_fields = selected.get("required_fields_satisfied")
    if not isinstance(required_fields, list) or "approval_gate" not in required_fields:
        failures.append({
            "kind": "w3_predictor_selection_card_approval_gate_missing",
            "message": "selection card must satisfy the approval_gate selection field",
        })
    runtime_probe = selection_card.get("runtime_probe_required")
    if not isinstance(runtime_probe, dict) or runtime_probe.get("required") is not True:
        failures.append({
            "kind": "w3_predictor_selection_card_runtime_probe_missing",
            "message": "selection card must keep runtime probing required before execution",
        })
    future = selection_card.get("future_artifacts_required")
    if not isinstance(future, list) or "execution_input_manifest" not in future or "approval_gated_command_wrapper" not in future:
        failures.append({
            "kind": "w3_predictor_selection_card_future_artifacts_incomplete",
            "message": "selection card must still require execution_input_manifest and approval_gated_command_wrapper",
        })
    blockers = selection_card.get("execution_blockers")
    if not isinstance(blockers, list) or not blockers:
        failures.append({
            "kind": "w3_predictor_selection_card_execution_blockers_missing",
            "message": "selection card must preserve explicit execution blockers",
        })
    return failures


def _attach_w3_predictor_selection_card(
    w3_status: Dict[str, Any],
    selection_card: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if selection_card is None:
        return w3_status
    if _is_missing_artifact(selection_card):
        failures = [{
            "kind": "w3_predictor_selection_card_missing",
            "message": selection_card.get("message", "W3 predictor selection card artifact is missing"),
            "path": selection_card.get("_path"),
        }]
    else:
        failures = _w3_predictor_selection_card_failures(selection_card, w3_status)
    ready = not failures
    selected = (
        selection_card.get("selected_predictor_protocol")
        if isinstance(selection_card, dict) and isinstance(selection_card.get("selected_predictor_protocol"), dict)
        else {}
    )
    w3_status["w3_predictor_selection_card"] = {
        "path": selection_card.get("_path") if isinstance(selection_card, dict) else None,
        "status": selection_card.get("status") if isinstance(selection_card, dict) else None,
        "ready": ready,
        "audit_ok": selection_card.get("audit_ok") if isinstance(selection_card, dict) else None,
        "selected_predictor_or_protocol_id": selected.get("predictor_or_protocol_id"),
        "model_or_protocol_family": selected.get("model_or_protocol_family"),
        "selection_status": selected.get("selection_status"),
        "runtime_ready": False,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "runtime_probe_required": selection_card.get("runtime_probe_required")
        if isinstance(selection_card, dict) else None,
        "future_artifacts_required": selection_card.get("future_artifacts_required")
        if isinstance(selection_card, dict) else None,
        "failures": failures,
    }
    w3_status["w3_predictor_selection_card_ready"] = ready
    w3_status["w3_selected_predictor_or_protocol_id"] = selected.get("predictor_or_protocol_id")
    w3_status["w3_selected_predictor_runtime_ready"] = False
    w3_status["w3_selected_predictor_execution_ready"] = False
    w3_status["future_w3_execution_requires_runtime_probe"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_predictor_selection_card_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 predictor selection card before generating execution inputs or wrappers; "
            "preserve the negative robustness boundary meanwhile"
        )
    else:
        recommended = selection_card.get("recommended_next_action") if isinstance(selection_card, dict) else None
        if isinstance(recommended, str) and recommended.strip():
            w3_status["next_action"] = recommended
        else:
            w3_status["next_action"] = (
                "probe/select the runtime for the selected W3 predictor protocol before generating "
                "execution inputs or wrappers; preserve the negative robustness boundary meanwhile"
            )
    return w3_status


def _w3_runtime_probe_plan_failures(runtime_probe_plan: Dict[str, Any],
                                    w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if runtime_probe_plan.get("status") != _W3_RUNTIME_PROBE_PLAN_READY_STATUS:
        failures.append({
            "kind": "w3_runtime_probe_plan_status_invalid",
            "expected": _W3_RUNTIME_PROBE_PLAN_READY_STATUS,
            "actual": runtime_probe_plan.get("status"),
        })
    if runtime_probe_plan.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_runtime_probe_plan_audit_not_ok",
            "expected": True,
            "actual": runtime_probe_plan.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if runtime_probe_plan.get(field) is not True:
            failures.append({
                "kind": f"w3_runtime_probe_plan_{field}_not_true",
                "expected": True,
                "actual": runtime_probe_plan.get(field),
            })
    for field in ("runtime_probe_ready", "runtime_ready", "probe_executed",
                  "execution_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted"):
        if runtime_probe_plan.get(field) is not False:
            failures.append({
                "kind": f"w3_runtime_probe_plan_{field}_drift",
                "expected": False,
                "actual": runtime_probe_plan.get(field),
            })
    if runtime_probe_plan.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_runtime_probe_plan_claim_leak",
            "expected": False,
            "actual": runtime_probe_plan.get("can_claim_independent_predictor_robustness_now"),
        })
    if w3_status.get("w3_predictor_selection_card_ready") is not True:
        failures.append({
            "kind": "w3_runtime_probe_plan_selection_card_not_ready",
            "message": "runtime-probe plan requires the W3 predictor selection card to be consumed and ready",
        })

    selection_card = (
        w3_status.get("w3_predictor_selection_card")
        if isinstance(w3_status.get("w3_predictor_selection_card"), dict)
        else {}
    )
    expected_selection_path = _resolve_existing_artifact_path(selection_card.get("path"))
    observed_selection_path = _resolve_existing_artifact_path(
        runtime_probe_plan.get("source_predictor_selection_card"),
    )
    if expected_selection_path and observed_selection_path != expected_selection_path:
        failures.append({
            "kind": "w3_runtime_probe_plan_selection_path_mismatch",
            "expected": expected_selection_path,
            "actual": observed_selection_path,
        })
    if expected_selection_path and os.path.exists(expected_selection_path):
        expected_sha = _sha256_file(expected_selection_path)
        if runtime_probe_plan.get("source_predictor_selection_card_sha256") != expected_sha:
            failures.append({
                "kind": "w3_runtime_probe_plan_selection_sha_mismatch",
                "expected": expected_sha,
                "actual": runtime_probe_plan.get("source_predictor_selection_card_sha256"),
            })

    expected_selected = w3_status.get("w3_selected_predictor_or_protocol_id")
    if runtime_probe_plan.get("selected_predictor_or_protocol_id") != expected_selected:
        failures.append({
            "kind": "w3_runtime_probe_plan_selected_protocol_mismatch",
            "expected": expected_selected,
            "actual": runtime_probe_plan.get("selected_predictor_or_protocol_id"),
        })

    contract = (
        runtime_probe_plan.get("probe_contract")
        if isinstance(runtime_probe_plan.get("probe_contract"), dict)
        else {}
    )
    checks = contract.get("checks")
    check_kinds = {
        check.get("kind")
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("kind"), str)
    } if isinstance(checks, list) else set()
    required_kinds = {"cli_help", "gpu_stack", "msa_policy", "dry_run_enumeration"}
    if not required_kinds.issubset(check_kinds):
        failures.append({
            "kind": "w3_runtime_probe_plan_required_checks_missing",
            "expected": sorted(required_kinds),
            "actual": sorted(check_kinds),
        })
    future = runtime_probe_plan.get("future_artifacts_required")
    required_future = {"runtime_probe_report", "execution_input_manifest", "approval_gated_command_wrapper"}
    if not isinstance(future, list) or not required_future.issubset(set(future)):
        failures.append({
            "kind": "w3_runtime_probe_plan_future_artifacts_incomplete",
            "expected": sorted(required_future),
            "actual": future,
        })
    blockers = runtime_probe_plan.get("execution_blockers")
    if not isinstance(blockers, list) or not blockers:
        failures.append({
            "kind": "w3_runtime_probe_plan_execution_blockers_missing",
            "message": "runtime-probe plan must preserve explicit execution blockers",
        })
    return failures


def _attach_w3_runtime_probe_plan(
    w3_status: Dict[str, Any],
    runtime_probe_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if runtime_probe_plan is None:
        return w3_status
    if _is_missing_artifact(runtime_probe_plan):
        failures = [{
            "kind": "w3_runtime_probe_plan_missing",
            "message": runtime_probe_plan.get("message", "W3 runtime-probe plan artifact is missing"),
            "path": runtime_probe_plan.get("_path"),
        }]
    else:
        failures = _w3_runtime_probe_plan_failures(runtime_probe_plan, w3_status)
    ready = not failures
    contract = (
        runtime_probe_plan.get("probe_contract")
        if isinstance(runtime_probe_plan, dict) and isinstance(runtime_probe_plan.get("probe_contract"), dict)
        else {}
    )
    w3_status["w3_runtime_probe_plan"] = {
        "path": runtime_probe_plan.get("_path") if isinstance(runtime_probe_plan, dict) else None,
        "status": runtime_probe_plan.get("status") if isinstance(runtime_probe_plan, dict) else None,
        "ready": ready,
        "audit_ok": runtime_probe_plan.get("audit_ok") if isinstance(runtime_probe_plan, dict) else None,
        "selected_predictor_or_protocol_id": runtime_probe_plan.get("selected_predictor_or_protocol_id")
        if isinstance(runtime_probe_plan, dict) else None,
        "probe_executed": False,
        "runtime_ready": False,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "probe_contract_checks": [
            check.get("kind")
            for check in contract.get("checks", [])
            if isinstance(check, dict)
        ],
        "future_artifacts_required": runtime_probe_plan.get("future_artifacts_required")
        if isinstance(runtime_probe_plan, dict) else None,
        "failures": failures,
    }
    w3_status["w3_runtime_probe_plan_ready"] = ready
    w3_status["w3_runtime_probe_plan_executed"] = False
    w3_status["w3_runtime_probe_executed"] = False
    w3_status["w3_selected_predictor_runtime_ready"] = False
    w3_status["w3_selected_predictor_execution_ready"] = False
    w3_status["future_w3_execution_requires_runtime_probe"] = True
    w3_status["future_w3_execution_requires_input_manifest"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_runtime_probe_plan_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 runtime-probe plan before probing runtime, generating inputs, "
            "or wrapping execution; preserve the negative robustness boundary meanwhile"
        )
    else:
        recommended = runtime_probe_plan.get("recommended_next_action") if isinstance(runtime_probe_plan, dict) else None
        if isinstance(recommended, str) and recommended.strip():
            w3_status["next_action"] = recommended
        else:
            w3_status["next_action"] = (
                "record a no-submit W3 runtime probe report before generating execution inputs "
                "or wrappers; preserve the negative robustness boundary meanwhile"
            )
    return w3_status


def _w3_runtime_probe_report_failures(runtime_probe_report: Dict[str, Any],
                                      w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if runtime_probe_report.get("status") not in {
        _W3_RUNTIME_PROBE_REPORT_RECORDED_STATUS,
        _W3_RUNTIME_PROBE_REPORT_READY_STATUS,
    }:
        failures.append({
            "kind": "w3_runtime_probe_report_status_invalid",
            "expected": [
                _W3_RUNTIME_PROBE_REPORT_RECORDED_STATUS,
                _W3_RUNTIME_PROBE_REPORT_READY_STATUS,
            ],
            "actual": runtime_probe_report.get("status"),
        })
    if runtime_probe_report.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_runtime_probe_report_audit_not_ok",
            "expected": True,
            "actual": runtime_probe_report.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if runtime_probe_report.get(field) is not True:
            failures.append({
                "kind": f"w3_runtime_probe_report_{field}_not_true",
                "expected": True,
                "actual": runtime_probe_report.get(field),
            })
    for field in ("execution_ready", "execution_inputs_emitted",
                  "command_wrapper_emitted", "approval_token_emitted"):
        if runtime_probe_report.get(field) is not False:
            failures.append({
                "kind": f"w3_runtime_probe_report_{field}_drift",
                "expected": False,
                "actual": runtime_probe_report.get(field),
            })
    if runtime_probe_report.get("probe_executed") is not True:
        failures.append({
            "kind": "w3_runtime_probe_report_probe_not_executed",
            "expected": True,
            "actual": runtime_probe_report.get("probe_executed"),
        })
    if runtime_probe_report.get("can_claim_independent_predictor_robustness_now") is not False:
        failures.append({
            "kind": "w3_runtime_probe_report_claim_leak",
            "expected": False,
            "actual": runtime_probe_report.get("can_claim_independent_predictor_robustness_now"),
        })
    if w3_status.get("w3_runtime_probe_plan_ready") is not True:
        failures.append({
            "kind": "w3_runtime_probe_report_plan_not_ready",
            "message": "runtime-probe report requires the W3 runtime-probe plan to be consumed and ready",
        })

    plan = (
        w3_status.get("w3_runtime_probe_plan")
        if isinstance(w3_status.get("w3_runtime_probe_plan"), dict)
        else {}
    )
    expected_plan_path = _resolve_existing_artifact_path(plan.get("path"))
    observed_plan_path = _resolve_existing_artifact_path(
        runtime_probe_report.get("source_runtime_probe_plan"),
    )
    expected_sha = None
    if expected_plan_path and os.path.exists(expected_plan_path):
        expected_sha = _sha256_file(expected_plan_path)
        if runtime_probe_report.get("source_runtime_probe_plan_sha256") != expected_sha:
            failures.append({
                "kind": "w3_runtime_probe_report_plan_sha_mismatch",
                "expected": expected_sha,
                "actual": runtime_probe_report.get("source_runtime_probe_plan_sha256"),
            })
    if (
        expected_plan_path
        and observed_plan_path != expected_plan_path
        and runtime_probe_report.get("source_runtime_probe_plan_sha256") != expected_sha
    ):
        failures.append({
            "kind": "w3_runtime_probe_report_plan_path_mismatch",
            "expected": expected_plan_path,
            "actual": observed_plan_path,
        })

    expected_selected = w3_status.get("w3_selected_predictor_or_protocol_id")
    if runtime_probe_report.get("selected_predictor_or_protocol_id") != expected_selected:
        failures.append({
            "kind": "w3_runtime_probe_report_selected_protocol_mismatch",
            "expected": expected_selected,
            "actual": runtime_probe_report.get("selected_predictor_or_protocol_id"),
        })

    checks = runtime_probe_report.get("observed_checks")
    check_kinds = {
        check.get("kind")
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("kind"), str)
    } if isinstance(checks, list) else set()
    required_kinds = {"env_discovery", "cli_help", "gpu_stack", "msa_policy", "dry_run_enumeration"}
    if not required_kinds.issubset(check_kinds):
        failures.append({
            "kind": "w3_runtime_probe_report_required_checks_missing",
            "expected": sorted(required_kinds),
            "actual": sorted(check_kinds),
        })
    future = runtime_probe_report.get("future_artifacts_required")
    required_future = {"execution_input_manifest", "approval_gated_command_wrapper"}
    if not isinstance(future, list) or not required_future.issubset(set(future)):
        failures.append({
            "kind": "w3_runtime_probe_report_future_artifacts_incomplete",
            "expected": sorted(required_future),
            "actual": future,
        })
    if (
        runtime_probe_report.get("status") == _W3_RUNTIME_PROBE_REPORT_READY_STATUS
        and runtime_probe_report.get("runtime_ready") is not True
    ):
        failures.append({
            "kind": "w3_runtime_probe_report_ready_status_runtime_not_ready",
            "expected": True,
            "actual": runtime_probe_report.get("runtime_ready"),
        })
    if (
        runtime_probe_report.get("status") == _W3_RUNTIME_PROBE_REPORT_RECORDED_STATUS
        and runtime_probe_report.get("runtime_ready") is not False
    ):
        failures.append({
            "kind": "w3_runtime_probe_report_recorded_status_runtime_ready_drift",
            "expected": False,
            "actual": runtime_probe_report.get("runtime_ready"),
        })
    return failures


def _attach_w3_runtime_probe_report(
    w3_status: Dict[str, Any],
    runtime_probe_report: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if runtime_probe_report is None:
        return w3_status
    if _is_missing_artifact(runtime_probe_report):
        failures = [{
            "kind": "w3_runtime_probe_report_missing",
            "message": runtime_probe_report.get("message", "W3 runtime-probe report artifact is missing"),
            "path": runtime_probe_report.get("_path"),
        }]
    else:
        failures = _w3_runtime_probe_report_failures(runtime_probe_report, w3_status)
    ready = not failures
    runtime_ready = bool(ready and runtime_probe_report.get("runtime_ready") is True)
    w3_status["w3_runtime_probe_report"] = {
        "path": runtime_probe_report.get("_path") if isinstance(runtime_probe_report, dict) else None,
        "status": runtime_probe_report.get("status") if isinstance(runtime_probe_report, dict) else None,
        "ready": ready,
        "audit_ok": runtime_probe_report.get("audit_ok") if isinstance(runtime_probe_report, dict) else None,
        "selected_predictor_or_protocol_id": runtime_probe_report.get("selected_predictor_or_protocol_id")
        if isinstance(runtime_probe_report, dict) else None,
        "probe_surface": runtime_probe_report.get("probe_surface") if isinstance(runtime_probe_report, dict) else None,
        "probe_executed": bool(ready and runtime_probe_report.get("probe_executed") is True),
        "cayuga_probe_executed": bool(ready and runtime_probe_report.get("cayuga_probe_executed") is True),
        "runtime_ready": runtime_ready,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "readiness_blockers": runtime_probe_report.get("readiness_blockers")
        if isinstance(runtime_probe_report, dict) else None,
        "failures": failures,
    }
    w3_status["w3_runtime_probe_report_ready"] = ready
    w3_status["w3_runtime_probe_report_executed"] = bool(
        ready and runtime_probe_report.get("probe_executed") is True
    )
    w3_status["w3_runtime_probe_executed"] = bool(ready and runtime_probe_report.get("probe_executed") is True)
    w3_status["w3_runtime_probe_cayuga_executed"] = bool(
        ready and runtime_probe_report.get("cayuga_probe_executed") is True
    )
    w3_status["w3_selected_predictor_runtime_ready"] = runtime_ready
    w3_status["w3_selected_predictor_execution_ready"] = False
    w3_status["future_w3_execution_requires_input_manifest"] = True
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_runtime_probe_report_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 runtime-probe report before treating runtime readiness as current; "
            "preserve the negative robustness boundary meanwhile"
        )
    elif runtime_ready:
        recommended = runtime_probe_report.get("recommended_next_action") if isinstance(runtime_probe_report, dict) else None
        w3_status["next_action"] = (
            recommended if isinstance(recommended, str) and recommended.strip()
            else "generate the no-submit W3 execution-input manifest; do not submit or predict"
        )
    else:
        recommended = runtime_probe_report.get("recommended_next_action") if isinstance(runtime_probe_report, dict) else None
        w3_status["next_action"] = (
            recommended if isinstance(recommended, str) and recommended.strip()
            else (
                "run the no-submit W3 runtime probe on the target Cayuga GPU surface before "
                "generating execution inputs"
            )
        )
    return w3_status


def _w3_runtime_repair_plan_failures(runtime_repair_plan: Dict[str, Any],
                                     w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if runtime_repair_plan.get("status") != _W3_RUNTIME_REPAIR_PLAN_READY_STATUS:
        failures.append({
            "kind": "w3_runtime_repair_plan_status_invalid",
            "expected": _W3_RUNTIME_REPAIR_PLAN_READY_STATUS,
            "actual": runtime_repair_plan.get("status"),
        })
    if runtime_repair_plan.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_runtime_repair_plan_audit_not_ok",
            "expected": True,
            "actual": runtime_repair_plan.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if runtime_repair_plan.get(field) is not True:
            failures.append({
                "kind": f"w3_runtime_repair_plan_{field}_not_true",
                "expected": True,
                "actual": runtime_repair_plan.get(field),
            })
    for field in ("prediction_executed", "runtime_ready", "execution_ready",
                  "execution_inputs_emitted", "command_wrapper_emitted",
                  "approval_token_emitted", "can_claim_independent_predictor_robustness_now"):
        if runtime_repair_plan.get(field) is not False:
            failures.append({
                "kind": f"w3_runtime_repair_plan_{field}_drift",
                "expected": False,
                "actual": runtime_repair_plan.get(field),
            })
    if w3_status.get("w3_runtime_probe_report_ready") is not True:
        failures.append({
            "kind": "w3_runtime_repair_plan_report_not_ready",
            "message": "runtime repair plan requires the W3 runtime-probe report to be consumed and ready",
        })
    report = (
        w3_status.get("w3_runtime_probe_report")
        if isinstance(w3_status.get("w3_runtime_probe_report"), dict)
        else {}
    )
    expected_report_path = _resolve_existing_artifact_path(report.get("path"))
    observed_report_path = _resolve_existing_artifact_path(
        runtime_repair_plan.get("source_runtime_probe_report"),
    )
    expected_sha = None
    if expected_report_path and os.path.exists(expected_report_path):
        expected_sha = _sha256_file(expected_report_path)
        if runtime_repair_plan.get("source_runtime_probe_report_sha256") != expected_sha:
            failures.append({
                "kind": "w3_runtime_repair_plan_report_sha_mismatch",
                "expected": expected_sha,
                "actual": runtime_repair_plan.get("source_runtime_probe_report_sha256"),
            })
    if (
        expected_report_path
        and observed_report_path != expected_report_path
        and runtime_repair_plan.get("source_runtime_probe_report_sha256") != expected_sha
    ):
        failures.append({
            "kind": "w3_runtime_repair_plan_report_path_mismatch",
            "expected": expected_report_path,
            "actual": observed_report_path,
        })
    expected_selected = w3_status.get("w3_selected_predictor_or_protocol_id")
    if runtime_repair_plan.get("selected_predictor_or_protocol_id") != expected_selected:
        failures.append({
            "kind": "w3_runtime_repair_plan_selected_protocol_mismatch",
            "expected": expected_selected,
            "actual": runtime_repair_plan.get("selected_predictor_or_protocol_id"),
        })
    failed_checks = set(runtime_repair_plan.get("failed_runtime_checks") or [])
    required_failed = {"env_discovery", "cli_help", "gpu_stack"}
    if not required_failed.issubset(failed_checks):
        failures.append({
            "kind": "w3_runtime_repair_plan_failed_checks_incomplete",
            "expected": sorted(required_failed),
            "actual": sorted(failed_checks),
        })
    repair_ids = {
        item.get("id")
        for item in runtime_repair_plan.get("repair_items") or []
        if isinstance(item, dict)
    }
    required_repairs = {"provision_colabfold_cli", "provision_jax_cuda_runtime"}
    if not required_repairs.issubset(repair_ids):
        failures.append({
            "kind": "w3_runtime_repair_plan_required_repairs_missing",
            "expected": sorted(required_repairs),
            "actual": sorted(repair_ids),
        })
    return failures


def _attach_w3_runtime_repair_plan(
    w3_status: Dict[str, Any],
    runtime_repair_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if runtime_repair_plan is None:
        return w3_status
    if _is_missing_artifact(runtime_repair_plan):
        failures = [{
            "kind": "w3_runtime_repair_plan_missing",
            "message": runtime_repair_plan.get("message", "W3 runtime repair plan artifact is missing"),
            "path": runtime_repair_plan.get("_path"),
        }]
    else:
        failures = _w3_runtime_repair_plan_failures(runtime_repair_plan, w3_status)
    ready = not failures
    w3_status["w3_runtime_repair_plan"] = {
        "path": runtime_repair_plan.get("_path") if isinstance(runtime_repair_plan, dict) else None,
        "status": runtime_repair_plan.get("status") if isinstance(runtime_repair_plan, dict) else None,
        "ready": ready,
        "audit_ok": runtime_repair_plan.get("audit_ok") if isinstance(runtime_repair_plan, dict) else None,
        "failed_runtime_checks": runtime_repair_plan.get("failed_runtime_checks")
        if isinstance(runtime_repair_plan, dict) else None,
        "passed_runtime_checks": runtime_repair_plan.get("passed_runtime_checks")
        if isinstance(runtime_repair_plan, dict) else None,
        "repair_item_ids": [
            item.get("id")
            for item in (runtime_repair_plan.get("repair_items") or [])
            if isinstance(item, dict)
        ] if isinstance(runtime_repair_plan, dict) else None,
        "runtime_ready": False,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "failures": failures,
    }
    w3_status["w3_runtime_repair_plan_ready"] = ready
    w3_status["w3_selected_predictor_runtime_ready"] = False
    w3_status["w3_selected_predictor_execution_ready"] = False
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_runtime_repair_plan_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 runtime repair-plan artifact before runtime installation or execution-input work"
        )
    else:
        recommended = runtime_repair_plan.get("next_action") if isinstance(runtime_repair_plan, dict) else None
        w3_status["next_action"] = (
            recommended if isinstance(recommended, str) and recommended.strip()
            else (
                "provision the W3 ColabFold/JAX runtime and rerun the no-submit Cayuga runtime probe "
                "before generating execution inputs"
            )
        )
    return w3_status


def _w3_runtime_provision_packet_failures(runtime_provision_packet: Dict[str, Any],
                                          w3_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if runtime_provision_packet.get("status") != _W3_RUNTIME_PROVISION_PACKET_READY_STATUS:
        failures.append({
            "kind": "w3_runtime_provision_packet_status_invalid",
            "expected": _W3_RUNTIME_PROVISION_PACKET_READY_STATUS,
            "actual": runtime_provision_packet.get("status"),
        })
    if runtime_provision_packet.get("audit_ok") is not True:
        failures.append({
            "kind": "w3_runtime_provision_packet_audit_not_ok",
            "expected": True,
            "actual": runtime_provision_packet.get("audit_ok"),
        })
    for field in ("no_submit", "no_api_spend", "no_gpu_spend"):
        if runtime_provision_packet.get(field) is not True:
            failures.append({
                "kind": f"w3_runtime_provision_packet_{field}_not_true",
                "expected": True,
                "actual": runtime_provision_packet.get(field),
            })
    for field in ("network_fetch_emitted", "install_executed", "provision_validation_executed",
                  "prediction_executed", "runtime_ready", "execution_ready",
                  "execution_inputs_emitted", "command_wrapper_emitted",
                  "approval_token_emitted", "can_claim_independent_predictor_robustness_now"):
        if runtime_provision_packet.get(field) is not False:
            failures.append({
                "kind": f"w3_runtime_provision_packet_{field}_drift",
                "expected": False,
                "actual": runtime_provision_packet.get(field),
            })
    if w3_status.get("w3_runtime_repair_plan_ready") is not True:
        failures.append({
            "kind": "w3_runtime_provision_packet_repair_plan_not_ready",
            "message": "runtime provision packet requires the W3 runtime repair plan to be consumed and ready",
        })
    repair = (
        w3_status.get("w3_runtime_repair_plan")
        if isinstance(w3_status.get("w3_runtime_repair_plan"), dict)
        else {}
    )
    expected_repair_path = _resolve_existing_artifact_path(repair.get("path"))
    observed_repair_path = _resolve_existing_artifact_path(
        runtime_provision_packet.get("source_runtime_repair_plan"),
    )
    expected_sha = None
    if expected_repair_path and os.path.exists(expected_repair_path):
        expected_sha = _sha256_file(expected_repair_path)
        if runtime_provision_packet.get("source_runtime_repair_plan_sha256") != expected_sha:
            failures.append({
                "kind": "w3_runtime_provision_packet_repair_sha_mismatch",
                "expected": expected_sha,
                "actual": runtime_provision_packet.get("source_runtime_repair_plan_sha256"),
            })
    if (
        expected_repair_path
        and observed_repair_path != expected_repair_path
        and runtime_provision_packet.get("source_runtime_repair_plan_sha256") != expected_sha
    ):
        failures.append({
            "kind": "w3_runtime_provision_packet_repair_path_mismatch",
            "expected": expected_repair_path,
            "actual": observed_repair_path,
        })
    if runtime_provision_packet.get("approval_env_var") != "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION":
        failures.append({
            "kind": "w3_runtime_provision_packet_approval_env_mismatch",
            "expected": "BIO_SFM_APPROVE_W3_RUNTIME_PROVISION",
            "actual": runtime_provision_packet.get("approval_env_var"),
        })
    if runtime_provision_packet.get("approval_env_value") != "approve-w3-runtime-provision":
        failures.append({
            "kind": "w3_runtime_provision_packet_approval_token_mismatch",
            "expected": "approve-w3-runtime-provision",
            "actual": runtime_provision_packet.get("approval_env_value"),
        })
    static_audit = runtime_provision_packet.get("static_script_audit")
    if not isinstance(static_audit, dict) or static_audit.get("ok") is not True:
        failures.append({
            "kind": "w3_runtime_provision_packet_static_audit_not_ok",
            "expected": True,
            "actual": static_audit,
        })
    return failures


def _attach_w3_runtime_provision_packet(
    w3_status: Dict[str, Any],
    runtime_provision_packet: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if runtime_provision_packet is None:
        return w3_status
    if _is_missing_artifact(runtime_provision_packet):
        failures = [{
            "kind": "w3_runtime_provision_packet_missing",
            "message": runtime_provision_packet.get("message", "W3 runtime provision packet artifact is missing"),
            "path": runtime_provision_packet.get("_path"),
        }]
    else:
        failures = _w3_runtime_provision_packet_failures(runtime_provision_packet, w3_status)
    ready = not failures
    w3_status["w3_runtime_provision_packet"] = {
        "path": runtime_provision_packet.get("_path") if isinstance(runtime_provision_packet, dict) else None,
        "status": runtime_provision_packet.get("status") if isinstance(runtime_provision_packet, dict) else None,
        "ready": ready,
        "audit_ok": runtime_provision_packet.get("audit_ok") if isinstance(runtime_provision_packet, dict) else None,
        "script": runtime_provision_packet.get("script") if isinstance(runtime_provision_packet, dict) else None,
        "receipt": runtime_provision_packet.get("receipt") if isinstance(runtime_provision_packet, dict) else None,
        "approval_env_var": runtime_provision_packet.get("approval_env_var")
        if isinstance(runtime_provision_packet, dict) else None,
        "approval_env_value": runtime_provision_packet.get("approval_env_value")
        if isinstance(runtime_provision_packet, dict) else None,
        "install_executed": False,
        "runtime_ready": False,
        "execution_ready": False,
        "execution_inputs_emitted": False,
        "command_wrapper_emitted": False,
        "can_claim_independent_predictor_robustness_now": False,
        "failures": failures,
    }
    w3_status["w3_runtime_provision_packet_ready"] = ready
    w3_status["w3_selected_predictor_runtime_ready"] = False
    w3_status["w3_selected_predictor_execution_ready"] = False
    w3_status["can_claim_independent_predictor_robustness_now"] = False
    if failures:
        w3_status["w3_runtime_provision_packet_failures"] = failures
        w3_status["next_action"] = (
            "repair W3 runtime provision-packet artifact before runtime validation or execution-input work"
        )
    else:
        recommended = runtime_provision_packet.get("next_action") if isinstance(runtime_provision_packet, dict) else None
        w3_status["next_action"] = (
            recommended if isinstance(recommended, str) and recommended.strip()
            else (
                "provide W3_COLABFOLD_BIN or W3_COLABFOLD_SIF and run the guarded runtime validation "
                "only after explicit approval"
            )
        )
    return w3_status


def _w3_status(predictor_contract: Optional[Dict[str, Any]],
               cross_predictor: Optional[Dict[str, Any]],
               decision_protocol: Optional[Dict[str, Any]] = None,
               next_protocol: Optional[Dict[str, Any]] = None,
               challenge_manifest: Optional[Dict[str, Any]] = None,
               third_predictor_contract: Optional[Dict[str, Any]] = None,
               predictor_selection_card: Optional[Dict[str, Any]] = None,
               runtime_probe_plan: Optional[Dict[str, Any]] = None,
               runtime_probe_report: Optional[Dict[str, Any]] = None,
               runtime_repair_plan: Optional[Dict[str, Any]] = None,
               runtime_provision_packet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if decision_protocol is not None:
        return _attach_w3_runtime_provision_packet(
            _attach_w3_runtime_repair_plan(
                _attach_w3_runtime_probe_report(
                    _attach_w3_runtime_probe_plan(
                        _attach_w3_predictor_selection_card(
                            _attach_w3_third_predictor_contract(
                                _attach_w3_challenge_manifest(
                                    _attach_w3_next_protocol(
                                        _w3_decision_protocol_status(decision_protocol, cross_predictor),
                                        next_protocol,
                                    ),
                                    challenge_manifest,
                                ),
                                third_predictor_contract,
                            ),
                            predictor_selection_card,
                        ),
                        runtime_probe_plan,
                    ),
                    runtime_probe_report,
                ),
                runtime_repair_plan,
            ),
            runtime_provision_packet,
        )
    if _is_missing_artifact(cross_predictor):
        cross_predictor = None
    if cross_predictor is None and predictor_contract is not None:
        return _w3_contract_status(predictor_contract)
    if cross_predictor is None:
        return {
            "workstream": "W3_independent_predictor",
            "status": "missing",
            "complete": False,
            "message": "No cross-predictor report provided.",
            "next_action": "validate a second-predictor contract, then generate matched records from an independent complex predictor",
        }
    audit_failures = _w3_cross_predictor_audit_failures(cross_predictor)
    base_ready = cross_predictor.get("ok") and cross_predictor.get("status") == "cross_predictor_ready"
    if base_ready and not audit_failures:
        status = "cross_predictor_ready"
        complete = True
        next_action = "single-model caveat can close for the checked matched set"
    else:
        status = "single_model_caveat_open"
        complete = False
        next_action = "fix overlap/agreement/provenance, regenerate strict W3 report, or add independent predictor records"
    return {
        "workstream": "W3_independent_predictor",
        "status": status,
        "complete": complete,
        "predictors": cross_predictor.get("predictors", []),
        "records_by_predictor": cross_predictor.get("records_by_predictor", {}),
        "require_disjoint_record_files": cross_predictor.get("require_disjoint_record_files"),
        "record_files": cross_predictor.get("record_files", []),
        "audit_failures": audit_failures,
        "failures": (
            list(cross_predictor.get("failures", []))
            if isinstance(cross_predictor.get("failures", []), list)
            else []
        ) + audit_failures,
        "next_action": next_action,
        "evidence": cross_predictor.get("_path"),
    }


def _default_campaign_path(batch_summary: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(batch_summary, dict):
        return None
    path = batch_summary.get("_path")
    if not isinstance(path, str):
        return None
    return os.path.join(os.path.dirname(path), "campaign.jsonl")


def _jsonl_has_record(path: Optional[str]) -> bool:
    return _jsonl_record_count(path) > 0


def _jsonl_record_count(path: Optional[str]) -> int:
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0
    count = 0
    with open(path) as fh:
        for line in fh:
            if line.strip():
                json.loads(line)
                count += 1
    return count


_CAMPAIGN_ALLOWED_ACTIONS = {"trust_sfm", "verify_assay", "default_baseline", "defer"}
_CAMPAIGN_BEST_ALLOWED_ACTIONS = {"trust_sfm", "default_baseline"}
_CAMPAIGN_ACTION_RATE_FIELDS = {
    "trust_sfm": "trust_rate",
    "verify_assay": "verify_rate",
    "default_baseline": "default_rate",
    "defer": "defer_rate",
}
_CAMPAIGN_ACTION_RATE_TOLERANCE = 1e-9
_CAMPAIGN_BEST_QUALITY_TOLERANCE = 1e-9


def _campaign_jsonl_audit(path: Optional[str]) -> Dict[str, Any]:
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return {
            "record_count": 0,
            "candidate_ids": [],
            "missing_candidate_id_lines": [],
            "duplicate_candidate_ids": [],
            "missing_action_lines": [],
            "invalid_action_records": [],
            "action_counts": {action: 0 for action in sorted(_CAMPAIGN_ALLOWED_ACTIONS)},
            "candidate_actions": {},
            "candidate_rounds": {},
            "candidate_hidden_qualities": {},
        }
    candidate_ids: List[str] = []
    missing_candidate_id_lines: List[int] = []
    missing_action_lines: List[int] = []
    invalid_action_records: List[Dict[str, Any]] = []
    action_counts = {action: 0 for action in sorted(_CAMPAIGN_ALLOWED_ACTIONS)}
    candidate_actions: Dict[str, Any] = {}
    candidate_rounds: Dict[str, Any] = {}
    candidate_hidden_qualities: Dict[str, Any] = {}
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: campaign row is not a JSON object")
            candidate_id = record.get("candidate_id")
            if isinstance(candidate_id, str) and candidate_id.strip():
                clean_candidate_id = candidate_id.strip()
                candidate_ids.append(clean_candidate_id)
                if "round" in record:
                    candidate_rounds[clean_candidate_id] = record.get("round")
                hidden_truth = record.get("hidden_truth")
                if isinstance(hidden_truth, dict) and "quality" in hidden_truth:
                    candidate_hidden_qualities[clean_candidate_id] = hidden_truth.get("quality")
            else:
                missing_candidate_id_lines.append(line_no)
            action = record.get("action")
            if not isinstance(action, str) or not action.strip():
                missing_action_lines.append(line_no)
            elif action.strip() not in _CAMPAIGN_ALLOWED_ACTIONS:
                invalid_action_records.append({"line": line_no, "action": action.strip()})
            else:
                clean_action = action.strip()
                action_counts[clean_action] += 1
                if isinstance(candidate_id, str) and candidate_id.strip():
                    candidate_actions[candidate_id.strip()] = clean_action
    seen = set()
    duplicates = []
    for candidate_id in candidate_ids:
        if candidate_id in seen and candidate_id not in duplicates:
            duplicates.append(candidate_id)
        seen.add(candidate_id)
    return {
        "record_count": len(candidate_ids) + len(missing_candidate_id_lines),
        "candidate_ids": candidate_ids,
        "missing_candidate_id_lines": missing_candidate_id_lines,
        "duplicate_candidate_ids": sorted(duplicates),
        "missing_action_lines": missing_action_lines,
        "invalid_action_records": invalid_action_records,
        "action_counts": action_counts,
        "candidate_actions": candidate_actions,
        "candidate_rounds": candidate_rounds,
        "candidate_hidden_qualities": candidate_hidden_qualities,
    }


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _campaign_action_rate_mismatches(campaign_audit: Dict[str, Any],
                                     aggregate: Any,
                                     n_routed: Any) -> List[Dict[str, Any]]:
    if not isinstance(aggregate, dict) or not isinstance(n_routed, int) or n_routed <= 0:
        return []
    action_counts = campaign_audit.get("action_counts")
    if not isinstance(action_counts, dict):
        return []
    mismatches: List[Dict[str, Any]] = []
    for action, rate_field in sorted(_CAMPAIGN_ACTION_RATE_FIELDS.items()):
        if rate_field not in aggregate:
            continue
        expected_rate = _finite_number(aggregate.get(rate_field))
        if expected_rate is None:
            continue
        actual_count = action_counts.get(action, 0)
        try:
            actual_rate = float(actual_count) / float(n_routed)
        except ZeroDivisionError:
            continue
        if abs(actual_rate - expected_rate) > _CAMPAIGN_ACTION_RATE_TOLERANCE:
            mismatches.append({
                "action": action,
                "rate_field": rate_field,
                "expected_rate": expected_rate,
                "actual_rate": actual_rate,
                "count": actual_count,
                "n": n_routed,
            })
    return mismatches


def _summary_per_round_count_mismatches(batch_summary: Dict[str, Any],
                                        n_routed: int) -> List[Dict[str, Any]]:
    if "per_round" not in batch_summary:
        return []
    per_round = batch_summary.get("per_round")
    if not isinstance(per_round, list) or not per_round:
        return [{
            "field": "per_round",
            "reason": "missing_or_invalid",
        }]
    total = 0
    mismatches: List[Dict[str, Any]] = []
    for index, row in enumerate(per_round):
        if not isinstance(row, dict):
            mismatches.append({
                "field": "per_round",
                "index": index,
                "reason": "row_not_object",
            })
            continue
        count = row.get("n")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            mismatches.append({
                "field": "per_round.n",
                "index": index,
                "reason": "missing_or_invalid",
                "actual": count,
            })
            continue
        total += count
    if mismatches:
        return mismatches
    if total != n_routed:
        return [{
            "field": "per_round.n_sum",
            "expected": n_routed,
            "actual": total,
        }]
    return []


def _campaign_assay_count_mismatches(campaign_audit: Dict[str, Any],
                                     batch_summary: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(batch_summary, dict) or "assays_used" not in batch_summary:
        return []
    expected = batch_summary.get("assays_used")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        return [{
            "field": "assays_used",
            "reason": "missing_or_invalid",
            "actual": expected,
        }]
    action_counts = campaign_audit.get("action_counts")
    if not isinstance(action_counts, dict):
        return []
    actual = action_counts.get("verify_assay", 0)
    if actual != expected:
        return [{
            "field": "assays_used",
            "action": "verify_assay",
            "expected": expected,
            "actual": actual,
        }]
    return []


def _campaign_best_mismatches(campaign_audit: Dict[str, Any],
                              batch_summary: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(batch_summary, dict) or "best" not in batch_summary:
        return []
    best = batch_summary.get("best")
    if best is None:
        return []
    if not isinstance(best, dict):
        return [{
            "field": "best",
            "reason": "missing_or_invalid",
            "actual": best,
        }]
    candidate_id = best.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        return [{
            "field": "best.candidate_id",
            "reason": "missing_or_invalid",
            "actual": candidate_id,
        }]
    clean_candidate_id = candidate_id.strip()
    candidate_ids = set(campaign_audit.get("candidate_ids") or [])
    if clean_candidate_id not in candidate_ids:
        return [{
            "field": "best.candidate_id",
            "reason": "not_in_campaign",
            "candidate_id": clean_candidate_id,
        }]
    mismatches: List[Dict[str, Any]] = []
    candidate_actions = campaign_audit.get("candidate_actions")
    if isinstance(candidate_actions, dict) and clean_candidate_id in candidate_actions:
        action = candidate_actions.get(clean_candidate_id)
        if action not in _CAMPAIGN_BEST_ALLOWED_ACTIONS:
            mismatches.append({
                "field": "best.action",
                "candidate_id": clean_candidate_id,
                "actual": action,
                "allowed": sorted(_CAMPAIGN_BEST_ALLOWED_ACTIONS),
            })
    candidate_rounds = campaign_audit.get("candidate_rounds")
    if isinstance(candidate_rounds, dict) and clean_candidate_id in candidate_rounds and "round" in best:
        expected_round = candidate_rounds.get(clean_candidate_id)
        actual_round = best.get("round")
        if actual_round != expected_round:
            mismatches.append({
                "field": "best.round",
                "candidate_id": clean_candidate_id,
                "expected": expected_round,
                "actual": actual_round,
            })
    candidate_hidden_qualities = campaign_audit.get("candidate_hidden_qualities")
    if (
        isinstance(candidate_hidden_qualities, dict)
        and clean_candidate_id in candidate_hidden_qualities
        and "realized_quality" in best
    ):
        expected_quality = _finite_number(candidate_hidden_qualities.get(clean_candidate_id))
        actual_quality = _finite_number(best.get("realized_quality"))
        if expected_quality is None or actual_quality is None:
            mismatches.append({
                "field": "best.realized_quality",
                "candidate_id": clean_candidate_id,
                "reason": "missing_or_invalid",
                "expected": candidate_hidden_qualities.get(clean_candidate_id),
                "actual": best.get("realized_quality"),
            })
        elif abs(actual_quality - expected_quality) > _CAMPAIGN_BEST_QUALITY_TOLERANCE:
            mismatches.append({
                "field": "best.realized_quality",
                "candidate_id": clean_candidate_id,
                "expected": expected_quality,
                "actual": actual_quality,
            })
    if isinstance(candidate_actions, dict) and isinstance(candidate_hidden_qualities, dict):
        best_quality = _finite_number(candidate_hidden_qualities.get(clean_candidate_id))
        if best_quality is not None:
            better: Optional[Dict[str, Any]] = None
            for other_candidate_id, action in candidate_actions.items():
                if other_candidate_id == clean_candidate_id or action not in _CAMPAIGN_BEST_ALLOWED_ACTIONS:
                    continue
                other_quality = _finite_number(candidate_hidden_qualities.get(other_candidate_id))
                if other_quality is None or other_quality <= best_quality + _CAMPAIGN_BEST_QUALITY_TOLERANCE:
                    continue
                if better is None or other_quality > better["quality"]:
                    better = {
                        "candidate_id": other_candidate_id,
                        "action": action,
                        "quality": other_quality,
                    }
            if better is not None:
                mismatches.append({
                    "field": "best.max_realized_quality",
                    "candidate_id": clean_candidate_id,
                    "actual_quality": best_quality,
                    "better_candidate_id": better["candidate_id"],
                    "better_action": better["action"],
                    "better_quality": better["quality"],
                })
    return mismatches


def _project_pending_input_prep_paths(workstreams) -> list:
    by_path = {}
    for workstream in workstreams:
        workstream_id = workstream.get("workstream")
        if workstream_id not in {"W1_M6c_scale_up", "W2_multi_target_panel"}:
            continue
        pending = workstream.get("pending_artifacts")
        if not isinstance(pending, list):
            continue
        for artifact in pending:
            if not isinstance(artifact, dict):
                continue
            path = artifact.get("declared_path") or artifact.get("path")
            if not path:
                continue
            entry = by_path.setdefault(str(path), {
                "path": str(path),
                "absolute_path": artifact.get("path") if artifact.get("path") != path else None,
                "target_ids": set(),
                "fields": set(),
                "errors": set(),
                "workstreams": set(),
            })
            if artifact.get("path") and artifact.get("path") != path and not entry.get("absolute_path"):
                entry["absolute_path"] = artifact.get("path")
            if artifact.get("target_id") is not None:
                entry["target_ids"].add(str(artifact.get("target_id")))
            if artifact.get("field") is not None:
                entry["fields"].add(str(artifact.get("field")))
            if artifact.get("error") or artifact.get("kind"):
                entry["errors"].add(str(artifact.get("error") or artifact.get("kind")))
            if workstream_id:
                entry["workstreams"].add(str(workstream_id))
    out = []
    for entry in by_path.values():
        out.append({
            "path": entry["path"],
            "absolute_path": entry.get("absolute_path"),
            "target_ids": sorted(entry["target_ids"]),
            "fields": sorted(entry["fields"]),
            "errors": sorted(entry["errors"]),
            "workstreams": sorted(entry["workstreams"]),
        })
    return out


def _add_external_artifact(by_path: Dict[str, Dict[str, Any]], *, path: Any,
                           absolute_path: Optional[Any] = None,
                           workstream: Optional[str] = None,
                           category: Optional[str] = None,
                           field: Optional[Any] = None,
                           artifact: Optional[Any] = None,
                           target_id: Optional[Any] = None,
                           status: Optional[Any] = None,
                           error: Optional[Any] = None,
                           sync_back_plan: Optional[str] = None) -> None:
    if not path:
        return
    path_s = str(path)
    entry = by_path.setdefault(path_s, {
        "path": path_s,
        "absolute_path": None,
        "workstreams": set(),
        "categories": set(),
        "fields": set(),
        "artifacts": set(),
        "target_ids": set(),
        "statuses": set(),
        "errors": set(),
        "sync_back_plans": set(),
    })
    if absolute_path and str(absolute_path) != path_s and not entry["absolute_path"]:
        entry["absolute_path"] = str(absolute_path)
    if workstream:
        entry["workstreams"].add(str(workstream))
    if category:
        entry["categories"].add(str(category))
    if field is not None:
        entry["fields"].add(str(field))
    if artifact is not None:
        entry["artifacts"].add(str(artifact))
    if target_id is not None:
        entry["target_ids"].add(str(target_id))
    if status is not None:
        entry["statuses"].add(str(status))
    if error is not None:
        entry["errors"].add(str(error))
    if sync_back_plan:
        entry["sync_back_plans"].add(str(sync_back_plan))


def _external_path_from_record_entry(record: Dict[str, Any]) -> tuple:
    path = record.get("path") or record.get("absolute_path")
    if not path:
        return None, None
    path_s = str(path)
    if os.path.isabs(path_s):
        cwd = os.getcwd()
        try:
            rel = os.path.relpath(path_s, cwd)
        except ValueError:
            rel = path_s
        if rel and not rel.startswith(".."):
            return rel, path_s
    return path_s, record.get("absolute_path")


def _completion_record_is_pending(record: Dict[str, Any]) -> bool:
    if record.get("exists") is True and record.get("nonempty") is True and record.get("jsonl_ok") is True:
        return False
    return bool(record.get("error") or record.get("status") or record.get("path"))


def _project_pending_external_artifacts(workstreams) -> list:
    by_path: Dict[str, Dict[str, Any]] = {}
    for workstream in workstreams:
        workstream_id = workstream.get("workstream")
        sync_back_plan = workstream.get("sync_back_plan")
        if workstream_id in {"W1_M6c_scale_up", "W2_multi_target_panel"}:
            for artifact in workstream.get("pending_artifacts") or []:
                if not isinstance(artifact, dict):
                    continue
                declared = artifact.get("declared_path")
                path = declared or artifact.get("path")
                absolute_path = artifact.get("path") if declared and artifact.get("path") != declared else None
                _add_external_artifact(
                    by_path,
                    path=path,
                    absolute_path=absolute_path,
                    workstream=workstream_id,
                    category="input_prep",
                    field=artifact.get("field"),
                    target_id=artifact.get("target_id"),
                    status=artifact.get("status"),
                    error=artifact.get("error") or artifact.get("kind"),
                    sync_back_plan=sync_back_plan,
                )
            if workstream.get("status") == "scale_completion_blocked":
                for record in workstream.get("records") or []:
                    if not isinstance(record, dict) or not _completion_record_is_pending(record):
                        continue
                    path, absolute_path = _external_path_from_record_entry(record)
                    _add_external_artifact(
                        by_path,
                        path=path,
                        absolute_path=absolute_path,
                        workstream=workstream_id,
                        category="scale_records",
                        artifact="records",
                        target_id=workstream.get("target_id") or "1BRS_AD",
                        status=record.get("status") or record.get("error"),
                        error=record.get("error"),
                        sync_back_plan=sync_back_plan,
                    )
            panel_records = []
            if workstream.get("status") == "panel_completion_blocked":
                panel_records = workstream.get("records") or []
            elif workstream.get("superseded_panel_completion_status") in {"blocked", "panel_completion_blocked"}:
                panel_records = workstream.get("superseded_panel_completion_records") or []
            if panel_records:
                for record in panel_records:
                    if not isinstance(record, dict) or not _completion_record_is_pending(record):
                        continue
                    path, absolute_path = _external_path_from_record_entry(record)
                    _add_external_artifact(
                        by_path,
                        path=path,
                        absolute_path=absolute_path,
                        workstream=workstream_id,
                        category="panel_records",
                        artifact="records",
                        target_id=record.get("target_id"),
                        status=record.get("status") or record.get("error"),
                        error=record.get("error"),
                        sync_back_plan=sync_back_plan,
                    )
        elif workstream_id == "W3_independent_predictor":
            for artifact in workstream.get("pending_secondary_records") or []:
                if not isinstance(artifact, dict):
                    continue
                _add_external_artifact(
                    by_path,
                    path=artifact.get("path") or artifact.get("absolute_path"),
                    absolute_path=artifact.get("absolute_path"),
                    workstream=workstream_id,
                    category="second_predictor",
                    field="secondary_records",
                    artifact="records",
                    status=artifact.get("status") or artifact.get("kind"),
                    error=artifact.get("error") or artifact.get("kind") or artifact.get("status"),
                    sync_back_plan=sync_back_plan,
                )
        elif workstream_id == "W4_closed_loop_DBTL":
            for artifact in workstream.get("pending_artifacts") or []:
                if not isinstance(artifact, dict):
                    continue
                _add_external_artifact(
                    by_path,
                    path=artifact.get("path") or artifact.get("absolute_path"),
                    absolute_path=artifact.get("absolute_path"),
                    workstream=workstream_id,
                    category="closed_loop_batch",
                    field=artifact.get("field"),
                    artifact=artifact.get("artifact"),
                    status=artifact.get("status") or artifact.get("kind"),
                    error=artifact.get("error") or artifact.get("kind"),
                    sync_back_plan=sync_back_plan,
                )
    out = []
    for entry in by_path.values():
        sync_back_plans = sorted(entry["sync_back_plans"])
        item = {
            "path": entry["path"],
            "absolute_path": entry.get("absolute_path"),
            "workstreams": sorted(entry["workstreams"]),
            "categories": sorted(entry["categories"]),
            "fields": sorted(entry["fields"]),
            "artifacts": sorted(entry["artifacts"]),
            "target_ids": sorted(entry["target_ids"]),
            "statuses": sorted(entry["statuses"]),
            "errors": sorted(entry["errors"]),
            "sync_back_plans": sync_back_plans,
        }
        if len(sync_back_plans) == 1:
            item["sync_back_plan"] = sync_back_plans[0]
        out.append(item)
    return out


def _list_values(entry: Dict[str, Any], key: str) -> list:
    values = entry.get(key)
    if not isinstance(values, list):
        return []
    return sorted({str(value) for value in values if str(value)})


def _bump(counter: Dict[str, int], values: list) -> None:
    for value in values:
        counter[value] = counter.get(value, 0) + 1


def _sorted_counter(counter: Dict[str, int]) -> Dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def summarize_pending_external_artifacts(entries: list) -> Dict[str, Any]:
    """Group the de-duplicated external checklist by roadmap provenance."""
    by_workstream: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    by_target_id: Dict[str, int] = {}
    by_artifact: Dict[str, int] = {}
    by_field: Dict[str, int] = {}
    workstream_items: Dict[str, Dict[str, Any]] = {}

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        workstreams = _list_values(entry, "workstreams") or ["unknown"]
        categories = _list_values(entry, "categories")
        target_ids = _list_values(entry, "target_ids")
        artifacts = _list_values(entry, "artifacts")
        fields = _list_values(entry, "fields")
        sync_back_plans = _list_values(entry, "sync_back_plans")

        _bump(by_workstream, workstreams)
        _bump(by_category, categories)
        _bump(by_target_id, target_ids)
        _bump(by_artifact, artifacts)
        _bump(by_field, fields)

        for workstream in workstreams:
            item = workstream_items.setdefault(workstream, {
                "workstream": workstream,
                "n_paths": 0,
                "paths": [],
                "categories": set(),
                "target_ids": set(),
                "artifacts": set(),
                "fields": set(),
                "sync_back_plans": set(),
            })
            item["n_paths"] += 1
            if path:
                item["paths"].append(str(path))
            item["categories"].update(categories)
            item["target_ids"].update(target_ids)
            item["artifacts"].update(artifacts)
            item["fields"].update(fields)
            item["sync_back_plans"].update(sync_back_plans)

    workstreams = []
    for key in sorted(workstream_items):
        item = workstream_items[key]
        workstreams.append({
            "workstream": key,
            "n_paths": item["n_paths"],
            "paths": sorted(item["paths"]),
            "categories": sorted(item["categories"]),
            "target_ids": sorted(item["target_ids"]),
            "artifacts": sorted(item["artifacts"]),
            "fields": sorted(item["fields"]),
            "sync_back_plans": sorted(item["sync_back_plans"]),
        })

    return {
        "n_paths": sum(1 for entry in entries or [] if isinstance(entry, dict)),
        "by_workstream": _sorted_counter(by_workstream),
        "by_category": _sorted_counter(by_category),
        "by_target_id": _sorted_counter(by_target_id),
        "by_artifact": _sorted_counter(by_artifact),
        "by_field": _sorted_counter(by_field),
        "workstreams": workstreams,
    }


def render_pending_input_prep_paths(rep: Dict[str, Any], *, absolute: bool = False) -> str:
    lines = []
    for entry in rep.get("pending_input_prep_paths") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("absolute_path") if absolute else entry.get("path")
        if not path:
            path = entry.get("path") or entry.get("absolute_path")
        if path:
            lines.append(str(path))
    return "\n".join(lines) + ("\n" if lines else "")


def render_pending_external_paths(rep: Dict[str, Any], *, absolute: bool = False) -> str:
    lines = []
    for entry in rep.get("pending_external_artifacts") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("absolute_path") if absolute else entry.get("path")
        if not path:
            path = entry.get("path") or entry.get("absolute_path")
        if path:
            lines.append(str(path))
    return "\n".join(lines) + ("\n" if lines else "")


def _local_artifact_path(entry: Dict[str, Any]) -> Optional[str]:
    path = entry.get("absolute_path") or entry.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    return path


def _audit_local_artifacts(entries: list) -> Dict[str, Any]:
    paths = []
    n_present = 0
    n_nonempty = 0
    n_empty = 0
    n_missing = 0
    n_unreadable = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        local_path = _local_artifact_path(entry)
        if not local_path:
            continue
        item = {
            "path": entry.get("path"),
            "absolute_path": entry.get("absolute_path"),
            "local_path": local_path,
            "workstreams": entry.get("workstreams", []),
            "categories": entry.get("categories", []),
            "fields": entry.get("fields", []),
            "artifacts": entry.get("artifacts", []),
            "target_ids": entry.get("target_ids", []),
        }
        try:
            exists = os.path.exists(local_path)
            is_file = os.path.isfile(local_path)
            size = os.path.getsize(local_path) if exists and is_file else None
            readable = os.access(local_path, os.R_OK) if exists else False
        except OSError as exc:
            exists = False
            is_file = False
            size = None
            readable = False
            item["error"] = str(exc)
        nonempty = bool(exists and is_file and readable and size and size > 0)
        empty = bool(exists and is_file and readable and size == 0)
        item.update({
            "exists": exists,
            "is_file": is_file,
            "readable": readable,
            "size_bytes": size,
            "nonempty": nonempty,
            "empty": empty,
        })
        if exists and is_file:
            n_present += 1
        else:
            n_missing += 1
        if nonempty:
            n_nonempty += 1
        if empty:
            n_empty += 1
        if exists and not readable:
            n_unreadable += 1
        paths.append(item)
    n_paths = len(paths)
    all_present_nonempty = bool(n_paths and n_nonempty == n_paths)
    status = (
        "all_present_nonempty" if all_present_nonempty
        else "partially_present" if n_present
        else "all_missing" if n_paths
        else "none"
    )
    next_action = (
        "run post-sync replay or workstream rerun commands before refreshing project status"
        if all_present_nonempty else
        "sync missing or empty artifacts before replaying local checks"
        if n_paths else
        "no pending artifacts to audit"
    )
    return {
        "status": status,
        "n_paths": n_paths,
        "n_present": n_present,
        "n_nonempty": n_nonempty,
        "n_empty": n_empty,
        "n_missing": n_missing,
        "n_unreadable": n_unreadable,
        "all_present_nonempty": all_present_nonempty,
        "paths": paths,
        "next_action": next_action,
    }


def attach_pending_artifact_local_audit(rep: Dict[str, Any]) -> Dict[str, Any]:
    rep["pending_artifact_local_audit"] = {
        "input_prep": _audit_local_artifacts(rep.get("pending_input_prep_paths") or []),
        "external": _audit_local_artifacts(rep.get("pending_external_artifacts") or []),
    }
    return rep


_GOAL_REQUIREMENTS = (
    (
        "W1_M6c_scale_up",
        "tighten M6c complex gate beyond alpha=0.3 toward target alpha",
        {"certified"},
    ),
    (
        "W2_multi_target_panel",
        "validate the complex signal target-wise across a multi-target panel",
        {"multi_target_certified"},
    ),
    (
        "W3_independent_predictor",
        "validate or quantify the single-predictor caveat with an independent predictor",
        {"cross_predictor_ready", _W3_NEGATIVE_ROBUSTNESS_STATUS},
    ),
    (
        "W4_closed_loop_DBTL",
        "integrate calibrated complex evidence into closed-loop DBTL routing",
        {"closed_loop_round_complete"},
    ),
)


def _evidence_supports_goal_status(requirement_id: str, status: Any, obj: Dict[str, Any]) -> bool:
    if obj.get("_missing_artifact") is True or obj.get("ok") is False:
        return False
    if requirement_id == "W1_M6c_scale_up" and status == "certified":
        return obj.get("decision") == "stop_certified" and not _w1_alpha_decision_audit_failures(obj)
    if requirement_id == "W2_multi_target_panel" and status == "multi_target_certified":
        return (
            obj.get("ok") is True
            and obj.get("panel_status") == "multi_target_certified"
            and not _w2_panel_report_audit_failures(obj)
        )
    if requirement_id == "W3_independent_predictor" and status == "cross_predictor_ready":
        return (
            obj.get("ok") is True
            and obj.get("status") == "cross_predictor_ready"
            and not _w3_cross_predictor_audit_failures(obj)
        )
    if requirement_id == "W3_independent_predictor" and status == _W3_NEGATIVE_ROBUSTNESS_STATUS:
        return not _w3_decision_protocol_failures(obj)
    if requirement_id == "W4_closed_loop_DBTL" and status == "closed_loop_round_complete":
        aggregate = obj.get("aggregate")
        n_routed = aggregate.get("n") if isinstance(aggregate, dict) else None
        return (
            obj.get("status") == "closed_loop_round_complete"
            and obj.get("gate_calibrated") is True
            and isinstance(n_routed, int)
            and n_routed > 0
        )
    return False


def _goal_evidence_audit(evidence: Any, *, requirement_id: str, status: Any,
                         status_complete: bool) -> Dict[str, Any]:
    if isinstance(evidence, str):
        paths = [evidence] if evidence.strip() else []
    elif isinstance(evidence, list):
        paths = [str(path) for path in evidence if isinstance(path, str) and path.strip()]
    else:
        paths = []

    missing = []
    empty = []
    parse_errors = []
    content_objects = []
    for path in paths:
        if not os.path.exists(path):
            missing.append(path)
            continue
        try:
            if os.path.getsize(path) <= 0:
                empty.append(path)
                continue
        except OSError:
            missing.append(path)
            continue
        try:
            with open(path) as fh:
                obj = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append({"path": path, "error": str(exc)})
            continue
        if not isinstance(obj, dict):
            parse_errors.append({"path": path, "error": "evidence JSON must be an object"})
            continue
        content_objects.append(obj)

    file_ok = bool(paths) and not missing and not empty and not parse_errors
    supports_status = (
        file_ok
        and status_complete
        and any(_evidence_supports_goal_status(requirement_id, status, obj) for obj in content_objects)
    )

    evidence_ok = bool(file_ok and (supports_status if status_complete else True))

    return {
        "evidence_paths": paths,
        "evidence_ok": evidence_ok,
        "evidence_file_ok": file_ok,
        "evidence_supports_status": supports_status if status_complete else None,
        "evidence_missing_paths": missing,
        "evidence_empty_paths": empty,
        "evidence_parse_errors": parse_errors,
    }


def _goal_supporting_artifact_audit(requirement_id: str, item: Dict[str, Any],
                                    *, status: Any, status_complete: bool) -> Dict[str, Any]:
    required: List[Dict[str, str]] = []
    if requirement_id == "W4_closed_loop_DBTL" and status == "closed_loop_round_complete":
        required = [
            {"role": "preflight", "path": item.get("preflight"), "kind": "json"},
            {"role": "summary", "path": item.get("summary") or item.get("evidence"), "kind": "json"},
            {"role": "campaign", "path": item.get("campaign"), "kind": "jsonl"},
        ]
    if not status_complete or not required:
        return {
            "supporting_artifact_ok": True,
            "supporting_artifacts": [],
            "supporting_artifact_missing": [],
            "supporting_artifact_empty": [],
            "supporting_artifact_parse_errors": [],
            "supporting_artifact_content_errors": [],
        }

    artifacts = []
    missing = []
    empty = []
    parse_errors = []
    content_errors = []
    expected_campaign_records: Optional[int] = None
    expected_campaign_ids: Optional[List[str]] = None
    expected_campaign_summary: Optional[Dict[str, Any]] = None
    expected_campaign_aggregate: Optional[Dict[str, Any]] = None
    for spec in required:
        role = spec["role"]
        path = spec.get("path")
        kind = spec["kind"]
        artifacts.append({"role": role, "path": path, "kind": kind})
        if not isinstance(path, str) or not path.strip():
            missing.append({"role": role, "path": path, "reason": "missing_field"})
            continue
        if not os.path.exists(path):
            missing.append({"role": role, "path": path, "reason": "missing_file"})
            continue
        try:
            if os.path.getsize(path) <= 0:
                empty.append({"role": role, "path": path})
                continue
        except OSError as exc:
            missing.append({"role": role, "path": path, "reason": str(exc)})
            continue
        if kind == "json":
            try:
                with open(path) as fh:
                    obj = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                parse_errors.append({"role": role, "path": path, "error": str(exc)})
                continue
            if not isinstance(obj, dict):
                parse_errors.append({"role": role, "path": path, "error": "JSON must be an object"})
                continue
            if role == "preflight":
                if obj.get("ok") is not True:
                    content_errors.append({"role": role, "path": path, "field": "ok"})
                if obj.get("strict_complex_records") is not True:
                    content_errors.append({"role": role, "path": path, "field": "strict_complex_records"})
                candidate_ids = obj.get("candidate_ids")
                if isinstance(candidate_ids, list) and all(
                    isinstance(candidate_id, str) and candidate_id.strip()
                    for candidate_id in candidate_ids
                ):
                    expected_campaign_ids = sorted(candidate_id.strip() for candidate_id in candidate_ids)
            if role == "summary":
                expected_campaign_summary = obj
                aggregate = obj.get("aggregate")
                if isinstance(aggregate, dict):
                    expected_campaign_aggregate = aggregate
                n_routed = aggregate.get("n") if isinstance(aggregate, dict) else None
                if obj.get("gate_calibrated") is not True:
                    content_errors.append({"role": role, "path": path, "field": "gate_calibrated"})
                if not isinstance(n_routed, int) or n_routed <= 0:
                    content_errors.append({"role": role, "path": path, "field": "aggregate.n"})
                else:
                    expected_campaign_records = n_routed
                    per_round_mismatches = _summary_per_round_count_mismatches(obj, n_routed)
                    if per_round_mismatches:
                        content_errors.append({
                            "role": role,
                            "path": path,
                            "field": "summary_per_round",
                            "mismatches": per_round_mismatches,
                        })
        elif kind == "jsonl":
            try:
                campaign_audit = _campaign_jsonl_audit(path) if role == "campaign" else None
                record_count = (
                    campaign_audit["record_count"]
                    if isinstance(campaign_audit, dict)
                    else _jsonl_record_count(path)
                )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                parse_errors.append({"role": role, "path": path, "error": str(exc)})
                continue
            if record_count <= 0:
                content_errors.append({"role": role, "path": path, "field": "jsonl_record"})
            if isinstance(campaign_audit, dict):
                if campaign_audit["missing_candidate_id_lines"]:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_candidate_id",
                        "lines": campaign_audit["missing_candidate_id_lines"],
                    })
                if campaign_audit["duplicate_candidate_ids"]:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_candidate_id_unique",
                        "candidate_ids": campaign_audit["duplicate_candidate_ids"],
                    })
                if campaign_audit["missing_action_lines"]:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_action",
                        "lines": campaign_audit["missing_action_lines"],
                    })
                if campaign_audit["invalid_action_records"]:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_action_allowed",
                        "allowed": sorted(_CAMPAIGN_ALLOWED_ACTIONS),
                        "records": campaign_audit["invalid_action_records"],
                    })
                action_mismatches = _campaign_action_rate_mismatches(
                    campaign_audit,
                    expected_campaign_aggregate,
                    expected_campaign_records,
                )
                if action_mismatches:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_action_rates",
                        "mismatches": action_mismatches,
                    })
                assay_mismatches = _campaign_assay_count_mismatches(
                    campaign_audit,
                    expected_campaign_summary,
                )
                if assay_mismatches:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_assays_used",
                        "mismatches": assay_mismatches,
                    })
                best_mismatches = _campaign_best_mismatches(
                    campaign_audit,
                    expected_campaign_summary,
                )
                if best_mismatches:
                    content_errors.append({
                        "role": role,
                        "path": path,
                        "field": "campaign_best",
                        "mismatches": best_mismatches,
                    })
                if expected_campaign_ids is not None:
                    actual_ids = sorted(campaign_audit["candidate_ids"])
                    if actual_ids != expected_campaign_ids:
                        content_errors.append({
                            "role": role,
                            "path": path,
                            "field": "campaign_candidate_ids",
                            "expected": expected_campaign_ids,
                            "actual": actual_ids,
                        })
            if (
                role == "campaign"
                and isinstance(expected_campaign_records, int)
                and record_count != expected_campaign_records
            ):
                content_errors.append({
                    "role": role,
                    "path": path,
                    "field": "campaign_record_count",
                    "expected": expected_campaign_records,
                    "actual": record_count,
                })

    ok = not missing and not empty and not parse_errors and not content_errors
    return {
        "supporting_artifact_ok": ok,
        "supporting_artifacts": artifacts,
        "supporting_artifact_missing": missing,
        "supporting_artifact_empty": empty,
        "supporting_artifact_parse_errors": parse_errors,
        "supporting_artifact_content_errors": content_errors,
    }


def _operator_resume_ladder_action(action: Any,
                                   recommended: Dict[str, Any],
                                   rep: Dict[str, Any]) -> Any:
    """Add the required downstream bridge order to the human resume action."""
    if not isinstance(action, str) or not action.strip():
        return action
    role = recommended.get("role") if isinstance(recommended, dict) else None
    if not role:
        return action
    ladder = rep.get("resume_execution_ladder")
    steps = ladder.get("steps") if isinstance(ladder, dict) else None
    if not isinstance(steps, list):
        return action
    roles = [step.get("role") for step in steps if isinstance(step, dict)]
    if role not in roles:
        return action
    later_roles = roles[roles.index(role) + 1:]
    if "project_status_refresh" not in later_roles:
        return action
    if role == "target_msa_precompute":
        dry_run_command = recommended.get("dry_run_command")
        if (
            isinstance(dry_run_command, str)
            and dry_run_command.strip()
            and dry_run_command not in action
        ):
            action = (
                f"run {dry_run_command} first to validate manifest freshness, planned targets, "
                f"helper/source FASTA guards, and Boltz runtime readiness without touching the receipt; "
                f"if it matches, {action}"
            )
    lower_action = action.lower()
    if "project status" in lower_action or "project-status" in lower_action:
        return action

    continuation = []
    if role != "external_remote_check" and "external_remote_check" in later_roles:
        if "remote-check" not in lower_action and "remote check" not in lower_action:
            continuation.append("run the remote-check bridge")
        continuation.append("after remote-check writes a fresh ok=true report")
    else:
        continuation.append("after it writes a fresh ok=true report")
    continuation.append("rerun project status with its --external-remote-check-report")
    if "external_sync_back" in later_roles:
        continuation.append("run external sync-back only if refreshed status recommends it")
    if "post_sync_replay" in later_roles:
        continuation.append("then run post-sync replay")
    return f"{action}; {', '.join(continuation)}"


def attach_resume_action_hints(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Keep preflight, ladder, and top-level resume text aligned."""
    recommended = rep.get("recommended_next_script")
    if not isinstance(recommended, dict) or not recommended.get("role"):
        return rep
    preflight = rep.get("resume_bridge_preflight")
    if not isinstance(preflight, dict):
        return rep
    if preflight.get("status") not in {
        "ready_to_execute",
        "waiting_on_cayuga_session",
        "waiting_on_env",
    }:
        return rep

    next_action = _operator_resume_ladder_action(
        preflight.get("next_action"),
        recommended,
        rep,
    )
    preflight["next_action"] = next_action
    recommended["resume_next_action"] = next_action

    ladder = rep.get("resume_execution_ladder")
    steps = ladder.get("steps") if isinstance(ladder, dict) else None
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("role") != recommended.get("role"):
                continue
            if step.get("next_action"):
                step["next_action"] = _operator_resume_ladder_action(
                    step.get("next_action"),
                    recommended,
                    rep,
                )
            if step.get("preflight_next_action"):
                step["preflight_next_action"] = _operator_resume_ladder_action(
                    step.get("preflight_next_action"),
                    recommended,
                    rep,
                )
            break
    return rep


def attach_goal_progress_audit(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize the long-lived Codex goal without weakening completion criteria."""
    workstreams = rep.get("workstreams") or {}
    requirements = []
    for key, label, accepted_statuses in _GOAL_REQUIREMENTS:
        item = workstreams.get(key) if isinstance(workstreams, dict) else None
        if isinstance(item, dict):
            status = item.get("status")
            status_complete = status in accepted_statuses
            evidence = item.get("evidence")
            evidence_audit = _goal_evidence_audit(
                evidence,
                requirement_id=key,
                status=status,
                status_complete=status_complete,
            )
            supporting_audit = _goal_supporting_artifact_audit(
                key,
                item,
                status=status,
                status_complete=status_complete,
            )
            complete = (
                bool(item.get("complete"))
                and status_complete
                and evidence_audit["evidence_ok"]
                and supporting_audit["supporting_artifact_ok"]
            )
            requirements.append({
                "id": key,
                "label": label,
                "complete": complete,
                "raw_complete": bool(item.get("complete")),
                "status": status,
                "accepted_statuses": sorted(accepted_statuses),
                "status_complete": status_complete,
                "evidence": evidence,
                **evidence_audit,
                **supporting_audit,
                "next_action": item.get("next_action"),
            })
        else:
            requirements.append({
                "id": key,
                "label": label,
                "complete": False,
                "raw_complete": False,
                "status": "missing_status",
                "accepted_statuses": sorted(accepted_statuses),
                "status_complete": False,
                "evidence": None,
                "evidence_paths": [],
                "evidence_ok": False,
                "evidence_file_ok": False,
                "evidence_supports_status": False,
                "evidence_missing_paths": [],
                "evidence_empty_paths": [],
                "evidence_parse_errors": [],
                "supporting_artifact_ok": False,
                "supporting_artifacts": [],
                "supporting_artifact_missing": [],
                "supporting_artifact_empty": [],
                "supporting_artifact_parse_errors": [],
                "supporting_artifact_content_errors": [],
                "next_action": "regenerate project status with this workstream evidence",
            })

    incomplete = [item for item in requirements if not item["complete"]]
    recommended = rep.get("recommended_next_script") if isinstance(rep.get("recommended_next_script"), dict) else {}
    sync_audit = rep.get("sync_manifest_audit") if isinstance(rep.get("sync_manifest_audit"), dict) else {}
    syntax_audit = (
        rep.get("generated_script_syntax_audit")
        if isinstance(rep.get("generated_script_syntax_audit"), dict)
        else {}
    )
    target_msa_script_audit = (
        rep.get("target_msa_precompute_script_validation_audit")
        if isinstance(rep.get("target_msa_precompute_script_validation_audit"), dict)
        else {}
    )
    posthoc_claims_audit = (
        rep.get("posthoc_science_claims_audit")
        if isinstance(rep.get("posthoc_science_claims_audit"), dict)
        else {}
    )
    posthoc_claims = (
        rep.get("posthoc_science_claims")
        if isinstance(rep.get("posthoc_science_claims"), dict)
        else {}
    )
    preflight = rep.get("resume_bridge_preflight") if isinstance(rep.get("resume_bridge_preflight"), dict) else {}
    remote_report = (
        rep.get("external_remote_check_report")
        if isinstance(rep.get("external_remote_check_report"), dict)
        else {}
    )
    local_audit = (
        rep.get("pending_artifact_local_audit")
        if isinstance(rep.get("pending_artifact_local_audit"), dict)
        else {}
    )
    external_local = local_audit.get("external") if isinstance(local_audit.get("external"), dict) else {}
    input_local = local_audit.get("input_prep") if isinstance(local_audit.get("input_prep"), dict) else {}

    status_mismatches = [
        item for item in requirements
        if item.get("raw_complete") and not item.get("status_complete")
    ]
    evidence_mismatches = [
        item for item in requirements
        if item.get("raw_complete") and item.get("status_complete") and not item.get("evidence_ok")
    ]
    supporting_mismatches = [
        item for item in requirements
        if (
            item.get("raw_complete")
            and item.get("status_complete")
            and item.get("evidence_ok")
            and not item.get("supporting_artifact_ok")
        )
    ]
    local_blockers = []
    if status_mismatches:
        local_blockers.append({
            "kind": "goal_requirement_status_mismatch",
            "requirements": [
                {
                    "id": item["id"],
                    "status": item.get("status"),
                    "accepted_statuses": item.get("accepted_statuses", []),
                }
                for item in status_mismatches
            ],
            "next_action": "regenerate project status or inspect noncanonical terminal workstream statuses",
        })
    if evidence_mismatches:
        local_blockers.append({
            "kind": "goal_requirement_evidence_invalid",
            "requirements": [
                {
                    "id": item["id"],
                    "evidence": item.get("evidence"),
                    "missing_paths": item.get("evidence_missing_paths", []),
                    "empty_paths": item.get("evidence_empty_paths", []),
                    "parse_errors": item.get("evidence_parse_errors", []),
                    "supports_status": item.get("evidence_supports_status"),
                    "status": item.get("status"),
                }
                for item in evidence_mismatches
            ],
            "next_action": "regenerate project status with W1-W4 evidence artifacts that parse and support the claimed terminal status",
        })
    if supporting_mismatches:
        local_blockers.append({
            "kind": "goal_requirement_supporting_artifact_invalid",
            "requirements": [
                {
                    "id": item["id"],
                    "supporting_artifacts": item.get("supporting_artifacts", []),
                    "missing": item.get("supporting_artifact_missing", []),
                    "empty": item.get("supporting_artifact_empty", []),
                    "parse_errors": item.get("supporting_artifact_parse_errors", []),
                    "content_errors": item.get("supporting_artifact_content_errors", []),
                    "status": item.get("status"),
                }
                for item in supporting_mismatches
            ],
            "next_action": "regenerate project status with required W4 preflight, summary, and campaign artifacts",
        })
    if sync_audit and sync_audit.get("ok") is False:
        local_blockers.append({
            "kind": "stale_or_invalid_sync_manifest",
            "n_failures": sync_audit.get("n_failures"),
            "next_action": "regenerate project status or the affected sync script before bridge execution",
        })
    if syntax_audit and syntax_audit.get("n_failures"):
        local_blockers.append({
            "kind": "generated_script_syntax_audit",
            "n_failures": syntax_audit.get("n_failures"),
            "failures": syntax_audit.get("failures"),
            "next_action": syntax_audit.get(
                "next_action",
                "regenerate or repair generated bridge scripts with bash syntax failures",
            ),
        })
    if target_msa_script_audit and target_msa_script_audit.get("ok") is False:
        local_blockers.append({
            "kind": _TARGET_MSA_RECEIPT_VALIDATION_AUDIT_BLOCKER,
            "status": target_msa_script_audit.get("status"),
            "missing_markers": target_msa_script_audit.get("missing_markers"),
            "next_action": target_msa_script_audit.get(
                "next_action",
                "regenerate the target-MSA precompute bridge before Cayuga submission",
            ),
        })
    if posthoc_claims_audit and posthoc_claims_audit.get("ok") is False:
        local_blockers.append({
            "kind": "posthoc_science_claims_audit",
            "status": posthoc_claims_audit.get("status"),
            "report_json": posthoc_claims_audit.get("report_json"),
            "mismatches": posthoc_claims_audit.get("mismatches"),
            "next_action": posthoc_claims_audit.get(
                "next_action",
                "regenerate the posthoc bundle so science claim summaries match source report artifacts",
            ),
        })
    w1 = workstreams.get("W1_M6c_scale_up") if isinstance(workstreams, dict) else None
    missing_claim_sections = _missing_posthoc_science_claim_sections(posthoc_claims)
    if (
        isinstance(w1, dict)
        and w1.get("status") in {"certified", "continue_scale"}
        and missing_claim_sections
    ):
        local_blockers.append({
            "kind": "posthoc_science_claims_missing",
            "status": w1.get("status"),
            "missing_sections": missing_claim_sections,
            "next_action": (
                "regenerate the M6c posthoc bundle/report so supported, not-yet-supported, "
                "planning, and decisive-next claim IDs are carried into project status"
            ),
        })
    for label, audit in (("input_prep", input_local), ("external", external_local)):
        if audit.get("n_paths") and audit.get("all_present_nonempty"):
            local_blockers.append({
                "kind": f"{label}_local_replay_required",
                "n_paths": audit.get("n_paths"),
                "next_action": audit.get("next_action"),
            })
    target_msa_plan = rep.get("target_msa_precompute_plan")
    target_msa_conflicts = (
        target_msa_plan.get("conflicting_duplicate_target_ids")
        if isinstance(target_msa_plan, dict)
        else None
    )
    if isinstance(target_msa_conflicts, list) and target_msa_conflicts:
        local_blockers.append({
            "kind": "target_msa_plan_conflict",
            "n_conflicts": len(target_msa_conflicts),
            "conflicts": target_msa_conflicts,
            "next_action": target_msa_plan.get("next_action"),
        })
    target_msa_receipt = rep.get("target_msa_precompute_receipt")
    if (
        _target_msa_receipt_requires_review(target_msa_receipt)
        and not _target_msa_outputs_satisfied(target_msa_plan)
    ):
        local_blockers.append({
            "kind": _TARGET_MSA_RECEIPT_REVIEW_BLOCKER,
            "status": target_msa_receipt.get("status"),
            "n_records": target_msa_receipt.get("n_records"),
            "bad_records": target_msa_receipt.get("bad_records"),
            "next_action": target_msa_receipt.get("next_action"),
        })

    external_blockers = []
    if preflight.get("missing_env"):
        external_blockers.append({
            "kind": "missing_env",
            "env": preflight.get("missing_env"),
            "next_action": preflight.get("next_action"),
        })
    if preflight.get("status") == "waiting_on_cayuga_session":
        external_blockers.append({
            "kind": "cayuga_session_required",
            "role": recommended.get("role"),
            "command": recommended.get("command"),
            "next_action": preflight.get("next_action"),
        })
    if remote_report.get("status") in {
        "target_msa_receipt_sync_missing",
        "target_msa_receipt_sync_failed",
        "target_msa_receipt_sync_mismatch",
    }:
        external_blockers.append({
            "kind": remote_report.get("status"),
            "status": remote_report.get("status"),
            "target_msa_receipt_sync_status": remote_report.get("target_msa_receipt_sync_status"),
            "target_msa_receipt_sync_synced": remote_report.get("target_msa_receipt_sync_synced"),
            "next_action": remote_report.get("next_action"),
        })
    if remote_report and not remote_report.get("ready_for_external_sync"):
        blocker = {
            "kind": "external_remote_check_report",
            "status": remote_report.get("status"),
            "fresh": remote_report.get("fresh"),
            "ok": remote_report.get("ok"),
            "next_action": remote_report.get("next_action"),
        }
        followups = remote_report.get("remote_missing_followups")
        if isinstance(followups, list) and followups:
            blocker["remote_missing_followups"] = followups
        external_blockers.append(blocker)
    if rep.get("n_pending_external_artifacts"):
        blocker = {
            "kind": "pending_external_artifacts",
            "n_paths": rep.get("n_pending_external_artifacts"),
            "next_action": "run the recommended external bridge before local replay",
        }
        pending_summary = rep.get("pending_external_summary")
        if isinstance(pending_summary, dict):
            blocker["summary"] = pending_summary
        pending_followups = rep.get("pending_external_followups")
        if isinstance(pending_followups, list) and pending_followups:
            blocker["pending_external_followups"] = pending_followups
        external_blockers.append(blocker)

    goal_completion_ready = bool(
        rep.get("complete")
        and not incomplete
        and not local_blockers
        and not external_blockers
    )

    if goal_completion_ready:
        status = "goal_complete"
        next_action = rep.get("next_action")
    elif local_blockers:
        status = "local_replay_or_regeneration_required"
        next_action = local_blockers[0].get("next_action")
    elif remote_report.get("status") == "missing_remote_artifacts":
        status = "remote_jobs_incomplete"
        next_action = remote_report.get("next_action")
    elif remote_report.get("status") == "target_msa_receipt_sync_missing":
        status = "external_remote_check_required"
        next_action = remote_report.get("next_action")
    elif remote_report.get("status") in {"target_msa_receipt_sync_failed", "target_msa_receipt_sync_mismatch"}:
        status = "external_receipt_sync_repair_required"
        next_action = remote_report.get("next_action")
    elif preflight.get("status") == "waiting_on_cayuga_session":
        status = "external_bridge_waiting_on_cayuga_session"
        next_action = preflight.get("next_action")
    elif preflight.get("status") == "waiting_on_env":
        status = "external_bridge_waiting_on_env"
        next_action = preflight.get("next_action")
    elif remote_report.get("status") in {"missing_report", "stale_report"}:
        status = "external_remote_check_required"
        next_action = remote_report.get("next_action")
    elif recommended:
        if recommended.get("ready_to_execute_now") is True:
            status = "recommended_script_ready"
        else:
            status = "recommended_script_not_ready"
        next_action = recommended.get("command")
    else:
        status = "local_artifact_work_required"
        next_action = rep.get("next_action")

    if status != "local_replay_or_regeneration_required":
        next_action = _operator_resume_ladder_action(next_action, recommended, rep)
    rep["operator_next_action"] = next_action
    if recommended.get("dry_run_command"):
        rep["operator_preflight_command"] = recommended.get("dry_run_command")
    if recommended.get("command"):
        rep["operator_next_command"] = recommended.get("command")
    if recommended.get("role"):
        rep["operator_next_role"] = recommended.get("role")
    if recommended.get("ready_to_execute_now") is not None:
        rep["operator_ready_to_execute_now"] = bool(recommended.get("ready_to_execute_now"))

    audit = {
        "status": status,
        "complete": bool(rep.get("complete")),
        "can_mark_goal_complete": goal_completion_ready,
        "remaining_requirements": len(incomplete),
        "requirements": requirements,
        "first_action": {
            "role": recommended.get("role"),
            "command": recommended.get("command"),
            "preflight_command": recommended.get("dry_run_command"),
            "ready_to_execute_now": recommended.get("ready_to_execute_now"),
            "resume_preflight_status": recommended.get("resume_preflight_status"),
        } if recommended else None,
        "local_blockers": local_blockers,
        "external_blockers": external_blockers,
        "execution_ladder": rep.get("resume_execution_ladder"),
        "next_action": next_action,
        "completion_note": (
            "all W1-W4 requirements complete"
            if goal_completion_ready
            else "do not mark the Codex goal complete; W1-W4 requirements are complete but local or external blockers remain"
            if rep.get("complete") and not incomplete
            else "do not mark the Codex goal complete; at least one W1-W4 requirement remains incomplete"
        ),
    }
    rep["goal_progress_audit"] = audit
    rep["goal_progress"] = audit["status"]
    rep["remaining_requirements"] = audit["remaining_requirements"]
    rep["remaining"] = audit["remaining_requirements"]
    rep["can_mark_goal_complete"] = audit["can_mark_goal_complete"]
    rep["goal_completion_note"] = audit["completion_note"]
    return rep


def _manifest_path_for(path: str) -> str:
    root, ext = os.path.splitext(path)
    if ext:
        return f"{root}.manifest.json"
    return f"{path}.manifest.json"


def _path_list_manifest(*, kind: str, text: str, path_file: Optional[str] = None,
                        absolute: bool = False) -> Dict[str, Any]:
    paths = [line for line in text.splitlines() if line.strip()]
    return {
        "kind": kind,
        "path_file": path_file,
        "manifest_file": _manifest_path_for(path_file) if path_file else None,
        "absolute_paths": bool(absolute),
        "n_paths": len(paths),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "paths": paths,
    }


def _paths_digest(paths: list) -> Dict[str, Any]:
    clean = [str(path) for path in paths if str(path).strip()]
    text = "\n".join(clean) + ("\n" if clean else "")
    return {
        "n_paths": len(clean),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "paths": clean,
    }


def _ordered_unique_manifest_paths(*manifests: Optional[Dict[str, Any]]) -> list:
    paths = []
    seen = set()
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        for path in manifest.get("paths") or []:
            value = str(path).strip()
            if not value or value in seen:
                continue
            paths.append(value)
            seen.add(value)
    return paths


def attach_path_manifests(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    input_text = render_pending_input_prep_paths(
        rep,
        absolute=args.absolute_pending_input_prep_paths,
    )
    external_text = render_pending_external_paths(
        rep,
        absolute=args.absolute_pending_external_paths,
    )
    rep["pending_input_prep_manifest"] = _path_list_manifest(
        kind="pending_input_prep_paths",
        text=input_text,
        path_file=args.emit_pending_input_prep_paths,
        absolute=args.absolute_pending_input_prep_paths,
    )
    rep["pending_external_manifest"] = _path_list_manifest(
        kind="pending_external_paths",
        text=external_text,
        path_file=args.emit_pending_external_paths,
        absolute=args.absolute_pending_external_paths,
    )
    return rep


def _safe_relative_sync_paths(rep: Dict[str, Any]) -> tuple:
    paths = []
    skipped = []
    for entry in rep.get("pending_input_prep_paths") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        norm = os.path.normpath(path)
        if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
            skipped.append(path)
            continue
        paths.append((norm, entry))
    return paths, skipped


def _safe_relative_external_sync_paths(rep: Dict[str, Any]) -> tuple:
    paths = []
    skipped = []
    for entry in rep.get("pending_external_artifacts") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        norm = os.path.normpath(path)
        if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
            skipped.append(path)
            continue
        paths.append((norm, entry))
    return paths, skipped


def _safe_relative_path(path: Optional[str]) -> Optional[str]:
    if not isinstance(path, str) or not path.strip():
        return None
    norm = os.path.normpath(path)
    if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
        return None
    return norm


def _remote_check_metadata(paths: list) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    list_keys = (
        "workstreams",
        "categories",
        "fields",
        "artifacts",
        "target_ids",
        "statuses",
        "errors",
        "sync_back_plans",
    )
    scalar_keys = ("sync_back_plan",)
    for rel_path, entry in paths:
        item: Dict[str, Any] = {}
        for key in list_keys:
            values = entry.get(key)
            if isinstance(values, list):
                item[key] = sorted(str(value) for value in values if str(value))
        for key in scalar_keys:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                item[key] = value
        metadata[rel_path] = item
    return metadata


def _shell_path_with_root(var_name: str, rel_path: str) -> str:
    if rel_path in ("", "."):
        return f'"${{{var_name}%/}}"/'
    return f'"${{{var_name}%/}}"/{shlex.quote(rel_path)}'


def _shell_assignment(name: str, value: Optional[str], default_expr: str) -> str:
    if value is None:
        return f"{name}={default_expr}"
    return f"{name}={shlex.quote(str(value))}"


def _bridge_python_bootstrap() -> list:
    return [
        "BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"",
        "export BIO_SFM_PYTHON_BIN",
        "python() {",
        "  command \"$BIO_SFM_PYTHON_BIN\" \"$@\"",
        "}",
        "export -f python",
    ]


def _heredoc_json_assignment(path_var: str, obj: Dict[str, Any]) -> list:
    return [
        f"cat > \"${path_var}\" <<'JSON'",
        json.dumps(obj, indent=2, sort_keys=True),
        "JSON",
        "",
    ]


def _path_list_freshness_check(*, var_prefix: str, label: str, path_file: str,
                               manifest: Dict[str, Any]) -> list:
    upper = var_prefix.upper()
    return [
        f"{upper}_PATHS={shlex.quote(str(path_file))}",
        f"EXPECTED_{upper}_COUNT={int(manifest.get('n_paths') or 0)}",
        f"EXPECTED_{upper}_SHA256={shlex.quote(str(manifest.get('sha256') or ''))}",
        f"python - \"${upper}_PATHS\" \"$EXPECTED_{upper}_COUNT\" "
        f"\"$EXPECTED_{upper}_SHA256\" <<'PY'",
        "import hashlib",
        "import pathlib",
        "import sys",
        "",
        "path = pathlib.Path(sys.argv[1])",
        "expected_count = int(sys.argv[2])",
        "expected_sha256 = sys.argv[3]",
        "data = path.read_bytes()",
        "text = data.decode()",
        "actual_count = len([line for line in text.splitlines() if line.strip()])",
        "actual_sha256 = hashlib.sha256(data).hexdigest()",
        "if actual_count != expected_count or actual_sha256 != expected_sha256:",
        "    raise SystemExit(",
        f"        f\"stale {label} path list: {{path}} \"",
        "        f\"count={actual_count} sha256={actual_sha256}\"",
        "    )",
        "PY",
        "",
    ]


def _path_manifest_provenance(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    out = {
        "kind": manifest.get("kind"),
        "path_file": manifest.get("path_file"),
        "manifest_file": manifest.get("manifest_file"),
        "expected_n_paths": manifest.get("n_paths"),
        "expected_sha256": manifest.get("sha256"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _external_remote_check_guard(*, rep: Dict[str, Any], args,
                                 manifest: Optional[Dict[str, Any]]) -> list:
    report_path = args.external_remote_check_report or _remote_check_report_path(args.emit_external_remote_check_plan)
    if not args.emit_external_remote_check_plan or not report_path or not isinstance(manifest, dict):
        return []
    target_msa_plan = rep.get("target_msa_precompute_plan")
    target_msa_receipt = rep.get("target_msa_precompute_receipt")
    target_msa_receipt_required = (
        isinstance(target_msa_plan, dict)
        and bool(target_msa_plan.get("n_targets"))
        and not _target_msa_outputs_satisfied(target_msa_plan)
    )
    target_msa_receipt_ok = (
        isinstance(target_msa_receipt, dict)
        and target_msa_receipt.get("ok") is True
    )
    target_msa_receipt_path = (
        str(target_msa_receipt.get("path"))
        if target_msa_receipt_ok and target_msa_receipt.get("path")
        else ""
    )
    target_msa_receipt_sha256 = (
        str(target_msa_receipt.get("sha256"))
        if target_msa_receipt_ok and target_msa_receipt.get("sha256")
        else ""
    )
    target_msa_receipt_size_bytes = (
        int(target_msa_receipt.get("size_bytes"))
        if target_msa_receipt_ok and isinstance(target_msa_receipt.get("size_bytes"), int)
        else 0
    )
    manifest_provenance = _path_manifest_provenance(manifest)
    return [
        "# Refuse external sync unless the current remote-check proof is ready.",
        f"REMOTE_CHECK_REPORT=${{REMOTE_CHECK_REPORT:-{shlex.quote(str(report_path))}}}",
        "export REMOTE_CHECK_REPORT",
        f"TARGET_MSA_RECEIPT_REQUIRED={1 if target_msa_receipt_required else 0}",
        f"TARGET_MSA_RECEIPT_OK={1 if target_msa_receipt_ok else 0}",
        f"TARGET_MSA_RECEIPT_PATH={shlex.quote(target_msa_receipt_path)}",
        f"TARGET_MSA_RECEIPT_SHA256={shlex.quote(target_msa_receipt_sha256)}",
        f"TARGET_MSA_RECEIPT_SIZE_BYTES={target_msa_receipt_size_bytes}",
        "python - \"$PENDING_EXTERNAL_PATHS\" \"$REMOTE_CHECK_REPORT\" "
        "\"$TARGET_MSA_RECEIPT_REQUIRED\" \"$TARGET_MSA_RECEIPT_OK\" "
        "\"$TARGET_MSA_RECEIPT_PATH\" \"$TARGET_MSA_RECEIPT_SHA256\" "
        "\"$TARGET_MSA_RECEIPT_SIZE_BYTES\" <<'PY'",
        "import hashlib",
        "import json",
        "import pathlib",
        "import sys",
        "",
        "path_file = pathlib.Path(sys.argv[1])",
        "report_file = pathlib.Path(sys.argv[2])",
        "receipt_required = sys.argv[3] == '1'",
        "receipt_ok = sys.argv[4] == '1'",
        "receipt_path_text = sys.argv[5]",
        "receipt_expected_sha256 = sys.argv[6]",
        "receipt_expected_size_bytes = int(sys.argv[7])",
        "expected_manifest = " + json.dumps(manifest_provenance, sort_keys=True),
        "",
        "def fail(message):",
        "    raise SystemExit(f'external sync blocked: {message}')",
        "",
        "path_data = path_file.read_bytes()",
        "paths = [line.strip() for line in path_data.decode().splitlines() if line.strip()]",
        "expected_n = len(paths)",
        "expected_sha = hashlib.sha256(path_data).hexdigest()",
        "if receipt_required:",
        "    if not receipt_ok:",
        "        fail('target-MSA precompute receipt is not satisfied in local status')",
        "    if not receipt_path_text or not receipt_expected_sha256:",
        "        fail('target-MSA precompute receipt proof is missing from generated status')",
        "    receipt_path = pathlib.Path(receipt_path_text)",
        "    if not receipt_path.exists() or receipt_path.stat().st_size <= 0:",
        "        fail(f'target-MSA precompute receipt is missing or empty: {receipt_path}')",
        "    actual_receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()",
        "    if actual_receipt_sha256 != receipt_expected_sha256:",
        "        fail(",
        "            'target-MSA precompute receipt changed since status generation: '",
        "            f'{receipt_path} expected_sha256={receipt_expected_sha256} '",
        "            f'actual_sha256={actual_receipt_sha256}'",
        "        )",
        "    if receipt_path.stat().st_size != receipt_expected_size_bytes:",
        "        fail(",
        "            'target-MSA precompute receipt size changed since status generation: '",
        "            f'{receipt_path} expected_size={receipt_expected_size_bytes} '",
        "            f'actual_size={receipt_path.stat().st_size}'",
        "        )",
        "if not report_file.exists():",
        "    fail(f'missing remote-check report: {report_file}')",
        "try:",
        "    report = json.loads(report_file.read_text())",
        "except Exception as exc:",
        "    fail(f'invalid remote-check report {report_file}: {exc}')",
        "if not isinstance(report, dict):",
        "    fail('remote-check report is not a JSON object')",
        "failures = []",
        "if report.get('ok') is not True:",
        "    failures.append({'field': 'ok', 'expected': True, 'actual': report.get('ok')})",
        "if report.get('status') != 'all_present_nonempty':",
        "    failures.append({'field': 'status', 'expected': 'all_present_nonempty', 'actual': report.get('status')})",
        "if report.get('n_paths') != expected_n:",
        "    failures.append({'field': 'n_paths', 'expected': expected_n, 'actual': report.get('n_paths')})",
        "if report.get('path_file_sha256') != expected_sha:",
        "    failures.append({'field': 'path_file_sha256', 'expected': expected_sha, 'actual': report.get('path_file_sha256')})",
        "if report.get('n_present') != expected_n:",
        "    failures.append({'field': 'n_present', 'expected': expected_n, 'actual': report.get('n_present')})",
        "if report.get('n_missing') != 0:",
        "    failures.append({'field': 'n_missing', 'expected': 0, 'actual': report.get('n_missing')})",
        "if report.get('n_not_checked') != 0:",
        "    failures.append({'field': 'n_not_checked', 'expected': 0, 'actual': report.get('n_not_checked')})",
        "report_manifest = report.get('path_manifest')",
        "if expected_manifest:",
        "    if not isinstance(report_manifest, dict):",
        "        failures.append({'field': 'path_manifest', 'expected': 'object', 'actual': type(report_manifest).__name__})",
        "    else:",
        "        for key, expected_value in expected_manifest.items():",
        "            actual_value = report_manifest.get(key)",
        "            if actual_value != expected_value:",
        "                failures.append({'field': f'path_manifest.{key}', 'expected': expected_value, 'actual': actual_value})",
        "if receipt_required:",
        "    receipt_sync = report.get('target_msa_precompute_receipt_sync')",
        "    if not isinstance(receipt_sync, dict):",
        "        failures.append({'field': 'target_msa_precompute_receipt_sync', 'expected': 'object', 'actual': type(receipt_sync).__name__})",
        "    else:",
        "        if receipt_sync.get('requested') is not True:",
        "            failures.append({'field': 'target_msa_precompute_receipt_sync.requested', 'expected': True, 'actual': receipt_sync.get('requested')})",
        "        if receipt_sync.get('status') != 'synced':",
        "            failures.append({'field': 'target_msa_precompute_receipt_sync.status', 'expected': 'synced', 'actual': receipt_sync.get('status')})",
        "        if receipt_sync.get('synced') is not True:",
        "            failures.append({'field': 'target_msa_precompute_receipt_sync.synced', 'expected': True, 'actual': receipt_sync.get('synced')})",
        "        if receipt_sync.get('sha256') != receipt_expected_sha256:",
        "            failures.append({'field': 'target_msa_precompute_receipt_sync.sha256', 'expected': receipt_expected_sha256, 'actual': receipt_sync.get('sha256')})",
        "        if receipt_sync.get('size_bytes') != receipt_expected_size_bytes:",
        "            failures.append({'field': 'target_msa_precompute_receipt_sync.size_bytes', 'expected': receipt_expected_size_bytes, 'actual': receipt_sync.get('size_bytes')})",
        "path_records = report.get('paths')",
        "if not isinstance(path_records, list):",
        "    failures.append({'field': 'paths', 'expected': 'list', 'actual': type(path_records).__name__})",
        "else:",
        "    record_paths = []",
        "    bad_records = []",
        "    for index, item in enumerate(path_records):",
        "        if not isinstance(item, dict):",
        "            bad_records.append({'index': index, 'error': 'path_record_not_object', 'actual': type(item).__name__})",
        "            continue",
        "        rel_path = str(item.get('path', ''))",
        "        record_paths.append(rel_path)",
        "        if item.get('status') != 'present_nonempty' or item.get('present_nonempty') is not True:",
        "            bad_records.append({",
        "                'index': index,",
        "                'path': rel_path,",
        "                'status': item.get('status'),",
        "                'present_nonempty': item.get('present_nonempty'),",
        "                'error': 'path_not_present_nonempty',",
        "            })",
        "    if record_paths != paths:",
        "        failures.append({'field': 'paths', 'expected': paths, 'actual': record_paths})",
        "    if bad_records:",
        "        failures.append({'field': 'paths', 'error': 'bad_path_records', 'bad_records': bad_records})",
        "if failures:",
        "    fail('remote-check report is not ready for this external sync: ' + json.dumps(failures, sort_keys=True))",
        "PY",
        "",
    ]


def render_sync_back_plan(rep: Dict[str, Any], *, args) -> str:
    paths, skipped = _safe_relative_sync_paths(rep)
    manifest = rep.get("pending_input_prep_manifest")
    lines = [
        "# M6 complex input-prep sync-back plan",
        "# Pull the project-level pending source/prep/FASTA/MSA/report artifacts from Cayuga.",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-$(cd \"${SCRIPT_DIR}/..\" && pwd)}\"",
        "cd \"$REPO_ROOT\"",
        "",
        *_bridge_python_bootstrap(),
        "",
        "INPUT_PREP_SYNC_FAILURES=0",
        "",
        "run_input_prep_sync_step() {",
        "  local label=\"$1\"",
        "  local command",
        "  command=\"$(cat)\"",
        "  echo",
        "  echo \"## ${label}\"",
        "  set +e",
        "  bash -euo pipefail -c \"$command\"",
        "  local rc=$?",
        "  set -e",
        "  if [ \"$rc\" -ne 0 ]; then",
        "    echo \"input-prep sync step failed (${rc}): ${label}\" >&2",
        "    INPUT_PREP_SYNC_FAILURES=$((INPUT_PREP_SYNC_FAILURES + 1))",
        "  fi",
        "  return 0",
        "}",
        "",
        _shell_assignment(
            "REMOTE_ROOT",
            args.sync_remote_root,
            "${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}",
        ),
        _shell_assignment("LOCAL_ROOT", args.sync_local_root, "${LOCAL_BIO_SFM_ROOT:-$REPO_ROOT}"),
        "export REMOTE_ROOT LOCAL_ROOT",
        "",
    ]
    if args.emit_pending_input_prep_paths and isinstance(manifest, dict):
        lines.extend(_path_list_freshness_check(
            var_prefix="pending_input_prep",
            label="pending input-prep",
            path_file=args.emit_pending_input_prep_paths,
            manifest=manifest,
        ))
    if not paths:
        lines.extend([
            "# No safe relative pending input-prep paths were present in the project status.",
            "",
        ])
    for rel_path, entry in paths:
        parent = os.path.dirname(rel_path) or "."
        provenance = []
        if entry.get("target_ids"):
            provenance.append("targets=" + ",".join(entry["target_ids"]))
        if entry.get("fields"):
            provenance.append("fields=" + ",".join(entry["fields"]))
        if entry.get("workstreams"):
            provenance.append("workstreams=" + ",".join(entry["workstreams"]))
        if provenance:
            lines.append("# " + " ".join(provenance))
        lines.append(f"run_input_prep_sync_step {shlex.quote(rel_path)} <<'SH'")
        lines.append(f"mkdir -p {_shell_path_with_root('LOCAL_ROOT', parent)}")
        lines.append(
            "rsync -avP "
            f"{_shell_path_with_root('REMOTE_ROOT', rel_path)} "
            f"{_shell_path_with_root('LOCAL_ROOT', parent)}/"
        )
        lines.append(f"test -s {_shell_path_with_root('LOCAL_ROOT', rel_path)}")
        lines.append("SH")
        lines.append("")
    if skipped:
        lines.append("# Skipped unsafe or absolute pending paths; handle manually:")
        for path in skipped:
            lines.append(f"# - {path}")
        lines.append("")
    if args.emit_post_sync_plan:
        lines.extend([
            "# Replay local completion/readiness/status after sync-back.",
            "run_input_prep_sync_step 'post-sync replay' <<'SH'",
            f"bash {shlex.quote(args.emit_post_sync_plan)}",
            "SH",
            "",
        ])
    else:
        lines.extend([
            "# After sync-back, rerun complex_project_status with --emit-post-sync-plan,",
            "# then execute that replay script.",
            "",
        ])
    lines.extend([
        "if [ \"$INPUT_PREP_SYNC_FAILURES\" -ne 0 ]; then",
        "  echo",
        "  echo \"input-prep sync completed with ${INPUT_PREP_SYNC_FAILURES} failed step(s)\" >&2",
        "  exit 1",
        "fi",
        "",
        "echo",
        "echo \"input-prep sync completed successfully\"",
        "",
    ])
    return "\n".join(lines)


def render_external_sync_back_plan(rep: Dict[str, Any], *, args) -> str:
    paths, skipped = _safe_relative_external_sync_paths(rep)
    manifest = rep.get("pending_external_manifest")
    lines = [
        "# M6 complex external-artifact sync-back plan",
        "# Pull all project-level W1/W2/W3/W4 pending external artifacts from Cayuga.",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-$(cd \"${SCRIPT_DIR}/..\" && pwd)}\"",
        "cd \"$REPO_ROOT\"",
        "",
        *_bridge_python_bootstrap(),
        "",
        "EXTERNAL_SYNC_FAILURES=0",
        "",
        "run_external_sync_step() {",
        "  local label=\"$1\"",
        "  local command",
        "  command=\"$(cat)\"",
        "  echo",
        "  echo \"## ${label}\"",
        "  set +e",
        "  bash -euo pipefail -c \"$command\"",
        "  local rc=$?",
        "  set -e",
        "  if [ \"$rc\" -ne 0 ]; then",
        "    echo \"external sync step failed (${rc}): ${label}\" >&2",
        "    EXTERNAL_SYNC_FAILURES=$((EXTERNAL_SYNC_FAILURES + 1))",
        "  fi",
        "  return 0",
        "}",
        "",
        _shell_assignment(
            "REMOTE_ROOT",
            args.sync_remote_root,
            "${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}",
        ),
        _shell_assignment("LOCAL_ROOT", args.sync_local_root, "${LOCAL_BIO_SFM_ROOT:-$REPO_ROOT}"),
        "export REMOTE_ROOT LOCAL_ROOT",
        "",
    ]
    if args.emit_pending_external_paths and isinstance(manifest, dict):
        lines.extend(_path_list_freshness_check(
            var_prefix="pending_external",
            label="pending external",
            path_file=args.emit_pending_external_paths,
            manifest=manifest,
        ))
        lines.extend(_external_remote_check_guard(
            rep=rep,
            args=args,
            manifest=manifest,
        ))
    else:
        lines.extend([
            "PENDING_EXTERNAL_PATHS=\"$REMOTE_CHECK_TMP.paths\"",
            "cat > \"$PENDING_EXTERNAL_PATHS\" <<'PATHS'",
        ])
        for rel_path, _entry in paths:
            lines.append(rel_path)
        lines.extend([
            "PATHS",
            "",
        ])
    if not paths:
        lines.extend([
            "# No safe relative pending external artifact paths were present in the project status.",
            "",
        ])
    replay_scripts = []
    seen_scripts = set()
    for rel_path, entry in paths:
        parent = os.path.dirname(rel_path) or "."
        provenance = []
        if entry.get("categories"):
            provenance.append("categories=" + ",".join(entry["categories"]))
        if entry.get("artifacts"):
            provenance.append("artifacts=" + ",".join(entry["artifacts"]))
        if entry.get("target_ids"):
            provenance.append("targets=" + ",".join(entry["target_ids"]))
        if entry.get("fields"):
            provenance.append("fields=" + ",".join(entry["fields"]))
        if entry.get("workstreams"):
            provenance.append("workstreams=" + ",".join(entry["workstreams"]))
        if entry.get("sync_back_plans"):
            provenance.append("sync_back_plans=" + ",".join(entry["sync_back_plans"]))
            for script in entry["sync_back_plans"]:
                if script not in seen_scripts:
                    replay_scripts.append(script)
                    seen_scripts.add(script)
        if provenance:
            lines.append("# " + " ".join(provenance))
        lines.append(f"run_external_sync_step {shlex.quote(rel_path)} <<'SH'")
        lines.append(f"mkdir -p {_shell_path_with_root('LOCAL_ROOT', parent)}")
        lines.append(
            "rsync -avP "
            f"{_shell_path_with_root('REMOTE_ROOT', rel_path)} "
            f"{_shell_path_with_root('LOCAL_ROOT', parent)}/"
        )
        lines.append(f"test -s {_shell_path_with_root('LOCAL_ROOT', rel_path)}")
        lines.append("SH")
        lines.append("")
    if skipped:
        lines.append("# Skipped unsafe or absolute pending paths; handle manually:")
        for path in skipped:
            lines.append(f"# - {path}")
        lines.append("")
    if replay_scripts:
        lines.extend([
            "# Workstream-specific sync/rerun plans represented in this checklist:",
        ])
        for script in replay_scripts:
            lines.append(f"# - bash {shlex.quote(script)}")
        lines.extend([
            "# The unified pull above already fetched their pending paths.",
            "# Local reruns are handled by the post-sync replay plan below when self-commands are available.",
        ])
        lines.append("")
    if args.emit_post_sync_plan:
        lines.extend([
            "# Refresh project completion/readiness/status after external sync-back.",
            "run_external_sync_step 'post-sync replay' <<'SH'",
            f"bash {shlex.quote(args.emit_post_sync_plan)}",
            "SH",
            "",
        ])
    else:
        lines.extend([
            "# After sync-back, rerun complex_project_status with --emit-post-sync-plan,",
            "# then execute that replay script.",
            "",
        ])
    lines.extend([
        "if [ \"$EXTERNAL_SYNC_FAILURES\" -ne 0 ]; then",
        "  echo",
        "  echo \"external sync completed with ${EXTERNAL_SYNC_FAILURES} failed step(s)\" >&2",
        "  exit 1",
        "fi",
        "",
        "echo",
        "echo \"external sync completed successfully\"",
        "",
    ])
    return "\n".join(lines)


def render_external_remote_check_plan(rep: Dict[str, Any], *, args) -> str:
    paths, skipped = _safe_relative_external_sync_paths(rep)
    manifest = rep.get("pending_external_manifest")
    metadata = _remote_check_metadata(paths)
    manifest_provenance = _path_manifest_provenance(manifest)
    receipt = rep.get("target_msa_precompute_receipt")
    receipt_rel_path = _safe_relative_path(receipt.get("path")) if isinstance(receipt, dict) else None
    lines = [
        "# M6 complex external-artifact remote preflight",
        "# Verify project-level W1/W2/W3/W4 pending artifacts exist on Cayuga before rsync.",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-$(cd \"${SCRIPT_DIR}/..\" && pwd)}\"",
        "cd \"$REPO_ROOT\"",
        "",
        *_bridge_python_bootstrap(),
        "",
        "REMOTE_CHECK_TMP=\"$(mktemp \"${TMPDIR:-/tmp}/m6c_remote_check.XXXXXX\")\"",
        "REMOTE_CHECK_METADATA=\"$(mktemp \"${TMPDIR:-/tmp}/m6c_remote_check_metadata.XXXXXX\")\"",
        "REMOTE_CHECK_MANIFEST_PROVENANCE=\"$(mktemp \"${TMPDIR:-/tmp}/m6c_remote_check_manifest.XXXXXX\")\"",
        "REMOTE_RECEIPT_SYNC_STATUS=\"$(mktemp \"${TMPDIR:-/tmp}/m6c_receipt_sync.XXXXXX\")\"",
        "REMOTE_CHECK_REPORT=\"${REMOTE_CHECK_REPORT:-${SCRIPT_DIR}/$(basename \"${BASH_SOURCE[0]}\" .sh).json}\"",
        "cleanup_remote_check_tmp() {",
        "  rm -f \"$REMOTE_CHECK_TMP\" \"$REMOTE_CHECK_METADATA\" \"$REMOTE_CHECK_MANIFEST_PROVENANCE\" \"$REMOTE_RECEIPT_SYNC_STATUS\"",
        "}",
        "trap cleanup_remote_check_tmp EXIT",
        "export REMOTE_CHECK_TMP REMOTE_CHECK_METADATA REMOTE_CHECK_MANIFEST_PROVENANCE REMOTE_RECEIPT_SYNC_STATUS REMOTE_CHECK_REPORT",
        "printf '%s\\n' '{\"requested\": false}' > \"$REMOTE_RECEIPT_SYNC_STATUS\"",
        "",
        "REMOTE_CHECK_FAILURES=0",
        "",
        "run_external_remote_check_step() {",
        "  local label=\"$1\"",
        "  local command",
        "  command=\"$(cat)\"",
        "  echo",
        "  echo \"## ${label}\"",
        "  set +e",
        "  bash -euo pipefail -c \"$command\"",
        "  local rc=$?",
        "  set -e",
        "  printf '%s\\t%s\\n' \"$label\" \"$rc\" >> \"$REMOTE_CHECK_TMP\"",
        "  if [ \"$rc\" -ne 0 ]; then",
        "    echo \"remote check step failed (${rc}): ${label}\" >&2",
        "    REMOTE_CHECK_FAILURES=$((REMOTE_CHECK_FAILURES + 1))",
        "  fi",
        "  return 0",
        "}",
        "",
        _shell_assignment(
            "REMOTE_ROOT",
            args.sync_remote_root,
            "${CAYUGA_BIO_SFM_ROOT:?set CAYUGA_BIO_SFM_ROOT, e.g. NETID@cayuga:/scratch/NETID/bio_sfm_designer}",
        ),
        _shell_assignment("LOCAL_ROOT", args.sync_local_root, "${LOCAL_BIO_SFM_ROOT:-$REPO_ROOT}"),
        "if [[ \"$REMOTE_ROOT\" != *:* ]]; then",
        "  echo \"REMOTE_ROOT must look like host:/absolute/path, got: $REMOTE_ROOT\" >&2",
        "  exit 2",
        "fi",
        "REMOTE_HOST=\"${REMOTE_ROOT%%:*}\"",
        "REMOTE_DIR=\"${REMOTE_ROOT#*:}\"",
        "if [ -z \"$REMOTE_HOST\" ] || [ -z \"$REMOTE_DIR\" ]; then",
        "  echo \"REMOTE_ROOT must include both host and directory: $REMOTE_ROOT\" >&2",
        "  exit 2",
        "fi",
        "export REMOTE_ROOT REMOTE_HOST REMOTE_DIR LOCAL_ROOT",
        "",
    ]
    if args.emit_pending_external_paths and isinstance(manifest, dict):
        lines.extend(_path_list_freshness_check(
            var_prefix="pending_external",
            label="pending external",
            path_file=args.emit_pending_external_paths,
            manifest=manifest,
        ))
    else:
        lines.extend([
            "PENDING_EXTERNAL_PATHS=\"$REMOTE_CHECK_TMP.paths\"",
            "cat > \"$PENDING_EXTERNAL_PATHS\" <<'PATHS'",
        ])
        for rel_path, _entry in paths:
            lines.append(rel_path)
        lines.extend([
            "PATHS",
            "",
        ])
    if receipt_rel_path:
        receipt_parent = os.path.dirname(receipt_rel_path) or "."
        lines.extend([
            f"TARGET_MSA_PRECOMPUTE_RECEIPT={shlex.quote(receipt_rel_path)}",
            "export TARGET_MSA_PRECOMPUTE_RECEIPT",
            "",
            "sync_target_msa_precompute_receipt() {",
            "  local rel_path=\"$TARGET_MSA_PRECOMPUTE_RECEIPT\"",
            "  local remote_receipt=\"${REMOTE_DIR%/}/$rel_path\"",
            "  local local_receipt=\"${LOCAL_ROOT%/}/$rel_path\"",
            "  local status=\"missing_remote_receipt\"",
            "  local rc=1",
            "  echo",
            "  echo \"## target-MSA precompute receipt\"",
            "  set +e",
            "  ssh \"$REMOTE_HOST\" \"test -s $(printf '%q' \"$remote_receipt\")\"",
            "  local test_rc=$?",
            "  set -e",
            "  if [ \"$test_rc\" -eq 0 ]; then",
            f"    mkdir -p {_shell_path_with_root('LOCAL_ROOT', receipt_parent)}",
            "    set +e",
            "    rsync -avP \"${REMOTE_ROOT%/}/$rel_path\" \"$(dirname \"$local_receipt\")\"/",
            "    rc=$?",
            "    set -e",
            "    if [ \"$rc\" -eq 0 ] && [ -s \"$local_receipt\" ]; then",
            "      status=\"synced\"",
            "    else",
            "      status=\"sync_failed\"",
            "    fi",
            "  else",
            "    rc=$test_rc",
            "    echo \"target-MSA precompute receipt not found on remote yet: $remote_receipt\" >&2",
            "  fi",
            "  python - \"$REMOTE_RECEIPT_SYNC_STATUS\" \"$rel_path\" \"$status\" \"$rc\" \"$local_receipt\" <<'PY'",
            "import hashlib, json, pathlib, sys",
            "path, rel_path, status, rc_text, local_receipt = sys.argv[1:6]",
            "size_bytes = None",
            "sha256 = None",
            "if status == 'synced':",
            "    local_path = pathlib.Path(local_receipt)",
            "    try:",
            "        data = local_path.read_bytes()",
            "    except OSError:",
            "        data = b''",
            "    if data:",
            "        size_bytes = len(data)",
            "        sha256 = hashlib.sha256(data).hexdigest()",
            "    else:",
            "        status = 'sync_failed'",
            "out = {",
            "    'requested': True,",
            "    'path': rel_path,",
            "    'status': status,",
            "    'returncode': int(rc_text),",
            "    'local_path': local_receipt,",
            "    'synced': status == 'synced',",
            "    'size_bytes': size_bytes,",
            "    'sha256': sha256,",
            "}",
            "pathlib.Path(path).write_text(json.dumps(out, indent=2, sort_keys=True) + '\\n')",
            "PY",
            "}",
            "sync_target_msa_precompute_receipt",
            "",
        ])
    lines.extend(_heredoc_json_assignment("REMOTE_CHECK_METADATA", metadata))
    lines.extend(_heredoc_json_assignment("REMOTE_CHECK_MANIFEST_PROVENANCE", manifest_provenance))
    if not paths:
        lines.extend([
            "# No safe relative pending external artifact paths were present in the project status.",
            "",
        ])
    for rel_path, entry in paths:
        provenance = []
        if entry.get("categories"):
            provenance.append("categories=" + ",".join(entry["categories"]))
        if entry.get("artifacts"):
            provenance.append("artifacts=" + ",".join(entry["artifacts"]))
        if entry.get("target_ids"):
            provenance.append("targets=" + ",".join(entry["target_ids"]))
        if entry.get("fields"):
            provenance.append("fields=" + ",".join(entry["fields"]))
        if entry.get("workstreams"):
            provenance.append("workstreams=" + ",".join(entry["workstreams"]))
        if provenance:
            lines.append("# " + " ".join(provenance))
        lines.append(f"run_external_remote_check_step {shlex.quote(rel_path)} <<'SH'")
        lines.append(f"remote_path=\"${{REMOTE_DIR%/}}\"/{shlex.quote(rel_path)}")
        lines.append("ssh \"$REMOTE_HOST\" \"test -s $(printf '%q' \"$remote_path\")\"")
        lines.append("SH")
        lines.append("")
    if skipped:
        lines.append("# Skipped unsafe or absolute pending paths; handle manually:")
        for path in skipped:
            lines.append(f"# - {path}")
        lines.append("")
    lines.extend([
        "python - \"$PENDING_EXTERNAL_PATHS\" \"$REMOTE_CHECK_TMP\" \"$REMOTE_CHECK_REPORT\" \"$REMOTE_CHECK_METADATA\" \"$REMOTE_RECEIPT_SYNC_STATUS\" \"$REMOTE_CHECK_MANIFEST_PROVENANCE\" <<'PY'",
        "import hashlib",
        "import json",
        "import os",
        "import pathlib",
        "import sys",
        "",
        "path_file = pathlib.Path(sys.argv[1])",
        "tmp_file = pathlib.Path(sys.argv[2])",
        "report_file = pathlib.Path(sys.argv[3])",
        "metadata_file = pathlib.Path(sys.argv[4])",
        "receipt_sync_file = pathlib.Path(sys.argv[5])",
        "manifest_provenance_file = pathlib.Path(sys.argv[6])",
        "path_file_data = path_file.read_bytes()",
        "paths = [line.strip() for line in path_file_data.decode().splitlines() if line.strip()]",
        "metadata_by_path = {}",
        "if metadata_file.exists():",
        "    try:",
        "        loaded_metadata = json.loads(metadata_file.read_text())",
        "    except ValueError:",
        "        loaded_metadata = {}",
        "    if isinstance(loaded_metadata, dict):",
        "        metadata_by_path = loaded_metadata",
        "manifest_provenance = {}",
        "if manifest_provenance_file.exists():",
        "    try:",
        "        loaded_manifest_provenance = json.loads(manifest_provenance_file.read_text())",
        "    except ValueError:",
        "        loaded_manifest_provenance = {}",
        "    if isinstance(loaded_manifest_provenance, dict):",
        "        manifest_provenance = loaded_manifest_provenance",
        "receipt_sync = {'requested': False}",
        "if receipt_sync_file.exists():",
        "    try:",
        "        loaded_receipt_sync = json.loads(receipt_sync_file.read_text())",
        "    except ValueError:",
        "        loaded_receipt_sync = {'requested': False, 'status': 'invalid_receipt_sync_status'}",
        "    if isinstance(loaded_receipt_sync, dict):",
        "        receipt_sync = loaded_receipt_sync",
        "status_by_path = {}",
        "if tmp_file.exists():",
        "    for line in tmp_file.read_text().splitlines():",
        "        if not line.strip():",
        "            continue",
        "        rel_path, rc_text = line.rsplit('\\t', 1)",
        "        try:",
        "            rc = int(rc_text)",
        "        except ValueError:",
        "            rc = None",
        "        status_by_path[rel_path] = rc",
        "remote_dir = os.environ.get('REMOTE_DIR', '').rstrip('/')",
        "records = []",
        "n_present = 0",
        "n_missing = 0",
        "n_not_checked = 0",
        "missing_by_workstream = {}",
        "missing_by_category = {}",
        "missing_by_target_id = {}",
        "missing_by_artifact = {}",
        "def bump(counter, values, *, include_unknown=True):",
        "    clean = [str(value) for value in (values or []) if str(value)]",
        "    if not clean and include_unknown:",
        "        clean = ['unknown']",
        "    for value in clean:",
        "        counter[value] = counter.get(value, 0) + 1",
        "for rel_path in paths:",
        "    rc = status_by_path.get(rel_path)",
        "    if rc is None:",
        "        status = 'not_checked'",
        "        n_not_checked += 1",
        "    elif rc == 0:",
        "        status = 'present_nonempty'",
        "        n_present += 1",
        "    else:",
        "        status = 'missing_or_empty'",
        "        n_missing += 1",
        "    metadata = metadata_by_path.get(rel_path, {})",
        "    if not isinstance(metadata, dict):",
        "        metadata = {}",
        "    record = {",
        "        'path': rel_path,",
        "        'remote_path': f\"{remote_dir}/{rel_path}\" if remote_dir else rel_path,",
        "        'returncode': rc,",
        "        'status': status,",
        "        'present_nonempty': status == 'present_nonempty',",
        "    }",
        "    for key in ('workstreams', 'categories', 'fields', 'artifacts', 'target_ids', 'statuses', 'errors', 'sync_back_plans'):",
        "        values = metadata.get(key)",
        "        if isinstance(values, list):",
        "            record[key] = values",
        "    if isinstance(metadata.get('sync_back_plan'), str):",
        "        record['sync_back_plan'] = metadata['sync_back_plan']",
        "    if status != 'present_nonempty':",
        "        bump(missing_by_workstream, record.get('workstreams'))",
        "        bump(missing_by_category, record.get('categories'))",
        "        bump(missing_by_artifact, record.get('artifacts'))",
        "        bump(missing_by_target_id, record.get('target_ids'), include_unknown=False)",
        "    records.append(record)",
        "out = {",
        "    'ok': n_missing == 0 and n_not_checked == 0,",
        "    'status': 'all_present_nonempty' if n_missing == 0 and n_not_checked == 0 else 'missing_remote_artifacts',",
        "    'remote_root': os.environ.get('REMOTE_ROOT'),",
        "    'remote_host': os.environ.get('REMOTE_HOST'),",
        "    'remote_dir': os.environ.get('REMOTE_DIR'),",
        "    'path_file': str(path_file),",
        "    'path_file_sha256': hashlib.sha256(path_file_data).hexdigest(),",
        "    'path_manifest': manifest_provenance,",
        "    'n_paths': len(paths),",
        "    'n_present': n_present,",
        "    'n_missing': n_missing,",
        "    'n_not_checked': n_not_checked,",
        "    'n_metadata_paths': len(metadata_by_path),",
        "    'missing_by_workstream': dict(sorted(missing_by_workstream.items())),",
        "    'missing_by_category': dict(sorted(missing_by_category.items())),",
        "    'missing_by_target_id': dict(sorted(missing_by_target_id.items())),",
        "    'missing_by_artifact': dict(sorted(missing_by_artifact.items())),",
        "    'target_msa_precompute_receipt_sync': receipt_sync,",
        "    'paths': records,",
        "}",
        "report_file.parent.mkdir(parents=True, exist_ok=True)",
        "tmp_out = report_file.with_name(f'.{report_file.name}.tmp')",
        "tmp_out.write_text(json.dumps(out, indent=2, sort_keys=True) + '\\n')",
        "os.replace(tmp_out, report_file)",
        "PY",
        "echo \"remote check report: $REMOTE_CHECK_REPORT\"",
        "",
        "if [ \"$REMOTE_CHECK_FAILURES\" -ne 0 ]; then",
        "  echo",
        "  echo \"remote preflight completed with ${REMOTE_CHECK_FAILURES} failed step(s)\" >&2",
        "  echo \"missing remote artifacts usually mean the corresponding Cayuga prep/predict/batch job has not finished yet\" >&2",
        "  exit 1",
        "fi",
        "",
        "echo",
        "echo \"remote preflight found all pending external artifacts\"",
    ])
    if args.external_remote_check_report:
        refresh_command = _project_status_command(args)
        lines.append(f"printf '%s\\n' {shlex.quote('next: ' + refresh_command)}")
        if args.emit_external_sync_back_plan:
            lines.append(
                f"printf '%s\\n' "
                f"{shlex.quote('then if status recommends it: bash ' + str(args.emit_external_sync_back_plan))}"
            )
    elif args.emit_external_sync_back_plan:
        lines.append(
            "echo \"next: rerun project status with --external-remote-check-report $REMOTE_CHECK_REPORT\""
        )
    lines.append("")
    return "\n".join(lines)


def _input_prep_replay_command(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        rep = _load_json(path, role="input_prep_completion", missing_ok=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    report = rep.get("report")
    if not isinstance(report, str) or not report.strip():
        return None
    parts = [
        "python",
        "-m",
        "bio_sfm_designer.experiments.complex_input_prep_completion",
        "--report",
        report,
        "--out",
        path,
    ]
    for target_id in rep.get("target_ids") or []:
        parts.extend(["--target-id", str(target_id)])
    return shlex.join(parts)


def _readiness_self_command(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        rep = _load_json(path, role="readiness", missing_ok=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    command = rep.get("self_command")
    if isinstance(command, str) and command.strip():
        return command
    return None


def _predictor_contract_self_command(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        rep = _load_json(path, role="predictor_contract", missing_ok=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    command = rep.get("self_command")
    if isinstance(command, str) and command.strip():
        return command
    return None


def _batch_preflight_self_command(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        rep = _load_json(path, role="batch_preflight", missing_ok=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    command = rep.get("self_command")
    if isinstance(command, str) and command.strip():
        return command
    return None


def _project_status_command(args) -> str:
    parts = ["python", "-m", "bio_sfm_designer.experiments.complex_project_status"]
    for option, value in [
        ("--posthoc-manifest", args.posthoc_manifest),
        ("--decision", args.decision),
        ("--scale-completion", args.scale_completion),
        ("--input-prep-completion", args.input_prep_completion),
        ("--scale-input-prep-completion", args.scale_input_prep_completion),
        ("--panel-input-prep-completion", args.panel_input_prep_completion),
        ("--scale-target-manifest", args.scale_target_manifest),
        ("--panel-target-manifest", args.panel_target_manifest),
        ("--target-manifest-report", args.target_manifest_report),
        ("--target-msa-gate-audit", args.target_msa_gate_audit),
        ("--w2-approval-packet", args.w2_approval_packet),
        ("--w2-approval-parity", args.w2_approval_parity),
        ("--w2-panel-approval-packet", args.w2_panel_approval_packet),
        ("--w2-panel-decision-protocol", args.w2_panel_decision_protocol),
        ("--w2-panel-remote-readiness", args.w2_panel_remote_readiness),
        ("--w2-panel-submission-decision-state", args.w2_panel_submission_decision_state),
        ("--w2-panel-postsync-interpretation", args.w2_panel_postsync_interpretation),
        ("--panel-completion", args.panel_completion),
        ("--panel-report", args.panel_report),
        ("--predictor-contract-report", args.predictor_contract_report),
        ("--cross-predictor-report", args.cross_predictor_report),
        ("--w3-decision-protocol", args.w3_decision_protocol),
        ("--w3-next-protocol", args.w3_next_protocol),
        ("--w3-challenge-manifest", args.w3_challenge_manifest),
        ("--w3-third-predictor-contract", args.w3_third_predictor_contract),
        ("--w3-predictor-selection-card", args.w3_predictor_selection_card),
        ("--w3-runtime-probe-plan", args.w3_runtime_probe_plan),
        ("--w3-runtime-probe-report", args.w3_runtime_probe_report),
        ("--w3-runtime-repair-plan", args.w3_runtime_repair_plan),
        ("--w3-runtime-provision-packet", args.w3_runtime_provision_packet),
        ("--predictor-sync-back-plan", args.predictor_sync_back_plan),
        ("--batch-preflight", args.batch_preflight),
        ("--batch-summary", args.batch_summary),
        ("--batch-campaign", args.batch_campaign),
        ("--batch-sync-back-plan", args.batch_sync_back_plan),
        ("--scale-readiness-report", args.scale_readiness_report),
        ("--panel-readiness-report", args.panel_readiness_report),
        ("--out", args.out),
        ("--emit-pending-input-prep-paths", args.emit_pending_input_prep_paths),
        ("--emit-pending-external-paths", args.emit_pending_external_paths),
        ("--emit-sync-back-plan", args.emit_sync_back_plan),
        ("--emit-external-sync-back-plan", args.emit_external_sync_back_plan),
        ("--emit-external-remote-check-plan", args.emit_external_remote_check_plan),
        ("--external-remote-check-report", args.external_remote_check_report),
        ("--emit-target-msa-precompute-plan", args.emit_target_msa_precompute_plan),
        ("--target-msa-precompute-receipt", args.target_msa_precompute_receipt),
        ("--emit-post-sync-plan", args.emit_post_sync_plan),
    ]:
        if value:
            parts.extend([option, str(value)])
    if (args.emit_sync_back_plan or args.emit_external_sync_back_plan) and args.sync_remote_root:
        parts.extend(["--sync-remote-root", str(args.sync_remote_root)])
    if (args.emit_sync_back_plan or args.emit_external_sync_back_plan) and args.sync_local_root:
        parts.extend(["--sync-local-root", str(args.sync_local_root)])
    parts.extend(["--target-alpha", str(args.target_alpha)])
    if args.absolute_pending_input_prep_paths:
        parts.append("--absolute-pending-input-prep-paths")
    if args.absolute_pending_external_paths:
        parts.append("--absolute-pending-external-paths")
    return shlex.join(parts)


def render_post_sync_plan(rep: Dict[str, Any], *, args) -> str:
    lines = [
        "# M6 complex post-sync replay plan",
        "# Run after syncing the paths in the project pending input-prep/external lists.",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-$(cd \"${SCRIPT_DIR}/..\" && pwd)}\"",
        "cd \"$REPO_ROOT\"",
        "",
        "BIO_SFM_PYTHON_BIN=\"${BIO_SFM_PYTHON:-python3}\"",
        "BIO_SFM_TRUST_CORE_SRC=\"${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}\"",
        "BIO_SFM_PYTHONPATH=\"${REPO_ROOT%/}/src\"",
        "if [ -d \"$BIO_SFM_TRUST_CORE_SRC\" ]; then",
        "  BIO_SFM_PYTHONPATH=\"${BIO_SFM_PYTHONPATH}:${BIO_SFM_TRUST_CORE_SRC}\"",
        "fi",
        "export BIO_SFM_PYTHON_BIN",
        "export PYTHONNOUSERSITE=\"${PYTHONNOUSERSITE:-1}\"",
        "export PYTHONPATH=\"${BIO_SFM_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}\"",
        "python() {",
        "  command \"$BIO_SFM_PYTHON_BIN\" \"$@\"",
        "}",
        "export -f python",
        "",
    ]
    post_sync_manifest = rep.get("post_sync_replay_manifest")
    if isinstance(post_sync_manifest, dict) and post_sync_manifest.get("manifest_file"):
        lines.extend([
            f"POST_SYNC_REPLAY_MANIFEST={shlex.quote(str(post_sync_manifest.get('manifest_file')))}",
            (
                "POST_SYNC_REPLAY_MANIFEST_SHA256_EXPECTED="
                f"{shlex.quote(str(post_sync_manifest.get('sha256') or ''))}"
            ),
            f"POST_SYNC_REPLAY_MANIFEST_N_PATHS_EXPECTED={int(post_sync_manifest.get('n_paths') or 0)}",
            "",
            "verify_post_sync_replay_manifest() {",
            "  if [ ! -f \"$POST_SYNC_REPLAY_MANIFEST\" ]; then",
            "    echo \"post-sync replay manifest is missing: $POST_SYNC_REPLAY_MANIFEST\" >&2",
            "    exit 1",
            "  fi",
            "  POST_SYNC_REPLAY_MANIFEST=\"$POST_SYNC_REPLAY_MANIFEST\" \\",
            "  POST_SYNC_REPLAY_MANIFEST_SHA256_EXPECTED=\"$POST_SYNC_REPLAY_MANIFEST_SHA256_EXPECTED\" \\",
            "  POST_SYNC_REPLAY_MANIFEST_N_PATHS_EXPECTED=\"$POST_SYNC_REPLAY_MANIFEST_N_PATHS_EXPECTED\" \\",
            "  python - <<'PY'",
            "import hashlib",
            "import json",
            "import os",
            "import sys",
            "",
            "path = os.environ['POST_SYNC_REPLAY_MANIFEST']",
            "expected_sha = os.environ.get('POST_SYNC_REPLAY_MANIFEST_SHA256_EXPECTED', '')",
            "expected_n = int(os.environ.get('POST_SYNC_REPLAY_MANIFEST_N_PATHS_EXPECTED', '0'))",
            "with open(path) as fh:",
            "    data = json.load(fh)",
            "paths = [str(item).strip() for item in data.get('paths') or [] if str(item).strip()]",
            "text = '\\n'.join(paths) + ('\\n' if paths else '')",
            "actual_sha = hashlib.sha256(text.encode()).hexdigest()",
            "if len(paths) != expected_n or actual_sha != expected_sha:",
            "    print(",
            "        'post-sync replay manifest is stale: '",
            "        f'expected_n={expected_n} actual_n={len(paths)} '",
            "        f'expected_sha256={expected_sha} actual_sha256={actual_sha}',",
            "        file=sys.stderr,",
            "    )",
            "    sys.exit(1)",
            "PY",
            "}",
            "",
            "verify_post_sync_replay_manifest",
            "",
        ])
    lines.extend([
        "POST_SYNC_FAILURES=0",
        "",
        "run_post_sync_step() {",
        "  local label=\"$1\"",
        "  local command",
        "  command=\"$(cat)\"",
        "  echo",
        "  echo \"## ${label}\"",
        "  set +e",
        "  bash -euo pipefail -c \"$command\"",
        "  local rc=$?",
        "  set -e",
        "  if [ \"$rc\" -ne 0 ]; then",
        "    echo \"post-sync step failed (${rc}): ${label}\" >&2",
        "    POST_SYNC_FAILURES=$((POST_SYNC_FAILURES + 1))",
        "  fi",
        "  return 0",
        "}",
        "",
    ])
    if args.emit_pending_input_prep_paths:
        lines.extend([
            "# Pending paths expected before this replay succeeds:",
            f"# {args.emit_pending_input_prep_paths}",
            "",
        ])
    if args.emit_pending_external_paths:
        lines.extend([
            "# All pending external artifact paths at status time:",
            f"# {args.emit_pending_external_paths}",
            "",
        ])
    commands = [
        ("refresh W1 input-prep completion", _input_prep_replay_command(args.scale_input_prep_completion)),
        ("refresh W2 input-prep completion", _input_prep_replay_command(args.panel_input_prep_completion)),
        ("rerun W1 readiness", _readiness_self_command(args.scale_readiness_report)),
        ("rerun W2 readiness", _readiness_self_command(args.panel_readiness_report)),
        ("rerun W3 predictor contract", _predictor_contract_self_command(args.predictor_contract_report)),
        ("rerun W4 batch", _batch_preflight_self_command(args.batch_preflight)),
        ("refresh project status and pending-path checklist", _project_status_command(args)),
    ]
    for label, command in commands:
        lines.append(f"# {label}")
        if command:
            lines.append(f"run_post_sync_step {shlex.quote(label)} <<'SH'")
            lines.append(command)
            lines.append("SH")
        else:
            lines.append(f"# unavailable: {label}")
        lines.append("")
    if rep.get("n_pending_input_prep_paths"):
        lines.extend([
            "# Current pending input-prep paths:",
        ])
        for entry in rep.get("pending_input_prep_paths") or []:
            path = entry.get("path") if isinstance(entry, dict) else None
            if path:
                lines.append(f"# - {path}")
        lines.append("")
    lines.extend([
        "if [ \"$POST_SYNC_FAILURES\" -ne 0 ]; then",
        "  echo",
        "  echo \"post-sync replay completed with ${POST_SYNC_FAILURES} failed step(s)\" >&2",
        "  exit 1",
        "fi",
        "",
        "echo",
        "echo \"post-sync replay completed successfully\"",
        "",
    ])
    return "\n".join(lines)


def _project_manifest_hint(manifest: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(manifest, dict):
        return None
    if not manifest.get("manifest_file"):
        return None
    return {
        "source": "project_status",
        "kind": manifest.get("kind"),
        "manifest_file": manifest.get("manifest_file"),
        "path_file": manifest.get("path_file"),
        "n_paths": manifest.get("n_paths"),
        "sha256": manifest.get("sha256"),
    }


def _post_sync_replay_manifest(rep: Dict[str, Any], *, args) -> Optional[Dict[str, Any]]:
    if not args.emit_post_sync_plan:
        return None
    input_manifest = rep.get("pending_input_prep_manifest")
    external_manifest = rep.get("pending_external_manifest")
    paths = _ordered_unique_manifest_paths(input_manifest, external_manifest)
    digest = _paths_digest(paths)
    out = {
        "source": "project_status",
        "kind": "post_sync_replay_dependencies",
        "manifest_file": _manifest_path_for(args.emit_post_sync_plan),
        "n_paths": digest["n_paths"],
        "sha256": digest["sha256"],
        "paths": digest["paths"],
        "input_prep_manifest_file": (
            input_manifest.get("manifest_file") if isinstance(input_manifest, dict) else None
        ),
        "external_manifest_file": (
            external_manifest.get("manifest_file") if isinstance(external_manifest, dict) else None
        ),
    }
    return out


def _sidecar_manifest_hint(script_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not script_path:
        return None
    manifest_file = _manifest_path_for(script_path)
    out: Dict[str, Any] = {
        "source": "sidecar",
        "manifest_file": manifest_file,
        "exists": os.path.exists(manifest_file),
    }
    if not out["exists"]:
        return out
    try:
        with open(manifest_file) as fh:
            manifest = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        out.update({"valid": False, "error": str(exc)})
        return out
    if not isinstance(manifest, dict):
        out.update({"valid": False, "error": "manifest is not a JSON object"})
        return out
    out.update({
        "valid": True,
        "kind": manifest.get("kind"),
        "n_paths": manifest.get("n_paths"),
        "sha256": manifest.get("sha256"),
        "sync_script": manifest.get("sync_script"),
    })
    return out


def _manifest_hint_usable(manifest: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(manifest, dict):
        return False
    if manifest.get("source") == "sidecar":
        if manifest.get("exists") is not True:
            return False
        if manifest.get("valid") is False:
            return False
    return manifest.get("n_paths") is not None and bool(manifest.get("sha256"))


def _safe_relative_artifact_paths(entries: list) -> list:
    paths = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") or entry.get("absolute_path")
        if not isinstance(path, str) or not path.strip():
            continue
        norm = os.path.normpath(path)
        if os.path.isabs(norm) or norm == ".." or norm.startswith("../"):
            continue
        paths.append(norm)
    return paths


def _expected_sync_paths_for_role(rep: Dict[str, Any], role: str) -> Optional[list]:
    if role == "external_sync_back":
        manifest = rep.get("pending_external_manifest")
        return list(manifest.get("paths", [])) if isinstance(manifest, dict) else []
    if role == "external_remote_check":
        manifest = rep.get("pending_external_manifest")
        return list(manifest.get("paths", [])) if isinstance(manifest, dict) else []
    if role == "input_prep_sync_back":
        manifest = rep.get("pending_input_prep_manifest")
        return list(manifest.get("paths", [])) if isinstance(manifest, dict) else []
    if role == "second_predictor_sync_back":
        w3 = rep.get("workstreams", {}).get("W3_independent_predictor", {})
        return _safe_relative_artifact_paths(w3.get("pending_secondary_records") or [])
    if role == "closed_loop_batch_sync_back":
        w4 = rep.get("workstreams", {}).get("W4_closed_loop_DBTL", {})
        return _safe_relative_artifact_paths(w4.get("pending_artifacts") or [])
    if role == "post_sync_replay":
        return _ordered_unique_manifest_paths(
            rep.get("pending_input_prep_manifest"),
            rep.get("pending_external_manifest"),
        )
    return None


def attach_sync_manifest_audit(rep: Dict[str, Any]) -> Dict[str, Any]:
    checks = []
    failures = []
    for script in rep.get("generated_scripts") or []:
        if not isinstance(script, dict):
            continue
        role = script.get("role")
        expected_paths = _expected_sync_paths_for_role(rep, str(role))
        if expected_paths is None:
            continue
        expected = _paths_digest(expected_paths)
        manifest = script.get("manifest")
        check = {
            "role": role,
            "script": script.get("path"),
            "expected_n_paths": expected["n_paths"],
            "expected_sha256": expected["sha256"],
            "manifest_file": manifest.get("manifest_file") if isinstance(manifest, dict) else None,
            "manifest_n_paths": manifest.get("n_paths") if isinstance(manifest, dict) else None,
            "manifest_sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
            "source": manifest.get("source") if isinstance(manifest, dict) else None,
        }
        ok = True
        reason = None
        if not isinstance(manifest, dict):
            ok = False
            reason = "missing_manifest_summary"
        elif manifest.get("source") == "sidecar" and manifest.get("exists") is not True:
            ok = False
            reason = "missing_sidecar_manifest"
        elif manifest.get("source") == "sidecar" and manifest.get("valid") is False:
            ok = False
            reason = "invalid_sidecar_manifest"
        elif manifest.get("n_paths") != expected["n_paths"] or manifest.get("sha256") != expected["sha256"]:
            ok = False
            reason = "manifest_digest_mismatch"
        elif manifest.get("sync_script") and manifest.get("sync_script") != script.get("path"):
            ok = False
            reason = "manifest_script_mismatch"
        check["ok"] = ok
        if reason:
            check["reason"] = reason
            failures.append(check)
        checks.append(check)
        if isinstance(manifest, dict):
            manifest["expected_n_paths"] = expected["n_paths"]
            manifest["expected_sha256"] = expected["sha256"]
            manifest["matches_expected"] = ok
    rep["sync_manifest_audit"] = {
        "ok": not failures,
        "n_checks": len(checks),
        "n_failures": len(failures),
        "checks": checks,
        "failures": failures,
    }
    if failures:
        failed_roles = {failure.get("role") for failure in failures}
        first_blocked_script = None
        for script in rep.get("generated_scripts") or []:
            if isinstance(script, dict) and script.get("role") in failed_roles:
                script["blocked_by_sync_manifest_audit"] = True
                script["recommended"] = False
                if first_blocked_script is None:
                    first_blocked_script = script
        recommended = rep.get("recommended_next_script")
        if isinstance(recommended, dict):
            recommended["blocked_by_sync_manifest_audit"] = True
            recommended["recommended"] = False
        elif first_blocked_script is not None:
            rep["recommended_next_script"] = first_blocked_script
        rep["sync_manifest_audit"]["blocks_recommended_next_script"] = True
        rep["next_action"] = "regenerate stale sync script manifests before running generated sync scripts"
    return rep


_CAYUGA_SYNC_ROLES = {
    "external_remote_check",
    "external_sync_back",
    "input_prep_sync_back",
    "second_predictor_sync_back",
    "closed_loop_batch_sync_back",
}
_CAYUGA_SUBMIT_ROLES = {
    "target_msa_precompute",
}


def _script_required_env(script: Dict[str, Any]) -> list:
    role = script.get("role")
    if role in _CAYUGA_SYNC_ROLES:
        return ["CAYUGA_BIO_SFM_ROOT"]
    return []


def _bash_syntax_audit(path: Optional[str], *, timeout_s: float = 10.0) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "checked": False,
        "ok": None,
        "returncode": None,
        "error": None,
    }
    if not isinstance(path, str) or not path.strip():
        return summary
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        return summary
    summary["checked"] = True
    try:
        proc = subprocess.run(
            ["bash", "-n", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        summary.update({
            "ok": False,
            "returncode": None,
            "error": "bash executable not found",
            "blocker": "bash_not_found",
        })
        return summary
    except subprocess.TimeoutExpired as exc:
        summary.update({
            "ok": False,
            "returncode": None,
            "error": f"bash -n timed out after {timeout_s:g}s",
            "blocker": "bash_syntax_timeout",
        })
        if exc.stderr:
            summary["stderr"] = str(exc.stderr).strip()
        return summary

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    summary.update({
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
    })
    if stdout:
        summary["stdout"] = stdout
    if stderr:
        summary["stderr"] = stderr
    if proc.returncode != 0:
        summary["error"] = stderr or stdout or f"bash -n exited {proc.returncode}"
        summary["blocker"] = "bash_syntax_error"
    return summary


def _attach_script_bash_syntax_fields(script: Dict[str, Any], audit: Dict[str, Any]) -> None:
    script["script_bash_syntax_checked"] = audit.get("checked")
    script["script_bash_syntax_ok"] = audit.get("ok")
    script["script_bash_syntax_returncode"] = audit.get("returncode")
    script["script_bash_syntax_error"] = audit.get("error")


def attach_generated_script_syntax_audit(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Audit every generated bridge with non-executing bash syntax checks."""
    scripts = rep.get("generated_scripts")
    if not isinstance(scripts, list):
        return rep

    checks = []
    failures = []
    n_scripts = 0
    n_checked = 0
    n_ok = 0
    n_not_checked = 0
    for index, script in enumerate(scripts):
        if not isinstance(script, dict):
            continue
        n_scripts += 1
        audit = _bash_syntax_audit(script.get("path"))
        _attach_script_bash_syntax_fields(script, audit)
        checked = audit.get("checked") is True
        ok = audit.get("ok")
        if checked:
            n_checked += 1
        else:
            n_not_checked += 1
        if ok is True:
            n_ok += 1
        check = {
            "index": index,
            "role": script.get("role"),
            "path": script.get("path"),
            "checked": audit.get("checked"),
            "ok": ok,
            "returncode": audit.get("returncode"),
        }
        if not checked:
            check["reason"] = "missing_or_unreadable_script"
        if audit.get("error"):
            check["error"] = audit.get("error")
        if audit.get("blocker"):
            check["blocker"] = audit.get("blocker")
        if ok is False:
            script["syntax_blocked"] = True
            check["blocks_script"] = True
            failures.append(check)
        checks.append(check)

    summary = {
        "ok": not failures,
        "all_checked": n_not_checked == 0,
        "n_scripts": n_scripts,
        "n_checked": n_checked,
        "n_ok": n_ok,
        "n_not_checked": n_not_checked,
        "n_failures": len(failures),
        "checks": checks,
        "failures": failures,
    }
    if failures:
        summary["next_action"] = "regenerate or repair generated bridge scripts with bash syntax failures"
    rep["generated_script_syntax_audit"] = summary
    return rep


def _target_msa_precompute_script_validation_audit(path: Optional[str],
                                                   plan: Any) -> Dict[str, Any]:
    """Check that the emitted target-MSA bridge carries its receipt guard."""
    target_ids = []
    expected_receipt_targets = {}
    sections = []
    if isinstance(plan, dict):
        target_ids = [str(target_id) for target_id in plan.get("target_ids") or []]
        raw_expectations = plan.get("expected_receipt_targets")
        if isinstance(raw_expectations, dict):
            expected_receipt_targets = {
                str(target_id): expectation
                for target_id, expectation in raw_expectations.items()
                if isinstance(expectation, dict)
            }
        sections = [section for section in plan.get("sections") or [] if isinstance(section, dict)]

    n_section_validators = sum(
        1
        for section in sections
        if section.get("selected_target_ids") and section.get("manifest")
    )
    expected_min_validation_calls = n_section_validators + (1 if target_ids else 0)
    summary: Dict[str, Any] = {
        "checked": False,
        "ok": None,
        "path": path,
        "n_expected_targets": len(target_ids),
        "expected_target_ids": target_ids,
        "expected_min_validation_calls": expected_min_validation_calls,
    }
    if not target_ids:
        summary.update({
            "ok": True,
            "status": "not_required",
            "reason": "no target-MSA precompute targets",
        })
        return summary
    if not isinstance(path, str) or not path.strip():
        summary.update({
            "ok": False,
            "status": "missing_script_path",
            "reason": "target-MSA precompute script path is missing",
        })
        return summary
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        summary.update({
            "ok": False,
            "status": "missing_or_unreadable_script",
            "reason": "target-MSA precompute script is missing or unreadable",
        })
        return summary

    try:
        with open(path) as fh:
            text = fh.read()
    except OSError as exc:
        summary.update({
            "ok": False,
            "status": "read_failed",
            "reason": str(exc),
        })
        return summary

    summary["checked"] = True
    expected_json = json.dumps(
        expected_receipt_targets,
        sort_keys=True,
        separators=(",", ":"),
    )
    validation_call_count = text.count("validate_target_msa_precompute_receipt --expect-json")
    required_markers = [
        ("receipt_safe_dry_run_mode", "TARGET_MSA_PRECOMPUTE_DRY_RUN"),
        ("dry_run_receipt_untouched_message", "receipt untouched"),
        ("dry_run_receipt_state", "will_block_real_submit"),
        ("dry_run_receipt_preview", "recorded_target_ids"),
        ("dry_run_receipt_strict_preview", "strictly_valid_for_planned_targets"),
        ("dry_run_helper_file_preview", "all_present_nonempty_matching"),
        ("helper_file_preflight", "verify_target_msa_helper_files"),
        ("helper_file_sha256_preflight", "helper_file_sha256_mismatch"),
        ("dry_run_boltz_runtime_preview", "would_require_boltz_runtime"),
        ("boltz_runtime_preflight", "verify_target_msa_boltz_runtime"),
        ("boltz_runtime_failure", "Boltz runtime preflight failed"),
        ("boltz_env_python_default", "TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT"),
        ("bio_sfm_python_env_fallback", "BIO_SFM_PYTHON_BIN=\"$TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT\""),
        ("dry_run_source_fasta_preview", "source_fasta_inputs"),
        ("dry_run_source_fasta_regenerability_preview", "all_present_or_regenerable"),
        ("source_fasta_preflight", "verify_target_msa_source_fastas"),
        ("source_fasta_regenerability_preflight", "target_fasta_missing_and_no_regeneration_source"),
        ("receipt_validator_function", "validate_target_msa_precompute_receipt() {"),
        ("project_receipt_validation_step", "# validate_project_target_msa_precompute_receipt"),
        ("strict_project_target_set", "TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET=1"),
        ("expect_json_validation_call", "validate_target_msa_precompute_receipt --expect-json"),
    ]
    if expected_receipt_targets:
        required_markers.append(("exact_expected_receipt_json", expected_json))
    missing_markers = [
        name for name, marker in required_markers if marker not in text
    ]
    missing_expected_target_args = [
        target_id for target_id in target_ids if shlex.quote(target_id) not in text
    ]
    if validation_call_count < expected_min_validation_calls:
        missing_markers.append("validation_call_count")
    dry_run_marker = "if [ \"${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}\" = \"1\" ]; then"
    receipt_truncate_marker = ": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\""
    dry_run_before_receipt_truncate = None
    if dry_run_marker in text and receipt_truncate_marker in text:
        dry_run_before_receipt_truncate = (
            text.index(dry_run_marker) < text.index(receipt_truncate_marker)
        )
        if not dry_run_before_receipt_truncate:
            missing_markers.append("dry_run_before_receipt_truncate")

    ok = not missing_markers and not missing_expected_target_args
    summary.update({
        "ok": ok,
        "status": "ok" if ok else "failed",
        "validation_call_count": validation_call_count,
        "missing_markers": missing_markers,
        "missing_expected_target_args": missing_expected_target_args,
        "dry_run_guard_present": dry_run_marker in text,
        "dry_run_before_receipt_truncate": dry_run_before_receipt_truncate,
        "exact_expected_receipt_json_present": (
            expected_json in text if expected_receipt_targets else None
        ),
        "strict_aggregate_validation_present": (
            "# validate_project_target_msa_precompute_receipt" in text
            and "TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET=1" in text
        ),
    })
    if not ok:
        summary["next_action"] = (
            "regenerate the target-MSA precompute bridge so receipt validation "
            "guards are present before Cayuga submission"
        )
    return summary


def _add_script_blocker(script: Dict[str, Any], blocker: str) -> None:
    blockers = script.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    if blocker not in blockers:
        blockers.append(blocker)
    script["blockers"] = blockers


def attach_target_msa_precompute_script_validation_audit(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a machine-readable audit for the target-MSA receipt guard."""
    scripts = rep.get("generated_scripts")
    if not isinstance(scripts, list):
        return rep
    plan = rep.get("target_msa_precompute_plan")
    for script in scripts:
        if not isinstance(script, dict) or script.get("role") != "target_msa_precompute":
            continue
        audit = _target_msa_precompute_script_validation_audit(script.get("path"), plan)
        script["target_msa_receipt_validation_audit"] = audit
        rep["target_msa_precompute_script_validation_audit"] = audit
        if audit.get("ok") is False:
            script["receipt_validation_blocked"] = True
            script["recommended"] = False
            _add_script_blocker(script, _TARGET_MSA_RECEIPT_VALIDATION_AUDIT_BLOCKER)
        break
    return rep


def attach_resume_bridge_preflight(rep: Dict[str, Any], *, env=None) -> Dict[str, Any]:
    """Record whether the recommended bridge can be executed from this checkout.

    The generated sync scripts already fail closed internally. This lightweight
    audit makes a resumed Codex session show the same blockers before a human or
    agent tries to run the bridge command.
    """

    recommended = rep.get("recommended_next_script")
    if not isinstance(recommended, dict):
        return rep
    env = os.environ if env is None else env
    path = recommended.get("path")
    script_exists = isinstance(path, str) and os.path.isfile(path)
    script_readable = bool(script_exists and os.access(path, os.R_OK))
    script_executable_bit = bool(script_exists and os.access(path, os.X_OK))
    bash_syntax = _bash_syntax_audit(path)

    manifest = recommended.get("manifest")
    path_file = manifest.get("path_file") if isinstance(manifest, dict) else None
    manifest_file = manifest.get("manifest_file") if isinstance(manifest, dict) else None
    path_file_exists = bool(isinstance(path_file, str) and os.path.isfile(path_file))
    manifest_file_exists = bool(isinstance(manifest_file, str) and os.path.isfile(manifest_file))

    required_env = _script_required_env(recommended)
    missing_env = [name for name in required_env if not env.get(name)]
    requires_cayuga_session = recommended.get("role") in _CAYUGA_SUBMIT_ROLES
    sync_audit = rep.get("sync_manifest_audit")
    sync_audit_ok = not isinstance(sync_audit, dict) or sync_audit.get("ok") is True

    blockers = []
    if not isinstance(path, str) or not path.strip():
        blockers.append("missing_script_path")
    elif not script_exists:
        blockers.append("missing_script")
    elif not script_readable:
        blockers.append("unreadable_script")
    if isinstance(manifest, dict):
        if manifest.get("source") == "sidecar" and manifest.get("exists") is not True:
            blockers.append("missing_sidecar_manifest")
        if manifest.get("valid") is False:
            blockers.append("invalid_manifest")
        if manifest.get("matches_expected") is False:
            blockers.append("manifest_digest_mismatch")
        if path_file and not path_file_exists:
            blockers.append("missing_path_file")
        if manifest_file and not manifest_file_exists:
            blockers.append("missing_manifest_file")
    if recommended.get("blocked_by_sync_manifest_audit") or not sync_audit_ok:
        blockers.append("sync_manifest_audit_failed")
    if bash_syntax.get("ok") is False:
        blockers.append(str(bash_syntax.get("blocker") or "bash_syntax_error"))
    recommended_blockers = recommended.get("blockers")
    if isinstance(recommended_blockers, list):
        blockers.extend(str(blocker) for blocker in recommended_blockers if blocker)

    structural_ok = not blockers
    ready_now = structural_ok and not missing_env and not requires_cayuga_session
    if ready_now:
        status = "ready_to_execute"
        next_action = recommended.get("command")
    elif structural_ok and requires_cayuga_session:
        status = "waiting_on_cayuga_session"
        next_action = (
            f"run {recommended.get('command')} from the Cayuga repo checkout, "
            "then rerun the remote-check bridge"
        )
    elif structural_ok and missing_env:
        status = "waiting_on_env"
        next_action = (
            "export CAYUGA_BIO_SFM_ROOT=NETID@cayuga:/scratch/NETID/bio_sfm_designer, "
            f"then run {recommended.get('command')}"
        )
    else:
        status = "blocked"
        if "target_msa_plan_conflicts" in blockers:
            next_action = "repair duplicated target ids that point to different target FASTA/MSA/report paths before precompute"
        elif _TARGET_MSA_RECEIPT_REVIEW_BLOCKER in blockers:
            next_action = _TARGET_MSA_RECEIPT_REVIEW_ACTION
        elif _TARGET_MSA_RECEIPT_VALIDATION_AUDIT_BLOCKER in blockers:
            next_action = "regenerate the target-MSA precompute bridge so receipt validation guards are present"
        else:
            next_action = "regenerate or fix the recommended bridge before running it"

    preflight = {
        "status": status,
        "ready_to_execute_now": ready_now,
        "structural_ok": structural_ok,
        "command": recommended.get("command"),
        "script": path,
        "script_exists": script_exists,
        "script_readable": script_readable,
        "script_executable_bit": script_executable_bit,
        "script_runs_via_bash": bool(script_exists),
        "script_bash_syntax_checked": bash_syntax.get("checked"),
        "script_bash_syntax_ok": bash_syntax.get("ok"),
        "script_bash_syntax_returncode": bash_syntax.get("returncode"),
        "script_bash_syntax_error": bash_syntax.get("error"),
        "required_env": required_env,
        "missing_env": missing_env,
        "requires_cayuga_session": requires_cayuga_session,
        "path_file": path_file,
        "path_file_exists": path_file_exists if path_file else None,
        "manifest_file": manifest_file,
        "manifest_file_exists": manifest_file_exists if manifest_file else None,
        "manifest_matches_expected": manifest.get("matches_expected") if isinstance(manifest, dict) else None,
        "sync_manifest_audit_ok": sync_audit_ok,
        "blockers": blockers,
        "next_action": next_action,
    }
    rep["resume_bridge_preflight"] = preflight
    recommended["resume_preflight_status"] = status
    recommended["ready_to_execute_now"] = ready_now
    _attach_script_bash_syntax_fields(recommended, bash_syntax)
    if blockers:
        recommended["resume_preflight_blockers"] = blockers
    if missing_env:
        recommended["missing_env"] = missing_env
    return rep


def _script_by_role(rep: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    scripts = rep.get("generated_scripts")
    if not isinstance(scripts, list):
        return {}
    by_role = {}
    for script in scripts:
        if isinstance(script, dict) and script.get("role"):
            by_role[str(script["role"])] = script
    return by_role


def _ladder_step(script: Dict[str, Any], *, status: str, ready: bool = False,
                 blocked_by: Optional[str] = None,
                 next_action: Optional[str] = None) -> Dict[str, Any]:
    step = {
        "role": script.get("role"),
        "status": status,
        "ready_to_execute_now": bool(ready),
        "command": script.get("command"),
        "path": script.get("path"),
        "label": script.get("label"),
        "reason": script.get("reason"),
        "recommended": bool(script.get("recommended")),
    }
    if script.get("manifest"):
        step["manifest"] = script.get("manifest")
    if script.get("report"):
        step["report"] = script.get("report")
    if script.get("receipt"):
        step["receipt"] = script.get("receipt")
    if blocked_by:
        step["blocked_by"] = blocked_by
    if next_action:
        step["next_action"] = next_action
    return step


def _apply_recommended_readiness(step: Dict[str, Any], rep: Dict[str, Any]) -> None:
    recommended = rep.get("recommended_next_script")
    if not isinstance(recommended, dict) or step.get("role") != recommended.get("role"):
        return
    preflight = rep.get("resume_bridge_preflight")
    if isinstance(preflight, dict):
        step["status"] = preflight.get("status", step["status"])
        step["ready_to_execute_now"] = bool(preflight.get("ready_to_execute_now"))
        step["resume_preflight_status"] = preflight.get("status")
        step["required_env"] = preflight.get("required_env")
        step["missing_env"] = preflight.get("missing_env")
        step["blockers"] = preflight.get("blockers")
        step["preflight_next_action"] = preflight.get("next_action")
    else:
        step["ready_to_execute_now"] = bool(recommended.get("ready_to_execute_now"))
    if recommended.get("blocked_by_sync_manifest_audit"):
        step["status"] = "blocked_by_sync_manifest_audit"


def _status_refresh_ladder_step(rep: Dict[str, Any], *, status: str,
                                blocked_by: Optional[str] = None,
                                next_action: Optional[str] = None) -> Dict[str, Any]:
    step = {
        "role": "project_status_refresh",
        "status": status,
        "ready_to_execute_now": False,
        "command": rep.get("self_command"),
        "label": "Refresh project status with remote-check report",
        "reason": "remote-check evidence must be consumed before external sync-back",
        "recommended": False,
        "pseudo_step": True,
    }
    remote_report = rep.get("external_remote_check_report")
    if isinstance(remote_report, dict):
        step["report_status"] = remote_report.get("status")
        if remote_report.get("report"):
            step["report"] = remote_report.get("report")
        elif remote_report.get("path"):
            step["report"] = remote_report.get("path")
    if blocked_by:
        step["blocked_by"] = blocked_by
    if next_action:
        step["next_action"] = next_action
    return step


def _external_remote_check_report_arg(rep: Dict[str, Any]) -> str:
    remote_report = rep.get("external_remote_check_report")
    report_path = None
    if isinstance(remote_report, dict):
        report_path = remote_report.get("report") or remote_report.get("path")
    if report_path:
        return f"--external-remote-check-report {report_path}"
    return "--external-remote-check-report <remote-check-report>"


def _w2_panel_approval_ladder_step(
    *,
    role: str,
    command: Optional[str],
    label: str,
    status: str,
    blocked_by: Optional[str] = None,
    next_action: Optional[str] = None,
    ready: bool = False,
) -> Dict[str, Any]:
    step: Dict[str, Any] = {
        "role": role,
        "status": status,
        "ready_to_execute_now": bool(ready),
        "command": command,
        "label": label,
        "recommended": False,
    }
    if blocked_by:
        step["blocked_by"] = blocked_by
    if next_action:
        step["next_action"] = next_action
    return step


def _attach_w2_panel_approval_ladder(rep: Dict[str, Any]) -> None:
    if rep.get("resume_execution_ladder"):
        return
    streams = rep.get("workstreams")
    if not isinstance(streams, dict):
        return
    w2 = streams.get("W2_multi_target_panel")
    if not isinstance(w2, dict):
        return
    if w2.get("status") != "panel_approval_packet_ready_awaiting_explicit_approval":
        return
    if w2.get("panel_submission_decision") != "awaiting_explicit_approval":
        return
    steps = [
        _w2_panel_approval_ladder_step(
            role="w2_panel_submit",
            command=w2.get("panel_submit_command_if_approved"),
            label="Submit guarded W2 v11 ProteinMPNN/Boltz panel after explicit approval",
            status="waiting_for_explicit_approval",
            next_action=(
                "obtain explicit approval naming W2 v11 Cayuga ProteinMPNN/Boltz panel submission; "
                "continuation phrases are not approval"
            ),
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_postsubmit_driver",
            command=w2.get("panel_postsubmit_driver_after_submit"),
            label="Run no-submit post-submit driver",
            status="blocked_until_w2_panel_submit_creates_receipt",
            blocked_by="w2_panel_submit",
            next_action=(
                "after explicit submit creates a receipt, run the no-submit driver to monitor receipt, "
                "query job states, require sync-ready status, sync records, complete, and replay interpretation"
            ),
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_receipt_monitor",
            command=w2.get("panel_receipt_monitor_after_submit"),
            label="Sync submit receipt and summary only",
            status="blocked_until_w2_panel_submit_creates_receipt",
            blocked_by="w2_panel_submit",
            next_action="after explicit submit creates a receipt, sync receipt/summary before any records",
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_job_state_query",
            command=w2.get("panel_job_state_query_after_receipt"),
            label="Run read-only Slurm job-state query",
            status="blocked_until_receipt_monitor_completes",
            blocked_by="w2_panel_receipt_monitor",
            next_action="after receipt sync, query job states without syncing panel records",
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_postsubmit_status",
            command=w2.get("panel_postsubmit_status_command_before_sync"),
            label="Require postsubmit sync-ready state",
            status="blocked_until_job_state_query_completes",
            blocked_by="w2_panel_job_state_query",
            next_action="wait for all submitted jobs to finish, then require sync-ready status",
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_sync_back",
            command=w2.get("panel_sync_back_command_after_jobs_finish"),
            label="Sync panel records back from Cayuga",
            status="blocked_until_postsubmit_sync_ready",
            blocked_by="w2_panel_postsubmit_status",
            next_action="sync records only after receipt, summary, job states, and sync-ready status pass",
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_completion",
            command=w2.get("panel_completion_command_after_sync"),
            label="Run panel completion gate",
            status="blocked_until_panel_sync_back_completes",
            blocked_by="w2_panel_sync_back",
            next_action="after record sync-back, run completion checks before interpretation",
        ),
        _w2_panel_approval_ladder_step(
            role="w2_panel_postsync_replay",
            command=w2.get("panel_postsync_replay_after_sync"),
            label="Run target-wise report and post-sync interpretation",
            status="blocked_until_panel_completion_completes",
            blocked_by="w2_panel_completion",
            next_action="generate target-wise panel report and refresh W2 interpretation",
        ),
    ]
    rep["resume_execution_ladder"] = {
        "next_role": "w2_panel_submit",
        "next_command": w2.get("panel_submit_command_if_approved"),
        "approval_disambiguation": {
            "continuation_phrases_are_approval": w2.get(
                "panel_submission_decision_continuation_phrases_are_approval"
            ),
            "non_approval_continuation_phrases": w2.get(
                "panel_submission_decision_non_approval_continuation_phrases"
            ),
            "approval_must_explicitly_name": w2.get("panel_submission_decision_approval_must_explicitly_name"),
            "machine_gate": w2.get("panel_submission_decision_machine_gate"),
        },
        "steps": steps,
    }


def attach_resume_execution_ladder(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Expose the bridge sequence needed to resume without rereading scripts."""
    scripts = _script_by_role(rep)
    recommended = rep.get("recommended_next_script") if isinstance(rep.get("recommended_next_script"), dict) else {}
    remote_report = rep.get("external_remote_check_report") if isinstance(rep.get("external_remote_check_report"), dict) else {}
    steps = []

    has_external_pending = bool(rep.get("n_pending_external_artifacts"))
    has_input_pending = bool(rep.get("n_pending_input_prep_paths"))
    remote_ready = remote_report.get("ready_for_external_sync") is True
    target_msa_script = scripts.get("target_msa_precompute")
    target_msa_plan = rep.get("target_msa_precompute_plan")
    target_msa_receipt = rep.get("target_msa_precompute_receipt")
    target_msa_receipt_ok = (
        isinstance(target_msa_receipt, dict)
        and target_msa_receipt.get("ok") is True
    )
    target_msa_outputs_satisfied = _target_msa_outputs_satisfied(target_msa_plan)
    target_msa_plan_available = (
        bool(target_msa_script)
        and isinstance(target_msa_plan, dict)
        and bool(target_msa_plan.get("n_targets"))
    )
    target_msa_precompute_required = (
        has_external_pending
        and not remote_ready
        and target_msa_plan_available
        and not target_msa_receipt_ok
        and not target_msa_outputs_satisfied
        and remote_report.get("status") != "target_msa_receipt_sync_missing"
    )

    if has_external_pending:
        sync_predecessor = "external_sync_back"
        if target_msa_plan_available and (target_msa_receipt_ok or target_msa_outputs_satisfied):
            steps.append(_ladder_step(
                target_msa_script,
                status="satisfied",
                next_action="target-MSA outputs are present; proceed to remote-check",
            ))
        elif target_msa_precompute_required:
            step = _ladder_step(
                target_msa_script,
                status="required",
                next_action=target_msa_plan.get("next_action"),
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)
        remote_script = scripts.get("external_remote_check")
        if remote_script:
            if remote_ready:
                status = "satisfied"
                next_action = "fresh remote-check report is ok; proceed to external sync-back"
            elif target_msa_precompute_required:
                status = "blocked_until_target_msa_precompute_completes"
                next_action = "run the target-MSA precompute bridge before remote-check"
            elif remote_report.get("status") == "missing_remote_artifacts":
                status = "waiting_on_remote_jobs"
                next_action = remote_report.get("next_action")
            else:
                status = "required"
                next_action = remote_report.get("next_action")
            step = _ladder_step(
                remote_script,
                status=status,
                blocked_by="target_msa_precompute" if target_msa_precompute_required and not remote_ready else None,
                next_action=next_action,
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)

        if remote_script:
            if remote_ready:
                refresh_status = "satisfied"
                refresh_blocked_by = None
                refresh_next_action = (
                    "project status has consumed the fresh remote-check report; proceed to external sync-back"
                )
            else:
                refresh_status = "blocked_until_remote_check_passes"
                refresh_blocked_by = "external_remote_check"
                refresh_next_action = (
                    "after remote-check writes a fresh ok=true report, rerun project status with "
                    f"{_external_remote_check_report_arg(rep)}"
                )
            steps.append(_status_refresh_ladder_step(
                rep,
                status=refresh_status,
                blocked_by=refresh_blocked_by,
                next_action=refresh_next_action,
            ))

        external_script = scripts.get("external_sync_back")
        if external_script:
            if remote_ready:
                status = "required"
                blocked_by = None
                next_action = "pull external artifacts, then run post-sync replay"
            else:
                status = "blocked_until_project_status_refresh_completes"
                blocked_by = "project_status_refresh"
                next_action = (
                    "rerun the remote-check bridge, then refresh project status before external sync-back"
                )
            step = _ladder_step(
                external_script,
                status=status,
                blocked_by=blocked_by,
                next_action=next_action,
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)
        elif scripts.get("input_prep_sync_back"):
            sync_predecessor = "input_prep_sync_back"
            step = _ladder_step(
                scripts["input_prep_sync_back"],
                status="partial_input_prep_sync",
                next_action="pull W1/W2 input-prep artifacts; emit the unified external sync bridge for W3/W4 artifacts when needed",
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)

        post_script = scripts.get("post_sync_replay")
        if post_script:
            step = _ladder_step(
                post_script,
                status=f"blocked_until_{sync_predecessor}_completes",
                blocked_by=sync_predecessor,
                next_action="rerun local completion/readiness/status checks after sync-back",
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)
    elif has_input_pending:
        input_script = scripts.get("input_prep_sync_back")
        if input_script:
            step = _ladder_step(
                input_script,
                status="required",
                next_action="pull W1/W2 input-prep artifacts, then run post-sync replay",
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)
        post_script = scripts.get("post_sync_replay")
        if post_script:
            step = _ladder_step(
                post_script,
                status="blocked_until_input_prep_sync_completes",
                blocked_by="input_prep_sync_back",
                next_action="rerun local completion/readiness/status checks after sync-back",
            )
            _apply_recommended_readiness(step, rep)
            steps.append(step)
    elif scripts.get("post_sync_replay") and recommended.get("role") == "post_sync_replay":
        step = _ladder_step(
            scripts["post_sync_replay"],
            status="required",
            next_action="rerun local completion/readiness/status checks",
        )
        _apply_recommended_readiness(step, rep)
        steps.append(step)

    if steps:
        rep["resume_execution_ladder"] = {
            "next_role": recommended.get("role"),
            "next_command": recommended.get("command"),
            "steps": steps,
        }
    _attach_w2_panel_approval_ladder(rep)
    return rep


def _remote_check_report_path(script_path: Optional[str]) -> Optional[str]:
    if not script_path:
        return None
    root, ext = os.path.splitext(script_path)
    if ext:
        return root + ".json"
    return script_path + ".json"


def _shell_plan_sibling(json_path: Optional[str]) -> Optional[str]:
    if not isinstance(json_path, str) or not json_path.strip():
        return None
    root, ext = os.path.splitext(json_path)
    if ext == ".json":
        candidate = root + ".sh"
        if os.path.exists(candidate):
            return candidate
    return None


def _readiness_followup(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    report = _load_json(path, role="readiness_report")
    if not isinstance(report, dict) or _is_missing_artifact(report):
        return None
    ordered_steps = []
    for step in report.get("ordered_steps") or []:
        if not isinstance(step, dict):
            continue
        ordered_steps.append({
            "id": step.get("id"),
            "status": step.get("status"),
            "plan_section": step.get("plan_section"),
            "description": step.get("description"),
        })
    available_steps = [
        step for step in ordered_steps
        if step.get("status") in {"available", "waiting_on_input_prep"}
    ]
    return {
        "path": path,
        "status": report.get("status"),
        "next_action": report.get("next_action"),
        "self_command": report.get("self_command"),
        "shell_plan": _shell_plan_sibling(path),
        "ordered_steps": ordered_steps,
        "available_steps": available_steps,
    }


def _remote_missing_action(workstream_id: str, readiness: Optional[Dict[str, Any]],
                           group: Optional[Dict[str, Any]] = None) -> str:
    if workstream_id in {"W1_M6c_scale_up", "W2_multi_target_panel"}:
        categories = set(str(value) for value in (group or {}).get("categories", set()))
        artifacts = set(str(value) for value in (group or {}).get("artifacts", set()))
        fields = set(str(value) for value in (group or {}).get("fields", set()))
        if (
            categories.intersection({"scale_records", "panel_records"})
            or ("records" in artifacts and not fields.intersection({"target_msa", "target_msa_report"}))
        ):
            return "wait for or fix the Cayuga ProteinMPNN/Boltz record jobs, then rerun the remote-check bridge"
        if readiness and any(step.get("id") == "target_msa_precompute" for step in readiness.get("available_steps", [])):
            return "run the readiness target_msa_precompute section for the listed targets, then rerun the remote-check bridge"
        return "finish target-MSA/input-prep artifacts for the listed targets, then rerun the remote-check bridge"
    if workstream_id == "W3_independent_predictor":
        return "finish or regenerate independent-predictor records, rerun the W3 contract, then rerun the remote-check bridge"
    if workstream_id == "W4_closed_loop_DBTL":
        return "finish or regenerate W4 candidates/records/verdicts, rerun W4 preflight, then rerun the remote-check bridge"
    return "finish the missing remote artifacts, then rerun the remote-check bridge"


def _workstream_followup_groups(records: list, *, skip_present: bool) -> Dict[str, Dict[str, Any]]:
    by_workstream: Dict[str, Dict[str, Any]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if skip_present and record.get("status") == "present_nonempty":
            continue
        record_workstreams = record.get("workstreams")
        if not isinstance(record_workstreams, list) or not record_workstreams:
            record_workstreams = ["unknown"]
        for workstream_id in record_workstreams:
            key = str(workstream_id)
            item = by_workstream.setdefault(key, {
                "workstream": key,
                "n_missing": 0,
                "paths": [],
                "categories": set(),
                "target_ids": set(),
                "artifacts": set(),
                "fields": set(),
                "sync_back_plans": set(),
            })
            item["n_missing"] += 1
            if record.get("path"):
                item["paths"].append(str(record.get("path")))
            for target_key, source_key in (
                ("categories", "categories"),
                ("target_ids", "target_ids"),
                ("artifacts", "artifacts"),
                ("fields", "fields"),
                ("sync_back_plans", "sync_back_plans"),
            ):
                values = record.get(source_key)
                if isinstance(values, list):
                    item[target_key].update(str(value) for value in values if str(value))
            if isinstance(record.get("sync_back_plan"), str):
                item["sync_back_plans"].add(record["sync_back_plan"])
    return by_workstream


def _build_workstream_followups(
    rep: Dict[str, Any],
    by_workstream: Dict[str, Dict[str, Any]],
    *,
    readiness_by_workstream: Dict[str, Optional[Dict[str, Any]]],
) -> list:
    workstreams = rep.get("workstreams") if isinstance(rep.get("workstreams"), dict) else {}
    followups = []
    for workstream_id in sorted(by_workstream):
        item = by_workstream[workstream_id]
        workstream = workstreams.get(workstream_id) if isinstance(workstreams, dict) else None
        readiness = readiness_by_workstream.get(workstream_id)
        followup = {
            "workstream": workstream_id,
            "n_missing": item["n_missing"],
            "paths": sorted(item["paths"]),
            "categories": sorted(item["categories"]),
            "target_ids": sorted(item["target_ids"]),
            "artifacts": sorted(item["artifacts"]),
            "fields": sorted(item["fields"]),
            "sync_back_plans": sorted(item["sync_back_plans"]),
            "next_action": _remote_missing_action(workstream_id, readiness, item),
        }
        if isinstance(workstream, dict):
            followup.update({
                "workstream_status": workstream.get("status"),
                "workstream_next_action": workstream.get("next_action"),
                "evidence": workstream.get("evidence"),
            })
            if workstream.get("manifest_command"):
                followup["manifest_command"] = workstream.get("manifest_command")
            if workstream.get("sync_back_plan"):
                followup["workstream_sync_back_plan"] = workstream.get("sync_back_plan")
        if readiness:
            followup["readiness"] = readiness
        followups.append(followup)
    return followups


def _remote_missing_followups(rep: Dict[str, Any], report: Dict[str, Any], *, args) -> list:
    records = report.get("paths")
    if not isinstance(records, list):
        return []
    readiness_by_workstream = {
        "W1_M6c_scale_up": _readiness_followup(args.scale_readiness_report),
        "W2_multi_target_panel": _readiness_followup(args.panel_readiness_report),
    }
    by_workstream = _workstream_followup_groups(records, skip_present=True)
    return _build_workstream_followups(
        rep,
        by_workstream,
        readiness_by_workstream=readiness_by_workstream,
    )


def attach_pending_external_followups(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    records = rep.get("pending_external_artifacts")
    if not isinstance(records, list):
        rep["pending_external_followups"] = []
        return rep
    readiness_by_workstream = {
        "W1_M6c_scale_up": _readiness_followup(args.scale_readiness_report),
        "W2_multi_target_panel": _readiness_followup(args.panel_readiness_report),
    }
    by_workstream = _workstream_followup_groups(records, skip_present=False)
    rep["pending_external_followups"] = _build_workstream_followups(
        rep,
        by_workstream,
        readiness_by_workstream=readiness_by_workstream,
    )
    return rep


def _followup_target_msa_ids(rep: Dict[str, Any], workstream_id: str) -> list:
    ids = []
    for item in rep.get("pending_external_followups") or []:
        if not isinstance(item, dict) or item.get("workstream") != workstream_id:
            continue
        fields = set(str(field) for field in item.get("fields") or [])
        if fields and not fields.intersection({"target_msa", "target_msa_report"}):
            continue
        for target_id in item.get("target_ids") or []:
            value = str(target_id)
            if value and value not in ids:
                ids.append(value)
    return ids


def _manifest_targets(path: Optional[str]) -> tuple:
    if not path:
        return [], {}
    try:
        with open(path) as fh:
            manifest = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError):
        return [], {}
    out = []
    by_id = {}
    for target in manifest.get("targets") or []:
        if isinstance(target, dict) and target.get("id") is not None:
            target_id = str(target["id"])
            out.append(target_id)
            by_id[target_id] = target
    return out, by_id


def _manifest_target_ids(path: Optional[str]) -> list:
    ids, _targets = _manifest_targets(path)
    return ids


def _receipt_expectation_from_target(target: Dict[str, Any], *, manifest: Optional[str],
                                     manifest_sha256: Optional[str] = None,
                                     workstream: str) -> Dict[str, Any]:
    expected: Dict[str, Any] = {}
    for field in ("target_fasta", "target_msa"):
        if target.get(field) is not None:
            expected[field] = str(target[field])
    target_msa = expected.get("target_msa")
    if target.get("target_msa_report") is not None:
        expected["target_msa_report"] = str(target["target_msa_report"])
    elif target_msa:
        expected["target_msa_report"] = str(target_msa) + ".report.json"
    if manifest:
        expected["manifest"] = manifest
    if manifest_sha256:
        expected["manifest_sha256"] = manifest_sha256
    if workstream:
        expected["workstream"] = workstream
    return expected


def _source_fasta_input_from_target(target: Dict[str, Any], *, target_id: str,
                                    manifest: Optional[str], workstream: str) -> Dict[str, Any]:
    expected: Dict[str, Any] = {"target_id": str(target_id)}
    for field in (
        "target_fasta",
        "target_fasta_report",
        "prepared_pdb",
        "prep_report",
        "source_pdb",
        "target_chain",
        "binder_chain",
        "rcsb_id",
    ):
        if target.get(field) is not None:
            expected[field] = str(target[field])
    if target.get("allow_numbering_gaps") is not None:
        expected["allow_numbering_gaps"] = bool(target.get("allow_numbering_gaps"))
    if manifest:
        expected["manifest"] = manifest
    if workstream:
        expected["workstream"] = workstream
    return expected


_TARGET_MSA_DEDUP_FIELDS = ("target_fasta", "target_msa", "target_msa_report")


def _target_msa_dedup_material(expectation: Dict[str, Any]) -> Dict[str, str]:
    return {
        field: str(expectation[field])
        for field in _TARGET_MSA_DEDUP_FIELDS
        if expectation.get(field) is not None
    }


def _select_manifest_targets(path: Optional[str], requested: list, seen: Dict[str, Dict[str, Any]], *,
                             workstream: str = "") -> tuple:
    manifest_ids, targets_by_id = _manifest_targets(path)
    manifest_sha256 = _sha256_file(path) if path and os.path.exists(path) else None
    manifest_set = set(manifest_ids)
    selected = []
    missing = []
    skipped_seen = []
    duplicate_conflicts = []
    receipt_expectations = {}
    source_fasta_inputs = {}
    for target_id in requested:
        if target_id in seen:
            target = targets_by_id.get(target_id)
            if isinstance(target, dict):
                expectation = _receipt_expectation_from_target(
                    target,
                    manifest=path,
                    manifest_sha256=manifest_sha256,
                    workstream=workstream,
                )
                previous = seen[target_id]
                material = _target_msa_dedup_material(expectation)
                previous_material = _target_msa_dedup_material(previous.get("expectation", {}))
                if material != previous_material:
                    duplicate_conflicts.append({
                        "target_id": target_id,
                        "first_workstream": previous.get("workstream"),
                        "first_manifest": previous.get("manifest"),
                        "duplicate_workstream": workstream,
                        "duplicate_manifest": path,
                        "first_material": previous_material,
                        "duplicate_material": material,
                    })
                else:
                    skipped_seen.append(target_id)
            else:
                skipped_seen.append(target_id)
        elif target_id in manifest_set:
            selected.append(target_id)
            target = targets_by_id.get(target_id)
            if isinstance(target, dict):
                expectation = _receipt_expectation_from_target(
                    target,
                    manifest=path,
                    manifest_sha256=manifest_sha256,
                    workstream=workstream,
                )
                receipt_expectations[target_id] = expectation
                source_fasta_inputs[target_id] = _source_fasta_input_from_target(
                    target,
                    target_id=target_id,
                    manifest=path,
                    workstream=workstream,
                )
                seen[target_id] = {
                    "expectation": expectation,
                    "manifest": path,
                    "workstream": workstream,
                }
        else:
            missing.append(target_id)
    return (
        selected,
        missing,
        skipped_seen,
        manifest_ids,
        receipt_expectations,
        duplicate_conflicts,
        source_fasta_inputs,
    )


def _target_msa_precompute_plan_summary(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    seen = {}
    sections = []
    missing_from_manifest = []
    skipped_duplicates = []
    conflicting_duplicates = []
    requested = [
        (
            "W1_M6c_scale_up",
            args.scale_target_manifest,
            _followup_target_msa_ids(rep, "W1_M6c_scale_up"),
        ),
        (
            "W2_multi_target_panel",
            args.panel_target_manifest,
            _followup_target_msa_ids(rep, "W2_multi_target_panel"),
        ),
    ]
    for workstream_id, manifest_path, target_ids in requested:
        (
            selected,
            missing,
            duplicates,
            manifest_ids,
            receipt_expectations,
            duplicate_conflicts,
            source_fasta_inputs,
        ) = _select_manifest_targets(
            manifest_path,
            target_ids,
            seen,
            workstream=workstream_id,
        )
        manifest_sha256 = None
        if isinstance(receipt_expectations, dict):
            for expectation in receipt_expectations.values():
                if isinstance(expectation, dict) and expectation.get("manifest_sha256"):
                    manifest_sha256 = str(expectation["manifest_sha256"])
                    break
        if manifest_sha256 is None and manifest_path and os.path.exists(manifest_path):
            manifest_sha256 = _sha256_file(manifest_path)
        sections.append({
            "workstream": workstream_id,
            "manifest": manifest_path,
            "manifest_sha256": manifest_sha256,
            "requested_target_ids": target_ids,
            "selected_target_ids": selected,
            "manifest_target_ids": manifest_ids,
            "receipt_expectations": receipt_expectations,
            "source_fasta_inputs": source_fasta_inputs,
        })
        missing_from_manifest.extend({
            "workstream": workstream_id,
            "manifest": manifest_path,
            "target_id": target_id,
        } for target_id in missing)
        skipped_duplicates.extend({
            "workstream": workstream_id,
            "manifest": manifest_path,
            "target_id": target_id,
        } for target_id in duplicates)
        conflicting_duplicates.extend(duplicate_conflicts)
    selected_ids = []
    expected_receipt_targets: Dict[str, Dict[str, Any]] = {}
    source_fasta_inputs: Dict[str, Dict[str, Any]] = {}
    for section in sections:
        selected_ids.extend(section["selected_target_ids"])
        expectations = section.get("receipt_expectations")
        if isinstance(expectations, dict):
            expected_receipt_targets.update(expectations)
        source_inputs = section.get("source_fasta_inputs")
        if isinstance(source_inputs, dict):
            source_fasta_inputs.update(source_inputs)
    return {
        "ok": not conflicting_duplicates,
        "path": args.emit_target_msa_precompute_plan,
        "command": (
            f"bash {args.emit_target_msa_precompute_plan}"
            if args.emit_target_msa_precompute_plan
            else None
        ),
        "dry_run_command": _target_msa_precompute_dry_run_command(args.emit_target_msa_precompute_plan),
        "receipt_path": args.target_msa_precompute_receipt,
        "n_targets": len(selected_ids),
        "target_ids": selected_ids,
        "expected_receipt_targets": expected_receipt_targets,
        "source_fasta_inputs": source_fasta_inputs,
        "sections": sections,
        "missing_from_manifest": missing_from_manifest,
        "skipped_duplicate_target_ids": skipped_duplicates,
        "conflicting_duplicate_target_ids": conflicting_duplicates,
        "next_action": (
            "repair duplicated target ids that point to different target FASTA/MSA/report paths before precompute"
            if conflicting_duplicates
            else "run the deduplicated W1/W2 target-MSA precompute plan on Cayuga, then rerun the remote-check bridge"
            if selected_ids
            else "provide raw W1/W2 target manifests or run the readiness target_msa_precompute sections directly"
        ),
    }


def attach_target_msa_precompute_plan(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    summary = _target_msa_precompute_plan_summary(rep, args=args)
    if args.emit_target_msa_precompute_plan or summary.get("n_targets"):
        rep["target_msa_precompute_plan"] = summary
    return rep


def attach_target_msa_precompute_receipt(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    plan = rep.get("target_msa_precompute_plan")
    receipt_path = args.target_msa_precompute_receipt
    expected_ids = []
    expected_receipt_targets: Dict[str, Dict[str, Any]] = {}
    if isinstance(plan, dict):
        receipt_path = receipt_path or plan.get("receipt_path")
        expected_ids = [str(target_id) for target_id in plan.get("target_ids") or []]
        raw_expectations = plan.get("expected_receipt_targets")
        if isinstance(raw_expectations, dict):
            expected_receipt_targets = {
                str(target_id): expectation
                for target_id, expectation in raw_expectations.items()
                if isinstance(expectation, dict)
            }
    if not receipt_path:
        return rep

    summary: Dict[str, Any] = {
        "path": receipt_path,
        "exists": os.path.exists(receipt_path),
        "ok": False,
        "fresh": False,
        "expected_target_ids": expected_ids,
        "expected_receipt_targets": expected_receipt_targets,
        "n_expected": len(expected_ids),
    }
    summary["size_bytes"] = os.path.getsize(receipt_path) if summary["exists"] else 0
    summary["sha256"] = _sha256_file(receipt_path) if summary["exists"] else None
    plan_conflicts = (
        plan.get("conflicting_duplicate_target_ids")
        if isinstance(plan, dict)
        else None
    )
    if isinstance(plan_conflicts, list) and plan_conflicts:
        summary.update({
            "status": "plan_conflict",
            "n_records": 0,
            "missing_target_ids": expected_ids,
            "conflicting_duplicate_target_ids": plan_conflicts,
            "next_action": "repair duplicated target ids that point to different target FASTA/MSA/report paths before precompute",
        })
        rep["target_msa_precompute_receipt"] = summary
        return rep
    if not expected_ids:
        summary.update({
            "status": "not_required",
            "ok": True,
            "fresh": True,
            "n_records": None,
            "n_recorded_expected": 0,
            "n_submitted": None,
            "n_validated_existing": None,
            "recorded_target_ids": [],
            "missing_target_ids": [],
            "unexpected_target_ids": [],
            "bad_records": [],
            "next_action": "no target-MSA precompute is pending; rerun the remote-check bridge for the current pending external checklist",
        })
        rep["target_msa_precompute_receipt"] = summary
        return rep
    if not summary["exists"]:
        summary.update({
            "status": "missing_receipt",
            "n_records": 0,
            "missing_target_ids": expected_ids,
            "next_action": "run the target-MSA precompute bridge on Cayuga, then rerun the remote-check bridge",
        })
        rep["target_msa_precompute_receipt"] = summary
        return rep

    try:
        records = _load_jsonl_records(receipt_path)
    except (OSError, ValueError) as exc:
        summary.update({
            "status": "invalid_receipt",
            "error": str(exc),
            "next_action": _TARGET_MSA_RECEIPT_REVIEW_ACTION,
        })
        if _target_msa_receipt_requires_review(summary):
            summary["resume_blocker"] = _TARGET_MSA_RECEIPT_REVIEW_BLOCKER
        rep["target_msa_precompute_receipt"] = summary
        return rep

    by_target: Dict[str, Dict[str, Any]] = {}
    bad_records = []
    accepted_statuses = {"submitted", "validated_existing"}
    for index, record in enumerate(records):
        target_id = str(record.get("target_id", ""))
        status = str(record.get("status", ""))
        if not target_id:
            bad_records.append({"index": index, "error": "missing_target_id"})
            continue
        if status not in accepted_statuses:
            bad_records.append({"target_id": target_id, "status": status, "error": "unexpected_status"})
            continue
        if status == "submitted":
            job_id_error = _submitted_job_id_error(record.get("job_id"))
            if job_id_error:
                bad_records.append({
                    "target_id": target_id,
                    "status": status,
                    "job_id": record.get("job_id"),
                    "error": job_id_error,
                })
                continue
        if target_id in by_target:
            bad_records.append({
                "target_id": target_id,
                "index": index,
                "error": "duplicate_target_id",
            })
            continue
        expected = expected_receipt_targets.get(target_id) or {}
        for field in (
            "target_fasta",
            "target_msa",
            "target_msa_report",
            "manifest",
            "manifest_sha256",
            "workstream",
        ):
            if field not in expected:
                continue
            actual_value = record.get(field)
            expected_value = str(expected[field])
            if actual_value is None or str(actual_value) != expected_value:
                bad_records.append({
                    "target_id": target_id,
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                    "error": "receipt_field_mismatch",
                })
        by_target[target_id] = record

    expected_set = set(expected_ids)
    recorded_expected = sorted(expected_set.intersection(by_target))
    missing = [target_id for target_id in expected_ids if target_id not in by_target]
    unexpected = sorted(target_id for target_id in by_target if target_id not in expected_set)
    for target_id in unexpected:
        bad_records.append({
            "target_id": target_id,
            "status": by_target[target_id].get("status"),
            "error": "unexpected_target_id",
        })
    ok = bool(expected_ids) and not missing and not bad_records
    summary.update({
        "status": "satisfied" if ok else "incomplete_receipt",
        "ok": ok,
        "fresh": ok,
        "n_records": len(records),
        "n_recorded_expected": len(recorded_expected),
        "n_submitted": sum(1 for record in by_target.values() if record.get("status") == "submitted"),
        "n_validated_existing": sum(1 for record in by_target.values() if record.get("status") == "validated_existing"),
        "recorded_target_ids": recorded_expected,
        "missing_target_ids": missing,
        "unexpected_target_ids": unexpected,
        "bad_records": bad_records,
        "next_action": (
            "rerun the remote-check bridge for the current pending external checklist"
            if ok
            else _TARGET_MSA_RECEIPT_REVIEW_ACTION
            if summary.get("size_bytes", 0) > 0
            else "rerun or repair the target-MSA precompute bridge before remote-check"
        ),
    })
    if _target_msa_receipt_requires_review(summary):
        summary["resume_blocker"] = _TARGET_MSA_RECEIPT_REVIEW_BLOCKER
    rep["target_msa_precompute_receipt"] = summary
    return rep


def render_project_target_msa_precompute_plan(rep: Dict[str, Any], *, args) -> str:
    summary = rep.get("target_msa_precompute_plan")
    if not isinstance(summary, dict):
        summary = _target_msa_precompute_plan_summary(rep, args=args)
    lines = [
        "# M6 complex project target-MSA precompute plan",
        "# Deduplicates W1/W2 target-MSA prep before remote-check and external sync-back.",
        "set -euo pipefail",
        "",
        "SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"",
        "REPO_ROOT=\"${BIO_SFM_REPO_ROOT:-$(cd \"${SCRIPT_DIR}/..\" && pwd)}\"",
        "cd \"$REPO_ROOT\"",
        "",
        "TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT=\"${ENV_PY:-$HOME/.conda/envs/boltz/bin/python}\"",
        "if [ -n \"${BIO_SFM_PYTHON:-}\" ]; then",
        "  BIO_SFM_PYTHON_BIN=\"$BIO_SFM_PYTHON\"",
        "elif [ -x \"$TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT\" ]; then",
        "  BIO_SFM_PYTHON_BIN=\"$TARGET_MSA_PRECOMPUTE_ENV_PY_DEFAULT\"",
        "else",
        "  BIO_SFM_PYTHON_BIN=\"python3\"",
        "fi",
        "BIO_SFM_TRUST_CORE_SRC=\"${BIO_SFM_TRUST_CORE_SRC:-${REPO_ROOT%/}/../bio-sfm-trust-core/src}\"",
        "BIO_SFM_PYTHONPATH=\"${REPO_ROOT%/}/src\"",
        "if [ -d \"$BIO_SFM_TRUST_CORE_SRC\" ]; then",
        "  BIO_SFM_PYTHONPATH=\"${BIO_SFM_PYTHONPATH}:${BIO_SFM_TRUST_CORE_SRC}\"",
        "fi",
        "export BIO_SFM_PYTHON_BIN",
        "export PYTHONNOUSERSITE=\"${PYTHONNOUSERSITE:-1}\"",
        "export PYTHONPATH=\"${BIO_SFM_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}\"",
        "python() {",
        "  command \"$BIO_SFM_PYTHON_BIN\" \"$@\"",
        "}",
        "export -f python",
        "",
        f"# target_ids={','.join(summary.get('target_ids') or []) or 'none'}",
        "",
    ]
    conflicts = summary.get("conflicting_duplicate_target_ids")
    if isinstance(conflicts, list) and conflicts:
        lines.extend([
            "echo 'target-MSA precompute plan has conflicting duplicate target ids; repair raw manifests before submitting.' >&2",
            "cat >&2 <<'JSON'",
            json.dumps(conflicts, indent=2, sort_keys=True),
            "JSON",
            "exit 2",
            "",
        ])
    lines.extend([
        "if ! command -v sbatch >/dev/null 2>&1; then",
        "  if [ \"${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}\" = \"1\" ]; then",
        "    :",
        "  elif [ \"${TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH:-0}\" != \"1\" ]; then",
        "    echo \"target-MSA precompute requires SLURM sbatch; run this from the Cayuga repo checkout.\" >&2",
        "    echo \"Set TARGET_MSA_PRECOMPUTE_DRY_RUN=1 for a receipt-safe local plan preview.\" >&2",
        "    echo \"Set TARGET_MSA_PRECOMPUTE_ALLOW_NO_SBATCH=1 only for explicit local diagnostics.\" >&2",
        "    exit 2",
        "  fi",
        "fi",
        "",
        "verify_target_msa_manifest_fresh() {",
        "  local manifest=\"$1\"",
        "  local expected_sha=\"$2\"",
        "  local workstream=\"$3\"",
        "  if [ -z \"$manifest\" ] || [ -z \"$expected_sha\" ]; then",
        "    echo \"target-MSA precompute cannot verify manifest freshness for ${workstream}: missing manifest or expected sha\" >&2",
        "    exit 2",
        "  fi",
        "  if [ ! -f \"$manifest\" ]; then",
        "    echo \"target-MSA precompute manifest is missing for ${workstream}: $manifest\" >&2",
        "    exit 2",
        "  fi",
        "  local actual_sha",
        "  actual_sha=$(TARGET_MSA_PRECOMPUTE_MANIFEST=\"$manifest\" python - <<'PY'",
        "import hashlib, os, pathlib",
        "path = pathlib.Path(os.environ[\"TARGET_MSA_PRECOMPUTE_MANIFEST\"])",
        "print(hashlib.sha256(path.read_bytes()).hexdigest())",
        "PY",
        ")",
        "  if [ \"$actual_sha\" != \"$expected_sha\" ]; then",
        "    echo \"target-MSA precompute manifest is stale for ${workstream}: $manifest expected_sha256=${expected_sha} actual_sha256=${actual_sha}\" >&2",
        "    exit 2",
        "  fi",
        "}",
        "",
    ])
    for section in summary.get("sections") or []:
        if not isinstance(section, dict):
            continue
        target_ids = section.get("selected_target_ids") or []
        manifest = section.get("manifest")
        manifest_sha256 = section.get("manifest_sha256")
        if not target_ids or not manifest:
            continue
        lines.append(
            "verify_target_msa_manifest_fresh "
            f"{shlex.quote(str(manifest))} "
            f"{shlex.quote(str(manifest_sha256 or ''))} "
            f"{shlex.quote(str(section.get('workstream') or ''))}"
        )
    if any(
        isinstance(section, dict) and section.get("selected_target_ids") and section.get("manifest")
        for section in summary.get("sections") or []
    ):
        lines.append("")
    receipt_path = summary.get("receipt_path")
    if receipt_path:
        lines.extend([
            "if [ -z \"${TARGET_MSA_PRECOMPUTE_RECEIPT:-}\" ]; then",
            f"  TARGET_MSA_PRECOMPUTE_RECEIPT={shlex.quote(str(receipt_path))}",
            "fi",
            "export TARGET_MSA_PRECOMPUTE_RECEIPT",
            "",
        ])
    required_helper_files = []
    for helper_path in (
        "hpc/prep_hetdimer.py",
        "hpc/extract_chain_fasta.py",
        "hpc/precompute_boltz_target_msa.py",
        "hpc/run_precompute_boltz_target_msa.sbatch",
    ):
        helper: Dict[str, Any] = {"path": helper_path}
        if os.path.isfile(helper_path):
            helper["sha256"] = _sha256_file(helper_path)
            helper["size_bytes"] = os.path.getsize(helper_path)
        else:
            helper["sha256"] = None
            helper["size_bytes"] = None
        required_helper_files.append(helper)
    dry_run_payload = {
        "dry_run": True,
        "message": "manifests fresh; no sbatch submitted; receipt untouched",
        "target_ids": summary.get("target_ids") or [],
        "expected_receipt_targets": summary.get("expected_receipt_targets") or {},
        "helper_files": required_helper_files,
        "boltz_runtime": {
            "env_py_default": "$HOME/.conda/envs/boltz/bin/python",
            "boltz_default": "$HOME/.conda/envs/boltz/bin/boltz",
            "target_msa_outputs": [
                {
                    "target_id": str(target_id),
                    "target_msa": str(expectation.get("target_msa") or ""),
                }
                for target_id, expectation in sorted(
                    (summary.get("expected_receipt_targets") or {}).items()
                )
                if isinstance(expectation, dict)
            ],
        },
        "source_fasta_inputs": [
            source_input
            for _target_id, source_input in sorted(
                (summary.get("source_fasta_inputs") or {}).items()
            )
            if isinstance(source_input, dict)
        ],
        "sections": [
            {
                "workstream": section.get("workstream"),
                "manifest": section.get("manifest"),
                "manifest_sha256": section.get("manifest_sha256"),
                "selected_target_ids": section.get("selected_target_ids") or [],
            }
            for section in summary.get("sections") or []
            if isinstance(section, dict)
            and section.get("selected_target_ids")
            and section.get("manifest")
        ],
    }
    lines.extend([
        "if [ \"${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}\" = \"1\" ]; then",
        "  echo \"target-MSA precompute dry-run: manifests fresh; no sbatch submitted; receipt untouched.\"",
        f"  TARGET_MSA_PRECOMPUTE_DRY_RUN_PAYLOAD={shlex.quote(json.dumps(dry_run_payload, sort_keys=True))}",
        "  export TARGET_MSA_PRECOMPUTE_DRY_RUN_PAYLOAD",
        "  python - <<'PY'",
        "from collections import Counter",
        "import json, os, pathlib",
        "payload = json.loads(os.environ['TARGET_MSA_PRECOMPUTE_DRY_RUN_PAYLOAD'])",
        "receipt_path = os.environ.get('TARGET_MSA_PRECOMPUTE_RECEIPT')",
        "overwrite = os.environ.get('TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT', '0') == '1'",
        "expected_specs = payload.get('expected_receipt_targets') or {}",
        "expected_targets = set(expected_specs.keys())",
        "helper_file_specs = payload.get('helper_files') or []",
        "boltz_runtime_spec = payload.get('boltz_runtime') or {}",
        "source_fasta_inputs = payload.get('source_fasta_inputs') or []",
        "accepted_statuses = {'submitted', 'validated_existing'}",
        "def sha256_file(path):",
        "    import hashlib",
        "    h = hashlib.sha256()",
        "    with open(path, 'rb') as fh:",
        "        for chunk in iter(lambda: fh.read(1024 * 1024), b''):",
        "            h.update(chunk)",
        "    return h.hexdigest()",
        "def submitted_job_id_error(job_id):",
        "    if job_id is None:",
        "        return 'missing_job_id'",
        "    text = str(job_id)",
        "    if not text.strip():",
        "        return 'missing_job_id'",
        "    if any(ch.isspace() for ch in text):",
        "        return 'invalid_job_id'",
        "    return None",
        "def receipt_preview(path):",
        "    n_lines = 0",
        "    n_blank_lines = 0",
        "    records = []",
        "    parse_errors = []",
        "    try:",
        "        with path.open() as fh:",
        "            for lineno, line in enumerate(fh, 1):",
        "                n_lines += 1",
        "                text = line.strip()",
        "                if not text:",
        "                    n_blank_lines += 1",
        "                    continue",
        "                try:",
        "                    record = json.loads(text)",
        "                except json.JSONDecodeError as exc:",
        "                    parse_errors.append({'line': lineno, 'error': str(exc)})",
        "                    continue",
        "                if not isinstance(record, dict):",
        "                    parse_errors.append({'line': lineno, 'error': 'record is not an object'})",
        "                    continue",
        "                records.append(record)",
        "    except OSError as exc:",
        "        parse_errors.append({'line': None, 'error': str(exc)})",
        "    target_counts = Counter(str(record.get('target_id') or '') for record in records)",
        "    target_counts.pop('', None)",
        "    recorded = set(target_counts)",
        "    valid_by_target = {}",
        "    validation_errors = list(parse_errors)",
        "    for index, record in enumerate(records):",
        "        target_id = str(record.get('target_id') or '')",
        "        status = str(record.get('status') or '')",
        "        record_errors = []",
        "        if not target_id:",
        "            record_errors.append({'index': index, 'error': 'missing_target_id'})",
        "        if target_id and target_id not in expected_targets:",
        "            record_errors.append({'target_id': target_id, 'status': status, 'error': 'unexpected_target_id'})",
        "        if status not in accepted_statuses:",
        "            record_errors.append({'target_id': target_id, 'status': status, 'error': 'unexpected_status'})",
        "        if status == 'submitted':",
        "            job_id_error = submitted_job_id_error(record.get('job_id'))",
        "            if job_id_error:",
        "                record_errors.append({",
        "                    'target_id': target_id,",
        "                    'status': status,",
        "                    'job_id': record.get('job_id'),",
        "                    'error': job_id_error,",
        "                })",
        "        if target_id in valid_by_target:",
        "            record_errors.append({'target_id': target_id, 'index': index, 'error': 'duplicate_target_id'})",
        "        expected = expected_specs.get(target_id) or {}",
        "        for field in ('target_fasta', 'target_msa', 'target_msa_report', 'manifest', 'manifest_sha256', 'workstream'):",
        "            if field not in expected:",
        "                continue",
        "            actual_value = record.get(field)",
        "            expected_value = str(expected[field])",
        "            if actual_value is None or str(actual_value) != expected_value:",
        "                record_errors.append({",
        "                    'target_id': target_id,",
        "                    'field': field,",
        "                    'expected': expected_value,",
        "                    'actual': actual_value,",
        "                    'error': 'receipt_field_mismatch',",
        "                })",
        "        if record_errors:",
        "            validation_errors.extend(record_errors)",
        "        elif target_id:",
        "            valid_by_target[target_id] = record",
        "    valid_recorded = set(valid_by_target)",
        "    return {",
        "        'n_lines': n_lines,",
        "        'n_blank_lines': n_blank_lines,",
        "        'n_records': len(records),",
        "        'n_parse_errors': len(parse_errors),",
        "        'parse_errors': parse_errors[:5],",
        "        'recorded_target_ids': sorted(recorded),",
        "        'valid_recorded_target_ids': sorted(valid_recorded),",
        "        'missing_target_ids': sorted(expected_targets - recorded),",
        "        'missing_valid_target_ids': sorted(expected_targets - valid_recorded),",
        "        'unexpected_target_ids': sorted(recorded - expected_targets),",
        "        'duplicate_target_ids': sorted(target_id for target_id, count in target_counts.items() if count > 1),",
        "        'status_counts': dict(sorted(Counter(str(record.get('status') or '') for record in records).items())),",
        "        'validation_error_count': len(validation_errors),",
        "        'validation_errors': validation_errors[:5],",
        "        'strictly_valid_for_planned_targets': (",
        "            not validation_errors",
        "            and not (expected_targets - valid_recorded)",
        "            and not (valid_recorded - expected_targets)",
        "            and bool(expected_targets)",
        "        ),",
        "        'looks_complete_for_planned_targets': (",
        "            not parse_errors",
        "            and not (expected_targets - recorded)",
        "            and not (recorded - expected_targets)",
        "            and all(count == 1 for count in target_counts.values())",
        "            and bool(expected_targets)",
        "        ),",
        "    }",
        "def path_state(path_text):",
        "    exists = False",
        "    size_bytes = 0",
        "    is_file = False",
        "    if path_text:",
        "        path = pathlib.Path(path_text)",
        "        exists = path.exists()",
        "        is_file = path.is_file()",
        "        size_bytes = path.stat().st_size if exists and is_file else 0",
        "    return {",
        "        'path': path_text,",
        "        'exists': exists,",
        "        'is_file': is_file,",
        "        'size_bytes': size_bytes,",
        "        'nonempty': bool(exists and is_file and size_bytes > 0),",
        "    }",
        "def helper_file_preview():",
        "    paths = []",
        "    for item in helper_file_specs:",
        "        if not isinstance(item, dict):",
        "            continue",
        "        path_text = str(item.get('path') or '')",
        "        expected_sha = item.get('sha256')",
        "        state = path_state(path_text)",
        "        actual_sha = None",
        "        sha256_matches = False",
        "        if state['nonempty']:",
        "            try:",
        "                actual_sha = sha256_file(path_text)",
        "            except OSError:",
        "                actual_sha = None",
        "        if expected_sha and actual_sha:",
        "            sha256_matches = str(expected_sha) == str(actual_sha)",
        "        status = 'present_matching_sha256' if state['nonempty'] and sha256_matches else 'blocked'",
        "        paths.append({",
        "            'path': path_text,",
        "            'exists': state['exists'],",
        "            'is_file': state['is_file'],",
        "            'size_bytes': state['size_bytes'],",
        "            'nonempty': state['nonempty'],",
        "            'expected_sha256': expected_sha,",
        "            'actual_sha256': actual_sha,",
        "            'sha256_matches': sha256_matches,",
        "            'status': status,",
        "        })",
        "    missing = [item for item in paths if not item['exists']]",
        "    empty = [item for item in paths if item['exists'] and not item['nonempty']]",
        "    mismatched = [item for item in paths if item['nonempty'] and not item['sha256_matches']]",
        "    return {",
        "        'n_inputs': len(paths),",
        "        'n_missing': len(missing),",
        "        'n_empty': len(empty),",
        "        'n_sha256_mismatch': len(mismatched),",
        "        'all_present_nonempty_matching': bool(paths) and not missing and not empty and not mismatched,",
        "        'paths': paths,",
        "    }",
        "def boltz_runtime_preview():",
        "    env_py = os.environ.get('ENV_PY') or os.path.expandvars(str(boltz_runtime_spec.get('env_py_default') or ''))",
        "    boltz = os.environ.get('BOLTZ') or os.path.expandvars(str(boltz_runtime_spec.get('boltz_default') or ''))",
        "    outputs = []",
        "    for item in boltz_runtime_spec.get('target_msa_outputs') or []:",
        "        if not isinstance(item, dict):",
        "            continue",
        "        target_id = str(item.get('target_id') or '')",
        "        target_msa = str(item.get('target_msa') or '')",
        "        state = path_state(target_msa)",
        "        outputs.append({",
        "            'target_id': target_id,",
        "            'target_msa': target_msa,",
        "            'present_nonempty': state['nonempty'],",
        "        })",
        "    missing_outputs = [item for item in outputs if not item['present_nonempty']]",
        "    env_py_state = path_state(env_py)",
        "    boltz_state = path_state(boltz)",
        "    env_py_executable = env_py_state['nonempty'] and os.access(env_py, os.X_OK)",
        "    boltz_executable = boltz_state['nonempty'] and os.access(boltz, os.X_OK)",
        "    would_require = bool(missing_outputs)",
        "    return {",
        "        'would_require_boltz_runtime': would_require,",
        "        'n_target_msa_outputs': len(outputs),",
        "        'n_missing_target_msa_outputs': len(missing_outputs),",
        "        'missing_target_ids': [item['target_id'] for item in missing_outputs],",
        "        'env_py': env_py,",
        "        'env_py_exists': env_py_state['exists'],",
        "        'env_py_executable': env_py_executable,",
        "        'boltz': boltz,",
        "        'boltz_exists': boltz_state['exists'],",
        "        'boltz_executable': boltz_executable,",
        "        'runtime_ready': (not would_require) or (env_py_executable and boltz_executable),",
        "        'outputs': outputs,",
        "    }",
        "def source_fasta_preview():",
        "    paths = []",
        "    for item in source_fasta_inputs:",
        "        if not isinstance(item, dict):",
        "            continue",
        "        path_text = str(item.get('target_fasta') or '')",
        "        target_id = str(item.get('target_id') or '')",
        "        target_state = path_state(path_text)",
        "        prepared_pdb = str(item.get('prepared_pdb') or '')",
        "        source_pdb = str(item.get('source_pdb') or '')",
        "        prepared_state = path_state(prepared_pdb)",
        "        source_state = path_state(source_pdb)",
        "        has_target_chain = bool(str(item.get('target_chain') or '').strip())",
        "        has_binder_chain = bool(str(item.get('binder_chain') or '').strip())",
        "        has_rcsb_id = bool(str(item.get('rcsb_id') or '').strip())",
        "        can_extract_from_prepared = prepared_state['nonempty'] and has_target_chain",
        "        can_prepare_from_source = source_state['nonempty'] and bool(prepared_pdb) and has_target_chain and has_binder_chain",
        "        can_fetch_prepare = has_rcsb_id and bool(source_pdb) and bool(prepared_pdb) and has_target_chain and has_binder_chain",
        "        if target_state['nonempty']:",
        "            status = 'present_nonempty'",
        "            blocking_reason = None",
        "        elif can_extract_from_prepared:",
        "            status = 'regenerable_from_prepared_pdb'",
        "            blocking_reason = None",
        "        elif can_prepare_from_source:",
        "            status = 'regenerable_from_source_pdb'",
        "            blocking_reason = None",
        "        elif can_fetch_prepare:",
        "            status = 'regenerable_from_rcsb'",
        "            blocking_reason = None",
        "        else:",
        "            status = 'blocked'",
        "            blocking_reason = 'target_fasta_missing_and_no_regeneration_source'",
        "        paths.append({",
        "            'target_id': target_id,",
        "            'path': path_text,",
        "            'exists': target_state['exists'],",
        "            'is_file': target_state['is_file'],",
        "            'size_bytes': target_state['size_bytes'],",
        "            'nonempty': target_state['nonempty'],",
        "            'prepared_pdb': prepared_pdb,",
        "            'prepared_pdb_nonempty': prepared_state['nonempty'],",
        "            'source_pdb': source_pdb,",
        "            'source_pdb_nonempty': source_state['nonempty'],",
        "            'target_chain': str(item.get('target_chain') or ''),",
        "            'binder_chain': str(item.get('binder_chain') or ''),",
        "            'rcsb_id': str(item.get('rcsb_id') or ''),",
        "            'can_regenerate': status != 'blocked' and not target_state['nonempty'],",
        "            'status': status,",
        "            'blocking_reason': blocking_reason,",
        "        })",
        "    missing = [item for item in paths if not item['exists']]",
        "    empty = [item for item in paths if item['exists'] and not item['nonempty']]",
        "    blocked = [item for item in paths if item['status'] == 'blocked']",
        "    regenerable = [item for item in paths if item['can_regenerate']]",
        "    return {",
        "        'n_inputs': len(paths),",
        "        'n_missing': len(missing),",
        "        'n_empty': len(empty),",
        "        'n_present': sum(1 for item in paths if item['status'] == 'present_nonempty'),",
        "        'n_regenerable': len(regenerable),",
        "        'n_blocked': len(blocked),",
        "        'all_present_nonempty': bool(paths) and not missing and not empty,",
        "        'all_present_or_regenerable': bool(paths) and not blocked,",
        "        'blocked_target_ids': [item['target_id'] for item in blocked],",
        "        'paths': paths,",
        "    }",
        "payload['helper_files'] = helper_file_preview()",
        "payload['boltz_runtime'] = boltz_runtime_preview()",
        "payload['source_fasta_inputs'] = source_fasta_preview()",
        "if receipt_path:",
        "    path = pathlib.Path(receipt_path)",
        "    exists = path.exists()",
        "    size_bytes = path.stat().st_size if exists else 0",
        "    nonempty = exists and size_bytes > 0",
        "    payload['receipt'] = {",
        "        'path': receipt_path,",
        "        'exists': exists,",
        "        'size_bytes': size_bytes,",
        "        'nonempty': nonempty,",
        "        'overwrite_requested': overwrite,",
        "        'will_block_real_submit': nonempty and not overwrite,",
        "        'preview': receipt_preview(path) if nonempty else None,",
        "    }",
        "else:",
        "    payload['receipt'] = {",
        "        'path': None,",
        "        'exists': False,",
        "        'size_bytes': 0,",
        "        'nonempty': False,",
        "        'overwrite_requested': overwrite,",
        "        'will_block_real_submit': False,",
        "        'preview': None,",
        "    }",
        "print(json.dumps(payload, indent=2, sort_keys=True))",
        "PY",
        "  exit 0",
        "fi",
        "",
        f"TARGET_MSA_PRECOMPUTE_HELPER_FILES={shlex.quote(json.dumps(required_helper_files, sort_keys=True))}",
        "export TARGET_MSA_PRECOMPUTE_HELPER_FILES",
        "verify_target_msa_helper_files() {",
        "  python - <<'PY'",
        "import hashlib, json, os, pathlib, sys",
        "helpers = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_HELPER_FILES') or '[]')",
        "def sha256_file(path):",
        "    h = hashlib.sha256()",
        "    with open(path, 'rb') as fh:",
        "        for chunk in iter(lambda: fh.read(1024 * 1024), b''):",
        "            h.update(chunk)",
        "    return h.hexdigest()",
        "bad = []",
        "for item in helpers:",
        "    if not isinstance(item, dict):",
        "        bad.append({'error': 'helper_file_record_not_object', 'record': item})",
        "        continue",
        "    path_text = str(item.get('path') or '')",
        "    expected_sha = item.get('sha256')",
        "    if not path_text:",
        "        bad.append({'error': 'missing_helper_file_path'})",
        "        continue",
        "    path = pathlib.Path(path_text)",
        "    if not path.exists():",
        "        bad.append({'path': path_text, 'error': 'missing_helper_file'})",
        "        continue",
        "    if not path.is_file():",
        "        bad.append({'path': path_text, 'error': 'helper_path_not_file'})",
        "        continue",
        "    if path.stat().st_size <= 0:",
        "        bad.append({'path': path_text, 'error': 'empty_helper_file'})",
        "        continue",
        "    actual_sha = sha256_file(path)",
        "    if expected_sha and str(expected_sha) != actual_sha:",
        "        bad.append({",
        "            'path': path_text,",
        "            'expected_sha256': expected_sha,",
        "            'actual_sha256': actual_sha,",
        "            'error': 'helper_file_sha256_mismatch',",
        "        })",
        "if bad:",
        "    print('target-MSA precompute helper file preflight failed before receipt initialization:', file=sys.stderr)",
        "    print(json.dumps({'ok': False, 'failures': bad}, indent=2, sort_keys=True), file=sys.stderr)",
        "    raise SystemExit(2)",
        "print(json.dumps({'ok': True, 'n_helper_files': len(helpers)}, sort_keys=True))",
        "PY",
        "}",
        "verify_target_msa_helper_files",
        "",
        f"TARGET_MSA_PRECOMPUTE_SOURCE_INPUTS={shlex.quote(json.dumps(dry_run_payload['source_fasta_inputs'], sort_keys=True))}",
        "export TARGET_MSA_PRECOMPUTE_SOURCE_INPUTS",
        "verify_target_msa_source_fastas() {",
        "  python - <<'PY'",
        "import json, os, pathlib, sys",
        "inputs = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_SOURCE_INPUTS') or '[]')",
        "def path_nonempty(path_text):",
        "    if not path_text:",
        "        return False",
        "    path = pathlib.Path(path_text)",
        "    return path.exists() and path.is_file() and path.stat().st_size > 0",
        "bad = []",
        "present = 0",
        "regenerable = 0",
        "for item in inputs:",
        "    if not isinstance(item, dict):",
        "        bad.append({'error': 'source_input_record_not_object', 'record': item})",
        "        continue",
        "    target_id = str(item.get('target_id') or '')",
        "    path_text = str(item.get('target_fasta') or '')",
        "    if not path_text:",
        "        bad.append({'target_id': target_id, 'error': 'missing_target_fasta_path'})",
        "        continue",
        "    if path_nonempty(path_text):",
        "        present += 1",
        "        continue",
        "    prepared_pdb = str(item.get('prepared_pdb') or '')",
        "    source_pdb = str(item.get('source_pdb') or '')",
        "    has_target_chain = bool(str(item.get('target_chain') or '').strip())",
        "    has_binder_chain = bool(str(item.get('binder_chain') or '').strip())",
        "    has_rcsb_id = bool(str(item.get('rcsb_id') or '').strip())",
        "    can_extract_from_prepared = path_nonempty(prepared_pdb) and has_target_chain",
        "    can_prepare_from_source = path_nonempty(source_pdb) and bool(prepared_pdb) and has_target_chain and has_binder_chain",
        "    can_fetch_prepare = has_rcsb_id and bool(source_pdb) and bool(prepared_pdb) and has_target_chain and has_binder_chain",
        "    if can_extract_from_prepared or can_prepare_from_source or can_fetch_prepare:",
        "        regenerable += 1",
        "        continue",
        "    bad.append({",
        "        'target_id': target_id,",
        "        'target_fasta': path_text,",
        "        'prepared_pdb': prepared_pdb,",
        "        'source_pdb': source_pdb,",
        "        'rcsb_id': str(item.get('rcsb_id') or ''),",
        "        'error': 'target_fasta_missing_and_no_regeneration_source',",
        "    })",
        "if bad:",
        "    print('target-MSA precompute source FASTA preflight failed before receipt initialization:', file=sys.stderr)",
        "    print(json.dumps({'ok': False, 'failures': bad}, indent=2, sort_keys=True), file=sys.stderr)",
        "    raise SystemExit(2)",
        "print(json.dumps({'ok': True, 'n_source_fastas': len(inputs), 'n_present': present, 'n_regenerable': regenerable}, sort_keys=True))",
        "PY",
        "}",
        "verify_target_msa_source_fastas",
        "",
        f"TARGET_MSA_PRECOMPUTE_RUNTIME_INPUTS={shlex.quote(json.dumps(dry_run_payload['boltz_runtime'], sort_keys=True))}",
        "export TARGET_MSA_PRECOMPUTE_RUNTIME_INPUTS",
        "verify_target_msa_boltz_runtime() {",
        "  python - <<'PY'",
        "import json, os, pathlib, sys",
        "spec = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_RUNTIME_INPUTS') or '{}')",
        "def path_nonempty(path_text):",
        "    if not path_text:",
        "        return False",
        "    path = pathlib.Path(path_text)",
        "    return path.exists() and path.is_file() and path.stat().st_size > 0",
        "outputs = []",
        "for item in spec.get('target_msa_outputs') or []:",
        "    if not isinstance(item, dict):",
        "        continue",
        "    target_id = str(item.get('target_id') or '')",
        "    target_msa = str(item.get('target_msa') or '')",
        "    outputs.append({'target_id': target_id, 'target_msa': target_msa, 'present_nonempty': path_nonempty(target_msa)})",
        "missing_outputs = [item for item in outputs if not item['present_nonempty']]",
        "if not missing_outputs:",
        "    print(json.dumps({'ok': True, 'runtime_required': False, 'n_target_msa_outputs': len(outputs)}, sort_keys=True))",
        "    raise SystemExit(0)",
        "env_py = os.environ.get('ENV_PY') or os.path.expandvars(str(spec.get('env_py_default') or ''))",
        "boltz = os.environ.get('BOLTZ') or os.path.expandvars(str(spec.get('boltz_default') or ''))",
        "bad = []",
        "for label, path_text in [('ENV_PY', env_py), ('BOLTZ', boltz)]:",
        "    if not path_text:",
        "        bad.append({'label': label, 'error': 'missing_runtime_path'})",
        "        continue",
        "    path = pathlib.Path(path_text)",
        "    if not path.exists():",
        "        bad.append({'label': label, 'path': path_text, 'error': 'missing_runtime_path'})",
        "        continue",
        "    if not path.is_file():",
        "        bad.append({'label': label, 'path': path_text, 'error': 'runtime_path_not_file'})",
        "        continue",
        "    if path.stat().st_size <= 0:",
        "        bad.append({'label': label, 'path': path_text, 'error': 'empty_runtime_file'})",
        "        continue",
        "    if not os.access(path_text, os.X_OK):",
        "        bad.append({'label': label, 'path': path_text, 'error': 'runtime_path_not_executable'})",
        "if bad:",
        "    print('target-MSA precompute Boltz runtime preflight failed before receipt initialization:', file=sys.stderr)",
        "    print(json.dumps({",
        "        'ok': False,",
        "        'runtime_required': True,",
        "        'missing_target_msa_outputs': missing_outputs,",
        "        'failures': bad,",
        "    }, indent=2, sort_keys=True), file=sys.stderr)",
        "    raise SystemExit(2)",
        "print(json.dumps({",
        "    'ok': True,",
        "    'runtime_required': True,",
        "    'n_missing_target_msa_outputs': len(missing_outputs),",
        "    'env_py': env_py,",
        "    'boltz': boltz,",
        "}, sort_keys=True))",
        "PY",
        "}",
        "verify_target_msa_boltz_runtime",
        "",
    ])
    if receipt_path:
        lines.extend([
            "mkdir -p \"$(dirname \"$TARGET_MSA_PRECOMPUTE_RECEIPT\")\"",
            "if [ -s \"$TARGET_MSA_PRECOMPUTE_RECEIPT\" ] && [ \"${TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT:-0}\" != \"1\" ]; then",
            "  echo \"target-MSA precompute receipt already exists and is non-empty: $TARGET_MSA_PRECOMPUTE_RECEIPT\" >&2",
            "  echo \"Run project status or remote-check to inspect it before resubmitting.\" >&2",
            "  echo \"Set TARGET_MSA_PRECOMPUTE_OVERWRITE_RECEIPT=1 only after confirming recorded jobs will not be duplicated.\" >&2",
            "  exit 2",
            "fi",
            ": > \"$TARGET_MSA_PRECOMPUTE_RECEIPT\"",
            "echo \"target-MSA precompute receipt: $TARGET_MSA_PRECOMPUTE_RECEIPT\"",
            "",
        ])
    wrote_section = False
    for section in summary.get("sections") or []:
        if not isinstance(section, dict):
            continue
        target_ids = section.get("selected_target_ids") or []
        manifest = section.get("manifest")
        if not target_ids or not manifest:
            continue
        lines.extend([
            f"# --- {section.get('workstream')} target_msa_precompute ---",
            f"TARGET_MSA_PRECOMPUTE_WORKSTREAM={shlex.quote(str(section.get('workstream') or ''))}",
            "export TARGET_MSA_PRECOMPUTE_WORKSTREAM",
            f"TARGET_MSA_PRECOMPUTE_MANIFEST={shlex.quote(str(manifest))}",
            "export TARGET_MSA_PRECOMPUTE_MANIFEST",
            f"TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED={shlex.quote(str(section.get('manifest_sha256') or ''))}",
            "export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED",
            "TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256=\"$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED\"",
            "export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256",
            render_target_msa_plan(
                manifest,
                target_ids=target_ids,
                workstream=str(section.get("workstream") or ""),
            ).rstrip(),
            "",
        ])
        wrote_section = True
    if wrote_section and summary.get("target_ids"):
        quoted_expected = " ".join(shlex.quote(str(target_id)) for target_id in summary.get("target_ids") or [])
        expected_json = json.dumps(
            summary.get("expected_receipt_targets") or {},
            sort_keys=True,
            separators=(",", ":"),
        )
        lines.extend([
            "# validate_project_target_msa_precompute_receipt",
            "if [ -n \"${TARGET_MSA_PRECOMPUTE_RECEIPT:-}\" ]; then",
            "  TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET=1 "
            f"validate_target_msa_precompute_receipt --expect-json {shlex.quote(expected_json)} {quoted_expected}",
            "fi",
            "",
        ])
    if not wrote_section:
        lines.extend([
            "# No W1/W2 target-MSA targets matched the supplied raw manifests.",
            "# Inspect target_msa_precompute_plan.missing_from_manifest in project status.",
            "",
        ])
    scale_readiness = _readiness_followup(args.scale_readiness_report)
    panel_readiness = _readiness_followup(args.panel_readiness_report)
    rerun_commands = []
    for readiness in (scale_readiness, panel_readiness):
        if isinstance(readiness, dict) and readiness.get("self_command"):
            rerun_commands.append(readiness["self_command"])
    if rerun_commands:
        lines.append("# rerun_readiness_after_target_msa_precompute")
        for command in rerun_commands:
            lines.append(f"# {command}")
        lines.append("")
    if args.emit_external_remote_check_plan:
        lines.extend([
            "# rerun_remote_check_after_target_msa_precompute",
            f"# bash {args.emit_external_remote_check_plan}",
            "",
        ])
    return "\n".join(lines)


def attach_external_remote_check_report(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    report_path = args.external_remote_check_report or _remote_check_report_path(args.emit_external_remote_check_plan)
    if not report_path:
        return rep
    manifest = rep.get("pending_external_manifest")
    expected_n = manifest.get("n_paths") if isinstance(manifest, dict) else None
    expected_sha = manifest.get("sha256") if isinstance(manifest, dict) else None
    expected_paths = manifest.get("paths") if isinstance(manifest, dict) else None
    expected_manifest_provenance = _path_manifest_provenance(manifest)
    summary: Dict[str, Any] = {
        "path": report_path,
        "exists": os.path.exists(report_path),
        "expected_n_paths": expected_n,
        "expected_sha256": expected_sha,
        "fresh": False,
        "ready_for_external_sync": False,
    }
    if not summary["exists"]:
        summary.update({
            "status": "missing_report",
            "ok": False,
            "next_action": "run the external remote-check bridge before external sync-back",
        })
        rep["external_remote_check_report"] = summary
        return rep
    try:
        with open(report_path) as fh:
            report = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        summary.update({
            "status": "invalid_report",
            "ok": False,
            "error": str(exc),
            "next_action": "regenerate the external remote-check report",
        })
        rep["external_remote_check_report"] = summary
        return rep
    if not isinstance(report, dict):
        summary.update({
            "status": "invalid_report",
            "ok": False,
            "error": "report is not a JSON object",
            "next_action": "regenerate the external remote-check report",
        })
        rep["external_remote_check_report"] = summary
        return rep

    report_n = report.get("n_paths")
    report_sha = report.get("path_file_sha256")
    fresh = (
        expected_n is not None
        and expected_sha
        and report_n == expected_n
        and report_sha == expected_sha
    )
    ok = report.get("ok") is True
    consistency_failures = []
    if fresh and ok:
        report_manifest = report.get("path_manifest")
        if expected_manifest_provenance:
            if not isinstance(report_manifest, dict):
                consistency_failures.append({
                    "field": "path_manifest",
                    "expected": "object",
                    "actual": type(report_manifest).__name__,
                })
            else:
                for key, expected_value in expected_manifest_provenance.items():
                    actual_value = report_manifest.get(key)
                    if actual_value != expected_value:
                        consistency_failures.append({
                            "field": f"path_manifest.{key}",
                            "expected": expected_value,
                            "actual": actual_value,
                        })
        if report.get("status") != "all_present_nonempty":
            consistency_failures.append({
                "field": "status",
                "expected": "all_present_nonempty",
                "actual": report.get("status"),
            })
        if report.get("n_present") != expected_n:
            consistency_failures.append({
                "field": "n_present",
                "expected": expected_n,
                "actual": report.get("n_present"),
            })
        if report.get("n_missing") != 0:
            consistency_failures.append({
                "field": "n_missing",
                "expected": 0,
                "actual": report.get("n_missing"),
            })
        if report.get("n_not_checked") != 0:
            consistency_failures.append({
                "field": "n_not_checked",
                "expected": 0,
                "actual": report.get("n_not_checked"),
            })
        path_records = report.get("paths")
        if not isinstance(path_records, list):
            consistency_failures.append({
                "field": "paths",
                "expected": "list",
                "actual": type(path_records).__name__,
            })
        else:
            record_paths = []
            bad_paths = []
            for index, item in enumerate(path_records):
                if not isinstance(item, dict):
                    bad_paths.append({
                        "index": index,
                        "error": "path_record_not_object",
                        "actual": type(item).__name__,
                    })
                    continue
                path = str(item.get("path", ""))
                record_paths.append(path)
                if item.get("status") != "present_nonempty" or item.get("present_nonempty") is not True:
                    bad_paths.append({
                        "index": index,
                        "path": path,
                        "status": item.get("status"),
                        "present_nonempty": item.get("present_nonempty"),
                        "error": "path_not_present_nonempty",
                    })
            if isinstance(expected_paths, list) and record_paths != expected_paths:
                consistency_failures.append({
                    "field": "paths",
                    "expected": expected_paths,
                    "actual": record_paths,
                })
            if bad_paths:
                consistency_failures.append({
                    "field": "paths",
                    "error": "bad_path_records",
                    "bad_records": bad_paths,
                })
    remote_artifacts_ready = bool(fresh and ok and not consistency_failures)
    target_msa_plan = rep.get("target_msa_precompute_plan")
    target_msa_receipt = rep.get("target_msa_precompute_receipt")
    target_msa_receipt_required = (
        isinstance(target_msa_plan, dict)
        and bool(target_msa_plan.get("n_targets"))
        and not _target_msa_outputs_satisfied(target_msa_plan)
    )
    target_msa_receipt_ok = (
        isinstance(target_msa_receipt, dict)
        and target_msa_receipt.get("ok") is True
    )
    target_msa_receipt_sha256 = (
        target_msa_receipt.get("sha256")
        if target_msa_receipt_ok and isinstance(target_msa_receipt.get("sha256"), str)
        else None
    )
    target_msa_receipt_size_bytes = (
        target_msa_receipt.get("size_bytes")
        if target_msa_receipt_ok and isinstance(target_msa_receipt.get("size_bytes"), int)
        else None
    )
    receipt_sync = report.get("target_msa_precompute_receipt_sync")
    receipt_sync_requested = (
        isinstance(receipt_sync, dict)
        and receipt_sync.get("requested") is True
    )
    receipt_sync_status = receipt_sync.get("status") if isinstance(receipt_sync, dict) else None
    receipt_sync_sha256 = receipt_sync.get("sha256") if isinstance(receipt_sync, dict) else None
    receipt_sync_size_bytes = receipt_sync.get("size_bytes") if isinstance(receipt_sync, dict) else None
    receipt_sync_has_digest = (
        isinstance(receipt_sync_sha256, str)
        and len(receipt_sync_sha256) == 64
        and all(ch in "0123456789abcdef" for ch in receipt_sync_sha256.lower())
        and isinstance(receipt_sync_size_bytes, int)
        and receipt_sync_size_bytes > 0
    )
    receipt_sync_synced = (
        receipt_sync_requested
        and receipt_sync.get("status") == "synced"
        and receipt_sync.get("synced") is True
        and receipt_sync_has_digest
    )
    receipt_sync_matches_local = (
        receipt_sync_synced
        and target_msa_receipt_ok
        and receipt_sync_sha256 == target_msa_receipt_sha256
        and receipt_sync_size_bytes == target_msa_receipt_size_bytes
    )
    receipt_sync_missing = (
        remote_artifacts_ready
        and target_msa_receipt_required
        and not receipt_sync_requested
    )
    receipt_sync_failed = (
        remote_artifacts_ready
        and target_msa_receipt_required
        and receipt_sync_requested
        and not receipt_sync_synced
    )
    receipt_sync_mismatch = (
        remote_artifacts_ready
        and target_msa_receipt_required
        and target_msa_receipt_ok
        and receipt_sync_synced
        and not receipt_sync_matches_local
    )
    receipt_blocks_external_sync = (
        remote_artifacts_ready
        and target_msa_receipt_required
        and (
            not target_msa_receipt_ok
            or receipt_sync_missing
            or receipt_sync_failed
            or receipt_sync_mismatch
        )
    )
    if fresh and ok and consistency_failures:
        status = "inconsistent_report"
        next_action = "regenerate the external remote-check report"
    elif receipt_sync_missing:
        status = "target_msa_receipt_sync_missing"
        next_action = (
            "rerun the external remote-check bridge so it attempts to sync the target-MSA precompute receipt"
        )
    elif receipt_sync_failed:
        status = "target_msa_receipt_sync_failed"
        next_action = (
            "inspect or repair the target-MSA precompute receipt on Cayuga, then rerun the external remote-check bridge"
        )
    elif receipt_sync_mismatch:
        status = "target_msa_receipt_sync_mismatch"
        next_action = (
            "rerun the external remote-check bridge so the synced target-MSA receipt digest matches the current local receipt"
        )
    elif receipt_blocks_external_sync:
        status = "target_msa_receipt_incomplete"
        next_action = (
            target_msa_receipt.get("next_action")
            if isinstance(target_msa_receipt, dict)
            else "run or repair the target-MSA precompute bridge before external sync-back"
        )
    elif remote_artifacts_ready:
        status = "ready_for_external_sync"
        next_action = "run the external sync-back bridge"
    elif fresh:
        status = "missing_remote_artifacts"
        next_action = "rerun the remote-check bridge after the corresponding Cayuga jobs finish"
    else:
        status = "stale_report"
        next_action = "rerun the remote-check bridge for the current pending external checklist"
    followups = _remote_missing_followups(rep, report, args=args) if fresh and not ok else []
    if status == "missing_remote_artifacts" and followups:
        next_action = followups[0].get("next_action", next_action)

    summary.update({
        "status": status,
        "ok": ok,
        "fresh": bool(fresh),
        "consistency_failures": consistency_failures,
        "remote_artifacts_ready": remote_artifacts_ready,
        "target_msa_receipt_required": target_msa_receipt_required,
        "target_msa_receipt_ok": target_msa_receipt_ok,
        "target_msa_receipt_local_sha256": target_msa_receipt_sha256,
        "target_msa_receipt_local_size_bytes": target_msa_receipt_size_bytes,
        "target_msa_receipt_sync_requested": receipt_sync_requested,
        "target_msa_receipt_sync_status": receipt_sync_status,
        "target_msa_receipt_sync_synced": receipt_sync_synced,
        "target_msa_receipt_sync_has_digest": receipt_sync_has_digest,
        "target_msa_receipt_sync_matches_local": receipt_sync_matches_local,
        "target_msa_receipt_sync_mismatch": receipt_sync_mismatch,
        "target_msa_receipt_sync_sha256": receipt_sync_sha256,
        "target_msa_receipt_sync_size_bytes": receipt_sync_size_bytes,
        "target_msa_receipt_sync_failed": receipt_sync_failed,
        "ready_for_external_sync": bool(remote_artifacts_ready and not receipt_blocks_external_sync),
        "report_n_paths": report_n,
        "report_sha256": report_sha,
        "path_manifest": report.get("path_manifest"),
        "n_present": report.get("n_present"),
        "n_missing": report.get("n_missing"),
        "n_not_checked": report.get("n_not_checked"),
        "n_metadata_paths": report.get("n_metadata_paths"),
        "missing_by_workstream": report.get("missing_by_workstream"),
        "missing_by_category": report.get("missing_by_category"),
        "missing_by_target_id": report.get("missing_by_target_id"),
        "missing_by_artifact": report.get("missing_by_artifact"),
        "target_msa_precompute_receipt_sync": report.get("target_msa_precompute_receipt_sync"),
        "remote_missing_followups": followups,
        "remote_root": report.get("remote_root"),
        "remote_host": report.get("remote_host"),
        "remote_dir": report.get("remote_dir"),
        "next_action": next_action,
    })
    rep["external_remote_check_report"] = summary
    return rep


def _append_script_hint(scripts, *, role: str, path: Optional[str],
                        label: str, reason: str,
                        recommended: bool = False,
                        manifest: Optional[Dict[str, Any]] = None,
                        report: Optional[str] = None,
                        receipt: Optional[str] = None,
                        dry_run_command: Optional[str] = None,
                        blockers: Optional[list] = None) -> None:
    if not path:
        return
    entry = {
        "role": role,
        "path": path,
        "command": f"bash {path}",
        "label": label,
        "reason": reason,
        "recommended": bool(recommended),
    }
    if manifest:
        entry["manifest"] = manifest
    if report:
        entry["report"] = report
    if receipt:
        entry["receipt"] = receipt
    if dry_run_command:
        entry["dry_run_command"] = dry_run_command
    if blockers:
        entry["blockers"] = blockers
        entry["blocked"] = True
    scripts.append(entry)


def attach_script_hints(rep: Dict[str, Any], *, args) -> Dict[str, Any]:
    scripts = []
    has_external_pending = bool(rep.get("n_pending_external_artifacts"))
    has_input_pending = bool(rep.get("n_pending_input_prep_paths"))
    remote_check_ready = (
        rep.get("external_remote_check_report", {}).get("ready_for_external_sync") is True
    )
    target_msa_plan = rep.get("target_msa_precompute_plan")
    target_msa_receipt = rep.get("target_msa_precompute_receipt")
    remote_report = (
        rep.get("external_remote_check_report")
        if isinstance(rep.get("external_remote_check_report"), dict)
        else {}
    )
    target_msa_receipt_ok = (
        isinstance(target_msa_receipt, dict)
        and target_msa_receipt.get("ok") is True
    )
    target_msa_plan_conflicts = (
        isinstance(target_msa_plan, dict)
        and bool(target_msa_plan.get("conflicting_duplicate_target_ids"))
    )
    target_msa_outputs_satisfied = _target_msa_outputs_satisfied(target_msa_plan)
    rep["target_msa_precompute_outputs_satisfied"] = target_msa_outputs_satisfied
    target_msa_receipt_review_required = (
        _target_msa_receipt_requires_review(target_msa_receipt)
        and not target_msa_outputs_satisfied
    )
    has_target_msa_precompute = (
        isinstance(target_msa_plan, dict)
        and bool(target_msa_plan.get("n_targets"))
        and bool(target_msa_plan.get("path"))
    )
    target_msa_first = (
        has_external_pending
        and has_target_msa_precompute
        and not target_msa_receipt_ok
        and not target_msa_outputs_satisfied
        and not remote_check_ready
        and remote_report.get("status") != "target_msa_receipt_sync_missing"
    )
    has_external_remote_check = (
        has_external_pending
        and bool(args.emit_external_remote_check_plan)
        and not remote_check_ready
        and not target_msa_first
    )
    _append_script_hint(
        scripts,
        role="external_remote_check",
        path=args.emit_external_remote_check_plan,
        label="Check that W1-W4 pending external artifacts exist on Cayuga before sync-back",
        reason="pending_external_artifacts is nonzero",
        recommended=has_external_remote_check,
        manifest=_project_manifest_hint(rep.get("pending_external_manifest")),
        report=_remote_check_report_path(args.emit_external_remote_check_plan),
    )
    _append_script_hint(
        scripts,
        role="external_sync_back",
        path=args.emit_external_sync_back_plan,
        label="Pull all W1-W4 pending external artifacts and replay dependent checks",
        reason="pending_external_artifacts is nonzero",
        recommended=has_external_pending and (
            remote_check_ready or (not has_external_remote_check and not target_msa_first)
        ),
        manifest=_project_manifest_hint(rep.get("pending_external_manifest")),
    )
    _append_script_hint(
        scripts,
        role="input_prep_sync_back",
        path=args.emit_sync_back_plan,
        label="Pull W1/W2 input-prep artifacts and rerun local readiness/status",
        reason="pending_input_prep_paths is nonzero",
        recommended=(has_input_pending and not has_external_pending),
        manifest=_project_manifest_hint(rep.get("pending_input_prep_manifest")),
    )
    if isinstance(target_msa_plan, dict) and target_msa_plan.get("n_targets"):
        target_msa_blockers = []
        if target_msa_plan_conflicts:
            target_msa_blockers.append("target_msa_plan_conflicts")
        if target_msa_receipt_review_required:
            target_msa_blockers.append(_TARGET_MSA_RECEIPT_REVIEW_BLOCKER)
        _append_script_hint(
            scripts,
            role="target_msa_precompute",
            path=target_msa_plan.get("path"),
            label="Precompute W1/W2 target MSAs once before remote-check",
            reason=(
                "W1/W2 target-MSA plan has conflicting duplicate target ids"
                if target_msa_plan_conflicts
                else "existing non-empty target-MSA receipt requires review before resubmission"
                if target_msa_receipt_review_required
                else f"{target_msa_plan.get('n_targets')} W1/W2 target-MSA target(s) are repairable"
            ),
            recommended=target_msa_first,
            receipt=target_msa_plan.get("receipt_path"),
            dry_run_command=target_msa_plan.get("dry_run_command"),
            blockers=target_msa_blockers or None,
        )
    w3 = rep.get("workstreams", {}).get("W3_independent_predictor", {})
    _append_script_hint(
        scripts,
        role="second_predictor_sync_back",
        path=w3.get("sync_back_plan"),
        label="Pull second-predictor records and rerun W3 contract/cross-predictor checks",
        reason=f"W3 status is {w3.get('status')}",
        manifest=_sidecar_manifest_hint(w3.get("sync_back_plan")),
    )
    w4 = rep.get("workstreams", {}).get("W4_closed_loop_DBTL", {})
    _append_script_hint(
        scripts,
        role="closed_loop_batch_sync_back",
        path=w4.get("sync_back_plan"),
        label="Pull W4 batch JSONLs and rerun closed-loop DBTL routing",
        reason=f"W4 status is {w4.get('status')}",
        manifest=_sidecar_manifest_hint(w4.get("sync_back_plan")),
    )
    post_sync_manifest = _post_sync_replay_manifest(rep, args=args)
    if post_sync_manifest is not None:
        rep["post_sync_replay_manifest"] = post_sync_manifest
    _append_script_hint(
        scripts,
        role="post_sync_replay",
        path=args.emit_post_sync_plan,
        label="Refresh completion, readiness, and project status after sync-back",
        reason="post-sync replay requested",
        manifest=post_sync_manifest,
    )
    if scripts:
        rep["generated_scripts"] = scripts
        recommended = next((script for script in scripts if script.get("recommended")), None)
        if recommended is not None:
            rep["recommended_next_script"] = recommended
    return rep


def _w4_gate_prevalidation_block(batch_preflight: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    gate_prevalidation = batch_preflight.get("gate_prevalidation")
    if not isinstance(gate_prevalidation, dict) or not gate_prevalidation.get("requested"):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_gate_prevalidation_missing",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "message": "complex/binder W4 requires prior gate prevalidation evidence",
            "next_action": "rerun run_batch_round.py with --prevalidate-records and --conformal-alpha",
            "evidence": batch_preflight.get("_path"),
        }
    if gate_prevalidation.get("ok") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_gate_prevalidation_blocked",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "failures": gate_prevalidation.get("failures", []),
            "next_action": "fix prior prevalidation records before W4 routing",
            "evidence": batch_preflight.get("_path"),
        }
    if gate_prevalidation.get("conformal_alpha") is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_gate_not_conformal",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "message": "W4 gate prevalidation must state a conformal false-accept target",
            "next_action": "rerun run_batch_round.py with --conformal-alpha",
            "evidence": batch_preflight.get("_path"),
        }
    regimes = gate_prevalidation.get("regimes")
    complex_regime = regimes.get("complex") if isinstance(regimes, dict) else None
    if not isinstance(complex_regime, dict) or complex_regime.get("validated") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_complex_gate_unvalidated",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "message": "complex regime was not validated for W4 trust routing",
            "next_action": "prevalidate the complex regime with prior verified records before W4 routing",
            "evidence": batch_preflight.get("_path"),
        }
    if complex_regime.get("tau") is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_complex_gate_tau_missing",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "message": "complex conformal prevalidation must record the certified trust threshold tau",
            "next_action": "regenerate preflight.json with the current run_batch_round.py",
            "evidence": batch_preflight.get("_path"),
        }
    batch_contract = gate_prevalidation.get("batch_contract")
    if not isinstance(batch_contract, dict) or batch_contract.get("checked") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_gate_contract_missing",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "message": "W4 gate prevalidation must prove its predictor/source/label contract matches the current batch",
            "next_action": "regenerate preflight.json with the current run_batch_round.py after synced batch records are available",
            "evidence": batch_preflight.get("_path"),
        }
    if batch_contract.get("ok") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_gate_contract_blocked",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "batch_contract": batch_contract,
            "failures": batch_contract.get("failures", []),
            "next_action": "fix predictor/source/label-threshold mismatch before W4 routing",
            "evidence": batch_preflight.get("_path"),
        }
    contract_regimes = batch_contract.get("regimes")
    complex_contract = contract_regimes.get("complex") if isinstance(contract_regimes, dict) else None
    if not isinstance(complex_contract, dict) or complex_contract.get("ok") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_complex_gate_contract_unvalidated",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "batch_contract": batch_contract,
            "message": "complex regime lacks a compatible prevalidation/current-batch measurement contract",
            "next_action": "rerun W4 preflight with current run_batch_round.py and matching prior/current records",
            "evidence": batch_preflight.get("_path"),
        }
    return None


def _w4_summary_gate_block(batch_summary: Dict[str, Any],
                           gate_prevalidation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if batch_summary.get("gate_calibrated") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_not_gate_calibrated",
            "complete": False,
            "message": "summary.json does not prove the DBTL round routed with a calibrated gate",
            "next_action": "rerun run_batch_round.py with prior --prevalidate-records so summary.json records gate_calibrated=true",
            "evidence": batch_summary.get("_path"),
        }
    summary_gate = batch_summary.get("gate_prevalidation")
    if not isinstance(summary_gate, dict):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_missing_gate_prevalidation",
            "complete": False,
            "message": "summary.json is missing the gate_prevalidation metadata from preflight",
            "next_action": "regenerate summary.json with the current run_batch_round.py",
            "evidence": batch_summary.get("_path"),
        }
    if summary_gate.get("conformal_alpha") != gate_prevalidation.get("conformal_alpha"):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_gate_mismatch",
            "complete": False,
            "message": "summary and preflight disagree on conformal_alpha",
            "next_action": "regenerate preflight.json and summary.json from the same batch run",
            "evidence": batch_summary.get("_path"),
        }
    if summary_gate.get("batch_contract") != gate_prevalidation.get("batch_contract"):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_gate_contract_mismatch",
            "complete": False,
            "message": "summary and preflight disagree on gate_prevalidation.batch_contract",
            "next_action": "regenerate preflight.json and summary.json from the same batch run",
            "evidence": batch_summary.get("_path"),
        }
    summary_block = _w4_gate_prevalidation_block({"gate_prevalidation": summary_gate})
    if summary_block is not None:
        summary_block.update({
            "status": "batch_summary_gate_prevalidation_invalid",
            "message": "summary.json contains incomplete gate_prevalidation metadata",
            "next_action": "regenerate summary.json with the current run_batch_round.py",
            "evidence": batch_summary.get("_path"),
        })
        return summary_block
    return None


def _w4_status(batch_preflight: Optional[Dict[str, Any]],
               batch_summary: Optional[Dict[str, Any]],
               batch_campaign_path: Optional[str]) -> Dict[str, Any]:
    if _is_missing_artifact(batch_summary):
        batch_summary = None
    if _is_missing_artifact(batch_preflight) and batch_summary is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_preflight_missing",
            "complete": False,
            "message": batch_preflight.get("message", ""),
            "next_action": "run run_batch_round.py --strict-complex-records to write preflight.json before W4 status claims",
            "evidence": batch_preflight.get("_path"),
        }
    if batch_preflight is None and batch_summary is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "missing",
            "complete": False,
            "message": "No batch preflight or DBTL summary artifact provided.",
            "next_action": "run run_batch_round.py --strict-complex-records after synchronized candidates/records/verdicts exist",
        }
    if batch_preflight is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "summary_without_preflight",
            "complete": False,
            "summary": batch_summary.get("_path") if isinstance(batch_summary, dict) else None,
            "message": "DBTL summary exists but no preflight artifact proves synchronized inputs.",
            "next_action": "rerun run_batch_round.py so preflight.json and summary.json are regenerated together",
        }

    failures = batch_preflight.get("failures", [])
    if not batch_preflight.get("ok"):
        failure_kinds = {f.get("kind") for f in failures if isinstance(f, dict)}
        if failure_kinds == {"gate_prevalidation_blocked"}:
            gate_block = _w4_gate_prevalidation_block(batch_preflight)
            if gate_block is not None:
                gate_block["preflight_failures"] = failures
                return gate_block
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_preflight_blocked",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "failures": failures,
            "pending_artifacts": batch_preflight.get("pending_artifacts", []),
            "next_action": "fix batch preflight failures before closed-loop DBTL routing",
            "evidence": batch_preflight.get("_path"),
        }
    if batch_preflight.get("strict_complex_records") is not True:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_preflight_not_strict",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "message": "complex/binder W4 requires run_batch_round.py --strict-complex-records",
            "next_action": "rerun run_batch_round.py with --strict-complex-records before treating this as W4 evidence",
            "evidence": batch_preflight.get("_path"),
        }
    gate_block = _w4_gate_prevalidation_block(batch_preflight)
    if gate_block is not None:
        return gate_block
    gate_prevalidation = batch_preflight["gate_prevalidation"]
    if batch_summary is None:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_preflight_ready",
            "complete": False,
            "n_candidates": batch_preflight.get("n_candidates"),
            "gate_prevalidation": gate_prevalidation,
            "next_action": "run or rerun run_batch_round.py to write campaign.jsonl and summary.json",
            "evidence": batch_preflight.get("_path"),
        }

    aggregate = batch_summary.get("aggregate")
    if not isinstance(aggregate, dict):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_invalid",
            "complete": False,
            "message": "summary.json is missing aggregate route/verify/net metrics",
            "next_action": "rerun run_batch_round.py and inspect summary.json",
            "evidence": batch_summary.get("_path"),
        }
    n_routed = aggregate.get("n")
    if not isinstance(n_routed, int) or n_routed <= 0:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_empty",
            "complete": False,
            "message": "summary aggregate has no routed candidates",
            "next_action": "inspect candidate/prediction inputs and rerun run_batch_round.py",
            "evidence": batch_summary.get("_path"),
        }
    summary_gate_block = _w4_summary_gate_block(batch_summary, gate_prevalidation)
    if summary_gate_block is not None:
        return summary_gate_block
    expected = batch_preflight.get("n_candidates")
    if isinstance(expected, int) and n_routed != expected:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_mismatch",
            "complete": False,
            "n_candidates": expected,
            "n_routed": n_routed,
            "message": "summary routed-candidate count differs from preflight candidate count",
            "next_action": "regenerate preflight and summary from the same synchronized artifacts",
            "evidence": batch_summary.get("_path"),
        }
    per_round_mismatches = _summary_per_round_count_mismatches(batch_summary, n_routed)
    if per_round_mismatches:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "batch_summary_per_round_mismatch",
            "complete": False,
            "n_routed": n_routed,
            "per_round_mismatches": per_round_mismatches,
            "message": "summary per_round counts differ from aggregate routed-candidate count",
            "next_action": "regenerate summary.json from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    campaign_path = batch_campaign_path or _default_campaign_path(batch_summary)
    try:
        campaign_audit = _campaign_jsonl_audit(campaign_path)
    except (OSError, json.JSONDecodeError, ValueError):
        campaign_audit = {
            "record_count": 0,
            "candidate_ids": [],
            "missing_candidate_id_lines": [],
            "duplicate_candidate_ids": [],
            "missing_action_lines": [],
            "invalid_action_records": [],
            "action_counts": {action: 0 for action in sorted(_CAMPAIGN_ALLOWED_ACTIONS)},
            "candidate_actions": {},
            "candidate_rounds": {},
            "candidate_hidden_qualities": {},
        }
    campaign_records = campaign_audit["record_count"]
    if campaign_records <= 0:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_missing_or_invalid",
            "complete": False,
            "campaign": campaign_path,
            "message": "campaign.jsonl is missing, empty, or malformed",
            "next_action": "rerun run_batch_round.py so campaign.jsonl and summary.json are generated together",
            "evidence": batch_summary.get("_path"),
        }
    if campaign_records != n_routed:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_summary_mismatch",
            "complete": False,
            "campaign": campaign_path,
            "campaign_records": campaign_records,
            "n_routed": n_routed,
            "message": "campaign row count differs from summary routed-candidate count",
            "next_action": "regenerate campaign.jsonl and summary.json from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    if (
        campaign_audit["missing_candidate_id_lines"]
        or campaign_audit["duplicate_candidate_ids"]
        or campaign_audit["missing_action_lines"]
        or campaign_audit["invalid_action_records"]
    ):
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_invalid",
            "complete": False,
            "campaign": campaign_path,
            "campaign_records": campaign_records,
            "missing_candidate_id_lines": campaign_audit["missing_candidate_id_lines"],
            "duplicate_candidate_ids": campaign_audit["duplicate_candidate_ids"],
            "missing_action_lines": campaign_audit["missing_action_lines"],
            "invalid_action_records": campaign_audit["invalid_action_records"],
            "allowed_actions": sorted(_CAMPAIGN_ALLOWED_ACTIONS),
            "message": "campaign.jsonl rows must have non-empty unique candidate_id and a known DBTL action",
            "next_action": "regenerate campaign.jsonl from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    action_rate_mismatches = _campaign_action_rate_mismatches(
        campaign_audit,
        aggregate,
        n_routed,
    )
    if action_rate_mismatches:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_summary_action_mismatch",
            "complete": False,
            "campaign": campaign_path,
            "campaign_records": campaign_records,
            "action_rate_mismatches": action_rate_mismatches,
            "message": "campaign action mix differs from summary aggregate action rates",
            "next_action": "regenerate campaign.jsonl and summary.json from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    assay_count_mismatches = _campaign_assay_count_mismatches(
        campaign_audit,
        batch_summary,
    )
    if assay_count_mismatches:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_summary_assay_mismatch",
            "complete": False,
            "campaign": campaign_path,
            "campaign_records": campaign_records,
            "assay_count_mismatches": assay_count_mismatches,
            "message": "campaign verify_assay count differs from summary assays_used",
            "next_action": "regenerate campaign.jsonl and summary.json from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    best_mismatches = _campaign_best_mismatches(
        campaign_audit,
        batch_summary,
    )
    if best_mismatches:
        return {
            "workstream": "W4_closed_loop_DBTL",
            "status": "campaign_summary_best_mismatch",
            "complete": False,
            "campaign": campaign_path,
            "campaign_records": campaign_records,
            "best_mismatches": best_mismatches,
            "message": "summary best candidate differs from campaign rows",
            "next_action": "regenerate campaign.jsonl and summary.json from the same DBTL batch run",
            "evidence": batch_summary.get("_path"),
        }
    expected_candidate_ids = batch_preflight.get("candidate_ids")
    if (
        isinstance(expected_candidate_ids, list)
        and all(isinstance(candidate_id, str) and candidate_id.strip() for candidate_id in expected_candidate_ids)
    ):
        expected_ids = sorted(candidate_id.strip() for candidate_id in expected_candidate_ids)
        actual_ids = sorted(campaign_audit["candidate_ids"])
        if actual_ids != expected_ids:
            return {
                "workstream": "W4_closed_loop_DBTL",
                "status": "campaign_preflight_mismatch",
                "complete": False,
                "campaign": campaign_path,
                "campaign_records": campaign_records,
                "expected_candidate_ids": expected_ids,
                "campaign_candidate_ids": actual_ids,
                "message": "campaign candidate_id set differs from preflight candidate_id set",
                "next_action": "regenerate preflight.json, campaign.jsonl, and summary.json from the same DBTL batch run",
                "evidence": batch_summary.get("_path"),
            }
    return {
        "workstream": "W4_closed_loop_DBTL",
        "status": "closed_loop_round_complete",
        "complete": True,
        "n_candidates": batch_preflight.get("n_candidates"),
        "n_routed": n_routed,
        "campaign_records": campaign_records,
        "assays_used": batch_summary.get("assays_used"),
        "screen_backend": batch_summary.get("screen_backend"),
        "aggregate": aggregate,
        "gate_calibrated": batch_summary.get("gate_calibrated"),
        "gate_prevalidation": gate_prevalidation,
        "preflight": batch_preflight.get("_path"),
        "summary": batch_summary.get("_path"),
        "campaign": campaign_path,
        "next_action": "use the closed-loop round summary to choose the next batch or broaden to de-novo binder generation",
        "evidence": batch_summary.get("_path"),
    }


def run_status(*, posthoc_manifest_path: Optional[str] = None,
               decision_path: Optional[str] = None,
               scale_completion_path: Optional[str] = None,
               input_prep_completion_path: Optional[str] = None,
               scale_input_prep_completion_path: Optional[str] = None,
               panel_input_prep_completion_path: Optional[str] = None,
               target_manifest_path: Optional[str] = None,
               target_msa_gate_audit_path: Optional[str] = None,
               w2_approval_packet_path: Optional[str] = None,
               w2_approval_parity_path: Optional[str] = None,
               w2_panel_approval_packet_path: Optional[str] = None,
               w2_panel_decision_protocol_path: Optional[str] = None,
               w2_panel_remote_readiness_path: Optional[str] = None,
               w2_panel_submission_decision_state_path: Optional[str] = None,
               w2_panel_postsync_interpretation_path: Optional[str] = None,
               panel_completion_path: Optional[str] = None,
               panel_report_path: Optional[str] = None,
               predictor_contract_path: Optional[str] = None,
               cross_predictor_path: Optional[str] = None,
               w3_decision_protocol_path: Optional[str] = None,
               w3_next_protocol_path: Optional[str] = None,
               w3_challenge_manifest_path: Optional[str] = None,
               w3_third_predictor_contract_path: Optional[str] = None,
               w3_predictor_selection_card_path: Optional[str] = None,
               w3_runtime_probe_plan_path: Optional[str] = None,
               w3_runtime_probe_report_path: Optional[str] = None,
               w3_runtime_repair_plan_path: Optional[str] = None,
               w3_runtime_provision_packet_path: Optional[str] = None,
               predictor_sync_back_plan: Optional[str] = None,
               batch_preflight_path: Optional[str] = None,
               batch_summary_path: Optional[str] = None,
               batch_campaign_path: Optional[str] = None,
               batch_sync_back_plan: Optional[str] = None,
               target_alpha: float = 0.2) -> Dict[str, Any]:
    posthoc_manifest = _load_json(posthoc_manifest_path, role="posthoc_manifest")
    if decision_path is None:
        decision_path = _decision_from_manifest(posthoc_manifest)
    decision = _load_json(decision_path, role="alpha_decision")
    scale_completion = _load_json(scale_completion_path, role="scale_completion")
    scale_input_prep_completion = _load_json(
        scale_input_prep_completion_path or input_prep_completion_path,
        role="scale_input_prep_completion",
    )
    panel_input_prep_completion = _load_json(
        panel_input_prep_completion_path or input_prep_completion_path,
        role="panel_input_prep_completion",
    )
    target_manifest = _load_json(target_manifest_path, role="target_manifest_report")
    target_msa_gate_audit = _load_json(target_msa_gate_audit_path, role="target_msa_gate_audit")
    w2_approval_packet = _load_json(w2_approval_packet_path, role="w2_approval_packet")
    w2_approval_parity = _load_json(w2_approval_parity_path, role="w2_approval_parity")
    w2_panel_approval_packet = _load_json(
        w2_panel_approval_packet_path,
        role="w2_panel_approval_packet",
    )
    w2_panel_decision_protocol = _load_json(
        w2_panel_decision_protocol_path,
        role="w2_panel_decision_protocol",
    )
    w2_panel_remote_readiness = _load_json(
        w2_panel_remote_readiness_path,
        role="w2_panel_remote_readiness",
    )
    w2_panel_submission_decision_state = _load_json(
        w2_panel_submission_decision_state_path,
        role="w2_panel_submission_decision_state",
    )
    w2_panel_postsync_interpretation = _load_json(
        w2_panel_postsync_interpretation_path,
        role="w2_panel_postsync_interpretation",
    )
    panel_completion = _load_json(panel_completion_path, role="panel_completion")
    panel_report = _load_json(panel_report_path, role="panel_report")
    predictor_contract = _load_json(predictor_contract_path, role="predictor_contract")
    cross_predictor = _load_json(cross_predictor_path, role="cross_predictor")
    w3_decision_protocol = _load_json(w3_decision_protocol_path, role="w3_decision_protocol")
    w3_next_protocol = _load_json(w3_next_protocol_path, role="w3_next_protocol")
    w3_challenge_manifest = _load_json(w3_challenge_manifest_path, role="w3_challenge_manifest")
    w3_third_predictor_contract = _load_json(
        w3_third_predictor_contract_path,
        role="w3_third_predictor_contract",
    )
    w3_predictor_selection_card = _load_json(
        w3_predictor_selection_card_path,
        role="w3_predictor_selection_card",
    )
    w3_runtime_probe_plan = _load_json(
        w3_runtime_probe_plan_path,
        role="w3_runtime_probe_plan",
    )
    w3_runtime_probe_report = _load_json(
        w3_runtime_probe_report_path,
        role="w3_runtime_probe_report",
    )
    w3_runtime_repair_plan = _load_json(
        w3_runtime_repair_plan_path,
        role="w3_runtime_repair_plan",
    )
    w3_runtime_provision_packet = _load_json(
        w3_runtime_provision_packet_path,
        role="w3_runtime_provision_packet",
    )
    batch_preflight = _load_json(batch_preflight_path, role="batch_preflight")
    batch_summary = _load_json(batch_summary_path, role="batch_summary")

    w3 = _w3_status(
        predictor_contract,
        cross_predictor,
        decision_protocol=w3_decision_protocol,
        next_protocol=w3_next_protocol,
        challenge_manifest=w3_challenge_manifest,
        third_predictor_contract=w3_third_predictor_contract,
        predictor_selection_card=w3_predictor_selection_card,
        runtime_probe_plan=w3_runtime_probe_plan,
        runtime_probe_report=w3_runtime_probe_report,
        runtime_repair_plan=w3_runtime_repair_plan,
        runtime_provision_packet=w3_runtime_provision_packet,
    )
    if (
        predictor_sync_back_plan
        and w3.get("status") in {"second_predictor_contract_missing", "second_predictor_contract_blocked"}
    ):
        w3["sync_back_plan"] = predictor_sync_back_plan

    w4 = _w4_status(batch_preflight, batch_summary, batch_campaign_path)
    if batch_sync_back_plan and not w4.get("complete"):
        w4["sync_back_plan"] = batch_sync_back_plan

    workstreams = [
        _w1_status(
            decision,
            posthoc_manifest,
            scale_completion,
            target_alpha,
            input_prep_completion=scale_input_prep_completion,
        ),
        _w2_status(
            target_manifest,
            panel_completion,
            panel_report,
            target_alpha,
            input_prep_completion=panel_input_prep_completion,
            target_msa_gate_audit=target_msa_gate_audit,
            target_msa_approval_packet=w2_approval_packet,
            target_msa_approval_parity=w2_approval_parity,
            panel_approval_packet=w2_panel_approval_packet,
            panel_decision_protocol=w2_panel_decision_protocol,
            panel_remote_readiness=w2_panel_remote_readiness,
            panel_submission_decision_state=w2_panel_submission_decision_state,
            panel_postsync_interpretation=w2_panel_postsync_interpretation,
        ),
        w3,
        w4,
    ]
    pending_input_prep_paths = _project_pending_input_prep_paths(workstreams)
    pending_external_artifacts = _project_pending_external_artifacts(workstreams)
    pending_external_summary = summarize_pending_external_artifacts(pending_external_artifacts)
    posthoc_science_claims = _posthoc_science_claims(posthoc_manifest)
    posthoc_science_claims_audit = _posthoc_science_claims_audit(
        posthoc_manifest,
        posthoc_science_claims,
        target_alpha=target_alpha,
    )
    evidence_complete = all(w["complete"] for w in workstreams[:3])
    complete = evidence_complete and workstreams[3]["complete"]
    if complete:
        status = "m6_complex_closed_loop_ready"
        next_action = "move to de-novo binder generation or live orchestration when key rotation is complete"
    elif evidence_complete:
        status = "m6_complex_evidence_ready"
        next_action = workstreams[3]["next_action"]
    else:
        status = "m6_complex_in_progress"
        next_action = next((w["next_action"] for w in workstreams[:3] if not w["complete"]), "inspect artifacts")
    rep = {
        "ok": True,
        "status": status,
        "complete": complete,
        "target_alpha": target_alpha,
        "workstreams": {w["workstream"]: w for w in workstreams},
        "pending_input_prep_paths": pending_input_prep_paths,
        "n_pending_input_prep_paths": len(pending_input_prep_paths),
        "pending_external_artifacts": pending_external_artifacts,
        "n_pending_external_artifacts": len(pending_external_artifacts),
        "pending_external_summary": pending_external_summary,
        "posthoc_science_claims": posthoc_science_claims,
        "posthoc_science_claims_audit": posthoc_science_claims_audit,
        "next_action": next_action,
    }
    attach_resume_execution_ladder(rep)
    return rep


def render_text(rep: Dict[str, Any]) -> str:
    lines = [
        f"# complex project status  status={rep['status']} complete={rep['complete']}",
        f"target_alpha={rep['target_alpha']}",
        "",
    ]
    science_claims = rep.get("posthoc_science_claims")
    if isinstance(science_claims, dict) and any(
        science_claims.get(key)
        for key in ("supported", "not_yet_supported", "planning_diagnostics", "decisive_next")
    ):
        chunks = []
        for label, key in (
            ("supported", "supported"),
            ("not_yet_supported", "not_yet_supported"),
            ("planning", "planning_diagnostics"),
            ("decisive", "decisive_next"),
        ):
            values = science_claims.get(key)
            if isinstance(values, list) and values:
                chunks.append(f"{label}:{','.join(str(value) for value in values)}")
        if chunks:
            lines.append(f"posthoc_science_claims={' '.join(chunks)}")
            lines.append("")
    for key in ("W1_M6c_scale_up", "W2_multi_target_panel", "W3_independent_predictor"):
        w = rep["workstreams"][key]
        lines.append(f"- {key}: {w['status']} (complete={w['complete']})")
        lines.append(f"  next: {w['next_action']}")
        if key == "W2_multi_target_panel" and "approval_packet_ready" in w:
            lines.append(
                "  approval_packet_ready={ready} panel_submission_allowed={panel}".format(
                    ready=w.get("approval_packet_ready"),
                    panel=w.get("can_submit_proteinmpnn_boltz_panel"),
                )
            )
        if key == "W2_multi_target_panel" and "approval_parity_ok" in w:
            lines.append(
                "  approval_parity_ok={ok} local_cayuga_agree={agree}".format(
                    ok=w.get("approval_parity_ok"),
                    agree=w.get("local_cayuga_approval_packet_agree"),
                )
            )
        if key == "W2_multi_target_panel" and "panel_approval_packet_ready" in w:
            lines.append(
                "  panel_approval_packet_ready={ready} panel_submit_after_explicit_approval={submit} can_claim_w2_generalization={claim}".format(
                    ready=w.get("panel_approval_packet_ready"),
                    submit=w.get("can_submit_panel_if_user_explicitly_approves"),
                    claim=w.get("can_claim_w2_generalization"),
                )
            )
            if "panel_postsubmit_sync_ready_gate_ok" in w:
                lines.append(
                    "  panel_postsubmit_sync_ready_gate_ok={ok} postsubmit={postsubmit} job_states={job_states}".format(
                        ok=w.get("panel_postsubmit_sync_ready_gate_ok"),
                        postsubmit=w.get("panel_postsubmit_status_before_sync"),
                        job_states=w.get("panel_job_state_probe_before_sync"),
                    )
                )
            if "panel_postsubmit_bridge_ok" in w:
                lines.append(
                    "  panel_postsubmit_bridge_ok={ok} receipt_monitor={receipt} driver={driver} job_query={job_query}".format(
                        ok=w.get("panel_postsubmit_bridge_ok"),
                        receipt=w.get("panel_receipt_monitor_after_submit"),
                        driver=w.get("panel_postsubmit_driver_after_submit"),
                        job_query=w.get("panel_job_state_query_after_receipt"),
                    )
                )
        if key == "W2_multi_target_panel" and "panel_decision_protocol_ready" in w:
            lines.append(
                "  panel_decision_protocol_ready={ready} no_submit={no_submit} can_claim_w2_now={claim}".format(
                    ready=w.get("panel_decision_protocol_ready"),
                    no_submit=w.get("panel_decision_no_submit"),
                    claim=w.get("panel_decision_can_claim_w2_now"),
                )
            )
        if key == "W2_multi_target_panel" and "panel_remote_submission_readiness_ok" in w:
            lines.append(
                "  panel_remote_submission_readiness_ok={ready} no_submit={no_submit} exact={exact} semantic={semantic} absent={absent}".format(
                    ready=w.get("panel_remote_submission_readiness_ok"),
                    no_submit=w.get("panel_remote_no_submit"),
                    exact=w.get("panel_remote_exact_checks"),
                    semantic=w.get("panel_remote_semantic_checks"),
                    absent=w.get("panel_remote_absence_checks"),
                )
            )
        if key == "W2_multi_target_panel" and "panel_submission_decision_ready" in w:
            lines.append(
                "  panel_submission_decision_ready={ready} decision={decision} no_submit={no_submit} submitted={submitted} can_claim_w2={claim}".format(
                    ready=w.get("panel_submission_decision_ready"),
                    decision=w.get("panel_submission_decision"),
                    no_submit=w.get("panel_submission_decision_no_submit"),
                    submitted=w.get("panel_submission_decision_submitted"),
                    claim=w.get("panel_submission_decision_can_claim_w2_generalization"),
                )
            )
        if key == "W2_multi_target_panel" and "panel_postsync_interpretation_ready" in w:
            lines.append(
                "  panel_postsync_interpretation_ready={ready} status={status} sync_ready={sync_ready} can_claim_w2={claim}".format(
                    ready=w.get("panel_postsync_interpretation_ready"),
                    status=w.get("panel_postsync_status"),
                    sync_ready=w.get("panel_postsync_sync_ready"),
                    claim=w.get("panel_postsync_can_claim_w2_generalization"),
                )
            )
        if key == "W3_independent_predictor" and "w3_next_protocol_ready" in w:
            next_protocol = w.get("w3_next_protocol") if isinstance(w.get("w3_next_protocol"), dict) else {}
            lines.append(
                "  w3_next_protocol_ready={ready} no_submit={no_submit} no_api={no_api} no_gpu={no_gpu} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_next_protocol_ready"),
                    no_submit=next_protocol.get("no_submit"),
                    no_api=next_protocol.get("no_api_spend"),
                    no_gpu=next_protocol.get("no_gpu_spend"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_challenge_manifest_ready" in w:
            challenge = w.get("w3_challenge_manifest") if isinstance(w.get("w3_challenge_manifest"), dict) else {}
            lines.append(
                "  w3_challenge_manifest_ready={ready} execution_ready={execution} no_submit={no_submit} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_challenge_manifest_ready"),
                    execution=w.get("w3_challenge_execution_ready"),
                    no_submit=challenge.get("no_submit"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_third_predictor_contract_ready" in w:
            contract = w.get("w3_third_predictor_contract") if isinstance(w.get("w3_third_predictor_contract"), dict) else {}
            lines.append(
                "  w3_third_predictor_contract_ready={ready} execution_ready={execution} no_submit={no_submit} wrapper_emitted={wrapper} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_third_predictor_contract_ready"),
                    execution=w.get("w3_third_predictor_execution_ready"),
                    no_submit=contract.get("no_submit"),
                    wrapper=contract.get("command_wrapper_emitted"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_predictor_selection_card_ready" in w:
            selection = w.get("w3_predictor_selection_card") if isinstance(w.get("w3_predictor_selection_card"), dict) else {}
            lines.append(
                "  w3_predictor_selection_card_ready={ready} selected={selected} runtime_ready={runtime} execution_ready={execution} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_predictor_selection_card_ready"),
                    selected=selection.get("selected_predictor_or_protocol_id"),
                    runtime=w.get("w3_selected_predictor_runtime_ready"),
                    execution=w.get("w3_selected_predictor_execution_ready"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_runtime_probe_plan_ready" in w:
            lines.append(
                "  w3_runtime_probe_plan_ready={ready} probe_executed={executed} runtime_ready={runtime} execution_ready={execution} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_runtime_probe_plan_ready"),
                    executed=w.get("w3_runtime_probe_plan_executed"),
                    runtime=w.get("w3_selected_predictor_runtime_ready"),
                    execution=w.get("w3_selected_predictor_execution_ready"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_runtime_probe_report_ready" in w:
            report = w.get("w3_runtime_probe_report") if isinstance(w.get("w3_runtime_probe_report"), dict) else {}
            lines.append(
                "  w3_runtime_probe_report_ready={ready} surface={surface} probe_executed={executed} cayuga_probe={cayuga} runtime_ready={runtime} execution_ready={execution} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_runtime_probe_report_ready"),
                    surface=report.get("probe_surface"),
                    executed=w.get("w3_runtime_probe_report_executed"),
                    cayuga=w.get("w3_runtime_probe_cayuga_executed"),
                    runtime=w.get("w3_selected_predictor_runtime_ready"),
                    execution=w.get("w3_selected_predictor_execution_ready"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_runtime_repair_plan_ready" in w:
            repair = w.get("w3_runtime_repair_plan") if isinstance(w.get("w3_runtime_repair_plan"), dict) else {}
            failed = ",".join(str(item) for item in repair.get("failed_runtime_checks") or [])
            lines.append(
                "  w3_runtime_repair_plan_ready={ready} failed_checks={failed} runtime_ready={runtime} execution_ready={execution} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_runtime_repair_plan_ready"),
                    failed=failed,
                    runtime=w.get("w3_selected_predictor_runtime_ready"),
                    execution=w.get("w3_selected_predictor_execution_ready"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if key == "W3_independent_predictor" and "w3_runtime_provision_packet_ready" in w:
            provision = (
                w.get("w3_runtime_provision_packet")
                if isinstance(w.get("w3_runtime_provision_packet"), dict)
                else {}
            )
            lines.append(
                "  w3_runtime_provision_packet_ready={ready} script={script} approval_env={approval} runtime_ready={runtime} execution_ready={execution} can_claim_w3_now={claim}".format(
                    ready=w.get("w3_runtime_provision_packet_ready"),
                    script=provision.get("script"),
                    approval=provision.get("approval_env_var"),
                    runtime=w.get("w3_selected_predictor_runtime_ready"),
                    execution=w.get("w3_selected_predictor_execution_ready"),
                    claim=w.get("can_claim_independent_predictor_robustness_now"),
                )
            )
        if w.get("sync_back_plan"):
            lines.append(f"  sync_back: bash {w['sync_back_plan']}")
    w4 = rep["workstreams"]["W4_closed_loop_DBTL"]
    lines.append(f"- W4_closed_loop_DBTL: {w4['status']} (complete={w4['complete']})")
    lines.append(f"  next: {w4['next_action']}")
    if w4.get("sync_back_plan"):
        lines.append(f"  sync_back: bash {w4['sync_back_plan']}")
    if rep.get("n_pending_input_prep_paths"):
        lines.append(f"pending_input_prep_paths={rep['n_pending_input_prep_paths']}")
    if rep.get("n_pending_external_artifacts"):
        lines.append(f"pending_external_artifacts={rep['n_pending_external_artifacts']}")
        summary = rep.get("pending_external_summary")
        by_workstream = summary.get("by_workstream") if isinstance(summary, dict) else None
        if isinstance(by_workstream, dict) and by_workstream:
            rendered = ",".join(f"{key}:{by_workstream[key]}" for key in sorted(by_workstream))
            lines.append(f"pending_external_workstreams={rendered}")
        followups = rep.get("pending_external_followups")
        if isinstance(followups, list) and followups:
            rendered = ",".join(
                f"{item.get('workstream')}:{item.get('n_missing')}"
                for item in followups
                if isinstance(item, dict) and item.get("workstream")
            )
            if rendered:
                lines.append(f"pending_external_followups={rendered}")
    target_msa_plan = rep.get("target_msa_precompute_plan")
    if isinstance(target_msa_plan, dict) and target_msa_plan.get("n_targets"):
        target_ids = ",".join(str(t) for t in target_msa_plan.get("target_ids") or [])
        command = target_msa_plan.get("command")
        line = f"target_msa_precompute_plan=targets:{target_msa_plan.get('n_targets')}"
        if target_ids:
            line += f" target_ids={target_ids}"
        if command:
            line += f" command={command}"
        lines.append(line)
        conflicts = target_msa_plan.get("conflicting_duplicate_target_ids")
        if isinstance(conflicts, list) and conflicts:
            lines.append(f"target_msa_precompute_plan_conflicts={len(conflicts)}")
    receipt = rep.get("target_msa_precompute_receipt")
    if isinstance(receipt, dict) and receipt.get("path"):
        line = f"target_msa_precompute_receipt={receipt.get('status')}"
        line += f" recorded={receipt.get('n_recorded_expected', 0)}/{receipt.get('n_expected', 0)}"
        line += f" path={receipt.get('path')}"
        lines.append(line)
        if receipt.get("resume_blocker"):
            lines.append(f"target_msa_precompute_receipt_blocker={receipt.get('resume_blocker')}")
    local_audit = rep.get("pending_artifact_local_audit")
    if isinstance(local_audit, dict):
        for label, key in (("pending_input_prep_local", "input_prep"),
                           ("pending_external_local", "external")):
            audit = local_audit.get(key)
            if not isinstance(audit, dict) or not audit.get("n_paths"):
                continue
            lines.append(
                f"{label}={audit.get('status')} "
                f"nonempty={audit.get('n_nonempty')}/{audit.get('n_paths')} "
                f"missing={audit.get('n_missing')} empty={audit.get('n_empty')}"
            )
    if rep.get("recommended_next_script"):
        lines.append(f"recommended_next_script: {rep['recommended_next_script']['command']}")
        dry_run_command = rep["recommended_next_script"].get("dry_run_command")
        if dry_run_command:
            lines.append(f"recommended_next_preflight: {dry_run_command}")
        if rep["recommended_next_script"].get("blocked_by_sync_manifest_audit"):
            lines.append("recommended_next_script_blocked: sync_manifest_audit failed")
    remote_report = rep.get("external_remote_check_report")
    if isinstance(remote_report, dict):
        line = f"external_remote_check_report={remote_report.get('status')}"
        if remote_report.get("fresh") is not None:
            line += f" fresh={remote_report.get('fresh')}"
        if remote_report.get("n_missing") is not None:
            line += f" missing={remote_report.get('n_missing')}"
        missing_by_workstream = remote_report.get("missing_by_workstream")
        if isinstance(missing_by_workstream, dict) and missing_by_workstream:
            summary = ",".join(
                f"{key}:{missing_by_workstream[key]}"
                for key in sorted(missing_by_workstream)
            )
            line += f" missing_workstreams={summary}"
        followups = remote_report.get("remote_missing_followups")
        if isinstance(followups, list) and followups:
            summary = ",".join(
                f"{item.get('workstream')}:{item.get('n_missing')}"
                for item in followups
                if isinstance(item, dict) and item.get("workstream")
            )
            if summary:
                line += f" followups={summary}"
        lines.append(line)
        receipt_sync = remote_report.get("target_msa_precompute_receipt_sync")
        if isinstance(receipt_sync, dict) and receipt_sync.get("requested"):
            receipt_sync_synced = remote_report.get(
                "target_msa_receipt_sync_synced",
                receipt_sync.get("synced"),
            )
            receipt_sync_status = receipt_sync.get("status")
            if (
                receipt_sync_status == "synced"
                and receipt_sync.get("synced") is True
                and receipt_sync_synced is False
            ):
                receipt_sync_status = "synced_missing_digest"
            receipt_sync_line = (
                "target_msa_precompute_receipt_sync="
                f"{receipt_sync_status} synced={receipt_sync_synced}"
            )
            receipt_sync_sha256 = (
                remote_report.get("target_msa_receipt_sync_sha256")
                or receipt_sync.get("sha256")
            )
            if isinstance(receipt_sync_sha256, str) and receipt_sync_sha256:
                receipt_sync_line += f" sha256={receipt_sync_sha256[:12]}"
            lines.append(
                receipt_sync_line
            )
    scripts = rep.get("generated_scripts") or []
    manifest_count = sum(
        1 for script in scripts
        if isinstance(script, dict) and _manifest_hint_usable(script.get("manifest"))
    )
    if manifest_count:
        lines.append(f"script_manifests={manifest_count}/{len(scripts)}")
    syntax_audit = rep.get("generated_script_syntax_audit")
    if isinstance(syntax_audit, dict):
        status = "ok" if syntax_audit.get("ok") else "fail"
        lines.append(
            f"generated_script_syntax_audit={status} "
            f"checked={syntax_audit.get('n_checked', 0)}/{syntax_audit.get('n_scripts', 0)}"
        )
        if syntax_audit.get("n_not_checked"):
            lines[-1] += f" unchecked={syntax_audit.get('n_not_checked')}"
    target_msa_script_audit = rep.get("target_msa_precompute_script_validation_audit")
    if isinstance(target_msa_script_audit, dict) and target_msa_script_audit.get("n_expected_targets"):
        status = "ok" if target_msa_script_audit.get("ok") else "fail"
        lines.append(
            "target_msa_precompute_script_validation_audit="
            f"{status} targets={target_msa_script_audit.get('n_expected_targets')}"
        )
    audit = rep.get("sync_manifest_audit")
    if isinstance(audit, dict):
        status = "ok" if audit.get("ok") else "fail"
        lines.append(f"sync_manifest_audit={status} checks={audit.get('n_checks', 0)}")
    preflight = rep.get("resume_bridge_preflight")
    if isinstance(preflight, dict):
        line = f"resume_bridge_preflight={preflight.get('status')}"
        missing_env = preflight.get("missing_env") or []
        blockers = preflight.get("blockers") or []
        if missing_env:
            line += " missing_env=" + ",".join(str(name) for name in missing_env)
        if blockers:
            line += " blockers=" + ",".join(str(reason) for reason in blockers)
        lines.append(line)
    ladder = rep.get("resume_execution_ladder")
    if isinstance(ladder, dict):
        steps = ladder.get("steps")
        if isinstance(steps, list) and steps:
            rendered_steps = []
            for step in steps:
                if isinstance(step, dict) and step.get("role"):
                    rendered_steps.append(f"{step.get('role')}:{step.get('status')}")
            if rendered_steps:
                lines.append("resume_execution_ladder=" + ">".join(rendered_steps))
    goal_audit = rep.get("goal_progress_audit")
    if isinstance(goal_audit, dict):
        line = (
            f"goal_progress={goal_audit.get('status')} "
            f"remaining={goal_audit.get('remaining_requirements')}"
        )
        first_action = goal_audit.get("first_action")
        if isinstance(first_action, dict) and first_action.get("role"):
            line += f" first={first_action.get('role')}"
        lines.append(line)
    operator_next_action = rep.get("operator_next_action")
    if operator_next_action and operator_next_action != rep.get("next_action"):
        operator_preflight_command = rep.get("operator_preflight_command")
        lines.extend([
            "",
            *(
                [f"operator_preflight_command: {operator_preflight_command}"]
                if operator_preflight_command
                else []
            ),
            f"operator_next_action: {operator_next_action}",
            f"workstream_next_action: {rep['next_action']}",
            "",
        ])
    else:
        lines.extend(["", f"next_action: {rep['next_action']}", ""])
    return "\n".join(lines)


def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="summarize M6 complex roadmap status from JSON artifacts")
    ap.add_argument("--posthoc-manifest", default=None)
    ap.add_argument("--decision", default=None)
    ap.add_argument("--scale-completion", default=None)
    ap.add_argument("--input-prep-completion", default=None,
                    help="legacy/shared complex_input_prep_completion.py JSON report for W1/W2 input-prep sync status")
    ap.add_argument("--scale-input-prep-completion", default=None,
                    help="W1 scale input-prep completion report; overrides --input-prep-completion for W1")
    ap.add_argument("--panel-input-prep-completion", default=None,
                    help="W2 panel input-prep completion report; overrides --input-prep-completion for W2")
    ap.add_argument("--scale-target-manifest", default=None,
                    help="raw W1 target manifest JSON used to emit a deduplicated target-MSA precompute plan")
    ap.add_argument("--panel-target-manifest", default=None,
                    help="raw W2 target manifest JSON used to emit a deduplicated target-MSA precompute plan")
    ap.add_argument("--target-manifest-report", default=None)
    ap.add_argument("--target-msa-gate-audit", default=None,
                    help="optional W2 target-MSA gate audit that supersedes older panel evidence for the active branch")
    ap.add_argument("--w2-approval-packet", default=None,
                    help="optional no-submit W2 target-MSA approval packet layered above the target-MSA gate audit")
    ap.add_argument("--w2-approval-parity", default=None,
                    help="optional local/Cayuga W2 target-MSA approval packet parity report")
    ap.add_argument("--w2-panel-approval-packet", default=None,
                    help="optional no-submit W2 panel approval packet layered above the target-MSA execution sync")
    ap.add_argument("--w2-panel-decision-protocol", default=None,
                    help="optional no-submit W2 post-panel decision protocol")
    ap.add_argument("--w2-panel-remote-readiness", default=None,
                    help="optional no-submit W2 v11 Cayuga mirror readiness audit")
    ap.add_argument("--w2-panel-submission-decision-state", default=None,
                    help="optional no-submit W2 v11 explicit panel-submission decision state")
    ap.add_argument("--w2-panel-postsync-interpretation", default=None,
                    help="optional no-submit W2 v11 post-sync interpretation state")
    ap.add_argument("--panel-completion", default=None)
    ap.add_argument("--panel-report", default=None)
    ap.add_argument("--predictor-contract-report", default=None)
    ap.add_argument("--cross-predictor-report", default=None)
    ap.add_argument("--w3-decision-protocol", default=None,
                    help="optional W3 adjudication decision protocol; supersedes raw cross-predictor readiness when present")
    ap.add_argument("--w3-next-protocol", default=None,
                    help="optional no-submit W3 next-protocol contract layered above the negative adjudication")
    ap.add_argument("--w3-challenge-manifest", default=None,
                    help="optional no-submit W3 challenge manifest layered above the next-protocol contract")
    ap.add_argument("--w3-third-predictor-contract", default=None,
                    help="optional no-submit W3 third-predictor execution contract layered above the challenge manifest")
    ap.add_argument("--w3-predictor-selection-card", default=None,
                    help="optional no-submit W3 predictor/protocol selection card layered above the third-predictor contract")
    ap.add_argument("--w3-runtime-probe-plan", default=None,
                    help="optional no-submit W3 runtime-probe plan layered above the predictor/protocol selection card")
    ap.add_argument("--w3-runtime-probe-report", default=None,
                    help="optional no-submit W3 runtime-probe report layered above the runtime-probe plan")
    ap.add_argument("--w3-runtime-repair-plan", default=None,
                    help="optional no-submit W3 runtime repair plan layered above the runtime-probe report")
    ap.add_argument("--w3-runtime-provision-packet", default=None,
                    help="optional guarded W3 runtime provision packet layered above the runtime repair plan")
    ap.add_argument("--predictor-sync-back-plan", default=None,
                    help="optional W3 sync-back shell plan for missing second-predictor records")
    ap.add_argument("--batch-preflight", default=None,
                    help="run_batch_round.py preflight.json artifact for W4")
    ap.add_argument("--batch-summary", default=None,
                    help="run_batch_round.py summary.json artifact for W4")
    ap.add_argument("--batch-campaign", default=None,
                    help="optional campaign.jsonl path; defaults to summary directory/campaign.jsonl")
    ap.add_argument("--batch-sync-back-plan", default=None,
                    help="optional W4 sync-back shell plan for missing batch candidates/records/verdicts")
    ap.add_argument("--scale-readiness-report", default=None,
                    help="optional W1 readiness JSON with self_command for --emit-post-sync-plan")
    ap.add_argument("--panel-readiness-report", default=None,
                    help="optional W2 readiness JSON with self_command for --emit-post-sync-plan")
    ap.add_argument("--target-alpha", type=float, default=0.2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--emit-pending-input-prep-paths", default=None,
                    help="optional text file listing unique W1/W2 pending input-prep paths, one per line")
    ap.add_argument("--absolute-pending-input-prep-paths", action="store_true",
                    help="write absolute paths in --emit-pending-input-prep-paths when available")
    ap.add_argument("--emit-pending-external-paths", default=None,
                    help="optional text file listing unique W1-W4 pending external artifact paths, one per line")
    ap.add_argument("--absolute-pending-external-paths", action="store_true",
                    help="write absolute paths in --emit-pending-external-paths when available")
    ap.add_argument("--emit-sync-back-plan", default=None,
                    help="optional shell plan to rsync project pending input-prep paths back from Cayuga")
    ap.add_argument("--emit-external-sync-back-plan", default=None,
                    help="optional shell plan to rsync all project pending external artifacts back from Cayuga")
    ap.add_argument("--emit-external-remote-check-plan", default=None,
                    help="optional shell plan to ssh-test pending external artifacts on Cayuga before rsync")
    ap.add_argument("--external-remote-check-report", default=None,
                    help="optional JSON report from the external remote-check plan; fresh ok reports unlock sync-back recommendation")
    ap.add_argument("--emit-target-msa-precompute-plan", default=None,
                    help="optional shell plan that deduplicates W1/W2 target-MSA precompute jobs before remote-check")
    ap.add_argument("--target-msa-precompute-receipt", default=None,
                    help="optional JSONL receipt written by the target-MSA precompute plan")
    ap.add_argument("--sync-remote-root", default=None,
                    help="remote repo root for sync-back plans; defaults to CAYUGA_BIO_SFM_ROOT in the script")
    ap.add_argument("--sync-local-root", default=None,
                    help="local repo root for sync-back plans; defaults to LOCAL_BIO_SFM_ROOT or the repo root")
    ap.add_argument("--emit-post-sync-plan", default=None,
                    help="optional shell plan to rerun completion/readiness/status after input-prep sync-back")
    args = ap.parse_args(argv)
    if args.emit_target_msa_precompute_plan and not args.target_msa_precompute_receipt:
        args.target_msa_precompute_receipt = _target_msa_precompute_receipt_path(
            args.emit_target_msa_precompute_plan,
        )

    rep = run_status(
        posthoc_manifest_path=args.posthoc_manifest,
        decision_path=args.decision,
        scale_completion_path=args.scale_completion,
        input_prep_completion_path=args.input_prep_completion,
        scale_input_prep_completion_path=args.scale_input_prep_completion,
        panel_input_prep_completion_path=args.panel_input_prep_completion,
        target_manifest_path=args.target_manifest_report,
        target_msa_gate_audit_path=args.target_msa_gate_audit,
        w2_approval_packet_path=args.w2_approval_packet,
        w2_approval_parity_path=args.w2_approval_parity,
        w2_panel_approval_packet_path=args.w2_panel_approval_packet,
        w2_panel_decision_protocol_path=args.w2_panel_decision_protocol,
        w2_panel_remote_readiness_path=args.w2_panel_remote_readiness,
        w2_panel_submission_decision_state_path=args.w2_panel_submission_decision_state,
        w2_panel_postsync_interpretation_path=args.w2_panel_postsync_interpretation,
        panel_completion_path=args.panel_completion,
        panel_report_path=args.panel_report,
        predictor_contract_path=args.predictor_contract_report,
        cross_predictor_path=args.cross_predictor_report,
        w3_decision_protocol_path=args.w3_decision_protocol,
        w3_next_protocol_path=args.w3_next_protocol,
        w3_challenge_manifest_path=args.w3_challenge_manifest,
        w3_third_predictor_contract_path=args.w3_third_predictor_contract,
        w3_predictor_selection_card_path=args.w3_predictor_selection_card,
        w3_runtime_probe_plan_path=args.w3_runtime_probe_plan,
        w3_runtime_probe_report_path=args.w3_runtime_probe_report,
        w3_runtime_repair_plan_path=args.w3_runtime_repair_plan,
        w3_runtime_provision_packet_path=args.w3_runtime_provision_packet,
        predictor_sync_back_plan=args.predictor_sync_back_plan,
        batch_preflight_path=args.batch_preflight,
        batch_summary_path=args.batch_summary,
        batch_campaign_path=args.batch_campaign,
        batch_sync_back_plan=args.batch_sync_back_plan,
        target_alpha=args.target_alpha,
    )
    rep["self_command"] = _project_status_command(args)
    attach_pending_artifact_local_audit(rep)
    attach_path_manifests(rep, args=args)
    attach_pending_external_followups(rep, args=args)
    attach_target_msa_precompute_plan(rep, args=args)
    attach_target_msa_precompute_receipt(rep, args=args)
    attach_external_remote_check_report(rep, args=args)
    attach_script_hints(rep, args=args)
    attach_sync_manifest_audit(rep)
    if args.emit_pending_input_prep_paths:
        pending_text = render_pending_input_prep_paths(
            rep,
            absolute=args.absolute_pending_input_prep_paths,
        )
        _write_text_atomic(args.emit_pending_input_prep_paths, pending_text)
        manifest_path = rep["pending_input_prep_manifest"].get("manifest_file")
        if manifest_path:
            _write_json_atomic(manifest_path, rep["pending_input_prep_manifest"])
        print(f"wrote {args.emit_pending_input_prep_paths}")
    if args.emit_pending_external_paths:
        pending_text = render_pending_external_paths(
            rep,
            absolute=args.absolute_pending_external_paths,
        )
        _write_text_atomic(args.emit_pending_external_paths, pending_text)
        manifest_path = rep["pending_external_manifest"].get("manifest_file")
        if manifest_path:
            _write_json_atomic(manifest_path, rep["pending_external_manifest"])
        print(f"wrote {args.emit_pending_external_paths}")
    if args.emit_sync_back_plan:
        _write_text_atomic(args.emit_sync_back_plan, render_sync_back_plan(rep, args=args))
        print(f"wrote {args.emit_sync_back_plan}")
    if args.emit_external_sync_back_plan:
        _write_text_atomic(
            args.emit_external_sync_back_plan,
            render_external_sync_back_plan(rep, args=args),
        )
        print(f"wrote {args.emit_external_sync_back_plan}")
    if args.emit_external_remote_check_plan:
        _write_text_atomic(
            args.emit_external_remote_check_plan,
            render_external_remote_check_plan(rep, args=args),
        )
        print(f"wrote {args.emit_external_remote_check_plan}")
    if args.emit_target_msa_precompute_plan:
        _write_text_atomic(
            args.emit_target_msa_precompute_plan,
            render_project_target_msa_precompute_plan(rep, args=args),
        )
        print(f"wrote {args.emit_target_msa_precompute_plan}")
    if args.emit_post_sync_plan:
        manifest = rep.get("post_sync_replay_manifest")
        if isinstance(manifest, dict) and manifest.get("manifest_file"):
            _write_json_atomic(str(manifest["manifest_file"]), manifest)
            print(f"wrote {manifest['manifest_file']}")
        _write_text_atomic(args.emit_post_sync_plan, render_post_sync_plan(rep, args=args))
        print(f"wrote {args.emit_post_sync_plan}")
    attach_generated_script_syntax_audit(rep)
    attach_target_msa_precompute_script_validation_audit(rep)
    attach_resume_bridge_preflight(rep)
    attach_resume_execution_ladder(rep)
    attach_resume_action_hints(rep)
    attach_goal_progress_audit(rep)
    print(render_text(rep))
    if args.out:
        _write_json_atomic(args.out, rep)
        print(f"wrote {args.out}")
    return rep


if __name__ == "__main__":
    main()
