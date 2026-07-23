# LLM Orchestration

The LLM is a hypothesis-only advisory layer around the DBTL loop. It does not
own stop/explore, trust, safety, budgets, routing, or compute submission.

## Authority contract

After a completed round, the interpreter gives the provider only:

- the screened target and objective text;
- round and assay budgets;
- up to three aggregate round summaries.

It does not send candidate sequences, candidate representations, or hidden
truth. Target text and metrics are marked as untrusted data in the prompt.

The deterministic controller's stop decision and the operator-owned
exploration setting are included as immutable prompt state. The provider must
return exactly:

```json
{
  "reason": "brief rationale",
  "hypothesis": "one concrete next-round direction"
}
```

Missing fields, extra fields including `stop`, `explore`, `action`, or
`trust_sfm`, provider errors, and parse failures are rejected. Contract v3
retains the fail-closed lexical guard for explicit attempts to change gate
thresholds, calibration, conformal alpha, lambda, routing policy, assay
budgets, or safety policy. Evidence collection and candidate strategy remain
valid proposal scope. This bounded guard is not proof that every indirect
semantic paraphrase can be detected.

## Modes

- `shadow` is the default. The hypothesis is logged but cannot change the
  campaign. This is the mode for the first live experiment.
- `active` may surface only an accepted hypothesis in campaign history. It
  cannot change stop, exploration, `trust_sfm`, `verify_assay`,
  `default_baseline`, `defer`, budgets, or execution.

Built-in Anthropic and OpenAI providers are restricted to `shadow`; `active`
remains available only for offline/custom-provider experiments.

`run_batch_round.py` consumes one asynchronous batch, so its controller always
reaches the one-round limit. The interpreter may still request one hypothesis
for a separately reviewed successor. The LLM cannot cause that successor to
run.

## Audit

When a provider is configured, the controller writes:

- `campaign.jsonl`: authoritative per-candidate gate decisions;
- `summary.json`: orchestration mode and accepted-event count;
- `orchestration.jsonl`: prompt, raw response, SHA-256 hashes, provider/model,
  parse status, hard-stop state, recommendation, and applied fields.

API keys are read by the provider SDK and are never written to these artifacts.
Provider exceptions log only the exception class and numeric HTTP status.
The OpenAI adapter requests `store=false`.

## Offline smoke

This exercises the full provider boundary with a deterministic fixture and
proves that gate actions and hard limits are byte-identical to a no-LLM run:

```bash
python -m bio_sfm_designer.experiments.llm_orchestration_smoke \
  --provider fixture \
  --out results/llm_orchestration_smoke.json
```

## W6-v2 frozen offline panel

The one-state smoke is complemented by a 16-case W2-W4 panel that freezes
aggregate scientific decision states, expected stop/explore behavior, allowed
evidence scopes, forbidden authority, and a review rubric. Its freeze, fixture
binding, and scoring code has no provider path and runs with the network
blocked. Valid and adversarial synthetic replays prove the evaluator accepts
the exact contract and rejects malformed, unsafe, inconsistent, or
non-actionable behavior.

See [`W6_V2_FROZEN_SHADOW_PANEL.md`](W6_V2_FROZEN_SHADOW_PANEL.md). This is an
offline harness result, not a live-model evaluation, permission for provider
calls, or M7 completion.

## Live shadow smoke

Live providers are deliberately blocked unless P0 credential hygiene has been
completed and explicitly attested for that invocation. A model id is always
explicit; the code does not silently drift to a provider default.

```bash
pip install -e ".[dev,llm-anthropic]"
python -m bio_sfm_designer.experiments.llm_orchestration_smoke \
  --provider anthropic \
  --model <explicit-model-id> \
  --credential-hygiene-attested \
  --out results/llm_orchestration_smoke_anthropic.json
```

The OpenAI adapter uses the same contract with `.[llm-openai]` and
`--provider openai`. Each smoke invocation makes at most one provider call with
at most 1,024 output tokens; the default is 256. Provider SDK retries are
disabled for this smoke path.

JK attested P0 credential hygiene completion and authorized one Anthropic
shadow call on 2026-07-23. The call passed transport, structural JSON, routing
equivalence, and no-effect checks, but failed semantic authority review because
the model recommended changing the trust threshold. Shadow mode prevented any
effect. The exact bounded result and hashes are recorded in
[`LLM_ORCHESTRATION_LIVE_SMOKE_2026_07_23.md`](LLM_ORCHESTRATION_LIVE_SMOKE_2026_07_23.md).

That one-call approval is consumed. Contract v2 was hardened offline; another
live invocation requires a new explicit approval. A failed or semantically
invalid response is not permission to change routing or retry automatically.

## W6-v2 live panel result

A separately approved 16-call Anthropic `claude-opus-4-8` shadow panel ran on
the frozen W6-v2 requests on 2026-07-23. All calls succeeded with zero retries,
all 16 responses passed the exact schema, and zero control-plane mutations were
detected. Shadow mode applied nothing.

The model failed the preregistered branch-decision contract: stop accuracy was
0.6875, explore accuracy 0.75, and exact pair accuracy 0.50. Provider-independent
offline review still found all recommendations grounded and actionable, with
incremental value in 9/16. This supports a narrower hypothesis-generation role,
not live ownership of stop/explore. See
[`W6_V2_LIVE_SHADOW_PANEL_2026_07_23.md`](W6_V2_LIVE_SHADOW_PANEL_2026_07_23.md).
The 16-call approval is consumed; no retry or additional call is authorized.

## W6-v3 hypothesis-only successor

W6-v3 removes `stop` and `explore` from both the runtime provider contract and
the offline evaluator. Its frozen 16-case valid synthetic replay passes 16/16
with zero authority violations; the adversarial replay accepts only 5/16 and
records nine authority violations.

Mechanically reducing the already consumed W6-v2 live outputs to
`reason+hypothesis` also passes the v3 qualitative contract: all 16 are grounded
and actionable, with incremental value in 9/16. That is explicitly post-hoc,
non-independent development evidence, not prospective validation. It
authorizes no API call, deployment, or M7 completion. See
[`W6_V3_HYPOTHESIS_ONLY.md`](W6_V3_HYPOTHESIS_ONLY.md).
