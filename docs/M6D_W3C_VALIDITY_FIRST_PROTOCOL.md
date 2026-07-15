# M6d W3c validity-first failure-localization protocol

Status: `preregistered_target_discovery_only_no_submit`.

Date: 2026-07-15.

## Why W3c is needed

W3b remains terminal at `w3b_fit_rule_not_found_stop`. Its 180 matched rows, frozen constraints, and
mathematical stop are unchanged. W3c does not remove `1FSK_LJ`, retune W3b, or reinterpret its fit as a
positive result.

The terminal fit exposed a more basic experimental-design question. The representative target pool was
selected by structural contact, source diversity, and sequence diversity, but it did not prospectively
require the selected pair to be the complete biological assembly or a defensible target-binder system.
The CPU-only audit in `results/m6d_w3c_target_validity_audit.json` therefore examined all 24 representatives
using only local RCSB `TITLE`, `COMPND`, and `REMARK 350` records plus selected-chain geometry. Historical
predictor labels were not used for the semantic annotations.

| Historical branch | Targets | Complete author dimer | Strict target-binder |
|---|---:|---:|---:|
| W2b | 8 | 1 | 0 |
| W2c | 8 | 2 | 2 |
| W3b | 8 | 2 | 1 |
| **Total** | **24** | **5** | **3** |

The three strict systems are `1FFG_CD`, `1FR2_BA`, and `1F3V_BA`. They remain historical and cannot enter
W3c. The audit was performed after historical outcomes were observed, so it is a design reset for fresh
targets, not a post-hoc subgroup claim.

## Public CPU replay

`tests/fixtures/m6d_w3c_historical_structure_fixture.json` contains the RCSB source hashes, biological-
assembly metadata, molecule/chain mapping, and first-model CA coordinates needed by the audit. It contains
no generated sequences or predictor outputs. A public clone can reproduce the audit without the ignored
`hpc_outputs` tree:

```bash
PYTHONPATH=src:../bio-sfm-trust-core/src python -m \
  bio_sfm_designer.experiments.m6d_w3c_target_validity
```

The canonical fixture was generated once from the local RCSB source cache with
`--refresh-structure-fixture-from-local-sources`; that mode also verifies every source byte count and
SHA-256 before writing the audit. Routine public replay must not refresh the fixture.

## The 1FSK diagnostic

`1FSK_LJ` is an author-determined trimeric Fab-antigen assembly with protein chains `J`, `K`, and `L`.
W3b represented allergen chain `J` against antibody heavy chain `L` and omitted antibody light chain `K`.
At the same 8 A CA cutoff used by the preparation path, `J-L` has 28 contact pairs over nine allergen
interface residues, while omitted `J-K` contributes 12 contact pairs over four allergen residues. The
selected pair covers 0.818182 of the unique allergen interface residues visible across the full assembly.
This does not prove that truncation caused every failed design. It proves that W3b could not distinguish
generator failure from representation failure on this target.

## Scientific question

After restricting the benchmark to complete biological target-binder dimers, can both frozen predictors
recover the native complexes before generated designs or a trust gate are evaluated?

This orders the failure modes:

1. representation validity;
2. native predictor recoverability;
3. generator yield;
4. trust-signal calibration.

A later stage cannot be interpreted when an earlier stage fails.

## W3c-A: fresh target discovery

Select exactly eight sources outside every historical target, RCSB source, and target-sequence registry.
Selection may use only RCSB identity and local structure metadata. It may not use predictor outputs or
generated-design labels.

Each target must satisfy all of the following before selection:

- an author-determined `DIMERIC` biological unit;
- the selected chains are the complete protein assembly;
- distinct molecule entities with manual `target-binder` semantic verdict `pass`;
- at least 40 CA residues per chain;
- at least 20 CA contact pairs at 8 A;
- no unreviewed numbering gaps;
- no post-output manual exception.

W3c-A is CPU/metadata-only. It authorizes no Cayuga work.

## W3c-B1: target MSA

After a target manifest and representation lock pass exactly, a separate approval packet may authorize at
most eight target-MSA queries on A40. It authorizes no ProteinMPNN or structure-predictor work. All eight
MSAs must pass frozen-sequence, depth, hash, and no-truncation checks before W3c-B2 can be prepared.

No approval packet exists yet.

## W3c-B2: native recoverability

After a separate exact H100 approval, evaluate exactly one native target-binder sequence per target with
both frozen predictors: 16 maximum predictor evaluations and zero ProteinMPNN designs. Templates and
prediction-time network access remain off, seed is `0`, and runtime identity must be re-observed and
hash-bound.

A target passes only when both predictors produce strict-QC records, finite interface pAE, and L-RMSD below
4.0 A against the native complex. At least six of eight targets must pass. Otherwise W3c stops before
candidate generation and the representation or predictor scope must be revised.

Native outputs may determine only target recoverability. They may not tune a gate, choose generator
settings, support a binder-success claim, or transfer approval to later compute.

## Later boundary

No generator-yield, trust-gate, certification, or held-out-test protocol is currently authorized. If W3c-B2
passes, the next experiment must be separately preregistered and approved. The W3b approvals are consumed
and cannot transfer.

## Current action

Discover and lock eight fresh strict target-binder dimers. Do not prepare an MSA or H100 approval packet
until the target manifest and representation audit pass exactly.
