# bio_sfm_designer — Handoff

Self-contained context to continue this project in a fresh session (Codex or otherwise) with **no prior
conversation history**. Read this top to bottom once; it links to the code that matters.

> One-line status (2026-06-25): the trust-gate thesis is demonstrated **end-to-end on the complex/binder
> regime** — interface confidence (pAE_interaction) discriminates designed-interface success, the gate
> routes on it, and **RCPS certifies a distribution-free false-accept bound (α=0.3) on 192 designs**. The
> monomer regime was honestly shown to carry **no** fine per-design trust signal. Next = scale (α≤0.2),
> more targets, an independent 2nd predictor.

---

## 1. What this project is (goal + thesis)

A **calibrated, cost-aware, safety-screened Design–Build–Test–Learn (DBTL) designer** for proteins.
Claude is the **orchestrator** (not an oracle) over specialist scientific foundation models (SFMs —
ProteinMPNN, ESMFold, Boltz-2). The intellectual core is an **external, engineered trust gate** that
decides, per candidate,

```
trust_sfm | verify_assay | default_baseline | defer      scored by  net = benefit − λ·assays
```

plus a second gate, a **biosafety screen**, before propose and before synth.

**Why the gate is external/engineered (the founding result, from the sibling `bio-sfm-trust-audit`):** an
LLM placed above specialist models allocates verification at ≈ chance, stronger models over-verify, and
trust tracks name-familiarity. So trust is **not delegated to the orchestrator** — it is keyed on a
**calibrated scalar risk**, with three hard constraints baked into `trust/gate.py`:
1. the gate is external — never "ask the LLM if it's confident";
2. the competence signal is **disagreement with a cheap baseline** where one exists (Bayes-optimal
   deferral); where none exists, `trust_sfm` is **restricted to calibration-validated regimes**;
3. confidence is consumed only as a **scalar calibrated risk**, never a raw latent.

**Goal of the current phase:** prove the thesis *dynamically on real protein data* — turn "the gate helps"
from assumed into measured — and harden it with conformal (distribution-free) risk control.

## 2. Repos, setup, how to run

Two local git repos (both pushed to **private** GitHub under `jang1563`):

| repo | path | GitHub | role |
|---|---|---|---|
| `bio-sfm-trust-core` | `…/Claude/bio-sfm-trust-core` | `jang1563/bio-sfm-trust-core` | **engine** (pure stdlib): TrustGate calibration, isotonic, RCPS conformal, metrics |
| `bio_sfm_designer` | `…/Claude/bio_sfm_designer` | `jang1563/bio_sfm_designer` | **application**: DBTL loop, ProteinMPNN/ESMFold/Boltz HPC bridges, biosafety screen |

Dependency is one-way: `designer → trust-core`. (There is also a third sibling, `bio-sfm-trust-audit`,
the measurement project the engine was extracted from — referenced, not required here.)

```bash
# fresh venv (NOTE: /tmp is ephemeral — recreate when gone; needs modern pip for PEP 660 editable installs)
python3 -m venv /tmp/bio_sfm_venv && /tmp/bio_sfm_venv/bin/pip install -U pip
/tmp/bio_sfm_venv/bin/pip install -e ../bio-sfm-trust-core -e . numpy
/tmp/bio_sfm_venv/bin/python -m unittest discover -s tests            # 107 designer tests, all green
/tmp/bio_sfm_venv/bin/python -m unittest discover -s ../bio-sfm-trust-core/tests   # 32 trust-core tests
```

The honest results live in committed experiments + fixtures (no GPU needed to re-run the analyses):

```bash
python -m bio_sfm_designer.experiments.within_regime_signal      # monomer: signal is CHANCE at fixed difficulty
python -m bio_sfm_designer.experiments.cross_model_auroc         # monomer: cross-model AUROC + the temp confound
python -m bio_sfm_designer.experiments.complex_interface_signal  # complex: pAE_interaction discriminates (the win)
python -m bio_sfm_designer.experiments.conformal_complex_gate    # complex: RCPS certifies α=0.3, gate vs trust-all
```

