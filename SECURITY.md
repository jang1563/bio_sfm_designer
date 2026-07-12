# Security Policy

## Reporting

Please report suspected security issues privately through GitHub Security Advisories.
Do not open a public issue for credentials, unsafe
biological capability concerns, or reproducibility gaps that could expose private
infrastructure.

## Scope

This project is a research prototype for calibrated trust routing over scientific
foundation-model outputs. It is not an autonomous wet-lab or synthesis system.

Security-sensitive areas include:

- credential or token exposure in scripts, docs, logs, or generated artifacts;
- safety-screen bypasses before candidate proposal or synthesis-facing stages;
- claims that imply autonomous biological clearance without human review;
- HPC paths, job receipts, or runbooks that reveal private infrastructure beyond
  what is needed for reproducibility.

## Release Rule

Run the public-release readiness audit before changing repository visibility or
cutting a public release:

```sh
PYTHONPATH=src python3 -m bio_sfm_designer.experiments.public_release_readiness \
  --repo-visibility public \
  --check-git-status
```
