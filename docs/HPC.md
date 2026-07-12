# External Compute Boundary

The controller and release tests are CPU-testable. Heavy generation, structure
prediction, MSA construction, and optional classifier inference run in an
external environment chosen by the user.

## Data contract

```text
versioned inputs
  -> external model runtime
  -> JSONL records and model artifacts
  -> local Precomputed* adapters
  -> provenance checks
  -> calibrated routing and evaluation
```

The repository ships generic Slurm examples alongside the Python adapters. It
does not ship cluster accounts, site partitions, model weights, caches,
credentials, or site-specific environment definitions. Users must review the
resource headers, invoke the adapters from their own scheduler or workflow
system, and provide every runtime path explicitly.

## Included adapter entry points

- `hpc/generate_proteinmpnn.py`
- `hpc/generate_proteinmpnn_complex.py`
- `hpc/predict_esmfold.py`
- `hpc/predict_boltz.py`
- `hpc/predict_boltz_complex.py`
- `hpc/precompute_boltz_target_msa.py`
- `hpc/run_chai1_api_with_metrics.py`
- `hpc/screen_deberta.py`

The corresponding `hpc/run_*.sbatch` files use only generic resource requests;
they are starting points, not validated site configurations.

Each adapter exposes `--help` and writes a bounded artifact consumed by the
local package. Availability of an adapter does not imply that its model,
weights, runtime, or scientific regime has been validated by this release.

## Reproducibility requirements

- record model and weight identity;
- preserve input and artifact hashes;
- record predictor, signal, and label provenance;
- keep raw model state and scheduler metadata outside Git; and
- run the public manifest, history, and test gates before publication.

See [`hpc/README.md`](../hpc/README.md) for the included adapter map.
