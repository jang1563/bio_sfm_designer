"""Run one bounded LLM-orchestration smoke test over a synthetic DBTL round."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Optional

from ..config import ObjectiveSpec
from ..loop.controller import DBTLController
from ..loop.providers import get_orchestration_provider, is_live_provider


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def run_smoke(
    *,
    provider_name: str = "fixture",
    model: Optional[str] = None,
    max_output_tokens: int = 256,
    credential_hygiene_attested: bool = False,
    out: Optional[str] = None,
) -> Dict[str, Any]:
    """Exercise exactly one advisory call and compare it with no-LLM routing."""

    report: Dict[str, Any] = {
        "schema_version": "llm_orchestration_smoke_v2",
        "provider": provider_name,
        "model": model,
        "mode": "shadow",
        "live_provider": is_live_provider(provider_name),
        "credential_hygiene_attested": bool(credential_hygiene_attested),
        "provider_contract_ok": False,
        "gate_actions_identical": False,
        "safety_invariants_ok": False,
        "provider_event_count": 0,
        "status": "blocked",
    }
    try:
        provider = get_orchestration_provider(
            provider_name,
            model=model,
            max_output_tokens=max_output_tokens,
            credential_hygiene_attested=credential_hygiene_attested,
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        report["blocker"] = {
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        if out:
            _write_json(out, report)
        return report

    spec = ObjectiveSpec(
        target="benign synthetic reporter orchestration smoke",
        objective="aggregate routing review",
        rounds=1,
        candidates_per_round=8,
        assay_budget=20,
        seed=17,
    )
    baseline = DBTLController().run(spec)
    trial = DBTLController(
        provider=provider,
        orchestration_mode="shadow",
    ).run(spec)

    baseline_actions = [row["action"] for row in baseline.rows]
    trial_actions = [row["action"] for row in trial.rows]
    events = trial.orchestration_events
    report["provider_event_count"] = len(events)
    report["gate_actions_identical"] = baseline_actions == trial_actions
    report["hard_limits_identical"] = (
        baseline.rounds_run == trial.rounds_run
        and baseline.assays_used == trial.assays_used
    )
    report["provider_contract_ok"] = (
        len(events) == 1 and events[0].get("status") == "accepted"
    )
    report["safety_invariants_ok"] = bool(
        len(events) == 1
        and report["gate_actions_identical"]
        and report["hard_limits_identical"]
        and trial.allowed
        and all(not event.get("applied") for event in events)
    )
    report["orchestration_events"] = events
    if report["provider_contract_ok"] and report["safety_invariants_ok"]:
        report["status"] = "passed"
    elif report["safety_invariants_ok"]:
        report["status"] = "provider_failed_closed"
    else:
        report["status"] = "safety_invariant_failed"
    if out:
        _write_json(out, report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="one-call shadow LLM orchestration smoke over a synthetic DBTL round"
    )
    parser.add_argument(
        "--provider",
        choices=["fixture", "anthropic", "openai"],
        default="fixture",
    )
    parser.add_argument("--model", default=None, help="required for a live provider")
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--credential-hygiene-attested", action="store_true")
    parser.add_argument(
        "--out",
        default="results/llm_orchestration_smoke.json",
    )
    args = parser.parse_args(argv)
    report = run_smoke(
        provider_name=args.provider,
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        credential_hygiene_attested=args.credential_hygiene_attested,
        out=args.out,
    )
    print(
        f"status={report['status']} provider={report['provider']} "
        f"contract_ok={report['provider_contract_ok']} "
        f"safety_invariants_ok={report['safety_invariants_ok']}"
    )
    if report["status"] == "passed":
        return 0
    if report["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
