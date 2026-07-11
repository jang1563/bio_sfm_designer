# Statistical Validity Reset (2026-07-10)

## Decision

Historical `certified`, `stop_certified`, and non-null `tau` fields produced before this reset are
**legacy exploratory results**, not current distribution-free certificates. They used leave-one-out
isotonic predictions and searched the threshold grid on the same labels used for a pointwise Hoeffding
bound. That procedure does not justify the formal claim previously attached to it.

The scientific signal result remains valid as an association: lower `pAE_interaction` strongly ranks
successful interfaces. What is reset is the finite-sample trust guarantee, not the observed ranking.

## Replacement Procedure

New reports use `certification_schema=split_ltt_v1`:

1. fit isotonic calibration and select a candidate threshold on a fit split;
2. freeze the calibrator and threshold;
3. validate that fixed rule on an independent certification split with a one-sided Hoeffding UCB;
4. evaluate routed behavior on a separate test split;
5. for target-wise panels, allocate `panel_delta / n_targets` to each target (Bonferroni).

No `tau` is emitted unless the independent certification UCB is at most `alpha`.

## Canonical 192-Design Reanalysis

At `alpha=0.3`, `delta=0.1`, seed 0:

- full-set signal AUROC (`-pAE_interaction` to success): `0.9381`;
- fit/certification/test sizes: `64 / 64 / 64`;
- fit AUROC: `0.9250`;
- fit-selected candidate tau: `0.6667`;
- certification accepted set: `29`, with `9` false accepts;
- certification empirical false-accept rate: `0.3103`;
- certification Hoeffding UCB: `0.5096`;
- result: `tau=null`, `certified=false`, test routing trusts `0/64`.

Therefore the current claim is: **the pAE signal is real, but alpha=0.3 is not independently certified**.

## W2 Panel Reset

The previous v11 manifest reused five evaluated targets. A historical registry now blocks exact target
or source reuse. Fresh discovery found 20 structurally admissible candidates after historical exclusion;
global-alignment sequence clustering yields 11 clusters, largest cluster 7/20 (`0.35`). The 11
representatives are in `configs/m6d_w2_target_family_redesign_v11_new_representative_targets.json`.

The fresh representative panel subsequently received explicit approval and completed on Cayuga. All 22
ProteinMPNN/Boltz jobs completed with exit code `0:0`; sync-back produced 100 valid records for each of
11 targets, for 1,100 records total. The target-wise report is
`multi_target_evaluable_not_certified` at alpha=0.2. No W2 generalization claim is supported.

Observed target behavior is strongly heterogeneous: success rates span 0% to 100%, and defined
`pAE_interaction` AUROCs span approximately 0.24 to 1.00. Three targets have AUROC above 0.5, four below
0.5, and four are one-class. This is evidence that the direction and strength of the pAE signal are
target-dependent on fresh targets; it is not evidence that every target lacks signal.

## Post-hoc Panel Power Diagnostic

The panel also exposed a design-level limitation. With 100 records per target, the current split gives
33 independent certification rows. Bonferroni allocation across 11 targets gives per-target
`delta=0.1/11`. Even with zero false accepts and all 33 rows accepted, the Hoeffding UCB floor is
approximately `0.2669`, so alpha=0.2 is mathematically unattainable under the declared procedure.

The minimum zero-error certification accepted count is 59. Under the current two-thirds calibration,
half-fit/half-certification split, the smallest total is 176 records per target (`117` calibration:
`58` fit + `59` certification; `59` test). This is only a best-case feasibility floor. It does not fix
targets with weak, inverse, or one-class signals, and it cannot be used to recertify this panel because
the calculation is post-hoc. See
`results/m6d_w2_target_family_redesign_v11_new_representative_panel_power_diagnostic.{json,md}`.

Before more panel compute, predeclare either a powered version of the existing Hoeffding/Bonferroni
protocol or a new target-conditional protocol with a validated finite-sample bound, then evaluate it on
new held-out targets. The project has selected the latter as the separate W2b milestone in
`docs/M6D_W2B_TARGET_ADAPTIVE_PROTOCOL.md`. The completed panel may inform that hypothesis but cannot
certify it.

## Operational Repairs

- Target diversity now uses Needleman-Wunsch global alignment rather than positional zip identity.
- The tracked W2 submit wrapper writes an append-only `proteinmpnn_submitted` event before Boltz submit;
  reruns recover partial pairs without duplicating ProteinMPNN jobs.
- Approval intent is bound to a manifest SHA-256, target list, scope digest, and freshness check.

## Claim Boundary

Old records remain valuable negative/evaluative data and can be reanalyzed without refolding. Any positive
certificate must be regenerated from original rows under `split_ltt_v1`; filenames and old status fields
alone are insufficient.
