# Scientific Background

`bio_sfm_designer` is a research implementation of an auditable
Design-Build-Test-Learn (DBTL) loop for biomolecular design. It separates five
responsibilities:

1. candidate generation,
2. model-based prediction,
3. external trust routing,
4. safety screening and human-review routing, and
5. evidence-preserving evaluation.

The central design choice is that a specialist model output is evidence, not a
certificate. The controller routes each candidate through an external,
calibrated gate rather than asking an LLM to decide whether its own scientific
tool call should be trusted.

## System model

The public package exposes CPU-testable orchestration and adapter interfaces.
Heavy model inference is performed outside the controller and returned as
versioned records. This keeps the local decision path deterministic and makes
the provenance of every routing decision inspectable.

The calibrated trust implementation is maintained separately in
[`bio-sfm-trust-core`](https://github.com/jang1563/bio-sfm-trust-core) and pinned
as a package dependency. This repository owns the DBTL controller, model
adapters, scientific protocols, replay fixtures, and release checks.

## Design principles

- **External routing:** trust, verification, baseline, and deferral decisions
  are made by a calibrated gate outside the generative model.
- **Regime-specific evidence:** calibration in one prediction regime does not
  automatically transfer to another.
- **Fail-closed provenance:** missing identities, incompatible schemas, or
  incomplete records stop a round before routing.
- **Offline replay:** checked-in fixtures support deterministic evaluation
  without model weights, schedulers, or private infrastructure.
- **Human review boundary:** safety and quality signals can route work for
  review; they do not authorize autonomous synthesis or wet-lab execution.

## Evidence boundary

The release makes only claims that are supported by checked-in protocols,
fixtures, reports, and their hashes:

- W2b ends in `w2b_certification_terminal_not_supported` under the predeclared
  exact-LTT criterion.
- W2c is a prospective, label-blind design with zero target-MSA execution
  records in this release.
- W3 independent-predictor robustness is unsupported by the current evidence.

See [RESULTS.md](RESULTS.md) for the quantitative boundary and replay commands.
Historical operator logs, scheduler receipts, private infrastructure details,
and unpublished workspaces are not release evidence.

## Scope

This repository is an engineering research artifact. It is not clinical
decision support, a biological deployment certificate, or an autonomous
wet-lab system. Passing a unit test or component diagnostic does not establish
scientific validity outside the evaluated protocol.

For high-level context on adjacent methods, see
[RELATED_WORK.md](RELATED_WORK.md). That page is a short orientation, not a
systematic review or a novelty claim.
