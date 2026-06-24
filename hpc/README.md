# HPC scripts (Cayuga / Expanse)

Heavy stages run here, not locally (see `../docs/HPC.md`). Pattern: stage the project to
`/scratch/USER/bio_sfm_designer`, submit an sbatch, sync `hpc_outputs/` back, let the local
`Precomputed*` adapters consume the JSONL offline.

## Scripts

| Script | Stage | Status |
|---|---|---|
| `run_screen_deberta.sbatch` + `screen_deberta.py` | DeBERTa biosafety screen (intent-level) | ready — DeBERTa already on Cayuga; consume with `safety.PrecomputedScreen` |
| `run_generate.sbatch` + `generate_template.py` | generate (RFdiffusion/ProteinMPNN/ESM) | template — plug in the model; consume with `generate.PrecomputedGenerator` |
| `run_predict_boltz.sbatch` | Boltz-2 + pLDDT | reuse the audit's `run_phase2_boltz_predict.sbatch`; consume with `predict.PrecomputedStructurePredictor` |

`make_smoke_candidates.py` writes a tiny benign+hazardous `candidates.jsonl` to submit for a
DeBERTa-screen smoke. The producer↔consumer JSONL contract is locked by
`tests/test_hpc_screen_contract.py` (a fake DeBERTa proves the round-trip without the cluster).

## DeBERTa screen — quickstart

```sh
# local: write candidate intents to screen, one {"id":..., "text":...} per line
#   e.g. round-0 objectives/candidates -> candidates.jsonl

REMOTE=/scratch/$USER/bio_sfm_designer
rsync -az --exclude .venv ./ "$HPC_LOGIN:$REMOTE/"

ssh "$HPC_LOGIN" "cd $REMOTE && \
  BIOGUARD_DIR=/scratch/$USER/constitutional_bioguard \
  CONDA_ENV=bioguard \
  CANDIDATES=$REMOTE/candidates.jsonl \
  sbatch hpc/run_screen_deberta.sbatch"

# after it finishes:
rsync -az "$HPC_LOGIN:$REMOTE/hpc_outputs/screen/verdicts.jsonl" ./hpc_outputs/screen/
# local: DBTLController(screen=PrecomputedScreen("hpc_outputs/screen/verdicts.jsonl")) consumes it
#        (fail-closed: a candidate with no verdict -> human review, never silently advanced)
```

Fill in `BIOGUARD_DIR` / `CONDA_ENV` / the model path to match your existing Cayuga bioguard
install (the env where you already installed DeBERTa). Expanse: add `--account`/`--partition`.
