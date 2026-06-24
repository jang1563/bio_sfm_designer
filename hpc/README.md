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

**Bring your own trained head.** `microsoft/deberta-v3-base` (MIT, arxiv:2111.09543) is the BASE
encoder — it has no classification head, so it cannot screen by itself (a raw load gives a random
head). Set `MODEL_DIR` to a **trained** bio-harm head: a local dir, or an HF id you fine-tuned from
deberta-v3-base. The repo pins no model; the model-free default is the built-in lexicon
(`safety.SafetyScreen`). The pipeline was verified end-to-end 2026-06-23 on Cayuga using one
trained head (the public/MIT `deberta-v1`): benign intents p_unsafe 0.04–0.14 (allow), "weaponize a
select-agent toxin…" 0.997 (escalate).

```sh
HPC=cayuga-login1
REMOTE=/home/fs01/$USER/bio_sfm_designer        # or an /athena scratch path
HEAD=/path/to/your/trained-head                 # local dir or HF id fine-tuned from deberta-v3-base

python hpc/make_smoke_candidates.py --out candidates.jsonl     # local: the intents to screen
rsync -az --exclude .venv --exclude hpc_outputs ./ "$HPC:$REMOTE/"
ssh "$HPC" "cd $REMOTE && CANDIDATES=$REMOTE/candidates.jsonl MODEL_DIR=$HEAD sbatch hpc/run_screen_deberta.sbatch"

# tiny sets can skip the queue:
#   srun --partition=scu-cpu --time=00:10:00 --mem=8G env PYTHONNOUSERSITE=1 \
#     ~/.conda/envs/bioguard/bin/python hpc/screen_deberta.py \
#     --model "$HEAD" --candidates candidates.jsonl --out hpc_outputs/screen/verdicts.jsonl

rsync -az "$HPC:$REMOTE/hpc_outputs/screen/verdicts.jsonl" ./hpc_outputs/screen/
# local: DBTLController(screen=PrecomputedScreen("hpc_outputs/screen/verdicts.jsonl")) consumes it
#        (fail-closed: a candidate with no verdict -> human review, never silently advanced)
```

**`PYTHONNOUSERSITE=1` is required** — otherwise `~/.local` shadows the conda env's numpy/scipy
and transformers fails to import. `--model` takes a local dir or HF id but it must be a TRAINED
head (the deberta-v3-base encoder alone yields a random head). Expanse: add `--account`/`--partition`.
