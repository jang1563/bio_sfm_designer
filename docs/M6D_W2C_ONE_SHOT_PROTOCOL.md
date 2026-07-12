# M6d W2c One-Shot Selective-Gate Protocol

Status: `w2c_design_power_qualified_no_submit`.

W2c is a new experiment motivated by the terminal W2b result. It is not an extension,
recertification, or reinterpretation of W2b. W2b rows may inform design diagnosis only and
cannot enter W2c threshold learning, fit screening, or certification.

The machine-readable protocol is `configs/m6d_w2c_one_shot_protocol.json`. Its locked
scientific fields are hashed by `m6d_w2c_design_gate.py`; mutable execution state is kept
outside that digest.

## Scientific Question

Can a genuinely selective, target-adaptive pAE gate certify false-accept risk at
`alpha=0.2` on at least three entirely fresh protein-complex targets?

`trust_all` targets do not answer this question and cannot count toward W2c success.

## Fixed Design

W2c begins with eight fresh targets. Every target must be absent from the historical
registry and W2b, use a unique source PDB, represent a distinct sequence cluster, and pass
manifest/MSA/hash validation. Failed and refused targets remain in the eight-target
Bonferroni denominator.

For each target:

1. Generate 60 threshold-learning rows under namespace `w2c-fit-learn-v1`.
2. Learn one deterministic selective-pAE threshold with at least 30 accepts, AUROC at
   least 0.65, and empirical false-accept risk at most 0.08.
3. Freeze that threshold and evaluate it on 120 disjoint fit-screen rows under namespace
   `w2c-fit-screen-v1`.
4. Continue only when the frozen rule accepts at least 75 screen rows, has empirical risk
   at most 0.08, exact one-sided risk UCB at most 0.15, and acceptance-rate LCB at least
   0.5.
5. Stop before certification unless at least three targets pass this selective screen.

For each eligible target, certification uses 180 new rows under namespace `w2c-cert-v1`.
The threshold remains frozen. Certification requires at least 90 accepts and an exact
one-sided Clopper-Pearson UCB at most 0.2 with per-target delta 0.0125.

At 90 accepts, at most 9 false accepts can certify. Under design true risk 0.08, the
conditional probability of certification is 0.817860, above the locked 0.8 power floor.
This is a prospective planning calculation, not a claim about future target risk.

Panel success requires at least three certified targets and all three must be
`selective_pae`. There is no adaptive sample top-up and no reporting-only test stage.

## Compute Boundary

- maximum fit rows: 1,440;
- maximum certification rows: 1,440;
- maximum total rows: 2,880;
- current generated rows: 0;
- current target manifest: `configs/m6d_w2c_fresh_targets.json`;
- selected targets: `1FR2_BA`, `1F80_BC`, `1EZV_XY`, `1FFG_CD`, `1FFK_HR`,
  `1FQ9_CA`, `1FYR_CD`, and `1F99_BA`;
- target selection: deterministic and label-blind from 16 eligible unused representatives
  after historical target/source and W2b target/source/sequence exclusion;
- target MSAs ready: false (8/8 still require MSA precompute);
- evaluator implemented: true (`m6d_w2c_one_shot_report.py`, with fail-closed regression tests);
- command wrapper emitted: false;
- Cayuga submission allowed: false.

The current design gate is `results/m6d_w2c_design_gate.{json,md}`. Passing it only shows
that the declared sample plan is internally coherent and prospectively powered. It does
not authorize compute or support a W2c claim.

## Go/No-Go Rule

The next boundary is a guarded target-MSA-only packet for the eight selected targets. MSA
precompute does not authorize ProteinMPNN/Boltz record generation. If strict MSA/input
locking or the later prospective fit screen cannot pass without changing locked rules,
close W2c before broader GPU spend and move the science frontier to W3
independent-predictor robustness.

The local/Cayuga packet is now ready but not submitted. See
`docs/M6D_W2C_TARGET_MSA_APPROVAL.md` and
`results/m6d_w2c_target_msa_approval_packet.json`. It requires a separate explicit
W2c target-MSA approval.
