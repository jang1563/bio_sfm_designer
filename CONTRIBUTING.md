# Contributing

Thanks for improving `bio_sfm_designer`. The project is a research engine for
calibrated, safety-screened DBTL workflows, so contributions should preserve the
claim boundaries as carefully as the code paths.

## Development

Use Python 3.9 or newer. The public install pulls the pinned public
`bio-sfm-trust-core` engine from GitHub:

```sh
pip install -e ".[dev]"
```

When developing both repos locally, you can still override the pinned dependency
with an editable sibling checkout:

```sh
pip install -e ../bio-sfm-trust-core -e ".[dev]"
```

Then run focused tests for the files you touched. Public-release hygiene can be
checked with:

```sh
PYTHONPATH=src python3 -m bio_sfm_designer.experiments.public_release_readiness \
  --repo-visibility public \
  --check-git-status
```

## Claim Boundaries

Do not describe pooled diagnostics as target-wise generalization evidence. Keep
unsupported W2 multi-target and W3 independent-predictor claims explicitly marked
as unsupported until the corresponding gates pass.

## Generated Artifacts

Keep large model outputs, HPC records, receipts, and temporary results out of git
unless they are intentionally small fixtures. Prefer machine-readable manifests
plus short human-readable summaries for durable evidence.
