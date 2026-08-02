# M6d W3c validity-first failure-localization protocol

Status: `w3c_b2_prediction_packet_ready_exact_approval_required`.

Date: 2026-08-02.

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

The hash-bound approval packet passed Cayuga mirror validation and its exact approval was consumed once.
All eight target MSAs now pass completion checks. The B1 packet cannot be reused.

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

Preserve the completed hash-bound, no-submit W3c-B2 packet for exactly eight native complexes and two
frozen predictors. Do not submit predictor or ProteinMPNN work without the exact separate native-screen
approval. Packet readiness and runtime observation are not native-recoverability evidence.

## Execution update: W3c-A complete

On 2026-07-15, exactly eight fresh targets passed the frozen representation and overlap gates. The locked
IDs are `1TE1_BA`, `3QB4_AB`, `5E5M_AB`, `5JSB_AB`, `6KBR_AC`, `6KMQ_AB`, `6SGE_AB`, and `7B5G_AB`.
The completed CPU-only audit is documented in [M6D_W3C_A_TARGET_LOCK.md](M6D_W3C_A_TARGET_LOCK.md).

No target-MSA query, ProteinMPNN design, or predictor evaluation was run.

## Historical pre-execution update: W3c-B1 packet validated without submission

The separate hash-bound W3c-B1 packet was prepared and documented in
[M6D_W3C_B1_TARGET_MSA_APPROVAL.md](M6D_W3C_B1_TARGET_MSA_APPROVAL.md). It locks exactly eight one-hour
A40 target-MSA queries and zero downstream work. Local dry-run and refusal checks pass. Cayuga no-submit
mirror validation passed with exact 13-artifact hash parity, all eight target IDs, exit `0`, zero scheduler
submissions, and absent receipt/summary/preflight/A3M outputs. At that immutable snapshot, exact approval
was request-ready but not recorded and no W3c-B1 output existed. The completion update below supersedes
that operational state without rewriting the packet.

## Execution update: W3c-B1 complete

The exact B1 approval was consumed once on 2026-08-02. Jobs `3118725`-`3118732` completed 8/8 at
`1.151111` A40 GPU-hours, and all eight A3M/report pairs pass frozen-sequence, query, depth, hash,
sanitization, and no-truncation checks. Observed A3M depth ranges from 96 to 8,845 records; the full frozen
panel is retained without post-hoc filtering.

Boltz was invoked as the packet-bound MSA transport. Each A3M was recovered after downstream target-only
inference returned nonzero. No structure-prediction output was consumed, and candidate-level predictor
evaluations and ProteinMPNN designs remain zero. See
[M6D_W3C_B1_TARGET_MSA_COMPLETION.md](M6D_W3C_B1_TARGET_MSA_COMPLETION.md).

## No-submit update: W3c-B2 packet ready

The W3c-B2 manifest, dual-predictor runtime lock, producer, adjudicator, approval packet, and append-only
submission journal are implemented. The frozen scope is eight native complexes evaluated once by Boltz 2
and once by AF2-Multimer, for 16 maximum one-hour H100 jobs and zero ProteinMPNN designs. Templates,
prediction-time network access, retries, and adaptive top-up remain disabled.

Both exact runtime identities were freshly reobserved on Cayuga without prediction. Local and Cayuga dry-
runs verified the hash-bound packet, enumerated all 16 evaluations, confirmed 77/77 output paths absent,
and created zero scheduler jobs or receipts. Therefore current execution authority and scientific output
remain zero. See [M6D_W3C_B2_NATIVE_SCREEN.md](M6D_W3C_B2_NATIVE_SCREEN.md). The only phrase that can open
this packet is `approve W3c-B2 native dual-predictor screen on H100`.
