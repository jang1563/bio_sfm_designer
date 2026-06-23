# bio_sfm_designer — Research & Strategic Background

> Consolidated background for the designer project, synthesized from five upstream
> projects in this workspace. Purpose: let `bio_sfm_designer` carry rich context from
> day one instead of re-deriving it. All findings below are **pilot-scale and measured,
> not settled** — match that register in any public framing.

`bio_sfm_designer` = a generative + predictive biology **Design–Build–Test–Learn (DBTL)**
designer with **Claude as orchestrator** over specialist scientific foundation models
(SFMs: protein / genome / single-cell). It reuses a **calibrated trust gate**
(`trust_sfm | verify_assay | default_baseline | defer`) as the per-candidate routing
engine and a **biosafety screening gate** before propose & before synth.

---

## The through-line (one thesis, five projects)

> A frontier LLM's job in science is to **GROUND and ROUTE, not to KNOW.** Capability
> lives in callable specialist SFMs; the LLM's value is orchestration; **calibration is
> the load-bearing part that makes orchestration safe.** The designer is the generative
> loop wrapped around that calibrated routing decision — and the audit work proves the
> LLM *cannot be trusted to make that routing decision unaided.*

The upstream projects are not loosely related; they are **two consecutive halves of this
designer, already measured** (an a-priori trust layer + a verify-or-trust layer), plus a
safety spine and a strategic frame.

---

## Upstream map — what the designer inherits

### 1. `LLM_SFM_interpretability` — release name **bio-sfm-trust-audit**
Importable harness: `experiments/trust_cue_attribution/` (note: package is **nested**, not
flat; repo has **no `pyproject.toml`** yet → not pip-installable as-is).

- **Action grammar (reuse verbatim):** `trust_sfm | verify_assay | default_baseline | defer`,
  scored `net = correct − λ·assays` (verification price λ; primary λ = 0.5). Source:
  `experiments/trust_cue_attribution/actions.py` (`ACTIONS` tuple + aliases).
- **Isotonic calibration lives in `phase2_calibrated_gate.py`** (`isotonic_calibrator()` +
  PAV + **leave-one-out** `raw_risk → P(wrong)`) — **NOT** in `analysis.py`. Beware the
  near-twin filename `phase2_calibration_gate.py` (a different, deterministic regime gate).
- **Phase 2 truth:** `phase2_truth.py` computes superposition-free **CA-lDDT** via gemmi as
  ground truth for Boltz-2 predictions; pLDDT→lDDT Pearson **0.89 monomers / 0.16 complexes**
  (the designed monomer→complex calibration gap = routing stakes for free).
- **Headline findings (cautionary, not celebratory):**
  1. *Cue-sensitivity* — the LLM routes far better with any reliability signal than none,
     but also follows misleading signals (extends Turpin et al. 2023 into a calibrated-signal regime).
  2. *Presentation vs enforcement* — **surfacing raw calibrated confidence is the robust
     lever**; repackaging it as a directive "reliability card" is NOT a free win.
     Presentation is insufficient → **enforcement (tools / MCP constraints / post-training)**
     is the named next lever.
  3. *Model-dependence* — the card backfires on more risk-averse models: Opus 4.8
     over-verifies (97.5% verify) and is significantly worse than raw confidence
     (Δnet −0.225). Benefit, where present, is **informational, not directive**.
- **Substrate selection discipline:** only build the loop where the specialist (a) beats a
  cheap baseline non-trivially AND (b) emits a validated calibrated confidence. Protein
  structure (Boltz-2/pLDDT) qualifies; single-cell (scFoundation) did **not** (NO-GO, cue
  near-noise AUROC 0.599).
- **Enforcement seam already in the harness:** trajectory / preference-pair / router
  scaffolding + a `tool_calls` schema slot — the bridge from audit to a designer/RL loop.

### 2. `Bio_Grounding_Eval` — **GroundAtlas** (`grounding-atlas`, HF: `jang1563/grounding-atlas`)
The **a-priori (pre-call) layer** of the trust gate.

