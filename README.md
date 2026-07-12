# bio_sfm_designer

[![CI](https://github.com/jang1563/bio_sfm_designer/actions/workflows/ci.yml/badge.svg)](https://github.com/jang1563/bio_sfm_designer/actions/workflows/ci.yml)

A calibrated, cost-aware, safety-screened Design–Build–Test–Learn (DBTL)
research engine for biology. An LLM can orchestrate specialist scientific
foundation models, but an **external calibrated trust gate** owns the decision
to:

```text
trust_sfm | verify_assay | default_baseline | defer
```

The gate uses model-visible evidence only. Hidden truth is reserved for
evaluation, and a fail-closed biosafety screen runs before proposal and before
synthesis-facing stages.

This repository is a research-engine artifact, not a publication plan.

## Why an external gate?

Specialist-model confidence is not automatically calibrated across regimes.
The project therefore separates orchestration from permissioning:

1. a generator proposes candidates;
2. specialist predictors produce structured evidence;
3. the trust layer converts evidence into calibrated risk;
4. the gate chooses trust, verification, baseline, or deferral;
5. the evaluator scores benefit minus verification cost;
6. observations feed the next DBTL round.

The reusable calibration and conformal-risk machinery lives in
[bio-sfm-trust-core](https://github.com/jang1563/bio-sfm-trust-core). This
repository is the biology application layer.

## What is included

| Area | Purpose |
|---|---|
| `src/bio_sfm_designer/loop/` | Closed-loop controller, acquisition, planning, and interpretation |
| `src/bio_sfm_designer/trust/` | Adapter from prediction evidence to the external trust gate |
| `src/bio_sfm_designer/safety/` | Fail-closed policy, screening, and label-integrity checks |
| `src/bio_sfm_designer/generate/` | Generator interfaces and precomputed adapters |
| `src/bio_sfm_designer/predict/` | Predictor interfaces and structure-prediction evidence |
| `src/bio_sfm_designer/experiments/` | Reusable calibration, panel, provenance, and exact-LTT evaluators |
| `hpc/` | Generic ProteinMPNN, ESMFold, Boltz, and Chai-1 execution adapters |
| `tests/` | CPU tests and public replay fixtures |
| `release/public_release_manifest.json` | Checksummed release evidence and scope |

Operator receipts, scheduler logs and identifiers, private paths, model state,
session handoffs, and historical branch ledgers are intentionally excluded from
this public snapshot.

The curated public suite currently contains 325 passing tests.

## Current scientific result

The strongest result is a fail-closed boundary, not broad positive
generalization.

### W2b exact learn-then-test replay

- Eight fresh protein-complex targets entered the locked fit stage.
- Five fit rules were eligible: four `trust_all` and one `selective_pae`.
- Four `trust_all` targets certified under the exact one-sided bound.
- The sole selective target, `1F51_AE`, did not certify: 31 accepted rows,
  6 false accepts, exact upper bound `0.4002` at target alpha `0.2`.
- Its diagnostic pAE AUROC remained `0.7839`, but diagnostic ranking does not
  change the certificate.
- Because the panel required at least one selective certificate, the terminal
  status is `w2b_certification_terminal_not_supported`.

This W2 result is **not W2 generalization evidence**. Pooled-only evidence is
not proof of target-wise transfer.

### W2c prospective successor

W2c is a fresh, selective-pAE-only one-shot design. Its exact prospective
power gate passes (`0.817860` conditional power at 90 accepted rows), and eight
historically disjoint targets have been selected. Target-MSA execution and all
record generation remain unrun in this release; no W2c result is claimed.

W3 independent-predictor robustness is not supported by the current evidence.

See [docs/RESULTS.md](docs/RESULTS.md),
[results/m6d_w2b_target_adaptive_certification_report.json](results/m6d_w2b_target_adaptive_certification_report.json),
and [docs/M6D_W2C_ONE_SHOT_PROTOCOL.md](docs/M6D_W2C_ONE_SHOT_PROTOCOL.md).

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/check_public_manifest.py
python -m bio_sfm_designer.experiments.public_release_readiness \
  --repo-visibility public \
  --tracked-only \
  --include-results
```

## Replay the terminal W2b result

```bash
python -m bio_sfm_designer.experiments.m6d_w2b_target_adaptive_report \
  --protocol configs/m6d_w2b_target_adaptive_exact_ltt_protocol.json \
  --fit-records tests/fixtures/m6d_w2b_target_adaptive_fit_records.jsonl \
  --certification-records tests/fixtures/m6d_w2b_target_adaptive_certification_records.jsonl \
  --out /tmp/w2b_report.json
```

Expected terminal status:

```text
w2b_certification_terminal_not_supported
```

## Claim and safety boundaries

- This is not clinical decision support or autonomous wet-lab execution.
- A passing component diagnostic is not a deployment certificate.
- `trust_all` controls do not establish selective gate transfer.
- W2c remains prospective until its predeclared stages are executed without
  post-hoc changes.
- Human review remains required for safety-sensitive or synthesis-facing work.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Scientific background](docs/BACKGROUND.md)
- [Results and limitations](docs/RESULTS.md)
- [Statistical validity reset](docs/STATISTICAL_VALIDITY_RESET_2026-07-10.md)
- [W2c one-shot protocol](docs/M6D_W2C_ONE_SHOT_PROTOCOL.md)
- [HPC adapter guide](docs/HPC.md)
- [Public roadmap](docs/PROJECT_ROADMAP.md)
- [Related work](docs/RELATED_WORK.md)

## License and citation

MIT licensed. Citation metadata is provided in [CITATION.cff](CITATION.cff).
