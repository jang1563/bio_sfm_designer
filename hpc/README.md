# HPC scripts (Cayuga / Expanse)

Heavy stages run here, not locally (see `../docs/HPC.md`). Pattern: stage the project to
`/scratch/USER/bio_sfm_designer`, submit an sbatch, sync `hpc_outputs/` back, let the local
`Precomputed*` adapters consume the JSONL offline.

## Scripts

| Script | Stage | Status |
|---|---|---|
| `run_screen_deberta.sbatch` + `screen_deberta.py` | DeBERTa biosafety screen (intent-level) | ready — DeBERTa already on Cayuga; consume with `safety.PrecomputedScreen` |
| `prep_hetdimer.py` | target prep for complex/binder runs | ready; strips two chains and rejects missing/gapped/non-contacting pairs before scale-up |
| `run_precompute_boltz_target_msa.sbatch` + `precompute_boltz_target_msa.py` | one-time target MSA for complex/binder runs | ready; runs one Boltz MSA-server job, extracts a matching `.a3m`, writes a report, then reuse via `TARGET_MSA` |
| `run_generate.sbatch` + `generate_template.py` | generate (RFdiffusion/ProteinMPNN/ESM) | template — plug in the model; consume with `generate.PrecomputedGenerator` |
| `run_generate_proteinmpnn.sbatch` + `generate_proteinmpnn.py` | ProteinMPNN monomer redesign | ready; consumes a fixed backbone PDB and writes candidates JSONL |
| `run_generate_proteinmpnn_complex.sbatch` + `generate_proteinmpnn_complex.py` | ProteinMPNN binder-chain redesign in a fixed complex | ready; pass `COMPLEX_ID=<target id>` so candidates carry `meta.complex_target_id` + target-namespaced ids for complex Boltz |
| `run_predict_boltz.sbatch` + `predict_boltz.py` | Boltz-2 monomer refold + scRMSD label | ready; consume with `predict.PrecomputedStructurePredictor` |
| `run_predict_boltz_complex.sbatch` + `predict_boltz_complex.py` | Boltz-2 complex refold + pAE/L-RMSD | ready; use `TARGET_MSA=/path/to/target.a3m` for scale-up |
| `run_chai1_smoke.sbatch` + `make_chai1_smoke_input.py` + `run_chai1_api_with_metrics.py` + `convert_chai1_complex_output.py` | W3 Chai-1 second-predictor smoke | smoke-proven; use `RUN_CHAI_FOLD=1,RUN_CHAI_API=1` to preserve pAE/PDE/pLDDT, then convert to strict complex records |

`make_smoke_candidates.py` writes a tiny benign+hazardous `candidates.jsonl` to submit for a
DeBERTa-screen smoke. The producer↔consumer JSONL contract is locked by
`tests/test_hpc_screen_contract.py` (a fake DeBERTa proves the round-trip without the cluster).

## Complex M6c scale-up quickstart

For barnase-barstar-style fixed-target binder redesigns, first prepare a clean two-chain PDB,
then generate candidates with the complex ProteinMPNN wrapper and refold them with Boltz using a
cached target MSA. The full end-to-end version is in `../docs/M6C_RUNBOOK.md`:

