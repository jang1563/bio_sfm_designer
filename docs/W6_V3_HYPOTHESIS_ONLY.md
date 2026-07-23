# W6-v3 Hypothesis-Only Orchestration

## Decision

The W6-v2 live shadow panel rejected LLM ownership of branch decisions. Its
16/16 responses were structurally valid and qualitatively useful, but exact
`stop/explore` pairs were correct in only 8/16. W6-v3 therefore removes both
fields from the provider contract.

Deterministic code now owns:

- stop versus continue;
- explore versus exploit;
- trust and verification routing;
- safety triage;
- assay and compute budgets;
- submission, retry, and execution.

The provider may return only:

```json
{
  "reason": "brief evidence-grounded rationale",
  "hypothesis": "one concrete candidate-strategy or evidence direction"
}
```

Any `stop`, `explore`, routing, threshold, calibration, alpha, lambda, safety,
budget, or execution field is rejected. The prompt includes the deterministic
decision as immutable state so the model is not asked to infer it.

## Runtime change

`loop/interpreter.py` now uses the hypothesis-only v3 contract. `shadow` records
a proposal and applies nothing. `active` may surface only the accepted
hypothesis in campaign history; it cannot change stop, exploration, routing,
budgets, safety, or compute. The historical v2 validator remains solely so the
frozen W6-v2 evidence can be replayed exactly.

## Frozen offline panel

The v3 contract reuses the exact 16 W2-W4 aggregate states from W6-v2 and binds
their source panel, evidence, request packet, synthetic fixtures, and prior live
review by SHA-256.

| Check | Valid synthetic replay | Adversarial replay |
|---|---:|---:|
| Cases | 16 | 16 |
| Exact schema accepted | 16/16 | 5/16 |
| Authority violations | 0 | 9 |
| Grounded | 16/16 | 2/16 |
| Actionable | 16/16 | 9/16 |
| Incremental value | 9/16 | 1/16 |
| Applied recommendations | 0 | 0 |
| Result | pass | fail |

No stop/explore accuracy is scored because those decisions are no longer model
outputs.

## Post-hoc live replay

The consumed W6-v2 Anthropic responses were reduced mechanically by removing
`stop` and `explore` while preserving the exact `reason`, `hypothesis`, and
provider-independent review. The reduced outputs pass the v3 contract:

- schema acceptance: 16/16;
- authority violations: 0;
- grounded and actionable: 16/16;
- incremental value: 9/16;
- applied recommendations: 0.

This result is **development evidence only**. The v3 contract was defined after
observing W6-v2, so the replay is explicitly:

- `prospective_validation=false`;
- `independent_evidence=false`;
- `deployment_authorized=false`;
- `future_provider_calls_authorized=false`.

It cannot complete M7 or justify a live provider call. The 16-call W6-v2
approval remains consumed.

## Reproduce offline

```bash
python -m bio_sfm_designer.experiments.w6_v3_hypothesis_only \
  --repo-root . freeze

python -m bio_sfm_designer.experiments.w6_v3_hypothesis_only \
  bind-reduced-v2-fixture \
  --v2-specs tests/fixtures/w6_v2_shadow_panel_valid_response_specs.json \
  --out tests/fixtures/w6_v3_hypothesis_only_valid_responses.jsonl

python -m bio_sfm_designer.experiments.w6_v3_hypothesis_only \
  --repo-root . score \
  --responses tests/fixtures/w6_v3_hypothesis_only_valid_responses.jsonl \
  --out results/w6_v3_hypothesis_only_valid_replay.json
```

The post-hoc command additionally requires the ignored, local, hash-bound
W6-v2 reviewed-response JSONL:

```bash
python -m bio_sfm_designer.experiments.w6_v3_hypothesis_only \
  --repo-root . post-hoc-live
```

All commands above make zero provider calls and submit zero compute.

## Frozen artifacts

| Artifact | SHA-256 |
|---|---|
| `configs/w6_v3_hypothesis_only_contract.json` | `0435ff8e82842c6feba9e4ecb54f2dce8d39d380ea7b1f81b0364ac84105f7ad` |
| `results/w6_v3_hypothesis_only_requests.jsonl` | `ce7de81e2685a1ea02468b1125d8d0f0f09f33b2d99a9ac70212b4863831c8f8` |
| `results/w6_v3_hypothesis_only_freeze.json` | `e325570874add5de4670c9cba1e420e855c96c40c6843eba9a0e64eabda7a2c2` |
| `results/w6_v3_hypothesis_only_valid_replay.json` | `e25c317a66ef8433cce77395381769a5fe9588f83d84ccec7dc8d0ee6d9a697d` |
| `results/w6_v3_hypothesis_only_adversarial_replay.json` | `945f0ec41ddbdd1b731f27cb2580ef68e95b9b7a17164b0f8575939bebf52d58` |
| `results/w6_v3_post_hoc_development_replay.json` | `2e97e51a01d36bfe325367c80bb7802de5623618a2e80028a8cdaa7a8f1a2e06` |

## Next evidence gate

The next valid test would be a new, independently frozen, prospective
hypothesis-only live panel with exact provider, model, call count, and output
budget approval. It must not reuse W6-v2 as its test set. Until then, v3 remains
offline-qualified and unvalidated for prospective live use.
