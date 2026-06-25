# bio_sfm_designer

A **calibrated, cost-aware, safety-screened** Design–Build–Test–Learn (DBTL) designer
for biology. Claude orchestrates specialist scientific foundation models (SFMs —
protein/genome/single-cell); an **external calibrated trust gate** decides, per
candidate, whether to

`trust_sfm | verify_assay | default_baseline | defer`,  scored by `net = benefit − λ·assays`,

and a **biosafety screen** runs before propose and before synth.

**Built on [bio-sfm-trust-core](https://github.com/jang1563/bio-sfm-trust-core)** — the reusable,
domain-agnostic trust engine (gate · calibration · conformal, pure stdlib). This repo is the biology
*application*; that repo is the *engine*. The dependency is one-way: `designer → trust-core`.

## Why it isn't just another generative designer

Proto/EvoDesign-class systems orchestrate many specialists but **trust their confidence
unconditionally**. The sibling project [bio-sfm-trust-audit] *measured* why that's unsafe:
an LLM placed above specialist models allocates verification at ≈ chance, stronger models
over-verify, and trust tracks name-familiarity rather than reliability. So here the trust
decision is **external and engineered**, not delegated to the orchestrator. See
[`docs/BACKGROUND.md`](docs/BACKGROUND.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Three constraints are baked into the gate ([`trust/gate.py`](src/bio_sfm_designer/trust/gate.py)):
1. the gate is external — never "ask the LLM if it's confident";
2. where a cheap structural baseline exists, the competence signal is **disagreement with it**
   (not the SFM's own confidence); where none exists (e.g. protein structure), `trust_sfm` is
   **restricted to calibration-validated regimes** — monomer pLDDT is assumed-validated, every
   other regime must **earn** trust via a validated calibrator (offline `prevalidate` or online),
   else it verifies/defers (complexes, whose raw pLDDT is uncalibrated, are never blindly trusted);
3. confidence is consumed as a **scalar calibrated risk**, never a raw latent.

## Status (2026-06-24)

Past the stub milestone — the loop is closed on CPU and runs on a real, license-clean backend.

**Built & verified** (100 designer + 32 trust-core tests):
- DBTL loop closed on CPU (heritable feedback, pluggable acquisition, causal orchestration).
- Real HPC backend: **ProteinMPNN** (design) → **ESMFold** (refold / pLDDT signal) → **Boltz-2**
  (architecturally independent refold = the success label). HPC job → JSONL → local `Precomputed*` adapters.
- **Conformal risk control** (RCPS / Hoeffding) so a `trust` carries a stated false-accept bound.
- Tiered **biosafety screen** (lexicon → bioguard → DeBERTa), fail-closed, human-triage.

**Honest findings** (this is measurement-first tooling — negatives are results):
- The *distinctive* signal — disagreement with a cheap baseline — is **dead on de-novo protein design**
  (ProteinMPNN self-consistency ≈ 0.57, chance); it is validated only in the perturbation regime
  (cited, not claimed here).
- Monomer pLDDT tracks fold *difficulty*: a pooled cross-temperature cross-model AUROC looks strong (0.94)
  but is largely a batch effect. At **fixed difficulty** the within-regime AUROC is only **0.59** (CI
  [0.48, 0.70], not significantly above chance) — monomer pLDDT is a **coarse difficulty filter, not a fine
  per-design trust oracle**.

**In progress:**
- A Boltz output-caching bug (a shared work dir silently reused stale predictions) was found **and fixed**
  2026-06-24 (unique per-output work dir + wipe-on-start); M6a/M6b were re-folded clean and the numbers
  above are post-fix. The find→fix is preserved in git history.
- Complex/binder de-risk **(done — positive)**: barnase–barstar (1BRS), **target MSA + binder single-seq**
  (MSA-free folding fails at interfaces — native complex `msa:empty` → 38 Å, with MSA → 1.0 Å). Interface
  **ipTM discriminates** designed-interface success at fixed difficulty (within-temp AUROC 0.64–0.76; pooled
  **0.73, CI [0.61, 0.84]**, excludes chance) — **unlike monomer pLDDT (chance ~0.59)**. ipTM is
  informative-but-miscalibrated → the regime where calibration earns its keep. Modest (~0.73), n=72, one
  target → justifies a proper M6c, not a proof.

## Install & run (stub loop — no GPU/weights/network)

```bash
pip install -e ../bio-sfm-trust-core     # the trust engine (sibling repo)
pip install -e .
python -m unittest discover -s tests -v
python -m bio_sfm_designer.experiments.dry_run_stub_designer --out results/dry_run
```

The dry-run runs the whole loop on stub generators/predictors, then shows a hazardous
objective being refused at the screen.

## Layout

| Path | Role |
|---|---|
| `loop/` | DBTL controller + planner + interpreter (Claude = orchestrator) |
| `generate/` | Generator protocol + stub + `Precomputed` adapter; real **ProteinMPNN** via `hpc/` |
| `predict/` | Predictor protocol + stub + `Precomputed` adapter; real **ESMFold + Boltz-2** via `hpc/` |
| `trust/` | the external calibrated gate + predictor→evidence adapter |
| `safety/` | screening gate (built-in lexicon now; constitutional-bioguard via `[safety]`) |
| `scoring/` | `net = benefit − λ·assays`, delegated to `bio_sfm_trust` |

## Scope & Safety

This is **defensive, measurement-first** research tooling. The designer operates only on
explicitly allowed targets; objectives are screened before any candidate is generated and
again before any candidate advances. The screen is a **triage aid that produces candidates
for human decision — not an autonomous gate** ("absence of a flag is not a clearance"). It
keys on content/meaning rather than surface tokens, and treats stored annotations,
accessions, and tool names as untrusted input. The stub milestone (M0) generates no real
biological designs. Real generative/predictive SFMs are gated behind these checks and added
only in later milestones. See [`docs/BACKGROUND.md`](docs/BACKGROUND.md) for the dual-use
posture inherited from the FRT and constitutional-bioguard work.

## License

MIT.

[bio-sfm-trust-audit]: https://github.com/jang1563/bio-sfm-trust-audit