## 3. Architecture

- `loop/` — DBTL controller + planner + acquisition + interpreter (Claude = orchestrator; live provider seam exists, mockable).
- `generate/` — Generator protocol + stub + `PrecomputedGenerator` (consumes HPC JSONL).
- `predict/` — Predictor protocol + stub + `PrecomputedStructurePredictor`.
- `trust/` — the external calibrated `TrustGate` (per-regime calibration-validated trust; conformal mode).
- `safety/` — tiered biosafety screen (lexicon → bioguard lexicon → DeBERTa head); **a human-triage aid, NOT an autonomous gate** ("absence of a flag is not a clearance"); fail-closed.
- `scoring/` — `net = benefit − λ·assays`, delegated to `bio_sfm_trust`.
- `hpc/` — Cayuga-side runners; **HPC bridge pattern = SLURM job → JSONL → local `Precomputed*` adapter** (heavy compute on the cluster, local = orchestration + gate + tests).

## 4. Roadmap & status

| milestone | status | what |
|---|---|---|
| M0–M2 | ✅ | scaffold, offline gate on real PDBs, per-regime calibration, live-Claude seam, **biosafety screen** (+HPC head training) |
| M3 | ✅ | DBTL loop **closed on CPU** (heritable feedback, pluggable acquisition, causal orchestration) |
| M4 | ✅ | first real backend: **ProteinMPNN → ESMFold** refold; pLDDT→self-consistency AUROC (single-model caveat) |
| M5a/M5b | ✅ | **conformal risk control** (RCPS/Hoeffding) + the conformal gate on real designs |
| M6a | ✅ | independent **Boltz-2** refold → honest cross-model AUROC (monomer) |
| M6b | ✅ | **clean within-regime test** → monomer pLDDT signal is **chance** at fixed difficulty |
| M6c-lite | ✅ | **complex/binder de-risk** → **pAE_interaction discriminates** (the regime where the gate works) |
| **M6c (live frontier)** | 🔨 | gate on the complex regime: **RCPS certifies α=0.3 at n=192**. Remaining = §8 |
| M6d/M6e/M6f | ⬜ | RFdiffusion de-novo binders · live Claude (blocked on P0 key) · DX one-command campaign |

Full milestone detail (with definitions of done) is in the plan: `~/.claude/plans/velvety-greeting-dijkstra.md`
(local to JK; the essentials are reproduced here).

## 5. The honest findings (the heart of the project)

This is **measurement-first** tooling — negative and corrected results are the deliverable. The defining
pattern: every headline number was adversarially re-reviewed, and several were corrected.

1. **The distinctive signal (cheap-baseline disagreement) is DEAD on de-novo protein design.** ProteinMPNN
   self-consistency score ≈ 0.57 (chance); `has_baseline=False`. It is validated only in the *perturbation*
   regime (CausalAtlas 0.88 AUROC) — **cite that, do not imply it was validated on protein design.**
2. **Monomer confidence is a coarse difficulty filter, not a fine trust signal.** A pooled cross-temperature
   AUROC looks strong (~0.95) but is a **temperature batch effect**; at *fixed* difficulty the within-regime
   AUROC is **~0.59 (chance)**, CI spans 0.5. (`within_regime_signal.py`.)
3. **The complex/binder regime DOES have a real interface signal — and it's `pAE_interaction`, not ipTM.**
   At fixed difficulty: pAE stratified AUROC **0.93**; and **0.88 even among well-folded binders** (foldability
   controlled), where **ipTM is weak (~0.59)** and complex-pLDDT is just foldability. (`complex_interface_signal.py`.)
   pAE is informative-but-optimistically-miscalibrated → exactly what calibration + selective deferral are for.
