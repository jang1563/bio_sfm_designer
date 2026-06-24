# Related Work & Prior-Art Review

> Deep-research hyper-review (2026-06-23). 24 sources fetched, 114 claims extracted,
> 22 confirmed / 3 killed by 3-vote adversarial verification. This is the prior-art
> map the eventual REPORT/manuscript must engage. **Treat reading lists flagged
> "engage" as not-yet-cleared; absence of a verified claim ≠ absence of prior art.**

## Verdict

**Novel combination, not novel components.** The LLM-orchestrator-over-SFMs architecture
is established prior art (Proto, Robin, Biomni, the chemistry-agent class). The defensible
novelty of `bio_sfm_designer` is the *assembly*: external calibrated trust gate + continuous
verification price λ + deferral-to-assay + disagreement-with-cheap-baseline competence signal
+ output-level biosafety/coherence screening, applied to multi-SFM biomolecule design. No
comparator occupies that cell. The positioning claim ("calibrated version of designers that
trust specialist confidence unconditionally") is accurate.

The two over-reaching equivalences were **killed** in verification, which *preserves* narrow
novelty: cost-sensitive L2D (DeCCaF) is capacity-constrained, not λ-priced, and generic L2D is
not the exact framework — so the continuous verification **price** + deferral to a physical
**assay** (not a human) is a genuine variant.

## Landscape map

| System | Orchestrates gen+pred SFMs | Calibrated trust/abstention gate | Priced (λ) defer | Screens generated outputs |
|---|:--:|:--:|:--:|:--:|
| Proto / EvoDesign (Hie lab, bioRxiv 2026) | yes | no | no | no |
| Robin (FutureHouse, Nature 2026) | partial | uncertain (claim refuted 1-2) | no | no |
| Biomni (Stanford, 2025) | yes | no (post-hoc manual only) | no | no (emits CRISPR/cloning) |
| ChemCrow / Coscientist | yes | no (reactive cross-check) | no | partial (evadable keyword) |
| RFdiffusion→ProteinMPNN→AF2 | partial (no LLM) | no (raw pAE/pLDDT filter) | no | no |
| Self-driving labs / BO active learning | partial | no | partial (acquisition cost) | no |
| **bio_sfm_designer** | yes | yes | yes | yes |

## Top prior-art threats (ranked)

1. **Proto / EvoDesign** — same class, experimentally validated, multi-objective; abstract shows
   no calibration/defer/biosafety. **Full body not yet read + ~1 day old at review** → read it
   before any published novelty claim. https://www.biorxiv.org/content/10.64898/2026.06.22.733870v1
2. **Cost-aware L2D** — DeCCaF (arXiv:2403.06906); cost-aware clinical deferral with named
   penalties incl. a deferral cost (Sci Rep 2026, s41598-026-40637-w); conformal-calibrated
   rejector (Fang & Nalisnick, openreview SZQJ8K2DUe); Conformal Alignment (arXiv:2405.10301).
   These name "verify-or-trust under cost" — cite or risk being scooped on framing.
3. **AF2 calibration benchmarks** (below) — bound what the isotonic calibration can claim.

## Blind spots (prioritized)

1. **[RED] Cheap-baseline disagreement may not transfer to de novo design.** Validated in the
   perturbation/genetic-combo regime (CausalAtlas, additive baseline, 0.88 AUC). For de novo
   backbone/binder design there is often *no* cheap structural baseline (no homolog/template),
   and the only signal is AF2 pLDDT/pTM — the thing being distrusted. Most distinctive, least
   corroborated mechanism → make it an explicit milestone hypothesis, not a baked-in assumption.
2. **[RED] pLDDT calibration is regime-dependent; the easy regime is solved.** Olechnovič/McGuffin
   (bioRxiv 2023.12.15.571846; Bioinformatics 2024 btae491): monomer pLDDT↔lDDT r=0.97 (already
   calibrated → isotonic buys little); multimer pLDDT r=0.67, pTM r=0.70, over-prediction up to
   +0.74, pTM errors cancel in aggregate (masks overconfidence). Binder/interface design (high
   value + high dual-use risk) lives in the bad regime. Independently confirms the audit's
   monomer-0.89 / complex-0.16 gap. Implication: scope calibration claims to monomers; for
   interfaces consider ipTM/pDockQ (also unreliable) or conformal intervals; do not overclaim.

   **Resolved in M1.5 (quantified on the 80-target fixture, λ=0.5).** "Verify everything in the
   uncalibrated regime" is the *worst* deployable policy — on complexes it nets 0.500 at 1.0
   assays/target, beaten by calibrated-selective (net 0.562 at 0.48 assays). The fix is NOT
   blanket verify-all but **per-regime, calibration-validated trust**: route on the calibrated
   wrong-risk and permit `trust_sfm` only where a regime clears an offline-gate check (AUROC≥0.7
   AND calibrated-selective beats trust-all). The pLDDT-value miscalibration (Pearson 0.16) is
   about *magnitude*; the *wrong-vs-right ranking* via ipTM-blend+isotonic is AUROC 0.82 — good
   enough to route selectively. monomer is assumed-validated; complexes EARN trust via
   `TrustGate.prevalidate` (offline) or online verified data, graduating from verify-all
   (32 verify / 8 defer / 0 trust) to calibrated-selective (16 trust / 24 verify). Cold-start
   caveat: a fresh de-novo (all-complex) campaign must verify up front to bootstrap the
   per-regime calibrator, then selectivity amortizes — an explicit, measurable active-learning cost.
3. **[ORANGE] Output screening beyond the lexicon.** ChemCrow's keyword filter was bypassed via
   IUPAC name — a direct analog of label-vs-identity mismatch. Motivates the coherence check;
   warns that M0's built-in lexicon is the evadable kind. Prioritize the M2 sequence-vs-claimed-
   identity check. (ChemCrow: Nat. Mach. Intel. s42256-024-00832-8; ChemSafetyBench: 2411.16736.)
4. **[ORANGE] "Capability inversion" needs citation armor.** Triangulate the audit's
   LLM-allocates-at-chance / stronger-models-over-verify finding against the L2D-rejector-
   reliability literature; frame as a bio-specific confirmation of a known fragility.

## State of practice — output screening

Synthesis-order screening exists (SecureDNA https://securedna.org ; IBBIS Common Mechanism).
No surviving primary source establishes a deployed system screening an AI's *proposed designs*
pre-synthesis → the output-level gate targets a real, named gap. Governance to engage: GovAI
"Coding Agents Are Changing the Biosecurity Risk Landscape" (2025); JHU CHS AIxBio
(centerforhealthsecurity.org/our-work/aixbio); RAND EP71093; responsiblebiodesign.ai (2023
community commitment); Science adu8578.

## Reading list to engage before publishing (not yet cleared)

- Systems by name only (no verified per-system trust-layer claim): Coscientist, ChemCrow,
  STELLA, AlphaFold3, Boltz-1/Boltz-2, Chai-1, ESM3/ESMFold, robot scientists (Adam/Eve),
  cloud labs.
- Protein-specific BO / ML-guided directed evolution / active learning under assay budget
  (represented only by clinical/generic L2D analogs in this review).
- DBTL sources fetched but unverified here: Nat. Commun. s41467-025-55987-8; PMID 36562723;
  Royal Society Open Sci self-driving-lab review (12/7/250646); arXiv 1811.10775; CEUR Vol-2655.

## Verified primary sources

Proto: biorxiv 10.64898/2026.06.22.733870 · Robin: nature s41586-026-10652-y · Biomni:
biorxiv 2025.05.30.656746 · JACS Au survey: 10.1021/jacsau.6c00213 · RFdiffusion: nature
s41586-023-06415-8 · DeCCaF: arXiv 2403.06906 · cost-aware deferral: nature s41598-026-40637-w ·
conformal rejector: openreview SZQJ8K2DUe · AF2 calibration: biorxiv 2023.12.15.571846.
