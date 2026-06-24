"""Run ONE batch DBTL round from synced HPC artifacts (docs/HPC.md).

Ties the three consume-side adapters into a single command: generate (candidates.jsonl) +
predict (records.jsonl, structure substrate) + screen (verdicts.jsonl) -> the controller routes
via the external calibrated trust gate, screens before synth, scores net = benefit - lambda*
assays, and writes campaign.jsonl + summary.json. This is the LOCAL half of an async HPC round;
the heavy stages produced the JSONL on Cayuga/Expanse (see hpc/). Candidate ids in --candidates
must be covered by --records (predict ran on those candidates) and --verdicts (screened).

Run:
  python -m bio_sfm_designer.experiments.run_batch_round \
    --candidates hpc_outputs/generate/candidates.jsonl \
    --records    hpc_outputs/predict/records.jsonl \
    --verdicts   hpc_outputs/screen/verdicts.jsonl \
    --target "thermostable variant of a benign reporter" --objective thermostability \
    --out results/round_0
"""

from __future__ import annotations

import argparse

from ..config import ObjectiveSpec
from ..generate import PrecomputedGenerator
from ..generate.precomputed import load_candidate_records
from ..loop.controller import DBTLController
from ..predict.structure import PrecomputedStructurePredictor
from ..safety import PrecomputedScreen, SafetyScreen


def run(args) -> "object":
    n = len(load_candidate_records(args.candidates))
    spec = ObjectiveSpec(
        target=args.target, objective=args.objective, lam=args.lam,
        rounds=1, candidates_per_round=max(1, n), assay_budget=args.assay_budget,
    )
    screen = PrecomputedScreen(args.verdicts) if args.verdicts else SafetyScreen()
    provider = None
    if args.provider:
        from bio_sfm_trust import get_provider
        provider = get_provider(args.provider)

    result = DBTLController(
        generator=PrecomputedGenerator(args.candidates),
        predictor=PrecomputedStructurePredictor(args.records),
        screen=screen,
        provider=provider,
    ).run(spec, out_dir=args.out)

    agg = result.aggregate
    print(f"status={result.status} allowed={result.allowed} rounds={result.rounds_run} "
          f"candidates={agg.get('n')} assays_used={result.assays_used}")
    print(f"action mix: trust={agg.get('trust_rate')} verify={agg.get('verify_rate')} "
          f"baseline={agg.get('default_rate')} defer={agg.get('defer_rate')}")
    print(f"net/item={agg.get('net_reward_per_item')}  screen_backend={result.screen_backend}  "
          f"best={result.best}")
    if result.campaign_path:
        print(f"wrote {result.campaign_path} and {result.summary_path}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="run one batch DBTL round from synced HPC artifacts")
    ap.add_argument("--candidates", required=True, help="generate output JSONL (PrecomputedGenerator)")
    ap.add_argument("--records", required=True, help="predict output JSONL (PrecomputedStructurePredictor)")
    ap.add_argument("--verdicts", default=None, help="screen output JSONL (PrecomputedScreen); omit -> built-in screen")
    ap.add_argument("--target", required=True)
    ap.add_argument("--objective", default="stability")
    ap.add_argument("--lam", type=float, default=0.5)
    ap.add_argument("--assay-budget", type=int, default=1000)
    ap.add_argument("--out", default="results/batch_round")
    ap.add_argument("--provider", default=None, help="optional LLM orchestrator: 'anthropic' or 'mock_defer'")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