4. **The gate works on the complex regime, with a guarantee.** Routing on calibrated pAE, RCPS **certifies
   α=0.3** at n=192: trusts 25/64 held-out at **12% false-accept vs 60% trust-all**. (`conformal_complex_gate.py`.)

**Net thesis status:** the calibrated trust gate adds value **in the complex/binder regime** (broken-but-
informative confidence) — *not* on monomers (well-calibrated but uninformative-at-fixed-difficulty) and *not*
via the disagreement route on protein design. This is a coherent, defensible, honestly-bounded position.

## 6. Key decision points (forks + why)

- **Drifted into the safety screen, then re-centered on the design engine** (the screen is one of two gates,
  was over-invested; now done). The thesis is the *gate + generative loop*, not the screen.
- **Monomer → complex pivot.** After M6b showed monomers carry no fine signal, the thesis's "last stand" was
  the complex regime (where confidence is genuinely broken-but-informative). JK chose to **de-risk it cheaply**
  before committing to a heavy full M6c.
- **Target choice for the complex de-risk:** 4YOW (homotrimer) was **abandoned** — isolating 2 chains breaks
  the geometry (native L-RMSD 33–47 Å) and C3 symmetry makes per-chain L-RMSD ambiguous. Switched to
  **barnase–barstar (1BRS, chain A target / D binder)** — a clean obligate heterodimer, gap-free.
- **MSA is mandatory for interfaces.** MSA-free (`msa:empty`) folds monomers fine but **fails at complexes**
  (native barnase–barstar `msa:empty` → 38 Å; **with MSA → 1.0 Å**). Protocol = **target gets an MSA, binder
  stays single-sequence** (designs have no homologs). `predict_boltz_complex.py --use-msa-server`.
