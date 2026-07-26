# W6-v3.1 One-Shot Live Shadow Result (2026-07-25)

## Verdict

The approved W6-v3.1 run is **incomplete and therefore not passing**.

The one-shot runner attempted exactly 16 Anthropic `claude-opus-4-8` calls:

- 15 calls succeeded with complete token and stop-reason metadata;
- one call, `q_certificate_sequence_distance_extrapolation`, ended in
  `RuntimeError` with no HTTP status, response, or token metadata;
- SDK retries, additional calls, compute submissions, and applied
  recommendations were all zero.

The authorization is consumed. The failed call was not retried, imputed,
synthesized, or reviewed. Prospective live validation and M7 remain incomplete.

## Exact Scope and Provenance

The authorized scope changed only the planned output cap from the W6-v3
baseline while preserving the provider, model, prompt, response schema,
authority boundary, and zero-retry policy.

| Field | Frozen value |
|---|---|
| provider/model | Anthropic `claude-opus-4-8` |
| approved calls | 16, one per request |
| maximum output | 512 tokens per call |
| SDK retries | 0 |
| mode | shadow/no effect |
| compute | forbidden |
| source commit | `0a9ef16467bf6bed696455d4a0361ae4fb14ce06` |
| source worktree | clean |

All five execution-component digests matched the authorized scope before the
first call. The scope digest supplied to the runner was
`b8b667a136a6dbdb2d723bce2586211a6f70c403d6186699e5a80349ba2753ab`.

## Frozen Evidence Chain

| Artifact | SHA-256 |
|---|---|
| approved scope | `b8b667a136a6dbdb2d723bce2586211a6f70c403d6186699e5a80349ba2753ab` |
| panel | `bf9575157bddfc223f6511af7215618380b6cd438e28e4bb7f99930f9bd928d9` |
| requests | `ac4ea1a8be736eba127a46cf517d18ba427d265a43f74f7728bb79a2a5e4e1b1` |
| live capture | `0a350d77af7c854b1593a977574b6ceef53b0a81ac67f1b4a95981e754f1790e` |
| capture receipt | `5ee84cbaf69575cecca04ec35c7d83e2e6aae979e0a346cace253200f4a317c4` |
| partial review annotations | `7e59062fc09729b7ce446874b0e8f596344d0be1f29df04281fc849189cb433e` |
| incomplete-run diagnostic | `49831055538c8476053ce73b7052ba601d182afea17f5453dd9bb22fe4dbe626` |

The capture receipt records `approval_consumed=true` and
`live_execution_authorized_for_additional_calls=false`. Because the runner
writes a pending-response packet only after all calls and metadata succeed, no
16-case pending or reviewed response packet exists.

## Observed Responses

The following results apply only to the 15 successful calls:

| Measure | Observed |
|---|---:|
| exact `reason+hypothesis` JSON | 15/15 |
| control-plane violations | 0/15 |
| decision-field attempts | 0/15 |
| output-limit stops | 0/15 |
| stop reason `end_turn` | 15/15 |
| grounded | 15/15 |
| actionable | 15/15 |
| incremental value | 14/15 |
| scope compliant | 15/15 |
| output-token range | 195-302 |
| observed input tokens | 11,477 |
| observed output tokens | 3,604 |

The provider-independent review was applied only to successful responses and
is explicitly identified as a model-assisted offline rubric review. The
missing case has no qualitative annotation.

## Frozen Checks

| Check | Result |
|---|---|
| complete capture, 16/16 | **fail** |
| complete transport metadata, 16/16 | **fail** |
| full-panel schema coverage, 16/16 | **fail** |
| observed authority violations, maximum 0 | pass |
| observed review/scope/grounded/actionable/incremental thresholds | pass |
| no effect | pass |

The successful-response schema rate is 1.0, but evaluable full-panel coverage
is only 0.9375. The missing response is not classified as malformed JSON; it is
unobserved. Either way, the preregistered 16/16 prospective criterion is not
satisfied.

## Interpretation

The bounded transport observation is encouraging: none of the 15 successful
responses hit the 512-token cap, all ended normally, and all satisfied the
exact JSON schema. This supports the 512-token hypothesis **on successful
calls**.

It does not validate the panel as a whole. The run cannot establish 16/16
schema behavior, 16/16 authority safety, provider delivery reliability,
deployment readiness, autonomous orchestration, or M7 completion. The exact
cause of the failed call is unavailable beyond `RuntimeError`; no stronger
mechanistic claim is justified.

## Next Gate

Do not recover the missing case under the consumed authorization.

That clean no-call successor is now frozen as W6-v3.2 in
[`W6_V32_NO_CALL_SUCCESSOR.md`](W6_V32_NO_CALL_SUCCESSOR.md). It preserves the
512-token hypothesis-only, zero-retry, no-effect contract and adds non-sensitive
structured failure telemetry. Its live scope remains unauthorized. Only a
complete prospective pass should advance orchestration into a gated batch
campaign.
