# Test fixtures

## `phase2_targets_records.jsonl`

80 protein targets (40 monomer + 40 complex) released **after Boltz-2's training cutoff**
(leakage-safe), each with Boltz-2 confidence (`mean_plddt`, `iptm`) and hidden experimental
truth (`truth.correct`, `truth.quality` = CA-lDDT).

**Provenance:** copied verbatim from the sibling repo bio-sfm-trust-audit
(`LLM_SFM_interpretability/experiments/trust_cue_attribution/hpc_outputs/phase2_targets/records.jsonl`),
same author (JK). Used by `tests/test_structure_gate.py` and
`experiments/offline_structure_gate.py` as the M1 real-data substrate — no GPU/Boltz needed
(records are precomputed). Schema matches `bio_sfm_trust.gate.confidence_to_risk` /
`phase2_calibration_gate`.

## W6-v2 shadow-panel fixtures

`w6_v2_shadow_panel_{valid,adversarial}_response_specs.json` are synthetic,
provider-free response definitions for the frozen 16-case orchestration panel.
`w6_v2_shadow_panel_{valid,adversarial}_responses.jsonl` bind those definitions
to the exact panel and prompt SHA-256 values. They test the offline scorer and
are not live-model outputs or scientific evidence.

## W6-v3 hypothesis-only fixtures

`w6_v3_hypothesis_only_{valid,adversarial}_responses.jsonl` mechanically reduce
the frozen W6-v2 synthetic specs by removing `stop` and `explore`. They bind
`reason+hypothesis` to the v3 request hashes and verify that the reduced
contract accepts bounded hypotheses while rejecting malformed, decision-
bearing, control-plane, and low-quality responses. They are synthetic contract
tests, not provider outputs or prospective evidence.

## W6-v3 independent prospective fixtures

`w6_v3_prospective_hypothesis_{valid,adversarial}_responses.jsonl` bind to 16
new counterfactual states that exclude every frozen W6-v2 case/source and have
zero exact aggregate-state hash overlap. The valid fixture passes 16/16; the
adversarial fixture accepts 3/16 and records eight authority violations. These
remain synthetic scorer tests. The distinct 2026-07-24 live result and its
negative schema verdict are documented in
`docs/W6_V3_PROSPECTIVE_LIVE_PANEL_2026_07_24.md`.

## W6-v3.1 transport-successor fixtures

`w6_v31_transport_{valid,adversarial}_responses.jsonl` bind to 16 additional
counterfactual states that exclude both prior W6 panels, all 32 prior case/state
hashes, and exact prior answers. The valid fixture passes 16/16 with zero
authority violations; the adversarial fixture accepts 3/16 and records eight.
They qualify the offline contract only. The 512-token live scope remains
unauthorized; see `docs/W6_V31_TRANSPORT_SUCCESSOR.md`.
