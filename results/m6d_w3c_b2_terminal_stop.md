# M6d W3c-B2 Terminal Partial-Result Stop

Status: `w3c_b2_terminal_partial_result_impossibility_stop`.
Audit ok: `True`.
Frozen stage pass: `False`.

Only 2/8 targets pass Boltz. Because dual-predictor target pass is conjunctive, at most 2/8 targets can pass even if every unobserved AF2 result is favorable. This is below the frozen 6/8 threshold.

- Boltz strict-QC records replayed: `8` / `8`
- Boltz native successes: `2` / `8`
- AF2 pre-inference terminal failures: `8` / `8`
- maximum possible dual-predictor passes: `2` / `8`
- frozen stage threshold: `6` / `8`
- H100 GPU-hours observed: `0.376944` / `16.0`
- additional jobs authorized: `0`

## Boltz Replay

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

## Claim Boundary

This terminal partial result proves only that the frozen W3c-B2 >=6/8 pass criterion cannot be reached: Boltz succeeds on 2/8 and each target requires both predictors. It is not a complete dual-predictor native-recoverability estimate, generator-yield evidence, trust-gate evidence, or biological binder-success evidence.

Next action: Close W3c-B2 at the validity-first stop before candidate generation. Any AF2 recovery or successor representation/predictor study must be separately preregistered, hash-bound, and explicitly approved.
