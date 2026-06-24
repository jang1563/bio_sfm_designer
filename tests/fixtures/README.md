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
