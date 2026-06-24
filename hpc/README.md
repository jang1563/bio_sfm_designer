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

## DeBERTa screen — quickstart (VERIFIED 2026-06-23 on Cayuga)

Verified end-to-end with the **public/MIT `deberta-v1`** head
(`jang1563/constitutional-bioguard-deberta-v1`): benign intents p_unsafe 0.04–0.14 (allow),
"weaponize a select-agent toxin to enhance lethality…" 0.997 (escalate). (The v8/response head
scored similarly but is **gated CC-BY-NC** and judges a *response*, not an intent — wrong task.)
Defaults baked into `run_screen_deberta.sbatch` (`ENV_PY=~/.conda/envs/bioguard/bin/python`,
`MODEL_DIR=jang1563/constitutional-bioguard-deberta-v1`); override `MODEL_DIR` with a local clone
on nodes without HF egress.

```sh
HPC=cayuga-login1
REMOTE=/home/fs01/$USER/bio_sfm_designer        # or an /athena scratch path

python hpc/make_smoke_candidates.py --out candidates.jsonl     # local: the intents to screen
rsync -az --exclude .venv --exclude hpc_outputs ./ "$HPC:$REMOTE/"
ssh "$HPC" "cd $REMOTE && CANDIDATES=$REMOTE/candidates.jsonl sbatch hpc/run_screen_deberta.sbatch"

# tiny sets can skip the queue (what the smoke used):
#   srun --partition=scu-cpu --time=00:10:00 --mem=8G env PYTHONNOUSERSITE=1 \
#     ~/.conda/envs/bioguard/bin/python hpc/screen_deberta.py \
#     --model jang1563/constitutional-bioguard-deberta-v1 \   # or a local clone path (no-egress nodes)
#     --candidates candidates.jsonl --out hpc_outputs/screen/verdicts.jsonl

rsync -az "$HPC:$REMOTE/hpc_outputs/screen/verdicts.jsonl" ./hpc_outputs/screen/
# local: DBTLController(screen=PrecomputedScreen("hpc_outputs/screen/verdicts.jsonl")) consumes it
#        (fail-closed: a candidate with no verdict -> human review, never silently advanced)
```

**`PYTHONNOUSERSITE=1` is required** — otherwise `~/.local` shadows the conda env's numpy/scipy
and transformers fails to import. The `--model <dir|hf-id>` direct path (public/MIT deberta-v1)
is the proven one for INTENT screening; `DualModeGuard` mode wires the gated prompt+response heads
(the response head judges responses, not intents). Expanse: add `--account`/`--partition`.