- Core question: does the LLM do biology by the **content** of a representation or just its
  **name**? Two-axis decomposition: **encoding** (linearly present in hidden states) vs
  **verbalization** (does it say it).
- **The web-exposure law:** the verbalization gap tracks how web-documented the
  representation→property mapping is — usable as an **a-priori routing/risk prior before any
  model call** (`PROJECT_DESIGN.md` §7.1).
- **Calibration/routing:** frontier Claude is a calibrated router (Opus self-confidence vs
  grounding corr **+0.90**; routing ≈ oracle 0.893 vs 0.894). **CAVEAT: route on a tuned
  threshold over *continuous* confidence, never the model's *binary* defer** — the binary
  decision is framing-sensitive (a "specialist available" prompt swings Opus deferral
  86%→47%). Honest downgrade: with *real* per-item specialists, confidence-routing collapses
  to "almost always call the specialist" and does not reach per-item oracle.
- **Reusable harness:** GroundBench (`docs/GROUNDBENCH_SPEC.md`, `eval/run_grounding_eval.py`)
  — GPU-free, deterministic, bootstrap CIs. Metric families: grounding (AUROC vs ceiling),
  calibration (ECE, AURC, selective-acc), **memorization-transparency** (`memo_delta =
  AUROC(matched) − AUROC(scrambled)`) — flags "looks right but is name-recall."
- **Hard interface result:** Claude reads raw ESM-2 / Nucleotide-Transformer embeddings at
  **chance (0.50)**; a trained read-out head on the *same* embedding hits 0.63–0.93.
  → **Orchestration must go through a trained head, not prompt-pasting raw latents.**

### 3. `Causal_Grounding_Eval` — **CausalAtlas** (public: `github.com/jang1563/verify-or-trust`)
The **verify-or-trust layer, fully built and measured.**

- Real perturbation data (Norman/GEARS, Replogle, Tahoe/Arc STATE); ground truth = held-out
  **real experiment** (the "cheap verifier moat"). Layer B = an LLM deciding per edge
  **TRUST vs pay λ to VERIFY**, reward = correct − λ·assays. Six arms isolate trust drivers
  (incl. `anonymized`, `baseline_swap` prestige probe).
