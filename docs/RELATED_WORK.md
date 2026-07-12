# Related Work

This project combines established ideas from generative protein design,
structure prediction, selective prediction, and cost-aware deferral. The
combination is an engineering hypothesis; this document does not claim that its
individual components are novel or that the current release validates
autonomous scientific discovery.

## Adjacent method families

- **Sequence and structure design.** ProteinMPNN and RFdiffusion illustrate
  specialist generators that can sit behind a typed adapter. Their outputs
  still require independent evaluation and provenance checks.
- **Structure prediction.** Confidence values from structure predictors are
  useful signals only within a validated regime. The controller therefore
  treats predictor identity, signal source, label source, and calibration scope
  as first-class record fields.
- **Selective prediction and deferral.** Conformal and learning-to-defer methods
  motivate explicit abstention and risk control instead of unconditional model
  acceptance.
- **Cost-aware verification.** The controller represents verification as a
  priced action, but the checked-in evidence supports only the protocols and
  regimes described in [RESULTS.md](RESULTS.md).

## Representative primary references

- Dauparas et al., ProteinMPNN,
  [Science (2022)](https://doi.org/10.1126/science.add2187).
- Watson et al., RFdiffusion,
  [Nature (2023)](https://doi.org/10.1038/s41586-023-06415-8).
- Angelopoulos and Bates, conformal prediction overview,
  [arXiv:2107.07511](https://arxiv.org/abs/2107.07511).
- Verma et al., cost-aware learning to defer,
  [arXiv:2403.06906](https://arxiv.org/abs/2403.06906).

These references orient the architecture; they are not an exhaustive landscape
review. Scientific claims for this release come from the repository's own
versioned artifacts, not from analogy to adjacent systems.
