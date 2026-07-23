# M6d W3c-A fresh target representation lock

Status: `w3c_a_fresh_target_representation_lock_complete_no_submit`.

Date: 2026-07-15.

## Result

W3c-A prospectively locked exactly eight fresh target-binder systems before any W3c predictor output.
Every selected pair passes the frozen validity gate:

- author-determined `DIMERIC` biological unit;
- exactly two protein chains in the selected assembly;
- distinct `COMPND` molecule entities;
- manual target-binder semantic verdict `pass`;
- at least 40 first-model CA residues per chain;
- at least 20 selected-pair CA contacts at 8 A;
- no observed residue-numbering gap in either selected chain;
- no exact historical target ID, RCSB source, or target-sequence SHA-256 overlap.

| Target | Interaction class | Target | Binder | CA residues | CA contacts |
|---|---|---|---|---:|---:|
| `1TE1_BA` | enzyme-inhibitor | xylanase B | XIP-I A | 190:274 | 79 |
| `3QB4_AB` | ligand-receptor | GDF5 A | BMPR1A B | 105:88 | 41 |
| `5E5M_AB` | nanobody-target | CTLA-4 A | nanobody B | 115:112 | 41 |
| `5JSB_AB` | protein-inhibitor | MCL-1 A | inhibitor B | 151:116 | 73 |
| `6KBR_AC` | protease-inhibitor | KLK4 A | SPINK2-derived inhibitor C | 223:55 | 54 |
| `6KMQ_AB` | toxin-antitoxin | HigB A | HigA B | 91:116 | 67 |
| `6SGE_AB` | nanobody-target | RhoB-GTP A | nanobody B6 B | 178:126 | 25 |
| `7B5G_AB` | nanobody-target | LexA A | NbSOS3 B | 132:123 | 50 |

The historical overlap registry combines 129 evaluated target IDs and 128 evaluated RCSB sources with the
24 W2b/W2c/W3b representative inputs. The resulting lock excludes 153 target IDs, 152 RCSB sources, and
24 exact historical target-sequence hashes. All eight selected target hashes and all eight binder hashes
are unique within W3c-A.

## Selection provenance

Candidate intake used the RCSB assembly search API with two protein entities, two protein-chain instances,
and protein-only content. Candidate titles were queried for inhibitor, toxin-antitoxin, ligand-receptor,
and nanobody complexes. Final selection used only RCSB identity, legacy PDB `TITLE`, `COMPND`, and
`REMARK 350` records, first-model CA geometry, exact overlap registries, and a manual semantic annotation.

No historical predictor outcome, generated-design label, W3c prediction, or post-output replacement was
used. The selected interaction-class mixture was frozen before W3c prediction.

## Public CPU replay

The committed fixture contains source byte counts and SHA-256 values, parsed molecule and assembly
metadata, selected-chain sequences and hashes, and first-model CA coordinates. A public clone can replay
the lock without the ignored local RCSB cache:

```bash
PYTHONPATH=src:../bio-sfm-trust-core/src python -m \
  bio_sfm_designer.experiments.m6d_w3c_fresh_target_lock \
  --out-manifest /tmp/m6d_w3c_fresh_targets.public-replay.json \
  --out-json /tmp/m6d_w3c_fresh_target_lock.public-replay.json \
  --out-md /tmp/m6d_w3c_fresh_target_lock.public-replay.md
```

Refreshing either the historical sequence registry or structure fixture is a maintainer-only operation
that requires the local historical FASTA reports or local RCSB source cache. Routine replay must not
refresh either artifact. Canonical lock outputs require `--verify-local-sources`; this prevents a public
fixture replay from overwriting the locally verified artifact hash bound into W3c-B1.

## Honest boundary

W3c-A proves representation validity under the preregistered metadata and geometry rules and exact
non-overlap under the frozen registries. Exact sequence-hash exclusion is not a sequence-family or remote-
homology guarantee. The manual semantic verdict is inspectable but is not an experimental binding assay.

This stage contains zero target-MSA queries, zero ProteinMPNN designs, zero predictor evaluations, and no
Cayuga authority. It supports no native-recoverability, generator-yield, trust-gate, or biological binder-
success claim.

## Next stage

The separate hash-bound, no-submit W3c-B1 packet is now locally prepared. It preserves all eight W3c-A
source, chain, and sequence bindings and authorizes zero ProteinMPNN and zero structure-predictor work.
Cayuga mirror dry-run validation remains the next action; exact user approval must not be requested before
that validation passes.
