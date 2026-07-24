# W6-v3.1 Transport Successor

## Status

W6-v3.1 is frozen and qualified **offline only**. No provider or API call has
been made under this successor.

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

`configs/w6_v31_live_scope.json` is a no-call scope packet. It freezes:

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

The current scope digest is
`3ce9af157ba0e3a9a5047c1f01b52c1d94713e356bfaa29fb5f01187be4cfe8e`,
but it deliberately sets:

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

## Review Path

`w6_v31_review.py` applies a provider-independent review only after exact
panel, request, and pending-response hash checks. It:

- requires one complete review per case;
- rejects undeclared scope tags;
- preserves raw provider responses byte-for-byte;
- writes a separate reviewed-response file and receipt;
- makes zero provider calls.

## Next Gate

The no-call packet should be committed and pushed first. A future live run then
requires a new explicit approval covering:

- Anthropic `claude-opus-4-8`;
- 16 calls;
- 512 maximum output tokens per call;
- zero retries;
- shadow-only/no effect.

After approval, the scope must be changed to authorized, hash-frozen, committed,
and validated from a clean worktree before any call. W6-v3.1 currently provides
no prospective live result and does not complete M7.
