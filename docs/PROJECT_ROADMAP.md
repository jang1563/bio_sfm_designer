# Public Research Roadmap

This roadmap covers scientific and software milestones in the public release.
It is not an operator runbook and does not authorize compute.

## Completed

- Closed a CPU DBTL loop with pluggable generation, prediction, screening,
  acquisition, and scoring.
- Integrated an external calibrated trust gate backed by
  `bio-sfm-trust-core`.
- Added strict provenance, chain-identity, label-integrity, and public-surface
  checks.
- Replaced same-sample threshold claims with split learn-then-test and exact
  one-sided certification where applicable.
- Preserved the terminal negative W2b result as a reproducible fixture-backed
  evaluation rather than converting diagnostic pAE signal into a certificate.

## Current frontier

W2b is closed as `w2b_certification_terminal_not_supported`: four
`trust_all` controls certified, but the required selective-pAE certificate did
not. The active scientific question is whether a genuinely selective,
target-adaptive gate can certify on multiple entirely fresh targets.

W2c predeclares that question with:

- eight historically disjoint targets;
- disjoint threshold-learning and fit-screen rows;
- a frozen selective-pAE threshold;
- exact one-sided risk and acceptance-rate bounds;
- fixed sample sizes and no adaptive top-up;
- at least three selective target-wise certificates required for success.

No W2c records exist in this release.

## Next evidence milestones

1. Preserve W2b as the terminal baseline and rerun its public replay in CI.
2. Keep the W2c scientific protocol frozen before any new evidence is read.
3. If W2c is executed later, publish only aggregate, provenance-checked results
   after independent review.
4. Treat an inverse, weak, or one-class signal as a target-specific failure,
   not as permission to pool away heterogeneity.
5. Revisit independent-predictor robustness only with a supported, compatible
   backend and predeclared evaluation contract.

## Release discipline

- The public snapshot contains no scheduler IDs, receipts, logs, model state,
  private paths, or session handoffs.
- W2 generalization and W3 robustness remain unsupported.
- Pooled diagnostics never replace target-wise certification.
- Hugging Face publication is out of scope until there is a distinct model or
  dataset artifact with its own card, license, and manifest.