```sh
# 0) Prepare/validate the target+binder pair after downloading the source PDB.
#    1BRS_AD has a reviewed RCSB chain-D residue-numbering gap (D64-D65), so the
#    template manifest and this manual command opt into the narrow exception.
python hpc/prep_hetdimer.py \
  --pdb /path/to/source_1BRS.pdb --target-chain A --binder-chain D \
  --out hpc_outputs/targets/prepared_1BRS_AD.pdb \
  --report hpc_outputs/targets/prepared_1BRS_AD.report.json \
  --allow-numbering-gaps

# 1) Extract the exact fixed target sequence for one-time MSA generation.
#    The report hashes the prepared PDB and target FASTA for manifest preflight.
python hpc/extract_chain_fasta.py \
  --pdb hpc_outputs/targets/prepared_1BRS_AD.pdb --chain A --id 1BRS_A \
  --out hpc_outputs/targets/1BRS_A.fasta \
  --report hpc_outputs/targets/1BRS_A.fasta.report.json

# 2) Generate hpc_outputs/targets/1BRS_A.a3m plus report once; reuse it for every designed binder.
FASTA=hpc_outputs/targets/1BRS_A.fasta OUT=hpc_outputs/targets/1BRS_A.a3m \
REPORT=hpc_outputs/targets/1BRS_A.a3m.report.json \
  sbatch hpc/run_precompute_boltz_target_msa.sbatch
#    precompute_boltz_target_msa.py and predict_boltz_complex.py both check that this
#    MSA query matches the extracted target sequence.

# 3) Generate binder redesigns from the prepared two-chain complex PDB.
PDB=hpc_outputs/targets/prepared_1BRS_AD.pdb TARGET_CHAIN=A DESIGN_CHAIN=D NUM_SEQ=200 TEMP=0.3 \
COMPLEX_ID=1BRS_AD \
  sbatch hpc/run_generate_proteinmpnn_complex.sbatch

# 4) Reuse that same target.a3m for every designed binder; binder stays single-seq.
CANDIDATES=hpc_outputs/generate/candidates_proteinmpnn_complex.jsonl \
BACKBONE=hpc_outputs/targets/prepared_1BRS_AD.pdb TARGET_CHAIN=A BINDER_CHAIN=D \
COMPLEX_ID=1BRS_AD TARGET_MSA=hpc_outputs/targets/1BRS_A.a3m \
OUT=hpc_outputs/predict/records_boltz_complex_scale.jsonl \
  sbatch hpc/run_predict_boltz_complex.sbatch

# 5) After syncing records back locally, run the synchronized posthoc bundle:
#    QC -> alpha sweep -> scale plan -> alpha decision (+ next_batch) -> report -> project status.
python -m bio_sfm_designer.experiments.complex_posthoc_bundle \
  --records tests/fixtures/barstar_interface_records.jsonl hpc_outputs/predict/records_boltz_complex_scale.jsonl \
  --alphas 0.3,0.2,0.1 \
  --require-complex-target-id --require-provenance --require-chain-ids \
  --out-dir results/m6c_posthoc
```

If `complex_alpha_decision.json` says `continue_scale`, use its `next_batch` block for the next
ProteinMPNN `NUM_SEQ` settings. By default, it preserves the current 0.3/0.5/0.7 temperature
distribution and rounds per-temperature jobs to practical batch sizes.

To avoid overwriting temp-specific outputs by hand, render the next batch commands:

```sh
python -m bio_sfm_designer.experiments.complex_next_batch_plan \
  --manifest configs/my_complex_targets.json \
  --decision results/m6c_posthoc/complex_alpha_decision.json \
  --target-id 1BRS_AD \
  --require-files \
  --previous-records tests/fixtures/barstar_interface_records.jsonl \
  --emit-plan results/m6c_next_batch_1BRS_AD.sh
```

The plan uses one candidate JSONL and one records JSONL per temperature, then chains the Boltz
job to its matching ProteinMPNN job with `sbatch --dependency=afterok`. `--require-files`
runs the selected target through the same FASTA/MSA/report/prep-report preflight used by the manifest
validator before any submit commands are emitted, and the emitted shell plan replays that preflight
before any `sbatch`. By default, the planner also requires the
`complex_alpha_decision.json` input to include passing strict QC provenance plus chain ids, and emits a
strict posthoc rerun command.

For the >=3-target generalization step, copy `configs/template_complex_targets.json`, replace the
placeholder targets/paths, then render target-MSA jobs before the strict submit plan:

```sh
python -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest configs/my_complex_targets.json \
  --emit-msa-plan results/m6c_target_msas.sh

python -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest configs/my_complex_targets.json --require-files --min-targets 3 \
  --out results/m6c_targets_manifest.json --emit-plan results/m6c_targets_submit.sh

python -m bio_sfm_designer.experiments.complex_panel_report \
  --records hpc_outputs/m6c_targets/*/records_boltz_complex.jsonl \
  --min-targets 3 --target-alpha 0.2 --out results/m6c_panel_report.json
```

