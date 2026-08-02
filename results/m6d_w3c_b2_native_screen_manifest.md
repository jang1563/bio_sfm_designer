# M6d W3c-B2 Native-Screen Manifest

Status: `w3c_b2_native_screen_manifest_locked_no_submit`.
No submit: `True`.

Preregistered native-recoverability input and decision lock only. This manifest authorizes zero prediction, zero ProteinMPNN work, and no scientific claim.

## Frozen Scope

- targets: `8`
- predictors: `boltz2_complex`, `af2_multimer_colabfold_v1`
- native complexes per target: `1`
- maximum predictor evaluations: `16`
- L-RMSD success threshold: `<4.0 A`
- target pass: both predictors pass strict QC and threshold
- stage pass: at least `6/8` targets
- ProteinMPNN designs: `0`
- maximum H100 GPU-hours: `16.0`
- runtime reobservation complete: `False`

## Targets

| Target | Target aa | Binder aa | A3M records |
|---|---:|---:|---:|
| `1TE1_BA` | 190 | 274 | 2442 |
| `3QB4_AB` | 105 | 88 | 1909 |
| `5E5M_AB` | 115 | 112 | 96 |
| `5JSB_AB` | 151 | 116 | 287 |
| `6KBR_AC` | 223 | 55 | 7447 |
| `6KMQ_AB` | 91 | 116 | 3195 |
| `6SGE_AB` | 178 | 126 | 8845 |
| `7B5G_AB` | 132 | 123 | 7594 |

Next action: Reobserve both exact predictor runtimes without prediction, then prepare a separately guarded W3c-B2 H100 approval packet.