- **The decisive findings (design constraints — see below):**
  - Orchestration fails as **allocation, not knowledge**: verify-decision discriminates
    FM-wrong edges at AUC **~0.57 (chance)**. **Capability inversion** — more capable models
    over-verify; Opus is the *worst* orchestrator at non-trivial λ.
  - The LLM follows a supplied reliability signal **94–99% but uncritically** (parrots a bad
    signal too); anonymization raises false-trust 27%→58% (trust tracks gene-name
    familiarity, not FM reliability).
  - **The missing free action:** add the cheap additive baseline → +10.7 acc for free and
    safety-aligned, but **no frontier model discovers it unaided** — engineer it.
  - **The competence signal is engineerable (the constructive result):** an
    **additive-disagreement** feature ("FM deviates from the cheap, usually-right baseline ≈
    FM is wrong") lifts FM-error prediction to **0.88 AUC** → near-oracle verification at
    ~10% budget.
  - **D3 (latest):** the FM's *own* uncertainty is NOT a strong competence signal
    (MC-dropout N/A; ensemble disagreement is mostly a magnitude proxy; STATE dispersion
    0.62–0.67 < additive-disagreement 0.88). **Deployable only where a strong, complete,
    cheap structural baseline exists** (genetic combos = additive); singles/drugs/GRN priors
    fail — documented open frontier.

### 4. `FRT_Pilot_Execution` — **Frontier Red Team** Emerging-Risks pilots
The **safety screen + responsible-disclosure posture.**

- Three pilots on refusal calibration over SFM outputs & scientific identifiers (≈17k API
  calls). Central thesis: an **invariant recognition core** behind a **movable refusal gate
  that keys on surface tokens** (names, accessions, keywords, tool-schema words) —
  *"a bouncer checking the T-shirt slogan, not the face."* One mechanism → both over-refusal
  and false-label bypass.
- Findings that constrain the screen: protein channel is a real (family) sequence
  classifier; chemistry/DNA are keyword-amplified → over-refuse benign, miss benign-labeled
  hazards. A **false benign label** suppresses refusal (a *wrong* label is worse than none).
  **P1: an LLM "safety brake" refused 100% → functionally no brake.**
- **Positive reusable primitive:** §2.1 label-integrity classifier flags a hazardous
  sequence hidden under a benign label (≥99.4% sensitivity) — a "design-vs-claimed-identity
  coherence checker." Deployment rules: parse the **content verdict, not `stop_reason`**;
  toxin-labeled record → route to **human review** ("absence of MATCH is not MATCH"). Posture
  = **triage aid → human decision, not autonomous gate.**
- **Disclosure scaffold (adopt wholesale):** Coordinated Flaw Disclosure register (flaw, not
  vuln); notify-then-publish with a courtesy window; channel routing (model-behavior →
  `usersafety@anthropic.com`, security → VDP); **public/private carve-out** keeping any
  bypass/override material vendor-only; gated publication behind a **token/infohazard audit**;
  non-negotiable guardrails (pre-registration, manipulation-budget = 0, store only aggregate +
  first-120-char excerpts).

### 5. `Safeguard/constitutional_bioguard` + `Calibrated_Permissioning_for_Biological_AI`
The **screening-gate implementation + decision-class taxonomy.**

- **bioguard is already pip-packaged** (`pyproject.toml` present; package
  `constitutional_bioguard/` with `models.py`, `taxonomy.py`, `dual_mode.py`; entry point
  `release/inference.py`) → `safety/screen.py` can `pip install -e` it **today**; no
  packaging decision needed. It also ships its own `SAFETY.md` → mirror it.
- **Calibrated permissioning:** safety = a **calibration** problem (minimize joint FPR+FNR
  across biology-specific distributions), per-case route among
  **answer / clarify / escalate / refuse / route-to-expert** — not blanket suppression.
  "No measured model occupies a low-FPR, low-FNR region."

---

## The three hard constraints the trust gate MUST obey

The expensive negatives the upstream work already paid for — bake in, don't rediscover:

1. **Don't let Claude self-allocate verification.** ~chance (0.57); capability inversion
   (stronger → over-verifies). The gate is **engineered and external**.
2. **Don't trust the SFM's own confidence** as the competence signal (CausalAtlas D3). It
   lives in **disagreement vs a cheap structural baseline (0.88 AUC).** Where no such
   baseline exists → **default to verify/abstain.**
3. **Don't paste raw SFM latents into the LLM** (GroundAtlas, chance-level). Go **through a
   trained read-out head.**

Plus from the audit: **surface raw calibrated confidence as information; reserve directive
recommendations for enforcement** (tools/MCP/post-training), and only build the loop on a
substrate where the specialist beats a cheap baseline AND emits validated calibrated confidence.

---

## Strategic frame

- **Proto / EvoDesign** (Hie lab, bioRxiv 2026.06.22.733870) is the explicit positioning
  anchor — an LLM orchestrating ~120 specialist models into multi-objective generative design
  (`π(x) ∝ p(x)·exp(−f(x)/T)`), with cost-ordered filter cascades and multi-oracle consensus.
  But Proto **trusts specialist confidence unconditionally** (no trust/verify/defer, no λ, no
  audit of the reasoning layer) and self-reports the exact gap: *"structure-prediction metrics
  are plausibility filters, not guarantees of function."* **`bio_sfm_designer` = the
  calibrated, cost-aware, audited version of a Proto-class designer.**
- **Anthropic AI-for-Science register:** measurement-first ("instrument, not a model build"),
  pilot-scale, CIs stated, anti-cheerleading. The `New_Science/discoverer` thread is a
  "skepticism charter" (*measure, don't settle*). Cognitive-bottleneck / verification-decay
  thesis (AI accelerates production not comprehension; human verification decays) motivates
  building verification **into** the DBTL loop rather than trusting the human reviewer.

---

## Vocabulary glossary

- **Trust-routing** — the per-candidate decision among `trust_sfm | verify_assay |
  default_baseline | defer`.
- **Verification price λ** — cost multiplier on assays in `net = correct − λ·assays` (swept
  0.2/0.5/0.8; primary 0.5). "Break-even λ" = when a more cautious model stops being useful.
- **Raw calibrated confidence vs reliability interface/"card"** — native confidence number
  (robust lever) vs a structured directive packet (neutral-to-harmful, model-dependent).
- **Informational vs directive** — cue helps by supplying calibrated information vs by
  recommending an action. Finding: benefit is informational.
- **Web-exposure law / tag** — a-priori, input-derived trust prior; how web-documented a
  representation→property mapping is.
- **Encoding vs verbalization gap** — present in activations vs actually said in output.
- **memo_delta** — `AUROC(matched) − AUROC(scrambled)`; memorization-transparency / name-recall flag.
- **Additive-disagreement signal** — SFM deviates from the cheap usually-right baseline ≈ SFM
  is wrong (0.88 AUC competence signal).
- **Capability inversion** — more capable models over-verify under cost (worse orchestrators at non-trivial λ).
- **Faithfulness gap** — divergence between cues a model self-reports using and cues that
  measurably shift its actions.
- **Offline (deterministic) gate** — discipline: a deterministic "verify iff calibrated-risk >
  λ" rule must beat trust-all + shuffled/inverted controls *before any LLM/API call is spent.*
- **Recognition core vs refusal gate** (FRT) — invariant content-recognition behind a movable
  surface-token-keyed refusal gate.

---

## Open frontiers / scope honesty

- The orchestrator is deployable **only where a strong cheap structural baseline exists**;
  novel/single/drug regimes have **no cheap competence signal** today (mean-dominance wall).
- The LLM is **not** a reliable autonomous safety brake (FRT P1). Screening/trust gates must
  be **external** and produce **candidates for human decision**, not autonomous verdicts.
- Single-cell is not yet a valid trust substrate; protein structure is the clean one.

---

## Provenance (workspace-relative paths)

- `LLM_SFM_interpretability/{README.md, REPORT.md}`,
  `LLM_SFM_interpretability/experiments/trust_cue_attribution/{actions.py, phase2_calibrated_gate.py,
  phase2_truth.py, BENCHMARK_CARD.md, PHASE2_PROTEIN_TRUST_DESIGN.md, PHASE2_PREREGISTRATION.md, SCHEMA.md}`
- `Bio_Grounding_Eval/{README.md, PROJECT_DESIGN.md, docs/GROUNDBENCH_SPEC.md, docs/field_message.md,
  docs/FAILURE_MODES.md, results/{SYNTHESIS.md, calibration_routing.md, decision_map_placement.md}}`
- `Causal_Grounding_Eval/{README.md, docs/CLAIMS.md, results/move1/MOVE1_SYNTHESIS.md,
  _private/CALIBRATED_ORCHESTRATION_DESIGN.md, _private/D3/RESULT_sfm_uq.md}`
- `FRT_Pilot_Execution/{README.md, OUTCOMES.md, disclosure/{Disclosure_Report.md,
  Vendor_Notification_CoverNote.md, Disclosure_Briefing.md}, docs/{LABEL_INTEGRITY_CARD.md,
  PUBLIC_RELEASE_MANIFEST.md}, shared/safety_guardrails.md}`
- `Safeguard/constitutional_bioguard/{pyproject.toml, release/inference.py, SAFETY.md,
  constitutional_bioguard/}`,
  `Calibrated_Permissioning_for_Biological_AI/{direction_plan_2026-04-28.md, HANDOFF.md}`
- `New_Science/discoverer/{INDEX.md, HANDOFF_discoverer_thread_2026_06_12.md}` (skepticism charter)
