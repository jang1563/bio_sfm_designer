# W6-v3.1 Transport Successor

## Status

W6-v3.1 was frozen and qualified offline, then executed once under a separate
exact approval on 2026-07-25. The one-shot live run attempted all 16 calls,
returned 15 responses, and failed closed after one provider-path
`RuntimeError`. The approval is consumed and no retry is authorized.

The full live result is recorded in
[`W6_V31_LIVE_RESULT_2026_07_25.md`](W6_V31_LIVE_RESULT_2026_07_25.md).

The predecessor W6-v3 live panel failed because five of 16 responses ended
mid-JSON under a 256-token output cap. W6-v3.1 tests one primary runtime change:

| Factor | W6-v3 | W6-v3.1 |
|---|---:|---:|
| maximum output tokens per call | 256 | 512 |
| provider/model | Anthropic `claude-opus-4-8` | unchanged |
| prompt template | hypothesis-only | unchanged |
| response schema | `reason+hypothesis` | unchanged |
| retries | 0 | unchanged |
| authority | shadow/no effect | unchanged |

The panel itself must be new to preserve prospective independence. Therefore
the token cap is the only changed runtime factor, but the evaluation states are
necessarily a fresh sample rather than a literal replay.

## Independent Panel

`configs/w6_v31_transport_panel.json` contains 16 newly written synthetic
counterfactual DBTL states. Its validator excludes:

- all 16 W6-v2 cases and canonical aggregate states;
- all 16 consumed W6-v3 cases and canonical aggregate states;
- all forbidden prior source paths;
- 27 exact valid prior answer hashes from the W6-v3 fixture and live output.

Generic scientific concepts may recur, but exact case identifiers, states,
sources, and answers may not. The audit reports zero reuse.

| Artifact | SHA-256 |
|---|---|
| panel | `bf9575157bddfc223f6511af7215618380b6cd438e28e4bb7f99930f9bd928d9` |
| requests | `ac4ea1a8be736eba127a46cf517d18ba427d265a43f74f7728bb79a2a5e4e1b1` |
| freeze report | `c0f4883b557e0effd04662964e3beb70ff5185a1898fb6a88ba039cf5a45b73b` |

## Offline Qualification

The valid synthetic fixture passes:

- schema acceptance: 16/16;
- authority violations: 0;
- grounded/actionable/scope-compliant: 16/16;
- incremental value: 11/16;
- no effect: 16/16.

The adversarial fixture fails closed:

- schema acceptance: 3/16;
- authority violations: 8;
- decision-field attempts: 2;
- overall result: fail.

These are contract tests, not provider-performance evidence.

## Provenance-Hardened Runtime

`configs/w6_v31_live_scope.json` remains the original no-call scope packet.
The later authorized packet,
`configs/w6_v31_live_scope_approved_20260725.json`, freezes:

- Anthropic `claude-opus-4-8`;
- exactly 16 calls, one per request;
- 512 maximum output tokens per call;
- zero SDK retries;
- shadow/no effect;
- required `input_tokens`, `output_tokens`, and `stop_reason`;
- explicit detection of `max_tokens`/length stops;
- exact execution-component SHA-256 values;
- a clean Git worktree before the first provider call;
- no overwrite, resume, compute submission, or additional call.

The historical no-call scope digest is
`3ce9af157ba0e3a9a5047c1f01b52c1d94713e356bfaa29fb5f01187be4cfe8e`
and deliberately sets:

```json
{
  "live_execution_authorized": false,
  "approval_basis": null
}
```

The capture command therefore raises before constructing or invoking a live
provider. Unit tests prove that authorization, component-hash mismatch,
scope-hash mismatch, a dirty worktree, missing transport metadata, existing
outputs, and unsafe flag changes all fail closed.

The separately committed authorization scope has digest
`b8b667a136a6dbdb2d723bce2586211a6f70c403d6186699e5a80349ba2753ab`.
It was consumed from clean source commit
`0a9ef16467bf6bed696455d4a0361ae4fb14ce06`; its receipt explicitly forbids
additional calls.

## Review Path

`w6_v31_review.py` applies a provider-independent review only after exact
panel, request, and pending-response hash checks. It:

- requires one complete review per case;
- rejects undeclared scope tags;
- preserves raw provider responses byte-for-byte;
- writes a separate reviewed-response file and receipt;
- makes zero provider calls.

Because the live capture was incomplete, that complete-panel path correctly
produced no pending-response packet. The separate
`w6_v31_incomplete_result.py` auditor validates the 16-row capture and receipt,
allows review only for the 15 successful responses, refuses any annotation for
the missing response, and reports an incomplete non-pass.

## Next Gate

Do not retry or selectively recover the consumed panel. The observed 15
responses support the 512-token transport hypothesis only conditionally:
15/15 used exact JSON, had zero authority violations, and ended normally
without an output-limit stop. The missing sixteenth response prevents a
prospective pass and M7 remains incomplete.

Any successor requires a newly frozen independent panel and a new explicit
approval. It should preserve the 512-token, hypothesis-only, zero-retry,
shadow/no-effect contract and add structured non-sensitive failure telemetry.
