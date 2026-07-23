# Architecture

`bio_sfm_designer` wraps a DBTL loop around an **external calibrated trust gate**. Claude
orchestrates (plans the next round, interprets results); the gate — not Claude — decides
whether each candidate is trusted, verified, replaced by a baseline, or deferred.

## The loop (one round)

```
                 ┌──────────────────────────────────────────────────────────┐
                 │                  ObjectiveSpec (target, λ, budgets)         │
                 └───────────────────────────┬──────────────────────────────┘
                                             │
              ┌──────────────────────────────▼──────────────────────────────┐
   round 0    │  SAFETY SCREEN (objective)   safety/screen.py + policy.py      │
   only       │  refuse | route_expert | clarify | allow                       │
              └──────────────────────────────┬──────────────────────────────┘
                                  allow       │
   ┌──────────────────────────────────────────▼─────────────────────────────────┐
   │ DESIGN     generate/   Generator.propose(spec, round, n, parents)            │
   │ BUILD      (materialize candidate; no-op in M0)                              │
   │ TEST       predict/    Predictor.predict(cand) -> Prediction(value, raw_conf,│
   │                         regime, baseline_value)         [truth HIDDEN]       │
   │ ROUTE      trust/gate.py  TrustGate.route(prediction, λ)                     │
   │              risk = confidence_to_risk(...)  ->  isotonic-calibrated          │
   │              ┌───────────────────────────────────────────────────────────┐ │
   │              │ calibrated_risk > λ            -> verify_assay              │ │
   │              │ disagrees with cheap baseline  -> default_baseline          │ │
   │              │ no baseline & risk non-trivial -> defer                     │ │
   │              │ else                           -> trust_sfm                 │ │
   │              └───────────────────────────────────────────────────────────┘ │
   │ BUDGET     cap verify_assay at assay_budget (overflow -> baseline/defer)     │
   │ SCREEN     safety/screen.py on any advancing candidate (pre-synth)           │
   │ CALIBRATE  verify_assay reveals truth -> gate.observe_verified -> refit       │
   │ SCORE      scoring/objective.py  net = benefit − λ·assays  (bio_sfm_trust)    │
   │ LEARN      loop/planner.py picks parents; loop/interpreter.py: stop?          │
   └──────────────────────────────────┬──────────────────────────────────────────┘
                                       │ iterate until rounds / budget / convergence
                                       ▼
                            campaign.jsonl + summary.json
```

## Where each SFM plugs in

| Stage | Interface | M0 (now) | Later |
|---|---|---|---|
| Generate | `generate.Generator` | `StubGenerator` | ProteinMPNN / RFdiffusion / ESM |
| Predict | `predict.Predictor` | `StubPredictor` | Boltz-2 / pLDDT (M1), property heads |
| Trust | `bio_sfm_trust` (calibration, gate, scoring) | wired, calibrates from verified data | same engine on real records |
| Safety | `safety.SafetyScreen` | built-in lexicon + policy | constitutional-bioguard DeBERTa + FRT label-integrity (M2) |
| Orchestrate | `loop.Planner` / `loop.Interpreter` | deterministic rules + fixture shadow provider | optional Anthropic/OpenAI provider adapters behind the same strict contract |

## LLM authority boundary

The provider is called only after routing, safety checks, budget enforcement,
calibration, and round scoring. It receives aggregate summaries, not candidate
sequences or hidden truth. Its exact JSON recommendation can contain only
`stop`, `reason`, `hypothesis`, and `explore`.

`shadow` mode is the default and records the recommendation without applying
it. `active` mode may affect only early stopping and next-round parent
diversity, after deterministic hard limits. Unknown fields, malformed output,
or provider errors fall back to the deterministic decision. Every provider call
is written to `orchestration.jsonl` with request/response hashes and an explicit
list of applied fields. See [`LLM_ORCHESTRATION.md`](LLM_ORCHESTRATION.md).

## Leakage discipline

`Prediction.truth` (whether the SFM was right, the realized quality) is **hidden from the
gate** and used only by the scorer — exactly what a real `verify_assay` would reveal. The
gate routes on the visible surface only; calibration data comes solely from candidates that
were actually verified.
