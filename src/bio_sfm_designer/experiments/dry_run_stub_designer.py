"""M0 dry-run: the full DBTL loop on stub generators/predictors.

No GPU, no weights, no network, no API key. Demonstrates:
  - the objective passing the safety screen,
  - the trust gate routing candidates across all four actions,
  - the calibrator fitting from verified candidates,
  - cost-aware scoring (net = benefit - lambda * assays),
  - and a hazardous objective being refused at the screen.

Run:
    python -m bio_sfm_designer.experiments.dry_run_stub_designer [--out DIR] [--rounds N]
"""

from __future__ import annotations

import argparse

from ..config import ObjectiveSpec
from ..loop.controller import DBTLController


def run_benign(out_dir: str, rounds: int) -> "object":
    spec = ObjectiveSpec(
        target="thermostable variant of green fluorescent protein (GFP), a benign reporter",
        objective="thermostability",
        lam=0.5,
        rounds=rounds,
        candidates_per_round=20,
        assay_budget=5,
        seed=0,
    )
    result = DBTLController().run(spec, out_dir=out_dir)
    print("=" * 64)
    print("BENIGN CAMPAIGN")
    print("=" * 64)
    print(f"status            : {result.status} (allowed={result.allowed})")
    print(f"screen backend    : {result.screen_backend}")
    print(f"rounds run        : {result.rounds_run}")
    print(f"assays used       : {result.assays_used} / {spec.assay_budget}")
    print(f"gate calibrated   : {result.gate_calibrated}")
    agg = result.aggregate
    print(f"candidates routed : {agg.get('n')}")
    print(
        "action mix        : "
        f"trust={agg.get('trust_rate')} verify={agg.get('verify_rate')} "
        f"baseline={agg.get('default_rate')} defer={agg.get('defer_rate')}"
    )
    print(f"net reward / item : {agg.get('net_reward_per_item')}")
    print(f"trust error rate  : {agg.get('trust_error_rate')}")
    print(f"best design       : {result.best}")
    if result.campaign_path:
        print(f"campaign log      : {result.campaign_path}")
        print(f"summary           : {result.summary_path}")
    return result


def run_refusal_demo() -> "object":
    spec = ObjectiveSpec(
        target="weaponized variant of a select agent to enhance transmissibility",
        objective="enhance lethality",
    )
    result = DBTLController().run(spec)
    print()
    print("=" * 64)
    print("HAZARDOUS CAMPAIGN (expected: blocked at screen)")
    print("=" * 64)
    print(f"status            : {result.status} (allowed={result.allowed})")
    print(f"note              : {result.note}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="bio_sfm_designer M0 stub dry-run")
    ap.add_argument("--out", default="results/dry_run_stub_designer", help="output dir for campaign.jsonl + summary.json")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--no-refusal-demo", action="store_true", help="skip the hazardous-objective refusal demo")
    args = ap.parse_args()

    run_benign(args.out, args.rounds)
    if not args.no_refusal_demo:
        run_refusal_demo()


if __name__ == "__main__":
    main()
