# HPC scripts (Cayuga / Expanse)

Heavy stages run here, not locally (see `../docs/HPC.md`). Pattern: stage the project to
`/scratch/USER/bio_sfm_designer`, submit an sbatch, sync `hpc_outputs/` back, let the local
`Precomputed*` adapters consume the JSONL offline.

## Scripts

| Script | Stage | Status |
|---|---|---|
| `run_screen_deberta.sbatch` + `screen_deberta.py` | DeBERTa biosafety screen (intent-level) | ready — DeBERTa already on Cayuga |
| `run_generate_*.sbatch` (RFdiffusion/ProteinMPNN/ESM) | generate | M3 (to add) |
| `run_predict_boltz.sbatch` | Boltz-2 + pLDDT | reuse the audit's `run_phase2_boltz_predict.sbatch` pattern |

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
# local SafetyScreen then consumes verdicts.jsonl (PrecomputedScreen backend — to wire)
```

Fill in `BIOGUARD_DIR` / `CONDA_ENV` / the model path to match your existing Cayuga bioguard
install (the env where you already installed DeBERTa). Expanse: add `--account`/`--partition`.
