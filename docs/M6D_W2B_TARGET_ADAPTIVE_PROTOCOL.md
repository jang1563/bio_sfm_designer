# M6d W2b Target-Adaptive Protocol

## Decision

The completed fresh 11-target W2 panel does not support a universal pAE gate. Target success rates and
pAE ranking behavior vary too widely, and its 100-record Hoeffding/Bonferroni split was structurally
underpowered for alpha=0.2. Scaling the same panel cannot repair either issue and would be post-hoc.

W2 therefore remains a negative result. The next experiment is a separate milestone, W2b:

> Can a predeclared target-adaptive gate independently control false accepts on at least three of eight
> entirely new, source-diverse, sequence-diverse targets?

This is a deployable calibration question, not a zero-shot universal-threshold claim.

## Locked Algorithm

For each of eight fresh targets, generate 60 fit records first. The fit split selects exactly one mode in
this order:

1. `trust_all` when the fit false-accept rate is at most 0.2;
2. otherwise `selective_pae` when both classes are present, AUROC for fixed-direction `-pAE_interaction`
   is at least 0.65, and a low-pAE threshold accepts at least 20 fit rows at empirical risk at most 0.2;
3. otherwise `refuse`.

The chosen mode and any threshold are frozen. Only fit-eligible targets receive 60 new certification
records and 60 new test records. Fit, certification, and test use disjoint seed namespaces and may not
share candidate IDs.

Certification uses a one-sided exact Clopper-Pearson upper bound with panel delta 0.1 and Bonferroni
correction over all eight initial targets, including targets that refuse. Thus per-target delta is
0.0125. A target certificate requires at least 22 accepted certification rows and an upper bound at most
0.2. The test split reports behavior but cannot change the certificate.

## Success Rule

W2b is supported only when all QC and provenance checks pass, at least three of the eight initial targets
certify, and at least one certified target uses `selective_pae` rather than `trust_all`.

Even a successful W2b result does not support a universal pAE threshold or zero-shot W2 generalization.
It supports target-adaptive multi-target gate viability. Failed and refused targets remain visible in the
denominator and report.

## Compute Gate

The first stage costs 480 folds. The maximum is 1,440 folds if every target advances. This staged design
avoids spending certification and test compute on targets that the locked fit rule already refuses.

Cayuga submission is currently blocked. The exact bound, designer compatibility path, bound-aware complex
panel reporting, and staged W2b evaluator are implemented and covered by the full local test suite. The
evaluator is `python -m bio_sfm_designer.experiments.m6d_w2b_target_adaptive_report`.

Before any compute:

- select eight targets absent from the historical registry and the completed v11 panel;
- pass source, sequence, MSA, strict manifest, candidate-overlap, and SHA-bound dry-run checks;
- obtain explicit operator approval for the manifest and protocol digests.

The machine-readable contract is
`configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json`.

## Current State (2026-07-11)

No-spend discovery replayed a saved 10,000-ID RCSB response after excluding 128 historical evaluated
sources and 860 previously screened seeds. Local intake fetched 200 new sources, screened 2,252 chain
pairs, and admitted 26 source-diverse candidates. Global-alignment clustering produced 24 sequence
clusters. A label-blind SHA-256 ranking bound only to the locked scientific protocol fields selected these eight fit
targets:

`1FXK_CA`, `1F93_DC`, `1F66_AB`, `1FJG_FR`, `1FDH_GA`, `1FLT_WV`, `1F51_AE`, `1FVC_DC`.

The final manifest passes historical target/source overlap checks, has 8/8 sequence clusters with largest
cluster fraction 0.125, and passes schema preflight 8/8. Its SHA-256 is
`1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14`; the locked scientific protocol
digest is `19bad978cdbccfeb5cfe3ec0f7c7455bb8d2f7e10697091c15ec6b40c7341b0b`. Mutable execution-status
fields are intentionally excluded from this digest so recording progress cannot change target selection.

Strict file preflight is intentionally blocked on exactly 16 missing files: one target MSA and one MSA
report for each target. The manifest-bound plan is
`results/m6d_w2b_target_adaptive_fit_target_msas.sh` with SHA-256
`34f44d18ab784a321a948bcf1d0c3c0b4cb0c7e5d5bd3f77d3fa247a20a9ff5d`. Local and Cayuga dry-runs both
passed with no receipt creation and no change in queued Slurm jobs (`0 -> 0`). The plan has not been
submitted. A separate guarded wrapper requires
`BIO_SFM_APPROVE_W2B_TARGET_MSA=approve-w2b-target-msa-precompute`; ordinary continuation language is not
approval. ProteinMPNN and Boltz fit-stage compute remains unauthorized.

## Claim Boundary

The v11 panel may motivate this protocol but cannot validate it. No v11 row can enter W2b fit,
certification, or test data, and no W2b rule may be changed after inspecting its certification or test
labels.

## Statistical Basis

The certification bound is the one-sided exact binomial interval obtained by inverting the binomial test,
following Clopper and Pearson (1934):
https://doi.org/10.1093/biomet/26.4.404. Reference behavior is cross-checked against SciPy's exact
`binomtest` confidence interval:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.BinomTestResult.proportion_ci.html.
