# M6d W3d Native Representation-by-Predictor Diagnostic

Status: `w3d_native_representation_predictor_protocol_locked_no_submit`.
Audit ok: `True`.
Execution ready: `False`.

## Frozen Design

| Representation | Boltz | AF2 |
|---|---:|---:|
| target MSA + binder query | 8 locked baseline | 8 prospective |
| query-only both chains | 8 prospective | 8 prospective |

- targets retained: `8` / `8`
- total factorial cells: `32`
- immutable baseline cells: `8`
- prospective cells: `24`
- currently authorized predictor evaluations: `0`
- currently authorized H100 GPU-hours: `0.0`

## Locked Baseline

| Target | interface pAE | L-RMSD (A) | Success |
|---|---:|---:|:---:|
| 1TE1_BA | 11.4271 | 30.981252 | False |
| 3QB4_AB | 18.0891 | 58.449146 | False |
| 5E5M_AB | 4.4283 | 2.426855 | True |
| 5JSB_AB | 3.2575 | 0.644485 | True |
| 6KBR_AC | 9.2236 | 17.343068 | False |
| 6KMQ_AB | 4.1455 | 7.910633 | False |
| 6SGE_AB | 11.0180 | 7.319867 | False |
| 7B5G_AB | 8.4088 | 39.582202 | False |

## Interpretation Boundary

This is a retrospective-baseline/prospective-completion diagnostic, not a fully prospective four-cell experiment. All eight baseline targets are retained, and the remaining 24 cells and decision rules are frozen before new outcomes.

A post-W3c-B2 representation-by-predictor diagnostic has been preregistered with an immutable eight-record baseline and 24 prospective cells; no new prediction has been run.

Next action: Build and validate the W3d CPU-only input producer and corrected no-prediction runtime wrappers for the 24 prospective cells, then stop before any compute approval packet.
