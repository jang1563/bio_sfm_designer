# Compute model: HPC-first (Cayuga / Expanse)

Local computing is insufficient for the heavy stages. The designer follows the same split the
sibling **bio-sfm-trust-audit** already uses (see its `HPC_RUNBOOK.md` "Cayuga / Expanse" and
`hpc/*.sbatch`): **GPU/model work runs on Cayuga (default) or Expanse (scale-out) via SLURM;
local runs only the orchestration, gate, scoring, and tests.** The bridge is precomputed JSONL
— exactly what M1 already does (Boltz-2 on Cayuga → `records.jsonl` → local consumes offline).

## Where each stage runs

| Stage | Runs on | Why |
|---|---|---|
| DBTL controller, trust gate, scoring, safety **policy/lexicon**, tests, dry-run | **Local** (or login node) | pure-Python, no GPU |
| Claude **orchestrator** (interpreter) + **label-integrity** check | **Local or Cayuga login node** | API calls — network, not GPU (key in `~/.api_keys`, per the audit RUNBOOK) |
| **Generate**: RFdiffusion / ProteinMPNN / ESM | **Cayuga/Expanse (GPU)** | model inference |
| **Predict**: Boltz-2 + pLDDT/ipTM, CA-lDDT truth | **Cayuga/Expanse (GPU)** | model inference (M1 already does this) |
| **Safety DeBERTa** screen (constitutional-bioguard) | **Cayuga** | DeBERTa **already installed there** (`scripts/cayuga_v*_*.slurm`); torch/weights present |

## The bridge (one pattern for every heavy stage)

```
local: write inputs JSONL  ──rsync──▶  Cayuga /scratch/USER/bio_sfm_designer
                                          │  sbatch hpc/run_<stage>.sbatch   (GPU/SLURM)
                                          ▼
                                       hpc_outputs/<stage>/*.jsonl
local: Precomputed<Stage> adapter  ◀──rsync──  (synced back)
       consumes the JSONL OFFLINE → controller routes/scores as usual
```

This is the **M1 design generalized**: `predict/structure.py::PrecomputedStructurePredictor`
reads Boltz-2 records produced on Cayuga. Generators and the DeBERTa screen get the same
"HPC job → JSONL → local `Precomputed*` adapter" shape. The loop is therefore **batch-per-round
(async)**, not a tight interactive loop — each Build/Test round is a submitted batch; the Claude
orchestrator runs between rounds. That matches how real DBTL campaigns (and the audit) work.

## Run one round from synced artifacts

Once a round's JSONL is synced back, one command wires all three consume-side adapters and
runs the local half of the round:

```sh
python -m bio_sfm_designer.experiments.run_batch_round \
  --candidates hpc_outputs/generate/candidates.jsonl \
  --records    hpc_outputs/predict/records.jsonl \
  --verdicts   hpc_outputs/screen/verdicts.jsonl \
  --target "..." --objective thermostability --out results/round_0
```

It builds `PrecomputedGenerator + PrecomputedStructurePredictor + PrecomputedScreen`, routes via
the calibrated trust gate, screens before synth, scores `net = benefit − λ·assays`, and writes
`campaign.jsonl` + `summary.json`. Omit `--verdicts` to fall back to the built-in screen; add
`--provider anthropic` for the live LLM orchestrator. One invocation = one async HPC round.

## Revised milestones (HPC-aware)

- **M2-live (was "real backends locally") → Cayuga jobs:**
  - **DeBERTa screen** = `hpc/run_screen_deberta.sbatch` → `screen_deberta.py` reads a candidates
    JSONL, scores with a TRAINED bio-harm head supplied via `MODEL_DIR` (the repo pins no model;
    `microsoft/deberta-v3-base` (MIT) is the base encoder these heads fine-tune from — it can't
    screen on its own), writes `verdicts.jsonl`.
    Local: `safety.PrecomputedScreen` reads the synced verdicts (fail-closed on missing — a
    candidate with no verdict routes to human review, never silently advances); it's a drop-in
    `DBTLController(screen=...)`. The in-process `_load_deberta()` in `safety/screen.py` stays
    only as a login-node convenience.
  - **Claude orchestrator / label-integrity** = live API from local or login node (no GPU).
- **M3 generators → Cayuga jobs:** RFdiffusion/ProteinMPNN/ESM behind the `Generator` protocol,
  each an sbatch writing a candidate JSONL; local `PrecomputedGenerator` consumes it.
- **Predict (M1)** already runs this way; extend to live Boltz-2 batches on Cayuga for new targets.

## Conventions (mirror the audit RUNBOOK)

- Stage to `/scratch/USER/bio_sfm_designer`; submit via `ssh <HPC_LOGIN> "cd $REMOTE && sbatch hpc/run_<stage>.sbatch"`.
- sbatch headers write logs to `hpc_outputs/logs/`; inputs/outputs are env-var overridable.
- Reuse existing Cayuga conda envs (bioguard for DeBERTa; a Boltz env for structure). Expanse:
  pass `--account YOUR_ACCOUNT --partition YOUR_PARTITION` at submit time.
- API keys: `source ~/.api_keys` (the audit convention), never in code; rotate the exposed key first.

See `hpc/README.md` for the per-stage scripts. Local code stays agnostic to where the JSONL came from.
