# External Model Adapters

This directory contains Python adapters for model work that is intentionally
separate from the CPU orchestration loop. Generic `run_*.sbatch` examples are
included, while site-specific accounts, partitions, modules, environments, and
storage paths are not.

## Adapter map

| Script | Purpose |
|---|---|
| `prep_hetdimer.py` | Validate and prepare a two-chain structure |
| `extract_chain_fasta.py` | Extract and hash a fixed target sequence |
| `precompute_boltz_target_msa.py` | Build a reusable target-MSA artifact |
| `generate_proteinmpnn.py` | Convert ProteinMPNN output to candidate JSONL |
| `generate_proteinmpnn_complex.py` | Convert fixed-target binder designs to candidate JSONL |
| `predict_esmfold.py` | Produce ESMFold prediction records |
| `predict_boltz.py` | Produce Boltz monomer records |
| `predict_boltz_complex.py` | Produce Boltz complex/interface records |
| `make_chai1_smoke_input.py` | Build a bounded Chai-1 compatibility input |
| `run_chai1_api_with_metrics.py` | Collect Chai-1 output from an available runtime |
| `convert_chai1_complex_output.py` | Convert Chai-1 output to the strict record schema |
| `screen_deberta.py` | Run an explicitly supplied classifier head |

Run an adapter with `--help` to inspect its required inputs. Review and adapt
the generic scheduler resource headers before submission; supply model
executables, weights, storage paths, and site configuration at runtime.

After synchronizing records to a local workspace, the controller consumes them
through `PrecomputedGenerator`, `PrecomputedStructurePredictor`, and
`PrecomputedScreen`. Local preflight rejects missing or duplicate candidate
IDs, incomplete prediction coverage, and incompatible provenance before trust
routing.

See [`docs/HPC.md`](../docs/HPC.md) for the data and reproducibility boundary.