With `--require-files`, the manifest validator checks each prepared PDB, target FASTA, target
MSA, optional prep report, and the target FASTA/MSA sequence agreement before marking a target
ready. The emitted plan captures each ProteinMPNN job id with `sbatch --parsable`, submits the
matching Boltz job with `--dependency=afterok`, and makes `NUM_SEQ`, `TEMP`, `SEED`, and
`OBJECTIVE` explicit from manifest `defaults` or per-target overrides. A wrong `.a3m` query is
rejected before ProteinMPNN/Boltz spend.

`TARGET_MSA` and `USE_MSA_SERVER=1` are mutually exclusive. Prefer `TARGET_MSA` for scale-up; it
avoids repeated identical target queries while keeping designed binders in the intended single-sequence
mode. On Cayuga, keep `ENV_PY` pointed at the Boltz conda Python for target-MSA precompute; if Boltz writes
a matching `.a3m` and then fails during the tiny structure-prediction tail, the helper recovers the `.a3m`
instead of discarding the MSA. The report keeps declared `fasta`/`out` paths repo-relative when called that
way, with absolute paths stored separately as `fasta_abs`/`out_abs` for debugging.

Before submitting a real scale or panel batch, render a readiness bundle:

```sh
python -m bio_sfm_designer.experiments.complex_readiness \
  --decision results/m6c_posthoc/complex_alpha_decision.json \
  --target-manifest configs/my_complex_targets.json \
  --scale-target-id 1BRS_AD \
  --previous-records tests/fixtures/barstar_interface_records.jsonl \
  --require-files \
  --out results/m6c_readiness.json \
  --emit-plan results/m6c_readiness.sh
```

This aggregates selected-target preflight, strict next-batch planning, panel-manifest checks when requested,
and second-predictor contract checks when supplied.

For the independent-predictor step, copy `configs/template_second_predictor_contract.json`, fill in the
synced second-predictor records path and provenance fields, then run:

```sh
python -m bio_sfm_designer.experiments.complex_predictor_contract \
  --contract configs/my_second_predictor_contract.json \
  --require-files --run-record-qc \
  --out results/m6c_second_predictor_contract.json \
  --emit-plan results/m6c_second_predictor_commands.sh
```

That plan emits the strict second-record QC command and the matched cross-predictor comparison command.

For the Chai-1 path specifically, the CLI fold confirms model execution but does not persist pAE in
`scores.model_idx_*.npz`. Use the API wrapper for W3 records:

```sh
cd "${CAYUGA_BIO_SFM_ROOT:-$HOME/bio_sfm_smoke}"
sbatch --export=ALL,RUN_CHAI_FOLD=1,RUN_CHAI_API=1 hpc/run_chai1_smoke.sbatch

PYTHONNOUSERSITE=1 "${BIO_SFM_CHAI_PYTHON:-$HOME/.conda/envs/chai1/bin/python}" \
  hpc/convert_chai1_complex_output.py \
  --manifest hpc_outputs/m6c_second_predictor/chai1_smoke/input_manifest.json \
  --chai-out hpc_outputs/m6c_second_predictor/chai1_smoke/chai_output \
  --backbone hpc_outputs/targets/prepared_3PC8_AB.pdb \
  --out hpc_outputs/m6c_second_predictor/chai1_complex_records.jsonl \
  --threshold 4.0
```

The one-candidate smoke receipt is `results/m6c_w3_chai1_smoke_receipt.{json,md}`. It proves the
converter path only; W3 still needs enough matched secondary records for the contract and cross-predictor
audit.

## DeBERTa screen — quickstart

**Bring your own trained head.** `microsoft/deberta-v3-base` (MIT, arxiv:2111.09543) is the BASE
encoder — it has no classification head, so it cannot screen by itself (a raw load gives a random
head). Set `MODEL_DIR` to a **trained** bio-harm head: a local dir, or an HF id you fine-tuned from
deberta-v3-base. The repo pins no model; the model-free default is the built-in lexicon
(`safety.SafetyScreen`). The pipeline was verified end-to-end 2026-06-23 on Cayuga using one
trained head (the public/MIT `deberta-v1`): benign intents p_unsafe 0.04–0.14 (allow), "weaponize a
select-agent toxin…" 0.997 (escalate).

```sh
HPC=${CAYUGA_BIO_SFM_HOST:?set Cayuga login host}
REMOTE=${CAYUGA_BIO_SFM_ROOT:-$HOME/bio_sfm_designer}  # or a scratch path
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