- **The metric is `pAE_interaction`, corrected twice.** First pass wrongly headlined ipTM (temp-inflated +
  weak); review showed pLDDT works but is foldability; the real interface-quality signal is **pAE_interaction**
  (which the first runs hadn't even captured). Lesson: use the metric the binder-design field uses, and control
  for foldability.

## 7. Where M6c stands now (live frontier)

- Fixture: `tests/fixtures/barstar_interface_records.jsonl` — **192 barstar redesigns** (1BRS A+D, temps
  0.3/0.5/0.7, target-MSA + binder single-seq), each with `iptm`, `ptm`, `mean_plddt`, `pae_interaction`,
  `lrmsd`, `truth.correct` (= L-RMSD < 4 Å).
- `confidence_to_risk` (trust-core) now **prefers `pae_interaction` for complexes** (risk = pae/30), falling
  back to the old pLDDT+ipTM blend then pLDDT. `Prediction` carries `pae_interaction`.
- `conformal_complex_gate.py` (defaults α=0.3, n_cal=128): **certifies τ=0.071**, gate trusts 25/64 held-out
  at 12% false-accept (≤ α) vs trust-all 60%. α≤0.2 still *refuses* (Hoeffding n↔α tradeoff).

## 8. Next steps (concrete, prioritized)

1. **FIRST fix the MSA inefficiency, then scale.** `--use_msa_server` currently queries the ColabFold server
   **once per design** — 120 redundant *identical* barnase-target queries cost ~90 min. **Pre-compute the
   target MSA once** (save the `.a3m`, reference it in each YAML's `msa:` field) so folds are ~50 s each.
   Then generate hundreds more barstar designs → certify **α≤0.2** (tighter guarantee).
2. **More targets (≥3 clean heterodimers)** → show the result generalizes beyond barnase–barstar. Use the
   `prep_hetdimer.py`-style flow (RCSB download → strip to a cognate pair → check gap-free + interface contacts).
3. **Independent 2nd complex predictor** (e.g. Chai-1; AF2/AF3 only if license permits — see landmines) to
   close the **single-model caveat** (pAE + the L-RMSD label currently both come from the one Boltz fold), as
   M6a did for monomers.
4. Optional: **RFdiffusion** de-novo binder backbones (vs ProteinMPNN interface redesign on a fixed backbone).
5. **P0 (blocks live Claude / M6e):** an exposed `sk-ant-` key exists in a *different* Dropbox dir
   (`…/Claude/API_key/…`, gitignored, NOT in these repos) — **rotate/revoke it** before any live-Claude run.
   That is JK's to do; do not touch the key files.

## 9. HPC (Cayuga) specifics + gotchas / landmines

- Access: `ssh cayuga-login1`. Working dir `~/bio_sfm_smoke/` (mirrors `hpc/`, holds `hpc_outputs/`).
  ProteinMPNN checkout at `~/ProteinMPNN`. Login node **has internet** (curl/MSA server); so do compute nodes.
- Conda envs (`module load anaconda3/2023.09-3` first): **`bioguard`** (ProteinMPNN + ESMFold via transformers,
  torch 2.6) and **`boltz`** (Boltz-2 2.2.x, torch 2.12). Partition `scu-gpu` (a40/a100/h100); submit with the
  `hpc/run_*.sbatch` files.
- **Always `export PYTHONNOUSERSITE=1`** before Boltz — else `~/.local` shadows the env's torch (and pip will
  silently skip installing torch into the env). Boltz needs **`--no_kernels`** (no cuequivariance on the cluster).
- **Boltz output caching bug (FIXED — do not regress):** Boltz **skips** any prediction whose output already
  exists. Two runs sharing one work dir → silent reuse of stale structures (this corrupted an early M6b run).
  Fix in `predict_boltz.py` / `predict_boltz_complex.py`: the work dir is **unique per output file AND wiped on
  start**. Keep distinct `OUT` per run.
- **Crystal gaps:** unmodeled residues come through ProteinMPNN as `X`; `generate_proteinmpnn_complex.py`
  **drops them** to get the continuous modeled sequence (a 2-residue barstar gap once voided every design).
- **Quoting:** zsh/ssh eat backticks and `(`/`)` inside `bash -lc "…"`; use quoted heredocs and avoid parens in
  `echo`. Git commit messages with backticks → `git commit -F - <<'MSG'`.
- The `/tmp/bio_sfm_venv` is **ephemeral** (cleared periodically); recreate per §2. Analyses are pure-stdlib
  (no numpy) except the Kabsch/PAE bits.

## 10. Key file map

- Engine: `bio-sfm-trust-core/src/bio_sfm_trust/{gate.py (confidence_to_risk, TrustGate helpers), calibration.py, conformal.py (rcps_threshold), metrics.py}`
- Gate: `src/bio_sfm_designer/trust/gate.py` (per-regime conformal τ routing); `types.py` (`Prediction.pae_interaction`)
- HPC runners: `hpc/{generate_proteinmpnn.py, predict_esmfold.py, predict_boltz.py, generate_proteinmpnn_complex.py, predict_boltz_complex.py}` + matching `run_*.sbatch`
- Experiments (each has a contract/result test in `tests/`): `experiments/{within_regime_signal, cross_model_auroc, complex_interface_signal, conformal_complex_gate, conformal_design_gate, closed_loop_campaign}.py`
- Fixtures: `tests/fixtures/{esmfold_designs_records, boltz_designs_records, esmfold_t07_records, boltz_t07_records, barstar_interface_records}.jsonl`

## 11. The meta-lesson (please preserve)

This project's value is **honest measurement**, not a win. In one stretch it caught — by adversarial
re-review — a temperature confound, a single-model-self-consistency inflation, a data-integrity caching bug,
two wrong interface metrics, and a degenerate target choice. **Default to reviewing your own headline number
before trusting it:** check the temperature/difficulty confound (analyze *within* a fixed regime), the
single-model circularity (signal and label from the same model), the small-n CIs, and whether the "signal" is
really the thing you claim or a proxy (foldability vs interface quality). Report caveats plainly; let RCPS
refuse rather than over-promise. Guarantees over vibes.
