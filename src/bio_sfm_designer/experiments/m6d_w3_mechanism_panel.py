"""Build the bounded M6d W3 third-predictor mechanism panel.

The public artifact contains only identifiers, source metrics, hashes, and the
frozen decision contract. Sequence-bearing ColabFold A3M inputs are written to
an ignored local directory. This module never launches a predictor, scheduler,
network request, or GPU process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_READY_STATUS = "w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit"
_BLOCKED_STATUS = "w3_mechanism_panel_preregistration_blocked"
_W2C_STATUS = "w2c_threshold_learning_terminal_not_supported"
_CHALLENGE_STATUS = "w3_challenge_manifest_ready_no_submit"
_SELECTION_STATUS = "w3_predictor_selection_card_ready_no_submit"
_RUNTIME_STATUS = "w3_runtime_provision_packet_ready_no_submit"
_PREDICTOR_ID = "af2_multimer_colabfold_v1"
_W2C_RANKS = (1, 15, 30, 45, 60)
_AA = frozenset("ACDEFGHIKLMNPQRSTVWY")


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
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            rows.append(row)
    return rows


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _jsonl_text(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _write_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value)


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _failure(
    failures: List[Dict[str, Any]],
    kind: str,
    message: str,
    *,
    expected: Any = None,
    observed: Any = None,
) -> None:
    item: Dict[str, Any] = {"kind": kind, "message": message}
    if expected is not None:
        item["expected"] = expected
    if observed is not None:
        item["observed"] = observed
    failures.append(item)


def _sequence(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an amino-acid sequence")
    sequence = value.strip().upper()
    if not sequence or any(char not in _AA for char in sequence):
        raise ValueError(f"{field} contains unsupported amino-acid characters")
    return sequence


def _label(row: Mapping[str, Any], threshold: float) -> bool:
    return float(row["lrmsd"]) < threshold


def _parse_a3m(text: str) -> List[Tuple[str, str]]:
    records: List[Tuple[str, str]] = []
    header: Optional[str] = None
    sequence: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and header is None):
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence)))
            header = line
            sequence = []
        else:
            if header is None:
                raise ValueError("A3M sequence appeared before its header")
            sequence.append("".join(line.split()))
    if header is not None:
        records.append((header, "".join(sequence)))
    if not records:
        raise ValueError("A3M contains no records")
    return records


def _aligned_sequence(value: str) -> str:
    return "".join(char for char in value if char != "-" and not char.islower()).upper()


def build_annotated_multimer_a3m(target_msa_text: str, target_sequence: str,
                                  binder_sequence: str) -> str:
    """Combine a target MSA with a single-sequence designed binder.

    The first row is the paired query required by ColabFold's annotated complex
    A3M parser. Remaining target rows and the binder query are unpaired. This
    makes no evolutionary pairing claim for a de novo designed binder.
    """
    target_sequence = _sequence(target_sequence, "target_sequence")
    binder_sequence = _sequence(binder_sequence, "binder_sequence")
    target_records = _parse_a3m(target_msa_text)
    if _aligned_sequence(target_records[0][1]) != target_sequence:
        raise ValueError("target MSA query does not match the locked target sequence")
    for header, sequence in target_records:
        aligned_columns = sum(1 for char in sequence if not char.islower())
        if aligned_columns != len(target_sequence):
            raise ValueError(
                f"target MSA row {header} has {aligned_columns} aligned columns; "
                f"expected {len(target_sequence)}"
            )

    lines = [
        f"#{len(target_sequence)},{len(binder_sequence)}\t1,1",
        ">101\t102",
        target_sequence + binder_sequence,
    ]
    binder_gap = "-" * len(binder_sequence)
    for header, sequence in target_records:
        lines.extend((header, sequence + binder_gap))
    lines.extend((">w3_designed_binder_query", "-" * len(target_sequence) + binder_sequence))
    return "\n".join(lines) + "\n"


def _max_prefix_under_cap(rows: Sequence[Mapping[str, Any]], threshold: float,
                          cap: float) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    wrong = 0
    for index, row in enumerate(rows, 1):
        wrong += int(not _label(row, threshold))
        rate = wrong / index
        if rate <= cap:
            best = {
                "accepted": index,
                "false_accepts": wrong,
                "false_accept_rate": rate,
                "tau": float(row["pae_interaction"]),
            }
    return best


def _best_prefix_at_or_above_minimum(
    rows: Sequence[Mapping[str, Any]], threshold: float, minimum: int
) -> Dict[str, Any]:
    candidates: List[Tuple[float, int, int, float]] = []
    wrong = 0
    for index, row in enumerate(rows, 1):
        wrong += int(not _label(row, threshold))
        if index >= minimum:
            candidates.append((wrong / index, index, wrong, float(row["pae_interaction"])))
    rate, accepted, false_accepts, tau = min(candidates)
    return {
        "accepted": accepted,
        "false_accepts": false_accepts,
        "false_accept_rate": rate,
        "tau": tau,
    }


def _w2c_failure_kind(auroc: Optional[float], n_success: int, n_failure: int,
                      minimum_auroc: float) -> str:
    if auroc is None and n_failure == 0:
        return "auroc_undefined_all_success"
    if auroc is None and n_success == 0:
        return "auroc_undefined_all_failure"
    if auroc is None:
        return "auroc_undefined"
    if auroc < minimum_auroc:
        return "auroc_below_floor"
    return "coverage_risk_joint_constraint_failed"


def _validate_top_level_sources(
    w2c_protocol: Mapping[str, Any],
    w2c_report: Mapping[str, Any],
    challenge: Mapping[str, Any],
    selection: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    checks = [
        (w2c_report.get("status"), _W2C_STATUS, "w2c_status_invalid"),
        (w2c_report.get("audit_ok"), True, "w2c_audit_not_ok"),
        (w2c_report.get("terminal_after_threshold_learning"), True, "w2c_not_terminal"),
        (w2c_report.get("n_threshold_candidate_targets"), 0, "w2c_candidates_not_zero"),
        (challenge.get("status"), _CHALLENGE_STATUS, "w3_challenge_status_invalid"),
        (challenge.get("audit_ok"), True, "w3_challenge_audit_not_ok"),
        (challenge.get("no_submit"), True, "w3_challenge_not_no_submit"),
        (selection.get("status"), _SELECTION_STATUS, "w3_selection_status_invalid"),
        (selection.get("audit_ok"), True, "w3_selection_audit_not_ok"),
        (runtime.get("status"), _RUNTIME_STATUS, "w3_runtime_packet_status_invalid"),
        (runtime.get("audit_ok"), True, "w3_runtime_packet_audit_not_ok"),
        (runtime.get("no_submit"), True, "w3_runtime_packet_not_no_submit"),
    ]
    for observed, expected, kind in checks:
        if observed != expected:
            _failure(failures, kind, "source artifact violates the W3 packet boundary",
                     expected=expected, observed=observed)

    selected = selection.get("selected_predictor_protocol")
    observed_predictor = selected.get("predictor_or_protocol_id") if isinstance(selected, dict) else None
    if observed_predictor != _PREDICTOR_ID:
        _failure(failures, "w3_predictor_selection_drift", "selected predictor changed",
                 expected=_PREDICTOR_ID, observed=observed_predictor)

    locked = w2c_protocol.get("locked_scientific_protocol")
    if not isinstance(locked, dict):
        _failure(failures, "w2c_locked_protocol_missing", "W2c locked protocol is missing")
    return failures


def _public_case(private: Mapping[str, Any]) -> Dict[str, Any]:
    keep = (
        "case_id", "panel_index", "panel_block", "panel_role", "source_target_id",
        "complex_target_id", "target_chain", "binder_chain", "pae_order_rank",
        "source_boltz2_pae_interaction", "source_boltz2_lrmsd", "source_boltz2_label",
        "source_chai1_label", "target_sequence_sha256", "binder_sequence_sha256",
        "target_msa_sha256", "reference_backbone_sha256", "a3m_sha256",
    )
    return {key: private.get(key) for key in keep if key in private}


def build_panel(
    *,
    w2c_protocol: Mapping[str, Any],
    w2c_target_manifest: Mapping[str, Any],
    w2c_report: Mapping[str, Any],
    challenge: Mapping[str, Any],
    selection: Mapping[str, Any],
    runtime: Mapping[str, Any],
    challenge_candidates: Sequence[Mapping[str, Any]],
    challenge_boltz_records: Sequence[Mapping[str, Any]],
    challenge_target_msa_text: str,
    challenge_target_msa_sha256: str,
    challenge_reference_path: str,
    challenge_reference_sha256: str,
    w2c_candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    w2c_records: Mapping[str, Sequence[Mapping[str, Any]]],
    w2c_target_msa_texts: Mapping[str, str],
    w2c_reference_sha256: Mapping[str, str],
    private_manifest_path: str,
    input_dir: str,
    report_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, str]]:
    """Build the public packet, private manifest rows, and A3M payloads."""
    failures = _validate_top_level_sources(w2c_protocol, w2c_report, challenge, selection, runtime)
    report_date = report_date or date.today().isoformat()
    locked = w2c_protocol.get("locked_scientific_protocol") or {}
    learning = (locked.get("fit_design") or {}).get("threshold_learning") or {}
    threshold = float(w2c_report.get("lrmsd_threshold", 4.0))
    minimum_accepted = int(learning.get("minimum_accepted", 30))
    minimum_auroc = float(learning.get("minimum_auroc", 0.65))
    risk_cap = float(learning.get("maximum_empirical_false_accept_rate", 0.08))
    observed_challenge_msa_sha = _sha256_text(challenge_target_msa_text)
    if observed_challenge_msa_sha != challenge_target_msa_sha256:
        _failure(
            failures,
            "challenge_target_msa_sha_mismatch",
            "3PC8 target MSA differs from its supplied source lock",
            expected=challenge_target_msa_sha256,
            observed=observed_challenge_msa_sha,
        )

    challenge_rows = challenge.get("rows")
    if not isinstance(challenge_rows, list) or len(challenge_rows) != 18:
        _failure(failures, "challenge_row_count_invalid", "W3 challenge must contain exactly 18 rows",
                 expected=18, observed=len(challenge_rows) if isinstance(challenge_rows, list) else None)
        challenge_rows = []
    role_counts = Counter(row.get("adjudication_role") for row in challenge_rows if isinstance(row, dict))
    expected_roles = {"concordant_success_control": 6, "discordant_boltz_chai_label": 12}
    if dict(sorted(role_counts.items())) != expected_roles:
        _failure(failures, "challenge_role_counts_invalid", "W3 challenge role counts drifted",
                 expected=expected_roles, observed=dict(sorted(role_counts.items())))

    target_rows = w2c_target_manifest.get("targets")
    if not isinstance(target_rows, list) or len(target_rows) != 8:
        _failure(failures, "w2c_target_count_invalid", "W2c panel requires exactly eight targets",
                 expected=8, observed=len(target_rows) if isinstance(target_rows, list) else None)
        target_rows = []
    target_specs = {str(row.get("id")): row for row in target_rows if isinstance(row, dict)}
    report_targets = {
        str(row.get("target_id")): row
        for row in w2c_report.get("targets", [])
        if isinstance(row, dict)
    }
    if sorted(target_specs) != sorted(report_targets):
        _failure(failures, "w2c_target_identity_drift", "W2c manifest and report target sets differ",
                 expected=sorted(target_specs), observed=sorted(report_targets))

    candidate_challenge = {str(row.get("id")): row for row in challenge_candidates}
    boltz_challenge = {str(row.get("target_id")): row for row in challenge_boltz_records}
    private_rows: List[Dict[str, Any]] = []
    a3m_payloads: Dict[str, str] = {}

    for source in challenge_rows:
        source_id = str(source.get("target_id"))
        candidate = candidate_challenge.get(source_id)
        boltz = boltz_challenge.get(source_id)
        if candidate is None or boltz is None:
            _failure(failures, "challenge_source_row_missing", "challenge source candidate or record is missing",
                     observed=source_id)
            continue
        try:
            target_sequence = _sequence(candidate.get("target_seq"), f"{source_id}.target_seq")
            binder_sequence = _sequence(candidate.get("representation"), f"{source_id}.representation")
            source_labels = source.get("source_labels") or {}
            boltz_label = _label(boltz, threshold)
            if source_labels.get("label_a") is not boltz_label:
                raise ValueError("challenge Boltz label does not match the source record")
            a3m = build_annotated_multimer_a3m(
                challenge_target_msa_text, target_sequence, binder_sequence
            )
        except (KeyError, TypeError, ValueError) as exc:
            _failure(failures, "challenge_case_invalid", str(exc), observed=source_id)
            continue
        index = len(private_rows) + 1
        case_id = f"w3m-{index:03d}"
        a3m_path = os.path.join(input_dir, f"{case_id}.a3m")
        row = {
            "case_id": case_id,
            "panel_index": index,
            "panel_block": "boltz_chai_3pc8_challenge",
            "panel_role": source.get("adjudication_role"),
            "source_target_id": source_id,
            "complex_target_id": "3PC8_AB",
            "target_chain": str(boltz.get("target_chain") or "A"),
            "binder_chain": str(boltz.get("binder_chain") or "B"),
            "target_sequence": target_sequence,
            "binder_sequence": binder_sequence,
            "target_sequence_sha256": _sha256_text(target_sequence),
            "binder_sequence_sha256": _sha256_text(binder_sequence),
            "target_msa_path": "hpc_outputs/targets/3PC8_A.a3m",
            "target_msa_sha256": challenge_target_msa_sha256,
            "reference_backbone_path": challenge_reference_path,
            "reference_backbone_sha256": challenge_reference_sha256,
            "a3m_path": a3m_path,
            "a3m_sha256": _sha256_text(a3m),
            "source_boltz2_pae_interaction": float(boltz["pae_interaction"]),
            "source_boltz2_lrmsd": float(boltz["lrmsd"]),
            "source_boltz2_label": boltz_label,
            "source_chai1_label": bool(source_labels.get("label_b")),
        }
        private_rows.append(row)
        a3m_payloads[case_id] = a3m

    w2c_characterization: List[Dict[str, Any]] = []
    for target_id in sorted(target_specs):
        spec = target_specs[target_id]
        candidates = {str(row.get("id")): row for row in w2c_candidates.get(target_id, [])}
        records = list(w2c_records.get(target_id, []))
        if len(candidates) != 60 or len(records) != 60:
            _failure(failures, "w2c_source_count_invalid", "each W2c target requires 60 candidates and records",
                     expected={"candidates": 60, "records": 60},
                     observed={"target_id": target_id, "candidates": len(candidates), "records": len(records)})
            continue
        ordered = sorted(records, key=lambda row: (float(row["pae_interaction"]), str(row["target_id"])))
        record_ids = {str(row.get("target_id")) for row in records}
        if set(candidates) != record_ids:
            _failure(failures, "w2c_candidate_record_identity_mismatch", "candidate and record IDs differ",
                     observed=target_id)
            continue
        n_success = sum(_label(row, threshold) for row in records)
        n_failure = len(records) - n_success
        report_row = report_targets.get(target_id) or {}
        report_learning = report_row.get("learning") or {}
        auroc = report_learning.get("auroc_pae")
        max_under_cap = _max_prefix_under_cap(ordered, threshold, risk_cap)
        best_minimum = _best_prefix_at_or_above_minimum(ordered, threshold, minimum_accepted)
        characterization = {
            "target_id": target_id,
            "n_records": len(records),
            "n_success": n_success,
            "n_failure": n_failure,
            "success_rate": n_success / len(records),
            "auroc_pae": auroc,
            "protocol_decision": report_learning.get("mode"),
            "protocol_candidate": report_learning.get("candidate"),
            "failure_kind": _w2c_failure_kind(auroc, n_success, n_failure, minimum_auroc),
            "largest_prefix_at_or_below_risk_cap": max_under_cap,
            "best_prefix_at_or_above_minimum_accepted": best_minimum,
        }
        w2c_characterization.append(characterization)

        target_msa_text = w2c_target_msa_texts.get(target_id)
        if not isinstance(target_msa_text, str):
            _failure(failures, "w2c_target_msa_missing", "target MSA text is missing", observed=target_id)
            continue
        observed_target_msa_sha = _sha256_text(target_msa_text)
        if observed_target_msa_sha != spec.get("target_msa_sha256"):
            _failure(
                failures,
                "w2c_target_msa_sha_mismatch",
                "W2c target MSA differs from the target-manifest lock",
                expected=spec.get("target_msa_sha256"),
                observed={"target_id": target_id, "sha256": observed_target_msa_sha},
            )
            continue
        for rank in _W2C_RANKS:
            boltz = ordered[rank - 1]
            source_id = str(boltz["target_id"])
            candidate = candidates[source_id]
            try:
                target_sequence = _sequence(candidate.get("target_seq"), f"{source_id}.target_seq")
                binder_sequence = _sequence(candidate.get("representation"), f"{source_id}.representation")
                if binder_sequence != _sequence(boltz.get("representation"), f"{source_id}.record_representation"):
                    raise ValueError("candidate and record binder sequences differ")
                if _sha256_text(target_sequence) != spec.get("target_sequence_sha256"):
                    raise ValueError("target sequence hash differs from the W2c target manifest")
                a3m = build_annotated_multimer_a3m(target_msa_text, target_sequence, binder_sequence)
            except (KeyError, TypeError, ValueError) as exc:
                _failure(failures, "w2c_case_invalid", str(exc), observed=source_id)
                continue
            index = len(private_rows) + 1
            case_id = f"w3m-{index:03d}"
            a3m_path = os.path.join(input_dir, f"{case_id}.a3m")
            row = {
                "case_id": case_id,
                "panel_index": index,
                "panel_block": "w2c_pae_order_statistics",
                "panel_role": "fixed_pae_order_statistic",
                "source_target_id": source_id,
                "complex_target_id": target_id,
                "target_chain": str(spec.get("target_chain")),
                "binder_chain": str(spec.get("binder_chain")),
                "pae_order_rank": rank,
                "target_sequence": target_sequence,
                "binder_sequence": binder_sequence,
                "target_sequence_sha256": _sha256_text(target_sequence),
                "binder_sequence_sha256": _sha256_text(binder_sequence),
                "target_msa_path": str(spec.get("target_msa")),
                "target_msa_sha256": str(spec.get("target_msa_sha256")),
                "reference_backbone_path": str(spec.get("prepared_pdb")),
                "reference_backbone_sha256": w2c_reference_sha256[target_id],
                "a3m_path": a3m_path,
                "a3m_sha256": _sha256_text(a3m),
                "source_boltz2_pae_interaction": float(boltz["pae_interaction"]),
                "source_boltz2_lrmsd": float(boltz["lrmsd"]),
                "source_boltz2_label": _label(boltz, threshold),
            }
            private_rows.append(row)
            a3m_payloads[case_id] = a3m

    if len(private_rows) != 58:
        _failure(failures, "panel_case_count_invalid", "combined W3 panel must contain exactly 58 cases",
                 expected=58, observed=len(private_rows))
    block_counts = dict(sorted(Counter(row["panel_block"] for row in private_rows).items()))
    expected_blocks = {"boltz_chai_3pc8_challenge": 18, "w2c_pae_order_statistics": 40}
    if block_counts != expected_blocks:
        _failure(failures, "panel_block_counts_invalid", "combined W3 panel block counts drifted",
                 expected=expected_blocks, observed=block_counts)

    private_text = _jsonl_text(private_rows)
    public_rows = [_public_case(row) for row in private_rows]
    runtime_ready = runtime.get("runtime_ready") is True
    audit_ok = not failures
    packet: Dict[str, Any] = {
        "artifact": "m6d_w3_decisive_mechanism_panel_protocol",
        "version": 1,
        "date": report_date,
        "status": _READY_STATUS if audit_ok else _BLOCKED_STATUS,
        "audit_ok": audit_ok,
        "failures": failures,
        "scientific_question": (
            "Does the W2c divergence between pAE ranking and protocol-usable selective coverage "
            "reflect reproducible target/coverage heterogeneity, or predictor/protocol label instability "
            "of the kind exposed by the Boltz-Chai disagreement?"
        ),
        "selection_lock": {
            "selection_uses_outcome_labels": False,
            "three_pc8_panel": "preserve all 18 previously frozen challenge rows unchanged",
            "w2c_order": "sort within target by (pae_interaction ascending, target_id ascending)",
            "w2c_fixed_one_based_ranks": list(_W2C_RANKS),
            "w2c_targets": sorted(target_specs),
            "n_three_pc8_cases": 18,
            "n_w2c_cases": 40,
            "n_total_cases": 58,
        },
        "w2c_locked_constraints": {
            "lrmsd_threshold": threshold,
            "minimum_accepted": minimum_accepted,
            "minimum_auroc": minimum_auroc,
            "maximum_empirical_false_accept_rate": risk_cap,
            "minimum_selective_targets_required": w2c_report.get("minimum_selective_targets_required"),
            "observed_threshold_candidate_targets": w2c_report.get("n_threshold_candidate_targets"),
        },
        "w2c_characterization": {
            "n_targets": len(w2c_characterization),
            "failure_kinds": dict(sorted(Counter(row["failure_kind"] for row in w2c_characterization).items())),
            "targets": w2c_characterization,
            "interpretation_boundary": (
                "These are descriptive diagnostics of the completed W2c learning set. They do not "
                "retune, rescue, reopen, or authorize W2c."
            ),
        },
        "predictor_protocol": {
            "predictor_or_protocol_id": _PREDICTOR_ID,
            "implementation": "ColabFold",
            "required_version": "1.6.1",
            "model_type": "alphafold2_multimer_v3",
            "models": 5,
            "total_ranked_model_evaluations": 290,
            "seeds": 1,
            "random_seed": 0,
            "recycles": 20,
            "rank_by": "multimer",
            "relax_models": 0,
            "templates": False,
            "msa_policy": {
                "target": "reuse the existing hash-locked target MSA",
                "designed_binder": "single-sequence query only",
                "evolutionary_pairing": "paired query row only; no paired homolog rows",
                "public_msa_server": "forbidden",
                "network_access_during_prediction": "forbidden",
            },
            "container_candidate": "ghcr.io/sokrypton/colabfold:1.6.1-cuda12",
            "container_digest_required_before_execution": True,
            "weights_must_exist_locally_before_execution": True,
        },
        "decision_contract": {
            "label": "lrmsd_to_reference < 4.0 Angstrom after target-chain alignment",
            "three_pc8": {
                "discordant_rows": 12,
                "controls": 6,
                "boltz_supported_if": "at least 10/12 discordant labels align with Boltz and at least 5/6 controls succeed",
                "chai_supported_if": "at least 10/12 discordant labels align with Chai and at least 5/6 controls succeed",
                "otherwise": "mixed_or_contract_blocked",
            },
            "w2c": {
                "rows": 40,
                "targets": 8,
                "boltz_supported_if": "at least 32/40 labels agree globally and at least 6/8 targets have at least 4/5 agreement",
                "strong_instability_if": "at most 24/40 labels agree globally or at most 3/8 targets have at least 4/5 agreement",
                "otherwise": "mixed",
                "threshold_rationale": (
                    "0.80 reuses the preregistered minimum cross-predictor label agreement; 0.60 "
                    "marks agreement no better than the observed Boltz-Chai result."
                ),
            },
            "joint_outcomes": [
                {
                    "outcome": "boltz_supported_target_or_coverage_mechanism",
                    "if": "3PC8 is Boltz-supported and W2c is Boltz-supported",
                },
                {
                    "outcome": "predictor_protocol_disagreement_dominant",
                    "if": "3PC8 is Chai-supported and W2c shows strong instability",
                },
                {
                    "outcome": "context_dependent_or_unresolved",
                    "if": "the two blocks disagree, either block is mixed, controls fail, or any contract check fails",
                },
            ],
            "claim_scope": "bounded challenge-panel mechanism adjudication only; not population-level independent-predictor robustness",
        },
        "execution_packet": {
            "private_manifest": private_manifest_path,
            "private_manifest_sha256": _sha256_text(private_text),
            "input_dir": input_dir,
            "inputs_emitted": audit_ok,
            "n_inputs": len(private_rows),
            "command_wrapper": "hpc/run_w3_mechanism_panel_guarded.sh",
            "runtime_validation_wrapper": "hpc/validate_w3_mechanism_runtime.sh",
            "runtime_receipt_builder": "hpc/prepare_w3_mechanism_runtime_receipt.py",
            "runtime_receipt": "results/m6d_w3_mechanism_runtime_receipt.json",
            "output_dir": "hpc_outputs/m6d_w3_mechanism_panel_af2",
            "output_converter": "hpc/convert_colabfold_mechanism_panel.py",
            "conversion_report": "results/m6d_w3_mechanism_panel_af2_conversion.json",
            "records_output": "results/m6d_w3_mechanism_panel_af2_records.jsonl",
            "adjudicator": "bio_sfm_designer.experiments.m6d_w3_mechanism_adjudication",
            "adjudication_output": "results/m6d_w3_mechanism_panel_adjudication.json",
            "approval_env_var": "BIO_SFM_APPROVE_W3_MECHANISM_PANEL",
            "approval_env_value": "approve-w3-mechanism-panel-h100",
            "approval_recorded": False,
            "approval_consumed": False,
            "runtime_ready": runtime_ready,
            "execution_ready": False,
            "no_submit": True,
            "no_gpu_compute": True,
            "no_api_spend": True,
            "no_network_fetch": True,
            "blockers": [
                "validated ColabFold 1.6.1 runtime receipt with an immutable image or binary identity is required",
                "local AlphaFold2-Multimer weights must be verified before execution",
                "a separate exact approval is required before any H100/GPU/HPC execution",
            ],
        },
        "public_safety": {
            "raw_sequences_in_public_packet": False,
            "absolute_paths_in_public_packet": False,
            "credentials_or_secrets_in_public_packet": False,
            "nonsecret_approval_literal_in_public_packet": True,
            "sequence_identity_bound_by_sha256": True,
            "sequence_bearing_inputs_are_gitignored": True,
        },
        "rows": public_rows,
        "source_bindings": {
            "w2c_protocol_digest": _canonical_digest(w2c_protocol),
            "w2c_report_digest": _canonical_digest(w2c_report),
            "w3_challenge_digest": _canonical_digest(challenge),
            "w3_predictor_selection_digest": _canonical_digest(selection),
            "w3_runtime_packet_digest": _canonical_digest(runtime),
        },
        "can_claim_independent_predictor_robustness_now": False,
        "can_claim_w2c_rescue_now": False,
        "claim_boundary": (
            "Preregistered no-submit mechanism panel only. No AF2 prediction has run, W2c remains "
            "terminal, and no positive independent-predictor robustness claim is supported."
        ),
    }
    return packet, private_rows, a3m_payloads


def render_markdown(packet: Mapping[str, Any]) -> str:
    characterization = packet.get("w2c_characterization") or {}
    lines = [
        "# M6d W3 decisive mechanism panel",
        "",
        f"Status: `{packet.get('status')}`.",
        "",
        "## Scientific question",
        "",
        str(packet.get("scientific_question")),
        "",
        "## What the completed W2c run actually showed",
        "",
        "| Target | Successes | Failures | pAE AUROC | Refusal mechanism | Largest prefix at FAR <= 0.08 |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for row in characterization.get("targets", []):
        auroc = "NA" if row.get("auroc_pae") is None else f"{float(row['auroc_pae']):.3f}"
        prefix = row.get("largest_prefix_at_or_below_risk_cap")
        accepted = 0 if prefix is None else int(prefix["accepted"])
        lines.append(
            f"| {row['target_id']} | {row['n_success']} | {row['n_failure']} | {auroc} | "
            f"`{row['failure_kind']}` | {accepted} |"
        )
    lines.extend([
        "",
        "W2c remains closed. These diagnostics characterize why the frozen rule refused each target; they do not retune it.",
        "",
        "## Frozen panel",
        "",
        "- 18 existing 3PC8 challenge cases: 12 Boltz-Chai discordances and 6 concordant-success controls.",
        "- 40 W2c mechanism cases: ranks 1, 15, 30, 45, and 60 after deterministic within-target pAE sorting for each of 8 targets.",
        "- Total: 58 distinct AF2-Multimer inputs. Outcome labels are not used for W2c row selection.",
        "",
        "## Predictor protocol",
        "",
        "- ColabFold 1.6.1 with `alphafold2_multimer_v3`, five models, one seed, 20 recycles, no relaxation.",
        "- Existing target MSAs are hash-locked and reused. Designed binders receive single-sequence rows only.",
        "- Templates, public MSA-server requests, and prediction-time network access are forbidden.",
        "- Official implementation references: [ColabFold repository](https://github.com/sokrypton/ColabFold), "
        "[ColabFold 1.6.1 input parser](https://github.com/sokrypton/ColabFold/blob/v1.6.1/colabfold/input.py), and "
        "[ColabFold 1.6.1 batch CLI](https://github.com/sokrypton/ColabFold/blob/v1.6.1/colabfold/batch.py).",
        "",
        "## Preregistered adjudication",
        "",
        "- 3PC8 Boltz support: at least 10/12 discordant rows align with Boltz and at least 5/6 controls succeed.",
        "- 3PC8 Chai support: at least 10/12 discordant rows align with Chai and at least 5/6 controls succeed.",
        "- W2c Boltz support: at least 32/40 global label agreement and at least 6/8 targets with at least 4/5 agreement.",
        "- W2c strong instability: at most 24/40 global agreement or at most 3/8 targets with at least 4/5 agreement.",
        "- All other valid outcomes are mixed; any contract failure is blocked.",
        "",
        "## Execution boundary",
        "",
        "This is a no-submit packet. It records no approval and performs no API, network, GPU, or HPC action. "
        "The guarded wrapper requires a separately supplied exact approval token, a validated immutable runtime receipt, "
        "local model weights, and exact input hashes before it can invoke ColabFold.",
        "",
        "## Claim boundary",
        "",
        str(packet.get("claim_boundary")),
        "",
    ])
    return "\n".join(lines)


def _path_sha(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return _sha256_file(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the no-submit W3 mechanism panel")
    parser.add_argument("--w2c-protocol", default="configs/m6d_w2c_one_shot_protocol.json")
    parser.add_argument("--w2c-target-manifest", default="configs/m6d_w2c_fit_learn_targets.json")
    parser.add_argument("--w2c-report", default="results/m6d_w2c_threshold_learning_report.json")
    parser.add_argument("--w3-challenge", default="results/m6d_w3_challenge_manifest.json")
    parser.add_argument("--w3-selection", default="results/m6d_w3_predictor_selection_card.json")
    parser.add_argument("--w3-runtime", default="results/m6d_w3_runtime_provision_packet.json")
    parser.add_argument(
        "--challenge-candidates",
        default="hpc_outputs/m6d_followup_3PC8_AB_scale_t030/candidates_proteinmpnn_complex_t030.jsonl",
    )
    parser.add_argument(
        "--challenge-records",
        default="hpc_outputs/m6d_followup_3PC8_AB_scale_t030/records_boltz_complex_t030.jsonl",
    )
    parser.add_argument("--challenge-target-msa", default="hpc_outputs/targets/3PC8_A.a3m")
    parser.add_argument("--challenge-reference", default="hpc_outputs/targets/prepared_3PC8_AB.pdb")
    parser.add_argument("--private-manifest", default="results/m6d_w3_mechanism_panel_inputs.jsonl")
    parser.add_argument("--input-dir", default="results/m6d_w3_mechanism_panel_inputs/a3m")
    parser.add_argument("--out-json", default="configs/m6d_w3_mechanism_panel_protocol.json")
    parser.add_argument("--out-md", default="docs/M6D_W3_MECHANISM_PANEL.md")
    parser.add_argument("--date", default=None)
    args = parser.parse_args(argv)

    target_manifest = _load_json(args.w2c_target_manifest)
    w2c_candidates: Dict[str, List[Dict[str, Any]]] = {}
    w2c_records: Dict[str, List[Dict[str, Any]]] = {}
    w2c_msas: Dict[str, str] = {}
    w2c_references: Dict[str, str] = {}
    for spec in target_manifest.get("targets", []):
        target_id = str(spec["id"])
        w2c_candidates[target_id] = _load_jsonl(str(spec["candidates"]))
        w2c_records[target_id] = _load_jsonl(str(spec["records"]))
        with open(str(spec["target_msa"])) as handle:
            w2c_msas[target_id] = handle.read()
        w2c_references[target_id] = _path_sha(str(spec["prepared_pdb"]))

    with open(args.challenge_target_msa) as handle:
        challenge_msa = handle.read()
    packet, private_rows, a3m_payloads = build_panel(
        w2c_protocol=_load_json(args.w2c_protocol),
        w2c_target_manifest=target_manifest,
        w2c_report=_load_json(args.w2c_report),
        challenge=_load_json(args.w3_challenge),
        selection=_load_json(args.w3_selection),
        runtime=_load_json(args.w3_runtime),
        challenge_candidates=_load_jsonl(args.challenge_candidates),
        challenge_boltz_records=_load_jsonl(args.challenge_records),
        challenge_target_msa_text=challenge_msa,
        challenge_target_msa_sha256=_path_sha(args.challenge_target_msa),
        challenge_reference_path=args.challenge_reference,
        challenge_reference_sha256=_path_sha(args.challenge_reference),
        w2c_candidates=w2c_candidates,
        w2c_records=w2c_records,
        w2c_target_msa_texts=w2c_msas,
        w2c_reference_sha256=w2c_references,
        private_manifest_path=args.private_manifest,
        input_dir=args.input_dir,
        report_date=args.date,
    )
    if not packet["audit_ok"]:
        _write_json(args.out_json, packet)
        _write_text(args.out_md, render_markdown(packet))
        return 2

    os.makedirs(args.input_dir, exist_ok=True)
    expected_names = {f"{case_id}.a3m" for case_id in a3m_payloads}
    for existing in Path(args.input_dir).glob("*.a3m"):
        if existing.name not in expected_names:
            existing.unlink()
    for case_id, payload in a3m_payloads.items():
        _write_text(os.path.join(args.input_dir, f"{case_id}.a3m"), payload)
    _write_text(args.private_manifest, _jsonl_text(private_rows))
    _write_json(args.out_json, packet)
    _write_text(args.out_md, render_markdown(packet))
    print(
        f"wrote public W3 packet with {len(packet['rows'])} hash-only rows; "
        f"no predictor or scheduler was invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
