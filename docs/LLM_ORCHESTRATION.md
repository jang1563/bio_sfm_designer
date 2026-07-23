# LLM Orchestration

The LLM is an advisory reasoning layer around the DBTL loop. It does not own
trust, safety, budgets, or compute submission.

## Authority contract

After a completed round, the interpreter gives the provider only:

- the screened target and objective text;
- round and assay budgets;
- up to three aggregate round summaries.

It does not send candidate sequences, candidate representations, or hidden
truth. Target text and metrics are marked as untrusted data in the prompt.

The provider must return exactly:

```json
{
  "stop": false,
  "reason": "brief rationale",
  "hypothesis": "one concrete next-round direction",
  "explore": true
}
```

Missing fields, extra fields such as `action` or `trust_sfm`, wrong types,
provider errors, and parse failures are rejected. The deterministic controller
continues or stops under its own rules.

## Modes

- `shadow` is the default. The recommendation is logged but cannot change the
  campaign. This is the mode for the first live experiment.
- `active` may apply early-stop and explore/exploit advice in a multi-round
  controller run. It still runs after hard limits and cannot change any
  `trust_sfm`, `verify_assay`, `default_baseline`, or `defer` decision.

`run_batch_round.py` consumes one asynchronous batch, so its controller always
reaches the one-round limit. The interpreter still makes one shadow call after
that hard stop to recommend what the next separately launched batch should
test. The LLM cannot cause that next batch to run.

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

The current repository state does not itself prove that out-of-band key
rotation has occurred. Until JK confirms P0, only the fixture smoke is
authorized. A failed live response is a provider failure, not permission to
change routing or retry automatically.
