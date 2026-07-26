# W6-v3.2 No-Call Telemetry Successor

## Status

W6-v3.2 was first frozen and qualified **offline only**. No provider or API
call was made during this successor-freeze stage.

It does not selectively recover the missing W6-v3.1 case. Instead, it prepares
a new 16-case prospective panel under the same behavioral contract and adds
non-sensitive structured failure telemetry.

The baseline no-call scope remains explicitly unauthorized:

```json
{
  "live_execution_authorized": false,
  "approval_basis": null,
  "additional_provider_calls_authorized": false
}
```

A later separately approved execution is recorded in
[`W6_V32_LIVE_RESULT_2026_07_26.md`](W6_V32_LIVE_RESULT_2026_07_26.md).
M7 remains incomplete.

## Successor Question

W6-v3.1 observed exact JSON and zero authority violations in all 15 successful
calls at a 512-token cap, but one call produced no response or transport
metadata. W6-v3.2 asks whether the same unchanged behavioral contract can
complete a new prospective panel while producing a safe diagnostic category
for any failure.

| Factor | W6-v3.1 | W6-v3.2 |
|---|---|---|
| provider/model | Anthropic `claude-opus-4-8` | unchanged |
| maximum output | 512 tokens | unchanged |
| prompt/schema | hypothesis-only `reason+hypothesis` | unchanged |
| authority | shadow/no effect | unchanged |
| retries | 0 | unchanged |
| pass criteria and review rubric | frozen | unchanged |
| failure telemetry | exception type and HTTP status only | structured non-sensitive v1 |

The declared behavioral change is `none`. The sole implementation change is
instrumentation.

## Independent Panel

`configs/w6_v32_transport_panel.json` contains 16 newly written synthetic DBTL
states covering input integrity, calibration/evidence, candidate quality,
predictor robustness, and a terminal computational-null branch.

The validator hash-excludes:

- all 48 case identifiers from W6-v2, W6-v3, and W6-v3.1;
- all 48 canonical aggregate-state hashes from those panels;
- 58 canonical fixture/live answer hashes from W6-v3 and W6-v3.1;
- every declared prior source path.

Exact case, source, state, and answer reuse are zero.

The analyst was not blind to the prior results. The panel therefore freezes
`analyst_blinded_to_prior_outputs=false`. It separately records that prior
outputs were not used as case templates, prior case artifacts were used for
exclusion auditing, and the W6-v3.1 result motivated the telemetry change.

## Offline Qualification

The valid synthetic replay passes:

| Measure | Result |
|---|---:|
| schema acceptance | 16/16 |
| authority violations | 0 |
| decision-field attempts | 0 |
| grounded | 16/16 |
| actionable | 16/16 |
| scope compliant | 16/16 |
| incremental value | 15/16 |
| no effect | 16/16 |

The adversarial replay fails closed:

| Measure | Result |
|---|---:|
| schema acceptance | 3/16 |
| authority violations | 8 |
| decision-field attempts | 2 |
| overall result | fail |

These are provider-free contract tests, not live model evidence.

## Failure Telemetry

`w6_v32_provider_failure_telemetry_v1` stores only:

- success/failure outcome;
- stable `safe_reason_code`;
- exception class name;
- integer HTTP status when available;
- coarse `potentially_transient`, `non_transient`, or `unknown` classification;
- `retry_authorized=false`.

It explicitly stores no exception message, traceback, headers, or request ID.
The known W6-v3.1 empty-text adapter error maps to
`safe_reason_code=empty_text_response` without persisting the original message.
The classification never grants retry authority.

Fake-provider tests prove that a failure on one case still yields exactly one
attempt per 16 frozen requests, zero retries, no response packet, complete safe
telemetry, and no raw error text in the capture.

## Frozen Artifacts

| Artifact | SHA-256 |
|---|---|
| panel | `5e9e2346c52b07a2fef2dd458e1d612a9733ff22a3da87b2d0a0604b5f5346dd` |
| requests | `e1d0f380dba775302cb077335edd9f2a614d1c2ac7518fb7fb46906d74184b44` |
| freeze report | `cc285cda091e34f68fb98a49c49c5ebaa11a3738b2153ce87e80e27e03a7b53d` |
| valid fixture | `f74800400e69ddb3bb2ac942d50979b1bbfc5379d4bcb4840dd55298b3419d0c` |
| adversarial fixture | `82989f8992cb34af9efac69f94ef2bdce15e8672fb0407701beb8c678da06c00` |
| valid replay | `3d5355ac71abbe6ec8c44670d6536469f42e85f1c1204c0f078e0d02126758ae` |
| adversarial replay | `5ebc2f415d643175b02d36a7edfd9af748f6d4ebef71d5847701e121ea3ccad6` |
| no-call scope | `e71cca5a7fba25eb30cf2ed5dbea4541d862cca7f5d8f404f2177ab7711c7708` |

The no-call scope binds the panel and request hashes plus six exact execution
component hashes. Validation constructs no provider and reports `api_calls=0`.

## Review Path

`w6_v32_review.py` requires complete provider-independent annotations bound to
the panel, request, and pending-response hashes. It preserves raw responses
byte-for-byte, rejects undeclared scope tags, and makes zero provider calls.

## Later Result And Next Gate

A separately approved, hash-bound live scope subsequently completed all 16
calls and passed the frozen prospective hypothesis-only contract. The no-call
scope above remains the immutable baseline; it was not rewritten.

That one-shot authorization is consumed, and no additional live call is
authorized. The complete result validates only the bounded hypothesis layer.
M7 additionally requires participation in a gated batch campaign without
ownership of stop/explore, trust, safety, routing, or budget decisions. See
[`W6_V32_LIVE_RESULT_2026_07_26.md`](W6_V32_LIVE_RESULT_2026_07_26.md).
