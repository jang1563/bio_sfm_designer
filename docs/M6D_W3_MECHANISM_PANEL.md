# M6d W3 decisive mechanism panel

Status: `w3_mechanism_panel_preregistered_inputs_ready_runtime_blocked_no_submit`.

## Scientific question

Does the W2c divergence between pAE ranking and protocol-usable selective coverage reflect reproducible target/coverage heterogeneity, or predictor/protocol label instability of the kind exposed by the Boltz-Chai disagreement?

## What the completed W2c run actually showed

| Target | Successes | Failures | pAE AUROC | Refusal mechanism | Largest prefix at FAR <= 0.08 |
|---|---:|---:|---:|---|---:|
| 1EZV_XY | 60 | 0 | NA | `auroc_undefined_all_success` | 60 |
| 1F80_BC | 15 | 45 | 0.336 | `auroc_below_floor` | 0 |
| 1F99_BA | 14 | 46 | 0.826 | `coverage_risk_joint_constraint_failed` | 3 |
| 1FFG_CD | 39 | 21 | 0.800 | `coverage_risk_joint_constraint_failed` | 28 |
| 1FFK_HR | 0 | 60 | NA | `auroc_undefined_all_failure` | 0 |
| 1FQ9_CA | 2 | 58 | 0.966 | `coverage_risk_joint_constraint_failed` | 0 |
| 1FR2_BA | 24 | 36 | 0.925 | `coverage_risk_joint_constraint_failed` | 15 |
| 1FYR_CD | 0 | 60 | NA | `auroc_undefined_all_failure` | 0 |

W2c remains closed. These diagnostics characterize why the frozen rule refused each target; they do not retune it.

## Frozen panel

- 18 existing 3PC8 challenge cases: 12 Boltz-Chai discordances and 6 concordant-success controls.
- 40 W2c mechanism cases: ranks 1, 15, 30, 45, and 60 after deterministic within-target pAE sorting for each of 8 targets.
- Total: 58 distinct AF2-Multimer inputs. Outcome labels are not used for W2c row selection.

## Predictor protocol

- ColabFold 1.6.1 with `alphafold2_multimer_v3`, five models, one seed, 20 recycles, no relaxation.
- Existing target MSAs are hash-locked and reused. Designed binders receive single-sequence rows only.
- Templates, public MSA-server requests, and prediction-time network access are forbidden.
- Official implementation references: [ColabFold repository](https://github.com/sokrypton/ColabFold), [ColabFold 1.6.1 input parser](https://github.com/sokrypton/ColabFold/blob/v1.6.1/colabfold/input.py), and [ColabFold 1.6.1 batch CLI](https://github.com/sokrypton/ColabFold/blob/v1.6.1/colabfold/batch.py).

## Preregistered adjudication

- 3PC8 Boltz support: at least 10/12 discordant rows align with Boltz and at least 5/6 controls succeed.
- 3PC8 Chai support: at least 10/12 discordant rows align with Chai and at least 5/6 controls succeed.
- W2c Boltz support: at least 32/40 global label agreement and at least 6/8 targets with at least 4/5 agreement.
- W2c strong instability: at most 24/40 global agreement or at most 3/8 targets with at least 4/5 agreement.
- All other valid outcomes are mixed; any contract failure is blocked.

## Execution boundary

This is a no-submit packet. It records no approval and performs no API, network, GPU, or HPC action. The guarded wrapper requires a separately supplied exact approval token, a validated immutable runtime receipt, local model weights, and exact input hashes before it can invoke ColabFold.

## Claim boundary

Preregistered no-submit mechanism panel only. No AF2 prediction has run, W2c remains terminal, and no positive independent-predictor robustness claim is supported.
