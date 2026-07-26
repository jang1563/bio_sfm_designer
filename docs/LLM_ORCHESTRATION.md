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

## W6-v3 independent prospective result

On 2026-07-24, 16 newly written counterfactual states were frozen as an
independent prospective panel. Validation excludes every W6-v2 case/source and
directly proves zero canonical aggregate-state hash overlap. The valid offline
fixture passed 16/16 with zero authority violations; the adversarial fixture
accepted 3/16 and detected eight violations.

A hash-bound one-shot Anthropic `claude-opus-4-8` scope then consumed exactly
16 calls with 256 maximum output tokens per call and zero retries. All calls
returned and none attempted to mutate deterministic decisions or the control
plane. Provider-independent review found grounded/actionable 16/16 and
incremental value 12/16. The live contract still failed because five responses
ended mid-JSON, leaving schema acceptance at 11/16 instead of the required
16/16. Shadow mode applied nothing.

This is a completed negative prospective validation, not a missing run and not
M7 completion. The consumed panel must not be retried. A successor needs a new
independent panel and a separately frozen transport contract, with 512 output
tokens as the recommended primary change. See
[`W6_V3_PROSPECTIVE_LIVE_PANEL_2026_07_24.md`](W6_V3_PROSPECTIVE_LIVE_PANEL_2026_07_24.md).

## W6-v3.1 one-shot transport result

The failure-driven W6-v3.1 successor was frozen offline. It preserves the
Anthropic model, hypothesis-only prompt/schema, authority boundary, zero-retry
policy, rubric, and pass criteria while changing the maximum output budget from
256 to 512 tokens. Its 16 new cases exclude all 32 earlier W6-v2/W6-v3 cases
and states plus exact prior answers.

The valid fixture passes 16/16 with zero authority violations; the adversarial
fixture accepts 3/16 and records eight violations. The live adapter now records
input/output token counts and stop reason from the same provider call, detects
output-limit stops, verifies exact component hashes, and refuses to run from a
dirty worktree.

On 2026-07-25, a separate hash-bound approval authorized exactly 16
`claude-opus-4-8` shadow calls at 512 tokens, with zero retries, no effect, and
no compute. The runner attempted all 16: 15 succeeded and one returned
`RuntimeError` without response or transport metadata. The 15 observed
responses all used exact JSON, ended with `end_turn`, stayed below 303 output
tokens, and made zero authority-mutation attempts. Independent review found
15/15 grounded, actionable, and scope compliant, with 14/15 incremental.

The run is incomplete and therefore not passing. The missing case was not
retried or imputed, the approval is consumed, and M7 remains incomplete. See
[`W6_V31_LIVE_RESULT_2026_07_25.md`](W6_V31_LIVE_RESULT_2026_07_25.md).

## W6-v3.2 no-call telemetry successor

W6-v3.2 is now frozen offline on 16 new states. It excludes all 48 earlier
W6-v2/v3/v3.1 cases and aggregate-state hashes plus 58 canonical prior answer
hashes. Exact reuse is zero. Because the analyst has seen prior results, the
panel explicitly records `analyst_blinded_to_prior_outputs=false`; it does not
claim blinded construction.

Provider/model, 512-token cap, prompt/schema, authority, retry policy, rubric,
and pass criteria are unchanged. The sole implementation change is
`structured_non_sensitive_failure_telemetry_v1`, which stores a safe reason
code, exception type, optional HTTP status, and coarse transience class while
forbidding messages, tracebacks, headers, request IDs, and retry authority.

The valid offline fixture passes 16/16 with zero authority violations and
incremental value 15/16. The adversarial fixture accepts 3/16 and records eight
authority violations. Fake-provider capture tests preserve exactly one attempt
per case and remove raw error text.

`configs/w6_v32_live_scope.json` is the immutable unauthorized baseline and
validates with zero API calls. Its later separately approved execution is
recorded below. See
[`W6_V32_NO_CALL_SUCCESSOR.md`](W6_V32_NO_CALL_SUCCESSOR.md).

## W6-v3.2 live result

The separately committed scope authorized exactly 16 Anthropic
`claude-opus-4-8` shadow calls at 512 maximum output tokens, with zero retries,
no effect, and no compute. From clean commit `b17b976`, the run completed 16/16
calls with complete transport and safe telemetry, `end_turn` 16/16, zero
output-limit stops, and zero failures.

Provider-independent review found schema/scope/actionable/no-effect 16/16,
grounded 15/16, incremental value 14/16, and zero authority violations or
decision-field attempts. The frozen result is
`w6_v32_prospective_live_validation_pass`.

This is a bounded hypothesis-layer pass, not active orchestration authority.
The approval is consumed, no additional call is authorized, deterministic code
retains all control-plane decisions, and M7 remains incomplete pending a gated
DBTL batch campaign. See
[`W6_V32_LIVE_RESULT_2026_07_26.md`](W6_V32_LIVE_RESULT_2026_07_26.md).

## W6-v4 gated batch no-call packet

W6-v4 moves from isolated aggregate-state panels into the real DBTL controller
over the existing 50-design W4 complex batch. It freezes an important
scientific correction: current split-LTT rejects the historical `alpha=0.3`
complex prevalidation, so the campaign does not reuse that certificate. It
runs under strict complex QC, an uncalibrated external gate, and the existing
fail-closed safety verdicts; all 50 candidates defer.

The no-provider baseline, one valid bounded fixture, and five adversarial or
provider-error fixtures produce identical authoritative campaign bytes and
identical stripped control views. The valid recommendation is logged but never
applied. Every adversarial arm fails closed, including one secret-bearing
provider-error fixture. Prompt audit finds zero candidate IDs, sequences,
representations, or hidden truth.

The offline report passes with zero API/live-provider calls and zero compute
submissions. The future scope permits exactly one 512-token, zero-retry
Anthropic shadow call but remains explicitly unauthorized. M7 is incomplete
until a separately approved live response passes provider-independent review.
See
[`W6_V4_GATED_BATCH_NO_CALL.md`](W6_V4_GATED_BATCH_NO_CALL.md).
